# -*- coding: utf-8 -*-
# @version 3.2.5
"""字幕工作台页（2026-11-15 功能解耦阶段③：从 video_toolbox_qt.py 拆出，逐字同源）。

* 内嵌字幕引擎工作台（vt_engine_ui 自研优先，videocaptioner 回退），预热三段
  构建原样保留；「字幕校准」板块经注册表服务 calibrate.build_page 组装；
* 双语判定/任务创建拖放放宽等 HELPER 为本功能专属，随页迁入（入口再导出旧名）；
* 本页全走 Qt 信号与调度器（无 pump 消息），不需要 bus 订阅。
"""
import os
import re
import time
import unicodedata

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (QApplication, QHBoxLayout, QVBoxLayout, QWidget)

from vt_fluent import (CaptionLabel, FluentIcon as FIF, InfoBar,
                       InfoBarPosition, MessageBox, PushButton)

import video_toolbox as engine

from vt_app.boot import _perf_note
from vt_app.scheduler import _SCHED, _defer
from vt_app.engine_ui import (_ENGINE_PREWARM, _engine_prewarm_probe,
                              _resolve_engine_ui, _start_engine_prewarm)
from vt_app.lazy_shell import _install_spinbox_fix_once
from vt_app.widgets import fit_caption
from features._media import SUBTITLE_EXTS

#: 「双语字幕」判定：cue 内同时出现中文行与非中文行。用于「任务创建」的跳转
#: 分派（单语 → 字幕翻译；双语 → 字幕校准）。
_ZH_CHAR_RE = re.compile(r"[\u4e00-\u9fff]")


def _has_non_zh_letters(line):
    """该行是否含「非中文的文字」——拉丁 / 假名 / 谚文 / 西里尔 等都算。

    ⚠️ 不能用 `[A-Za-z]` 判：日文（こんにちは）、韩文（안녕하세요）里一个
    拉丁字母都没有，那样「日中对照」「韩中对照」会被误判成单语。
    """
    for ch in line:
        if _ZH_CHAR_RE.match(ch):
            continue
        if unicodedata.category(ch)[0] == "L":      # L* = 字母类
            return True
    return False


def iter_subtitle_cues(txt, max_cues=200):
    """把字幕文本拆成 cue 列表（每个 cue = 该条目的若干行文本）。

    兼容 SRT/VTT（`-->` 时间轴行切分）与 ASS/SSA（`Dialogue:` 行，`\\N` 换行）。
    ⚠️ **不能按"空行分隔"切块**：大量 SRT 的 cue 之间根本没有空行（导出器各异），
    那样整份文件会被当成一个块，双语判定必然失败（实测踩过）。
    """
    cues, cur = [], []
    for ln in (txt or "").splitlines():
        s = ln.strip()
        if "-->" in ln:                       # SRT / VTT 时间轴行
            if cur:
                cues.append(cur)
            cur = []
            continue
        if s.startswith("Dialogue:"):         # ASS / SSA
            if cur:
                cues.append(cur)
            cur = []
            body = ln.split(",", 9)[-1] if ln.count(",") >= 9 else s
            cur = [p.strip() for p in body.split("\\N") if p.strip()]
            cues.append(cur)
            cur = []
            continue
        if s and not s.isdigit() and not s.startswith(("[", "{")):
            cur.append(s)
        if len(cues) >= max_cues:
            break
    if cur:
        cues.append(cur)
    return cues


def subtitle_looks_bilingual(path, max_cues=200, need=3):
    """字幕是不是「双语」（中外对照）？

    判据用「同一个 cue 里既有中文行、又有非中文行」，而不是"文件里出现过
    中文"——否则带中文注释的外语字幕、单语中文字幕都会被误判成双语送去校准。
    取前 ``max_cues`` 个 cue，命中 ``need`` 个即认为双语（少量行内混排不算）。
    """
    try:
        txt = engine.read_text_any(path)
    except Exception:  # noqa: BLE001
        return False
    hits = 0
    for lines in iter_subtitle_cues(txt, max_cues=max_cues):
        if not lines:
            continue
        has_zh = any(_ZH_CHAR_RE.search(ln) for ln in lines)
        # 「非中文行」= 不含汉字、但含别的文字（假名/谚文/拉丁…）
        has_other = any((not _ZH_CHAR_RE.search(ln)) and _has_non_zh_letters(ln)
                        for ln in lines)
        if has_zh and has_other:
            hits += 1
            if hits >= need:
                return True
    return False


def make_task_creation_drop_handler(tc):
    """给「任务创建」页换一个 dropEvent：额外接受**字幕**文件。

    引擎原实现只认 SupportedVideoFormats / SupportedAudioFormats，拖 `.srt`
    进去会弹「格式错误 srt / 不支持该文件格式」；可字幕本就是这个工作台的合法
    输入（任务创建 → 字幕翻译 / 字幕校准）。这里只放宽"接受哪些扩展名"：
    是字幕就自己收下，**其余一律交回原实现**（保留它原有的提示与行为）。
    """
    orig_drop = tc.dropEvent

    def _drop(event):
        try:
            files = [u.toLocalFile() for u in event.mimeData().urls()]
        except Exception:  # noqa: BLE001
            files = []
        subs = [p for p in files
                if p and os.path.isfile(p)
                and os.path.splitext(p)[1].lower() in SUBTITLE_EXTS]
        if not subs:
            return orig_drop(event)
        tc.search_input.setText(subs[0])
        try:
            tc.status_label.setText("导入成功")
            InfoBar.success(
                "导入成功", "已导入字幕文件，点右侧按钮继续",
                duration=3000, position=InfoBarPosition.BOTTOM_RIGHT, parent=tc)
        except Exception:  # noqa: BLE001
            pass
    return _drop


