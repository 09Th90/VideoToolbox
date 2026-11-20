# -*- coding: utf-8 -*-
# @version 3.1.3
"""校准 Agent 的联网查证工具（2026-09-20 新增；2026-11-18 重构 v2）。

定位
====
AI 校准 Agent（calib_ai_agent）过去只能靠注入的术语知识库：库里没有的疑似
错形，模型只能盲改（被证据校验拒绝）或放弃。本模块给它补上「联网查证」这条
腿：Agent 在逐块判定时可以发 `web_search` / `web_fetch` 工具请求，由这里的
实现真实出网，把结果作为**只读证据**回填给模型再下结论。

v2 重构（2026-11-18）修掉的已知缺陷
==================================
* 中文 URL 必崩：`urllib` 用 ascii 编码请求行，任何含中文的 wiki 链接都抛
  UnicodeEncodeError。现在统一走 `_encode_url()`（path/query 分别 quote）。
* 英文查询拿到 bing.com/ck/a 跳转链：`_unwrap_bing_link()` 解 base64 还原真实地址。
* 噪声当证据：`_is_relevant()` 用「术语整词 / 2-gram 覆盖」过滤，查「崔林特尔梅
  之金」不再把「崔姓_百度百科」回填给模型。
* 来源平权：`_tier_of()` 按 官网 > 维基 > 百科 > 社区 分级排序并标注。
* 正文从头截断：`_focus_text()` 按关键词位置取窗口，wiki 页面不再只回填导航。
* DDG 白等 12s：超时压到 5s，且只在前两个 Bing 都失败时才尝试。

站点适配（本次新增）
====================
* PRTS（prts.wiki）—— MediaWiki `api.php`：`list=search` 找标题 + `parse` 取 wikitext。
* BWIKI（wiki.biligame.com/{wutheringwaves,arknights,zspms}）—— 同上。
* wiki.gg（endfield.wiki.gg）—— 同上。
* 终末地 Wiki（www.fz.wiki）—— Next.js 客户端渲染：正文不可得，用 `sitemap.xml`
  做标题索引（发现）+ 页面 meta 做存在性证据。
* 库街区（wiki.kurobbs.com）—— 前端 SPA，但公开检索引擎免密：
  `POST api.kurobbs.com/wiki/core/catalogue/item/search`（表单体 + `wiki_type`
  区分游戏：鸣潮=9 / 战双=2），无 token 即可返回条目 `name`/`id`；条目标题
  已是官方名，足够做「官方写法」证据。
* 森空岛（wiki.skland.com，终末地）—— 公开免密签名接口：先
  `GET zonai.skland.com/web/v1/auth/refresh` 取 sign token，再按
  `md5(hmac_sha256(path+query+timestamp+JSON({platform,timestamp,dId,vName}), token))`
  签名调 `wiki/item/search` 与 `wiki/item/info`。搜索给官方名+分类，
  详情 `document.documentMap` 可还原正文。
  （两家都不涉及账号鉴权：只用站点公开检索/公开条目接口。）

设计约束（与 calib_ai_agent 的契约一致）
========================================
* 零第三方依赖：只用标准库 urllib（tools\\python 无 pip）；
* 网络出口走应用统一策略：`proxy` 注入一个 callable（engine.ai_proxy_for_requests
  语义：None=跟随系统 / {}=强制直连 / {"http":u,"https":u}=走指定代理）；
* 只读证据：本模块只返回文本，绝不参与写盘/回填——采纳与否仍由
  calib_ai_agent 的证据校验把关；
* 进程内缓存：同一查询不重复出网；搜索缓存按（作品, 核心词）归一化，
  同一术语换措辞不再重复请求；
* 失败降级：网络异常返回「查询失败：…」文本给模型（不抛异常打断校准主流程）。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import html as _html
import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
UA_MOBILE = ("Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 "
             "(KHTML, like Gecko) Chrome/126.0 Mobile Safari/537.36")

#: 单次抓页最多回填给模型的正文字符数（v2：3500 -> 6000，配合关键词窗口）
MAX_FETCH_CHARS = 6000
#: 搜索结果保留条数（每通道）
MAX_RESULTS = 5
#: 汇总后最多回填条数
MAX_TOTAL_HITS = 8
#: Bing 超时（秒）；DDG 只用更短的独立超时
BING_TIMEOUT = 12
DDG_TIMEOUT = 5

#: 页面正文少于该字符数且站点为 SPA/Next.js 时，判定「客户端渲染，未取到正文」
_RENDER_SHELL_CHARS = 220

_RE_SCRIPT = re.compile(r"<(script|style|noscript)\b.*?</\1>", re.S | re.I)
_RE_TAG = re.compile(r"<[^>]+>")
_RE_WS = re.compile(r"[ \t\r\f\v]+")
_RE_ML = re.compile(r"\n{2,}")
_RE_META = re.compile(
    r'<meta[^>]+(?:name|property)=["\'](?:description|og:description)["\'][^>]*'
    r'content=["\'](.*?)["\']', re.S | re.I)
_RE_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.S | re.I)


# ============================ 站点表 ============================
#: 作品 -> 该作品的权威站点（站内优先检索；顺序即优先级）
WORK_SITES = {
    "鸣潮": [
        # 官方站优先：同名条目在 _dedupe 里先到先得，官方名优先于社区 wiki
        {"kind": "kuro", "name": "库街区WIKI",
         "page": "https://wiki.kurobbs.com/",
         "host": "wiki.kurobbs.com",
         "wiki_type": 9, "game": "mc"},
        {"kind": "mediawiki", "name": "BWIKI·鸣潮",
         "api": "https://wiki.biligame.com/wutheringwaves/api.php",
         "page": "https://wiki.biligame.com/wutheringwaves/{title}",
         "referer": "https://wiki.biligame.com/wutheringwaves/"},
    ],
    "明日方舟": [
        {"kind": "mediawiki", "name": "PRTS",
         "api": "https://prts.wiki/api.php",
         "page": "https://prts.wiki/w/{title}",
         "referer": "https://prts.wiki/"},
        {"kind": "mediawiki", "name": "BWIKI·明日方舟",
         "api": "https://wiki.biligame.com/arknights/api.php",
         "page": "https://wiki.biligame.com/arknights/{title}",
         "referer": "https://wiki.biligame.com/arknights/"},
    ],
    "终末地": [
        # 官方站优先：森空岛条目名即官方名；BWIKI zmd 提供可深抓的 wikitext 正文
        {"kind": "skland", "name": "森空岛WIKI",
         "page": "https://wiki.skland.com/",
         "host": "wiki.skland.com",
         "game": "endfield"},
        # 2026-11-18 实测：终末地在 BWIKI 有独立站 /zmd（MediaWiki 可深抓），
        # 之前 sources.py 的「BWIKI 无终末地站」结论已过时。
        {"kind": "mediawiki", "name": "BWIKI·终末地",
         "api": "https://wiki.biligame.com/zmd/api.php",
         "page": "https://wiki.biligame.com/zmd/{title}",
         "referer": "https://wiki.biligame.com/zmd/"},
        {"kind": "fz", "name": "终末地Wiki",
         "sitemap": "https://www.fz.wiki/sitemap.xml",
         "page": "https://www.fz.wiki/wiki/{title}"},
        {"kind": "mediawiki", "name": "wiki.gg·终末地",
         "api": "https://endfield.wiki.gg/api.php",
         "page": "https://endfield.wiki.gg/wiki/{title}",
         "referer": "https://endfield.wiki.gg/"},
    ],
    "战双": [
        # 官方站优先：库街区战双站（公开检索免密，wiki_type=2）
        {"kind": "kuro", "name": "库街区WIKI·战双",
         "page": "https://wiki.kurobbs.com/",
         "host": "wiki.kurobbs.com",
         "wiki_type": 2, "game": "pns"},
        {"kind": "mediawiki", "name": "BWIKI·战双",
         "api": "https://wiki.biligame.com/zspms/api.php",
         "page": "https://wiki.biligame.com/zspms/{title}",
         "referer": "https://wiki.biligame.com/zspms/"},
    ],
    "边狱巴士": [
        {"kind": "mediawiki", "name": "wiki.gg·边狱",
         "api": "https://limbuscompany.wiki.gg/api.php",
         "page": "https://limbuscompany.wiki.gg/wiki/{title}",
         "referer": "https://limbuscompany.wiki.gg/"},
    ],
}

#: 作品别名（用于从 query 识别作品；小写匹配）
WORK_ALIASES = {
    "鸣潮": ("鸣潮", "wuthering waves", "wuwa"),
    "明日方舟": ("明日方舟", "arknights", "方舟"),
    "终末地": ("终末地", "endfield", "明日方舟终末地"),
    "战双": ("战双", "战双帕弥什", "punishing gray raven", "pgr"),
    "边狱巴士": ("边狱巴士", "边狱公司", "limbus"),
}

#: 来源分级（域名后缀 -> 级别）；用于排序与标注
_TIER_RULES = (
    ("官网", ("kurogames.com", "hypergryph.com", "gryphline.com", "skland.com",
              "mihoyo.com", "hoyoverse.com")),
    ("维基", ("biligame.com", "prts.wiki", "fz.wiki", "huijiwiki.com",
              "fandom.com", "moegirl", "wiki.gg", "wikipedia.org")),
    ("百科", ("baike.baidu.com", "baike.sogou.com")),
    ("社区", ("taptap", "zhihu", "bilibili", "tieba", "weibo", "xiaohongshu",
              "nga", "reddit", "youtube", "douyin")),
)
_TIER_ORDER = {"官网": 0, "维基": 1, "百科": 2, "社区": 3, "其他": 4}

#: query 里的噪声词（检索前剥掉，否则 Bing/站内搜索会被稀释成单字）
_NOISE_RE = re.compile(
    r"(官方名称|官方中文|官方译名|官方名|官方|名称|译名|中文名|叫什么|是什么|"
    r"怎么读|怎么翻|资料|介绍|百科|词条|角色|技能|设定)")

#: 可直接从 URL 推导的 MediaWiki 站点（host -> api 模板）
_MW_HOSTS = {
    "prts.wiki": ("https://prts.wiki/api.php", "https://prts.wiki/w/{title}"),
    "endfield.wiki.gg": ("https://endfield.wiki.gg/api.php",
                         "https://endfield.wiki.gg/wiki/{title}"),
    "limbuscompany.wiki.gg": ("https://limbuscompany.wiki.gg/api.php",
                              "https://limbuscompany.wiki.gg/wiki/{title}"),
}

#: 库街区公开检索（免密）：表单体 POST，wiki_type 区分游戏（9=鸣潮 / 2=战双）
_KURO_SEARCH_API = "https://api.kurobbs.com/wiki/core/catalogue/item/search"
_KURO_WIKI_TYPE = {"mc": 9, "pns": 2}
#: 库街区卡片类型白名单：角色/机体/词条卡；horizontal-figure 多为影像/同人/攻略
_KURO_CARD_TYPES = ("vertical-figure", "square-figure",
                    "multiple-figure", "text-list-small")
#: 首页「快捷导航」十类图鉴对应的一级分类 id（游戏图鉴/剧情/成就/攻略/百科/任务）
_KURO_HOME_FIDS = {1099, 1328, 1314, 1322, 1334, 1249}
#: 一级分类下要剔除的二级分类（头像/称号/装饰等非图鉴词条，避免同名噪声）
_KURO_EXCLUDE_SIDS = {1363, 1613, 1614, 1518, 1523, 1634, 1637}

#: 森空岛公开签名接口（免密）：先 refresh 取 sign token，再 hmac/md5 签名
_SKLAND_HOST = "https://zonai.skland.com"
#: 设备标识：只参与签名串拼接；实测服务端不校验设备真实性，固定值即可
_SKLAND_DID = ("BJTZZ4OX8A5l0iuZBCMStZ0XY5YrfC5CR+bt+bBkFWZNuUxx5nYdezX"
               "/42ULqzakrGcfDEcER8bJtVp+0w2ZSqA==")
_SKLAND_TOKEN_CACHE = {"at": 0.0, "token": ""}
_SKLAND_TOKEN_TTL = 3600
_SKLAND_LOCK = threading.Lock()
#: 森空岛噪声子类（影像/攻略/装扮不是「官方词条名」证据）
_SKLAND_NOISE_SUBTYPES = {"装扮", "游戏视频", "同人绘画", "任务", "活动",
                          "情报档案库", "游戏壁纸"}


# ============================ HTTP 原语 ============================
def _opener(proxy):
    """按 proxy 快照构造 opener。proxy 语义对齐 ai_proxy_for_requests 返回值。"""
    if proxy is None:
        return urllib.request.build_opener(urllib.request.ProxyHandler())
    if isinstance(proxy, dict) and not proxy:
        return urllib.request.build_opener(urllib.request.ProxyHandler({}))
    u = (proxy or {}).get("https") or (proxy or {}).get("http") or ""
    if not u:
        return urllib.request.build_opener(urllib.request.ProxyHandler({}))
    return urllib.request.build_opener(
        urllib.request.ProxyHandler({"http": u, "https": u}))


def _encode_url(url: str) -> str:
    """把含中文/空格的 URL 规范成可请求的 ASCII URL（保留已有百分号编码）。

    这是 v2 的关键修复：旧实现直接 `Request(url)`，http.client 用 ascii 编码
    请求行，凡 path/query 含非 ASCII 必抛 UnicodeEncodeError（实测 100%）。
    """
    try:
        parts = urllib.parse.urlsplit(url)
        path = urllib.parse.quote(urllib.parse.unquote(parts.path),
                                  safe="/:@!$&'()*+,;=%")
        query = urllib.parse.quote(urllib.parse.unquote(parts.query),
                                   safe="=&%+")
        return urllib.parse.urlunsplit(
            (parts.scheme, parts.netloc, path, query, ""))
    except Exception:  # noqa: BLE001
        return url


def _decode_body(raw: bytes, content_type: str) -> str:
    """按 Content-Type / meta / BOM 猜编码（UTF-8 / GBK / Big5 / UTF-16）。"""
    ctype = (content_type or "").lower()
    m = re.search(r"charset=?[\"']?([a-z0-9_\-]+)", ctype)
    enc = m.group(1) if m else ""
    if not enc:
        head = raw[:2048]
        m2 = re.search(rb'charset=["\']?([a-zA-Z0-9_\-]+)', head)
        if m2:
            enc = m2.group(1).decode("ascii", "ignore")
    if raw.startswith(b"\xef\xbb\xbf"):
        enc = "utf-8-sig"
    for cand in ([enc] if enc else []) + ["utf-8", "gb18030", "big5",
                                          "shift_jis", "latin-1"]:
        try:
            return raw.decode(cand, errors="strict" if cand == enc else "replace")
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace")


def _http_get_full(url, proxy, timeout=12, referer="", mobile=False):
    """GET 一个页面，返回 (状态码, 解码文本, 最终 URL)。

    2026-11-18：BWIKI 边缘节点会偶发 567/5xx（实测同一 URL 连续请求时出现），
    对这类状态自动退避重试一次；仍失败再向上抛，由调用方降级。
    """
    url = _encode_url(url)
    headers = {
        "User-Agent": UA_MOBILE if mobile else UA,
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
        "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
        "Accept-Encoding": "identity",
    }
    if referer:
        headers["Referer"] = referer
    req = urllib.request.Request(url, headers=headers)
    for attempt in (0, 1):
        try:
            with _opener(proxy).open(req, timeout=timeout) as r:
                raw = r.read()
                ctype = r.headers.get("Content-Type") or ""
                final = r.geturl() or url
                status = getattr(r, "status", 200)
            return status, _decode_body(raw, ctype), final
        except urllib.error.HTTPError as e:
            if attempt == 0 and e.code in (429, 500, 502, 503, 504, 567):
                time.sleep(0.4)
                continue
            raise


def _http_get(url, proxy, timeout=12, referer=""):
    """兼容旧接口：返回 (状态码, 文本)。"""
    code, text, _final = _http_get_full(url, proxy, timeout, referer)
    return code, text


def _http_post_form(url, data, proxy, timeout=12, referer="", extra=None):
    """POST application/x-www-form-urlencoded，返回 (状态码, 解码文本)。

    库街区 wiki 检索只收表单体：实测 JSON body 必 `{"code":500,"msg":"系统异常"}`。
    """
    url = _encode_url(url)
    headers = {
        "User-Agent": UA,
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
        "Accept-Encoding": "identity",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }
    if referer:
        headers["Referer"] = referer
    headers.update(extra or {})
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with _opener(proxy).open(req, timeout=timeout) as r:
            raw = r.read()
            return (getattr(r, "status", 200),
                    _decode_body(raw, r.headers.get("Content-Type") or ""))
    except urllib.error.HTTPError as e:
        return e.code, _decode_body(e.read(), e.headers.get("Content-Type") or "")


def _json_get(url, proxy, timeout=12, referer=""):
    try:
        _code, text, _final = _http_get_full(url, proxy, timeout, referer)
        return json.loads(text)
    except Exception:  # noqa: BLE001
        return {}


def _strip_html(text: str) -> str:
    text = _RE_SCRIPT.sub(" ", text or "")
    text = re.sub(r"<br\s*/?>|</p>|</li>|</h\d>|</div>|</tr>", "\n", text, flags=re.I)
    text = _RE_TAG.sub("", text)
    text = _html.unescape(text)
    text = _RE_WS.sub(" ", text)
    return _RE_ML.sub("\n", text).strip()


def _focus_text(text: str, keywords, limit: int = MAX_FETCH_CHARS) -> str:
    """按关键词位置取正文窗口；关键词都不在时取头部。"""
    text = text or ""
    if len(text) <= limit:
        return text
    for kw in keywords or ():
        kw = (kw or "").strip()
        if len(kw) < 2:
            continue
        idx = text.find(kw)
        if idx >= 0:
            start = max(0, idx - limit // 3)
            end = min(len(text), start + limit)
            head = "…（前文省略）" if start else ""
            tail = "…（后文省略）" if end < len(text) else ""
            return head + "\n" + text[start:end] + tail
    return text[:limit] + ("…（后文省略）" if len(text) > limit else "")


# ============================ Bing ============================
def _bing_url(query, host):
    return f"https://{host}/search?" + urllib.parse.urlencode(
        {"q": query, "count": "8", "setlang": "zh-hans", "mkt": "zh-CN"})


def _ddg_url(query):
    return "https://html.duckduckgo.com/html/?" + urllib.parse.urlencode(
        {"q": query, "kl": "cn-zh"})


def _unwrap_bing_link(url: str) -> str:
    """还原 bing.com/ck/a?...&u=a1<base64> 跳转链为真实地址。"""
    if "bing.com/ck/a" not in (url or ""):
        return url
    try:
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
        u = q.get("u") or ""
        if u.startswith("a1"):
            s = u[2:]
            s += "=" * (-len(s) % 4)
            return base64.urlsafe_b64decode(s).decode("utf-8", "replace")
    except Exception:  # noqa: BLE001
        pass
    return url


def _parse_bing(page):
    """Bing 结果抽取：b_algo 块里的标题/链接/摘要。"""
    out = []
    for m in re.finditer(
            r'<li class="b_algo".*?<h2[^>]*>\s*<a[^>]+href="(?P<u>[^"]+)"'
            r'[^>]*>(?P<t>.*?)</a>(?P<rest>.*?)</li>', page, re.S):
        url = _unwrap_bing_link(_html.unescape(m.group("u")))
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


# ============================ 查询归一化 ============================
def _detect_work(query: str) -> str:
    q = (query or "").lower()
    for work, aliases in WORK_ALIASES.items():
        if any(a.lower() in q for a in aliases):
            return work
    return ""


def _clean_query(query: str, default_work: str = ""):
    """返回 (作品, 核心词)。

    例：'鸣潮 卡提希娅 官方名称' -> ('鸣潮', '卡提希娅')
        '明日方舟 崔林特尔梅之金 官方中文' -> ('明日方舟', '崔林特尔梅之金')
    站内搜索与 Bing 都用核心词——实测带「官方名称」的长 query 会被 Bing 切词
    降级成「鸣」字词典，剥掉后召回率显著提升。
    """
    q = str(query or "").strip()
    work = _detect_work(q) or default_work
    term = q
    # 别名按长度降序替换：先换「战双帕弥什」再换「战双」，否则会留下「帕弥什」。
    aliases_all = sorted(
        (a for aliases in WORK_ALIASES.values() for a in aliases),
        key=len, reverse=True)
    for a in aliases_all:
        term = re.sub(re.escape(a), " ", term, flags=re.I)
    term = _NOISE_RE.sub(" ", term)
    term = re.sub(r"[\s　]+", " ", term).strip(" 　-—:：·、")
    if not term:
        term = q.strip()
    return work, term[:80]


def _is_relevant(term: str, title: str, snippet: str) -> bool:
    """相关性判定：术语整词命中，或 2-gram 覆盖过半。"""
    term = (term or "").strip().lower()
    if not term:
        return True
    hay = ((title or "") + " " + (snippet or "")).lower()
    if term in hay:
        return True
    if len(term) >= 3:
        grams = [term[i:i + 2] for i in range(len(term) - 1)]
        hit = sum(1 for g in grams if g in hay)
        return hit >= max(2, len(grams) // 2)
    return False


def _title_rank(title: str, term: str) -> int:
    """标题与术语的匹配度：完全相等 0 / 前缀 1 / 包含 2 / 其他 3。"""
    t, k = (title or "").lower().strip(), (term or "").lower().strip()
    if not k:
        return 0
    if t == k:
        return 0
    if t.startswith(k):
        return 1
    if k in t:
        return 2
    return 3


def _tier_of(url: str) -> str:
    u = (url or "").lower()
    for tier, domains in _TIER_RULES:
        if any(d in u for d in domains):
            return tier
    return "其他"


# ============================ MediaWiki ============================
def _mw_target(spec, url):
    """从 URL 推导 (api, title)。支持 /w/<title>、/wiki/<title>、/<site>/<title>。"""
    p = urllib.parse.urlsplit(url)
    path = urllib.parse.unquote(p.path or "")
    host = (p.netloc or "").lower()
    if host in _MW_HOSTS:
        api, _page_tpl = _MW_HOSTS[host]
        m = re.match(r"^/(?:w|wiki)/(.*)$", path, re.I)
        title = m.group(1) if m else path.lstrip("/")
        return api, title.strip("/")
    if host == "wiki.biligame.com":
        parts = [x for x in path.split("/") if x]
        site = parts[0] if parts else ""
        title = "/".join(parts[1:]) if len(parts) > 1 else ""
        if site and title:
            return (f"https://wiki.biligame.com/{site}/api.php", title)
    return "", ""


def _clean_wiki_inline(s: str) -> str:
    """把 MediaWiki search snippet 里的 wiki 标记压成可读文本。"""
    s = re.sub(r"<[^>]+>", " ", s or "")
    s = re.sub(r"\[\[(?:文件|File|Image):.*?\]\]", " ", s, flags=re.I)
    s = re.sub(r"\{\{[^{}]*\}\}", " ", s)
    s = re.sub(r"\[\[(?:[^\]|]*\|)?([^\]]+)\]\]", r"\1", s)
    s = re.sub(r"={2,}\s*(.*?)\s*={2,}", r"\1", s)
    s = re.sub(r"[|]+\s*", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _mw_search(api: str, term: str, proxy, timeout: int, referer: str = ""):
    """MediaWiki 站内搜索：返回 [(title, snippet)]，按标题匹配度重排。"""
    url = api + "?" + urllib.parse.urlencode({
        "action": "query", "list": "search", "srsearch": term,
        "srlimit": str(MAX_RESULTS), "format": "json", "formatversion": "2"})
    d = _json_get(url, proxy, timeout, referer=referer)
    raw = (d.get("query") or {}).get("search") or []
    out = [(str(x.get("title") or ""),
            _clean_wiki_inline(str(x.get("snippet") or "")))
           for x in raw if x.get("title")]
    out.sort(key=lambda x: _title_rank(x[0], term))
    return out[:MAX_RESULTS]


def _mw_wikitext(api: str, title: str, proxy, timeout: int, referer: str = "") -> str:
    """取页面源码：优先 parse（注意 BWIKI 会把 wikitext 返回成 {"*": ...}），
    失败回退 revisions；两者都兼容 formatversion=1/2 的两种形态。

    2026-11-18 实测：wiki.biligame.com 的 api.php 必须带
    `Referer: https://wiki.biligame.com/<site>/`，否则返回 HTTP 567。
    """
    url = api + "?" + urllib.parse.urlencode({
        "action": "parse", "page": title, "prop": "wikitext",
        "format": "json", "redirects": "1"})
    d = _json_get(url, proxy, timeout, referer=referer)
    wt = (d.get("parse") or {}).get("wikitext")
    if isinstance(wt, dict):
        wt = wt.get("*") or ""
    if isinstance(wt, str) and wt.strip():
        return wt
    # 回退：prop=revisions（不依赖 parse 的返回形态）
    url2 = api + "?" + urllib.parse.urlencode({
        "action": "query", "prop": "revisions", "titles": title,
        "rvprop": "content", "rvslots": "main",
        "format": "json", "redirects": "1"})
    d2 = _json_get(url2, proxy, timeout, referer=referer)
    pages = (d2.get("query") or {}).get("pages") or []
    if isinstance(pages, dict):
        pages = list(pages.values())
    for p in pages:
        rev = (p.get("revisions") or [{}])[0]
        main = (rev.get("slots") or {}).get("main") or {}
        content = main.get("content") or main.get("*") or rev.get("*") or ""
        if isinstance(content, str) and content.strip():
            return content
    return ""


_FIELD_RE = re.compile(
    r"\|+\s*(名称|中文名|中文译名|官方名|英文名|日文名|韩文名|全名|真名|别名|"
    r"角色名|机体名称|干员名|代号|职业|阵营|所属势力|所属|分类)\s*=\s*([^\n|]{1,80})")


def _flatten_template(inner: str) -> str:
    """长模板（条目主体常写在模板参数里）保留参数值，短模板由调用方删掉。"""
    out = []
    for part in re.split(r"\s*\|+\s*", inner)[1:]:
        if "=" not in part:
            val = part.strip()
        else:
            _key, _val = part.split("=", 1)
            val = _val.strip()
        val = re.sub(r"\[\[(?:[^\]|]*\|)?([^\]]+)\]\]", r"\1", val)
        if len(val) >= 12 and not val.lower().startswith(("http", "#", "{{")):
            out.append(val)
    return "\n" + "\n".join(out) + "\n"


def _wikitext_to_text(wt: str, limit: int = MAX_FETCH_CHARS) -> str:
    """wikitext -> 可读文本：先抽 infobox 高价值字段，再温和剥离标记。

    2026-11-18 实测：BWIKI 的条目正文（鸣潮/终末地）常整段写在长模板参数里，
    前几版「无脑删模板」会把 19k 字符的页面删成 100 字符。这里只删短模板
    （导航/面包屑/样式），长模板改走 _flatten_template 保留参数值。
    """
    fields, seen = [], set()
    for m in _FIELD_RE.finditer(wt or ""):
        k, v = m.group(1), _html.unescape(m.group(2)).strip()
        v = re.sub(r"^\[\[[^\]]*\|", "", v).rstrip("]]").strip()
        if v and "{{" not in v and "}}" not in v and (k, v) not in seen:
            seen.add((k, v))
            fields.append((k, v))
    body = wt or ""
    body = re.sub(r"<!--.*?-->", " ", body, flags=re.S)
    body = re.sub(r"<ref[^>]*>.*?</ref>", " ", body, flags=re.S | re.I)
    body = re.sub(r"<[^>]+>", " ", body)
    body = re.sub(r"\{\|.*?^\s*\|\}", " ", body, flags=re.S | re.M)  # 整块表格
    body = re.sub(r"\{\{#widget:.*?\}\}", " ", body, flags=re.S | re.I)
    body = re.sub(r"\{\{#invoke:.*?\}\}", " ", body, flags=re.S | re.I)

    def _tpl(m):
        inner = m.group(1)
        if "\n" in inner or len(inner) > 300:
            return _flatten_template(inner)
        return " "

    for _ in range(4):
        body = re.sub(r"\{\{([^{}]*)\}\}", _tpl, body)
    body = re.sub(r"\[\[(?:文件|File|Image):.*?\]\]", " ", body, flags=re.I)
    body = re.sub(r"\[\[(?:[^\]|]*\|)?([^\]]+)\]\]", r"\1", body)
    body = re.sub(r"''+", "", body)
    body = re.sub(r"^\s*[|!].*$", "", body, flags=re.M)
    body = re.sub(r"={2,}\s*(.*?)\s*={2,}", r"\n〔\1〕\n", body)
    body = re.sub(r"[ \t]+", " ", body)
    body = re.sub(r"\n{3,}", "\n\n", body).strip()
    head = "；".join(f"{k}：{v}" for k, v in fields[:12])
    text = (head + "\n\n" + body) if head else body
    return text[:limit]


# ============================ fz sitemap 索引 ============================
_FZ_CACHE = {"at": 0.0, "items": []}


def _fz_titles(term: str, proxy, timeout: int, limit: int = MAX_RESULTS):
    """用 fz.wiki 的 sitemap 做标题索引（正文客户端渲染，只有发现能力）。"""
    now = time.time()
    if now - _FZ_CACHE["at"] > 600:
        try:
            _code, xml, _final = _http_get_full(
                "https://www.fz.wiki/sitemap.xml", proxy, timeout)
            items = []
            for loc in re.findall(r"<loc>(.*?)</loc>", xml):
                path = urllib.parse.urlsplit(_html.unescape(loc)).path
                if "/wiki/" in path:
                    title = urllib.parse.unquote(path.split("/wiki/", 1)[1])
                    if title:
                        items.append((title, loc))
            _FZ_CACHE.update({"at": now, "items": items})
        except Exception:  # noqa: BLE001
            _FZ_CACHE["at"] = now  # 失败也记时间，避免每次请求都重试 2MB
    hits = [(t, u) for t, u in _FZ_CACHE["items"] if term.lower() in t.lower()]
    # 同等相关度下短标题优先：避免「技能动作帧/xxx/attack1_projhit」这类子页挤掉主条目
    hits.sort(key=lambda x: (_title_rank(x[0], term), len(x[0])))
    return hits[:limit]


# ============================ 库街区（免密检索） ============================
def _kuro_search(site, term, proxy, timeout, limit=MAX_RESULTS):
    """库街区公开检索，返回 [(标题, 条目URL, 摘要, 来源级别, 站点名)]。

    接口只返回目录卡片（无正文），但 `name` 即官方条目名，足以判定「官方写法」；
    条目 URL 按 SPA 路由 `/{game}/item/{id}` 构造（game：mc=鸣潮 / pns=战双）。
    """
    game = site.get("game") or ("pns" if site.get("wiki_type") == 2 else "mc")
    wiki_type = site.get("wiki_type") or _KURO_WIKI_TYPE.get(game, 9)
    payload = {"keyword": term, "page": 1, "limit": max(int(limit), 10)}
    code, text = _http_post_form(
        _KURO_SEARCH_API, payload, proxy, timeout,
        referer="https://wiki.kurobbs.com/",
        extra={"wiki_type": str(wiki_type), "source": "h5",
               "devcode": uuid.uuid4().hex,
               "Origin": "https://wiki.kurobbs.com"})
    if code >= 400:
        return []
    try:
        data = json.loads(text or "{}")
    except ValueError:
        return []
    if data.get("code") != 200:
        return []
    records = (((data.get("data") or {}).get("results") or {}).get("records") or [])
    main, other = [], []
    for r in records[: limit * 4]:
        name = str(r.get("name") or "").strip()
        rid = r.get("id")
        if not name or rid is None:
            continue
        # 鸣潮按「当前页（首页快捷导航）」十类图鉴分类限定；战双分类 id 体系不同，不套用
        fid, sid = r.get("fid"), r.get("sid")
        if wiki_type == 9 and (fid not in _KURO_HOME_FIDS
                               or sid in _KURO_EXCLUDE_SIDS):
            continue
        card = r.get("content") or {}
        ctype = str(card.get("type") or "")
        if ctype not in _KURO_CARD_TYPES:
            continue
        url = f"https://wiki.kurobbs.com/{game}/item/{rid}"
        bits = []
        star = str(card.get("star") or "").strip()
        if star:
            bits.append(f"{star}星")
        if ctype:
            bits.append(ctype)
        item = (name, url, "｜".join(bits), "官网",
                site.get("name") or "库街区WIKI")
        (main if fid == 1099 else other).append(item)
    main.sort(key=lambda h: _title_rank(h[0], term))
    other.sort(key=lambda h: _title_rank(h[0], term))
    ranked = main + other
    exact = [h for h in ranked if h[0] == term]
    if exact:
        return exact[:3]
    return ranked[:2]


# ============================ 森空岛（免密签名） ============================
def _skland_sign(path, query, ts, key):
    """复刻前端 encodeParams + getSign：md5(hmac_sha256(待签串, token))。

    待签串 = path + (GET 的 query) + timestamp +
              JSON({platform, timestamp, dId, vName})（紧凑、不转义中文）。
    """
    obj = {"platform": "3", "timestamp": ts, "dId": _SKLAND_DID, "vName": "1.0.0"}
    raw = (path + (query or "") + str(ts)
           + json.dumps(obj, separators=(",", ":"), ensure_ascii=False))
    return hashlib.md5(
        hmac.new(key.encode(), raw.encode(), hashlib.sha256).hexdigest().encode()
    ).hexdigest()


def _skland_request(path, params, proxy, timeout, key=""):
    """按森空岛前端规则签名并请求，返回 (状态码, JSON dict)。"""
    ts = str(int(time.time()))
    query = urllib.parse.urlencode(params) if params else ""
    url = _SKLAND_HOST + path + (("?" + query) if query else "")
    headers = {
        "User-Agent": UA,
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "Accept-Encoding": "identity",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "timestamp": ts,
        "sign": _skland_sign(path, query, ts, key),
        "did": _SKLAND_DID,
        "vname": "1.0.0",
        "platform": "3",
        "Referer": "https://wiki.skland.com/",
    }
    req = urllib.request.Request(_encode_url(url), headers=headers)
    try:
        with _opener(proxy).open(req, timeout=timeout) as r:
            raw = r.read()
            return (getattr(r, "status", 200),
                    json.loads(_decode_body(
                        raw, r.headers.get("Content-Type") or "") or "{}"))
    except urllib.error.HTTPError as e:
        return e.code, {}
    except Exception:  # noqa: BLE001
        return 0, {}


def _skland_token(proxy, timeout):
    """取 sign token（公开接口，无需登录）；进程内缓存 1 小时。"""
    now = time.time()
    with _SKLAND_LOCK:
        if (_SKLAND_TOKEN_CACHE["token"]
                and now - _SKLAND_TOKEN_CACHE["at"] < _SKLAND_TOKEN_TTL):
            return _SKLAND_TOKEN_CACHE["token"]
    _code, data = _skland_request("/web/v1/auth/refresh", None, proxy, timeout, "")
    token = str(((data.get("data") or {}).get("token") or ""))
    if token:
        with _SKLAND_LOCK:
            _SKLAND_TOKEN_CACHE.update({"at": now, "token": token})
    return token


def _skland_search(site, term, proxy, timeout, limit=MAX_RESULTS):
    """森空岛公开签名检索，返回 [(标题, 条目URL, 摘要, 来源级别, 站点名)]。"""
    key = _skland_token(proxy, timeout)
    if not key:
        return []
    code, data = _skland_request("/web/v1/wiki/item/search",
                                 {"keyword": term}, proxy, timeout, key)
    if code >= 400 or data.get("code") != 0:
        return []
    items = ((data.get("data") or {}).get("items") or [])
    game = site.get("game") or "endfield"
    out = []
    for it in items[: limit * 3]:
        name = str(it.get("name") or "").strip()
        if not name:
            continue
        main = str((it.get("mainType") or {}).get("name") or "").strip()
        sub = str((it.get("subType") or {}).get("name") or "").strip()
        if sub in _SKLAND_NOISE_SUBTYPES:
            continue
        item_id = it.get("itemId")
        brief = it.get("brief") or {}
        bits = []
        if main:
            bits.append(f"分类：{main}" + (f"/{sub}" if sub else ""))
        elif sub:
            bits.append(f"分类：{sub}")
        desc = str(brief.get("description") or "").strip()
        if desc:
            bits.append(desc[:100])
        url = (f"https://wiki.skland.com/{game}/item/{item_id}"
               if item_id is not None else (site.get("page") or "https://wiki.skland.com/"))
        out.append((name, url, "｜".join(bits), "官网",
                    site.get("name") or "森空岛WIKI"))
    out.sort(key=lambda h: _title_rank(h[0], term))
    exact = [h for h in out if h[0] == term]
    if exact:
        return exact[:3]
    return out[:2]


def _skland_detail(item_id, proxy, timeout, limit=MAX_FETCH_CHARS):
    """取森空岛条目正文（document.documentMap -> 纯文本）。

    documentMap 是 58 个组件文档，每个有独立 blockIds/blockMap；必须按
    blockIds 递归展开（表格文本挂在 cellMap[*].childIds），否则结果是一堆
    乱序的数值碎片。纯数字/百分比如「57%」「RANK 7」丢弃，只留含中文的段落。
    """
    key = _skland_token(proxy, timeout)
    if not key:
        return ""
    _code, data = _skland_request("/web/v1/wiki/item/info",
                                  {"id": str(item_id)}, proxy, timeout, key)
    item = ((data.get("data") or {}).get("item") or {})
    dm = ((item.get("document") or {}).get("documentMap") or {})

    def walk(bid, block_map, depth=0):
        if depth > 6:
            return []
        blk = block_map.get(bid) or {}
        out = []
        if (blk.get("kind") or "") == "text":
            frag = []
            for el in (((blk.get("text") or {}).get("inlineElements") or [])):
                if (el.get("kind") or "") == "text":
                    frag.append(str((el.get("text") or {}).get("text") or ""))
            line = "".join(frag).strip()
            if line:
                out.append(line)
        for cid in (blk.get("childIds") or []):
            out.extend(walk(cid, block_map, depth + 1))
        if (blk.get("kind") or "") == "table":
            for cell in (((blk.get("table") or {}).get("cellMap") or {}).values()):
                for cid in (cell.get("childIds") or []):
                    out.extend(walk(cid, block_map, depth + 1))
        return out

    lines = []
    for d in dm.values():
        block_map = (d or {}).get("blockMap") or {}
        for bid in ((d or {}).get("blockIds") or []):
            lines.extend(walk(bid, block_map))
    kept = [ln for ln in lines
            if len(ln) >= 4 and re.search(r"[\u4e00-\u9fff]", ln)]
    body = re.sub(r"\n{3,}", "\n\n", "\n".join(kept)).strip()
    # 档案/简介通常在各组件的后半段，超长时优先保留尾部
    return body[-limit:] if len(body) > limit else body


# ============================ 搜索 ============================
def _site_hits(work: str, term: str, proxy, timeout: int):
    """站内优先检索：MediaWiki 直查 + fz sitemap 索引 + SPA 的 site: 兜底。"""
    hits = []
    site_timeout = min(int(timeout or 12), 8)   # 站点适配不让单个站拖死整轮
    for site in WORK_SITES.get(work, []):
        kind = site.get("kind")
        try:
            if kind == "mediawiki":
                for title, snip in _mw_search(site["api"], term, proxy,
                                               site_timeout,
                                               site.get("referer", "")):
                    url = site["page"].format(
                        title=urllib.parse.quote(title, safe="/"))
                    hits.append((title, url, snip, "维基", site["name"]))
            elif kind == "fz":
                for title, url in _fz_titles(term, proxy, site_timeout):
                    hits.append((title, url, "", "维基", site["name"]))
            elif kind == "kuro":
                for t, u, s, tier, name in _kuro_search(site, term, proxy,
                                                        site_timeout):
                    hits.append((t, u, s, tier, name))
            elif kind == "skland":
                for t, u, s, tier, name in _skland_search(site, term, proxy,
                                                          site_timeout):
                    hits.append((t, u, s, tier, name))
            elif kind == "spa":
                host = site.get("host") or ""
                if host:
                    # Bing 经常忽略 site: 限定，必须再按域名过滤，
                    # 否则萌娘/Fandom 的结果会被错标成「库街区 WIKI」。
                    for t, u, s in _bing_hits(f"site:{host} {term}", term,
                                              proxy, site_timeout):
                        if _host_key(urllib.parse.urlsplit(u).netloc) == _host_key(host):
                            hits.append((t, u, s, _tier_of(u), site["name"]))
        except Exception:  # noqa: BLE001
            continue
    return hits


def _bing_hits(query: str, term: str, proxy, timeout: int):
    """Bing 两域名 + DDG 兜底；结果做相关性与来源分级。"""
    hits = []
    for host in ("cn.bing.com", "www.bing.com"):
        try:
            _code, page, _final = _http_get_full(
                _bing_url(query, host), proxy, timeout)
            raw = _parse_bing(page)
            if raw:
                hits = raw
                break
        except (urllib.error.URLError, OSError, ValueError):
            continue
    if not hits:
        try:
            _code, page, _final = _http_get_full(
                _ddg_url(query), proxy, min(timeout, DDG_TIMEOUT))
            hits = _parse_ddg(page)
        except Exception:  # noqa: BLE001
            hits = []
    return [(t, u, s) for t, u, s in hits if _is_relevant(term, t, s)]


def _dedupe(hits):
    out, seen_url, seen_title = [], set(), set()
    for h in hits:
        title, url = str(h[0] or "").strip(), str(h[1] or "").strip()
        key_u = re.sub(r"^https?://(www\.)?", "", url).rstrip("/").lower()
        key_t = title.lower()
        if not title or key_u in seen_url or key_t in seen_title:
            continue
        seen_url.add(key_u)
        seen_title.add(key_t)
        out.append(h)
    return out


def _format_results(query, work, term, hits):
    if not hits:
        return (f"搜索「{query}」（核心词：{term}）没有可用结果；"
                "请勿据此臆改。")
    head = (f"搜索「{query}」（核心词：{term}"
            + (f"｜作品：{work}" if work else "")
            + f"）共 {len(hits)} 条，按来源可信度排序（只读证据，禁止照抄进字幕）：")
    lines = [head]
    for i, (t, u, s, tier, src) in enumerate(hits, 1):
        # 站内命中标注「级别·站点」，Bing 命中只标级别（站点名对模型无信息量）
        tag = f"{tier}·{src}" if src and src not in (tier, "Bing") else tier
        lines.append(f"{i}. [{tag}] {t}\n   链接：{u}")
        if s:
            lines.append(f"   摘要：{s}")
    return "\n".join(lines)


# ============================ 抓取 ============================
def _fetch_mediawiki(spec, url, proxy, timeout):
    api, title = _mw_target(spec, url)
    if not api:
        api = spec.get("api") or ""
    if not title:
        return "", ""
    wt = _mw_wikitext(api, title, proxy, timeout, spec.get("referer", ""))
    if not wt:
        return "", ""
    body = _wikitext_to_text(wt)
    return (f"【{spec.get('name') or '维基'}｜页面「{title}」wikitext 摘录】\n"
            + body), url


def _fetch_html(url, spec, proxy, timeout, keywords):
    mobile = (spec or {}).get("kind") == "spa"
    code, text, final = _http_get_full(
        url, proxy, timeout, referer=(spec or {}).get("referer", ""),
        mobile=mobile)
    title_m = _RE_TITLE.search(text or "")
    page_title = _html.unescape(title_m.group(1)).strip() if title_m else ""
    desc_m = _RE_META.search(text or "")
    desc = _html.unescape(desc_m.group(1)).strip() if desc_m else ""
    body = _strip_html(text or "")
    body = _focus_text(body, keywords)
    kind = (spec or {}).get("kind")
    if len(body) < _RENDER_SHELL_CHARS and kind in ("spa", "fz", "kuro", "skland"):
        return (f"【{(spec or {}).get('name') or '站点'}｜客户端渲染站】\n"
                f"页面标题：{page_title or '（未取到）'}\n"
                f"站点描述：{desc or '（无）'}\n"
                "说明：该站正文由浏览器端脚本渲染，静态抓取只能拿到标题/描述，"
                "不构成条目正文证据；如需正文请在浏览器打开链接人工核对。"), final
    head = f"【{(spec or {}).get('name') or '页面'}｜{page_title or url}】"
    if desc:
        head += f"\n站点描述：{desc[:200]}"
    return head + "\n" + body, final


def _host_key(host: str) -> str:
    h = (host or "").lower()
    return h[4:] if h.startswith("www.") else h


def _site_of(url):
    host = _host_key(urllib.parse.urlsplit(url).netloc or "")
    # BWIKI 一个域名挂多个站（/wutheringwaves、/arknights、/zspms），
    # 必须先按路径段区分，否则战双页会被标成「BWIKI·鸣潮」。
    if host == "wiki.biligame.com":
        path = urllib.parse.urlsplit(url).path or ""
        m = re.match(r"^/([^/]+)/", path)
        site = m.group(1) if m else ""
        for sites in WORK_SITES.values():
            for s in sites:
                if site and f"/{site}/api.php" in (s.get("api") or ""):
                    return s
        return {"kind": "mediawiki", "name": "BWIKI"}
    for sites in WORK_SITES.values():
        for s in sites:
            if s.get("host") and host == s["host"]:
                return s
            api = s.get("api") or ""
            if api and _host_key(urllib.parse.urlsplit(api).netloc) == host:
                return s
            page = s.get("page") or ""
            if page and _host_key(urllib.parse.urlsplit(page).netloc) == host:
                return s
    if host in _MW_HOSTS:
        api, page = _MW_HOSTS[host]
        return {"kind": "mediawiki", "name": host,
                "api": api, "page": page,
                "referer": f"https://{host}/"}
    return None


# ============================ 对外工具工厂 ============================
def make_tools(proxy=None, log=None, timeout=12, work=""):
    """返回 {"search": fn(query)->str, "fetch": fn(url)->str}。

    proxy: None 或 callable→(None|dict)（engine.ai_proxy_for_requests）。
    每次调用现取代理快照：内置代理可能在长跑中途才拉起。
    work:  片源作品（鸣潮/明日方舟/终末地/战双…），用于站内优先检索；
           为空时从 query 里自动识别。
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

    def _say(msg, level="dim"):
        try:
            _log(msg, level)
        except TypeError:
            _log(msg)

    def search(query):
        query = str(query or "").strip()[:160]
        if not query:
            return "查询失败：query 为空"
        cur_work, term = _clean_query(query, work)
        key = ("s", cur_work, term)
        with lock:
            if key in cache:
                return cache[key]
        hits = []
        try:
            hits = _site_hits(cur_work, term, _proxy(), timeout)
            if hits:
                _say(f"  · 站内检索「{term}」命中 {len(hits)} 条"
                     f"（{cur_work or '通用'}）", "dim")
        except Exception as e:  # noqa: BLE001
            _say(f"  · 站内检索失败：{type(e).__name__}", "dim")
        try:
            q = f"{cur_work} {term}".strip() if cur_work else term
            bing = _bing_hits(q, term, _proxy(), timeout)
            for t, u, s in bing:
                hits.append((t, u, s, _tier_of(u), "Bing"))
        except Exception as e:  # noqa: BLE001
            _say(f"  · Bing 检索失败：{type(e).__name__}", "dim")
        hits = _dedupe(hits)
        hits.sort(key=lambda h: (_TIER_ORDER.get(h[3], 4),
                                 _title_rank(h[0], term)))
        hits = hits[:MAX_TOTAL_HITS]
        text = (_format_results(query, cur_work, term, hits) if hits else
                f"搜索「{query}」（核心词：{term}）失败"
                "（网络不通或全部引擎无结果），请勿臆改。")
        with lock:
            cache[key] = text
        return text

    def fetch(url):
        url = str(url or "").strip()
        if not re.match(r"^https?://", url):
            return "抓取失败：只允许 http/https 链接"
        url = _unwrap_bing_link(url)
        key = ("f", url[:300])
        with lock:
            if key in cache:
                return cache[key]
        text = ""
        try:
            spec = _site_of(url)
            keywords = []
            path = urllib.parse.unquote(urllib.parse.urlsplit(url).path)
            for seg in path.split("/"):
                if len(seg) >= 2 and not re.search(r"\.(?:php|html?|js|css)$", seg):
                    keywords.append(seg)
            # 森空岛条目：公开签名接口能直接给正文（documentMap），不必抓 SPA 壳
            m_sk = re.match(
                r"https://wiki\.skland\.com/[^/]+/item/(\d+)", url)
            if m_sk:
                body = _skland_detail(m_sk.group(1), _proxy(), timeout)
                if body:
                    text = "【森空岛WIKI｜条目正文（公开接口）】\n" + body
            if not text and spec and spec.get("kind") == "mediawiki":
                text, _final = _fetch_mediawiki(spec, url, _proxy(), timeout)
            if not text:
                text, final = _fetch_html(url, spec, _proxy(), timeout, keywords)
                text = f"页面 {final}\n" + text if text else ""
            if not text:
                text = f"页面 {url} 没有可提取正文。"
        except Exception as e:  # noqa: BLE001
            text = f"抓取 {url} 失败：{type(e).__name__}: {str(e)[:120]}"
        with lock:
            cache[key] = text
        return text

    return {"search": search, "fetch": fetch}


if __name__ == "__main__":  # 手工连通性小样（不走缓存，仅调试用）
    tools = make_tools(work="鸣潮")
    print(tools["search"]("鸣潮 卡提希娅 官方名称"))
