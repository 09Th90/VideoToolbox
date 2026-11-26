<!-- @version 3.3.1 -->
# 视频工具箱 v3.1.2 变更说明（2026-11-20）

**主题：ASR 反馈修复收尾——设置页测试不再假阳性、失败可直达配置、
「默认」通道前置拦截、引擎配置枚举防御。**
延续 v3.1.1：全部改动走我方源码与运行期补丁，引擎 site-packages 本体零改动。

## 修复 · 设置页「测试 ASR 配置」假阳性（第三方反馈收尾）

v3.0.0 反馈里用户看到「ASR 语音识别 正常（已就绪）」，点转录却立刻崩——
旧测试只校验「模型名非空 + 目录存在且非空」，不验证权重完整性，也不构造实例。

- 本地模式改为**逐项校验**权重文件：`config.json / model.bin / tokenizer.json`
  必需，`vocabulary.json / vocabulary.txt` 二选一，缺哪个报哪个；
  `preprocessor_config.json` 缺失只提示不阻断。
- 目录留空时按运行期同口径自动定位
  `<程序根>/tools/asr_model/faster-whisper/<模型名>`，并兼容 HF 缓存旧权重；
  找不到时明确失败并给出应放置的目录，不再笼统提示「去引擎里下载」。
- 测试追加**干跑**：目录解析 → 逐项体检 → 用 1 秒静音 WAV 走真实
  `_create_asr_instance` 构造 ASR（**不加载权重**，不占显存），并核对构造出的
  模型名 / 目录与配置一致。字段类型 / 枚举映射问题在建任务前就暴露。
- 显式目录残缺但工具箱内有可用权重时，按既有设计回退并**明确告警**
  「你填写的目录不完整（缺…），已回退到 …」，避免「测试过了却没按我填的跑」。
- 多行失败原因（逐项清单）改用对话框完整展示，不再被 InfoBar 截成半句。

## 修复 · 转录失败提示可直达配置

- 失败 InfoBar 命中 ASR 相关特征（必剪 / 剪映 / 412 / faster-whisper /
  模型 / `'str' object` 等）时挂「去配置 ASR」按钮，常驻至手动关闭；
  点击直达 设置 → ASR 语音识别 卡片（`MainWindow.open_asr_settings()`）。

## 修复 · 「默认」不再静默走必剪

- 转录下拉显示名改为「默认（必剪已失效）」——B 接口 `task/result` 自
  2026-10 起被平台整体风控（412），停在该项建任务必失败。
- 停在「默认」且 ASR 未配置时，**建任务前中止**并弹「去配置 ASR」引导，
  不再等整条音频转码完才吃 412。覆盖两个入口：转录页「开始转录」与
  首页「拖入 → 转录」；后者已配置 ASR 时会自动切换并**重建任务**，
  保证真正跑的模型与按钮显示一致（上游创建的 task 不随界面切换更新）。

## 修复 · 引擎 settings.json 枚举反序列化防御

`qfluentwidgets.QConfig.load` 被 `@exceptionHandler()` 整体包裹：任一配置项
反序列化抛异常（枚举外取值）会**中断整份配置加载**，后续配置全部保持出厂
默认且界面无提示。新增 `_vc_sanitize_enum_settings()`，在 qconfig 读盘前把
`Transcribe.TranscribeModel / TranscribeLanguage / OutputFormat`、
`Whisper.WhisperModel`、`FasterWhisper.Model / VadMethod` 的枚举外取值
回落为合法值并写日志；自定义模型名照旧由运行期 `enum_like` 补丁注入，不写盘。

## 回归门禁

- `src/_selftest_local_asr.py` 新增 T17（B/J 异常翻译：412 / 额度 / 签名 403 /
  1014 / 无关异常透传）、T18（枚举外回落 + 合法值不动）、T19（空目录不再
  就绪 + 无权重干跑失败）；本轮 **44/44 PASS**（负向 8 项）。
- 本机 large-v3 / small.en 权重在 CPU/int8 下 T09（子进程加载）/ T10
  （端到端出字幕）通过；GPU 失败自动降级 CPU 由 T06d 覆盖。
- `_selftest_asr_proto` 207 PASS / 0 FAIL；`_selftest_core_api` PASS
  （「默认（必剪已失效）」常量基线同步）；`_selftest_asr_language`、
  `_selftest_engine_task_factory` PASS。

## 引擎裸 `.value` 点审计结论（不改 site-packages）

- `core/asr/transcribe.py:137/144` 与 `entities.print_config`：已被
  `vc_asr_local_model_patch` / `vc_asr_print_config_patch` 兜住；
- `ui/task_factory.py:79/87/92`：`cfg` 为 QConfig，值必为枚举，枚举外盘值
  已被上述清洗拦截；
- `FasterWhisperSettingWidget.py:557/580`：仅「模型下载完成」回调可达，
  值为枚举、`.value` 安全；`:891` 引擎内无调用点（死代码）；
- `WhisperCppSettingWidget.py:457`：有 try/except 包裹，异常不外溢。

## 升级说明

- v3.0.0 / v3.1.0 / v3.1.1 用户经「检查更新」或在线安装器升级即可；
  日常迭代只下变更层（code / docs / tools），app 层（exe）本轮因源码
  修复一并更新。
- 仍不绕过 B 接口风控、不恢复已下线的 J 签名服务；内置免费通道失败
  一律中文可操作提示，引导自有 ASR 服务或本地模型。