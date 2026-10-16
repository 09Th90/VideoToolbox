# -*- coding: utf-8 -*-
# @version 2.3.1
"""内置代理（mihomo/ClashMeta）：引导 / 选节点 / 代理参数 / 节点锁定（v2.3.1 拆分工程 · 自 video_toolbox.py 原样搬入）。

本模块是 src/core/shared/ 的组成部分；域间依赖规则见 core/__init__.py。
"""

from core.shared.paths import LOGS_DIR, TOOLS_DIR, clean_path

import atexit
import json
import os
import subprocess
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
MIHOMO_API = "http://" + MIHOMO_CONTROLLER
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
    """经代理真实出网一次（gstatic 204 探测），确认"端口活着且节点可用"。"""
    try:
        import urllib.parse
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
        opener.addheaders = [("User-Agent", "Mozilla/5.0")]
        with opener.open(MIHOMO_TEST_URL, timeout=timeout) as r:
            return getattr(r, "status", 200) == 204
    except Exception:
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


def ytdlp_proxy_args(refresh=False):
    """给 yt-dlp 的 `--proxy` 参数表；拿不到代理时返回 []（退回直连）。

    为什么下载链路必须带这个：`ensure_builtin_proxy()` 此前只服务于 GitHub
    相关请求，yt-dlp 全程直连 —— 在国内那就是"YouTube 永远连不上"。带上本地
    mihomo 之后，分流仍由 yaml 的 rules 决定（规则没覆盖的域名它自己也走
    直连），所以对 B 站等本来直连的站点没有副作用。

    并发安全：双检锁。此前 N 个任务同时首次取用时，各线程都会看到缓存为空，
    各自去拉起/等待 mihomo（最坏各等 20s 端口就绪）——多任务同加时集体白等。
    """
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
    """给界面用：(是否可用, 代理地址或空, 一句话说明)。附当前节点名。"""
    args = ytdlp_proxy_args()
    if args:
        info = _mihomo_api("/proxies/SELECT", timeout=3)
        now = info.get("now") if isinstance(info, dict) else None
        if now:
            return True, args[1], f"代理可用：{args[1]}（当前节点：{now}）"
        return True, args[1], "代理可用：" + args[1]
    if not os.path.isfile(MIHOMO_EXE):
        return False, "", "未安装内置代理组件（tools\\mihomo\\mihomo.exe）"
    return False, "", "代理未能启动或节点不可用，详见 logs\\mihomo.log"


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
# ========== 代理节点锁定（2026-10-08：治「EOF in violation of protocol」） ==========
#: mihomo 的 external-controller（见 tools/mihomo/config.yaml）
MIHOMO_API = os.environ.get("VT_MIHOMO_API", "http://127.0.0.1:9098")
#: 出网策略组名
PROXY_GROUP = os.environ.get("VT_PROXY_GROUP", "SELECT")
#: 节点锁定开关：默认开。设 VT_PROXY_LOCK=0 可退回「由 mihomo 自动切换」的旧行为。
PROXY_LOCK_ENABLED = os.environ.get("VT_PROXY_LOCK", "1").strip().lower() not in ("0", "off", "no", "false")

_PROXY_LOCK_STATE = {"orig": None, "count": 0}
_PROXY_LOCK_MUTEX = threading.Lock()


