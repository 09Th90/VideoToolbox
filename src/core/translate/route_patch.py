# -*- coding: utf-8 -*-
# @version 2.5.1
"""翻译请求路由补丁（v2.3.1 拆分工程 · 自 video_toolbox.py 原样搬入）。

2026-10-17 增强（用户在途）：双重保险——除 __init__ 外再包一层
translate_subtitle，治「实例早于补丁存在」导致的 trust_env 遗留。

2026-10-18 增强（用户报「527/527 segments failed，请检查 API key」）：
新增 :func:`vc_translate_no_llm_patch`——字幕翻译**全面去 AI 的运行期保险**。
用户看到的失败文案「Check your API key and network connection」是引擎
``BaseTranslator`` 的通用文案，而机翻（谷歌/微软/DeepLx）根本不读 API key；
叠加设置页「翻译服务」下拉里残留的「LLM 大模型翻译」选项（清理代码取的
属性名 ``translateServiceCard`` 在两个设置界面里都不存在，实际叫
``translatorServiceCard``，导致该项从未被移除），用户一旦选中它，翻译就会
真去调全局 AI 密钥——那才是「AI 接进翻译」的设计漏洞。本补丁在翻译器
创建的唯一收口处把 LLM 服务归一为机翻，并把机翻失败文案改成如实描述。
"""
import os
import re
import time

from core.shared.log import _vc_log
from core.shared.proxy import translate_session_proxies

#: 机翻翻译器类名（这些失败与 API 密钥无关，文案不得让用户去查密钥）。
#: 实际判据用 :func:`_is_mt_translator` 的 isinstance（覆盖子类），此常量仅作文档。
_MT_TRANSLATOR_CLASSES = ("BingTranslator", "GoogleTranslator", "DeepLXTranslator")

#: 引擎翻译服务枚举里「LLM 大模型翻译」的值。v1.12.0 起字幕翻译板块仅机翻；
#: 与 ``core.asr.patches.TS_LLM`` 同值——translate 域不准依赖 asr 域，故本地定义。
_TS_LLM_VALUE = "LLM 大模型翻译"

#: 引擎机翻失败文案里「让用户查 API key」的尾巴（``base._parallel_translate``）。
_API_KEY_TAIL = "Check your API key and network connection."

#: 失败计数形态：``Translation failed: 527/527 segments failed (100%)``
_MT_FAIL_RE = re.compile(
    r"Translation failed:\s*(\d+)\s*/\s*(\d+)\s+segments failed\s*\((\d+)%\)")

#: 机翻失败时给用户的实话：翻译是纯机翻，没有密钥可查。
_MT_FAIL_HINT = ("字幕翻译只使用机器翻译（谷歌 / 微软 / DeepLx），不涉及 AI 密钥；"
                 "请检查网络或代理后重试，或在「字幕处理 → 设置 → 翻译服务」"
                 "更换翻译服务。")

#: 机翻类元组的进程内缓存（惰性导入，避免补丁挂载时强拖引擎翻译模块）。
_MT_CLASSES_CACHE = []

#: 翻译缓存降级日志只打一次（缓存坏了每块都报会刷屏）
_CACHE_DEGRADED = {"logged": False}


class _SafeTranslatorCache:
    """翻译缓存兜底代理：缓存坏了只降级为「不缓存」，绝不让整批翻译失败。

    2026-10-18 21:26 实证：``data\\videocaptioner\\cache\\translate_results\\
    cache.db`` 损坏（``database disk image is malformed``），引擎
    ``_safe_translate_chunk`` 只给 ``get`` 包了 try，**``set`` 在 try 之外**
    ——译文其实已经翻好，写缓存一抛异常整个 chunk 就被判失败，66 条全部丢弃，
    界面显示「66/66 条未拿到译文」。缓存是加速器，不是正确性的一部分。
    """

    def __init__(self, inner):
        self._inner = inner

    def _degrade(self, op, exc):
        try:
            if not _CACHE_DEGRADED["logged"]:
                _CACHE_DEGRADED["logged"] = True
                _vc_log("翻译缓存不可用（%s 失败：%s），已改为不缓存继续翻译"
                        "（建议清掉 data\\videocaptioner\\cache\\translate_results）"
                        % (op, str(exc)[:100]))
        except Exception:  # noqa: BLE001
            pass

    def get(self, *args, **kwargs):
        try:
            return self._inner.get(*args, **kwargs)
        except Exception as e:  # noqa: BLE001
            self._degrade("get", e)
            return kwargs.get("default", args[1] if len(args) > 1 else None)

    def set(self, *args, **kwargs):
        try:
            return self._inner.set(*args, **kwargs)
        except Exception as e:  # noqa: BLE001
            self._degrade("set", e)
            return False

    def delete(self, *args, **kwargs):
        try:
            return self._inner.delete(*args, **kwargs)
        except Exception as e:  # noqa: BLE001
            self._degrade("delete", e)
            return False

    def __getattr__(self, name):
        return getattr(self._inner, name)


