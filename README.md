<!-- @version 2.3.1 -->
<h1 align="center">视频工具箱 · VideoToolbox</h1>

<p align="center">
  把「找视频 → 下下来 → 弄出字幕 → 修好字幕 → 装回视频」<br>
  这一整条流程装进一个 Windows 窗口。
</p>

<p align="center">
  <a href="https://github.com/09Th90/VideoToolbox/releases/latest"><img src="https://img.shields.io/github/v/release/09Th90/VideoToolbox?label=release&color=blue" alt="Release"></a>
  <a href="https://github.com/09Th90/VideoToolbox/actions/workflows/ci.yml"><img src="https://github.com/09Th90/VideoToolbox/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <img src="https://img.shields.io/badge/platform-Windows-0078D4" alt="Platform">
  <img src="https://img.shields.io/badge/license-CC%20BY--SA%204.0-lightgrey" alt="License">
</p>

<p align="center">
  <a href="https://github.com/09Th90/VideoToolbox/releases/latest">下载</a> ·
  <a href="#-快速开始">快速开始</a> ·
  <a href="#-功能">功能</a> ·
  <a href="#-第三方组件与许可">许可</a>
</p>

---

## 📌 这是什么

一个 **Windows 桌面软件**，把「找视频 → 下下来 → 弄出字幕 → 修好字幕 → 装回视频」
这一整条流程装进一个窗口，不用在好几个软件之间来回倒腾。

**你不需要懂技术**：不用装 Python，不用配环境变量，双击图标就能用。
需要 AI 的功能（字幕润色、AI 校准）要先填一次自己的 AI 密钥，其余功能开箱即用。

---

## ✨ 功能

九个功能页，从左边的导航栏切换：

| 页面 | 干什么用 |
| --- | --- |
| **首页** | 工作台：一键创建下载/转录/翻译任务，直达最近进度 |
| **视频处理** | 从 YouTube、B 站等网站下载视频（含字幕、封面、信息），也能把分开下载的画面和声音合成一个文件 |
| **视频库** | 把某个文件夹里的视频扫出来，用缩略图卡片浏览、点开就播 |
| **字幕处理** | 给视频生成字幕、翻译字幕、校准专有名词、把字幕烧进画面或封装进视频 |
| **字幕编辑** | 在软件里一边放视频一边拖字幕的时间轴，把字幕和画面对齐 |
| **流水线** | 粘贴一个链接，下载→翻译→校准→打包全自动跑完；也可以盯住一个文件夹自动处理 |
| **自动化** | B 站自动投稿：保存投稿模板（标题/简介/标签/分区/话题），投稿表单可从视频目录的 `视频信息.txt` 一键读取；执行在后台线程跑，失败自动留整屏截图 |
| **AI 托管** | 内置 AI 托管（harness）：常驻技能包自动部署到各 Agent 约定位置，程序目录当工作区打开即接入 |
| **设置** | 填 AI 密钥、语音识别服务、下载目录、界面主题等（全软件唯一的设置入口） |

### 🎯 招牌功能：字幕术语校准

机器翻译最容易翻错的就是**专有名词**——人名、地名、技能名、道具名。
一部动画里主角名字被翻成三种写法，看着非常出戏。字幕校准就是专门解决这个的。

- 内置四套游戏名词底表，共 **3174 条**中英日韩对照：
  鸣潮 1650 · 终末地 1002 · 明日方舟 453 · 战双帕弥什 69
  （按去重计，同一条目可能同时出现在多张表里）；
  另有日语、韩语、塞尔达等专用词表；
- 可开 **AI 校准**，让 AI 逐块复核术语表没覆盖到的疑似错形；
- 校准知识库会持续积累，并可在多台设备间同步。

**它保证不动什么**：序号、时间轴、空行、换行符、BOM **一个字节都不改**，
只替换中文行里的术语。也就是说校准完的字幕和原字幕在播放器里的表现完全一致，
只有文字变了。

### 🎬 字幕编辑：看着画面对轴

左边放视频、右边是字幕轨道，拖动字幕条即可调整时间。
支持 `.srt` / `.ass` 双格式导出，还有些防手滑的设计（撤销、吸附、越界提示）。

