# @version 2.5.0
"""引擎实体与任务数据类（自研，替代 videocaptioner.core.entities 的公开面）。

枚举部分复用已接线的自研接缝模块 ``engine_entities``（取值是
settings.json 的持久化契约）；本模块补齐三项**引擎仍持有**的内容：

1. 其余枚举（WhisperModel / VadMethod / 输出格式 / 画质 / 批量任务状态）；
2. 任务数据类（TranscribeConfig / TranscribeTask / SubtitleTask /
   SynthesisTask / 两个组合任务 + SubtitleProcessData / VideoInfo /
   AudioStreamInfo）——引擎 ``ui.task_factory`` 目前仍从
   ``core.entities`` 取这些类，自研 ``vt_engine.tasks`` 改取本模块；
3. ASR 语言能力表与平台探测助手（``get_available_transcribe_models``：
   macOS 不过 FasterWhisper，与引擎 platform_utils 行为一致）。

**字段名与默认值逐一对齐引擎 entities**——任务工厂构造出来的任务对象
要能被同一套线程/核心消费；两套并存期（并行开发）也便于逐字段比对自检。
"""

from __future__ import annotations

import datetime
import sys
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional

from vt_engine._bootstrap import SRC_DIR  # noqa: F401  （确保平铺接缝模块可导入）

from engine_entities import (  # noqa: E402
    TranscribeModelEnum,
    TranscribeLanguageEnum,
    FasterWhisperModelEnum,
    LLMServiceEnum,
    TranslatorServiceEnum,
    SubtitleLayoutEnum,
    LANGUAGES,
)
from vt_engine.llm_context import generate_task_id as _generate_task_id  # noqa: E402

__all__ = [
    # 复用接缝枚举
    "TranscribeModelEnum",
    "TranscribeLanguageEnum",
    "FasterWhisperModelEnum",
    "LLMServiceEnum",
    "TranslatorServiceEnum",
    "SubtitleLayoutEnum",
    "LANGUAGES",
    # 新增枚举
    "WhisperModelEnum",
    "VadMethodEnum",
    "TranscribeOutputFormatEnum",
    "SubtitleRenderModeEnum",
    "VideoQualityEnum",
    "OutputSubtitleFormatEnum",
    "SupportedAudioFormats",
    "SupportedVideoFormats",
    "SupportedSubtitleFormats",
    "BatchTaskType",
    "BatchTaskStatus",
    # 能力表
    "ASRLanguageCapability",
    "ASR_LANGUAGE_CAPABILITIES",
    "get_asr_language_capability",
    "get_available_transcribe_models",
    # 数据类
    "SubtitleProcessData",
    "AudioStreamInfo",
    "VideoInfo",
    "TranscribeConfig",
    "SubtitleConfig",
    "SynthesisConfig",
    "TranscribeTask",
    "SubtitleTask",
    "SynthesisTask",
    "TranscriptAndSubtitleTask",
    "FullProcessTask",
]


class WhisperModelEnum(Enum):
    """WhisperCpp 模型名（写入 Whisper.WhisperModel）。"""

    TINY = "tiny"
    BASE = "base"
    SMALL = "small"
    MEDIUM = "medium"
    LARGE_V1 = "large-v1"
    LARGE_V2 = "large-v2"


class VadMethodEnum(Enum):
    """faster-whisper VAD 方法（写入 FasterWhisper.VadMethod）。"""

    SILERO_V3 = "silero_v3"
    SILERO_V4 = "silero_v4"
    SILERO_V5 = "silero_v5"
    SILERO_V4_FW = "silero_v4_fw"
    PYANNOTE_V3 = "pyannote_v3"
    PYANNOTE_ONNX_V3 = "pyannote_onnx_v3"
    WEBRTC = "webrtc"
    AUDITOK = "auditok"


class TranscribeOutputFormatEnum(Enum):
    """转录输出格式（写入 Transcribe.OutputFormat）。"""

    SRT = "SRT"
    ASS = "ASS"
    VTT = "VTT"
    TXT = "TXT"
    ALL = "All"


