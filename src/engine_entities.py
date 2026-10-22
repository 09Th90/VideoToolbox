# @version 2.5.2
"""引擎实体定义（自研，替代 videocaptioner.core.entities）。

P1 接缝之一：把 `videocaptioner.core.entities` 的公开面迁到本项目自有模块，
使 `src/video_toolbox.py` 等调用方不再需要 import 第三方包。

设计约束
--------
1. **取值与既有持久化契约逐值一致**。P1~P4 期间第三方引擎仍在读写
   `data/videocaptioner/settings.json`，枚举值是该文件里的持久化字段
   （如 ``Transcribe.TranscribeModel``、``Translate.TranslatorServiceEnum``）。
   取值不一致会造成设置错位，因此这里的值以「运行期可观察接口 + 既有
   settings.json 实存数据」为唯一事实来源，不引入新值、不改写旧值。
2. **零第三方依赖**，仅用标准库 ``enum`` / ``typing``。
3. 语言代码采用 ISO 639-1 标准代码（事实数据，非创作性表达）。

演进
----
本模块是渐进式替换的第一块。后续 P2/P3 会把引擎其余职责（ASR 调度、
任务编排、UI 视图）逐步迁出自研实现；届时如无调用方再依赖某些历史取值，
可收紧而不必继续保持完整兼容面。
"""

from enum import Enum

__all__ = [
    "TranscribeModelEnum",
    "TranscribeLanguageEnum",
    "FasterWhisperModelEnum",
    "LLMServiceEnum",
    "TranslatorServiceEnum",
    "SubtitleLayoutEnum",
    "LANGUAGES",
]


class TranscribeModelEnum(Enum):
    """转写模型。

    取值说明：
      · ``BIJIAN`` / ``JIANYING`` / ``WHISPER_CPP`` 为历史取值。当前主程序已把
        转录下拉收敛为「默认 / ASR」两项（见 ``video_toolbox.py`` 的
        ``vc_transcribe_ui_patch``），「默认」落到 ``BIJIAN``；其余历史取值
        仅用于把旧 settings.json 迁回，不新增入口。
      · ``WHISPER_API`` 对应全局 ASR 配置的 service 模式（OpenAI 兼容
        ``/audio/transcriptions``）。
      · ``FASTER_WHISPER`` 对应 local 模式（本地 faster-whisper 模型）。
    """

    BIJIAN = "B 接口"
    JIANYING = "J 接口"
    WHISPER_API = "Whisper [API] ✨"
    FASTER_WHISPER = "FasterWhisper ✨"
    WHISPER_CPP = "WhisperCpp"


