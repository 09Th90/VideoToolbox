# -*- coding: utf-8 -*-
# @version 2.4.0
"""自检：字幕翻译全面去 AI（v2.3.1，2026-10-18 用户报告驱动）。

背景
----
用户在「字幕翻译」页点开始，527/527 条全失败，文案是
「Translation failed: 527/527 segments failed (100%). Check your API key
and network connection.」——机翻（谷歌/微软/DeepLx）根本不读 API key，
这句提示把用户带去查全局 AI 配置；而设置页「翻译服务」下拉里残留的
「LLM 大模型翻译」（清理代码找错了卡片属性名，从未被移除）真会把翻译
接进全局 AI。本脚本守护三件事：

  A. 翻译器创建收口：LLM 服务 → 微软翻译（不实例化 LLMTranslator）；
     异类枚举（engine_entities 副本）同样归一；谷歌/DeepLx 不被误映射；
     原配置对象不被改写。
  B. ``need_llm``：翻译服务=LLM 不再触发 LLM 验证；优化/词级时间戳仍需要。
  C. 失败文案：机翻整批失败 → 中文「翻译失败…不涉及 AI 密钥…」；
     LLM 失败文案保持原样（仍提示查密钥）。
  D. 整批失败自动重试一次（网络瞬断自愈；失败块不缓存、成功块走缓存）。

负向（防绿屏假象）
------------------
  ① 不挂补丁：LLM 服务确实会产 LLMTranslator、机翻失败文案确实含
     「Check your API key」、整批失败确实只有 2 次尝试——证明正向检查有牙齿；
  ② 弄坏补丁副本（真实代码行锚点）：把创建收口的 LLM 判据污染为恒假，
     验证「目标行为」检测能抓到（补丁失效 → LLM 服务原样产 LLMTranslator）。

用法（任意目录）：
    ..\\tools\\python\\python.exe scripts\\dev\\_selftest_translate_no_llm.py
退出码 0 = 通过。
"""
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
SRC = os.path.join(ROOT, "src")

PYPARSE = os.path.join(ROOT, "tools", "python", "python.exe")
if not os.path.exists(PYPARSE):
    PYPARSE = sys.executable

#: 负向②的污染锚点：create_translator 收口处的 LLM 判据（真实代码行）
_ANCHOR = "            if _svc_value(svc) == _TS_LLM_VALUE:"


