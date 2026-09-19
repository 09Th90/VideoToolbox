"""谷歌翻译器（抓取免费网页版接口）"""

import random
import threading
import time
from typing import Callable, List, Optional

import requests

from videocaptioner.core.entities import SubtitleProcessData
from videocaptioner.core.translate.base import BaseTranslator, logger
from videocaptioner.core.translate.types import TargetLanguage, get_language_code
from videocaptioner.core.utils.cache import generate_cache_key

#: dict-chrome-ex 全局限速（跨线程共享）：免费端点按 IP 限流，实测 30 连发
#: （50ms 间隔）无碍，但字幕任务 83 个 chunk × 高并发线程会瞬时打爆触发
#: 429 → 全部 ERROR → 上层兜底改用 LLM。这里把全局请求间隔钳到 ≥0.12s
#: （约 8 QPS），415 行约 40~50 秒完成，可接受。
_GTX_LOCK = threading.Lock()
_GTX_NEXT = [0.0]
_GTX_MIN_INTERVAL = 0.12


def _gtx_throttle() -> None:
    """全局节流：保证相邻两次请求间隔不小于 _GTX_MIN_INTERVAL。"""
    while True:
        with _GTX_LOCK:
            now = time.monotonic()
            wait = _GTX_NEXT[0] - now
            if wait <= 0:
                _GTX_NEXT[0] = now + _GTX_MIN_INTERVAL
                return
        time.sleep(min(wait, 1.0))


class GoogleTranslator(BaseTranslator):
    """谷歌翻译器 —— 抓取免费网页版接口（Chrome 内置翻译同源端点）。

    v1.12.0：官方旧实现用的 ``translate.google.com/m`` 已死——该端点会被
    谷歌 302 到 /sorry/ 验证码页（旧 IE UA 被风控）；退而求其次的
    ``translate_a/single?client=gtx`` 在国内代理出口 IP 上也会被 429 限流
    （实测同一 IP 下 curl / Chrome 均可用、仅 Python requests 被拒）。
    本实现改抓 Chrome 浏览器内置翻译同源的免费接口，无需任何密钥：

      GET https://translate.googleapis.com/translate_a/t
          ?client=dict-chrome-ex&sl=auto&tl=<目标语言>&q=<文本>

      · 返回 JSON：[["<译文>", "<检测到的源语言>"], ...]，取 [0][0] 即译文；
      · 换行符会原样保留在译文中；
      · 对 Python requests 友好：实测 30 连发（50ms 间隔）零 429，仍保留
        指数退避重试兜底；彻底失败时条目标 ERROR（上层兜底会改用 LLM 重做）；
      · requests 默认信任系统代理（trust_env），国内网络开代理即可直用；
      · 文本上限 5000 字符（与官方实现一致，超出部分截断）。
    """

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
        self.endpoint = "https://translate.googleapis.com/translate_a/t"
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        }
        self.lang_map = {
            "简体中文": "zh-CN",
            "繁体中文": "zh-TW",
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
        }

    def _target_lang_code(self) -> str:
        """目标语言代码：优先官方 lang_map，未命中回退 types.get_language_code。"""
        name = getattr(self.target_language, "value", str(self.target_language))
        if name in self.lang_map.values():
            return name
        return self.lang_map.get(name) or get_language_code(self.target_language,
                                                            "google")

    def _request_text(self, text: str, target_lang: str,
                      timeout: Optional[int] = None) -> Optional[str]:
        """单条请求，全局限速 + 429 指数退避重试；成功返回译文，失败返回 None。"""
        for attempt in range(4):
            _gtx_throttle()
            response = self.session.get(
                self.endpoint,
                params={
                    "client": "dict-chrome-ex",
                    "sl": "auto",
                    "tl": target_lang,
                    "q": text,
                },
                headers=self.headers,
                timeout=timeout or self.timeout,
            )
            if response.status_code == 429:
                wait = 2.0 * (2 ** attempt) + random.uniform(0, 1.0)
                logger.warning(f"Google 429 rate limited, retry in {wait:.1f}s "
                               f"(attempt {attempt + 1}/4)")
                time.sleep(wait)
                continue
            break
        else:
            return None

        if response.status_code != 200:
            return None
        result = response.json()
        # 返回格式：[["<译文>", "<源语言>"], ...]；防御式取第一个字符串
        if isinstance(result, list) and result and isinstance(result[0], list):
            for seg in result[0]:
                if isinstance(seg, str):
                    return seg.strip()
        return None

    def _preflight(self) -> None:
        """连通性预检（v1.15.1）：探测失败立刻抛错，别让整批字幕慢慢超时。

        背景：谷歌这几个免费端点在境内直连必超时（实测 421 条字幕 421 条失败）。
        没有预检时，每条约 20s 超时、几十个 chunk 并发跑完要好几分钟，用户干等
        半天才看到失败。预检只用一条短文本探一次（超时压到 8s），不通就马上把
        控制权交回上层——上层会换一个免密钥机翻（微软）重试。
        """
        try:
            got = self._request_text("hello", self._target_lang_code(), timeout=8)
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(
                "谷歌翻译端点不可达（%s）。免费谷歌翻译在境内需经代理访问，"
                "请检查网络代理，或改用「微软翻译」。" % str(e)[:80]
            ) from e
        if not got:
            raise RuntimeError(
                "谷歌翻译端点没有返回有效译文。该免费端点在境内常被限流/拦截，"
                "请检查网络代理，或改用「微软翻译」。"
            )

    def _translate_chunk(
        self, subtitle_chunk: List[SubtitleProcessData]
    ) -> List[SubtitleProcessData]:
        """翻译字幕块（失败条目标 ERROR，便于上层兜底识别）"""
        target_lang = self._target_lang_code()

        for data in subtitle_chunk:
            try:
                text = data.original_text[:5000]  # google translate max length
                translated = self._request_text(text, target_lang)
                data.translated_text = translated if translated else "ERROR"
                if not translated:
                    logger.warning(
                        f"Cannot extract translation from Google response: {data.index}")
            except Exception as e:
                logger.error(f"Google translation failed {data.index}: {str(e)}")
                data.translated_text = "ERROR"

        return subtitle_chunk

    def _get_cache_key(self, chunk: List[SubtitleProcessData]) -> str:
        """生成缓存键"""
        class_name = self.__class__.__name__
        chunk_key = generate_cache_key(chunk)
        lang = self.target_language.value
        return f"{class_name}:{chunk_key}:{lang}"
