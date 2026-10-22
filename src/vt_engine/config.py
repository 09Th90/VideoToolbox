# @version 2.5.3
"""设置层（自研，替代 videocaptioner.ui.common.config 的 qconfig 单例）。

P2 最后阻塞项：引擎的 ``ui.common.config`` 是**载荷性单例**——模块级
``cfg = Config()`` + ``qconfig.load(SETTINGS_PATH, cfg)``，引擎线程与
核心直接 import 它读写同一份 settings.json。单独替换会造成「两个 cfg
单例」的内存/磁盘 desync，必须连线程一起切换；本模块即该重建，配套
``vt_engine.threads`` / ``vt_engine.tasks`` / ``vt_engine.pipeline``
构成不依赖引擎的完整运行链。

兼容面（调用方按名访问，一个都不能少）
--------------------------------------
* ``cfg.<item>.value`` —— 读（反序列化后的 Python 值）/ 写（校验+纠正+落盘）；
* ``cfg.get(item)`` / ``cfg.set(item, value)`` —— 主程序 vcsettings
  的「内存态同步（免重启生效）」在用；
* ``cfg.appRestartSig`` —— 设置页重启提示（纯 Python 信号垫片，无 Qt 依赖）；
* 全部配置项的 (group, key, default) 与引擎 ``Config`` 逐项一致——
  settings.json 是**持久化契约**：组名/键名/默认值任一处不一致都会造成
  设置错位或历史配置反构造失败。

文件格式与引擎一致：JSON ``{group: {key: serialized_value}}``，
``indent=4`` / ``ensure_ascii=False``，枚举按 ``.value`` 存取，
**未知组/键原样保留**（qfluentwidgets 自己的 QFluentWidgets 组也得
round-trip），写盘原子化（临时文件 + os.replace）。
"""

from __future__ import annotations

import copy
import json
import os
import threading
from enum import Enum

from vt_engine.config_items import (
    BoolValidator,
    ConfigItem,
    EnumSerializer,
    FolderValidator,
    OptionsConfigItem,
    OptionsValidator,
    RangeConfigItem,
    RangeValidator,
)
from vt_engine.entities import (
    FasterWhisperModelEnum,
    LLMServiceEnum,
    SubtitleLayoutEnum,
    SubtitleRenderModeEnum,
    TranscribeLanguageEnum,
    TranscribeModelEnum,
    TranscribeOutputFormatEnum,
    TranslatorServiceEnum,
    VadMethodEnum,
    VideoQualityEnum,
    WhisperModelEnum,
    get_available_transcribe_models,
)
from vt_engine.paths import default_engine_paths
from vt_engine.translate_types import TargetLanguage

__all__ = [
    "Language",
    "Config",
    "cfg",
    "settings_path",
    "load_config",
    "save_config",
]


class Language(Enum):
    """软件语言（序列化为 QLocale 名字符串，与引擎 LanguageSerializer 一致）。"""

    CHINESE_SIMPLIFIED = "zh_CN"
    CHINESE_TRADITIONAL = "zh_HK"
    ENGLISH = "en_US"
    AUTO = "Auto"


class _SignalShim:
    """纯 Python 信号垫片（对齐 Qt Signal 的 connect/disconnect/emit 面）。

    设置层必须无 Qt 可用；真实 Qt 环境下接入方若需要与 Qt 信号互通，
    在外层包一层转发即可（本引擎未接入主程序前不需要）。
    """

    def __init__(self):
        self._slots = []

    def connect(self, slot):
        if slot not in self._slots:
            self._slots.append(slot)

    def disconnect(self, slot=None):
        if slot is None:
            self._slots.clear()
        elif slot in self._slots:
            self._slots.remove(slot)

    def emit(self, *args):
        for slot in list(self._slots):
            try:
                slot(*args)
            except Exception:  # noqa: BLE001  信号槽异常不得拖垮设置写入
                pass


def settings_path() -> str:
    """settings.json 路径（与引擎/主程序 ``vc_settings_path()`` 同址）。"""
    return str(default_engine_paths().settings_path)


