# -*- coding: utf-8 -*-
"""流水线页（2026-11-15 功能解耦阶段③：从 video_toolbox_qt.py 拆出，逐字同源）。

* 后端：引擎侧 pipeline 模块（目录感知 + 阶段状态机，STAGES 自带 optional 降级）；
* 消息自订阅（bus「pipe_state」），不再依赖入口 _dispatch；pipe_ready 属壳层
  编排（MainWindow 装配 registry/watcher），仍留在入口。
"""
import os

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from vt_fluent import (BodyLabel, CaptionLabel, FluentIcon as FIF, InfoBar,
                       InfoBarPosition, LineEdit, MessageBox,
                       PrimaryPushButton, PushButton, SimpleCardWidget,
                       SpinBox, StrongBodyLabel, SwitchButton, ToolButton)

import video_toolbox as engine
import pipeline as pl

from vt_app.widgets import (LogView, TabPage, card, expand_h, fit_caption,
                            fit_spin, row, tab_caption)


class _StageDot(ToolButton):
    """阶段圆点：灰=等待 / 蓝=运行 / 绿=完成 / 红=失败 / 斜杠=跳过。

    点击跳到对应功能页（点的是"哪一步出问题了"的人，下一步自然是去那页看）。
    """

    COLORS = {"waiting": "#6E6E6E", "ready": "#9AA3AD", "running": "#2E7FD6",
              "done": "#2E9E5B", "failed": "#D64545", "skipped": "#6E6E6E"}
    LABELS = {"waiting": "等待", "ready": "待执行", "running": "进行中",
              "done": "已完成", "failed": "失败", "skipped": "已跳过"}

    def __init__(self, stage_key, label, parent=None):
        super().__init__(parent)
        self.stage_key = stage_key
        self.label = label
        self.state = "waiting"
        self.detail = ""
        self.setFixedSize(20, 20)
        self.setCursor(Qt.PointingHandCursor)
        self.setText("")
        self._tip()

    def _tip(self):
        tip = f"{self.label}：{self.LABELS.get(self.state, self.state)}"
        if self.detail:
            tip += f"\n{self.detail[:200]}"
        tip += "\n（点击跳到对应功能页）"
        self.setToolTip(tip)

    def set_stage(self, state, detail=""):
        self.state = state or "waiting"
        self.detail = str(detail or "")
        self._tip()
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        color = QColor(self.COLORS.get(self.state, "#6E6E6E"))
        r = QRectF(2.5, 2.5, self.width() - 5, self.height() - 5)
        if self.state in ("waiting", "ready", "skipped"):
            p.setPen(QPen(color, 2))
            p.setBrush(Qt.NoBrush)
        else:
            p.setPen(Qt.NoPen)
            p.setBrush(color)
        p.drawEllipse(r)
        if self.state == "skipped":      # 跳过：斜杠
            p.setPen(QPen(color, 2))
            p.drawLine(r.topRight(), r.bottomLeft())
        p.end()


