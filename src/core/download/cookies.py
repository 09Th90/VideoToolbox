# -*- coding: utf-8 -*-
# @version 2.5.0
"""YouTube cookie 通道（游客 cookie / 浏览器直读 / CDP 导出，反风控）（v2.3.1 拆分工程 · 自 video_toolbox.py 原样搬入）。

core/download 域：yt-dlp 全链 / cookie / NPE / 媒体合并；依赖规则见 core/__init__.py。
"""

from core.shared.proc import kill_process_tree, popen_process, run_process
from core.shared.textio import decode_bytes_any
from core.shared.textio import read_text_any


import json
import subprocess
import time
from core.download.deps import ensure_ytdlp
from core.shared.config import load_config, save_config
from core.shared.proc import (kill_process_tree, popen_process,
                           run_process)

import os
import threading

from core.shared.paths import DATA_DIR
from core.shared.proxy import ytdlp_proxy_args
from core.shared.runtime import _is_self_exe, system_python
from core.shared.textio import write_text_utf8

# ========== YouTube cookie（反「Sign in to confirm」风控） ==========
# ⚠️ 2026-09 实测：站方**游客 cookie** 在数据中心 / 代理节点 IP 上已基本失效
# ——同节点、同 UA、带游客 cookie 依旧被 `Sign in to confirm you're not a bot`
# 拦下（该方案原注释写的"前几发全过"已不再成立）。要真正过风控只能上**登录态**。
#
# 三级来源，按可信度从高到低自动降级：
#   ① 自备 cookies.txt（浏览器扩展导出）→ `--cookies <file>`（最彻底）；
#   ② 本机浏览器登录态               → `--cookies-from-browser <browser>`；
#   ③ 自动索取的站方游客 cookie（v1.15.8 老方案，仅作兜底）。
USER_COOKIES_PATH = os.path.join(DATA_DIR, "user_cookies.txt")
GUEST_COOKIES_PATH = os.path.join(DATA_DIR, "guest_cookies.txt")
GUEST_COOKIES_TTL = 6 * 3600
_GUEST_COOKIE_LOCK = threading.Lock()
_GUEST_COOKIE_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/131.0.0.0 Safari/537.36")

#: cookie 相关配置键（落在 data/config.json）
CFG_COOKIE_MODE = "ytdlp_cookie_mode"
CFG_COOKIE_BROWSER = "ytdlp_cookie_browser"
CFG_COOKIE_FILE = "ytdlp_cookie_file"
#: cookie 模式：显示名 ↔ 键（设置页下拉与此一一对应）
COOKIE_MODE_LABELS = (
    ("自动（自备文件 → 游客 cookie）", "auto"),
    ("从浏览器读取登录态", "browser"),
    ("使用我导出的 cookies.txt", "file"),
    ("只用自动游客 cookie", "guest"),
)
#: yt-dlp `--cookies-from-browser` 支持的常见浏览器
COOKIE_BROWSERS = ("chrome", "edge", "firefox", "brave", "chromium",
                   "opera", "vivaldi", "safari")
#: 只有**登录态**才会带的 cookie 名（游客 cookie 里没有这些）
_LOGIN_COOKIE_NAMES = ("SID", "HSID", "SSID", "APISID", "SAPISID",
                       "LOGIN_INFO", "__Secure-1PSID", "__Secure-3PSID",
                       "__Secure-1PAPISID", "__Secure-3PAPISID")