class Config:
    """应用配置（group/key/default 与引擎 Config 逐项一致）。

    声明期（类属性）创建配置项；实例化时收集全部条目、绑定 owner 并
    从 settings.json 载入。读不到文件时全部落默认值（不抛异常——
    首次运行的软件本来就没有设置文件）。
    """

    # ------------------- LLM 配置 -------------------
    llm_service = OptionsConfigItem(
        "LLM", "LLMService", LLMServiceEnum.OPENAI)
    openai_model = ConfigItem("LLM", "OpenAI_Model", "gpt-4o-mini")
    openai_api_key = ConfigItem("LLM", "OpenAI_API_Key", "")
    openai_api_base = ConfigItem("LLM", "OpenAI_API_Base",
                                 "https://api.openai.com/v1")
    silicon_cloud_model = ConfigItem("LLM", "SiliconCloud_Model", "gpt-4o-mini")
    silicon_cloud_api_key = ConfigItem("LLM", "SiliconCloud_API_Key", "")
    silicon_cloud_api_base = ConfigItem(
        "LLM", "SiliconCloud_API_Base", "https://api.siliconflow.cn/v1")
    deepseek_model = ConfigItem("LLM", "DeepSeek_Model", "deepseek-chat")
    deepseek_api_key = ConfigItem("LLM", "DeepSeek_API_Key", "")
    deepseek_api_base = ConfigItem("LLM", "DeepSeek_API_Base",
                                   "https://api.deepseek.com/v1")
    ollama_model = ConfigItem("LLM", "Ollama_Model", "llama2")
    ollama_api_key = ConfigItem("LLM", "Ollama_API_Key", "ollama")
    ollama_api_base = ConfigItem("LLM", "Ollama_API_Base",
                                 "http://localhost:11434/v1")
    lm_studio_model = ConfigItem("LLM", "LmStudio_Model", "qwen2.5:7b")
    lm_studio_api_key = ConfigItem("LLM", "LmStudio_API_Key", "lmstudio")
    lm_studio_api_base = ConfigItem("LLM", "LmStudio_API_Base",
                                    "http://localhost:1234/v1")
    gemini_model = ConfigItem("LLM", "Gemini_Model", "gemini-pro")
    gemini_api_key = ConfigItem("LLM", "Gemini_API_Key", "")
    gemini_api_base = ConfigItem("LLM", "Gemini_API_Base",
                                 "https://generativelanguage.googleapis.com/v1beta/openai/")
    chatglm_model = ConfigItem("LLM", "ChatGLM_Model", "glm-4")
    chatglm_api_key = ConfigItem("LLM", "ChatGLM_API_Key", "")
    chatglm_api_base = ConfigItem("LLM", "ChatGLM_API_Base",
                                  "https://open.bigmodel.cn/api/paas/v4")

    # ------------------- 翻译配置 -------------------
    translator_service = OptionsConfigItem(
        "Translate", "TranslatorServiceEnum", TranslatorServiceEnum.BING)
    need_reflect_translate = ConfigItem(
        "Translate", "NeedReflectTranslate", False, BoolValidator())
    deeplx_endpoint = ConfigItem("Translate", "DeeplxEndpoint", "")
    batch_size = RangeConfigItem("Translate", "BatchSize", 10, (5, 50))
    thread_num = RangeConfigItem("Translate", "ThreadNum", 10, (1, 50))

    # ------------------- 转录配置 -------------------
    transcribe_model = OptionsConfigItem(
        "Transcribe", "TranscribeModel", TranscribeModelEnum.BIJIAN,
        OptionsValidator(get_available_transcribe_models()))
    transcribe_output_format = OptionsConfigItem(
        "Transcribe", "OutputFormat", TranscribeOutputFormatEnum.SRT)
    transcribe_language = OptionsConfigItem(
        "Transcribe", "TranscribeLanguage", TranscribeLanguageEnum.AUTO)

    # ------------------- WhisperCpp 配置 -------------------
    whisper_model = OptionsConfigItem(
        "Whisper", "WhisperModel", WhisperModelEnum.TINY)

    # ------------------- FasterWhisper 配置 -------------------
    faster_whisper_program = ConfigItem(
        "FasterWhisper", "Program", "faster-whisper-xxl.exe")
    faster_whisper_model = OptionsConfigItem(
        "FasterWhisper", "Model", FasterWhisperModelEnum.TINY)
    faster_whisper_model_dir = ConfigItem("FasterWhisper", "ModelDir", "")
    faster_whisper_device = OptionsConfigItem(
        "FasterWhisper", "Device", "cuda",
        OptionsValidator(["cuda", "cpu"]))
    faster_whisper_vad_filter = ConfigItem(
        "FasterWhisper", "VadFilter", True, BoolValidator())
    faster_whisper_vad_threshold = RangeConfigItem(
        "FasterWhisper", "VadThreshold", 0.4, (0, 1))
    faster_whisper_vad_method = OptionsConfigItem(
        "FasterWhisper", "VadMethod", VadMethodEnum.SILERO_V4)
    faster_whisper_ff_mdx_kim2 = ConfigItem(
        "FasterWhisper", "FfMdxKim2", False, BoolValidator())
    faster_whisper_one_word = ConfigItem(
        "FasterWhisper", "OneWord", True, BoolValidator())
    faster_whisper_prompt = ConfigItem("FasterWhisper", "Prompt", "")

    # ------------------- Whisper API 配置 -------------------
    whisper_api_base = ConfigItem("WhisperAPI", "WhisperApiBase", "")
    whisper_api_key = ConfigItem("WhisperAPI", "WhisperApiKey", "")
    whisper_api_model = OptionsConfigItem("WhisperAPI", "WhisperApiModel", "")
    whisper_api_prompt = ConfigItem("WhisperAPI", "WhisperApiPrompt", "")

    # ------------------- 字幕配置 -------------------
    need_optimize = ConfigItem("Subtitle", "NeedOptimize", False, BoolValidator())
    need_translate = ConfigItem("Subtitle", "NeedTranslate", False, BoolValidator())
    need_split = ConfigItem("Subtitle", "NeedSplit", False, BoolValidator())
    target_language = OptionsConfigItem(
        "Subtitle", "TargetLanguage", TargetLanguage.SIMPLIFIED_CHINESE)
    max_word_count_cjk = RangeConfigItem(
        "Subtitle", "MaxWordCountCJK", 28, (8, 100))
    max_word_count_english = RangeConfigItem(
        "Subtitle", "MaxWordCountEnglish", 20, (8, 100))
    custom_prompt_text = ConfigItem("Subtitle", "CustomPromptText", "")

    # ------------------- 字幕合成配置 -------------------
    soft_subtitle = ConfigItem("Video", "SoftSubtitle", False, BoolValidator())
    need_video = ConfigItem("Video", "NeedVideo", True, BoolValidator())
    video_quality = OptionsConfigItem(
        "Video", "VideoQuality", VideoQualityEnum.MEDIUM)
    use_subtitle_style = ConfigItem("Video", "UseSubtitleStyle", False, BoolValidator())

    # ------------------- 字幕样式配置 -------------------
    subtitle_style_name = ConfigItem("SubtitleStyle", "StyleName", "default")
    subtitle_layout = OptionsConfigItem(
        "SubtitleStyle", "Layout", SubtitleLayoutEnum.TRANSLATE_ON_TOP)
    subtitle_preview_image = ConfigItem("SubtitleStyle", "PreviewImage", "")
    subtitle_render_mode = OptionsConfigItem(
        "SubtitleStyle", "RenderMode", SubtitleRenderModeEnum.ROUNDED_BG)

    # 圆角背景模式配置
    rounded_bg_font_name = ConfigItem("RoundedBgStyle", "FontName", "Noto Sans SC")
    rounded_bg_font_size = RangeConfigItem(
        "RoundedBgStyle", "FontSize", 52, (16, 120))
    rounded_bg_color = ConfigItem("RoundedBgStyle", "BgColor", "#191919C8")
    rounded_bg_text_color = ConfigItem("RoundedBgStyle", "TextColor", "#FFFFFF")
    rounded_bg_corner_radius = RangeConfigItem(
        "RoundedBgStyle", "CornerRadius", 12, (0, 50))
    rounded_bg_padding_h = RangeConfigItem(
        "RoundedBgStyle", "PaddingH", 28, (4, 100))
    rounded_bg_padding_v = RangeConfigItem(
        "RoundedBgStyle", "PaddingV", 14, (4, 50))
    rounded_bg_margin_bottom = RangeConfigItem(
        "RoundedBgStyle", "MarginBottom", 60, (20, 300))
    rounded_bg_line_spacing = RangeConfigItem(
        "RoundedBgStyle", "LineSpacing", 10, (0, 50))
    rounded_bg_letter_spacing = RangeConfigItem(
        "RoundedBgStyle", "LetterSpacing", 0, (0, 20))

    # ------------------- 保存配置 -------------------
    work_dir = ConfigItem("Save", "Work_Dir",
                          str(default_engine_paths().work_path),
                          FolderValidator())

    # ------------------- 软件页面配置 -------------------
    mica_enabled = ConfigItem("MainWindow", "MicaEnabled", False, BoolValidator())
    dpi_scale = OptionsConfigItem(
        "MainWindow", "DpiScale", "Auto",
        OptionsValidator([1, 1.25, 1.5, 1.75, 2, "Auto"]), restart=True)
    language = OptionsConfigItem(
        "MainWindow", "Language", Language.AUTO, restart=True)

    # ------------------- 更新配置 -------------------
    check_update_at_start_up = ConfigItem(
        "Update", "CheckUpdateAtStartUp", True, BoolValidator())

    # ------------------- 缓存配置 -------------------
    cache_enabled = ConfigItem("Cache", "CacheEnabled", True, BoolValidator())

    # ------------------- 主题配置（qfluentwidgets 组，原样 round-trip）------
    theme_mode = ConfigItem("QFluentWidgets", "ThemeMode", "Dark")
    theme_color = ConfigItem("QFluentWidgets", "ThemeColor", "#ff28f08b")
    font_families = ConfigItem("QFluentWidgets", "FontFamilies", "")

    def __init__(self, path: str = ""):
        self.appRestartSig = _SignalShim()
        self._lock = threading.RLock()
        self._path = path or settings_path()
        self._data = {}       # {group: {key: serialized}}（含未知组）
        self._items = []      # [(attr_name, item)]
        # 配置项是**类属性**——若不拷贝，多个 Config 实例（单例 cfg +
        # 自检/临时路径实例）会共享同一批 item 对象：一个实例 set 过的值
        # 会漏进另一个实例，owner 也被最后创建的实例抢走。每个实例持
        # 有一份独立拷贝（校验器/序列化器无状态，浅拷贝共享即可）。
        for attr in dir(type(self)):
            item = getattr(type(self), attr, None)
            if isinstance(item, ConfigItem):
                own = copy.copy(item)
                own._owner = self
                setattr(self, attr, own)
                self._items.append((attr, own))
        self.load()

    # ---------- 文件读写 ----------
    def load(self, path: str = "") -> bool:
        """从 settings.json 载入（缺失/损坏全部落默认值，绝不抛）。"""
        self._path = path or self._path
        data = {}
        try:
            with open(self._path, encoding="utf-8") as f:
                raw = json.load(f)
            if isinstance(raw, dict):
                data = raw
        except (OSError, ValueError):
            data = {}
        self._data = data
        with self._lock:
            # 先整体复位默认值——load 是幂等的：文件里被删掉的键要回落到
            # 默认，而不是保留上一次 load/set 的残留。
            for _attr, item in self._items:
                item._value = item.default
            for _attr, item in self._items:
                group = data.get(item.group)
                if not isinstance(group, dict):
                    continue
                if item.name not in group:
                    continue
                raw_v = group[item.name]
                v = item.serializer.deserialize(raw_v)
                if v is None:
                    continue  # 反构造失败 → 保留默认
                if not item.validator.validate(v):
                    v = item.validator.correct(v)
                item._value = v
        return True

    def save(self) -> bool:
        """原子写回（缩进与上游 qconfig 落盘风格一致）。"""
        with self._lock:
            payload = dict(self._data)
            path = self._path
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            tmp = path + ".vt_tmp"
            with open(tmp, "w", encoding="utf-8", newline="") as f:
                json.dump(payload, f, ensure_ascii=False, indent=4)
            os.replace(tmp, path)
            return True
        except OSError:
            return False

    # ---------- 条目读写 ----------
    def get(self, item: ConfigItem):
        """读（qconfig 兼容面）。"""
        return item.value

    def set(self, item: ConfigItem, value) -> object:
        """写：校验 → 纠正 → 内存 → 序列化落盘。返回生效值。"""
        if not item.validator.validate(value):
            value = item.validator.correct(value)
        with self._lock:
            changed = item._value != value
            item._value = value
            self._data.setdefault(item.group, {})[item.name] = \
                item.serializer.serialize(value)
            ok = self.save()
        if changed and item.restart:
            self.appRestartSig.emit()
        if not ok:
            # 落盘失败不阻塞内存态（主程序「免重启生效」语义优先）
            pass
        return value

    def items(self):
        """全部配置项（自检/诊断用）。"""
        return list(self._items)

    def dump(self) -> dict:
        """当前全部序列化值（自检用）。"""
        with self._lock:
            return json.loads(json.dumps(self._data, ensure_ascii=False))


#: 进程内唯一设置单例（引擎 cfg 的同位替代）。
cfg = Config()


def load_config(path: str = "") -> Config:
    """重新载入单例（便捷函数）。"""
    cfg.load(path)
    return cfg


def save_config() -> bool:
    """保存单例（便捷函数）。"""
    return cfg.save()
