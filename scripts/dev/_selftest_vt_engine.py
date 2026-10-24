# @version 2.6.0
"""自检：vt_engine 完整运行引擎（并行开发线）的契约 + 红线 + 负向注入。

覆盖（全部离线，不需要网络/密钥；联网项留 --net）：

A. 红线：全包 AST 扫 ``videocaptioner`` 引用 + 运行期导入隔离
   （import 全部子模块后 ``'videocaptioner' not in sys.modules``）。
B. 设置层 config：与 settings.json 实况逐键 round-trip、set→落盘→重载、
   校验器纠正（范围钳制/选项纠正）、未知组保留、临时路径构造。
C. 数据类 entities：任务数据类字段集与引擎 entities 逐一比对
   （引擎在场时）；枚举取值与 settings.json 可反构造。
D. 翻译编排 translate_base / llm_translator：0 条抛错、ERROR 记账、
   >=50% 抛错、<50% 放行、缓存键形式、stop 语义；JSON 容忍解析；
   反思模式 native_translation 校验；LLM 缓存键带模型名；agent loop
   纠正反馈自带原始输入（单通道压扁多轮历史，2026-10-19）；断句单块
   失败回退原文；说话人提示词换行；run_full_process need_translate
   落地；组合任务 config 透传；stop 反注册 atexit。
E. 任务工厂 tasks + 编排 pipeline：任务构造字段/输出路径命名、
   ASR 覆盖注入、本地假 ASR 服务端到端出 SRT、已下载字幕跳过。
F. 线程层 threads：信号契约 + RetranslateThread 键值映射对齐
   （PySide6 在场时；Signal(dict) 会归一化键序，只能查值）。

负向：污染 → 确认检查能抓到（防「绿屏假象」）。N1-N6 六注入点
（红线 AST 扫描、config 默认值、失败率阈值、LLM 缓存键、适配器
缓存键、适配器委托）+ N7 八注入点回归守护（2026-10-19 自查修复
逐点还原，防新检查恒真）。

用法：
    python scripts/dev/_selftest_vt_engine.py [--net]

退出码 0 = 通过；非 0 = 有失败项（明细见输出）。
"""

import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
SRC = os.path.join(ROOT, "src")
PKG = os.path.join(SRC, "vt_engine")

PYPARSE = os.path.join(ROOT, "tools", "python", "python.exe")
if not os.path.exists(PYPARSE):
    PYPARSE = sys.executable

_RESULTS = []


def report(name, ok, detail=""):
    _RESULTS.append((name, bool(ok), detail))
    mark = "PASS" if ok else "FAIL"
    line = "[%s] %s" % (mark, name)
    if detail and not ok:
        line += "  <- " + detail
    print(line)


def _env(extra=None):
    """构造子进程环境。extra 里的 PYTHONPATH **领先于** SRC——
    负向注入的污染副本只有在最前面才会被 import 到。"""
    env = dict(os.environ)
    lead = []
    if extra and extra.get("PYTHONPATH"):
        lead.append(extra["PYTHONPATH"])
    lead.append(SRC)
    if env.get("PYTHONPATH"):
        lead.append(env["PYTHONPATH"])
    env["PYTHONPATH"] = os.pathsep.join(lead)
    env["VT_SELFTEST"] = "1"
    if extra:
        rest = {k: v for k, v in extra.items() if k != "PYTHONPATH"}
        env.update(rest)
    return env


def _run(code, extra_env=None):
    p = subprocess.run([PYPARSE, "-c", code], env=_env(extra_env),
                       capture_output=True, text=True, timeout=300)
    return p.returncode, p.stdout + p.stderr


# ================================================================ A 红线
def test_redline():
    # A1: AST 扫全包（含 threads），任何 videocaptioner 引用都不允许
    code = r'''
import ast, os, sys
bad = []
pkg = sys.argv[1] if len(sys.argv) > 1 else ""
root = pkg
for dirpath, _dirs, files in os.walk(root):
    for fn in files:
        if not fn.endswith(".py"):
            continue
        p = os.path.join(dirpath, fn)
        try:
            tree = ast.parse(open(p, encoding="utf-8").read())
        except SyntaxError as e:
            bad.append("%s: 语法错误 %s" % (p, e)); continue
        for node in ast.walk(tree):
            mod = ""
            if isinstance(node, ast.Import):
                mod = ".".join(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
            if "videocaptioner" in mod:
                bad.append("%s: import %s" % (p, mod))
print("\n".join(bad))
sys.exit(1 if bad else 0)
'''
    rc, out = _run(code, {"_ST_PKG": PKG})
    # code 通过 argv 传路径不可用（-c），改用内联路径
    code2 = code.replace('pkg = sys.argv[1] if len(sys.argv) > 1 else ""',
                         'pkg = %r' % PKG)
    rc, out = _run(code2)
    report("A1 全包 AST 无 videocaptioner 引用", rc == 0, out[-400:])

    # A2: 运行期导入隔离——import 全部子模块（threads 除外，需 Qt）
    code = r'''
import sys
sys.path.insert(0, r"@SRC@")
import vt_engine
import vt_engine.config, vt_engine.config_items, vt_engine.entities
import vt_engine.paths, vt_engine.cache, vt_engine.constants, vt_engine.log
import vt_engine.asr_data, vt_engine.asr_http, vt_engine.asr_local
import vt_engine.asr_core, vt_engine.translators, vt_engine.media
import vt_engine.llm_client, vt_engine.llm_context, vt_engine.style_manager
import vt_engine.translate_types, vt_engine.translate_base
import vt_engine.llm_translator, vt_engine.translate_factory
import vt_engine.subtitle_llm, vt_engine.tasks, vt_engine.pipeline
bad = [m for m in sys.modules if m.split(".")[0] == "videocaptioner"]
print("BAD:" + ",".join(bad))
sys.exit(1 if bad else 0)
'''.replace("@SRC@", SRC)
    rc, out = _run(code)
    report("A2 运行期导入隔离（零引擎模块）", rc == 0, out[-400:])

    # A3: threads 子包在场时同样零引擎（Qt 由 tools/python 提供）
    code = r'''
import sys
sys.path.insert(0, r"@SRC@")
import vt_engine.threads
bad = [m for m in sys.modules if m.split(".")[0] == "videocaptioner"]
print("BAD:" + ",".join(bad))
sys.exit(1 if bad else 0)
'''.replace("@SRC@", SRC)
    rc, out = _run(code)
    report("A3 threads 子包导入隔离", rc == 0, out[-300:])


