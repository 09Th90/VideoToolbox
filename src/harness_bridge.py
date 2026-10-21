# @version 2.4.1
"""deepseek-harness 适配层——工具箱**单向适配** harness 的唯一入口。

设计契约（用户 2026-10-14 拍板）
--------------------------------
1. **harness 独立部署、内部零改动**：harness（DeepSeek Harness，MIT）整目录
   放在程序根目录的 ``harness\\`` 下，是只读的第三方原件——本模块及整个工具箱
   **不写入、不修补** 该目录内的任何文件；升级 = 整目录替换。
2. **完全解耦**：工具箱去适配 harness，不是 harness 适配工具箱。通信只走
   harness 官方 CLI（``--profile headless`` 一次性任务 / ``web`` 交互控制台），
   一切运行期状态（profile、凭据、配置补丁）放 harness 目录**之外**的
   DSH_HOME（默认 ``<数据根>\\harness-home``）。
3. **API 配置唯一事实来源 = 工具箱「设置」页**（``data/ai_config.json``）：
   每次运行前把 base_url / api_key / model 同步成 harness 的 provider 路由与
   默认模型（home 级 ``cordis.patch.yml`` + ``.credentials.yaml``），
   用户不需要在 harness 里再配一遍 key。v2.3.0 起改为**实时同步**：
   「设置」页一保存（或 ai_config.json 任何落盘）立即重写这两个文件，
   headless 下次运行拿新值、已在跑的交互控制台经 HMR 热加载；
   ``.credentials.yaml`` 一律写 harness 原生 versioned 布局——旧版写
   pre-release flat 布局，运行中进程的 watcher 解析失败后会**沿用内存里的
   旧密钥**（用户实测「调用已经放弃的 API」正是此因）。
4. **路由级重试策略**：DeepSeek 官方 / 火山等账号普遍「组织并发 1、RPM 3」，
   而 harness 每个任务会并发打出两个请求（主循环 + 首提示标题生成），必撞
   429。v2.3.0 起补丁给路由挂 ``retryPolicy``（8 次重试 + 最长 60s 退避），
   并**禁用标题 LLM 与内置 DeepSeek 搜索**（后者会绕过设置页直连旧 API），
   把每任务请求数压回 1、且任何组件都不可能再调用废弃账号。
5. **Agent 技能包（v2.4.0）**：内置 harness 与一切第三方 Agent
   （Claude Code / WorkBuddy / Trae / Kimi…）共用同一份「工具箱技能卡」——
   ``AGENTS.md``（常驻指令，harness 经 DSH_HOME user-global 自动加载）
   + ``SKILL.md``（能力表 + 精确命令 + 中文思考铁律）；统一 CLI 入口
   ``src\\agent_cli.py``（无 Qt 依赖）。agent 开箱即知能干什么、直接调用，
   不再每轮任务花几十次推理重新发现目录结构（2026-10-15 用户实测痛点）。
6. **有无 harness 都不影响已有功能**：探测失败/未部署/未安装依赖时所有接口
   返回结构化状态，调用方降级即可，绝不向 GUI 抛异常。

harness 侧事实（2026-10-14 实测，源码内嵌部署）
-----------------------------------------------
* 启动器（按优先级）：``node <harness>\\apps\\cli\\lib\\bin.js``（构建产物，
  首选）→ ``node --import tsx/esm <harness>\\apps\\cli\\src\\bin.ts``（源码模式，
  未构建也能跑 headless）。
* 一次性任务：``dsh --profile headless "<文本>"``，cwd=程序根目录即 agent 的
  workspace；stdout 只有最终答复（exit 0=completed），stderr 是 reasoning 流。
* 交互控制台：``dsh web --no-open --host 127.0.0.1 --port <port>``。
* ``DSH_HOME`` 必须显式提供（源码/构建版都不回落 ``~/.dsh``）。
* provider 配置走 home 级补丁（对全部 profile 生效）：
  ``llm-pi-ai`` 的 ``providers.<route>``（``api: openai-completions`` +
  ``baseURL`` + ``apiKeyEnv``）+ ``agent-default-model`` 的 provider/model；
  密钥写 ``.credentials.yaml``（POSIX 标识符 → 非空字符串的严格映射）。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

__all__ = [
    "app_root", "data_dir", "harness_dir", "dsh_home",
    "load_config", "save_config", "probe", "available", "status_text",
    "sync_provider_config", "ensure_agent_assets", "run_task", "web_url",
    "web_alive", "start_web", "stop_web", "open_web", "start_config_watch",
]

#: 配置文件名（落在数据目录，属于工具箱自己的数据，不是 harness 的）
CONFIG_NAME = "harness_config.json"
#: harness 在程序根目录下的文件夹名（獨立部署、可整目录替换）
HARNESS_DIRNAME = "harness"
DEFAULT_PORT = 3080
DEFAULT_TIMEOUT_SEC = 900
#: 同步进 harness 的 provider 路由名与凭据引用名（自定义路由，合法小写连字符标识符）
ROUTE_NAME = "videotoolbox"
ROUTE_NAME_VISION = "videotoolbox-vision"
CRED_REF = "VT_LLM_API_KEY"
CRED_REF_VISION = "VT_VISION_API_KEY"
#: 内部状态缓存有效期（秒）——探测是几次 stat，没必要每次真跑
_CACHE_TTL = 3.0

_lock = threading.Lock()
_cache = {"t": 0.0, "probe": None}
_web_proc = None
#: sync_provider_config 的写互斥（脉冲线程 ↔ 任务/控制台启动线程）
_sync_write_lock = threading.Lock()


# ---------------------------------------------------------------- 路径解析
def app_root() -> str:
    """程序根目录（与引擎 ``video_toolbox.APP_DIR`` 同口径）。

    冻结运行（PyInstaller）取 exe 所在目录；源码运行取本文件上两级
    （``<根>\\src\\harness_bridge.py`` → ``<根>``）。
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _resolve_data_root() -> str:
    """数据根目录：环境变量 ``VT_DATA_ROOT`` > 指针文件 > 程序目录。

    与引擎 ``video_toolbox._resolve_data_root`` 保持一致（指针文件
    ``data_dir.txt`` 由「设置 → 工具设置 → 数据目录」写），此处不复用引擎
    是为了让本模块可独立 import / 单测（不拖进整个引擎）。
    """
    env = (os.environ.get("VT_DATA_ROOT") or "").strip().strip('"')
    if env:
        try:
            return os.path.abspath(env)
        except OSError:
            pass
    pointer = os.path.join(app_root(), "data_dir.txt")
    try:
        if os.path.isfile(pointer):
            with open(pointer, encoding="utf-8-sig") as f:
                v = f.read().strip().strip('"')
            if v:
                return os.path.abspath(v)
    except OSError:
        pass
    return app_root()