class _JobCard(SimpleCardWidget):
    """单个视频的流水线卡片：名称 + 状态 + 阶段圆点（按任务链动态）+ 重试。"""

    def __init__(self, job, on_jump, on_retry, parent=None):
        super().__init__(parent)
        self.job_id = job.get("id") or ""
        self.on_jump = on_jump
        self.on_retry = on_retry
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 12)
        lay.setSpacing(6)
        self.name_label = StrongBodyLabel(job.get("name") or "(未命名)", self)
        self.status_label = BodyLabel(job.get("status") or "", self)
        self.status_label.setTextColor("#8a8a8a", "#9a9a9a")
        lay.addWidget(row(self.name_label, None, self.status_label))
        self.dots_holder = QWidget(self)
        self.dots_lay = QHBoxLayout(self.dots_holder)
        self.dots_lay.setContentsMargins(0, 0, 0, 0)
        self.dots_lay.setSpacing(10)
        self.dots = {}
        self._chain = tuple(job.get("chain") or ())
        for key in self._chain:
            dot = _StageDot(key, pl.STAGE_LABELS.get(key, key), self)
            dot.clicked.connect(lambda _c=False, k=key: self._jump(k))
            self.dots[key] = dot
            self.dots_lay.addWidget(dot)
        self.dots_lay.addStretch(1)
        self.retry_btn = PushButton(FIF.UPDATE, "执行", self)
        self.retry_btn.setFixedHeight(26)
        self.retry_btn.clicked.connect(self._retry)
        self.dots_lay.addWidget(self.retry_btn)
        lay.addWidget(self.dots_holder)
        self.update_job(job)

    def _jump(self, key):
        if callable(self.on_jump):
            self.on_jump(self.job_id, key)

    def _retry(self):
        if callable(self.on_retry):
            self.on_retry(self.job_id)

    def update_job(self, job):
        self.job_id = job.get("id") or self.job_id
        chain = tuple(job.get("chain") or ())
        if chain != self._chain:          # 链变了（旧状态迁移）→ 重建圆点
            self._chain = chain
            for dot in self.dots.values():
                self.dots_lay.removeWidget(dot)
                dot.setParent(None)
                dot.deleteLater()
            self.dots = {}
            for key in chain:
                dot = _StageDot(key, pl.STAGE_LABELS.get(key, key), self)
                dot.clicked.connect(lambda _c=False, k=key: self._jump(k))
                self.dots[key] = dot
                self.dots_lay.insertWidget(self.dots_lay.count() - 2, dot)
        stages = job.get("stages") or {}
        failed = False
        for key, dot in self.dots.items():
            st = stages.get(key) or {}
            state = st.get("state") or "waiting"
            dot.set_stage(state, st.get("error") or st.get("reason") or "")
            if state == "failed":
                failed = True
        self.status_label.setText(job.get("status") or "")
        self.name_label.setText(job.get("name") or "(未命名)")
        # 失败 → 重试；其余（含存量任务）→ 执行
        self.retry_btn.setText("重试" if failed else "执行")
        self.retry_btn.setVisible(True)


