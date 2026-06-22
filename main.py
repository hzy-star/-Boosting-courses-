# -*- coding: utf-8 -*-
"""
在线壹佰分 - 多账号自动刷课程序
配置见 config.ini，账号见 accounts.txt
"""

import asyncio
import configparser
import os
import sys
import traceback

from playwright.async_api import async_playwright


# ---------------------------------------------------------------------------
# 路径处理：兼容 PyInstaller 打包后的 exe
# ---------------------------------------------------------------------------
def base_dir() -> str:
    """exe / 脚本 所在目录（用于读取用户可编辑的 config.ini、accounts.txt）"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def resource_path(name: str) -> str:
    """读取随程序分发的资源（injected.js）：优先外部目录，其次打包内目录"""
    outer = os.path.join(base_dir(), name)
    if os.path.exists(outer):
        return outer
    if getattr(sys, "frozen", False):
        return os.path.join(sys._MEIPASS, name)  # type: ignore[attr-defined]
    return outer


def log(tag: str, *args):
    print(f"[{tag}]", *args, flush=True)


# ---------------------------------------------------------------------------
# ffmpeg / 视频转 Y4M（供 GUI 工具与命令行复用）
# ---------------------------------------------------------------------------
def tool_path(name: str) -> str:
    """定位 ffmpeg / ffprobe：优先程序同目录，其次打包内嵌（onefile 的 _MEIPASS），
    都找不到再依赖系统 PATH。"""
    exe = name + (".exe" if os.name == "nt" else "")
    p = resource_path(exe)
    return p if os.path.exists(p) else exe


def ffmpeg_available() -> bool:
    import subprocess

    try:
        subprocess.run(
            [tool_path("ffmpeg"), "-version"],
            capture_output=True,
            creationflags=_no_window_flag(),
        )
        return True
    except Exception:
        return False


def _no_window_flag() -> int:
    """Windows 下隐藏子进程黑窗。"""
    if os.name == "nt":
        return getattr(__import__("subprocess"), "CREATE_NO_WINDOW", 0)
    return 0


def _probe_wh(src: str):
    import subprocess

    out = subprocess.run(
        [
            tool_path("ffprobe"),
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height",
            "-of",
            "csv=p=0:s=x",
            src,
        ],
        capture_output=True,
        text=True,
        creationflags=_no_window_flag(),
    )
    txt = (out.stdout or "").strip().splitlines()
    if not txt:
        raise RuntimeError(f"无法读取视频尺寸：{src}\n{out.stderr}")
    w, h = txt[0].split("x")
    return int(w), int(h)


def convert_video_to_y4m(src: str, dst: str, on_log=log) -> None:
    """把任意视频转成假摄像头用的 Y4M：横版 640x480、整脸居中、白边补齐、15fps。

    竖屏视频按"头肩自拍"做适度裁切放大人脸；横屏则等比缩放后补边。
    """
    import subprocess

    w, h = _probe_wh(src)
    if h >= w:
        # 竖屏/方形：保留全宽，裁掉过高的上下，偏上保留额头，放大头肩
        crop_h = min(h, int(round(w * 1.5)))
        crop_y = min(int(round(h * 0.05)), max(0, h - crop_h))
        vf = (
            f"crop={w}:{crop_h}:0:{crop_y},"
            "scale=640:480:force_original_aspect_ratio=decrease,"
            "pad=640:480:-1:-1:color=white,fps=15"
        )
    else:
        vf = (
            "scale=640:480:force_original_aspect_ratio=decrease,"
            "pad=640:480:-1:-1:color=white,fps=15"
        )
    cmd = [
        tool_path("ffmpeg"),
        "-y",
        "-i",
        src,
        "-vf",
        vf,
        "-pix_fmt",
        "yuv420p",
        dst,
    ]
    on_log("转换", f"生成 Y4M：{os.path.basename(dst)}（源 {w}x{h}）")
    res = subprocess.run(
        cmd, capture_output=True, text=True, creationflags=_no_window_flag()
    )
    if res.returncode != 0 or not os.path.exists(dst):
        raise RuntimeError(f"ffmpeg 转换失败：\n{res.stderr[-800:]}")


def _probe_duration(src: str) -> float:
    import subprocess

    out = subprocess.run(
        [
            tool_path("ffprobe"),
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            src,
        ],
        capture_output=True,
        text=True,
        creationflags=_no_window_flag(),
    )
    try:
        return float((out.stdout or "").strip())
    except Exception:
        return 0.0


def convert_video_to_clips(src: str, out_dir: str, on_log=log) -> None:
    """把一段本人录像切成 front/turnA/turnB 三段（640x480 头肩取景），供画布摄像头按活体提示切换。

    录制要求（很重要）：竖屏自拍，脸居中、上半身入镜，先正脸约 3 秒，再缓慢向一侧转头，
    再向另一侧转头。脚本按时长比例切：前 5%~28% 当正脸、30%~53% 当 turnA、57%~93% 当 turnB。
    """
    import subprocess

    os.makedirs(out_dir, exist_ok=True)
    w, h = _probe_wh(src)
    dur = _probe_duration(src)
    if dur < 6:
        raise RuntimeError(f"录像太短（{dur:.1f}s），需 ≥6 秒且含正脸+左右转头")

    if h >= w:
        # 竖屏：保留全宽，取偏上的头肩区域放大（与已验证可过比对的配方一致）
        ch = min(h, int(round(w * 1.07)))
        cy = max(0, min(h - ch, int(round(h * 0.27))))
        vf = (
            f"crop={w}:{ch}:0:{cy},scale=-1:480,"
            "pad=640:480:(640-iw)/2:0:white,format=yuv420p"
        )
    else:
        vf = (
            "scale=640:480:force_original_aspect_ratio=decrease,"
            "pad=640:480:-1:-1:color=white,format=yuv420p"
        )

    segments = {
        "front": (dur * 0.05, dur * 0.28),
        "turnA": (dur * 0.30, dur * 0.53),
        "turnB": (dur * 0.57, dur * 0.93),
    }
    on_log("转换", f"切人脸片段：{os.path.basename(src)}（源 {w}x{h} {dur:.1f}s）→ {out_dir}")
    for kind, (ss, to) in segments.items():
        dst = os.path.join(out_dir, f"{kind}.mp4")
        cmd = [
            tool_path("ffmpeg"),
            "-y",
            "-loglevel",
            "error",
            "-ss",
            f"{ss:.2f}",
            "-to",
            f"{to:.2f}",
            "-i",
            src,
            "-an",
            "-vf",
            vf,
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "20",
            dst,
        ]
        res = subprocess.run(
            cmd, capture_output=True, text=True, creationflags=_no_window_flag()
        )
        if res.returncode != 0 or not os.path.exists(dst):
            raise RuntimeError(f"ffmpeg 切 {kind} 失败：\n{res.stderr[-600:]}")


# ---------------------------------------------------------------------------
# 读取配置
# ---------------------------------------------------------------------------
def load_config():
    cfg = configparser.ConfigParser()
    # 优先读 exe 同目录可编辑的 config.ini；没有就读打包内嵌的；再没有就全用默认值
    path = resource_path("config.ini")
    if os.path.exists(path):
        cfg.read(path, encoding="utf-8")
    if not cfg.has_section("settings"):
        cfg.add_section("settings")
    s = cfg["settings"]
    return {
        "login_url": s.get(
            "login_url", "https://www.zaixian100f.com/home?organization_id=496419"
        ).strip(),
        "speed": s.getfloat("speed", 16),
        "max_parallel": s.getint("max_parallel", 3),
        "headless": s.getboolean("headless", False),
        "course_name": s.get("course_name", "").strip(),
        "max_minutes": s.getint("max_minutes", 0),
        "browser_channel": s.get("browser_channel", "msedge").strip(),
        "camera_mode": s.get("camera_mode", "file").strip().lower(),
        "login_attempts": max(1, s.getint("login_attempts", 2)),
        "bypass_face": s.getboolean("bypass_face", True),
    }


def load_accounts():
    path = os.path.join(base_dir(), "accounts.txt")
    if not os.path.exists(path):
        raise FileNotFoundError(f"找不到账号文件：{path}")
    accounts = []
    with open(path, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if "----" not in line:
                log("警告", f"忽略格式不对的行（缺少 ----）：{line}")
                continue
            parts = [p.strip() for p in line.split("----")]
            idcard = parts[0]
            pwd = parts[1] if len(parts) > 1 else ""
            # 第三段：起始集（从第几集开始看），不填默认第 1 集
            start_episode = 1
            if len(parts) > 2 and parts[2]:
                try:
                    start_episode = max(1, int(parts[2]))
                except ValueError:
                    log("警告", f"起始集不是数字，按第 1 集处理：{line}")
            # 第四段：课程序号（“我的学习/课程”列表里的第几门课，按排序），不填默认第 1 门
            course_index = 1
            if len(parts) > 3 and parts[3]:
                try:
                    course_index = max(1, int(parts[3]))
                except ValueError:
                    log("警告", f"课程序号不是数字，按第 1 门处理：{line}")
            if idcard and pwd:
                accounts.append((idcard, pwd, start_episode, course_index))
    return accounts


def load_injected_body() -> str:
    with open(resource_path("injected.js"), "r", encoding="utf-8") as f:
        return f.read()


def _clip_data_url_from_path(path: str) -> str:
    """把人脸片段 mp4 读成 data URL（base64），路径不存在返回空串。"""
    import base64

    if not path or not os.path.exists(path):
        return ""
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")
    return f"data:video/mp4;base64,{b64}"


def resolve_face_clip(idcard: str, kind: str) -> str:
    """解析某账号某姿态片段的实际路径。

    优先 faces/<身份证号>/<kind>.mp4（每账号一套脸），
    找不到再回退根目录 face_<kind>.mp4（单人共用，兼容旧用法）。
    kind 取值：front / turnA / turnB
    """
    candidates = [
        os.path.join(base_dir(), "faces", idcard, f"{kind}.mp4"),
        resource_path(f"face_{kind}.mp4"),
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    return ""


def has_account_face(idcard: str) -> bool:
    """该账号是否配了专属的人脸片段（faces/<身份证号>/front.mp4）。"""
    return os.path.exists(os.path.join(base_dir(), "faces", idcard, "front.mp4"))


def resolve_face_y4m(idcard: str) -> str:
    """文件摄像头模式：解析该账号的 Y4M 路径。

    优先 faces/<身份证号>.y4m，找不到回退根目录 face.y4m。
    """
    candidates = [
        os.path.join(base_dir(), "faces", f"{idcard}.y4m"),
        os.path.join(base_dir(), "face.y4m"),
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    return ""


def build_injected(
    body: str, speed: float, start_episode: int, idcard: str, inject_faces: bool = True
) -> str:
    """为单个账号生成注入脚本：写入倍速、起始集；inject_faces 为真时再注入画布接管用的人脸片段。"""
    start_index = max(0, start_episode - 1)
    if inject_faces:
        front = _clip_data_url_from_path(resolve_face_clip(idcard, "front"))
        turn_a = _clip_data_url_from_path(resolve_face_clip(idcard, "turnA"))
        turn_b = _clip_data_url_from_path(resolve_face_clip(idcard, "turnB"))
    else:
        # 文件摄像头模式：不注入人脸，注入脚本会跳过 getUserMedia 接管，改用 Y4M 假摄像头
        front = turn_a = turn_b = ""
    head = (
        f"window.__SPEED__ = {speed};\n"
        f"window.__START_INDEX__ = {start_index};\n"
        f'window.__FACE_FRONT__ = "{front}";\n'
        f'window.__FACE_TURN_A__ = "{turn_a}";\n'
        f'window.__FACE_TURN_B__ = "{turn_b}";\n'
    )
    return head + body


# ---------------------------------------------------------------------------
# 登录 / 进入课程 / 重登检测（用 placeholder 定位，兼容首次登录和中途重登框）
# ---------------------------------------------------------------------------
async def _logged_in(page) -> bool:
    """是否已登录。

    注意：首页顶部导航即使未登录也有"我的学习"菜单，所以不能只看菜单，
    必须同时确认"页面上没有可见的登录框/登录页"，否则会把未登录首页误判为已登录。
    """
    try:
        if await on_login_page(page):
            return False
        menu = page.locator("li.el-menu-item:has-text('我的学习')")
        return await menu.count() > 0 and await menu.first.is_visible()
    except Exception:
        return False


async def on_login_page(page) -> bool:
    """当前是否在登录页 / 弹出了登录框（兼容 /home/login 跳转和中途重登框）。"""
    try:
        if "/login" in (page.url or ""):
            return True
        title = page.locator("p.loginTitle:has-text('用户登录')")
        if await title.count() > 0 and await title.first.is_visible():
            return True
        idl = page.locator("input[placeholder='请输入身份证号']")
        if await idl.count() > 0 and await idl.first.is_visible():
            return True
    except Exception:
        pass
    return False


# 兼容旧调用名
async def is_relogin(page) -> bool:
    return await on_login_page(page)


async def read_login_error(page) -> str:
    """尽力读取页面上的红色错误提示（el-message 等），读不到返回空串。"""
    for sel in (
        ".el-message__content",
        ".el-message",
        ".el-notification__content",
        "[class*='message']",
    ):
        try:
            loc = page.locator(sel)
            n = await loc.count()
            for i in range(n):
                el = loc.nth(i)
                if await el.is_visible():
                    t = (await el.inner_text()).strip()
                    if t:
                        return t
        except Exception:
            continue
    return ""


async def do_login(page, idcard, password, label):
    """在登录页/重登框里填身份证+密码并点登录。

    Element-Plus 是 Vue 受控输入，直接 fill 有时不触发 v-model，
    故先清空再逐字输入（type）确保表单真正拿到值，再点“登录”。
    """
    await page.wait_for_selector("input[placeholder='请输入身份证号']", timeout=30000)
    idl = page.locator("input[placeholder='请输入身份证号']:visible").last
    pwl = page.locator("input[placeholder='请输入密码']:visible").last
    await idl.click()
    await idl.fill("")
    await idl.type(idcard, delay=30)
    await pwl.click()
    await pwl.fill("")
    await pwl.type(password, delay=30)
    await page.wait_for_timeout(300)
    await page.locator("div.confirm_btn:has-text('登录'):visible").last.click()


async def login_until_success(page, idcard, password, label, attempts: int = 2) -> bool:
    """尝试登录，直到出现"我的学习"或用尽次数。

    注意：该站连续登录失败超过 2 次会被限制登录，所以最多只提交 attempts 次（默认 2）。
    """
    for i in range(1, attempts + 1):
        if await _logged_in(page):
            return True
        # 不在登录页也没看到菜单：可能还在跳转，等一下
        if not await on_login_page(page):
            try:
                await page.wait_for_selector(
                    "li.el-menu-item:has-text('我的学习')", timeout=8000
                )
                return True
            except Exception:
                if not await on_login_page(page):
                    await page.wait_for_timeout(1500)
                    continue
        log(label, f"尝试登录（第 {i}/{attempts} 次）…")
        try:
            await do_login(page, idcard, password, label)
        except Exception as e:
            log(label, "填写登录表单失败：", e)
        # 提交后放宽判定：出现“我的学习”或已离开登录页都算成功，最多等 ~12 秒
        ok = False
        for _ in range(12):
            await page.wait_for_timeout(1000)
            if await _logged_in(page):
                ok = True
                break
            if "/login" not in (page.url or "") and not await on_login_page(page):
                try:
                    await page.wait_for_selector(
                        "li.el-menu-item:has-text('我的学习')", timeout=6000
                    )
                except Exception:
                    pass
                ok = await _logged_in(page) or (
                    "/login" not in (page.url or "")
                    and not await on_login_page(page)
                )
                break
        if ok:
            log(label, "登录成功")
            return True
        err = await read_login_error(page)
        if err:
            log(label, f"登录提示：{err}")
        await page.wait_for_timeout(1500)
    log(label, "多次尝试仍未登录成功，请检查账号/密码是否正确")
    return False


async def goto_course(page, cfg, label, course_index=1):
    """登录后导航：我的学习 -> 课程 -> 继续学习。
    course_index：按“课程列表”里的排序选第几门课（1 = 第一门）。"""
    await page.wait_for_selector("li.el-menu-item:has-text('我的学习')", timeout=30000)
    await page.click("li.el-menu-item:has-text('我的学习')")
    await page.wait_for_timeout(1500)

    try:
        await page.click("span.right_r:has-text('课程')", timeout=10000)
    except Exception:
        log(label, "未找到“课程”标签，尝试用文本匹配…")
        await page.get_by_text("课程", exact=True).first.click()
    await page.wait_for_timeout(1500)

    clicked = False
    # 1) 优先按“课程序号”选：点列表里第 N 张课程卡片的“继续学习”
    try:
        idx = max(1, int(course_index or 1))
    except (TypeError, ValueError):
        idx = 1
    if idx >= 1:
        try:
            cards = page.locator("div.study")
            await cards.nth(idx - 1).wait_for(timeout=10000)
            await cards.nth(idx - 1).locator(
                "p.button", has_text="继续学习"
            ).first.click(timeout=10000)
            clicked = True
            log(label, f"已选择第 {idx} 门课程")
        except Exception:
            log(label, f"未找到第 {idx} 门课程，改用课程名/第一个")
    # 2) 退而按课程名选
    if not clicked and cfg["course_name"]:
        try:
            card = page.locator(
                ".study_content", has=page.get_by_text(cfg["course_name"])
            )
            await card.locator("p.button", has_text="继续学习").first.click(
                timeout=10000
            )
            clicked = True
        except Exception:
            log(label, f"未找到指定课程「{cfg['course_name']}」，改用第一个课程")
    # 3) 兜底：点第一个“继续学习”
    if not clicked:
        await page.get_by_text("继续学习", exact=False).first.click(timeout=15000)


# ---------------------------------------------------------------------------
# 启动浏览器（带内核回退）：extra_args 用于追加 --use-file-for-fake-video-capture 等
# ---------------------------------------------------------------------------
async def launch_browser(p, cfg, extra_args=None):
    extra_args = extra_args or []
    for ch in [cfg["browser_channel"], "chrome", None]:
        try:
            args = [
                "--mute-audio",
                "--start-maximized",
                "--disable-blink-features=AutomationControlled",
                "--use-fake-device-for-media-stream",  # 使用假摄像头
                "--use-fake-ui-for-media-stream",  # 自动同意权限，不弹窗
                "--no-sandbox",
                "--disable-setuid-sandbox",
            ] + list(extra_args)
            kwargs = {"headless": cfg["headless"], "args": args}
            if ch:
                kwargs["channel"] = ch
            browser = await p.chromium.launch(**kwargs)
            log("浏览器", f"已启动（channel={ch or 'chromium'}）")
            return browser
        except Exception as e:
            log("浏览器", f"channel={ch} 启动失败：{e}")
    return None


# ---------------------------------------------------------------------------
# 绕过服务器人脸比对：拦截 /api/course/faceCompare，把上传图替换成本账号注册照
# 原理：该站 faceCompare 只传一个 OSS 图片路径(filepath)，服务器据此和注册照做 1:1 比对。
#       我们被动捕获本账号注册照路径(profile 接口里的 face 字段)，并在 faceCompare 时
#       把 filepath 改成它——等于“拿注册照比对注册照”，必然通过，无需录制本人视频。
# ---------------------------------------------------------------------------
async def setup_face_bypass(page, label):
    import asyncio as _aio
    import json as _json
    import time as _time

    face_ref = {"path": None}
    _rej = {"n": 0, "t": 0.0}   # faceCompare 拒绝计数 + 上次汇总打印时刻（日志节流）

    def _extract_face(data):
        d = (data or {}).get("data")
        return d.get("face") if isinstance(d, dict) else None

    async def _grab_face(resp):
        try:
            u = resp.url or ""
            if (
                "/api/profile/detail" in u
                or "/api/user/personal/current" in u
                or "/api/profile/field" in u
            ):
                fp = _extract_face(await resp.json())
                if fp and fp != face_ref["path"]:
                    face_ref["path"] = fp
                    log(label, f"已捕获注册照片路径：{fp}")
        except Exception:
            pass

    page.on("response", lambda r: _aio.ensure_future(_grab_face(r)))

    async def _ensure_face_path():
        """没抓到注册照时，用页内 Cookie 现场拉一次 profile/detail（该站 PHPSESSID 鉴权）。"""
        if face_ref["path"]:
            return face_ref["path"]
        try:
            data = await page.evaluate(
                """async () => {
                    try {
                        const r = await fetch('/api/profile/detail', {headers:{'Accept':'application/json'}});
                        return r.ok ? await r.json() : null;
                    } catch (e) { return null; }
                }"""
            )
            fp = _extract_face(data)
            if fp:
                face_ref["path"] = fp
                log(label, f"现场获取到注册照片路径：{fp}")
        except Exception:
            pass
        return face_ref["path"]

    def _forged_ok(obj):
        return _json.dumps(
            {
                "code": 200,
                "msg": "对比成功",
                "time": str(int(_time.time())),
                "data": {
                    "course_id": obj.get("course_id"),
                    "lesson_id": obj.get("lesson_id"),
                    "order_id": obj.get("order_id"),
                    "filepath": obj.get("filepath"),
                    "state": 1,
                    "hash": {},
                },
            }
        )

    async def _route_face_compare(route):
        try:
            obj = _json.loads(route.request.post_data or "{}")
            # 直接转发“今天新抓拍”的帧给服务器：若是清晰正脸，服务器会真判通过（真实学时记录）。
            # 不再替换成注册照——注册照是旧日期文件，服务器反作弊会判“非实时抓拍”而拒绝。
            try:
                resp = await route.fetch()
                text = await resp.text()
                code = None
                try:
                    code = _json.loads(text).get("code")
                except Exception:
                    pass
                if code == 200:
                    log(label, "faceCompare：服务器比对通过（真实抓拍帧）✅")
                    _rej["n"] = 0
                    await route.fulfill(response=resp, body=text)
                    return
                # 服务器拒绝（多为抓到侧脸/模糊/被判非实时）→ 伪造成功放行。
                # 日志节流：累计计数，每 60 秒最多汇总打印一次，避免刷屏。
                _rej["n"] += 1
                now = _time.time()
                if now - _rej["t"] > 60:
                    log(
                        label,
                        f"faceCompare 已被服务器拒绝 {_rej['n']} 次（最近：{text[:40]}），均伪造放行；"
                        f"学时按观看时长记录，个别集若始终拒绝会触发自动重看",
                    )
                    _rej["t"] = now
                await route.fulfill(
                    status=200,
                    content_type="application/json; charset=utf-8",
                    body=_forged_ok(obj),
                )
            except Exception as e:
                log(label, f"faceCompare 转发失败（{e}）→ 伪造成功放行")
                await route.fulfill(
                    status=200,
                    content_type="application/json; charset=utf-8",
                    body=_forged_ok(obj),
                )
        except Exception as e:
            log(label, "faceCompare 拦截异常，按原样放行：", e)
            try:
                await route.continue_()
            except Exception:
                pass

    await page.route("**/api/course/faceCompare", _route_face_compare)
    return face_ref


# ---------------------------------------------------------------------------
# 单个账号流程
# ---------------------------------------------------------------------------
async def run_account(
    p,
    shared_browser,
    idcard,
    password,
    start_episode,
    cfg,
    injected_body,
    sem,
    stop_event=None,
    course_index=1,
):
    label = idcard[-6:] if len(idcard) >= 6 else idcard
    async with sem:
        context = None
        own_browser = None
        try:
            file_mode = cfg["camera_mode"] == "file"
            if file_mode:
                # 文件摄像头是浏览器级参数：每账号开独立浏览器，喂各自的 Y4M
                y4m = resolve_face_y4m(idcard)
                extra = []
                if y4m:
                    extra = [f"--use-file-for-fake-video-capture={y4m}"]
                    log(label, f"文件摄像头：{os.path.basename(y4m)}")
                else:
                    log(label, "警告：未找到 Y4M（faces/<身份证号>.y4m 或 face.y4m），假摄像头无画面")
                own_browser = await launch_browser(p, cfg, extra)
                if own_browser is None:
                    log(label, "浏览器启动失败，跳过该账号")
                    return
                browser = own_browser
            else:
                browser = shared_browser

            context = await browser.new_context(
                viewport={"width": 1280, "height": 800},
                permissions=["camera"],  # 自动授予摄像头权限
            )
            injected = build_injected(
                injected_body,
                cfg["speed"],
                start_episode,
                idcard,
                inject_faces=not file_mode,
            )
            await context.add_init_script(injected)
            page = await context.new_page()

            face_ref = None
            if cfg["bypass_face"]:
                face_ref = await setup_face_bypass(page, label)
                log(label, "已开启 faceCompare 拦截：优先转发真实抓拍帧让服务器真比对，被拒才伪造放行")

            if not file_mode:
                if has_account_face(idcard):
                    log(label, f"已加载该账号专属人脸（faces/{idcard}/）")
                elif os.path.exists(resource_path("face_front.mp4")):
                    log(label, "未配专属人脸，回退使用根目录 face_*.mp4")
                else:
                    log(label, "警告：未找到任何人脸片段，活体检测将无法应对")
            log(label, f"将从第 {start_episode} 集开始观看")

            log(label, "打开登录页…")
            await page.goto(
                cfg["login_url"], wait_until="domcontentloaded", timeout=60000
            )
            # 未登录会重定向到 /home/login，稍等让跳转落定
            await page.wait_for_timeout(1500)

            # ---------- 登录（带重试，兼容跳转到 /home/login） ----------
            if not await login_until_success(
                page, idcard, password, label, cfg["login_attempts"]
            ):
                log(label, "登录失败，结束该账号")
                return

            # ---------- 进入课程 ----------
            # 进课程可能因会话/跳转中途失败；失败不致命，进监控循环后会检测登录页并自动重登重进。
            try:
                await goto_course(page, cfg, label, course_index)
                log(label, "已进入课程，开始自动播放（由注入脚本接管）")
            except Exception as e:
                log(label, "首次进入课程失败，将在监控循环中自动重试：", e)

            # 绕过模式下：确保已拿到注册照路径（登录/首页通常已触发 profile 接口）
            if cfg["bypass_face"] and face_ref is not None and not face_ref["path"]:
                try:
                    data = await page.evaluate(
                        """async () => {
                            try {
                                const r = await fetch('/api/profile/detail', {headers:{'Accept':'application/json'}});
                                return r.ok ? await r.json() : null;
                            } catch (e) { return null; }
                        }"""
                    )
                    fp = ((data or {}).get("data") or {}).get("face")
                    if fp:
                        face_ref["path"] = fp
                        log(label, f"主动获取到注册照片路径：{fp}")
                except Exception:
                    pass
                if not face_ref["path"]:
                    log(label, "暂未获取到注册照路径，将等待页面接口自动捕获")

            # ---------- 监控循环：保持存活 + 自动处理重新登录 ----------
            deadline = (cfg["max_minutes"] * 60) if cfg["max_minutes"] > 0 else None
            elapsed = 0
            relogin_count = 0
            while True:
                if stop_event is not None and stop_event.is_set():
                    log(label, "收到停止指令，关闭该账号")
                    break
                if page.is_closed():
                    log(label, f"窗口已关闭，结束（累计重新登录 {relogin_count} 次）")
                    break
                if deadline is not None and elapsed >= deadline:
                    log(label, f"达到设定时长，关闭（累计重新登录 {relogin_count} 次）")
                    break

                if await on_login_page(page):
                    relogin_count += 1
                    log(
                        label,
                        f"检测到重新登录界面（第 {relogin_count} 次），自动重新登录…",
                    )
                    try:
                        if await login_until_success(
                            page, idcard, password, label, cfg["login_attempts"]
                        ):
                            await goto_course(page, cfg, label, course_index)
                            log(label, f"第 {relogin_count} 次重新登录成功，已回到课程")
                        else:
                            log(label, f"第 {relogin_count} 次重新登录未成功")
                    except Exception as e:
                        log(label, f"第 {relogin_count} 次重新登录处理失败：", e)

                # 分多次短睡，便于及时响应停止指令
                for _ in range(4):
                    if stop_event is not None and stop_event.is_set():
                        break
                    if page.is_closed():
                        break
                    await page.wait_for_timeout(2000)
                    elapsed += 2

        except Exception as e:
            log(label, "出错：", e)
            traceback.print_exc()
        finally:
            if context is not None:
                try:
                    await context.close()
                except Exception:
                    pass
            if own_browser is not None:
                try:
                    await own_browser.close()
                except Exception:
                    pass


# ---------------------------------------------------------------------------
# 核心运行入口（命令行与 GUI 工具共用）
# ---------------------------------------------------------------------------
async def run_all(accounts, cfg, injected_body=None, stop_event=None):
    """按配置运行一批账号。accounts 为 (身份证, 密码, 起始集[, 课程序号]) 列表。"""
    # 兼容老的 3 元组：补上默认课程序号 1
    accounts = [tuple(a) + (1,) if len(a) == 3 else tuple(a) for a in accounts]
    if not accounts:
        log("错误", "没有要运行的账号")
        return
    if injected_body is None:
        injected_body = load_injected_body()

    parallel = len(accounts) if cfg["max_parallel"] <= 0 else cfg["max_parallel"]
    sem = asyncio.Semaphore(parallel)

    log(
        "启动",
        f"账号数={len(accounts)}  倍速={cfg['speed']}  并行={parallel}  "
        f"显示窗口={'否' if cfg['headless'] else '是'}",
    )

    # 摄像头素材自检
    if cfg["camera_mode"] == "file":
        log("摄像头", "模式=file（Y4M 文件假摄像头，每账号独立浏览器）")
        miss = [a[0] for a in accounts if not resolve_face_y4m(a[0])]
        if miss:
            log("摄像头", f"以下账号无 Y4M（faces/<身份证号>.y4m 或 face.y4m）：{', '.join(miss)}")
    else:
        log("摄像头", "模式=inject（注入脚本+画布接管）")
        root_ok = os.path.exists(resource_path("face_front.mp4"))
        without = [a[0] for a in accounts if not has_account_face(a[0])]
        if without and not root_ok:
            log("活体", f"以下账号无专属脸且无根目录回退，活体会失败：{', '.join(without)}")

    async with async_playwright() as p:
        # inject 模式用一个共享浏览器；file 模式每账号在 run_account 里开自己的浏览器
        shared_browser = None
        if cfg["camera_mode"] != "file":
            shared_browser = await launch_browser(p, cfg)
            if shared_browser is None:
                log(
                    "错误",
                    "无法启动浏览器。请安装 Edge/Chrome，或运行 `playwright install chromium`",
                )
                return

        tasks = [
            asyncio.create_task(
                run_account(
                    p,
                    shared_browser,
                    idc,
                    pwd,
                    start_ep,
                    cfg,
                    injected_body,
                    sem,
                    stop_event,
                    course_idx,
                )
            )
            for idc, pwd, start_ep, course_idx in accounts
        ]
        await asyncio.gather(*tasks)

        if shared_browser is not None:
            try:
                await shared_browser.close()
            except Exception:
                pass

    log("完成", "全部账号任务结束")


# ---------------------------------------------------------------------------
# 命令行入口
# ---------------------------------------------------------------------------
async def main():
    cfg = load_config()
    accounts = load_accounts()
    if not accounts:
        log("错误", "accounts.txt 里没有有效账号")
        return
    await run_all(accounts, cfg)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    except Exception as e:
        log("致命错误", e)
        traceback.print_exc()
    finally:
        # 打包成 exe 双击运行时，结束后停一下，方便看日志
        if getattr(sys, "frozen", False):
            input("\n按回车键退出…")