class TranscribeLanguageEnum(Enum):
    """识别语言（102 项，取值与既有持久化契约逐值一致）。

    调用方以标签反构造（``TranscribeLanguageEnum(_lang_label)``），标签来自
    ``data/videocaptioner/settings.json`` 的 ``Transcribe.TranscribeLanguage``
    或界面下拉。因此必须收录全部历史取值——少任何一项，旧配置反构造时就会
    ``ValueError``。标签→ISO 639-1 代码映射见 :data:`LANGUAGES`。
    """

    AUTO = '自动检测'
    ENGLISH = '英语'
    CHINESE = '中文'
    JAPANESE = '日本語'
    KOREAN = '韩语'
    YUE = '粤语'
    FRENCH = '法语'
    GERMAN = '德语'
    SPANISH = '西班牙语'
    RUSSIAN = '俄语'
    PORTUGUESE = '葡萄牙语'
    TURKISH = '土耳其语'
    POLISH = 'Polish'
    CATALAN = 'Catalan'
    DUTCH = 'Dutch'
    ARABIC = 'Arabic'
    SWEDISH = 'Swedish'
    ITALIAN = 'Italian'
    INDONESIAN = 'Indonesian'
    HINDI = 'Hindi'
    FINNISH = 'Finnish'
    VIETNAMESE = 'Vietnamese'
    HEBREW = 'Hebrew'
    UKRAINIAN = 'Ukrainian'
    GREEK = 'Greek'
    MALAY = 'Malay'
    CZECH = 'Czech'
    ROMANIAN = 'Romanian'
    DANISH = 'Danish'
    HUNGARIAN = 'Hungarian'
    TAMIL = 'Tamil'
    NORWEGIAN = 'Norwegian'
    THAI = 'Thai'
    URDU = 'Urdu'
    CROATIAN = 'Croatian'
    BULGARIAN = 'Bulgarian'
    LITHUANIAN = 'Lithuanian'
    LATIN = 'Latin'
    MAORI = 'Maori'
    MALAYALAM = 'Malayalam'
    WELSH = 'Welsh'
    SLOVAK = 'Slovak'
    TELUGU = 'Telugu'
    PERSIAN = 'Persian'
    LATVIAN = 'Latvian'
    BENGALI = 'Bengali'
    SERBIAN = 'Serbian'
    AZERBAIJANI = 'Azerbaijani'
    SLOVENIAN = 'Slovenian'
    KANNADA = 'Kannada'
    ESTONIAN = 'Estonian'
    MACEDONIAN = 'Macedonian'
    BRETON = 'Breton'
    BASQUE = 'Basque'
    ICELANDIC = 'Icelandic'
    ARMENIAN = 'Armenian'
    NEPALI = 'Nepali'
    MONGOLIAN = 'Mongolian'
    BOSNIAN = 'Bosnian'
    KAZAKH = 'Kazakh'
    ALBANIAN = 'Albanian'
    SWAHILI = 'Swahili'
    GALICIAN = 'Galician'
    MARATHI = 'Marathi'
    PUNJABI = 'Punjabi'
    SINHALA = 'Sinhala'
    KHMER = 'Khmer'
    SHONA = 'Shona'
    YORUBA = 'Yoruba'
    SOMALI = 'Somali'
    AFRIKAANS = 'Afrikaans'
    OCCITAN = 'Occitan'
    GEORGIAN = 'Georgian'
    BELARUSIAN = 'Belarusian'
    TAJIK = 'Tajik'
    SINDHI = 'Sindhi'
    GUJARATI = 'Gujarati'
    AMHARIC = 'Amharic'
    YIDDISH = 'Yiddish'
    LAO = 'Lao'
    UZBEK = 'Uzbek'
    FAROESE = 'Faroese'
    HAITIAN_CREOLE = 'Haitian Creole'
    PASHTO = 'Pashto'
    TURKMEN = 'Turkmen'
    NYNORSK = 'Nynorsk'
    MALTESE = 'Maltese'
    SANSKRIT = 'Sanskrit'
    LUXEMBOURGISH = 'Luxembourgish'
    MYANMAR = 'Myanmar'
    TIBETAN = 'Tibetan'
    TAGALOG = 'Tagalog'
    MALAGASY = 'Malagasy'
    ASSAMESE = 'Assamese'
    TATAR = 'Tatar'
    HAWAIIAN = 'Hawaiian'
    LINGALA = 'Lingala'
    HAUSA = 'Hausa'
    BASHKIR = 'Bashkir'
    JAVANESE = 'Javanese'
    SUNDANESE = 'Sundanese'
    CANTONESE = 'Cantonese'


class FasterWhisperModelEnum(Enum):
    """本地 faster-whisper 模型名。

    写入 ``FasterWhisper.Model``；枚举外的自定义模型名由运行期补丁生效
    （见 ``video_toolbox.py`` 的 ``vc_asr_patch_apply``）。
    """

    TINY = "tiny"
    BASE = "base"
    SMALL = "small"
    MEDIUM = "medium"
    LARGE_V1 = "large-v1"
    LARGE_V2 = "large-v2"
    LARGE_V3 = "large-v3"
    LARGE_V3_TURBO = "large-v3-turbo"


class LLMServiceEnum(Enum):
    """LLM 服务。

    主程序已把 LLM 入口收敛为 OpenAI 兼容单通道（``tools/ai_client.py``），
    其余取值仅用于兼容既有 settings.json 的 ``LLM.LLMService`` 字段。
    """

    OPENAI = "OpenAI 兼容"
    SILICON_CLOUD = "SiliconCloud"
    DEEPSEEK = "DeepSeek"
    OLLAMA = "Ollama"
    LM_STUDIO = "LM Studio"
    GEMINI = "Gemini"
    CHATGLM = "ChatGLM"