def data_dir() -> str:
    return os.path.join(_resolve_data_root(), "data")


def _config_path() -> str:
    return os.path.join(data_dir(), CONFIG_NAME)


def load_config() -> dict:
    """harness 接入配置（默认值 < 配置文件 < 环境变量）。"""
    cfg = {
        "enabled": True,
        "dir": "",            # 空 = <程序根>/harness
        "port": DEFAULT_PORT,
        "dsh_home": "",       # 空 = <数据根>/harness-home
        "timeout_sec": DEFAULT_TIMEOUT_SEC,
        "prompt_prefix": "",  # 空 = 内置默认定向语
        "open_console": False,  # 任务完成后是否顺带打开交互控制台
    }
    try:
        p = _config_path()
        if os.path.isfile(p):
            with open(p, encoding="utf-8-sig") as f:
                disk = json.load(f) or {}
            for k in list(cfg):
                if k in disk and disk[k] is not None:
                    cfg[k] = disk[k]
    except Exception:  # noqa: BLE001 —— 配置损坏不影响任何既有功能
        pass
    env = (os.environ.get("VT_HARNESS_DIR") or "").strip().strip('"')
    if env:
        cfg["dir"] = env
    env = (os.environ.get("VT_HARNESS_PORT") or "").strip()
    if env.isdigit():
        cfg["port"] = int(env)
    env = (os.environ.get("VT_HARNESS_DSH_HOME") or "").strip().strip('"')
    if env:
        cfg["dsh_home"] = env
    if (os.environ.get("VT_HARNESS_DISABLED") or "").strip() == "1":
        cfg["enabled"] = False
    try:
        cfg["port"] = int(cfg["port"])
    except Exception:  # noqa: BLE001
        cfg["port"] = DEFAULT_PORT
    try:
        cfg["timeout_sec"] = max(30, int(cfg["timeout_sec"]))
    except Exception:  # noqa: BLE001
        cfg["timeout_sec"] = DEFAULT_TIMEOUT_SEC
    return cfg


