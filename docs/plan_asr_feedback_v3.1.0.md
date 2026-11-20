<!-- @version 3.1.2 -->
# ASR 反馈修复与优化计划（v3.1.0）

> 来源：第三方用户《视频工具箱 v3.0.0 问题反馈》（`C:\Users\LENOVO\Downloads\视频工具箱_v3.0.0_问题反馈.md`）。
> 范围：本地独立模型转录必崩（阻断）、B 接口（必剪）失效、J 接口（剪映）失效。
> 引擎为冻结 site-packages，**所有改动走运行期补丁 / 我方源码**，不改引擎本体。

## 一、反馈条目与定性

| # | 现象（用户实测） | 定性 | 处置方向 |
|---|---|---|---|
| 1 | 本地 faster-whisper 转录必崩：`'str' object has no attribute 'value'`；堆栈 `transcript_thread.py:27 run` → `entities.py:604 print_config`；素材 1h53m21s，RTX 5060 Laptop 8GB | 我方覆盖链把纯字符串模型名写进枚举配置，引擎两处按 `.value` 取（`print_config` 先崩，`_create_asr_instance` 后崩） | 代码修复（阻断，已部分落地，见第二节） |
| 2 | B 接口 `task/result` 对 `model_id=7/8/0` 一律 `412`；12h 窗口累计 6h 音频即 `duration limit exceeded` | 平台侧风控 + 本地额度账本（`base.py`：100 次 / 360 分钟 / 12h），非拼接 bug | 不做风控绕过；异常翻译为可操作提示，引导服务模式 |
| 3 | J 接口签名端 `asrtools-update.bkfeng.top/sign` 返回 403；submit `ret=1014 system busy` | 第三方签名服务下线，客户端无解 | 不尝试恢复；异常翻译为明确提示 |

## 二、已落地（开发仓库，离线验证通过）

**第一轮（v3.1.1，2026-11-19 上午）**

- `src/core/asr/enum_compat.py`（新增）：`EnumLike`（str 子类 + `.value`）、`enum_like()`。
- `src/core/asr/patches.py`：
  - `_normalize_local_asr_config()`：归一化 `transcribe_model / faster_whisper_model / whisper_model / faster_whisper_vad_method / output_format`；
  - `vc_asr_local_model_patch()`：包引擎 `_create_asr_instance`，内部顺带挂打印补丁；
  - `vc_asr_print_config_patch()`：包 `TranscribeConfig.print_config`（反馈堆栈的真实崩点）；
  - `vc_builtin_asr_error_patch()`：包 `BcutASR.run` / `JianYingASR.run`，412 / 额度 / 签名 403 / 1014 转中文提示；
  - `vc_asr_protocol_patch()` 末尾依次挂四补丁，幂等。
- 源头写配置三处：`src/engine_task_factory.py`、`src/vt_engine/tasks.py`、`src/core/asr/engine_config.py`，模型名经 `enum_like` 双兼容。
- 自检：`src/_selftest_local_asr.py` T11b（print_config）/ T11c（构造）；`data/tmp/` 对照脚本 9 项；`_selftest_asr_proto` 207 PASS / 0 FAIL；`_selftest_core_api` PASS；任务工厂逐字段一致。

**第二轮（2026-11-19 下午，本次；对应 plan P0-2/P0-3/P0-4/P1-5/P1-6/P2-9）**

- **P0-2 测试干跑**（`tools/ai_client.py` + `src/core/shared/ai.py` + `asr_local_paths.py`）：
  - 本地模式不再以「目录存在且非空」视为就绪，改为**逐项**校验
    `config.json / model.bin / tokenizer.json + vocabulary.json|txt`，缺哪个报哪个；
  - 目录留空时按 `<程序根>/tools/asr_model/faster-whisper/<model>` 自动定位并校验；
  - `ai_test_asr` 追加本地干跑：目录解析 → `diagnose_model_dir()` → 用 1 秒静音 WAV
    构造 ASR（`_create_asr_instance`，**不加载权重**），并核对构造出的模型名/目录；
  - 显式目录残缺但工具箱内有可用权重时，按设计回退并**明确告警**（避免「填的目录错了却测试通过」的新困惑）；
  - 新增 `asr_local_paths.diagnose_model_dir()` / `OPTIONAL_WEIGHT_FILES`。