def _refresh_guest_cookies():
    """经内置代理访问 YouTube，收集站方签发的游客 cookie 并写 Netscape 文件。

    成功返回文件路径，失败返回 None（不抛异常——cookie 只是增益项，
    任何失败都不能阻塞下载主流程）。
    """
    import http.cookiejar
    # 必须经 ytdlp_proxy_args() 拿代理：它会启动/复用内置 mihomo 并填充缓存，
    # 直接读 _PROXY_CACHE 在首次调用时永远是 None（缓存还没人填过）
    proxy_args = ytdlp_proxy_args()
    proxy = proxy_args[1] if proxy_args else None
    if not proxy:
        # 代理不可用时直连抓取在用户网络必然失败，直接放弃，避免 20s 白等
        return None
    try:
        cj = http.cookiejar.MozillaCookieJar()
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": proxy, "https": proxy}),
            urllib.request.HTTPCookieProcessor(cj),
        )
        opener.addheaders = [
            ("User-Agent", _GUEST_COOKIE_UA),
            ("Accept-Language", "en-US,en;q=0.9"),
            ("Accept", "text/html,application/xhtml+xml,"
                       "application/xml;q=0.9,*/*;q=0.8"),
        ]
        # 首页拿 VISITOR_INFO1_LIVE / YSC / __Secure-ROLLOUT_TOKEN 等，
        # watch 页补一轮访客凭证（实测两步比只抓首页多拿 VISITOR_PRIVACY_METADATA）
        opener.open("https://www.youtube.com/", timeout=20).read(65536)
        time.sleep(1.0)
        opener.open("https://www.youtube.com/watch?v=BaW_jenozKc",
                    timeout=20).read(65536)
        names = {c.name for c in cj}
        if "VISITOR_INFO1_LIVE" not in names and "YSC" not in names:
            return None
        os.makedirs(DATA_DIR, exist_ok=True)
        cj.save(GUEST_COOKIES_PATH, ignore_discard=True, ignore_expires=True)
        return GUEST_COOKIES_PATH
    except Exception:  # noqa: BLE001
        return None


def cookie_mode():
    """当前 cookie 模式：auto / browser / file / guest。"""
    try:
        m = str((load_config() or {}).get(CFG_COOKIE_MODE) or "auto").strip().lower()
    except Exception:  # noqa: BLE001
        m = "auto"
    return m if m in ("auto", "browser", "file", "guest") else "auto"


def cookie_browser():
    """`--cookies-from-browser` 用的浏览器名。

    默认 **edge**（不是 chrome）：2026-09 实测，新版 Chrome 的 cookie 走
    App-Bound 加密，yt-dlp 直接 `Failed to decrypt with DPAPI` 解不开；Edge 是
    Windows 预装、加密方式仍可读，只要**完全退出**即可（否则报库被锁）。
    """
    try:
        b = str((load_config() or {}).get(CFG_COOKIE_BROWSER)
                or "edge").strip().lower()
    except Exception:  # noqa: BLE001
        b = "edge"
    return b if b in COOKIE_BROWSERS else "edge"


def cookie_file():
    """自备 cookies.txt 的路径（配置为空时回退 data\\user_cookies.txt）。"""
    try:
        p = str((load_config() or {}).get(CFG_COOKIE_FILE) or "").strip().strip('"')
    except Exception:  # noqa: BLE001
        p = ""
    if p and os.path.isfile(p):
        return p
    return USER_COOKIES_PATH if os.path.isfile(USER_COOKIES_PATH) else ""


def cookies_file_status(path):
    """检查 cookies.txt 是否可用：返回 `(可用, 是否登录态, 说明)`。

    关键是把「登录态」和「游客」分开报——2026-09 起游客 cookie 基本过不了
    风控，只说"文件在"会让用户以为配好了却照旧被拦，必须说清是哪一种。
    """
    if not path or not os.path.isfile(path):
        return False, False, "文件不存在"
    try:
        txt = read_text_any(path)
    except Exception as e:  # noqa: BLE001
        return False, False, f"读取失败：{type(e).__name__}"
    if "Netscape HTTP Cookie File" not in txt and "HTTP Cookie File" not in txt:
        return False, False, "不是 Netscape 格式的 cookies.txt"
    names, has_yt = set(), False
    for ln in txt.splitlines():
        if not ln or ln.startswith("#"):
            continue
        parts = ln.split("\t")
        if len(parts) < 7:
            continue
        dom = parts[0].lstrip(".")
        if dom == "youtube.com" or dom.endswith(".youtube.com") \
                or dom == "google.com" or dom.endswith(".google.com"):
            has_yt = True
            names.add(parts[5])
    if not has_yt:
        return False, False, "里面没有 youtube.com / google.com 的 cookie"
    if names & set(_LOGIN_COOKIE_NAMES):
        return True, True, "登录态（可用）"
    return True, False, "只有游客 cookie（多半仍会被风控拦）"