class SubtitleRenderModeEnum(Enum):
    """字幕渲染模式（写入 SubtitleStyle.RenderMode）。"""

    ASS_STYLE = "ASS 样式"      # FFmpeg ASS 渲染
    ROUNDED_BG = "圆角背景"     # Pillow 圆角矩形背景


class VideoQualityEnum(Enum):
    """视频合成质量（写入 Video.VideoQuality）。"""

    ULTRA_HIGH = "极高质量"
    HIGH = "高质量"
    MEDIUM = "中等质量"
    LOW = "低质量"

    def get_crf(self) -> int:
        """CRF 值（越小质量越高，文件越大）。"""
        return {
            VideoQualityEnum.ULTRA_HIGH: 18,
            VideoQualityEnum.HIGH: 23,
            VideoQualityEnum.MEDIUM: 28,
            VideoQualityEnum.LOW: 32,
        }[self]

    def get_preset(self) -> str:
        """FFmpeg preset（影响编码速度）。"""
        return {
            VideoQualityEnum.ULTRA_HIGH: "slow",
            VideoQualityEnum.HIGH: "medium",
            VideoQualityEnum.MEDIUM: "medium",
            VideoQualityEnum.LOW: "fast",
        }[self]


class OutputSubtitleFormatEnum(Enum):
    """字幕输出格式。"""

    SRT = "srt"
    ASS = "ass"
    VTT = "vtt"
    JSON = "json"
    TXT = "txt"


class SupportedAudioFormats(Enum):
    """支持的音频格式。"""

    AAC = "aac"
    AC3 = "ac3"
    AIFF = "aiff"
    AMR = "amr"
    APE = "ape"
    AU = "au"
    FLAC = "flac"
    M4A = "m4a"
    MP2 = "mp2"
    MP3 = "mp3"
    MKA = "mka"
    OGA = "oga"
    OGG = "ogg"
    OPUS = "opus"
    RA = "ra"
    WAV = "wav"
    WMA = "wma"


class SupportedVideoFormats(Enum):
    """支持的视频格式。"""

    MP4 = "mp4"
    WEBM = "webm"
    OGM = "ogm"
    MOV = "mov"
    MKV = "mkv"
    AVI = "avi"
    WMV = "wmv"
    FLV = "flv"
    M4V = "m4v"
    TS = "ts"
    MPG = "mpg"
    MPEG = "mpeg"
    VOB = "vob"
    ASF = "asf"
    RM = "rm"
    RMVB = "rmvb"
    M2TS = "m2ts"
    MTS = "mts"
    DV = "dv"
    GXF = "gxf"
    TOD = "tod"
    MXF = "mxf"
    F4V = "f4v"


class SupportedSubtitleFormats(Enum):
    """支持的字幕格式。"""

    SRT = "srt"
    ASS = "ass"
    VTT = "vtt"


class BatchTaskType(Enum):
    """批量处理任务类型。"""

    TRANSCRIBE = "批量转录"
    SUBTITLE = "批量字幕"
    TRANS_SUB = "转录+字幕"
    FULL_PROCESS = "全流程处理"

    def __str__(self):
        return self.value


class BatchTaskStatus(Enum):
    """批量处理任务状态。"""

    WAITING = "等待中"
    RUNNING = "处理中"
    COMPLETED = "已完成"
    FAILED = "失败"

    def __str__(self):
        return self.value


# ============ ASR 语言能力表 ============

@dataclass
class ASRLanguageCapability:
    """ASR 语言支持能力。"""

    supported_languages: List[TranscribeLanguageEnum]
    supports_auto: bool


def _all_langs_except_auto() -> List[TranscribeLanguageEnum]:
    return [lang for lang in TranscribeLanguageEnum
            if lang != TranscribeLanguageEnum.AUTO]


