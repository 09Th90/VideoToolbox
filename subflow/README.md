<!-- @version 2.4.1 -->
# subflow —— 字幕生产全链路编排

《字幕生产全链路整合方案书》阶段 2/3 交付物：把 **finesub**（转写精修主引擎）、
**MAW / MAWE**（人工校对编辑器）与 **ffmpeg 烧录**串成单命令工作流，
知识库与 Gemini 配置全链路单源。

```
URL/本地文件 ──> [①获取] yt-dlp 下载留档（URL 任务）
                    │
                    v
              [②转写精修] finesub --stage final-srt（人声分离→ASR→稳定化→Gemini 纠错翻译→知识库）
                    │   产物：finesub/<任务名>.srt + <任务名>-raw.srt
                    v
              [③人工校对] MAWE 波形编辑器（人工交接点，唯一手动环节）
                    │   SRT 自动转 .mosp 工程直开；保存后自动渲染回 reviewed SRT
                    v
              [④校准补充] （可选）视频工具箱图形界面，术语表见 glossary/
                    v
              [⑤交付] ffmpeg 烧录 → final/<任务名>.mp4 + .srt
```

## 一、环境准备（阶段 0，源码自行构建）

约束：不使用任何发行版二进制（downloads 内的 zip/exe 安装包一律不用），全部从源码构建。

### 1. finesub（源码安装）

```powershell
cd downloads\finesub
uv venv --python 3.12
.venv\Scripts\activate
uv pip install --torch-backend cu128 -e ".[asr,harness]"
uv pip install yt-dlp
# ASR 必需的补丁版 CTranslate2（覆盖安装；直连失败走 gh-proxy 镜像）
uv pip install --reinstall --no-deps "https://github.com/caca2331/finesub/releases/download/ct2-4.8.1%2Bfinesub0.4.0/ctranslate2-4.8.1+finesub0.4.0.cu128-cp312-cp312-win_amd64.whl"
```

自检（期望 torch `2.11.0+cu128 True`、ct2 `4.8.1+finesub0.4.0.cu128`）：

```powershell
.venv\Scripts\python -c "import torch; print(torch.__version__, torch.cuda.is_available())"
.venv\Scripts\python -c "import ctranslate2; print(ctranslate2.__version__)"
.venv\Scripts\python -m finesub.pipeline --help
```

**中文路径必做**：torch 在 Windows 用 ANSI `fopen` 加载 jit 模型，仓库路径含中文
（…\软件开发\视频工具箱\…）会让 silero_vad.jit 加载报 errno 2。给 venv 建 C 盘
junction（ASCII 入口，subflow 默认使用它，可用 `FINESUB_PYTHON` 覆盖）：

```powershell
New-Item -ItemType Junction -Path 'C:\finesub-venv' -Target '<仓库根>\downloads\finesub\.venv'
```

### 2. MAW（源码编译）

```powershell
cd downloads\moys-asr-workflow
uv sync --group build --frozen
uv run python -m maw.runtimes.freezer freeze --force
uv run --group build pyinstaller --noconfirm --clean MAW.spec
# 产物：dist\MAW\MAW.exe
```

注意：uv 的缓存锁不支持并发，两个构建任务不要同时跑；网络抖动导致下载超时时，
直接重跑同一条命令（已下载的大包走缓存）。

### 3. Gemini 密钥

