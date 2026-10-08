<!-- @version 1.17.0 -->
# Video Toolbox — User Manual

> Applies to: v1.16.5 | Last updated: 2026-10-04
> This manual is written for **people who use the software** — it only covers "how to get things done after opening the app."
> For source-code structure, packaging, release procedures, and self-test scripts, see the Developer Manual (`程序说明书(开发版).md`) in the same folder.

---

## Table of Contents

1. [What This Software Can Do for You](#1-what-this-software-can-do-for-you)
2. [Installation & Launch](#2-installation--launch)
3. [First-Time Setup: Enter Your AI Configuration Once](#3-first-time-setup-enter-your-ai-configuration-once)
4. [Video Processing: Download & A/V Merge](#4-video-processing-download--av-merge)
5. [Video Library: Browse Local Videos](#5-video-library-browse-local-videos)
6. [Subtitle Processing: Transcription, Translation, Calibration, Burning](#6-subtitle-processing-transcription-translation-calibration-burning)
7. [Subtitle Editor: Sync Subtitles Against the Picture](#7-subtitle-editor-sync-subtitles-against-the-picture)
8. [Pipeline: Fully Automated, One Link In](#8-pipeline-fully-automated-one-link-in)
9. [Settings Page, Item by Item](#9-settings-page-item-by-item)
10. [Where Everything Is Stored](#10-where-everything-is-stored)
11. [FAQ](#11-faq)

> **Note on UI labels**: the software interface is in Simplified Chinese. Throughout this manual, button and page names are given in English with the original Chinese in parentheses, so you can match them on screen.

---

## 1. What This Software Can Do for You

**Video Toolbox** is a Windows desktop app that packs the entire workflow — *find video → download → produce subtitles → fix subtitles → put subtitles back into the video* — into a single window, so you don't have to juggle multiple programs.

There are six function pages, switched from the navigation bar on the left:

| Page | What it's for |
| --- | --- |
| **Video Processing** (视频处理) | Download videos from YouTube, Bilibili and other yt-dlp-supported sites (including subtitles, cover art, and metadata); also merge separately downloaded video and audio into one file |
| **Video Library** (视频库) | Scan a folder for videos and browse them as thumbnail cards; click to play |
| **Subtitle Processing** (字幕处理) | Generate subtitles for a video, translate them, calibrate proper nouns, and burn subtitles into the picture or mux them into the video |
| **Subtitle Editor** (字幕编辑) | Play the video inside the app while dragging subtitle segments on a timeline to sync them with the picture |
| **Pipeline** (流水线) | Paste one link and run download → translation → calibration → packaging fully automatically; or watch a folder and process new files as they appear |
| **Settings** (设置) | Enter AI keys, speech-recognition services, download directory, UI theme, etc. (the one and only settings entry point in the whole app) |

**No technical knowledge required**: no Python installation, no environment variables — just double-click the icon and go. Features that need AI (subtitle polishing, AI translation, AI calibration) require you to enter your own AI key once; everything else works out of the box.

---

## 2. Installation & Launch

### 2.1 Choosing an Installer

| Installer | Size | Best for |
| --- | --- | --- |
| **Offline installer** `视频工具箱_Setup_v1.15.7.exe` | ~548 MB | Most people. One download; no internet needed during installation |
| **Online installer** `视频工具箱_在线安装_v1.15.7.exe` | ~32 MB | Small download, but pulls ~104 MB of components from the web during installation |

> The online installer downloads components from GitHub Pages (overseas). A direct connection from mainland China is often only a few dozen KB/s. **The slow part is that international link — it's not a software problem.** In that case, switching to the offline installer is the easiest fix.
>
> If you have a local-network distribution source or a proxy tool, the online installer can also be fast — see the "What to do when the online installer is too slow" section in `使用说明.txt`.

### 2.2 Installing and Opening

1. Double-click the installer. The setup wizard is entirely in Simplified Chinese (no language-selection prompt);
2. It installs to `D:\VideoToolbox` by default; you can change this. **No administrator rights are required** — no UAC prompt will appear;
3. After installation, launch from the Start menu or the desktop shortcut, or simply double-click `视频工具箱.exe` in the installation folder.

### 2.3 Handy Ways to Open Things

- **Drag a link onto the app icon**: opens the Video Processing page with the link already filled in — no copy-paste needed;
- **Drag a folder onto the app icon**: opens the A/V merge page with the path filled in;
- **Drag files into the already-open window**: videos and subtitles go to the Subtitle Editor page, link text goes to the download page, and folders go to the Video Library.

### 2.4 If It Won't Open

`视频工具箱.exe` is not code-signed (signing certificates cost money). A small number of PCs with Device Guard or application-control policies enabled will block it. In that case, use the script-based launch instead: double-click `src\视频工具箱.bat` in the installation folder (requires Python 3 on the machine).

Also note the app has **single-instance protection** — double-clicking the icon while the app is already running won't open a second window or corrupt your configuration.

---

## 3. First-Time Setup: Enter Your AI Configuration Once

**Everything except AI features works without AI**: downloading videos, browsing the library, and editing subtitle timelines are all fully functional. Only **Subtitle Polishing** (字幕优化), **AI Translation** (AI 翻译), and **AI Calibration** (AI 校准) need AI. To use them, go to **Settings → Global AI** (设置 → 全局 AI) and enter your configuration once — the whole app shares this single configuration; you never need to re-enter it anywhere else.

Four fields to fill in:

| Field | Example |
| --- | --- |
| API Key (密钥) | The string issued by your service provider |
| Endpoint URL (接口地址) | `https://open.bigmodel.cn/api/paas/v4` |
| Text model (文本模型) | `glm-4.7-flash` |
| Vision model (视觉模型) | `glm-4.6v-flash` (only used by screenshot-recognition features) |

**The endpoint URL doesn't need to be exact** — entering just the domain, up to `/v1`, or the full `/chat/completions` path all work; the software completes it automatically. For Azure, enter up to `deployments/<deployment-name>`.

Compatible services: OpenAI, DeepSeek, Zhipu (GLM), Gemini-compatible endpoints, Ollama (local models), Azure OpenAI — anything with an OpenAI-compatible API.

After filling in, click **"Test Connection"** (测试接口) to verify connectivity, then **"Save & Apply"** (保存并应用) — the settings take effect immediately and are also written into the subtitle engine automatically, so you don't have to change them again in the engine's own settings.

> **About your API key**: the key is stored only in `data\ai_config.json` on your machine. It is not distributed with the software and is never uploaded anywhere. The software's own source code contains no real keys.

### 3.1 Do You Need Speech Recognition (ASR)?

The Subtitle Processing page converts speech in a video into text — this step is called "transcription" (语音转录). The software has several free online transcription engines built in (Bijian, Jianying, etc.), so **transcription works without any ASR setup**.

Setting up ASR lets you choose a more accurate service or a local model. In **Settings → ASR Speech Recognition (Transcription Config)** (设置 → ASR 语音识别（转录配置）), pick one source:

- **Your own ASR service** (recommended): enter the endpoint URL, API key, and model name. Any OpenAI-compatible speech-recognition API works, e.g. `FunAudioLLM/SenseVoiceSmall`, `whisper-1`, or Alibaba Cloud Bailian's ASR service. **No model files need to be downloaded**.
- **Local standalone model**: enter the model name (e.g. `large-v3`, `large-v3-turbo`) and the model directory. This requires a faster-whisper runtime and the corresponding model files on your machine.

Leave the protocol field on **"Auto-detect"** (自动识别) — the software figures out which protocol to use based on the URL and model name you entered. Eleven protocols are currently supported: Auto-detect, OpenAI Whisper-compatible, Azure OpenAI, Chat-audio transcription (Bailian / MiMo), Deepgram, ElevenLabs Scribe, Google Gemini, Volcano Engine (Doubao), AssemblyAI, Bailian Realtime (WebSocket), and Bailian Native (dedicated ASR endpoint).

Click "Test ASR Config" (测试 ASR 配置) when done to verify.

> **A network fix in v1.15.7**: when using a domestic Chinese service (such as Alibaba Cloud Bailian) while a proxy tool is running, requests could be routed through the proxy to an overseas node and fail to connect. The software now forces direct connections for domestic endpoints, so you no longer need to manually disable your proxy.

---

## 4. Video Processing: Download & A/V Merge

The top of this page has two tabs: **Video Download** (视频下载) and **A/V Merge** (音画合并).

### 4.1 Video Download

1. **Paste a link** — YouTube, Bilibili, and any other site supported by yt-dlp;
2. **Choose a save location** — click "Browse…" (浏览…) to pick a folder, or drag a folder into the input box. The choice is remembered permanently: it is auto-filled next time, even if that folder is currently unavailable (e.g. an external drive is unplugged) — plug it back in and it works again;
3. **Click "Detect Quality"** (检测画质) — the app lists all streams at 720p and above. For each resolution only the largest file is kept, and if a 60 fps version exists only that one is shown, saving you from agonizing over a dozen options;
4. **Click "Add to Parallel Download"** (加入并行下载) — the task enters the list, and several can run at once. With "Download subtitles simultaneously" (同时下载字幕, enabled by default) checked, both uploader-provided and auto-generated subtitles are downloaded and converted to `.srt`, supporting Chinese, English, Japanese, Korean, Spanish, French, German, and more.

**Each video is automatically packaged into its own folder**, named after the video title:

```
Some Video Title\
  ├─ Some Video Title.mp4    the video itself (audio always at highest quality)
  ├─ cover.jpg               cover art, normalized to 1280x720
  ├─ video_info.txt          title / description / video URL / channel URL / quality / download time
  └─ *.srt                   subtitles (if subtitle download was checked)
```

A few thoughtful details:

- No matter whether the original cover is portrait or ultra-wide, it is scaled proportionally and padded with black bars to exactly 1280x720 — **never stretched or distorted**; when multiple candidates exist, the highest-resolution one is picked automatically;
- `video_info.txt` is saved in UTF-8 with BOM, so **it opens in Windows Notepad without garbled characters**;
- Illegal characters in titles (`\ / : * ? " < > |`) are replaced with spaces, and overly long titles are truncated to 80 characters;
- **Same-name videos never overwrite** — if a folder with the same name already exists, the new one is automatically renamed "Title (2)", "Title (3)", and so on;
- When a download finishes, the folder opens automatically for you to inspect.

You can keep pasting the next link while downloads are running — tasks don't interfere with each other, and each has its own progress. Rate-limiting from sites like Bilibili (HTTP 412) is handled with automatic wait-and-retry. All background calls hide the black console window, so nothing flashes on your screen.

> **Failed subtitles don't affect the video**: subtitles are fetched separately after the video completes. If the subtitle API gets rate-limited or the video simply has no subtitles, you just get a brief notice — the video, cover, and info file are still delivered as normal.

### 4.2 A/V Merge

Some sites deliver video and audio as separate files (e.g. an `.mp4` video plus an `.m4a` audio), which must be merged before they play properly.

This tab is split into two sub-tabs: **Auto Pairing** (自动配对) and **Manual Merge** (手动合并).

**Auto Pairing** — for batch-processing downloaded files:

1. Select the input folder;
2. Click **"Scan & Pair"** (扫描配对) — the app pairs video and audio files automatically by file name and duration;
3. Click **"Start Merging"** (开始合成); results are output to the "Merge Results" (合成结果) folder.

**Manual Merge** — for loose files of your own, no matching names required:

1. Drag your **video** and **audio** files in from Explorer (drop them on any slot or anywhere on the page — they are routed by file type automatically), or click a slot to browse; subtitles are optional and support `.srt` / `.ass`;
2. Optionally change the **output folder**; leave it empty to write next to the video;
3. Click **"Start Merging"** (开始合并); the result is named `original-name_merged.mp4`, and existing files are never overwritten (a numeric suffix is added instead).

Manual merge is more forgiving than auto pairing: the audio codec is probed first — AAC is muxed as-is, anything else (mp3/wav/flac/…) is transcoded to AAC; the video is muxed directly first, and if it cannot live in an mp4 (vp9/av1 and friends) the app automatically retries with H.264 re-encoding.

How files are handled: `.m4a` audio is muxed directly without re-encoding (zero quality loss); `.weba` is automatically converted to AAC; `.srt` subtitles are attached as soft subtitles (toggleable in players); `.ass` styled subtitles can be burned into the picture, muxed into an MKV, or ignored — your choice.

---

## 5. Video Library: Browse Local Videos

1. By default the library shows the save location remembered by the download page. You can also click "Browse…" (浏览…) to pick another folder, or click "Sync with Download Directory" (同步下载目录) to follow the download page;
2. Click **"Refresh"** (刷新) to start scanning — **the app does not scan automatically at startup**, so it won't freeze on a folder with tens of thousands of files by accident;
3. Subfolders are scanned recursively, so videos inside each video's own folder are all visible. Cards display "Folder name \ File name" so you can tell them apart;
4. Each card automatically shows the video duration and file size;
5. **Single-click a card to play it; right-click to open its containing folder.**

Thumbnails are generated automatically and cached in `data\thumb_cache`; the second refresh is much faster. Cache names include a fingerprint of the full path, so **same-named videos in different folders never get their thumbnails crossed**.

---

## 6. Subtitle Processing: Transcription, Translation, Calibration, Burning

This page embeds an open-source subtitle engine (VideoCaptioner), used directly inside the page without popping up a separate window. Tabs at the top: **Task Creation** (任务创建) / **Speech Transcription** (语音转录) / **Subtitle Translation** (字幕翻译) / **Subtitle Calibration** (字幕校准) / **Subtitle-Video Composition** (字幕视频合成).

Opening this page causes no stutter — the engine is pre-warmed in the background after the app starts; in practice the UI builds in about 0.7 seconds.

### 6.1 Basic Usage

Drag a video in, or paste a link, then run whichever steps you need:

- **Speech Transcription**: turn the speech in a video into subtitle text;
- **Subtitle Translation**: translate into Chinese (or another language), outputting bilingual subtitles;
- **Subtitle Calibration**: fix proper nouns that machine translation got wrong (covered in detail below — this is the software's signature feature);
- **Subtitle-Video Composition**: burn subtitles into the picture, or mux them as toggleable soft subtitles.

Subtitle optimization and voice-over depend on large language models, so **enter your AI configuration in Settings first**. Without it, only these two items are unavailable; transcription and translation work as usual.

Configuration, logs, model caches, and task outputs all live under `data\VideoCaptioner\` inside the app folder — **nothing is written to the C drive**.

### 6.2 A Note on Translation Services

Subtitle translation can use LLM translation (best quality) or the free services Bing, Google, and DeepLx.

One thing you should know: **the public endpoints of these free translation services have been failing one after another in recent years** — Microsoft's token endpoint officially returns 404, and Google Translate is usually unreachable from mainland China. The software has updated its endpoints, parameters, and language mappings to the official new implementations, but if the endpoint itself is dead, there is nothing the software can do.

So:

- If a chosen free service fails for an entire batch, the software automatically falls back to Microsoft Translate once and tells you;
- **Since v1.15.1, if translations are missing, the software reports an explicit error and produces no file** — it will no longer silently hand you a fake "translation" named something like `-Google Translate.srt` whose content is still the original text;
- For reliable translation quality, use LLM translation.

The engine's translation fallback behavior is logged in `logs\vc_fallback.log`; show this file to the maintainer when something goes wrong.

### 6.3 Subtitle Calibration (Signature Feature)

What machine translation gets wrong most often is **proper nouns** — character names, place names, skill names, item names. In one anime the protagonist's name might come out three different ways, which is very jarring. Subtitle Calibration exists specifically to solve this.

**Basic usage**:

1. Switch to the **Subtitle Calibration** (字幕校准) tab and select an `.srt` file;
2. Choose the **source mode** (片源模式, 12 options in total): Chinese-English bilingual (default) / Japanese audio · Wuthering Waves / Japanese audio · Arknights: Endfield / Korean audio · Wuthering Waves / Arknights / Arknights · Korean / Endfield / Chinese-line-only / Punishing: Gray Raven / Punishing English audio / Mobile-game OST (general) / Music commentary;
3. Click **"Start Calibration"** (开始校准).

**What it guarantees not to touch**: sequence numbers, timestamps, blank lines, line breaks, and the BOM — **not a single byte is changed**. Only terminology inside Chinese lines is replaced. In other words, the calibrated subtitle behaves exactly like the original in any player; only the text is different.

**Output**: by default it creates `<original name>.calib.srt` in the same folder; on name collision a sequence number is appended. **Your original subtitle is never overwritten.**

**Optional settings**:

- Fix English/reference lines (effective only in bilingual mode);
- Generate a change-comparison report (same name, `.md`), documenting every change and its basis;
- Count hits only (仅统计命中) — preview which words would change without writing any file.

**AI Calibration (recommended)**: with the "AI Calibration" (AI 校准) switch on, calibration is no longer just a mechanical glossary pass — the AI reviews, block by block, suspected wrong forms that the glossary doesn't cover. The flow is:

① Run the glossary script first (official-term hits are guaranteed correct — a safety net) → ② Extract the subtitle table, strip timestamps → ③ Load the knowledge base → ④ Split into blocks automatically → ⑤ AI re-reviews block by block → ⑥ **Evidence verification** (every change must be explainable by the knowledge base or verifiable online research; anything unexplained is rejected) → ⑦ Merge and write back with boundary checks → ⑧ Independent verification (re-asserts that the structure is completely unchanged) → ⑨ **Source profile** (new in v1.15.1: outputs Chinese title, tags, official-verification results, and script-consolidation suggestions).

Step ⑥ is the key: **the AI is not allowed to rewrite sentences freely** — it may only make evidence-based, noun-level replacements; changes to line counts, whole-sentence rewrites, and unsupported edits are all rejected and recorded in the report. This prevents the AI from mangling your subtitles beyond recognition.

**Since v1.15.6, the AI can also verify facts online**: for suspected wrong forms not yet in the knowledge base, the AI can run web searches and fetch official reference pages, treating what it finds as **read-only evidence** before drawing conclusions. Verification results still go through the step-⑥ evidence check — the AI cannot freestyle based on search results. If the network fails, it degrades gracefully without interrupting calibration.

**"Calibrate Again"** (再次校准): runs another pass using the previous output as input, targeting residual wrong forms. Outputs `<original name>.calib.r2.srt`, `<original name>.calib.r3.srt`, … You can chain passes until satisfied.

**Reading the report**: with "Generate change-comparison report" checked, a same-named `.md` file lists every change's sequence number, original text, calibrated text, and basis — plus **rejected AI proposals and the reasons for rejection** (so you can review manually). Entries marked ⚠ are suspected new wrong forms not yet in the knowledge base; they can be consolidated into it later.

> When AI Calibration is on, "Count glossary hits only" turns off automatically (AI calibration needs to produce files). If AI isn't configured or the endpoint is unavailable, turn this switch off — pure script calibration works just as well.

### 6.4 Calibration Knowledge Sync

Different users accumulate different calibration results (glossaries, entities, context rules) over time. The software shares these among users, eventually converging toward the union of everyone's content.

**All you need to know**: updates run automatically in the background at startup, and you can also click "Update Now" (立即更新) on the Settings page. Uploading is completely seamless — there is no upload button in the UI; it happens automatically in the background when you exit the app, without pop-ups or blocking shutdown.

Merging is **deterministic**: anything missing locally is adopted from the remote; additions on both sides are merged in; when both sides changed the same entry to different content, the local version is kept and a conflict is logged. **Users never overwrite each other.**

If you don't want syncing, turn off "Enable auto-sync" (启用自动同步) on the Settings page. Logs are in `logs\calib_sync.log`.

---

## 7. Subtitle Editor: Sync Subtitles Against the Picture

Downloaded subtitles often have inaccurate timelines — a subtitle appears half a second early or a second late, which is uncomfortable to watch. This page lets you play the video inside the app while dragging timelines into place, without switching back and forth between a player and a text editor.

> **First-time use requires a one-time playback-component install**: video playback is provided by libmpv (~40 MB), which is not bundled with the installer for licensing and size reasons. Run the following in the app directory:
> ```
> python tools\download_open_source_deps.py --only mpv
> ```
> Or manually download `libmpv-2.zip` from the release page and extract it to `tools\mpv\`.
>
> **Nothing crashes if it's not installed** — this page just shows a notice; viewing and editing the subtitle table work as usual.

### 7.1 Layout

- **Toolbar**: Open Video / Open Subtitle / Save / Save As · Play (Pause) · ◀ Frame / Frame ▶ · speed dropdown · timecode on the right
- **Edit bar**: Split / Merge / Delete / Insert / Set start `[` / Set end `]` / Nudge −0.1 s / Nudge +0.1 s · Undo / Redo (hover any button to see its shortcut in the tooltip)
- **Upper area** (draggable splitter): video picture on the left, subtitle table on the right (No. / Start / End / Duration / Text)
- **Lower area**: the waveform timeline — gray waveform with subtitle blocks overlaid; **drag a block directly to change its timing**
- **Bottom status bar**: video name / subtitle name / entry & character counts / overlap & too-short counts / encoding & line-ending info / current zoom / "● Unsaved"

### 7.2 Basic Workflow

1. **"Open Video"** (打开视频) — the picture loads, and the audio waveform is parsed in the background (a progress bar shows on first load; afterwards it's cached and opens instantly);
2. **"Open Subtitle"** (打开字幕) — loads an `.srt`; the prompt states the entry count, source encoding (UTF-8 / GBK, etc.), and line-ending format (CRLF / LF);
3. **Sync while watching**: drag subtitle blocks on the waveform to change timing; double-click the waveform to split at that position; double-click a table cell to edit start time, end time, or text (times use `hh:mm:ss.mmm`, e.g. `00:01:23.456`; line breaks inside text display as ` / ` in the table);
4. **"Save"** (保存) writes back to the original file; **"Save As"** (另存为) writes a copy.

### 7.3 Shortcuts

Active when this page has focus (while typing in a table cell, the arrow keys keep their normal text-editing behavior):

| Key | Action |
| --- | --- |
| `Space` | Play / Pause |
| `,` `.` | Step back / forward one frame (`←` `→` work the same) |
| `Shift+←` / `→` | Move the selected subtitle back / forward 100 ms |
| `Alt+←` / `→` | Move back / forward 1 second |
| `↑` / `↓` | Previous / next entry, and jump the playhead there |
| `[` / `]` | Set the selected entry's start / end to the current playhead position |
| `Ctrl+K` | Split at the playhead |
| `Del` | Delete the selected entries (multiple table selections are deleted together) |
| `Ctrl+Z` | Undo　　`Ctrl+Y` / `Ctrl+Shift+Z` Redo |
| `Ctrl+S` | Save　　`Ctrl+Shift+S` Save As |
| `Ctrl+O` | Open Video　　`Ctrl+Shift+O` Open Subtitle |
| `Ctrl+=` / `-` / `0` | Zoom timeline in / out / fit entire track |
| `Ctrl+Shift+F` | Zoom to the selected entry's range |

### 7.4 Anti-Fumble Design

- **100 undo steps**, and a timing drag counts as one step — a snapshot is saved before dragging, so undo returns precisely to "before the drag," not "somewhere mid-drag";
- **Automatic backup on save**: if the target file already exists and has no same-named `.bak`, a backup is made first, so mistakes can be rolled back;
- Before opening a new video or subtitle with unsaved changes, the app asks "Discard changes?" first;
- Splits or boundary grabs that would make a subtitle shorter than one frame (40 ms) are rejected with a warning — **no bad data is ever written**;
- Sequence numbers, timestamp format, line endings, and BOM are all preserved exactly;
- Switching to another page pauses playback automatically; exiting the app releases the playback component and leaves no temporary files.

### 7.5 Embedded Subtitles and the Subtitle Layer

- **Embedded subtitles** (内嵌字幕): attaches the current subtitles (**including unsaved changes**) as a separate mov_text track in the mp4. It uses stream copy — **no re-encoding** — so it finishes in seconds with zero quality loss, and the soft subtitle can be toggled in players.
- **Subtitle layer** (字幕层): overlays a transparent subtitle-preview layer on the video, rendering the current subtitles in real time as it plays — **what you see is what you get**: the style you tune here is exactly what the final burn-in will look like.

> If you want subtitles **hard-burned** into the picture (the kind players can't turn off), use the "Subtitle-Video Composition" tab on the Subtitle Processing page. The hard-burn path on this page has been deprecated — in practice it caused the processing process to freeze.

---

## 8. Pipeline: Fully Automated, One Link In

The previous pages are all manual, step by step. If you have a batch of videos that all need the same workflow, use this page.

**Paste a link, and the rest is automatic**: download (original video + subtitles + cover + info) → translate → subtitle calibration → AI second-pass calibration → packaged output.

You can also **watch a folder**: new videos appearing in the download directory are automatically taken over, run through the same chain once the download completes, with A/V merge handled automatically in between.

### 8.1 What's on the Page

- **New Task** (新建任务): paste a link, press Enter or click "Add Task" (添加任务);
- **Auto Pipeline** (自动流水线): the on/off switch, **concurrency** (1–8, default 3), plus whether to enable AI second-pass calibration;
- **Task Progress** (任务进度): every stage of every task at a glance — Waiting / Ready / Running / Done / Failed / Skipped. The card header has a "**Clear Task Progress**" (清空任务进度) button for wiping historical tasks in one go.

### 8.2 Worth-Knowing Behaviors

- **Resume after interruption**: task state is persisted in real time. After a restart, completed stages are auto-skipped and in-progress stages are re-run from a clean position — nothing starts over from scratch;
- **One task's failure doesn't drag down the others**: failures are isolated to the current task; queued tasks keep moving;
- **No re-runs when input hasn't changed**: outputs carry an input fingerprint, so identical input never repeats work;
- **Multiple tasks run in parallel**: concurrency defaults to 3, so one video can be downloading while another is being calibrated — no waiting in line. Within a single task the stages still run strictly in order;
- **Historical tasks can be cleared**: click "Clear Task Progress" (清空任务进度) in the Task Progress card header to wipe completed / failed / pre-existing tasks at once (a task that is running is removed once its current stage finishes). Only the records are cleared — no downloaded or generated file is ever deleted. Cleared historical videos won't be re-enqueued automatically; re-downloading or replacing the file brings them back;
- **Existing files are never processed automatically**: only newly appearing files are taken over; files you already had there won't be touched.

If you don't want this feature, just turn off the "Auto Pipeline" switch.

---

## 9. Settings Page, Item by Item

**Settings** (设置), at the bottom of the left navigation, is the one and only settings entry point in the whole app, laid out vertically on one page:

### 9.1 Directories

- **Download Directory** (下载目录): default save location for video downloads (linked with the download page)
- **Data Root Directory** (数据根目录): the root for all runtime files; defaults to the app folder and can be relocated wholesale
- **Engine Working Directory** (引擎工作目录): where the subtitle engine puts task outputs; read-only, fixed inside the app folder (never on the C drive)

> All default locations stay inside the app folder — **nothing is written to the system drive**. To relocate, see Section 10.

### 9.2 Global AI

A single OpenAI-compatible configuration (API key / endpoint URL / text model / vision model), **shared by the entire app** — the toolbox itself, the subtitle engine, and AI calibration all use this one. Click "Test Connection" (测试接口) to verify; "Save & Apply" (保存并应用) takes effect immediately and syncs into the subtitle engine.

### 9.3 ASR Speech Recognition (Transcription Config)

The source of the transcription model: your own ASR service (OpenAI-compatible API) or a local standalone model (model name + model directory). After saving, it is written into the engine's "Transcription Config" automatically — no need to edit it manually in the engine's settings. Leave the protocol on "Auto-detect."

### 9.4 AI Calibration

Controls how much content AI calibration processes per pass and how far it may go:

| Option | Description |
| --- | --- |
| **Thinking Mode** (思考模式) | Toggle. Off is cheaper and faster; turn it on for whole-sentence rewrites of long sources |
| **Thinking Effort** (思考强度) | New in v1.15.6; shown only when Thinking Mode is on. Corresponds to the model vendor's "advanced configuration" tiers |
| **Max entries per block / char budget per block** | Smaller blocks are steadier (a block that can't be read is halved and retried automatically), but more blocks means slower runs |
| **Input / output budgets** | Per-request token limits, with quick presets. Since v1.15.6 the output cap goes up to 512K |
| **Calibration Style** (校准风格) | "Term-level (replace nouns only — safe)" or "Whole-sentence rewrite." **When in doubt, choose term-level** |

Which AI is used is decided by "Global AI" above; there is no separate channel selection here.

### 9.5 Subtitle Engine

Runtime parameters for transcription, translation, composition, etc. LLM settings and save locations have been moved up to the global settings and are not repeated here.

### 9.6 Calibration Knowledge Sync

The auto-sync switch and the "Update Now" (立即更新) button. Uploading happens in the background at app exit — **there is deliberately no upload button** (one less thing for you to worry about).

### 9.7 Appearance

- **Theme** (主题): Dark / Light / Follow System, plus 8 preset accent colors (default green `#45C877`)
- **UI Scale** (界面缩放): takes effect immediately; consistent from 100% to 200%
- **Mica effect** (云母特效): Windows acrylic/mica material effect
- **Background** (背景): can be blurred; you can also set a separate background image for each navigation section (drag-and-drop images is supported; manually typed paths go through four-state validation)

> Theme changes take **full effect after restarting the app**.

### 9.8 About

Version number, plus the entry points for full third-party component license texts and attribution statements.

---

## 10. Where Everything Is Stored

The software is **green/portable**: everything produced at runtime — configuration, downloads, thumbnail cache, logs, temp files, and the subtitle engine's configuration and caches — lives under the "Data Root Directory," **which defaults to the app folder itself**. Copy the whole folder and you've carried all your data with you; nothing is left on the system drive.

### 10.1 Moving Data Somewhere Else

For example, if the app sits in a read-only folder on C: and you want data on D::

1. **Settings → Directories → Data Root Directory** (设置 → 目录 → 数据根目录): enter or select the target folder, click "Apply" (应用);
2. The app migrates the existing `data\` and `logs\` contents there (on same-named files, the new location's copy wins);
3. A `data_dir.txt` is created in the app folder recording the new location;
4. **Takes full effect after a restart.**

To switch back, click "Restore Default" (还原默认).

### 10.2 Directory Overview

```
视频工具箱\                      Video Toolbox\
├─ 视频工具箱.exe                 main program (double-click this)
├─ data\                         your data (config, downloads, caches)
│   ├─ config.json               global settings (download dir, data root, sync switch)
│   ├─ ai_config.json            AI & ASR configuration (contains your keys — don't share)
│   ├─ downloads\                default download directory
│   ├─ thumb_cache\              Video Library thumbnail cache (deletable; rebuilds automatically)
│   ├─ waveforms\                waveform cache for the Subtitle Editor (deletable; rebuilds automatically)
│   └─ VideoCaptioner\           subtitle engine data (config / cache / models / task outputs)
├─ logs\                         logs (show these to the maintainer when something goes wrong)
│   ├─ gui_errors.log            UI exception records
│   ├─ calib_sync.log            calibration knowledge sync log
│   ├─ startup.log               startup timing diagnostics
│   └─ vc_fallback.log           subtitle engine translation fallback log
├─ docs\                         documentation and third-party license statements
├─ tools\                        runtime dependencies (bundled; no download needed)
└─ src\                          source code (used by the script-based launch)
```

**Safe to delete**: `data\thumb_cache\` (thumbnail cache), `data\waveforms\` (waveform cache), `data\tmp\` (temp files), and the logs under `logs\`. All of these rebuild on demand — the first use after deletion is just a bit slower.

**Do not delete**: `data\ai_config.json` (your AI key configuration), `data\config.json` (global settings), anything under `tools\`, and `docs\VideoCaptioner_GPL-3.0.txt` (full open-source license text; legally required to be kept).

### 10.3 Uninstalling

Uninstalling **does not delete the `data\` directory** — your configuration, download records, and subtitle work are all kept. If you're sure you don't need them anymore, delete the folder manually.

---

## 11. FAQ

**Q: The app doesn't respond when I open it / gets blocked by the system?**
A: The exe is not code-signed; PCs with Device Guard or application-control policies may block it. Use the script-based launch instead: double-click `src\视频工具箱.bat`.

**Q: Subtitle translation keeps failing?**
A: The public endpoints of free translation services have been failing one after another in recent years (Microsoft's token endpoint returns 404; Google is unreachable from mainland China) — this is an endpoint-side problem. The software automatically retries once via Microsoft Translate; if that still fails, configure AI in Settings and use LLM translation. Since v1.15.1, incomplete translations produce **an explicit error and no file** — no more silent "fake translations" whose content is still the original text.

**Q: AI Calibration does nothing or reports an error when clicked?**
A: First check **Settings → Global AI** (设置 → 全局 AI): is it filled in, and does "Test Connection" pass? If AI isn't configured, turn off the "AI Calibration" switch — pure script calibration works just as well. The calibration page has a "Refresh" (刷新) button; if the UI seems stuck, clicking it resets the view (during normal operation it won't interrupt running tasks).

**Q: The Subtitle Editor plays audio but shows no picture?**
A: The libmpv playback component isn't installed. Run `python tools\download_open_source_deps.py --only mpv` once more and restart the app.

**Q: A domestic AI service (e.g. Bailian) won't connect, proxy errors?**
A: Fixed in v1.15.7 — domestic endpoints are forced to connect directly and are no longer routed by the system proxy to overseas nodes. If you're on an older version, upgrade; the temporary workaround is to disable your proxy tool.

**Q: The online installer downloads extremely slowly?**
A: The slow part is the international link to GitHub Pages. The easiest fix is the offline installer (~548 MB, one download). With an intranet source or a proxy tool you can also speed it up — see `使用说明.txt` for details.

**Q: The downloaded subtitles have inaccurate timing?**
A: Platforms like YouTube have a "rolling" subtitle format where one entry's end time is extended into the next, showing up as subtitles hanging on screen for a long time (measured overlap rate as high as 84.9%). Newly downloaded subtitles are auto-corrected; for existing old files, sync them manually on the Subtitle Editor page.

**Q: Can data live on a different drive?**
A: Yes — see Section 10, "Moving Data Somewhere Else."

**Q: Does the app write anything to the C drive?**
A: No. All runtime files live under the Data Root Directory (the app folder by default). Historically the subtitle engine once wrote to `C:\Users\…\VideoCaptioner`; on startup this is now migrated back into the app folder automatically.

---

## Appendix: Documents Distributed with the Software

| Document | Contents |
| --- | --- |
| `docs\使用说明.txt` | Plain-text usage notes, similar in content to this manual; bundled with the installer |
| `docs\程序说明书(用户版).md` | This manual (Chinese original) |
| `docs\程序说明书(开发版).md` | For developers and maintainers: file-by-file source structure, build & release procedures, known pitfalls |
| `docs\校准知识增量同步_管理员手册.md` | Administrator manual for the knowledge base in LAN shared-drive environments |
| `docs\VideoCaptioner_GPL-3.0.txt` | Full GPL-3.0 license text of the embedded subtitle engine |
| `docs\VideoCaptioner_组件来源.txt` | Third-party component provenance and license list |
| `文件版本清单.md` | Version stamps and SHA-1 checksums for all files (auto-generated, for version verification) |

---

**About open-source components**: this software embeds the open-source subtitle engine VideoCaptioner v1.4.2 (GPL-3.0 license) and uses open-source components including yt-dlp, FFmpeg, Deno, and CPython. Full license statements are in `docs\VideoCaptioner_组件来源.txt`. The libmpv playback component used by the Subtitle Editor is an **LGPL build**, downloaded on demand and not bundled with the installer.

*This manual was verified against the actual UI and code of v1.16.5. If the interface differs from what is described here, trust what the software actually shows, and feedback is welcome.*