# ================================================================ B config
def test_config():
    # B 节环境无关：不预设任何设置值，全部从实际 settings.json 推导——
    # 同一套检查要能跑在开发库、安装副本、全新空环境上。
    code = r'''
import json, os, sys, tempfile
sys.path.insert(0, r"@SRC@")
from vt_engine.config import Config, cfg, settings_path

fails = []
def chk(name, cond, detail=""):
    if not cond:
        fails.append(name + (" <- " + str(detail) if detail else ""))

raw = json.load(open(settings_path(), encoding="utf-8"))
chk("settings.json 可读且为 dict", isinstance(raw, dict))

# B1: 全量 round-trip——文件里实际存在的每个键，cfg 读出值序列化后
# 必须与文件值相等（枚举反构造/标量类型全链路）
checked = 0
mismatch = []
for _attr, item in cfg.items():
    g = raw.get(item.group)
    if not isinstance(g, dict) or item.name not in g:
        continue
    checked += 1
    want = g[item.name]
    got = item.serializer.serialize(item.value)
    if got != want:
        mismatch.append("%s.%s: file=%r cfg=%r"
                        % (item.group, item.name, want, got))
chk("B1 全量 round-trip（%d 键）" % checked,
    checked >= 40 and not mismatch, "; ".join(mismatch[:5]))

# B2: 类型保真（int 不漂成 float）
for _attr, item in cfg.items():
    g = raw.get(item.group)
    if not isinstance(g, dict) or item.name not in g:
        continue
    raw_v = g[item.name]
    if isinstance(raw_v, bool):
        continue
    if isinstance(raw_v, int):
        chk("B2 整数 %s.%s" % (item.group, item.name),
            isinstance(item.value, int)
            and not isinstance(item.value, bool),
            type(item.value).__name__)
    if isinstance(raw_v, float):
        chk("B2 浮点 %s.%s" % (item.group, item.name),
            abs(float(item.value) - raw_v) < 1e-9, item.value)

# B3: set -> 落盘 -> 新实例重载（持久化契约；临时文件不碰真设置）
with tempfile.TemporaryDirectory() as td:
    p = os.path.join(td, "settings.json")
    c1 = Config(p)
    c1.set(c1.batch_size, 33)
    c1.set(c1.translator_service,
            c1.translator_service.validator.options[2])
    c2 = Config(p)
    chk("set->reload batch_size", c2.batch_size.value == 33)
    chk("set->reload translator", c2.translator_service.value ==
        c1.translator_service.value)
    # 未知组保留
    c1._data.setdefault("SomeUnknownGroup", {"X": 1})
    c1.save()
    c3 = Config(p)
    chk("未知组保留", c3._data.get("SomeUnknownGroup", {}).get("X") == 1)
    # restart 项触发 appRestartSig
    fired = []
    c3.appRestartSig.connect(lambda: fired.append(1))
    c3.set(c3.dpi_scale, 2)
    chk("restart 信号", fired == [1])

# B4: 校验器纠正
from vt_engine.config_items import (BoolValidator, RangeValidator,
                                    OptionsValidator)
rv = RangeValidator(5, 50)
chk("范围钳制-下", rv.correct(1) == 5)
chk("范围钳制-上", rv.correct(99) == 50)
chk("范围合法", rv.validate(25) and not rv.validate(51)
    and not rv.validate("x"))
ov = OptionsValidator(["a", "b"])
chk("选项纠正", ov.correct("zzz") == "a" and ov.validate("b")
    and not ov.validate("c"))
bv = BoolValidator()
chk("布尔纠正", bv.correct("yes") is True and bv.validate(False))

# B5: 缺失文件不抛（首次运行）+ 多实例互不污染（回归事故）
with tempfile.TemporaryDirectory() as td:
    c = Config(os.path.join(td, "nope", "settings.json"))
    chk("缺失文件落默认", c.batch_size.value == 10
        and c.transcribe_model.value.value == "B 接口")
    c.set(c.batch_size, 42)
    c2 = Config(os.path.join(td, "other", "settings.json"))
    chk("多实例互不污染", c2.batch_size.value == 10)

# B6: 枚举反构造失败保留默认 + load 幂等复位
with tempfile.TemporaryDirectory() as td:
    p = os.path.join(td, "settings.json")
    json.dump({"Translate": {"TranslatorServiceEnum": "不存在的服务"}},
              open(p, "w", encoding="utf-8"))
    c = Config(p)
    chk("脏值回落默认", c.translator_service.value.value == "微软翻译",
        c.translator_service.value)
    c.set(c.batch_size, 25)
    c.load()
    chk("load 读回文件值", c.batch_size.value == 25, c.batch_size.value)
    _d = json.load(open(p, encoding="utf-8"))
    _d["Translate"].pop("BatchSize", None)
    json.dump(_d, open(p, "w", encoding="utf-8"))
    c.load()
    chk("load 删键回落默认", c.batch_size.value == 10, c.batch_size.value)

print("\n".join(fails))
sys.exit(1 if fails else 0)
'''.replace("@SRC@", SRC)
    rc, out = _run(code)
    report("B 设置层契约（round-trip/持久化/纠正/兜底/信号）", rc == 0,
           out[-800:])

# ================================================================ C entities
def test_entities():
    code = r'''
import dataclasses, sys
sys.path.insert(0, r"@SRC@")
from vt_engine import entities as E

fails = []
def chk(name, cond, detail=""):
    if not cond:
        fails.append(name + (" <- " + str(detail) if detail else ""))

# C1: 与引擎 entities 字段逐一比对（引擎在场才跑）
try:
    import videocaptioner.core.entities as VE
    have_engine = True
except Exception:
    have_engine = False
if have_engine:
    pairs = [
        (E.SubtitleProcessData, VE.SubtitleProcessData),
        (E.AudioStreamInfo, VE.AudioStreamInfo),
        (E.VideoInfo, VE.VideoInfo),
        (E.TranscribeConfig, VE.TranscribeConfig),
        (E.SubtitleConfig, VE.SubtitleConfig),
        (E.SynthesisConfig, VE.SynthesisConfig),
        (E.TranscribeTask, VE.TranscribeTask),
        (E.SubtitleTask, VE.SubtitleTask),
        (E.SynthesisTask, VE.SynthesisTask),
        (E.TranscriptAndSubtitleTask, VE.TranscriptAndSubtitleTask),
        (E.FullProcessTask, VE.FullProcessTask),
    ]
    for mine, theirs in pairs:
        mf = [f.name for f in dataclasses.fields(mine)]
        tf = [f.name for f in dataclasses.fields(theirs)]
        chk("字段一致 " + mine.__name__, mf == tf,
            "mine=%s engine=%s" % (mf, tf))
    # 枚举取值一致
    for name in ("TranscribeModelEnum", "TranscribeLanguageEnum",
                 "FasterWhisperModelEnum", "LLMServiceEnum",
                 "TranslatorServiceEnum", "SubtitleLayoutEnum"):
        mine = getattr(E, name)
        theirs = getattr(VE, name)
        mv = {m.value for m in mine}
        tv = {m.value for m in theirs}
        chk("枚举取值 " + name, mv == tv, "diff=%s" % (mv ^ tv))
    # 新增枚举与引擎比对
    for name in ("TranscribeOutputFormatEnum", "SubtitleRenderModeEnum",
                 "VideoQualityEnum", "VadMethodEnum", "WhisperModelEnum"):
        mine = getattr(E, name)
        theirs = getattr(VE, name)
        mv = {m.value for m in mine}
        tv = {m.value for m in theirs}
        chk("新枚举取值 " + name, mv == tv, "diff=%s" % (mv ^ tv))
    # TargetLanguage
    from vt_engine.translate_types import TargetLanguage as TL
    mv = {m.value for m in TL}
    tv = {m.value for m in VE.TargetLanguage} if hasattr(VE, "TargetLanguage") else None
    if tv is None:
        from videocaptioner.core.translate.types import TargetLanguage as VTL
        tv = {m.value for m in VTL}
    chk("TargetLanguage 取值", mv == tv, "diff=%s" % (mv ^ tv))

# C2: 枚举可反构造 + LANGUAGES 覆盖
from vt_engine.config import cfg
chk("按标签反构造", E.TranscribeLanguageEnum(cfg.transcribe_language.value.value)
    is cfg.transcribe_language.value)
chk("LANGUAGES 有日语", E.LANGUAGES.get("日本語") == "ja")
chk("LANGUAGES 无双语重复键", len(E.LANGUAGES) == 112, len(E.LANGUAGES))

# C3: 任务默认值
t = E.TranscribeTask(file_path="x.mp4")
chk("task_id 8 位", len(t.task_id) == 8 and t.task_id.isalnum())
chk("selected_audio_track_index 默认 0", t.selected_audio_track_index == 0)
s = E.SubtitleTask(subtitle_path="x.srt")
chk("SubtitleTask need_next_task 默认 True", s.need_next_task is True)

# C4: 平台模型列表（Windows 全量）
models = E.get_available_transcribe_models()
chk("Win 全量模型", len(models) == len(list(E.TranscribeModelEnum)))

print("\n".join(fails))
sys.exit(1 if fails else 0)
'''.replace("@SRC@", SRC)
    rc, out = _run(code)
    report("C 数据类/枚举契约（与引擎逐字段比对）", rc == 0, out[-800:])


