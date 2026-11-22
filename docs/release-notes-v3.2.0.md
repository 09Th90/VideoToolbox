<!-- @version 3.2.5 -->
# 视频工具箱 v3.2.0 变更说明（2026-11-22）

**主题：字幕校准升级到「对象级」——知识对象化 / 执行对象化 / mention 对齐三层落地，
Jev 结构化决策以影子形态接入校准与声纹筛选；新增 ASR 转录「本地 / 云端」模式真切换。
本次为源码发布，安装包与在线安装器未重新构建（沿用 v3.1.6 安装资产）。**

## 新增 · 对象级字幕校准（calib 工程线）

- **注册表驱动**：`MODE_REGISTRY` 单一事实源驱动 cli/engine（31 模式），state 缓存规格表循环重建，process 版式归一；一键 rerun 表驱动 + 13 一键用例。
- **执行对象化**：`calib_core/acindex.py` 自包含字符级 Aho-Corasick 索引 + `replace_serial_ac` 预筛串行等价，全分支零漂移。
- **mention 对齐**：`calib_core/mention.py` 序次配对框架（`longest_bounded` 纯 ASCII 词边界 + `pair_cue` + `scope_state`）；对象级 ctx scoping 集成 engine 全分支，**最小触发门**（仅多目标 ref 启用，单目标走原路径结构化零漂移）；三级 fail-closed tie-break（zh 序次交集 → category 首段证据 → parent 链），失败保守回退只少改不改错；EXCLUDE 整行倒回 → mention 级预跳过。
- **知识对象化**：Entity 增 `aliases`/`parent` 字段 + spec 折叠 + kind 前缀两轮（unknown 2973→2666）；parent 单父防环宁缺毋滥；lint `multi_target` 改 (rx,wrong) 判定降噪（error 31→~5）。
- **未登录候选闭环**：`calib_entity candidates` 子命令合流 unresolved_proper ∪ family_gap 去重分级（stub-eligible / keep-latin / human-review），srt 只读，cue281 型大小写丢失只进人工绝不自动改写。

## 新增 · Jev 结构化决策影子审核（shadow-only）

- **校准侧**：`features/calibrate/calib_mention_decision.py`（`vt.calibrate.mention_review.v1`）离线重建 mention 决策点 + 本地证据闸门先行 + 证据卡，挂载 `calib_ai_agent`，独立侧车 `*.mention_review.json`；**calib_core 引擎零网络引用，字幕/rows/hits 永不回写**。
- **声纹侧**：`features/voiceprint/voiceprint_decision.py` 存疑 cue 影子路由（routine_review / priority_manual / insufficient_evidence），只追加明细不改 verdict。
- **升级证据门**：`scripts/dev/{build_jev_mention_dataset,eval_jev_mention,eval_jev_mention_gate}.py` 评测探针（522 case：T1 正例 197 / T2 待人工 293 / T3 假候选 32；三层金标排除 *.calib.srt 污染）。离线回放 J1-J4 判定：**J1 不降指标 PASS / J2 待人工金标 / J3 高置信 precision 0.8444<0.85 FAIL / J4 假候选 uncertain PASS** → **维持 shadow-only**，J1-J4 全过才参与硬裁决且只收缩 R。

## 新增 · ASR 转录「本地 / 云端」模式切换

- `core/asr/mode_switch.py`：转录下拉拆「本地 / 云端」两项，写 `asr_mode` → `apply_asr_to_engine` 落槽 → 体检真实生效；本地模型留空自动挑可加载权重（优先 large-v3）。
- 配套补丁链与界面接线（`core/asr/{patches,runtime_patches,ui_patch}`、`vt_engine_ui/transcription_interface`、`vt_app/settings_page`）。

## 新增 · 验收框架（T7-T10）

- 上限型指标门禁 `check_metric_le` + `_baseline.json`（family_gap before49/target5）；lint **差分门**（新增 error=0，非绝对门，不误伤存量）；`_gate_{lint_diff,family_gap,films,premerge}.py`。
- 负向测试 16 条（ctx gate / 删 ctx→family_gap≥1 / 白名单污染 / parent 环双父 / 单目标恒 disabled）+ L2 多目标回归 29 条（#235 Sentinel / #207 Meta 挂起 / parent 三向 / category 跨类目）。
- 合并前三件套 `_gate_premerge.py`：10 组 onepass --gate 0 + verify EQUIVALENT + lint 差分，**10/10 PASS**。
- 修复 monolith 拍平缺陷：`mention.mode_terms` 双模式（monolith 顶层 `TABLES` / 包 `state.TABLES`），消除 mention 路径 NameError。

## 文档

- 《字幕智能筛选与校准优化计划书》V1.0 评审稿入库（WP1-WP6：双音色识别 / 结构化决策 / 音频分离 / 质量评估，8 周分级发布 R0→R1→R2，G0-G5 门禁）。
- `docs/对象级校准节目总报告_2026-11-22.md`（calib 工程线交付总结）。

## 验证

- calib_core 零漂移：selftest `--ref` 冻结基线 **603 PASS / 0 FAIL**；`build_calib_monolith --check` **OK**（1112 Entity，AST 兼容）；7 片 onepass `--gate --max-differ 0` + verify EQUIVALENT。
- 声纹自测 `_selftest_speaker_voiceprint.py` **280/0**；决策客户端 `_selftest_decision.py` **36/0**；Jev mention 探针 `--self-test` **13/0**（金标零 .calib 污染 + mock 零网络）。
- 引擎纯度：`src/calib_core/` 对 decision_client / network / http **0 引用**；凭据隔离机制就位（`credential_store.py` 将 api_key/asr_api_key 存入 ignore 的 `data/credentials.json`，不进配置树/日志/报告/发布包）。独立 `decision_api_key` 属 WP3 计划项，v3.2.0 尚未实现（现决策客户端复用全局 AI 凭据槽）。

## 发布形态

- **源码发布**：版本号升至 3.2.0，完整源码推送 GitHub main。**未跑** `_build_onefile` / `_build_inno` / `build_online_installer`，**未生成** exe/7z，安装包与在线安装器沿用 v3.1.6 资产。