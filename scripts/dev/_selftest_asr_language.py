# -*- coding: utf-8 -*-
# @version 2.0.0
"""ASR 识别语言选择自检（2026-10-12；离线，不联网、不耗额度）。

覆盖：
  1. schema：DEFAULT_CONFIG 含 asr_language（否则保存被静默丢弃）；
  2. asr_config 语言映射：标签 → ISO 码（自动检测/未知 → ""）；
  3. 标签表与契约 LANGUAGES / TranscribeLanguageEnum 对齐（含 QT 下拉 ⊆ 枚举）；
  4. apply_asr_to_engine：显式语言写 settings.json 的 TranscribeLanguage，
     「自动检测」刻意不碰（mock IO，不写真实引擎配置）；
  5. 运行期补丁：任务创建时 TranscribeConfig.transcribe_language 被强制
     （真实引擎 task_factory，改后即还原 settings.json）；
  6. asr_examples：curl / Python 示例反映语言（openai + local 两条路）。

运行：tools\\python\\python.exe scripts\\dev\\_selftest_asr_language.py
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
_VT_ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(_VT_ROOT, "src"))
sys.path.insert(0, os.path.join(_VT_ROOT, "tools", "python", "Lib", "site-packages"))
os.environ.setdefault("VT_NO_PIPELINE", "1")
os.environ.setdefault("VT_NO_SYNC", "1")
os.environ.setdefault("VT_NO_CALIB_SYNC", "1")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import video_toolbox as engine  # noqa: E402

LINES, FAILS = [], []


def check(name, cond, extra=""):
    line = "  [%s] %s%s" % ("PASS" if cond else "FAIL", name,
                            (" -> " + str(extra)) if extra else "")
    print(line)
    LINES.append(line)
    if not cond:
        FAILS.append(name)


# ---------- 1. schema ----------
check("DEFAULT_CONFIG 含 asr_language",
      "asr_language" in engine.ai_mod().DEFAULT_CONFIG)
check("出厂默认为「自动检测」（不强制语言）",
      engine.ai_mod().DEFAULT_CONFIG.get("asr_language") == "自动检测")

# ---------- 2. asr_config 映射 ----------
ac = engine.ai_mod().asr_config({"asr_language": "日本語"})
check("日本語 → label=日本語 / code=ja",
      ac["language_label"] == "日本語" and ac["language"] == "ja",
      (ac["language_label"], ac["language"]))
ac = engine.ai_mod().asr_config({"asr_language": "自动检测"})
check("自动检测 → code=''（不下发 language）",
      ac["language_label"] == "自动检测" and ac["language"] == "")
ac = engine.ai_mod().asr_config({})
check("缺键 → 按自动检测", ac["language"] == "")
ac = engine.ai_mod().asr_config({"asr_language": "克林贡语"})
check("未知标签 → code=''（不猜）", ac["language"] == "")

# ---------- 3. 与契约表对齐 ----------
# 权威表已迁到自研 engine_entities（与引擎的逐值一致性由
# scripts/dev/_selftest_engine_entities.py 保证），此处验我们自己的码表。
try:
    from engine_entities import LANGUAGES, TranscribeLanguageEnum
    _enum = [e.value for e in TranscribeLanguageEnum]
    _codes = engine.ai_mod().ASR_LANGUAGE_CODES
    check("码表键 ⊆ 契约 LANGUAGES", all(k in LANGUAGES for k in _codes),
          str([k for k in _codes if k not in LANGUAGES]))
    check("码表值与 LANGUAGES 一致",
          all(LANGUAGES[k] == v for k, v in _codes.items()),
          str({k: (v, LANGUAGES.get(k)) for k, v in _codes.items()
               if LANGUAGES.get(k) != v}))
    # QT 下拉列表：类属性（SettingsPage），不在引擎导入链上也没关系
    import video_toolbox_qt as _qt
    _labels = list(_qt.SettingsPage.ASR_LANG_LABELS)
    check("QT 下拉 ⊆ 引擎枚举（选错标签引擎解析不了）",
          all(l in _enum for l in _labels),
          str([l for l in _labels if l not in _enum]))
    check("QT 下拉去重", len(_labels) == len(set(_labels)))
    check("QT 下拉首项为自动检测", _labels[0] == "自动检测")
    check("QT 下拉每项都有 ISO 码",
          all(l in _codes for l in _labels),
          str([l for l in _labels if l not in _codes]))
except Exception as e:  # noqa: BLE001
    check("引擎枚举可用（对齐检查）", False, "%s: %s" % (type(e).__name__, e))

# ---------- 4. apply_asr_to_engine（mock IO） ----------
_orig_read, _orig_write = engine._vc_read_settings, engine._vc_write_settings
_sink = {}
try:
    engine._vc_read_settings = lambda: dict(_sink.get("data")
                                            or {"Transcribe": {}})
    engine._vc_write_settings = lambda d: _sink.update(data=d)

    ok, detail = engine.apply_asr_to_engine(
        {"asr_mode": "service", "asr_base_url": "u", "asr_api_key": "k",
         "asr_model": "m", "asr_language": "日本語"})
    check("显式语言 → 写入 TranscribeLanguage",
          ok and _sink["data"]["Transcribe"].get("TranscribeLanguage") == "日本語",
          detail)
    check("detail 带识别语言", "识别语言 → 日本語" in detail, detail)

    _sink.clear()
    ok, _d = engine.apply_asr_to_engine(
        {"asr_mode": "service", "asr_base_url": "u", "asr_api_key": "k",
         "asr_model": "m", "asr_language": "自动检测"})
    check("自动检测 → 不写 TranscribeLanguage（不覆盖引擎取值）",
          "TranscribeLanguage" not in _sink["data"].get("Transcribe", {}),
          _sink["data"].get("Transcribe"))

    _sink.clear()
    ok, _d = engine.apply_asr_to_engine(
        {"asr_mode": "local", "asr_local_model": "large-v3",
         "asr_language": "韩语"})
    check("本地模式同样写语言",
          _sink["data"]["Transcribe"].get("TranscribeLanguage") == "韩语",
          _sink["data"].get("Transcribe"))
finally:
    engine._vc_read_settings, engine._vc_write_settings = _orig_read, _orig_write

# ---------- 5. 运行期补丁：任务创建强制语言 ----------
try:
    _cfg_path = engine.vc_settings_path()
    _raw = engine.read_text_any(_cfg_path)
    _data = json.loads(_raw)
    _old = _data.get("Transcribe", {}).get("TranscribeLanguage", "自动检测")
    # 补丁读的是 ai_load_config()（工具箱 ASR 配置）——mock 它注入「日本語」，
    # 不碰真实 ai_config.json；settings.json 同步写成日语，模拟 apply 已跑过。
    _orig_cfg = engine.ai_load_config
    engine.ai_load_config = lambda: {"asr_language": "日本語"}
    try:
        engine.vc_asr_patch_apply()
        from videocaptioner.ui import task_factory as _tf
        _data.setdefault("Transcribe", {})["TranscribeLanguage"] = "日本語"
        engine._vc_write_settings(_data)
        _task = _tf.TaskFactory.create_transcribe_task(
            os.path.abspath("subtitle_calib_merged.py"))
        check("任务创建时语言被强制（日本語 → ja）",
              _task.transcribe_config.transcribe_language == "ja",
              repr(_task.transcribe_config.transcribe_language))
        # 反向：工具箱配置为自动检测时补丁不强制（任务保持引擎自己的取值）
        engine.ai_load_config = lambda: {"asr_language": "自动检测"}
        _task2 = _tf.TaskFactory.create_transcribe_task(
            os.path.abspath("subtitle_calib_merged.py"))
        from videocaptioner.ui.common.config import cfg as _cfg
        from videocaptioner.core.entities import LANGUAGES as _LG
        _expect = _LG.get(_cfg.transcribe_language.value.value, "")
        check("自动检测时补丁不强制（任务保持引擎取值）",
              _task2.transcribe_config.transcribe_language == _expect,
              "task=%r 引擎=%r" % (_task2.transcribe_config.transcribe_language,
                                   _expect))
    finally:
        engine.ai_load_config = _orig_cfg
        _data["Transcribe"]["TranscribeLanguage"] = _old
        engine._vc_write_settings(_data)
except Exception as e:  # noqa: BLE001
    check("运行期补丁语言强制", False, "%s: %s" % (type(e).__name__, e))

# ---------- 6. asr_examples 反映语言 ----------
ex = engine.asr_examples({"asr_mode": "service", "asr_base_url":
                          "https://api.openai.com/v1", "asr_api_key": "k",
                          "asr_model": "whisper-1", "asr_language": "日本語"})
check("openai curl 带 language=ja", 'language=ja' in ex["curl"], ex["curl"])
check("openai python 带 language", 'language="ja"' in ex["python"]
      or "language='ja'" in ex["python"], ex["python"])
check("示例说明带语言备注", any("识别语言" in n for n in ex["notes"]))

ex2 = engine.asr_examples({"asr_mode": "service", "asr_base_url":
                           "https://api.openai.com/v1", "asr_api_key": "k",
                           "asr_model": "whisper-1", "asr_language": "自动检测"})
check("自动检测时 curl 不带 language", "language" not in ex2["curl"])

ex3 = engine.asr_examples({"asr_mode": "local", "asr_local_model": "large-v3",
                           "asr_language": "中文"})
check("本地 python 示例带 language='zh'",
      "language='zh'" in ex3["python"], ex3["python"])

print()
print("FAILED: %d" % len(FAILS) if FAILS else "ALL PASS")
sys.exit(1 if FAILS else 0)
