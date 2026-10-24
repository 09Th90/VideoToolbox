<!-- @version 2.6.0 -->
# Video Toolbox — User Manual

Applies to: v2.6.0

> For end users. No Python setup is required for the installed build.
> Developer-facing details are in `docs/程序说明书(开发版).md`.

## Contents

1. [What It Does](#1-what-it-does)
2. [Installation & First Launch](#2-installation--first-launch)
3. [Interface & Workflow](#3-interface--workflow)
4. [Video Processing](#4-video-processing)
5. [Video Library](#5-video-library)
6. [Subtitle Processing](#6-subtitle-processing)
7. [Term Calibration](#7-term-calibration)
8. [Subtitle Editor](#8-subtitle-editor)
9. [Pipeline](#9-pipeline)
10. [Automation: Bilibili Upload](#10-automation-bilibili-upload)
11. [AI Harness](#11-ai-harness)
12. [Settings](#12-settings)
13. [Files, Backup & Privacy](#13-files-backup--privacy)
14. [Update & Uninstall](#14-update--uninstall)
15. [Command Line (Source Mode)](#15-command-line-source-mode)
16. [FAQ](#16-faq)
17. [Appendix](#17-appendix)

---

## 1. What It Does

Video Toolbox puts the whole subtitling workflow into one Windows window:

**find a video → download it → transcribe → translate → calibrate names →
sync the timeline → put the subtitles back into the video.**

Each step works on its own, and the pipeline can run the chain automatically.

| Page (Chinese label) | Purpose |
| --- | --- |
| 首页 Home | Create tasks, check status and logs |
| 视频处理 Video | Download videos/subtitles, merge separate audio/video |
| 视频库 Library | Scan and browse local videos |
| 字幕处理 Subtitles | Transcribe, translate, calibrate, compose |
| 字幕编辑 Editor | Adjust subtitle timing against the picture |
| 流水线 Pipeline | Link-driven or download-folder automation |
| 自动化 Automation | Bilibili upload templates and jobs |
| 设置 Settings | The only settings entry point |
| AI 托管 AI Harness | Conditional page for the built-in AI agent |

Eight pages are always in the navigation; Automation and AI Harness load after
the first frame (AI Harness only appears when its runtime is available).

### What it does not do

- It does not provide video sources.
- It does not bypass paywalls or account permissions.
- Machine translation is a first pass; proper nouns still need calibration.
- It is not a video editor (no multi-track editing, effects or color grading).
- Voice separation is a placeholder; no model is bundled.
- The AI harness engine (about 2.2GB) is not included in the installer.

### Requirements

- Windows 10/11, 64-bit.
- No administrator rights needed. Default install path is `D:\VideoToolbox`.
- Reserve at least 6GB of disk space (the offline installer is about 1.0GB,
  and FFmpeg/yt-dlp/ASR models/player components are downloaded on demand).
- AI features require your own OpenAI-compatible endpoint and key.

---

## 2. Installation & First Launch

### Choose an installer

| Package | Best for | Notes |
| --- | --- | --- |
| `VideoToolbox_Setup_v2.6.0.exe` | New users, offline deployment | About 1.0GB |
| `VideoToolbox_OnlineSetup_v2.6.0.exe` | Existing users with good network | Downloads only missing files |
| Source mode | Running the latest code | Python 3.12 required, see section 15 |

Already installed? Open **设置 → 程序更新 → 检查更新**. The updater downloads only
changed files. The same version can be repaired with “修复安装”.

### Steps

1. Run the installer. The wizard is Simplified Chinese and does not ask for a
   language.
2. Keep or change the default path `D:\VideoToolbox`.
3. Launch from the Start menu or desktop shortcut.
4. The installed `docs\` folder contains this manual, the Chinese manual, the
   quick reference, the GPL text and third-party notices.

Since v2.6.0 the app uses an **onedir** layout: the install directory contains
`视频工具箱.exe` and `_internal\`. Do not copy the exe alone.

### First launch

- A splash screen appears, then the Home page.
- Missing runtimes are downloaded on demand.
- `data\` and `logs\` are created under the program directory.
- If antivirus blocks the app, add the install directory to its trust list.
  The executable is not code-signed.

### AI configuration (optional)

Open **设置 → 全局 AI** and fill in:

- Enable AI (master switch)
- API key
- Base URL (OpenAI-compatible)
- Text model
- Vision model
- Test connection
- Save and apply

Keys are stored in `data\credentials.json` (read-only, not distributed, not
uploaded). `data\ai_config.json` no longer stores plaintext keys.

Without a key you can still use: download, merge, transcription, machine
translation, script-based calibration, composition, editor and pipeline
(without AI calibration).

### ASR configuration (optional)

**设置 → ASR 语音识别** supports:

- A Whisper-compatible ASR service (URL, key, model, protocol).
- A local faster-whisper model (model name and directory).

Use “测试 ASR 配置” before a long job.

---

## 3. Interface & Workflow

### Drag and drop

- **Link** → Video page, link filled in.
- **Plain text** with AI Harness ready → harness; otherwise a warning.
- **Video/audio** → Subtitle page (transcription).
- **Bilingual subtitle** → Subtitle page (calibration).
- **Monolingual subtitle** → Subtitle page (translation).
- **Folder** → Video Library.
- **Subtitle/audio/video onto the Editor** → loaded for editing.
- Dropping onto the app icon follows the same rules.

### Shortest path

1. Download the video.
2. Transcribe to SRT.
3. Translate to Chinese (bilingual).
4. Calibrate with the correct source type; enable AI calibration if needed.
5. Check the timeline in the Editor and export.
6. Burn or mux the subtitles into the video.

The Pipeline can run the same chain automatically.

---

## 4. Video Processing

### Download

1. Paste a link.
2. Pick a quality. Only 720p and above are listed, one entry per resolution;
   >30fps is preferred, then the larger file. The first item is “最高，推荐”.
3. Enable “同时下载字幕” to convert available subtitles to SRT.
4. Start. Jobs can run in parallel and can be cancelled.
5. Default output: `data\downloads` (configurable in Settings).

### Cookies and network

There is no cookie box on the download page. Use
**设置 → 下载 Cookie（反风控）**:

- Auto
- Read from one of 8 browsers
- Your exported `cookies.txt`
- Guest cookies only

The app has an internal proxy fallback; there is no proxy switch in the UI.

### Audio/video merge

**Automatic pairing**

- Video: mp4/mkv/webm/mov, etc.; audio: m4a/weba, etc.; subtitles: srt/ass.
- Default input `D:\剪辑`; empty output means `<input>\合成结果`.
- ASS subtitles default to **burn-in**; you can choose MKV muxing or ignore.
- Same-name files with different durations can be forced to pair.

**Manual merge**

- Video and audio are required; subtitle is optional.
- Non-AAC audio is transcoded; video that cannot fit MP4 is re-encoded to H.264.

---

## 5. Video Library

- Scans the download directory automatically after launch.
- Recursively finds videos; skips hidden folders and `thumb_cache`.
- Thumbnails are taken at 5 seconds (or 0 for short clips).
- Cache: `data\thumb_cache`; safe to delete.
- **Click**: open the containing folder and play with the system player.
- **Right click**: open the folder only.

---

## 6. Subtitle Processing

The page has three sections: transcription, translation and calibration.

### Transcription

1. Choose an audio/video file.
2. Choose the model source (Settings ASR config or a temporary ASR choice).
3. Language defaults to auto-detect; specifying it is usually more reliable.
4. Enable speaker diarization if needed.
5. Start and get an SRT.

“语音分离” is a placeholder; speaker splitting is selected when exporting from
the Editor (“按说话人拆分”).

### Translation

- Engines: Microsoft (default), Google, DeepLx.
- No LLM translation is provided in this version.
- Layout: translation on top (default), original on top, translation only,
  original only.
- The calibration step detects Chinese lines by character set, so the order of
  Chinese/English does not matter.
- Voiceprint filtering is available after translation.

### Composition

| Form | How | Notes |
| --- | --- | --- |
| Soft subtitles | Editor → embed subtitles | No re-encode; toggleable |
| Hard subtitles | Merge, ASS → burn-in | Re-encode; maximum compatibility |
| MKV mux | Merge, ASS → MKV | Keeps subtitle track; no re-encode |

The CLI `compose` command supports `soft`, `burn` and `mkv`.

---

## 7. Term Calibration

### Why

Machine translation usually gets grammar roughly right but proper nouns wrong:
character names, places, skills, items. Calibration unifies them with the
official names without touching the subtitle structure.

### Two passes

1. **Script calibration** — term tables + context regex. Fast, repeatable,
   always run first.
2. **AI calibration** — an LLM reviews chunks the tables could not cover.
   Uses your AI quota; results still need review.

### Source types (GUI)

- Chinese-English bilingual (default, `--bi`)
- Japanese · Wuthering Waves (`--ja`)
- Japanese · Endfield (`--jpe`)
- Korean · Wuthering Waves (`--ko`)
- Arknights (`--ak`)
- Arknights · Korean (`--akko`)
- Endfield (`--endo`)
- Endfield · Chinese-English (`--endobi`)
- Endfield · Korean (`--endoko`)
- Chinese lines only (`--zho`)
- Punishing: Gray Raven (`--pgr`)
- PGR English source (`--pgren`)
- Mobile-game OST (`--wwoc`)
- Music reaction (`--react`)

The CLI also supports Zelda (`--zel`), Honkai: Star Rail (`--hsr`) and Pokémon
(`--pkm`). Choosing the wrong source type can damage correct lines.

### Guarantees

- Sequence numbers, timestamps, blank lines, line endings and BOM are preserved.
- Only Chinese lines are changed by default; reference lines are untouched
  unless `--fix-en` is used.
- `--endo` only changes Chinese lines.
- Always spot-check the report; calibration is not a substitute for reading.

### Knowledge sync

**设置 → 校准知识同步**:

- Enable automatic sync (update on start, upload in background on exit)
- Update now

Only rule text is synced; videos and subtitles are not uploaded. The local
knowledge base is `subtitle_learned_kb.json`.

---

## 8. Subtitle Editor

- Opens SRT/VTT/ASS/SSA; exports SRT or ASS.
- ASS export keeps the current style.
- Speaker splitting is available for multi-speaker subtitles.
- Undo stack: 100 steps; minimum cue boundary: 40ms; overlap/short warnings.

### Shortcuts

| Key | Action |
| --- | --- |
| Space | Play/pause |
| `,` `.` `←` `→` | Step one frame |
| `Shift+←/→` | 0.1s |
| `Alt+←/→` | 1s |
| `↑` `↓` | Previous/next cue |
| `[` `]` | Set start/end |
| `Ctrl+K` | Split at playhead |
| `Ctrl+A` / `Del` | Select all / delete |
| `Ctrl+Z` / `Ctrl+Y` | Undo / redo |
| `Ctrl+S` / `Ctrl+Shift+S` | Save / save as |
| `Ctrl+O` / `Ctrl+Shift+O` | Open video / subtitle |
| `Ctrl+=` `Ctrl+-` `Ctrl+0` | Zoom in/out/reset |
| `Ctrl+Shift+F` | Fit selected |

There is no magnetic-snap toggle in this version.

---

## 9. Pipeline

- Link chain: **download → translate → calibrate → second calibration → output**.
- Folder monitoring watches the **download directory** for new videos; there is
  no separate folder picker.
- Auto mode is on by default; concurrency 1–8, default 3.
- Progress is stored in `data\pipeline_state.json`.
- On restart: DONE jobs are skipped; RUNNING jobs return to READY.
- Buttons: scan now, retry failed, clear progress.

Not ideal for long videos that need line-by-line human editing, mixed-language
sources, or links that require manual verification.

---

## 10. Automation: Bilibili Upload

### Prerequisites

- A browser logged in to Bilibili.
- Global AI configured (zone/topic detection uses vision and text models).
- Templates collected on the Automation page.

### Templates

13 templates: 10 required + 3 optional (参与话题, 第一张候选封面,
创作声明「自制」).

Collection flow: choose window → capture frame → draw box → save as template.
The page shows ✓/✗ and hints. Missing required templates block execution.

### Form

Fields: video, title, description, tags, zone, topic.
“从 视频信息.txt 读取” searches the current and parent directory and parses
title, description, tags, zone and topic. Dry-run is on by default; turn it off
to actually submit. Jobs run in a background thread; failures save a full-screen
screenshot under `data\bili_upload\shots`.

### CLI uploader (source mode)

v2.6.0 adds `src\bili_auto_submit.py`, a UIA + PostMessage automation that does
not move the real cursor. It is used only by `agent_cli bili-submit`; the GUI
does not import it and the installer does not include it.

```bash
tools\python\python.exe src\bili_auto_submit.py "<media-dir>" --dry-run
tools\python\python.exe src\bili_auto_submit.py "<media-dir>" --visibility self
tools\python\python.exe src\bili_auto_submit.py --probe
```

The media directory should contain the video, cover, subtitle and
`投稿信息.txt` (or `视频信息.txt`). Run `--probe` first, then `--dry-run`.

---

## 11. AI Harness

- Conditional page; only appears when the harness runtime is available.
- Cards: status, tasks, runtime output.
- Workspace: the program root. Runtime data: `data\harness-home`.
- Buttons: open/stop console, re-detect, hand over to AI.
- The harness engine (about 2.2GB) is not bundled; deploy it separately.
- Missing harness does not affect other features.

---

## 12. Settings

In page order:

1. **目录**: download directory, data root, engine work directory.
2. **下载 Cookie（反风控）**: auto/browser/cookies.txt/guest; 8 browsers.
3. **全局 AI**: enable, key, base URL, text/vision model, test, save.
4. **ASR 语音识别**: service/local, language, URL/key/model/prompt/protocol,
   diarization, voice separation placeholder, test, save.
5. **AI 校准**: chunk size, character budget, thinking mode/strength, context,
   output limit, style, web verification, A/V evidence, rounds, cluster,
   collaboration.
6. **字幕引擎**: transcription/translation/composition parameters.
7. **校准知识同步**: automatic sync, update now.
8. **程序更新**: current version, check update, repair install.
9. **界面美化 / 界面**: background, theme, scaling, Mica, accent color.
10. **关于**: version, license, third-party notices.

---

## 13. Files, Backup & Privacy

### Install directory

Default `D:\VideoToolbox`:

- `视频工具箱.exe`
- `_internal\` (runtime, required)
- `tools\` (Python, FFmpeg, yt-dlp, Deno, mihomo, etc.)
- `src\` (source, useful for troubleshooting and CLI)
- `docs\` (manuals and licenses)
- `data\` (user data)
- `logs\` (logs)

### data\

`ai_config.json`, `credentials.json`, `config.json`, `subtitle_style.json`,
`ui_custom.json`, `videocaptioner\settings.json`, `downloads\`, `thumb_cache\`,
`tmp\`, `pipeline_state.json`, `bili_upload\shots\`, `harness-home\`.

### Backup

Back up at least:

- `data\ai_config.json`
- `data\credentials.json`
- `data\subtitle_style.json`
- `data\ui_custom.json`
- `subtitle_learned_kb.json`
- `data\calib_sync*` (if sync is used)

To migrate, copy the whole install directory including `data\`. Copying only the
exe will not work because `_internal\` and `tools\` are required.

### Privacy

- Keys stay in `data\credentials.json` and are never distributed.
- Calibration sync uploads rule text only.
- Online AI/ASR/translation send the relevant text to the provider you choose.
- Cookies and browser sessions stay local; clear them on a shared PC.

---

## 14. Update & Uninstall

### Check for updates

**设置 → 程序更新 → 检查更新**. The updater reads the manifest from GitHub
Releases (fixed `repo-latest` channel), downloads only files whose sha256
changed, verifies them and restarts. The same version can be repaired. If the
update fails, install the offline package over the existing installation.

### Uninstall

Use Windows “Installed apps” or the Start-menu uninstaller. Uninstalling does
**not** delete `data\`, `logs\` or your downloads. To remove everything, delete
the install directory manually after uninstalling.

---

## 15. Command Line (Source Mode)

The installed package provides the GUI. The CLI lives in the source tree and is
intended for batch jobs and automation.

```bash
tools\python\python.exe src\agent_cli.py status --json
tools\python\python.exe src\agent_cli.py info "<video>"
tools\python\python.exe src\agent_cli.py download "<url>" --height 1080
tools\python\python.exe src\agent_cli.py transcribe "<video>" --lang ja
tools\python\python.exe src\agent_cli.py translate "<srt>" --engine bing
tools\python\python.exe src\agent_cli.py calibrate "<srt>" --endobi
tools\python\python.exe src\agent_cli.py stabilize "<srt>"
tools\python\python.exe src\agent_cli.py audit "<srt>"
tools\python\python.exe src\agent_cli.py compose "<video>" "<srt>" --mode burn
tools\python\python.exe src\agent_cli.py bili-submit "<media-dir>" --dry-run
```

All commands accept `--json`. Check the `error` field on failure.

### Source mode

```bash
git clone https://github.com/09Th90/VideoToolbox.git
cd VideoToolbox
pip install -r requirements.txt
python src/video_toolbox_qt.py
```

Python 3.12 is required. Run from the repository root; the app locates `tools\`
and `data\` relative to the current directory.

---

## 16. FAQ

**Downloads are slow or fail.** Try another network/proxy and refresh cookies.
GitHub's international link is often the bottleneck.

**The downloaded video has no sound.** Audio and video may be separate; use
Video Processing → Merge (automatic or manual).

**Transcription fails.** Check ASR URL/key/model/protocol; test the config.
For a local model, check the model directory.

**Google translation is unavailable.** The free Google endpoint is often blocked
on some networks; use Microsoft translation.

**Calibration changed nothing.** The source type may be wrong, or the tables
already cover the file. Read the report; do not add terms just to see changes.

**Calibration broke a normal word.** Choose the correct source type; use
`verify` to check structure and `subfix` for a single-line rollback.

**Subtitles are out of sync.** Fix the timeline in the Editor with frame and
0.1s adjustments; do not shift the whole file to fix a middle section.

**Burning is slow.** Hard subtitles require re-encoding. Use soft subtitles or
MKV muxing when speed matters.

**Bilibili upload cannot find a control.** Recollect the missing template,
check browser zoom/layout/login state. Screenshots are in
`data\bili_upload\shots`.

**Update failed.** Install the offline package over the existing installation;
`data\` is preserved.

**The AI Harness page is missing.** The harness runtime is not deployed, or the
adapter is not ready. Other features are unaffected.

---

## 17. Appendix

### Formats

- Video: mp4, mkv, webm, mov, etc. (FFmpeg-dependent)
- Audio: m4a, weba, mp3, wav, etc.
- Subtitles: read SRT/VTT/ASS/SSA; export SRT/ASS.
- Composition: soft subtitles, hard subtitles, MKV mux.

### Glossary

| Term | Meaning |
| --- | --- |
| Transcription | Speech to text (SRT) |
| Translation | Subtitle translation, usually bilingual |
| Calibration | Text-only normalization of proper nouns |
| Soft subtitles | Separate track, toggleable |
| Hard subtitles | Burned into the picture |
| Pipeline | Automated download→translate→calibrate→output chain |
| Voiceprint | Speaker feature used to separate speakers |
| Template | Captured screenshot/coordinates of an upload control |

### License

The application itself is released under CC BY-SA 4.0. The combined work
distributed in the installer (application + GPL-3.0 components) is provided
under GPL-3.0. See `docs/开源许可_GPL-3.0.txt`, `LICENSE` and
`docs/第三方组件来源与许可声明.txt`.

### Feedback

- Author: <https://space.bilibili.com/507185588>
- Issues: <https://github.com/09Th90/VideoToolbox/issues>