def _patch_translate_cache_safety():
    """给所有翻译器的 ``self._cache`` 套上 _SafeTranslatorCache（幂等）。"""
    from videocaptioner.core.translate.base import BaseTranslator
    if getattr(BaseTranslator, "_vt_cache_safe_patched", False):
        return False
    orig_init = BaseTranslator.__init__

    def _init(self, *a, **kw):
        orig_init(self, *a, **kw)
        try:
            cache = getattr(self, "_cache", None)
            if cache is not None and not isinstance(cache, _SafeTranslatorCache):
                self._cache = _SafeTranslatorCache(cache)
        except Exception as e:  # noqa: BLE001
            _vc_log(f"翻译缓存降级代理挂载失败（按原缓存继续）：{e}")

    BaseTranslator.__init__ = _init
    BaseTranslator._vt_cache_safe_patched = True
    return True


def _heal_corrupt_caches():
    """启动自检：翻译/ASR 缓存 SQLite 损坏则挪走重建（缓存可抛弃）。

    2026-10-18 实证：``translate_results/cache.db`` 损坏
    （``database disk image is malformed``），引擎写缓存时整 chunk 被判失败、
    译文全丢。缓存是加速器，坏了就重建——挪到同目录 ``*.corrupt-<时间戳>``
    （不删，保留现场），引擎下次使用会自建新库。启动期跑，此时引擎的惰性
    缓存还没打开文件，挪得动。
    """
    import sqlite3
    try:
        from core.shared.runtime import vc_data_dir
        root = os.path.join(str(vc_data_dir()), "cache")
    except Exception:  # noqa: BLE001
        return False
    healed = []
    for sub in ("translate_results", "asr_results"):
        d = os.path.join(root, sub)
        db = os.path.join(d, "cache.db")
        if not os.path.isfile(db):
            continue
        status = ""
        try:
            # 只读打开：绝不对「可能正被另一个进程持有」的库做任何写操作
            uri = "file:%s?mode=ro" % str(db).replace("\\", "/")
            con = sqlite3.connect(uri, uri=True, timeout=3)
            try:
                row = con.execute("PRAGMA quick_check").fetchone()
            finally:
                con.close()
            status = str((row or ("",))[0])
        except Exception as e:  # noqa: BLE001
            status = "open-failed: %s" % e
        if status.strip().lower() == "ok":
            continue
        stamp = time.strftime("%Y%m%d_%H%M%S")
        moved = failed = 0
        for name in ("cache.db", "cache.db-wal", "cache.db-shm"):
            p = os.path.join(d, name)
            if os.path.isfile(p):
                try:
                    os.replace(p, p + ".corrupt-" + stamp)
                    moved += 1
                except OSError as e:
                    failed += 1
                    _vc_log("损坏缓存挪走失败（%s/%s）：%s" % (sub, name, e))
        healed.append("%s（%s，%s）" % (
            sub, status[:40],
            "已挪走 %d 个文件" % moved if not failed else
            "挪走失败（进程占用，重启后再试）"))
    if healed:
        _vc_log("缓存自检：%s —— 引擎下次使用会重建（译文/转录自动重算）"
                % "；".join(healed))
    return True


