# @version 2.2.5
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
   用户不需要在 harness 里再配一遍 key。
4. **有无 harness 都不影响已有功能**：探测失败/未部署/未安装依赖时所有接口
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
import urllib.request
import webbrowser
from pathlib import Path

__all__ = [
    "app_root", "data_dir", "harness_dir", "dsh_home",
    "load_config", "save_config", "probe", "available", "status_text",
    "sync_provider_config", "run_task", "web_url", "web_alive",
    "start_web", "stop_web", "open_web",
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
    """node 可执行文件：PATH 优先，其次 harness 部署目录旁的可能位置。"""
    n = shutil.which("node")
    if n:
        return n
    for c in (os.path.join(harness_dir(), "node.exe"),
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


def status_text() -> str:
    """给界面/日志用的一行式状态。"""
    p = probe()
    return "%s：%s" % (p["state"], p["detail"])


# ---------------------------------------------------------------- 子进程环境
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


def _patch_yaml(base_url: str, model: str, vision_base: str,
                vision_model: str) -> str:
    """生成 home 级 cordis.patch.yml（自定义 OpenAI 兼容路由 + 默认模型）。"""
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
    lines += [
        "- id: agent-default-model",
        "  config:",
        "    provider: %s" % ROUTE_NAME,
        "    model: %s" % model,
        "",
    ]
    return "\n".join(lines)


def sync_provider_config(force: bool = False) -> dict:
    """把工具箱「设置」页的 AI 配置同步进 harness 的 DSH_HOME。

    写两个文件（都在 DSH_HOME，**不碰 harness 目录**）：

    * ``.credentials.yaml`` —— 凭据仓库（严格映射：标识符 → 非空字符串）
    * ``cordis.patch.yml`` —— home 级补丁：``llm-pi-ai`` 自定义路由 +
      ``agent-default-model`` 默认模型，对 web/headless 全部 profile 生效

    内容一致时跳过写入（不动 mtime）。返回 ``{"ok", "detail"}``。
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

    cred_lines = ["%s: %s" % (CRED_REF, api_key)]
    if vision_base != base_url or vision_model != model:
        cred_lines.append("%s: %s" % (CRED_REF_VISION, vision_key))
    cred_text = "\n".join(cred_lines) + "\n"
    patch_text = _patch_yaml(base_url, model, vision_base, vision_model)

    try:
        cp = os.path.join(home, ".credentials.yaml")
        if force or not os.path.isfile(cp) or _read_text(cp) != cred_text:
            _write_private(cp, cred_text)
        pp = os.path.join(home, "cordis.patch.yml")
        if force or not os.path.isfile(pp) or _read_text(pp) != patch_text:
            with open(pp, "w", encoding="utf-8", newline="\n") as f:
                f.write(patch_text)
    except OSError as e:
        return {"ok": False, "detail": "写入 harness 配置失败：%s" % e}
    return {"ok": True, "detail": "已按「设置」页同步（%s @ %s）" % (model, base_url)}


def _read_text(p: str) -> str:
    try:
        with open(p, encoding="utf-8-sig") as f:
            return f.read()
    except OSError:
        return ""


def _write_private(p: str, text: str) -> None:
    """写凭据文件；POSIX 上尽量收紧权限（Windows 无 mode 可设，跳过）。"""
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    try:
        if os.name == "posix":
            os.chmod(p, 0o600)
    except OSError:
        pass


# ---------------------------------------------------------------- 一次性任务
PROMPT_PREFIX_DEFAULT = (
    "【运行环境说明 · 由视频工具箱自动附加】\n"
    "你在「视频工具箱」的程序根目录中工作（当前工作目录即程序根）。\n"
    "- Python 运行时：tools\\python\\python.exe；引擎源码在 src\\ 下。\n"
    "- 运行期数据集中在 data\\（配置 / 下载 / 日志 / 临时产物），日志在 logs\\。\n"
    "- 你可以读写本工作区文件并执行命令来完成用户的任务；处理音视频、字幕、"
    "下载、校准等优先复用程序已有能力（src\\ 下的模块、tools\\ 下的二进制）。\n"
    "- 完成后用简体中文汇报：做了什么、关键产物路径、失败原因（如有）。\n\n"
    "【用户任务】\n"
)


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
        result["error"] = ("harness 退出码 %s。%s" % (code, tail)).strip()
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
