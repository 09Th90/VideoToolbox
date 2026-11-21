# -*- coding: utf-8 -*-
# @version 3.1.5
"""音画合并页（2026-11-15 功能解耦阶段③：从 video_toolbox_qt.py 拆出，逐字同源）。

* 只经 vt_app 基建 + engine 门面（merge_pair/scan_media/smart_pair 等）；
* 消息自订阅（bus「scan_done / mg_ / mvm_」），不再依赖入口 _dispatch；
* 容器页（视频处理）经注册表服务 ``merge.build_page`` 组装本板块，
  merge 功能缺失时该板块自动缺席，不影响下载/切片。
"""
import os
import threading

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemView, QFileDialog, QHBoxLayout,
                               QHeaderView, QSizePolicy, QStackedWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from vt_fluent import (BodyLabel, ComboBox, FluentIcon as FIF, InfoBar,
                       InfoBarPosition, LineEdit, PrimaryPushButton,
                       ProgressBar, PushButton, SegmentedWidget,
                       SwitchButton, TableWidget)

import video_toolbox as engine
import ui_theme

from vt_app.widgets import (LogView, TabPage, _MergeDropSlot, card,
                            label_row, row, srow, tab_caption)
from features._media import (AUDIO_EXTS, AUDIO_FILE_FILTER, SUB_FILE_FILTER,
                             SUBTITLE_EXTS, VIDEO_EXTS, VIDEO_FILE_FILTER)


