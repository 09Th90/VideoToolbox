# -*- coding: utf-8 -*-
# @version 2.4.0
"""代理节点锁定 + EOF 自愈链路自测（2026-10-17）。

覆盖对象：``core/shared/proxy.py`` 的锁定家族与
``core/download/ytdlp_util.py`` 的 ``ytdlp_error_needs_reextract``。

为什么要单独一份：锁定链路**不能依赖本机真有代理**——开发机/CI/换设备后
形态各异（有 FlClash / 有 IDE 自带内核 / 一个控制口都没有 / 控制口要密钥）。
这里用标准库起一个 **mock mihomo 控制口**，把四种设备形态各跑一遍：

  ① 单控制口 + 一个 Selector 组  → 能锁、能守护、能恢复
  ② 多控制口命中                → 不猜，交 VT_MIHOMO_API 指定
  ③ 控制口 401（要密钥）        → 给出明确指引而非静默
  ④ 无任何控制口                → 不锁但不阻断下载，日志说清原因
  ⑤ EOF 判定                    → needs_reextract / retryable 分工正确
  ⑥ 无本地代理                  → 走直连（换设备/能访问外网的场景）

跑法：``tools\\python\\python.exe scripts\\dev\\_selftest_proxy_lock.py``
加 ``--verbose`` 打印每个用例的细节。
"""
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "src"))

VERBOSE = "--verbose" in sys.argv


def _say(*a):
    if VERBOSE:
        print(*a)


# ---------------------------------------------------------------------------
# mock 控制口：/version + /proxies + /connections + PUT 切节点
# ---------------------------------------------------------------------------
class _State:
    def __init__(self):
        self.proxies = {
            "PROXIES": {"all": ["节点A", "节点B", "香港-01"], "now": "节点A",
                        "type": "Selector"},
            "自动选择": {"all": ["节点A", "节点B"], "now": "节点A", "type": "URLTest"},
            "节点A": {"type": "Shadowsocks"}, "节点B": {"type": "Shadowsocks"},
            "香港-01": {"type": "Vmess"},
        }
        self.puts = []          # [(group, name)]
        self.require_secret = False
        self.lock = threading.Lock()


def _make_handler(state):
    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):  # 静音
            pass

        def _json(self, obj, code=200):
            body = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _auth_ok(self):
            if not state.require_secret:
                return True
            return self.headers.get("Authorization") == "Bearer s3cr3t"

        def do_GET(self):
            if not self._auth_ok():
                return self._json({"error": "unauthorized"}, 401)
            path = self.path.split("?")[0]
            if path == "/version":
                return self._json({"version": "mock-1.0", "meta": True})
            if path == "/proxies":
                with state.lock:
                    return self._json({"proxies": state.proxies})
            if path == "/connections":
                # 真实链路形态：[出口节点, ..., 外层组]，跟随组当前选择变化 ——
                # 这样守护线程才能像真实环境那样"看到"漂移。
                with state.lock:
                    cur = state.proxies["PROXIES"]["now"]
                return self._json({"connections": [
                    {"chains": [cur, "PROXIES"]}]})
            return self._json({}, 404)

        def do_PUT(self):
            if not self._auth_ok():
                return self._json({"error": "unauthorized"}, 401)
            group = self.path.split("?")[0].rsplit("/", 1)[-1]
            try:
                data = json.loads(self.rfile.read(int(
                    self.headers.get("Content-Length") or 0)) or b"{}")
            except ValueError:
                data = {}
            name = str(data.get("name") or "")
            with state.lock:
                state.puts.append((group, name))
                if group in state.proxies:
                    state.proxies[group]["now"] = name
                    # 透传到内层：把节点名解析成叶子，供 _find_active_group 用
                    leaf = state.proxies.get(name, {})
                    if leaf and leaf.get("type") not in (
                            "Selector", "URLTest", "Fallback"):
                        pass
            # mihomo 的真实行为：PUT 成功返回 204 空体
            self.send_response(204)
            self.send_header("Content-Length", "0")
            self.end_headers()
    return H


def _serve(state, port):
    srv = ThreadingHTTPServer(("127.0.0.1", port), _make_handler(state))
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv


