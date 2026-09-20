# -*- coding: utf-8 -*-
# @version 1.15.6
"""校准 Agent 的联网查证工具（2026-09-20 新增）。

定位
====
AI 校准 Agent（calib_ai_agent）过去只能靠注入的术语知识库：库里没有的疑似
错形，模型只能盲改（被证据校验拒绝）或放弃。本模块给它补上「联网查证」这条
腿：Agent 在逐块判定时可以发 `web_search` / `web_fetch` 工具请求，由这里的
实现真实出网，把结果作为**只读证据**回填给模型再下结论。

设计约束（与 calib_ai_agent 的契约一致）
========================================
* 零第三方依赖：只用标准库 urllib（tools\\python 无 pip）；
* 网络出口走应用统一策略：`proxy` 注入一个 callable（engine.ai_proxy_for_requests
  语义：None=跟随系统 / {}=强制直连 / {"http":u,"https":u}=走指定代理），
  由引擎层在构造时传入，本模块不 import 引擎（保持 Agent 无 GUI 依赖）；
* 只读证据：本模块只返回文本，绝不参与写盘/回填——采纳与否仍由
  calib_ai_agent 的证据校验把关；
* 进程内缓存：同一查询不重复出网（长片源多块反复遇到同一术语时省时间省流量）；
* 失败降级：网络异常返回「查询失败：…」文本给模型（不抛异常打断校准主流程），
  模型据此选择不改。

搜索引擎顺位：cn.bing（国内大多直连可查中文专名）→ www.bing → html.duckduckgo。
任一引擎解析不出结果就换下一个；全失败返回提示文本。
"""

from __future__ import annotations

import html as _html
import re
import threading
import urllib.error
import urllib.parse
import urllib.request

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

#: 单次抓页最多回填给模型的正文字符数（防提示词爆炸）
MAX_FETCH_CHARS = 3500
#: 搜索结果保留条数
MAX_RESULTS = 5

_RE_SCRIPT = re.compile(r"<(script|style|noscript)\b.*?</\1>",
                        re.S | re.I)
_RE_TAG = re.compile(r"<[^>]+>")
_RE_WS = re.compile(r"[ \t\r\f\v]+")
_RE_ML = re.compile(r"\n{2,}")


# ============================ HTTP 原语 ============================
def _opener(proxy):
    """按 proxy 快照构造 opener。proxy 语义对齐 ai_proxy_for_requests 返回值。"""
    if proxy is None:
        return urllib.request.build_opener(
            urllib.request.ProxyHandler())          # 跟随系统/环境变量
    if isinstance(proxy, dict) and not proxy:
        return urllib.request.build_opener(
            urllib.request.ProxyHandler({}))         # 显式直连
    u = (proxy or {}).get("https") or (proxy or {}).get("http") or ""
    if not u:
        return urllib.request.build_opener(
            urllib.request.ProxyHandler({}))
    return urllib.request.build_opener(
        urllib.request.ProxyHandler({"http": u, "https": u}))


def _http_get(url, proxy, timeout=12, referer=""):
    """GET 一个页面，返回 (状态码, 解码后文本)；异常向上抛。"""
    headers = {"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7"}
    if referer:
        headers["Referer"] = referer
    req = urllib.request.Request(url, headers=headers)
    with _opener(proxy).open(req, timeout=timeout) as r:
        raw = r.read()
        ctype = (r.headers.get("Content-Type") or "").lower()
    enc = "utf-8"
    m = re.search(r"charset=?([a-z0-9_\-]+)", ctype)
    if m:
        enc = m.group(1)
    else:
        head = raw[:2048]
        m2 = re.search(rb'charset=["\']?([a-zA-Z0-9_\-]+)', head)
        if m2:
            enc = m2.group(1).decode("ascii", "ignore")
    return getattr(r, "status", 200), raw.decode(enc, errors="replace")


def _strip_html(text: str) -> str:
    text = _RE_SCRIPT.sub(" ", text or "")
    text = re.sub(r"<br\s*/?>|</p>|</li>|</h\d>", "\n", text, flags=re.I)
    text = _RE_TAG.sub("", text)
    text = _html.unescape(text)
    text = _RE_WS.sub(" ", text)
    return _RE_ML.sub("\n", text).strip()


# ============================ 搜索引擎 ============================
def _parse_bing(page):
    """Bing/cn.bing 结果抽取：b_algo 块里的标题/链接/摘要。"""
    out = []
    for m in re.finditer(
            r'<li class="b_algo".*?<h2[^>]*>\s*<a[^>]+href="(?P<u>[^"]+)"'
            r'[^>]*>(?P<t>.*?)</a>(?P<rest>.*?)</li>', page, re.S):
        url = _html.unescape(m.group("u"))
        title = _html.unescape(_RE_TAG.sub("", m.group("t"))).strip()
        sm = re.search(r"<p[^>]*>(.*?)</p>", m.group("rest"), re.S)
        snip = _html.unescape(_RE_TAG.sub("", sm.group(1))).strip() if sm else ""
        if title:
            out.append((title, url, snip[:220]))
        if len(out) >= MAX_RESULTS:
            break
    return out


