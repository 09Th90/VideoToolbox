# -*- coding: utf-8 -*-
# @version 2.4.1
"""内置代理（mihomo/ClashMeta）：引导 / 选节点 / 代理参数 / 节点锁定（v2.3.1 拆分工程 · 自 video_toolbox.py 原样搬入）。

本模块是 src/core/shared/ 的组成部分；域间依赖规则见 core/__init__.py。
"""

from core.shared.paths import LOGS_DIR, TOOLS_DIR, clean_path

import atexit
import json
import os
import subprocess
import sys
import threading
import time

from core.shared.config import load_config, save_config
from core.shared.log import _append_log
from core.shared.paths import LOGS_DIR, TOOLS_DIR
from core.shared.proc import run_process

# ===== 内置代理（mihomo/ClashMeta 核心，与 FlClash 同源，随安装包分发）=====
# 用途：程序从 GitHub/HuggingFace 等开源库下载依赖、yt-dlp 下载 YouTube 视频
#       与字幕时自动启用，其余流量直连。
# 端口固定 7897，与本机其他代理（FlClash 等占用 7890）互不冲突。
MIHOMO_DIR = os.path.join(TOOLS_DIR, "mihomo")
MIHOMO_EXE = os.path.join(MIHOMO_DIR, "mihomo.exe")
MIHOMO_CONFIG = os.path.join(MIHOMO_DIR, "config.yaml")
#: 引擎编译出的运行配置（节点取自订阅，端口/规则/代理组固定程序专用）
MIHOMO_RUNTIME_CONFIG = os.path.join(MIHOMO_DIR, "runtime.yaml")
MIHOMO_PROXY = "http://127.0.0.1:7897"
MIHOMO_PORT = 7897
#: mihomo 控制端口（RESTful API）：程序用来主动触发节点测速 / 切换节点。
#: 只绑 127.0.0.1，无密钥，仅本机可访问。
MIHOMO_CONTROLLER = "127.0.0.1:9098"
#: ⚠ 本文件**唯一**的 MIHOMO_API 定义点。VT_MIHOMO_API 可覆盖（应急/排查）；
#:   后半部分不得再赋值——顶层同名定义会互相遮蔽（2026-10-12 事故根因）。
MIHOMO_API = os.environ.get("VT_MIHOMO_API", "http://" + MIHOMO_CONTROLLER)
#: 节点测活 URL（mihomo 惯例 204 探测）
MIHOMO_TEST_URL = "https://www.gstatic.com/generate_204"


# ========== 工具引导：mihomo 常驻进程句柄（v2.3.1 随代理域迁入） ==========
_MIHOMO_PROC = None

def _port_listening(port, timeout=0.5):
    """探测本地端口是否已被监听（判断内置代理是否已在运行）"""
    import socket
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


#: mihomo 的运行日志（配置写错 / 节点不通时唯一能查的地方）
MIHOMO_LOG = os.path.join(LOGS_DIR, "mihomo.log")


def _mihomo_log(msg):
    """把 mihomo 相关事件追加到 logs\\mihomo.log（失败静默，绝不影响主流程）。

    统一走 `_append_log`：轮转 + 去重 + 级别标记（v1.16.2）。节点超时一类
    重复告警不再把日志刷成几百行。
    """
    _append_log("mihomo.log", msg)


def _load_proxy_nodes(path):
    """从 Clash/mihomo yaml 提取节点定义（proxies 段原样保留，含密钥字段）。

    返回节点 dict 列表；文件不存在/解析失败/没有节点返回 []。
    只取节点不取规则与代理组 —— 分流规则固定用内置模板（GitHub/YouTube 走
    代理、国内直连），避免订阅里 "MATCH,SELECT" 之类规则把所有流量推进代理。
    """
    try:
        import yaml
        with open(path, encoding="utf-8-sig") as f:
            data = yaml.safe_load(f) or {}
        nodes = [n for n in (data.get("proxies") or [])
                 if isinstance(n, dict) and n.get("name")]
        return nodes
    except Exception:
        return []


def _build_runtime_config():
    """编译 mihomo 运行配置，返回 (runtime.yaml 路径或 None, 节点数)。

    结构（v1.13.8，参考 FlClash 的内核用法，补上自动选活）：
      · 节点源：config.json proxy_yaml 指向的订阅/自定义 yaml 优先；
        为空时用内置 config.yaml 自带的节点快照兜底。
      · mixed-port 固定 7897（与 FlClash 7890 互不冲突，也不再从订阅里
        读端口 —— 旧逻辑订阅写 7890 就监听 7890，和 FlClash 撞车风险）。
      · 代理组重写为自动收敛结构：
          AUTO   url-test 全部节点，自动选延迟最低的活节点；
          SELECT fallback，成员 = [AUTO] + 全部节点 —— 死节点自动跳过、
                 每分钟健康检查，即使程序不做任何干预也能自愈。
      · 分流规则/dns/log-level 沿用内置 config.yaml 模板。
    """
    import yaml
    base = {}
    try:
        with open(MIHOMO_CONFIG, encoding="utf-8-sig") as f:
            base = yaml.safe_load(f) or {}
    except Exception:
        base = {}
    nodes = []
    sub = get_proxy_yaml()
    if sub and os.path.isfile(sub):
        nodes = _load_proxy_nodes(sub)
    if not nodes:
        nodes = [n for n in (base.get("proxies") or [])
                 if isinstance(n, dict) and n.get("name")]
    if not nodes:
        return None, 0
    names = [str(n["name"]) for n in nodes]
    cfg = dict(base) if isinstance(base, dict) else {}
    cfg["mixed-port"] = MIHOMO_PORT
    cfg["allow-lan"] = False
    cfg["mode"] = "rule"
    cfg["ipv6"] = False
    cfg["external-controller"] = MIHOMO_CONTROLLER
    cfg["secret"] = ""
    cfg["proxies"] = nodes
    cfg["proxy-groups"] = [
        {"name": "AUTO", "type": "url-test", "url": MIHOMO_TEST_URL,
         "interval": 300, "tolerance": 50, "proxies": names},
        {"name": "SELECT", "type": "fallback", "url": MIHOMO_TEST_URL,
         "interval": 60, "proxies": ["AUTO"] + names},
    ]
    if not cfg.get("rules"):
        cfg["rules"] = ["MATCH,SELECT"]
    try:
        os.makedirs(MIHOMO_DIR, exist_ok=True)
        with open(MIHOMO_RUNTIME_CONFIG, "w", encoding="utf-8") as f:
            yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False,
                           default_flow_style=False)
    except Exception as e:  # noqa: BLE001
        _mihomo_log(f"写入运行配置失败：{e}")
        return None, len(names)
    return MIHOMO_RUNTIME_CONFIG, len(names)


def _mihomo_api(path, method="GET", body=None, timeout=10):
    """调用 mihomo 控制端口 RESTful API；失败返回 None。"""
    import json as _json
    import urllib.parse
    import urllib.request          # 显式补齐：早期靠别处 import 的属性副作用
    url = MIHOMO_API + path
    data = None
    if body is not None:
        data = _json.dumps(body).encode("utf-8")
    try:
        req = urllib.request.Request(url, data=data, method=method)
        if data is not None:
            req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8", "replace")
        return _json.loads(raw) if raw.strip() else {}
    except Exception:
        return None