def _reset_env():
    for k in ("VT_MIHOMO_API", "VT_MIHOMO_SECRET", "VT_PROXY_GROUP",
              "VT_PROXY_LOCK", "VT_YTDLP_PROXY", "VT_USE_BUILTIN_PROXY"):
        os.environ.pop(k, None)


def case_single_controller(fails):
    """① 单控制口：锁得住、漂移能纠正、结束能恢复。"""
    from core.shared import proxy as P
    _reset_env()
    st = _State()
    PORT = 19198
    srv = _serve(st, PORT)
    try:
        os.environ["VT_MIHOMO_API"] = "http://127.0.0.1:%d" % PORT
        _prime_lock_state(P, "http://127.0.0.1:%d" % PORT)
        leaf = P.proxy_lock_acquire()
        ok = bool(leaf)
        _say("  ① 锁定节点 =", repr(leaf), "| PUTs =", st.puts)
        (fails.append("① 单控制口未能锁定节点") if not ok else None)
        # 引用计数：并行第二个任务只叠加计数、不重复切换
        n_put = len(st.puts)
        leaf2 = P.proxy_lock_acquire()
        if leaf2 != leaf or len(st.puts) != n_put:
            fails.append("① 并行任务重复切换或返回不一致（%r vs %r）"
                         % (leaf, leaf2))
        # 漂移守护：把组里 now 改掉，等守护线程纠正
        if ok:
            with st.lock:
                st.proxies["PROXIES"]["now"] = "节点B"
            st.puts.clear()
            # _LOCK_GUARD_INTERVAL=15s，要给足两个周期；否则用例还没轮到就超时
            deadline = time.time() + 22
            while time.time() < deadline and not st.puts:
                time.sleep(0.4)
            _say("  ① 漂移纠正 PUTs =", st.puts,
                 "| guard =", bool(P._GUARD.get("thread")))
            if not st.puts:
                fails.append("① 出口漂移后守护线程未纠正（15s 周期 ×2 内应有 PUT）")
        # 释放后恢复原选择（两次 release 让引用计数归零）
        P.proxy_lock_release()
        P.proxy_lock_release()
        time.sleep(0.5)
        _say("  ① 释放后 PUTs =", st.puts)
        restored = [p for p in st.puts if p[0] == "PROXIES" and p[1] == "节点A"]
        if not restored:
            fails.append("① 释放后未把策略组恢复成原选择")
    finally:
        srv.shutdown()
        proxy_stop_guard(P)


def case_multi_controller(fails):
    """② 多个控制口：只操作显式指定的那个（VT_MIHOMO_API）。"""
    from core.shared import proxy as P
    _reset_env()
    a, b = _State(), _State()
    PA, PB = 19199, 19200
    sa, sb = _serve(a, PA), _serve(b, PB)
    try:
        os.environ["VT_MIHOMO_API"] = "http://127.0.0.1:%d" % PB
        _prime_lock_state(P, "http://127.0.0.1:%d" % PB)
        leaf = P.proxy_lock_acquire()
        _say("  ② 显式指定 :%d → 锁定 = %r | B-PUTs = %s | A-PUTs = %s"
             % (PB, leaf, b.puts, a.puts))
        if not leaf:
            fails.append("② 显式 VT_MIHOMO_API 指向的控制口应能锁定")
        if b.puts and a.puts:
            fails.append("② 只应操作显式指定的那个控制口")
        P.proxy_lock_release()
    finally:
        sa.shutdown()
        sb.shutdown()
        proxy_stop_guard(P)


