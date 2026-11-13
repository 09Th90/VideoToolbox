# -*- coding: utf-8 -*-
# @version 2.9.0
"""自检：谷歌翻译批量请求层（``core.translate.gtx_batch``，2026-11-01）。

背景
----
GUI 翻 3376 条要 6.5 分钟，根因是引擎 ``GoogleTranslator._translate_chunk``
**一条一次 GET** + 模块级 ``_gtx_throttle`` 把跨线程间隔钳到 ≥0.12s（进程级
串行，实测只有 5.8 行/秒）。同时 ``agent_cli`` / 自动流水线走的自研线
``engine_translate.GoogleTranslator`` 还挂在已死的 ``translate_a/single`` 上、
``probe()`` 硬编码返回「不可用」，选谷歌必然秒失败。

本脚本守护批量层（25 条 / 6000 编码字节，重复 ``q`` 参数、响应 1:1 保序）的
四件事：

  A. 分组与字节预算：条数上限、CJK 编码字节上限（percent-encode 后 9 字节/字，
     不是 3 倍）、分组确定性、超长单条截断但不丢条目。
  B. **位置映射**：假端点把下标回显进译文，逐位断言相等——抓 off-by-one。
     错位是本改动唯一不可逆的后果：引擎落盘门禁只看「非空」「有中文」，
     译文错位照样全绿并直接产出语序打乱的字幕文件。
  C. 降级阶梯：条数/形状不符 → 逐条；400/413/414 → 二分；429 → 整组失败且
     **不逐条狂补**（越打越死）、单请求条数上限自适应减半；组内重复原文映射
     不一致 → 判错位退回逐条。
  D. 两条线集成：引擎线补丁幂等、切块按预算而非 ``batch_num``；与
     ``_patch_missing_retranslate`` 串联时补翻轮也吃批量。

负向（防绿屏假象）
------------------
  ① 不挂补丁：引擎逐条实现确实一条一请求（证明「请求数下降」的检测有牙齿）；
  ② 抽掉字节预算：确实会生成超限 URL（证明预算在被使用）；
  ③ 假端点「响应旋转一位」：朴素赋值会产出错位译文，我们的不变量必须抓到。

用法（任意目录）：
    ..\\tools\\python\\python.exe scripts\\dev\\_selftest_gtx_batch.py
退出码 0 = 通过。
"""
import os
import subprocess
import sys

#: 子进程按 utf-8 收，父进程也必须按 utf-8 打——控制台默认 gbk，中日韩样本一
#: 打印就 UnicodeEncodeError（本仓库另一条自检 `_selftest_engine_translate.py`
#: 就是这个坑）。errors="replace" 保证任何情况下都不会因为编码而中断判定。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
SRC = os.path.join(ROOT, "src")

PYPARSE = os.path.join(ROOT, "tools", "python", "python.exe")
if not os.path.exists(PYPARSE):
    PYPARSE = sys.executable

#: 公共前置：绕缓存 + 假 session 骨架。
#: ⚠ 缓存必须在**构造翻译器之前**替换——``_SafeTranslatorCache.disable_cache()``
#: 只 gate ``memoize`` 装饰器，而翻译器直接调 ``self._cache.get/set``。
PRELUDE = r'''
import os, sys, time
from urllib.parse import quote
sys.path.insert(0, r"{src}")

# 子进程也按 utf-8 打：样本里含中日韩与【】，Windows 控制台默认 gbk 会
# UnicodeEncodeError 把整条用例炸掉（看起来像功能失败，其实是编码）。
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from core.translate import gtx_batch as G
from videocaptioner.core.translate import base as _base

class NoopCache:
    def get(self, *a, **k): return k.get("default", a[1] if len(a) > 1 else None)
    def set(self, *a, **k): return None
    def delete(self, *a, **k): return None

_base.get_translate_cache = lambda: NoopCache()

class Resp:
    def __init__(self, status, payload=None, text=""):
        self.status_code = status
        self._payload = payload
        self.text = text or ("" if payload is None else str(payload))
    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload
    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("HTTP %d" % self.status_code)

class FakeSession:
    """按脚本回放响应。``script`` 是 (谓词, 响应) 列表，否则用默认回显。

    默认回显把请求下标写进译文，便于逐位断言对齐。
    """
    def __init__(self, script=None, mode="echo", rotate=False):
        self.calls = []
        self.script = script or []
        self.mode = mode
        self.rotate = rotate

    @staticmethod
    def _texts(params):
        # 批量层传 list[(k,v)]（重复 q），引擎逐条实现传 dict——两种都要吃，
        # 否则负向①「不挂补丁」的对照会在假 session 里先炸掉。
        items = (list(params.items()) if isinstance(params, dict)
                 else list(params or []))
        return [v for k, v in items if k == "q"]

    def get(self, endpoint, params=None, headers=None, timeout=None, **kw):
        texts = self._texts(params)
        self.calls.append({"n": len(texts),
                           "url_bytes": sum(len(quote(t, safe="")) for t in texts)})
        for pred, resp in self.script:
            if pred(texts):
                return resp
        if self.mode == "empty":
            return Resp(200, [])
        # 回显**原文**而非批内下标：批量层按组发请求，组内下标无法校验全局对齐；
        # 且必须带汉字，否则会被引擎 ``_assert_translation_language``
        # （「整片译文一个汉字都没有」判端点没翻）挡在批量层之外。
        out = [["译【%s】" % t, "en"] for t in texts]
        if self.rotate:
            out = out[1:] + out[:1]
        return Resp(200, out)
'''.replace("{src}", SRC)


