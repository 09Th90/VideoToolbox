<!-- @version 2.9.0 -->
# 视频工具箱 v2.9.0

> 本版把本地 ASR 改为程序内直连 faster-whisper，新增谷歌翻译批量请求层与声纹自动过滤，
> 校准链完成「`src/calib_core` 真源包 + 根目录生成物」双轨化并沉淀多部片源的二次精校；
> 同时统一打包配置、补齐安装版源码副本与全量自测。**本地 ASR 模型权重不随安装包分发**，
> 详见「已知限制」。

## 新增

- **本地 ASR 内置化**：转录改为主进程内 `faster_whisper.WhisperModel` 直连，替代外部
  `faster-whisper-xxl.exe`；新增 `asr_local_paths.py` 统一解析模型目录（源码运行 /
  PyInstaller onefile / 自定义数据根三种形态），支持 GPU 失败自动降级 CPU、离线加载、
  模型缓存清理、幻觉过滤与结构化日志；配套 567 行全链自检（含负向用例）。
  ⚠ 权重文件需用户自备，见「已知限制」。
- **谷歌翻译批量层**：`core/translate/gtx_batch.py` 利用 `dict-chrome-ex` 端点重复 `q`
  参数批量请求（25 条/请求、6000 编码字节上限、响应 1:1 保序），修复 3376 条字幕
  耗时 6.5 分钟（5.8 行/秒）的串行瓶颈；补齐漏译重译、并行翻译与 `probe()`。
- **声纹自动过滤**：设置页/转录页新增自动过滤开关、最小保留比、结果提示与报告输出，
  主界面与 `vt_engine_ui` 四处同步挂载，配套 284 行自检。
- **校准双轨化**：`agent_cli` 与 GUI 运行时直连 `src/calib_core`；`audit` 子命令内建
  反向核查／误改反查／同词族一致性三扫；新增 `--pbz`（影之刃零）词表。
- **术语沉淀**：3.8 直播片二校（修 Sushi 锚过宽、Echo 单数漏校、Lily 跨语义误伤）、
  TRANSCENDO 专名修正、明日方舟哲学片与鸣潮 Part2 二次精校，全部回灌真源并重新生成单体。
- **决策模型技能**：新增 `decision-model` 技能卡，接百炼 Token Plan 的结构化判定端点，
  用于字幕校准歧义裁决等低延迟判定场景。

## 改进

- 打包配置：spec 递归收全 `calib_core`，内置 `faster_whisper` 系依赖与 `asr_local_paths`；
  iss 补齐安装版 `src\` 方式运行所需的 3 处源码副本。
- 任务路径前缀剥离、流水线空内容自愈、工作区分桶清理工具、UI 契约与基线快照更新。
- `SKILL.md` 三份技能卡同步双轨口径：改规则一律改 `src/calib_core/data/*.py` 真源，
  改完重新生成并跑 `build_calib_monolith.py --check`。

## 修复

- 修校准三处根因：`Sushi` 锚过宽把真·寿司误改为角色「穗穗」；`\bechoes?\b`
  不匹配单数 `echo` 导致漏校；`\bLily\b` 把版本标题「旧梦凋零的百合」误改为角色「莉莉」。
- 修在线翻译自研线挂在已失效端点、`probe()` 硬编码不可用导致选谷歌即失败的问题。
- 修安装版按 `src\` 方式运行时本地转录 ImportError 的打包缺漏。

## 验证

- `build_calib_monolith.py --check`：CHECK OK，1055 个 Entity，生成物与真源一致。
- `_selftest_calib_core.py`：**PASS 381 / FAIL 0**。
- `check_secrets.py` 工作区/暂存区 clean；pre-push 全历史门禁仅命中已知已吊销残留。
- 《文件版本清单》按 git blob SHA-1 口径重生成，逐条与最终提交比对 0 差异。
- `check_doc_drift.py --ci` 与全量模式通过。
- 离线安装包构建成功（Inno 编译 570.1s，1,042,849,654 B）；
  在线安装器 12,573,348 B；`build_online_release.py --dry-run` 校验通过。

## 下载

| 文件 | 体积 | 说明 |
| --- | --- | --- |
| `VideoToolbox_Setup_v2.9.0.exe` | 约 1.0 GB | 离线安装包，新用户首选 |
| `VideoToolbox_OnlineSetup_v2.9.0.exe` | 约 12 MB | 在线安装器，只下载缺失文件 |

SHA-256 校验：

```
0fecdbc76218952173739a8420639344a14b5c673a4e434392912d678cd3b461  VideoToolbox_Setup_v2.9.0.exe
8daea0e6a0aeacc8745251e80fc1d1484d37abe77dbb9ca926d182b32eb38a0a  VideoToolbox_OnlineSetup_v2.9.0.exe
```

已装旧版：打开程序 → 设置 → 程序更新 → 检查更新。更新失败时改用离线包
覆盖安装，`data\` 会保留。

## 安装

1. 双击运行安装包，向导全程简体中文；
2. 默认装到 `D:\VideoToolbox`，可以改；不需要管理员权限，不会弹 UAC；
3. 装完从开始菜单或桌面快捷方式启动。

## 已知限制

- **本地 ASR 模型权重不随任何安装包分发**。faster-whisper 的功能代码与运行依赖已内置，
  但 `large-v3` / `small.en` 权重需用户自备：放到安装目录下
  `{app}\tools\asr_model\faster-whisper\`，或在「设置 → ASR → 本地独立模型」指定目录。
  缺少权重时本地转录会**明确报错**，不会静默切回云端。离线全量包、在线安装与
  程序内增量更新三种渠道均不含权重。
- 必剪 bcut 的 B 接口当前固定返回 412；请使用设置页的自有 ASR 服务或本地 faster-whisper。
- 下载队列/统一 job 层保留回退开关（`VT_DL_QUEUE=0`、`VT_DL_ORCH=legacy`）；
  分段依赖下载可用 `VT_DEPS_SEGMENTED=0` 回退。
- Windows 路径上限仍存在；超长标题会截断并追加哈希，极长路径场景建议缩短下载目录。
- 语音分离仍是占位能力，不内置模型。
