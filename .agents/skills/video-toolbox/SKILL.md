---
name: video-toolbox
description: 视频工具箱的字幕翻译/术语校准/视频下载/语音转录/字幕合成能力与精确调用方式。当用户要求翻译字幕、校准字幕术语（终末地/明日方舟/鸣潮/战双等游戏）、下载视频、语音转录出字幕、把字幕合成进视频，或需要把工具箱当 skill 直接调用时使用。触发词：翻译字幕、校准、终末地、明日方舟、鸣潮、战双、字幕合成、转录、agent_cli、SKILL.md。
---

# 视频工具箱 · Agent 技能卡

> **铁律 1：思考过程与最终汇报一律使用简体中文，不要用英文思考。**
> **铁律 2：工具箱程序根目录 = 你的工作目录（cwd）。所有能力经统一 CLI 调用，不要重新实现、不要漫游式探索代码结构。**

## 运行方式（唯一入口）

```bash
tools\python\python.exe src\agent_cli.py <子命令> [参数] --json
```

- 必须用程序自带的 `tools\python\python.exe`（系统 Python 缺引擎依赖）。
- `--json` 放子命令前后都认；此时 stdout 只落一个 JSON 对象，过程日志走 stderr。
- 产物默认落 `data\agent_out\<时间戳>\`，`--out` 可覆盖。
- AI 模型/密钥/接口地址读 `data\ai_config.json`（「设置」页配置），CLI 不设密钥参数。
- 失败时 JSON 的 `error` 字段就是原因，据此换方案，不要原样重试。

## 源码布局（v3.0.0 模块独立文件夹）

- 功能实现都在 `src\features\<id>\`（16 个功能包，如 split/translate/compose/transcribe/subtitle_edit/library/pipeline/download/calibrate/voiceprint/automation/harness）；每包＝feature.py 清单 + cli.py 子命令 + page.py 页面 + 实现模块。
- `src\` 顶层只留入口（video_toolbox_qt/agent_cli/video_toolbox）、壳层（ui_theme/qt_compat/vt_update_check）、共享接缝（engine_asr_data/engine_entities/engine_cache/engine_paths/engine_task_factory/subtitle_editor_core）。
- 确需查源码按功能包精准 grep；**禁止新增顶层功能域模块**。完整约定见 docs/程序说明书(开发版).md §2.7。

## 能力表（直接调用，别自己搓）

| 子命令 | 干什么 | 示例 |
|---|---|---|
| `status [--ping]` | 环境自检：ffmpeg/yt-dlp/deno 在位性、AI 与 ASR 槽是否已配 | `status --json` |
| `info <file>` | 媒体元信息（ffprobe）/ 字幕 cue 数与时间跨度 | `info ep01.mp4` |
| `download <url> [--height 1080] [--dir D]` | 下载（yt-dlp 全链：自动代理+游客 cookie+风控重试，合并 mp4） | `download "https://…" --height 1080` |
| `transcribe <file> [--lang ja] [--out x.srt]` | 音视频 → SRT（引擎 ASR 全链；模型/密钥读设置页 ASR 槽） | `transcribe ep01.mp4 --lang ja` |
| `translate <srt> [--to zh-Hans] [--engine bing]` | → 中文双语 SRT（原文在上、译文在下，时间轴不动） | `translate ep01.en.srt --engine bing` |
| `calibrate <srt> [旗标] [--out F] [--report R]` | 术语校准（只改文字，不动时间轴/序号/空行/换行/BOM） | `calibrate ep01.zh.srt --endobi` |
| `stabilize <srt> [--out F]` | cue 稳定化（同进程直连 calib_core；`VT_CALIB_SUBPROCESS=1` 回退根脚本透传） | `stabilize ep01.srt` |
| `compose <video> <sub> [--mode soft\|burn\|mkv] [--audio x.m4a] [--out F]` | 字幕合成（soft=软封装不重编码；burn=ASS 硬烧；mkv=封装） | `compose ep01.mp4 ep01.srt --mode burn` |
| `audit <srt> [--out R]` | 校准后漏校三扫（拉丁残留/知识库错形残留/同词族一致性；退出码 1＝有候选，可当门禁） | `audit ep01.zh.srt` |
| `split <video> --points "…" \| --durations "…" [--mode copy\|auto\|encode] [--verify quick\|full] [--out D]` | 视频切片：按时间点（HH:MM:SS）或时长（xHyMzS）拆多段，逐段校验可播放 | `split ep01.mp4 --durations "1h,1h"` |
| `bili-submit [素材目录] [--probe\|--dry-run\|--edit] [--only basic,chapters,…] [--visibility self\|public]` | B 站后台自动投稿（UIA 定位 + PostMessage 后台输入；素材目录含投稿信息.txt） | `bili-submit data\素材 --dry-run` |

## 标准配方

### 「翻译，然后完成校准」（最常见）

1. `info` 确认 cue 数与源语言；
2. `translate --engine bing` 出双语 SRT——**谷歌端点本机 429/421 不可用，不要尝试 google**；
3. `calibrate` 按游戏选旗标（见下表）；
4. 汇报：产物路径、cue 数、校准改动数。

### 一条龙：下载 → 转录 → 翻译 → 校准 → 合成

`download` → `transcribe --lang <源语言>` → `translate` → `calibrate` → `compose`。

## 校准旗标速查（与 src/calib_core 完全同源）

> 双轨（2026-11-09）：`agent_cli` / GUI 运行时直连 `src/calib_core`；根目录 `subtitle_calib_merged.py` 为生成物，供知识同步链与外部 `D:/原片/` 工作流读取。改真源后须重新生成并跑 `build_calib_monolith.py --check`。

| 片源 | 旗标 |
|---|---|
| 终末地·中英双语（英文参考行不动） | `--endobi` |
| 终末地·单语 | `--endo` |
| 明日方舟本体（英语原声+中文） | `--ak` |
| 日语原声 | `--ja`（含英文参考行用 `--jpe`） |
| 韩语原声 | `--ko` |
| 鸣潮（中英/双语，默认模式） | 不加旗标 |
| 战双帕弥什 | `--pgr` |
| 其他 | `--zho` / `--zel` |
| 长句断行（≥14 字在标点处拆两行） | `--layout` |
| 修正英文参考行的 ASR 错词 | `--fix-en` |

不带 `--out` 时校准只做「术语命中统计」不改文件；带 `--out` 才落盘。`--report` 出 TSV 差异报告。

## 已知坑（2026-10-15 实测）

- 谷歌免费端点（translate.googleapis.com gtx）本机 429/421；必应 edge 端点（`--engine bing`）直连可用、顺序一一对应。
- 机翻专有名词必然不准（如 Arknights Endfield → "恩德菲尔德"）——校准步骤就是干这个的，不要手工逐条改。
- 校准/稳定化/漏校审计默认同进程直连 `src\calib_core`（`VT_CALIB_SUBPROCESS=1` 回退根脚本透传），退出码原样保留（`length` 子命令用退出码当门禁）；`data\subtitle_learned_kb.json` 是学习库，校准跑完会更新其中的日期书签，属正常现象。
- 一次性脚本放 `data\tmp\`；脚本内取程序根用 `os.getcwd()`（harness/agent 的 cwd 就是程序根），**不要**用 `__file__` 相对推导（放 `data\tmp\` 下会算错）。
- `harness\` 是只读第三方部署，禁止改动；`src\` 是工具箱源码，可读可改。
- 路径在程序根之外没关系（托管 agent 有 danger-full-access），但读大文件前先 `info` 看规模。

## 独立 CLI（统一入口之外）

```bash
tools\python\python.exe src\features\voiceprint\speaker_voiceprint.py enroll --src 视频.mp4 --name 主播 --auto
tools\python\python.exe src\features\voiceprint\speaker_voiceprint.py list|assess|audit|score|filter …
tools\python\python.exe src\features\voiceprint\voiceprint_sync.py sync|push|backfill|status
```

- 声纹录入/素材体检/打分/筛选与多用户模板同步不在统一 CLI，走上面的独立脚本（cwd=程序根）。
- B 站投稿与视频切片已入统一 CLI（`bili-submit` / `split`），优先统一入口。

## 数据目录布局

```
data\
  ai_config.json      「设置」页的 AI/ASR 配置（CLI 唯一读取处）
  agent_out\          CLI 产物（<时间戳>\ 每次调用一个目录）
  downloads\          下载产物（GUI 与 CLI 共用）
  tmp\                一次性脚本/中间产物
  harness-home\      内置 AI 托管（harness）的运行期数据
```
