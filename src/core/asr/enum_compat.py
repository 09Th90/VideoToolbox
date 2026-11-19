# -*- coding: utf-8 -*-
# @version 3.1.1
"""ASR 配置字段的「枚举 / 字符串」双兼容取值层。

背景（2026-11-18 第三方反馈）
----------------------------
本地独立模型（faster-whisper）的模型名由 ``asr_local_override()`` 以**纯字符串**
（``large-v3``，或枚举外的自训练/自定义名）写进
``TranscribeConfig.faster_whisper_model``，而引擎
``videocaptioner.core.asr.transcribe._create_faster_whisper_asr`` 按枚举取
``config.faster_whisper_model.value`` ⇒ ``'str' object has no attribute
'value'``，本地模式 100% 失败，界面只弹一句「转录失败」。

``enum_like()`` 返回 str 子类 :class:`EnumLike`：引擎取 ``.value`` 得到原名，
字符串语义（拼接 / 比较 / 日志 / JSON 序列化）与普通 str 完全一致，不需要
改动引擎本体。

使用面（三层）：
  1. 任务工厂 ``_apply_asr_override`` —— 源头写配置时就包一层；
  2. ``vc_asr_patch_apply`` / ``vt_engine.tasks`` —— 引擎工厂补丁同款；
  3. :func:`core.asr.patches.vc_asr_local_model_patch` —— 引擎
     ``_create_asr_instance`` 入口兜底，任何来源的任务（含引擎自带
     TaskFactory 产物、旧队列任务）都不会再把 str 当枚举取 ``.value``。
"""
from __future__ import annotations

__all__ = ["EnumLike", "enum_like"]


class EnumLike(str):
    """str 子类 + ``.value``：同时满足「按字符串用」与「按枚举取 .value」。

    ``__slots__ = ()`` 保证实例不额外占内存；不做任何 str 行为改写——
    ``json.dumps`` / f-string / ``==`` / ``.lower()`` 全部与普通 str 一致。
    """

    __slots__ = ()

    @property
    def value(self):
        return str(self)


def enum_like(value):
    """把任意取值转成可安全取 ``.value`` 的对象。

    * ``None`` 原样返回（调用方的 ``x if x else 默认值`` 语义不变）；
    * 已是枚举成员 / 任何自带 ``.value`` 的对象原样返回（不破坏真枚举）；
    * 其余（含纯 str）包成 :class:`EnumLike`。
    """
    if value is None:
        return None
    if hasattr(value, "value"):
        return value
    return EnumLike(str(value))
