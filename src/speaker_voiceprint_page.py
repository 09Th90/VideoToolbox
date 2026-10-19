#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# @version 2.4.0
"""主播声纹 · 界面组件（v1.18.0）
====================================================================
两个组件，供 `video_toolbox.py::vc_transcribe_ui_patch()` 挂进引擎界面：

  ① `VoiceprintEnrollCard` —— **声纹录入卡**，挂在「语音转录」页的空白区
     （引擎 `TranscriptionSettingCard.empty_widget`）。列出已录入声纹，并
     提供「选源文件 + 自动选段（默认）/ 起点 + 时长 + 名字 → 开始录入」的表单；
     提特征要跑模型，所以走后台线程，日志经信号回主线程。
     v2.2.0 起默认走**自动选段**（`SV.enroll_auto`：全片扫描 → 主说话人簇 →
     频谱门控排 BGM → 时间分箱取 12 段 → 录入后素材体检 + 库内混淆检查），
     体检与混淆告警直接回显在状态栏（琥珀色）。

  ② `VoiceprintPicker` —— **声纹多选器**，挂在「转录设置」弹窗
     （引擎 `TranscriptionSettingDialog`）。勾选要保留的声纹，**可多选**
     （并集语义：与其中任意一个够像就算主播），选择即时落盘。

为什么单独成模块：主文件 `video_toolbox_qt.py` 里的页面共享 `ScrollPage` /
`card()`，页面独立成模块会反向 import 主文件形成循环导入（`auto_vision_page`
也是因此单独成模块）。本模块只依赖 `ui_theme` / `qfluentwidgets` /
`speaker_voiceprint`，主文件里只留两处挂载代码。

⚠ 本模块**不 import `video_toolbox`**：它会被引擎的 UI 补丁调用，而补丁本身
   就跑在 `video_toolbox` 里，反向 import 会造成加载期循环。
"""

import os

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QVBoxLayout, QWidget

from vt_fluent import (BodyLabel, CaptionLabel, CheckBox, LineEdit,
                            PrimaryPushButton, ProgressBar, PushButton,
                            SpinBox, StrongBodyLabel, ToolButton,
                            FluentIcon as FIF)

import speaker_voiceprint as SV

#: 常见音视频后缀（文件对话框过滤用）
MEDIA_FILTER = ("音视频文件 (*.mp4 *.mkv *.mov *.flv *.webm *.ts *.m4v *.avi "
                "*.mp3 *.m4a *.aac *.wav *.flac *.ogg *.opus);;所有文件 (*.*)")


# ---------------------------------------------------------------------- #
# 录入后台线程
# ---------------------------------------------------------------------- #
class EnrollWorker(QThread):
    """后台跑声纹录入（提特征要跑 ONNX 模型，别卡住界面）。

    ⚠ 属性名必须带下划线：`QThread` 自己有 `start()` / `wait()` 等方法，
    直接写 `self.start = 0.0` 会**把 start() 覆盖成浮点数**，之后
    `self._worker.start()` 就报 `'float' object is not callable`。

    `auto=True` 走 `SV.enroll_auto`（全片扫描 + 频谱门控 + 分箱拼接 + 录入后
    素材体检），比手选一段稳得多，代价是慢（十几分钟的素材约 1~2 分钟），所以
    阶段进度经 `progress` 信号回显——没有反馈用户会以为卡死。
    录入结果里的 `warnings`（素材体检 / 库内混淆）一律拼进 done 的文本，
    界面不再另开一个告警区。
    """

    done = Signal(bool, str)
    progress = Signal(str)

    def __init__(self, src, start, dur, name, append=False, auto=False,
                 parent=None):
        super().__init__(parent)
        self._src, self._start, self._dur, self._name = src, start, dur, name
        self._append = bool(append)
        self._auto = bool(auto)

    def run(self):
        try:
            if self._auto:
                r = SV.enroll_auto(self._src, self._name, append=self._append,
                                   progress=lambda m: self.progress.emit(str(m)))
                msg = ("已追加到「%s」：现共 %d 个片段 / %.1f 秒"
                       % (r["name"], r["clips"], r["seconds"])
                       if r.get("appended") else
                       "已录入「%s」：自动选段 %d 片段 / %.1f 秒人声"
                       % (r["name"], r["clips"], r["seconds"]))
                q = r.get("quality") or {}
                if q.get("verdict"):
                    msg += "（素材体检：%s）" % SV.verdict_text(q["verdict"])
            else:
                r = SV.enroll(self._src, self._start, self._dur, self._name,
                              append=self._append)
                msg = ("已追加到「%s」：现共 %d 个片段"
                       % (r["name"], r["clips"]) if r.get("appended") else
                       "已录入「%s」：%.1f 秒人声" % (r["name"], r["seconds"]))
                # 手工录入也查库内混淆：纯余弦、不解码音频，成本可忽略
                try:
                    r["warnings"] = SV.format_confusion(SV.check_confusion(
                        SV.load_template(self._name), skip=self._name))
                except SV.VoiceprintError:
                    r["warnings"] = []
            warn = [str(x) for x in (r.get("warnings") or [])]
            if warn:
                msg += "\n⚠ " + "\n⚠ ".join(warn)
            self.done.emit(True, msg)
        except SV.VoiceprintError as e:
            self.done.emit(False, str(e))
        except Exception as e:  # noqa: BLE001
            self.done.emit(False, "录入失败：%s" % e)


