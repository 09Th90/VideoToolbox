<!-- @version 3.2.5 -->
# 视频工具箱 v3.2.5 变更说明（2026-11-22）

**主题：落地《字幕智能筛选与校准优化计划书》V1.0 的 WP1–WP6 工作包——双音色识别 ·
结构化决策 · 音频分离 · 质量评估。全部能力以「默认全影子」安全形态发布：决策模型总闸
出厂关闭、第二音色影子默认 off、语音分离默认 off，用户手动开启；R1 辅助 / R2 有限自动
留待 G0 评估基线数据投喂并通过门禁后逐项开放。本次源码与安装包同步更新。**

## WP1 · 数据基线与现有缺陷修复（公共依赖）

- **P0② 默认模式翻转**：声纹筛选缺省从「召回优先」翻转为「精准优先」——`load_filter_mode` 单一真相源（缺省/脏值→precision，显式 recall 尊重）；存疑与判不了的条目另存 `_待复核.srt` 不混入成品；NaN/音频不足 precision 下不进成品；误杀熔断线照常兜底。core 调用方 `mode=None` 自动跟随，零改动。
- **P0③ 阈值三级解析**：`resolve_thresholds`（显式参数 > selection.json 全局覆盖 > 模板 calib 校准 > 出厂常量），多模板保守取窄；出厂常量 0.55/0.45/0.05 保持；`calibrate_threshold` 数据驱动校准入口（建议不自动生效，待 G0 数据）；报告记 `threshold_source`。
- **P0① 聚类零回归**：v3.1.0 已修的二遍聚类（合并→冻结簇心→整体重指派）盯守不变。
- **G1 回归 39 条**：默认 precision/显式 recall/NaN/熔断/结构不变量（BOM/CRLF/序号/时间轴 100%）/阈值三级/calibrate。
- **评估器增量**：F1（cue+时长双口径）+ hard_flags 困难样本切片 + split 分列 + 效率采集 + manifest v1.1 兼容（现有口径只增不改）。
- **G0 评估架构**：`voiceprint_baseline.py` 基线报告器（可复现快照：媒体/SRT/模板/模型/配置哈希 + 报告哈希自证）+ `voiceprint_gates.py` G0/G1 门禁判定。**架构就位，真实标注数据集后期投喂**（无数据时输出「待数据」不放行，不伪造基线数字）。

## WP2 · 第二路音色模型与融合（默认 off / 影子）

- 第二路 `wespeaker_zh_cnceleb_resnet34_LM`（256 维 ResNet34，CNCeleb 中文，Apache-2.0，sherpa-onnx ONNX CPU，**无需 torch**），与 CAM++ 架构+语料双差异。
- `second_voiceprint.py` 影子链路：filter_srt 尾部 hook，复用 pcm/cues/labels/chunks 零重复解码；簇级 target/competitor/margin 打分；缓存键 media_sha256+model_id+version+preproc 命中零推理；**永不参与 decide / 不改 verdict**；模型缺失→degraded 主筛选照常。
- `score_calibration.py` 校准融合：竞争者底噪池分位标准化（公共刻度）→ 可选 Platt（≥200 样本）；线性加权融合起步；升辅助后**只降级 keep→review 永不 drop**。
- 模板 `models` 命名空间加键不换锁（顶层 192 维 CAM++ 主向量永不动）；sync 叶子 fp 按 model_id 域隔离去重（旧输入逐字节兼容）。
- 前处理对齐检查（cos≥0.995）作启用硬开关；模型下载/真实对齐后期运行时按需。

## WP3 · 决策模型辅助字幕筛选（默认 decision_enabled=False / 影子）

- **独立凭据 decision_api_key**：`credential_store` SECRET_FIELDS 加键（独立存储 ignore，不进配置树/日志/报告/界面快照/发布包）；shim 运行期内存覆盖永不回写 ai_config；R0 影子允许全局 fallback（审计标记），R1 起强制独立 key。
- **端点白名单**：`decision_base_url` 北京实测 + 新加坡预留（R0 只实放行北京），主机精确命中拒子域/后缀伪装；区域-凭据绑定（改端点须重测）。
- **声纹 Schema v2**（`vt.voiceprint.filter.v2`）：state 补竞争者分差/簇一致性/文本角色/邻接上下文；5 问/cue（content_role/evidence_conflict/cluster_split_needed/route+cannot_determine/evidence_quality），每请求 3 cue（15≤16）；数值字段附业务口径 GLOSSARY。
- **三态路由**：apply_shadow（R0 只记录不改 verdict）/ apply_assist（R1 默认关闭，本地闸门先行，只排序/标注/冲突标记，A.3 约束：低置信待复核不丢弃/硬规则优先/声学证据冲突不凭文本改/失败回退）/ apply_auto（R2 默认关闭，高置信≥98%+场景白名单全门禁才改路由三值）。
- R0 补强：请求缓存（TTL 7 天）+ 错误分类 + 聚合审计（request_id 索引，零明文）。

