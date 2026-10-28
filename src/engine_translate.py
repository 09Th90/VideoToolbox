# @version 2.8.0
"""字幕机翻（自研，替代 videocaptioner.core.translate.* 翻译器实现）。

P1 接缝之一：把第三方引擎的三个免费翻译器（微软 / 谷歌 / DeepLx）的公开
行为迁到本项目自有模块，使本项目不再持有第三方源码副本。

为什么这一项比其它接缝更硬
--------------------------
引擎的翻译器不是「只 import 不改」——本项目历史上把**改写后的引擎源码
逐字节归档**进 ``docs/vc_translate_impl/``（6 个文件，与引擎侧 sha1 完全
一致），再由 ``scripts/dev/apply_vc_official.py`` 回写覆盖引擎。
这意味着仓库里躺着一份第三方 GPL 源码的完整副本，且安装包会分发它
（``packaging/视频工具箱.iss`` 有对应 ``Source:`` 行）。它是本项目持有
第三方源码的**唯一显式副本**，比「打包时顺带收进去」更难在 P5 阶段清掉。

编写依据
--------
按规格风险约束 1，本模块基于**接口契约 + 可观察行为**编写，未复制第三方
实现：

* 接口契约：类名 ``BingTranslator`` / ``GoogleTranslator`` / ``DeepLxTranslator``、
  构造签名 ``(thread_num, batch_num, target_language, update_callback)``、
  覆写点 ``_translate_chunk(chunk) -> chunk`` 与 ``_get_cache_key(chunk)``、
  失败条目标 ``"ERROR"``（上层据此改用 LLM 重做）；
* 可观察行为：端点、请求头形状、批量数组请求、响应顺序一一对应、错误标记。
  2026-10-13 实测（``scripts/dev/_selftest_engine_translate.py`` 联网项）：
  微软 Edge 端点直连 200、批量 2 条顺序正确、6000 字符不截断（端点侧上限
  远高于 5000，故仍按 5000 截断以贴合既有行为）、空数组返回 400。

实测得到的可观察事实（写在此处以免后人重测）
------------------------------------------
* 微软：``POST https://edge.microsoft.com/translate/translatetext?to=<lang>&api-version=3.0``，
  body 为 JSON 字符串数组，**直连可用**（不读系统代理）。
* 谷歌：``translate.googleapis.com/translate_a/single`` 在本机网络下**不可用**
  （历史实测 421；规格第二节亦已记载「此路径本就不通」）。因此谷歌翻译器
  默认直接判定不可用、不发请求，避免每个字幕块白等一个超时。
* DeepLx：``POST https://api.deeplx.org/translate``，请求 ``{"text": [...]}``、
  取 ``translations``；公开实例不稳定，失败按 ``ERROR`` 标记交上层兜底。

设计约束
--------
1. **零第三方依赖**（仅 ``requests``，项目本就依赖）。
2. **会话路由显式**（``trust_env=False`` + 显式 proxies）：跟随系统代理会
   把「直连可用」的微软端点也塞进代理，是历史上踩过的坑。
3. **失败必须显式标记**：翻译失败绝不静默回落成原文——那会让用户以为
   「翻译了但结果没变」，比报错更难排查。
4. **键与引擎一致**：``_get_cache_key`` 的构造形式保持
   ``f"{class_name}:{chunk_key}:{lang}"``，否则既有缓存全部失效。
"""

from __future__ import annotations

import threading

__all__ = [
    "BaseSubtitleTranslator",
    "BingTranslator",
    "GoogleTranslator",
    "DeepLxTranslator",
    "TRANSLATOR_PROBES",
    "probe_translator",
    "make_translator",
    "ERROR_MARK",
]

#: 失败条目的统一标记。上层 ``BaseTranslator`` 据此识别失败并改用 LLM 重做，
#: 界面上呈现为需要重试，而不是「翻译成功但内容没变」。
ERROR_MARK = "ERROR"