# ================================================================ D 翻译编排
def test_translate():
    # 隔离缓存根：桩翻译器会写 translate 缓存，写进真实 data 目录会
    # ① 污染用户缓存 ② 让结果依赖历史缓存（D1 命中 D3 的假绿/假红都见过）。
    with tempfile.TemporaryDirectory(prefix="vt_engine_st_trans_") as td:
        _run_translate_isolated(td)


def _run_translate_isolated(temp_root):
    code = r'''
import sys
sys.path.insert(0, r"@SRC@")
from vt_engine.asr_data import ASRData, ASRDataSeg
from vt_engine.entities import SubtitleProcessData
from vt_engine.translate_base import (BaseTranslator,
                                      TranslationIncompleteError)
from vt_engine.translate_types import TargetLanguage
from vt_engine.llm_translator import LLMTranslator, parse_llm_json

fails = []
def chk(name, cond, detail=""):
    if not cond:
        fails.append(name + (" <- " + str(detail) if detail else ""))

TL = TargetLanguage.SIMPLIFIED_CHINESE

class Stub(BaseTranslator):
    """可控桩翻译器：mode=ok/err/half/cancel。"""
    def __init__(self, mode="ok", **kw):
        super().__init__(thread_num=2, batch_num=2, target_language=TL,
                         update_callback=None)
        self.mode = mode
    def _translate_chunk(self, chunk):
        if self.mode == "err":
            raise RuntimeError("boom")
        if self.mode == "half":
            for i, d in enumerate(chunk):
                d.translated_text = "ERROR" if i == 0 else "译文"
        else:
            for d in chunk:
                d.translated_text = "译文-" + str(d.index)
        return chunk

def make(n=4):
    return ASRData([ASRDataSeg(text="原文%d" % i, start_time=i * 1000,
                               end_time=i * 1000 + 900)
                    for i in range(1, n + 1)])

# D1: 正常路径——译文回填 + 断言通过
data = make()
out = Stub("ok").translate_subtitle(data)
chk("D1 译文回填", all(s.translated_text.startswith("译文-")
                       for s in out.segments))

# D2: 0 条抛错
try:
    Stub("ok").translate_subtitle(ASRData([]))
    fails.append("D2 0 条未抛错")
except TranslationIncompleteError:
    pass

# D3: >=50% 失败抛 RuntimeError（ERROR 记账）。
# 注意用独立子类：缓存键含类名，D1 的 Stub 成功条目会把同内容的 D3 命中去。
class StubHalf(Stub):
    def _translate_chunk(self, chunk):
        for i, d in enumerate(chunk):
            d.translated_text = "ERROR" if i == 0 else "译文"
        return chunk

try:
    StubHalf().translate_subtitle(make(4))
    fails.append("D3 >=50% 未抛错")
except RuntimeError as e:
    chk("D3 报错口径", "segments failed" in str(e), str(e))

# D4: 任何缺失译文都被落盘断言拦下（1/6 也一样——引擎的可观察行为：
# _parallel_translate 的 <50% 分支只记警告，_assert_translation_complete
# 对单条缺失照样抛，部分翻译绝不落盘）
class MostlyOk(Stub):
    def _translate_chunk(self, chunk):
        for i, d in enumerate(chunk):
            d.translated_text = "ERROR" if d.index == 1 else "译文"
        return chunk
try:
    MostlyOk().translate_subtitle(make(6))
    fails.append("D4 单条缺失未拦截")
except TranslationIncompleteError as e:
    chk("D4 落盘断言拦单条缺失", "1/6" in str(e), str(e))
except Exception as e:
    fails.append("D4 异常类型不符: %r" % e)

# D5: 缓存键形式（机翻 vs LLM 带模型名）
t = Stub("ok")
key = t._get_cache_key([SubtitleProcessData(index=1, original_text="x")])
chk("D5 机翻缓存键", key.startswith("Stub:") and key.endswith(":简体中文"),
    key)
lt = LLMTranslator(thread_num=1, batch_num=1, target_language=TL,
                   model="m1")
k2 = lt._get_cache_key([SubtitleProcessData(index=1, original_text="x")])
chk("D5 LLM 缓存键带模型", k2.startswith("LLMTranslator:")
    and k2.endswith(":简体中文:m1"), k2)

# D6: stop 语义（is_running=False + executor 关闭）
t = Stub("ok")
t.stop()
chk("D6 stop", t.is_running is False and t.executor is None)

# D7: JSON 容忍解析
chk("D7a 纯 JSON", parse_llm_json('{"1": "甲"}') == {"1": "甲"})
chk("D7b 围栏", parse_llm_json('前言\n```json\n{"1": "甲"}\n```\n后记')
    == {"1": "甲"})
chk("D7c 尾逗号", parse_llm_json('{"1": "甲",}') == {"1": "甲"})
try:
    parse_llm_json("not json at all")
    fails.append("D7d 垃圾未抛 ValueError")
except ValueError:
    pass

# D8: 反思模式校验——缺 native_translation 检出
lt_reflect = LLMTranslator(thread_num=1, batch_num=1, target_language=TL,
                           model="m1", is_reflect=True)
ok, msg = lt_reflect._validate_llm_response(
    {"1": {"native_translation": "甲"}}, {"1": "原"})
chk("D8a 反思合法", ok)
ok2, msg2 = lt_reflect._validate_llm_response({"1": {"other": "x"}},
                                              {"1": "原"})
chk("D8b 反思缺字段检出", not ok2 and "native_translation" in msg2)
ok3, msg3 = lt._validate_llm_response({"2": "多余"}, {"1": "原"})
chk("D8c 键集检出", not ok3 and "Extra keys" in msg3)

# D9: 工厂产出的**每个**服务都必须可编排（hasattr translate_subtitle）
# ——2026-10-18 实测事故：机翻器是 chunk 级 API，缺适配器时编排层
# 直接 AttributeError，机翻链路全瘫还被误判成「服务不可用」。
from vt_engine.entities import SubtitleConfig, TranslatorServiceEnum
from vt_engine.translate_factory import (create_translator_from_config,
                                      MachineTranslatorAdapter)
for svc in (TranslatorServiceEnum.BING,
            TranslatorServiceEnum.GOOGLE,
            TranslatorServiceEnum.DEEPLX):
    cfg = SubtitleConfig(translator_service=svc,
                         target_language=TL,
                         thread_num=2, batch_size=2)
    tr = create_translator_from_config(cfg)
    chk("D9 可编排 %s" % svc.value,
        hasattr(tr, "translate_subtitle")
        and hasattr(tr, "stop")
        and hasattr(tr, "_translate_chunk"),
        type(tr).__name__)
    tr.stop()

# D10: 适配器委托 + 缓存键沿用内层类名（引擎旧缓存不失效）
class FakeInner:
    def __init__(self):
        self.calls = 0
    def translate(self, chunk):
        self.calls += 1
        for d in chunk:
            d.translated_text = "译:" + d.original_text
        return chunk
inner = FakeInner()
ad = MachineTranslatorAdapter(inner, thread_num=2, batch_num=2,
                              target_language=TL)
out = ad.translate_subtitle(make(4))
chk("D10 适配器委托", inner.calls == 2
    and all(sg.translated_text.startswith("译:")
            for sg in out.segments), inner.calls)
k = ad._get_cache_key([SubtitleProcessData(index=1, original_text="x")])
chk("D10 缓存键内层类名", k.startswith("FakeInner:"), k)
ad.stop()

# D11: agent loop 纠正反馈必须自带上下文——单通道 chat() 只取「首个
# system + 末位 user」，多轮历史被压扁；反馈丢了原始输入与坏响应，
# 模型看不到待修数据，三轮纠正全废（2026-10-19 自查修复项）。
import vt_engine.llm_translator as LT
_calls = []
def _fake_chat(user, system="", model="", max_tokens=None, use_cache=True):
    _calls.append(user)
    if len(_calls) == 1:
        return '{"1": "只翻了一条"}'      # 键集不符 → 触发反馈轮
    return '{"1": "\u7532", "2": "\u4e59"}'   # 第二轮纠正成功
LT.chat = _fake_chat
LT.ai_enabled = lambda: True
lt2 = LLMTranslator(thread_num=1, batch_num=2, target_language=TL,
                    model="m1")
out2 = lt2.translate_subtitle(make(2))
chk("D11 纠正循环产出", [s.translated_text for s in out2.segments]
    == ["\u7532", "\u4e59"], [s.translated_text for s in out2.segments])
chk("D11 反馈含原始输入", len(_calls) >= 2 and "\u539f\u65871" in _calls[1]
    and "Error" in _calls[1], _calls[1][:120] if len(_calls) > 1 else "n/a")
lt2.stop()

# D12: split_subtitle 单块失败回退原文，不是 TypeError（_run_chunks
# 回落写回 utterance 三元组，消费者按 parts 列表用会炸）。
import vt_engine.subtitle_llm as SL
SL.ai_enabled = lambda: True
_state = {"n": 0}
def _flaky(text, system="", model="", use_cache=True):
    _state["n"] += 1
    if _state["n"] == 1:
        raise RuntimeError("\u6a21\u62df\u7f51\u7edc\u4e2d\u65ad")
    return text.replace("\u3002", "<br>")
SL.chat = _flaky
words = ASRData([ASRDataSeg(text=t, start_time=i * 400,
                            end_time=i * 400 + 350)
                 for i, t in enumerate(
                     ["\u4f60", "\u597d", "\u4e16", "\u754c", "\u3002",
                      "\u518d", "\u89c1", "\u3002"])])
sp = SL.split_subtitle(words, thread_num=1)
chk("D12 \u5355\u5757\u5931\u8d25\u56de\u9000", sp is not None
    and len(sp.segments) == 2
    and any("\u4f60\u597d\u4e16\u754c" in s.text for s in sp.segments),
    [s.text for s in (sp.segments if sp else [])])

# D13: 说话人锚定提示词换行（heredoc /n \u8179\u9cc4\u8001\u5757，2026-10-19）
from vt_engine.pipeline import _speaker_rule_prompt
sp_data = ASRData([ASRDataSeg(text="[\u8bf4\u8bdd\u4eba1] \u4f60\u597d\u4e16\u754c",
                              start_time=0, end_time=1000)])
prompt = _speaker_rule_prompt(sp_data)
chk("D13 \u63d0\u793a\u8bcd\u6362\u884c\u6b63\u786e",
    "/n" not in prompt and "Rules:\n1)" in prompt, prompt[:80])

# D14: run_full_process \u7684 need_translate \u53c2\u6570\u5fc5\u987b\u751f\u6548\uff08\u66fe\u9759\u9ed8\u5ffd\u7565\uff09
import vt_engine.pipeline as PL
from vt_engine.tasks import TaskFactory as TF
_seen = []
PL.transcribe_media = lambda t, callback=None: _seen.append("t") or ""
PL.process_subtitle = lambda s, callback=None, on_data=None: (
    _seen.append(s.subtitle_config.need_translate) or "")
from vt_engine.config import cfg as _c
_c.need_translate.value = True
PL.run_full_process("x.mp4", need_translate=False)
PL.run_full_process("x.mp4", need_translate=True)
chk("D14 need_translate \u843d\u5730",
    _seen == ["t", False, "t", True], _seen)

# D15: \u7ec4\u5408\u4efb\u52a1\u5de5\u5382\u900f\u4f20\u8c03\u7528\u65b9 config\uff08\u66fe\u63a5\u53d7\u4f46\u4e22\u5f03\uff09
t_a, s_b = object(), object()
tt = TF.create_transcript_and_subtitle_task(
    "x.mp4", transcribe_config=t_a, subtitle_config=s_b)
chk("D15a \u8f6c\u5f55+\u5b57\u5e55 config \u900f\u4f20",
    tt.transcribe_config is t_a and tt.subtitle_config is s_b)
ft = TF.create_full_process_task("x.mp4", transcribe_config=t_a,
                                 subtitle_config=s_b)
chk("D15b \u5168\u6d41\u7a0b config \u900f\u4f20",
    ft.transcribe_config is t_a and ft.subtitle_config is s_b)

# D16: stop \u53cd\u6ce8\u518c atexit\u2014\u2014\u5b9e\u4f8b\u4e0d\u518d\u88ab\u9a7b\u7559\u5230\u8fdb\u7a0b\u9000\u51fa\u3002
# \u6ce8\uff1a_ncallbacks() \u5728 3.12 \u4e0d\u53cd\u5c04\u79fb\u9664\uff08\u5df2\u5b9e\u9a8c\u9a8c\u8bc1\uff09\uff0c\u6539\u7528\u5f31\u5f15\u7528\u5224\u5b9a\u53ef\u56de\u6536\u6027\u3002
import gc, weakref
_refs = []
for _ in range(5):
    _t = Stub("ok")
    _refs.append(weakref.ref(_t))
    _t.stop()
del _t  # \u5faa\u73af\u53d8\u91cf\u672c\u8eab\u4ecd\u6301\u64e6\u6700\u540e\u4e00\u4e2a\u5b9e\u4f8b
gc.collect()
chk("D16 \u5b9e\u4f8b\u53ef\u56de\u6536\uff08atexit \u4e0d\u9a7b\u7559\uff09",
    all(r() is None for r in _refs),
    [r() is not None for r in _refs])

print("\n".join(fails))
sys.exit(1 if fails else 0)
'''.replace("@SRC@", SRC)
    rc, out = _run(code, {"VT_DATA_ROOT": temp_root})
    report("D 翻译编排契约（桩翻译器/缓存键/解析/校验/纠正循环）", rc == 0,
           out[-800:])


