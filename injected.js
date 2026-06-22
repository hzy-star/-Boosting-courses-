// 在线壹佰分 自动刷课注入脚本（最终加强版）
(function () {
    'use strict';

    if (window.__ZX_INJECTED__) return;
    window.__ZX_INJECTED__ = true;

    var SPEED = window.__SPEED__ || 1;
    var startIndex = (typeof window.__START_INDEX__ === 'number') ? window.__START_INDEX__ : 0;
    if (startIndex < 0) startIndex = 0;

    var currentIndex = startIndex;
    // 点“下一集”后会刷新页面让新一集画面显示，刷新会重跑本脚本，
    // 所以把当前集数存到 sessionStorage，刷新后恢复，避免跳回起始集。
    try {
        var __savedIdx = parseInt(sessionStorage.getItem('__ZX_IDX__'));
        if (!isNaN(__savedIdx) && __savedIdx >= 0) currentIndex = __savedIdx;
    } catch (e) {}
    function saveIndex() {
        try { sessionStorage.setItem('__ZX_IDX__', String(currentIndex)); } catch (e) {}
    }
    var noVideoTicks = 0;
    var advancing = false;
    // 当前这集“进入时刻”：进入播放页/点章节/点下一集时都会刷新。
    // 初始化为页面加载时刻，避免进场就被残留的“结束弹窗”误判为已结束。
    var episodeEnterTime = Date.now();
    // 本会话内是否真正观察到“当前这集”播放到了结尾，只有 true 才允许跳下一集。
    var watchedToEnd = false;
    // 本会话内是否观察到“当前这集”停在靠前位置（确认是从头往后播，而非载入即在结尾）。
    var sawEarlyPosition = false;
    // 当前这集已强制拉回开头重播的次数（防止站点反复把进度跳到末尾时死循环）。
    var replaysThisEpisode = 0;
    // 上一次跳集时刻，用于每次跳集的独立冷却。
    var lastAdvanceTime = 0;
    // 上一次点击“重播”的时刻，避免在弹窗上疯狂连点重播。
    var lastReplayTime = 0;

    function log() {
        try { console.log.apply(console, ['[刷课]'].concat([].slice.call(arguments))); } catch (e) {}
    }

    log('注入成功，倍速=' + SPEED + '，起始集=第' + (startIndex + 1) + '集');

    // =========================================================
    // 摄像头接管：用画布当摄像头，按活体提示切换“正脸/左转/右转”
    // 三段人脸视频由 main.py 以 data URL 注入（__FACE_FRONT__/A/B）
    // =========================================================
    var setFacePose = null;  // 供活体循环调用：'front' | 'A' | 'B'
    (function setupFakeCamera() {
        var FRONT = window.__FACE_FRONT__ || '';
        var TURN_A = window.__FACE_TURN_A__ || '';
        var TURN_B = window.__FACE_TURN_B__ || '';
        if (!FRONT) {
            log('未注入人脸片段，摄像头沿用浏览器默认假画面');
            return;
        }
        var md = navigator.mediaDevices;
        if (!md || !md.getUserMedia) {
            log('该环境无 getUserMedia，无法接管摄像头');
            return;
        }

        var videos = {};
        function makeVideo(src) {
            var v = document.createElement('video');
            v.src = src;
            v.muted = true;
            v.loop = true;
            v.autoplay = true;
            v.setAttribute('playsinline', '');
            v.setAttribute('muted', '');
            // 标记为“假摄像头”视频，避免被 getVideo() 当成课程视频
            v.setAttribute('data-fakecam', '1');
            v.style.cssText = 'position:fixed;left:-9999px;top:0;width:2px;height:2px;opacity:0;';
            (document.body || document.documentElement).appendChild(v);
            v.play().catch(function () {});
            return v;
        }
        function ensureVideos() {
            if (!videos.front && (document.body || document.documentElement)) {
                videos.front = makeVideo(FRONT);
                videos.A = TURN_A ? makeVideo(TURN_A) : videos.front;
                videos.B = TURN_B ? makeVideo(TURN_B) : videos.front;
            }
        }

        var pose = 'front';
        setFacePose = function (p) { pose = p; };

        var canvas = document.createElement('canvas');
        // 与人脸片段同尺寸（头肩取景 480x720），整帧绘制；draw() 会按实际视频尺寸再校正
        canvas.width = 480;
        canvas.height = 720;
        var ctx = canvas.getContext('2d');

        function currentVideo() {
            if (pose === 'A') return videos.A;
            if (pose === 'B') return videos.B;
            return videos.front;
        }
        var _lastVT = -1;       // 上一帧隐藏视频的 currentTime，用于检测“画面僵住”
        var _stallCnt = 0;
        function draw() {
            ensureVideos();
            var v = currentVideo();
            if (v && v.readyState >= 2 && v.videoWidth) {
                if (v.paused) v.play().catch(function () {});
                // 防“画面僵在同一帧”：隐藏视频被浏览器节流/暂停时只重新 play()，
                // 不再强行 seek（seek 会取到模糊的过渡帧，被判“图片质量不达标”）。
                if (v.currentTime === _lastVT) {
                    if (++_stallCnt >= 8) { _stallCnt = 0; try { v.play().catch(function () {}); } catch (e) {} }
                } else {
                    _stallCnt = 0;
                    _lastVT = v.currentTime;
                }
                if (canvas.width !== v.videoWidth || canvas.height !== v.videoHeight) {
                    canvas.width = v.videoWidth;
                    canvas.height = v.videoHeight;
                }
                try {
                    // 只做极轻微亚像素位移(<1px)：让每帧字节不同、规避“重复抓拍”判定，
                    // 又几乎不损画质（不做亮度滤镜，避免被判“图片质量不达标”）。
                    var dx = (Math.random() - 0.5) * 0.9;
                    var dy = (Math.random() - 0.5) * 0.9;
                    ctx.drawImage(v, dx, dy, canvas.width, canvas.height);
                } catch (e) {}
            }
            // 视频未就绪时不清屏：保留上一帧，避免黑帧被采样成“未检测到人脸”
        }
        // 用 setInterval 而非 rAF，避免窗口失焦时绘制被节流导致画面僵在黑帧
        setInterval(draw, 33);   // ~30fps
        draw();

        var fakeStream = null;
        function getFakeStream() {
            if (!fakeStream) fakeStream = canvas.captureStream(25);
            return fakeStream;
        }

        var origGUM = md.getUserMedia.bind(md);
        md.getUserMedia = function (constraints) {
            if (constraints && constraints.video) {
                try {
                    ensureVideos();
                    log('已用画布接管摄像头（getUserMedia）');
                    return Promise.resolve(getFakeStream());
                } catch (e) {
                    return origGUM(constraints);
                }
            }
            return origGUM(constraints);
        };
        // 兼容老接口
        try {
            navigator.getUserMedia = function (c, ok, err) {
                md.getUserMedia(c).then(ok).catch(err);
            };
        } catch (e) {}

        log('摄像头接管已就绪（按活体提示切换姿态）');
    })();

    // 活体检测应对：只读“当前可见的提示框”短文本来判断，避免误读页面残留文字
    var dirForRight = 'A';   // “向右转头”用哪段片段
    var dirForLeft = 'B';
    var lastInstr = '';
    var lastInstrTime = 0;
    var lastFlipTime = 0;

    // 扫描所有可见的短提示，按优先级判断当前指令：右转 > 左转 > 通用(正脸)
    function detectInstr() {
        var nodes = document.querySelectorAll('div,span,p,b,strong,h1,h2,h3');
        var hasRight = false, hasLeft = false, hasOther = false;
        for (var i = 0; i < nodes.length; i++) {
            var el = nodes[i];
            var t = (el.textContent || '').trim();
            if (!t || t.length > 24) continue;
            if (typeof isVisible === 'function' && !isVisible(el)) continue;
            if (t.indexOf('向右转头') >= 0) hasRight = true;
            else if (t.indexOf('向左转头') >= 0) hasLeft = true;
            else if (t.indexOf('端正') >= 0 || t.indexOf('面向镜头') >= 0 || t.indexOf('正对') >= 0 ||
                     t.indexOf('眨眼') >= 0 || t.indexOf('张嘴') >= 0 ||
                     t.indexOf('未检测到人脸') >= 0 || t.indexOf('活体检测') >= 0) hasOther = true;
        }
        if (hasRight) return 'right';
        if (hasLeft) return 'left';
        if (hasOther) return 'front';
        return null;
    }

    function livenessTick() {
        if (typeof setFacePose !== 'function') return;
        var instr = detectInstr();

        if (!instr) {
            // 没有活体提示：保持正脸待命
            if (lastInstr) { lastInstr = ''; setFacePose('front'); }
            return;
        }
        if (instr !== lastInstr) {
            lastInstr = instr;
            lastInstrTime = Date.now();
            log('活体提示[' + instr + ']');
        }
        // 同一转头指令卡超过 5 秒 → 翻转左右映射（自适应镜像方向）
        if ((instr === 'right' || instr === 'left') &&
            Date.now() - lastInstrTime > 5000 && Date.now() - lastFlipTime > 5000) {
            var t = dirForRight; dirForRight = dirForLeft; dirForLeft = t;
            lastFlipTime = Date.now();
            lastInstrTime = Date.now();
            log('活体方向卡住，已翻转左右映射');
        }
        if (instr === 'right') setFacePose(dirForRight);
        else if (instr === 'left') setFacePose(dirForLeft);
        else setFacePose('front');
    }
    setInterval(livenessTick, 600);

    // 防切后台
    try {
        Object.defineProperty(document, 'hidden', { get: () => false });
        Object.defineProperty(document, 'visibilityState', { get: () => 'visible' });
    } catch (e) {}

    ['visibilitychange', 'blur'].forEach(evt => {
        document.addEventListener(evt, e => e.stopImmediatePropagation(), true);
    });

    // =========================================================
    // 后台学时校验：用 /api/course/lessonTree 的 study_state 判断每集是否“后台已记录”
    //   study_state===1 → 已记录（可跳过）；其它(0) → 未记录（需要观看）
    //   该接口靠 Cookie 鉴权，无需 token，可直接在页面内 fetch。
    // =========================================================
    // 实时从当前 URL（search + hash）读参数：本站是 SPA，注入脚本在首页就执行了，
    // 那时还没有 courseId/order_id，必须每次实时读，不能在启动时取一次。
    function qparam(name) {
        try {
            var v = new URLSearchParams(location.search).get(name);
            if (v) return v;
            var h = location.hash || '';
            var qi = h.indexOf('?');
            if (qi >= 0) { v = new URLSearchParams(h.slice(qi + 1)).get(name); if (v) return v; }
        } catch (e) {}
        return '';
    }
    var g_lessons = null;      // [{id, study_state, title}]，按集顺序（第1集在前）
    var g_fetching = false;
    var g_courseId = '';       // 从网站自身请求里兜底捕获的 course_id / order_id
    var g_orderId = '';
    function getCourseId() { return qparam('courseId') || qparam('course_id') || g_courseId; }
    function getOrderId() { return qparam('order_id') || g_orderId; }

    function parseTree(j) {
        var d = (j && j.data) || {};
        var arr = [];
        function push(it) {
            if (it && it.id != null)
                arr.push({ id: String(it.id), study_state: Number(it.study_state) || 0, title: it.title || '' });
        }
        // 兼容两种结构：chapter 里可能嵌套小节，un_chapter 为扁平列表
        (d.chapter || []).forEach(function (c) {
            if (c && (c.lesson || c.children)) (c.lesson || c.children).forEach(push);
            else push(c);
        });
        (d.un_chapter || []).forEach(push);
        return arr;
    }
    function fetchTree() {
        var cid = getCourseId(), oid = getOrderId();
        if (g_fetching || !cid || !oid) return;
        g_fetching = true;
        fetch('/api/course/lessonTree?course_id=' + cid + '&order_id=' + oid,
            { credentials: 'include', headers: { 'accept': 'application/json, text/plain, */*', 'cache-control': 'no-cache' } })
            .then(function (r) { return r.json(); })
            .then(function (j) { var a = parseTree(j); if (a && a.length) g_lessons = a; })
            .catch(function () {})
            .then(function () { g_fetching = false; });
    }

    // 拦截网站自己发的 lessonTree（fetch / XHR），直接拿到每集 study_state，
    // 不依赖我们能否拼出参数，最稳。同时顺手捕获 course_id / order_id。
    (function hookNet() {
        function ingest(url, text) {
            url = String(url || '');
            if (url.indexOf('/api/course/lessonTree') < 0) return;
            try {
                var m = url.match(/course_id=(\d+)/); if (m) g_courseId = m[1];
                var n = url.match(/order_id=(\d+)/); if (n) g_orderId = n[1];
                var a = parseTree(JSON.parse(text));
                if (a && a.length) g_lessons = a;
            } catch (e) {}
        }
        try {
            var of = window.fetch;
            if (of) {
                window.fetch = function () {
                    var url = (arguments[0] && arguments[0].url) || arguments[0] || '';
                    return of.apply(this, arguments).then(function (resp) {
                        try {
                            if (String(url).indexOf('/api/course/lessonTree') >= 0)
                                resp.clone().text().then(function (t) { ingest(url, t); }).catch(function () {});
                        } catch (e) {}
                        return resp;
                    });
                };
            }
        } catch (e) {}
        try {
            var oOpen = XMLHttpRequest.prototype.open;
            var oSend = XMLHttpRequest.prototype.send;
            XMLHttpRequest.prototype.open = function (m, u) { this.__zxUrl = u; return oOpen.apply(this, arguments); };
            XMLHttpRequest.prototype.send = function () {
                var xhr = this;
                if (xhr.__zxUrl && String(xhr.__zxUrl).indexOf('/api/course/lessonTree') >= 0) {
                    xhr.addEventListener('load', function () { try { ingest(xhr.__zxUrl, xhr.responseText); } catch (e) {} });
                }
                return oSend.apply(this, arguments);
            };
        } catch (e) {}
    })();
    function getSkipped() {
        try { return JSON.parse(sessionStorage.getItem('__ZX_SKIP__') || '[]'); } catch (e) { return []; }
    }
    function addSkipped(id) {
        var s = getSkipped();
        if (s.indexOf(String(id)) < 0) { s.push(String(id)); try { sessionStorage.setItem('__ZX_SKIP__', JSON.stringify(s)); } catch (e) {} }
    }
    // “本次运行已看过一遍”的集合：看到结尾即记入，之后不再回头重看（不重播）。
    function getWatched() {
        try { return JSON.parse(sessionStorage.getItem('__ZX_WATCHED__') || '[]'); } catch (e) { return []; }
    }
    function addWatched(id) {
        var s = getWatched();
        if (s.indexOf(String(id)) < 0) { s.push(String(id)); try { sessionStorage.setItem('__ZX_WATCHED__', JSON.stringify(s)); } catch (e) {} }
    }
    function isDone(it) { return it && Number(it.study_state) === 1; }
    // 从 from 下标起（含）找第一集“后台未记录、未放弃、且本次还没看过”的下标；没有则 -1
    function firstUndone(from) {
        if (!g_lessons) return -1;
        var skip = getSkipped(), watched = getWatched();
        for (var i = Math.max(0, from); i < g_lessons.length; i++) {
            var id = g_lessons[i].id;
            if (!isDone(g_lessons[i]) && skip.indexOf(id) < 0 && watched.indexOf(id) < 0) return i;
        }
        return -1;
    }
    // 当前是否有“活体检测/人脸提示”弹窗（此时网站会暂停视频，我们不应抢着 play）
    function livenessActive() {
        try { return detectInstr() !== null; } catch (e) { return false; }
    }
    function idxOfId(id) {
        if (!g_lessons) return -1;
        for (var i = 0; i < g_lessons.length; i++) if (g_lessons[i].id === String(id)) return i;
        return -1;
    }
    function gotoLessonId(id) {
        try {
            var u = new URL(location.href);
            u.searchParams.set('lessonId', String(id));
            location.href = u.toString();   // 改变 query 会触发整页导航，脚本随之重新注入
        } catch (e) { location.reload(); }
    }

    function getVideo() {
        var v = document.querySelector('video.vjs-tech');
        if (v) return v;
        // 跳过假摄像头的隐藏 video，只返回真正的课程播放器
        var all = document.querySelectorAll('video');
        for (var i = 0; i < all.length; i++) {
            if (!all[i].hasAttribute('data-fakecam')) return all[i];
        }
        return null;
    }

    function chapters() {
        return document.querySelectorAll('.chapter_2');
    }

    function clickChapter(i) {
        const list = chapters();
        if (i >= 0 && i < list.length) {
            const el = list[i];
            const target = el.querySelector('.chapter_j span') || el.querySelector('.chapter_j') || el;
            log('点击第 ' + (i + 1) + ' 集：' + (target.innerText || '').slice(0, 40));
            target.click();
            episodeEnterTime = Date.now();
            watchedToEnd = false;
            sawEarlyPosition = false;
            replaysThisEpisode = 0;
            return true;
        }
        return false;
    }

    function isVisible(el) {
        if (!el) return false;
        const rect = el.getBoundingClientRect();
        if (rect.width <= 0 || rect.height <= 0) return false;
        const st = window.getComputedStyle(el);
        return st.display !== 'none' && st.visibility !== 'hidden' && parseFloat(st.opacity || 1) > 0.1;
    }

    function getEndNextButton() {
        const mask = document.querySelector('.mask_content');
        if (!mask || !isVisible(mask)) return null;
        const txt = (mask.innerText || '').trim();
        if (!txt.includes('播放结束') && !txt.includes('下一集')) return null;

        const btns = mask.querySelectorAll('button');
        for (let b of btns) {
            const t = (b.innerText || '').trim();
            if ((b.classList.contains('next') || t === '确定' || t.includes('下一集')) && isVisible(b)) {
                return b;
            }
        }
        return null;
    }

    // 找“播放结束”弹窗里的“重播 / 重新观看”按钮（用于强制从头重看这一集）。
    function getReplayButton() {
        const mask = document.querySelector('.mask_content');
        if (!mask || !isVisible(mask)) return null;
        const txt = (mask.innerText || '').trim();
        if (!txt.includes('播放结束') && !txt.includes('下一集') && !txt.includes('重播') && !txt.includes('重新观看')) return null;

        const btns = mask.querySelectorAll('button');
        for (let b of btns) {
            const t = (b.innerText || '').trim();
            // 排除“下一集/确定”那个按钮，只认重播类
            if (b.classList.contains('next') || t === '确定' || t.includes('下一集')) continue;
            if ((b.classList.contains('replay') || t.includes('重播') || t.includes('重新观看') || t.includes('再看') || t.includes('再次')) && isVisible(b)) {
                return b;
            }
        }
        return null;
    }

    // ===== 控制器状态 =====
    var startedFromZero = false;  // 本集是否已做过“一次性从头校正”
    var lastNavAt = 0;            // 上次 URL 跳集时刻，防抖
    var finished = false;         // 是否已全部完成
    var livenessSince = 0;        // 中途活体检测连续进行的起始时刻（用于超时兜底）

    function controllerTick() {
        if (finished) return;

        // 1) 还没拿到课程树：取一次，等它就绪即可（很快）。若在课程列表页则点进起始集。
        if (!g_lessons) {
            fetchTree();
            if (!getVideo() && chapters().length > 0) {
                noVideoTicks++;
                if (noVideoTicks >= 4 && clickChapter(currentIndex)) noVideoTicks = 0;
            }
            return;
        }

        // 2) 计算应看的目标集：从起始集起，第一集“后台未记录且未放弃”的。
        var targetIdx = firstUndone(startIndex);
        if (targetIdx < 0) {
            finished = true;
            log('🎉 从第 ' + (startIndex + 1) + ' 集起，后台已全部记录完成，无需再刷。');
            return;
        }
        var targetId = g_lessons[targetIdx].id;
        var curId = qparam('lessonId');

        // 3) 当前不在目标集 → 定位过去（自动跳过后台已记录的集）。
        //    · 课程列表页(无 lessonId、有章节列表)：点击对应章节进入播放页（改 URL 在列表页无效）。
        //    · 播放页(已有 lessonId)：直接改 URL 的 lessonId 跳集。
        if (curId !== targetId) {
            if (Date.now() - lastNavAt > 6000) {
                lastNavAt = Date.now();
                startedFromZero = false; livenessSince = 0;
                log('定位到第 ' + (targetIdx + 1) + ' 集：' + g_lessons[targetIdx].title);
                if (!curId && chapters().length > targetIdx) {
                    clickChapter(targetIdx);     // 列表页：点章节进入
                } else {
                    gotoLessonId(targetId);      // 播放页：URL 跳集
                }
            }
            return;
        }

        // 4) 已在目标集：取播放器。被“播放结束”弹窗挡住时点“确定/下一集”推进（不重播）。
        var video = getVideo();
        if (!video || video.readyState < 2 || !video.duration || video.duration < 5) {
            var nb0 = getEndNextButton();
            if (nb0 && Date.now() - lastNavAt > 6000) {
                lastNavAt = Date.now();
                addWatched(targetId);
                log('第 ' + (targetIdx + 1) + ' 集结束弹窗 → 进入下一集');
                var nA = firstUndone(targetIdx + 1);
                startedFromZero = false;
                if (nA < 0) { finished = true; return; }
                gotoLessonId(g_lessons[nA].id);
            }
            return;
        }
        video.muted = true;
        if (video.playbackRate !== SPEED) video.playbackRate = SPEED;

        // 防进度跳跃（绑定一次）
        if (!video.__protected) {
            video.__protected = true;
            var lastTime = 0;
            video.addEventListener('timeupdate', function () {
                var now = video.currentTime;
                if (now > lastTime + 15 && lastTime > 5) video.currentTime = lastTime;
                lastTime = now;
            });
        }

        var nearEnd = video.ended || video.currentTime >= video.duration - 2;

        // 5) “载入即在结尾”的脏进度：仅当几乎到末尾(≤末尾15秒)时从头校正一次（只一次，不是重播），
        //    保证这集真的从头看过；正常中途位置则不动、接着往下播。
        if (!startedFromZero) {
            startedFromZero = true;
            if (video.currentTime >= video.duration - 15) {
                try { video.currentTime = 0; } catch (e) {}
                log('第 ' + (targetIdx + 1) + ' 集载入即在结尾(脏进度)，从头看一次：' + g_lessons[targetIdx].title);
            } else {
                log('开始观看第 ' + (targetIdx + 1) + ' 集：' + g_lessons[targetIdx].title);
            }
            video.play().catch(function () {});
            return;
        }

        // 6) 中途活体检测进行中：不抢播放，交给活体循环摆正姿态、网站自己暂停/继续，
        //    检测过了网站会自动接着播。超过 2 分钟仍没过则不卡死，跳到下一集。
        if (livenessActive()) {
            if (!livenessSince) livenessSince = Date.now();
            if (Date.now() - livenessSince > 120000) {
                livenessSince = 0; addWatched(targetId);
                log('第 ' + (targetIdx + 1) + ' 集中途检测超过2分钟未通过 → 跳过，进入下一集');
                var nB = firstUndone(targetIdx + 1);
                startedFromZero = false;
                if (nB < 0) { finished = true; return; }
                gotoLessonId(g_lessons[nB].id);
            }
            return;
        }
        livenessSince = 0;

        // 7) 没到结尾：保持播放（仅在非检测原因暂停时补一脚）。
        if (!nearEnd) {
            if (video.paused && !video.ended) video.play().catch(function () {});
            return;
        }

        // 8) 到结尾 → 不重播、不卡校验，标记看过并进入下一集。
        addWatched(targetId);
        log('第 ' + (targetIdx + 1) + ' 集已播放到结尾 → 进入下一集');
        var nxt = firstUndone(targetIdx + 1);
        startedFromZero = false;
        if (nxt < 0) { finished = true; log('🎉 起始集之后未记录的集已全部看过一遍。'); return; }
        gotoLessonId(g_lessons[nxt].id);
    }

    setInterval(controllerTick, 1500);
})();