def _run(code, prelude=True):
    """跑一段子进程代码。返回 ``(退出码, 合并输出, 是否通过)``。

    通过与否**只看 stdout 的 RESULT 标记**：引擎 logger 会把 WARNING 打到
    stderr（补翻、部分失败等），拼进合并输出后 ``endswith`` 必然误判。
    """
    env = dict(os.environ)
    env["PYTHONPATH"] = SRC
    env["VT_GTX_BATCH"] = env.get("VT_GTX_BATCH", "1")
    body = (PRELUDE + "\n" + code) if prelude else code
    p = subprocess.run([PYPARSE, "-c", body], env=env,
                       capture_output=True, encoding="utf-8", errors="replace")
    stdout = p.stdout or ""
    passed = (p.returncode == 0
              and any(line.strip() == "RESULT True"
                      for line in stdout.splitlines()))
    return p.returncode, stdout + (p.stderr or ""), passed


def _show(out):
    for line in out.rstrip().splitlines():
        print("    " + line)


def chk(name, cond, detail=""):
    print("%-4s %s%s" % ("OK" if cond else "FAIL", name,
                         (" | " + detail) if detail else ""))
    return bool(cond)


# ------------------------------------------------------------------ 正向 A
def positive_grouping():
    """分组与字节预算。"""
    rc, out, passed = _run(r'''
ok = True
# A2 拉丁文：条数上限先约束
lat = ["line %d hello world" % i for i in range(100)]
g = G.group_texts(lat)
print("拉丁 100 条 -> %d 组，最大组 %d 条" % (len(g), max(len(x) for x in g)))
ok &= (max(len(x) for x in g) <= G.MAX_ITEMS_PER_REQUEST)
ok &= (sum(len(x) for x in g) == 100)

# A1 中日韩：编码字节先约束（9 字节/字，不是 3 倍）
cjk = ["こんにちは世界です" * 6 for _ in range(40)]
gc = G.group_texts(cjk)
per = [sum(G.url_bytes(cjk[i]) for i in x) for x in gc]
print("CJK 40 条 -> %d 组，单组最大编码字节 %d（预算 %d）"
      % (len(gc), max(per), G.MAX_REQUEST_URL_BYTES))
ok &= max(per) <= G.MAX_REQUEST_URL_BYTES
ok &= len(gc) > (40 // G.MAX_ITEMS_PER_REQUEST)   # 确实被字节拆开
ok &= sum(len(x) for x in gc) == 40

# A3 确定性（分组是缓存键的一部分，非确定 = 缓存永不命中）
ok &= (G.group_texts(cjk) == gc and G.group_texts(cjk) == gc)

# A4 超长单条：截断但不丢条目
long = "あ" * 3000
clip, was = G.clip_to_url_bytes(long)
ok &= was and G.url_bytes(clip) <= G.MAX_ITEM_URL_BYTES and clip == "あ" * len(clip)
g4 = G.group_texts([long] + lat[:5])
ok &= sum(len(x) for x in g4) == 6
print("超长单条 3000 字 -> 截断 %d 编码字节，分组 %s"
      % (G.url_bytes(clip), [len(x) for x in g4]))
print("RESULT", ok)
''')
    _show(out)
    return chk("[A] 分组与编码字节预算", passed)