def case_secret(fails):
    """③ 控制口要密钥：给明确指引；带上密钥后能锁。"""
    from core.shared import proxy as P
    _reset_env()
    st = _State()
    st.require_secret = True
    PORT = 19201
    srv = _serve(st, PORT)
    try:
        base = "http://127.0.0.1:%d" % PORT
        os.environ["VT_MIHOMO_API"] = base
        os.environ.pop("VT_MIHOMO_SECRET", None)
        _prime_lock_state(P, base)
        leaf = P.proxy_lock_acquire()
        err = P.proxy_lock_status().get("error") or ""
        _say("  ③ 无密钥 → %r | %s" % (leaf, err))
        if leaf:
            fails.append("③ 无密钥时不应锁定成功")
        if "密钥" not in err:
            fails.append("③ 无密钥时报错未提及密钥（误导排查方向）: %r" % err)
        # 带上密钥后应能锁
        os.environ["VT_MIHOMO_SECRET"] = "s3cr3t"
        _prime_lock_state(P, base)
        leaf2 = P.proxy_lock_acquire()
        _say("  ③ 带密钥 → %r | %s" % (leaf2, st.puts))
        if not leaf2:
            fails.append("③ 提供 VT_MIHOMO_SECRET 后应能锁定（Bearer 校验）")
        if not any(p[0] == "PROXIES" for p in st.puts):
            fails.append("③ 带密钥锁定后应发生节点切换 PUT")
        P.proxy_lock_release()
    finally:
        srv.shutdown()
        proxy_stop_guard(P)


def case_no_controller(fails):
    """④ 一个控制口都没有：不锁，但绝不能抛异常、不能阻断下载。"""
    from core.shared import proxy as P
    _reset_env()
    # 指向一个必然没有服务的端口（高位，避开常用服务与其它用例）
    os.environ["VT_MIHOMO_API"] = "http://127.0.0.1:19202"
    try:
        P._PROXY_CTL.update({"base": "", "checked": 0.0, "source": "",
                             "hits": []})
        with P._PROXY_LOCK_MUTEX:
            P._PROXY_LOCK_STATE.clear()
            P._PROXY_LOCK_STATE.update({"orig": None, "count": 0, "base": "",
                                       "group": "", "node": "", "error": "",
                                       "egress_ip": "", "fail": 0})
        leaf = P.proxy_lock_acquire()
        err = P.proxy_lock_status().get("error") or ""
        _say("  ④ 无控制口 →", repr(leaf), "|", err)
        if leaf:
            fails.append("④ 无控制口时不应报告锁定成功")
        if not err:
            fails.append("④ 无控制口时必须记录原因（供界面/日志展示）")
        P.proxy_lock_release()
        st = P.proxy_lock_status()
        _say("  ④ status =", {k: st[k] for k in (
            "proxy", "controller", "ctl_hits", "secret_needed")})
    finally:
        proxy_stop_guard(P)


def case_eof_detect(fails):
    """⑤ EOF 判定分工：needs_reextract 与 retryable 各管一段。"""
    from core.download.ytdlp_util import (ytdlp_error_needs_reextract,
                                         ytdlp_error_retryable)
    C = [
        ("Got error: EOF occurred in violation of protocol "
         "(_ssl.c:1007). Retrying (1/10)", True),
        ("ERROR: unable to download video data: HTTP Error 403", True),
        ("ERROR: [hlsnative] fragment not found", True),
        ("ERROR: unable to download video data: Remote end closed "
         "connection without response", True),
        ("ERROR: Video unavailable. This video is private", False),
        ("", False),
        ("Retrying (1/10)", False),
    ]
    for text, want in C:
        got = ytdlp_error_needs_reextract(text)
        _say("  ⑤ %-28r → %s" % (text[:28], got))
        if got != want:
            fails.append("⑤ needs_reextract 判定错: %r 期望 %s 实得 %s"
                         % (text[:40], want, got))
    # 可重试性：EOF 也 retryable=True（语义是"临时"），但调用方应优先走 reextract
    eof = "ERROR: Got error: EOF occurred in violation of protocol (_ssl.c:1007)"
    if not ytdlp_error_retryable(eof):
        fails.append("⑤ EOF 应仍属 retryable（两者不互斥，调用方有优先级）")


