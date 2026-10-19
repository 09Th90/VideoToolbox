# @version 2.4.0
"""翻译工厂与机翻回落（自研，替代引擎 subtitle_thread 的两个模块级函数）。

可观察行为：

* :func:`create_translator_from_config` —— 按 ``SubtitleConfig`` 的
  ``translator_service`` 构造翻译器；各服务的 batch 收敛值沿用引擎
  工厂（谷歌 5 / 必应 10 / DeepLx 5）；DeepLx 自定义端点**显式覆盖**
  实例 endpoint（引擎借 os.environ 传递，且空值会把实例端点打成空串）；
* :func:`translate_with_machine_fallback` —— 谷歌 ⇄ 必应互退。
  背景（2026-09-19 实测）：用户网络下谷歌 421 全失败（直连被墙、
  本地代理不通），不回退用户只能得到一条报错。回退可逆：只临时改
  ``config.translator_service``，用完还原；失败轮不写缓存；重跑前清空
  已写入的部分译文，避免新旧混杂。
* **LLM 失败不回退机翻**（v1.12.0 原则）：LLM 服务异常应当暴露给
  用户，而不是偷偷换免费端点改变翻译质量与计费主体。
"""

from __future__ import annotations

import os
from typing import Callable, Optional

from vt_engine.cache import generate_cache_key
from vt_engine.entities import (
    SubtitleConfig,
    SubtitleProcessData,
    TranslatorServiceEnum,
)
from vt_engine.llm_translator import LLMTranslator
from vt_engine.log import setup_logger
from vt_engine.translate_base import BaseTranslator
from vt_engine.translators import (
    BingTranslator,
    DeepLxTranslator,
    GoogleTranslator,
)
from vt_engine.asr_data import ASRData

logger = setup_logger("vt_engine.translate_factory")

__all__ = [
    "MACHINE_FALLBACK",
    "create_translator_from_config",
    "translate_with_machine_fallback",
    "MachineTranslatorAdapter",
]

#: DeepLx 公开实例（自定义端点为空时用它）。
_DEEPLX_DEFAULT_ENDPOINT = "https://api.deeplx.org/translate"

#: 机翻服务回退表（只涉及机器翻译，不引入 LLM）。
MACHINE_FALLBACK = {
    TranslatorServiceEnum.GOOGLE: TranslatorServiceEnum.BING,
    TranslatorServiceEnum.BING: TranslatorServiceEnum.GOOGLE,
}

#: 各服务的 batch 收敛值（引擎 TranslatorFactory 行为）。
_BATCH_BY_SERVICE = {
    TranslatorServiceEnum.GOOGLE: 5,
    TranslatorServiceEnum.BING: 10,
    TranslatorServiceEnum.DEEPLX: 5,
}


class MachineTranslatorAdapter(BaseTranslator):
    """把 ``engine_translate`` 的 **chunk 级**翻译器包进自研编排基类。

    背景（两个基类的分工，2026-10-18 实测抓出）：
    接缝模块 ``engine_translate`` 的 BingTranslator/GoogleTranslator/
    DeepLxTranslator 继承 ``BaseSubtitleTranslator``——只提供
    ``translate(chunk)`` 的**块级协议**；而编排（分块/线程池/缓存/失败
    兜底/落盘断言）在引擎侧是 ``core.translate.base.BaseTranslator``，
    它的子类（含各机翻器）直接长在编排之上。自研线里编排由
    ``vt_engine.translate_base`` 提供，机翻协议仍复用接缝模块——本适配器
    负责把两者组合起来，缺了它编排层调 ``translate_subtitle`` 会直接
    AttributeError（机翻链路整体瘫痪，且会被误判成「服务不可用」走错
    排查方向）。

    缓存键沿用**内层类名**（``BingTranslator:...``）——与引擎同键，
    用户既有的翻译缓存继续有效，不因切换实现而全部失效。
    """

    def __init__(self, inner, thread_num: int, batch_num: int,
                 target_language, update_callback=None):
        super().__init__(thread_num=thread_num, batch_num=batch_num,
                         target_language=target_language,
                         update_callback=update_callback)
        self._inner = inner

    def _get_cache_key(self, chunk) -> str:
        name = getattr(self.target_language, "value",
                       str(self.target_language))
        return "%s:%s:%s" % (type(self._inner).__name__,
                             generate_cache_key(chunk), name)

    def _translate_chunk(self, chunk):
        """委托内层 chunk 级翻译器（失败条目由它标 ERROR，上层记账）。"""
        return self._inner.translate(chunk)