# ------------------------------------------------------------------ 正向 B
def positive_alignment():
    """位置映射：假端点回显下标，逐位断言。"""
    rc, out, passed = _run(r'''
ok = True
s = FakeSession()
c = G.GtxBatchClient(s, "https://example/translate_a/t", {}, "zh-CN",
                     throttle=lambda: None)
texts = ["row %d" % i for i in range(60)] + ["", "   "]
got = c.translate_texts(texts)
print("请求 %d 次，每次条数 %s" % (len(s.calls), [x["n"] for x in s.calls]))
# 位置映射：第 i 条必须拿回第 i 条自己的回显（跨 25/25/10 三组也不能串）
mis = [i for i in range(60) if got[i] != "译【row %d】" % i]
print("错位下标", mis[:8])
ok &= not mis
# 空原文摘出批量：不发请求、返回空串
ok &= got[60] == "" and got[61] == ""
ok &= c.stats["blank"] == 2
# 非空的 60 条按 25/25/10 分组，空白两条不占请求
ok &= [x["n"] for x in s.calls] == [25, 25, 10]
# 组内下标是 pending 内部的相对值，必须映射回原列表（曾经的真 bug 形态）
mixed = ["", "a", "", "b", "c"]
s2 = FakeSession(); c2 = G.GtxBatchClient(s2, "e", {}, "zh-CN", throttle=lambda: None)
r2 = c2.translate_texts(mixed)
print("混合空文本 ->", r2)
ok &= r2 == ["", "译【a】", "", "译【b】", "译【c】"]
print("RESULT", ok)
''')
    _show(out)
    return chk("[B] 位置映射与空文本摘出", passed)


# ------------------------------------------------------------------ 正向 C
def positive_fallback():
    """降级阶梯。"""
    rc, out, passed = _run(r'''
ok = True
# C1 条数不符（批量只回一条）→ 逐条回退且全部有效
s = FakeSession(script=[(lambda t: len(t) > 1, Resp(200, [["T0", "en"]]))])
c = G.GtxBatchClient(s, "e", {}, "zh-CN", throttle=lambda: None)
r = c.translate_texts(["x%d" % i for i in range(5)])
print("C1 批量 %d 次 + 逐条 %d 次，形状异常 %d"
      % (c.stats["batch_req"], c.stats["single_req"], c.stats["shape_bad"]))
ok &= r == ["译【x%d】" % i for i in range(5)] and c.stats["single_req"] == 5

# C2 400 → 二分恢复到 1 条
s = FakeSession(script=[(lambda t: len(t) > 1, Resp(400, None, "<html>400</html>"))])
c = G.GtxBatchClient(s, "e", {}, "zh-CN", throttle=lambda: None)
r = c.translate_texts(["x%d" % i for i in range(8)])
sizes = [x["n"] for x in s.calls]
print("C2 请求尺寸序列", sizes, "超限计数", c.stats["oversize"])
ok &= all(r) and 1 in sizes and c.stats["oversize"] >= 1

# C3 429 → 整组失败、不逐条狂补、上限减半
s = FakeSession(script=[(lambda t: True, Resp(429, None))])
c = G.GtxBatchClient(s, "e", {}, "zh-CN", throttle=lambda: None)
before = c.max_items
r = c.translate_texts(["x%d" % i for i in range(6)])
print("C3 逐条请求 %d 次（应为 0），上限 %d -> %d，429 计数 %d"
      % (c.stats["single_req"], before, c.max_items, c.stats["rate_limited"]))
ok &= all(x is None for x in r)
ok &= c.stats["single_req"] == 0 and c.max_items == before // 2
ok &= c.stats["rate_limited"] >= 1

# C4 形状异常（元素不是数组）→ 逐条
s = FakeSession(script=[(lambda t: len(t) > 1, Resp(200, ["字符串", "字符串"]))])
c = G.GtxBatchClient(s, "e", {}, "zh-CN", throttle=lambda: None)
r = c.translate_texts(["x%d" % i for i in range(4)])
ok &= r == ["译【x%d】" % i for i in range(4)] and c.stats["shape_bad"] >= 1

# C5 组内重复原文映射不一致 → 判错位、退回逐条
def dup_bad(t):
    return len(t) > 1 and t.count("dup") >= 1
s = FakeSession(script=[(dup_bad, Resp(200, [["A", "en"], ["B", "en"],
                                             ["C", "en"]]))])
c = G.GtxBatchClient(s, "e", {}, "zh-CN", throttle=lambda: None)
r = c.translate_texts(["dup", "dup", "other"])
print("C5 错位计数 %d，逐条 %d 次，结果 %s"
      % (c.stats["misalign"], c.stats["single_req"], r))
ok &= c.stats["misalign"] == 1 and c.stats["single_req"] >= 3
ok &= r == ["译【dup】", "译【dup】", "译【other】"]   # 重复原文必须拿回同一译文

# C6 开关：VT_GTX_BATCH=0 整体退回逐条
os.environ["VT_GTX_BATCH"] = "0"
s = FakeSession(); c = G.GtxBatchClient(s, "e", {}, "zh-CN", throttle=lambda: None)
r = c.translate_texts(["x%d" % i for i in range(6)])
ok &= c.stats["batch_req"] == 0 and c.stats["single_req"] == 6 and all(r)
del os.environ["VT_GTX_BATCH"]
print("RESULT", ok)
''')
    _show(out)
    return chk("[C] 降级阶梯（条数/400/429/形状/错位/开关）",
               passed)