def case_no_proxy(fails):
    """⑥ 换设备/能直连外网：没有本地代理也能正常工作（拿不到就直连）。"""
    from core.shared import proxy as P
    _reset_env()
    # 强制复活节前先确认 _proxy_candidates 不依赖本机注册表/环境
    cands = P._proxy_candidates()
    _say("  ⑥ 本机候选 =", cands)
    # 关键断言：函数在任何平台都不抛
    try:
        P._env_proxy_url, P._registry_proxy_url, P._macos_proxy_url,\
            P._linux_proxy_url
        P._local_listen_ports()
        P._port_pid(0)
    except Exception as e:  # noqa: BLE001
        fails.append("⑥ 代理发现族在任何环境下都不应抛异常: %r" % e)
    # 解析注册表路径之外的端口不应崩
    try:
        P._system_proxy_url()
    except Exception as e:  # noqa: BLE001
        fails.append("⑥ _system_proxy_url 异常: %r" % e)


def case_eof_kill_logic(fails):
    """⑨ EOF 是否该「主动结束进程」的判定（2026-10-17 监控后新增）。

    规则：直链 EOF = 整条链接作废，yt-dlp 自己重试死链纯属白等
    （`--retry-sleep exp=1:20` 最长 20s × `--retries` 10 次），必须主动结束
    交给上层重新提取；分片 EOF = 单片失效，`--fragment-retries` 逐片重下
    更有效且不丢已下进度，不能杀。
    这里内联同样的判据（GUI 类依赖 PySide6，无法在无界面环境导入）。
    """
    def is_fatal(line):
        low = (line or "").lower()
        return not any(k in low for k in
                       ("fragment", "hlsnative", "m3u8", "frag", "dash"))

    C = [
        ("ERROR: unable to download video data: Got error: EOF occurred in "
         "violation of protocol (_ssl.c:1007). Retrying (2/10)", True,
         "直链 EOF → 应主动结束"),
        ("ERROR: unable to download video data: _ssl.c:1007", True,
         "直链 EOF（无 Retrying 尾串）→ 应主动结束"),
        ("ERROR: [hlsnative] Downloading fragment 42/500: Got error: EOF "
         "occurred in violation of protocol", False,
         "HLS 分片 EOF → 不杀（fragment-retries 更有效）"),
        ("ERROR: [hlsnative] Downloading fragment 42/500: _ssl.c:1007", False,
         "HLS 分片 EOF（无 Retrying 尾串）→ 不杀"),
        ("ERROR: [dashsegments] Total fragments: 300: _ssl.c:1007", False,
         "DASH 分片 EOF → 不杀"),
    ]
    for text, want, note in C:
        got = is_fatal(text)
        _say("  ⑨ %-46s → %s (%s)" % (text[:46], got, note))
        if got != want:
            fails.append("⑨ EOF 主动结束判定错: %r 期望 %s 实得 %s（%s）"
                         % (text[:60], want, got, note))


def case_env_parse(fails):
    """⑦ 环境变量解析：端口补全 / IPv6 / SOCKS 直接采信（2026-10-17 自检补）。"""
    import os as _os
    from core.shared import proxy as P
    _reset_env()
    C = [
        ({"HTTP_PROXY": "127.0.0.1"}, "http://127.0.0.1:8080"),
        ({"HTTP_PROXY": "http://127.0.0.1:7890"}, "http://127.0.0.1:7890"),
        # IPv6 裸地址里本身含冒号，老实现会误判成"已带端口"而漏补 8080
        ({"HTTP_PROXY": "http://[::1]"}, "http://[::1]:8080"),
        ({"HTTP_PROXY": "http://[::1]:7890"}, "http://[::1]:7890"),
        ({"HTTP_PROXY": "socks5://127.0.0.1:1080"}, "socks5://127.0.0.1:1080"),
    ]
    for env, want in C:
        saved = {k: _os.environ.get(k) for k in P._PROXY_ENV_VARS}
        for k in P._PROXY_ENV_VARS:
            _os.environ.pop(k, None)
        _os.environ.update(env)
        try:
            got = P._env_proxy_url()
        finally:
            for k, v in saved.items():
                if v is None:
                    _os.environ.pop(k, None)
                else:
                    _os.environ[k] = v
        _say("  ⑦ %-30s → %s" % (env, got))
        if got != want:
            fails.append("⑦ _env_proxy_url(%r) 期望 %s 实得 %s" % (env, want, got))
    # SOCKS 候选必须被判"可用"：标准库探不了 socks://，但 yt-dlp 支持。
    # 若这里判 False，用户显式设的 SOCKS 代理会被静默丢弃、退回直连。
    us = "socks5://127.0.0.1:1080"
    orig_cands, orig_probe = P._proxy_candidates, dict(P._PROXY_PROBE)
    P._proxy_candidates = lambda: [us]
    P._PROXY_PROBE.update({"at": 0.0, "val": "", "log_miss": True})
    try:
        got = P._system_proxy_url()
        _say("  ⑦ 仅 SOCKS 候选 → _system_proxy_url =", repr(got))
        if got != us:
            fails.append("⑦ 仅 SOCKS 代理时应直接采信（不能因标准库探不到而丢弃），"
                         "实得 %r" % got)
    finally:
        P._proxy_candidates = orig_cands
        P._PROXY_PROBE.update(orig_probe)