class ModelDownloadWorker(QThread):
    """后台下载声纹模型（约 27MB，直连失败自动切 gh-proxy 镜像 / 内置代理）。"""

    progress = Signal(int, int)      # done, total（total 可能为 0 = 未知）
    done = Signal(bool, str)

    def run(self):
        try:
            p = SV.download_model(
                progress=lambda d, t: self.progress.emit(int(d), int(t)))
            self.done.emit(True, "模型已就绪：%s" % os.path.basename(p))
        except SV.VoiceprintError as e:
            self.done.emit(False, str(e))
        except Exception as e:  # noqa: BLE001
            self.done.emit(False, "下载失败：%s" % e)


# ---------------------------------------------------------------------- #
# ① 声纹录入卡（语音转录页空白区）
# ---------------------------------------------------------------------- #
class VoiceprintEnrollCard(QWidget):
    """声纹录入卡：列已录入 + 录入新声纹。"""

    #: 声纹增删后发出，供多选器刷新
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker = None
        self._dl_worker = None
        self._rows = []
        self._build()
        self.refresh()

    # ---------------- UI ----------------
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        head = QHBoxLayout()
        head.setSpacing(8)
        title = StrongBodyLabel("主播声纹", self)
        head.addWidget(title)
        hint = CaptionLabel("录入主播的声音，转录后可只保留主播的字幕", self)
        hint.setStyleSheet("color: #8a8a8a;")
        head.addWidget(hint)
        head.addStretch(1)
        root.addLayout(head)

        # 模型缺失时的提示 + 一键下载（非阻塞：仍允许看列表）
        self.model_row = QWidget(self)
        mrow = QHBoxLayout(self.model_row)
        mrow.setContentsMargins(0, 0, 0, 0)
        mrow.setSpacing(8)
        self.model_tip = CaptionLabel("", self.model_row)
        self.model_tip.setWordWrap(True)
        self.model_tip.setStyleSheet("color: #b06a00;")
        mrow.addWidget(self.model_tip, 1)
        self.btn_model = PushButton("下载模型", self.model_row)
        self.btn_model.clicked.connect(self._do_download_model)
        mrow.addWidget(self.btn_model)
        root.addWidget(self.model_row)

        self.model_bar = ProgressBar(self)
        self.model_bar.setVisible(False)
        root.addWidget(self.model_bar)
        self._refresh_model_state()

        # 已录入列表容器
        self.list_box = QWidget(self)
        self.list_lay = QVBoxLayout(self.list_box)
        self.list_lay.setContentsMargins(0, 0, 0, 0)
        self.list_lay.setSpacing(4)
        root.addWidget(self.list_box)
        # v2.1.0：按用户要求**隐藏「已录入声纹」历史列表**——历史卡片只增
        # 不减（删除入口在此），录多了把任务创建/首页拉得老长，视觉噪音大。
        # 隐藏后 refresh() 仍照常构建行（删改逻辑原样保留，数据不动），
        # 只是容器不显示；声纹的选择走转录设置里的「主播声纹（可多选）」。
        self.list_box.hide()

        # 录入表单
        form = QHBoxLayout()
        form.setSpacing(8)
        form.addWidget(CaptionLabel("源文件", self))
        self.src_edit = LineEdit(self)
        self.src_edit.setPlaceholderText(
            "拖入或选择含主播人声的音视频（默认自动选段，整段丢进来即可）")
        self.src_edit.setClearButtonEnabled(True)
        self.src_edit.setMinimumWidth(240)
        form.addWidget(self.src_edit, 1)
        btn_pick = PushButton("浏览", self)
        btn_pick.clicked.connect(self._pick_file)
        form.addWidget(btn_pick)
        root.addLayout(form)

        form2 = QHBoxLayout()
        form2.setSpacing(6)
        # v2.2.0：自动选段默认开着。手工挑一段的问题是实测出来的——挑不出 BGM
        # 之外的干净时刻、只覆盖视频开头、多人素材容易把嘉宾录进去；自动选段
        # 全片扫描后按「主说话人 + 频谱门控 + 时间分箱」取 12 段，录完还当场
        # 体检素材并查库内混淆。代价是慢（十几分钟的素材 1~2 分钟），所以进度
        # 经 worker 的 progress 信号回显在状态栏。
        self.auto_box = CheckBox("自动选段（推荐）", self)
        self.auto_box.setChecked(True)
        self.auto_box.setToolTip(
            "勾选（默认）：全片扫描 → 只取主说话人 → 频谱门控排掉 BGM 响的时段 →\n"
            "按时间分箱取 %d 段拼成模板，录完自动做素材体检与库内混淆检查。\n"
            "更稳，但更慢：十几分钟的素材约 1~2 分钟，进度显示在下方状态栏。\n"
            "取消勾选：改用右边的「起点 / 时长」手工指定一段（快，适合已经\n"
            "知道哪一段干净的情况）。" % SV.AUTO_CLIPS)
        self.auto_box.stateChanged.connect(self._on_auto_toggled)
        form2.addWidget(self.auto_box)
        form2.addWidget(CaptionLabel("起点", self))
        self.start_spin = SpinBox(self)
        self.start_spin.setRange(0, 100000)
        self.start_spin.setSuffix(" 秒")
        self.start_spin.setValue(0)
        form2.addWidget(self.start_spin)
        form2.addWidget(CaptionLabel("时长", self))
        self.dur_spin = SpinBox(self)
        self.dur_spin.setRange(2, 600)
        self.dur_spin.setSuffix(" 秒")
        self.dur_spin.setValue(20)
        form2.addWidget(self.dur_spin)
        form2.addWidget(CaptionLabel("名称", self))
        self.name_edit = LineEdit(self)
        self.name_edit.setPlaceholderText("主播")
        self.name_edit.setText("主播")
        self.name_edit.setMinimumWidth(120)
        form2.addWidget(self.name_edit)
        self.append_box = CheckBox("追加到已有同名声纹", self)
        self.append_box.setToolTip("勾选：在已有声纹上继续添加该主播的声音（扩充校准）\n"
                                   "不勾：同名覆盖重录")
        form2.addWidget(self.append_box)
        self.btn_enroll = PrimaryPushButton("开始录入", self)
        self.btn_enroll.clicked.connect(self._do_enroll)
        form2.addWidget(self.btn_enroll)
        form2.addStretch(1)
        root.addLayout(form2)
        self._on_auto_toggled()          # 初始：自动选段开着 -> 起点/时长禁用

        self.status = CaptionLabel("", self)
        self.status.setWordWrap(True)
        self.status.setStyleSheet("color: #8a8a8a;")
        root.addWidget(self.status)
        root.addStretch(1)

    # ---------------- 列表 ----------------
    def refresh(self):
        # ⚠ setParent(None) 只把控件摘成顶层窗口（仍隐藏驻留），必须再
        #   deleteLater()——反复刷新会攒下一堆看不见的孤儿窗口占内存。
        #   与主界面其余动态列表的处理保持一致（setParent(None) + deleteLater()）。
        for w in self._rows:
            w.setParent(None)
            w.deleteLater()
        self._rows = []
        names = SV.list_templates()
        if not names:
            lab = CaptionLabel("还没有录入任何声纹", self.list_box)
            lab.setStyleSheet("color: #8a8a8a;")
            self.list_lay.addWidget(lab)
            self._rows.append(lab)
            return
        for n in names:
            self.list_lay.addWidget(self._make_row(n))

    def _make_row(self, name):
        row = QWidget(self.list_box)
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        try:
            t = SV.load_template(name)
            meta = []
            if t.get("seconds"):
                meta.append("%.1f 秒" % float(t["seconds"]))
            if int(t.get("clips") or 1) > 1:
                meta.append("%d 片段" % int(t["clips"]))
            if t.get("sources"):
                meta.append("%d 来源" % len(t["sources"]))
            if t.get("created"):
                meta.append(str(t["created"])[:16])
            if t.get("source"):
                meta.append(os.path.basename(str(t["source"]))[:28])
            info = "　".join(meta) or "—"
        except SV.VoiceprintError:
            info = "（读取失败）"

        lab = BodyLabel(name, row)
        lay.addWidget(lab)
        cap = CaptionLabel(info, row)
        cap.setStyleSheet("color: #8a8a8a;")
        lay.addWidget(cap)
        lay.addStretch(1)

        btn = ToolButton(FIF.DELETE, row)
        btn.setToolTip("删除这个声纹")
        btn.clicked.connect(lambda _=False, n=name: self._do_delete(n))
        lay.addWidget(btn)
        self._rows.append(row)
        return row

    # ---------------- 动作 ----------------
    def _refresh_model_state(self):
        """按模型是否就位切换「下载模型」提示区的显隐。返回是否已就位。"""
        ok = SV.model_present()
        self.model_row.setVisible(not ok)
        self.model_bar.setVisible(False)
        if not ok:
            self.model_tip.setText(
                "尚未下载声纹模型（约 27MB）。点「下载模型」即可"
                "（存到 %s，不占系统盘）" % SV.MODEL_DIR)
        return ok

    def _do_download_model(self):
        if self._dl_worker is not None and self._dl_worker.isRunning():
            return
        self.btn_model.setEnabled(False)
        self.model_bar.setVisible(True)
        self.model_bar.setValue(0)
        self.model_tip.setText("正在下载声纹模型（约 27MB，失败会自动切换镜像 / 代理）…")
        self._dl_worker = ModelDownloadWorker(self)
        self._dl_worker.progress.connect(self._on_dl_progress)
        self._dl_worker.done.connect(self._on_dl_done)
        self._dl_worker.start()

    def _on_dl_progress(self, done, total):
        if total > 0:
            self.model_bar.setValue(int(done * 100 / total))
        else:
            self.model_bar.setValue(0)

    def _on_dl_done(self, ok, msg):
        self.btn_model.setEnabled(True)
        self.status.setText(msg)
        if ok and self._refresh_model_state():
            self.status.setText("声纹模型已就绪，可以开始录入了")

    def _pick_file(self):
        p, _ = QFileDialog.getOpenFileName(self, "选择音视频文件", "",
                                           MEDIA_FILTER)
        if p:
            self.src_edit.setText(p)

    def _do_delete(self, name):
        if SV.delete_template(name):
            self.status.setText("已删除声纹「%s」" % name)
            self.refresh()
            self.changed.emit()

    def _do_enroll(self):
        src = (self.src_edit.text() or "").strip().strip('"')
        if not src or not os.path.isfile(src):
            self.status.setText("请先选择一个存在的音视频文件")
            self.status.setStyleSheet("color: #8a8a8a;")   # 清掉上一次的告警色
            return
        if self._worker is not None and self._worker.isRunning():
            return
        name = (self.name_edit.text() or "").strip() or "主播"
        auto = self.auto_box.isChecked()
        self.btn_enroll.setEnabled(False)
        self.auto_box.setEnabled(False)
        self.status.setText("正在扫描全片、自动选段…（十几分钟的素材约 1~2 分钟）"
                            if auto else
                            "正在提取声纹…（首次会加载模型，约需数秒）")
        self._worker = EnrollWorker(src, float(self.start_spin.value()),
                                    float(self.dur_spin.value()), name,
                                    append=self.append_box.isChecked(),
                                    auto=auto, parent=self)
        self._worker.progress.connect(self._on_progress)
        self._worker.done.connect(self._on_enrolled)
        self._worker.start()

    def _on_auto_toggled(self, _state=0):
        """自动选段勾选状态 -> 起点/时长两个 spin 的可用性（互斥，避免误解）。"""
        auto = self.auto_box.isChecked()
        self.start_spin.setEnabled(not auto)
        self.dur_spin.setEnabled(not auto)

    def _on_progress(self, msg):
        # 录入进行中才刷进度：done 之后再来的迟到信号不该盖掉结果文本
        if self._worker is not None and self._worker.isRunning():
            self.status.setText(str(msg))

    def _on_enrolled(self, ok, msg):
        self.btn_enroll.setEnabled(True)
        self.auto_box.setEnabled(True)
        self.status.setText(msg)
        # 有告警就换成琥珀色（与「模型缺失」提示同色系）：素材体检/库内混淆
        # 的结论是用户该看见的，灰色小字容易被当成普通状态忽略掉
        self.status.setStyleSheet("color: #b06a00;" if "⚠" in str(msg)
                                  else "color: #8a8a8a;")
        if ok:
            self.refresh()
            self.changed.emit()


