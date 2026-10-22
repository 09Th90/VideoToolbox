# @version 2.5.3
"""引擎磁盘缓存（自研，替代 videocaptioner.core.utils.cache）。

P1 接缝之一：引擎在 ``core/utils/cache.py`` **模块级**创建 5 个 diskcache
实例（LLM / ASR / TTS / 翻译 / 版本状态），每个都会真实打开 SQLite、建库并
做维护。本机实测每个约 0.9 秒（慢盘更久），合计 2.5~4.5 秒——而打开「字幕
处理」页根本用不到任何缓存。旧办法 ``video_toolbox.vc_lazy_cache_patch()``
把 ``diskcache.Cache`` 整个换成一个代理类，属于「改写第三方库的公开类」。

本模块把这件事收进自研代码：

* :class:`LazyCache` 是自研的惰性代理，**不再 monkey-patch diskcache**；
* :class:`CacheHub` 持有 5 个缓存实例的工厂，**惰性建库**；
* :func:`generate_cache_key` 是自研实现（键的算法是接口契约，必须一致）。

设计约束
--------
1. **diskcache 保留为组件**（Apache-2.0，广泛使用，非个人项目）——按
   ``docs/引擎自研化替换规格.md`` 第三节口径属「保留并登记」。本模块不重写
   SQLite 缓存引擎，只自研**惰性策略与实例管理**。
2. **零硬依赖**：``diskcache`` 缺失时降级为进程内字典缓存（语义近似、不落盘），
   不让整个程序起不来。旧行为是「import 失败即崩」。
3. **语义不变**：``memoize`` 的 expire/typed 参数透传；缓存键算法与引擎
   ``generate_cache_key`` 逐字节一致（否则引擎已写入的缓存全部失效、
   ``asr_results`` 目录体积翻倍）。
4. **线程安全**：引擎的转写/翻译 worker 多线程共用同一实例，建库加锁。
"""

from __future__ import annotations

import functools
import hashlib
import json
import threading
from dataclasses import asdict, is_dataclass

__all__ = [
    "LazyCache",
    "CacheHub",
    "generate_cache_key",
    "enable_cache",
    "disable_cache",
    "is_cache_enabled",
    "CACHE_KINDS",
]

#: 引擎实际使用的 5 类缓存 → 目录名。目录名是**持久化契约**：
#: 已有用户的缓存文件在这些目录下，改名等于全部失效重算。
CACHE_KINDS = {
    "llm": "llm_translation",
    "asr": "asr_results",
    "tts": "tts_audio",
    "translate": "translate_results",
    "version_state": "version_state",
}

#: 需要 tag 索引的缓存类型（引擎对 asr_results 传了 tag_index=True）。
#: tag 索引用来按标签批量失效，自研降级实现不支持 ⇒ 这些类型不走降级路径。
_TAG_INDEXED = {"asr"}

#: 第三方引擎通过 diskcache 的**私有** ``_sql`` 属性查限流记录
#: （``videocaptioner.core.asr.base.BaseASR._check_rate_limit``：
#: ``SELECT key FROM Cache WHERE tag = ? AND store_time >= ?``）。
#: ``LazyCache.__getattr__`` 对 ``_`` 前缀一律 AttributeError 是为了挡
#: copy/pickle 等协议探测，但会把这类「已知的私有 API 转发」一并挡掉——
#: 症状是公益转录（Bcut/剪映）直接失败，报错文本就是裸属性名
#: （``Failed to query rate limit: _sql``）。这里显式放行**仅此一个**
#: 具名属性，不开任意私有属性的口子。
_FORWARDED_PRIVATE = frozenset({"_sql"})

#: 全局开关（与引擎 is_cache_enabled 语义一致）
_cache_enabled = True


def enable_cache() -> None:
    """启用缓存（全局）。"""
    global _cache_enabled
    _cache_enabled = True


def disable_cache() -> None:
    """禁用缓存（全局）。"""
    global _cache_enabled
    _cache_enabled = False


def is_cache_enabled() -> bool:
    """查询缓存全局开关。"""
    return _cache_enabled


