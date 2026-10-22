# @version 2.5.2
"""翻译编排（自研，替代 videocaptioner.core.translate.base.BaseTranslator）。

把「分块 → 线程池并发 → 缓存 → 失败兜底 → 落盘前断言」这套**可观察
行为**收进自研代码。以下每条都是引擎的真实行为（踩过的坑），逐条固化：

1. **0 条直接抛** :class:`TranslationIncompleteError`——空字幕不许产出
   「名为翻译、实为空」的文件；
2. **预检钩子** ``_preflight()``：端点可能整体不可达时（如谷歌在境内）
   先探测再开翻，别让 421 条字幕一条条白等超时；
3. **失败条目标 ERROR**：机翻翻译器内部吞异常写 ``ERROR`` 标记，上层
   按标记统计失败率（只数 chunk 抛异常会恒为 0——端点整批挂掉也会被
   当成成功，这就是「跑完没中文」的根源）；
4. **失败率 ≥50% 抛错**，<50% 只警告；用户主动停止单独给话；
5. **含失败条目不写缓存**：端点失败缓存 7 天会让端点恢复后仍命中文
   脏数据（实测 2205 条脏缓存导致「0/415 条产出」）；
6. **落盘前两道断言**：译文缺失明细 + 「整片一个汉字都没有」判定端点
   其实没翻；
7. **缓存键** ``类名:内容哈希:目标语言[:模型]``——LLM 翻译器多带
   一截模型名（换模型必须重翻，这是引擎的真实差异）。

与引擎共享同一份 translate 缓存目录与键算法（既有翻译缓存继续有效）；
机翻翻译器实现复用 ``engine_translate``（已逐条比对译文一致）。
"""

from __future__ import annotations

import atexit
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, List, Optional

from vt_engine.asr_data import ASRData, ASRDataSeg
from vt_engine.cache import generate_cache_key
from vt_engine.constants import TRANSLATE_CACHE_EXPIRE
from vt_engine.entities import SubtitleProcessData
from vt_engine.log import setup_logger
from vt_engine.translators import ERROR_MARK

logger = setup_logger("vt_engine.translate")

__all__ = [
    "TranslationIncompleteError",
    "BaseTranslator",
]

#: 目标语言是中文时，判断「译文到底有没有翻成中文」的整片判据。
_CJK_TARGETS = {"简体中文", "繁体中文", "粤语"}


class TranslationIncompleteError(RuntimeError):
    """译文缺失或未真正翻译——绝不落盘「名为翻译、实为原文」的字幕。"""


