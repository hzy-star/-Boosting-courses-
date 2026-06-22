# -*- coding: utf-8 -*-
"""
在线壹佰分 - 刷课工具（桌面 GUI）

功能：
  - 添加多个账号（身份证号 / 密码 / 起始集），每个账号选一段本人录制的视频
  - 自动把录像切成 front/turnA/turnB 三段（faces/<身份证号>/），画布摄像头按活体提示转头
  - 按设置的并行数排队/并行打开 Edge/Chrome 自动刷课
  - 实时日志；停止 / 关闭窗口时清理浏览器
"""

import asyncio
import os
import queue
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import main as core


# ---------------------------------------------------------------------------
# 把 print 输出重定向到 GUI 日志框
# ---------------------------------------------------------------------------
class QueueWriter:
    def __init__(self, q: "queue.Queue[str]"):
        self.q = q

    def write(self, s: str):
        if s:
            self.q.put(s)

    def flush(self):
        pass


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("在线壹佰分 - 刷课工具")
        self.geometry("860x640")
        self.minsize(760, 560)

        self.accounts = []  # [{idcard, pwd, start, video, status, iid}]
        self.log_q: "queue.Queue[str]" = queue.Queue()
        self.ui_q: "queue.Queue[tuple]" = queue.Queue()  # 线程->主线程的UI更新
        self.worker = None
        self.stop_event = threading.Event()
        self.running = False

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(120, self._drain_log)

    # ---------------------- UI ----------------------
    def _build_ui(self):
        pad = {"padx": 6, "pady": 4}

        # 顶部：全局设置
        top = ttk.LabelFrame(self, text="设置")
        top.pack(fill="x", **pad)
        ttk.Label(top, text="倍速").grid(row=0, column=0, sticky="e", padx=4, pady=4)
        self.var_speed = tk.StringVar(value="2")
        ttk.Entry(top, textvariable=self.var_speed, width=6).grid(row=0, column=1, padx=4)
        ttk.Label(top, text="并行数").grid(row=0, column=2, sticky="e", padx=4)
        self.var_parallel = tk.StringVar(value="1")
        ttk.Entry(top, textvariable=self.var_parallel, width=6).grid(row=0, column=3, padx=4)
        ttk.Label(top, text="浏览器").grid(row=0, column=4, sticky="e", padx=4)
        self.var_channel = tk.StringVar(value="msedge")
        ttk.Combobox(
            top,
            textvariable=self.var_channel,
            values=["msedge", "chrome"],
            width=8,
            state="readonly",
        ).grid(row=0, column=5, padx=4)
        self.var_headless = tk.BooleanVar(value=False)
        ttk.Checkbutton(top, text="隐藏浏览器窗口", variable=self.var_headless).grid(
            row=0, column=6, padx=8
        )

        # 中部：添加账号
        form = ttk.LabelFrame(self, text="添加账号")
        form.pack(fill="x", **pad)
        ttk.Label(form, text="身份证号").grid(row=0, column=0, sticky="e", padx=4, pady=4)
        self.var_id = tk.StringVar()
        ttk.Entry(form, textvariable=self.var_id, width=22).grid(row=0, column=1, padx=4)
        ttk.Label(form, text="密码").grid(row=0, column=2, sticky="e", padx=4)
        self.var_pwd = tk.StringVar()
        ttk.Entry(form, textvariable=self.var_pwd, width=14).grid(row=0, column=3, padx=4)
        ttk.Label(form, text="起始集").grid(row=0, column=4, sticky="e", padx=4)
        self.var_start = tk.StringVar(value="1")
        ttk.Entry(form, textvariable=self.var_start, width=6).grid(row=0, column=5, padx=4)
        ttk.Label(form, text="课程序号").grid(row=0, column=6, sticky="e", padx=4)
        self.var_course = tk.StringVar(value="1")
        ttk.Entry(form, textvariable=self.var_course, width=6).grid(row=0, column=7, padx=4)

        self.var_video = tk.StringVar(value="")
        ttk.Button(form, text="选择本人录像…", command=self._pick_video).grid(
            row=1, column=1, sticky="w", padx=4, pady=4
        )
        self.lbl_video = ttk.Label(
            form, text="（竖屏自拍：先正脸约3秒→慢慢向左转头→再向右转头；已放好片段可留空）", foreground="#888"
        )
        self.lbl_video.grid(row=1, column=2, columnspan=3, sticky="w")
        ttk.Button(form, text="＋ 添加到列表", command=self._add_account).grid(
            row=1, column=5, padx=4
        )

        # 列表
        mid = ttk.LabelFrame(self, text="待运行账号")
        mid.pack(fill="both", expand=False, **pad)
        cols = ("idcard", "start", "course", "video", "status")
        self.tree = ttk.Treeview(mid, columns=cols, show="headings", height=6)
        for c, t, w in [
            ("idcard", "身份证号", 190),
            ("start", "起始集", 60),
            ("course", "课程序号", 70),
            ("video", "视频", 320),
            ("status", "状态", 110),
        ]:
            self.tree.heading(c, text=t)
            self.tree.column(c, width=w, anchor="w")
        self.tree.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(mid, orient="vertical", command=self.tree.yview)
        sb.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=sb.set)

        # 操作按钮
        btns = ttk.Frame(self)
        btns.pack(fill="x", **pad)
        ttk.Button(btns, text="删除选中", command=self._del_selected).pack(side="left")
        self.btn_start = ttk.Button(btns, text="▶ 开始刷课", command=self._start)
        self.btn_start.pack(side="right")
        self.btn_stop = ttk.Button(btns, text="■ 停止", command=self._stop, state="disabled")
        self.btn_stop.pack(side="right", padx=6)

        # 日志
        logf = ttk.LabelFrame(self, text="运行日志")
        logf.pack(fill="both", expand=True, **pad)
        self.txt = tk.Text(logf, height=12, wrap="word", state="disabled", bg="#111", fg="#ddd")
        self.txt.pack(side="left", fill="both", expand=True)
        lsb = ttk.Scrollbar(logf, orient="vertical", command=self.txt.yview)
        lsb.pack(side="right", fill="y")
        self.txt.configure(yscrollcommand=lsb.set)

    # ---------------------- 账号管理 ----------------------
    def _pick_video(self):
        path = filedialog.askopenfilename(
            title="选择本人录制的视频",
            filetypes=[
                ("视频文件", "*.mp4 *.mov *.avi *.mkv *.m4v *.webm *.3gp"),
                ("所有文件", "*.*"),
            ],
        )
        if path:
            self.var_video.set(path)
            self.lbl_video.config(text=os.path.basename(path), foreground="#222")

    def _add_account(self):
        idc = self.var_id.get().strip()
        pwd = self.var_pwd.get().strip()
        video = self.var_video.get().strip()
        try:
            start = max(1, int(self.var_start.get().strip() or "1"))
        except ValueError:
            messagebox.showwarning("提示", "起始集必须是数字")
            return
        try:
            course = max(1, int(self.var_course.get().strip() or "1"))
        except ValueError:
            messagebox.showwarning("提示", "课程序号必须是数字")
            return
        if not idc or not pwd:
            messagebox.showwarning("提示", "请填写身份证号和密码")
            return
        if video and not os.path.exists(video):
            messagebox.showwarning("提示", "选择的视频文件不存在，请重新选择或留空")
            return
        if any(a["idcard"] == idc for a in self.accounts):
            messagebox.showwarning("提示", "该身份证号已在列表中")
            return
        video_show = os.path.basename(video) if video else "（未选录像·需已放好人脸片段）"
        iid = self.tree.insert(
            "", "end", values=(idc, start, course, video_show, "待处理")
        )
        self.accounts.append(
            {"idcard": idc, "pwd": pwd, "start": start, "course": course,
             "video": video, "iid": iid}
        )
        # 清空输入
        self.var_id.set("")
        self.var_pwd.set("")
        self.var_start.set("1")
        self.var_course.set("1")
        self.var_video.set("")
        self.lbl_video.config(
            text="（竖屏自拍：先正脸约3秒→慢慢向左转头→再向右转头；已放好片段可留空）", foreground="#888"
        )

    def _del_selected(self):
        if self.running:
            return
        for iid in self.tree.selection():
            self.tree.delete(iid)
            self.accounts = [a for a in self.accounts if a["iid"] != iid]

    def _set_status(self, iid, status):
        try:
            vals = list(self.tree.item(iid, "values"))
            vals[4] = status   # 列：idcard, start, course, video, status
            self.tree.item(iid, values=vals)
        except Exception:
            pass

    # ---------------------- 运行 ----------------------
    def _start(self):
        if self.running:
            return
        if not self.accounts:
            messagebox.showinfo("提示", "请先添加至少一个账号")
            return
        need_ffmpeg = any(
            a.get("video") and not core.has_account_face(a["idcard"])
            for a in self.accounts
        )
        if need_ffmpeg and not core.ffmpeg_available():
            messagebox.showerror(
                "缺少 ffmpeg",
                "有账号选了录像需要切人脸片段，但未找到 ffmpeg。\n"
                "请把 ffmpeg.exe 和 ffprobe.exe 放到本程序同目录，或安装到系统 PATH。",
            )
            return
        try:
            speed = float(self.var_speed.get().strip() or "16")
            parallel = int(self.var_parallel.get().strip() or "1")
        except ValueError:
            messagebox.showwarning("提示", "倍速/并行数必须是数字")
            return

        self.running = True
        self.stop_event.clear()
        self.btn_start.config(state="disabled")
        self.btn_stop.config(state="normal")

        cfg = core.load_config()
        cfg.update(
            {
                "speed": speed,
                "max_parallel": parallel,
                "headless": self.var_headless.get(),
                "browser_channel": self.var_channel.get(),
                # 画布摄像头模式：能按“向左/向右转头”活体提示实时转头（file 模式静止图过不了活体）
                "camera_mode": "inject",
            }
        )
        accounts = [dict(a) for a in self.accounts]  # 拷贝快照

        self.worker = threading.Thread(
            target=self._run_worker, args=(accounts, cfg), daemon=True
        )
        self.worker.start()

    def _run_worker(self, accounts, cfg):
        old_stdout = sys.stdout
        sys.stdout = QueueWriter(self.log_q)
        try:
            faces_dir = os.path.join(core.base_dir(), "faces")
            os.makedirs(faces_dir, exist_ok=True)

            # 1) 为每个账号准备人脸片段 faces/<身份证号>/{front,turnA,turnB}.mp4（画布摄像头按活体提示切换）
            #    已放好片段的账号直接复用；选了视频的账号现切；都没有的回退共享/警告。
            ready = []
            for a in accounts:
                if self.stop_event.is_set():
                    break
                idc = a["idcard"]
                clip_dir = os.path.join(faces_dir, idc)
                if core.has_account_face(idc):
                    self.ui_q.put(("status", a["iid"], "就绪(已有人脸片段)"))
                    ready.append((idc, a["pwd"], a["start"], a.get("course", 1), a["iid"]))
                    continue
                if a.get("video"):
                    self.ui_q.put(("status", a["iid"], "切人脸片段…"))
                    try:
                        core.convert_video_to_clips(a["video"], clip_dir)
                        self.ui_q.put(("status", a["iid"], "已就绪"))
                        ready.append((idc, a["pwd"], a["start"], a.get("course", 1), a["iid"]))
                    except Exception as e:
                        core.log("切片段失败", idc, e)
                        self.ui_q.put(("status", a["iid"], "切片段失败"))
                    continue
                # 无专属片段、也没选视频：靠共享 face_*.mp4（若有），否则活体可能过不了
                self.ui_q.put(("status", a["iid"], "就绪(无专属人脸,可能过不了活体)"))
                core.log(
                    idc,
                    "警告：未配人脸片段也未选视频，活体转头可能无法通过；建议选一段本人录像",
                )
                ready.append((idc, a["pwd"], a["start"], a.get("course", 1), a["iid"]))

            if not ready or self.stop_event.is_set():
                core.log("结束", "没有可运行的账号或已停止")
                return

            # 2) 写入 accounts.txt（持久化，方便复用）
            try:
                self._write_accounts_file(ready)
            except Exception as e:
                core.log("警告", "写 accounts.txt 失败：", e)

            # 3) 运行自动化
            run_list = [(idc, pwd, st, cs) for idc, pwd, st, cs, _iid in ready]
            for _idc, _pwd, _st, _cs, iid in ready:
                self.ui_q.put(("status", iid, "运行中"))

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(
                    core.run_all(run_list, cfg, stop_event=self.stop_event)
                )
            finally:
                loop.close()

            for _idc, _pwd, _st, _cs, iid in ready:
                self.ui_q.put(("status", iid, "已结束"))
        except Exception as e:
            core.log("致命错误", e)
        finally:
            sys.stdout = old_stdout
            self.ui_q.put(("done", None, None))

    def _write_accounts_file(self, ready):
        path = os.path.join(core.base_dir(), "accounts.txt")
        lines = [
            "# 由刷课工具自动写入，格式：身份证号----密码----起始集----课程序号",
        ]
        for idc, pwd, st, cs, _iid in ready:
            lines.append(f"{idc}----{pwd}----{st}----{cs}")
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")

    def _on_worker_done(self):
        self.running = False
        self.btn_start.config(state="normal")
        self.btn_stop.config(state="disabled")

    def _stop(self):
        if not self.running:
            return
        self.stop_event.set()
        core_log = "[停止] 正在停止并关闭浏览器…\n"
        self.log_q.put(core_log)
        self.btn_stop.config(state="disabled")

    # ---------------------- 日志刷新 ----------------------
    def _drain_log(self):
        # 日志
        try:
            while True:
                s = self.log_q.get_nowait()
                self.txt.config(state="normal")
                self.txt.insert("end", s)
                self.txt.see("end")
                self.txt.config(state="disabled")
        except queue.Empty:
            pass
        # UI 更新（状态 / 结束）
        try:
            while True:
                kind, iid, val = self.ui_q.get_nowait()
                if kind == "status":
                    self._set_status(iid, val)
                elif kind == "done":
                    self._on_worker_done()
        except queue.Empty:
            pass
        self.after(120, self._drain_log)

    def _on_close(self):
        if self.running:
            if not messagebox.askokcancel("退出", "正在运行，退出将停止刷课并关闭浏览器，确定？"):
                return
            self.stop_event.set()
            # 给后台一点时间优雅关闭
            self.after(1500, self.destroy)
            return
        self.destroy()


if __name__ == "__main__":
    App().mainloop()
