# -*- coding: utf-8 -*-
# @version 3.3.1
"""发布素材页：选字幕 + 游戏名/主播名 → 生成 10 段时间轴/10 tag/标题。"""
import os
import threading

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFileDialog

from vt_fluent import LineEdit, PrimaryPushButton, PushButton

import video_toolbox as engine
import features.publish.publish_material as pm

from vt_app.widgets import LogView, TabPage, card, label_row, row


class PublishPage(TabPage):
    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        lay = self.view_layout() if hasattr(self, "view_layout") else self.layout()
        box = card(self)
        self.srt_edit = LineEdit(box)
        self.srt_edit.setPlaceholderText("字幕文件路径（校准产物优先）")
        browse = PushButton("浏览", box)
        browse.clicked.connect(self._browse)
        self.game_edit = LineEdit(box)
        self.game_edit.setPlaceholderText("游戏名（缺省读配置默认）")
        self.streamer_edit = LineEdit(box)
        self.streamer_edit.setPlaceholderText("主播名（缺省读配置默认）")
        self.video_edit = LineEdit(box)
        self.video_edit.setPlaceholderText("源视频（可选，取时长）")
        self.gen_btn = PrimaryPushButton("生成发布素材", box)
        self.gen_btn.clicked.connect(self._generate)
        for w in (label_row("字幕", self.srt_edit, browse),
                  label_row("游戏名", self.game_edit),
                  label_row("主播名", self.streamer_edit),
                  label_row("源视频", self.video_edit),
                  row(self.gen_btn, None)):
            box.layout().addWidget(w) if box.layout() else None
        self.log = LogView("素材日志", 160, self)
        try:
            lay.addWidget(box)
            lay.addWidget(self.log)
        except Exception:
            pass

    def _browse(self):
        p, _ = QFileDialog.getOpenFileName(self, "选择字幕", "",
                                           "字幕 (*.srt *.ass);;所有文件 (*)")
        if p:
            self.srt_edit.setText(p)

    def _generate(self):
        srt = self.srt_edit.text().strip()
        if not srt:
            self.log.line("请先选择字幕", "err")
            return
        params = dict(srt=srt, video=self.video_edit.text().strip(),
                      game=self.game_edit.text().strip(),
                      streamer=self.streamer_edit.text().strip())
        self.gen_btn.setEnabled(False)

        def _work():
            try:
                res = pm.generate_material(log=lambda m: self.log.line(m), **params)
                if res.get("ok"):
                    self.log.line("✓ 标题：" + res["title"], "ok")
                    self.log.line("✓ 素材目录：" + res["folder"], "ok")
                else:
                    self.log.line("✗ " + str(res.get("error")), "err")
            except Exception as e:
                self.log.line("✗ 异常：" + str(e), "err")
            finally:
                self.gen_btn.setEnabled(True)

        threading.Thread(target=_work, daemon=True).start()


def build_page(app, parent=None):
    return PublishPage(app, parent)