ASR_LANGUAGE_CAPABILITIES = {
    TranscribeModelEnum.BIJIAN: ASRLanguageCapability(
        supported_languages=[TranscribeLanguageEnum.CHINESE,
                             TranscribeLanguageEnum.ENGLISH],
        supports_auto=True),
    TranscribeModelEnum.JIANYING: ASRLanguageCapability(
        supported_languages=[TranscribeLanguageEnum.CHINESE,
                             TranscribeLanguageEnum.ENGLISH],
        supports_auto=True),
    TranscribeModelEnum.FASTER_WHISPER: ASRLanguageCapability(
        supported_languages=_all_langs_except_auto(), supports_auto=False),
    TranscribeModelEnum.WHISPER_CPP: ASRLanguageCapability(
        supported_languages=_all_langs_except_auto(), supports_auto=True),
    TranscribeModelEnum.WHISPER_API: ASRLanguageCapability(
        supported_languages=_all_langs_except_auto(), supports_auto=True),
}


def get_asr_language_capability(model: TranscribeModelEnum) -> ASRLanguageCapability:
    """获取指定模型的语言能力（未知模型按最宽能力返回）。"""
    return ASR_LANGUAGE_CAPABILITIES.get(
        model,
        ASRLanguageCapability(supported_languages=_all_langs_except_auto(),
                              supports_auto=True))


def get_available_transcribe_models() -> List[TranscribeModelEnum]:
    """当前平台可用的转录模型列表。

    macOS 不支持 FasterWhisper（依赖 CUDA/CuDNN），与引擎
    ``platform_utils.get_available_transcribe_models`` 行为一致。
    """
    all_models = list(TranscribeModelEnum)
    if sys.platform == "darwin":
        return [m for m in all_models if m != TranscribeModelEnum.FASTER_WHISPER]
    return all_models


# ============ 任务数据类（字段与引擎 entities 逐一对应） ============

@dataclass
class SubtitleProcessData:
    """翻译处理数据（一条字幕的原文/译文/优化文）。"""

    index: int
    original_text: str
    translated_text: str = ""
    optimized_text: str = ""


@dataclass
class AudioStreamInfo:
    """音频流信息。"""

    index: int        # 音轨在视频中的实际索引（如 0, 1, 2 或 2, 3, 4）
    codec: str        # 音频编解码器（如 aac, mp3, opus）
    language: str = ""  # 语言标签（如 eng, chi, deu）
    title: str = ""     # 音轨标题（可选）


@dataclass
class VideoInfo:
    """视频信息（ffprobe 探测结果）。"""

    file_name: str
    file_path: str
    width: int
    height: int
    fps: float
    duration_seconds: float
    bitrate_kbps: int
    video_codec: str
    audio_codec: str
    audio_sampling_rate: int
    thumbnail_path: str
    audio_streams: List[AudioStreamInfo] = field(default_factory=list)


@dataclass
class TranscribeConfig:
    """转录配置（字段与引擎 entities.TranscribeConfig 一致）。"""

    transcribe_model: Optional[TranscribeModelEnum] = None
    transcribe_language: str = ""
    need_word_time_stamp: bool = True
    output_format: Optional[TranscribeOutputFormatEnum] = None
    whisper_model: Optional[WhisperModelEnum] = None
    whisper_api_key: Optional[str] = None
    whisper_api_base: Optional[str] = None
    whisper_api_model: Optional[str] = None
    whisper_api_prompt: Optional[str] = None
    faster_whisper_program: Optional[str] = None
    faster_whisper_model: Optional[FasterWhisperModelEnum] = None
    faster_whisper_model_dir: Optional[str] = None
    faster_whisper_device: str = "cuda"
    faster_whisper_vad_filter: bool = True
    faster_whisper_vad_threshold: float = 0.5
    faster_whisper_vad_method: Optional[VadMethodEnum] = VadMethodEnum.SILERO_V3
    faster_whisper_ff_mdx_kim2: bool = False
    faster_whisper_one_word: bool = True
    faster_whisper_prompt: Optional[str] = None

    def print_config(self) -> str:
        """人类可读的配置摘要（线程日志用）。"""
        return "\n".join("%s: %s" % (k, v) for k, v in self.__dict__.items())