def save_config(cfg: dict) -> None:
    """写回配置（只认白名单键，避免磁盘上的历史键被悄悄抹掉）。"""
    keep = ("enabled", "dir", "port", "dsh_home", "timeout_sec",
            "prompt_prefix", "open_console")
    out = {k: cfg[k] for k in keep if k in cfg}
    try:
        os.makedirs(data_dir(), exist_ok=True)
        with open(_config_path(), "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
    except Exception:  # noqa: BLE001
        pass


def harness_dir() -> str:
    d = (load_config().get("dir") or "").strip().strip('"')
    if d:
        return os.path.abspath(d)
    return os.path.join(app_root(), HARNESS_DIRNAME)


def dsh_home() -> str:
    """harness 的运行期根（profile/凭据/补丁全部在这里，**不在 harness 目录内**）。

    默认落在数据目录 ``<数据根>\\data\\harness-home``（与引擎"运行期产物一律
    落 data"的约定一致），可用 ``VT_HARNESS_DSH_HOME`` 或配置覆盖。
    """
    d = (load_config().get("dsh_home") or "").strip().strip('"')
    if d:
        return os.path.abspath(d)
    return os.path.join(data_dir(), "harness-home")


# ---------------------------------------------------------------- 探测
def _node_exe() -> str:
    """node 可执行文件：PATH 优先 → tools 目录运行时（在线安装形态由
    tools/download_open_source_deps.py 的 node 项下载）→ harness 部署目录旁。"""
    n = shutil.which("node")
    if n:
        return n
    for c in (os.path.join(app_root(), "tools", "node.exe"),
              os.path.join(harness_dir(), "node.exe"),
              os.path.join(harness_dir(), "runtime", "node.exe")):
        if os.path.isfile(c):
            return c
    return ""


def _cli_entry() -> str:
    """harness CLI 入口（构建产物优先，其次 TypeScript 源码入口）。

    两者都从 harness 的 ``package.json`` / 目录布局**只读推断**，不写任何文件。
    """
    base = harness_dir()
    built = os.path.join(base, "apps", "cli", "lib", "bin.js")
    if os.path.isfile(built):
        return built
    src = os.path.join(base, "apps", "cli", "src", "bin.ts")
    if os.path.isfile(src):
        return src
    return ""


def _launcher() -> list:
    """拼出启动 argv 前缀；无法启动时返回空列表。

    优先级：构建产物（``node lib/bin.js``）→ 源码模式（需要 tsx 依赖在场）
    → pnpm/corepack（``pnpm dsh``，最重，留作兜底）。
    """
    node = _node_exe()
    entry = _cli_entry()
    if node and entry:
        if entry.endswith(".js"):
            return [node, entry]
        # 源码模式：tsx 必须已安装（harness 根 devDependencies 之一）
        if os.path.isdir(os.path.join(harness_dir(), "node_modules", "tsx")):
            return [node, "--import", "tsx/esm", entry]
    return []


def _pnpm_launcher() -> list:
    """兜底启动器：pnpm（PATH）或 corepack pnpm（Node 22 自带）。"""
    p = shutil.which("pnpm")
    if p:
        return [p, "dsh"]
    c = shutil.which("corepack")
    if c:
        return [c, "pnpm", "dsh"]
    return []


def probe(force: bool = False) -> dict:
    """探测 harness 部署状态（带 3 秒缓存；force=True 强制重查）。

    返回 ``{"state", "detail", "dir", "launcher"}``：

    * ``ready``      —— 可启动（node + CLI 入口都在）
    * ``disabled``   —— 配置里关闭了接入
    * ``missing``    —— 没有 harness 文件夹 / 不是 harness 源码树
    * ``no_node``    —— 找不到 node
    * ``not_installed`` —— 有源码但没装依赖（``node_modules`` 缺失）
    * ``no_launcher``  —— 依赖装了但既无构建产物也无 tsx（需要先构建）
    """
    now = time.time()
    with _lock:
        if not force and _cache["probe"] is not None and now - _cache["t"] < _CACHE_TTL:
            return dict(_cache["probe"])

    cfg = load_config()
    base = harness_dir()
    result = {"state": "missing", "detail": "", "dir": base, "launcher": []}

    if not cfg.get("enabled", True):
        result.update(state="disabled", detail="已在配置中关闭 AI 托管接入")
    elif not os.path.isdir(base) or not os.path.isfile(os.path.join(base, "package.json")):
        result["detail"] = "未找到 harness 部署目录：%s" % base
    elif not _node_exe():
        result.update(state="no_node", detail="未找到 node 运行时（harness 需要 Node.js）")
    else:
        launcher = _launcher()
        if launcher:
            result.update(state="ready", launcher=launcher,
                          detail="harness 就绪（%s）" % os.path.basename(launcher[-1]))
        elif not os.path.isdir(os.path.join(base, "node_modules")):
            result.update(state="not_installed",
                          detail="harness 依赖未安装（%s\\node_modules 不存在）" % base)
        else:
            result.update(state="no_launcher",
                          detail="harness 未构建且无 tsx，无法启动（需 pnpm run build）")

    with _lock:
        _cache["t"] = time.time()
        _cache["probe"] = dict(result)
    return dict(result)


def available() -> bool:
    return probe()["state"] == "ready"


#: 每个非 ready 状态的处置引导（界面「怎么修」卡片 + 复制命令按钮用）。
#  写在这里而不是页面里，是为了让 CLI / 日志 / 界面拿到**同一份**口径；
#  页面只负责排版，不含任何 harness 细节（模块边界见 harness_page docstring）。
_DEPLOY_DOC = "docs/AI托管_部署与排障.md"


def _quoted(p: str) -> str:
    """命令行里安全包围路径（含空格/中文时必加引号）。"""
    return '"%s"' % p if (" " in p or "\t" in p) else p


def fix_hint(state: str, probe_result: "dict | None" = None) -> str:
    """给定探测状态，返回给人看的处置步骤（多行纯文本）。

    ``ready`` / 未知状态返回空串——调用方据此隐藏「怎么修」区块。
    """
    p = probe_result or probe()
    base = p.get("dir") or harness_dir()
    node_need = "Node.js >= 22.19"

    if state == "missing":
        frozen = getattr(sys, "frozen", False)
        head = (
            "harness 引擎本体**没有随安装包分发**（官方第三方原件、体积约 2.2 GB，"
            "刻意不进安装包），安装版 exe 所在目录下自然没有 harness 文件夹。"
            if frozen else
            "harness 部署目录不存在。"
        )
        # 安装版与源码版给出的上手路径不同：后者仓库里通常已经有一份可直接拷
        return "\n".join([
            head,
            "",
            "解决（二选一）：",
            "  A. 从已有部署处整目录复制（最快，含依赖与构建产物，拷完即用）",
            "  B. 干净安装：下载官方源码 zip 解压到下面这个目录，再装依赖并构建",
            "",
            "预期目录：%s" % base,
            "",
            "方式 B 的命令（在该目录的父目录执行）：",
            "  mkdir %s" % _quoted(base),
            "  cd %s" % _quoted(base),
            "  # 把官方源码 zip 内容解压覆盖到这里（应有 package.json）",
            "  pnpm install --ignore-scripts",
            "  pnpm run build",
            "",
            "前置：%s，且在 PATH 中可执行（装依赖时加 LEFTHOOK=0，"
            "否则会污染工具箱仓库的 git hooks）。" % node_need,
        ])

    if state == "no_node":
        return "\n".join([
            "harness 需要 %s，但 PATH、tools 目录、harness 目录旁都没找到 node。" % node_need,
            "",
            "解决：安装 Node.js 后重试，或把 node.exe 放到下列任一位置：",
            "  · tools\\node\\node.exe（在线安装形态由下载依赖向导拉取）",
            "  · harness 目录旁边",
            "  然后点「重新检测」。",
        ])

    if state == "not_installed":
        return "\n".join([
            "harness 源码在，但依赖没装（%s\\node_modules 不存在）。" % base,
            "",
            "解决：",
            "  cd %s" % _quoted(base),
            "  LEFTHOOK=0 pnpm install --ignore-scripts",
            "",
            "装完点「重新检测」。",
        ])

    if state == "no_launcher":
        return "\n".join([
            "依赖装了，但既没有构建产物、也没有 tsx，起不来。",
            "",
            "解决：",
            "  cd %s" % _quoted(base),
            "  pnpm run build",
            "",
            "不想构建也可以在 harness 根装一个 tsx（源码模式运行，会更慢）。",
        ])

    if state == "disabled":
        return "\n".join([
            "已在配置里关闭 AI 托管接入。",
            "",
            "解决：删除配置项 enabled=false（或把它改 true）后点「重新检测」：",
            "  %s" % _config_path(),
        ])

    return ""


#: 界面「复制命令」按钮给出的、针对 missing / not_installed / no_launcher 的
#: 可直接粘贴的命令串（按当前状态取，避免给用户一堆用不上的步骤）。
def fix_commands(state: str, probe_result: "dict | None" = None) -> str:
    p = probe_result or probe()
    base = p.get("dir") or harness_dir()
    if state == "missing":
        return "\r\n".join([
            'mkdir "%s"' % base,
            'cd /d "%s"' % base,
            "# 解压官方源码 zip 到此处（含 package.json）",
            "set LEFTHOOK=0",
            "pnpm install --ignore-scripts",
            "pnpm run build",
        ])
    if state == "not_installed":
        return "\r\n".join([
            'cd /d "%s"' % base,
            "set LEFTHOOK=0",
            "pnpm install --ignore-scripts",
        ])
    if state == "no_launcher":
        return "\r\n".join([
            'cd /d "%s"' % base,
            "pnpm run build",
        ])
    return ""


def doc_path() -> str:
    """部署排障文档在磁盘上的路径（可能不存在，调用方要先判断）。

    注意：``_DEPLOY_DOC`` 是单条相对路径，必须作为**一个参数**传给
    ``os.path.join``——若写成 ``*rel`` 会把字符串拆成单个字符逐个拼接，
    中文路径会整个被切碎（``D:\\A\\I\\托\\管…``）。
    """
    rel = _DEPLOY_DOC.replace("/", os.sep)
    return os.path.join(app_root(), rel)


def status_text() -> str:
    """给界面/日志用的一行式状态。"""
    p = probe()
    return "%s：%s" % (p["state"], p["detail"])


# ---------------------------------------------------------------- 子进程环境
#: 权限模式默认值。本机 Windows ACL 沙箱的「私有临时根目录」provisioning 实测
#: 失败（agent 每条 pwsh 都报 ACL 错，shell 工具整体瘫痪），且 headless 模式
#: 无人可应答审批；产品承诺（任务页说明 + 定向语）本就是「AI 可读写工作区、
#: 执行命令来托管本程序」。故默认 danger-full-access，可用
#: VT_HARNESS_PERMISSION_MODE 覆盖（read-only / workspace-write /
#: danger-full-access）。
_DEFAULT_PERMISSION_MODE = "danger-full-access"


def child_env() -> dict:
    """harness 子进程环境：DSH_HOME 外置 + 屏蔽 corepack/lefthook 交互。"""
    env = dict(os.environ)
    home = dsh_home()
    try:
        os.makedirs(home, exist_ok=True)
    except OSError:
        pass
    env["DSH_HOME"] = home
    # 资源下载缓存也放数据区（harness 目录零写入）
    env["DSH_RESOURCE_CACHE"] = os.path.join(home, ".resource-cache")
    env["COREPACK_ENABLE_DOWNLOAD_PROMPT"] = "0"
    env["COREPACK_ENABLE_STRICT"] = "0"
    env["LEFTHOOK"] = "0"   # 杜绝 harness 的 postinstall 反向污染父仓库
    env["CI"] = env.get("CI", "1")
    # sandbox-policy / approval 两行都是 !!js process.env.DSH_PERMISSION_MODE
    env["DSH_PERMISSION_MODE"] = (
        (os.environ.get("VT_HARNESS_PERMISSION_MODE") or "").strip()
        or _DEFAULT_PERMISSION_MODE)
    return env


def _kill_tree(proc) -> None:
    """Windows 下整棵进程树杀掉（node 会再拉子进程）。"""
    if proc is None or proc.poll() is not None:
        return
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           capture_output=True, timeout=10,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        else:
            proc.kill()
    except Exception:  # noqa: BLE001
        try:
            proc.kill()
        except Exception:  # noqa: BLE001
            pass


# ------------------------------------------- 设置页配置 → harness（唯一事实来源）
def _read_toolbox_ai() -> dict:
    """读工具箱「设置」页的 AI 配置（与 tools/ai_client.py 同一份文件）。

    只取需要的键；读失败/缺项返回空 dict，由调用方转译成用户可读的提示。
    """
    for p in (os.path.join(data_dir(), "ai_config.json"),
              os.path.join(app_root(), "data", "ai_config.json")):
        try:
            if os.path.isfile(p):
                with open(p, encoding="utf-8-sig") as f:
                    d = json.load(f)
                if isinstance(d, dict):
                    return d
        except Exception:  # noqa: BLE001
            continue
    return {}


#: 路由级重试策略（llm-pi-ai provider 自有的 ``retryPolicy``，由 dsh-llm-retry 执行）。
#: 依据（2026-10-15 实测）：harness 每个任务会并发打出两个请求——主 agent 循环 +
#: 首提示标题生成（session-title-first-prompt-llm 走同一路由）；DeepSeek 官方 /
#: 火山等账号普遍「组织并发 1、RPM 3」，两个请求相撞即 429，重试耗尽后整次任务
#: 退出码 1。``maxDelayMs`` 必须 ≥ provider 回报的 ``Retry-After``（实测 1s），
#: 否则 llm-retry 对 normal 模式直接放弃重试；故给到 60s 窗口、8 次重试。
_RETRY_POLICY_LINES = [
    "        retryPolicy:",
    "          mode: normal",
    "          maxRetries: 8",
    "          retryableCodes:",
    "            - RATE_LIMIT",
    "            - SERVER",
    "            - TIMEOUT",
    "            - TRANSPORT",
    "            - EMPTY_RESPONSE",
    "          backoff:",
    "            initialDelayMs: 2000",
    "            maxDelayMs: 60000",
    "            jitterRatio: 0.2",
]

#: glob/grep 工具超时（默认 30s）。程序根含 harness\node_modules（十万级文件），
#: 一次宽模式 glob 必然超时（实测 agent 「glob超时了」后连环换工具）。提到 120s。
_SEARCH_TIMEOUT_MS = 120000


def _patch_yaml(base_url: str, model: str, vision_base: str,
                vision_model: str) -> str:
    """生成 home 级 cordis.patch.yml（自定义 OpenAI 兼容路由 + 默认模型）。

    除 provider 路由外，还负责把 harness 内置的「旧 API 消费端」摘掉
    （用户实测切了设置页账号后仍在调用废弃 API 的两条路径）：

    * ``session-title-llm`` 禁用 —— 首提示标题生成与主循环**并发**打同一个
      路由，是 429 撞车的直接原因；禁用后退回确定性标题（取首条消息前几个
      词），不花 token、不占并发。
    * ``web-search-deepseek`` 禁用 —— 内置搜索走 ``deepseek-official`` 路由
      （apiKeyEnv=DEEPSEEK_API_KEY），完全绕开设置页；禁用后 ``web`` 行仍配着
      ``searchProvider: deepseek-official``，agent 一旦调用搜索会得到
      「配置的提供方未注册」的明确错误，而不是静默连到废弃账号。

    补丁语义注意：cordis 的 patch **整段替换**目标行的 config（不合并），
    所以 ``tool-fs-search`` 必须把它必填的 ``sampleOverCapGlobResults``
    一起重述，否则该行校验失败、glob 工具直接挂掉。
    """
    lines = [
        "- id: llm-pi-ai",
        "  config:",
        "    providers:",
        "      %s:" % ROUTE_NAME,
        "        displayName: 视频工具箱（设置页配置）",
        "        apiKeyEnv: %s" % CRED_REF,
        "        api: openai-completions",
        "        baseURL: %s" % base_url,
        "        models:",
        "          - id: %s" % model,
        "            input:",
        "              - text",
    ]
    lines += _RETRY_POLICY_LINES
    if vision_model and vision_model != model:
        lines += [
            "          - id: %s" % vision_model,
            "            input:",
            "              - text",
            "              - image",
        ]
    if vision_base and vision_base != base_url:
        lines += [
            "      %s:" % ROUTE_NAME_VISION,
            "        displayName: 视频工具箱（设置页·视觉）",
            "        apiKeyEnv: %s" % CRED_REF_VISION,
            "        api: openai-completions",
            "        baseURL: %s" % vision_base,
            "        models:",
            "          - id: %s" % vision_model,
            "            input:",
            "              - text",
            "              - image",
        ]
        lines += _RETRY_POLICY_LINES
    lines += [
        "- id: agent-default-model",
        "  config:",
        "    provider: %s" % ROUTE_NAME,
        "    model: %s" % model,
        "",
        # —— 摘除内置旧 API 消费端（详见函数 docstring）——
        "- id: session-title-llm",
        "  disabled: true",
        "- id: web-search-deepseek",
        "  disabled: true",
        # —— glob/grep 超时放宽（整段替换，必填项一起重述）——
        "- id: tool-fs-search",
        "  config:",
        "    sampleOverCapGlobResults: false",
        "    timeoutMs: %d" % _SEARCH_TIMEOUT_MS,
        "",
    ]
    return "\n".join(lines)


def sync_provider_config(force: bool = False) -> dict:
    """把工具箱「设置」页的 AI 配置同步进 harness 的 DSH_HOME。

    写两个文件（都在 DSH_HOME，**不碰 harness 目录**）：

    * ``.credentials.yaml`` —— 凭据仓库。**必须写 harness 原生的
      versioned 布局**（``version: 1`` + ``refs:``）：运行中进程的
      chokidar watcher 只认这个布局，pre-release flat 布局会被
      ``parseCredentialsDocument`` 拒绝、reload 失败后**沿用内存里的旧
      密钥**——那就是「切换账号后仍调用废弃 API」的根因（2026-10-15 实证）。
    * ``cordis.patch.yml`` —— home 级补丁：``llm-pi-ai`` 自定义路由 +
      ``agent-default-model`` 默认模型 + 重试策略 + 摘除内置旧 API 消费端，
      对 web/headless 全部 profile 生效；长驻进程经 cordis HMR 热加载。

    refs 全量替换（设置页是唯一事实来源，彻底替换掉旧的）；``records:`` 段
    （harness Models 页 / 登录态自管）形态可信时原样保留。内容一致时跳过
    写入（不动 mtime，避免无谓触发 HMR）。返回 ``{"ok", "detail"}``。
    """
    ai = _read_toolbox_ai()
    base_url = (ai.get("base_url") or "").strip()
    api_key = (ai.get("api_key") or "").strip()
    model = (ai.get("model") or "").strip()
    if not (base_url and api_key and model):
        return {"ok": False,
                "detail": "请先在「设置」页配置 AI（接口地址 / 密钥 / 模型）"}
    vision_base = (ai.get("vision_base_url") or "").strip() or base_url
    vision_model = (ai.get("vision_model") or "").strip() or model
    vision_key = (ai.get("vision_api_key") or "").strip() or api_key

    home = dsh_home()
    try:
        os.makedirs(home, exist_ok=True)
    except OSError as e:
        return {"ok": False, "detail": "无法创建 DSH_HOME：%s" % e}

    cred_refs = {CRED_REF: api_key}
    if vision_base != base_url or vision_model != model:
        cred_refs[CRED_REF_VISION] = vision_key
    cp = os.path.join(home, ".credentials.yaml")
    cred_text = _credentials_text(cred_refs, _read_text(cp))
    patch_text = _patch_yaml(base_url, model, vision_base, vision_model)

    try:
        with _sync_write_lock:      # 脉冲线程与任务线程互斥，杜绝同 PID 临时文件相撞
            if force or not os.path.isfile(cp) or _read_text(cp) != cred_text:
                _write_private(cp, cred_text)
            pp = os.path.join(home, "cordis.patch.yml")
            if force or not os.path.isfile(pp) or _read_text(pp) != patch_text:
                _write_atomic(pp, patch_text)
    except OSError as e:
        return {"ok": False, "detail": "写入 harness 配置失败：%s" % e}
    return {"ok": True, "detail": "已按「设置」页同步（%s @ %s）" % (model, base_url)}


def _yaml_quote(value: str) -> str:
    """YAML 双引号标量：密钥可能含 ``#`` / ``:`` / 前导 ``*`` 等字符，一律转义。"""
    return '"%s"' % value.replace("\\", "\\\\").replace('"', '\\"')


def _extract_records_section(text: str) -> str:
    """从既有 versioned 文档里原样取出 ``records:`` 段（harness 自管登录态等）。

    只认块式风格（机器写入的形态）；取不到或形态存疑返回空串，由调用方退化
    为「只写 refs」——绝不产出连自己都无法置信的文档。
    """
    start = -1
    lines = (text or "").splitlines()
    for i, ln in enumerate(lines):
        if ln.rstrip() == "records:":
            start = i
            break
    if start < 0:
        return ""
    body: list = []
    for ln in lines[start + 1:]:
        if ln.strip() and not ln[:1].isspace():
            break                      # 下一个顶层键，records 段结束
        body.append(ln)
    while body and not body[-1].strip():
        body.pop()
    if not body:
        return ""
    if any(ln.strip() and not ln[:1].isspace() for ln in body):
        return ""                     # 段内存疑（非块式），放弃保留
    return "\n".join(body) + "\n"


def _credentials_text(refs: dict, existing: str) -> str:
    """渲染 harness 原生 versioned 凭据文档（``version: 1`` + ``refs:``）。

    refs 全量替换；``records:`` 段存在且形态可信时原样保留在文档尾部。
    """
    lines = ["version: 1", "refs:"]
    for k, v in refs.items():
        lines.append("  %s: %s" % (k, _yaml_quote(v)))
    records = _extract_records_section(existing)
    if records:
        lines.append("records:")
        lines.extend(records.rstrip("\n").split("\n"))
    return "\n".join(lines) + "\n"


def _read_text(p: str) -> str:
    try:
        with open(p, encoding="utf-8-sig") as f:
            return f.read()
    except OSError:
        return ""


def _write_atomic(p: str, text: str) -> None:
    """原子写（临时文件 + os.replace）：读者只会看到旧或新的完整内容，
    不会读到半个文件——harness 的凭据 watcher 对半截文档会解析失败。"""
    tmp = os.path.join(os.path.dirname(p) or ".",
                       ".%s.tmp.%d" % (os.path.basename(p), os.getpid()))
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    os.replace(tmp, p)


def _write_private(p: str, text: str) -> None:
    """写凭据文件；POSIX 上尽量收紧权限（Windows 无 mode 可设，跳过）。"""
    _write_atomic(p, text)
    try:
        if os.name == "posix":
            os.chmod(p, 0o600)
    except OSError:
        pass


# ---------------------------------------- 第三方 Agent 技能包（常驻内容）
#: 与仓库静态文件逐字节同源（selftest 断言相等）：
#:   AGENTS.md / CLAUDE.md / .trae/rules/project_rules.md   <- _AGENTS_MD_TEXT
#:   SKILL.md / .claude/skills/video-toolbox/SKILL.md / .workbuddy/skills/
#:   video-toolbox/SKILL.md / .agents/skills/video-toolbox/SKILL.md  <- _SKILL_MD_TEXT
#: 内置 harness：<DSH_HOME>/AGENTS.md（user-global 常驻指令，每会话自动加载）
#: + <DSH_HOME>/skills/video-toolbox/SKILL.md（user-dsh 技能，skill 工具按需取用）。
#: 安装版程序根 best-effort 物化同一套文件（只读目录失败即跳过）。
_AGENTS_MD_TEXT = r"""# 视频工具箱 · Agent 常驻指令

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
"""

_SKILL_MD_TEXT = r"""---
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

## 能力表（直接调用，别自己搓）

| 子命令 | 干什么 | 示例 |
|---|---|---|
| `status [--ping]` | 环境自检：ffmpeg/yt-dlp/deno 在位性、AI 与 ASR 槽是否已配 | `status --json` |
| `info <file>` | 媒体元信息（ffprobe）/ 字幕 cue 数与时间跨度 | `info ep01.mp4` |
| `download <url> [--height 1080] [--dir D]` | 下载（yt-dlp 全链：自动代理+游客 cookie+风控重试，合并 mp4） | `download "https://…" --height 1080` |
| `transcribe <file> [--lang ja] [--out x.srt]` | 音视频 → SRT（引擎 ASR 全链；模型/密钥读设置页 ASR 槽） | `transcribe ep01.mp4 --lang ja` |
| `translate <srt> [--to zh-Hans] [--engine bing]` | → 中文双语 SRT（原文在上、译文在下，时间轴不动） | `translate ep01.en.srt --engine bing` |
| `calibrate <srt> [旗标] [--out F] [--report R]` | 术语校准（只改文字，不动时间轴/序号/空行/换行/BOM） | `calibrate ep01.zh.srt --endobi` |
| `stabilize <srt> [--out F]` | cue 稳定化（透传同脚本 stabilize 子命令） | `stabilize ep01.srt` |
| `compose <video> <sub> [--mode soft\|burn\|mkv] [--audio x.m4a] [--out F]` | 字幕合成（soft=软封装不重编码；burn=ASS 硬烧；mkv=封装） | `compose ep01.mp4 ep01.srt --mode burn` |

## 标准配方

### 「翻译，然后完成校准」（最常见）

1. `info` 确认 cue 数与源语言；
2. `translate --engine bing` 出双语 SRT——**谷歌端点本机 429/421 不可用，不要尝试 google**；
3. `calibrate` 按游戏选旗标（见下表）；
4. 汇报：产物路径、cue 数、校准改动数。

### 一条龙：下载 → 转录 → 翻译 → 校准 → 合成

`download` → `transcribe --lang <源语言>` → `translate` → `calibrate` → `compose`。

## 校准旗标速查（与 subtitle_calib_merged.py 完全同源）

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
- 校准脚本透传时退出码原样保留（`length` 子命令用退出码当门禁）；`data\subtitle_learned_kb.json` 是学习库，校准跑完会更新其中的日期书签，属正常现象。
- 一次性脚本放 `data\tmp\`；脚本内取程序根用 `os.getcwd()`（harness/agent 的 cwd 就是程序根），**不要**用 `__file__` 相对推导（放 `data\tmp\` 下会算错）。
- `harness\` 是只读第三方部署，禁止改动；`src\` 是工具箱源码，可读可改。
- 路径在程序根之外没关系（托管 agent 有 danger-full-access），但读大文件前先 `info` 看规模。

## 数据目录布局

```
data\
  ai_config.json      「设置」页的 AI/ASR 配置（CLI 唯一读取处）
  agent_out\          CLI 产物（<时间戳>\ 每次调用一个目录）
  downloads\          下载产物（GUI 与 CLI 共用）
  tmp\                一次性脚本/中间产物
  harness-home\      内置 AI 托管（harness）的运行期数据
```
"""


def agent_asset_paths() -> "list[tuple[str, str]]":
    """各 Agent 约定位置 → 内容键（``agents`` / ``skill``）。

    第三方 Agent 的技能包落点（与仓库静态文件同源同内容）：
    harness 走 DSH_HOME（user-global 常驻 + user-dsh 技能）；程序根副本让
    Claude Code / WorkBuddy / Trae / Kimi 等把程序目录当工作区打开即接入。
    """
    root = app_root()
    home = dsh_home()
    return [
        (os.path.join(home, "AGENTS.md"), "agents"),
        (os.path.join(home, "skills", "video-toolbox", "SKILL.md"), "skill"),
        (os.path.join(root, "AGENTS.md"), "agents"),
        (os.path.join(root, "CLAUDE.md"), "agents"),
        (os.path.join(root, "SKILL.md"), "skill"),
        (os.path.join(root, ".claude", "skills", "video-toolbox", "SKILL.md"), "skill"),
        (os.path.join(root, ".workbuddy", "skills", "video-toolbox", "SKILL.md"), "skill"),
        (os.path.join(root, ".agents", "skills", "video-toolbox", "SKILL.md"), "skill"),
        (os.path.join(root, ".trae", "rules", "project_rules.md"), "agents"),
    ]


def ensure_agent_assets(force: bool = False) -> dict:
    """把「工具箱技能包」物化到各 Agent 约定位置（内容一致才跳过写入）。

    解决的问题（2026-10-15 用户实测）：第三方/内置 agent 都要"非常清楚工具箱
    能干什么、直接调用"，而不是每轮任务花几十次推理重新发现目录结构。
    AGENTS.md 是常驻指令（每会话自动进上下文）；SKILL.md 是按需取用的详细
    技能卡。``force`` 或内容变化才写（原子写，不无谓触发 watcher）。
    """
    texts = {"agents": _AGENTS_MD_TEXT, "skill": _SKILL_MD_TEXT}
    written, skipped, failed = 0, 0, []
    for path, key in agent_asset_paths():
        try:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            if not force and os.path.isfile(path) and _read_text(path) == texts[key]:
                skipped += 1
                continue
            _write_atomic(path, texts[key])
            written += 1
        except OSError as e:
            failed.append("%s（%s）" % (os.path.basename(path), e.strerror or e))
    detail = "技能包已就位（写入 %d / 跳过 %d）" % (written, skipped)
    if failed:
        detail += "；失败：%s" % "；".join(failed[:3])
    return {"ok": not failed, "detail": detail, "written": written}


# ---------------------------------------------------------------- 实时同步
#: 变动脉冲周期（秒）。ai_config.json 是设置页唯一落点，stat 一次成本可忽。
_WATCH_INTERVAL_SEC = 2.0
_watch_lock = threading.Lock()
_watch_thread = None
_watch_stop = threading.Event()


def _ai_config_paths() -> list:
    """设置页 AI 配置的全部可能落点（与 ``_read_toolbox_ai`` 同口径）。"""
    return [os.path.join(data_dir(), "ai_config.json"),
            os.path.join(app_root(), "data", "ai_config.json")]


def _config_signature() -> tuple:
    sig = []
    for p in _ai_config_paths():
        try:
            st = os.stat(p)
            sig.append((p, st.st_mtime_ns, st.st_size))
        except OSError:
            sig.append((p, None, None))
    return tuple(sig)


def _watch_loop(interval: float) -> None:
    last = _config_signature()
    while not _watch_stop.wait(interval):
        sig = _config_signature()
        if sig == last:
            continue
        last = sig
        try:
            sync_provider_config()
        except Exception:  # noqa: BLE001 —— 脉冲异常绝不影响宿主
            pass


def start_config_watch(interval: float = _WATCH_INTERVAL_SEC) -> bool:
    """启动「设置」页配置的变动脉冲（守护线程，幂等；返回是否新启动）。

    ai_config.json 每次落盘（mtime/大小变化）立即把 provider 路由与凭据
    重写进 DSH_HOME：headless 下次运行拿到新值；**已在跑的交互控制台**经
    cordis HMR（home patch）+ 凭据 watcher（versioned 文档）热加载——
    做到「API 信息实时变化、彻底替换旧的」。运行任务 / 启动控制台时调用。
    """
    global _watch_thread
    with _watch_lock:
        if _watch_thread is not None and _watch_thread.is_alive():
            return False
        _watch_stop.clear()
        t = threading.Thread(target=_watch_loop, args=(interval,), daemon=True,
                             name="vt-harness-config-watch")
        t.start()
        _watch_thread = t
        return True


# ---------------------------------------------------------------- 一次性任务
PROMPT_PREFIX_DEFAULT = (
    "【运行环境说明 · 由视频工具箱自动附加】\n"
    "你在「视频工具箱」的程序根目录中工作（当前工作目录即程序根）。\n"
    "- Python 运行时：tools\\python\\python.exe；引擎源码在 src\\ 下。\n"
    "- 运行期数据集中在 data\\（配置 / 下载 / 日志 / 临时产物），日志在 logs\\。\n"
    "- 你可以读写本工作区文件并执行命令来完成用户的任务；处理音视频、字幕、"
    "下载、校准等优先复用程序已有能力（src\\ 下的模块、tools\\ 下的二进制）。\n"
    "- **统一 CLI 入口（优先用它，不要自己重新实现）**："
    "tools\\python\\python.exe src\\agent_cli.py <子命令> --json，"
    "子命令 status/info/download/transcribe/translate/calibrate/stabilize/"
    "compose；完整技能卡见程序根 SKILL.md。\n"
    "- **思考过程（reasoning）与最终汇报一律使用简体中文**，不要用英文思考。\n"
    "- 完成后用简体中文汇报：做了什么、关键产物路径、失败原因（如有）。\n\n"
    "【用户任务】\n"
)


#: 429 限流的可操作提示（harness 退出码 1 + stderr 含 RATE_LIMIT 时附上）。
#: TPD（每日 token 配额）与并发/RPM 是两种完全不同的失败，处置也不同。
_RATE_LIMIT_HINT = (
    "账号并发/RPM 限制：harness 已按路由重试策略重试仍失败。"
    "稍后重试，或在「设置」页更换并发更宽松的账号/模型。")


def _rate_limit_hint(err: str) -> str:
    """按限流类型给可操作提示（TPD 重试无用，必须换账号或等次日）。"""
    low = (err or "").lower()
    if "tpd" in low or "per day" in low or "tokens per day" in low:
        return ("账号每日 token 配额（TPD）已用尽——重试无用，"
                "请在「设置」页更换账号/模型，或等次日配额重置。")
    return _RATE_LIMIT_HINT


def run_task(text: str, timeout: int = 0, on_reasoning=None,
             cwd: str = "") -> dict:
    """把一段文本交给 harness 跑一个一次性 agent 任务（阻塞，放后台线程调）。

    参数
    ----
    text:         用户在首页任务框里输入的纯文本。
    timeout:      秒；0 = 用配置里的 ``timeout_sec``。
    on_reasoning: 可选回调 ``fn(line: str)``，harness 的 reasoning 流（stderr）。
    cwd:          agent 的 workspace；默认 = 程序根目录（托管本程序）。

    返回 ``{"ok","answer","exit_code","reasoning","error","elapsed","argv"}``；
    任何失败都是**返回值**，不抛异常。
    """
    t0 = time.time()
    text = (text or "").strip()
    if not text:
        return {"ok": False, "answer": "", "exit_code": None, "reasoning": "",
                "error": "空任务文本", "elapsed": 0.0, "argv": []}
    p = probe(force=True)
    if p["state"] != "ready":
        return {"ok": False, "answer": "", "exit_code": None, "reasoning": "",
                "error": "harness 不可用：%s" % p["detail"], "elapsed": 0.0,
                "argv": []}
    start_config_watch()      # 实时同步：跑一次就够，幂等
    ensure_agent_assets()     # 技能包就位（AGENTS.md/SKILL.md，幂等）
    sync = sync_provider_config()
    if not sync["ok"]:
        return {"ok": False, "answer": "", "exit_code": None, "reasoning": "",
                "error": sync["detail"], "elapsed": 0.0, "argv": []}

    cfg = load_config()
    limit = int(timeout or cfg["timeout_sec"])
    prefix = cfg.get("prompt_prefix") or PROMPT_PREFIX_DEFAULT
    argv = list(p["launcher"]) + ["--profile", "headless", prefix + text]
    workdir = cwd or app_root()

    try:
        proc = subprocess.Popen(
            argv, cwd=workdir, env=child_env(),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
            if os.name == "nt" else 0)
    except OSError as e:
        return {"ok": False, "answer": "", "exit_code": None, "reasoning": "",
                "error": "启动 harness 失败：%s" % e, "elapsed": 0.0,
                "argv": argv}

    out_lines, err_lines = [], []
    boxes = {"out": out_lines, "err": err_lines}

    def _pump(stream, key):
        try:
            for line in stream:
                boxes[key].append(line)
                if key == "err" and on_reasoning is not None:
                    try:
                        on_reasoning(line.rstrip("\r\n"))
                    except Exception:  # noqa: BLE001 —— 回调异常不影响任务
                        pass
        except Exception:  # noqa: BLE001
            pass
        finally:
            try:
                stream.close()
            except Exception:  # noqa: BLE001
                pass

    ts = [threading.Thread(target=_pump, args=(proc.stdout, "out"), daemon=True),
          threading.Thread(target=_pump, args=(proc.stderr, "err"), daemon=True)]
    for t in ts:
        t.start()
    try:
        code = proc.wait(timeout=limit)
    except subprocess.TimeoutExpired:
        _kill_tree(proc)
        for t in ts:
            t.join(timeout=3)
        return {"ok": False, "answer": "", "exit_code": None,
                "reasoning": "".join(err_lines), "error": "任务超时（%ds）" % limit,
                "elapsed": time.time() - t0, "argv": argv}
    for t in ts:
        t.join(timeout=5)

    answer = "".join(out_lines).strip()
    err = "".join(err_lines)
    result = {"ok": code == 0 and bool(answer), "answer": answer,
              "exit_code": code, "reasoning": err, "error": "",
              "elapsed": time.time() - t0, "argv": argv}
    if code != 0:
        tail = "\n".join([l for l in err.strip().splitlines() if l.strip()][-6:])
        msg = ("harness 退出码 %s。%s" % (code, tail)).strip()
        if "RATE_LIMIT" in err or "rate_limit" in err.lower():
            msg += "\n" + _rate_limit_hint(err)
        result["error"] = msg
    elif not answer:
        result["error"] = "harness 没有产出最终答复"
    _save_transcript(text, result)
    return result


def _save_transcript(text: str, result: dict) -> None:
    """任务存档（数据目录内，便于回溯；失败不影响主流程）。"""
    try:
        d = os.path.join(dsh_home(), "transcripts")
        os.makedirs(d, exist_ok=True)
        name = time.strftime("%Y%m%d-%H%M%S", time.localtime())
        with open(os.path.join(d, "%s.md" % name), "w", encoding="utf-8") as f:
            f.write("# harness 任务 %s\n\n- 退出码：%s\n- 耗时：%.1fs\n\n"
                    "## 任务\n\n%s\n\n## 答复\n\n%s\n\n## 诊断\n\n```\n%s\n```\n"
                    % (name, result.get("exit_code"), result.get("elapsed", 0),
                       text, result.get("answer", ""),
                       (result.get("reasoning") or "")[-4000:]))
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------- 交互控制台
def _no_proxy_opener():
    """绕过环境变量里的 http_proxy——探针目标是本机 127.0.0.1。"""
    import urllib.request          # 惰性：仅探活/控制台路径需要
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def web_url() -> str:
    return "http://127.0.0.1:%d/" % load_config()["port"]


def web_token() -> str:
    """从日志里取控制台的访问令牌（``dsh web: .../?token=xxx``，取最后一条）。

    令牌由 harness 每次启动时生成；没启动过 / 日志被清时返回空串。
    """
    try:
        p = os.path.join(_resolve_data_root(), "logs", "harness-web.log")
        if not os.path.isfile(p):
            return ""
        token = ""
        with open(p, encoding="utf-8", errors="replace") as f:
            for line in f:
                if "token=" in line:
                    token = line.split("token=", 1)[1].strip()
        return token.split("&")[0].split("?")[0]
    except Exception:  # noqa: BLE001
        return ""


def web_console_url() -> str:
    """带令牌的完整控制台地址（可直接给用户点 / 复制）。"""
    t = web_token()
    return web_url() + ("?token=" + t if t else "")


def web_alive() -> bool:
    """harness Web 控制台是否已在监听。

    **任何 HTTP 响应都算活着**（401 = 服务在、要令牌；4xx/5xx 同理），
    只有连接被拒 / 超时才算没起来。必须绕代理——目标是本机回环。
    """
    try:
        import urllib.error        # 与 _no_proxy_opener 的 request 惰性导入配套
        with _no_proxy_opener().open(web_url(), timeout=3) as r:
            return r.status < 500
    except urllib.error.HTTPError:
        return True          # 服务端应答了（只是要令牌）
    except Exception:  # noqa: BLE001
        return False


def start_web(wait_sec: int = 180) -> dict:
    """启动（或复用）harness Web 控制台；返回 ``{"ok","url","detail"}``。

    冷启动要把整个插件树组合起来，实测 1～3 分钟，``wait_sec`` 给到 180s；
    已在跑就复用（可能是别的实例起的，不动它）。
    """
    global _web_proc
    if web_alive():
        return {"ok": True, "url": web_console_url(), "detail": "控制台已在运行"}
    p = probe(force=True)
    if p["state"] != "ready":
        return {"ok": False, "url": "", "detail": "harness 不可用：%s" % p["detail"]}
    start_config_watch()      # 控制台常驻：配置变化经 HMR 热加载
    ensure_agent_assets()     # 控制台会话同样吃到技能包（幂等）
    sync = sync_provider_config()
    if not sync["ok"]:
        return {"ok": False, "url": "", "detail": sync["detail"]}
    cfg = load_config()
    argv = list(p["launcher"]) + [
        "web", "--no-open", "--host", "127.0.0.1", "--port", str(cfg["port"])]
    log_path = os.path.join(_resolve_data_root(), "logs")
    try:
        os.makedirs(log_path, exist_ok=True)
        logf = open(os.path.join(log_path, "harness-web.log"), "a",
                    encoding="utf-8", errors="replace")
    except OSError:
        logf = subprocess.DEVNULL
    try:
        proc = subprocess.Popen(
            argv, cwd=app_root(), env=child_env(),
            stdout=logf, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
            creationflags=(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                           | getattr(subprocess, "DETACHED_PROCESS", 0))
            if os.name == "nt" else 0)
    except OSError as e:
        return {"ok": False, "url": "", "detail": "启动控制台失败：%s" % e}
    _web_proc = proc
    deadline = time.time() + max(10, wait_sec)
    while time.time() < deadline:
        if web_alive():
            return {"ok": True, "url": web_console_url(), "detail": "控制台已启动"}
        if proc.poll() is not None:
            return {"ok": False, "url": "",
                    "detail": "控制台进程退出（码 %s），见 logs/harness-web.log"
                              % proc.returncode}
        time.sleep(1.5)
    return {"ok": False, "url": "",
            "detail": "控制台启动超时（%ds），见 logs/harness-web.log" % wait_sec}


def stop_web() -> dict:
    """停掉本进程启动的控制台（复用他人已在跑的不动）。"""
    global _web_proc
    if _web_proc is None:
        return {"ok": True, "detail": "本实例未启动控制台"}
    _kill_tree(_web_proc)
    _web_proc = None
    return {"ok": True, "detail": "控制台已停止"}


def open_web() -> dict:
    """确保控制台在跑并用默认浏览器打开（完整交互式托管入口）。"""
    r = start_web()
    if r["ok"]:
        try:
            webbrowser.open(r["url"])
        except Exception:  # noqa: BLE001
            pass
    return r


# ------------------------------------------------------------ 模块级兜底落盘
# 技能包（AGENTS.md / SKILL.md 等 9 处约定位置）属于 harness 的「配套资产」，
# 不能依赖 harness 本体就绪（run_task/控制台）才落盘——在线安装形态用户可能
# 一直没部署 harness 本体，但配套必须开箱完整。主程序 exe 启动即无条件
# import 本模块（video_toolbox_qt 顶层），在这里幂等执行一次即可全链覆盖；
# 失败静默（只读目录等），不阻塞程序启动。
try:
    ensure_agent_assets()
except Exception:  # noqa: BLE001
    pass
