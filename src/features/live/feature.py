# -*- coding: utf-8 -*-
# @version 3.3.1
"""实时字幕功能清单。

并入自项目二（vt-web-server / ITX-Windows），只保留实时链路独有的数据面：
WASAPI 采集、能量 VAD、有界队列、云端/本地双后端、降级状态机、悬浮层。

与项目一共享：
* ASR 端点 / 模型 / 密钥 —— 读 ``data/ai_config.json`` + ``data/credentials.json``；
* 术语校准 —— 直连 ``calib_core`` 真源（不再 import 校准单文件生成物）；
* 壳层、设置页、打包、更新。
"""
from features._registry import CliCommand, FeatureSpec, GuiSpec

FEATURE = FeatureSpec(
    id="live",                          # 必须与目录名一致
    title="实时字幕",
    summary="系统内录/麦克风实时双语字幕；复用设置里的 ASR；同步输出 SRT 与 OBS 文本",
    backend="features.live.service",
    requires=("asr", "network"),
    services={
        "service": "features.live.service:LiveService",
        "build_sinks": "features.live.sinks:build_sinks",
    },
    cli=(),                             # 长生命周期服务，不注册 agent_cli（避免 --help 膨胀）
    gui=GuiSpec(nav="实时字幕",
                builder="features.live.page:build_page",
                position="top",
                order=35,               # 视频库 30 与字幕处理 40 之间
                object_name="LivePage",
                attr="live_page",
                icon="MICROPHONE",
                lazy=True),
    order=35,
)