def _mihomo_proxy_api(method, path, payload=None, timeout=10):
    """调 mihomo 的 RESTful API；失败抛异常（调用方按需吞掉）。

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
        quote），失败返回 None；服务 ensure_builtin_proxy / proxy_status。
      · `_mihomo_proxy_api(method, path, ...)` —— path 为 `/proxies/` **之后**
        的一段（函数内统一 quote），失败抛异常；服务节点锁定/测速。
    """
    from urllib.parse import quote
    import urllib.request

    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    # ⚠ safe 必须保留 URL 结构字符：整体 quote 会把 `?`/`&`/`=` 也编码掉，
    #   导致 /proxies/<节点>/delay?url=... 这类带查询串的路径失效。
    req = urllib.request.Request(
        MIHOMO_API + "/proxies/" + quote(path, safe="/?=&:%~"), method=method,
        data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read().decode("utf-8", "replace")
        # 切换节点(PUT)返回 204 空体，别 json.loads
        return json.loads(body) if body.strip() else None


def proxy_group_now(group=None):
    """策略组当前选中的节点名；拿不到返回空串。"""
    try:
        return (_mihomo_proxy_api("GET", group or PROXY_GROUP, timeout=6) or {}).get("now", "") or ""
    except Exception:  # noqa: BLE001
        return ""


def proxy_node_delays(names, url="https://www.youtube.com/", timeout=6000):
    """实测各节点到 `url` 的延迟（毫秒）；不可达的节点不出现在结果里。"""
    from urllib.parse import quote
    out = {}
    for name in names:
        try:
            d = _mihomo_proxy_api("GET", "%s/delay?url=%s&timeout=%d"
                            % (name, quote(url, safe=""), timeout), timeout=12)
            delay = d.get("delay") if isinstance(d, dict) else None
            if delay and delay > 0:
                out[name] = int(delay)
        except Exception:  # noqa: BLE001
            continue
    return out


def pick_best_proxy_node(group=None, url="https://www.youtube.com/"):
    """挑出延迟最低的可用节点；测不到返回空串（表示维持现状）。"""
    try:
        info = _mihomo_proxy_api("GET", group or PROXY_GROUP, timeout=8) or {}
    except Exception:  # noqa: BLE001
        return ""
    # ⚠ mihomo 的 `all` 是**节点名字符串数组**，不是对象数组
    members = [m for m in (info.get("all") or []) if isinstance(m, str) and m]
    # 排除策略组与内置项（AUTO 本身是 url-test 组，不能当出口节点测）
    skip = {"AUTO", "DIRECT", "REJECT", "GLOBAL", "SELECT", "PROXY", group or PROXY_GROUP}
    members = [m for m in members if m not in skip]
    if not members:
        return ""
    delays = proxy_node_delays(members[:12], url=url)
    if not delays:
        return ""
    return min(delays.items(), key=lambda kv: kv[1])[0]


def proxy_lock_acquire():
    """下载任务开始时调用：把策略组钉到当前最快的节点。

    为什么要钉：YouTube 的 videoplayback 直链在签发时会**绑定当时的出口 IP**，
    而 mihomo 的 AUTO/Fallback 组会在中途换节点（url-test 每 300s 重测、
    fallback 遇故障即切）。一换 IP，已签发的所有分片 URL 全部失效 —— 表现为
    「Got error: EOF occurred in violation of protocol (_ssl.c:1007). Retrying」，
    且重试多少次都没用（重试用的还是那条绑定旧 IP 的 URL）。

    多任务并行时用引用计数：只有第一个任务真正切换，最后一个任务结束时恢复。
    """
    if not PROXY_LOCK_ENABLED:
        return ""
    with _PROXY_LOCK_MUTEX:
        _PROXY_LOCK_STATE["count"] += 1
        if _PROXY_LOCK_STATE["count"] > 1:
            return ""
        orig = proxy_group_now()
        _PROXY_LOCK_STATE["orig"] = orig
        best = pick_best_proxy_node()
        if not best or best == orig:
            return ""
        try:
            _mihomo_proxy_api("PUT", PROXY_GROUP, {"name": best})
            return best
        except Exception:  # noqa: BLE001
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
        orig = _PROXY_LOCK_STATE["orig"]
        _PROXY_LOCK_STATE["orig"] = None
        if not orig:
            return
        try:
            _mihomo_proxy_api("PUT", PROXY_GROUP, {"name": orig})
        except Exception:  # noqa: BLE001
            pass


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
    "proxy_lock_acquire",
    "proxy_lock_release",
]
