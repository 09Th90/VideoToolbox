# @version 2.4.0
"""翻译类型定义（自研，替代 videocaptioner.core.translate.types 的公开面）。

:class:`TargetLanguage` 的成员取值是**持久化契约**——settings.json 的
``Subtitle.TargetLanguage`` 存的就是这里的 ``.value`` 字符串，少任何一项
旧配置反构造时都会 ``ValueError``。取值以「运行期可观察接口 + 既有
settings.json 实存数据」为唯一事实来源。
"""

from __future__ import annotations

from enum import Enum

__all__ = ["TargetLanguage"]


class TargetLanguage(Enum):
    """目标语言枚举（取值与既有持久化契约逐值一致）。"""

    # 中文
    SIMPLIFIED_CHINESE = "简体中文"
    TRADITIONAL_CHINESE = "繁体中文"

    # 英语
    ENGLISH = "英语"
    ENGLISH_US = "英语(美国)"
    ENGLISH_UK = "英语(英国)"

    # 亚洲语言
    JAPANESE = "日本語"
    KOREAN = "韩语"
    CANTONESE = "粤语"
    THAI = "泰语"
    VIETNAMESE = "越南语"
    INDONESIAN = "印尼语"
    MALAY = "马来语"
    TAGALOG = "菲律宾语"

    # 欧洲语言
    FRENCH = "法语"
    GERMAN = "德语"
    SPANISH = "西班牙语"
    SPANISH_LATAM = "西班牙语(拉丁美洲)"
    RUSSIAN = "俄语"
    PORTUGUESE = "葡萄牙语"
    PORTUGUESE_BR = "葡萄牙语(巴西)"
    PORTUGUESE_PT = "葡萄牙语(葡萄牙)"
    ITALIAN = "意大利语"
    DUTCH = "荷兰语"
    POLISH = "波兰语"
    TURKISH = "土耳其语"
    GREEK = "希腊语"
    CZECH = "捷克语"
    SWEDISH = "瑞典语"
    DANISH = "丹麦语"
    FINNISH = "芬兰语"
    NORWEGIAN = "挪威语"
    HUNGARIAN = "匈牙利语"
    ROMANIAN = "罗马尼亚语"
    BULGARIAN = "保加利亚语"
    UKRAINIAN = "乌克兰语"

    # 中东语言
    ARABIC = "阿拉伯语"
    HEBREW = "希伯来语"
    PERSIAN = "波斯语"
