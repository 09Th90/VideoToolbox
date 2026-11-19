<!-- @version 3.1.1 -->
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

## 二、本轮已落地（开发仓库，离线验证通过）

- `src/core/asr/enum_compat.py`（新增）：`EnumLike`（str 子类 + `.value`）、`enum_like()`。
- `src/core/asr/patches.py`：
  - `_normalize_local_asr_config()`：归一化 `transcribe_model / faster_whisper_model / whisper_model / faster_whisper_vad_method / output_format`；
  - `vc_asr_local_model_patch()`：包引擎 `_create_asr_instance`，内部顺带挂打印补丁；
  - `vc_asr_print_config_patch()`：包 `TranscribeConfig.print_config`（反馈堆栈的真实崩点）；
  - `vc_builtin_asr_error_patch()`：包 `BcutASR.run` / `JianYingASR.run`，412 / 额度 / 签名 403 / 1014 转中文提示；
  - `vc_asr_protocol_patch()` 末尾依次挂四补丁，幂等。
- 源头写配置三处：`src/engine_task_factory.py`、`src/vt_engine/tasks.py`、`src/core/asr/engine_config.py`，模型名经 `enum_like` 双兼容。
- 自检：`src/_selftest_local_asr.py` T11b（print_config）/ T11c（构造）；`data/tmp/` 对照脚本 9 项；`_selftest_asr_proto` 207 PASS / 0 FAIL；`_selftest_core_api` PASS；任务工厂逐字段一致。

**尚未验证**：真实 GPU 端到端转录（本机无 large-v3 权重）；设置页内嵌引擎控件的裸 `.value` 路径；冻结 exe 重打包。

## 三、待办（分阶段）

### P0 · 阻断收尾（发版前必须完成）

1. **真机端到端转录验证**
   - 条件：large-v3 权重、8GB 显存、反馈同类长片（≥1h）。
   - 路径：设置页测试 → 建任务 → `print_config` → 实例构造 → 推理 → 出 SRT，全链无 `AttributeError`。
   - 同步记录：8GB 显存下 large-v3 是否需量化 / CPU 降级；降级路径（device=CPU、int8）是否走通。
   - 责任文件：`src/features/transcribe/`、`src/core/asr/patches.py`。

2. **本地模式「测试 ASR 配置」前置干跑**
   - 现状：`tools/ai_client.py::asr_test_connection` 本地分支只校验模型名非空、目录存在且非空，**不构造实例**——所以反馈用户看到「测试正常」，转录才崩。
   - 改法：本地分支在不加载权重的前提下干跑构造（引擎 `_create_asr_instance` 或我方 `engine_asr` 同款入口，喂一段临时静音 wav），把字段类型 / 枚举映射问题前置到设置页。
   - 模型目录文件清单逐项校验：`config.json / model.bin / tokenizer.json / vocabulary.json / preprocessor_config.json`，缺哪个报哪个，而不是目录非空即「就绪」。

3. **引擎其余裸 `.value` 点审计**（内嵌引擎设置页在 `settings_page.py::_ensure_engine_setting` 懒加载，控件可达）
   - `ui/components/FasterWhisperSettingWidget.py`：L557 `cfg.faster_whisper_model.value`、L580 `current_value.value`（二次取值）、L891 `cfg.faster_whisper_model.value.value`；
   - `ui/components/WhisperCppSettingWidget.py` L434 同类；
   - `videocaptioner/ui/task_factory.py` L79/87/92；
   - 结论分类：可达 → 运行期补丁 `getattr(x, 'value', x)` 兼容；不可达 → 记录理由，不改。

4. **回归门禁**
   - T11b/T11c 纳入离线自检必跑；
   - 为 `_friendly_builtin_asr_error()` 补合成异常单测（412 / 额度 / 签名 403 / 1014 / 无关异常透传）；
   - 发版前 `_selftest_asr_proto`、`_selftest_core_api`、任务工厂自检全绿。

### P1 · 提示与引导（体验）

5. **失败提示可直达配置**：转录失败 InfoBar 对 B/J / 本地配置错误增加「去配置 ASR」按钮，跳转设置页 ASR 卡片（当前只有静态文案）。

6. **下拉「默认」不再静默走必剪**：未配置可用 ASR 时，「默认」选项标注「必剪接口已失效」；`_ensure_asr_selected()` 逻辑保持，未就绪时明确提示先配服务 / 本地模型，而不是开任务后才失败。

7. **额度提示补剩余额度与重置时间**：`base.py` 账本在本地 Cache 表（tag `rate_limit:<Service>`，12h / 360min / 100 次）；超限文案读出已用时长、剩余时长、窗口重置时刻，必要时给出「清空本地额度缓存」入口。

8. **内置通道全不可用时引导服务模式**：首次使用或 B/J 均失败后，设置页挂 `asr_examples()` 示例入口（curl / Python 模板），降低配服务模式的门槛。

### P2 · 健壮性

9. **配置反序列化防御**：`settings.json` 中枚举值非法（枚举外自定义名、旧版本残留）时，在加载缝或 `apply_asr_to_engine` 还原到默认枚举，不保留裸 str 流入引擎。

10. **本地模型目录解析**：自定义模型名与目录回退规则梳理；缺文件 / 损坏权重逐项报错；模型名在枚举内 vs 枚举外两条分支分别有测试用例。

11. **日志 / 缓存键一致性**：复核模型名、协议名在日志、Cache 键、示例文案中的取值口径，避免一处 `.value` 一处裸名。

### P3 · 可选（排期后定）

12. 置灰 / 隐藏不可用的内置通道选项；
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

- 真机验证依赖 large-v3 权重与 8GB 显存；8GB 跑 large-v3 可能需 int8 / CPU 降级，需同步验证降级路径。
- 引擎设置控件为内嵌懒加载，审计改动需覆盖「打开设置页 → 本地模型分组可见」路径。
- 第三方 v3.0.0 用户跑冻结 exe，**必须重新打包发版**才生效；改安装目录 `src` 副本不影响 exe。
- 工作区存在与本次无关的脏文件（`calib_core/_doc.py`、`bilingual.py`、`subtitle_calib_merged.py`），发版前由 `scripts/dev/stamp_versions.py` 重跑版本清单时需剔除，避免把无关改动钉进清单。