class BaseTranslator(ABC):
    """翻译器基类：线程池 + 分块 + 缓存 + 失败语义 + 落盘断言。"""

    def __init__(self, thread_num: int, batch_num: int,
                 target_language, update_callback: Optional[Callable]):
        self.thread_num = max(1, int(thread_num or 1))
        self.batch_num = max(1, int(batch_num or 1))
        self.target_language = target_language
        self.is_running = True
        self.update_callback = update_callback
        self.executor = None
        from vt_engine.cache import default_cache_hub
        self._cache = default_cache_hub().get("translate")
        self._init_thread_pool()

    def _init_thread_pool(self):
        self.executor = ThreadPoolExecutor(max_workers=self.thread_num)
        atexit.register(self.stop)

    # ---------------- 对外：翻译整份字幕 ----------------
    def translate_subtitle(self, subtitle_data: ASRData) -> ASRData:
        """翻译一份 ASRData（就地写 ``translated_text``，返回新 ASRData）。"""
        try:
            asr_data = subtitle_data
            translate_data_list = [
                SubtitleProcessData(index=i, original_text=seg.text)
                for i, seg in enumerate(asr_data.segments, 1)
            ]
            if not translate_data_list:
                raise TranslationIncompleteError(
                    "字幕没有可翻译的正文（0 条），未生成任何文件")

            # 连通性预检：端点不通立刻失败，别让用户干等几分钟
            self._preflight()

            chunks = self._split_chunks(translate_data_list)
            translated_list = self._parallel_translate(chunks)

            new_segments = self._set_segments_translated_text(
                asr_data.segments, translated_list)

            # 落盘前的最后两道防线
            self._assert_translation_complete(new_segments)
            self._assert_translation_language(new_segments)
            return ASRData(new_segments)
        except TranslationIncompleteError:
            raise
        except Exception as e:
            msg = str(e)
            if isinstance(e, RuntimeError) and \
                    msg.startswith("Translation failed"):
                raise
            logger.error("Translation failed: %s", msg)
            raise RuntimeError("Translation failed: %s" % msg)

    # ---------------- 钩子（子类可覆写） ----------------
    def _preflight(self) -> None:
        """翻译前的连通性预检（默认不做；实现失败应抛异常）。"""

    # ---------------- 断言 ----------------
    def _assert_translation_complete(self,
                                     segments: List[ASRDataSeg]) -> None:
        """逐条校验译文；缺失即抛（含失败明细与示例）。"""
        total = len(segments)
        if total <= 0:
            raise TranslationIncompleteError("字幕没有可翻译的正文（0 条）")
        missing = [i for i, seg in enumerate(segments, 1)
                   if not self._valid_translated_text(
                       getattr(seg, "translated_text", ""))]
        if not missing:
            return
        if not self.is_running:
            raise TranslationIncompleteError(
                "翻译已中断：%d/%d 条没有译文，未生成字幕文件。请重新执行翻译。"
                % (len(missing), total))
        sample = []
        for i in missing[:3]:
            seg = segments[i - 1]
            sample.append("#%d %s" % (i, str(getattr(seg, "text", ""))[:24]))
        logger.error("译文缺失 %d/%d 条，放弃保存：%s", len(missing), total,
                     "；".join(sample))
        raise TranslationIncompleteError(
            "翻译不完整：%d/%d 条没有拿到译文（%.0f%%）。已放弃保存，"
            "避免产出「名为翻译、实为原文」的字幕。失败示例：%s。"
            "请检查网络/代理是否可用，或换一种翻译服务后重试。"
            % (len(missing), total, len(missing) / total * 100,
               "；".join(sample)))

    def _assert_translation_language(self,
                                     segments: List[ASRDataSeg]) -> None:
        """目标语言是中文时，整片一个汉字都没有 → 端点其实没翻。"""
        name = getattr(self.target_language, "value",
                       str(self.target_language))
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
                "译文里没有任何中文：目标语言是「%s」，但 %d 条译文全是"
                "非中文文本，说明翻译端点没有真正翻译（常见于免费机翻端点"
                "被限流/返回原文）。已放弃保存，请换服务或稍后重试。"
                % (name, len(segments)))

    # ---------------- 分块与并发 ----------------
    def _split_chunks(self, translate_data_list):
        return [translate_data_list[i:i + self.batch_num]
                for i in range(0, len(translate_data_list), self.batch_num)]

    def _parallel_translate(self, chunks):
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
                translated_list.extend(future.result())
            except Exception as e:  # noqa: BLE001
                logger.error("Translation chunk failed: %s", e)
                failed_count += len(future_to_chunk[future])
                translated_list.extend(future_to_chunk[future])

        if cancelled:
            logger.warning("翻译被中断：已产出 %d/%d 条，剩余批次未执行",
                           len(translated_list), total_segments)
            return translated_list

        # 失败数按「译文是否真的有效」算——机翻翻译器自己吞异常写 ERROR，
        # 只数 chunk 抛异常会恒为 0（端点整批挂也被当成成功）。
        invalid_count = sum(
            1 for d in translated_list
            if not self._valid_translated_text(
                getattr(d, "translated_text", "")))
        failed_count = max(failed_count, invalid_count)

        if failed_count > 0 and total_segments > 0:
            fail_rate = failed_count / total_segments
            if fail_rate >= 0.5:
                raise RuntimeError(
                    "Translation failed: %d/%d segments failed (%.0f%%). "
                    "Check your API key and network connection."
                    % (failed_count, total_segments, fail_rate * 100))
            logger.warning("Translation partially failed: %d/%d segments",
                           failed_count, total_segments)
        return translated_list

    # ---------------- 缓存 ----------------
    @staticmethod
    def _valid_translated_text(text) -> bool:
        """译文是否有效（失败条目被写成 ERROR / xxx||ERROR 标记）。"""
        t = str(text or "").strip()
        if not t or t in (ERROR_MARK, "TRANSLATION ERROR"):
            return False
        return not t.endswith("||ERROR")

    def _get_cache_key(self, chunk) -> str:
        """``类名:内容哈希:目标语言``（LLM 翻译器多带模型名，见子类）。"""
        name = getattr(self.target_language, "value",
                       str(self.target_language))
        return "%s:%s:%s" % (type(self).__name__,
                             generate_cache_key(chunk), name)

    def _cache_get(self, cache_key):
        """读缓存；任何缓存层异常都返回 None（脏 pickle / 库损坏）。

        库级损坏（sqlite DatabaseError）会留下 ``_cache_broken`` 标记，
        后续 chunk 直接跳过缓存——不让每个 chunk 都去撞一遍坏库。
        """
        if getattr(self, "_cache_broken", False):
            return None
        try:
            return self._cache.get(cache_key, default=None)
        except Exception as e:  # noqa: BLE001
            logger.warning("缓存读取失败（按未命中处理）: %s", e)
            self._cache_broken = True
            try:
                self._cache.delete(cache_key)
            except Exception:  # noqa: BLE001
                pass
            return None

    def _cache_put(self, cache_key, result):
        """写缓存；失败只警告不抛——缓存是性能优化，不是正确性依赖。"""
        if getattr(self, "_cache_broken", False):
            return
        try:
            self._cache.set(cache_key, result, expire=TRANSLATE_CACHE_EXPIRE)
        except Exception as e:  # noqa: BLE001
            logger.warning("缓存写入失败（不影响本次翻译）: %s", e)
            self._cache_broken = True

    def _safe_translate_chunk(self, chunk):
        """带缓存翻译一个 chunk；失败条目不写缓存（下次自动重试）。"""
        try:
            cache_key = self._get_cache_key(chunk)
            cached_result = self._cache_get(cache_key)
            if cached_result is not None:
                return cached_result

            result = self._translate_chunk(chunk)
            if self.update_callback:
                self.update_callback(result)

            if all(self._valid_translated_text(
                    getattr(d, "translated_text", "")) for d in result):
                self._cache_put(cache_key, result)
            else:
                logger.warning(
                    "Chunk translation has invalid entries, "
                    "skip caching for retry")
            return result
        except Exception as e:
            logger.exception("Translation failed: %s", e)
            raise

    # ---------------- 回填 ----------------
    @staticmethod
    def _set_segments_translated_text(original_segments, translated_list):
        """按 index 回填译文（缺项打日志，由断言统一报错）。"""
        translation_map = {data.index: data.translated_text
                           for data in translated_list}
        missing = []
        for i, seg in enumerate(original_segments, 1):
            if i not in translation_map:
                missing.append(i)
                continue
            seg.translated_text = translation_map[i]
        if missing:
            logger.error("Subtitle segment(s) without translation: %d 条 %s%s",
                         len(missing), missing[:10],
                         " ..." if len(missing) > 10 else "")
        return original_segments

    @abstractmethod
    def _translate_chunk(self, subtitle_chunk):
        """翻译一个字幕块（子类实现）。"""

    def stop(self):
        """停止翻译器（取消未执行任务）。"""
        if not self.is_running:
            return
        self.is_running = False
        if getattr(self, "executor", None) is not None:
            try:
                self.executor.shutdown(wait=False, cancel_futures=True)
            except Exception as e:  # noqa: BLE001
                logger.error("Error closing thread pool: %s", e)
            finally:
                self.executor = None
        # 反注册 atexit 钩子：每个实例构造时都 register 过，不反注册
        # 会被 atexit 强引用到进程退出——长驻进程反复建翻译器会持续
        # 堆积实例与钩子（2026-10-19 自查优化）。
        try:
            atexit.unregister(self.stop)
        except Exception:  # noqa: BLE001
            pass