#: 单条文本上限（贴合引擎既有行为；实测端点可接受更长，但截断可避免
#: 超长单条导致的响应体异常）。
MAX_CHARS_PER_ITEM = 5000


def _chunk_texts(chunk):
    """取 chunk 内各条原文（并做长度截断）。"""
    return [(getattr(d, "original_text", "") or "")[:MAX_CHARS_PER_ITEM]
            for d in chunk]


def _mark_error(chunk, reason=""):
    """把整个 chunk 标为失败。绝不保留原文冒充译文。"""
    for d in chunk:
        try:
            d.translated_text = ERROR_MARK
        except Exception:  # noqa: BLE001
            pass
    return chunk


def _chunk_target_name(chunk):
    """取目标语言标签（枚举对象的 ``.value``）。"""
    tl = getattr(chunk, "target_language", None)
    if tl is None and chunk:
        tl = getattr(chunk[0], "target_language", None)
    return getattr(tl, "value", str(tl)) if tl is not None else ""


class BaseSubtitleTranslator:
    """翻译器基类：会话、超时、目标语言代码解析、缓存键。

    子类只需实现 :meth:`_translate_chunk`。
    """

    #: 端点（子类覆盖）
    endpoint = ""
    #: 端点是否直连可用（False 时 :func:`probe_translator` 直接判不可用）
    direct_ok = True
    #: 超时秒数
    timeout = 20

    def __init__(self, thread_num=1, batch_num=1, target_language=None,
                 update_callback=None):
        self.thread_num = int(thread_num or 1)
        self.batch_num = int(batch_num or 1)
        self.target_language = target_language
        self.update_callback = update_callback
        self.session = self._make_session()
        self.headers = dict(self._default_headers())

    # ---------- 会话 ----------
    @staticmethod
    def _make_session():
        import requests
        s = requests.Session()
        # 关键：不读环境/系统代理。微软端点直连可用，塞进代理只会变慢或失败。
        s.trust_env = False
        s.proxies = {}
        return s

    @staticmethod
    def _default_headers():
        return {
            "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) "
                           "Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0"),
            "Origin": "https://www.microsoft.com",
            "Referer": "https://www.microsoft.com/",
        }

    # ---------- 目标语言 ----------
    #: 标签 → 端点语言代码。取值为**协议事实**（端点接受的代码），非创作。
    lang_map = {}

    def _target_lang_code(self):
        """目标语言代码：先查本类映射，再走全局映射表。"""
        name = getattr(self.target_language, "value", str(self.target_language))
        if name in self.lang_map.values():
            return name
        code = self.lang_map.get(name)
        if code:
            return code
        from engine_entities import LANGUAGES
        return LANGUAGES.get(name, "zh-Hans")

    # ---------- 覆写点 ----------
    def _translate_chunk(self, chunk):
        raise NotImplementedError

    def _get_cache_key(self, chunk):
        """缓存键：``类名:内容哈希:目标语言``（与引擎构造形式一致）。"""
        from engine_cache import generate_cache_key
        name = getattr(self.target_language, "value", str(self.target_language))
        return "%s:%s:%s" % (type(self).__name__, generate_cache_key(chunk),
                             name)

    # ---------- 对外 ----------
    def translate(self, chunk):
        """翻译一个 chunk（就地写 ``translated_text`` 并返回同一对象）。"""
        if not chunk:
            return chunk
        try:
            return self._translate_chunk(chunk)
        except Exception:  # noqa: BLE001
            # 兜底：任何未预期异常都要变成显式失败，不能让上层拿到半成品
            return _mark_error(chunk)

    def probe(self, sample="ok"):
        """探测端点可用性。返回 ``(是否可用, 说明)``。

        ``direct_ok=False`` 的实现（谷歌）直接短路返回，不发请求——本机网络
        下该端点必然失败，发请求只会让每个字幕块白等一个超时。
        """
        if not self.direct_ok:
            return False, "该端点在本机网络下不可用（已跳过探测）"
        if not self.endpoint:
            return False, "未配置端点"
        try:
            data = self._probe_payload(sample)
            r = self.session.post(
                self.endpoint, params=self._probe_params(),
                json=data, headers=self._probe_headers(), timeout=10)
            return (r.status_code == 200, "HTTP %d" % r.status_code)
        except Exception as e:  # noqa: BLE001
            return False, "%s: %s" % (type(e).__name__, str(e)[:80])

    # 探测用钩子（子类可覆盖）
    def _probe_params(self):
        return {"to": self._target_lang_code(), "api-version": "3.0"}

    def _probe_headers(self):
        return self.headers

    def _probe_payload(self, sample):
        return [sample]