- **P0-3 引擎裸 `.value` 审计结论**：
  - `videocaptioner/core/asr/transcribe.py:137/144` —— 已由 `vc_asr_local_model_patch` 归一化兜住；
  - `videocaptioner/core/entities.py print_config` —— 已由 `vc_asr_print_config_patch` 兜住；
  - `videocaptioner/ui/task_factory.py:79/87/92` —— `cfg` 是 QConfig，`EnumSerializer` 保证枚举值；枚举外盘值已被 P2-9 清洗 → 不改；
  - `FasterWhisperSettingWidget.py:557/580` —— 仅「模型下载完成」回调可达，`cfg` 值为枚举、`.value` 安全 → 不改；
  - `FasterWhisperSettingWidget.py:891` —— 引擎内无调用点（死代码）→ 不改；
  - `WhisperCppSettingWidget.py:457` —— 有 try/except 包裹，异常不外溢 → 不改。
- **P0-4 回归门禁**（`src/_selftest_local_asr.py`）：新增 T17（412/额度/签名 403/1014/无关异常透传）、
  T18（枚举外取值回落 + 合法值不动）、T19（空目录不再就绪 + 无权重干跑失败）；
  本轮 `SELFTEST_RESULT=PASS`（44/44，负向 8 项）。
- **P1-5 失败提示直达配置**（`src/vt_engine_ui/transcription_interface.py`）：
  转录失败 InfoBar 命中 ASR 相关特征时挂「去配置 ASR」按钮（常驻至手动关闭），
  经 `MainWindow.open_asr_settings()` → `SettingsPage.scroll_to_asr()` 直达卡片。
- **P1-6 默认项标注 + 前置拦截**：
  - 下拉显示名改为「默认（必剪已失效）」（`voiceprint.TM_DISPLAY_DEFAULT` 与
    `vt_engine_ui._seams` 同步；golden 基线已更新）；
  - 停在「默认」且 ASR 未配置时，`_ensure_asr_selected()` 返回 False，
    `start_transcription()` **建任务前中止**并弹「去配置 ASR」引导，
    不再等整条音频转码完才吃 412。
- **P2-9 配置反序列化防御**（`src/core/asr/runtime_patches.py`）：
  `_vc_sanitize_enum_settings()` 在 `vc_prepare_settings_file()`（qconfig 读盘前）
  把 `Transcribe.TranscribeModel / TranscribeLanguage / OutputFormat`、
  `Whisper.WhisperModel`、`FasterWhisper.Model / VadMethod` 的枚举外取值回落为合法值
  ——`QConfig.load` 被 `@exceptionHandler()` 整体包裹，任何一项反序列化异常都会
  **中断整份配置加载且界面无提示**，这是比单点 `.value` 更隐蔽的雷。

**仍未验证**：设置页干跑在冻结 exe 内的真实点击（本机源码态已用一次性脚本覆盖 6 项；
GUI 导入冒烟通过）；真机 GPU `large-v3` 长片端到端（本机 large-v3 仅在 CPU/int8 跑通）。

## 三、待办（分阶段）

### P0 · 阻断收尾

1. **[未完成] 真机 GPU 端到端转录验证**
   - 条件：large-v3 权重、8GB 显存、反馈同类长片（≥1h）。
   - 路径：设置页测试 → 建任务 → `print_config` → 实例构造 → 推理 → 出 SRT，全链无 `AttributeError`。
   - 已覆盖部分：本机 large-v3 / small.en 在 **CPU/int8** 下 T09（子进程加载）、T10（端到端出字幕）通过；
     GPU 失败 → CPU 自动降级由 T06d 覆盖。仍缺「8GB 显存 + 小时级长片」的真机记录。
   - 同步记录：8GB 显存下 large-v3 是否需量化 / CPU 降级；降级路径（device=CPU、int8）是否走通。
   - 责任文件：`src/features/transcribe/`、`src/core/asr/patches.py`。