def _mt_classes():
    """机翻翻译器类元组（Bing / Google / DeepLX；引擎不可导入时返回空）。"""
    if _MT_CLASSES_CACHE:
        return _MT_CLASSES_CACHE[0]
    classes = []
    try:
        from videocaptioner.core.translate.bing_translator import BingTranslator
        classes.append(BingTranslator)
        from videocaptioner.core.translate.google_translator import GoogleTranslator
        classes.append(GoogleTranslator)
        from videocaptioner.core.translate.deeplx_translator import DeepLXTranslator
        classes.append(DeepLXTranslator)
    except Exception:  # noqa: BLE001
        pass
    _MT_CLASSES_CACHE.append(tuple(classes))
    return _MT_CLASSES_CACHE[0]


def _is_mt_translator(translator) -> bool:
    """是否机翻翻译器（isinstance，覆盖子类；LLMTranslator 不在其中）。"""
    classes = _mt_classes()
    return bool(classes) and isinstance(translator, classes)


def _patch_translator_route(mod, cls_name):
    """给某个翻译器类上**双重**保险：`__init__` 包一层 + `translate_subtitle` 包一层。

    为什么不能只包 `__init__`（2026-10-17 实测教训）：
    补丁只影响**之后创建**的实例。若引擎在 GUI 启动早期（补丁挂载前）就
    建好了 translator 实例，那个实例的 session 仍是默认的
    `trust_env=True` → 跟随环境变量里的 `https_proxy`（本机 IDE 代理
    127.0.0.1:14901，对微软/国内站点一律不通）→ 全部片段失败。
    用户看到的是「Translation failed: 252/252 segments failed (100%)」，
    而那个时候 BingTranslator 明明已经被「补丁已挂」的日志覆盖过——
    坑就在于实例早于补丁存在。

    故 `translate_subtitle` 也包一层：**每次翻译前**重新钉死路由，
    无论实例何时创建都有效；同时若发现 `trust_env` 仍为 True（说明该实例
    绕过了构造补丁），往日志里写一条，让这类问题以后有迹可循。
    """
    cls = getattr(mod, cls_name, None)
    if cls is None or getattr(cls, "_vt_route_patched", False):
        return False
    orig_init = cls.__init__

    def _pin_route(self):
        """把 session 路由钉死；返回是否发生了修正（用于日志）。"""
        session = getattr(self, "session", None)
        if session is None:
            return False
        fixed = False
        if getattr(session, "trust_env", False):
            session.trust_env = False      # 关键：不读环境/系统代理
            fixed = True
        want = translate_session_proxies(getattr(self, "endpoint", ""))
        if getattr(session, "proxies", None) != want:
            session.proxies = want
            fixed = True
        return fixed

    def _route_snapshot(self):
        """路由快照：端点 / session 状态 / 代理环境变量（排障用，一次性写盘）。

        2026-10-17 用户报「252/252 segments failed」，静态排查全绿却无法解释，
        缺的就是这份现场。现在每次翻译前落一条，失败时直接对照。
        """
        try:
            ep = str(getattr(self, "endpoint", "") or "")
            s = getattr(self, "session", None)
            envs = {k: os.environ.get(k) for k in
                    ("https_proxy", "HTTPS_PROXY", "http_proxy", "HTTP_PROXY",
                     "ALL_PROXY", "all_proxy") if os.environ.get(k)}
            _vc_log("翻译路由快照（%s）：endpoint=%s｜trust_env=%s｜proxies=%r｜"
                    "代理环境变量=%s"
                    % (cls_name, ep[:60],
                       getattr(s, "trust_env", "<无session>"),
                       getattr(s, "proxies", "<无session>"),
                       envs or "无"))
        except Exception:  # noqa: BLE001
            pass

    def _init(self, *a, **kw):
        orig_init(self, *a, **kw)
        try:
            if _pin_route(self):
                _route_snapshot(self)
        except Exception as e:  # noqa: BLE001
            _vc_log(f"翻译会话路由设置失败（{cls_name}）：{e}")

    cls.__init__ = _init
    orig_translate = getattr(cls, "translate_subtitle", None)
    if callable(orig_translate):
        def _translate(self, subtitle_data):
            try:
                if _pin_route(self):
                    _vc_log(f"翻译前重新钉死 {cls_name} 请求路由"
                            "（该实例早于补丁创建，已修正）")
                _route_snapshot(self)
            except Exception as e:  # noqa: BLE001
                _vc_log(f"翻译前路由钉死失败（{cls_name}）：{e}")
            return orig_translate(self, subtitle_data)

        cls.translate_subtitle = _translate
    cls._vt_route_patched = True
    return True