# ================================================================ E 任务/编排
def test_pipeline():
    code = r'''
import json, os, sys, threading, tempfile, time
from http.server import BaseHTTPRequestHandler, HTTPServer
sys.path.insert(0, r"@SRC@")

fails = []
def chk(name, cond, detail=""):
    if not cond:
        fails.append(name + (" <- " + str(detail) if detail else ""))

# ---- 本地假 ASR 服务 ----
class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass
    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n)
        auth = self.headers.get("Authorization", "")
        if "Bearer test-key" not in auth:
            self.send_response(401); self.end_headers()
            self.wfile.write(b'{"error":"bad key"}'); return
        if b"audio.mp3" not in body or b"file" not in body:
            self.send_response(400); self.end_headers()
            self.wfile.write(b'{"error":"no file"}'); return
        # 校验 multipart 必填字段（引擎契约）
        for must in (b'name="model"', b'name="response_format"',
                     b'verbose_json', b'name="prompt"'):
            if must not in body:
                self.send_response(400); self.end_headers()
                self.wfile.write(b'{"error":"missing field"}'); return
        resp = {"text": "你好世界。这是一段测试。",
                "segments": [
                    {"start": 0.0, "end": 1.5, "text": "你好世界。"},
                    {"start": 1.5, "end": 3.2, "text": "这是一段测试。"}]}
        data = json.dumps(resp, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

srv = HTTPServer(("127.0.0.1", 0), H)
port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()

# ---- 合成 3 秒测试视频（testsrc + sine） ----
tmp = tempfile.mkdtemp(prefix="vt_engine_st_")
video = os.path.join(tmp, "smoke.mp4")
import subprocess
ff = None
from vt_engine.media import find_ffmpeg
ff = find_ffmpeg()
r = subprocess.run([ff, "-hide_banner", "-loglevel", "error",
                    "-f", "lavfi", "-i",
                    "testsrc=duration=3:size=160x120:rate=10",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
                    "-shortest", "-y", video],
                   capture_output=True, text=True)
chk("E0 合成测试视频", r.returncode == 0 and os.path.isfile(video),
    r.stderr[-200:])

from vt_engine import entities as ent
from vt_engine.tasks import TaskFactory
from vt_engine.pipeline import transcribe_media, process_subtitle

task = TaskFactory.create_transcribe_task(video, need_next_task=False)
task.transcribe_config.transcribe_model = ent.TranscribeModelEnum.WHISPER_API
task.transcribe_config.whisper_api_base = "http://127.0.0.1:%d/v1" % port
task.transcribe_config.whisper_api_key = "test-key"
task.transcribe_config.whisper_api_model = "fake-whisper"
task.transcribe_config.transcribe_language = "zh"
task.output_path = os.path.join(tmp, "smoke.srt")

try:
    transcribe_media(task, callback=lambda p, m: None)
    chk("E1 端到端出 SRT", os.path.isfile(task.output_path))
    content = open(task.output_path, encoding="utf-8").read()
    chk("E2 SRT 两条 + 时间戳", content.count("-->") == 2
        and "00:00:01,500" in content, content[:200])

    # E3: ALL 格式展开 + need_next_task 补 srt
    task2 = TaskFactory.create_transcribe_task(video, need_next_task=True)
    task2.transcribe_config.transcribe_model = ent.TranscribeModelEnum.WHISPER_API
    task2.transcribe_config.whisper_api_base = "http://127.0.0.1:%d/v1" % port
    task2.transcribe_config.whisper_api_key = "test-key"
    task2.transcribe_config.whisper_api_model = "fake-whisper"
    task2.transcribe_config.transcribe_language = "zh"
    task2.transcribe_config.output_format = ent.TranscribeOutputFormatEnum.ALL
    task2.output_path = os.path.join(tmp, "smoke_all.srt")
    transcribe_media(task2, callback=lambda p, m: None)
    base = os.path.splitext(task2.output_path)[0]
    exts = sorted(f.split(".")[-1] for f in os.listdir(os.path.dirname(base))
                  if f.startswith(os.path.basename(base)))
    chk("E3 ALL 展开 srt/vtt/ass/txt",
        set(exts) >= {"srt", "vtt", "ass", "txt"}, exts)

    # E4: 已下载字幕跳过转录
    sub_dir = os.path.join(tmp, "subtitle")
    os.makedirs(sub_dir, exist_ok=True)
    dl = os.path.join(sub_dir, "【下载字幕】smoke.srt")
    open(dl, "w", encoding="utf-8").write("1\n00:00:00,000 --> 00:00:01,000\n测试\n\n")
    task3 = TaskFactory.create_transcribe_task(video, need_next_task=True)
    transcribe_media(task3, callback=lambda p, m: None)
    chk("E4 已下载字幕跳过", task3.output_path == dl)

    # E5: process_subtitle 关翻译直通（need_translate=False）
    st = TaskFactory.create_subtitle_task(task.output_path,
                                          need_next_task=False)
    st.subtitle_config.need_translate = False
    st.subtitle_config.need_optimize = False
    st.subtitle_config.need_split = False
    st.output_path = os.path.join(tmp, "smoke_out.srt")
    process_subtitle(st, callback=lambda p, m: None)
    chk("E5 process_subtitle 直通", os.path.isfile(st.output_path))

    # E6: 失败路径——视频不存在抛 PipelineError（不是裸异常）
    from vt_engine.pipeline import PipelineError
    bad = TaskFactory.create_transcribe_task(os.path.join(tmp, "nope.mp4"))
    try:
        transcribe_media(bad)
        fails.append("E6 缺失文件未抛错")
    except PipelineError:
        pass
except Exception as e:
    import traceback
    fails.append("E 执行期异常: %s" % traceback.format_exc()[-500:])

print("\n".join(fails))
sys.exit(1 if fails else 0)
'''.replace("@SRC@", SRC)
    rc, out = _run(code)
    report("E 任务工厂 + 端到端编排（假 ASR 服务）", rc == 0, out[-900:])