在 [Google AI Studio](https://aistudio.google.com/apikey) 创建密钥（免费档即可，
建议 2 把分摊限流），写入 finesub 源码目录的 `.env`（key 自动 DPAPI 加密）：

```powershell
cd downloads\finesub
.venv\Scripts\python -m finesub.keys     # 按提示写入
```

视频工具箱侧如需 AI 校准：设置 → 全局 AI，接口地址填
`https://generativelanguage.googleapis.com/v1beta/openai/`。

### 4. 一键自检

```powershell
tools\python\python.exe scripts\dev\_selftest_subflow.py
```

覆盖：SRT 解析与 .mosp 往返、知识库导出解析、任务状态机、ffmpeg 烧录实测（35 断言）。

## 二、快速上手

```powershell
cd subflow

# 1. 登记任务（URL 或本地文件）
python subflow.py add "https://www.bilibili.com/video/BVxxxx" --lang ja --extra-info "主播名、节目名、关键专名" --name ep01

# 2. 全自动：下载留档 → finesub 精修 → 校对就绪（GPU 长任务，可中断后 resume）
python subflow.py run ep01

# 3. 启动 MAWE 人工校对（浏览器打开工程，改完 Ctrl+S 保存即自动检出 SRT）
python subflow.py review ep01

# 4. 烧录交付
python subflow.py burn ep01

# 任意时刻看进度
python subflow.py status
```

中断恢复：`run`/`burn` 失败原因写入 task.json 的 error 字段，排障后
`python subflow.py resume ep01` 从断点继续，已完成阶段按产物存在性跳过，不重复执行。

## 三、命令速查

| 命令 | 功能 | 备注 |
|---|---|---|
| `add <URL\|文件>` | 登记任务，写入 task.json | `--lang`、`--extra-info` 透传 finesub；`--knowledge update\|collect\|none` |
| `run [任务名]` | 处理待办：下载 → 转写精修 → 校对就绪 | 缺省处理全部待办；URL 先经 yt-dlp 留档到 media/ |
| `status` | 各任务阶段、耗时、错误标记 | |
| `review <任务名>` | 启动 MAW --server 打开工程并等待校对 | `--no-wait` 只启动；`--port` 换端口（默认 8250） |
| `burn <任务名>` | ffmpeg 烧录成片到 final/ | `--style default\|small\|large`；`--force` 重烧 |
| `resume <任务名>` | 从中断/失败阶段继续 | 幂等，已完成的阶段不重复执行 |
| `open <任务名>` | 资源管理器打开任务目录 | |
| `kb-sync` | 知识库主库 → VT 术语表 + MAW 预设 | 单向导出，见第四节 |

review 等待逻辑：检测到 `review/<任务名>-reviewed.srt`（编辑器「导出 SRT」另存）
或工程 `.mosp` 被保存（mtime 变化，自动渲染）即推进到 burn 阶段；Ctrl+C 停止等待不影响工程。

## 四、知识库统一（阶段 3）

**finesub 知识库为唯一主库**（`workflow/knowledge/`，finesub 经
`FINESUB_KNOWLEDGE_ROOT` 环境变量直接读写，`--knowledge update` 自动积累专名）。
同步严格单向：主库 → 导出物，杜绝双写冲突。

```powershell
python subflow.py kb-sync
```

| 导出物 | 用途 | 接入方式 |
|---|---|---|
| `glossary/video-toolbox.tsv` | 视频工具箱 AI 校准术语表 | 字幕处理页导入（列：原文、译名、类别） |
| `glossary/maw-hotwords.txt` | MAW 转写热词 | `MAW.exe --hotword-file`（本链路 MAW 只当编辑器，备选） |
| `glossary/maw-context.txt` | MAW 供应商上下文 | `MAW.exe --context-file`（备选） |

工作惯例：新系列开工先 `--knowledge update` 跑前两集积累专名，`kb-sync` 后再批量处理后续集数。
主库人读层在 `knowledge/rendered/`（按类别分目录，markdown 行式见 finesub
`examples/knowledge` 样板），直接编辑即生效。style/ 翻译口味不参与导出；
视频工具箱自身的 learned_kb 校准知识库走其增量同步机制，不纳入主库回流。

## 五、目录契约（工作站根，默认 `subflow/workflow/`）

```
workflow/
├─ work/<任务名>/                 # 每任务一目录
│   ├─ task.json                 # 状态机（stage/artifacts/history/error）
│   ├─ media/input.mp4           # 下载留档媒体（本地文件任务直接引用原路径）
│   ├─ finesub/<任务名>.srt       # ② 成品 SRT
│   ├─ finesub/<任务名>-raw.srt   # ② 稳定化原始轴（留档对照）
│   ├─ review/<任务名>.mosp       # ③ MAW 工程（SRT 自动转换生成）
│   ├─ review/<任务名>-reviewed.srt  # ③ 校对导出
│   └─ final/<任务名>.mp4 / .srt  # ⑤ 交付
├─ knowledge/                    # finesub 知识库主库（唯一真源）
├─ glossary/                     # kb-sync 导出物
└─ logs/                         # 按工具/任务落盘的子进程日志
```

根目录可用 `--root` 参数或 `SUBFLOW_ROOT` 环境变量改到其他盘（大任务建议放 SSD）。

## 六、编码契约（方案书 4.3）

SRT 一律 **UTF-8 无 BOM + CRLF**（读取端兼容 BOM/GBK/LF）；`.mosp` 工程 UTF-8 + LF
（对齐 MAW 规范）；时间码标准 `时:分:秒,毫秒`；任务名仅半角字母数字、连字符、下划线。

## 七、路径与覆盖

工具定位默认锚定仓库内源码构建产物，均可用环境变量覆盖：

| 环境变量 | 默认 |
|---|---|
| `SUBFLOW_ROOT` | `subflow/workflow` |
| `FINESUB_PYTHON` | `C:\finesub-venv\Scripts\python.exe`（junction，见上） |
| `MAW_EXE` | `downloads/moys-asr-workflow/dist/MAW/MAW.exe` |
| `FFMPEG_BIN` / `YTDLP_BIN` | `tools/ffmpeg.exe` / `tools/yt-dlp.exe` |
| `MAW_PORT` | `8250` |

## 八、许可与合规（方案书 4.5 执行纪律）

三工具源码与构建产物只在本地工作站内使用，**不随本仓库再分发**（downloads/ 不入库）；
对外分享仅限 subflow 编排脚本与文档。finesub（GPL-3.0-or-later）、MAW（AGPL-3.0-only）
以子进程 + 文件接口交互，编排层不含其代码。