def vc_translate_route_patch():
    """把「翻译请求路由」钉死（幂等运行期补丁，理由见 `translate_session_proxies`）。"""
    try:
        import videocaptioner.core.translate.bing_translator as _bt
        import videocaptioner.core.translate.google_translator as _gt
    except Exception as e:  # noqa: BLE001
        _vc_log(f"翻译路由补丁导入失败：{e}")
        return False
    done = []
    if _patch_translator_route(_bt, "BingTranslator"):
        done.append("微软")
    if _patch_translator_route(_gt, "GoogleTranslator"):
        done.append("谷歌")
    if done:
        _vc_log("翻译路由补丁已挂：%s 请求显式路由（微软直连 / 谷歌走本地代理，"
                "不再跟随系统代理）" % "+".join(done))
    return True


# ========== 字幕翻译全面去 AI（v2.3.1，2026-10-18 用户报告驱动） ==========

def _svc_value(service):
    """取翻译服务的显示值（枚举取 ``.value``，裸字符串原样）。"""
    return str(getattr(service, "value", service))


def _svc_to_bing(service):
    """把「LLM 大模型翻译」归一成「微软翻译」。

    返回值取**引擎枚举**（``videocaptioner.core.entities.TranslatorServiceEnum``）
    的 BING 成员——``subtitle_thread.SERVICE_TO_TYPE`` 只认引擎枚举，传同值
    的异类枚举（如自研 ``engine_entities`` 的副本）会连成员检查都过不了。
    引擎枚举拿不到时退化为「同枚举类取 BING」，再不行原样返回。
    """
    try:
        from videocaptioner.core.entities import TranslatorServiceEnum as _TSE
        return _TSE.BING
    except Exception:  # noqa: BLE001
        cls = type(service)
        return getattr(cls, "BING", service)


def _patch_create_translator():
    """翻译器创建的**唯一收口**：LLM 翻译服务按微软翻译接管。

    ``SubtitleThread`` 与 ``RetranslateThread`` 都经
    ``subtitle_thread.create_translator_from_config`` 建翻译器；只要配置里
    还留着「LLM 大模型翻译」（历史配置 / 设置下拉残留项），这里就换成
    微软翻译——翻译链路从此不可能实例化 ``LLMTranslator``。
    """
    import videocaptioner.ui.thread.subtitle_thread as _st
    if getattr(_st, "_vt_no_llm_patched", False):
        return False
    orig_create = _st.create_translator_from_config

    def _create_translator_from_config(config, custom_prompt="", callback=None):
        try:
            svc = getattr(config, "translator_service", None)
            if _svc_value(svc) == _TS_LLM_VALUE:
                import copy
                patched = copy.copy(config)
                patched.translator_service = _svc_to_bing(svc)
                _vc_log("翻译服务为「LLM 大模型翻译」，已按纯机翻接管（微软翻译）"
                        "——字幕翻译不接入 AI")
                config = patched
        except Exception as e:  # noqa: BLE001
            _vc_log(f"翻译去 AI 归一失败（按原配置继续）：{e}")
        return orig_create(config, custom_prompt, callback)

    _st.create_translator_from_config = _create_translator_from_config
    _st._vt_no_llm_patched = True
    return True


def _patch_need_llm():
    """``need_llm``：翻译服务=LLM 不再触发「验证 LLM 配置」。

    不修这一处的话，``SubtitleThread.run`` 会先拿全局 AI 密钥去
    ``check_llm_connection``——密钥是订阅制（如火山 Token Plan，只认
    /api/plan/*）时直接报「LLM API 测试失败」，用户根本走不到翻译那步。
    归一后只有「字幕校正（优化）」和「词级时间戳断句」才需要 LLM。
    """
    import videocaptioner.ui.thread.subtitle_thread as _st
    cls = _st.SubtitleThread
    if getattr(cls, "_vt_need_llm_patched", False):
        return False
    orig_need_llm = cls.need_llm

    def _need_llm(self, subtitle_config, asr_data):
        try:
            if _svc_value(getattr(subtitle_config, "translator_service", None)) \
                    == _TS_LLM_VALUE:
                return (bool(getattr(subtitle_config, "need_optimize", False))
                        or bool(asr_data.is_word_timestamp()))
        except Exception:  # noqa: BLE001
            pass
        return orig_need_llm(self, subtitle_config, asr_data)

    cls.need_llm = _need_llm
    cls._vt_need_llm_patched = True
    return True