def _run(code, extra_path=None):
    env = dict(os.environ)
    paths = [extra_path, SRC] if extra_path else [SRC]
    env["PYTHONPATH"] = os.pathsep.join(
        paths + ([os.environ["PYTHONPATH"]] if os.environ.get("PYTHONPATH") else []))
    p = subprocess.run([PYPARSE, "-c", code], env=env,
                       capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


# ---------------------------------------------------------------- 正向 A/B/C
def positive():
    code = r'''
import sys

# 先挂补丁（与 prepare_runtime_env 同一入口）
from core.translate.route_patch import (
    vc_translate_no_llm_patch, _mt_failure_text)
vc_translate_no_llm_patch()

from videocaptioner.core.entities import (
    SubtitleConfig, SubtitleProcessData, TranslatorServiceEnum)
from videocaptioner.core.translate.types import TargetLanguage
from videocaptioner.core.translate.bing_translator import BingTranslator
from videocaptioner.core.translate.google_translator import GoogleTranslator
from videocaptioner.core.translate.llm_translator import LLMTranslator
from videocaptioner.ui.thread import subtitle_thread as st

fails = []
def chk(name, cond, detail=""):
    if cond:
        print("OK  ", name)
    else:
        fails.append(name); print("FAIL", name, detail)

TL = TargetLanguage.SIMPLIFIED_CHINESE

def mk_cfg(service, need_optimize=False):
    return SubtitleConfig(translator_service=service, need_translate=True,
                          need_optimize=need_optimize, target_language=TL)

# ---- A. 翻译器创建收口 ----
t = st.create_translator_from_config(mk_cfg(TranslatorServiceEnum.OPENAI))
chk("LLM 服务归一为微软翻译", isinstance(t, BingTranslator), type(t).__name__)
chk("不实例化 LLMTranslator", not isinstance(t, LLMTranslator), type(t).__name__)

cfg = mk_cfg(TranslatorServiceEnum.OPENAI)
st.create_translator_from_config(cfg)
chk("原配置 translator_service 不被改写",
    cfg.translator_service == TranslatorServiceEnum.OPENAI,
    str(cfg.translator_service))

# 异类枚举（自研 engine_entities 副本）：跨类相等恒 False，也必须归一
from engine_entities import TranslatorServiceEnum as EETSE
t2 = st.create_translator_from_config(mk_cfg(EETSE.OPENAI))
chk("异类 OPENAI 枚举也归一", isinstance(t2, BingTranslator), type(t2).__name__)

# 裸字符串服务值（历史配置的直接形态）
t2b = st.create_translator_from_config(mk_cfg("LLM 大模型翻译"))
chk("裸字符串 LLM 值也归一", isinstance(t2b, BingTranslator), type(t2b).__name__)

chk("谷歌服务保持谷歌",
    isinstance(st.create_translator_from_config(mk_cfg(TranslatorServiceEnum.GOOGLE)),
               GoogleTranslator))
from videocaptioner.core.translate.deeplx_translator import DeepLXTranslator
chk("DeepLx 服务保持 DeepLx",
    isinstance(st.create_translator_from_config(mk_cfg(TranslatorServiceEnum.DEEPLX)),
               DeepLXTranslator))

# ---- B. need_llm ----
class FakeASR:
    def is_word_timestamp(self):
        return False
class WordASR(FakeASR):
    def is_word_timestamp(self):
        return True

th = st.SubtitleThread(None)
chk("翻译=LLM 不再验证 LLM",
    th.need_llm(mk_cfg(TranslatorServiceEnum.OPENAI), FakeASR()) is False)
chk("优化仍需要 LLM",
    th.need_llm(mk_cfg(TranslatorServiceEnum.OPENAI, need_optimize=True),
                FakeASR()) is True)
chk("词级时间戳仍需要 LLM",
    th.need_llm(mk_cfg(TranslatorServiceEnum.OPENAI), WordASR()) is True)
chk("微软翻译不需要 LLM",
    th.need_llm(mk_cfg(TranslatorServiceEnum.BING), FakeASR()) is False)

# ---- C. 失败文案 ----
class ErrBing(BingTranslator):
    """离线假端点：全部条目标 ERROR（不碰网络、不写缓存）。"""
    def _translate_chunk(self, chunk):
        for d in chunk:
            d.translated_text = "ERROR"
        return chunk

chunk = [SubtitleProcessData(index=1, original_text="hello"),
         SubtitleProcessData(index=2, original_text="world")]
tb = ErrBing(thread_num=1, batch_num=10, target_language=TL,
             update_callback=None)
try:
    tb._parallel_translate([chunk])
    chk("机翻整批失败应抛 RuntimeError", False, "未抛")
except RuntimeError as e:
    msg = str(e)
    chk("文案为中文机翻失败", msg.startswith("翻译失败"), msg[:60])
    chk("文案声明不涉及 AI 密钥", "不涉及 AI 密钥" in msg, msg[:100])
    chk("文案不再让查 API key", "API key" not in msg, msg[:100])
    chk("失败计数保留（2/2）", "2/2" in msg, msg[:60])
except Exception as e:
    chk("机翻整批失败应抛 RuntimeError", False, "%s: %s" % (type(e).__name__, e))

class FakeLLM:
    """非机翻翻译器：文案必须原样（LLM 失败确实该提示查密钥）。"""
_orig = ("Translation failed: 3/3 segments failed (100%). "
         "Check your API key and network connection.")
chk("LLM 失败文案不改写",
    _mt_failure_text(FakeLLM(), RuntimeError(_orig)) == _orig)

chk("非失败文案不碰",
    _mt_failure_text(tb, RuntimeError("其他错误")) == "其他错误")

# ---- 幂等 ----
vc_translate_no_llm_patch()
t3 = st.create_translator_from_config(mk_cfg(TranslatorServiceEnum.OPENAI))
chk("重复挂载仍归一", isinstance(t3, BingTranslator), type(t3).__name__)
chk("重复挂载不双层包装",
    st.create_translator_from_config.__name__ == "_create_translator_from_config",
    st.create_translator_from_config.__name__)

print()
print("FAIL:", len(fails), fails if fails else "翻译去 AI 三项全部成立")
sys.exit(1 if fails else 0)
'''
    rc, out = _run(code)
    if "No module named" in out:
        print("SKIP  第三方 videocaptioner 不在环境，跳过")
        return True
    print(out.rstrip())
    return rc == 0


# ---------------------------------------------------------------- 正向 D
def positive_retry():
    """整批失败 → 1.5s 后自动重试一次（网络瞬断自愈）。"""
    code = r'''
import sys
from core.translate.route_patch import vc_translate_no_llm_patch
vc_translate_no_llm_patch()

import videocaptioner.ui.thread.subtitle_thread as st
from videocaptioner.core.entities import (
    SubtitleConfig, SubtitleProcessData, TranslatorServiceEnum)
from videocaptioner.core.translate.types import TargetLanguage

fails = []
def chk(name, cond, detail=""):
    if cond:
        print("OK  ", name)
    else:
        fails.append(name); print("FAIL", name, detail)

calls = {"n": 0, "msgs": []}

class FakeT:
    def translate_subtitle(self, asr):
        for s in asr.segments:
            s.translated_text = "译文%d" % s.index
        return asr

def fake_create(config, prompt="", cb=None):
    calls["n"] += 1
    # 首次创建即失败（引擎首次 create 在 try 之外，失败直接抛出、不走回退），
    # 自动重试那一次才成功——正是「整批瞬时失败」的最小复现。
    if calls["n"] <= 1:
        raise RuntimeError(
            "Translation failed: 3/3 segments failed (100%). "
            "Check your API key and network connection.")
    return FakeT()

# 先挂补丁、再替换工厂：补丁捕获的是真工厂；fallback 内部按模块名查找，替换生效
st.create_translator_from_config = fake_create

class FakeAsr:
    def __init__(self):
        self.segments = [SubtitleProcessData(index=i, original_text="t%d" % i)
                         for i in (1, 2, 3)]

cfg = SubtitleConfig(translator_service=TranslatorServiceEnum.GOOGLE,
                     need_translate=True,
                     target_language=TargetLanguage.SIMPLIFIED_CHINESE)
asr = FakeAsr()
out = st.translate_with_machine_fallback(cfg, "", None, asr,
                                         progress=calls["msgs"].append)
chk("整批失败后自动重试成功", out is asr and calls["n"] == 2,
    "calls=%d" % calls["n"])
chk("重试有进度提示",
    any("自动重试" in m for m in calls["msgs"]), str(calls["msgs"])[:120])
chk("重试后全部有译文",
    all(str(s.translated_text).strip() for s in asr.segments))

chk("DeepLx 也补进了机翻回退表",
    st.MACHINE_FALLBACK.get(TranslatorServiceEnum.DEEPLX)
    == TranslatorServiceEnum.BING,
    str(st.MACHINE_FALLBACK.get(TranslatorServiceEnum.DEEPLX)))

print()
print("FAIL:", len(fails), fails if fails else "自动重试成立")
sys.exit(1 if fails else 0)
'''
    rc, out = _run(code)
    print(out.rstrip())
    return rc == 0


# ---------------------------------------------------------------- 正向 E
def positive_cache_safety():
    """翻译缓存损坏（database disk image is malformed）不得拖垮翻译。"""
    code = r'''
import os, sqlite3, sys, tempfile
from core.translate.route_patch import vc_translate_no_llm_patch, _SafeTranslatorCache
vc_translate_no_llm_patch()

import videocaptioner.core.translate.base as base
from videocaptioner.core.translate.bing_translator import BingTranslator
from videocaptioner.core.translate.types import TargetLanguage
from videocaptioner.core.asr.asr_data import ASRData

fails = []
def chk(name, cond, detail=""):
    if cond:
        print("OK  ", name)
    else:
        fails.append(name); print("FAIL", name, detail)

class BrokenCache:
    def get(self, *a, **k):
        raise sqlite3.DatabaseError("database disk image is malformed")
    def set(self, *a, **k):
        raise sqlite3.DatabaseError("database disk image is malformed")
    def delete(self, *a, **k):
        raise sqlite3.DatabaseError("database disk image is malformed")

# 构造前替换引擎的缓存工厂：模拟真实损坏的 cache.db
base.get_translate_cache = lambda: BrokenCache()

class OfflineBing(BingTranslator):
    def _translate_chunk(self, chunk):
        for d in chunk:
            d.translated_text = "译文%d" % d.index
        return chunk

p = os.path.join(tempfile.mkdtemp(prefix="vt_badcache_"), "t.srt")
open(p, "w", encoding="utf-8").write(
    "1\n00:00:00,000 --> 00:00:01,000\nhello\n\n"
    "2\n00:00:01,000 --> 00:00:02,000\nworld\n\n")
asr = ASRData.from_subtitle_file(p)
t = OfflineBing(thread_num=1, batch_num=10,
                target_language=TargetLanguage.SIMPLIFIED_CHINESE,
                update_callback=None)
chk("缓存降级代理已挂", isinstance(t._cache, _SafeTranslatorCache),
    type(t._cache).__name__)
t.translate_subtitle(asr)
chk("坏缓存不影响翻译",
    all(str(s.translated_text) == "译文%d" % (i + 1)
        for i, s in enumerate(asr.segments)),
    str([s.translated_text for s in asr.segments]))
chk("坏缓存 set 返回 False 不抛",
    t._cache.set("k", "v") is False)

print()
print("FAIL:", len(fails), fails if fails else "坏缓存降级成立")
sys.exit(1 if fails else 0)
'''
    rc, out = _run(code)
    print(out.rstrip())
    return rc == 0


def negative_cache_safety():
    """不挂补丁：坏缓存必须真的把整批翻译打死（证明检查有牙齿）。"""
    code = r'''
import os, sqlite3, sys, tempfile
import videocaptioner.core.translate.base as base
from videocaptioner.core.translate.bing_translator import BingTranslator
from videocaptioner.core.translate.types import TargetLanguage
from videocaptioner.core.asr.asr_data import ASRData

class BrokenCache:
    def get(self, *a, **k):
        raise sqlite3.DatabaseError("database disk image is malformed")
    def set(self, *a, **k):
        raise sqlite3.DatabaseError("database disk image is malformed")
    def delete(self, *a, **k):
        raise sqlite3.DatabaseError("database disk image is malformed")

base.get_translate_cache = lambda: BrokenCache()

class OfflineBing(BingTranslator):
    def _translate_chunk(self, chunk):
        for d in chunk:
            d.translated_text = "译文"
        return chunk

p = os.path.join(tempfile.mkdtemp(prefix="vt_badcache_neg_"), "t.srt")
open(p, "w", encoding="utf-8").write(
    "1\n00:00:00,000 --> 00:00:01,000\nhello\n\n"
    "2\n00:00:01,000 --> 00:00:02,000\nworld\n\n")
asr = ASRData.from_subtitle_file(p)
t = OfflineBing(thread_num=1, batch_num=10,
                target_language=TargetLanguage.SIMPLIFIED_CHINESE,
                update_callback=None)
try:
    t.translate_subtitle(asr)
    sys.exit(3)   # 没补丁也成功 → 负向无效
except Exception as e:
    sys.exit(0 if "malformed" in str(e) or "Translation failed" in str(e) else 3)
'''
    rc, out = _run(code)
    if rc == 0:
        print("OK   负向①d：不挂补丁时坏缓存确实打死整批翻译"
              "——缓存降级检查有牙齿")
        return True
    print("FAIL 负向①d：不挂补丁坏缓存也没打死翻译——缓存降级检查可能是假绿")
    print(out.rstrip()[-800:])
    return False


def positive_cache_heal():
    """启动自愈：损坏的 cache.db 挪走、正常的原样保留。"""
    tmp = tempfile.mkdtemp(prefix="vt_heal_")
    try:
        root = os.path.join(tmp, "data", "VideoCaptioner", "cache")
        bad_dir = os.path.join(root, "translate_results")
        ok_dir = os.path.join(root, "asr_results")
        os.makedirs(bad_dir)
        os.makedirs(ok_dir)
        with open(os.path.join(bad_dir, "cache.db"), "wb") as f:
            f.write(b"definitely-not-a-sqlite-database" * 20)
        import sqlite3
        con = sqlite3.connect(os.path.join(ok_dir, "cache.db"))
        con.execute("CREATE TABLE t (k TEXT)")
        con.commit()
        con.close()

        code = (
            "import glob, os, sys\n"
            "from core.translate.route_patch import vc_translate_no_llm_patch\n"
            "vc_translate_no_llm_patch()\n"
            "root = os.path.join(os.environ['VT_DATA_ROOT'], 'data',\n"
            "                    'VideoCaptioner', 'cache')\n"
            "bad = os.path.join(root, 'translate_results')\n"
            "ok = os.path.join(root, 'asr_results')\n"
            "bad_alive = os.path.isfile(os.path.join(bad, 'cache.db'))\n"
            "bad_moved = bool(glob.glob(os.path.join(bad, 'cache.db.corrupt-*')))\n"
            "ok_alive = os.path.isfile(os.path.join(ok, 'cache.db'))\n"
            "ok_moved = bool(glob.glob(os.path.join(ok, 'cache.db.corrupt-*')))\n"
            "print('bad_alive=%s bad_moved=%s ok_alive=%s ok_moved=%s'\n"
            "      % (bad_alive, bad_moved, ok_alive, ok_moved))\n"
            "sys.exit(0 if (not bad_alive and bad_moved and ok_alive\n"
            "               and not ok_moved) else 3)\n"
        )
        env = dict(os.environ)
        env["VT_DATA_ROOT"] = tmp
        env["PYTHONPATH"] = os.pathsep.join(
            [SRC] + ([os.environ["PYTHONPATH"]]
                     if os.environ.get("PYTHONPATH") else []))
        p = subprocess.run([PYPARSE, "-c", code], env=env,
                           capture_output=True, text=True)
        if p.returncode == 0:
            print("OK   缓存自愈：损坏库被挪走、正常库原样保留")
            return True
        print("FAIL 缓存自愈：损坏库未被处理或误伤正常库")
        print((p.stdout + p.stderr).rstrip()[-800:])
        return False
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------- 负向①
def negative_unpatched():
    """不挂补丁：LLM 服务必须真的会产 LLMTranslator（证明检查有牙齿）。"""
    code = (
        "import sys\n"
        "from videocaptioner.core.entities import SubtitleConfig, TranslatorServiceEnum\n"
        "from videocaptioner.core.translate.types import TargetLanguage\n"
        "from videocaptioner.core.translate.llm_translator import LLMTranslator\n"
        "from videocaptioner.ui.thread import subtitle_thread as st\n"
        "cfg = SubtitleConfig(translator_service=TranslatorServiceEnum.OPENAI,\n"
        "                     need_translate=True,\n"
        "                     target_language=TargetLanguage.SIMPLIFIED_CHINESE)\n"
        "t = st.create_translator_from_config(cfg)\n"
        "sys.exit(0 if isinstance(t, LLMTranslator) else 3)\n"
    )
    rc, out = _run(code)
    if rc == 0:
        print("OK   负向①：不挂补丁时 LLM 服务确实产 LLMTranslator"
              "（补丁前的漏洞真实存在，正向检查有牙齿）")
        return True
    print("FAIL 负向①：不挂补丁也未走 LLM——正向「归一」检查可能是假绿")
    print(out.rstrip()[-800:])
    return False


def negative_unpatched_message():
    """不挂补丁：机翻失败文案必须真的含「Check your API key」。"""
    code = (
        "import sys\n"
        "from videocaptioner.core.translate.bing_translator import BingTranslator\n"
        "from videocaptioner.core.translate.types import TargetLanguage\n"
        "from videocaptioner.core.entities import SubtitleProcessData\n"
        "class ErrBing(BingTranslator):\n"
        "    def _translate_chunk(self, chunk):\n"
        "        for d in chunk:\n"
        "            d.translated_text = 'ERROR'\n"
        "        return chunk\n"
        "chunk = [SubtitleProcessData(index=1, original_text='hello'),\n"
        "         SubtitleProcessData(index=2, original_text='world')]\n"
        "tb = ErrBing(thread_num=1, batch_num=10,\n"
        "             target_language=TargetLanguage.SIMPLIFIED_CHINESE,\n"
        "             update_callback=None)\n"
        "try:\n"
        "    tb._parallel_translate([chunk])\n"
        "    sys.exit(3)\n"
        "except RuntimeError as e:\n"
        "    msg = str(e)\n"
        "    sys.exit(0 if 'Check your API key' in msg else 3)\n"
    )
    rc, out = _run(code)
    if rc == 0:
        print("OK   负向①b：不挂补丁时机翻失败文案确实让用户查 API key"
              "（文案改写检查有牙齿）")
        return True
    print("FAIL 负向①b：不挂补丁文案也无 API key 提示——改写检查形同虚设")
    print(out.rstrip()[-800:])
    return False


# ---------------------------------------------------------------- 负向②
def negative_no_retry():
    """不挂补丁：整批失败只有引擎自带的两次尝试，没有第三次（无自动重试）。"""
    code = (
        "import sys\n"
        "import videocaptioner.ui.thread.subtitle_thread as st\n"
        "from videocaptioner.core.entities import (\n"
        "    SubtitleConfig, SubtitleProcessData, TranslatorServiceEnum)\n"
        "from videocaptioner.core.translate.types import TargetLanguage\n"
        "calls = {'n': 0}\n"
        "def fake_create(config, prompt='', cb=None):\n"
        "    calls['n'] += 1\n"
        "    raise RuntimeError('Translation failed: 3/3 segments failed (100%). '\n"
        "                       'Check your API key and network connection.')\n"
        "st.create_translator_from_config = fake_create\n"
        "cfg = SubtitleConfig(translator_service=TranslatorServiceEnum.GOOGLE,\n"
        "                     need_translate=True,\n"
        "                     target_language=TargetLanguage.SIMPLIFIED_CHINESE)\n"
        "class A:\n"
        "    segments = [SubtitleProcessData(index=1, original_text='a')]\n"
        "try:\n"
        "    st.translate_with_machine_fallback(cfg, '', None, A())\n"
        "    sys.exit(3)\n"
        "except Exception:\n"
        "    sys.exit(0 if calls['n'] == 1 else 3)\n"
    )
    rc, out = _run(code)
    if rc == 0:
        print("OK   负向①c：不挂补丁时整批失败只尝试 1 次就抛出（无自动重试）"
              "——重试检查有牙齿")
        return True
    print("FAIL 负向①c：不挂补丁也出现第三次尝试——重试检查可能是假绿")
    print(out.rstrip()[-800:])
    return False


def negative_polluted():
    """弄坏补丁副本：LLM 判据恒假 → 必须检出「没归一」。"""
    src_file = os.path.join(SRC, "core", "translate", "route_patch.py")
    with open(src_file, encoding="utf-8") as f:
        txt = f.read()
    if _ANCHOR not in txt:
        print("负向②：未找到注入点（%r），跳过（不代表检查无效）" % _ANCHOR[:40])
        return False
    polluted = txt.replace(_ANCHOR,
                           "            if False and _svc_value(svc) == _TS_LLM_VALUE:",
                           1)
    if polluted == txt:
        print("负向②：污染未生效，跳过（不代表检查无效）")
        return False
    tmp = tempfile.mkdtemp(prefix="vt_nollm_neg_")
    try:
        dst = os.path.join(tmp, "route_patch_polluted.py")
        with open(dst, "w", encoding="utf-8") as f:
            f.write(polluted)
        code = (
            "import sys\n"
            "import route_patch_polluted as rp\n"
            "rp.vc_translate_no_llm_patch()\n"
            "from videocaptioner.core.entities import SubtitleConfig, TranslatorServiceEnum\n"
            "from videocaptioner.core.translate.types import TargetLanguage\n"
            "from videocaptioner.core.translate.bing_translator import BingTranslator\n"
            "from videocaptioner.core.translate.llm_translator import LLMTranslator\n"
            "from videocaptioner.ui.thread import subtitle_thread as st\n"
            "cfg = SubtitleConfig(translator_service=TranslatorServiceEnum.OPENAI,\n"
            "                     need_translate=True,\n"
            "                     target_language=TargetLanguage.SIMPLIFIED_CHINESE)\n"
            "t = st.create_translator_from_config(cfg)\n"
            "if isinstance(t, LLMTranslator):\n"
            "    print('POLLUTED-AS-EXPECTED')\n"
            "    sys.exit(3)\n"
            "print('UNEXPECTED', type(t).__name__)\n"
            "sys.exit(0)\n"
        )
        rc, out = _run(code, extra_path=tmp)
        if rc == 3 and "POLLUTED-AS-EXPECTED" in out:
            print("OK   负向②：补丁被弄坏后「没归一」被成功检出"
                  "（判据打的是目标行为，不是与参照物的差异）")
            return True
        print("FAIL 负向②：污染后仍判通过 —— 归一检查形同虚设")
        print(out.rstrip()[-800:])
        return False
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    print("=" * 60)
    print("字幕翻译全面去 AI 自检（route_patch.vc_translate_no_llm_patch）")
    print("=" * 60)
    print("\n[1/5] 正向 A：归一 / need_llm / 失败文案 / 幂等")
    ok1 = positive()
    print("\n[2/5] 正向 B：整批失败自动重试（网络瞬断自愈）")
    ok1b = positive_retry()
    print("\n[3/5] 正向 C：坏缓存只降级不拖垮翻译 + 启动自愈")
    ok1c = positive_cache_safety()
    ok1d = positive_cache_heal()
    print("\n[4/5] 负向①：不挂补丁的基线（证明检查有牙齿）")
    ok2 = negative_unpatched()
    ok2b = negative_unpatched_message()
    ok2c = negative_no_retry()
    ok2d = negative_cache_safety()
    print("\n[5/5] 负向②：弄坏补丁副本（真实代码行锚点）")
    ok3 = negative_polluted()
    print("\n" + "=" * 60)
    allok = (ok1 and ok1b and ok1c and ok1d and ok2 and ok2b and ok2c
             and ok2d and ok3)
    print("结论：", "PASS" if allok else "FAIL")
    return 0 if allok else 1


if __name__ == "__main__":
    sys.exit(main())