#: yt-dlp 加载浏览器 cookie 失败时的典型输出 → 给用户看的原因
_BROWSER_COOKIE_FAILS = (
    ("could not copy",
     "浏览器正在运行，cookie 库被锁 —— 请**完全退出**该浏览器后重试"),
    ("failed to decrypt",
     "该浏览器的 cookie 用了新版加密（App-Bound / DPAPI），yt-dlp 解不开 "
     "—— 请改用「cookies.txt」方式导出"),
    ("could not find",
     "没找到该浏览器的 cookie 库（未安装，或从未登录过）"),
)


def browser_cookie_probe(browser=None, timeout=30):
    """离线预检 `--cookies-from-browser` 能否真的读到登录态。

    做法：拿一个不需要联网的伪地址（about:blank）跑 `--simulate` —— yt-dlp 会
    **先加载 cookie、再解析 URL**：cookie 读不出来就直接报错，读得出来才轮到
    "Unsupported URL"。整个探测 1~3 秒、不产生真实下载请求，因此可以放心在
    下载前预检，避免"选了浏览器却读不到 → 任务直接失败"（实测 edge 与 chrome
    在浏览器开着 / 新版加密时都会这样）。

    返回 `(可用, 说明)`。
    """
    ok, _key, why = _browser_cookie_probe_raw(browser, timeout)
    return ok, why


def _browser_cookie_probe_raw(browser=None, timeout=30):
    """同 `browser_cookie_probe`，但额外把**失败类别**透出来。

    返回 `(可用, 失败键, 说明)`；失败键 ∈ `""` / `"could not copy"` /
    `"failed to decrypt"` / `"could not find"` / `"probe"`。

    为什么要多返一个键：`browser_cookie_probe` 给的是**中文文案**，拿它做分类
    只能靠字符串匹配中文，一改文案就失效（踩过）；分类判据必须钉在 yt-dlp 的
    英文原文上。`browser_cookie_diagnose` 用这个版本。
    """
    br = browser or cookie_browser()
    try:
        r = run_process([ensure_ytdlp(), "--cookies-from-browser", br,
                         "--simulate", "--no-playlist", "about:blank"],
                        capture_output=True, timeout=timeout)
        out = (decode_bytes_any(r.stdout) + decode_bytes_any(r.stderr)).lower()
    except Exception as e:  # noqa: BLE001
        return False, "probe", f"探测失败：{type(e).__name__}"
    for key, why in _BROWSER_COOKIE_FAILS:
        if key in out:
            return False, key, f"{br}：{why}"
    return True, "", f"{br} 登录态可读"


#: yt-dlp 读不出浏览器 cookie 库的输出特征（与网络无关，重试同参数永远失败）
_COOKIE_LOAD_FAIL_KEYS = (
    "could not copy",            # #7271：浏览器开着，cookie 库被独占锁
    "could not find",            # 找不到 cookie 库（未安装 / 从未登录）
    "failed to decrypt",         # App-Bound / DPAPI 解不开
    "no encrypted key",
    "cookie database",
)


def cookie_load_failure_reason(text):
    """yt-dlp 输出是否属「浏览器 cookie 读不出来」。是则返回中文原因，否则 ''。

    这类失败跟站点风控/网络都无关，**换 cookie 来源才能继续**——所以调用方
    应当失效 cookie 缓存、重新解析来源后重试，而不是退避重试同一套参数。
    """
    low = str(text or "").lower()
    if not any(k in low for k in _COOKIE_LOAD_FAIL_KEYS):
        return ""
    for key, why in _BROWSER_COOKIE_FAILS:
        if key in low:
            return why
    return "浏览器 cookie 库读取失败"