# ================================================================ F 线程契约
def test_threads():
    code = r'''
import sys
sys.path.insert(0, r"@SRC@")
fails = []
try:
    import vt_engine.threads as TH
except Exception as e:
    print("SKIP: PySide6 不可用（%s）" % e)
    sys.exit(0)

want = {
    "TranscriptThread": ["finished", "progress", "error"],
    "VideoInfoThread": ["finished", "error"],
    "SubtitleThread": ["finished", "progress", "update", "update_all",
                       "error"],
    "RetranslateThread": ["finished", "progress", "error"],
    "VideoDownloadThread": ["finished", "progress", "error"],
}
for cls_name, sigs in want.items():
    cls = getattr(TH, cls_name, None)
    if cls is None:
        fails.append("缺线程类 " + cls_name); continue
    for s in sigs:
        if not hasattr(cls, s):
            fails.append("%s 缺信号 %s" % (cls_name, s))

# 构造契约（不起线程）
t = TH.TranscriptThread.__init__  # 存在性
import inspect
sig = inspect.signature(TH.TranscriptThread.__init__)
chk = list(sig.parameters)[1:] == ["task"]
if not chk:
    fails.append("TranscriptThread(task) 签名不符: %s" % list(sig.parameters))
d = TH.VideoDownloadThread("http://x", ".")
if d.url != "http://x" or d.work_dir != ".":
    fails.append("VideoDownloadThread 构造不符")

# F2: RetranslateThread 键值映射对齐 from_json——selected_data 是表格选中序、
# 不保证有序，直接 list() 会把译文错标到别的键上（2026-10-19 自查修复项）。
# ⚠ 断言必须查**键值映射**：Signal(dict) 发射时经 QVariantMap 会把键序
# 归一化（按键排序），查键序对干净/污染代码恒真，查不到问题。
import vt_engine.threads.subtitle_thread as ST
ST.translate_with_machine_fallback = (
    lambda config, prompt, cb, asr_data, on_translator=None: asr_data)
from vt_engine.entities import SubtitleConfig as _SC
from vt_engine.translate_types import TargetLanguage as _TL
sel = {"5": {"start_time": 4000, "end_time": 4900,
             "original_subtitle": "\u4e94", "translated_subtitle": "\u8bd1\u4e94"},
       "2": {"start_time": 1000, "end_time": 1900,
             "original_subtitle": "\u4e8c", "translated_subtitle": "\u8bd1\u4e8c"}}
cap = []
th = ST.RetranslateThread(sel, _SC(target_language=_TL.SIMPLIFIED_CHINESE))
th.finished.connect(lambda dd: cap.append(dd))
th.run()
if not cap or cap[0].get("5") != "\u8bd1\u4e94" \
        or cap[0].get("2") != "\u8bd1\u4e8c":
    fails.append("RetranslateThread \u952e\u503c\u9519\u4f4d: %s"
                 % (cap[0] if cap else "no signal"))

# G1: 缩略图路径必须按**完整路径**派生（2026-10-19 修复项）。
# 旧实现用 Path(file_path).stem 命名，A/第01集.mp4 与 B/第01集.mp4 落到同一个
# 缓存文件 → 缩略图串味（B 探测后 A 显示别的片的画面），且从不清理。
import vt_engine.threads.video_info_thread as VIT
_tp = VIT._thumbnail_path
_SP = chr(92)                      # 反斜杠：避免与外层原始三引号的转义层级打架
_A = "A" + _SP + "第01集"
_p1 = _tp(_A + ".mp4")
_p2 = _tp("B" + _SP + "第01集.mp4")
_p3 = _tp(_A + ".mkv")
if _p1 == _p2:
    fails.append("VideoInfoThread 缩略图跨目录同名串味: %s" % _p1)
if _p1 == _p3:
    fails.append("VideoInfoThread 缩略图跨扩展名同名串味: %s" % _p1)
if _tp(_A + ".mp4") != _p1:
    fails.append("VideoInfoThread 缩略图路径不稳定（无法复用缓存）")
if not _p1.lower().endswith(".jpg"):
    fails.append("VideoInfoThread 缩略图扩展名丢失: %s" % _p1)
_bn = _p1.rsplit(_SP, 1)[-1].rsplit("/", 1)[-1]
if any(c in _bn for c in '<>:"|?*'):
    fails.append("VideoInfoThread 缩略图文件名含非法字符: %s" % _bn)

print("\n".join(fails))
sys.exit(1 if fails else 0)
'''.replace("@SRC@", SRC)
    rc, out = _run(code)
    report("F 线程层信号契约", rc == 0, out[-400:])


