"""微软翻译器（借用 Edge 浏览器的内置翻译服务）"""

from typing import Callable, List, Optional

import requests

from videocaptioner.core.entities import SubtitleProcessData
from videocaptioner.core.translate.base import BaseTranslator, logger
from videocaptioner.core.translate.types import TargetLanguage, get_language_code
from videocaptioner.core.utils.cache import generate_cache_key


class BingTranslator(BaseTranslator):
    """微软翻译器 —— 借用 Edge 浏览器的内置翻译服务（免认证）。

    v1.12.0：官方旧实现的匿名 token 方案已死——
    ``edge.microsoft.com/translate/auth`` 取 token 返回 404。本实现改调
    Edge 浏览器页面翻译实际使用的免认证端点：

      POST https://edge.microsoft.com/translate/translatetext
           ?to=<目标语言>&api-version=3.0

      · Body 为 JSON 字符串数组，整个 chunk 批量一次请求，省略 from 参数
        即自动检测源语言；
      · 需带 Origin / Referer: https://www.microsoft.com（Edge 页面翻译的
        调用方站点），UA 用普通 Edge 浏览器标识；
      · 返回 JSON 数组与请求顺序一一对应，每项 translations[0].text 即译文；
      · 直连可用（无需代理），失败条目标 ERROR（上层兜底会改用 LLM 重做）；
      · 文本上限 5000 字符（与官方实现一致，超出部分截断）。
    """

    def __init__(
        self,
        thread_num: int,
        batch_num: int,
        target_language: TargetLanguage,
        update_callback: Optional[Callable],
    ):
        super().__init__(
            thread_num=thread_num,
            batch_num=batch_num,
            target_language=target_language,
            update_callback=update_callback,
        )
        self.timeout = 20
        self.session = requests.Session()
        self.endpoint = "https://edge.microsoft.com/translate/translatetext"

        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0",
            "Origin": "https://www.microsoft.com",
            "Referer": "https://www.microsoft.com/",
        }
        # v1.12.0：语言映射沿用官方实现（translatetext 端点同样接受这些代码）
        self.lang_map = {
            "简体中文": "zh-Hans",
            "繁体中文": "zh-Hant",
            "英语": "en",
            "日本語": "ja",
            "韩语": "ko",
            "粤语": "yue",
            "法语": "fr",
            "德语": "de",
            "西班牙语": "es",
            "俄语": "ru",
            "葡萄牙语": "pt",
            "土耳其语": "tr",
            "Chinese": "zh-Hans",
            "English": "en",
            "Japanese": "ja",
            "Korean": "ko",
            "French": "fr",
            "German": "de",
            "Russian": "ru",
            "Spanish": "es",
        }

    def _target_lang_code(self) -> str:
        """目标语言代码：优先官方 lang_map，未命中回退 types.get_language_code。"""
        name = getattr(self.target_language, "value", str(self.target_language))
        if name in self.lang_map.values():
            return name
        return self.lang_map.get(name) or get_language_code(self.target_language,
                                                            "bing")

    def _translate_chunk(
        self, subtitle_chunk: List[SubtitleProcessData]
    ) -> List[SubtitleProcessData]:
        """翻译字幕块（批量一次请求；失败条目标 ERROR，便于上层兜底识别）"""
        target_lang = self._target_lang_code()
        texts = [data.original_text[:5000] for data in subtitle_chunk]

        if texts:
            try:
                response = self.session.post(
                    self.endpoint,
                    params={
                        "to": target_lang,
                        "api-version": "3.0",
                    },
                    json=texts,
                    timeout=self.timeout,
                )
                response.raise_for_status()
                results = response.json()

                if (not isinstance(results, list)
                        or len(results) != len(subtitle_chunk)):
                    raise ValueError(
                        f"响应条数与请求不匹配: {len(results) if isinstance(results, list) else '非数组'}"
                        f"/{len(subtitle_chunk)}")

                # 处理翻译结果（与请求顺序一一对应）
                for data, item in zip(subtitle_chunk, results):
                    try:
                        data.translated_text = item["translations"][0]["text"]
                    except (KeyError, IndexError, TypeError):
                        data.translated_text = "ERROR"
                        logger.warning(
                            f"Cannot extract translation from Bing response: {data.index}"
                        )

            except Exception as e:
                logger.error(f"Bing translation failed: {str(e)}")
                # 失败条目打 ERROR 标记（内容不静默变成原文）
                for data in subtitle_chunk:
                    if not str(data.translated_text or "").strip():
                        data.translated_text = "ERROR"

        return subtitle_chunk

    def _get_cache_key(self, chunk: List[SubtitleProcessData]) -> str:
        """生成缓存键"""
        class_name = self.__class__.__name__
        chunk_key = generate_cache_key(chunk)
        lang = self.target_language.value
        return f"{class_name}:{chunk_key}:{lang}"