class SubtitlePage(QWidget):
    """字幕处理：内嵌字幕引擎工作台（任务创建 / 语音转录 / 优化翻译 / 合成）。

    v1.10.2 起不再唤起独立窗口，引擎界面直接嵌入本页：
      · 引擎以第三方开源组件形式随包内置，界面在宿主窗口内呈现；
      · 品牌水印与捐助入口在嵌入层隐藏（许可与来源见 docs/ 下声明文件）；
      · 引擎背景改为透明，跟随宿主深色主题（其自带样式是白底，会与
        宿主界面割裂）。

    v1.10.4 起解决首次进入卡顿：
      · `prewarm()` 在主窗口首帧之后由后台线程提前 import 引擎模块
        （videocaptioner 及其 Qt 子模块的导入是卡顿的主要来源），
        再回到主线程按空闲时机建好界面——用户点进来时已是现成控件；
      · `showEvent` 仍保留兜底构建，预热失败时行为与旧版一致。
    """

    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self.setObjectName("SubtitlePage")
        self._engine = None
        self._built = False
        self._prewarming = False
        self._prewarm_ready = False
        # 首页在预热完成前就收下文件时，先记在这里，工作台建好后再分派。
        self._pending_dispatch = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # v1.13.0：移除页内一级分段「字幕处理 / 字幕校准」——SegmentedWidget
        # 对每项固定 stretch=1 等分，只有两个标签时会被拉开大片空隙、下划线
        # 与文字错位（观感「区域不对齐」）。「字幕校准」改为并入下方引擎工作台
        # 分段，排在「字幕翻译」之后（见 _build_engine 中的挂载）。
        self.work_tab = QWidget(self)
        wlay = QVBoxLayout(self.work_tab)
        wlay.setContentsMargins(20, 10, 20, 12)
        wlay.setSpacing(8)
        outer.addWidget(self.work_tab, 1)
        self.vbox = wlay

        # 中部：引擎界面宿主；底部一行：引擎状态 + 设置/许可入口
        # （第三方组件的许可与来源见 docs\ 声明文件）
        self.host = QWidget(self.work_tab)
        self.host_lay = QVBoxLayout(self.host)
        self.host_lay.setContentsMargins(0, 0, 0, 0)
        self.vbox.addWidget(self.host, 1)

        foot = QWidget(self.work_tab)
        flay = QHBoxLayout(foot)
        flay.setContentsMargins(0, 0, 0, 0)
        flay.setSpacing(12)
        self.foot = foot                      # v1.12.0：引擎就绪后整行收起
        self.state_label = fit_caption(
            CaptionLabel("正在加载字幕引擎界面 …", foot))
        # v1.10.4：引擎设置并入「设置」页的「字幕引擎」分组，这里只留跳转
        self.set_btn = PushButton(FIF.SETTING, "打开设置", foot)
        self.set_btn.clicked.connect(self.open_settings)
        self.lic_btn = PushButton(FIF.CERTIFICATE, "许可与来源…", foot)
        self.lic_btn.clicked.connect(self.show_license)
        flay.addWidget(self.state_label, 1)
        flay.addWidget(self.set_btn)
        flay.addWidget(self.lic_btn)
        self.vbox.addWidget(foot)

        # ——「字幕校准」独立内容页：不进入任何宿主导航，待引擎工作台
        #    构建完成后并入其分段（见 _build_engine） ——
        # 2026-10-20 启动 <5s 专项：CalibPage 构造改惰性（真实平台实测
        # 211ms，只服务引擎工作台的一个分段，而工作台本身就在首帧后构建）。
        # app 必须传主窗口（消息队列 q 挂在主窗口上；此前传 SubtitlePage
        # 导致 AI 校准线程投递日志即抛 AttributeError 而死，校准等于没跑）。
        self._calib_page = None

    @property
    def calib_page(self):
        """「字幕校准」页——惰性构造（首次取用才建，幂等）。

        阶段③：经注册表服务 calibrate.build_page 组装；calibrate 功能缺失时
        返回 None，_build_engine 的挂载段自带 try/except 会跳过校准分段。
        """
        if self._calib_page is None:
            try:
                from features import registry
                self._calib_page = registry().service(
                    "calibrate", "build_page")(self.app, self)
            except Exception as _e:  # noqa: BLE001
                _perf_note(f"字幕校准页不可用（不影响工作台其它分段）：{_e}")
                return None
        return self._calib_page

    # ---------- 预热（消除首次进入卡顿） ----------
    def prewarm_import_only(self):
        """只预热 import，**不登记界面构建**（2026-11-14 启动修复）。

        启动期不再自动建工作台（见 MainWindow.__init__ 中 prewarm 那段的说明），
        但可以趁用户还没点进来，把引擎模块的 import 在后台线程先做掉。import
        不碰主线程（只抢 GIL，且 main() 已把切换间隔压到 1ms），用户首次进入
        「字幕处理」时只需付纯构造的代价（热态实测 0.36s）。

        与 :meth:`prewarm` 的区别：这里**不登记** ``prewarm_done`` /
        ``build_engine``，界面构建仍然只在页面真正显示时发生。
        """
        if self._built:
            return
        # 已因用户进入页面而起了预热线程：不要重复记日志，也不要另起一份
        # （两个预热线程互抢 GIL，实测导入会从 3s 劣化到 20s）。
        if _ENGINE_PREWARM["thread"] is not None:
            return
        _perf_note("prewarm_import_only() 被调用（起线程，不建界面）")
        self._prewarm_thread = _start_engine_prewarm()

    def prewarm(self):
        """空闲时预导入引擎模块。

        卡顿的根因有三块，v1.11.0 起逐条拆掉：
          1. `videocaptioner.core.utils.cache` 在模块级建 5 个 diskcache 库
             （每个约 0.9s）——已在 prepare_runtime_env 里用惰性代理消除；
          2. `videocaptioner.ui.view.home_interface` 依赖树（qtawesome 图标
             字体、platformdirs、transcribe/llm 子模块、vlc 探测）首次 import；
             本预热把它丢到后台线程完成（Python 的 import 锁让主线程的后续
             import 命中缓存）；
          3. 界面构造本身（引擎界面 30 多张卡片）。第 2 步完成后自动回主线程
             构建，做到「用户点进来时已是现成控件」。
        设置界面（setting_interface）不在这里预热：它属于设置页，由设置页
        自己懒加载，避免白等一份当前用不到的导入。
        """
        if self._built or self._prewarming:
            return
        _perf_note("prewarm() 被调用（起线程）")
        self._prewarming = True
        # 2026-10-20 第三波：统一走**模块级**预热线程（幂等）。本方法可能
        # 先于 main() 的 _defer_after_show 到达（QTimer 注册顺序），所以这里
        # 自己负责起线程——但绝不另起第二份导入：实测两个预热线程互抢 GIL，
        # 导入从 3.0s 劣化到 19.97s。
        self._prewarm_thread = _start_engine_prewarm()
        # 2026-10-21（启动调度专项）：不再 200ms 自轮询。交给调度器：
        #   · prewarm_done —— 探针任务，线程未结束就返回 False，64ms 后重问；
        #   · build_engine —— 依赖 prewarm_done，满足后回主线程构建，
        #     单帧预算 400ms（实测 HomeInterface 0.13s + 引擎界面 0.26s）。
        # 好处：完成瞬间即被感知（不再被 200ms 栅格拖后），且不再每轮写日志。
        _defer("prewarm_done", _engine_prewarm_probe, 0, 3, budget_ms=1)
        _defer("build_engine", self._build_when_ready, 0, 30,
               depends_on=("prewarm_done",), budget_ms=400)

    def _build_when_ready(self):
        """预热结束后的主线程构建（调度器任务体，见 prewarm）。"""
        if self._built:
            return True
        # 界面模块已就绪即可构建（后端 ASR 补丁可能还在跑，见 ui_ready 说明）
        self._prewarm_ready = bool(_ENGINE_PREWARM["ok"]
                                   or _ENGINE_PREWARM["ui_ready"])
        self._build_now("正在准备字幕引擎界面 …")
        return True

    def _wait_prewarm(self):
        """旧版 200ms 自轮询（2026-10-21 起由调度器的 prewarm_done 接管）。

        保留仅作兼容兜底：外部脚本/自检若显式调用仍能工作。
        """
        t = getattr(self, "_prewarm_thread", None)
        if t is not None and t.is_alive():
            QTimer.singleShot(200, self._wait_prewarm)
            return
        if self._built:
            return
        self._prewarm_ready = bool(_ENGINE_PREWARM["ok"])
        self._build_now("正在准备字幕引擎界面 …")

    # ---------- 构建 ----------
    def _build_engine(self):
        """创建并内嵌字幕工作台；隐藏品牌水印与捐助入口。

        v1.21.0（P3 引擎自研化）：默认使用自研 UI 包 ``vt_engine_ui``，其各页已把
        原先的 UI 视觉/交互补丁内建为显式逻辑；构造失败时自动回退引擎 UI。走自研
        路径时不再挂 ``engine_ui_brand_patch`` / ``vc_transcribe_ui_patch``（那些是
        打在引擎类上的运行期补丁，自研页无需），但**后端**协议补丁照挂。
        """
        HomeInterface, _setting_cls, is_self, ui_err = _resolve_engine_ui()
        if ui_err:
            _perf_note(f"自研 UI 不可用，回退引擎：{ui_err}")
        if HomeInterface is None:
            self.state_label.setText("字幕引擎加载失败：无可用 UI 实现")
            _perf_note("字幕引擎 import 失败：home_cls=None")
            return None
        if not is_self:
            # 引擎路径：品牌中性化 + 转录 UI 补丁（类级，须在实例化前挂上）
            engine.engine_ui_brand_patch()   # 用户可见文案中性化（见 docs\ 声明）
            # v1.14.1：转录下拉收敛「默认/ASR」+ 独立转录完成回填「字幕翻译」
            try:
                engine.vc_transcribe_ui_patch()
            except Exception as e:  # noqa: BLE001
                # 别再静默：UI 补丁一旦失败，协议补丁（在它的 ⑤ 里挂）就跟着
                # 没了，表现为"百炼端点被拿去打 /audio/transcriptions 而断连"
                try:
                    engine._vc_log(f"转录 UI 补丁失败：{e}")
                except Exception:  # noqa: BLE001
                    pass
        # 协议补丁独立再挂一次（幂等）：它才是"走哪条协议"的决定因素（后端，两条路径都要）
        try:
            engine.vc_asr_protocol_patch()
        except Exception:  # noqa: BLE001
            pass
        t0 = time.perf_counter()
        try:
            home = HomeInterface()
        except Exception as e:  # noqa: BLE001
            if not is_self:
                self.state_label.setText(f"字幕引擎加载失败：{e}")
                _perf_note(f"HomeInterface 构造失败：{e}")
                return None
            # 自研构造失败 → 回退引擎，界面绝不能打不开
            _perf_note(f"自研 HomeInterface 构造失败，回退引擎：{e}")
            try:
                engine._vc_log(f"自研 UI 构造失败，回退引擎：{e}")
            except Exception:  # noqa: BLE001
                pass
            try:
                from videocaptioner.ui.view.home_interface import HomeInterface as _EH
                engine.engine_ui_brand_patch()
                engine.vc_transcribe_ui_patch()
            except Exception as e2:  # noqa: BLE001
                self.state_label.setText(f"字幕引擎加载失败：{e2}")
                return None
            home = _EH()
        _perf_note(f"HomeInterface 构造：{time.perf_counter() - t0:.2f}s"
                   f"（{'自研' if is_self else '引擎'}）")
        # v1.12.0：工作台优化——
        #   · 隐藏「字幕校正」按钮（校准类功能统一到「字幕校准」板块）；
        #   · 收紧主布局间距、字幕表格吃满剩余空间（调整页面比例）。
        sub_if = getattr(home, "subtitle_optimization_interface", None)
        if sub_if is not None:
            opt_btn = getattr(sub_if, "optimize_button", None)
            cmd_bar = getattr(sub_if, "command_bar", None)
            if opt_btn is not None and cmd_bar is not None:
                # optimize_button 是 QAction（非 QWidget），从命令栏移除；
                # CommandBar.removeAction 只删按钮不清 actions 列表，
                # 再补一次 QWidget 基类的 removeAction 把 action 摘干净
                cmd_bar.removeAction(opt_btn)
                try:
                    from PySide6.QtWidgets import QWidget as _QW
                    _QW.removeAction(cmd_bar, opt_btn)
                except Exception:
                    pass
            lay = getattr(sub_if, "main_layout", None)
            table = getattr(sub_if, "subtitle_table", None)
            if lay is not None:
                lay.setSpacing(10)
                if table is not None:
                    lay.setStretch(lay.indexOf(table), 1)
        # 引擎自带白色页面背景，内嵌到深色宿主里改为透明、随主题配色
        home.setStyleSheet("HomeInterface{background:transparent;}")
        # v1.13.0：引擎工作台分段项「字幕优化与翻译」更名「字幕翻译」
        try:
            home.pivot.setItemText("SubtitleInterface", "字幕翻译")
        except Exception:  # noqa: BLE001
            pass
        # v2.1.0：彻底摘掉「字幕视频合成」分段——用户要求「去掉这块多余内容，
        # 剩下三个平铺」。合成能力早已并入「字幕编辑」页的「内嵌字幕」入口。
        #
        # ⚠ 这里**不能只调** ``pivot.removeWidget()``：它内部是
        # ``items.pop`` + ``hBoxLayout.removeWidget`` + ``item.deleteLater()``，
        # 而 ``QLayout.removeWidget`` **只解除布局管理、不隐藏控件**，控件在
        # 被真正 delete 之前仍会照常绘制（用户截图里那个孤立残留的
        # 「字幕视频合成」小块就是这么来的）。所以额外显式 hide 一次。
        try:
            syn = getattr(home, "video_synthesis_interface", None)
            if syn is not None:
                try:
                    home.subtitle_optimization_interface.finished.disconnect(
                        home.switch_to_video_synthesis)
                except Exception:  # noqa: BLE001
                    pass
                # 兜底：万一还有别的路径调过来，也不该切到一个已摘掉的页面
                home.switch_to_video_synthesis = lambda *a, **k: None
                item = home.pivot.items.get("VideoSynthesisInterface")
                if item is not None:
                    item.hide()
                home.pivot.removeWidget("VideoSynthesisInterface")
                # removeWidget 内部是 deleteLater()，**延迟**到事件循环才真正
                # 销毁；在那之前它仍是 SegmentedWidget 的子控件（多出一个
                # sibling 下标，且仍有一帧绘制）。立即脱父，顺带彻底切断
                # 残留来源，也与自研路径（构造期就 setParent(None)）结构一致。
                if item is not None:
                    item.setParent(None)
                home.stackedWidget.removeWidget(syn)
                syn.hide()
                syn.setParent(None)
        except Exception:  # noqa: BLE001
            pass
        tc = getattr(home, "task_creation_interface", None)
        if tc is not None:
            self.wire_task_creation(tc, lambda: home)
            # v2.1.0：「任务创建」已提为应用首页 ⇒ 工作台**构建时就永久摘除**
            # 该分段——**不能**依赖 adopt 的时机或成败（用户实机出现过分段
            # 仍在的情况，原因难追，必须结构性保证）。摘掉后 tc 成为孤儿
            # （引用仍挂在 home 上），随后 adopt 把它认领到首页；即使 adopt
            # 没跑，工作台也绝无这个分段。
            #   · pivot 项：hide → removeWidget → setParent(None)（三件套，
            #     原因同上「字幕视频合成」：QLayout.removeWidget 不隐藏控件）；
            #   · 堆叠页：removeWidget（会顺手 hide，正好）。
            try:
                # ⚠ 摘除前先把当前页切走：构造期当前页就是 tc 本身，
                # 直接 removeWidget 会让 currentIndex 自动落到「语音转录」，
                # 引擎回退路径的转录页 showEvent 会 **lazy 创建第二个
                # RoundMenu**（自研页无此 lazy）⇒ golden 结构比对失衡，
                # 且引擎路径下用户会凭空看到一次转录页闪现。
                home.stackedWidget.setCurrentWidget(
                    home.subtitle_optimization_interface)
                _item = home.pivot.items.get("TaskCreationInterface")
                if _item is not None:
                    _item.hide()
                home.pivot.removeWidget("TaskCreationInterface")
                if _item is not None:
                    _item.setParent(None)
                home.stackedWidget.removeWidget(tc)
                # 摘掉首段后堆叠/分段的当前项可能悬空，落到第一个存在的分段
                if home.stackedWidget.count():
                    _first = home.stackedWidget.widget(0)
                    home.stackedWidget.setCurrentWidget(_first)
                    home.pivot.setCurrentItem(_first.objectName())
            except Exception as e:  # noqa: BLE001
                _perf_note(f"工作台摘除任务创建分段失败：{e}")
        # v1.13.0：把「字幕校准」并入引擎工作台分段，排在工作台「字幕翻译」
        # 之后（用户要求：校准并入「字幕翻译排」）。只加引擎界面 + 分段项，
        # 不改动引擎本体的处理流程。
        try:
            self.calib_page.setObjectName("CalibrationInterface")
            home.stackedWidget.addWidget(self.calib_page)
            keys = list(home.pivot.items.keys())
            if "SubtitleInterface" in keys:
                idx = keys.index("SubtitleInterface") + 1
            else:
                idx = -1   # 没找到「字幕翻译」时追加到末尾
            home.pivot.insertItem(
                idx, "CalibrationInterface", "字幕校准",
                onClick=lambda: home.stackedWidget.setCurrentWidget(
                    self.calib_page))
        except Exception:  # noqa: BLE001
            pass
        # v2.1.0：三个分段**平铺**这件事**不需要任何额外干预**——
        # ``Pivot.insertWidget`` 内部就是 ``hBoxLayout.insertWidget(idx, w, 1)``，
        # stretch=1，SegmentedWidget 又随外层容器同宽扩张，三项自然等宽均分
        # （实测 252/253/252@757）。曾在这里加过一套「setAlignment /
        # setSizePolicy(Expanding) / setSizeConstraint(0)」，负向验证
        # （``_negtest_synth_tabs.py`` N2：整段撤掉）证明撤掉后几何**一模一样**
        # ⇒ 属多余代码，已删。教训：别凭"看起来该这么配"加设置，
        # 先用负向验证证明它是必要的。
        #
        # ⚠ 但若将来真要加分段边距：**绝不能设在 SegmentedWidget 自身上**——
        # 它的 paintEvent 用 ``item.rect().adjusted(1,1,-1,-1).translated(
        # slideAni,0)`` 画选中底框，完全无视布局 y；一旦加上下边距，
        # 选中框会和文字错位。要留白就加在外层容器（HomeInterface 的
        # vBoxLayout）上。
        self._engine_home = home
        return home

    def wire_task_creation(self, tc, home_getter=None):
        """给「任务创建」控件做实例整形 + 信号接线（幂等）。

        首页在预热之前就构造独立的 TaskCreationInterface（见
        ``HomePage.ensure_task_creation``），因此接线不能再只放在
        ``_build_engine`` 里；这里成为唯一入口。``home_getter`` 延迟解析
        工作台实例——首页早期它可能还是 None。
        """
        if tc is None or getattr(tc, "_vt_wired", False):
            return
        try:
            tc._vt_wired = True
        except Exception:  # noqa: BLE001
            pass
        for attr in ("info_label", "donate_button"):
            w = getattr(tc, attr, None)
            if w is not None:
                w.hide()

        def _home():
            try:
                return home_getter() if callable(home_getter) else None
            except Exception:  # noqa: BLE001
                return None

        # 工作台的 HomeInterface 构造时把 finished 接到了 switch_to_transcription；
        # 首页接管后必须断开，改走宿主自己的类型分派。
        try:
            home = _home()
            if home is not None:
                tc.finished.disconnect(home.switch_to_transcription)
        except Exception:  # noqa: BLE001
            pass
        try:
            tc.finished.connect(
                lambda fp: self._dispatch_created_task(_home(), fp))
        except Exception as e:  # noqa: BLE001
            _perf_note(f"任务创建页分派接线失败：{e}")
        # v1.16.4：任务创建页原本只收音视频，拖 .srt 会弹「格式错误」。
        # 字幕本就是本工作台的合法输入，这里放宽接收（见工厂函数说明）。
        try:
            tc.dropEvent = make_task_creation_drop_handler(tc)
        except Exception as e:  # noqa: BLE001
            _perf_note(f"任务创建页字幕接收补丁失败：{e}")
        # v2.1.0：识别到网页链接 → 跳「视频处理 / 视频下载」。
        try:
            sig = getattr(tc, "url_detected", None)
            if sig is not None:
                sig.connect(self.app.goto_video_download)
        except Exception as e:  # noqa: BLE001
            _perf_note(f"任务创建页链接跳转接线失败：{e}")
        # v2.1.0：harness 就绪时，纯文本输入 → AI 托管。
        try:
            sig = getattr(tc, "ai_requested", None)
            if sig is not None:
                sig.connect(self._on_ai_requested)
        except Exception as e:  # noqa: BLE001
            _perf_note(f"任务创建页 AI 托管接线失败：{e}")

    def _on_ai_requested(self, text):
        """首页任务框识别到「纯文本」→ 交给 AI 托管页执行（v2.1.0）。

        只在 harness 就绪时才会收到这个信号（发送方判过 ``available()``）；
        宿主没建 AI 托管页（harness 不在场）时这里是静默 no-op。
        """
        try:
            win = self.app if hasattr(self, "app") else self.window()
            goto = getattr(win, "goto_ai_console", None)
            if goto is not None:
                goto(text)
        except Exception as e:  # noqa: BLE001
            _perf_note(f"AI 托管跳转失败：{e}")

    def _dispatch_created_task(self, home, file_path):
        """任务创建完成后**按文件类型**跳转到对应工作台（见 _build_engine 说明）。

        · 视频 / 音频           → 语音转录（引擎原行为）；
        · 单语字幕（无中文对照） → 字幕翻译；
        · 双语字幕（中英对照）   → 字幕校准。

        v2.1.0：任务创建已提为**首页**，用户此刻停在首页而不是工作台内，
        所以每次分派都要先把宿主窗口切到「字幕处理」——否则分段切了、
        窗口还停在首页，用户看到的是"点了没反应"。
        """
        path = str(file_path or "")
        if home is None:
            home = getattr(self, "_engine_home", None)
        if home is None:
            # 首页任务框现在先于引擎预热就绪（2026-10-23 启动专项）。
            # 此时用户已经给了文件：切到字幕处理页显示占位，等工作台构建完
            # 再自动续跑，绝不在主线程同步等 6～18 秒的导入。
            self._pending_dispatch = path
            self._reveal_workbench()
            try:
                self.state_label.setText("正在准备字幕引擎，就绪后自动继续 …")
            except Exception:  # noqa: BLE001
                pass
            self.ensure_built()
            return
        ext = os.path.splitext(path)[1].lower()
        self._reveal_workbench()
        if ext not in SUBTITLE_EXTS:
            home.switch_to_transcription(path)
            return
        if subtitle_looks_bilingual(path):
            self.calib_page.accept_subtitle(path)
            self.switch_to_calib()
        else:
            self._open_subtitle_translate(home, path)

    def _reveal_workbench(self):
        """把宿主窗口切到「字幕处理」页（工作台所在的导航页）。"""
        try:
            win = self.window()
            if getattr(win, "stackedWidget", None) is not None:
                cur = win.stackedWidget.currentWidget()
                if cur is not self:
                    win.switchTo(self)
        except Exception as e:  # noqa: BLE001
            _perf_note(f"切到字幕处理页失败：{e}")

    def _open_subtitle_translate(self, home, sub_path):
        """把字幕送进引擎「字幕翻译」页并切过去。

        字幕没有配套视频，`video_path` 传 None（引擎的 `create_subtitle_task`
        本来就允许）；task_id 沿用 home 当前的，保持同一条任务链。
        """
        try:
            # 走自研工厂：命名会剥掉应用自己的【字幕】前缀，避免叠成双层
            from engine_task_factory import TaskFactory
            task = TaskFactory.create_subtitle_task(
                sub_path, None, need_next_task=True,
                task_id=getattr(home, "_current_task_id", "") or "")
            home.subtitle_optimization_interface.set_task(task)
            home.pivot.setCurrentItem("SubtitleInterface")
            home.stackedWidget.setCurrentWidget(
                home.subtitle_optimization_interface)
        except Exception as e:  # noqa: BLE001
            _perf_note(f"跳转字幕翻译失败：{e}")
            # 兜底：切不过去就退回引擎原行为，至少别把用户卡在任务创建页
            try:
                home.switch_to_transcription(sub_path)
            except Exception:  # noqa: BLE001
                pass

    def switch_to_calib(self):
        """外部跳转：切到引擎工作台的「字幕校准」子页（拖拽定位/截图用）。"""
        home = getattr(self, "_engine_home", None)
        if home is None:
            return
        try:
            home.pivot.setCurrentItem("CalibrationInterface")
            home.stackedWidget.setCurrentWidget(self.calib_page)
        except Exception:  # noqa: BLE001
            pass

    def calib_active(self):
        """当前是否停在「字幕校准」子页（引擎工作台分段的当前项）。

        供主窗口的全局拖放分派器判断：用户在校准页上拖字幕时，拖到本页
        之外的位置（页面边缘、导航条）也应就地填入校准输入框，而不是跳页。
        """
        home = getattr(self, "_engine_home", None)
        if home is None:
            return False
        try:
            return home.stackedWidget.currentWidget() is self.calib_page
        except Exception:  # noqa: BLE001
            return False

    def active_segment(self):
        """引擎工作台当前在前台的分段控件；未构建返回 None（不触发构建）。"""
        home = getattr(self, "_engine_home", None)
        if home is None:
            return None
        try:
            return home.stackedWidget.currentWidget()
        except Exception:  # noqa: BLE001
            return None

    def claim_dropped_media(self, paths):
        """全局兜底分派：本页在前台时按当前分段认领视频/音频。

        与 v1.16.4 字幕按当前页分流同一原则——拖到页面之外（边缘/导航条）
        应与拖在页内行为一致，而不是一律跳「字幕编辑」：
          · 语音转录分段 → 就地载入待转录（与页内 dropEvent 同路径）；
          · 其余分段（字幕翻译/校准等）不认领视频/音频，交回全局默认路由
            （与各分段自身 dropEvent 对视频的行为一致）。
        任务创建分段已搬去首页（adopt），由主窗口首页分支处理。
        返回 True = 已消费。
        """
        home = getattr(self, "_engine_home", None)
        if home is None:
            return False
        seg = self.active_segment()
        if seg is None:
            return False
        files = [p for p in (engine.clean_path(x) for x in (paths or []))
                 if p and os.path.isfile(p)]
        if not files:
            return False
        try:
            if seg is home.transcription_interface:
                return bool(home.transcription_interface.import_dropped_files(files))
        except Exception as e:  # noqa: BLE001
            _perf_note(f"转录分段认领拖放失败：{e}")
        return False

    def _build_now(self, busy_text):
        if self._built:
            return
        self._built = True
        # 引擎工作台可能含 SpinBox：补丁必须先于它存在（幂等，通常早已装好）
        _install_spinbox_fix_once()
        self._build_t0 = time.perf_counter()
        if busy_text:
            self.state_label.setText(busy_text)
            # 2026-11-14：先把「正在准备…」推到屏幕上再进构建。整段构建实测可达
            # 30s 级且全程占着主线程，没有这一步用户只会看到上一个页面的残帧，
            # 体感是「点进来先死一下」。
            try:
                QApplication.processEvents()
            except Exception:  # noqa: BLE001
                pass
        # 2026-11-14：构建拆成三段，段与段之间回一次事件循环。
        # 冷缓存下整段实测可达 33–42s（logs\startup.log 2026-11-12/11-14），
        # 一段做完期间窗口会被系统判成「未响应」；分段后每次连续占用短一截，
        # 用户也还能在间隙里切回别的页面。热态下三段合计仍是 0.6s 量级。
        self.state_label.setText("正在准备字幕引擎界面 …（1/3 构建控件）")
        QTimer.singleShot(0, self._build_stage_engine)

    def _build_stage_engine(self):
        """第 1/3 段：构造引擎工作台（HomeInterface + 整形）。"""
        t0 = self._build_t0
        try:
            self._engine = self._build_engine()
        except Exception as e:  # noqa: BLE001
            _perf_note(f"工作台构建异常：{e}")
            self._engine = None
        _perf_note("工作台[1/3 构建控件] %.2fs（返回 %s）"
                   % (time.perf_counter() - t0,
                      "None" if self._engine is None else "ok"))
        if self._engine is None:
            self.state_label.setText("字幕引擎加载失败，详见 logs\\startup.log")
            return
        self.state_label.setText("正在准备字幕引擎界面 …（2/3 并入页面）")
        QTimer.singleShot(0, self._build_stage_mount)

    def _build_stage_mount(self):
        """第 2/3 段：把工作台塞进宿主布局（首次 polish/布局最贵的一段）。"""
        t0 = self._build_t0
        try:
            self.host_lay.addWidget(self._engine)
        except Exception as e:  # noqa: BLE001
            _perf_note(f"工作台装箱失败：{e}")
            return
        _perf_note("工作台[2/3 并入页面] %.2fs" % (time.perf_counter() - t0))
        self.state_label.setText("正在准备字幕引擎界面 …（3/3 收尾）")
        QTimer.singleShot(0, self._build_stage_adopt)

    def _build_stage_adopt(self):
        """第 3/3 段：任务创建移交首页、运行期配置、状态行、导航收敛。"""
        t0 = self._build_t0
        # v2.1.0：任务创建分段已提升为应用首页（见 HomePage）。把它从工作台
        # 摘出来交给首页——**必须在 addWidget 到本页之后**，否则首页先拿到
        # 控件、工作台随后又把同一个控件 addWidget 一次，Qt 只会保留最后一次。
        try:
            win = self.window()
            hp = getattr(win, "home_page", None)
            if hp is not None:
                hp.adopt(self._engine)
                # 首页若已在预热前建好任务框，工作台自带的那个就是孤儿：
                # 它已从分段/堆叠摘除，这里直接销毁，避免重复信号源。
                orphan = getattr(self._engine, "task_creation_interface", None)
                if (orphan is not None and hp.task_creation is not None
                        and orphan is not hp.task_creation):
                    orphan.deleteLater()
        except Exception as e:  # noqa: BLE001
            _perf_note(f"任务创建页移交首页失败：{e}")
        # 引擎 QConfig 已随 HomeInterface 导入并读盘，再做一次运行期兜底：
        # 强制工作目录等收敛到软件文件夹（防止历史 C 盘值在内存里复活）
        try:
            engine.vc_enforce_runtime_cfg()
        except Exception:
            pass
        self.state_label.setText("字幕引擎已就绪（内嵌运行，无需联网下载模型）")
        # v1.12.0：引擎就绪后收起底部状态行（打开设置/许可走导航栏），
        # 把页面高度全部让给工作台（调整页面比例）
        self.foot.hide()
        # 首页在预热前收下的文件：等界面真正并入主树后再续跑分派。
        pending = self._pending_dispatch
        self._pending_dispatch = None
        if pending:
            QTimer.singleShot(
                0, lambda p=pending: self._dispatch_created_task(self._engine, p))
        # 引擎界面（自带字体）进来后，导航宽度重新按宿主的统一口径收敛一次
        try:
            self.window().refresh_nav_width()
        except Exception:
            pass
        _perf_note(f"字幕引擎界面构建完成：{time.perf_counter() - t0:.2f}s"
                   f"（预热 {'已就绪' if self._prewarm_ready else '未完成'}，"
                   f"三段构建）")

        # 引擎界面刚并入主树。
        # 2026-10-21（启动调度专项）：这里原本挂一个「空闲时分片扫全树、预热
        # 主题色小表」的任务（更早是 singleShot(300) 一次性全量，首次 ≈1.8s）。
        # 实测**两头都不划算**：
        #   · 分片版每片 200 个控件在冷缓存下仍要 200ms+，连跑 10 余轮 →
        #     UI 心跳探针在首帧后 3–6s 持续报「主线程被占用」，正是用户说的
        #     「刚进来点不动」；
        #   · 而它想预热的东西其实**已经被预热了**——`_PlainAccentFilter`
        #     在每次 Polish（首绘前）就算过 plain_accent_qss，缓存本就是热的，
        #     用户第一次改主题色不会再有 1.8s。
        # 故直接移除，不再启动期扫全树。改主题色时 set_accent() 里的全量刷新
        # 仍在（缓存热态 ~30ms），语义不变。

    def showEvent(self, event):
        """首次显示时才加载引擎界面（内嵌 QWidget，随主题自动配色）。

        2026-10-20：**不在主线程同步导入**引擎 UI 树（openai 6.2s +
        qfluentwidgets 2.8s + ASR 链，合计 ≈14s，整窗冻死）。改为起预热
        线程、显示占位文案，由 _wait_prewarm 在后台导入完成后回主线程构建
        ——界面全程可响应，用户可先去别的页。
        """
        super().showEvent(event)
        if self._built:
            return
        self.state_label.setText("正在准备字幕引擎界面 …")
        self.ensure_built()

    def ensure_built(self):
        """确保工作台已构建（幂等）——供首页在启动时提前触发。

        v2.1.0：任务创建成为应用默认落地页，构建时机从「用户点进本页」
        提前到「首页首次显示」。预热线程仍在跑时不等它（:meth:`_wait_prewarm`
        会在预热结束后自行构建），直接返回即可。

        2026-10-20 第四波（启动 <5s 专项）：**绝不在 show() 的同步路径里
        起导入线程**。原实现经 HomePage.showEvent → ensure_built → prewarm()
        在 window.show() 内部就把 CPU 密集的引擎导入线程拉起来，首帧 paint
        （posted 事件）随后在事件循环里与导入线程抢 GIL——实测窗口可见
        从亚秒劣化到 10s 级（整链 25.8s 的直接根因）。改为只挂号
        singleShot(0)：show() 返回、首帧 paint 落定之后才起线程。
        """
        if self._built:
            return
        if self._prewarming:
            # 预热线程在跑：用户可能已经点进本页 → 把相关任务插到队首，
            # 预热一结束立刻构建（而不是排在库页/自动化页后面）。
            s = _SCHED["inst"]
            if s is not None:
                s.run_now("prewarm_done", priority=0)
                s.run_now("build_engine", priority=0)
            return
        _defer("prewarm_kick", self.prewarm, 0, 5, budget_ms=5)

    def open_settings(self):
        """跳到唯一的全局设置页，并定位到字幕引擎参数区。

        v1.10.8 起不再保留独立引擎设置对话框：所有设置（含 LLM、保存位置）
        都在主设置页这一处。
        """
        win = self.window()
        try:
            if hasattr(win, "open_engine_settings"):
                win.open_engine_settings()
        except Exception:  # noqa: BLE001
            pass

    def show_license(self):
        if os.path.isfile(engine.VC_LICENSE_FILE):
            try:
                os.startfile(engine.VC_LICENSE_FILE)     # noqa: S606
                return
            except OSError:
                pass
        MessageBox("第三方组件许可与来源",
                   "本工具内置第三方开源字幕引擎，其许可全文与来源声明见安装目录 "
                   "docs/ 下的 VideoCaptioner_GPL-3.0.txt 与 VideoCaptioner_组件来源.txt。",
                   self).exec()


def build_page(app, parent=None):
    """注册表 GuiSpec.builder 入口（workbench 功能页，常驻真身 lazy=False）。"""
    return SubtitlePage(app, parent)