# -*- coding: utf-8 -*-
# @version 3.3.1
"""字幕校准页（2026-11-15 功能解耦阶段③：从 video_toolbox_qt.py 拆出，逐字同源）。

* 宿主：字幕工作台（SubtitlePage）经注册表服务 ``calibrate.build_page`` 惰性
  组装本板块；calibrate 功能缺失时工作台自动跳过「字幕校准」分段。
* 消息自订阅（bus「cal_」前缀，含任务代号 _gen 代际守卫），不再依赖入口
  _dispatch。
* 后端：脚本模式 subprocess 直连 calib_core（-m）；AI 模式 engine.calib_ai_run。
"""
import os
import subprocess
import threading
import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QFileDialog, QVBoxLayout, QWidget

from vt_fluent import (BodyLabel, CaptionLabel, ComboBox, FluentIcon as FIF,
                       InfoBar, InfoBarPosition, LineEdit, MessageBox,
                       PrimaryPushButton, PushButton, SwitchButton)

import video_toolbox as engine

from vt_app.widgets import (LogView, TabPage, card, fit_caption, label_row,
                            row, tab_caption)
from features._media import SUBTITLE_EXTS


class CalibPage(QWidget):
    # P3b 子键化（2026-11-22）：12 个变体校准键降级为「游戏-细类」ASCII 子键
    #   （ja→wuwa-ja、jpe→endo-ja、ko→wuwa-ko、akko→ak-ko、akja→ak-ja、arcak→ak-arcaea、
    #   endobi→endo-bi、endoko→endo-ko、pgren→pgr-en、pgrja→pgr-ja + 新入口
    #   wuwa-40ko/wuwa-40ign），子键无顶层简单旗标，统一走「--mode <子键>」两 token；
    #   顶层模式保留简单旗标（--ak/--endo/--pgr/--zho/…）。
    # 下拉按 parent 分组显示：「── 组名 ──」为不可选分组行（值 None，见 _on_mode_index
    #   守卫），分组内先顶层键后子键。wuwa-40ko/40ign 走一键重跑旗标（带内置侧车装配，
    #   裸 --mode 只设模式不装侧车，故不采用）。
    MODES = [
        ("中英双语（默认，BILINGUAL_TERMS）", ""),
        ("── 鸣潮 ──", None),
        ("鸣潮-日语（--mode wuwa-ja）", "--mode wuwa-ja"),
        ("鸣潮-韩语（--mode wuwa-ko）", "--mode wuwa-ko"),
        ("鸣潮-4.0韩语（--wuwa40ko 一键）", "--wuwa40ko"),
        ("鸣潮-4.0IGN（--wuwa40ign 一键）", "--wuwa40ign"),
        ("鸣潮-4.0新地区PV（--wuwa40pv 一键）", "--wuwa40pv"),
        ("鸣潮-4.0新联邦实机（--wuwa40reveal 一键）", "--wuwa40reveal"),
        ("── 明日方舟 ──", None),
        ("明日方舟（--ak）", "--ak"),
        ("明日方舟-日语（--mode ak-ja）", "--mode ak-ja"),
        ("明日方舟-韩语（--mode ak-ko）", "--mode ak-ko"),
        ("明日方舟-Arcaea（--mode ak-arcaea）", "--mode ak-arcaea"),
        ("── 终末地 ──", None),
        ("终末地（--endo）", "--endo"),
        ("终末地-双语（--mode endo-bi）", "--mode endo-bi"),
        ("终末地-韩语（--mode endo-ko）", "--mode endo-ko"),
        ("终末地-日语（--mode endo-ja）", "--mode endo-ja"),
        ("── 战双 ──", None),
        ("战双帕弥什（--pgr）", "--pgr"),
        ("战双-英文（--mode pgr-en）", "--mode pgr-en"),
        ("战双-日语（--mode pgr-ja）", "--mode pgr-ja"),
        ("── 其他 ──", None),
        ("中文行专属（--zho）", "--zho"),
        ("综合手游OST（--wwoc）", "--wwoc"),
        ("音乐点评（--react）", "--react"),
        ("边狱巴士（--limbus）", "--limbus"),
        # 2026-11-24：补齐后端 MODE_REGISTRY 已注册但界面缺失的 8 个模式
        # （hsr/zel 注册表 name=None、无实体投影槽，暂不暴露；fix-en 是旗标非模式）。
        ("最终幻想14（--mode ff14）", "--mode ff14"),
        ("最终幻想：共鸣（--mode ffrs）", "--mode ffrs"),
        ("少女前线2：追放（--mode gfl2）", "--mode gfl2"),
        ("影之刃零（--mode pbz）", "--mode pbz"),
        ("宝可梦城镇主题（--mode pkm）", "--mode pkm"),
        ("星之救援者（--mode ssv）", "--mode ssv"),
        ("TGA 2026 游戏大奖（--mode tga26）", "--mode tga26"),
        ("燕云十六声（--mode wwm）", "--mode wwm"),
    ]

    @staticmethod
    def style_label(cfg_value):
        """配置值 → 界面文案（与 settings_page 三档下拉、core/calibrate/ai.py 路由同口径）：
        ""/None/term/auto → 自动（后端 style=None：机翻腔 hot==0 自动整句重写）；
        term-locked → 锁定术语级；rewrite → 整句重写。"""
        v = str(cfg_value or "").strip().lower()
        if v == "rewrite":
            return "整句重写（理顺机翻）"
        if v == "term-locked":
            return "锁定术语级（只换名词，绝不改写）"
        return "自动（机翻腔 hot==0 自动整句重写）"

    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self.setObjectName("CalibPage")
        self.running = False
        self.ai_running = False
        self._cancel_flag = False   # AI 校准取消标志（关闭页面/再次点击）
        self._round = 0             # 已完成的 AI 校准轮次（「再次校准」据此递增）
        self._last_out = ""         # 上一轮 AI 校准输出（再次校准的输入）
        self._last_accepted = []    # 上一轮 AI 采纳明细 [(num, old, new)]，续跑时禁止回退
        self._base_stem = ""        # 第 1 轮确定的输出基名（后续轮次派生命名）
        self._thread = None         # 当前校准工作线程（脚本/AI 共用），卡死自检依据
        self._gen = 0               # 任务代号：每轮 +1，旧线程残留消息按代号丢弃
        self._last_beat = 0.0       # 最近一次收到校准日志/完成消息的时刻（心跳）
        self._script = os.path.join(engine.APP_DIR, "subtitle_calib_merged.py")

        # 功能解耦阶段③：消息自订阅（原入口 _dispatch 的 cal_* 分支）。
        app.bus.subscribe("cal_", self._on_bus_message)

        # 子板块壳：可滚动、无大标题（标题由字幕处理页的分段控件承担）。
        # 保留 ScrollPage 时代的 `view` / `add_card` API，调用方不受影响。
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.shell = TabPage(self)
        outer.addWidget(self.shell)
        self.view = self.shell
        self.add_card = self.shell.content_lay.addWidget
        self.vbox = self.shell.content_lay
        self.vbox.setSpacing(12)
        self.vbox.addWidget(tab_caption(
            "调用 calib_core 校准引擎做名词级术语校准（根目录单文件为生成物/同步载体）；"
            "序号 / 时间轴 / 空行 / 换行 / BOM 一字不动", self.view))

        if not os.path.isfile(self._script):
            warn = fit_caption(CaptionLabel(f"校准脚本缺失：{self._script}", self.view))
            warn.setWordWrap(True)
            warn.setTextColor(Qt.darkRed)
            self.add_card(warn)

        self.in_edit = LineEdit(self)
        self.in_edit.setPlaceholderText("选择 .srt 字幕文件")
        in_btn = PushButton(FIF.DOCUMENT, "浏览…", self)
        in_btn.clicked.connect(self.browse_in)
        self.out_edit = LineEdit(self)
        self.out_edit.setPlaceholderText("留空自动：同目录 原名.calib.srt（重名自动加序号）")
        out_btn = PushButton(FIF.SAVE, "浏览…", self)
        out_btn.clicked.connect(self.browse_out)

        box, lay = card("字幕文件（.srt）")
        lay.addWidget(row(self.in_edit, in_btn))
        lay.addWidget(row(self.out_edit, out_btn))
        self.add_card(box)

        self.mode_combo = ComboBox(self)
        self.mode_combo.addItems([m[0] for m in self.MODES])
        self.mode_combo.setCurrentIndex(0)
        # P3b 分组行守卫：「── 组名 ──」行（值 None）不可选，误选即回退上一个有效模式；
        #   _mode_idx 始终指向 MODES 中最近的**可选**项（取值处不再信任 currentIndex）。
        self._mode_idx = 0
        self.mode_combo.currentIndexChanged.connect(self._on_mode_index)
        self.fix_switch = SwitchButton(self)
        self.report_switch = SwitchButton(self)
        self.report_switch.setChecked(True)
        self.stats_switch = SwitchButton(self)
        # AI 校准（Agent 级）：开启后「开始校准」等价于让 AI 基于校准脚本
        # 逐块复校——只改文字、不动时间轴与格式，读不完自动拆分再合并。
        self.ai_switch = SwitchButton(self)
        self.ai_switch.checkedChanged.connect(self._on_ai_toggle)
        self.run_btn = PrimaryPushButton(FIF.PLAY, "开始校准", self.view)
        self.run_btn.clicked.connect(self.start)
        self.again_btn = PushButton(FIF.SYNC, "再次校准", self.view)
        self.again_btn.setEnabled(False)
        self.again_btn.clicked.connect(self.start_again)
        # 刷新：程序卡死（异常/线程僵住导致按钮永久禁用）时，一键复位界面状态，
        # 之后可正常点「开始校准」重新执行；正常运行时点它只提示不打断任务。
        self.refresh_btn = PushButton(FIF.UPDATE, "刷新", self.view)
        self.refresh_btn.clicked.connect(self.refresh_state)
        self.stage_label = fit_caption(CaptionLabel("", self.view))

        box, lay = card("片源模式与选项")
        lay.addWidget(label_row("片源模式", self.mode_combo))
        lay.addWidget(row(BodyLabel("修正英文/参考行（--fix-en，仅双语模式生效）", self.view),
                          self.fix_switch, None))
        lay.addWidget(row(BodyLabel("生成改动对照报告（同名 .md）", self.view),
                          self.report_switch, None))
        lay.addWidget(row(BodyLabel("仅统计术语命中，不写输出文件", self.view),
                          self.stats_switch, None))
        lay.addWidget(row(BodyLabel("AI 校准（Agent 级，接入你自己的 AI 辅助校准）",
                                    self.view), self.ai_switch, None))
        # 说明文案保持「一行放得下」：滚动区内不能换行，长文案会撑破卡片
        self.ai_hint = fit_caption(CaptionLabel(
            "开启后 = 让 AI 基于校准脚本逐块复校：只改文字，不动时间轴与格式",
            self.view))
        self.ai_hint.setTextColor("#8a8a8a", "#9a9a9a")
        lay.addWidget(self.ai_hint)
        lay.addWidget(row(self.stage_label, None,
                          self.refresh_btn, self.again_btn, self.run_btn))
        # 2026-11-24 状态透传：只读标签显示上一轮 AI 校准的「本轮风格」与「不动点」结论
        #   （脚本模式保持「—」）。后端 res 的 style_auto_rewrite / fixed_point 经
        #   on_cal_done 写入；详细数字仍在日志与报告三c 节。
        self.style_tag = fit_caption(CaptionLabel("本轮风格：—", self.view))
        self.style_tag.setTextColor("#8a8a8a", "#9a9a9a")
        self.fp_tag = fit_caption(CaptionLabel("不动点：—", self.view))
        self.fp_tag.setTextColor("#8a8a8a", "#9a9a9a")
        lay.addWidget(row(self.style_tag, None, self.fp_tag))
        self.add_card(box)

        self.log = LogView("校准日志", 170, self.view)
        self.log.text.setAcceptDrops(False)
        self.add_card(self.log)
        self.vbox.addStretch(1)
        # v1.14.2 修复：拖进本页的字幕文件就地填入「字幕文件」框。
        # 此前本页不收拖放，.srt 事件冒泡到主窗口的全局分派器，
        # 被 switchTo 到「字幕编辑」页——表现为"放入字幕后页面乱跳"。
        self.setAcceptDrops(True)
        # LineEdit 默认吞文件拖放（会把 file:// 字符串插进框里），关掉后
        # 事件冒泡到本页统一处理，拖到输入框上与拖到页面空白处行为一致。
        self.in_edit.setAcceptDrops(False)
        # 同理：输出路径框与日志区（QLineEdit/QTextEdit 默认 acceptDrops）
        # 也关掉，避免拖到这些控件上时被就地吞掉、行为不一致。
        self.out_edit.setAcceptDrops(False)

    # ---------- 消息 ----------
    def _on_bus_message(self, msg):
        """bus「cal_」前缀消息（原入口 _dispatch 的 cal_* 分支，语义逐字一致）。"""
        kind, args = msg[0], msg[1:]
        if kind == "cal_log":
            # (文本, 级别, 任务代号)：旧线程残留消息丢弃；有效消息刷新心跳
            if len(args) < 3 or args[2] == self._gen:
                self._last_beat = time.time()
                self.log.line(args[0], args[1] if len(args) > 1 else "dim")
        elif kind == "cal_done":
            # (rc, out, result, 任务代号)
            self.on_cal_done(*args)

    # ---------- 拖入字幕就地接收（v1.14.2） ----------
    def _drop_subtitle_path(self, e):
        """从拖放事件里取第一个本地字幕文件路径；没有返回 ""。
        （只认 SUBTITLE_EXTS：视频/音频等仍放行给主窗口全局分派。）"""
        if not e.mimeData().hasUrls():
            return ""
        for u in e.mimeData().urls():
            p = engine.clean_path(u.toLocalFile() if u.isLocalFile() else "")
            if p and os.path.splitext(p)[1].lower() in SUBTITLE_EXTS:
                return p
        return ""

    def accept_subtitle(self, path):
        """把字幕文件填进「字幕文件」框；返回 True = 已接收。

        本页拖入与主窗口兜底分派**共用同一条路径**（v1.15.8）：
        CalibPage 只覆盖引擎工作台那块矩形，页面边缘、顶部导航条、窗口边框
        这些"本页之外"的位置收不到它的拖放事件，会一路冒泡到主窗口的全局
        分派器。此前那里一律 switchTo 到「字幕编辑」，用户看到的就是
        "字幕拖到边缘就跳页"。现在主窗口先问一句"校准页在前台吗"，是就
        走这里就地填入，行为与拖在页面正中完全一致。
        """
        p = engine.clean_path(path or "")
        if not p or os.path.splitext(p)[1].lower() not in SUBTITLE_EXTS:
            return False
        self.in_edit.setText(p)
        self.log.line(f"[校准] 已接收字幕文件：{p}", "dim")
        return True

    def dragEnterEvent(self, e):
        if self._drop_subtitle_path(e):
            e.acceptProposedAction()   # 有字幕 → 本页接管
        # 没有字幕 → 不调 accept，事件照旧冒泡给主窗口全局分派

    def dragMoveEvent(self, e):
        if self._drop_subtitle_path(e):
            e.acceptProposedAction()

    def dropEvent(self, e):
        p = self._drop_subtitle_path(e)
        if not p:
            return
        e.acceptProposedAction()       # 中断冒泡：不再触发主窗口的页面跳转
        self.accept_subtitle(p)
        # 混拖的其它文件（视频/目录等）仍交全局分派器，保持原有能力
        others = [engine.clean_path(u.toLocalFile())
                  for u in e.mimeData().urls() if u.isLocalFile()]
        others = [x for x in others
                  if x and x != p
                  and os.path.splitext(x)[1].lower() not in SUBTITLE_EXTS]
        if others:
            QTimer.singleShot(0, lambda ps=others: self.app._handle_dropped_files(ps))

    def _on_mode_index(self, idx):
        """P3b 分组行守卫：MODES 里值为 None 的行是「── 组名 ──」分组标题，
        不可作为片源模式。误选时静默回退到上一个有效选择（屏蔽信号防递归）。"""
        if 0 <= idx < len(self.MODES) and self.MODES[idx][1] is not None:
            self._mode_idx = idx
            return
        self.mode_combo.blockSignals(True)
        self.mode_combo.setCurrentIndex(self._mode_idx)
        self.mode_combo.blockSignals(False)

    def browse_in(self):
        p, _ = QFileDialog.getOpenFileName(self, "选择字幕文件",
                                           self.in_edit.text() or engine.APP_DIR,
                                           "字幕文件 (*.srt);;所有文件 (*.*)")
        if p:
            self.in_edit.setText(p)

    def browse_out(self):
        p, _ = QFileDialog.getSaveFileName(self, "选择输出文件",
                                           self.in_edit.text() or engine.APP_DIR,
                                           "字幕文件 (*.srt);;所有文件 (*.*)")
        if p:
            self.out_edit.setText(p)

    # 卡死判定阈值（秒）：任务标志挂着但超过该时长没有任何日志/完成心跳 → 视为卡死
    STUCK_AFTER = 120

    def _is_stuck(self):
        """运行标志挂着、但工作线程已死或长时间无心跳 → 判定卡死。"""
        if not (self.running or self.ai_running):
            return False
        th = self._thread
        if th is not None and not th.is_alive():
            return True
        return (time.time() - self._last_beat) > self.STUCK_AFTER

    def _reset_controls(self, stage_text):
        """复位运行态控件（开始/再次按钮、阶段标签）。

        逐项单独容错：这是"脱离卡死"的最后出口，任何一个控件调用失败都不能
        中断其余复位，否则界面又回到按钮永久禁用的卡死状态。
        """
        for fn in (lambda: self.run_btn.setEnabled(True),
                   lambda: self.again_btn.setEnabled(
                       bool(self.ai_switch.isChecked() and self._last_out)),
                   lambda: self.stage_label.setText(stage_text)):
            try:
                fn()
            except Exception:  # noqa: BLE001
                pass

    def refresh_state(self, silent=False):
        """刷新：复位校准页运行状态，脱离卡死。任务正常心跳时不打断。"""
        if (self.running or self.ai_running) and not self._is_stuck():
            if not silent:
                InfoBar.info("提示", "校准任务正在正常运行，无需刷新",
                             duration=3000,
                             position=InfoBarPosition.BOTTOM_RIGHT, parent=self)
            return False
        was_stuck = self.running or self.ai_running
        self.running = False
        self.ai_running = False
        self._cancel_flag = True     # 通知可能残留的旧线程尽快退出
        self._gen += 1               # 旧线程后续投来的消息按代号丢弃
        self._thread = None
        self._reset_controls("已刷新，可重新校准")
        if was_stuck:
            self.log.line("[刷新] 检测到上一轮校准已中断，界面状态已复位；"
                          "现在可以重新点「开始校准」", "info")
        return True

    def start(self):
        if self.running or self.ai_running:
            if self._is_stuck():
                # 卡死自愈：先复位再按本次点击重新执行（用户要求：报错则重新执行）
                self.refresh_state(silent=True)
                self.log.line("[刷新] 检测到上一轮校准已卡死，已自动复位并重新执行",
                              "info")
            else:
                InfoBar.info("提示", "校准任务进行中，请稍候", duration=3000,
                             position=InfoBarPosition.BOTTOM_RIGHT, parent=self)
                return
        # 双轨（2026-11-08）：脚本模式直连 calib_core，不再依赖根目录单文件；
        # 生成物缺失只提示不阻断（AI 校准链仍读单文件，其检查保留在 _start_ai）。
        if not os.path.isfile(self._script):
            self.log.line("[提示] 根目录单文件生成物缺失（不影响脚本校准，仅影响外部同步/交付）", "dim")
        src = engine.clean_path(self.in_edit.text())
        if not src or not os.path.isfile(src):
            InfoBar.warning("提示", "请先选择一个 .srt 字幕文件", duration=3000,
                            position=InfoBarPosition.BOTTOM_RIGHT, parent=self)
            return
        mode_flag = self.MODES[self._mode_idx][1]          # P3b：分组行守卫跟踪的有效项
        if self.ai_switch.isChecked():
            self._start_ai(src, again=False, mode_flag=mode_flag)
            return
        stats_only = self.stats_switch.isChecked()

        out = ""
        if not stats_only:
            out = engine.clean_path(self.out_edit.text())
            if not out:
                out = os.path.splitext(src)[0] + ".calib.srt"
            out = self._unique(out)

        # 双轨：运行时直连 src/calib_core；进程隔离与轮询/取消/心跳契约不变。
        args = [engine.system_python(), "-m", "calib_core", src]
        if out:
            args += ["--out", out]
            if self.report_switch.isChecked():
                args += ["--report", os.path.splitext(out)[0] + ".md"]
        if mode_flag:
            # P3b：子键旗标是「--mode <子键>」两 token，按空白拆开透传。
            args.extend(mode_flag.split())
        if self.fix_switch.isChecked():
            args.append("--fix-en")

        self.running = True
        self._cancel_flag = False
        self._gen += 1
        gen = self._gen
        self._last_beat = time.time()
        try:
            self.run_btn.setEnabled(False)
            self.stage_label.setText("正在校准…")
            self.log.line(f"[校准] 模式: {self.mode_combo.currentText()}"
                          + ("（仅统计）" if stats_only else ""), "dim")
            self.log.line(f"[校准] 输入: {os.path.basename(src)}", "dim")
            if out:
                self.log.line(f"[校准] 输出: {out}", "dim")
            t = threading.Thread(target=self._worker, args=(gen, args, out),
                                 daemon=True)
            self._thread = t
            t.start()
        except Exception as e:  # noqa: BLE001
            self._reset_after_crash(f"校准启动失败：{type(e).__name__}: {e}")

    # ---------- AI 校准（Agent 级） ----------
    @staticmethod
    def _unique(path):
        """输出文件重名时自动加序号（与脚本模式的旧行为一致）。"""
        if not os.path.exists(path):
            return path
        stem, ext = os.path.splitext(path)
        n = 2
        while os.path.exists(f"{stem}({n}){ext}"):
            n += 1
        return f"{stem}({n}){ext}"

    def _on_ai_toggle(self, checked):
        """AI 校准开关：与「仅统计」互斥，并决定「再次校准」是否可用。"""
        if checked and self.stats_switch.isChecked():
            self.stats_switch.setChecked(False)
        self.stats_switch.setEnabled(not checked)
        self.again_btn.setEnabled(bool(checked and self._last_out))
        self.ai_hint.setText(
            "已开启：先跑机械校准，再由 AI 逐块补齐残留错形（不动时间轴与格式）"
            if checked else
            "开启后 = 让 AI 基于校准脚本逐块复校：只改文字，不动时间轴与格式")

    def start_again(self):
        """再次校准：以上一轮 AI 校准的输出为输入再跑一轮，专挑残留错形。"""
        if self.running or self.ai_running:
            if self._is_stuck():
                self.refresh_state(silent=True)
                self.log.line("[刷新] 检测到上一轮校准已卡死，已自动复位并重新执行",
                              "info")
            else:
                InfoBar.info("提示", "校准任务进行中，请稍候", duration=3000,
                             position=InfoBarPosition.BOTTOM_RIGHT, parent=self)
                return
        if not self.ai_switch.isChecked():
            InfoBar.warning("提示", "「再次校准」需要先开启 AI 校准",
                            duration=3000,
                            position=InfoBarPosition.BOTTOM_RIGHT, parent=self)
            return
        if not self._last_out or not os.path.isfile(self._last_out):
            InfoBar.warning("提示", "还没有可续跑的结果，请先完成一轮 AI 校准",
                            duration=3000,
                            position=InfoBarPosition.BOTTOM_RIGHT, parent=self)
            return
        mode_flag = self.MODES[self._mode_idx][1]          # P3b：分组行守卫跟踪的有效项
        self._start_ai(self._last_out, again=True, mode_flag=mode_flag)

    def _start_ai(self, src, again, mode_flag):
        """发起一轮 AI 校准（后台线程跑 Agent，日志经消息队列回主线程）。"""
        if not os.path.isfile(self._script):
            MessageBox("错误", f"校准脚本缺失：{self._script}", self).exec()
            return
        if again:
            n = self._round + 1
            out = self._unique(f"{self._base_stem or os.path.splitext(src)[0]}.r{n}.srt")
        else:
            out = engine.clean_path(self.out_edit.text())
            if not out:
                out = os.path.splitext(src)[0] + ".calib.srt"
            out = self._unique(out)
            self._base_stem = os.path.splitext(out)[0]
            self._round = 0
            self._last_out = ""
        # v1.15.1：报告固定写**同一个**文件（第 1 轮定的 base_stem.md），多轮校准
        # 复写它，不再在目录里堆 .r2.md / .r3.md —— 轮次信息写在报告正文里。
        report_stem = self._base_stem or os.path.splitext(out)[0]
        report = (report_stem + ".md") if self.report_switch.isChecked() else ""
        round_no = self._round + 1

        self.ai_running = True
        self._cancel_flag = False
        self._gen += 1
        gen = self._gen
        self._last_beat = time.time()
        try:
            self.run_btn.setEnabled(False)
            self.again_btn.setEnabled(False)
            self.stage_label.setText(f"AI 校准中（第 {round_no} 轮）…")
            self.log.line(f"===== AI 校准 · 第 {round_no} 轮 =====", "info")
            self.log.line(f"[AI] 模式: {self.mode_combo.currentText()}", "dim")
            # 校准风格属于全局设置（设置页「AI 校准」卡片三档下拉），本页无对应控件；
            # 与 engine.calib_ai_run 内部 style=None 时的取值口径保持一致，仅用于日志。
            _ai_cfg = engine.ai_load_config() or {}
            self.log.line(f"[AI] 风格: {self.style_label(_ai_cfg.get('calib_style'))}"
                          + ("；以上轮结果为起点续跑（跳过脚本基线、禁止回退）"
                             if again else ""), "dim")
            self.log.line("[AI] 联网查证: "
                          + ("开启（Agent 可搜索/抓取官方名作证据）"
                             if _ai_cfg.get("calib_web_enabled") else "关闭"), "dim")
            _media_cfg = _ai_cfg.get("calib_media_enabled")
            _media_src = engine.calib_media_for_srt(src) if _media_cfg else ""
            self.log.line("[AI] 音画证据: "
                          + ("开启（Agent 可请求源媒体音频重转写/抽帧作证据）"
                             if _media_cfg else "关闭")
                          + (("（%s）" % os.path.basename(_media_src)
                              if _media_src else
                              ("（未找到同名源视频，按离线继续）"
                               if _media_cfg else ""))), "dim")
            self.log.line(f"[AI] 输入: {src}", "dim")
            self.log.line(f"[AI] 输出: {out}", "dim")
            if report:
                self.log.line(f"[AI] 报告: {report}", "dim")
            # 状态标签复位：新一轮开始，上一轮的结论不再有效
            self.style_tag.setText("本轮风格：运行中…")
            self.fp_tag.setText("不动点：运行中…")
            t = threading.Thread(target=self._ai_worker,
                                 args=(gen, src, out, report, mode_flag,
                                       round_no, again,
                                       # v1.16.5 修复：控件值必须在**主线程**读好
                                       # 再传入——_ai_worker 跑在子线程里，直接在
                                       # 其中调 fix_switch.isChecked() 属跨线程访问
                                       # Qt 控件（Qt 非线程安全）。
                                       self.fix_switch.isChecked(),
                                       # 音画证据（2026-10-12）：同名源媒体路径
                                       # （找不到传空串，Agent 按离线继续）。
                                       engine.calib_media_for_srt(src)),
                                 daemon=True)
            self._thread = t
            t.start()
        except Exception as e:  # noqa: BLE001
            self._reset_after_crash(f"AI 校准启动失败：{type(e).__name__}: {e}")

    def _reset_after_crash(self, msg):
        """主线程启动任务时抛异常：立即复位运行状态，保证界面不会卡死。

        复位必须"无论控件本身是否还能用都要执行完"（见 _reset_controls），
        否则又回到卡死状态。
        """
        self.running = False
        self.ai_running = False
        self._cancel_flag = True     # 通知可能残留的旧线程尽快退出
        self._gen += 1               # 旧线程后续投来的消息按代号丢弃
        self._thread = None
        self._reset_controls("校准失败")
        self.log.line(f"[错误] {msg}", "err")
        self.log.line("界面状态已自动复位，可直接重新点「开始校准」", "info")

    def _ai_worker(self, gen, src, out, report, mode_flag, round_no, again=False,
                   fix_en=False, media_path=""):
        def _log(msg, level="dim"):
            self.app.q.put(("cal_log", str(msg), level, gen))

        try:
            res = engine.calib_ai_run(
                src, out=out, report=(report or None), mode_flag=mode_flag,
                fix_en=fix_en, log=_log, round_no=round_no,
                cancel=lambda: self._cancel_flag,
                # 音画证据（2026-10-12）：同名源媒体作为证据源；
                # 空串 = 未找到，Agent 按离线继续（行为同旧版）。
                media_path=media_path,
                # 续跑：以上轮产物为起点（跳过脚本基线），并把上轮采纳明细注入提示词
                resume_from=(src if again else None),
                prev_changes=(self._last_accepted if again else None))
        except Exception as e:  # noqa: BLE001
            res = {"ok": False, "out": out, "error": f"{type(e).__name__}: {e}",
                   "script_changes": 0, "ai_changes": 0, "rejected": 0,
                   "round": round_no}
        self.app.q.put(("cal_done", 0 if res.get("ok") else 1,
                        res.get("out") or out, res, gen))

    def _worker(self, gen, args, out):
        try:
            # -m calib_core 需要 <根>/src 在模块搜索路径；保留既有 PYTHONPATH。
            _src_dir = os.path.join(engine.APP_DIR, "src")
            _old_pp = os.environ.get("PYTHONPATH", "")
            env = dict(os.environ, PYTHONIOENCODING="utf-8",
                       PYTHONPATH=_src_dir + (os.pathsep + _old_pp if _old_pp else ""))
            proc = engine.popen_process(args, cwd=os.path.dirname(self._script),
                                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                        text=True, encoding="utf-8", errors="replace",
                                        bufsize=1, env=env)
            for line in proc.stdout:
                line = line.rstrip()
                if line:
                    self.app.q.put(("cal_log", line, "dim", gen))
            rc = proc.wait()
        except Exception as e:  # noqa: BLE001
            self.app.q.put(("cal_log", f"[错误] 校准进程异常: {e}", "dim", gen))
            rc = 1
        self.app.q.put(("cal_done", rc, out, None, gen))

    def on_cal_done(self, rc, out, res=None, gen=None):
        """校准结束（脚本模式 res 为 None；AI 模式 res 为 Agent 结果 dict）。"""
        if gen is not None and gen != self._gen:
            return                      # 已被刷新/新任务取代的旧线程消息，丢弃
        self.running = False
        self.ai_running = False
        self._thread = None
        self.run_btn.setEnabled(True)
        res = res or {}
        if res.get("round"):                    # AI 轮次
            if rc == 0:
                self._round = int(res.get("round") or self._round)
                self._last_out = out
                # 保存采纳明细：下一轮 resume 时作为「不得回退」清单注入提示词
                self._last_accepted = [(n, o, x)
                                       for n, o, x, *_ in res.get("accepted", [])]
            self.again_btn.setEnabled(bool(self.ai_switch.isChecked()
                                           and self._last_out))
        if rc == 0:
            self.stage_label.setText("校准完成")
            if res:
                self.log.line(
                    f"[OK] AI 校准完成（第 {self._round} 轮）：术语脚本 "
                    f"{res.get('script_changes', 0)} 处 + AI {res.get('ai_changes', 0)} 处，"
                    f"拒绝 {res.get('rejected', 0)} 处"
                    + (f"，耗时 {res.get('seconds')}s" if res.get("seconds") else ""),
                    "ok")
                if out:
                    self.log.line(f"[输出] {out}", "ok")
                if res.get("report"):
                    self.log.line(f"[报告] {res['report']}（含采纳明细与拒绝原因）", "dim")
                if res.get("width_over"):
                    self.log.line(f"[行宽] {res['width_over']} 处中文行超过 32 汉字当量，"
                                  f"已列进报告（检查报告第四节）", "err")
                elif (res.get("width_widest") or ("", ""))[0]:
                    self.log.line(f"[行宽] 体检通过（最宽 {res['width_widest'][0]} / 32）",
                                  "dim")
                # 2026-11-24 状态透传：风格路由 / 8d audit 门禁 / 8c 不动点 / 8e 会话回灌
                #   后端 _log_do 的逐条日志已经 bus 无过滤进本日志；这里补「结论级」摘要
                #   + 只读标签，数字细节见报告三c 节。
                self._log_gate_summary(res)
                self.log.line("可点「再次校准」再跑一轮：以上轮结果为起点，"
                              "已确认的改动不会被改回去", "info")
            else:
                self.log.line("[OK] 校准完成" +
                              (f"，输出: {out}" if out else
                               "（仅统计模式，未改写文件）"), "ok")
        else:
            self.stage_label.setText("校准失败")
            msg = res.get("error") or f"退出码 {rc}"
            self.log.line(f"[错误] 校准失败：{msg}", "err")
            if res:
                self.log.line("[提示] 已拒绝的模型提议会写进报告，便于人工复核", "dim")

    def _log_gate_summary(self, res):
        """AI 校准收尾：把 res 里的门禁结论写进日志并更新只读标签（2026-11-24）。

        只读 res 的既有键，不重算：style / style_explicit / style_auto_rewrite /
        audit_gate / audit_fixes / fixed_point* / session_canonicals / session_promote。
        """
        try:
            # —— 风格：配置档位 → 本轮实际生效档位（自动改派只在未锁定时发生）
            if res.get("style_auto_rewrite"):
                _txt = "自动 → 整句重写"
                _why = "（规则命中 0 条且双语带参考行，自动改派）"
            elif res.get("style") == "rewrite":
                _txt = "整句重写"
                _why = "（配置锁定）"
            elif res.get("style_explicit"):
                _txt = "术语级"
                _why = "（配置锁定，未自动改派）"
            else:
                _txt = "自动 → 术语级"
                _why = "（规则命中非零或非双语片，保持术语级）"
            self.style_tag.setText(f"本轮风格：{_txt}")
            self.log.line(f"[风格] 本轮：{_txt}{_why}", "dim")
            # —— 8d audit 门禁
            _ag = res.get("audit_gate")
            if isinstance(_ag, dict):
                if not _ag.get("anchors"):
                    self.log.line("[门禁] audit：无参考行锚点，三扫仅供参考（inconclusive）", "dim")
                elif res.get("audit_fixes"):
                    self.log.line(f"[门禁] audit：机械补校 {res['audit_fixes']} 处高置信残留"
                                  f"（拉丁残留 {_ag.get('s1', 0)} / 同族 {_ag.get('s3', 0)} 处待人工，见报告）", "ok")
                else:
                    self.log.line(f"[门禁] audit：高置信残留 0 处，无需补校"
                                  f"（拉丁残留 {_ag.get('s1', 0)} / 同族 {_ag.get('s3', 0)} 处待人工，见报告）", "dim")
            # —— 8c 不动点
            _fp = res.get("fixed_point")
            if _fp is True:
                self.fp_tag.setText("不动点：✓")
                self.log.line(f"[门禁] 不动点：✓ 成立（机械基线上引擎复跑零改动，"
                              f"SHA {str(res.get('fixed_point_sha') or '')[:12]}…）", "ok")
            elif _fp is False:
                self.fp_tag.setText("不动点：⚠")
                _cv = bool(res.get("fixed_point_converges"))
                self.log.line(f"[门禁] 不动点：⚠ 未成立——机械基线上引擎仍会改 "
                              f"{res.get('fixed_point_break', '?')} 处；"
                              + (f"补跑 {res.get('fixed_point_passes')} 跑后收敛（渐进精修，良性）"
                                 if _cv else
                                 f"补跑 {res.get('fixed_point_passes')} 跑仍不收敛（振荡，需排查）"),
                              "err")
            else:
                self.fp_tag.setText("不动点：—（无机械层）")
                self.log.line("[门禁] 不动点：跳过（未跑脚本基线，无机械层可验）", "dim")
            # —— 8e 会话回灌
            _sc = res.get("session_canonicals") or []
            if _sc:
                _pm = res.get("session_promote") or {}
                self.log.line(f"[回灌] 会话回灌 {len(_sc)} 条 A 级条目当轮生效（"
                              + ("已固化进真源" if _pm.get("state") == "promoted"
                                 else "未固化（VT_SESSION_PROMOTE 未开启）") + "）", "ok")
        except Exception as e:  # noqa: BLE001
            self.log.line(f"[门禁] 状态摘要生成失败（不影响校准结果）：{e}", "dim")


def build_page(app, parent=None):
    """注册表服务 calibrate.build_page：字幕工作台惰性组装本板块。"""
    return CalibPage(app, parent)