2. ~~本地模式「测试 ASR 配置」前置干跑~~ —— **已完成**（本轮，见第二节）。
3. ~~引擎其余裸 `.value` 点审计~~ —— **已完成**（本轮，结论见第二节；均不可达或已被枚举化/补丁兜住）。
4. ~~回归门禁~~ —— **已完成**（T11b/T11c/T17/T18/T19；`asr_proto` 207 PASS、`core_api` PASS）。

### P1 · 提示与引导（体验）

5. ~~失败提示可直达配置~~ —— **已完成**（本轮，「去配置 ASR」按钮）。
6. ~~下拉「默认」不再静默走必剪~~ —— **已完成**（本轮：文案 + 建任务前拦截）。
7. **[可选，排期后定] 额度提示补剩余额度与重置时间**：
   B 接口已被整体风控（412），额度提示只在「必剪曾短暂恢复」时有意义；优先级降低。
8. ~~内置通道全不可用时引导服务模式~~ —— **已有**：设置页「调用示例（curl / Python）」
   （`asr_examples()` + `AsrExampleDialog`）自 v1.x 起常驻。

### P2 · 健壮性

9. ~~配置反序列化防御~~ —— **已完成**（本轮，`_vc_sanitize_enum_settings` 挂 qconfig 读盘前）。
10. **本地模型目录解析** —— **基本完成**（本轮：逐项体检 + 回退告警 + 干跑）；
    仍可补：模型名「枚举内 vs 枚举外」两条分支的独立自检用例（当前由 T11 + T19 间接覆盖）。
11. **日志 / 缓存键一致性**：复核模型名、协议名在日志、Cache 键、示例文案中的取值口径，
    避免一处 `.value` 一处裸名（未做，非阻断）。

### P3 · 可选（排期后定）

12. 置灰 / 隐藏不可用的内置通道选项（当前已用文案标注 + 前置拦截替代，优先级低）。
13. 额度账本查看页（已用时长、调用次数、重置时间、手动清零）。

## 四、明确不做（边界）

- **不绕过 B 接口风控**：不加 buvid Cookie、不伪造 Referer / Origin、不换 UA 池——属绕过访问控制，且实测无效；
- **不恢复已下线的 J 签名服务**：403 是第三方端关闭，客户端无解；
- 不改字幕序号 / 时间轴 / 空行 / 换行 / BOM 的既有契约；
- 不改 `harness\` 只读部署。

## 五、验收标准

- 本地模式：设置页干跑通过 → 转录 `print_config`、实例构造、推理、出 SRT 全链无 `AttributeError`；
- B/J 失败一律显示中文可操作提示，界面不出现裸 HTTPError / system busy 原文；
- 离线自检全绿；真机至少 1 条长片（≥1h）转录通过；
- 变更只在我方源码与运行期补丁，引擎 site-packages 本体零改动。

## 六、风险与依赖

- 真机验证依赖 large-v3 权重与 8GB 显存；本机已有 large-v3 / small.en 权重，CPU/int8 全链通过；
  GPU（cuda/float16）在 8GB 显存上的长片表现仍待真机记录，失败会按既有逻辑自动降级 CPU/int8。
- 引擎设置控件为内嵌懒加载；本轮审计结论是「这些裸 `.value` 点不可达或输入必为枚举」，
  因此不改 site-packages，改由「qconfig 读盘前枚举清洗 + 运行期 `enum_like` 补丁」双层兜住。
- 第三方 v3.0.0 用户跑冻结 exe，**必须重新打包发版**才生效；改安装目录 `src` 副本不影响 exe。
- 工作区存在与本次无关的脏文件（`calib_core/_doc.py`、`bilingual.py`、`subtitle_calib_merged.py`），发版前由 `scripts/dev/stamp_versions.py` 重跑版本清单时需剔除，避免把无关改动钉进清单。
