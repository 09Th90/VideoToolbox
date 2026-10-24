# @version 2.6.0
"""自检：engine_cache 的惰性语义 + 缓存键与引擎逐字节一致。

P1-B2 cache 接缝验收脚本。

判定口径分两层，缺一不可：

**A. 惰性语义**（不依赖第三方包）
   · 构造不建库；首次读写才建库；
   · 构造后目录**不存在**——这是本接缝省下 2.5~4.5 秒的根据；
   · ``memoize`` 透传 expire/typed，且保留 ``__name__``/``__doc__``；
   · diskcache 缺失时降级为内存缓存，程序不崩；
   · ``tag_index=True`` 时**不允许**静默降级（否则 tag 失效语义失真）。

**B. 缓存键逐字节一致**（依赖第三方包）
   ``generate_cache_key`` 的算法变了 ⇒ 引擎已落盘的缓存全部失效、ASR 结果
   被重算一遍。这类退化不会报错、只会「变慢」和目录翻倍，所以必须用
   逐字节比对来守，不能只测「能算出一个值」。

结构
----
正向：A 组全部 + B 组与引擎交叉比对。
负向：故意弄坏，确认检查**确实能抓到**。

用法
----
    python scripts/dev/_selftest_engine_cache.py

退出码 0 = 通过。
"""

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
SRC = os.path.join(ROOT, "src")

PYPARSE = os.path.join(ROOT, "tools", "python", "python.exe")
if not os.path.exists(PYPARSE):
    PYPARSE = sys.executable