def create_translator_from_config(config: SubtitleConfig,
                                  custom_prompt: str = "",
                                  callback: Optional[Callable] = None):
    """根据 SubtitleConfig 创建翻译器。"""
    service = config.translator_service
    if service == TranslatorServiceEnum.OPENAI:
        return LLMTranslator(
            thread_num=config.thread_num,
            batch_num=config.batch_size,
            target_language=config.target_language,
            model=config.llm_model or "",
            custom_prompt=custom_prompt,
            is_reflect=config.need_reflect,
            update_callback=callback,
        )
    if service not in _BATCH_BY_SERVICE:
        raise ValueError("不支持的翻译服务: %s" % service)

    batch_num = _BATCH_BY_SERVICE[service]
    if service == TranslatorServiceEnum.GOOGLE:
        return MachineTranslatorAdapter(
            GoogleTranslator(
                thread_num=config.thread_num, batch_num=batch_num,
                target_language=config.target_language,
                update_callback=callback),
            thread_num=config.thread_num, batch_num=batch_num,
            target_language=config.target_language,
            update_callback=callback)
    if service == TranslatorServiceEnum.BING:
        return MachineTranslatorAdapter(
            BingTranslator(
                thread_num=config.thread_num, batch_num=batch_num,
                target_language=config.target_language,
                update_callback=callback),
            thread_num=config.thread_num, batch_num=batch_num,
            target_language=config.target_language,
            update_callback=callback)
    # DeepLx：自定义端点显式覆盖（空值回落公开实例）
    t = DeepLxTranslator(
        thread_num=config.thread_num, batch_num=batch_num,
        target_language=config.target_language, update_callback=callback)
    t.endpoint = str(getattr(config, "deeplx_endpoint", "") or "").strip() \
        or _DEEPLX_DEFAULT_ENDPOINT
    return MachineTranslatorAdapter(
        t, thread_num=config.thread_num, batch_num=batch_num,
        target_language=config.target_language, update_callback=callback)


def translate_with_machine_fallback(config: SubtitleConfig,
                                     custom_prompt: str,
                                     callback,
                                     asr_data: ASRData,
                                     progress=None,
                                     on_translator=None) -> ASRData:
    """翻译字幕；首选机翻失败时自动回退到另一个免密钥机翻服务。"""
    service = config.translator_service
    translator = create_translator_from_config(config, custom_prompt,
                                               callback)
    if on_translator:
        on_translator(translator)
    try:
        return translator.translate_subtitle(asr_data)
    except Exception as e:  # noqa: BLE001
        fallback = MACHINE_FALLBACK.get(service)
        if fallback is None:
            raise
        logger.warning("「%s」翻译失败（%s），自动改用「%s」重试",
                       service.value, str(e)[:160], fallback.value)
        if progress:
            progress("「%s」不可用，自动改用「%s」重试…"
                     % (service.value, fallback.value))
        try:
            translator.stop()
        except Exception:  # noqa: BLE001
            pass
        # 上一轮可能已写入部分译文，清干净再重跑
        for seg in asr_data.segments:
            seg.translated_text = ""
        config.translator_service = fallback
        try:
            translator = create_translator_from_config(config,
                                                       custom_prompt, callback)
            if on_translator:
                on_translator(translator)
            return translator.translate_subtitle(asr_data)
        finally:
            config.translator_service = service