# ================================================================ 负向注入
def _pollute(rel_path, old, new):
    """把 vt_engine 复制到临时目录并对某文件注入缺陷，返回临时根目录。

    注入副本的 ``_bootstrap.py`` 改指真实 src——否则包内
    ``import engine_*``（平铺接缝）在副本里不可见。
    """
    import shutil
    tmp = tempfile.mkdtemp(prefix="vt_engine_neg_")
    dst = os.path.join(tmp, "vt_engine")
    shutil.copytree(PKG, dst,
                    ignore=shutil.ignore_patterns("__pycache__"))
    boot = os.path.join(dst, "_bootstrap.py")
    s = open(boot, encoding="utf-8").read()
    s = s.replace('os.path.dirname(os.path.dirname(os.path.abspath(__file__)))',
                  'os.path.abspath(%r)' % SRC)
    open(boot, "w", encoding="utf-8", newline="").write(s)
    target = os.path.join(dst, rel_path)
    s = open(target, encoding="utf-8").read()
    assert old in s, "污染锚点未命中: %s" % rel_path
    open(target, "w", encoding="utf-8", newline="").write(
        s.replace(old, new, 1))
    return tmp


def test_negative():
    # N1: 红线 AST 扫描抓得到注入的 import videocaptioner
    tmp = _pollute("paths.py",
                   "from engine_paths import (",
                   "import videocaptioner\nfrom engine_paths import (")
    code = ("import ast, os, sys\n"
            "bad = []\n"
            "for dirpath, _d, files in os.walk(%r):\n"
            "    for fn in files:\n"
            "        if fn.endswith('.py'):\n"
            "            p = os.path.join(dirpath, fn)\n"
            "            tree = ast.parse(open(p, encoding='utf-8').read())\n"
            "            for node in ast.walk(tree):\n"
            "                mod = ''\n"
            "                if isinstance(node, ast.Import):\n"
            "                    mod = '.'.join(a.name for a in node.names)\n"
            "                elif isinstance(node, ast.ImportFrom):\n"
            "                    mod = node.module or ''\n"
            "                if 'videocaptioner' in mod:\n"
            "                    bad.append(p)\n"
            "sys.exit(0 if bad else 3)\n" % os.path.join(tmp, "vt_engine"))
    rc, out = _run(code, {"PYTHONPATH": tmp + os.pathsep + SRC})
    report("N1 红线检查能抓到注入引擎 import", rc == 0, "rc=%s %s" % (rc, out[-200:]))

    # N2: config 默认值污染被 round-trip 检查抓到
    tmp = _pollute("config.py",
                   '"Translate", "BatchSize", 10, (5, 50))',
                   '"Translate", "BatchSize", 99, (5, 50))')
    code = ("import os, sys, json, tempfile\n"
            "from vt_engine.config import Config\n"
            "p = os.path.join(tempfile.mkdtemp(), 'settings.json')\n"
            "c = Config(p)\n"
            "sys.exit(0 if c.batch_size.value == 99 else 3)\n")
    rc, out = _run(code, {"PYTHONPATH": tmp + os.pathsep + SRC})
    report("N2 config 默认值污染被抓到", rc == 0, "rc=%s" % rc)

    # N3: 失败率阈值污染（0.5→0.99）被 >=50% 抛错检查抓到
    tmp = _pollute("translate_base.py",
                   "if fail_rate >= 0.5:",
                   "if fail_rate >= 0.99:")
    code = ("import sys\n"
            "from vt_engine.asr_data import ASRData, ASRDataSeg\n"
            "from vt_engine.translate_base import BaseTranslator\n"
            "from vt_engine.translate_types import TargetLanguage\n"
            "class Stub(BaseTranslator):\n"
            "    def _translate_chunk(self, chunk):\n"
            "        for i, d in enumerate(chunk):\n"
            "            d.translated_text = 'ERROR' if i == 0 else '译文'\n"
            "        return chunk\n"
            "data = ASRData([ASRDataSeg(text='x', start_time=i*1000,\n"
            "               end_time=i*1000+900) for i in range(1, 5)])\n"
            "try:\n"
            "    Stub(2, 2, TargetLanguage.SIMPLIFIED_CHINESE,\n"
            "         None).translate_subtitle(data)\n"
            "    anomaly = True  # 完全没抛错 = 阈值检查失效\n"
            "except RuntimeError as e:\n"
            "    anomaly = 'segments failed' not in str(e)\n"
            "sys.exit(0 if anomaly else 3)  # 0 = 抓到污染\n")
    rc, out = _run(code, {"PYTHONPATH": tmp + os.pathsep + SRC})
    report("N3 失败率阈值污染被抓到", rc == 0, "rc=%s" % rc)

    # N4: LLM 缓存键去掉模型名被键形检查抓到
    tmp = _pollute("llm_translator.py",
                   'return "%s:%s:%s:%s" % (type(self).__name__,\n'
                   "                                generate_cache_key(chunk), name, self.model)",
                   'return "%s:%s:%s" % (type(self).__name__,\n'
                   "                             generate_cache_key(chunk), name)")
    code = ("import sys\n"
            "from vt_engine.entities import SubtitleProcessData\n"
            "from vt_engine.llm_translator import LLMTranslator\n"
            "from vt_engine.translate_types import TargetLanguage\n"
            "lt = LLMTranslator(1, 1, TargetLanguage.SIMPLIFIED_CHINESE,\n"
            "                   model='m1')\n"
            "k = lt._get_cache_key(\n"
            "    [SubtitleProcessData(index=1, original_text='x')])\n"
            "sys.exit(0 if not k.endswith(':简体中文:m1') else 3)\n")
    rc, out = _run(code, {"PYTHONPATH": tmp + os.pathsep + SRC})
    report("N4 LLM 缓存键污染被抓到", rc == 0, "rc=%s" % rc)


    # N5: 适配器缓存键改用自身类名 -> 与引擎缓存断链，D10 检查抓到
    tmp = _pollute("translate_factory.py",
                   "type(self._inner).__name__,",
                   "type(self).__name__,")
    code = r'''
import sys
from vt_engine.asr_data import ASRData, ASRDataSeg
from vt_engine.entities import SubtitleProcessData
from vt_engine.translate_types import TargetLanguage
from vt_engine.translate_factory import MachineTranslatorAdapter
class FakeInner:
    def translate(self, chunk):
        return chunk
ad = MachineTranslatorAdapter(FakeInner(), 1, 1,
                              TargetLanguage.SIMPLIFIED_CHINESE)
k = ad._get_cache_key(
    [SubtitleProcessData(index=1, original_text="x")])
sys.exit(0 if not k.startswith("FakeInner:") else 3)
'''
    rc, out = _run(code, {"PYTHONPATH": tmp + os.pathsep + SRC,
                          "VT_DATA_ROOT": tempfile.mkdtemp()})
    report("N5 适配器缓存键污染被抓到", rc == 0, "rc=%s" % rc)
    # N6: 适配器不委托内层 -> D10 委托检查抓到
    tmp = _pollute("translate_factory.py",
                   "return self._inner.translate(chunk)",
                   "return chunk")
    code = r'''
import sys
from vt_engine.asr_data import ASRData, ASRDataSeg
from vt_engine.translate_types import TargetLanguage
from vt_engine.translate_factory import MachineTranslatorAdapter
class FakeInner:
    def __init__(self):
        self.calls = 0
    def translate(self, chunk):
        self.calls += 1
        return chunk
inner = FakeInner()
ad = MachineTranslatorAdapter(inner, 1, 1,
                              TargetLanguage.SIMPLIFIED_CHINESE)
data = ASRData([ASRDataSeg(text="x", start_time=0,
                           end_time=900)])
try:
    ad.translate_subtitle(data)
except Exception:
    pass
sys.exit(0 if inner.calls == 0 else 3)
'''
    rc, out = _run(code, {"PYTHONPATH": tmp + os.pathsep + SRC,
                          "VT_DATA_ROOT": tempfile.mkdtemp()})
    report("N6 适配器委托污染被抓到", rc == 0, "rc=%s" % rc)

