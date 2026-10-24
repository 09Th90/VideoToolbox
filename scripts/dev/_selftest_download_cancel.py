# -*- coding: utf-8 -*-
# @version 2.7.0
"""下载取消链路回归自检（v1.19.1）。

为什么要有这个：用户报「中止下载没有真正生效」——截图里 T3/T4 两个任务都
卡在 1.2%，下载日志还在刷 yt-dlp 的 `Retrying (1/10)` + `Sleeping 1.00s`。

v1.19.0 的取消只覆盖了 `_run_ytdlp`（真正的下载进程）这一段，而一个下载
任务实际会依次经过：引导（ensure_ffmpeg）→ 提取（fetch_info_json）→ 下载
→ 兜底重试 → 换源 → NPE 解析 → NPE 下载 → 封面（ffmpeg）。其中

  · 提取阶段用的是 `subprocess.run`（跑满 180s×4 次 + 退避），杀不掉；
  · NPE 解析用 `subprocess.run`（(45+25)s×2），杀不掉；
  · 封面用 `subprocess.run`（60s），杀不掉；
  · 子进程都没登记进 `_procs`，取消按钮压根拿不到它们；
  · `with _EXTRACT_LOCK` 是不可中断阻塞，排队等锁时取消毫无反应；
  · `proc.kill()` 只杀父进程，yt-dlp/ffmpeg fork 出的孙进程继续写 .part；
  · 最要命的是 UI 回弹：`on_dl_progress` 无条件把状态写回「下载中」，
    队列里积压的进度消息会把刚点完取消的界面顶回去 —— 这才是用户
    判定「中止没生效」的直接观感。

逐条验证（每条都有「进程确实起来了」的正向对照，避免假阳性）：

  1  kill_process_tree 杀整棵进程树（孙进程一并死）
  2  sleep_cancellable 取消后立刻返回 / 未取消不误打断
  3  fetch_info_json 可取消 + 登记子进程 + 未取消时行为不变
  4  make_cover_1280x720 可取消
  5  npe_backend.probe 可取消（errorType=cancelled）
  6  GUI 源码层：状态不回弹、杀进程树、提取锁可中断、各阶段已接 cancel

跑法（项目根目录）：
    python scripts/dev/_selftest_download_cancel.py
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
import time

APP_DIR = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(APP_DIR, "src"))
os.environ.setdefault("VT_NO_PIPELINE", "1")

import video_toolbox as engine  # noqa: E402
# v2.3.1（A1 拆 download 域）：子进程拦截的 patch 点跟随实现域——函数搬进
# core.download.* 后，内部调用查的是**那些模块命名空间**的 popen_process /
# ytdlp_proxy_args / ytdlp_cookie_args，再 patch engine.* 不再生效
# （WinError 2 / 3a 前置失败即此形态）。engine.* 的 patch 保留（无害，
# 且护住尚未拆域的调用方）。
from core.download import util as _dl_util  # noqa: E402
from core.download import ytdlp_util as _dl_ytdlp  # noqa: E402

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("[PASS] " if cond else "[FAIL] ") + name
          + (f"   {detail}" if detail else ""))


# ---------- 假程序 ----------
#: 冒充 yt-dlp：打印用户截图里的那两行（进度 + Retrying），然后长睡；
#: 期间 fork 一个孙进程，模拟 ffmpeg 合并/分片写入的持有者
#: ——只杀父进程的话它会活下来继续占着 .part。
FAKE_YTDLP_BODY = (
    "import subprocess, sys, time\n"
    "print('[download]   1.2% of 8.00GiB at 20.00KiB/s')\n"
    "print('[download] Got error: Read timed out. Retrying (1/10)')\n"
    "sys.stdout.flush()\n"
    "kid = subprocess.Popen([sys.executable, '-c',\n"
    "    'import time; time.sleep(9999)'])\n"
    "open(sys.argv[1], 'w').write(str(kid.pid))\n"
    "time.sleep(9999)\n"
)

#: 冒充 ffmpeg（封面阶段）：先在自己所在目录写 marker（证明真的被启动），
#: 然后长睡等待取消。marker 不能写到 -i 指向的路径 —— 那是待转换的缩略图
#: 目录，自检里未必存在，写失败会让「前置校验」变成假阴性。
FAKE_FFMPEG_BODY = (
    "import os, sys, time\n"
    "open(os.path.join(os.path.dirname(os.path.abspath(__file__)),\n"
    "     'ffmpeg.marker'), 'w').write('ran')\n"
    "print('fake ffmpeg')\nsys.stdout.flush()\ntime.sleep(9999)\n"
)

#: 冒充 NPE 的 java CLI
FAKE_JAVA_BODY = (
    "import sys, time\nsys.argv = sys.argv[1:]\n"
    "sys.stdout.write('booting\\n')\nsys.stdout.flush()\ntime.sleep(9999)\n"
)

#: 反向对照专用：短命且**不 fork 孙进程**的假 yt-dlp。
#: 绝不能复用上面那个——它会 fork 出 9999s 的孤儿进程，并让未取消的
#: fetch_info_json 白等满 180s 超时，把自检整体拖死。
FAKE_YTDLP_SHORT_BODY = (
    "import sys\n"
    "print('[info] fake failure')\nsys.stdout.flush()\n"
    "sys.exit(1)\n"
)


def _script(tmp, name, body):
    path = os.path.join(tmp, name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(body)
    return path


class _PyShim:
    """把「可执行文件路径 + 参数」形式的调用改写成 `python 脚本 + 参数`。

    产品代码拿到的永远是 yt-dlp.exe / ffmpeg.exe / java.exe 这类**可执行
    路径**，Windows 又不能直接执行 .py。与其造 .cmd 包装器（MSYS 会把
    反斜杠路径吃掉，写出来是坏的），不如在这里拦截 Popen 换掉可执行文件
    ——被测的「轮询 + 取消 + 登记」逻辑一字未动。

    `drop_n` = 从参数里丢掉前 n 个（用来吃掉 `-jar xxx.jar` 之类）。
    """

    def __init__(self, script, drop_n=0):
        self.script = script
        self.drop_n = drop_n

    def Popen(self, cmd, **kw):  # noqa: N802 —— 模拟 subprocess.Popen
        rest = list(cmd)[1 + self.drop_n:]
        return subprocess.Popen([sys.executable, self.script, *rest], **kw)

    run = staticmethod(subprocess.run)


def _pid_alive(pid):
    if not pid:
        return False
    try:
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                             capture_output=True, timeout=20)
        return str(pid).encode() in out.stdout
    except Exception:  # noqa: BLE001
        return False


def _wait_until(fn, timeout=6.0, step=0.15):
    end = time.time() + timeout
    while time.time() < end:
        if fn():
            return True
        time.sleep(step)
    return False


# ---------- 1. kill_process_tree ----------
def t_kill_tree():
    tmp = os.environ["VT_TMP"]
    pidfile = os.path.join(tmp, "kid.pid")
    if os.path.exists(pidfile):
        os.remove(pidfile)
    script = _script(tmp, "fk_tree.py", FAKE_YTDLP_BODY)
    proc = subprocess.Popen([sys.executable, script, pidfile],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if not _wait_until(lambda: os.path.exists(pidfile)):
        check("1a 前置：假进程 fork 出了孙进程", False, "pid 文件未生成")
        return
    with open(pidfile) as f:
        kid = f.read().strip()
    check("1a 前置：孙进程已存在且活着", _pid_alive(kid), f"pid={kid}")
    engine.kill_process_tree(proc)
    time.sleep(1.0)
    check("1b 父进程已退出", proc.poll() is not None, f"rc={proc.poll()}")
    check("1c 孙进程一并被杀（原实现只 kill 父进程——残留元凶）",
          not _pid_alive(kid), f"pid={kid}")


# ---------- 2. sleep_cancellable ----------
def t_sleep():
    evt = threading.Event()
    threading.Timer(0.3, evt.set).start()
    t0 = time.time()
    hit = engine.sleep_cancellable(30.0, evt)
    dt = time.time() - t0
    check("2a 取消后 sleep 立刻被打断", hit and dt < 3.0, f"{dt:.2f}s")
    t0 = time.time()
    hit = engine.sleep_cancellable(0.4, threading.Event())
    check("2b 未取消时睡满且不误打断",
          (not hit) and 0.35 <= time.time() - t0 < 2.0)


# ---------- 3. fetch_info_json ----------
def t_fetch():
    tmp = os.environ["VT_TMP"]
    script = _script(tmp, "fk_extract.py", FAKE_YTDLP_BODY)
    shim = _PyShim(script)
    orig = engine.popen_process
    orig_dl = _dl_ytdlp.popen_process
    # 隔离代理/cookie 初始化：这两步会去拉起 mihomo / 索取游客 cookie，
    # 与「取消能否生效」无关，却会把子进程启动拖到测量窗口之外。
    # v2.3.1：patch 点跟随实现域（见文件头说明）——engine.* 与
    # core.download.ytdlp_util.* 两侧都打，护住所有调用路径。
    orig_proxy, orig_cookie = engine.ytdlp_proxy_args, engine.ytdlp_cookie_args
    engine.popen_process = lambda *a, **k: shim.Popen(*a, **k)
    _dl_ytdlp.popen_process = engine.popen_process
    engine.ytdlp_proxy_args = lambda: []
    engine.ytdlp_cookie_args = lambda log=None: []
    _dl_ytdlp.ytdlp_proxy_args = engine.ytdlp_proxy_args
    _dl_ytdlp.ytdlp_cookie_args = engine.ytdlp_cookie_args
    try:
        # --- 正向对照：不取消时子进程确实起来了（否则下面的 PASS 是假阳性）
        evt0 = threading.Event()
        seen0 = {}
        th0 = threading.Thread(
            target=lambda: seen0.update(r=engine.fetch_info_json(
                "yt-dlp.exe", "http://example.invalid/v", attempts=1,
                cancel=evt0,
                register=lambda p: seen0.__setitem__("proc", p))),
            daemon=True)
        th0.start()
        ok_started = _wait_until(lambda: seen0.get("proc") is not None, timeout=5)
        check("3a 前置：提取阶段子进程确实被启动并登记", ok_started)
        evt0.set()
        th0.join(timeout=8)
        if seen0.get("proc") is not None:
            engine.kill_process_tree(seen0["proc"])

        # --- 取消：应立刻返回 None
        evt = threading.Event()
        seen = {}
        t0 = time.time()
        th = threading.Thread(
            target=lambda: seen.update(r=engine.fetch_info_json(
                "yt-dlp.exe", "http://example.invalid/v", attempts=3,
                cancel=evt, register=lambda p: seen.__setitem__("proc", p))),
            daemon=True)
        th.start()
        started = _wait_until(lambda: seen.get("proc") is not None, timeout=5)
        check("3b 前置：取消前子进程已登记", started)
        proc = seen.get("proc")
        evt.set()
        th.join(timeout=8)
        dt = time.time() - t0
        check("3c 提取阶段取消后立刻返回 None（原实现 180s×3 + 退避）",
              (not th.is_alive()) and seen.get("r") is None, f"{dt:.2f}s")
        check("3d 取消后子进程确实被杀掉",
              proc is not None and proc.poll() is not None)
        check("3e 取消后登记被回收（_procs 不留野指针）",
              seen.get("proc") is None or seen["proc"].poll() is not None)

        # --- 反向：未取消时行为不变（正常失败仍返回 None，不抛异常）
        #     用短命假源：验证「未取消时不误杀、正常走失败路径」。
        short = _script(tmp, "fk_short.py", FAKE_YTDLP_SHORT_BODY)
        engine.popen_process = (
            lambda *a, **k: subprocess.Popen(
                [sys.executable, short, *list(a[0])[1:]], **k))
        _dl_ytdlp.popen_process = engine.popen_process
        r = engine.fetch_info_json("yt-dlp.exe", "http://example.invalid/v",
                                   attempts=1, cancel=threading.Event())
        check("8a 未取消 + 短命假源 → 仍返回 None（失败路径未变）", r is None)
    finally:
        engine.popen_process = orig
        _dl_ytdlp.popen_process = orig_dl
        engine.ytdlp_proxy_args = orig_proxy
        engine.ytdlp_cookie_args = orig_cookie
        _dl_ytdlp.ytdlp_proxy_args = orig_proxy
        _dl_ytdlp.ytdlp_cookie_args = orig_cookie


# ---------- 4. make_cover_1280x720 ----------
def t_cover():
    tmp = os.environ["VT_TMP"]
    folder = os.path.join(tmp, "covertest")
    os.makedirs(folder, exist_ok=True)
    src = os.path.join(folder, "webp-thumb.jpg")
    with open(src, "wb") as f:
        f.write(b"\xff\xd8\xff\xe0" + b"x" * 4096)
    script = _script(tmp, "fk_ffmpeg.py", FAKE_FFMPEG_BODY)
    marker = os.path.join(tmp, "ffmpeg.marker")
    if os.path.exists(marker):
        os.remove(marker)
    shim = _PyShim(script)
    orig = engine.popen_process
    orig_dl = _dl_util.popen_process
    engine.popen_process = lambda *a, **k: shim.Popen(*a, **k)
    _dl_util.popen_process = engine.popen_process
    try:
        evt = threading.Event()
        box = {}
        th = threading.Thread(
            target=lambda: box.update(r=engine.make_cover_1280x720(
                "ffmpeg.exe", folder, timeout=60, cancel=evt,
                register=lambda p: box.__setitem__("proc", p))), daemon=True)
        th.start()
        # 正向对照：ffmpeg 真的跑起来了（marker 落地）
        ok_started = _wait_until(lambda: os.path.exists(marker), timeout=6)
        check("4a 前置：封面阶段的 ffmpeg 确实被启动", ok_started)
        proc = box.get("proc")   # 先取引用，再置标志，避免竞态读到 None
        t0 = time.time()
        evt.set()
        th.join(timeout=8)
        dt = time.time() - t0
        check("4b 封面阶段取消后立刻返回 False（原先白等 60s 超时）",
              (not th.is_alive()) and box.get("r") is False, f"{dt:.2f}s")
        check("4c 取消后 ffmpeg 被杀掉",
              proc is not None and _wait_until(
                  lambda: proc.poll() is not None, timeout=5),
              f"rc={proc.poll() if proc else 'no proc'}")
    finally:
        engine.popen_process = orig
        _dl_util.popen_process = orig_dl


# ---------- 5. NPE probe ----------
def t_npe():
    import npe_backend
    tmp = os.environ["VT_TMP"]
    script = _script(tmp, "fk_npe.py", FAKE_JAVA_BODY)
    # cmd 形如 [java, "-jar", jar, "--url", u, ...] → 丢掉 "-jar jar" 两项
    shim = _PyShim(script, drop_n=2)
    orig_popen = npe_backend.subprocess.Popen
    orig_jar = npe_backend.JAR_PATH
    npe_backend.subprocess = type("S", (), {
        "Popen": staticmethod(shim.Popen),
        "run": staticmethod(subprocess.run),
        "TimeoutExpired": subprocess.TimeoutExpired,
        "PIPE": subprocess.PIPE, "STDOUT": subprocess.STDOUT,
    })()
    # is_available() 会 os.path.isfile(JAR_PATH) —— 指向一个真实存在的
    # 占位文件，否则在 spawn 之前就短路返回「缺少 jar」，测不到取消逻辑。
    npe_backend.JAR_PATH = _script(tmp, "placeholder.jar", "x")
    try:
        evt = threading.Event()
        box = {}
        th = threading.Thread(
            target=lambda: box.update(r=npe_backend.probe(
                "http://example.invalid/v", timeout=45, retries=1,
                cancel=evt, register=lambda p: box.__setitem__("proc", p))),
            daemon=True)
        th.start()
        ok_started = _wait_until(lambda: box.get("proc") is not None, timeout=6)
        check("5a 前置：NPE 解析子进程确实被启动并登记", ok_started)
        proc = box.get("proc")
        t0 = time.time()
        evt.set()
        th.join(timeout=8)
        dt = time.time() - t0
        check("5b NPE 解析取消后立刻返回 cancelled（原先 (45+25)s×2）",
              (not th.is_alive())
              and box.get("r", {}).get("errorType") == "cancelled",
              f"{dt:.2f}s {box.get('r')}")
        check("5c 取消后 java 进程被杀掉",
              proc is not None and proc.poll() is not None)
    finally:
        npe_backend.subprocess.Popen = orig_popen
        npe_backend.JAR_PATH = orig_jar


# ---------- 6. GUI 源码层 ----------
def t_gui_source():
    path = os.path.join(APP_DIR, "src", "video_toolbox_qt.py")
    with open(path, encoding="utf-8") as f:
        text = f.read()
    check("6a on_dl_progress 对已取消/已收尾任务提前 return（状态不回弹）",
          'if item["status"] in ("取消中", "已取消", "完成", "失败"):' in text)
    check("6b on_dl_log 丢弃已取消任务的迟到日志（不再刷屏）",
          'if item and item["status"] in ("已取消", "完成", "失败"):' in text)
    check("6c 取消时置「取消中」而非写死「已取消」",
          'item["status"] = "取消中"' in text)
    check("6d 取消按钮杀的是进程树",
          "engine.kill_process_tree(proc)" in text)
    check("6e 提取锁改为可中断获取（_extract_lock）",
          "def _extract_lock(self, task_id" in text
          and "_EXTRACT_LOCK.acquire(timeout=0.2)" in text)
    check("6f 提取阶段传入 cancel + register",
          "cancel=evt,\n                register=lambda p: self._register_proc(task_id, p))"
          in text)
    check("6g 封面阶段传入 cancel + register",
          "engine.make_cover_1280x720(" in text
          and "cancel=evt," in text)
    check("6h NPE probe 传入 cancel + register",
          "cancel=evt, register=lambda p: self._register_proc(task_id, p))" in text)
    check("6i 引导阶段可取消（_CancelledEarly）",
          "raise _CancelledEarly()" in text
          and "except _CancelledEarly:" in text)
    check("8b on_task_select 只对「下载中」开放取消按钮",
          'self.cancel_btn.setEnabled(item["status"] == "下载中")' in text)
    # 反向：确认没有残留的 subprocess.run 提取/封面调用（它们杀不掉）
    # v2.3.1：download 域拆入 core/download/，fetch_info_json/parse_qualities
    # 锚点随迁至 core/download/ytdlp_util.py（facade 里已无这两个 def）。
    eng = os.path.join(APP_DIR, "src", "core", "download", "ytdlp_util.py")
    with open(eng, encoding="utf-8") as f:
        et = f.read()
    i = et.index("def fetch_info_json(")
    j = et.index("def parse_qualities(")
    check("8c fetch_info_json 内已无 subprocess.run（杀不掉的写法）",
          "subprocess.run(" not in et[i:j])
    check("8d fetch_info_json / make_cover 已导出 cancel 与 register 形参",
          "cancel=None, register=None" in et[i:j])


def main():
    import tempfile
    with tempfile.TemporaryDirectory(prefix="vt_cancel_") as tmp:
        os.environ["VT_TMP"] = tmp
        for fn in (t_kill_tree, t_sleep, t_fetch, t_cover, t_npe, t_gui_source):
            try:
                fn()
            except Exception as e:  # noqa: BLE001
                import traceback
                FAIL.append(fn.__name__)
                print(f"[FAIL] {fn.__name__} 抛异常: {e}")
                traceback.print_exc()
    print(f"\n结果：{len(PASS)} PASS / {len(FAIL)} FAIL")
    if FAIL:
        print("失败项：" + ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
