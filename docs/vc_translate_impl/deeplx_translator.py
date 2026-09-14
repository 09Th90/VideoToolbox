"""DeepLX 翻译器"""

import os
from typing import Callable, List, Optional

import requests

from videocaptioner.core.translate.base import BaseTranslator, SubtitleProcessData, logger
from videocaptioner.core.translate.types import TargetLanguage, get_language_code
from videocaptioner.core.utils.cache import generate_cache_key


class DeepLXTranslator(BaseTranslator):
    """DeepLX翻译器"""

    def __init__(
        self,
        thread_num: int,
        batch_num: int,
        target_language: TargetLanguage,
        timeout: int,
        update_callback: Optional[Callable],
    ):
        super().__init__(
            thread_num=thread_num,
            batch_num=batch_num,
            target_language=target_language,
            update_callback=update_callback,
        )
        self.timeout = timeout
        self.session = requests.Session()
        self.endpoint = os.getenv("DEEPLX_ENDPOINT", "https://api.deeplx.org/translate")
        # v1.11.0：语言映射照官方新版实现
        # （E:\VideoCaptioner app\core\subtitle_processor\translate.py:DeepLXTranslator）
        self.lang_map = {
            "简体中文": "zh",
            "繁体中文": "zh-TW",
            "英语": "en",
            "日本語": "ja",
            "韩语": "ko",
            "法语": "fr",
            "德语": "de",
            "西班牙语": "es",
            "俄语": "ru",
            "葡萄牙语": "pt",
            "土耳其语": "tr",
            "Chinese": "zh",
            "English": "en",
            "Japanese": "ja",
            "Korean": "ko",
            "French": "fr",
            "German": "de",
            "Spanish": "es",
            "Russian": "ru",
        }

    def _target_lang_code(self) -> str:
        """目标语言代码：优先官方 lang_map，未命中回退 types.get_language_code。"""
        name = getattr(self.target_language, "value", str(self.target_language))
        if name in self.lang_map.values():
            return name
        return self.lang_map.get(name) or get_language_code(self.target_language,
                                                            "deeplx")

    def _translate_chunk(
        self, subtitle_chunk: List[SubtitleProcessData]
    ) -> List[SubtitleProcessData]:
        """翻译字幕块（照官方实现：失败条目写 ERROR 标记）"""
        target_lang = self._target_lang_code().lower()

        for data in subtitle_chunk:
            try:
                response = self.session.post(
                    self.endpoint,
                    json={
                        "text": data.original_text,
                        "source_lang": "auto",
                        "target_lang": target_lang,
                    },
                    timeout=self.timeout,
                )
                response.raise_for_status()
                data.translated_text = response.json()["data"]
            except Exception as e:
                logger.error(f"DeepLXTranslation failed {data.index}: {str(e)}")
                data.translated_text = "ERROR"

        return subtitle_chunk

    def _get_cache_key(self, chunk: List[SubtitleProcessData]) -> str:
        """生成缓存键"""
        class_name = self.__class__.__name__
        chunk_key = generate_cache_key(chunk)
        lang = self.target_language.value
        return f"{class_name}:{chunk_key}:{lang}"