# ================================================================ N7 新检查负向守护
# 2026-10-19 自查新增检查（D11-D16/F2）的回归守护：把每处修复还原到
# 污染副本，确认对应新检查**确实抓得到**——F2 曾因 Signal(dict) 经
# QVariantMap 归一化键序而恒真（绿屏假象），负向守护是唯一解药。
# 检查代码约定：exit 0 = 干净代码通过；非 0 = 污染被抓住；77 = 跳过。
_NEG7 = []


def _neg7(name, rel, new, old, check):
    _NEG7.append((name, rel, new, old, check))


#: D13 —— 说话人提示词 Rules:/n（heredoc \n 腐蚀）
_neg7("D13 说话人提示词换行", "pipeline.py",
      '"[说话人N] (Speaker N) marker. Rules:\\n"',
      '"[说话人N] (Speaker N) marker. Rules:/n"', r'''
from vt_engine.asr_data import ASRData, ASRDataSeg
from vt_engine.pipeline import _speaker_rule_prompt
d = ASRData([ASRDataSeg(text="[\u8bf4\u8bdd\u4eba1] \u4f60\u597d", start_time=0,
                        end_time=900)])
p = _speaker_rule_prompt(d)
sys.exit(0 if ("/n" not in p and "Rules:\n1)" in p) else 1)
''')

#: D11 —— agent loop 反馈丢原始输入（单通道压扁多轮历史）
_neg7("D11 纠正循环反馈含原始输入", "llm_translator.py",
      '                           "Original input:\\n%s\\n\\nFix the errors above and "\n'
      '                           "output ONLY a valid JSON dictionary with ALL %d "\n'
      '                           "keys" % (error_message, bad,\n'
      '                                     json.dumps(subtitle_dict,\n'
      '                                                ensure_ascii=False),\n'
      '                                     len(subtitle_dict))})',
      '                           "Fix the errors above and output "\n'
      '                           "ONLY a valid JSON dictionary with ALL %d keys"\n'
      '                           % (error_message, len(subtitle_dict))})', r'''
from vt_engine.asr_data import ASRData, ASRDataSeg
from vt_engine.translate_types import TargetLanguage
from vt_engine.llm_translator import LLMTranslator
import vt_engine.llm_translator as LT
calls = []
def fake(user, system="", model="", max_tokens=None, use_cache=True):
    calls.append(user)
    if len(calls) == 1:
        return '{"1": "x"}'
    return '{"1": "\u7532", "2": "\u4e59"}'
LT.chat = fake
LT.ai_enabled = lambda: True
data = ASRData([ASRDataSeg(text="\u539f\u6587%d" % i, start_time=i*1000,
                           end_time=i*1000+900) for i in (1, 2)])
lt = LLMTranslator(thread_num=1, batch_num=2,
                   target_language=TargetLanguage.SIMPLIFIED_CHINESE,
                   model="m")
out = lt.translate_subtitle(data)
lt.stop()
ok = ([s.translated_text for s in out.segments] == ["\u7532", "\u4e59"]
      and len(calls) >= 2 and "\u539f\u65871" in calls[1])
sys.exit(0 if ok else 1)
''')

#: D12 —— 断句失败回落三元组炸TypeError
_neg7("D12 断句单块失败回退", "subtitle_llm.py",
      '        if not isinstance(parts, list):\n'
      '            parts = [text]\n', '', r'''
from vt_engine.asr_data import ASRData, ASRDataSeg
import vt_engine.subtitle_llm as SL
SL.ai_enabled = lambda: True
st = {"n": 0}
def flaky(text, system="", model="", use_cache=True):
    st["n"] += 1
    if st["n"] == 1:
        raise RuntimeError("net down")
    return text.replace("\u3002", "<br>")
SL.chat = flaky
words = ASRData([ASRDataSeg(text=t, start_time=i*400, end_time=i*400+350)
                 for i, t in enumerate(
                     ["\u4f60", "\u597d", "\u4e16", "\u754c", "\u3002",
                      "\u518d", "\u89c1", "\u3002"])])
try:
    sp = SL.split_subtitle(words, thread_num=1)
except TypeError:
    sys.exit(1)
ok = (sp is not None and len(sp.segments) == 2
      and any("\u4f60\u597d\u4e16\u754c" in s.text for s in sp.segments))
sys.exit(0 if ok else 1)
''')

