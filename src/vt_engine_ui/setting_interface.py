# -*- coding: utf-8 -*-
# @version 2.2.5
"""自研「设置」页（对齐引擎 SettingInterface 的原始结构）。

本类**忠实复现引擎设置页的原始控件树**（同名分组/卡片、同顺序、同标题、同样式
表、同 ``resize(1000, 800)`` 与视口边距）。宿主 ``_ensure_engine_setting`` 会对
其做既有的实例级整形（隐藏 llm/save/personal/about/transcribe 分组、合并翻译
分组、拍平内层视口……）——那段整形代码保持不变，作用在同名同构的控件上，因而
最终可见 GUI 与替换前逐像素一致。

后端（配置项、连接自检线程调用的 core.llm / cache）经 ``_seams`` 取值，属档 B。
"""
from __future__ import annotations

import webbrowser

from PySide6.QtCore import Qt, QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QFileDialog, QLabel, QWidget
from qfluentwidgets import (
    ComboBoxSettingCard,
    CustomColorSettingCard,
    ExpandLayout,
    HyperlinkCard,
    InfoBar,
    OptionsSettingCard,
    PrimaryPushSettingCard,
    PushSettingCard,
    RangeSettingCard,
    ScrollArea,
    SettingCardGroup,
    SwitchSettingCard,
    setTheme,
    setThemeColor,
)
from qfluentwidgets import FluentIcon as FIF

from . import _seams
from .components import EditComboBoxSettingCard, LineEditSettingCard


