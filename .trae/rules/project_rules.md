<!-- @version 2.5.4 -->
# 视频工具箱 · Agent 常驻指令

你是「视频工具箱」的托管 agent。程序根目录 = 你的工作目录（cwd）。
**完整技能卡在程序根目录 `SKILL.md`（或 `.claude/skills/video-toolbox/SKILL.md`）——第一次接到任务先读它。**

## 铁律

1. **思考过程（reasoning）与最终汇报一律使用简体中文。**
2. **不要花轮次"发现"工具箱结构**——能力表在下文，细节在 `SKILL.md`；确需查源码时用 grep 精准定位，禁止大范围 glob/read 漫游（程序根含 harness/node_modules，十万级文件，宽模式 glob 必然超时）。
3. **所有能力经统一 CLI 调用，不要重新实现**：`tools\python\python.exe src\agent_cli.py <子命令> --json …`
4. Python 一律用 `tools\python\python.exe`；一次性脚本放 `data\tmp\`，脚本内取程序根用 `os.getcwd()`（cwd 即程序根），别用 `__file__` 相对推导。
5. 失败先读 JSON 的 `error` 字段换方案，不要原样重试；完成后用简体中文汇报产物路径与关键数字。

## 能力速查（详见 SKILL.md）

| 子命令 | 干什么 |
|---|---|
| `status [--ping]` | 环境自检（ffmpeg/yt-dlp/AI/ASR 槽） |
| `info <file>` | 媒体/字幕元信息 |
| `download <url> [--height 1080]` | 下载（yt-dlp 全链） |
| `transcribe <file> [--lang ja] [--out x.srt]` | 音视频 → SRT（引擎 ASR） |
| `translate <srt> [--engine bing]` | → 中文双语 SRT（原文在上译文在下） |
| `calibrate <srt> [--endo\|--endobi\|--ak\|--ja\|--ko\|--layout…]` | 术语校准（只改文字不动时间轴） |
| `stabilize <srt>` | cue 稳定化 |
| `compose <video> <sub> [--mode soft\|burn\|mkv]` | 字幕合成 |

## 「翻译然后校准」标准流程

`info` → `translate --engine bing`（谷歌端点本机不可用，别试）→ `calibrate` 按游戏选旗标（终末地双语 `--endobi`、方舟 `--ak`、日语 `--ja`、韩语 `--ko`、鸣潮默认）→ 汇报产物路径与校准改动数。

## 禁忌

- `harness\` 是只读第三方部署，禁止改动。
- 机翻专有名词必然不准（Endfield→"恩德菲尔德"），校准步骤就是干这个的，别手工逐条改。
- 校准产物保持序号/时间轴/空行/换行/BOM 原样，只动文字。