#: 各浏览器「用户数据目录」（与 yt-dlp `_get_chromium_based_browser_settings` 同源）
_BROWSER_USER_DATA = {
    "chrome": r"%LOCALAPPDATA%\Google\Chrome\User Data",
    "edge": r"%LOCALAPPDATA%\Microsoft\Edge\User Data",
    "chromium": r"%LOCALAPPDATA%\Chromium\User Data",
    "brave": r"%LOCALAPPDATA%\BraveSoftware\Brave-Browser\User Data",
    "vivaldi": r"%LOCALAPPDATA%\Vivaldi\User Data",
    "whale": r"%LOCALAPPDATA%\Naver\Naver Whale\User Data",
    "opera": r"%APPDATA%\Opera Software\Opera Stable",
}
#: 各浏览器可执行文件的候选路径（按顺序取第一个存在的）
_BROWSER_EXE = {
    "chrome": (r"%PROGRAMFILES%\Google\Chrome\Application\chrome.exe",
               r"%PROGRAMFILES(X86)%\Google\Chrome\Application\chrome.exe",
               r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    "edge": (r"%PROGRAMFILES(X86)%\Microsoft\Edge\Application\msedge.exe",
             r"%PROGRAMFILES%\Microsoft\Edge\Application\msedge.exe"),
    "chromium": (r"%PROGRAMFILES%\Chromium\Application\chrome.exe",
                 r"%LOCALAPPDATA%\Chromium\Application\chrome.exe"),
    "brave": (r"%PROGRAMFILES%\BraveSoftware\Brave-Browser\Application\brave.exe",
              r"%LOCALAPPDATA%\BraveSoftware\Brave-Browser\Application\brave.exe"),
    "vivaldi": (r"%LOCALAPPDATA%\Vivaldi\Application\vivaldi.exe",),
    "whale": (r"%PROGRAMFILES%\Naver\Naver Whale\Application\whale.exe",
              r"%LOCALAPPDATA%\Naver\Naver Whale\Application\whale.exe"),
    "opera": (r"%LOCALAPPDATA%\Programs\Opera\opera.exe",
              r"%PROGRAMFILES%\Opera\opera.exe"),
}


def browser_user_data_dir(browser=None):
    """浏览器「用户数据目录」绝对路径（不存在时也返回路径，供上层判断）。"""
    br = browser or cookie_browser()
    p = _BROWSER_USER_DATA.get(br)
    return os.path.expandvars(p) if p else ""


def browser_exe_path(browser=None):
    """浏览器可执行文件路径；找不到返回 ""。"""
    br = browser or cookie_browser()
    for p in _BROWSER_EXE.get(br, ()):
        p = os.path.expandvars(p)
        if os.path.isfile(p):
            return p
    return ""


def browser_app_bound_enabled(browser=None):
    """浏览器是否启用了 App-Bound 加密（cookie 值前缀 `v20`）。

    判据：`Local State` 的 `os_crypt.app_bound_encrypted_key` 存在。这是
    「yt-dlp 解不开」的根因标志（见 `browser_cookie_diagnose`）。
    """
    base = browser_user_data_dir(browser)
    if not base:
        return False
    try:
        with open(os.path.join(base, "Local State"), encoding="utf-8") as f:
            oc = (json.load(f) or {}).get("os_crypt") or {}
        return bool(oc.get("app_bound_encrypted_key"))
    except Exception:  # noqa: BLE001
        return False


def browser_cookie_diagnose(browser=None):
    """浏览器登录态可读性诊断：返回 `(verdict, 说明)`。

    verdict ∈ `ok` / `locked` / `appbound` / `missing` / `unknown`。

    ⚠️ 2026-10-14 实测结论（本机 Edge 155 / Chrome 155，Windows）：
    Chrome / Edge 已全面启用 **App-Bound 加密**（cookie 值前缀 `v20`，
    `meta.version=24`，`Local State` 带 `os_crypt.app_bound_encrypted_key`）。
    而 yt-dlp 2026.08.19 的 `WindowsChromeCookieDecryptor.decrypt` **只认 `v10`**，
    其它前缀一律当成 DPAPI 去解 → `Failed to decrypt with DPAPI`
    （yt-dlp #10927）→ 直接 `DownloadError` 判死任务。

    ⇒ **现代 Chrome/Edge 的登录态，yt-dlp 根本读不出来，跟浏览器开不开无关。**
    真正可用的只有两条路：
      ① `export_browser_cookies_via_cdp()`——让浏览器自己解密后经 CDP 吐明文；
      ② 浏览器扩展导出 cookies.txt。
    """
    br = browser or cookie_browser()
    base = browser_user_data_dir(br)
    if not base or not os.path.isdir(base):
        return "missing", f"没找到 {br} 的用户数据目录（未安装，或从未运行过）"

    ok, key, why = _browser_cookie_probe_raw(br)
    if ok:
        return "ok", f"{br} 登录态可读，可直接使用"
    if key == "could not copy":
        return "locked", (
            f"{br} 正在运行 → cookie 库被独占锁，yt-dlp 读不出来"
            f"（yt-dlp #7271；实测 `FILE_SHARE_READ|WRITE|DELETE` 也开不了）。"
            f"两条路：① 完全退出 {br} 后重试；② 直接点下面的"
            f"「导入浏览器登录态」——它用独立配置目录，不受这个锁影响")
    if key == "failed to decrypt":
        abe = "（已在 Local State 确认启用）" \
            if browser_app_bound_enabled(br) else ""
        return "appbound", (
            f"{br} 的 cookie 是 **App-Bound 加密（v20）**{abe}，而 yt-dlp 只会"
            f"按老的 DPAPI(v10) 去解 → 必然失败（yt-dlp #10927）——"
            f"**完全退出浏览器也没用**。两条路："
            f"① 点下面的「导入浏览器登录态」（借浏览器自己解密、经 CDP 取明文）；"
            f"② 用浏览器扩展「Get cookies.txt LOCALLY」在 youtube.com 导出")
    if key == "could not find":
        return "missing", (f"{br}：没找到 cookie 库（未安装，或从未登录过）"
                           f"—— 先打开该浏览器登录一次 YouTube 再试")
    return "unknown", f"{why}"


#: 「导入浏览器登录态」专用的独立配置目录。
#: ⚠️ 刻意**不复用**用户正在用的配置：既不与运行中的浏览器抢 cookie 库锁，
#: 也不会被浏览器的单实例守卫拦下（用户原来的浏览器可以照常开着）。
CDP_LOGIN_DIR = os.path.join(DATA_DIR, "browser_login")
#: 登录窗口打开的地址
CDP_LOGIN_URL = "https://www.youtube.com/"


def write_netscape_cookies(cookies, path):
    """把 CDP 取回的 cookie 列表写成 yt-dlp 认的 Netscape cookies.txt。

    返回写入条数。`expires<=0`（会话 cookie）按 Netscape 惯例写 0。
    """
    lines = ["# Netscape HTTP Cookie File",
             "# 由 视频工具箱 经 CDP 从浏览器导出（明文）；内含登录凭据，请勿外传",
             ""]
    n = 0
    for c in cookies or []:
        domain = str(c.get("domain") or "").strip()
        name = str(c.get("name") or "").strip()
        if not domain or not name:
            continue
        try:
            exp = int(float(c.get("expires") or 0))
        except (TypeError, ValueError):
            exp = 0
        if exp < 0:
            exp = 0
        lines.append("\t".join((
            domain,
            "TRUE" if domain.startswith(".") else "FALSE",
            str(c.get("path") or "/"),
            "TRUE" if c.get("secure") else "FALSE",
            str(exp), name, str(c.get("value") or ""))))
        n += 1
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    # 固定 LF：Netscape 文件跨平台通用，也避免 CRLF 影响 yt-dlp 解析
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    return n


def _free_local_port():
    import socket
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
    finally:
        s.close()


def export_browser_cookies_via_cdp(browser=None, log=None, cancel=None,
                                   login_timeout=300, start_timeout=60,
                                   out_path=None, port=0):
    """借「独立配置 + 调试端口」的浏览器，把登录态 cookie 导出成 cookies.txt。

    **为什么必须绕这一圈**：现代 Chrome/Edge 的 cookie 是 App-Bound 加密
    （v20），yt-dlp 解不开（#10927）；但**浏览器自己**解得开。于是让它把 cookie
    通过 CDP（DevTools 协议）吐出来——那是明文，与加密版本无关，也不受
    「浏览器开着锁库」影响（#7271）。

    流程：用 `--user-data-dir=<独立目录> --remote-debugging-port=<端口>` 起一个
    全新配置的浏览器窗口 → 用户在窗口里登录 YouTube → 程序轮询 CDP 直到出现
    登录态 cookie（`SID` / `SAPISID` / `__Secure-3PSID` …）→ 写
    `data/user_cookies.txt` → 把「Cookie 来源」切到「自备 cookies.txt」→
    关掉这个临时浏览器。

    返回 `(是否成功, 说明, cookies.txt 路径或 "")`。全程不抛异常。
    """
    def _log(msg):
        if log:
            try:
                log(msg)
            except Exception:  # noqa: BLE001
                pass

    def _cancelled():
        return cancel is not None and cancel.is_set()

    br = browser or cookie_browser()
    exe = browser_exe_path(br)
    if not exe:
        return False, (f"没找到 {br} 的可执行文件——请先在设置页把「浏览器」"
                       f"换成已安装的那个，或改用 cookies.txt 方式"), ""
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:  # noqa: BLE001
        return False, f"内置浏览器组件（Playwright）不可用：{type(e).__name__}", ""

    prof = os.path.join(CDP_LOGIN_DIR, br)
    try:
        os.makedirs(prof, exist_ok=True)
    except OSError as e:
        return False, f"无法创建登录用配置目录：{e}", ""
    out = out_path or USER_COOKIES_PATH
    p = int(port or 0) or _free_local_port()

    args = [
        exe,
        f"--user-data-dir={prof}",
        f"--remote-debugging-port={p}",
        "--no-first-run", "--no-default-browser-check",
        "--disable-features=Translate,MediaRouter",
        "--window-size=1180,860",
        CDP_LOGIN_URL,
    ]
    _log(f"[信息] 正在启动独立配置的 {br}（不影响你正在用的浏览器窗口）...")
    proc = None
    try:
        proc = popen_process(args, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
    except Exception as e:  # noqa: BLE001
        return False, f"启动浏览器失败：{type(e).__name__}: {e}", ""

    endpoint = f"http://127.0.0.1:{p}"
    try:
        # ① 等 CDP 端点就绪
        deadline = time.time() + max(10, int(start_timeout))
        ver = None
        while time.time() < deadline:
            if _cancelled():
                return False, "已取消", ""
            try:
                import urllib.request
                with urllib.request.urlopen(endpoint + "/json/version",
                                            timeout=1) as r:
                    ver = json.loads(r.read().decode("utf-8", "replace"))
                break
            except Exception:  # noqa: BLE001
                time.sleep(0.5)
        if not ver:
            return False, (
                f"{br} 的调试端口没起来。常见原因：上一次导入留下的浏览器窗口"
                f"还开着（会顶掉这次启动）——把它关掉后重试；"
                f"或换一个浏览器再试"), ""
        _log(f"[信息] 已连接浏览器 {ver.get('Browser', br)}，"
             f"请在打开的窗口里登录 YouTube ...")

        # ② 连上去轮询登录态 cookie
        login_names = set(_LOGIN_COOKIE_NAMES)
        with sync_playwright() as pw:
            browser_cdp = pw.chromium.connect_over_cdp(endpoint)
            try:
                ctx = browser_cdp.contexts[0] if browser_cdp.contexts \
                    else browser_cdp.new_context()
                deadline = time.time() + max(30, int(login_timeout))
                last_tip = 0.0
                cookies = []
                while True:
                    if _cancelled():
                        return False, "已取消", ""
                    try:
                        cookies = ctx.cookies()
                    except Exception:  # noqa: BLE001
                        cookies = []
                    names = {c.get("name") for c in cookies}
                    if names & login_names:
                        break
                    if time.time() > deadline:
                        return False, (
                            f"等待登录超时（{int(login_timeout)}s）——"
                            f"请在打开的 {br} 窗口里完成 YouTube 登录后重试"), ""
                    if time.time() - last_tip > 20:
                        last_tip = time.time()
                        _log("[信息] 仍在等待登录（登录成功后会自动继续）...")
                    time.sleep(1.5)

                n = write_netscape_cookies(cookies, out)
                if n <= 0:
                    return False, "已连接但没取到任何 cookie", ""
                ok, logged, why = cookies_file_status(out)
                if not (ok and logged):
                    return False, f"导出的 cookies.txt 校验不通过（{why}）", ""
                # ③ 切到「自备 cookies.txt」并清缓存
                cfg = load_config() or {}
                cfg[CFG_COOKIE_MODE] = "file"
                cfg[CFG_COOKIE_FILE] = out
                save_config(cfg)
                invalidate_cookie_cache()
                _log(f"[信息] 已导出 {n} 条 cookie（含登录态）→ {out}")
                return True, f"已导出 {n} 条 cookie 并切换为「自备 cookies.txt」", out
            finally:
                try:
                    browser_cdp.close()
                except Exception:  # noqa: BLE001
                    pass
    except Exception as e:  # noqa: BLE001
        return False, f"导入失败：{type(e).__name__}: {e}", ""
    finally:
        if proc is not None:
            try:
                kill_process_tree(proc)
            except Exception:  # noqa: BLE001
                try:
                    proc.terminate()
                except Exception:  # noqa: BLE001
                    pass


def _guest_cookie_args(emit=None):
    """站方**游客** cookie（v1.15.8 老方案）。2026-09 起多数代理节点已失效。"""
    def _emit(msg):
        if emit:
            try:
                emit(msg)
            except Exception:  # noqa: BLE001
                pass

    def _fresh(path):
        try:
            return (time.time() - os.path.getmtime(path)) < GUEST_COOKIES_TTL
        except OSError:
            return False

    with _GUEST_COOKIE_LOCK:
        path = GUEST_COOKIES_PATH
        if not _fresh(path):
            _emit("[信息] 正在获取 YouTube 游客 cookie（反风控）...")
            new = _refresh_guest_cookies()
            if new:
                _emit("[信息] 游客 cookie 已更新（6 小时内自动复用）")
            elif os.path.isfile(path):
                _emit("[信息] 游客 cookie 刷新失败，沿用上一次的文件")
            else:
                _emit("[信息] 游客 cookie 不可用，按无 cookie 继续")
        return ["--cookies", path] if os.path.isfile(path) else []


#: cookie 参数缓存（配置变更时由 `invalidate_cookie_cache()` 清掉）
_COOKIE_ARGS_CACHE = {"args": None, "at": 0.0}
_COOKIE_ARGS_LOCK = threading.Lock()
#: 缓存有效期（秒）。浏览器登录态是**易变**的——用户随时开/关浏览器。缓存太久
#: 会出现：预检时浏览器没开 → 缓存了「浏览器来源」→ 用户随后打开浏览器 →
#: 之后所有任务都撞 cookie 库被独占锁（yt-dlp #7271）。120s 既省掉同一批任务
#: 的重复预检，又让状态变化在一两分钟内自愈。
_COOKIE_ARGS_TTL = 120.0


def invalidate_cookie_cache():
    """设置页保存 cookie 配置后调用，让下一次取用重新解析来源。"""
    _COOKIE_ARGS_CACHE["args"] = None
    _COOKIE_ARGS_CACHE["at"] = 0.0


def ytdlp_cookie_args(refresh=False, log=None):
    """给 yt-dlp 的 cookie 参数表（三级来源，按可信度自动降级）。

    · `auto`（默认）：自备 cookies.txt → 浏览器登录态（**离线预检通过才用**）
      → 自动游客 cookie，逐级降级。浏览器那级必须预检，否则 cookie 库被锁 /
      新版加密解不开时 yt-dlp 会直接报错退出，反而把能下的任务弄挂。
    · `browser`：`--cookies-from-browser <浏览器>`（需该浏览器已登录 YouTube，
      且读取时**完全退出浏览器**）。
    · `file`  ：只用自备 cookies.txt。
    · `guest` ：只用自动索取的游客 cookie。

    全部不可得 → 返回 []（退回无 cookie，行为与旧版一致）。
    """
    def _emit(msg):
        if log:
            try:
                log(msg)
            except Exception:  # noqa: BLE001
                pass

    #: 双检锁：并发任务同时首次取用时只探测一次 cookie 来源。此前 N 个任务
    #: 会各自 spawn 一个浏览器 cookie 预检 yt-dlp 进程（各 30s 超时）、再
    #: 串行抢游客 cookie 刷新锁——多任务同加时集体白等几十秒。
    with _COOKIE_ARGS_LOCK:
        if (not refresh and _COOKIE_ARGS_CACHE["args"] is not None
                and (time.time() - _COOKIE_ARGS_CACHE["at"]) < _COOKIE_ARGS_TTL):
            return _COOKIE_ARGS_CACHE["args"]
        args = _ytdlp_cookie_args_uncached(_emit)
        _COOKIE_ARGS_CACHE["args"] = args
        _COOKIE_ARGS_CACHE["at"] = time.time()
        return args


def _self_cookie_args(_emit, warn=False):
    """① 自备 cookies.txt（登录态，最彻底）。不可用时返回 []。"""
    p = cookie_file()
    ok, logged, why = cookies_file_status(p) if p else (False, False, "未配置")
    if ok:
        if not logged:
            _emit("[信息] 自备 cookies.txt 里只有游客 cookie —— "
                  "若仍被风控拦，请用**已登录 YouTube** 的浏览器重新导出")
        return ["--cookies", p]
    if warn:
        _emit(f"[信息] 自备 cookies.txt 不可用（{why}），已回退其它来源")
    return []


def _browser_cookie_args(_emit, explicit):
    """② 浏览器登录态。不可用时返回 []。`explicit` = 设置页显式选了 browser 档。

    ⚠️ 2026-10-14 修正：此前 `explicit` 时**预检失败也照用**——结果浏览器开着
    → cookie 库被独占锁 → yt-dlp 直接 `ERROR: Could not copy Chrome cookie
    database`（yt-dlp #7271）→ 整条任务判死，界面上只看到「画质检测失败：
    站点风控或网络异常」，完全看不出真因。现在一律**预检通过才用**，否则降级
    到下一级来源，并把「怎么恢复登录态」直接写进日志。
    """
    br = cookie_browser()
    verdict, text = browser_cookie_diagnose(br)
    if verdict == "ok":
        _emit(f"[信息] 从浏览器读取登录态：{br}")
        return ["--cookies-from-browser", br]
    # 诊断文案里已经带了「怎么办」，这里只补一句设置页的入口
    _emit(f"[警告] 浏览器登录态不可用 —— {text}")
    if explicit:
        if verdict == "locked":
            _emit("[提示] 完全退出该浏览器后重试即可；"
                  "或用设置页「下载 Cookie」卡片的「导入浏览器登录态」"
                  "（独立配置，不受浏览器开着的影响）")
        else:
            _emit("[提示] 请用设置页「下载 Cookie」卡片的「导入浏览器登录态」，"
                  "或用浏览器扩展「Get cookies.txt LOCALLY」导出 cookies.txt")
    return []


def _ytdlp_cookie_args_uncached(_emit):
    """（调用方须持 _COOKIE_ARGS_LOCK）cookie 来源逐级降级。

    顺序按当前模式定：
      · auto    → 自备文件 → 浏览器登录态 → 游客 cookie
      · file    → 自备文件 → 游客 cookie
      · browser → 浏览器登录态 → 自备文件 → 游客 cookie
      · guest   → 游客 cookie
    任一来源不可用就往下走——**绝不把「读不到 cookie」当成任务失败**。
    """
    mode = cookie_mode()

    # ① 自备 cookies.txt（登录态，最彻底）
    if mode in ("auto", "file"):
        args = _self_cookie_args(_emit, warn=(mode == "file"))
        if args:
            return args

    # ② 浏览器登录态
    if mode in ("auto", "browser"):
        args = _browser_cookie_args(_emit, explicit=(mode == "browser"))
        if args:
            return args
        # browser 档预检不过时再退一级到自备文件（总比裸奔强）
        if mode == "browser":
            args = _self_cookie_args(_emit, warn=False)
            if args:
                return args

    # ③ 游客 cookie 兜底
    return _guest_cookie_args(emit=_emit)






__all__ = [
    "USER_COOKIES_PATH",
    "GUEST_COOKIES_PATH",
    "GUEST_COOKIES_TTL",
    "CDP_LOGIN_DIR",
    "CDP_LOGIN_URL",
    "CFG_COOKIE_MODE",
    "CFG_COOKIE_BROWSER",
    "CFG_COOKIE_FILE",
    "COOKIE_MODE_LABELS",
    "COOKIE_BROWSERS",
    "cookie_mode",
    "cookie_browser",
    "cookie_file",
    "cookies_file_status",
    "browser_cookie_probe",
    "cookie_load_failure_reason",
    "browser_user_data_dir",
    "browser_exe_path",
    "browser_app_bound_enabled",
    "browser_cookie_diagnose",
    "write_netscape_cookies",
    "export_browser_cookies_via_cdp",
    "ytdlp_cookie_args",
    "invalidate_cookie_cache",
    "_GUEST_COOKIE_LOCK",
    "_GUEST_COOKIE_UA",
    "_LOGIN_COOKIE_NAMES",
    "_BROWSER_COOKIE_FAILS",
    "_COOKIE_LOAD_FAIL_KEYS",
    "_BROWSER_USER_DATA",
    "_BROWSER_EXE",
    "_COOKIE_ARGS_CACHE",
    "_COOKIE_ARGS_LOCK",
    "_COOKIE_ARGS_TTL",
]
