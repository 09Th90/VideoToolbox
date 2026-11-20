<!-- @version 3.1.4 -->
# 视频工具箱 v3.1.1 变更说明（2026-11-19）

**主题：ASR 本地独立模型转录崩溃修复 + 内置免费通道失效提示。**
全部改动走我方源码与运行期补丁，引擎 site-packages 本体零改动。

## 修复 · 本地 faster-whisper 转录必崩（第三方反馈）

现象：选择「ASR · 本地独立模型（faster-whisper）」后点转录，必弹
`转录失败 'str' object has no attribute 'value'`，服务模式不受影响。

根因在三段衔接处（不是用户配置问题）：

- `asr_local_override()` 返回**纯字符串**模型名（`large-v3` 或枚举外自定义名）；
- 任务工厂 `_apply_asr_override` 把它直接写进
  `TranscribeConfig.faster_whisper_model`（原值是 `FasterWhisperModelEnum`）；
- 转录线程第一步 `print_config()` 就按枚举取
  `self.faster_whisper_model.value` / `self.faster_whisper_vad_method.value`
  ⇒ `'str' object has no attribute 'value'`（第三方完整堆栈：
  `transcript_thread.py:27 run` → `entities.py:604 print_config`）；
- 即使绕过这一处，引擎 `_create_faster_whisper_asr` 同样按枚举取
  `config.faster_whisper_model.value`，继续崩。

修复（四层，引擎本体零改动）：

1. 新增 `core/asr/enum_compat.py`：`EnumLike`（str 子类 + `.value`）与
   `enum_like()`，字符串语义完全不变；
2. 源头：`engine_task_factory._apply_asr_override`、`vt_engine/tasks.py`
   与 `core/asr/engine_config.vc_asr_patch_apply` 写配置时即包双兼容对象；
3. 兜底一：`vc_asr_local_model_patch()`（随 `vc_asr_protocol_patch()` 自动
   挂载）在引擎 `_create_asr_instance` 入口归一化
   `transcribe_model / faster_whisper_model / whisper_model /
   faster_whisper_vad_method / output_format`——旧任务、引擎自带
   TaskFactory 产物同样覆盖；
4. 兜底二：`vc_asr_print_config_patch()` 包住
   `TranscribeConfig.print_config`，线程启动第一行不再因 str 取 `.value`
   崩（这正是第三方堆栈的崩点，上一版只补了构造入口，漏了这里）。

## 修复 · 内置免费通道（B 接口 / J 接口）失效提示

第三方实测（2026-11-19）：B 接口 `task/result` 对 `model_id=7/8/0` 一律
`412 Precondition Failed`（结果端点整体风控，与 task_id 无关）；12 小时窗口
累计 6 小时即 `BcutASR duration limit exceeded`；J 接口签名端
`asrtools-update.bkfeng.top/sign` 返回 `403`，submit 返回
`1014 system busy`。

新增 `vc_builtin_asr_error_patch()`（随协议补丁挂载）：包住
`BcutASR.run` / `JianYingASR.run`，把上述底层异常翻译成可操作中文提示，
统一引导用户到「自有 ASR 服务」（设置 → ASR 语音识别 → 服务模式）。
**不做任何风控绕过**（不加 Cookie、不伪造 Referer）：平台侧关闭就走自建
通道，这是产品边界。

## 验证

- 未打补丁时 `print_config` 与 `_create_asr_instance` 两处均可稳定复现
  原异常；挂载后配置打印正常、构造落到 `ChunkedASR`；
- `data/tmp` 对照脚本 9 项全 PASS（含枚举输入不被替换、自研链路回归）；
- `src/_selftest_local_asr.py` 新增 **T11b/T11c**：用**真实**引擎
  `TranscribeConfig` 先跑 `print_config()` 再走 `_create_asr_instance`，
  直接覆盖第三方堆栈的两条路径；
- `_selftest_engine_task_factory` 逐字段一致、`_selftest_core_api` 通过、
  `_selftest_asr_proto` 207 PASS / 0 FAIL。

> 说明：本机没有 large-v3 权重与 8 GB 显存档位，真实 GPU 端到端转录
> （≥1 小时长片）仍需在相应硬件上复验；8 GB 显存下 large-v3 的量化 / CPU
> 降级路径同理。补丁覆盖的是崩溃点本身，不改变模型加载与推理参数。

## 兼容性

- 校准铁律不变：序号/时间轴/空行/换行/BOM 原样，只动文字；
- `EnumLike` 是 `str` 子类：JSON 序列化、拼接、比较、日志输出与普通字符串
  完全一致，旧配置 / 旧任务无需迁移；
- 数据目录布局不变；`subtitle_learned_kb.json` 仍为运行期数据，不入库；
- 内置通道不做风控绕过；平台侧不可用时按提示改用自有 ASR 服务。

## 门禁汇总（发布前全绿）

语法检查全过 · 校准单文件 CHECK OK · `_selftest_decision` 36/0 ·
doc drift 8/8 · 密钥扫描通过 · 本地 ASR 自检（含 T11b/T11c）通过 ·
`_selftest_asr_proto` 207 PASS / 0 FAIL。
