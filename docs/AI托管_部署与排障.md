<!-- @version 2.8.0 -->
# AI 托管（deepseek-harness）部署与排障

> v2.1.0 起，工具箱首页任务框支持把**纯文本**交给 AI 托管执行：AI 以「程序根目录」
> 为工作区，可读写文件、执行命令，从而完整托管本程序（下载 / 转录 / 校准 / 打包等）。
> 承载 AI 的 harness 是**独立部署的第三方原件**，与本程序完全解耦——
> 是工具箱去适配 harness，不是 harness 适配工具箱。

## 1. 架构与边界

```
程序根目录/
├─ harness/                 ← AI 引擎（deepseek-harness 源码部署，**内部零改动**）
│    └─ apps/cli/lib/bin.js ← 构建产物（启动入口；未构建时回退 tsx 源码入口）
├─ data/harness-home/       ← harness 运行期状态（DSH_HOME：profile/凭据/配置补丁）
│    ├─ .credentials.yaml    （API 密钥，由工具箱按「设置」页配置同步写入）
│    ├─ cordis.patch.yml     （provider 路由 + 默认模型补丁，home 级）
│    └─ transcripts/         （每次任务的任务文本/答复/诊断存档）
├─ src/harness_bridge.py    ← 适配层（无 Qt）：探测/启动/配置同步/收显，工具箱→harness 单向适配
├─ src/harness_page.py      ← 「AI 托管」导航页（状态/任务/输出/交互控制台）
└─ logs/harness-web.log     ← 交互控制台日志（含带 token 的访问地址）
```

**硬边界**：

1. harness 文件夹内的任何文件都不允许修改（升级 = 整目录替换）。
   运行期产物一律落在 harness **之外**（`data\harness-home`、`logs\`）。
2. 工具箱与 harness 只通过 harness 官方 CLI 通信：
   - 一次性任务：`dsh --profile headless "<文本>"`（首页文本走这条）；
   - 交互控制台：`dsh web --no-open --port 3080`（浏览器打开，完整人工托管）。
3. **有无 harness 都不影响既有功能**：未部署 / 未装依赖 / 未构建 / 缺 node /
   配置关闭时，「AI 托管」导航项**仍会出现**，但页面在「状态」下方展示一张
   「部署引导」卡——内含按当前状态生成的处置步骤、可一键复制的命令、以及本文档
   入口；任务 / 控制台按钮在 harness 就绪前禁用。用户照卡操作补齐即可，不会只
   看到一个裸错误。首页任务框把纯文本交给 AI 托管的行为依旧只在 harness 就绪时
   触发，未就绪时与从前逐字一致。

## 2. 部署（一次性，约 5～15 分钟）

 prerequisites：Node.js ≥ 22.19。

```powershell
# 在程序根目录执行（zip 路径可用 VT_HARNESS_ZIP 覆盖）
powershell -ExecutionPolicy Bypass -File scripts\dev\deploy_harness.ps1
```

脚本依次做：解压官方 zip → `harness\`；`corepack pnpm install --frozen-lockfile
--ignore-scripts`；`corepack pnpm run build`。三个细节及其原因：

- **`LEFTHOOK=0`**：harness 的 lefthook postinstall 会向上找到**本仓库**的
  `.git` 并写入 git hooks 与根目录 `lefthook.yml`（2026-10-14 实测踩到），必须屏蔽。
- **`--ignore-scripts`**：Windows 上 esbuild 的 postinstall 校验会因并发 spawn
  node.exe 偶发 `EBUSY` 失败（二进制本身完好），跳过不影响构建。
- 升级 harness：换一份新 zip 重跑本脚本即可（`data\harness-home` 里的配置不动）。

## 3. API 配置：唯一事实来源 = 「设置」页

harness **不单独配 key**。每次任务/控制台启动前，`harness_bridge` 会把
`data\ai_config.json`（设置页 → AI）里的 `base_url` / `api_key` / `model`
（及视觉模型）同步成 harness 的 provider：

- `.credentials.yaml`：`VT_LLM_API_KEY` 等凭据引用；
- `cordis.patch.yml`（home 级，对 web/headless 全部 profile 生效）：
  `llm-pi-ai` 声明 `videotoolbox` 路由（`openai-completions` 协议 + 设置页的
  baseURL），`agent-default-model` 指向该路由与设置页的模型。

因此：**改模型/换密钥只用在「设置」页改**，下一次 AI 托管自动生效。
（harness 的 Web 控制台「设置 → 模型」页改的是同一份 DSH_HOME 配置的另一层，
以设置页为准；控制台里改不会回写到工具箱。）

## 4. 日常使用

| 场景 | 操作 |
|---|---|
| 让 AI 干活 | 首页任务框输入纯文本（如"把 `data/downloads` 里最新的视频转成字幕"）回车 → 自动跳「AI 托管」页执行 |
| 交互式托管 | 「AI 托管」页 → 打开交互控制台（冷启动 1～3 分钟，自动开浏览器；地址带 token 在日志里） |
| 看过程 | 「AI 托管」页输出区：`[推理]` 是 harness 的 reasoning 流，`AI 答复` 是最终结果；全文存档在 `data\harness-home\transcripts\` |
| 停控制台 | 「AI 托管」页 → 停止控制台（只停本程序起的那个） |

AI 能干的事取决于 harness 的工具（读改工作区文件、执行命令、联网抓取等），
工作目录 = 程序根目录。涉及删除、改写配置等高危操作前它会按权限策略询问。

## 5. 排障

| 现象 | 原因 / 处理 |
|---|---|
| 导航没有「AI 托管」项 | harness 未就绪。看 `python -c "import sys;sys.path.insert(0,'src');import harness_bridge as h;print(h.status_text())"`（在 src 目录外先 `sys.path`）。`missing`=没部署；`not_installed`=跑部署脚本；`no_launcher`=需要 `pnpm run build` |
| 任务秒退、提示缺凭据 | 「设置」页 AI 配置不完整（接口/密钥/模型），或提供商账号状态异常（如 Ark 订阅过期） |
| 答复里出现 401/订阅类报错 | 上游账号问题，与接入无关；换可用 key 或模型后重试 |
| 控制台打不开 | 看 `logs\harness-web.log`；冷启动慢属正常（1～3 分钟）。端口被占改 `data\harness_config.json` 的 `port` |
| 想彻底关掉接入 | `data\harness_config.json` 写 `{"enabled": false}`，或设环境变量 `VT_HARNESS_DISABLED=1` |
| harness 放到别处了 | 配置 `data\harness_config.json` 的 `dir`，或环境变量 `VT_HARNESS_DIR` |

配置文件 `data\harness_config.json`（均可选）：`dir`（harness 位置）、
`port`（控制台端口，默认 3080）、`dsh_home`（运行期根，默认 `data\harness-home`）、
`timeout_sec`（单任务超时，默认 900）、`prompt_prefix`（任务前的定向语）。

## 6. 许可

harness 为 DeepSeek Harness（MIT，源码：github.com/deepseek-ai/deepseek-harness，
本部署版本 0.2.1-alpha.2），许可原文在其 `LICENSE` 内，本程序未做任何改动。