# ------------------------------------------------------------------ 正向 D
def positive_integration():
    """两条线集成 + 与补翻轮串联。"""
    rc, out, passed = _run(r'''
ok = True
from core.translate.route_patch import ensure_translate_patches
import videocaptioner.core.translate.google_translator as gm
from videocaptioner.core.translate.types import TargetLanguage
from videocaptioner.core.asr.asr_data import ASRData, ASRDataSeg

ensure_translate_patches()
first = gm.GoogleTranslator._vt_gtx_batch_patched
ensure_translate_patches()
ok &= first and gm.GoogleTranslator._vt_gtx_batch_patched

t = gm.GoogleTranslator(thread_num=10, batch_num=10,
                        target_language=TargetLanguage.SIMPLIFIED_CHINESE,
                        timeout=20, update_callback=None)
t.session = FakeSession()
segs = [ASRDataSeg(text="row %d" % i, start_time=i*1000, end_time=i*1000+500)
        for i in range(60)]
out_data = t.translate_subtitle(ASRData(segs))
st = t._vt_gtx_client.stats
sizes = [c["n"] for c in t.session.calls]
print("D1 60 条 -> 批量请求 %d 次，尺寸 %s，失败 %d"
      % (st["batch_req"], sizes, sum(1 for s in out_data.segments
                                     if s.translated_text in ("", "ERROR"))))
# 切块必须按预算（25/25/10），而不是配置的 batch_num=10。
# 首条 1 项请求是引擎的 _preflight（单条探连通性），按设计保留。
# ⚠ 10 线程并发，calls 记录的是**到达顺序**、不确定 → 只能按重数比。
ok &= sizes[0] == 1 and sorted(sizes[1:]) == [10, 25, 25]
ok &= all(s.translated_text == "译【row %d】" % i
          for i, s in enumerate(out_data.segments))

# D2 与定向补翻串联：让第 2 组（25 条）整组拿不到 → 缺失 25/60=42%（不触发
# 引擎 ≥50% 的整批抛错）→ 补翻轮必须把这 25 条**再一次批量**拿回
from core.translate import route_patch as RP
class Flaky(FakeSession):
    def __init__(self):
        super().__init__()
        self.batch_round = 0

    def get(self, endpoint, params=None, headers=None, timeout=None, **kw):
        texts = FakeSession._texts(params)   # 引擎 _preflight 传 dict，要同吃
        if len(texts) > 1:
            self.batch_round += 1
            if self.batch_round == 2:        # 第 2 个批量组整组拿不到
                return Resp(200, [["", "en"] for _ in texts])
        return super().get(endpoint, params=params, headers=headers,
                           timeout=timeout)
t2 = gm.GoogleTranslator(thread_num=10, batch_num=25,
                         target_language=TargetLanguage.SIMPLIFIED_CHINESE,
                         timeout=20, update_callback=None)
flaky = Flaky(); t2.session = flaky
segs2 = [ASRDataSeg(text="row %d" % i, start_time=i*1000, end_time=i*1000+500)
         for i in range(60)]
res = t2.translate_subtitle(ASRData(segs2))
bad = sum(1 for s in res.segments if s.translated_text in ("", "ERROR"))
rsizes = [c["n"] for c in flaky.calls]
print("D2 补翻后缺失 %d 条，请求尺寸 %s（失败那组不计入 calls）"
      % (bad, rsizes))
ok &= bad == 0
ok &= all(s.translated_text == "译【row %d】" % i
          for i, s in enumerate(res.segments))
# 补翻轮也吃批量：3 个初始组 + 1 轮补翻 = ≥3 次批量形状请求（失败那次不记账）
ok &= len([x for x in rsizes if x > 1]) >= 3

# D3 自研线同一份实现
from engine_translate import make_translator
g = make_translator("google", thread_num=10, batch_num=5,
                    target_language="简体中文")
g.session = FakeSession()
class D:
    def __init__(self, n):
        self.index = n; self.original_text = "row %d" % n; self.translated_text = ""
chunk = [D(i) for i in range(30)]
g._translate_chunk(chunk)
ok &= [d.translated_text for d in chunk] == ["译【row %d】" % i for i in range(30)]
print("D3 自研线 30 条 -> 请求尺寸 %s" % [c["n"] for c in g.session.calls])
print("RESULT", ok)
''')
    _show(out)
    return chk("[D] 两条线集成与补翻串联", passed)