def _proxy_http_ok(proxy, timeout=6):
    """经代理真实出网一次（204 探测），确认"端口活着且节点可用"。

    双目标逐个尝试：gstatic（mihomo 默认测活地址）→ YouTube。
    单目标 + 短超时会在慢节点上**误杀可用代理**（2026-10-17 实测：3s 超时
    只探 gstatic 时，FlClash 的 TLS 握手偶发 5.9s，被判不可用 → yt-dlp
    静默直连 → YouTube 全部超时）。
    """
    import urllib.request
    for url in (MIHOMO_TEST_URL, "https://www.youtube.com/generate_204"):
        try:
            opener = urllib.request.build_opener(
                urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
            opener.addheaders = [("User-Agent", "Mozilla/5.0")]
            with opener.open(url, timeout=timeout) as r:
                if getattr(r, "status", 200) in (200, 204):
                    return True
        except Exception:
            continue
    return False


def _group_alive_delays(group="AUTO", timeout_ms=4000):
    """让 mihomo 对组内全部节点并发测速，返回 {节点名: 延迟ms}（只含成功的）。

    对应 mihomo 扩展接口 GET /group/:name/delay；核心不支持该接口时返回 None。
    """
    import urllib.parse
    q = urllib.parse.urlencode({"url": MIHOMO_TEST_URL, "timeout": timeout_ms})
    res = _mihomo_api(f"/group/{urllib.parse.quote(group)}/delay?{q}",
                      timeout=max(12.0, timeout_ms / 1000.0 + 8.0))
    if not isinstance(res, dict):
        return None
    return {k: int(v) for k, v in res.items()
            if isinstance(v, (int, float)) and v > 0}


def _probe_each_node(names, timeout_ms=2500, workers=8):
    """逐节点测速兜底（组级接口不可用时），并发执行，返回 {节点名: 延迟ms}。"""
    import urllib.parse
    from concurrent.futures import ThreadPoolExecutor

    def _one(name):
        q = urllib.parse.urlencode(
            {"url": MIHOMO_TEST_URL, "timeout": timeout_ms})
        res = _mihomo_api(
            f"/proxies/{urllib.parse.quote(name)}/delay?{q}",
            timeout=timeout_ms / 1000.0 + 6.0)
        if isinstance(res, dict) and isinstance(res.get("delay"), (int, float)) \
                and res["delay"] > 0:
            return name, int(res["delay"])
        return name, None

    out = {}
    try:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            for name, delay in ex.map(_one, names):
                if delay:
                    out[name] = delay
    except Exception:
        pass
    return out


def _pick_alive_node():
    """启动后主动收敛节点：触发 AUTO 组测速并确保 SELECT 走在活节点上。

    返回 (当前选中节点名或 None, {节点: 延迟})。链路：
      1) 组级测速（一次拿全组延迟，mihomo 内部并发）；
      2) 失败则逐节点并发兜底，找到活节点后 PUT 切换 SELECT；
      3) 都失败说明订阅节点全死，返回 (None, {})。
    """
    delays = _group_alive_delays("AUTO")
    names = []
    info = _mihomo_api("/proxies", timeout=5)
    if isinstance(info, dict):
        auto = (info.get("proxies") or {}).get("AUTO") or {}
        names = [str(n) for n in (auto.get("all") or [])]
    if delays is None:
        delays = _probe_each_node(names) if names else {}
    if not delays:
        return None, {}
    best = min(delays, key=lambda k: delays[k])
    # SELECT(fallback) 正常情况会自动落在 AUTO 上；若 fallback 卡在死节点，
    # 显式把 SELECT 切到实测最快的节点（对 select/fallback 组都合法）。
    sel = _mihomo_api("/proxies/SELECT", timeout=4)
    if isinstance(sel, dict) and sel.get("now") not in ("AUTO", best):
        _mihomo_api("/proxies/SELECT", "PUT", {"name": best}, timeout=4)
    return best, delays


def ensure_builtin_proxy():
    """确保内置 mihomo 代理可用，返回代理地址或 None。

    幂等设计：目标端口已被监听（本程序残留进程）时校验可用后复用；否则
    编译运行配置并启动 tools/mihomo/mihomo.exe（隐藏窗口）等端口就绪。

    v1.12.0：允许用户接入自己的 Clash/mihomo yaml（设置页选择，路径存
    config.json 的 proxy_yaml 键）；留空用内置配置。

    v1.13.7 修正：mihomo 的 stdout/stderr 落 logs\\mihomo.log（此前丢进
    DEVNULL，配置写错、节点不通全无痕迹）。

    v1.13.8（内置网络代理 v2）——修复"yaml 正常、下载全超时"：
      · 旧链路直接拿订阅 yaml 启动：订阅的 SELECT 组是**手选**类型，永远
        默认第一个节点；第一个节点一死（i/o timeout），所有请求跟着死，
        mihomo 不会自己换。FlClash 能用是因为有人在界面上手动选过活节点。
      · 现在改为：节点从订阅提取 → 编译成程序专用 runtime.yaml（固定
        7897 + AUTO 自动测速 + SELECT 故障切换）→ 启动后主动触发全组
        测速收敛到活节点 → 经代理真实出网 204 校验后才算"可用"。
      · 端口不再从订阅读取：mixed-port 固定 7897，避免与 FlClash(7890)
        互相复用踩踏。
    """
    global _MIHOMO_PROC
    proxy = f"http://127.0.0.1:{MIHOMO_PORT}"
    if _port_listening(MIHOMO_PORT):
        # 已在跑（本程序上次拉起的常驻实例）：校验真的能出网，不能就重新选节点
        if _proxy_http_ok(proxy):
            return proxy
        best, delays = _pick_alive_node()
        _mihomo_log("7897 已监听但 204 校验失败；重新测速%s"
                    % (f"后选中 {best}（{delays.get(best, '?')}ms）" if best else "仍无可用节点"))
        if best and _proxy_http_ok(proxy):
            return proxy
        _mihomo_log("复用失败：代理端口活着但节点不可用（订阅可能已过期）")
        return None
    if not os.path.isfile(MIHOMO_EXE):
        _mihomo_log(f"缺少 mihomo 可执行文件：{MIHOMO_EXE}")
        return None
    runtime, n_nodes = _build_runtime_config()
    cfg_path = runtime or MIHOMO_CONFIG
    if runtime is None:
        if n_nodes == 0:
            _mihomo_log("订阅/内置配置里没有可用节点（proxies 为空），无法启动")
            return None
        cfg_path = MIHOMO_CONFIG
    try:
        os.makedirs(MIHOMO_DIR, exist_ok=True)
        os.makedirs(LOGS_DIR, exist_ok=True)
        handle = open(MIHOMO_LOG, "ab", buffering=0)
        handle.write(("\n=== %s 启动 mihomo（配置 %s，端口 %d）===\n"
                      % (time.strftime("%Y-%m-%d %H:%M:%S"), cfg_path, MIHOMO_PORT)
                      ).encode("utf-8"))
        _MIHOMO_PROC = subprocess.Popen(
            [MIHOMO_EXE, "-d", MIHOMO_DIR, "-f", cfg_path],
            stdin=subprocess.DEVNULL, stdout=handle, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except Exception as e:  # noqa: BLE001
        _mihomo_log(f"启动 mihomo 失败：{e}")
        return None
    # 等待端口就绪（AUTO 组节点首次测速约需数秒）
    for _ in range(40):
        if _port_listening(MIHOMO_PORT):
            break
        if _MIHOMO_PROC.poll() is not None:
            _mihomo_log(f"mihomo 进程已退出（exit={_MIHOMO_PROC.returncode}），"
                        "多为配置语法错误或端口被占用；详见本文件上文输出")
            return None
        time.sleep(0.5)
    else:
        _mihomo_log(f"等待 20 秒后 127.0.0.1:{MIHOMO_PORT} 仍未监听")
        return None
    # 首次收敛：主动测速，让 AUTO/fallback 立刻落在活节点上（不等周期检查）
    best, delays = _pick_alive_node()
    if best:
        _mihomo_log(f"节点测速完成：{len(delays)} 个可用，当前 {best}"
                    f"（{delays[best]}ms）")
    else:
        _mihomo_log("警告：全部节点测速失败 —— 订阅可能已过期，"
                    "请在 FlClash 里更新订阅后重新导出，或在设置页更换代理配置")
    if _proxy_http_ok(proxy):
        return proxy
    _mihomo_log("mihomo 已启动，但经代理出网校验失败（节点全部不可达？）")
    return None


#: 代理地址缓存（进程内）。ensure_builtin_proxy 每次都要探测端口/等 20 秒，
#: 而下载链路每个任务、每次拉字幕都会问一次，必须记住结果。
_PROXY_CACHE = {"checked": False, "proxy": None}
_PROXY_LOCK = threading.Lock()


#: 标准代理环境变量（跨平台通用通道，优先级最高）。
#: Linux / macOS / headless 没有 Windows 注册表，ClashX、ClashMeta、v2rayN、
#: 公司网关、CI 容器都通过这几个变量暴露代理；设了它就是用户的显式意图。
#: ⚠ 曾经只读注册表：换到非 Windows 直接判定「无代理」，且有 https_proxy
#:   显式设置时反而被忽略（2026-10-17 修）。
_PROXY_ENV_VARS = ("HTTPS_PROXY", "https_proxy", "ALL_PROXY", "all_proxy",
                   "HTTP_PROXY", "http_proxy")
#: 代理可用性探测的结果缓存与冷却。``ever`` = 本进程是否曾经探测到过代理 ——
#: 用来区分「这台机器本来就没代理」和「代理刚才掉了」：后者是故障，必须告警。
_PROXY_PROBE = {"at": 0.0, "val": "", "log_miss": False, "ever": False}
_PROXY_PROBE_LOCK = threading.Lock()
_PROXY_PROBE_TTL = 60.0


def _env_proxy_url():
    """读标准代理环境变量，规范化成 `scheme://host:port`；没有返回空串。"""
    for v in _PROXY_ENV_VARS:
        val = (os.environ.get(v) or "").strip().rstrip("/")
        if not val:
            continue
        if "://" not in val:
            val = "http://" + val
        rest = val.split("://", 1)[1]
        # 判断有没有端口：IPv4/v6 都要覆盖 —— "[":1]" 这种裸 v6 地址里本身
        # 含冒号，直接看 ":" in rest 会误判成已带端口，导致漏补 8080。
        host, sep, port = rest.rpartition(":")
        if not (sep and port.isdigit()):
            val += ":8080"
        return val
    return ""


def _registry_proxy_url():
    """Windows 系统代理（Internet 选项）。非 Windows 或未启用返回空串。"""
    if not sys.platform.startswith("win"):
        return ""
    server = ""
    try:
        import winreg
        with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Internet Settings") as k:
            try:
                enable, _ = winreg.QueryValueEx(k, "ProxyEnable")
            except FileNotFoundError:
                return ""
            if not int(enable or 0):
                return ""
            try:
                server, _ = winreg.QueryValueEx(k, "ProxyServer")
            except FileNotFoundError:
                return ""
    except Exception:  # noqa: BLE001
        return ""
    server = str(server or "").strip()
    if not server:
        return ""
    # ProxyServer 可能是 "host:port"，也可能 "http=h:p;https=h:p" / "socks=h:p"
    if "=" in server:
        seg = {}
        for part in server.split(";"):
            if "=" in part:
                kk, vv = part.split("=", 1)
                seg[kk.strip().lower()] = vv.strip()
        server = seg.get("https") or seg.get("http") or seg.get("socks") or ""
    server = server.strip()
    if not server:
        return ""
    if "://" not in server:
        server = "http://" + server
    return server


def _macos_proxy_url():
    """macOS 系统代理：`scutil --proxy`（HTTPS > HTTP > SOCKS）。"""
    if sys.platform != "darwin":
        return ""
    from core.shared.textio import decode_bytes_any
    try:
        cp = run_process(["scutil", "--proxy"], capture_output=True, timeout=4)
        out = decode_bytes_any(cp.stdout or b"")
    except Exception:  # noqa: BLE001
        return ""
    kv = {}
    for ln in out.splitlines():
        if ":" not in ln:
            continue
        k, v = ln.strip().split(":", 1)
        kv[k.strip()] = v.strip()
    for prefix in ("HTTPS", "HTTP", "SOCKS"):
        if kv.get(prefix + "Enable") != "1":
            continue
        host = kv.get(prefix + "Proxy") or ""
        if not host:
            continue
        port = kv.get(prefix + "Port") or ""
        scheme = "socks5" if prefix == "SOCKS" else "http"
        return f"{scheme}://{host}" + (f":{port}" if port else "")
    return ""


def _linux_proxy_url():
    """Linux 桌面代理：GNOME gsettings（无桌面/无 gsettings 返回空串）。"""
    if not sys.platform.startswith("linux"):
        return ""
    from core.shared.textio import decode_bytes_any
    try:
        cp = run_process(["gsettings", "get", "org.gnome.system.proxy", "mode"],
                         capture_output=True, timeout=4)
        out = decode_bytes_any(cp.stdout or b"").strip().strip("'")
        if out and out.lower() != "none":
            for key, scheme in (("https", "http"), ("http", "http"), ("socks", "socks5")):
                c = run_process(["gsettings", "get", f"org.gnome.system.proxy.{key}",
                                 "port"], capture_output=True, timeout=4)
                port = decode_bytes_any(c.stdout or b"").strip()
                h = run_process(["gsettings", "get", f"org.gnome.system.proxy.{key}",
                                 "host"], capture_output=True, timeout=4)
                host = decode_bytes_any(h.stdout or b"").strip().strip("'")
                if host and host not in ("''", '""') and port.isdigit():
                    return f"{scheme}://{host}:{port}"
    except Exception:  # noqa: BLE001
        pass
    return ""


def _proxy_candidates():
    """本机可能的代理地址（按优先级、去重）。不含内置 mihomo。"""
    out = []

    def _add(u):
        u = (u or "").strip().rstrip("/")
        if u and u not in out:
            out.append(u)

    _add(_env_proxy_url())
    if sys.platform.startswith("win"):
        _add(_registry_proxy_url())
    elif sys.platform == "darwin":
        _add(_macos_proxy_url())
    else:
        _add(_linux_proxy_url())
    return out


def _system_proxy_url():
    """当前**实际可用**的本地代理地址；探测不到返回空串（= 交给 yt-dlp 直连）。

    2026-10-17 彻底重写。旧实现只读 Windows 注册表，两个后果：
      ① 换到 macOS / Linux / headless 设备直接判定「无代理」；
      ② 本机 `https_proxy=http://127.0.0.1:1205` 这种显式环境变量设置被忽略，
         反而用了注册表里那个不一定活的代理。
    现在按「标准环境变量 → 系统代理设置」多级收集候选，并发做**真实出网探测**，
    取优先级最高的存活者；全部失败返回空串 —— 在能直连外网的设备上，
    空串正是正确答案（直连即可下载，无需任何代理配置）。
    """
    from concurrent.futures import ThreadPoolExecutor
    import time as _time
    # ⚠ 整个探测过程持锁：此前只在入口置时间戳就放锁，多个下载任务同时首探
    # 会各跑一遍（每个候选最长 5s，纯属重复等待）。
    with _PROXY_PROBE_LOCK:
        now = _time.time()
        if now - _PROXY_PROBE["at"] < _PROXY_PROBE_TTL:
            return _PROXY_PROBE["val"]
        _PROXY_PROBE["at"] = now
        cands = _proxy_candidates()

        def _usable(u):
            scheme = u.split("://", 1)[0].lower() if "://" in u else "http"
            # SOCKS 代理不能让标准库探——urllib 的 ProxyHandler 不认识 socks://，
            # 对纯 SOCKS5 端口必失败。但 yt-dlp 支持 SOCKS5，用户显式设置了
            # socks 代理就是明确意图：**直接采信，不能因"探不到"而丢弃**
            # （2026-10-17 自检发现：否则 ALL_PROXY=socks5://… 会被静默忽略）。
            if scheme.startswith("socks"):
                return True
            return _proxy_http_ok(u, timeout=5.0)

        live = ""
        if cands:
            def _usable(u):
                scheme = u.split("://", 1)[0].lower() if "://" in u else "http"
                # SOCKS 代理不能让标准库探——urllib 的 ProxyHandler 不认识 socks://，
                # 对纯 SOCKS5 端口必失败。但 yt-dlp 支持 SOCKS5，用户显式设置了
                # socks 代理就是明确意图：**直接采信，不能因"探不到"而丢弃**
                # （2026-10-17 自检发现：否则 ALL_PROXY=socks5://… 会被静默忽略）。
                if scheme.startswith("socks"):
                    return True
                # 抖动防护：代理的 TLS 握手实测会在 0.3s~5.9s 之间跳，单次失败
                # 不足以判定"代理不可用"——补一次再下结论（2026-10-17 下载监控
                # 实录：单次探测失败会写出"按直连下载"的误导日志）。
                return _proxy_http_ok(u, timeout=5.0) or _proxy_http_ok(u, timeout=5.0)

            try:
                with ThreadPoolExecutor(max_workers=min(6, len(cands))) as ex:
                    flags = list(ex.map(_usable, cands))
                for u, ok in zip(cands, flags):
                    if ok:
                        live = u
                        break
            except Exception:  # noqa: BLE001
                for u in cands:
                    if _usable(u):
                        live = u
                        break
        miss, gone = False, False
        _PROXY_PROBE["val"] = live
        if live:
            _PROXY_PROBE["ever"] = True
        elif not _PROXY_PROBE["log_miss"]:
            _PROXY_PROBE["log_miss"] = True
            miss = True
            # 曾经可用、现在探不到 = 代理掉线/节点全挂，这跟"这台机器没代理"
            # 是两回事，必须给出不同措辞（前者要用户去看代理客户端）。
            gone = _PROXY_PROBE["ever"]
    if miss and not gone:
        _mihomo_log("[代理] 未检测到可用的本地代理（候选：%s）—— 新任务将按直连下载。"
                    "若目标站点必须经代理，请设置 VT_YTDLP_PROXY=http://host:port"
                    % (", ".join(cands) or "无"))
    elif miss and gone:
        _mihomo_log("[代理] 警告：此前可用的本地代理现在探测不到（候选：%s）—— "
                    "本次失败可能是瞬时抖动，也可能代理已掉线/节点全部不可用。"
                    "新任务会暂按直连下载；若随后下载失败，请检查代理客户端，"
                    "或用 VT_YTDLP_PROXY 显式指定地址"
                    % (", ".join(cands) or "无"))
    return live


def _builtin_proxy_enabled():
    """内置 mihomo 是否启用。**默认停用**（2026-10-16 起优先系统代理）。

    需要恢复旧行为时设环境变量 `VT_USE_BUILTIN_PROXY=1`。
    """
    v = (os.environ.get("VT_USE_BUILTIN_PROXY") or "").strip().lower()
    return v in ("1", "true", "yes", "on")


def ytdlp_proxy_args(refresh=False):
    """给 yt-dlp 的 `--proxy` 参数表；拿不到代理时返回 []（退回直连）。

    为什么下载链路必须带这个：`ensure_builtin_proxy()` 此前只服务于 GitHub
    相关请求，yt-dlp 全程直连 —— 在国内那就是"YouTube 永远连不上"。带上本地
    mihomo 之后，分流仍由 yaml 的 rules 决定（规则没覆盖的域名它自己也走
    直连），所以对 B 站等本来直连的站点没有副作用。

    并发安全：双检锁。此前 N 个任务同时首次取用时，各线程都会看到缓存为空，
    各自去拉起/等待 mihomo（最坏各等 20s 端口就绪）——多任务同加时集体白等。
    """
    #: 显式覆盖（应急/排查）：`VT_YTDLP_PROXY=http://127.0.0.1:7890` 时直接采用，
    #: 不走内置 mihomo —— 内置实例会中途退出或节点全挂（7897 返回 000/502），
    #: 而 FlClash(7890) 往往仍可用；长下载被代理中断时用它快速接续。
    override = (os.environ.get("VT_YTDLP_PROXY") or "").strip()
    if override:
        return ["--proxy", override]
    #: ② 系统代理优先（2026-10-16 用户要求：内置 mihomo 下线，改用电脑既有代理）
    sp = _system_proxy_url()
    if sp:
        return ["--proxy", sp]
    #: ③ 内置 mihomo（默认停用；VT_USE_BUILTIN_PROXY=1 恢复旧行为）
    if not _builtin_proxy_enabled():
        return []
    with _PROXY_LOCK:
        if not refresh and _PROXY_CACHE["checked"]:
            return ["--proxy", _PROXY_CACHE["proxy"]] if _PROXY_CACHE["proxy"] else []
        proxy = None
        try:
            proxy = ensure_builtin_proxy()
        except Exception as e:  # noqa: BLE001
            _mihomo_log(f"ensure_builtin_proxy 异常：{e}")
        _PROXY_CACHE["checked"] = True
        _PROXY_CACHE["proxy"] = proxy
        return ["--proxy", proxy] if proxy else []


# ========== 翻译请求的显式路由（v1.16.2） ==========
#: 翻译端点里「国内可直连」的域名后缀 —— 这些**强制直连**，绝不跟随系统代理。
#: 实测 edge.microsoft.com 直连 0.7s 可用；而一旦跟随系统代理（通常指向本地
#: mihomo），mihomo 没就绪 / 节点不通时它也会跟着失败。
TRANSLATE_DIRECT_SUFFIXES = ("microsoft.com", "bing.com", "msn.com",
                             "microsofttranslator.com", "live.com")


def translate_session_proxies(endpoint):
    """翻译请求该用的 `requests` 代理表（`{}` = 直连）。

    引擎的机翻翻译器都用 `requests.Session()`，默认 `trust_env=True` 会**跟随
    系统代理**；而系统代理通常指向本地 mihomo（Clash / FlClash）。mihomo 没就绪
    或节点不通时，**连直连就能用的微软翻译也一起被带崩** —— 用户侧
    「235/235 segments failed (100%)」正是这个形态（谷歌要代理，微软被系统代理
    拖下水，两个都挂）。

    这里把路由定死，不再依赖系统代理设置：
      · 微软 `edge.microsoft.com` 等国内可达端点 → 直连；
      · 谷歌 `translate.googleapis.com`（境内不可达）→ 本地 mihomo，拿不到就直连
        （总比硬套一个不通的系统代理强）。

    ⚠️ 调用方必须同时设 `session.trust_env = False`：requests 的
    `merge_environment_settings` 会把环境代理 `setdefault` 进 request 级
    proxies，只在 session.proxies 里写 None **覆盖不掉**。
    """
    host = ""
    try:
        from urllib.parse import urlsplit
        host = (urlsplit(str(endpoint or "")).hostname or "").lower()
    except Exception:  # noqa: BLE001
        pass
    if host and any(host == s or host.endswith("." + s)
                    for s in TRANSLATE_DIRECT_SUFFIXES):
        return {}
    proxy = ""
    try:
        args = ytdlp_proxy_args()
        proxy = args[1] if args else ""
    except Exception:  # noqa: BLE001
        proxy = ""
    return {"http": proxy, "https": proxy} if proxy else {}


def proxy_status():
    """给界面用：``(是否可用, 代理地址或空, 一句话说明)``。附当前节点名。

    2026-10-17：原先写死 `_mihomo_api("/proxies/SELECT")` —— 外网代理的组名
    根本不叫 SELECT、控制口也不是内置的 9098，节点名永远取不到；内置 mihomo
    默认停用后，"未安装内置代理组件"更是彻底的误导结论。改为走自动发现，
    且**没有控制口时不出节点名**（避免为显示一个名字触发几秒端口探测、卡界面）。
    """
    args = ytdlp_proxy_args()
    if args:
        now = ""
        if _PROXY_CTL["base"] or (os.environ.get("VT_MIHOMO_API") or "").strip():
            try:
                now = proxy_group_now()
            except Exception:  # noqa: BLE001
                now = ""
        if now:
            return True, args[1], f"代理可用：{args[1]}（当前节点：{now}）"
        return True, args[1], "代理可用：" + args[1]
    return False, "", ("未检测到可用的本地代理，已按直连下载；若目标站点必须经代理，"
                      "请设置 VT_YTDLP_PROXY=http://host:port（详见 logs\\mihomo.log）")


def get_proxy_yaml():
    """用户接入的 Clash/mihomo yaml（多为机场订阅导出）；空 = 内置节点快照。

    v1.13.8 起语义变化：这份文件只用来**提取节点（proxies 段）**，端口与
    分流规则由引擎编译进 runtime.yaml（固定 7897），不再整份直接启动。
    """
    return str(load_config().get("proxy_yaml", "")).strip()


def set_proxy_yaml(path):
    """记住用户自定义代理 yaml 路径（长期固定）；空串 = 恢复内置默认。

    文件必须存在；仅做存在性校验，格式/端口在 ensure_builtin_proxy 时解析
    （解析失败回退默认端口 7897）。
    """
    path = clean_path(str(path or "")).strip()
    if path:
        path = os.path.abspath(path)
        if not os.path.isfile(path):
            raise FileNotFoundError(path)
    cfg = load_config()
    cfg["proxy_yaml"] = path
    save_config(cfg)
    return path


def _proxy_yaml_port(path):
    """从 Clash/mihomo yaml 解析监听端口（mixed-port > port > socks-port）。"""
    try:
        import yaml
        with open(path, encoding="utf-8-sig") as f:
            data = yaml.safe_load(f)
        if isinstance(data, dict):
            for key in ("mixed-port", "port", "socks-port"):
                try:
                    val = int(data.get(key) or 0)
                except (TypeError, ValueError):
                    continue
                if 0 < val < 65536:
                    return val
    except Exception:
        pass
    return None


def _stop_builtin_proxy():
    global _MIHOMO_PROC
    if _MIHOMO_PROC is not None and _MIHOMO_PROC.poll() is None:
        try:
            _MIHOMO_PROC.terminate()
        except OSError:
            pass
    _MIHOMO_PROC = None


atexit.register(_stop_builtin_proxy)
# ========== 代理节点锁定（2026-10-08 初版；2026-10-17 重写：控制口自动发现） ==========
# 背景：YouTube 的 videoplayback 直链在签发时把当时的**出口 IP**写进 URL（ip= 参数）。
# 下载几十分钟的中途一旦换节点，已签发的所有分片 URL 立刻失效，CDN 直接掐连接 ——
# 表现为 `Got error: EOF occurred in violation of protocol (_ssl.c:1007). Retrying`，
# 且重试无效（重试用的还是绑定旧 IP 的那条 URL）。
#
# 2026-10-16 起内置 mihomo 下线、改用系统代理（FlClash 7890），而原实现只认
# 127.0.0.1:9098 一个控制口 → 锁定链路静默失效、日志里一个字都没有。本版改为：
#   ① 控制口四级发现：VT_MIHOMO_API → 内置 9098 → 由系统代理端口推断 → 常见端口兜底；
#   ② 组名不再写死 SELECT，改为从 /connections 的真实链路推断实际出网的策略组；
#   ③ 按链路拓扑逐层钉死（Selector 直接成员含目标节点时一步到位，否则逐层固定）；
#   ④ 下载期间守护线程周期性校正漂移；
#   ⑤ 失败一律写 logs/mihomo.log 并记入 proxy_lock_status()，绝不再静默。
#: 内置 mihomo 的 external-controller（见 tools/mihomo/config.yaml）
#: ⚠ 单一权威定义：勿在文件后半部分再赋值一次 —— 2026-10-12 已因顶层同名
#:   定义互相遮蔽出过事故（代理引导链路整个失效）。需要覆盖时用 VT_MIHOMO_API。
#: 出网策略组名。空串 = 自动探测「实际命中的组」（推荐，FlClash 的组名不是 SELECT）。
PROXY_GROUP = os.environ.get("VT_PROXY_GROUP", "").strip()
#: 节点锁定开关：默认开。设 VT_PROXY_LOCK=0 可退回「由 mihomo 自动切换」的旧行为。
PROXY_LOCK_ENABLED = os.environ.get("VT_PROXY_LOCK", "1").strip().lower() not in ("0", "off", "no", "false")

#: 可切换的策略组类型（会「选」节点/子组的）
_GROUP_TYPES = ("Selector", "Fallback", "URLTest", "LoadBalance", "Relay")
#: 非出网项（既不是节点也不是可切换组），不参与锁定
_NON_GROUP_NAMES = {"GLOBAL", "DIRECT", "REJECT", "REJECT-DROP", "PASS",
                    "COMPATIBLE", "REJECT-DROP"}
_LEAF_EXCLUDE_TYPES = ("Direct", "Reject", "RejectDrop", "Pass", "Compatible",
                       "Dns", "Block")

_PROXY_LOCK_STATE = {"orig": None, "count": 0, "base": "", "group": "",
                     "node": "", "error": "", "egress_ip": "", "fail": 0}
_PROXY_LOCK_MUTEX = threading.Lock()

#: 控制口发现结果缓存（秒级 TTL：FlClash 可能中途启动/关闭）
_PROXY_CTL = {"base": "", "checked": 0.0, "source": "", "hits": []}
_PROXY_CTL_TTL = 60.0
_PROXY_CTL_MUTEX = threading.Lock()

#: 系统代理端口 → 该客户端控制口的常见取值（FlClash / Clash Verge / 内置 mihomo）
_CTL_PORTS_BY_MIXED = {
    7890: (9090, 9091, 9092),   # FlClash / Clash Verge Rev
    7891: (9090,),
    7897: (9098, 9090),         # 本程序内置 mihomo
    7899: (9090,),
}
#: 兜底候选（只在「非显式指定」时才猜）
_CTL_PORTS_FALLBACK = (9090, 9091, 9092, 9097, 9098, 9099, 6170)

#: 漂移守护：间隔与最大纠正次数
_LOCK_GUARD_INTERVAL = 15.0
_LOCK_GUARD_MAX_FIX = 3
_GUARD = {"stop": None, "thread": None}


#: 端口→PID 反查缓存（5s TTL）：进程监听关系短期内稳定，避免每个候选
#: 控制口都重跑一次 netstat/lsof。
_PID_CACHE = {}


def _ctl_secret():
    """控制口密钥（FlClash/Clash Verge 的 external-controller secret）。"""
    return (os.environ.get("VT_MIHOMO_SECRET") or "").strip()


def _local_listen_ports():
    """本机全部 LISTENING TCP 端口（跨平台；拿不到返回空集）。

    为什么绕这么一圈：FlClash / Clash Verge 的外部控制口常是**随机端口**，
    任何写死的端口表都会漏。直接从系统要监听列表最稳：
      · Windows ``netstat -ano -p tcp``
      · Linux   ``ss -tln``（普通用户看不到进程名，但端口本身就够了）
      · macOS   ``lsof -iTCP -sTCP:LISTEN -P -n``
    混进来的数据库/开发服务端口随后会被 ``/version`` 探测自动过滤掉。
    """
    from core.shared.textio import decode_bytes_any
    if sys.platform.startswith("win"):
        cmd = ["netstat", "-ano", "-p", "tcp"]
    elif sys.platform == "darwin":
        cmd = ["lsof", "-iTCP", "-sTCP:LISTEN", "-P", "-n"]
    else:
        cmd = ["ss", "-tln"]
    try:
        cp = run_process(cmd, capture_output=True, timeout=8)
        out = decode_bytes_any(cp.stdout or b"")
    except Exception:  # noqa: BLE001
        return set()
    ports = set()
    for ln in out.splitlines():
        # ⚠ 三个平台的关键字都在行内，但列位置不同；且 Windows 的 netstat 默认
        #   会列出**全部** TCP 连接（ESTABLISHED 等），不按 LISTEN 过滤就会把
        #   几百个临时端口当成候选控制口。
        if "LISTEN" not in ln.upper():
            continue
        for cell in ln.split():
            if ":" not in cell:
                continue
            tail = cell.rsplit(":", 1)[-1].strip("[]()")
            if tail.isdigit():
                p = int(tail)
                if 1024 < p < 65536:
                    ports.add(p)
    return ports


def _port_pid(port):
    """监听 `port` 的进程 PID（拿不到返回 0；跨平台，尽力而为）。

    用途：本机可能有多个 Clash 兼容内核（IDE 自带、FlClash、Verge…），只有
    **与当前代理端口同一进程**的控制口，切它才对正在下载的连接生效。
    Windows ``netstat -ano`` 必有 PID；macOS ``lsof`` 有；Linux ``ss -tlnp``
    普通用户看不到 pid —— 拿不到就返回 0，由调用方走其它判据。
    """
    from core.shared.textio import decode_bytes_any
    port = int(port or 0)
    if port <= 0:
        return 0
    key, now = str(port), time.time()
    hit = _PID_CACHE.get(key)
    if hit and now - hit[1] < 5.0:
        return hit[0]
    pid = 0
    try:
        if sys.platform.startswith("win"):
            cp = run_process(["netstat", "-ano", "-p", "tcp"],
                             capture_output=True, timeout=8)
            out = decode_bytes_any(cp.stdout or b"")
            tag = ":%d " % port
            for ln in out.splitlines():
                if "LISTEN" not in ln.upper() or tag not in ln:
                    continue
                cells = ln.split()
                if cells and cells[-1].isdigit():
                    pid = int(cells[-1])
                    break
        elif sys.platform == "darwin":
            cp = run_process(["lsof", "-tiTCP:%d" % port, "-sTCP:LISTEN"],
                             capture_output=True, timeout=6)
            out = decode_bytes_any(cp.stdout or b"").split()
            if out and out[0].isdigit():
                pid = int(out[0])
        else:
            cp = run_process(["ss", "-tlnp"], capture_output=True, timeout=6)
            out = decode_bytes_any(cp.stdout or b"")
            for ln in out.splitlines():
                if ":%d " % port not in ln:
                    continue
                i = ln.find("pid=")
                if i >= 0:
                    digits = ""
                    for ch in ln[i + 4:]:
                        if ch.isdigit():
                            digits += ch
                        else:
                            break
                    if digits:
                        pid = int(digits)
                    break
    except Exception:  # noqa: BLE001
        pid = 0
    _PID_CACHE[key] = (pid, now)
    return pid


def _ctl_request(base, method, path, payload=None, timeout=10):
    """调控制口的**绝对路径**（/version、/proxies、/connections …）；失败抛异常。

    带 ``Authorization: Bearer <secret>``（``VT_MIHOMO_SECRET``）——FlClash /
    Clash Verge 默认不开 secret，但开了之后不带这个头的请求一律 401。
    """
    import urllib.error
    import urllib.request
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Content-Type": "application/json"}
    secret = _ctl_secret()
    if secret:
        headers["Authorization"] = "Bearer " + secret
    req = urllib.request.Request(
        base.rstrip("/") + path, method=method, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise RuntimeError(
                "控制口需要密钥（HTTP %d）。请在代理客户端的「外部控制 / "
                "External Controller」里查看 Secret，并设置 VT_MIHOMO_SECRET" % e.code)
        raise
    # 切换节点(PUT)返回 204 空体，别 json.loads
    return json.loads(body) if body.strip() else None


def _ctl_alive(base, timeout=1.5):
    """控制口存活探测：``/version`` 形状正确**且** ``/proxies`` 是 mihomo 形状。

    两步都得过——只查 /version 会把任何返回含 "version" 字段的服务误判成
    控制口（2026-10-17 实测命中过 4096 上的无关服务，随后所有锁定调用全失败）。
    """
    try:
        d = _ctl_request(base, "GET", "/version", timeout=timeout)
        if not (isinstance(d, dict) and ("version" in d or "meta" in d)):
            return False
        p = _ctl_request(base, "GET", "/proxies", timeout=timeout)
        return (isinstance(p, dict) and isinstance(p.get("proxies"), dict)
                and bool(p.get("proxies")))
    except Exception as e:  # noqa: BLE001
        return "需要密钥" in str(e)


def _ctl_candidates(explicit=""):
    """候选控制口列表（有序）。显式指定时只认它，不做任何猜测。

    2026-10-17 通用化（此前只认 FlClash/Verge 的固定端口组合，换客户端或
    控制口是随机端口时就扫不到）：
      ① ``MIHOMO_API``——内置 mihomo（``VT_USE_BUILTIN_PROXY=1`` 场景）；
      ② ``VT_MIHOMO_API``——显式指定，应急通道；
      ③ config.json 记忆——上次成功过的地址，重启免扫；
      ④ **本机监听端口全枚举**（``_local_listen_ports``）——随机端口控制口的
         唯一可靠发现途径，混入的无关端口由 /version 探测过滤；
      ⑤ 系统代理端口 → 常见控制口映射 + 兜底端口表。
    """
    if explicit:
        return [explicit.rstrip("/")]
    out = []

    def _add(b):
        b = (b or "").strip().rstrip("/")
        if b and b not in out:
            out.append(b)

    _add(MIHOMO_API)
    try:
        _add(load_config().get("mihomo_controller", ""))
    except Exception:  # noqa: BLE001
        pass
    try:
        sp = _system_proxy_url()
        mix_port = int(sp.rsplit(":", 1)[-1]) if sp else 0
    except (ValueError, AttributeError):
        mix_port = 0
    for p in _CTL_PORTS_BY_MIXED.get(mix_port, ()):
        _add("http://127.0.0.1:%d" % p)
    for p in sorted(_local_listen_ports()):
        _add("http://127.0.0.1:%d" % p)
    for p in _CTL_PORTS_FALLBACK:
        _add("http://127.0.0.1:%d" % p)
    # 上限 40：监听端口枚举可能带出几十个无关服务，全部探测要好几秒
    return out[:40]


def _probe_ctl(explicit=""):
    """并发探测候选控制口，返回 ``(base, 来源说明, 全部命中列表)``。

    ⚠ 命中多个控制口时**必须挑对**：控制口只对自己的内核有效。若本机同时
    跑了 FlClash 和 IDE 自带内核，锁了后者对前者正在处理的下载毫无帮助
    （甚至会因为反复切换另一个内核的节点而显得"锁定生效了但下载照旧断"）。
    同域判据：命中端口与当前系统代理端口有已知映射关系的排最前。
    """
    cands = _ctl_candidates(explicit)
    if not cands:
        return "", "", []
    if explicit:
        b = cands[0]
        return (b, "VT_MIHOMO_API", [b]) if _ctl_alive(b) else ("", "", [])
    if len(cands) == 1:
        return (cands[0], "唯一候选", [cands[0]]) if _ctl_alive(cands[0]) \
            else ("", "", [])
    hits = []
    try:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=min(8, len(cands))) as ex:
            flags = list(ex.map(_ctl_alive, cands))
        hits = [b for b, ok in zip(cands, flags) if ok]
    except Exception:  # noqa: BLE001
        for b in cands:
            try:
                if _ctl_alive(b):
                    hits.append(b)
            except Exception:  # noqa: BLE001
                continue
    if not hits:
        return "", "", []
    try:
        sp = _system_proxy_url()
        mp = int(sp.rsplit(":", 1)[-1]) if sp else 0
    except (ValueError, AttributeError):
        mp = 0
    known = _CTL_PORTS_BY_MIXED.get(mp, ())
    proxy_pid = _port_pid(mp) if mp else 0

    def _rank(b):
        try:
            p = int(b.rsplit(":", 1)[-1])
        except ValueError:
            return 99
        if p in known:
            return known.index(p)          # 已知映射：同域概率最高
        if proxy_pid and _port_pid(p) == proxy_pid:
            return 50                        # 同进程监听 → 几乎必然同一内核
        return 99

    hits.sort(key=_rank)
    src = ("同域代理内核" if _rank(hits[0]) < 99 else "自动发现")
    return hits[0], src, hits


def proxy_ctl_base(refresh=False):
    """当前可用的控制口基址（如 http://127.0.0.1:9090）；没有返回空串。

    结果缓存 ``_PROXY_CTL_TTL`` 秒。多任务并发时不会反复扫端口。
    全部命中列表见 ``_PROXY_CTL["hits"]``（供日志提示用户手动指定）。
    """
    explicit = (os.environ.get("VT_MIHOMO_API") or "").strip()
    with _PROXY_CTL_MUTEX:
        now = time.time()
        if (not refresh and _PROXY_CTL["base"]
                and now - _PROXY_CTL["checked"] < _PROXY_CTL_TTL):
            return _PROXY_CTL["base"]
        base, source, hits = _probe_ctl(explicit)
        _PROXY_CTL.update({"base": base, "checked": now,
                           "source": source, "hits": hits})
    # 持久化到 config.json：让 `_ctl_candidates` 的「config 记忆」分支真正有内容，
    # 重启后不必再扫一遍本机监听端口。只写变化时，且失败静默（不影响主流程）。
    if base:
        try:
            cfg = load_config()
            if str(cfg.get("mihomo_controller", "") or "") != base:
                cfg["mihomo_controller"] = base
                save_config(cfg)
        except Exception:  # noqa: BLE001
            pass
    return base


def _mihomo_proxy_api(method, path, payload=None, timeout=10, base=None):
    """调 mihomo 的 RESTful API（path 相对 `/proxies`）；失败抛异常。

    ⚠️ 与上面的 `_mihomo_api(path, ...)` 是**两个函数**，勿再合并/重名：
    2026-10-12 修复前两者同名，后定义的这本把前一本整个遮蔽掉——
    代理引导链路（`_pick_alive_node` → `ensure_builtin_proxy`）按
    `_mihomo_api("/proxies", ...)` 全路径风格调用，撞上这本的
    `(method, path, ...)` 签名直接 TypeError，`ensure_builtin_proxy`
    异常中断 → `ytdlp_proxy_args()` 拿不到代理 → yt-dlp 直连 →
    YouTube 提取 180s 超时 ×4 →「检测画质」永远失败（日志见
    logs\\mihomo.log 的 "missing 1 required positional argument"）。

    区别约定：
      · `_mihomo_api(path, ...)`      —— path 为**完整路径**（调用方自行
        quote），只服务内置 mihomo，失败返回 None；
      · `_mihomo_proxy_api(method, path, ...)` —— path 为 `/proxies/` **之后**
        的一段（函数内统一 quote；空串 = 列表 `/proxies`），可指定 `base`
        （默认自动发现的控制口），失败抛异常；服务节点锁定/测速。

    ⚠️ safe 必须保留 URL 结构字符：整体 quote 会把 `?`/`&`/`=` 也编码掉，
       导致 `/proxies/<节点>/delay?url=...` 这类带查询串的路径失效。
    """
    from urllib.parse import quote
    b = base or proxy_ctl_base()
    if not b:
        raise RuntimeError("没有可用的代理控制口")
    path = "/proxies" + ("/" + quote(path, safe="/?=&:%~") if path else "")
    return _ctl_request(b, method, path, payload, timeout)


def _group_members(table, group):
    return [str(n) for n in ((table.get(group) or {}).get("all") or [])]


def _is_group_name(table, name):
    if not name or name in _NON_GROUP_NAMES:
        return False
    return (table.get(name) or {}).get("type") in _GROUP_TYPES


def _is_leaf_name(table, name):
    if not name or name in _NON_GROUP_NAMES:
        return False
    p = table.get(name) or {}
    return bool(p) and p.get("type") not in _GROUP_TYPES \
        and p.get("type") not in _LEAF_EXCLUDE_TYPES


def _resolve_leaf(table, name, depth=0):
    """把可能是组名的选中值递归解析到具体节点；解析不到返回空串。"""
    if depth > 6 or not name:
        return ""
    p = table.get(name) or {}
    if not p:
        return ""
    if p.get("type") in _GROUP_TYPES:
        return _resolve_leaf(table, str(p.get("now") or ""), depth + 1)
    if p.get("type") in _LEAF_EXCLUDE_TYPES:
        return ""
    return name


def _find_active_group(base=""):
    """推断「实际出网的那个策略组」。

    返回 ``{"group","now","chain","table"}``；失败返回空结构。
    ``chain`` 是从内到外的真实链路（[节点, 子组, …, 外层组]），来自
    ``/connections`` 最近一条连接——比猜组名可靠得多（FlClash 的组名
    是「节点选择」「自动选择」，根本不叫 SELECT）。
    """
    empty = {"group": "", "now": "", "chain": [], "table": {}}
    base = base or proxy_ctl_base()
    if not base:
        return empty
    try:
        raw = _mihomo_proxy_api("GET", "", timeout=6, base=base) or {}
    except Exception as e:  # noqa: BLE001
        # 密钥类异常必须透出：吞掉它会报成「没找到可切换的策略组」，
        # 把"控制口要 secret"误导成"订阅里没有组"（2026-10-17 实测踩中）。
        if "需要密钥" in str(e):
            raise
        return empty
    table = raw.get("proxies") if isinstance(raw, dict) else None
    if not isinstance(table, dict) or not table:
        return empty

    # ① 最准：真实连接链（chains 从内到外）
    try:
        cd = _ctl_request(base, "GET", "/connections", timeout=4) or {}
        for c in reversed((cd.get("connections") or [])[-40:]):
            chain = [str(x) for x in (c.get("chains") or [])]
            groups = [n for n in chain if _is_group_name(table, n)]
            if groups:
                outer = groups[-1]
                return {"group": outer,
                        "now": str((table.get(outer) or {}).get("now") or ""),
                        "chain": chain, "table": table}
    except Exception:  # noqa: BLE001
        pass

    # ② 显式指定的组名
    if PROXY_GROUP and _is_group_name(table, PROXY_GROUP):
        return {"group": PROXY_GROUP,
                "now": str((table.get(PROXY_GROUP) or {}).get("now") or ""),
                "chain": [], "table": table}

    # ③ 兜底：挑一个 Selector（名字像出口组的优先）
    sels = [n for n in table
            if _is_group_name(table, n) and (table[n].get("type") == "Selector")]

    def _rank(n):
        low = n.lower()
        for i, kw in enumerate(("select", "选择", "proxy", "代理", "节点", "outbound")):
            if kw in low:
                return i
        return 99

    if sels:
        sels.sort(key=_rank)
        g = sels[0]
        return {"group": g,
                "now": str((table.get(g) or {}).get("now") or ""),
                "chain": [], "table": table}
    return empty


def _current_exit_leaf(base):
    """从 /connections 取最近一条连接的出口节点名（用于漂移检测）。"""
    try:
        cd = _ctl_request(base, "GET", "/connections", timeout=4) or {}
        for c in reversed((cd.get("connections") or [])[-40:]):
            ch = [str(x) for x in (c.get("chains") or [])]
            if ch:
                return ch[0]
    except Exception:  # noqa: BLE001
        pass
    return ""


def proxy_group_now(group=None):
    """策略组当前选中的节点名；拿不到返回空串。"""
    g = group or PROXY_GROUP
    if not g:
        g = _find_active_group().get("group") or ""
    if not g:
        return ""
    try:
        return str((_mihomo_proxy_api("GET", g, timeout=6) or {}).get("now") or "")
    except Exception:  # noqa: BLE001
        return ""


def proxy_node_delays(names, url="https://www.youtube.com/", timeout=6000, base=None):
    """实测各节点到 `url` 的延迟（毫秒）；不可达的节点不出现在结果里。"""
    from urllib.parse import quote
    out = {}
    for name in names:
        try:
            d = _mihomo_proxy_api("GET", "%s/delay?url=%s&timeout=%d"
                                  % (name, quote(url, safe=""), timeout),
                                  timeout=12, base=base)
            delay = d.get("delay") if isinstance(d, dict) else None
            if delay and delay > 0:
                out[name] = int(delay)
        except Exception:  # noqa: BLE001
            continue
    return out


def _pick_node_via_ctl(base, table, group=""):
    """在控制口侧测速，挑延迟最低的**具体节点**（优先只在当前组内挑）。"""
    members = [n for n in _group_members(table, group) if _is_leaf_name(table, n)]
    if not members:
        members = [n for n in table if _is_leaf_name(table, n)]
    if not members:
        return ""
    delays = proxy_node_delays(members[:16], base=base)
    if not delays:
        return ""
    return min(delays.items(), key=lambda kv: kv[1])[0]


def pick_best_proxy_node(group=None, url="https://www.youtube.com/"):
    """挑出延迟最低的可用节点；测不到返回空串（表示维持现状）。"""
    base = proxy_ctl_base()
    if not base:
        return ""
    try:
        info = _find_active_group(base) if not group else {
            "group": group,
            "now": "",
            "table": (_mihomo_proxy_api("GET", "", timeout=8, base=base) or {}).get("proxies") or {},
        }
    except Exception:  # noqa: BLE001
        return ""
    table = info.get("table") or {}
    if not table:
        return ""
    members = [m for m in _group_members(table, info.get("group") or "") if _is_leaf_name(table, m)]
    if not members:
        members = [m for m in table if _is_leaf_name(table, m)]
    if not members:
        return ""
    delays = proxy_node_delays(members[:12], url=url, base=base)
    if not delays:
        return ""
    return min(delays.items(), key=lambda kv: kv[1])[0]


def _egress_ip():
    """经当前代理取出口 IP（用于判断「是不是换了节点」）；失败返回空串。

    ⚠ timeout 压到 2.5s：本函数会被 ``proxy_note_eof`` 在下载行循环里同步调用，
    4s×3 个候选最坏要 12s —— 那会连下载日志/进度一起卡住。
    国内不可达这些站点时快速失败走空，调用方有对应的文案分支。
    """
    try:
        args = ytdlp_proxy_args()
        proxy = args[1] if args else ""
    except Exception:  # noqa: BLE001
        proxy = ""
    if not proxy:
        return ""
    import urllib.request
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
    opener.addheaders = [("User-Agent", "curl/8")]
    for url in ("https://api.ipify.org", "https://ifconfig.me/ip",
                "https://ipinfo.io/ip"):
        try:
            with opener.open(url, timeout=2.5) as r:
                ip = r.read(64).decode("utf-8", "replace").strip()
            if ip and len(ip) <= 45 and " " not in ip:
                return ip
        except Exception:  # noqa: BLE001
            continue
    return ""


def proxy_egress_ip():
    """对外暴露的出口 IP 探测（诊断用）。"""
    return _egress_ip()


def _pin_chain(base, table, chain, leaf):
    """按真实链路逐层钉死出口。返回 (被切的组名, 是否成功)。

    拓扑现实（FlClash 默认）：``节点选择(Selector) → 自动选择(URLTest) → 节点``。
    直接对外层 Selector PUT 具体节点会 400（它不是外层组的直接成员），所以：
      ① 若某层 Selector 的**直接成员**含该节点 → 一步钉死（最稳）；
      ② 否则从外向内逐层把 Selector 钉到链路下一环，最后再钉内层 Selector。
    """
    if not chain:
        return "", False
    # ① 一步钉死：最外层的、直接成员含 leaf 的 Selector
    for g in reversed(chain):
        if not _is_group_name(table, g):
            continue
        if (table.get(g) or {}).get("type") != "Selector":
            continue
        if leaf in _group_members(table, g):
            try:
                _mihomo_proxy_api("PUT", g, {"name": leaf}, base=base, timeout=6)
                return g, True
            except Exception:  # noqa: BLE001
                continue
    # ② 逐层固定（阻止 fallback / url-test 换子组）
    pinned_group, ok = "", False
    for i in range(len(chain) - 1, 0, -1):
        g, want = chain[i], chain[i - 1]
        if (table.get(g) or {}).get("type") != "Selector":
            continue
        if want not in _group_members(table, g):
            continue
        try:
            _mihomo_proxy_api("PUT", g, {"name": want}, base=base, timeout=6)
            pinned_group, ok = g, True
        except Exception:  # noqa: BLE001
            continue
    # ③ 内层若是 Selector，再把它钉到 leaf
    for g in chain:
        if (table.get(g) or {}).get("type") != "Selector":
            continue
        if leaf in _group_members(table, g):
            try:
                _mihomo_proxy_api("PUT", g, {"name": leaf}, base=base, timeout=6)
                return g, True
            except Exception:  # noqa: BLE001
                continue
    return pinned_group, ok


def _lock_fail(reason):
    """记录锁定失败原因：写日志 + 存进状态，供界面/CLI 展示。"""
    with _PROXY_LOCK_MUTEX:
        _PROXY_LOCK_STATE["error"] = reason
    _mihomo_log("[代理锁定] 未生效：" + reason)


def _lock_once():
    """首个任务时真正执行锁定。返回锁定的节点名（失败为空串）。"""
    base = proxy_ctl_base(refresh=True)
    if not base:
        n = len(_ctl_candidates(""))
        _lock_fail("找不到可用的代理控制口（已试 %d 个候选）。下载期间无法固定出口"
                   "节点，代理中途切换会让已签发的分片 URL 全部失效（表现为 "
                   "EOF/_ssl.c:1007）。若所用客户端支持外部控制（Clash / FlClash / "
                   "Clash Verge 的「外部控制 / External Controller」），开启后设 "
                   "VT_MIHOMO_API=http://127.0.0.1:<端口> 即可启用；"
                   "若设置了 Secret，再加 VT_MIHOMO_SECRET。没有控制口也能正常下载，"
                   "只是失去防漂移保护" % n)
        return ""
    info = _find_active_group(base)
    table, group, now = info.get("table") or {}, info.get("group") or "", info.get("now") or ""
    if not group:
        _lock_fail("控制口 %s 可用，但没找到可切换的策略组" % base)
        return ""
    chain = list(info.get("chain") or [])
    leaf = _resolve_leaf(table, now)
    if not leaf:
        leaf = _pick_node_via_ctl(base, table, group)
        if not leaf:
            _lock_fail("策略组 %s 内没有可用节点（订阅可能已过期）" % group)
            return ""
        chain = [leaf] + [g for g in chain if _is_group_name(table, g)]
        if not chain[1:]:
            chain = [leaf, group]
    # 当前节点不通就换最快的（此时还没提取，换 IP 无代价）
    elif not _proxy_http_ok(_proxy_url_for_probe()):
        better = _pick_node_via_ctl(base, table, group)
        if better and better != leaf:
            _mihomo_log("[代理锁定] 当前节点 %s 不通，改用 %s" % (leaf, better))
            leaf = better
            chain = [leaf] + [g for g in chain[1:]] if chain else [leaf, group]
    if not chain or chain[0] != leaf:
        chain = [leaf] + [g for g in chain if _is_group_name(table, g)]
        if not chain[1:]:
            chain = [leaf, group]
    try:
        pinned, ok = _pin_chain(base, table, chain, leaf)
    except Exception as e:  # noqa: BLE001
        _lock_fail("切换节点失败：%s" % e)
        return ""
    if not ok:
        _lock_fail("组 %s 的拓扑不支持手动钉死（成员里没有该节点的直接入口），"
                   "请在客户端里手动固定节点" % group)
        return ""
    _PROXY_LOCK_STATE.update({
        "base": base, "group": pinned or group, "node": leaf,
        "orig": (pinned or group, now), "fail": 0, "error": "",
        "egress_ip": _egress_ip(),
    })
    _start_guard()
    hits = list(_PROXY_CTL.get("hits") or [])
    if len(hits) > 1:
        _mihomo_log("[代理锁定] 本机有 %d 个控制口 %s，已按同域优先选用 %s。"
                    "若下载仍频繁断流，说明锁定的内核与实际代理不是同一个，"
                    "请用 VT_MIHOMO_API 指定代理所属的那个"
                    % (len(hits), hits, base))
    _mihomo_log("[代理锁定] 控制口 %s（%s）｜组 %s｜节点 %s%s"
                % (base, _PROXY_CTL.get("source") or "", pinned or group, leaf,
                   "" if leaf == now else "（已从 %s 切换）" % (now or "?")))
    return leaf


def _proxy_url_for_probe():
    try:
        args = ytdlp_proxy_args()
        return args[1] if args else ""
    except Exception:  # noqa: BLE001
        return ""


def _guard_loop(stop):
    """下载期间周期性校正漂移。

    为什么要守：fallback / url-test 组的健康检查会在节点抖动时**自动漂移**，
    而 videoplayback 直链绑定签发时的出口 IP —— 漂一次，已下发的分片全废。
    """
    fixes = 0
    while not stop.wait(_LOCK_GUARD_INTERVAL):
        with _PROXY_LOCK_MUTEX:
            if _PROXY_LOCK_STATE["count"] <= 0:
                return
            base = _PROXY_LOCK_STATE.get("base") or ""
            group = _PROXY_LOCK_STATE.get("group") or ""
            node = _PROXY_LOCK_STATE.get("node") or ""
        if not (base and group and node):
            return
        cur = _current_exit_leaf(base)
        if not cur:
            # 空闲期没有活动连接 → 退回看组的 now
            try:
                cur = str((_mihomo_proxy_api("GET", group, timeout=5, base=base)
                           or {}).get("now") or "")
            except Exception:  # noqa: BLE001
                continue
            if cur and _is_group_name(
                    (_mihomo_proxy_api("GET", "", timeout=5, base=base) or {}).get("proxies") or {},
                    cur):
                continue  # 组内仍是子组名，无法判断出口，跳过本轮
        if not cur or cur == node:
            continue
        fixes += 1
        try:
            _mihomo_proxy_api("PUT", group, {"name": node}, timeout=5, base=base)
            _mihomo_log("[代理锁定] 出口漂移到 %s，已切回 %s（第 %d 次）"
                        % (cur, node, fixes))
        except Exception as e:  # noqa: BLE001
            _mihomo_log("[代理锁定] 切回 %s 失败：%s" % (node, e))
        if fixes >= _LOCK_GUARD_MAX_FIX:
            _mihomo_log("[代理锁定] 连续 %d 次漂移，放弃守护（节点可能已不可用）" % fixes)
            return


def _start_guard():
    stop = threading.Event()
    _GUARD["stop"] = stop
    t = threading.Thread(target=_guard_loop, args=(stop,), daemon=True,
                         name="proxy-lock-guard")
    _GUARD["thread"] = t
    t.start()


def proxy_lock_acquire():
    """下载任务开始时调用：把实际出网的策略组钉死到一个具体节点。

    为什么要钉：YouTube 的 videoplayback 直链在签发时会**绑定当时的出口 IP**，
    而 mihomo 的 AUTO/Fallback 组会在中途换节点（url-test 每 300s 重测、
    fallback 遇故障即切）。一换 IP，已签发的所有分片 URL 全部失效 —— 表现为
    「Got error: EOF occurred in violation of protocol (_ssl.c:1007). Retrying」，
    且重试多少次都没用（重试用的还是那条绑定旧 IP 的 URL）。

    多任务并行时用引用计数：只有第一个任务真正切换，最后一个任务结束时恢复。
    返回锁定的节点名；未锁定返回空串，原因见 ``proxy_lock_status()["error"]``。
    """
    if not PROXY_LOCK_ENABLED:
        with _PROXY_LOCK_MUTEX:
            _PROXY_LOCK_STATE["error"] = "已关闭（VT_PROXY_LOCK=0）"
        return ""
    with _PROXY_LOCK_MUTEX:
        _PROXY_LOCK_STATE["count"] += 1
        if _PROXY_LOCK_STATE["count"] > 1:
            return _PROXY_LOCK_STATE.get("node") or ""
    try:
        return _lock_once()
    except Exception as e:  # noqa: BLE001
        _lock_fail("锁定过程异常：%s" % e)
        return ""


def proxy_lock_release():
    """下载任务结束时调用：引用计数归零后把策略组恢复成原样。"""
    if not PROXY_LOCK_ENABLED:
        return
    with _PROXY_LOCK_MUTEX:
        if _PROXY_LOCK_STATE["count"] > 0:
            _PROXY_LOCK_STATE["count"] -= 1
        if _PROXY_LOCK_STATE["count"] > 0:
            return
        base = _PROXY_LOCK_STATE.get("base") or ""
        orig = _PROXY_LOCK_STATE.get("orig")
        stop = _GUARD.get("stop")
        _GUARD["stop"] = None
        _PROXY_LOCK_STATE.update({"base": "", "group": "", "node": "",
                                  "orig": None, "egress_ip": "", "fail": 0})
    if stop is not None:
        try:
            stop.set()
        except Exception:  # noqa: BLE001
            pass
    if not (base and orig):
        return
    g, now = orig
    if not g or not now:
        return
    try:
        _mihomo_proxy_api("PUT", g, {"name": now}, timeout=5, base=base)
    except Exception:  # noqa: BLE001
        pass


def proxy_lock_status():
    """给界面 / CLI / 日志用：一次说清「锁没锁、锁在哪、为什么没锁」。

    ``proxy`` 是当前实际使用的本地代理地址（哪个通道发现的，见
    ``proxy`` 值本身）；``secret_needed`` 表示控制口存在但要密钥。
    换设备排查时这个 dict 就是全部答案。
    """
    with _PROXY_LOCK_MUTEX:
        s = dict(_PROXY_LOCK_STATE)
    proxy = ""
    try:
        args = ytdlp_proxy_args()
        proxy = args[1] if args else ""
    except Exception:  # noqa: BLE001
        proxy = ""
    return {
        "enabled": PROXY_LOCK_ENABLED,
        "locked": bool(s.get("node")),
        "node": s.get("node") or "",
        "group": s.get("group") or "",
        "controller": s.get("base") or "",
        "egress_ip": s.get("egress_ip") or "",
        "active_tasks": s.get("count", 0),
        "proxy": proxy,
        "secret_needed": "需要密钥" in (s.get("error") or ""),
        "ctl_hits": list(_PROXY_CTL.get("hits") or []),
        "ctl_source": _PROXY_CTL.get("source") or "",
        "error": s.get("error") or "",
    }


def proxy_note_eof(detail=""):
    """下载输出出现 TLS EOF 时调用：判断是不是出口 IP 变了，写日志并返回说明。

    返回的文案供界面直接展示——这是用户唯一能看懂「为什么一直重试都失败」的地方。
    """
    with _PROXY_LOCK_MUTEX:
        old = _PROXY_LOCK_STATE.get("egress_ip") or ""
        node = _PROXY_LOCK_STATE.get("node") or ""
        err = _PROXY_LOCK_STATE.get("error") or ""
    new = _egress_ip()
    if node and old and new and old != new:
        msg = ("检测到 TLS 断连（EOF），出口 IP 已从 %s 变为 %s（锁定节点 %s 失效）"
               "—— 旧分片链接全部作废，正在重新提取新链接" % (old, new, node))
    elif node:
        msg = ("检测到 TLS 断连（EOF），出口节点仍是 %s；多为线路抖动，"
               "正在重新提取链接后重试" % node)
    else:
        msg = ("检测到 TLS 断连（EOF），且出口节点**未锁定**（%s）。直链在签发时"
               "绑定了当时的出口 IP，代理一换节点，旧链接就全部作废、重试多少次都"
               "无效。请在代理客户端里手动固定节点，或开启外部控制后设置 "
               "VT_MIHOMO_API（有 Secret 时再加 VT_MIHOMO_SECRET）。"
               "现已改为重新提取链接后重试" % (err or "原因未知"))
    _mihomo_log("[代理锁定] " + msg + (("；原文：" + detail) if detail else ""))
    return msg


__all__ = [
    "MIHOMO_DIR",
    "MIHOMO_EXE",
    "MIHOMO_CONFIG",
    "MIHOMO_RUNTIME_CONFIG",
    "MIHOMO_PROXY",
    "MIHOMO_PORT",
    "MIHOMO_CONTROLLER",
    "MIHOMO_API",
    "MIHOMO_TEST_URL",
    "MIHOMO_LOG",
    "PROXY_GROUP",
    "PROXY_LOCK_ENABLED",
    "TRANSLATE_DIRECT_SUFFIXES",
    "ensure_builtin_proxy",
    "ytdlp_proxy_args",
    "translate_session_proxies",
    "proxy_status",
    "get_proxy_yaml",
    "set_proxy_yaml",
    "proxy_group_now",
    "proxy_node_delays",
    "pick_best_proxy_node",
    "proxy_ctl_base",
    "proxy_egress_ip",
    "proxy_lock_acquire",
    "proxy_lock_release",
    "proxy_lock_status",
    "proxy_note_eof",
]