# ---------------------------------------------------------------------- #
# ② 声纹多选器（转录设置弹窗）
# ---------------------------------------------------------------------- #
class VoiceprintPicker(QWidget):
    """声纹多选器：勾选要保留的声纹（可多选，并集）。选择即时落盘。"""

    changed = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._boxes = []
        self._build()
        self.refresh()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)

        head = QHBoxLayout()
        head.setSpacing(8)
        head.addWidget(BodyLabel("主播声纹（可多选）", self))
        head.addStretch(1)
        btn_clear = ToolButton(FIF.CANCEL, self)
        btn_clear.setToolTip("全部取消（不做声纹筛选）")
        btn_clear.clicked.connect(self._clear)
        head.addWidget(btn_clear)
        btn_re = ToolButton(FIF.SYNC, self)
        btn_re.setToolTip("刷新列表")
        btn_re.clicked.connect(self.refresh)
        head.addWidget(btn_re)
        root.addLayout(head)

        self.hint = CaptionLabel("勾选要保留的声音；不勾选则不做筛选\n"
                                 "多选 = 并集：任一匹配即保留", self)
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet("color: #8a8a8a;")
        root.addWidget(self.hint)

        self.box_wrap = QWidget(self)
        self.box_lay = QVBoxLayout(self.box_wrap)
        self.box_lay.setContentsMargins(4, 0, 0, 0)
        self.box_lay.setSpacing(2)
        root.addWidget(self.box_wrap)

        self.status = CaptionLabel("", self)
        self.status.setWordWrap(True)
        self.status.setStyleSheet("color: #8a8a8a;")
        root.addWidget(self.status)

    def refresh(self):
        for w in self._boxes:
            w.setParent(None)
            w.deleteLater()
        self._boxes = []
        names = SV.list_templates()
        sel = set(SV.load_selection())
        if not names:
            lab = CaptionLabel("还没有录入声纹 —— 在「语音转录」页的"
                               "「主播声纹」里录入", self.box_wrap)
            lab.setWordWrap(True)
            lab.setStyleSheet("color: #8a8a8a;")
            self.box_lay.addWidget(lab)
            self._boxes.append(lab)
            self.status.setText("")
            return
        for n in names:
            try:
                t = SV.load_template(n)
                secs = t.get("seconds")
                text = "%s（%.1f 秒）" % (n, float(secs)) if secs else n
            except SV.VoiceprintError:
                text = n
            cb = CheckBox(text, self.box_wrap)
            # ⚠ 名字必须**原样挂**在控件上：显示文本是「名字（x.x 秒）」，
            #   靠 split("（") 反解名字在名字里本就含括号时会截错
            #   （例「主播（小明）」→ 取成「主播」→ save_selection 查无此人 →
            #   勾选被静默丢弃）。
            cb.vp_name = n
            cb.stateChanged.connect(self._on_toggle)
            # 回填勾选状态会触发 stateChanged → 逐个写盘（中间态会把名单写成
            # 只有前几项）。先屏蔽信号，填完再放开；最终名单由调用方落盘。
            cb.blockSignals(True)
            cb.setChecked(n in sel)
            cb.blockSignals(False)
            self.box_lay.addWidget(cb)
            self._boxes.append(cb)
        self.status.setText("已启用 %d 个" % len(SV.load_selection()))

    # ---------------- 动作 ----------------
    def selected(self):
        """当前勾选的声纹名列表（顺序 = 列表顺序）。

        名字取 `cb.vp_name`（录入时挂上的原值），**不反解显示文本**——
        显示文本带「（x.x 秒）」后缀，反解在名字含括号时会截错。
        """
        out = []
        for cb in self._boxes:
            if isinstance(cb, CheckBox) and cb.isChecked():
                out.append(getattr(cb, "vp_name", None) or cb.text())
        return out

    def _on_toggle(self, _state=0):
        keep = SV.save_selection(self.selected())
        self.status.setText("已启用 %d 个" % len(keep)
                            if keep else "未启用（不做声纹筛选）")
        self.changed.emit(keep)

    def _clear(self):
        for cb in self._boxes:
            if isinstance(cb, CheckBox) and cb.isChecked():
                cb.blockSignals(True)
                cb.setChecked(False)
                cb.blockSignals(False)
        SV.save_selection([])
        self.status.setText("未启用（不做声纹筛选）")
        self.changed.emit([])