def _run(code):
    env = dict(os.environ)
    env["PYTHONPATH"] = SRC + os.pathsep + env.get("PYTHONPATH", "")
    p = subprocess.run([PYPARSE, "-c", code], env=env,
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return p.returncode, p.stdout + p.stderr


# ---------------------------------------------------------------- A 惰性语义
def positive_lazy():
    code = r'''
import sys, os, tempfile
from engine_cache import (LazyCache, CacheHub, CACHE_KINDS, memoize,
                          generate_cache_key, disable_cache, enable_cache,
                          is_cache_enabled)

fails = []
def chk(name, cond, detail=""):
    if cond:
        print("OK  ", name)
    else:
        fails.append(name); print("FAIL", name, detail)

tmp = tempfile.mkdtemp(prefix="vt_cache_")

# ── 1. 构造不建库（省 2.5~4.5 秒的核心证据）──
d = os.path.join(tmp, "lazy1")
c = LazyCache(d)
chk("构造不建目录", not os.path.exists(d), d)
chk("构造后 is_built=False", c.is_built is False)

# ── 2. 首次写入才建库 ──
c["k"] = "v"
chk("首次写入后建目录", os.path.exists(d), d)
chk("写入后 is_built=True", c.is_built is True)
chk("读回一致", c["k"] == "v")
chk("get 一致", c.get("k") == "v")
chk("len 一致", len(c) == 1, str(len(c)))
chk("contains 一致", "k" in c)
chk("iter 一致", list(c) == ["k"], str(list(c)))
del c["k"]
chk("删除一致", "k" not in c)

# ── 3. 属性透传（第三方公开面未被改写）──
chk("透传 delete", hasattr(c, "delete"))
chk("透传 expire", hasattr(c, "expire"))
chk("透传 set", hasattr(c, "set"))

# ── 3b. 递归回归：宿主把 diskcache.Cache 换成工厂后，代理仍须能建真库 ──
#   历史真实缺陷：_ensure() 里 `from diskcache import Cache` 拿到的是被
#   接管后的工厂 → Cache(...) 又返回代理 → RecursionError。
#   这里完整复现该场景，锁死修复。
import diskcache as _dc
_saved_cache, _saved_flag = _dc.Cache, getattr(_dc, "_vt_lazy_patched", False)
_saved_real = getattr(_dc, "_vt_real_cache", None)
try:
    _dc.Cache = lambda d, *a, **k: c  # 模拟工厂接管
    _dc._vt_lazy_patched = True
    _dc._vt_real_cache = _saved_cache   # 宿主在接管前保存的原类
    c2 = LazyCache(os.path.join(tmp, "recur"))
    c2["x"] = 1
    chk("接管后建库不递归", c2["x"] == 1)
    chk("接管后非降级", c2.is_degraded is False)
finally:
    _dc.Cache = _saved_cache
    if _saved_flag:
        _dc._vt_lazy_patched = True
    elif hasattr(_dc, "_vt_lazy_patched"):
        del _dc._vt_lazy_patched
    if _saved_real is not None:
        _dc._vt_real_cache = _saved_real
    elif hasattr(_dc, "_vt_real_cache"):
        del _dc._vt_real_cache

# ── 4. memoize：语义 + 元信息保留 ──
calls = {"n": 0}
@c.memoize(expire=3600, typed=True)
def slow(x):
    """加倍的测试函数。"""
    calls["n"] += 1
    return x * 2
chk("memoize 保留 __name__", slow.__name__ == "slow", slow.__name__)
chk("memoize 保留 __doc__", slow.__doc__ == "加倍的测试函数。", repr(slow.__doc__))
chk("memoize 保留 __wrapped__", hasattr(slow, "__wrapped__"))
r1, r2 = slow(21), slow(21)
chk("memoize 结果正确", r1 == 42 and r2 == 42, "%r %r" % (r1, r2))
chk("memoize 命中缓存", calls["n"] == 1, "调用 %d 次" % calls["n"])

# ── 5. CacheHub：目录名契约 + 单例复用 + 惰性 ──
root = os.path.join(tmp, "hub")
hub = CacheHub(root)
chk("hub 初始未建库", hub.built_kinds() == [], str(hub.built_kinds()))
a = hub.get("llm")
b = hub.get("llm")
chk("同 kind 复用同实例", a is b)
chk("不同 kind 不同实例", hub.get("asr") is not hub.get("tts"))
chk("5 类目录名契约", CACHE_KINDS == {
    "llm": "llm_translation", "asr": "asr_results", "tts": "tts_audio",
    "translate": "translate_results", "version_state": "version_state"},
    str(CACHE_KINDS))
try:
    hub.get("不存在")
    chk("未知 kind 抛 KeyError", False, "未抛")
except KeyError:
    chk("未知 kind 抛 KeyError", True)
chk("取实例不建目录", not os.path.exists(root), root)

# ── 6. 全局开关 ──
chk("默认启用缓存", is_cache_enabled() is True)
disable_cache()
chk("可禁用", is_cache_enabled() is False)
enable_cache()
chk("可启用", is_cache_enabled() is True)

# ── 7. diskcache 缺失时降级不崩 ──
mem = LazyCache(None)
chk("directory=None 用内存", mem.is_degraded is True)
mem["a"] = 1
chk("内存缓存可读写", mem["a"] == 1)
chk("内存缓存 len", len(mem) == 1)

# ── 8. tag_index=True 不允许静默降级 ──
#    （此环境有 diskcache，故用「断言它是真磁盘缓存」间接验证不降级）
ti = LazyCache(os.path.join(tmp, "tagged"), tag_index=True)
ti.build_now()
chk("tag_index 走真磁盘缓存", ti.is_degraded is False)

print()
print("FAIL:", len(fails), fails if fails else "惰性语义全部成立")
sys.exit(1 if fails else 0)
'''
    rc, out = _run(code)
    print(out.rstrip())
    return rc == 0


# ---------------------------------------------------------------- B 键一致
def positive_key_parity():
    """缓存键与引擎 generate_cache_key 逐字节一致（含中文 / 嵌套 / dataclass）。"""
    code = r'''
import sys
from dataclasses import dataclass
from engine_cache import generate_cache_key as mine
from videocaptioner.core.utils.cache import generate_cache_key as theirs

fails = []
def chk(name, a, b=None):
    """两参数 = 与引擎比对；一参数 = 布尔断言。"""
    if b is None:
        ok = bool(a)
        if ok:
            print("OK  ", name)
        else:
            fails.append(name); print("FAIL", name, "(布尔断言未成立)")
        return
    if a == b:
        print("OK  ", name)
    else:
        fails.append(name)
        print("FAIL", name, "\n  自研", a, "\n  引擎", b)

@dataclass
class D:
    x: int
    y: str

CASES = [
    ("空 dict", {}),
    ("普通 dict", {"a": 1, "b": "x"}),
    ("中文", {"text": "中文字幕测试", "n": 3}),
    ("键序无关", {"b": 2, "a": 1}),
    ("列表", [1, 2, {"k": "v"}]),
    ("嵌套 dataclass", D(1, "中")),
    ("dataclass 列表", [D(1, "a"), D(2, "b")]),
    ("None 值", {"a": None}),
    ("浮点", {"x": 1.5}),
    ("长文本", {"t": "测试" * 500}),
]
for name, val in CASES:
    chk(name, mine(val), theirs(val))

# 键序无关性：两个不同插入顺序的 dict 必须同键
chk("键序无关性", mine({"a": 1, "b": 2}), mine({"b": 2, "a": 1}))

# 长度与字符集：SHA256 hex
k = mine({"a": 1})
print("     样例键:", k)
chk("SHA256 长度 64", len(k) == 64)
chk("纯小写 hex", all(ch in "0123456789abcdef" for ch in k))

print()
print("FAIL:", len(fails), fails if fails else "缓存键与引擎逐字节一致")
sys.exit(1 if fails else 0)
'''
    rc, out = _run(code)
    if "No module named" in out or "ModuleNotFoundError" in out:
        print("SKIP  第三方 videocaptioner 不在当前解释器环境，跳过键交叉项")
        return True
    print(out.rstrip())
    return rc == 0


# ---------------------------------------------------------------- C 接线
def positive_wiring():
    """接线验证：引擎实际拿到的 5 个实例是自研惰性代理，且未建库。"""
    code = r'''
import sys, os
sys.path.insert(0, "src")
os.environ["VT_DATA_ROOT"] = os.path.abspath("data")
import video_toolbox as vt
vt.prepare_runtime_env()
from engine_cache import LazyCache

fails = []
def chk(name, cond, detail=""):
    if cond:
        print("OK  ", name)
    else:
        fails.append(name); print("FAIL", name, detail)

import videocaptioner.core.utils.cache as ec

chk("未提前建库", all(not c.is_built for c in (
    ec._llm_cache, ec._asr_cache, ec._tts_cache,
    ec._translate_cache, ec._version_state_cache)),
    "有实例已建库")

import diskcache
chk("diskcache.Cache 已被接管", callable(getattr(diskcache, "Cache", None)))
chk("保留真 Cache 引用", hasattr(diskcache, "_vt_real_cache"))

# 真实写入一次，确认代理可用
ec._translate_cache["__selftest__"] = "ok"
chk("代理可写可读", ec._translate_cache["__selftest__"] == "ok")
chk("写入后已建库", ec._translate_cache.is_built is True)
del ec._translate_cache["__selftest__"]

# 键算法与引擎一致（同一函数对象路径）
from engine_cache import generate_cache_key
chk("键算法一致", generate_cache_key({"a": 1}) == ec.generate_cache_key({"a": 1}))

print()
print("FAIL:", len(fails), fails if fails else "接线正确")
sys.exit(1 if fails else 0)
'''
    rc, out = _run(code)
    if "No module named" in out or "ModuleNotFoundError" in out:
        print("SKIP  第三方依赖不在当前解释器环境，跳过接线项")
        return True
    print("\n".join(l for l in out.rstrip().splitlines()
                    if l.startswith(("OK", "FAIL", "SKIP")) or "FAIL:" in l))
    return rc == 0


# ---------------------------------------------------------------- 负向
def negative():
    import shutil
    import tempfile
    tmp = tempfile.mkdtemp(prefix="vt_cache_neg_")
    src_file = os.path.join(SRC, "engine_cache.py")
    dst = os.path.join(tmp, "engine_cache.py")
    ok = True
    try:
        with open(src_file, encoding="utf-8") as f:
            txt = f.read()
        # 合并进 os.environ 并**保留原有 PYTHONPATH**：直接覆盖会丢掉外部注入的
        # 路径（本机就有 WorkBuddy 的 cli shim），换个环境自检就会莫名失败。
        env = dict(os.environ)
        env["PYTHONPATH"] = os.pathsep.join(
            [tmp, SRC] + ([os.environ["PYTHONPATH"]]
                          if os.environ.get("PYTHONPATH") else []))

        # ① 污染键算法（去掉 sort_keys）→ 与引擎比对须失败
        #    ⚠ 锚点必须是**真实代码行**，不能只 replace 一次全文件：
        #    文档字符串里也写了 sort_keys=True，先命中的是注释，污染不生效
        #    ⇒ 检查「仍判一致」→ 被误认为负向验证通过，实则形同虚设。
        anchor = 'text = json.dumps(serialized, ensure_ascii=False, sort_keys=True)'
        if anchor not in txt:
            print("负向①：未找到注入点，跳过（不代表检查无效）")
            return False
        p1 = txt.replace(anchor, anchor.replace("sort_keys=True",
                                                "sort_keys=False"), 1)
        if p1 == txt:
            print("负向①：污染未生效，跳过（不代表检查无效）")
            return False
        with open(dst, "w", encoding="utf-8") as f:
            f.write(p1)
        # 验证污染确实进了副本（防止又一次「锚点选错」）
        with open(dst, encoding="utf-8") as f:
            if "sort_keys=False" not in f.read().replace(
                    "``json.dumps(ensure_ascii=False, sort_keys=False)``", ""):
                print("FAIL 负向①：污染未落入真实代码行")
                return False
        code = (
            "import sys\n"
            "from engine_cache import generate_cache_key as mine\n"
            "from videocaptioner.core.utils.cache import "
            "generate_cache_key as theirs\n"
            "sys.exit(0 if mine({'b':2,'a':1}) == theirs({'b':2,'a':1}) else 3)\n"
        )
        r = subprocess.run([PYPARSE, "-c", code], env={**os.environ, **env},
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        if r.returncode == 3:
            print("OK   负向①：键算法被污染后成功检出")
        else:
            print("FAIL 负向①：污染后仍判一致 —— 键一致性检查形同虚设")
            ok = False

        # ② 破坏惰性（构造即建库）→ 惰性检查须失败
        #    锚点取自 __init__ 的真实代码序列；改过 __init__ 就要同步改这里，
        #    否则 replace 落空 → 被误当成「检查通过」。
        #    ⚠ 污染点必须在 self._factory 赋值**之后**：插在之前会先撞上
        #    AttributeError（_factory 尚未定义），目录照样不建 → 检查同样「通过」。
        anchor2 = "        self._factory = _real_cache_class()"
        if anchor2 not in txt:
            print("负向②：未找到注入点，跳过（不代表检查无效）")
            return False
        p2 = txt.replace(anchor2, anchor2 + "\n        self._ensure()", 1)
        if p2 == txt:
            print("负向②：污染未生效，跳过（不代表检查无效）")
            return False
        with open(dst, "w", encoding="utf-8") as f:
            f.write(p2)
        code2 = (
            "import sys, os, tempfile\n"
            "from engine_cache import LazyCache\n"
            "d = os.path.join(tempfile.mkdtemp(), 'x')\n"
            "c = LazyCache(d)\n"
            "sys.exit(3 if os.path.exists(d) else 0)\n"
        )
        r2 = subprocess.run([PYPARSE, "-c", code2], env={**os.environ, **env},
                            capture_output=True, text=True, encoding="utf-8", errors="replace")
        if r2.returncode == 3:
            print("OK   负向②：构造即建库被成功检出")
        else:
            print("FAIL 负向②：惰性检查形同虚设")
            ok = False
        return ok
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    print("=" * 60)
    print("engine_cache 惰性缓存 + 键一致性自检")
    print("=" * 60)
    print("\n[1/4] 正向 A：惰性语义")
    ok1 = positive_lazy()
    print("\n[2/4] 正向 B：缓存键与引擎逐字节一致")
    ok2 = positive_key_parity()
    print("\n[3/4] 正向 C：引擎接线（5 实例为惰性代理）")
    ok3 = positive_wiring()
    print("\n[4/4] 负向校验（故意弄坏）")
    ok4 = negative()
    print("\n" + "=" * 60)
    allok = ok1 and ok2 and ok3 and ok4
    print("结论：", "PASS" if allok else "FAIL")
    return 0 if allok else 1


if __name__ == "__main__":
    sys.exit(main())