## WP4 · 决策模型辅助字幕校准（默认影子）

- `calib_triage_decision.py` 校准前分诊（`vt.calibrate.triage.v1`）：位于机械术语基线之后、生成式 LLM 之前；复用 mention 预分类，本地确定性闸门先行（零疑点/anchorable 可验证→skip_generative）；四问/块（需生成校准/需联网/需音画/路由）；**只记 would_skip/would_save，不改 pending / 不跳生成式**。
- 改动复核 `review_change`：validate 通过后、accepted 写入前影子复核（meaning_preserved/evidence_supported/introduced_new_error/change_risk）；R0 只记录不拦截。
- **铁律**：机械基线/参考行保护/verify 始终执行，决策模型只减生成式处理不跳硬校验；硬校验拒绝 Jev 无权复活。
- 价值门槛门禁脚本（J1 漏改护栏≥纯本地闸门 + J3 置信单调高置信≥0.85 + 近随机护栏）；**LLM 降≥20% 且质量不回退**待 G0 数据验证，当前恒影子。

## WP5 · 音频分离 PoC 与微调门禁（默认 off / 影子）

- `separation_backend.py`：MossFormer2（ModelScope）盲分离按说话人多轨 + CAM++ 声纹选轨（「先拆开再认人」，enrollment 余弦 margin，**声纹不出本地**）；Demucs vocals 辅线「歌声」标签；独立子进程完成即退释放显存（8GB 与 large-v3 错峰）；8k→16k 重采样；D 盘缓存重定向。
- `_asr_separate_audio` 契约不变：off 原轨直通零开销；on 影子模式分离轨落缓存+日志仍返回原轨；后端缺失/异常→degraded 回退原轨**绝不阻断转录**；弃轨日志计数不静默删。
- patches.py 消费侧逐轨提交合并（off 逐字节同现状）；`eval_separation_poc.py` A 归因→B 人声隔离（SI-SDR numpy）→C 目标提取→D 微调门禁逐级架构。
- **torch/modelscope 为可选依赖**（现栈无 torch，lazy import 缺失 graceful degraded）；模型下载/安装/真实分离后期运行时按需。

## WP6 · 界面、配置与可运维性

- 设置页决策模型区域：总闸 decision_enabled（出厂关）+ 三模式 shadow/assist/auto（assist/auto 标注需门禁）+ 独立凭据（只写不回填明文，has/mask 状态）+ 区域端点白名单 + 连通性测试（绝不回显 key）+ 第二音色开关。
- 报告渲染增强：graceful 追加阈值来源/第二音色摘要/Jev 路由/影子侧车（键缺失不加，脏类型不崩）；Audit 不记密钥可定位 cue+时间轴。
- 功能开关与版本回退：总闸关→decision_mode=off 一键回纯本地规则；第二音色关恢复纯 CAM++；分离 ASR 卡默认 off。
- 缺件降级提示优先级收敛（组件缺失=故障态独立于总闸选择，缺件可观测性）。
- 文档补全（程序说明书开发版/用户版/User_Manual_EN：决策区域/三模式/独立凭据/配置键/凭据隔离）。

## 验证

- 声纹：`_selftest_speaker_voiceprint.py` **319/0** + `_selftest_second_voiceprint.py` **93/93** + `_selftest_voiceprint_decision.py` **139/0**。
- 校准：`_selftest_calib_core.py --ref` 冻结基线 **603/0**（零漂移）+ `eval_jev_triage_gate.py --self-test` PASS。
- ASR：`_selftest_local_asr.py` **45/45**（分离 off 零回归）+ `eval_separation_poc.py --self-test` **19/19**。
- 决策：`_selftest_decision.py` **99/0**（凭据隔离/端点白名单/区域绑定/缓存审计/七类异常回退）。
- 界面：`_selftest_settings_resilience.py` **8/8** + WP6 逻辑 62/0 + 建页冒烟 25/0 + notice 回归 5/0。
- 核心 API：`_selftest_core_api.py` **167 符号** PASS。
- 引擎纯度：`src/calib_core/` 对 decision_client/network/http **0 引用**；凭据隔离实机验证（ai_config 回读零明文）。
- **默认全影子零行为变化**：decision_enabled=False / 第二音色 off / 分离 off 时各链路行为与旧版逐字节一致。

## 发布形态

- **源码 + 安装包同步更新**：版本号升至 3.2.5，完整源码推送 GitHub main，重建离线安装包（`视频工具箱_Setup_v3.2.5.exe`）与在线安装器（`VideoToolbox_OnlineSetup_v3.2.5.exe`），更新版本化 Release v3.2.5 与 repo-latest 在线更新包。
- **默认全影子安全态**：所有模型辅助能力出厂关闭/影子，用户手动开启；R1/R2 有限自动待 G0 评估基线数据投喂并通过 G0–G5 门禁后逐项开放（计划书分级发布 R0→R1→R2）。
- 含非商业限制权重（CNCeleb/VoxCeleb 系）商用分发前须核验许可；内部使用先行。