def generate_cache_key(data) -> str:
    """生成缓存键（SHA256）。

    算法必须与引擎 ``core.utils.cache.generate_cache_key`` **逐字节一致**——
    这不是风格问题：键变了，引擎已落盘的缓存全部失效，ASR 结果会被重算一遍。

    契约：递归把 dataclass 转 dict、list/dict 递归处理，然后
    ``json.dumps(ensure_ascii=False, sort_keys=True)`` 再 SHA256。
    """
    def _serialize(obj):
        if is_dataclass(obj) and not isinstance(obj, type):
            return asdict(obj)
        if isinstance(obj, list):
            return [_serialize(item) for item in obj]
        if isinstance(obj, dict):
            return {k: _serialize(v) for k, v in obj.items()}
        return obj

    serialized = _serialize(data)
    text = json.dumps(serialized, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(text.encode()).hexdigest()


def _real_cache_class():
    """取 diskcache 的**真** Cache 类；不可用时返回 ``None``。

    为什么需要这个函数：``video_toolbox.vc_lazy_cache_patch()`` 会把
    ``diskcache.Cache`` 替换成工厂函数，好让引擎模块级建实例时走到惰性代理。
    若此时 ``LazyCache._ensure()`` 直接 ``from diskcache import Cache``，
    拿到的就是那个工厂 → 建库时又返回代理 → **无限递归**。

    因此优先用宿主在接管前保存的原类（``diskcache._vt_real_cache``），
    它是唯一可靠的“真身”引用；没有才退回 diskcache 自身。
    """
    try:
        import diskcache
    except ImportError:
        return None
    real = getattr(diskcache, "_vt_real_cache", None)
    if real is not None:
        return real
    # 未被接管时 _vt_real_cache 不存在；此时 diskcache.Cache 就是真类。
    # 但若已被接管且未保存原类（不该发生），退回 None 更安全。
    if getattr(diskcache, "_vt_lazy_patched", False):
        return None
    return getattr(diskcache, "Cache", None)


class _MemoryCache:
    """diskcache 缺失时的降级缓存：进程内字典，仅本进程有效。"""

    def __init__(self):
        self._d = {}

    def get(self, key, default=None, **kw):
        return self._d.get(key, default)

    def __len__(self):
        return len(self._d)

    def __contains__(self, key):
        return key in self._d

    def __getitem__(self, key):
        return self._d[key]

    def __setitem__(self, key, value):
        self._d[key] = value

    def __delitem__(self, key):
        del self._d[key]

    def __iter__(self):
        return iter(self._d)

    def delete(self, key, **kw):
        self._d.pop(key, None)

    def memoize(self, **kwargs):
        def deco(func):
            return func  # 无 expire 语义，直接透传
        return deco


class LazyCache:
    """惰性磁盘缓存代理：真正用到第一个键时才建库。

    与旧 ``vc_lazy_cache_patch`` 的差别是**它不再替换 diskcache 的类**——
    引擎自己 ``from diskcache import Cache`` 拿到的仍是真 ``Cache``，只是我们
    在构造时传进去的是本代理。第三方库的公开面保持完整。

    参数
    ----
    directory:
        缓存目录。``None`` 表示纯内存（测试与「不落盘」场景）。
    tag_index:
        需要标签索引。降级缓存不支持 ⇒ 真磁盘缓存不可用时**直接抛
        ImportError**，而不是静默退化成会丢失效语义的实现。
    """

    def __init__(self, directory=None, tag_index=False, **kwargs):
        self._args = (directory,)
        self._kwargs = dict(kwargs)
        if tag_index:
            self._kwargs["tag_index"] = True
        self._tag_index = bool(tag_index)
        self._lock = threading.Lock()
        self._real = None
        self._degraded = False
        # 建库用的**真** Cache 类。若 diskcache.Cache 已被宿主接管成工厂
        # （见 video_toolbox.vc_lazy_cache_patch），这里必须用接管前保存的
        # 原类，否则 Cache(...) 会返回另一个代理 → 无限递归建库。
        self._factory = _real_cache_class()

    # ---------- 建库 ----------
    def _ensure(self):
        if self._real is not None or self._degraded:
            return self._real
        with self._lock:
            if self._real is not None or self._degraded:
                return self._real
            directory = self._args[0]
            if directory is None:
                self._real, self._degraded = _MemoryCache(), True
                return self._real
            factory = self._factory
            if factory is None:
                if self._tag_index:
                    # 静默退化会让 tag 失效语义失真（缓存该失效却还在）
                    raise ImportError("需要 diskcache 才能提供 tag_index 缓存")
                self._real, self._degraded = _MemoryCache(), True
                return self._real
            self._real = factory(*self._args, **self._kwargs)
            return self._real

    @property
    def is_built(self):
        """是否已真实建库（自检与诊断用；不触发建库）。"""
        return self._real is not None

    @property
    def is_degraded(self):
        """是否会降级为内存缓存。

        这是**构造期即可回答**的静态属性（由 ``directory`` 是否为 ``None``
        与 diskcache 可用性决定），不是「建库后」的状态——否则调用方在首次
        访问前查询会拿到 False，从而误判「磁盘缓存可用」。
        """
        if self._real is not None:
            return self._degraded
        if self._args[0] is None:
            return True
        return _real_cache_class() is None

    def build_now(self):
        """立即建库并返回底层对象（供预热/诊断）。"""
        return self._ensure()

    # ---------- Cache 协议 ----------
    def __getattr__(self, name):
        # 只在底层对象建好后才解析属性；未建库时访问即触发建库（与旧代理一致）
        if name.startswith("_") and name not in _FORWARDED_PRIVATE:
            raise AttributeError(name)
        return getattr(self._ensure(), name)

    def __len__(self):
        return len(self._ensure())

    def __contains__(self, key):
        return key in self._ensure()

    def __getitem__(self, key):
        return self._ensure()[key]

    def __setitem__(self, key, value):
        self._ensure()[key] = value

    def __delitem__(self, key):
        del self._ensure()[key]

    def __iter__(self):
        return iter(self._ensure())

    def get(self, key, default=None, **kw):
        return self._ensure().get(key, default, **kw)

    def memoize(self, **kwargs):
        """记忆化装饰器（惰性建库 + 保留 __name__/__doc__）。

        必须透传 expire/typed 等参数——引擎 ``core/llm/client.py`` 用
        ``@memoize(get_llm_cache(), expire=3600, typed=True)``，丢掉参数
        会让 LLM 缓存永不过期或不做类型隔离。
        """

        def deco(func):
            holder = {}

            def wrapper(*args, **kw):
                m = holder.get("m")
                if m is None:
                    m = holder["m"] = self._ensure().memoize(**kwargs)(func)
                return m(*args, **kw)

            wrapper.__name__ = getattr(func, "__name__", "wrapper")
            wrapper.__doc__ = getattr(func, "__doc__", None)
            wrapper.__wrapped__ = func
            return wrapper

        return deco


class CacheHub:
    """5 类缓存的惰性工厂（替代引擎的 5 个模块级实例）。

    参数
    ----
    cache_root:
        缓存根目录（通常是 ``<data>/VideoCaptioner/cache``）。
    """

    def __init__(self, cache_root):
        import os
        self.cache_root = str(cache_root)
        self._caches = {}
        self._lock = threading.Lock()

    def get(self, kind):
        """按类型取缓存实例（首次调用才建库）。"""
        c = self._caches.get(kind)
        if c is not None:
            return c
        with self._lock:
            c = self._caches.get(kind)
            if c is not None:
                return c
            sub = CACHE_KINDS.get(kind)
            if sub is None:
                raise KeyError("未知缓存类型: %r（可用: %s）"
                               % (kind, ", ".join(sorted(CACHE_KINDS))))
            import os
            c = LazyCache(
                os.path.join(self.cache_root, sub),
                tag_index=(kind in _TAG_INDEXED),
            )
            self._caches[kind] = c
            return c

    # 具名 getter（与引擎接口同名，便于按需替换调用点）
    def llm(self):
        return self.get("llm")

    def asr(self):
        return self.get("asr")

    def tts(self):
        return self.get("tts")

    def translate(self):
        return self.get("translate")

    def version_state(self):
        return self.get("version_state")

    def built_kinds(self):
        """已建库的缓存类型（自检用；不触发建库）。"""
        return sorted(k for k, v in self._caches.items() if v.is_built)


def memoize(cache_instance, **kwargs):
    """带全局开关的记忆化装饰器（与引擎同名同语义）。

    引擎 ``core/utils/cache.py`` 的 ``memoize`` = ``diskcache.memoize`` +
    「开关关闭则直算」。这里保留该行为，使开关真正生效。
    """

    def decorator(func):
        memoized = cache_instance.memoize(**kwargs)(func)

        @functools.wraps(func)
        def wrapper(*args, **kw):
            if is_cache_enabled():
                return memoized(*args, **kw)
            return func(*args, **kw)

        return wrapper

    return decorator
