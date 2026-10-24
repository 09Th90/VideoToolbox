# -*- coding: utf-8 -*-
# @version 2.6.0
"""转录 UI 补丁（下拉收敛「默认/ASR」+ 独立转录完成回填「字幕翻译」）（v2.3.1 拆分工程 · 自 video_toolbox.py 原样搬入）。

v2.3.1 拆分工程；域间依赖规则见 core/__init__.py。
"""

from core.asr.engine_config import apply_asr_to_engine
from core.asr.patches import vc_asr_protocol_patch
from core.asr.voiceprint import (TM_DISPLAY_ASR, TM_DISPLAY_DEFAULT, voiceprint_enabled_names, voiceprint_filter_subtitle)
from core.shared.ai import ai_load_config, ai_mod
from core.shared.log import _vc_log

import os

def vc_transcribe_ui_patch():
    """工作台转录下拉收敛为「默认 / ASR」+ 独立转录完成回填「字幕翻译」。

    v1.14.1 用户需求，全部运行期补丁（引擎 site-packages 保持原版）：
      ① 命令栏转录模型菜单只建「默认 / ASR」两项——J 接口 / FasterWhisper /
         WhisperCpp / Whisper [API] 不再出现；
      ② 选「ASR」时实时调 apply_asr_to_engine()（以全局设置「ASR 语音识别」
         卡片为准，按 asr_mode 落到 Whisper [API] / FasterWhisper）；
         选「默认」时落回 B 接口；历史残留取值一并收敛；
      ③ 引擎转录页自带的 Whisper API / FasterWhisper 配置块随下拉收敛
         不再可达（重复入口，从根上消除「与全局设置不一致」的两张页面），
         空位留一行提示；
      ④ 在转录页单独转录（拖入媒体，need_next_task=False）完成后，引擎原
         逻辑不做任何事——这里把生成的字幕装载进「字幕翻译」并自动切换
         过去（不自动开跑优化/翻译，等用户按「开始」）。
    幂等；必须在 HomeInterface 导入之后、实例构造之前调用。
    """
    try:
        from videocaptioner.ui.view import transcription_interface as ti
        from videocaptioner.ui.components import transcription_setting_card as tsc
        from engine_entities import TranscribeModelEnum
        from videocaptioner.ui.common.config import cfg as _cfg
        from vt_fluent import (Action, BodyLabel, FluentIcon, InfoBar,
                               InfoBarPosition, PushButton, RoundMenu)
        from PySide6.QtWidgets import QVBoxLayout as _QVBox
    except Exception as e:  # noqa: BLE001
        _vc_log(f"转录 UI 补丁导入失败：{e}")
        return False
    if getattr(ti, "_vt_transcribe_ui_patched", False):
        return True

    def _asr_not_ready():
        """全局 ASR 是否还没配好（用于给出设置指引提示）。"""
        try:
            ac = ai_mod().asr_config(ai_load_config())
            if ac.get("mode") == "local":
                return not (ac.get("local_model") or ac.get("local_model_dir"))
            return not (ac.get("base_url") and ac.get("api_key"))
        except Exception:  # noqa: BLE001
            return False

    def _asr_missing_hint():
        """**已保存的**配置里缺什么 —— 说清楚，用户才知道该改哪一格。

        ⚠️ 读的是磁盘配置（不是界面输入框）：实测最常踩的坑是"设置页填好了
        但没点「保存并应用」"，这时磁盘上还是旧值/空值，转录页就说未配置。
        """
        try:
            ac = ai_mod().asr_config(ai_load_config())
            if ac.get("mode") == "local":
                if not (ac.get("local_model") or ac.get("local_model_dir")):
                    return "本地模式还没填模型名或目录"
                return ""
            miss = []
            if not ac.get("base_url"):
                miss.append("接口地址")
            if not ac.get("api_key"):
                miss.append("密钥")
            return ("已保存的配置里缺：" + "、".join(miss)) if miss else ""
        except Exception:  # noqa: BLE001
            return ""

    # ① 命令栏菜单：只留「默认 / ASR」
    orig_setup_bar = ti.TranscriptionInterface._setup_command_bar

    def _setup_command_bar(self):
        orig_setup_bar(self)
        try:
            menu = RoundMenu(parent=self)
            menu.addActions([
                Action(FluentIcon.GLOBE, TM_DISPLAY_DEFAULT),
                Action(FluentIcon.MICROPHONE, TM_DISPLAY_ASR),
            ])
            self.model_menu = menu          # _setup_signals 遍历的是这个菜单
            self.model_button.setMenu(menu)
        except Exception:  # noqa: BLE001
            pass

    ti.TranscriptionInterface._setup_command_bar = _setup_command_bar

    # ② 模型切换：显示名 ↔ 引擎枚举映射
    def _on_model_changed(self, model_name: str):
        # 防重入：cfg 信号 → 本槽 → cfg 信号 的环路在此截断
        if getattr(self, "_vt_model_busy", False):
            return
        try:
            asr_values = (TranscribeModelEnum.WHISPER_API.value,
                          TranscribeModelEnum.FASTER_WHISPER.value)
            if model_name == TM_DISPLAY_ASR:
                # 用户点了「ASR」：以全局「ASR 语音识别」设置为准实时同步
                self._vt_model_busy = True
                try:
                    self.model_button.setText(TM_DISPLAY_ASR)
                    self.transcription_setting_card.on_model_changed(
                        TM_DISPLAY_ASR)
                    ok, detail = apply_asr_to_engine()
                    if not ok:
                        _vc_log(f"ASR 应用失败：{detail}")
                    if _asr_not_ready():
                        InfoBar.warning(
                            "ASR 未配置",
                            ("%s；" % _asr_missing_hint() if _asr_missing_hint()
                             else "")
                            + "请到 设置 → ASR 语音识别 填好后点「保存并应用」"
                              "（只填不保存不生效）",
                            duration=8000, parent=self.window())
                finally:
                    self._vt_model_busy = False
                return
            if model_name == TM_DISPLAY_DEFAULT:
                # 用户点了「默认」：落回 B 接口
                self._vt_model_busy = True
                try:
                    self.model_button.setText(TM_DISPLAY_DEFAULT)
                    self.transcription_setting_card.on_model_changed(
                        TM_DISPLAY_DEFAULT)
                    _cfg.set(_cfg.transcribe_model, TranscribeModelEnum.BIJIAN)
                finally:
                    self._vt_model_busy = False
                return
            # 其余为启动恢复/signalBus 广播（传引擎枚举值）：只做显示映射，
            # 不回写配置，避免构造期触发配置环路
            if model_name in asr_values:
                self.model_button.setText(TM_DISPLAY_ASR)
                self.transcription_setting_card.on_model_changed(TM_DISPLAY_ASR)
            else:
                # 「B 接口」及被移除的历史取值（J 接口/WhisperCpp）→ 显示「默认」
                self.model_button.setText(TM_DISPLAY_DEFAULT)
                self.transcription_setting_card.on_model_changed(
                    TM_DISPLAY_DEFAULT)
                if model_name != TranscribeModelEnum.BIJIAN.value:
                    self._vt_model_busy = True
                    try:
                        _cfg.set(_cfg.transcribe_model,
                                 TranscribeModelEnum.BIJIAN)
                    finally:
                        self._vt_model_busy = False
        except Exception as e:  # noqa: BLE001
            self._vt_model_busy = False
            _vc_log(f"转录模型切换异常：{e}")

    ti.TranscriptionInterface.on_transcription_model_changed = _on_model_changed

    # ③ 独立转录完成 → 回填「字幕翻译」
    orig_finished = ti.TranscriptionInterface._on_transcript_finished

    def _home_of(widget):
        """沿 parent 链向上找 HomeInterface（判定标准：持有字幕翻译子界面）。

        ⚠️ 不能用 `self.parent()`：HomeInterface 构造时把各子界面
        `stackedWidget.addWidget(...)`，Qt 会顺手把父级改成那个
        QStackedWidget，于是 parent() 返回的是容器而不是 HomeInterface，
        `getattr(home, "subtitle_optimization_interface", None)` 恒为 None，
        整段回填被静默跳过（v1.14.1「转录完不自动跳字幕翻译」的根因）。
        这里逐级向上找，并以属性为准而非类名，宿主层级怎么改都不会再失联。
        """
        w = widget
        while w is not None:
            if getattr(w, "subtitle_optimization_interface", None) is not None:
                return w
            w = w.parent()
        # 兜底：宿主窗口里扫一遍（parent 链被重挂接打断时仍能找到）
        try:
            from PySide6.QtWidgets import QApplication, QWidget as _QWidget
            for tl in QApplication.topLevelWidgets():
                if getattr(tl, "subtitle_optimization_interface", None) is not None:
                    return tl
                for ch in tl.findChildren(_QWidget):
                    if getattr(ch, "subtitle_optimization_interface",
                               None) is not None:
                        return ch
        except Exception:  # noqa: BLE001
            pass
        return None

    def _produced_subtitle(path):
        """定位转录产物：引擎按 output_format 落盘（base_path + 实际后缀），
        task.output_path 的后缀未必等于真实文件名，这里按同基名补齐。"""
        if not path:
            return None
        try:
            if os.path.isfile(path):
                return path
            base = os.path.splitext(path)[0]
            for ext in (".srt", ".ass", ".vtt"):
                cand = base + ext
                if os.path.isfile(cand):
                    return cand
            # 输出格式设成「全部」等自定义后缀时，同目录同基名的字幕文件
            d, stem = os.path.split(base)
            if os.path.isdir(d):
                for name in sorted(os.listdir(d)):
                    low = name.lower()
                    if (name.startswith(stem + ".")
                            and low.endswith((".srt", ".ass", ".vtt"))):
                        return os.path.join(d, name)
        except Exception:  # noqa: BLE001
            pass
        return None

    def _start_voiceprint_filter(iface, out, media, then):
        """后台跑声纹筛选，完成后回调 `then()`；返回是否已接管流程。

        ⚠ 用 QThread 而非同步调用：实测 18 分钟素材「解码 + 提 275 段声纹 +
        聚类打分」约 27 秒，同步跑会把界面冻住（用户会以为卡死）。
        ⚠ worker 必须挂在 iface 上防 GC——局部变量出作用域就被回收，线程会被
        连带销毁，表现为"进度条一闪、什么都没发生"。
        """
        try:
            # ⚠ `Signal` 必须在这里导入：本补丁函数只 import 了
            #   QVBoxLayout / BodyLabel 等，没带 Signal。漏了会抛
            #   `name 'Signal' is not defined`，而它被外层 try 吞进
            #   logs\vc_fallback.log —— 界面上表现就是"什么都没发生"
            #   （v1.18.0 实测踩过：转录完既不筛也不提示）。
            from PySide6.QtCore import QThread as _QThread
            from PySide6.QtCore import Signal as _Signal
        except Exception:  # noqa: BLE001
            return False

        parent = _home_of(iface) or iface.window()
        try:
            bar = InfoBar.info(
                "正在按声纹筛选", "只保留主播台词，请稍候（长片约需半分钟）…",
                duration=-1, position=InfoBarPosition.BOTTOM, parent=parent)
        except Exception:  # noqa: BLE001
            bar = None

        class _VpWorker(_QThread):
            done = _Signal(object)

            def run(self):
                try:
                    r = voiceprint_filter_subtitle(out, media)
                except Exception as e:  # noqa: BLE001
                    _vc_log(f"声纹筛选失败：{e}")
                    r = {"error": str(e)}
                self.done.emit(r)

        def _finish(res):
            try:
                if bar is not None:
                    bar.close()
            except Exception:  # noqa: BLE001
                pass
            try:
                if isinstance(res, dict) and res.get("error"):
                    InfoBar.error("声纹筛选失败",
                                  str(res["error"])[:200] + "\n字幕已保留未筛选版本",
                                  duration=9000,
                                  position=InfoBarPosition.BOTTOM, parent=parent)
                elif res is None:
                    InfoBar.warning(
                        "声纹筛选未执行",
                        "声纹模型还没下载：到「语音转录 → 主播声纹」点「下载模型」",
                        duration=8000,
                        position=InfoBarPosition.BOTTOM, parent=parent)
                else:
                    InfoBar.success(
                        "声纹筛选完成",
                        "保留 %d 条（其中存疑 %d）/ 丢弃 %d；原件已备份为「%s」"
                        % (res["kept_total"], res["review"], res["drop"],
                           os.path.basename(res.get("backup") or "")),
                        duration=9000,
                        position=InfoBarPosition.BOTTOM, parent=parent)
            except Exception:  # noqa: BLE001
                pass
            try:
                then()
            except Exception as e:  # noqa: BLE001
                _vc_log(f"声纹筛选后回填异常：{e}")

        w = _VpWorker()
        w.done.connect(_finish)
        iface._vt_vp_worker = w          # 防 GC
        w.start()
        return True

    def _vt_filter_current_subtitle(iface):
        """对「字幕翻译」页**当前加载的字幕**套用声纹筛选，完了刷新表格。

        为什么需要这个手动入口：自动筛选只在「转录完成」时触发，而用户完全可能
        （a）走的是别的路径、（b）直接打开一份旧字幕、（c）想换个阈值再筛一次
        ——总不能每次都重转录（费时又费 ASR 额度）。有了它，任何来源的字幕都能筛。
        """
        path = getattr(iface, "subtitle_path", None)
        media = getattr(getattr(iface, "task", None), "video_path", None)
        if not path or not os.path.isfile(path):
            InfoBar.warning("没有可筛选的字幕", "请先加载字幕文件",
                            duration=5000, position=InfoBarPosition.BOTTOM,
                            parent=iface)
            return
        if not media or not os.path.isfile(media):
            InfoBar.warning(
                "缺少配套视频",
                "声纹筛选要从原视频/音频里取声音，当前字幕没有关联的媒体文件",
                duration=7000, position=InfoBarPosition.BOTTOM, parent=iface)
            return
        if not voiceprint_enabled_names():
            InfoBar.warning(
                "没有启用声纹",
                "到「语音转录 → 主播声纹」勾选要保留的声音（可多选）",
                duration=7000, position=InfoBarPosition.BOTTOM, parent=iface)
            return
        # 先把表格里的编辑写回文件——与引擎 `start_subtitle_optimization` 同款，
        # 否则筛选会连带丢掉用户在表格里做的合并 / 删除 / 编辑。
        try:
            from engine_asr_data import ASRData
            if getattr(getattr(iface, "model", None), "_data", None):
                ASRData.from_json(iface.model._data).to_srt(save_path=path)
        except Exception as e:  # noqa: BLE001
            _vc_log(f"筛选前回写表格失败（忽略，继续筛）：{e}")

        def _after():
            try:
                iface.load_subtitle_file(path)      # 刷新表格为筛选后的内容
            except Exception as e:  # noqa: BLE001
                _vc_log(f"筛选后刷新表格失败：{e}")

        if not _start_voiceprint_filter(iface, path, media, _after):
            _after()

    def _on_transcript_finished(self, task):
        # ⚠️⚠️ 入口先复位「处理中」标记（v1.15.7 修复）。
        # 引擎原生 _on_transcript_finished 的第一件事就是 is_processing=False，
        # 而下面的成功分支会 return、不再回调 orig_finished ⇒ 该标记永久停在
        # True：字幕明明已落盘、卡片按钮已是「转录完成」，但拖拽换视频被拦
        # 「正在处理中，请等待当前任务完成」，start_button 也被禁用（update_info
        # 见 is_processing=True 就 setEnabled(False)）⇒ 既中止不了也换不了视频。
        # 此处无条件复位（orig_finished 里那次复位是幂等的，重复无害）。
        self.is_processing = False
        try:
            if task is not None and not getattr(task, "need_next_task", False):
                out = _produced_subtitle(getattr(task, "output_path", None))
                media = getattr(task, "file_path", None)

                def _handoff():
                    """把产物字幕装载到「字幕翻译」并切过去（原 ③ 的跳转）。"""
                    home = _home_of(self) if out else None
                    sub = (getattr(home, "subtitle_optimization_interface", None)
                           if home is not None else None)
                    if sub is None:
                        if out:
                            _vc_log("独立转录完成，但未定位到工作台首页，"
                                    "回退引擎原逻辑")
                        return False
                    from videocaptioner.ui.task_factory import TaskFactory
                    st = TaskFactory.create_subtitle_task(
                        out, media, need_next_task=False,
                        task_id=getattr(home, "_current_task_id", None))
                    sub.set_task(st)
                    # 切到「字幕翻译」并让分段控件同步高亮（原生跳转同款两连）
                    home.stackedWidget.setCurrentWidget(sub)
                    home.pivot.setCurrentItem("SubtitleInterface")
                    _vc_log(f"独立转录完成 → 已装载「字幕翻译」：{out}")
                    InfoBar.success(
                        "转录完成",
                        "生成的字幕已装载到「字幕翻译」，可直接开始优化 / 翻译",
                        duration=5000,
                        position=InfoBarPosition.BOTTOM,
                        parent=home)
                    return True

                # ⑥ 主播声纹（v1.18.0）：启用了声纹就先筛，**筛完再回填字幕翻译**
                #    ——顺序不能反：字幕翻译要拿筛过的字幕，否则翻译出来还是多人。
                #    ⚠ 必须走后台线程：18 分钟的片子解码+提声纹要二三十秒，同步跑
                #    会把主线程（也就是整个界面）冻住。
                if out and voiceprint_enabled_names():
                    if _start_voiceprint_filter(self, out, media, _handoff):
                        return
                if _handoff():
                    return
        except Exception as e:  # noqa: BLE001
            _vc_log(f"转录完成回填异常：{e}")
        orig_finished(self, task)

    ti.TranscriptionInterface._on_transcript_finished = _on_transcript_finished

    # ③-B 陈旧「处理中」自愈（v1.15.7 兜底）——根因已在 ③ 修掉，这里防历史
    #      残留与其它路径把标记卡死（例如线程异常退出、任务创建页派发后中断）。
    #      判据：标记为 True 但转录线程不存在 / 已不在运行 ⇒ 判为陈旧，清标记
    #      并复位卡片按钮，然后照常放行拖拽与「打开文件」。
    def _vt_heal_stale(self):
        """陈旧「处理中」自愈；返回是否真的发生了自愈。"""
        if not getattr(self, "is_processing", False):
            return False
        card = getattr(self, "video_info_card", None)
        th = (getattr(card, "transcript_thread", None)
              if card is not None else None)
        if th is not None:
            try:
                if th.isRunning():
                    return False        # 真在跑：保持拦截，不误放行
            except Exception:  # noqa: BLE001
                return False
        self.is_processing = False
        try:
            if card is not None:
                card.reset_ui()         # 文案→「开始转录」并解除禁用
        except Exception:  # noqa: BLE001
            pass
        _vc_log("转录页陈旧「处理中」状态已自愈（无运行中的转录线程）")
        return True

    ti.TranscriptionInterface._vt_heal_stale = _vt_heal_stale

    def _heal_guard(orig):
        """在两个用户入口前先跑一次自愈，其后完全保持原行为。"""
        def _wrapped(self, *args, **kwargs):
            try:
                self._vt_heal_stale()
            except Exception:  # noqa: BLE001
                pass
            return orig(self, *args, **kwargs)
        return _wrapped

    ti.TranscriptionInterface.dropEvent = _heal_guard(
        ti.TranscriptionInterface.dropEvent)
    ti.TranscriptionInterface._on_file_select = _heal_guard(
        ti.TranscriptionInterface._on_file_select)

    # ④ 转录设置卡片空位提示（默认/ASR 都不再展示引擎内置 ASR 配置块）
    #    + ⑥ 主播声纹录入卡（v1.18.0）：本页 `empty_widget` 是默认显示的空白
    #    区，正好用来放声纹录入——不新增页面，用户也不用另找入口。
    orig_card_init = tsc.TranscriptionSettingCard.__init__

    def _card_init(self, parent=None):
        orig_card_init(self, parent)
        try:
            lay = _QVBox(self.empty_widget)
            lay.setContentsMargins(24, 4, 24, 4)
            tip = BodyLabel(
                "默认：内置免费语音识别；ASR：使用设置页「ASR 语音识别」的模型"
                "（自有服务 / 本地模型），统一在全局设置中维护",
                self.empty_widget)
            tip.setStyleSheet("color: #8a8a8a;")
            tip.setWordWrap(True)   # 窄窗口下不换行会被裁掉右半句
            lay.addWidget(tip)
            try:
                from speaker_voiceprint_page import VoiceprintEnrollCard
                self.vt_voiceprint_card = VoiceprintEnrollCard(self.empty_widget)
                lay.addWidget(self.vt_voiceprint_card)
            except Exception as e:  # noqa: BLE001
                _vc_log(f"声纹录入卡挂载失败：{e}")
            lay.addStretch(1)
        except Exception:  # noqa: BLE001
            pass

    tsc.TranscriptionSettingCard.__init__ = _card_init

    # ⑦ 转录设置弹窗加「主播声纹（可多选）」（v1.18.0）
    #    勾选即写入 data/voiceprint/selection.json；多选 = 并集语义。
    try:
        from videocaptioner.ui.components.TranscriptionSettingDialog import (
            TranscriptionSettingDialog as _VTSettingDialog)
        from speaker_voiceprint_page import VoiceprintPicker

        _orig_dlg_init = _VTSettingDialog.__init__

        def _dlg_init(self, parent=None):
            _orig_dlg_init(self, parent)
            try:
                self.vt_voiceprint_picker = VoiceprintPicker(self)
                self.viewLayout.addWidget(self.vt_voiceprint_picker)
            except Exception as e:  # noqa: BLE001
                _vc_log(f"声纹多选器挂载失败：{e}")

        _VTSettingDialog.__init__ = _dlg_init
    except Exception as e:  # noqa: BLE001
        _vc_log(f"转录设置弹窗声纹补丁未挂：{e}")

    # ⑧ 任务创建路径的声纹筛选（v1.18.0）
    #    ⚠⚠ 引擎的 `TranscriptionInterface._on_transcript_finished` **只在
    #    `need_next_task=True` 时**才 `self.finished.emit(...)`；而补丁 ③ 挂的是
    #    `not need_next_task`（「独立转录」）那一支 ⇒ **走「任务创建」的用户筛选
    #    完全不生效**（2026-10-09 实测踩过：转录产物 275 条原样没筛，用户看到
    #    "还是混杂"）。这里把另一条路也挂上——它的落点是
    #    `HomeInterface.switch_to_subtitle_optimization(file_path, video_path)`。
    try:
        from videocaptioner.ui.view.home_interface import (
            HomeInterface as _VT_HOME)
        _orig_switch_sub = _VT_HOME.switch_to_subtitle_optimization

        def _switch_sub(self, file_path, video_path):
            if voiceprint_enabled_names() and _start_voiceprint_filter(
                    self, file_path, video_path,
                    lambda: _orig_switch_sub(self, file_path, video_path)):
                return
            return _orig_switch_sub(self, file_path, video_path)

        _VT_HOME.switch_to_subtitle_optimization = _switch_sub
    except Exception as e:  # noqa: BLE001
        _vc_log(f"任务创建路径的声纹筛选补丁未挂：{e}")

    # ⑨ 「字幕翻译」页加「按声纹筛选」按钮（v1.18.0）
    #    自动筛选只在「转录完成」时触发；用户完全可能直接打开一份旧字幕、或想
    #    换个阈值再筛一次——总不能每次重转录。给个手动入口，任何来源都能筛。
    try:
        from videocaptioner.ui.view.subtitle_interface import (
            SubtitleInterface as _VT_SubIface)
        _orig_sub_init = _VT_SubIface.__init__

        def _sub_init(self, parent=None):
            _orig_sub_init(self, parent)
            try:
                btn = PushButton("按声纹筛选", self)
                btn.setToolTip("按已启用的主播声纹过滤当前字幕"
                               "（原件自动备份为 *_未筛选.srt）")
                btn.clicked.connect(lambda: _vt_filter_current_subtitle(self))
                self.command_bar.addWidget(btn)
                self._vt_vp_button = btn
            except Exception as e:  # noqa: BLE001
                _vc_log(f"字幕翻译页声纹按钮挂载失败：{e}")

        _VT_SubIface.__init__ = _sub_init
    except Exception as e:  # noqa: BLE001
        _vc_log(f"字幕翻译页声纹补丁未挂：{e}")

    # ⑤ ASR 服务模式多协议适配（auto / openai / azure / dashscope）
    try:
        vc_asr_protocol_patch()
    except Exception:  # noqa: BLE001
        pass

    ti._vt_transcribe_ui_patched = True
    _vc_log("转录 UI 补丁已挂：下拉=默认/ASR，独立转录完成回填「字幕翻译」")
    return True




__all__ = [
    "vc_transcribe_ui_patch",
]
