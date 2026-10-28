<!-- @version 2.8.0 -->
# 视频工具箱 v2.8.0

> 本版新增下载任务队列与暂停/恢复，流水线支持无字幕自动转录，
> 并扩充边狱巴士、最终幻想：共鸣两套校准词表；同时修复 ASR 配置、
> 长路径与游客 cookie 等问题。本版包含 v2.7.0 的校准脚本源码拆分
> （单文件由 `calib_core` 生成，行为不变）。

## 新增

- **下载任务队列**：视频处理页支持多任务排队、并发上限 1–6（默认 2）、
  暂停/继续、速度与剩余时间列、同链接去重；调低并发不会打断正在下载的任务。
- **统一下载编排**：GUI 与 `agent_cli download` 共用 `core/download/job.py`
  的阶段编排；字幕拉取/补拉/归一化拆到 `core/download/subtitles.py`。
  可用 `VT_DL_ORCH=legacy` 回退旧路径，`VT_DL_QUEUE=0` 回退单任务模式。
- **分段依赖下载**：yt-dlp / ffmpeg / deno 等依赖优先走 Range 多线程分段下载，
  支持断点续传、SHA-256 校验、镜像回退与原子替换；失败自动回退单流。
  可用 `VT_DEPS_SEGMENTED=0` 强制旧单流。
- **无字幕自动转录**：流水线在下载后检测不到字幕时，自动调用设置页的 ASR
  做语音转录，再进入翻译/校准；转录阶段有串行锁，避免多个任务同时打满显存/带宽。
- **转录页命令栏**：识别语言与输出格式移到顶部命令栏，随选随用；
  常用语言与引擎枚举逐字对齐，选错标签会静默回落到自动检测的问题已收口。
- **校准新模式**：
  - 边狱巴士（`--limbus`）：`LIMBUS_TERMS` + `LIMBUS_CONTEXT`，配合 ENTITIES
    落官方中文；游戏名保留「边狱巴士」，组织名「边狱公司」。
  - 最终幻想：共鸣（`--ffrs`）：`FFRS_TERMS` + `FFRS_CONTEXT`，覆盖
    《最终幻想：共鸣》《最终幻想：勇气启示录》等作品名与 Visions/Stagger 等歧义词。
- **词表扩充**：六套游戏名词底表共 **3917 条**（鸣潮 2063 · 终末地 1186 ·
  明日方舟 530 · 战双帕弥什 69 · 边狱巴士 7 · 最终幻想：共鸣 62）。

## 改进

- **ASR 选择更可靠**：转录模型停在「默认」、且已配置全局 ASR 时，建任务前
  自动切到 ASR；用户显式选择 Whisper [API] / FasterWhisper 时不覆盖。
- **智能合并**：视频容器自带音轨时不再等待独立的 m4a，避免任务卡在合并阶段；
  同目录仍有未配对的 m4a/weba 时保持等待。
- **长标题路径收敛**：转录工作目录与产物文件名按 Windows 248 字符预算
  截断并追加确定性 crc32 后缀，避免产物写得出却读不回。
- **翻译顺序**：流水线优先必应，必应不可用才回退谷歌。
- **下载依赖**：GitHub 前缀镜像只使用已验证可配置的 gh-proxy，并校验
  文件大小与 SHA-256，减少半截文件与镜像污染。

## 修复

- 修复 ASR 设置使用项目自建枚举类、被引擎 `OptionsValidator` 静默拒绝，
  导致「设置页已切 ASR、任务仍走 B 接口」的问题。
- 修复必剪 bcut `task/result` 固定 HTTP 412 后，转录页「默认」模型仍把任务
  送进必剪的问题（已配置 ASR 时自动切换）。
- 修复游客 cookie 抓取缺少 `urllib.request` 导入，导致该兜底通道静默失效。
- 修复下载队列重复添加同一链接、暂停后状态回弹等队列状态问题。
- 修复校准帮助未列出 `--limbus` / `--ffrs` 及部分历史旗标说明的问题。

## 验证

- `check_syntax`、`check_names`（180 个 src 模块）、`check_secrets`、
  `check_doc_drift --ci`、`check_deps` 通过。
- 下载链：`_selftest_download_job` 11/11、`download_queue` 27/27、
  `download_pause` 7/7、`segment_download` 15/15、`download_cancel` 29/0、
  GUI 队列 10/10。
- 流水线、ASR 语言、任务工厂、`agent_cli`、校准核心（236/0）、
  在线更新链（xval / versions / setup）自检通过。
- `build_calib_monolith.py --check`：单文件与 `calib_core` 源码一致。
- 桌面 GUI 自检：171 项 PASS / 0 FAIL。

## 下载

| 文件 | 体积 | 说明 |
| --- | --- | --- |
| `VideoToolbox_Setup_v2.8.0.exe` | 约 1.0 GB | 离线安装包，新用户首选 |
| `VideoToolbox_OnlineSetup_v2.8.0.exe` | 约 12 MB | 在线安装器，只下载缺失文件 |

SHA-256 校验（构建后回填）：

```
（待回填）  VideoToolbox_Setup_v2.8.0.exe
（待回填）  VideoToolbox_OnlineSetup_v2.8.0.exe
```

已装旧版：打开程序 → 设置 → 程序更新 → 检查更新。更新失败时改用离线包
覆盖安装，`data\` 会保留。

## 安装

1. 双击运行安装包，向导全程简体中文；
2. 默认装到 `D:\VideoToolbox`，可以改；不需要管理员权限，不会弹 UAC；
3. 装完从开始菜单或桌面快捷方式启动。

## 已知限制

- 必剪 bcut 的 B 接口当前固定返回 412；请使用设置页的自有 ASR 服务或
  本地 faster-whisper。
- 下载队列/统一 job 层保留回退开关（`VT_DL_QUEUE=0`、`VT_DL_ORCH=legacy`）；
  分段依赖下载可用 `VT_DEPS_SEGMENTED=0` 回退。
- Windows 路径上限仍存在；超长标题会截断并追加哈希，极长路径场景建议缩短
  下载目录。
- 语音分离仍是占位能力，不内置模型。