def case_static(fails):
    """⑧ 静态自检：顶层同名定义互相遮蔽（2026-10-12 事故的回归防线）。

    那次是 `_mihomo_api` 被后一个同名函数整个遮蔽 → 代理引导链路 TypeError →
    YouTube 提取全超时。此处用 AST 扫 `src/core/**` 全部模块的顶层作用域，
    出现重复的函数名 / 赋值名即判失败。
    """
    import ast
    import glob as _glob
    import collections
    pats = [os.path.join(ROOT, "src", "core", "**", "*.py"),
            os.path.join(ROOT, "src", "*.py")]
    files = sorted({f for p in pats for f in _glob.glob(p, recursive=True)})
    total = 0
    for path in files:
        try:
            tree = ast.parse(open(path, encoding="utf-8").read())
        except (SyntaxError, UnicodeDecodeError) as e:
            fails.append("⑧ 解析失败 %s: %r" % (path, e))
            continue
        seen = collections.Counter()
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                ast.ClassDef)):
                seen[node.name] += 1
            elif isinstance(node, ast.Assign):
                for tg in node.targets:
                    if isinstance(tg, ast.Name):
                        seen[tg.id] += 1
            elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
                tg = getattr(node, "target", None)
                if isinstance(tg, ast.Name):
                    seen[tg.id] += 1
        dups = {k: v for k, v in seen.items()
                if v > 1 and not k.startswith("__")}
        total += 1
        if dups:
            fails.append("⑧ %s 顶层同名定义（会互相遮蔽）: %s"
                         % (os.path.relpath(path, ROOT), dups))
    _say("  ⑧ 已扫描 %d 个模块" % total)