#: D12b —— optimize 的 _fix_up_loop 反馈同样丢上下文
_neg7("D12b fix_up_loop 反馈含原始输入", "subtitle_llm.py",
      '                                    "\\n\\nPrevious (invalid) response:\\n%s"\n'
      '                                    "\\n\\nOriginal input:\\n%s"\n'
      '                                    % (len(subtitle_dict), response,\n'
      '                                       json.dumps(subtitle_dict,\n'
      '                                                  ensure_ascii=False))})',
      '                                    % len(subtitle_dict)})', r'''
from vt_engine.asr_data import ASRData, ASRDataSeg
import vt_engine.subtitle_llm as SL
calls = []
def fake(user, system="", model="", max_tokens=None, use_cache=True):
    calls.append(user)
    if len(calls) == 1:
        return '{"0": "\u7532"}'
    return '{"0": "\u7532", "1": "\u4e59"}'
SL.chat = fake
SL.ai_enabled = lambda: True
data = ASRData([ASRDataSeg(text=t, start_time=i*1000, end_time=i*1000+900)
                for i, t in enumerate(["\u539f\u6587\u4e00", "\u539f\u6587\u4e8c"])])
out = SL.optimize_subtitle(data, thread_num=1)
ok = ([s.text for s in out.segments] == ["\u7532", "\u4e59"]
      and len(calls) >= 2 and "\u539f\u6587\u4e00" in calls[1])
sys.exit(0 if ok else 1)
''')

#: D14 —— run_full_process need_translate 静默忽略
_neg7("D14 run_full_process need_translate", "pipeline.py",
      '    if need_translate is not None and s_task.subtitle_config is not None:\n'
      '        # \u8c03\u7528\u65b9\u663e\u5f0f\u6307\u5b9a\u65f6\u8986\u76d6 cfg \u9ed8\u8ba4\u2014\u2014\u53c2\u6570\u88ab\u63a5\u53d7\u5c31\u5fc5\u987b\u751f\u6548\uff0c\n'
      '        # \u5426\u5219 need_translate=False \u7684\u8c03\u7528\u65b9\u4ecd\u4f1a\u8d70\u7ffb\u8bd1\u94fe\u8def\u3002\n'
      '        s_task.subtitle_config.need_translate = bool(need_translate)\n',
      '', r'''
import vt_engine.pipeline as PL
from vt_engine.tasks import TaskFactory
from vt_engine.config import cfg
seen = []
PL.transcribe_media = lambda t, callback=None: seen.append("t") or ""
PL.process_subtitle = lambda s, callback=None, on_data=None: (
    seen.append(s.subtitle_config.need_translate) or "")
cfg.need_translate.value = True
PL.run_full_process("x.mp4", need_translate=False)
PL.run_full_process("x.mp4", need_translate=True)
sys.exit(0 if seen == ["t", False, "t", True] else 1)
''')

#: D15 —— 组合任务 config 透传
_neg7("D15 组合任务 config 透传", "tasks.py",
      '            transcribe_config=transcribe_config,\n'
      '            subtitle_config=subtitle_config,\n', '', r'''
from vt_engine.tasks import TaskFactory
a, b = object(), object()
tt = TaskFactory.create_transcript_and_subtitle_task(
    "x.mp4", transcribe_config=a, subtitle_config=b)
sys.exit(0 if (tt.transcribe_config is a and tt.subtitle_config is b) else 1)
''')

#: D16 —— stop 反注册 atexit（实例可回收）
_neg7("D16 atexit 实例可回收", "translate_base.py",
      '        try:\n'
      '            atexit.unregister(self.stop)\n'
      '        except Exception:  # noqa: BLE001\n'
      '            pass\n', '', r'''
import gc, weakref
from vt_engine.translate_base import BaseTranslator
from vt_engine.translate_types import TargetLanguage
class T(BaseTranslator):
    def _translate_chunk(self, chunk):
        return chunk
refs = []
for _ in range(5):
    t = T(1, 2, TargetLanguage.SIMPLIFIED_CHINESE, None)
    refs.append(weakref.ref(t))
    t.stop()
del t
gc.collect()
sys.exit(0 if all(r() is None for r in refs) else 1)
''')

#: F2 —— RetranslateThread 键值映射（Signal(dict) 归一化键序，只能查值）
_neg7("F2 RetranslateThread 键值映射", "threads/subtitle_thread.py",
      '            keys = sorted(self.selected_data.keys(), key=int)',
      '            keys = list(self.selected_data.keys())', r'''
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
try:
    import PySide6  # noqa: F401
except Exception:
    sys.exit(77)
import vt_engine.threads.subtitle_thread as ST
ST.translate_with_machine_fallback = (
    lambda config, prompt, cb, asr_data, on_translator=None: asr_data)
from vt_engine.entities import SubtitleConfig
from vt_engine.translate_types import TargetLanguage
sel = {"5": {"start_time": 4000, "end_time": 4900,
             "original_subtitle": "\u4e94", "translated_subtitle": "\u8bd1\u4e94"},
       "2": {"start_time": 1000, "end_time": 1900,
             "original_subtitle": "\u4e8c", "translated_subtitle": "\u8bd1\u4e8c"}}
cap = []
th = ST.RetranslateThread(sel, SubtitleConfig(
    target_language=TargetLanguage.SIMPLIFIED_CHINESE))
th.finished.connect(lambda d: cap.append(d))
th.run()
ok = bool(cap) and cap[0].get("5") == "\u8bd1\u4e94" \
    and cap[0].get("2") == "\u8bd1\u4e8c"
sys.exit(0 if ok else 1)
''')


def test_negative_new():
    """N7：逐点还原 2026-10-19 自查修复，确认新检查抓得到（防恒真绿屏）。"""
    missed = []
    skipped = []
    for name, rel, new, old, check in _NEG7:
        try:
            tmp = _pollute(rel, new, old)
        except AssertionError:
            missed.append(name + "（锚点未命中）")
            continue
        try:
            # 检查代码统一前置 import sys（各片段只用 sys.exit）
            rc, out = _run("import sys\n" + check,
                           {"PYTHONPATH": tmp + os.pathsep + SRC,
                            "VT_DATA_ROOT": tempfile.mkdtemp()})
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)
        if rc == 77:
            skipped.append(name)
        elif rc == 0:
            missed.append(name + "（污染未被抓到）")
    detail = ""
    if missed:
        detail = "漏抓: " + "; ".join(missed)
    elif skipped:
        detail = "跳过: " + "; ".join(skipped)
    else:
        detail = "%d 注入点全部抓到" % len(_NEG7)
    report("N7 新检查负向守护（%d 注入点）" % len(_NEG7),
           not missed, detail)


# ================================================================ main
def main():
    print("=" * 64)
    print("vt_engine 自检（P2 并行引擎线）  python=%s" % PYPARSE)
    print("=" * 64)
    test_redline()
    test_config()
    test_entities()
    test_translate()
    test_pipeline()
    test_threads()
    test_negative()
    test_negative_new()
    print("-" * 64)
    bad = [n for n, ok, _ in _RESULTS if not ok]
    print("合计 %d 项：PASS %d / FAIL %d"
          % (len(_RESULTS), len(_RESULTS) - len(bad), len(bad)))
    if bad:
        print("失败项：")
        for n in bad:
            print("  - " + n)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