def _mt_failure_text(translator, exc: Exception) -> str:
    """把机翻失败文案改成如实描述（不动 LLM 失败的密钥提示）。"""
    msg = str(exc)
    if _API_KEY_TAIL not in msg:
        return msg
    if not _is_mt_translator(translator):
        return msg
    m = _MT_FAIL_RE.search(msg)
    if m:
        text = ("翻译失败：%s/%s 条未拿到译文（%s%%）。%s"
                % (m.group(1), m.group(2), m.group(3), _MT_FAIL_HINT))
    else:
        text = msg.replace(_API_KEY_TAIL, _MT_FAIL_HINT)
    try:
        _vc_log("机翻失败文案已改写（%s）：%s"
                % (type(translator).__name__, text[:160]))
    except Exception:  # noqa: BLE001
        pass
    return text


def _patch_mt_failure_message():
    """``BaseTranslator._parallel_translate``：机翻整批失败时的用户文案。

    原文案 ``... Check your API key and network connection.`` 对机翻是纯误导
    （机翻没有密钥），用户会跑去查全局 AI 配置——正是本次用户被带偏的路径。
    """
    from videocaptioner.core.translate.base import BaseTranslator
    if getattr(BaseTranslator, "_vt_mt_msg_patched", False):
        return False
    orig_parallel = BaseTranslator._parallel_translate

    def _parallel_translate(self, chunks):
        try:
            return orig_parallel(self, chunks)
        except RuntimeError as e:
            raise RuntimeError(_mt_failure_text(self, e)) from None

    BaseTranslator._parallel_translate = _parallel_translate
    BaseTranslator._vt_mt_msg_patched = True
    return True


def _patch_machine_fallback_retry():
    """整条机翻链失败后自动重试一次（治「网络瞬断把整批打成 ERROR」）。

    2026-10-18 21:10 实测：66 条字幕在 **1 秒内**两端全挂（谷歌预检即失败、
    微软 7 个 chunk 全异常），5 分钟后同样配置同样文件 66/66 全过——瞬时
    DNS/连接抖动，不是端点长期不可用。引擎对整批失败不重试，用户只能手点
    第二次。这里隔 1.5s 自动重跑一次（成功块有缓存，重跑很便宜）。

    只在**快速失败**（<25s）时重试：慢速超时说明端点是真不可用，重试只会
    让用户多等一倍，没意义。
    """
    import videocaptioner.ui.thread.subtitle_thread as _st
    if getattr(_st, "_vt_retry_patched", False):
        return False
    orig = getattr(_st, "translate_with_machine_fallback", None)
    if not callable(orig):
        return False

    def _translate_with_retry(config, custom_prompt, callback, asr_data,
                              progress=None, on_translator=None):
        t0 = time.time()
        try:
            return orig(config, custom_prompt, callback, asr_data,
                        progress=progress, on_translator=on_translator)
        except Exception as e:  # noqa: BLE001
            elapsed = time.time() - t0
            if elapsed >= 25:
                raise
            _vc_log("翻译整批失败（%.1fs，%s），1.5s 后自动重试一次：%s"
                    % (elapsed, type(e).__name__, str(e)[:120]))
            if progress:
                progress("翻译端点暂时不可用，1.5 秒后自动重试…")
            time.sleep(1.5)
            for seg in getattr(asr_data, "segments", []):
                seg.translated_text = ""
            return orig(config, custom_prompt, callback, asr_data,
                        progress=progress, on_translator=on_translator)

    _st.translate_with_machine_fallback = _translate_with_retry
    _st._vt_retry_patched = True
    # DeepLx 也有机翻兜底（公开实例经常挂）：补进引擎的回退表
    try:
        fb = getattr(_st, "MACHINE_FALLBACK", None)
        TSE = _st.TranslatorServiceEnum
        if isinstance(fb, dict) and TSE.DEEPLX not in fb:
            fb[TSE.DEEPLX] = TSE.BING
    except Exception:  # noqa: BLE001
        pass
    return True