@dataclass
class SubtitleConfig:
    """字幕配置（字段与引擎 entities.SubtitleConfig 一致）。"""

    base_url: Optional[str] = None
    api_key: Optional[str] = None
    llm_model: Optional[str] = None
    deeplx_endpoint: Optional[str] = None
    translator_service: Optional[TranslatorServiceEnum] = None
    need_translate: bool = False
    need_optimize: bool = False
    need_reflect: bool = False
    thread_num: int = 10
    batch_size: int = 10
    subtitle_layout: SubtitleLayoutEnum = SubtitleLayoutEnum.ORIGINAL_ON_TOP
    max_word_count_cjk: int = 12
    max_word_count_english: int = 18
    need_split: bool = True
    target_language: Optional[object] = None
    subtitle_style: Optional[str] = None
    custom_prompt_text: Optional[str] = None

    def print_config(self) -> str:
        """人类可读的配置摘要（密钥打码）。"""
        lines = []
        for k, v in self.__dict__.items():
            if "key" in k.lower() and v:
                v = "***"
            lines.append("%s: %s" % (k, v))
        return "\n".join(lines)


@dataclass
class SynthesisConfig:
    """合成配置（字段与引擎 entities.SynthesisConfig 一致）。"""

    need_video: bool = True
    soft_subtitle: bool = True
    render_mode: SubtitleRenderModeEnum = SubtitleRenderModeEnum.ASS_STYLE
    video_quality: VideoQualityEnum = VideoQualityEnum.MEDIUM
    subtitle_layout: SubtitleLayoutEnum = SubtitleLayoutEnum.ORIGINAL_ON_TOP
    ass_style: str = ""
    rounded_style: Optional[dict] = None


@dataclass
class TranscribeTask:
    """转录任务。"""

    task_id: str = field(default_factory=_generate_task_id)
    queued_at: Optional[datetime.datetime] = None
    started_at: Optional[datetime.datetime] = None
    completed_at: Optional[datetime.datetime] = None
    file_path: Optional[str] = None
    output_path: Optional[str] = None
    need_next_task: bool = False
    selected_audio_track_index: int = 0
    transcribe_config: Optional[TranscribeConfig] = None


@dataclass
class SubtitleTask:
    """字幕任务。"""

    task_id: str = field(default_factory=_generate_task_id)
    queued_at: Optional[datetime.datetime] = None
    started_at: Optional[datetime.datetime] = None
    completed_at: Optional[datetime.datetime] = None
    subtitle_path: str = ""
    video_path: Optional[str] = None
    output_path: Optional[str] = None
    need_next_task: bool = True
    subtitle_config: Optional[SubtitleConfig] = None


@dataclass
class SynthesisTask:
    """合成任务。"""

    task_id: str = field(default_factory=_generate_task_id)
    queued_at: Optional[datetime.datetime] = None
    started_at: Optional[datetime.datetime] = None
    completed_at: Optional[datetime.datetime] = None
    video_path: Optional[str] = None
    subtitle_path: Optional[str] = None
    output_path: Optional[str] = None
    need_next_task: bool = False
    synthesis_config: Optional[SynthesisConfig] = None


@dataclass
class TranscriptAndSubtitleTask:
    """转录和字幕任务类。"""

    task_id: str = field(default_factory=_generate_task_id)
    queued_at: Optional[datetime.datetime] = None
    started_at: Optional[datetime.datetime] = None
    completed_at: Optional[datetime.datetime] = None
    file_path: Optional[str] = None
    output_path: Optional[str] = None
    transcribe_config: Optional[TranscribeConfig] = None
    subtitle_config: Optional[SubtitleConfig] = None


@dataclass
class FullProcessTask:
    """完整处理任务类（转录+字幕+合成）。"""

    task_id: str = field(default_factory=_generate_task_id)
    queued_at: Optional[datetime.datetime] = None
    started_at: Optional[datetime.datetime] = None
    completed_at: Optional[datetime.datetime] = None
    file_path: Optional[str] = None
    output_path: Optional[str] = None
    transcribe_config: Optional[TranscribeConfig] = None
    subtitle_config: Optional[SubtitleConfig] = None
    synthesis_config: Optional[SynthesisConfig] = None