def _parse_ddg(page):
    """html.duckduckgo 结果抽取；uddg 重定向链还原为真实地址。"""
    out = []
    titles = re.finditer(
        r'<a[^>]+class="result__a"[^>]+href="(?P<u>[^"]+)"[^>]*>(?P<t>.*?)</a>',
        page, re.S)
    snips = [re.sub(r"<[^>]+>", "", m.group(1)) for m in re.finditer(
        r'class="result__snippet"[^>]*>(.*?)</a>', page, re.S)]
    for i, m in enumerate(titles):
        url = _html.unescape(m.group("u"))
        q = urllib.parse.urlparse(url).query
        real = dict(urllib.parse.parse_qsl(q)).get("uddg") or url
        title = _html.unescape(m.group("t")).strip()
        snip = _html.unescape(snips[i]).strip() if i < len(snips) else ""
        if title:
            out.append((title, real, snip[:220]))
        if len(out) >= MAX_RESULTS:
            break
    return out


def _ddg_url(query):
    return "https://html.duckduckgo.com/html/?" + urllib.parse.urlencode(
        {"q": query, "kl": "cn-zh"})


def _bing_url(query, host):
    return f"https://{host}/search?" + urllib.parse.urlencode(
        {"q": query, "count": "8", "setlang": "zh-hans"})


def _format_results(query, hits):
    if not hits:
        return f"搜索「{query}」没有可用结果。"
    lines = [f"搜索「{query}」共 {len(hits)} 条结果（只读证据，禁止照抄进字幕）："]
    for i, (t, u, s) in enumerate(hits, 1):
        lines.append(f"{i}. {t}\n   链接：{u}")
        if s:
            lines.append(f"   摘要：{s}")
    return "\n".join(lines)


# ============================ 对外工具工厂 ============================
def make_tools(proxy=None, log=None, timeout=12):
    """返回 {"search": fn(query)->str, "fetch": fn(url)->str}。

    proxy: None 或 callable→(None|dict)（engine.ai_proxy_for_requests）。
    每次调用现取代理快照：内置代理可能在长跑中途才拉起。
    所有异常都吞成「失败：…」文本——查证失败时模型应当选择不改，
    主流程绝不能被网络抖动打断。
    """
    cache = {}
    lock = threading.Lock()
    _log = log or (lambda m, level="dim": None)

    def _proxy():
        try:
            return proxy() if callable(proxy) else proxy
        except Exception:  # noqa: BLE001
            return None

    def search(query):
        query = str(query or "").strip()[:160]
        if not query:
            return "查询失败：query 为空"
        key = ("s", query)
        with lock:
            if key in cache:
                return cache[key]
        text = ""
        for host, parser in (("cn.bing.com", _parse_bing),
                             ("www.bing.com", _parse_bing),
                             ("ddg", _parse_ddg)):
            url = _ddg_url(query) if host == "ddg" else _bing_url(query, host)
            try:
                _code, page = _http_get(url, _proxy(), timeout=timeout)
                hits = parser(page)
                if hits:
                    text = _format_results(query, hits)
                    break
            except (urllib.error.URLError, OSError, ValueError) as e:
                _log(f"  · 联网查证 {host} 失败：{type(e).__name__}", "dim")
        if not text:
            text = f"搜索「{query}」失败（网络不通或全部引擎无结果），请勿臆改。"
        with lock:
            cache[key] = text
        return text

    def fetch(url):
        url = str(url or "").strip()
        if not re.match(r"^https?://", url):
            return "抓取失败：只允许 http/https 链接"
        key = ("f", url[:300])
        with lock:
            if key in cache:
                return cache[key]
        try:
            _code, page = _http_get(url, _proxy(), timeout=timeout)
            body = _strip_html(page)[:MAX_FETCH_CHARS]
            text = (f"页面 {url} 正文摘录（只读证据）：\n{body}" if body
                    else f"页面 {url} 没有可提取正文。")
        except Exception as e:  # noqa: BLE001
            text = f"抓取 {url} 失败：{type(e).__name__}: {e}"
        with lock:
            cache[key] = text
        return text

    return {"search": search, "fetch": fetch}


if __name__ == "__main__":  # 手工连通性小样（不走缓存，仅调试用）
    tools = make_tools()
    print(tools["search"]("鸣潮 卡提希娅 官方"))