def _patch_engine_translate_log():
    """把引擎翻译日志桥到工具箱日志（源码态引擎 app.log 不落盘，排障抓瞎）。

    引擎 ``setup_logger`` 的文件 handler 在源码态经常没落盘（LOG_PATH 在导入期
    固化），``Bing translation failed: ...`` 这类关键行全丢——21:10 那次整批
    失败就因此看不到真实原因。这里给引擎翻译相关 logger 挂一个 handler，
    WARNING 及以上转发到 logs\\vc_fallback.log（同进程去重，不会刷屏）。
    """
    import logging

    class _Bridge(logging.Handler):
        def emit(self, record):
            try:
                _vc_log("[引擎/%s] %s" % (record.name, record.getMessage()))
            except Exception:  # noqa: BLE001
                pass

    done = []
    for name in ("subtitle_translator", "translator_factory",
                 "subtitle_optimization_thread"):
        lg = logging.getLogger(name)
        if getattr(lg, "_vt_log_bridged", False):
            continue
        h = _Bridge()
        h.setLevel(logging.WARNING)
        lg.addHandler(h)
        lg._vt_log_bridged = True
        done.append(name)
    return bool(done)


def vc_translate_no_llm_patch():
    """字幕翻译全面去 AI（幂等运行期补丁，2026-10-18）。

    三件事，缺一不可：
      1. 翻译器创建收口处把「LLM 大模型翻译」归一为「微软翻译」——
         翻译链路不可能实例化 ``LLMTranslator``；
      2. ``need_llm`` 不再因翻译服务=LLM 去验证全局 AI 密钥；
      3. 机翻整批失败的文案去掉「Check your API key」误导，改为
         「纯机翻、不涉及 AI 密钥、请检查网络/代理或更换服务」。

    另附两项稳定性/可观测性补丁（同属本条用户报告）：
      · 机翻整批失败**自动重试一次**（治网络瞬断）；
      · 引擎翻译日志桥到 logs\\vc_fallback.log（源码态引擎日志不落盘）。

    与设置页下拉移除「LLM 大模型翻译」（video_toolbox_qt.py）互补：
    下拉管「别再选」，本补丁管「选了/历史残留也不走 AI」。
    """
    done = []
    for fn in (_heal_corrupt_caches, _patch_create_translator, _patch_need_llm,
               _patch_mt_failure_message, _patch_machine_fallback_retry,
               _patch_engine_translate_log, _patch_translate_cache_safety):
        try:
            if fn():
                done.append(fn.__name__)
        except Exception as e:  # noqa: BLE001
            _vc_log(f"翻译去 AI 补丁（{fn.__name__}）挂载失败：{e}")
    if done:
        _vc_log("翻译去 AI 补丁已挂：字幕翻译仅机翻（微软/谷歌/DeepLx），"
                "LLM 翻译配置按微软翻译接管，机翻报错文案不再提示查 API key，"
                "整批失败自动重试一次，缓存损坏自动重建/降级")
    return True


#: 补丁只装一次（线程安全）；2026-10-20 起从 prepare_runtime_env 移到
#: 预热线程末尾/翻译入口，把 ≈0.7-2s 的引擎翻译模块导入移出启动关键路径。
_PATCH_LOCK = None
_PATCH_DONE = False


def ensure_translate_patches():
    """确保「翻译路由钉死 + 去 AI」两补丁已挂（幂等、线程安全）。

    调用点：预热线程末尾（引擎模块已热，代价≈0）、agent_cli 翻译命令开头。
    补丁必须早于**第一个翻译任务**——GUI 里翻译由用户点击触发，预热线程
    在首帧后 1~3s 就装好了，远早于任何点击。
    """
    global _PATCH_LOCK, _PATCH_DONE
    if _PATCH_DONE:
        return True
    import threading
    if _PATCH_LOCK is None:
        _PATCH_LOCK = threading.Lock()
    with _PATCH_LOCK:
        if _PATCH_DONE:
            return True
        try:
            vc_translate_route_patch()
        except Exception:  # noqa: BLE001
            pass
        try:
            vc_translate_no_llm_patch()
        except Exception:  # noqa: BLE001
            pass
        _PATCH_DONE = True
    return True


__all__ = [
    "vc_translate_route_patch",
    "vc_translate_no_llm_patch",
    "ensure_translate_patches",
    "_patch_translator_route",
]