class BingTranslator(BaseSubtitleTranslator):
    """微软翻译（Edge 页面翻译使用的免认证端点）。

    协议（2026-10-13 实测）：
      ``POST https://edge.microsoft.com/translate/translatetext``
      ``?to=<code>&api-version=3.0``，body 为 JSON 字符串数组；
      返回 JSON 数组与请求**顺序一一对应**，每项 ``translations[0].text``；
      直连可用。空数组会得到 400（故调用前必须判空）。
    """

    endpoint = "https://edge.microsoft.com/translate/translatetext"
    direct_ok = True

    #: 中文/英文标签 → 端点代码。中英双语标签都要收：历史 settings.json
    #: 两种写法都出现过。
    lang_map = {
        "简体中文": "zh-Hans", "繁体中文": "zh-Hant",
        "英语": "en", "日本語": "ja", "韩语": "ko", "粤语": "yue",
        "法语": "fr", "德语": "de", "西班牙语": "es", "俄语": "ru",
        "葡萄牙语": "pt", "土耳其语": "tr",
        "Chinese": "zh-Hans", "English": "en", "Japanese": "ja",
        "Korean": "ko", "French": "fr", "German": "de", "Russian": "ru",
        "Spanish": "es",
    }

    def _translate_chunk(self, chunk):
        texts = _chunk_texts(chunk)
        if not texts:
            return chunk
        r = self.session.post(
            self.endpoint,
            params={"to": self._target_lang_code(), "api-version": "3.0"},
            json=texts, headers=self.headers, timeout=self.timeout)
        r.raise_for_status()
        results = r.json()
        if not isinstance(results, list) or len(results) != len(chunk):
            # 条数不匹配 ⇒ 不能按 zip 配对，否则译文会整体错位（比报错更糟）
            return _mark_error(chunk, "条数不匹配")
        for data, item in zip(chunk, results):
            try:
                data.translated_text = item["translations"][0]["text"]
            except (KeyError, IndexError, TypeError):
                data.translated_text = ERROR_MARK
        return chunk


class GoogleTranslator(BaseSubtitleTranslator):
    """谷歌翻译（本机网络下不可用，默认短路）。

    历史实测：``translate.googleapis.com/translate_a/single`` 在本机返回
    421。保留实现是为了兼容「网络可用」的其他部署环境，但 ``direct_ok``
    为 False ⇒ 探测与实际翻译都直接短路，不浪费时间在不通的端点上。
    """

    endpoint = "https://translate.googleapis.com/translate_a/single"
    direct_ok = False

    lang_map = {
        "简体中文": "zh-CN", "繁体中文": "zh-TW", "英语": "en",
        "日本語": "ja", "韩语": "ko", "粤语": "yue", "法语": "fr",
        "德语": "de", "西班牙语": "es", "俄语": "ru",
        "Chinese": "zh-CN", "English": "en", "Japanese": "ja",
        "Korean": "ko", "French": "fr", "German": "de", "Spanish": "es",
        "Russian": "ru",
    }

    def _translate_chunk(self, chunk):
        # 端点不可用 ⇒ 全部标失败，交上层兜底（LLM / 提示换服务）
        return _mark_error(chunk, "谷歌端点在本机网络下不可用")

    def probe(self, sample="ok"):
        return False, "该端点在本机网络下不可用（421，历史实测）"