# ------------------------------------------------------------------ 负向
def negative():
    """证明正向检测有牙齿。"""
    rc, out, passed = _run(r'''
ok = True
# ① 不挂补丁：引擎逐条实现确实一条一请求
import importlib
m = importlib.reload(importlib.import_module(
    "videocaptioner.core.translate.google_translator"))
t = m.GoogleTranslator(thread_num=10, batch_num=10,
                       target_language=__import__(
                           "videocaptioner.core.translate.types",
                           fromlist=["TargetLanguage"]).TargetLanguage.SIMPLIFIED_CHINESE,
                       timeout=20, update_callback=None)
t.session = FakeSession()
datas = []
for i in range(12):
    from videocaptioner.core.entities import SubtitleProcessData
    datas.append(SubtitleProcessData(index=i, original_text="row %d" % i))
t._translate_chunk(datas)
n = len(t.session.calls)
print("① 未打补丁：12 条发了 %d 个请求（逐条 = 12）" % n)
ok &= n == 12

# ② 抽掉字节预算：确实会生成超限 URL
saved = G.MAX_REQUEST_URL_BYTES
try:
    G.MAX_REQUEST_URL_BYTES = 10 ** 9
    cjk = ["こんにちは世界です" * 6 for _ in range(40)]
    g = G.group_texts(cjk)
    per = max(sum(G.url_bytes(cjk[i]) for i in x) for x in g)
    print("② 无字节预算：单组最大 %d 编码字节（> %d 即端点会 400）"
          % (per, saved))
    ok &= per > saved
finally:
    G.MAX_REQUEST_URL_BYTES = saved

# ③ 响应旋转一位：朴素赋值会产出错位译文，不变量必须抓到
rot = FakeSession(rotate=True)
c = G.GtxBatchClient(rot, "e", {}, "zh-CN", throttle=lambda: None)
texts = ["dup", "one", "dup", "two"]      # 含重复原文 → 可检测
got = c.translate_texts(texts)
naive = ["译【one】", "译【dup】", "译【two】", "译【dup】"]
print("③ 旋转响应：朴素赋值会得到 %s（#0 与 #2 同为 dup 却译文不同）" % naive)
print("   我们的结果 %s，错位计数 %d，逐条 %d 次"
      % (got, c.stats["misalign"], c.stats["single_req"]))
ok &= c.stats["misalign"] >= 1 and c.stats["single_req"] >= 4
ok &= got == ["译【dup】", "译【one】", "译【dup】", "译【two】"]
print("RESULT", ok)
''')
    _show(out)
    return chk("[负向] 不挂补丁/无预算/旋转响应均被检出",
               passed)


def main():
    print("=" * 60)
    print("谷歌批量翻译层自检（core.translate.gtx_batch）")
    print("=" * 60)
    results = []
    for title, fn in (("[1/5] 分组与字节预算", positive_grouping),
                      ("[2/5] 位置映射", positive_alignment),
                      ("[3/5] 降级阶梯", positive_fallback),
                      ("[4/5] 两条线集成", positive_integration),
                      ("[5/5] 负向对照", negative)):
        print("\n" + title)
        results.append(fn())
    print("\n" + "-" * 60)
    passed = sum(1 for r in results if r)
    print("结论：%d/%d PASS" % (passed, len(results)))
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
