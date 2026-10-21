<!-- @version 2.5.0 -->
# 计划：第三方 Agent 接入工具箱（统一 CLI + SKILL.md）

## Context

工具箱现有「AI 托管」（harness 方向）保留不动。本次新增**反向接入**：把工具箱核心能力封装成统一 CLI，并在根目录提供 SKILL.md 技能说明书——任意第三方 agent（Claude Code、Trae、Codex 等）读 SKILL.md、跑命令即可直接调用工具箱功能，把工具箱当成一个"skill"使用。

用户已拍板：
- **需要** SKILL.md（根目录技能说明书，agent 的唯一学习入口）；
- **不需要** 改 GUI——「AI 托管」页保持原样；
- **不需要** 改打包 iss；
- **不移除 harness**——现有功能与代码全部保留，两者共存。

## 改动内容

### 1. 新建 `src\agent_cli.py`（核心交付物，无 Qt 依赖）

全局参数：`--json`（结构化输出）、`--data-root <dir>`（实现为 import 引擎前设 `VT_DATA_ROOT`，对齐 `video_toolbox.py:292-321` 的优先级）、`--version`；运行前把 `src` 注入 `sys.path` 复用引擎（pipeline/media_registry 的 PySide6 均 try-import 可退化）。

子命令与复用路径（已验证可无 Qt 调用）：

| 子命令 | 复用 | 关键入口 |
|---|---|---|
| `status` | 环境自检 | ffmpeg/yt-dlp 在位性 + AI 配置读取（`engine.ai_load_config()`，`video_toolbox.py:5141`）|
| `info <file>` | 媒体/字幕元信息 | ffprobe + `media_registry` 扫描原语 |
| `download <url> [--dir]` | 下载原语 | `video_toolbox.py:7515 ensure_ytdlp`、`:7863 fetch_info_json`、`:8256 output_template`、`:5906 ytdlp_proxy_args` |
| `transcribe <file> [--lang] [--out]` | ASR | `engine_task_factory.py:84 create_transcribe_task` + `engine_asr.py:154 set_ffmpeg`（必调）+ `engine_asr.py:647 transcribe` |
| `translate <srt> [--to zh] [--engine ...]` | 翻译 | `engine_translate.py:351 make_translator` |
| `calibrate <srt> [校准参数…]` | 术语校准 | **subprocess 透传** `subtitle_calib_merged.py`（877KB 单文件 import 慢、含 GitHub 学习库全局态与退出钩子，须隔离；exit code 透传）；argv 参数表与该脚本完全同源 |
| `stabilize <srt> […]` | cue 稳定化 | 同上透传（已是内建子命令） |
| `compose <video> <sub> [--mode burn\|mkv] [--audio]` | 合成 | `video_toolbox.py:8907 merge_pair`（不走 `ComposeDialog`，它依赖 Qt） |

约定：
- AI 参数一律读 `data\ai_config.json`（不设密钥 CLI 参数，避免泄进 shell history）；
- 产物默认落 `data\agent_out\<时间戳>\`，`--out` 可覆盖；
- `--help` 每个子命令带用法示例与产物路径说明（与 SKILL.md 内容同源）。

### 2. 新建根目录 `SKILL.md`（第三方 agent 技能说明书）

Agent 视角的组织（front-matter 带 name/description，便于支持 skill 协议的宿主直接挂载）：
- 工具箱是什么、能干什么（功能清单一句话一条）；
- 运行方式：`tools\python\python.exe src\agent_cli.py <子命令> …`（含各子命令参数表 + 示例命令）；
- 数据目录布局（`data\`、产物 `data\agent_out\`、AI 配置 `data\ai_config.json` 的字段含义）；
- 注意事项：字幕校准"只改文字不动时间轴"、游戏内容校准优先用 calibrate 的对应语言旗标、上传/账号类功能不暴露等；
- 常见任务配方：如"下载→转录→翻译→校准→合成"一条龙的命令序列示例。

### 3. 自测 `scripts\dev\_selftest_agent_cli.py`

沿用现有 `_selftest_*` 惯例：`--help`/`status --json` 结构断言；对样例字幕（根目录 `gacha_disappointed.srt`）跑 `calibrate`/`stabilize` 冒烟并断言产物存在；`--json` 输出可被 `json.loads` 解析。

## 不做的事（用户明确排除）

- 「AI 托管」页零改动（不改造、不加卡片）；
- `packaging\视频工具箱.iss` 零改动（agent_cli.py 与 SKILL.md 不进安装包，当前以开发目录使用为主）；
- harness 全套（harness_bridge.py、harness_page.py、harness\ 目录、部署文档）原样保留。

## 关键风险与对策

- `subtitle_calib_merged.py` 透传时 exit code 语义（length=1 门禁）原样保留；
- 校准学习库路径显式指向数据根，防写 CWD；
- `engine_asr.transcribe` 前必须 `set_ffmpeg`；
- `video_toolbox.py` 是纯引擎单文件（无模块级 Qt import），但体量大，CLI 对其 import 做惰性加载（用到才 import）。

## 验证

1. `tools\python\python.exe src\agent_cli.py --help` 与各子命令 `--help` 输出完整；
2. `status --json`、`info <样例视频>`、`calibrate gacha_disappointed.srt --ja --out <tmp>`、`stabilize` 实跑通过，产物落盘；
3. SKILL.md 中的示例命令逐条可复制执行；
4. `scripts\dev\_selftest_agent_cli.py` 全绿。