class SettingInterface(ScrollArea):
    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setWindowTitle(self.tr("设置"))
        self.scrollWidget = QWidget()
        self.expandLayout = ExpandLayout(self.scrollWidget)
        self.settingLabel = QLabel(self.tr("设置"), self)

        self.__initGroups()
        self.__initCards()
        self.__initWidget()
        self.__initLayout()
        self.__connectSignalToSlot()

    # ---------------- groups ----------------
    def __initGroups(self):
        self.transcribeGroup = SettingCardGroup(self.tr("转录配置"), self.scrollWidget)
        self.llmGroup = SettingCardGroup(self.tr("LLM配置"), self.scrollWidget)
        self.translate_serviceGroup = SettingCardGroup(self.tr("翻译服务"), self.scrollWidget)
        self.translateGroup = SettingCardGroup(self.tr("翻译与优化"), self.scrollWidget)
        self.subtitleGroup = SettingCardGroup(self.tr("字幕合成配置"), self.scrollWidget)
        self.saveGroup = SettingCardGroup(self.tr("保存配置"), self.scrollWidget)
        self.personalGroup = SettingCardGroup(self.tr("个性化"), self.scrollWidget)
        self.aboutGroup = SettingCardGroup(self.tr("关于"), self.scrollWidget)

    # ---------------- cards ----------------
    def __initCards(self):
        cfg = _seams.cfg
        self.__createASRServiceCards()
        self.__createLLMServiceCards()
        self.__createTranslateServiceCards()

        self.subtitleCorrectCard = SwitchSettingCard(
            FIF.EDIT, self.tr("字幕校正"),
            self.tr("字幕处理过程是否对生成的字幕错别字、名词等进行校正"),
            cfg.need_optimize, self.translateGroup)
        self.subtitleTranslateCard = SwitchSettingCard(
            FIF.LANGUAGE, self.tr("字幕翻译"),
            self.tr("字幕处理过程是否对生成的字幕进行翻译"),
            cfg.need_translate, self.translateGroup)
        self.targetLanguageCard = ComboBoxSettingCard(
            cfg.target_language, FIF.LANGUAGE, self.tr("目标语言"),
            self.tr("选择翻译字幕的目标语言"),
            texts=[lang.value for lang in cfg.target_language.validator.options],
            parent=self.translateGroup)

        self.subtitleStyleCard = HyperlinkCard(
            "", self.tr("修改"), FIF.FONT, self.tr("字幕样式"),
            self.tr("选择字幕的样式（颜色、大小、字体等）"), self.subtitleGroup)
        self.subtitleLayoutCard = HyperlinkCard(
            "", self.tr("修改"), FIF.FONT, self.tr("字幕布局"),
            self.tr("选择字幕的布局（单语、双语）"), self.subtitleGroup)
        self.needVideoCard = SwitchSettingCard(
            FIF.VIDEO, self.tr("需要合成视频"),
            self.tr("开启时触发合成视频，关闭时跳过"), cfg.need_video, self.subtitleGroup)
        self.softSubtitleCard = SwitchSettingCard(
            FIF.FONT, self.tr("软字幕"),
            self.tr("开启时字幕可在播放器中关闭或调整，关闭时字幕烧录到视频画面上"),
            cfg.soft_subtitle, self.subtitleGroup)
        self.videoQualityCard = ComboBoxSettingCard(
            cfg.video_quality, FIF.SPEED_HIGH, self.tr("视频合成质量"),
            self.tr("硬字幕视频合成时的质量等级（质量越高文件越大，编码时间越长）"),
            texts=[q.value for q in cfg.video_quality.validator.options],
            parent=self.subtitleGroup)

        self.savePathCard = PushSettingCard(
            self.tr("工作文件夹"), FIF.SAVE, self.tr("工作目录路径"),
            cfg.get(cfg.work_dir), self.saveGroup)

        self.cacheEnabledCard = SwitchSettingCard(
            FIF.HISTORY, self.tr("启用缓存"),
            self.tr("相同配置下会复用之前的 ASR 和 LLM 结果；关闭缓存后每次重新生成"),
            cfg.cache_enabled, self.personalGroup)
        self.themeCard = OptionsSettingCard(
            cfg.themeMode, FIF.BRUSH, self.tr("应用主题"),
            self.tr("更改应用程序的外观"),
            texts=[self.tr("浅色"), self.tr("深色"), self.tr("使用系统设置")],
            parent=self.personalGroup)
        self.themeColorCard = CustomColorSettingCard(
            cfg.themeColor, FIF.PALETTE, self.tr("主题颜色"),
            self.tr("更改应用程序的主题颜色"), self.personalGroup)
        self.zoomCard = OptionsSettingCard(
            cfg.dpiScale, FIF.ZOOM, self.tr("界面缩放"),
            self.tr("更改小部件和字体的大小"),
            texts=["100%", "125%", "150%", "175%", "200%", self.tr("使用系统设置")],
            parent=self.personalGroup)
        self.languageCard = ComboBoxSettingCard(
            cfg.language, FIF.LANGUAGE, self.tr("语言"),
            self.tr("设置您偏好的界面语言"),
            texts=["简体中文", "繁體中文", "English", self.tr("使用系统设置")],
            parent=self.personalGroup)

        vcc = _seams.vc_config
        self.helpCard = HyperlinkCard(
            vcc.HELP_URL, self.tr("打开帮助页面"), FIF.HELP, self.tr("帮助"),
            self.tr("发现新功能并了解有关VideoCaptioner的使用技巧"), self.aboutGroup)
        self.feedbackCard = PrimaryPushSettingCard(
            self.tr("提供反馈"), FIF.FEEDBACK, self.tr("提供反馈"),
            self.tr("提供反馈帮助我们改进VideoCaptioner"), self.aboutGroup)
        self.aboutCard = PrimaryPushSettingCard(
            self.tr("检查更新"), FIF.INFO, self.tr("关于"),
            "© " + self.tr("版权所有") + f" {vcc.YEAR}, {vcc.AUTHOR}. "
            + self.tr("版本") + " " + vcc.VERSION, self.aboutGroup)

        self.translateGroup.addSettingCard(self.subtitleCorrectCard)
        self.translateGroup.addSettingCard(self.subtitleTranslateCard)
        self.translateGroup.addSettingCard(self.targetLanguageCard)

        self.subtitleGroup.addSettingCard(self.subtitleStyleCard)
        self.subtitleGroup.addSettingCard(self.subtitleLayoutCard)
        self.subtitleGroup.addSettingCard(self.needVideoCard)
        self.subtitleGroup.addSettingCard(self.softSubtitleCard)
        self.subtitleGroup.addSettingCard(self.videoQualityCard)

        self.saveGroup.addSettingCard(self.savePathCard)
        self.saveGroup.addSettingCard(self.cacheEnabledCard)

        self.personalGroup.addSettingCard(self.themeCard)
        self.personalGroup.addSettingCard(self.themeColorCard)
        self.personalGroup.addSettingCard(self.zoomCard)
        self.personalGroup.addSettingCard(self.languageCard)

        self.aboutGroup.addSettingCard(self.helpCard)
        self.aboutGroup.addSettingCard(self.feedbackCard)
        self.aboutGroup.addSettingCard(self.aboutCard)

    def __createLLMServiceCards(self):
        cfg = _seams.cfg
        LLMServiceEnum = _seams.entities.LLMServiceEnum
        self.llmServiceCard = ComboBoxSettingCard(
            cfg.llm_service, FIF.ROBOT, self.tr("LLM 提供商"),
            self.tr("选择大模型提供商，用于字幕断句、优化、翻译"),
            texts=[s.value for s in cfg.llm_service.validator.options], parent=self.llmGroup)
        self.llmServiceCard.comboBox.setMinimumWidth(150)

        self.openaiOfficialApiCard = HyperlinkCard(
            "https://api.videocaptioner.cn/register?aff=UrLB", self.tr("访问"),
            FIF.DEVELOPER_TOOLS, self.tr("VideoCaptioner 官方API"),
            self.tr("集成多种大语言模型，支持高并发字幕优化、翻译"), self.llmGroup)
        self.openaiOfficialApiCard.setVisible(False)

        service_configs = {
            LLMServiceEnum.OPENAI: {
                "prefix": "openai", "api_key_cfg": cfg.openai_api_key,
                "api_base_cfg": cfg.openai_api_base, "model_cfg": cfg.openai_model,
                "default_base": "https://api.openai.com/v1",
                "default_models": ["gemini-2.5-pro", "gpt-5",
                                   "claude-sonnet-4-5-20250929", "gemini-2.5-flash",
                                   "claude-haiku-4-5-20251001"]},
            LLMServiceEnum.SILICON_CLOUD: {
                "prefix": "silicon_cloud", "api_key_cfg": cfg.silicon_cloud_api_key,
                "api_base_cfg": cfg.silicon_cloud_api_base, "model_cfg": cfg.silicon_cloud_model,
                "default_base": "https://api.siliconflow.cn/v1",
                "default_models": ["moonshotai/Kimi-K2-Instruct-0905", "deepseek-ai/DeepSeek-V3"]},
            LLMServiceEnum.DEEPSEEK: {
                "prefix": "deepseek", "api_key_cfg": cfg.deepseek_api_key,
                "api_base_cfg": cfg.deepseek_api_base, "model_cfg": cfg.deepseek_model,
                "default_base": "https://api.deepseek.com/v1",
                "default_models": ["deepseek-chat", "deepseek-reasoner"]},
            LLMServiceEnum.OLLAMA: {
                "prefix": "ollama", "api_key_cfg": cfg.ollama_api_key,
                "api_base_cfg": cfg.ollama_api_base, "model_cfg": cfg.ollama_model,
                "default_base": "http://localhost:11434/v1", "default_models": ["qwen3:8b"]},
            LLMServiceEnum.LM_STUDIO: {
                "prefix": "LM Studio", "api_key_cfg": cfg.lm_studio_api_key,
                "api_base_cfg": cfg.lm_studio_api_base, "model_cfg": cfg.lm_studio_model,
                "default_base": "http://127.0.0.1:1234/v1", "default_models": ["qwen3:8b"]},
            LLMServiceEnum.GEMINI: {
                "prefix": "gemini", "api_key_cfg": cfg.gemini_api_key,
                "api_base_cfg": cfg.gemini_api_base, "model_cfg": cfg.gemini_model,
                "default_base": "https://generativelanguage.googleapis.com/v1beta/openai/",
                "default_models": ["gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.0-flash-lite"]},
            LLMServiceEnum.CHATGLM: {
                "prefix": "chatglm", "api_key_cfg": cfg.chatglm_api_key,
                "api_base_cfg": cfg.chatglm_api_base, "model_cfg": cfg.chatglm_model,
                "default_base": "https://open.bigmodel.cn/api/paas/v4",
                "default_models": ["glm-4-plus", "glm-4-air-250414", "glm-4-flash"]},
        }

        self.llm_service_configs = {}
        for service, config in service_configs.items():
            prefix = config["prefix"]
            api_key_card = LineEditSettingCard(
                config["api_key_cfg"], FIF.FINGERPRINT, self.tr("API Key"),
                self.tr(f"输入您的 {service.value} API Key"),
                "sk-" if service != LLMServiceEnum.OLLAMA else "", self.llmGroup)
            setattr(self, f"{prefix}_api_key_card", api_key_card)
            api_base_card = LineEditSettingCard(
                config["api_base_cfg"], FIF.LINK, self.tr("Base URL"),
                self.tr(f"输入 {service.value} Base URL"), config["default_base"], self.llmGroup)
            setattr(self, f"{prefix}_api_base_card", api_base_card)
            if service not in [LLMServiceEnum.OPENAI, LLMServiceEnum.OLLAMA, LLMServiceEnum.LM_STUDIO]:
                api_base_card.lineEdit.setReadOnly(True)
            model_card = EditComboBoxSettingCard(
                config["model_cfg"], FIF.ROBOT, self.tr("模型"),
                self.tr(f"选择 {service.value} 模型"), config["default_models"], self.llmGroup)
            setattr(self, f"{prefix}_model_card", model_card)
            cards = [api_key_card, api_base_card, model_card]
            self.llm_service_configs[service] = {
                "cards": cards, "api_base": api_base_card,
                "api_key": api_key_card, "model": model_card}

        self.checkLLMConnectionCard = PushSettingCard(
            self.tr("检查连接"), FIF.LINK, self.tr("检查 LLM 连接"),
            self.tr("点击检查 API 连接是否正常，并获取模型列表"), self.llmGroup)
        self.__onLLMServiceChanged(self.llmServiceCard.comboBox.currentText())

    def __createASRServiceCards(self):
        cfg = _seams.cfg
        self.transcribeModelCard = ComboBoxSettingCard(
            cfg.transcribe_model, FIF.MICROPHONE, self.tr("转录模型"),
            self.tr("语音转换文字要使用的语音识别服务"),
            texts=[m.value for m in cfg.transcribe_model.validator.options],
            parent=self.transcribeGroup)
        self.transcribeModelCard.comboBox.setMinimumWidth(150)
        self.whisperApiBaseCard = LineEditSettingCard(
            cfg.whisper_api_base, FIF.LINK, self.tr("Whisper API Base URL"),
            self.tr("输入 Whisper API Base URL"), "https://api.openai.com/v1", self.transcribeGroup)
        self.whisperApiKeyCard = LineEditSettingCard(
            cfg.whisper_api_key, FIF.FINGERPRINT, self.tr("Whisper API Key"),
            self.tr("输入 Whisper API Key"), "sk-", self.transcribeGroup)
        self.whisperApiModelCard = EditComboBoxSettingCard(
            cfg.whisper_api_model, FIF.ROBOT, self.tr("Whisper 模型"),
            self.tr("选择 Whisper 模型"), ["whisper-1", "whisper-large-v3-turbo"], self.transcribeGroup)
        self.checkWhisperConnectionCard = PushSettingCard(
            self.tr("测试 Whisper 连接"), FIF.CONNECT, self.tr("测试 Whisper API 连接"),
            self.tr("点击测试 API 连接是否正常"), self.transcribeGroup)
        self.whisperApiBaseCard.setVisible(False)
        self.whisperApiKeyCard.setVisible(False)
        self.whisperApiModelCard.setVisible(False)
        self.checkWhisperConnectionCard.setVisible(False)

    def __createTranslateServiceCards(self):
        cfg = _seams.cfg
        self.translatorServiceCard = ComboBoxSettingCard(
            cfg.translator_service, FIF.ROBOT, self.tr("翻译服务"), self.tr("选择翻译服务"),
            texts=[s.value for s in cfg.translator_service.validator.options],
            parent=self.translate_serviceGroup)
        self.translatorServiceCard.comboBox.setMinimumWidth(150)
        self.needReflectTranslateCard = SwitchSettingCard(
            FIF.EDIT, self.tr("需要反思翻译"),
            self.tr("启用反思翻译可以提高翻译质量，但耗费更多时间和token"),
            cfg.need_reflect_translate, self.translate_serviceGroup)
        self.deeplxEndpointCard = LineEditSettingCard(
            cfg.deeplx_endpoint, FIF.LINK, self.tr("DeepLx 后端"),
            self.tr("输入 DeepLx 的后端地址(开启deeplx翻译时必填)"),
            "https://api.deeplx.org/translate", self.translate_serviceGroup)
        self.batchSizeCard = RangeSettingCard(
            cfg.batch_size, FIF.ALIGNMENT, self.tr("批处理大小"),
            self.tr("每批处理字幕的数量，建议为 10 的倍数"), parent=self.translate_serviceGroup)
        self.threadNumCard = RangeSettingCard(
            cfg.thread_num, FIF.SPEED_HIGH, self.tr("线程数"),
            self.tr("请求并行处理的数量，模型服务商允许的情况下建议尽可能大，数值越大速度越快"),
            parent=self.translate_serviceGroup)
        self.translate_serviceGroup.addSettingCard(self.translatorServiceCard)
        self.translate_serviceGroup.addSettingCard(self.needReflectTranslateCard)
        self.translate_serviceGroup.addSettingCard(self.deeplxEndpointCard)
        self.translate_serviceGroup.addSettingCard(self.batchSizeCard)
        self.translate_serviceGroup.addSettingCard(self.threadNumCard)
        self.__onTranslatorServiceChanged(self.translatorServiceCard.comboBox.currentText())

    # ---------------- widget / layout ----------------
    def __initWidget(self):
        self.resize(1000, 800)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setViewportMargins(0, 80, 0, 20)
        self.setWidget(self.scrollWidget)
        self.setWidgetResizable(True)
        self.setObjectName("settingInterface")
        self.scrollWidget.setObjectName("scrollWidget")
        self.settingLabel.setObjectName("settingLabel")
        self.__onTranscribeModelChanged(self.transcribeModelCard.comboBox.currentText())
        self.__onTranslatorServiceChanged(self.translatorServiceCard.comboBox.currentText())
        self.setStyleSheet(
            """
            SettingInterface, #scrollWidget {
                background-color: transparent;
            }
            QScrollArea {
                border: none;
                background-color: transparent;
            }
            QLabel#settingLabel {
                font: 33px 'Microsoft YaHei';
                background-color: transparent;
                color: white;
            }
        """)

    def __initLayout(self):
        self.settingLabel.move(36, 30)
        self.transcribeGroup.addSettingCard(self.transcribeModelCard)
        self.transcribeGroup.addSettingCard(self.whisperApiBaseCard)
        self.transcribeGroup.addSettingCard(self.whisperApiKeyCard)
        self.transcribeGroup.addSettingCard(self.whisperApiModelCard)
        self.transcribeGroup.addSettingCard(self.checkWhisperConnectionCard)

        self.llmGroup.addSettingCard(self.llmServiceCard)
        self.llmGroup.addSettingCard(self.openaiOfficialApiCard)
        for config in self.llm_service_configs.values():
            for card in config["cards"]:
                self.llmGroup.addSettingCard(card)
        self.llmGroup.addSettingCard(self.checkLLMConnectionCard)

        self.expandLayout.setSpacing(28)
        self.expandLayout.setContentsMargins(36, 10, 36, 0)
        self.expandLayout.addWidget(self.transcribeGroup)
        self.expandLayout.addWidget(self.llmGroup)
        self.expandLayout.addWidget(self.translate_serviceGroup)
        self.expandLayout.addWidget(self.translateGroup)
        self.expandLayout.addWidget(self.subtitleGroup)
        self.expandLayout.addWidget(self.saveGroup)
        self.expandLayout.addWidget(self.personalGroup)
        self.expandLayout.addWidget(self.aboutGroup)

    def __connectSignalToSlot(self):
        cfg = _seams.cfg
        sb = _seams.signal_bus
        cfg.appRestartSig.connect(self.__showRestartTooltip)
        self.llmServiceCard.comboBox.currentTextChanged.connect(self.__onLLMServiceChanged)
        self.translatorServiceCard.comboBox.currentTextChanged.connect(self.__onTranslatorServiceChanged)
        self.transcribeModelCard.comboBox.currentTextChanged.connect(self.__onTranscribeModelChanged)
        self.checkLLMConnectionCard.clicked.connect(self.checkLLMConnection)
        self.checkWhisperConnectionCard.clicked.connect(self.checkWhisperConnection)
        self.savePathCard.clicked.connect(self.__onsavePathCardClicked)
        self.subtitleStyleCard.linkButton.clicked.connect(
            lambda: self.window().switchTo(self.window().subtitleStyleInterface))
        self.subtitleLayoutCard.linkButton.clicked.connect(
            lambda: self.window().switchTo(self.window().subtitleStyleInterface))
        self.cacheEnabledCard.checkedChanged.connect(self.__onCacheEnabledChanged)
        self.themeCard.optionChanged.connect(lambda ci: setTheme(cfg.get(ci)))
        self.themeColorCard.colorChanged.connect(setThemeColor)
        self.feedbackCard.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(_seams.vc_config.FEEDBACK_URL)))
        self.aboutCard.clicked.connect(self.checkUpdate)
        self.transcribeModelCard.comboBox.currentTextChanged.connect(sb.transcription_model_changed)
        self.subtitleCorrectCard.checkedChanged.connect(sb.subtitle_optimization_changed)
        self.subtitleTranslateCard.checkedChanged.connect(sb.subtitle_translation_changed)
        self.targetLanguageCard.comboBox.currentTextChanged.connect(sb.target_language_changed)
        self.softSubtitleCard.checkedChanged.connect(sb.soft_subtitle_changed)
        self.needVideoCard.checkedChanged.connect(sb.need_video_changed)
        self.videoQualityCard.comboBox.currentTextChanged.connect(sb.video_quality_changed)

    # ---------------- slots ----------------
    def __showRestartTooltip(self):
        InfoBar.success(self.tr("更新成功"), self.tr("配置将在重启后生效"),
                        duration=_seams.constants.INFOBAR_DURATION_SUCCESS, parent=self)

    def __onsavePathCardClicked(self):
        cfg = _seams.cfg
        folder = QFileDialog.getExistingDirectory(self, self.tr("选择文件夹"), "./")
        if not folder or cfg.get(cfg.work_dir) == folder:
            return
        cfg.set(cfg.work_dir, folder)
        self.savePathCard.setContent(folder)

    def __onCacheEnabledChanged(self, is_enabled: bool):
        const = _seams.constants
        if is_enabled:
            _seams.core_cache.enable_cache()
            InfoBar.success(self.tr("缓存已启用"), self.tr("ASR、翻译等操作将优先使用缓存"),
                            duration=const.INFOBAR_DURATION_SUCCESS, parent=self)
        else:
            _seams.core_cache.disable_cache()
            InfoBar.warning(self.tr("缓存已禁用"),
                            self.tr("所有操作将重新生成，不使用缓存（建议开启缓存）"),
                            duration=const.INFOBAR_DURATION_WARNING, parent=self)

    def checkLLMConnection(self):
        LLMServiceEnum = _seams.entities.LLMServiceEnum
        scroll_position = self.verticalScrollBar().value()
        current_service = LLMServiceEnum(self.llmServiceCard.comboBox.currentText())
        service_config = self.llm_service_configs.get(current_service)
        if not service_config:
            return
        api_base = service_config["api_base"].lineEdit.text() if service_config["api_base"] else ""
        api_key = service_config["api_key"].lineEdit.text() if service_config["api_key"] else ""
        model = service_config["model"].comboBox.currentText() if service_config["model"] else ""
        self.checkLLMConnectionCard.button.setEnabled(False)
        self.checkLLMConnectionCard.button.setText(self.tr("正在检查..."))
        self.verticalScrollBar().setValue(scroll_position)
        self.connection_thread = LLMConnectionThread(api_base, api_key, model)
        self.connection_thread.finished.connect(self.onConnectionCheckFinished)
        self.connection_thread.error.connect(self.onConnectionCheckError)
        self.connection_thread.start()

    def onConnectionCheckError(self, message):
        self.checkLLMConnectionCard.button.setEnabled(True)
        self.checkLLMConnectionCard.button.setText(self.tr("检查连接"))
        InfoBar.error(self.tr("LLM 连接测试错误"), message,
                      duration=_seams.constants.INFOBAR_DURATION_ERROR, parent=self)

    def onConnectionCheckFinished(self, is_success, message, models):
        LLMServiceEnum = _seams.entities.LLMServiceEnum
        const = _seams.constants
        self.checkLLMConnectionCard.button.setEnabled(True)
        self.checkLLMConnectionCard.button.setText(self.tr("检查连接"))
        current_service = LLMServiceEnum(self.llmServiceCard.comboBox.currentText())
        if models:
            service_config = self.llm_service_configs.get(current_service)
            if service_config and service_config["model"]:
                temp = service_config["model"].comboBox.currentText()
                service_config["model"].setItems(models)
                service_config["model"].comboBox.setCurrentText(temp)
            InfoBar.success(self.tr("获取模型列表成功:"),
                            self.tr("一共") + str(len(models)) + self.tr("个模型"),
                            duration=const.INFOBAR_DURATION_SUCCESS, parent=self)
        if not is_success:
            InfoBar.error(self.tr("LLM 连接测试错误"), message,
                          duration=const.INFOBAR_DURATION_ERROR, parent=self)
        else:
            InfoBar.success(self.tr("LLM 连接测试成功"), message,
                            duration=const.INFOBAR_DURATION_SUCCESS, parent=self)

    def checkUpdate(self):
        webbrowser.open(_seams.vc_config.RELEASE_URL)

    def __onLLMServiceChanged(self, service):
        LLMServiceEnum = _seams.entities.LLMServiceEnum
        current_service = LLMServiceEnum(service)
        for config in self.llm_service_configs.values():
            for card in config["cards"]:
                card.setVisible(False)
        self.openaiOfficialApiCard.setVisible(False)
        if current_service in self.llm_service_configs:
            for card in self.llm_service_configs[current_service]["cards"]:
                card.setVisible(True)
            service_config = self.llm_service_configs[current_service]
            if current_service == LLMServiceEnum.OLLAMA and service_config["api_key"]:
                if not service_config["api_key"].lineEdit.text():
                    service_config["api_key"].lineEdit.setText("ollama")
            if current_service == LLMServiceEnum.LM_STUDIO and service_config["api_key"]:
                if not service_config["api_key"].lineEdit.text():
                    service_config["api_key"].lineEdit.setText("lm-studio")
            if current_service == LLMServiceEnum.OPENAI:
                self.openaiOfficialApiCard.setVisible(True)
        self.llmGroup.adjustSize()
        self.expandLayout.update()

    def __onTranslatorServiceChanged(self, service):
        TranslatorServiceEnum = _seams.entities.TranslatorServiceEnum
        openai_cards = [self.needReflectTranslateCard, self.batchSizeCard]
        deeplx_cards = [self.deeplxEndpointCard]
        for card in openai_cards + deeplx_cards:
            card.setVisible(False)
        if service in [TranslatorServiceEnum.DEEPLX.value]:
            for card in deeplx_cards:
                card.setVisible(True)
        elif service in [TranslatorServiceEnum.OPENAI.value]:
            for card in openai_cards:
                card.setVisible(True)
        self.translate_serviceGroup.adjustSize()
        self.expandLayout.update()

    def __onTranscribeModelChanged(self, model_name):
        TranscribeModelEnum = _seams.entities.TranscribeModelEnum
        whisper_api_cards = [self.whisperApiBaseCard, self.whisperApiKeyCard,
                             self.whisperApiModelCard, self.checkWhisperConnectionCard]
        is_whisper_api = model_name == TranscribeModelEnum.WHISPER_API.value
        for card in whisper_api_cards:
            card.setVisible(is_whisper_api)
        self.transcribeGroup.adjustSize()
        self.expandLayout.update()

    def checkWhisperConnection(self):
        const = _seams.constants
        scroll_position = self.verticalScrollBar().value()
        base_url = self.whisperApiBaseCard.lineEdit.text().strip()
        api_key = self.whisperApiKeyCard.lineEdit.text().strip()
        model = self.whisperApiModelCard.comboBox.currentText().strip()
        if not base_url:
            InfoBar.warning(self.tr("配置不完整"), self.tr("请输入 Whisper API Base URL"),
                            duration=const.INFOBAR_DURATION_ERROR, parent=self)
            return
        if not api_key:
            InfoBar.warning(self.tr("配置不完整"), self.tr("请输入 Whisper API Key"),
                            duration=const.INFOBAR_DURATION_ERROR, parent=self)
            return
        if not model:
            InfoBar.warning(self.tr("配置不完整"), self.tr("请输入 Whisper 模型名称"),
                            duration=const.INFOBAR_DURATION_ERROR, parent=self)
            return
        self.checkWhisperConnectionCard.button.setEnabled(False)
        self.checkWhisperConnectionCard.button.setText(self.tr("正在测试..."))
        self.verticalScrollBar().setValue(scroll_position)
        self.whisper_connection_thread = WhisperConnectionThread(base_url, api_key, model)
        self.whisper_connection_thread.finished.connect(self.onWhisperConnectionCheckFinished)
        self.whisper_connection_thread.error.connect(self.onWhisperConnectionCheckError)
        self.whisper_connection_thread.start()

    def onWhisperConnectionCheckFinished(self, success, result):
        const = _seams.constants
        self.checkWhisperConnectionCard.button.setEnabled(True)
        self.checkWhisperConnectionCard.button.setText(self.tr("测试 Whisper 连接"))
        if success:
            InfoBar.success(self.tr("连接成功"), self.tr("Whisper API 连接成功！\n转录结果:") + result,
                            duration=const.INFOBAR_DURATION_SUCCESS, parent=self)
        else:
            InfoBar.error(self.tr("连接失败"), self.tr(f"Whisper API 连接失败！\n{result}"),
                          duration=const.INFOBAR_DURATION_ERROR, parent=self)

    def onWhisperConnectionCheckError(self, message):
        self.checkWhisperConnectionCard.button.setEnabled(True)
        self.checkWhisperConnectionCard.button.setText(self.tr("测试 Whisper 连接"))
        InfoBar.error(self.tr("测试错误"), message,
                      duration=_seams.constants.INFOBAR_DURATION_ERROR, parent=self)


class WhisperConnectionThread(QThread):
    finished = Signal(bool, str)
    error = Signal(str)

    def __init__(self, base_url, api_key, model):
        super().__init__()
        self.base_url = base_url
        self.api_key = api_key
        self.model = model

    def run(self):
        try:
            success, result = _seams.core_llm.check_whisper_connection(
                self.base_url, self.api_key, self.model)
            self.finished.emit(success, result)
        except Exception as e:  # noqa: BLE001
            self.error.emit(str(e))


class LLMConnectionThread(QThread):
    finished = Signal(bool, str, list)
    error = Signal(str)

    def __init__(self, api_base, api_key, model):
        super().__init__()
        self.api_base = api_base
        self.api_key = api_key
        self.model = model

    def run(self):
        try:
            chk = _seams.core_check_llm
            is_success, message = chk.check_llm_connection(self.api_base, self.api_key, self.model)
            models = chk.get_available_models(self.api_base, self.api_key)
            self.finished.emit(is_success, message, models)
        except Exception as e:  # noqa: BLE001
            self.error.emit(str(e))