class MergePage(QWidget):
    """音画合并：页内二级分段「自动配对 / 手动合并」。

    · 自动配对（原流程）：扫描目录 → 按文件名 + 时长自动配 视频 + m4a/weba +
      srt/ass → 批量合成。视频侧不止 mp4：mkv/webm/mov/m4v… 一律参与配对
      （v1.18.0；此前只 glob `*.mp4`，同名 webm + m4a 恒配不出对）；
    · 手动合并（v1.18.0 新增）：用户把任意视频、音频（+ 可选字幕）拖进来或点选，
      直接合成一个文件。音频编码由 ffprobe 实测决定 copy / 转 AAC，视频 copy
      失败自动改 H.264 重编码重试（实测救的是 VP8；vp9/av1 本就能 copy）。

    两条路互不干扰：各自独立的进度条、日志、输出设置；页级拖放只在「手动合并」
    子页生效，其余情形仍按主窗口的全局分派走（视频/音频进字幕编辑）。
    """

    ASS_MODES = {"烧录为硬字幕": "burn", "封装为 MKV": "mkv", "忽略": "ignore"}

    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self.setObjectName("MergePage")
        self.pairs = []
        self.mv_busy = False

        # 功能解耦阶段③：消息自订阅（原入口 _dispatch 的 scan_done/mg_*/mvm_* 分支）。
        app.bus.subscribe("scan_done", self._on_bus_message)
        app.bus.subscribe("mg_", self._on_bus_message)
        app.bus.subscribe("mvm_", self._on_bus_message)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # —— 页内二级分段：自动配对 / 手动合并 ——
        # v1.18.0：原「音画合并」只有自动配对一条路——必须先把文件凑成"同名 +
        # 时长一致"的目录才能合成。这里补上「手动合并」：用户把视频、音频直接
        # 拖进来就能合，不必先改名归档。两条路各自独立成子页、互不挤占。
        # 与「视频下载」页内一级分段同款：SegmentedWidget 每项固定 stretch=1，
        # 必须铺满整行，否则两个标签会被拉开大片空隙；边距只能加在外层容器上
        # （原因见 DownloadPage.__init__ 的长注释）。
        self.mode_seg = SegmentedWidget(self)
        self.mode_seg.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        seg_wrap = QWidget(self)
        seg_lay = QHBoxLayout(seg_wrap)
        seg_lay.setContentsMargins(24, 10, 24, 0)
        seg_lay.setSpacing(0)
        seg_lay.addWidget(self.mode_seg)
        outer.addWidget(seg_wrap)

        self.stack = QStackedWidget(self)
        outer.addWidget(self.stack, 1)

        # —— 子板块 A：自动配对（原有流程整体保留） ——
        self.shell = TabPage(self)
        self.stack.addWidget(self.shell)
        self.vbox = self.shell.content_lay
        self.vbox.setSpacing(12)
        self.vbox.addWidget(tab_caption(
            "自动配对 视频（mp4/mkv/webm/mov…）+ m4a/weba + srt/ass；"
            "m4a 直封，weba 转 AAC", self))

        self.in_edit = LineEdit(self)
        self.in_edit.setText(engine.DEFAULT_INPUT_DIR)
        in_browse = PushButton(FIF.FOLDER, "浏览…", self)
        in_browse.clicked.connect(lambda: self._browse(self.in_edit))
        self.out_edit = LineEdit(self)
        out_browse = PushButton(FIF.FOLDER, "浏览…", self)
        out_browse.clicked.connect(lambda: self._browse(self.out_edit))
        box, lay = card("输入 / 输出文件夹", "输出留空则默认写入「输入文件夹\合成结果」")
        lay.addWidget(label_row("输入文件夹", self.in_edit))
        lay.addWidget(in_browse, 0, Qt.AlignLeft)
        lay.addWidget(label_row("输出文件夹", self.out_edit))
        lay.addWidget(out_browse, 0, Qt.AlignLeft)
        self.vbox.addWidget(box)

        self.ass_combo = ComboBox(self)
        self.ass_combo.addItems(list(self.ASS_MODES))
        self.ass_combo.setCurrentIndex(0)
        self.force_switch = SwitchButton(self)
        self.scan_btn = PrimaryPushButton(FIF.SEARCH, "扫描配对", self)
        self.scan_btn.clicked.connect(self.scan)
        box, lay = card("配对选项")
        lay.addWidget(label_row("ASS 字幕处理", self.ass_combo))
        lay.addWidget(row(BodyLabel("同名但时长不一致也强制合成", self),
                          self.force_switch, None))
        lay.addWidget(row(None, self.scan_btn))
        self.vbox.addWidget(box)

        self.table = TableWidget(self)
        self.table.setBorderVisible(True)
        self.table.setBorderRadius(8)
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["视频", "音频", "字幕", "匹配", "时长差"])
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        # —— 鼠标选中：单击=单选，Ctrl+单击=加选/减选，Shift+单击=连选，
        #    Ctrl+A=全选，点空白处=清空（于是又回到"合成全部"）——
        # 选中项就是本次要合成的范围，未选中则保持原样"全部合成"。
        # ⚠️ selectionMode 必须**显式**给 ExtendedSelection：TableBase 只设了
        #    selectionBehavior=SelectRows，模式仍是 QTableView 的默认值，
        #    别指望它替我们记住"允许多选"。
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setCheckedColor(ui_theme.get_accent(), ui_theme.get_accent())
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        for i, w in enumerate((240, 240, 150, 80, 80)):
            self.table.setColumnWidth(i, w)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        # 选中区提示 + 全选 / 清除选择：多选靠 Ctrl/Shift 太隐蔽，给显式按钮。
        # 「清除选择」是必须有的——它把用户一键退回"未选中 = 全部合成"。
        self.sel_info = BodyLabel("", self)
        self.sel_all_btn = PushButton(FIF.ACCEPT, "全选", self)
        self.sel_all_btn.clicked.connect(self.table.selectAll)
        self.sel_clear_btn = PushButton(FIF.CANCEL, "清除选择", self)
        self.sel_clear_btn.clicked.connect(self._clear_row_selection)
        box, lay = card("配对结果",
                        "单击行选中，Ctrl/Shift 多选；未选中则「开始合成」= 全部")
        lay.addWidget(self.table)
        self.table.setMinimumHeight(200)
        lay.addWidget(row(self.sel_info, None, self.sel_all_btn, self.sel_clear_btn))
        self.vbox.addWidget(box)

        row3 = row(self.prog_bar(), None, self.merge_btn())
        self.vbox.addWidget(row3)
        # 初始提示依赖 sel_info / 两个按钮都已就位，放在最后初始化
        self._refresh_selection_ui()
        # 切深浅主题要重铺选中底色（alpha 两档不同），否则旧底色留在行上
        ui_theme.connect_theme(self, lambda v: v._apply_row_selection())
        self.log = LogView("合并日志", 120, self)
        self.vbox.addWidget(self.log)
        self.vbox.addStretch(1)

        # —— 子板块 B：手动合并（用户拖入自己的音视频） ——
        self.manual = TabPage(self)
        self.stack.addWidget(self.manual)
        mv = self.manual.content_lay
        mv.setSpacing(12)
        mv.addWidget(tab_caption(
            "把视频和音频拖进来（也可点击槽位选择），选好输出位置后点「开始合并」", self))

        self.mv_video = _MergeDropSlot(
            "视频（必填）", "拖入视频文件，或点击这里选择", VIDEO_EXTS,
            lambda: self._pick_into(self.mv_video, "选择视频文件",
                                    VIDEO_FILE_FILTER), self.manual)
        self.mv_audio = _MergeDropSlot(
            "音频（必填）", "拖入音频文件，或点击这里选择", AUDIO_EXTS,
            lambda: self._pick_into(self.mv_audio, "选择音频文件",
                                    AUDIO_FILE_FILTER), self.manual)
        self.mv_sub = _MergeDropSlot(
            "字幕（可选）", "拖入 srt / ass 字幕，或点击这里选择", SUBTITLE_EXTS,
            lambda: self._pick_into(self.mv_sub, "选择字幕文件",
                                    SUB_FILE_FILTER), self.manual)
        box, lay = card("拖入文件", "从资源管理器拖到任意槽位或本页空白处，自动按类型归位")
        lay.addWidget(self.mv_video)
        lay.addWidget(self.mv_audio)
        lay.addWidget(self.mv_sub)
        mv.addWidget(box)

        self.mv_ass_combo = ComboBox(self)
        self.mv_ass_combo.addItems(list(self.ASS_MODES))
        self.mv_ass_combo.setCurrentIndex(0)
        self.mv_out_edit = LineEdit(self)
        self.mv_out_edit.setPlaceholderText("留空则输出到视频所在文件夹")
        mv_out_browse = PushButton(FIF.FOLDER, "浏览…", self)
        mv_out_browse.clicked.connect(self._pick_out_dir)
        box, lay = card("合并选项",
                        "音频非 AAC 自动转码；视频装不进 mp4 时自动改用 H.264 重编码")
        lay.addWidget(label_row("ASS 字幕处理", self.mv_ass_combo))
        lay.addWidget(srow("输出文件夹", self.mv_out_edit))
        lay.addWidget(mv_out_browse, 0, Qt.AlignLeft)
        mv.addWidget(box)

        self.mv_progress = ProgressBar(self)
        self.mv_button = PrimaryPushButton(FIF.MEDIA, "开始合并", self)
        self.mv_button.clicked.connect(self.start_manual_merge)
        mv.addWidget(row(self.mv_progress, None, self.mv_button))
        self.mv_log = LogView("合并日志", 120, self)
        mv.addWidget(self.mv_log)
        mv.addStretch(1)

        # —— 分段联动 ——
        # ⚠️ qfluentwidgets 的 SegmentedWidget.setCurrentItem() **不会**触发
        #    onClick（DownloadPage.page_by_key 里也是设完分段再手动设一次
        #    stack 索引）。所以"当前是哪个子页"一律以 stack.currentIndex()
        #    为准，别去比 currentItem()——它返回的是 SegmentedItem 对象而非
        #    routeKey。
        self.mode_seg.addItem("auto", "自动配对",
                              onClick=lambda: self._switch_mode(0))
        self.mode_seg.addItem("manual", "手动合并",
                              onClick=lambda: self._switch_mode(1))
        self.mode_seg.setCurrentItem("auto")

        # —— 拖放：整页接收（仅「手动合并」子页生效） ——
        # 子控件一律关掉 acceptDrops，让文件拖放事件冒泡到本页统一按后缀归位。
        # QLineEdit / QTextEdit / 滚动视口默认都 acceptDrops，会把 file:// 字符串
        # 插进框里、或在日志区被就地吞掉，行为不一致（与 CalibPage 同思路）。
        self.setAcceptDrops(True)
        for area in (self.shell.area, self.manual.area):
            try:
                area.setAcceptDrops(False)
                area.viewport().setAcceptDrops(False)
            except Exception:  # noqa: BLE001
                pass
        for edit in (self.in_edit, self.out_edit, self.mv_out_edit):
            edit.setAcceptDrops(False)
        for lv in (self.log, self.mv_log):
            try:
                lv.text.setAcceptDrops(False)
            except Exception:  # noqa: BLE001
                pass

    # ---------- 消息 ----------
    def _on_bus_message(self, msg):
        """bus 消息（原入口 _dispatch 的 scan_done/mg_*/mvm_* 分支，语义逐字一致）。"""
        kind, args = msg[0], msg[1:]
        if kind == "scan_done":
            self.on_scan_done(*args)
        elif kind == "mg_log":
            self.log.line(args[0], "dim")
        elif kind == "mg_progress":
            self.progress.setValue(int(args[0]))
        elif kind == "mg_done":
            self.on_mg_done(args[0], args[1], args[2])
        elif kind == "mvm_log":
            self.mv_log.line(args[0], args[1] if len(args) > 1 else "dim")
        elif kind == "mvm_progress":
            self.mv_progress.setValue(int(args[0]))
        elif kind == "mvm_done":
            self.on_mvm_done(args[0], args[1])

    def prog_bar(self):
        self.progress = ProgressBar(self)
        return self.progress

    def _switch_mode(self, index):
        """切「自动配对(0) / 手动合并(1)」子页，并把分段状态对齐。"""
        self.stack.setCurrentIndex(index)
        try:
            self.mode_seg.setCurrentItem("auto" if index == 0 else "manual")
        except Exception:  # noqa: BLE001
            pass

    def merge_btn(self):
        self.merge_button = PrimaryPushButton(FIF.MEDIA, "开始合成", self)
        self.merge_button.clicked.connect(self.start_merge)
        return self.merge_button

    # ---------- 配对表：鼠标选中 → 决定「开始合成」的范围 ----------
    # v1.18.0：原先表格只能看不能选，「开始合成」永远合全部。可实际批量处理时
    # 常是"这 20 对里只补 3 对"，全量重来太浪费。于是加选中语义：
    #   有选中 → 只合成选中行；无选中 → 保持原样，全部合成。
    # 行的选中状态只存在表格里，pairs 列表不动（顺序与行号一一对应），
    # 所以重新扫描后必须清掉选择，否则旧行号会指向新数据。

    def selected_rows(self):
        """当前被选中的行号集合（升序）。空集合 = 未选中 = 合成全部。"""
        idx = self.table.selectedIndexes()
        return sorted({i.row() for i in idx})

    def _on_selection_changed(self):
        self._apply_row_selection()
        self._refresh_selection_ui()

    def _apply_row_selection(self):
        """给选中行铺一层淡主题色底，让"选中了"在浅色主题下也一眼可见。

        qfluentwidgets 的 delegate 只给选中行左边画一道 indicator（细条），
        底色 alpha=17 在白底上几乎看不出来；这里额外用 BackgroundRole 铺底。
        注意 BackgroundRole 一旦设上，delegate 会**跳过**自己的 hover/选中
        底色绘制（见 table_view.py 的 paint：先判 BackgroundRole），所以
        取消选择时必须把 role 显式清成无效值，不能只"换个颜色"。
        """
        sel = set(self.selected_rows())
        alpha = 46 if ui_theme.is_dark() else 26
        bg = QColor(ui_theme.get_accent())
        bg.setAlpha(alpha)
        for r in range(self.table.rowCount()):
            for c in range(self.table.columnCount()):
                item = self.table.item(r, c)
                if item is None:
                    continue
                if r in sel:
                    item.setBackground(bg)
                else:
                    # Qt6/PySide6 已移除 QVariant：None 即空值，效果等同旧 QVariant()
                    item.setData(Qt.BackgroundRole, None)
        self.table.viewport().update()

    def _refresh_selection_ui(self):
        """同步"已选 N 项"提示 + 全选/清除按钮可用性。"""
        total = self.table.rowCount()
        n = len(self.selected_rows())
        if total <= 0:
            self.sel_info.setText("尚未扫描配对")
        elif n:
            self.sel_info.setText(f"已选 {n} / {total} 项 —— 点「开始合成」只合成选中项")
        else:
            self.sel_info.setText(
                f"共 {total} 项，未选中 —— 点「开始合成」合成全部")
        self.sel_all_btn.setEnabled(total > 0)
        self.sel_clear_btn.setEnabled(n > 0)

    def _clear_row_selection(self):
        self.table.clearSelection()

    def merge_targets(self):
        """本次「开始合成」要处理哪些 pair —— 选中的语义全在这一个纯函数里。

        · 有选中 → 就合选中的那几行。**不再**按 match_type 二次过滤：用户
          亲手点了「仅同名」那行就是要合它，静默跳过只会让人以为功能没生效。
          匹配不够好的项由 start_merge 记一条日志告知，不阻断。
        · 无选中 → 老规矩：perfect / duration 才合，除非勾了强制合成。

        纯函数（不碰 UI、不起线程），自检可直接断言返回值。
        """
        picked = self.selected_rows()
        if picked:
            return [self.pairs[r] for r in picked if 0 <= r < len(self.pairs)]
        return [p for p in self.pairs
                if p[3] in ("perfect", "duration") or self.force_switch.isChecked()]

    def _browse(self, edit):
        d = QFileDialog.getExistingDirectory(self, "选择文件夹", edit.text() or engine.APP_DIR)
        if d:
            edit.setText(d)

    def set_busy(self, busy):
        self.scan_btn.setEnabled(not busy)
        self.merge_button.setEnabled(not busy)
        # 合成/扫描期间把选择入口一并锁住：worker 用的是启动瞬间抓到的行号
        # 快照，中途改选中会让屏幕上的高亮与实际合成范围对不上。
        self.table.setEnabled(not busy)
        self.sel_all_btn.setEnabled(not busy and self.table.rowCount() > 0)
        self.sel_clear_btn.setEnabled(not busy and bool(self.selected_rows()))

    def scan(self):
        in_dir = engine.clean_path(self.in_edit.text())
        if not os.path.isdir(in_dir):
            InfoBar.warning("提示", "输入文件夹不存在", duration=3000,
                            position=InfoBarPosition.BOTTOM_RIGHT, parent=self)
            return
        self.set_busy(True)
        self.log.line(f"[信息] 正在扫描: {in_dir}", "dim")
        threading.Thread(target=self._scan_worker, args=(in_dir,), daemon=True).start()

    def _scan_worker(self, in_dir):
        try:
            _, ffprobe = engine.ensure_ffmpeg()
            mp4s, m4as, webas, srts, asss = engine.scan_media(in_dir)
            pairs, rem_mp4, rem_m4a, rem_weba = engine.smart_pair(
                mp4s, m4as, webas, srts, asss, ffprobe)
            self.app.q.put(("scan_done", pairs, (rem_mp4, rem_m4a, rem_weba),
                            (len(mp4s), len(m4as), len(webas), len(srts), len(asss)), None))
        except Exception as e:
            self.app.q.put(("scan_done", None, None, None, str(e)))

    def on_scan_done(self, pairs, remaining, counts, err):
        self.set_busy(False)
        if err:
            self.log.line(f"[错误] 扫描失败: {err}", "err")
            return
        self.pairs = pairs or []
        self.table.clearSelection()      # 旧行号已失效，必须先清选中
        self.table.setRowCount(0)
        name = {"perfect": "完美", "duration": "时长", "name_only": "仅同名"}
        for p in self.pairs:
            mp4, audio, at, mt, diff, sub, st = p
            r = self.table.rowCount()
            self.table.insertRow(r)
            for c, text in enumerate((
                    os.path.basename(mp4), os.path.basename(audio),
                    os.path.basename(sub) if sub else "—",
                    name.get(mt, mt), f"{diff:.2f}s")):
                item = QTableWidgetItem(str(text))
                item.setToolTip(str(text))
                self.table.setItem(r, c, item)
        n_mp4, n_m4a, n_weba, n_srt, n_ass = counts
        self.log.line(f"[OK] 找到 {n_mp4} 个视频 / {n_m4a} 个 m4a / {n_weba} 个 weba / "
                      f"{n_srt} 个 srt / {n_ass} 个 ass，配对 {len(self.pairs)} 对", "ok")
        rem_mp4, rem_m4a, rem_weba = remaining
        if rem_mp4:
            self.log.line(f"[未匹配视频] {len(rem_mp4)} 个：" +
                          "、".join(os.path.basename(f) for f in rem_mp4), "dim")
        if rem_m4a or rem_weba:
            self.log.line(f"[未匹配音频] {len(rem_m4a) + len(rem_weba)} 个", "dim")
        # 填完行再刷一次提示：从"尚未扫描"变成"共 N 项，未选中"。
        # 只靠选中变化刷新是不够的——首扫时没有任何选中事件。
        self._refresh_selection_ui()

    def start_merge(self):
        if not self.pairs:
            InfoBar.warning("提示", "请先「扫描配对」", duration=3000,
                            position=InfoBarPosition.BOTTOM_RIGHT, parent=self)
            return
        in_dir = engine.clean_path(self.in_edit.text())
        out_dir = engine.clean_path(self.out_edit.text()) or os.path.join(in_dir, "合成结果")
        os.makedirs(out_dir, exist_ok=True)
        ass_mode = self.ASS_MODES.get(self.ass_combo.currentText(), "burn")
        # 有选中 → 只合成选中行；无选中 → 按匹配类型筛全部（见 merge_targets）
        to_merge = self.merge_targets()
        if not to_merge:
            InfoBar.warning("提示", "没有可合成的配对（可勾选强制合成）", duration=3000,
                            position=InfoBarPosition.BOTTOM_RIGHT, parent=self)
            return
        if self.selected_rows():
            weak = sum(1 for p in to_merge if p[3] not in ("perfect", "duration"))
            self.log.line(
                f"[选择] 只合成选中的 {len(to_merge)} 项"
                + (f"（其中 {weak} 项匹配不完美，仍按你的选择合成）" if weak else ""),
                "dim")
        self.set_busy(True)
        self.progress.setValue(0)
        threading.Thread(target=self._merge_worker,
                         args=(to_merge, out_dir, ass_mode), daemon=True).start()

    def _merge_worker(self, to_merge, out_dir, ass_mode):
        ok_n = fail_n = 0
        try:
            ffmpeg_path, _ = engine.ensure_ffmpeg()
            total = len(to_merge)
            for idx, p in enumerate(to_merge, 1):
                mp4, audio, at, mt, diff, sub, st = p
                if st == "ass" and ass_mode == "ignore":
                    sub, st = None, None
                base = engine.get_base_name(mp4)
                out_path = os.path.join(out_dir, f"{base}_merged.mp4")
                counter, orig = 1, out_path
                while os.path.exists(out_path):
                    stem, ext = os.path.splitext(orig)
                    out_path = f"{stem}_{counter}{ext}"
                    counter += 1
                self.app.q.put(("mg_log", f"[{idx}/{total}] {base}"))
                ok, final_out = engine.merge_pair(mp4, audio, at, sub, st,
                                                  out_path, ffmpeg_path, ass_mode)
                if ok and os.path.exists(final_out):
                    ok_n += 1
                    self.app.q.put(("mg_log", f"     [OK] "
                                              f"{engine.format_size(os.path.getsize(final_out))}"))
                else:
                    fail_n += 1
                    self.app.q.put(("mg_log", "     [X] 失败"))
                self.app.q.put(("mg_progress", idx / total * 100))
            self.app.q.put(("mg_done", ok_n, fail_n, out_dir))
        except Exception as e:
            self.app.q.put(("mg_done", ok_n, fail_n, f"出错: {e}"))

    def on_mg_done(self, ok_n, fail_n, out_dir):
        self.set_busy(False)
        self.progress.setValue(100)
        self.log.line(f"[完成] 成功 {ok_n} / 失败 {fail_n} → {out_dir}",
                      "ok" if fail_n == 0 else "err")
        if fail_n == 0:
            engine.open_folder(out_dir)

    # ---------- 手动合并（拖入任意音视频） ----------
    def _pick_into(self, slot, title, filt):
        p, _ = QFileDialog.getOpenFileName(self, title, "", filt)
        if p:
            slot.set_path(p)

    @staticmethod
    def _resolve_sub(path, ass_mode):
        """把手动合并选中的字幕归一成 merge_pair 认得的 (路径, 类型)。

        merge_pair 只处理 srt（软字幕）与 ass（烧录 / 封装 MKV）；SSA 与 ASS
        同族，按 ass 处理。其余格式（vtt / sub / smi / lrc）暂不支持——直接
        当没有字幕，别把 ffmpeg 喂到失败分支。另外 ASS 选了「忽略」时也要在
        这里摘掉：否则 merge_pair 会走 else 分支返回 False，白跑一次重试。
        """
        if not path:
            return None, None
        ext = os.path.splitext(path)[1].lstrip(".").lower()
        if ext == "ssa":
            ext = "ass"
        if ext not in ("srt", "ass"):
            return None, None
        if ext == "ass" and ass_mode == "ignore":
            return None, None
        return path, ext

    def _pick_out_dir(self):
        d = QFileDialog.getExistingDirectory(
            self, "选择输出文件夹", self.mv_out_edit.text() or engine.APP_DIR)
        if d:
            self.mv_out_edit.setText(d)

    def set_mv_busy(self, busy):
        self.mv_busy = busy
        self.mv_button.setEnabled(not busy)

    def start_manual_merge(self):
        video = self.mv_video.path()
        audio = self.mv_audio.path()
        if not video or not os.path.isfile(video):
            InfoBar.warning("提示", "请先拖入或选择视频文件", duration=3000,
                            position=InfoBarPosition.BOTTOM_RIGHT, parent=self)
            return
        if not audio or not os.path.isfile(audio):
            InfoBar.warning("提示", "请先拖入或选择音频文件", duration=3000,
                            position=InfoBarPosition.BOTTOM_RIGHT, parent=self)
            return
        if self.mv_busy:
            return
        ass_mode = self.ASS_MODES.get(self.mv_ass_combo.currentText(), "burn")
        raw_sub = self.mv_sub.path()
        sub, sub_type = self._resolve_sub(raw_sub, ass_mode)
        if raw_sub and not sub:
            self.mv_log.line(
                f"[信息] 已忽略字幕 {os.path.basename(raw_sub)}"
                "（仅支持 srt / ass；ASS 选了「忽略」时同样跳过）", "dim")
        out_dir = (engine.clean_path(self.mv_out_edit.text())
                   or os.path.dirname(video) or engine.APP_DIR)
        os.makedirs(out_dir, exist_ok=True)
        base = engine.get_base_name(video)
        out_path = os.path.join(out_dir, f"{base}_merged.mp4")
        counter, orig = 1, out_path
        while os.path.exists(out_path):      # 同名不覆盖，自动加序号
            stem, ext = os.path.splitext(orig)
            out_path = f"{stem}_{counter}{ext}"
            counter += 1
        self.set_mv_busy(True)
        self.mv_progress.setValue(0)
        self.mv_log.line(f"[信息] 开始合并：{os.path.basename(video)} + "
                         f"{os.path.basename(audio)}"
                         + (f" + {os.path.basename(sub)}" if sub else ""), "dim")
        threading.Thread(target=self._manual_merge_worker,
                         args=(video, audio, sub, sub_type, out_path, ass_mode),
                         daemon=True).start()

    def _manual_merge_worker(self, video, audio, sub, sub_type, out_path, ass_mode):
        try:
            ffmpeg_path, ffprobe_path = engine.ensure_ffmpeg()
            # 与自动配对复用同一条合成链（merge_pair）：AAC 直接 copy，其余转 AAC。
            # 但这里不能靠扩展名猜——用户拖进来的音频五花八门，实测编码才可靠。
            codec = engine.probe_audio_codec(audio, ffprobe_path)
            audio_type = "m4a" if codec == "aac" else "weba"
            self.app.q.put(("mvm_log",
                            f"[信息] 音频编码 {codec or '未知'} → "
                            f"{'直接封装' if audio_type == 'm4a' else '转 AAC 192k'}",
                            "dim"))
            self.app.q.put(("mvm_progress", 5))
            ok, final_out = engine.merge_pair(video, audio, audio_type, sub,
                                              sub_type, out_path, ffmpeg_path,
                                              ass_mode)
            if not ok:
                # copy 封装失败 → 视频重编码 H.264 重试一次。
                # 实测（v1.18.0 纠正旧注释）：vp9 / av1 其实能直接进 mp4，
                # 真正失败的是 **vp8**；输入容器是 webm 也一样失败
                # （webm 容器装不了 h264/aac）。重试机制仍要留着。
                self.app.q.put(("mvm_log",
                                "[信息] 首次封装失败，改用 H.264 重编码重试…", "dim"))
                ok, final_out = engine.merge_pair(video, audio, audio_type, sub,
                                                  sub_type, out_path, ffmpeg_path,
                                                  ass_mode, reencode_video=True)
            self.app.q.put(("mvm_progress", 100))
            self.app.q.put(("mvm_done", ok, final_out))
        except Exception as e:  # noqa: BLE001
            self.app.q.put(("mvm_done", False, f"出错: {e}"))

    def on_mvm_done(self, ok, final_out):
        self.set_mv_busy(False)
        if ok and os.path.exists(final_out):
            self.mv_progress.setValue(100)
            self.mv_log.line(f"[完成] {final_out} "
                             f"（{engine.format_size(os.path.getsize(final_out))}）",
                             "ok")
            engine.open_folder(os.path.dirname(final_out))
        else:
            self.mv_log.line(f"[X] 合并失败：{final_out}", "err")

    # ---------- 拖入音视频就地合并 ----------
    def _drop_active(self):
        """当前是否停在「音画合并 → 手动合并」子页（决定要不要接管拖放）。

        其它情形一律放行：一级分段停在「视频下载」时本页收不到事件；停在
        「自动配对」子页时 ignore()，让事件冒泡给主窗口全局分派，与旧行为
        一致（视频/音频仍进字幕编辑）。

        判据用 stack 索引而非 mode_seg.currentItem()：后者返回 SegmentedItem
        对象，且 setCurrentItem 不触发 onClick（见 _switch_mode 注释）。
        """
        try:
            if self.app.download_page.stack.currentWidget() is not self:
                return False
            return self.stack.currentIndex() == 1
        except Exception:  # noqa: BLE001
            return False

    @staticmethod
    def _drop_paths(e):
        if not e.mimeData().hasUrls():
            return []
        return [u.toLocalFile() for u in e.mimeData().urls()
                if u.isLocalFile() and u.toLocalFile()]

    @staticmethod
    def _classify(paths):
        """把拖入的文件按后缀分到（视频, 音频, 字幕），每类取第一个。"""
        video = audio = sub = ""
        for p in paths:
            ext = os.path.splitext(p)[1].lower()
            if not video and ext in VIDEO_EXTS:
                video = p
            elif not audio and ext in AUDIO_EXTS:
                audio = p
            elif not sub and ext in SUBTITLE_EXTS:
                sub = p
        return video, audio, sub

    def dragEnterEvent(self, e):
        if self._drop_active() and self._drop_paths(e):
            e.acceptProposedAction()
        else:
            e.ignore()

    def dragMoveEvent(self, e):
        if self._drop_active() and self._drop_paths(e):
            e.acceptProposedAction()
        else:
            e.ignore()

    def dropEvent(self, e):
        if not self._drop_active():
            return                          # 放行冒泡：交主窗口全局分派
        paths = self._drop_paths(e)
        if not paths:
            return
        e.acceptProposedAction()            # 中断冒泡，别跳去字幕编辑
        self.accept_media(paths)

    def accept_media(self, paths):
        """按后缀把文件归位到视频 / 音频 / 字幕槽；返回 True = 至少接了一个。

        页级 dropEvent 与主窗口兜底分派**共用同一条路径**：MergePage 只覆盖页内
        那块矩形，拖到页面边缘 / 顶部导航条 / 窗口边框这些"本页之外"的位置收不到
        它的 dragEnter，会一路冒泡到主窗口的全局分派器；那里先问一句"手动合并子页
        在前台吗"，是就调这里就地归位，行为与拖在页面正中完全一致（与 CalibPage
        的处理同思路，避免"拖到边缘就跳页"）。
        """
        if not self._drop_active():
            return False
        video, audio, sub = self._classify(
            [engine.clean_path(p) for p in (paths or [])])
        if video:
            self.mv_video.set_path(video)
        if audio:
            self.mv_audio.set_path(audio)
        if sub:
            self.mv_sub.set_path(sub)
        got = [(p, n) for p, n in ((video, "视频"), (audio, "音频"), (sub, "字幕")) if p]
        if got:
            self.mv_log.line("[拖入] " + "、".join(
                f"{n} {os.path.basename(p)}" for p, n in got), "ok")
            return True
        self.mv_log.line("[拖入] 未识别出音视频 / 字幕文件", "err")
        return False


def build_page(app, parent=None):
    """注册表 GuiSpec.builder / 容器页组装入口（merge.build_page 服务）。"""
    return MergePage(app, parent)