class TranslatorServiceEnum(Enum):
    """翻译服务。

    成员名沿用调用方既有的按名访问（``_TSE.OPENAI`` / ``_TSE.BING``），
    不要改成 ``LLM`` 之类——``video_toolbox_qt.py`` 的设置页收敛逻辑直接
    按名取成员。

    v1.12.0 起字幕翻译板块仅支持机翻（微软 / 谷歌 / DeepLx），LLM 翻译入口
    已移除；``OPENAI``（值「LLM 大模型翻译」）仅用于把历史配置迁回机翻。
    """

    OPENAI = "LLM 大模型翻译"
    DEEPLX = "DeepLx 翻译"
    BING = "微软翻译"
    GOOGLE = "谷歌翻译"


class SubtitleLayoutEnum(Enum):
    """字幕布局（``ASRData.to_srt`` / ``to_ass`` / ``save`` 的 layout 参数类型）。

    取值与运行期接口逐值一致（写入引擎 ``Synthesize.Layout`` 设置字段）；
    成员名是调用方的按名访问形态（``SubtitleLayoutEnum.ORIGINAL_ON_TOP`` 为
    导出方法的默认 layout），两者都不可改名。
    """

    TRANSLATE_ON_TOP = "译文在上"
    ORIGINAL_ON_TOP = "原文在上"
    ONLY_ORIGINAL = "仅原文"
    ONLY_TRANSLATE = "仅译文"


#: 语言标签 → ISO 639-1 代码。键为界面显示标签，空字符串表示自动检测。
#: 同时收录中英双语标签（历史 settings.json 两种写法都出现过）。
LANGUAGES = {
    "自动检测": "",
    "英语": "en", "中文": "zh", "日本語": "ja", "德语": "de", "粤语": "yue",
    "西班牙语": "es", "俄语": "ru", "韩语": "ko", "法语": "fr",
    "葡萄牙语": "pt", "土耳其语": "tr",
    "English": "en", "Chinese": "zh", "German": "de", "Spanish": "es",
    "Russian": "ru", "Korean": "ko", "French": "fr", "Japanese": "ja",
    "Portuguese": "pt", "Turkish": "tr",
    "Polish": "pl", "Catalan": "ca", "Dutch": "nl", "Arabic": "ar",
    "Swedish": "sv", "Italian": "it", "Indonesian": "id", "Hindi": "hi",
    "Finnish": "fi", "Vietnamese": "vi", "Hebrew": "he", "Ukrainian": "uk",
    "Greek": "el", "Malay": "ms", "Czech": "cs", "Romanian": "ro",
    "Danish": "da", "Hungarian": "hu", "Tamil": "ta", "Norwegian": "no",
    "Thai": "th", "Urdu": "ur", "Croatian": "hr", "Bulgarian": "bg",
    "Lithuanian": "lt", "Latin": "la", "Maori": "mi", "Malayalam": "ml",
    "Welsh": "cy", "Slovak": "sk", "Telugu": "te", "Persian": "fa",
    "Latvian": "lv", "Bengali": "bn", "Serbian": "sr", "Azerbaijani": "az",
    "Slovenian": "sl", "Kannada": "kn", "Estonian": "et", "Macedonian": "mk",
    "Breton": "br", "Basque": "eu", "Icelandic": "is", "Armenian": "hy",
    "Nepali": "ne", "Mongolian": "mn", "Bosnian": "bs", "Kazakh": "kk",
    "Albanian": "sq", "Swahili": "sw", "Galician": "gl", "Marathi": "mr",
    "Punjabi": "pa", "Sinhala": "si", "Khmer": "km", "Shona": "sn",
    "Yoruba": "yo", "Somali": "so", "Afrikaans": "af", "Occitan": "oc",
    "Georgian": "ka", "Belarusian": "be", "Tajik": "tg", "Sindhi": "sd",
    "Gujarati": "gu", "Amharic": "am", "Yiddish": "yi", "Lao": "lo",
    "Uzbek": "uz", "Faroese": "fo", "Haitian Creole": "ht", "Pashto": "ps",
    "Turkmen": "tk", "Nynorsk": "nn", "Maltese": "mt", "Sanskrit": "sa",
    "Luxembourgish": "lb", "Myanmar": "my", "Tibetan": "bo", "Tagalog": "tl",
    "Malagasy": "mg", "Assamese": "as", "Tatar": "tt", "Hawaiian": "haw",
    "Lingala": "ln", "Hausa": "ha", "Bashkir": "ba", "Javanese": "jw",
    "Sundanese": "su", "Cantonese": "yue",
}