---

## 🚀 快速开始

### 下载

| 安装包 | 体积 | 说明 |
| --- | --- | --- |
| **在线安装器** `VideoToolbox_OnlineSetup_v2.3.1.exe` | 约 12 MB | 当前唯一发布形态。安装时从 GitHub Releases 拉取约 127 MB 组件 |

> 附件名用英文，是因为 GitHub Releases 会把非 ASCII 文件名截断
> （历史版本 v1.12.0 的 Setup 包在下载页显示成了 `_Setup_v1.12.0.exe`）。
> 安装后程序名仍是中文。

> 最新发布：[v2.3.1](https://github.com/09Th90/VideoToolbox/releases/tag/v2.3.1)。
> 发布产物与源码版本严格对应，**README 不再预告尚未构建的产物**。

> **离线安装包当前不提供。** onefile 单体打包后体积超过 1 GB，已超出可维护的分发体积，
> 也不适合放在仓库或 Release 附件里。需要完全离线部署的场合，请按
> [源码方式](#源码方式) 运行，或自行用 `packaging/` 下的脚本构建。
> 后续版本会把运行时依赖拆出安装包，届时恢复离线包。

> 安装器从 GitHub Releases（海外）下载组件，国内直连常常只有几十 KB/s。
> **慢的是这条国际链路，不是软件本身有问题**。

### 安装

1. 双击安装包，安装向导全程简体中文（不会弹语言选择框）；
2. 默认装到 `D:\VideoToolbox`，可以改；**安装不需要管理员权限**，不会弹 UAC 窗口；
3. 装完从开始菜单或桌面快捷方式打开。

### 几个方便的打开方式

- **把链接拖到图标上**：直接打开「视频处理」页并把链接填进去；
- **把文件夹拖到图标上**：直接打开合并页并填好路径；
- **把文件拖进已打开的窗口**：视频和字幕会进「字幕编辑」页，链接文字会进下载页。

### 如果打不开

`视频工具箱.exe` 没有做代码签名（签名证书需要付费购买）。少数开启了
Device Guard 或应用控制策略的电脑会拦住它。这种情况可改用脚本方式启动：
双击安装目录里的 `src\视频工具箱.bat`（需要电脑装有 Python 3）。

### 源码方式

完全离线、或想直接用最新源码时，按下面几步走（需要 Python 3.12）：

```bash
git clone https://github.com/09Th90/VideoToolbox.git
cd VideoToolbox
pip install -r requirements.txt
python -m playwright install chromium   # 可选：Cookie 导出 / B 站投稿才需要
python src/video_toolbox_qt.py
```

**必须在仓库根目录运行**：程序按当前工作目录定位 `tools/`、`data/`，换目录启动会找不到运行时。

首次运行会按需下载 FFmpeg、yt-dlp、ASR 模型、libmpv 等外部依赖；
`python tools/download_open_source_deps.py --check` 可先体检缺什么。
`tools/videocaptioner/` 是随仓库内置的组件包，不需要另行 pip 安装。

---

## 🧩 技术栈与架构

| 层 | 选型 |
| --- | --- |
| 界面 | PySide6（Qt for Python）+ PySide6-Fluent-Widgets（导入名 `qfluentwidgets`，Fluent 风格） |
| 界面主题 | 自研 `vt_fluent` QSS 主题引擎（正逐步替换 qfluentwidgets 的控件外观） |
| 语音识别 | OpenAI 兼容 ASR API（service 模式）/ faster-whisper（local 模式） |
| 下载 | yt-dlp（主）+ NewPipe Extractor（兜底） |
| 媒体处理 | FFmpeg / ffprobe |
| 打包 | PyInstaller（onefile monolith）+ Inno Setup |

### 源码结构

```
src/                        主程序与功能模块
  video_toolbox.py          核心引擎（下载/转录/翻译/校准/流水线）
  video_toolbox_qt.py       界面层
  vt_engine_ui/             自研界面组件库
  engine_*.py               自研能力模块（ASR / 翻译 / 缓存 / 路径 / 数据模型）
tools/
  ai_client.py              AI 单通道客户端
  newpipe-cli/              NewPipe 兜底解析器（Java 侧封装 + 构建脚本）
packaging/                  打包脚本（spec / Inno Setup / 在线安装器）
docs/                       说明书与第三方许可声明
scripts/dev/                开发期自检脚本
```

---

## 📜 第三方组件与许可

本软件包含并使用若干第三方开源组件，它们**各自适用其原有的许可证**。
完整清单、许可证与源码获取途径见：

- [`docs/第三方组件来源与许可声明.txt`](docs/第三方组件来源与许可声明.txt)（随安装包分发）
- [`docs/开源许可_GPL-3.0.txt`](docs/开源许可_GPL-3.0.txt)（标准 GPL-3.0 原文，随安装包分发）

主要组件：

| 组件 | 用途 | 许可证 |
| --- | --- | --- |
| NewPipe Extractor | YouTube 兜底解析 | GPL-3.0 |
| PySide6 | 界面框架（Qt for Python） | LGPL-3.0 |
| PySide6-Fluent-Widgets | 界面组件库（导入名 `qfluentwidgets`） | GPL-3.0 |
| yt-dlp | 视频下载 | Unlicense |
| FFmpeg / ffprobe | 音视频处理 | GPL / LGPL |
| faster-whisper | 本地语音识别 | MIT |
| libmpv | 字幕编辑页播放 | LGPL |
| CPython 3.12 | 运行时 | PSF License |

> 安装包内 `docs\开源许可_GPL-3.0.txt` 是法律要求必须保留的文件，请勿删除。

### 本软件自身的许可

本软件自身以 [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/)（署名-相同方式共享 4.0 国际）许可发布，
许可全文（含官方英文原文）见 [`LICENSE`](LICENSE)。

由于 CC BY-SA 4.0 与 GPL-3.0 存在单向兼容（CC BY-SA 4.0 作品可并入 GPL-3.0 组合作品），
**随安装包分发的组合作品（本软件 + 上述 GPL-3.0 组件）整体按 GPL-3.0 提供**。
这一条是分发义务的闭环：安装包内含 GPL-3.0 组件时，接收方对组合作品整体享有 GPL-3.0 的权利。
单独获取本软件源码的，仍按 CC BY-SA 4.0 授权。

---

## ⚠️ 已知限制

写在这里，而不是藏在 issue 列表里——这些是当前版本明确做不到的事：

| 限制 | 现状 | 对你的影响 |
| --- | --- | --- |
| 无代码签名 | 签名证书需付费购买 | 少数开启 Device Guard / 应用控制策略的电脑会拦截 exe |
| 无离线安装包 | onefile 打包后超过 1 GB | 完全断网的环境只能用「源码方式」 |
| 无自动化测试 | 只有 `scripts/dev/` 下的人工自检脚本 | 升级前建议先备份 `data/` 目录 |
| 组件走国际链路 | 托管在 GitHub Releases | 国内直连速度取决于你的网络 |

已具备的工程约束：`scripts/dev/check_syntax.py`（全部受跟踪 `.py` 的语法解析）
与 `scripts/dev/check_doc_drift.py`（README / LICENSE 与代码事实的一致性）随仓库
提供，本地一条命令即可跑，把文档漂移挡在提交之前。

---

## 📄 文档

- [`docs/程序说明书(用户版).md`](docs/程序说明书(用户版).md) —— 面向使用者，只讲「怎么把事办成」
- [`docs/程序说明书(开发版).md`](docs/程序说明书(开发版).md) —— 面向开发者，讲源码结构、打包发布、自检脚本
- [`docs/引擎自研化替换规格.md`](docs/引擎自研化替换规格.md) —— 能力自研化路线与验收标准

---

## 📬 联系

- 作者主页：<https://space.bilibili.com/507185588>
- 问题反馈：<https://github.com/09Th90/VideoToolbox/issues>

---

<p align="center">
  <sub>本软件按「现状」提供，不附带任何明示或默示的担保。</sub>
</p>