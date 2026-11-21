# -*- coding: utf-8 -*-
# @version 3.1.6
"""跨线程业务消息总线（2026-11-15 功能解耦阶段②新增）。

原单体的 ``_dispatch`` 是 60+ 分支的字符串路由表，页面与路由硬耦合。
本总线把「消息名 → 处理器」改为**订阅式**：页面拆出到 features/<id>/page.py
后各自 ``bus.subscribe(前缀, handler)``，未迁移的消息仍走 fallback（旧路由表），
逐页认领、逐段清空，最终旧表整体删除。

泵语义不变：MainWindow._pump 每 120ms 一轮、每轮最多 200 条（防冻结脉冲），
本类只负责单条消息的分发，不拥有定时器。
"""
import traceback


class MessageBus:
    """消息名 → 订阅处理器；未命中走 fallback（兼容旧路由表）。

    * subscribe(prefix, handler)：前缀匹配（``dl_`` 命中 dl_progress/dl_log/…；
      完整消息名如 ``detect_done`` 也按前缀规则命中）。handler 收整条元组。
    * 同一前缀只允许一个订阅者（页面级路由，现状无跨页广播）；后订阅覆盖前者。
    * 处理器异常经 on_error 落盘，绝不炸泵；fallback 自带异常兜底（旧表原样）。
    """

    def __init__(self, queue, fallback=None, on_error=None):
        self.q = queue
        self._subs = {}        # prefix -> handler
        self.fallback = fallback
        self.on_error = on_error

    def subscribe(self, prefix, handler):
        self._subs[prefix] = handler

    def unsubscribe(self, prefix):
        self._subs.pop(prefix, None)

    def dispatch(self, msg) -> bool:
        kind = msg[0] if msg else ""
        # 最长前缀优先：``dl_`` 与 ``dl_done`` 同时订阅时取更具体的
        best = None
        for prefix in self._subs:
            if kind == prefix or kind.startswith(prefix):
                if best is None or len(prefix) > len(best):
                    best = prefix
        if best is not None:
            try:
                self._subs[best](msg)
            except Exception:  # noqa: BLE001 —— 单条消息失败不炸泵
                if self.on_error is not None:
                    try:
                        self.on_error(traceback.format_exc())
                    except Exception:  # noqa: BLE001
                        pass
            return True
        if self.fallback is not None:
            self.fallback(msg)
            return True
        return False