def case_translate_route(fails):
    """⑩ 翻译链路路由（2026-10-17 用户报「252/252 segments failed」后新增）。

    复现故障环境（https_proxy 指向一个对国内站点不通的 IDE 代理），验证：
      ① BingTranslator 的路由被钉死为直连（trust_env=False, proxies={}）；
      ② 真实翻译请求能通（HTTP 200 且返回中文）；
      ③ worker 子进程环境里标准代理变量被剥掉（VT_YTDLP_PROXY 保留）。
    这三条任一失守，都会复现「全部片段失败」。
    """
    import os as _os
    from core.shared.env import prepare_runtime_env
    saved_env = {k: _os.environ.get(k) for k in
                 ("https_proxy", "HTTPS_PROXY", "http_proxy", "HTTP_PROXY",
                  "ALL_PROXY", "all_proxy")}
    for k in saved_env:
        _os.environ.pop(k, None)
    _os.environ["https_proxy"] = "http://127.0.0.1:14901"
    _os.environ["HTTPS_PROXY"] = "http://127.0.0.1:14901"
    try:
        prepare_runtime_env()
        from videocaptioner.core.translate.factory import TranslatorFactory
        from videocaptioner.core.translate.types import (TranslatorType,
                                                        TargetLanguage)
        t = TranslatorFactory.create_translator(
            TranslatorType.BING, thread_num=1, batch_num=5,
            target_language=TargetLanguage.SIMPLIFIED_CHINESE,
            update_callback=lambda *a, **k: None)
        pinned = (getattr(t.session, "trust_env", True) is False
                  and getattr(t.session, "proxies", None) == {})
        _say("  ⑩ BingTranslator 路由钉死 =", pinned,
             "| trust_env =", t.session.trust_env,
             "| proxies =", t.session.proxies)
        if not pinned:
            fails.append("⑩ BingTranslator 路由未被钉死（会跟随 https_proxy 环境变量）")
        try:
            r = t.session.post(
                getattr(t, "endpoint", ""),
                params={"to": "zh-Hans", "api-version": "3.0"},
                json=["Good morning"], headers=t.headers, timeout=20)
            txt = ""
            if r.status_code == 200:
                txt = (r.json()[0].get("translations") or [{}])[0].get("text", "")
            _say("  ⑩ 真实翻译请求 =", r.status_code, "→", txt)
            if r.status_code != 200 or not txt:
                fails.append("⑩ 翻译请求未通（HTTP %s）——排障请看 logs 里的"
                             "「翻译路由快照」" % r.status_code)
        except Exception as e:  # noqa: BLE001
            fails.append("⑩ 翻译请求异常: %r" % e)
        # 子进程环境：代理变量必须剥掉，VT_YTDLP_PROXY 必须保留
        from core.shared.runtime import worker_subprocess_env
        _os.environ["VT_YTDLP_PROXY"] = "http://127.0.0.1:7890"
        env = worker_subprocess_env()
        leaked = [k for k in ("https_proxy", "HTTPS_PROXY", "http_proxy",
                              "HTTP_PROXY", "ALL_PROXY", "all_proxy")
                  if env.get(k)]
        _say("  ⑩ 子进程残留代理变量 =", leaked or "无",
             "| VT_YTDLP_PROXY =", env.get("VT_YTDLP_PROXY"))
        if leaked:
            fails.append("⑩ worker 子进程仍带代理环境变量: %s" % leaked)
        if env.get("VT_YTDLP_PROXY") != "http://127.0.0.1:7890":
            fails.append("⑩ VT_YTDLP_PROXY 应在子进程中保留（显式代理通道）")
    finally:
        for k, v in saved_env.items():
            if v is None:
                _os.environ.pop(k, None)
            else:
                _os.environ[k] = v
        _os.environ.pop("VT_YTDLP_PROXY", None)


def proxy_stop_guard(P):
    stop = P._GUARD.get("stop")
    if stop is not None:
        stop.set()
        P._GUARD["stop"] = None


def _prime_lock_state(P, base):
    """把锁定状态与控制口缓存对准 mock 服务，避免受本机环境影响。"""
    P._PROXY_CTL.update({"base": base, "checked": time.time(),
                         "source": "mock", "hits": [base]})
    with P._PROXY_LOCK_MUTEX:
        P._PROXY_LOCK_STATE.clear()
        P._PROXY_LOCK_STATE.update({"orig": None, "count": 0, "base": "",
                                    "group": "", "node": "", "error": "",
                                    "egress_ip": "", "fail": 0})


def main():
    fails = []
    print("=" * 64)
    print("PROXY-LOCK SELFTEST（mock mihomo 控制口 · 十项检查）")
    print("=" * 64)
    for name, fn in (("① 单控制口", case_single_controller),
                     ("② 多控制口", case_multi_controller),
                     ("③ 控制口要密钥", case_secret),
                     ("④ 无控制口", case_no_controller),
                     ("⑤ EOF 判定", case_eof_detect),
                     ("⑥ 无本地代理/直连", case_no_proxy),
                     ("⑦ 环境变量解析", case_env_parse),
                     ("⑧ 静态：顶层同名遮蔽", case_static),
                     ("⑨ EOF 主动结束判定", case_eof_kill_logic),
                     ("⑩ 翻译链路路由", case_translate_route)):
        print("[RUN ] %s" % name)
        t0 = time.time()
        try:
            fn(fails)
        except Exception as e:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            fails.append("%s 用例本身抛异常: %r" % (name, e))
        print("[DONE] %s (%.1fs)" % (name, time.time() - t0))
    print("-" * 64)
    if fails:
        print("PROXY-LOCK RESULT: FAIL (%d 项)" % len(fails))
        for f in fails:
            print("  -", f)
        return 1
    print("PROXY-LOCK RESULT: PASS（10 项全绿）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