class DeepLxTranslator(BaseSubtitleTranslator):
    """DeepLx 翻译。

    协议：``POST https://api.deeplx.org/translate``，
    body ``{"text": [...]}``，响应取 ``translations``（顺序一一对应）。
    公开实例稳定性差，失败按 ``ERROR`` 标记交上层兜底。
    """

    endpoint = "https://api.deeplx.org/translate"
    direct_ok = True
    timeout = 20

    lang_map = {
        "简体中文": "ZH", "繁体中文": "ZH", "英语": "EN",
        "日本語": "JA", "韩语": "KO", "粤语": "ZH", "法语": "FR",
        "德语": "DE", "西班牙语": "ES", "俄语": "RU",
        "葡萄牙语": "PT", "土耳其语": "TR",
        "Chinese": "ZH", "English": "EN", "Japanese": "JA",
        "Korean": "KO", "French": "FR", "German": "DE", "Spanish": "ES",
        "Russian": "RU",
    }

    @staticmethod
    def _default_headers():
        return {
            "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) "
                           "Chrome/131.0.0.0 Safari/537.36"),
            "Content-Type": "application/json",
        }

    def _translate_chunk(self, chunk):
        texts = _chunk_texts(chunk)
        if not texts:
            return chunk
        r = self.session.post(self.endpoint, json={"text": texts},
                              headers=self.headers, timeout=self.timeout)
        r.raise_for_status()
        data = r.json()
        out = data.get("translations") if isinstance(data, dict) else None
        if not isinstance(out, list) or len(out) != len(chunk):
            return _mark_error(chunk, "响应格式不符")
        for item, translated in zip(chunk, out):
            item.translated_text = translated if isinstance(translated, str) \
                else ERROR_MARK
        return chunk

    def _probe_payload(self, sample):
        return {"text": [sample]}

    def _probe_params(self):
        return {}


#: 服务标签 → 实现类。标签沿用 ``engine_entities.TranslatorServiceEnum`` 的
#: 取值（微软翻译 / 谷歌翻译 / DeepLx 翻译），保证与既有配置一一对应。
TRANSLATOR_PROBES = {
    "微软翻译": BingTranslator,
    "谷歌翻译": GoogleTranslator,
    "DeepLx 翻译": DeepLxTranslator,
}

_BY_CODE = {
    "bing": BingTranslator,
    "google": GoogleTranslator,
    "deeplx": DeepLxTranslator,
}


def make_translator(kind, thread_num=1, batch_num=1, target_language=None,
                    update_callback=None):
    """按服务标签或简码构造翻译器。未知标签抛 ``KeyError``。"""
    cls = TRANSLATOR_PROBES.get(kind) or _BY_CODE.get(str(kind).lower())
    if cls is None:
        raise KeyError("未知翻译服务: %r（可用: %s）"
                       % (kind, ", ".join(sorted(TRANSLATOR_PROBES))))
    return cls(thread_num=thread_num, batch_num=batch_num,
               target_language=target_language,
               update_callback=update_callback)


def probe_translator(kind, target_language=None):
    """探测某个服务的端点可用性。返回 ``(是否可用, 说明)``。"""
    try:
        t = make_translator(kind, target_language=target_language)
    except KeyError as e:
        return False, str(e)
    return t.probe()


#: 探测缓存（端点可用性在一次会话内不变，避免重复等超时）
_PROBE_CACHE = {}
_PROBE_LOCK = threading.Lock()


def probe_translator_cached(kind, target_language=None, force=False):
    """带缓存的探测。返回 ``(是否可用, 说明)``。"""
    with _PROBE_LOCK:
        if not force and kind in _PROBE_CACHE:
            return _PROBE_CACHE[kind]
    ok, why = probe_translator(kind, target_language)
    with _PROBE_LOCK:
        _PROBE_CACHE[kind] = (ok, why)
    return ok, why