class PipelinePage(QWidget):
    """流水线页：订阅引擎侧 Pipeline 的状态，只读展示 + 开关/重试。

    线程边界：pipeline 的回调来自后台线程，这里一律不碰控件，只往 app.q 投
    消息，等主线程 bus 泵出再更新界面（与其余页面同一套模型）。
    """

    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self.pipe = None
        self.cards = {}
        self.setObjectName("PipelinePage")

        # 功能解耦阶段③：消息自订阅（原入口 _dispatch 的 pipe_state 分支）。
        # 惰性外壳未建真身时没有订阅者，消息经 fallback 旧表 _lazy_real 判空
        # 跳过——与旧行为一致（不为投一条日志而建页）。
        app.bus.subscribe("pipe_state", self._on_bus_message)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.shell = TabPage(self)
        outer.addWidget(self.shell)
        vbox = self.shell.content_lay
        vbox.addWidget(tab_caption(
            "填入链接即可自动完成：下载（原片/字幕/封面/信息）→ 谷歌翻译 → "
            "字幕校准 → 二次校准 → 成品输出；下载目录里新出现的视频也会自动接管。"
            "成品不另建目录，直接增量写回视频所在的原文件夹", self))

        # ---- 新建任务（链接驱动） ----
        self.link_edit = LineEdit(self)
        expand_h(self.link_edit, 220)
        self.link_edit.setPlaceholderText(
            "粘贴视频链接（YouTube/B站等），回车或点「添加任务」")
        self.link_edit.returnPressed.connect(self._add_link)
        self.add_btn = PrimaryPushButton(FIF.DOWNLOAD, "添加任务", self)
        self.add_btn.clicked.connect(self._add_link)
        box, lay = card("新建任务", None)
        lay.addWidget(row(self.link_edit, self.add_btn, None))
        vbox.addWidget(box)

        # ---- 自动开关与操作 ----
        self.auto_switch = SwitchButton(self)
        self.auto_switch.setChecked(True)
        self.auto_switch.checkedChanged.connect(self._on_auto)
        self.scan_btn = PushButton(FIF.SYNC, "立即扫描", self)
        self.scan_btn.clicked.connect(self._scan)
        self.retry_btn = PushButton(FIF.UPDATE, "重试失败项", self)
        self.retry_btn.clicked.connect(self._retry_all)
        self.open_btn = PushButton(FIF.FOLDER, "打开下载目录", self)
        self.open_btn.clicked.connect(self._open_download_dir)
        self.clear_btn = PushButton(FIF.BROOM, "清空任务进度", self)
        self.clear_btn.clicked.connect(self._clear_jobs)
        #: 并发任务数（多个 job 同时推进；单个 job 内部仍严格按阶段顺序跑）
        self.workers_spin = SpinBox(self)
        self.workers_spin.setRange(pl.MIN_WORKERS, pl.MAX_WORKERS)
        self.workers_spin.setValue(pl.DEFAULT_WORKERS)
        fit_spin(self.workers_spin, 150)
        self.workers_spin.valueChanged.connect(self._on_workers)
        box, lay = card("自动流水线")
        lay.addWidget(row(BodyLabel("自动执行后续阶段", self), self.auto_switch, None))
        lay.addWidget(row(BodyLabel("并发任务数", self), self.workers_spin,
                          fit_caption(CaptionLabel(
                              "多个任务同时推进；单个任务内部仍按阶段顺序执行", self)),
                          None))
        lay.addWidget(row(self.scan_btn, self.retry_btn, self.open_btn, None))
        vbox.addWidget(box)

        self.list_box, self.list_lay = card("任务进度")
        # 清空按钮跟着「任务进度」走：清掉的是这一块里的历史任务卡片
        self.list_lay.insertWidget(1, row(None, self.clear_btn))
        self.empty = fit_caption(CaptionLabel("暂无任务：下载目录里出现视频后会自动建卡", self))
        self.list_lay.addWidget(self.empty)
        vbox.addWidget(self.list_box)

        self.log = LogView("流水线日志", 130, self)
        vbox.addWidget(self.log)
        vbox.addStretch(1)

    # ---------- 消息 ----------
    def _on_bus_message(self, msg):
        """bus「pipe_state」消息（原入口 _dispatch 分支，语义逐字一致）。"""
        self.on_state(msg[1])

    # ---------- 绑定 ----------
    def attach(self, pipe):
        """接上引擎侧 Pipeline（主线程调用）。"""
        self.pipe = pipe
        try:
            self.auto_switch.blockSignals(True)
            self.auto_switch.setChecked(bool(pipe.auto))
            self.auto_switch.blockSignals(False)
        except Exception:  # noqa: BLE001
            pass
        try:
            self._sync_workers_spin(getattr(pipe, "max_workers",
                                            pl.DEFAULT_WORKERS))
        except Exception:  # noqa: BLE001
            pass
        self._refresh()

    # ---------- 状态更新（主线程） ----------
    def on_state(self, payload):
        """主线程消息入口（bus 转进来）。"""
        if not isinstance(payload, dict):
            return
        kind = payload.get("type")
        if kind == "log":
            self.log.line(payload.get("text", ""), "dim")
        elif kind == "jobs":
            self._rebuild(payload.get("jobs") or [])
            auto = payload.get("auto")
            if auto is not None:
                self.auto_switch.blockSignals(True)
                self.auto_switch.setChecked(bool(auto))
                self.auto_switch.blockSignals(False)
            workers = payload.get("workers")
            if workers is not None:
                self._sync_workers_spin(workers)
        elif kind == "auto":
            self.auto_switch.blockSignals(True)
            self.auto_switch.setChecked(bool(payload.get("auto")))
            self.auto_switch.blockSignals(False)
        elif kind == "workers":
            self._sync_workers_spin(payload.get("workers"))

    def _sync_workers_spin(self, value):
        try:
            value = int(value)
        except (TypeError, ValueError):
            return
        self.workers_spin.blockSignals(True)
        self.workers_spin.setValue(value)
        self.workers_spin.blockSignals(False)

    def _refresh(self):
        if self.pipe is not None:
            self._rebuild(self.pipe.job_list())

    def _rebuild(self, jobs):
        self.empty.setVisible(not jobs)
        seen = set()
        for job in jobs:
            jid = job.get("id") or ""
            if not jid:
                continue
            seen.add(jid)
            card_w = self.cards.get(jid)
            if card_w is None:
                card_w = _JobCard(job, self._jump, self._retry, self.list_box)
                self.list_lay.addWidget(card_w)
                self.cards[jid] = card_w
            else:
                card_w.update_job(job)
        for jid in list(self.cards):
            if jid not in seen:
                w = self.cards.pop(jid)
                self.list_lay.removeWidget(w)
                w.setParent(None)
                w.deleteLater()

    # ---------- 操作 ----------
    def _add_link(self):
        url = engine.extract_url(self.link_edit.text()) or self.link_edit.text().strip()
        if self.pipe is None:
            InfoBar.warning("提示", "流水线尚未启动，请稍候", duration=3000,
                            position=InfoBarPosition.BOTTOM_RIGHT, parent=self)
            return
        jid, msg = self.pipe.add_link(url)
        if jid:
            self.link_edit.clear()
            self.log.line(f"[任务] {msg}（{url if len(url) <= 60 else url[:60] + '...'}）", "ok")
        else:
            InfoBar.warning("提示", msg, duration=3000,
                            position=InfoBarPosition.BOTTOM_RIGHT, parent=self)

    def _jump(self, job_id, stage_key):
        key = pl.STAGE_JUMP.get(stage_key, "download")
        try:
            page = self.app.page_by_key(key)
            if page is not None:
                self.app.switchTo(page)
        except Exception:  # noqa: BLE001
            pass

    def _retry(self, job_id, _stage=None):
        if self.pipe is not None:
            self.pipe.retry(job_id)

    def _retry_all(self):
        if self.pipe is None:
            return
        n = 0
        for job in self.pipe.job_list():
            stages = job.get("stages") or {}
            stalled = any((s or {}).get("state") in (pl.FAILED, pl.WAITING)
                          for s in stages.values())
            if stalled and not job.get("bootstrap"):
                self.pipe.retry(job.get("id") or "")
                n += 1
        self.log.line(f"[重试] 已重新排队 {n} 个任务" if n else "[重试] 没有停滞的任务",
                      "ok" if n else "dim")

    def _scan(self):
        if self.pipe is not None:
            self.pipe.manual_evaluate()
            self.log.line("[扫描] 已触发一次目录评估", "dim")

    def _clear_jobs(self):
        """清空「任务进度」：把历史任务卡片全部清掉（含已完成 / 失败 / 存量）。

        执行中的阶段无法安全中断，会等它跑完再连同卡片一起消失；被清掉的
        任务会被记下来，目录里同一份视频不会下一轮评估又冒出来（换过文件
        则视为新任务，正常建卡）。
        """
        if self.pipe is None:
            InfoBar.warning("提示", "流水线尚未启动，请稍候", duration=3000,
                            position=InfoBarPosition.BOTTOM_RIGHT, parent=self)
            return
        jobs = self.pipe.job_list()
        if not jobs:
            self.log.line("[清空] 当前没有任务", "dim")
            InfoBar.info("提示", "当前没有可清理的任务", duration=2500,
                         position=InfoBarPosition.BOTTOM_RIGHT, parent=self)
            return
        running = 0
        for job in jobs:
            for st in (job.get("stages") or {}).values():
                if (st or {}).get("state") == pl.RUNNING:
                    running += 1
                    break
        extra = (f"（{running} 个正在执行，跑完即移除）" if running else "")
        box = MessageBox(
            "清空任务进度",
            f"确定清空全部 {len(jobs)} 个任务吗？{extra}"
            "只清理进度记录，不删除任何已下载 / 已生成的文件；"
            "清空后这批历史视频不会自动重新入列，重新下载或替换文件后会正常出现。",
            self)
        box.yesButton.setText("清空")
        box.cancelButton.setText("取消")
        if not box.exec():
            return
        now, deferred = self.pipe.clear_jobs()
        self.log.line(f"[清空] 已清理 {now} 个任务"
                      + (f"，{deferred} 个执行中（跑完即移除）" if deferred else ""),
                      "ok")
        self._refresh()

    def _on_workers(self, value):
        if self.pipe is not None:
            self.pipe.set_workers(value)

    def _open_download_dir(self):
        """打开下载根目录：成品已直接写回各视频的原文件夹（v1.17.1）。"""
        d = engine.get_saved_download_dir()
        if d and os.path.isdir(d):
            engine.open_folder(d)
        else:
            self.log.line("[流水线] 下载目录不存在，请先在「下载」页设置", "dim")

    def _on_auto(self, checked):
        if self.pipe is not None:
            self.pipe.set_auto(bool(checked))
            self.log.line(f"[开关] 自动流水线：{'开' if checked else '关'}", "dim")


def build_page(app, parent=None):
    """注册表 GuiSpec.builder 入口（pipeline 功能页）。"""
    return PipelinePage(app, parent)