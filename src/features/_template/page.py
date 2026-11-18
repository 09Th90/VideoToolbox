# -*- coding: utf-8 -*-
# @version 3.1.0
"""GUI 页模板。本模块只由 gui.builder 惰性构造（CLI 路径永不 import）。

约束：只用 vt_app 基建 + 注册表服务；禁止反向 import video_toolbox_qt。
消息回传统一走 app.q 元组（前缀与 GuiSpec.messages 一致），主线程 bus 泵出。
"""
from __future__ import annotations


def build_page(app):
    from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget  # noqa: PLC0415

    page = QWidget()
    page.setObjectName("templatePage")
    lay = QVBoxLayout(page)
    lay.addWidget(QLabel("模板功能页（替换成你的 UI）", page))
    return page