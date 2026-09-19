"""翻译器基类"""

import atexit
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, List, Optional

from videocaptioner.core.asr.asr_data import ASRData, ASRDataSeg
from videocaptioner.core.entities import SubtitleProcessData
from videocaptioner.core.translate.types import TargetLanguage
from videocaptioner.core.utils.cache import generate_cache_key, get_translate_cache
from videocaptioner.core.utils.logger import setup_logger

logger = setup_logger("subtitle_translator")

#: 目标语言是中文时，用于判断"译文到底有没有翻成中文"（见
#: _assert_translation_language）。整片译文一个汉字都没有 = 端点其实没翻。
_CJK_TARGETS = {"简体中文", "繁体中文", "粤语"}


class TranslationIncompleteError(RuntimeError):
    """译文缺失或未真正翻译。

    v1.15.1 新增：以前机翻端点整批失败时，条目译文是空字符串，``ASRData.to_srt``
    会"静默回落成原文"（``f"{translated}\\n{original}" if translated else original``），
    于是产出一个**名字叫「-谷歌翻译.srt」、内容其实是原文**的文件，全程零报错。
    现在这类结果一律抛本异常，绝不落盘。
    """


class BaseTranslator(ABC):
    """翻译器基类"""

    def __init__(
        self,
        thread_num: int,
        batch_num: int,
        target_language: TargetLanguage,
        update_callback: Optional[Callable],
    ):
        self.thread_num = thread_num
        self.batch_num = batch_num
        self.target_language = target_language
        self.is_running = True
        self.update_callback = update_callback
        self.executor = None
        self._cache = get_translate_cache()

        self._init_thread_pool()

    def _init_thread_pool(self):
        """初始化线程池"""
        self.executor = ThreadPoolExecutor(max_workers=self.thread_num)
        atexit.register(self.stop)

    def translate_subtitle(self, subtitle_data: ASRData) -> ASRData:
        """翻译字幕文件"""
        try:
            asr_data = subtitle_data

            # 将ASRData转换为SubtitleProcessData列表
            translate_data_list = [
                SubtitleProcessData(index=i, original_text=seg.text)
                for i, seg in enumerate(asr_data.segments, 1)
            ]
            if not translate_data_list:
                raise TranslationIncompleteError(
                    "字幕没有可翻译的正文（0 条），未生成任何文件"
                )

            # v1.15.1：可选的连通性预检——端点不通就**立刻**失败（上层据此换
            # 服务重试）。没有预检的话，421 条字幕会一条条慢慢超时，用户要干等
            # 好几分钟才看到失败。
            self._preflight()

            # 分批处理字幕
            chunks = self._split_chunks(translate_data_list)

            # 多线程翻译
            translated_list = self._parallel_translate(chunks)

            # 设置Subtitle segment的翻译文本
            new_segments = self._set_segments_translated_text(
                asr_data.segments, translated_list
            )

            # v1.15.1：落盘前的最后一道防线——译文缺失/整片没翻成中文时直接
            # 抛错，绝不让「名为翻译、实为原文」的字幕流到用户手里。
            self._assert_translation_complete(new_segments)
            self._assert_translation_language(new_segments)

            return ASRData(new_segments)
        except TranslationIncompleteError:
            # 已经是给用户看的消息，原样上抛（不要被包成 RuntimeError）
            raise
        except Exception as e:
            msg = str(e)
            # 已经是 "Translation failed: ..." 的别再套一层（旧实现会出现
            # 「Translation failed: Translation failed: ...」这种叠词）
            if isinstance(e, RuntimeError) and msg.startswith("Translation failed"):
                raise
            logger.error(f"Translation failed: {msg}")
            raise RuntimeError(f"Translation failed: {msg}")

    def _preflight(self) -> None:
        """翻译前的连通性预检（可选，默认不做）。

        子类只有在"端点可能整体不可达"时才需要实现它——例如谷歌翻译在境内
        直连必超时。实现里探测失败应当**抛异常**，让上层快速回退/报错。
        """

    def _assert_translation_complete(self, segments: List[ASRDataSeg]) -> None:
        """逐条校验译文是否拿到；缺失即抛错（含失败明细）。"""
        total = len(segments)
        if total <= 0:
            raise TranslationIncompleteError("字幕没有可翻译的正文（0 条）")

        missing = [
            i
            for i, seg in enumerate(segments, 1)
            if not self._valid_translated_text(getattr(seg, "translated_text", ""))
        ]
        if not missing:
            return

        # 用户主动点「停止」时线程池会被 cancel，这一支单独给话
        if not self.is_running:
            raise TranslationIncompleteError(
                f"翻译已中断：{len(missing)}/{total} 条没有译文，"
                f"未生成字幕文件。请重新执行翻译。"
            )

        sample = []
        for i in missing[:3]:
            seg = segments[i - 1]
            sample.append(f"#{i} {str(getattr(seg, 'text', ''))[:24]}")
        logger.error(
            "译文缺失 %d/%d 条，放弃保存：%s", len(missing), total, "；".join(sample)
        )
        raise TranslationIncompleteError(
            f"翻译不完整：{len(missing)}/{total} 条没有拿到译文"
            f"（{len(missing) / total:.0%}）。已放弃保存，"
            f"避免产出「名为翻译、实为原文」的字幕。"
            f"失败示例：{'；'.join(sample)}。"
            f"请检查网络/代理是否可用，或换一种翻译服务后重试。"
        )

    def _assert_translation_language(self, segments: List[ASRDataSeg]) -> None:
        """目标语言是中文时，整片译文一个汉字都没有 → 判定端点其实没翻。

        只做整片判断（不看单条），专有名词/纯数字行不会误伤。
        """
        name = getattr(self.target_language, "value", str(self.target_language))
        if name not in _CJK_TARGETS:
            return
        han = 0
        letters = 0
        for seg in segments:
            t = str(getattr(seg, "translated_text", "") or "")
            han += sum(1 for ch in t if "\u4e00" <= ch <= "\u9fff")
            letters += sum(1 for ch in t if ch.isalpha())
        if letters and not han:
            raise TranslationIncompleteError(
                "译文里没有任何中文：目标语言是"
                f"「{name}」，但 {len(segments)} 条译文全是非中文文本，"
                "说明翻译端点没有真正翻译（常见于免费机翻端点被限流/返回原文）。"
                "已放弃保存，请换服务或稍后重试。"
            )

    def _split_chunks(
        self, translate_data_list: List[SubtitleProcessData]
    ) -> List[List[SubtitleProcessData]]:
        """将字幕分割成块"""
        return [
            translate_data_list[i : i + self.batch_num]
            for i in range(0, len(translate_data_list), self.batch_num)
        ]

    def _parallel_translate(
        self, chunks: List[List[SubtitleProcessData]]
    ) -> List[SubtitleProcessData]:
        """并行翻译All块"""
        future_to_chunk = {}
        translated_list = []
        failed_count = 0
        total_segments = sum(len(c) for c in chunks)

        for chunk in chunks:
            future = self.executor.submit(self._safe_translate_chunk, chunk)
            future_to_chunk[future] = chunk

        cancelled = False
        for future in as_completed(future_to_chunk):
            if not self.is_running:
                cancelled = True
                break
            try:
                result = future.result()
                translated_list.extend(result)
            except Exception as e:
                logger.error(f"Translation chunk failed: {e}")
                failed_count += len(future_to_chunk[future])
                translated_list.extend(future_to_chunk[future])

        if cancelled:
            logger.warning(
                "翻译被中断：已产出 %d/%d 条，剩余批次未执行",
                len(translated_list), total_segments,
            )
            return translated_list

        # v1.15.1：失败数要按「译文是否真的有效」来算，而不是只看 chunk 有没有抛异常。
        # 机翻翻译器的 _translate_chunk 内部自己吞掉了请求异常（失败条目标 ERROR），
        # 所以 failed_count 恒为 0——端点整批挂掉也会被当成翻译成功，这才是
        # 「跑完没中文」的根源。这里把空译文 / ERROR / xxx||ERROR 一并计入。
        invalid_count = sum(
            1
            for d in translated_list
            if not self._valid_translated_text(getattr(d, "translated_text", ""))
        )
        failed_count = max(failed_count, invalid_count)

        if failed_count > 0 and total_segments > 0:
            fail_rate = failed_count / total_segments
            if fail_rate >= 0.5:
                raise RuntimeError(
                    f"Translation failed: {failed_count}/{total_segments} segments failed "
                    f"({fail_rate:.0%}). Check your API key and network connection."
                )
            elif failed_count > 0:
                logger.warning(f"Translation partially failed: {failed_count}/{total_segments} segments")

        return translated_list

    @staticmethod
    def _valid_translated_text(text) -> bool:
        """译文是否有效（失败条目会被各翻译器写成 ERROR / xxx||ERROR 标记）"""
        t = str(text or "").strip()
        if not t or t in ("ERROR", "TRANSLATION ERROR"):
            return False
        return not t.endswith("||ERROR")

    def _get_cache_key(self, chunk: List[SubtitleProcessData]) -> str:
        """生成缓存键"""
        class_name = self.__class__.__name__
        chunk_key = generate_cache_key(chunk)
        lang = self.target_language.value
        return f"{class_name}:{chunk_key}:{lang}"

    def _safe_translate_chunk(
        self, chunk: List[SubtitleProcessData]
    ) -> List[SubtitleProcessData]:
        """安全的翻译块"""
        try:
            cache_key = self._get_cache_key(chunk)
            try:
                cached_result = self._cache.get(cache_key, default=None)
            except Exception:
                # Graceful degradation: corrupted cache (e.g. old pickle from app→videocaptioner rename)
                cached_result = None
                self._cache.delete(cache_key)
            if cached_result is not None:
                return cached_result

            result = self._translate_chunk(chunk)

            if self.update_callback:
                self.update_callback(result)

            # v1.12.0：含失败条目（ERROR / 空译文 / xxx||ERROR）不写缓存——
            # 旧实现端点失败时把 ERROR 结果缓存了 7 天，端点恢复后新实现
            # 仍命中同一缓存键直接返回脏数据（实测 2205 条脏缓存导致谷歌
            # 翻译"0/415 条产出"）。失败不缓存，下次自动重试真实端点。
            if all(
                self._valid_translated_text(getattr(d, "translated_text", ""))
                for d in result
            ):
                self._cache.set(cache_key, result, expire=86400 * 7)
            else:
                logger.warning(
                    "Chunk translation has invalid entries, skip caching for retry"
                )
            return result

        except Exception as e:
            logger.exception(f"Translation failed: {str(e)}")
            raise

    @staticmethod
    def _set_segments_translated_text(
        original_segments: List[ASRDataSeg], translated_list: List[SubtitleProcessData]
    ) -> List[ASRDataSeg]:
        """设置Subtitle segment的翻译文本"""
        # 创建索引到翻译文本的映射
        translation_map = {data.index: data.translated_text for data in translated_list}

        missing = []
        for i, seg in enumerate(original_segments, 1):
            if i not in translation_map:
                missing.append(i)
                continue
            seg.translated_text = translation_map[i]

        if missing:
            # v1.15.1：明细打出来，配合 _assert_translation_complete 的报错定位
            logger.error(
                "Subtitle segment(s) without translation: %d 条 %s%s",
                len(missing),
                missing[:10],
                " ..." if len(missing) > 10 else "",
            )

        return original_segments

    @abstractmethod
    def _translate_chunk(
        self, subtitle_chunk: List[SubtitleProcessData]
    ) -> List[SubtitleProcessData]:
        """翻译字幕块"""
        pass

    def stop(self):
        """停止翻译器"""
        if not self.is_running:
            return

        self.is_running = False
        if hasattr(self, "executor") and self.executor is not None:
            try:
                self.executor.shutdown(wait=False, cancel_futures=True)
            except Exception as e:
                logger.error(f"Error closing thread pool: {str(e)}")
            finally:
                self.executor = None
