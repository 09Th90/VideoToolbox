# -*- coding: utf-8 -*-
# @version 2.3.1
"""校准知识/声纹模板多用户同步（GitHub 整文件通道 + 本地增量镜像）。

v2.3.1 拆分工程 · 自 video_toolbox.py 原样搬入。
含 sync_env_into（DOMAIN_MAP 原登记 shared——与同步家族物理同段，
A3-2 追认移域，同 clean_path/proxy_* 先例）。
"""

import base64
import json
import subprocess
import time
from datetime import datetime
from core.shared.paths import APP_DIR, DATA_DIR, DATA_ROOT, LOGS_DIR, TOOLS_DIR
from core.shared.log import _append_log
from core.shared.proc import popen_process, run_process
from core.shared.textio import decode_bytes_any
from core.shared.proxy import ensure_builtin_proxy
from core.calibrate.ai import calib_sync_enabled

import os

from core.shared.config import load_config
from core.shared.paths import APP_DIR, DATA_DIR, LOGS_DIR
from core.shared.runtime import _is_self_exe, system_python
from core.shared.textio import read_text_any


# ========== 校准知识同步（v1.12.2：GitHub 整文件通道收集 + 可选本地增量镜像） ==========
# 架构：
#   · 更新（界面唯一入口，启动自动 + 手动）：从内置 github_proxy.yaml 指向的
#     GitHub 仓库拉取全体使用者沉淀，条目级三方合并进本地；若管理员另配了
#     共享更新库（VT_SYNC_ROOT 下有 baseline.json），叠加本地增量镜像 kb-sync；
#   · 上传：全自动、隐藏在后台——learn 实时写本地学习库，退出程序时派生
#     隐藏子进程把「校准脚本 + 学习库」推回 GitHub（先拉后推，互不覆盖），
#     镜像启用时同时 kb-push 进收件箱；界面上不存在任何上传按钮；
#   · 折叠基线、清理更新库等管理动作全部在独立程序 kb_admin.exe。
# 连接参数统一在 github_proxy.yaml 的 vt-github 段（owner/repo/branch/api/
#   token/files），改仓库只动 yaml。
# 策略：静默、不阻塞、不弹窗，结果写 logs/calib_sync.log；失败一律降级为
#   "本地功能照常可用"，绝不因同步失败影响校准。
SYNC_LOG = os.path.join(LOGS_DIR, "calib_sync.log")
#: 用户侧同步脚本与更新库路径（打包后随包分发在程序根目录）
CALIB_SCRIPT = os.path.join(APP_DIR, "subtitle_calib_merged.py")
CALIB_KB_PATH = os.path.join(APP_DIR, "subtitle_learned_kb.json")
#: 更新库根目录（管理员维护、可指向网络盘）与本机同步状态目录
SYNC_REMOTE_DIR = os.path.join(DATA_DIR, "calib_sync_remote")
SYNC_LOCAL_DIR = os.path.join(DATA_DIR, "calib_sync")


def _sync_log(msg):
    """追加一行同步日志（best-effort，绝不因日志失败影响主流程）。

    统一走 `_append_log`：轮转 + 去重 + 级别标记（v1.16.2）。GitHub 直连
    超时这类每次启动都会重放的告警，去重后只留首次。
    """
    _append_log("calib_sync.log", msg)


def sync_env_into(env):
    """给校准/同步子进程补齐增量通道路径变量（外部显式设置优先，setdefault 语义）。

    引擎导入时对 os.environ 调用一次：此后所有子进程（校准 worker、AI 校准、
    同步子进程）自动继承，保证 learn 自动上传、退出补传、启动更新指向同一库。
    """
    env.setdefault("VT_DATA_ROOT", DATA_ROOT)
    env.setdefault("VT_SYNC_ROOT", SYNC_REMOTE_DIR)
    env.setdefault("VT_SYNC_DIR", SYNC_LOCAL_DIR)
    env.setdefault("VT_SYNC_KB", CALIB_KB_PATH)
    return env


for _d in (SYNC_REMOTE_DIR, SYNC_LOCAL_DIR):
    try:
        os.makedirs(_d, exist_ok=True)
    except OSError:
        pass
sync_env_into(os.environ)


def _calib_py():
    """跑增量通道子命令的 Python：工具箱内嵌运行时优先，其次系统 python。

    拿不到可用解释器时返回 ""（调用方据此跳过），**绝不回退到 exe 自身**——
    打包后 sys.executable 就是本程序，拿它 Popen 会拉起一个新实例。
    """
    py = system_python()
    if not py or _is_self_exe(py) or not os.path.isfile(py):
        return ""
    return py


# ---------- GitHub 整文件通道（v1.12.2 恢复：收集各使用者校准增量） ----------
# 连接参数统一来自内置 github_proxy.yaml 的 vt-github 段（owner/repo/branch/
# api/token/files）；改仓库或加同步文件只动 yaml、不动代码。上传全部自动、
# 隐藏在后台完成（退出时自动推送）；界面只保留「更新」。
# 全程静默、直连失败回退内置 mihomo 代理、任何异常只写 logs/calib_sync.log，
# 绝不影响校准主流程。
GITHUB_PROXY_YAML = os.path.join(APP_DIR, "github_proxy.yaml")
#: yaml 缺失/解析失败时的兜底默认（与内置 yaml 的 vt-github 段一致）
_SYNC_CONN_DEFAULTS = {
    "owner": "09Th90", "repo": "VideoToolbox", "branch": "main",
    "api": "https://api.github.com", "token": "",
    "files": ["subtitle_calib_merged.py", "subtitle_learned_kb.json"],
}
#: 兼容旧引用（自检/文档仍以此名访问）；实际目标文件以 yaml files 段为准
SYNC_REL_PATH = _SYNC_CONN_DEFAULTS["files"][0]
SYNC_KB_REL_PATH = _SYNC_CONN_DEFAULTS["files"][1]
#: 上次同步成功内容快照 = 条目级三方合并的「公共祖先」（放数据根，不入库不分发）
CALIB_BASE_SNAPSHOT = os.path.join(DATA_DIR, "calib_sync_base.py")
CALIB_KB_BASE_SNAPSHOT = os.path.join(DATA_DIR, "calib_sync_kb_base.json")

_SYNC_CONN_CACHE = None


def _sync_conn(refresh=False):
    """读内置 github_proxy.yaml 的 vt-github 段（模块级缓存；缺字段用默认补齐）。"""
    global _SYNC_CONN_CACHE
    if _SYNC_CONN_CACHE is not None and not refresh:
        return _SYNC_CONN_CACHE
    cfg = {k: (list(v) if isinstance(v, list) else v)
           for k, v in _SYNC_CONN_DEFAULTS.items()}
    try:
        import yaml
        with open(GITHUB_PROXY_YAML, encoding="utf-8-sig") as f:
            data = yaml.safe_load(f) or {}
        vg = data.get("vt-github") or {}
        for key in ("owner", "repo", "branch", "api", "token"):
            val = str(vg.get(key) or "").strip()
            if val:
                cfg[key] = val
        files = vg.get("files")
        if isinstance(files, list) and files:
            cfg["files"] = [str(p).strip() for p in files if str(p).strip()]
    except Exception as e:  # noqa: BLE001  解析失败退回默认，不阻断同步
        _sync_log(f"读取 github_proxy.yaml 失败，改用内置默认连接：{e}")
    if not refresh:
        _SYNC_CONN_CACHE = cfg
    return cfg


def _gh_token(cfg=None):
    """取 GitHub token：内置 yaml 显式配置 > 环境变量 > gh keyring；取不到返回空串。"""
    cfg = cfg or _sync_conn()
    tok = (cfg.get("token") or "").strip()
    if tok:
        return tok
    tok = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if tok:
        return tok.strip()
    for exe in ("gh", os.path.join(TOOLS_DIR, "gh.exe")):
        try:
            p = run_process([exe, "auth", "token"], capture_output=True,
                            text=True, timeout=15)
            if p.returncode == 0 and p.stdout.strip():
                return p.stdout.strip()
        except (OSError, subprocess.SubprocessError):
            continue
    return ""


def _gh_request(method, path, token, payload=None, proxy="", timeout=30):
    """访问 GitHub API（用 curl，避开 requests 的代理问题）。返回 (ok, 数据或错误)。"""
    url = f"{_sync_conn()['api']}/{path}"
    cmd = ["curl", "-sS", "--max-time", str(timeout), "-X", method]
    if proxy:
        cmd += ["-x", proxy]
    if token:  # 公开库匿名读时不带认证头
        cmd += ["-H", f"Authorization: Bearer {token}"]
    cmd += ["-H", "Accept: application/vnd.github+json",
            "-H", "X-GitHub-Api-Version: 2022-11-28",
            "-H", "User-Agent: VideoToolbox-sync",
            "-w", "\n%{http_code}"]
    stdin = b""
    if payload is not None:
        cmd += ["-H", "Content-Type: application/json", "--data-binary", "@-"]
        stdin = json.dumps(payload).encode("utf-8")
    cmd.append(url)
    try:
        p = run_process(cmd, input=stdin, capture_output=True,
                        timeout=timeout + 10)
    except (OSError, subprocess.SubprocessError) as e:
        return False, f"curl 调用失败: {e}"
    if p.returncode != 0:
        return False, f"curl 退出码 {p.returncode}: {decode_bytes_any(p.stderr)[:150]}"
    body, _, code = decode_bytes_any(p.stdout).rpartition("\n")
    try:
        code = int(code.strip() or 0)
    except ValueError:
        code = 0
    if code >= 400:
        return False, f"HTTP {code}: {body[:200]}"
    try:
        return True, (json.loads(body) if body.strip() else {})
    except ValueError:
        return True, {}


def _gh_request_any(method, path, token, payload=None):
    """先直连，失败再走内置代理（仅 GitHub 流量）。认证/参数类错误不重试代理。"""
    ok, data = _gh_request(method, path, token, payload)
    if ok:
        return True, data
    msg = str(data)
    if any(code in msg for code in ("HTTP 401", "HTTP 403", "HTTP 404", "HTTP 422")):
        return False, data
    _sync_log(f"直连 {method} {path} 失败（{msg[:80]}），改用内置代理")
    proxy = ensure_builtin_proxy()
    if not proxy:
        return False, f"{data}；内置代理不可用"
    return _gh_request(method, path, token, payload, proxy=proxy)


def _gh_fetch_file(token, rel_path, cfg):
    """拉仓库单文件最新内容。返回 (ok, 文本或错误, blob_sha)；公开库可匿名读。"""
    path = (f"repos/{cfg['owner']}/{cfg['repo']}/contents/{rel_path}"
            f"?ref={cfg['branch']}")
    ok, data = _gh_request_any("GET", path, token)
    if not ok:
        return False, str(data), ""
    try:
        content = data.get("content")
        if not content and data.get("git_url"):
            blob_path = str(data["git_url"]).replace(cfg["api"] + "/", "")
            ok2, blob = _gh_request_any("GET", blob_path, token)
            if not ok2:
                return False, str(blob), ""
            data, content = blob, blob.get("content")
        text = decode_bytes_any(base64.b64decode(content or ""))
        return True, text, data.get("sha", "")
    except (ValueError, KeyError, TypeError, OSError) as e:
        return False, f"解码失败: {e}", ""


def _read_sync_text(path):
    """读同步目标文件（兼容 UTF-8/GBK/无 BOM）；不存在返回空串。"""
    try:
        return read_text_any(path)
    except OSError:
        return ""


def _atomic_write(path, text):
    """原子写回同步文件：先写同目录临时文件再 os.replace，避免半截文件。"""
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    tmp = path + ".vt_tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    os.replace(tmp, path)


def _pull_and_merge(token, rel_path, base_path, cfg):
    """拉远程单文件与本地做条目级三方合并，结果回写本地与基线。返回本地是否有更新。

    files 段第一个同步文件视为「校准脚本」（走 merge_calib_script），其余视为
    「学习库」（走 merge_learned_kb）。任何失败只记日志，绝不阻断启动/退出。"""
    is_script = (rel_path == cfg["files"][0])
    local_path = os.path.join(APP_DIR, rel_path)
    local_text = _read_sync_text(local_path)
    base_text = _read_sync_text(base_path)
    ok, remote_text, _sha = _gh_fetch_file(token, rel_path, cfg)
    if not ok:
        _sync_log(f"拉取[{rel_path}]跳过合并：{str(remote_text)[:100]}")
        return False
    if not local_text.strip():
        _atomic_write(local_path, remote_text)
        _atomic_write(base_path, remote_text)
        _sync_log(f"拉取[{rel_path}]：本地缺失，已采用远程版（{len(remote_text)} 字符）")
        return True
    if remote_text == local_text:
        if base_text != local_text:
            _atomic_write(base_path, local_text)
        return False
    if is_script:
        merged, added, conflicts = merge_calib_script(local_text, remote_text, base_text)
    else:
        merged, added, conflicts = merge_learned_kb(local_text, remote_text)
    if merged == local_text:
        if conflicts:
            _sync_log(f"合并[{rel_path}]：无可并入"
                      f"（{'; '.join(str(c) for c in conflicts)[:200]}）")
        return False
    _atomic_write(local_path, merged)
    _atomic_write(base_path, merged)
    n_conf = len(conflicts) if isinstance(conflicts, list) else conflicts
    _sync_log(f"合并[{rel_path}]：并入 {added} 条，冲突 {n_conf} 条（保留本地）")
    return True


def sync_calib_to_github(cfg=None):
    """把本地校准脚本与学习库推到 GitHub（推送前先拉远程合并；静默，返回 (ok, 说明)）。"""
    cfg = cfg or _sync_conn()
    token = _gh_token(cfg)
    if not token:
        _sync_log("跳过上传：未取得 GitHub token（需 gh auth login 或设 GH_TOKEN）")
        return False, "未取得 GitHub token"
    # 先拉远程把他人增量并进来再推，多用户互不覆盖、最终收敛到并集
    for idx, rel in enumerate(cfg["files"]):
        base_path = (CALIB_BASE_SNAPSHOT if idx == 0 else CALIB_KB_BASE_SNAPSHOT)
        _pull_and_merge(token, rel, base_path, cfg)
    # 声纹模板增量：与校准文件同走一条 GitHub 通道，但目录隔离——只有这里会搬运
    # vp_inbox/，校准的 files 段永远看不到它（反之亦然）。同一份 rtree 既用于
    # 拉他人增量、也用于判断本机哪些增量还没上去，省一次递归树请求。
    rtree, n_vp_pull = {}, 0
    try:
        rtree = _gh_remote_tree(cfg, token) or {}
        n_vp_pull = _gh_pull_vp_inbox(cfg, token, rtree)
    except Exception as e:  # noqa: BLE001  声纹失败不影响校准知识上传
        _sync_log(f"声纹收件箱拉取异常（忽略）: {e}")
    entries = []  # (rel, bytes, text)
    for rel in cfg["files"]:
        try:
            with open(os.path.join(APP_DIR, rel), "rb") as f:
                b = f.read()
            entries.append((rel, b, decode_bytes_any(b)))
        except (OSError, UnicodeDecodeError) as e:
            if rel == cfg["files"][0]:
                _sync_log(f"跳过上传：读取失败 {e}")
                return False, f"读取失败: {e}"
            _sync_log(f"上传[{rel}]跳过：{e}")
    base = f"repos/{cfg['owner']}/{cfg['repo']}"
    ok, head = _gh_request_any("GET", f"{base}/git/ref/heads/{cfg['branch']}", token)
    if not ok:
        _sync_log(f"失败：读取分支 head {head}")
        return False, f"读取分支失败: {head}"
    head_sha = head["object"]["sha"]
    ok, commit = _gh_request_any("GET", f"{base}/git/commits/{head_sha}", token)
    if not ok:
        return False, f"读取 commit 失败: {commit}"
    base_tree = commit["tree"]["sha"]
    tree_entries = []
    for rel, b, _text in entries:
        ok, blob = _gh_request_any("POST", f"{base}/git/blobs", token, {
            "content": base64.b64encode(b).decode("ascii"), "encoding": "base64"})
        if not ok:
            return False, f"创建 blob 失败: {blob}"
        tree_entries.append({"path": rel, "mode": "100644",
                             "type": "blob", "sha": blob["sha"]})
    # 声纹增量：远端没有的本机文件才上传（文件名含 cid+时间戳+随机 hex，撞名即同一次推送）
    vp_entries, n_vp_push = [], 0
    try:
        vp_entries, n_vp_push = _gh_push_vp_inbox(cfg, token, rtree)
    except Exception as e:  # noqa: BLE001  声纹失败不影响校准知识上传
        _sync_log(f"声纹增量上传异常（忽略）: {e}")
    tree_entries.extend(vp_entries)
    if not tree_entries:
        _sync_log("跳过上传：无内容可提交")
        return True, "无变更"
    ok, tree = _gh_request_any("POST", f"{base}/git/trees", token, {
        "base_tree": base_tree, "tree": tree_entries})
    if not ok:
        return False, f"创建 tree 失败: {tree}"
    ok, new_commit = _gh_request_any("POST", f"{base}/git/commits", token, {
        "message": (f"chore(calib): 同步校准知识{'与声纹模板' if n_vp_push else ''} "
                    f"（{datetime.now():%Y-%m-%d %H:%M:%S}，来自视频工具箱）"),
        "tree": tree["sha"], "parents": [head_sha]})
    if not ok:
        return False, f"创建 commit 失败: {new_commit}"
    ok, res = _gh_request_any("PATCH", f"{base}/git/refs/heads/{cfg['branch']}",
                              token, {"sha": new_commit["sha"], "force": False})
    if not ok:
        return False, f"更新分支失败: {res}"
    _sync_log(f"成功：已上传 {len(entries)} 个文件"
              f"（另声纹模板 +{n_vp_push} / 拉取 {n_vp_pull}）-> "
              f"{cfg['owner']}/{cfg['repo']}@{cfg['branch']} "
              f"commit {new_commit['sha'][:12]}")
    # 推送成功：基线快照对齐本次内容（下次三方合并的公共祖先）
    for idx, (rel, _b, text) in enumerate(entries):
        try:
            _atomic_write(CALIB_BASE_SNAPSHOT if idx == 0
                          else CALIB_KB_BASE_SNAPSHOT, text)
        except OSError as e:
            _sync_log(f"基线快照写入失败[{rel}]（忽略）: {e}")
    return True, f"已上传 commit {new_commit['sha'][:12]}"


# ---------- 本地增量镜像（可选：管理员配了共享盘更新库才启用） ----------
def _local_delta_enabled():
    """VT_SYNC_ROOT 下存在 baseline.json 才启用 kb-sync/kb-push 增量镜像。"""
    try:
        root = os.environ.get("VT_SYNC_ROOT") or SYNC_REMOTE_DIR
        return os.path.isfile(os.path.join(root, "baseline.json"))
    except OSError:
        return False


def sync_calib_push_local():
    """退出子进程内部调用：把学习库新增增量写进本地更新库收件箱（若启用镜像）。"""
    try:
        if not _local_delta_enabled():
            return
        py = _calib_py()
        if not py or not os.path.isfile(CALIB_SCRIPT):
            return
        env = sync_env_into(os.environ.copy())
        env.setdefault("PYTHONIOENCODING", "utf-8")
        run_process([py, CALIB_SCRIPT, "kb-push", "--learned", CALIB_KB_PATH],
                    capture_output=True, text=True, encoding="utf-8",
                    errors="replace", timeout=120, cwd=APP_DIR, env=env)
    except Exception as e:  # noqa: BLE001
        _sync_log(f"本地增量上传异常（忽略）: {e}")


def _exit_sync_child_script():
    """退出子进程入口源码：本地增量补传（若启用镜像）+ GitHub 整文件上传。"""
    src_dir = os.path.join(APP_DIR, "src")
    # ⚠ 顺序要紧：先把待传声纹冲进本地 vp_inbox（纯本地、秒级），再跑 GitHub
    #   上传——否则本次录入的模板要等下一次退出才进得了仓库。
    return ("import sys; sys.path.insert(0, r'%s');"
            "import video_toolbox as e;"
            "e.sync_voiceprint_on_exit();"
            "e.sync_calib_push_local();"
            "e.sync_calib_to_github()" % src_dir)


def sync_calib_on_startup(force=False):
    """更新：从 GitHub 拉全体使用者沉淀并条目级合并进本地；可选叠加本地增量镜像。

    幂等、静默、best-effort；任何失败只写日志，本地校准功能照常可用。
    force 为兼容设置页「立即更新」参数，可忽略。"""
    try:
        if os.environ.get("VT_NO_CALIB_SYNC") or not calib_sync_enabled():
            return False, "同步已禁用"
        updated, notes = False, []
        # 1) GitHub 整文件通道（默认收集渠道；公开库可匿名读）
        cfg = _sync_conn()
        token = _gh_token(cfg)
        for idx, rel in enumerate(cfg["files"]):
            base_path = (CALIB_BASE_SNAPSHOT if idx == 0 else CALIB_KB_BASE_SNAPSHOT)
            if _pull_and_merge(token, rel, base_path, cfg):
                updated = True
                notes.append(rel)
        # 2) 本地增量镜像（管理员配置了共享盘更新库时）
        py = _calib_py()
        if py and os.path.isfile(CALIB_SCRIPT) and _local_delta_enabled():
            env = sync_env_into(os.environ.copy())
            env.setdefault("PYTHONIOENCODING", "utf-8")
            try:
                p = run_process([py, CALIB_SCRIPT, "kb-sync"],
                                capture_output=True, text=True, encoding="utf-8",
                                errors="replace", timeout=180, cwd=APP_DIR, env=env)
                if p.returncode == 0:
                    updated = True
                    notes.append("本地增量")
                else:
                    _sync_log(f"本地增量更新失败（降级）：rc={p.returncode}")
            except Exception as e:  # noqa: BLE001
                _sync_log(f"本地增量更新异常（忽略）: {e}")
        if updated:
            _sync_log("更新完成：" + "、".join(notes))
            return True, "校准知识已更新（" + "、".join(notes) + "）"
        return False, "无可用更新或已是最新"
    except Exception as e:  # noqa: BLE001
        _sync_log(f"更新异常（忽略）: {e}")
        return False, str(e)


def sync_calib_on_exit():
    """退出时自动上传：派生隐藏子进程完成「本地增量补传 + GitHub 整文件上传」。

    用子进程而非线程：主进程退出后线程会被强杀，子进程能自行跑完。
    上传对用户完全无感——不阻塞退出、不弹窗、不出现在任何界面。"""
    try:
        if os.environ.get("VT_NO_CALIB_SYNC") or not calib_sync_enabled():
            return
        py = _calib_py()
        if not py:
            _sync_log("退出上传跳过：无可用 Python 运行时")
            return
        env = sync_env_into(os.environ.copy())
        env.setdefault("PYTHONIOENCODING", "utf-8")
        popen_process([py, "-c", _exit_sync_child_script()],
                      stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                      stderr=subprocess.DEVNULL, cwd=APP_DIR, env=env,
                      close_fds=True)
        _sync_log("已派生退出上传子进程（GitHub 整文件 + 本地增量）")
    except Exception as e:  # noqa: BLE001
        _sync_log(f"派生退出上传子进程失败（忽略）: {e}")


# ---------- 声纹模板同步（独立通道；与上面的校准知识同步互不干涉） ----------
# 数据形态、生命周期与责任边界都不同（192 维向量 / 重录与删除是常态 / 无基线
# 概念），故自成一套：schema、确定性合并、落地裁决、待传队列、状态目录与 CLI
# 全在 src\voiceprint_sync.py，只共用哑存储根的 vp_inbox\ 子目录作传输
# （校准通道只枚举 inbox\，两边永远看不到对方的条目）。
# 用户侧开关沿用同一个「校准同步」设置项（避免设置页多一个语义重叠的开关），
# 另有独立环境变量 VT_NO_VP_SYNC 可单独关停声纹通道。
VP_SYNC_LOG = os.path.join(LOGS_DIR, "vp_sync.log")
#: 声纹增量在仓库里的子目录（与 voiceprint_sync.INBOX_SUB 同名，挂在哑存储根下）
VP_INBOX_SUB = "vp_inbox"
#: 单次同步最多搬运的声纹增量文件数（防目录异常膨胀把启动/退出拖成网络风暴）
VP_INBOX_MAX_FILES = 200


def _vp_inbox_local_files():
    """本机哑存储根下的声纹增量 -> [(仓库相对路径, 绝对路径)]（按路径排序，确定性）。"""
    base = os.path.join(SYNC_REMOTE_DIR, VP_INBOX_SUB)
    out = []
    if not os.path.isdir(base):
        return out
    for cid in sorted(os.listdir(base)):
        d = os.path.join(base, cid)
        if not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            p = os.path.join(d, fn)
            if fn.endswith(".jsonl") and os.path.isfile(p):
                out.append(("%s/%s/%s" % (VP_INBOX_SUB, cid, fn), p))
    return out


def _gh_remote_tree(cfg, token):
    """拉远端分支整树 -> {path: blob_sha}（只收 blob）；失败返回 None。

    ⚠ `?recursive=1` 是必须的：不带它只能拿到第一层目录，vp_inbox/<cid>/ 下的
    文件一个都看不到，声纹就永远同步不到。"""
    base = "repos/%s/%s" % (cfg["owner"], cfg["repo"])
    ok, ref = _gh_request_any("GET", "%s/git/ref/heads/%s" % (base, cfg["branch"]),
                              token)
    if not ok:
        return None
    ok, commit = _gh_request_any(
        "GET", "%s/git/commits/%s" % (base, (ref or {}).get("object", {}).get("sha", "")),
        token)
    if not ok:
        return None
    ok, tree = _gh_request_any(
        "GET", "%s/git/trees/%s?recursive=1"
        % (base, (commit or {}).get("tree", {}).get("sha", "")), token)
    if not ok:
        return None
    return {t.get("path"): (t.get("sha") or "")
            for t in ((tree or {}).get("tree") or [])
            if t.get("type") == "blob" and t.get("path")}


def _gh_pull_vp_inbox(cfg, token, tree=None):
    """把远端收件箱里本机没有的声纹增量拉进哑存储根。返回拉取文件数。

    「只新建、绝不改写」与 voiceprint_sync 的收件箱语义一致：文件名带
    client_id + UTC 时间戳 + 随机 hex，同名必然是同一次推送、内容相同。
    写盘用临时文件 + os.replace，避免拉到一半被中断留下半截文件。
    任何失败只记日志——没有声纹增量不影响校准知识同步。"""
    if tree is None:
        tree = _gh_remote_tree(cfg, token)
    if not tree:
        return 0
    want = [(p, s) for p, s in sorted(tree.items())
            if p.startswith(VP_INBOX_SUB + "/") and p.endswith(".jsonl")]
    if not want:
        return 0
    base = "repos/%s/%s" % (cfg["owner"], cfg["repo"])
    n = 0
    for rel, sha in want[:VP_INBOX_MAX_FILES]:
        dst = os.path.join(SYNC_REMOTE_DIR, rel.replace("/", os.sep))
        if os.path.isfile(dst) or not sha:
            continue
        ok, blob = _gh_request_any("GET", "%s/git/blobs/%s" % (base, sha), token)
        if not ok:
            continue
        try:
            raw = base64.b64decode((blob or {}).get("content") or "")
        except (ValueError, TypeError):
            continue
        if not raw.strip():
            continue
        try:
            # ⚠ 必须按**字节**落盘：文本模式下 Windows 会把远端文件里已有的
            #   \r\n 再转成 \r\r\n（实测往返内容不一致的根因）。原样写才能
            #   保证多客户端间逐字节一致。
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            tmp = dst + ".vt_tmp"
            with open(tmp, "wb") as f:
                f.write(raw)
            os.replace(tmp, dst)
            n += 1
        except OSError:
            continue
    if n:
        _sync_log("声纹收件箱：拉取 %d 个增量文件" % n)
    return n


def _gh_push_vp_inbox(cfg, token, tree):
    """把本机新增的声纹增量做成 tree 条目。返回 (条目列表, 上传数)。

    远端已有的跳过——文件名含 client_id + 时间戳 + 随机 hex，撞名即同一次
    推送，内容必然相同；这样每次退出只为真正的新增量付 API 调用。"""
    if not tree:
        return [], 0
    base = "repos/%s/%s" % (cfg["owner"], cfg["repo"])
    out, n = [], 0
    for rel, abs_p in _vp_inbox_local_files():
        if rel in tree:
            continue
        if len(out) >= VP_INBOX_MAX_FILES:
            break
        try:
            with open(abs_p, "rb") as f:
                b = f.read()
        except OSError:
            continue
        if not b.strip():
            continue
        ok, blob = _gh_request_any("POST", "%s/git/blobs" % base, token, {
            "content": base64.b64encode(b).decode("ascii"), "encoding": "base64"})
        if not ok:
            _sync_log("声纹增量上传跳过[%s]：%s" % (rel, str(blob)[:80]))
            continue
        out.append({"path": rel, "mode": "100644", "type": "blob",
                    "sha": blob["sha"]})
        n += 1
    return out, n


def _vp_sync_log(msg):
    try:
        os.makedirs(LOGS_DIR, exist_ok=True)
        with open(VP_SYNC_LOG, "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")
    except OSError:
        pass


def sync_voiceprint_on_startup(force=False):
    """启动：把其他客户端录入的主播声纹模板拉下来落地（幂等、静默、best-effort）。

    与 `sync_calib_on_startup` 各自独立：不共用子进程、不共用日志、失败互不影响。
    返回 (是否更新, 说明) 以兼容设置页「立即更新」的回调口径。"""
    try:
        if os.environ.get("VT_NO_CALIB_SYNC") or not calib_sync_enabled():
            return False, "同步已禁用"
        # 先把远端收件箱搬进本地哑存储根，再让 voiceprint_sync 合并落地。
        # ⚠ vp_inbox/ 不在 cfg["files"] 里，校准通道不会替我们搬——少了这一步，
        #   声纹就只在本机打转（v1.19.0 的「声纹库没共享」就是漏了它）。
        try:
            _cfg = _sync_conn()
            _gh_pull_vp_inbox(_cfg, _gh_token(_cfg))
        except Exception as _e:  # noqa: BLE001
            _vp_sync_log(f"声纹收件箱拉取异常（忽略）: {_e}")
        import voiceprint_sync as _vps
        if not _vps.enabled():
            return False, "声纹同步已单独禁用（VT_NO_VP_SYNC）"
        # ⚠⚠ 在「拉取收件箱」之后、「合并落地」之前，把**待传队列冲刷一遍**
        #   （2026-10-13 补）：
        #   退出推送只挂在 QApplication.aboutToQuit 上，进程被强杀 / 崩溃 /
        #   taskkill 时它根本不触发——实测安装版 08:43、08:50 录入的两个声纹
        #   就因此一直卡在 data/vp_sync/voiceprint_pending.jsonl（vp_sync.log
        #   停在 07:33，其后只有校准的退出上传记录，没有任何「退出推送」行；
        #   同一时刻残留的孤儿 mihomo.exe 亦印证是异常终止）。
        #   启动时补一次，队列即自愈：强杀只影响「本次到上次启动之间」的增量，
        #   且下一次启动必补上。push 只写本地哑存储根，不联网、不阻塞启动。
        try:
            _n_pushed = _vps.push(quiet=True)
            if _n_pushed:
                _vp_sync_log(f"启动补推 %d 条声纹增量（上次未正常退出遗留）"
                             % _n_pushed)
        except Exception as _e:  # noqa: BLE001
            _vp_sync_log(f"启动补推异常（忽略）: {_e}")
        ok = _vps.sync(quiet=True)
        s = _vps.status()
        _vp_sync_log(f"启动同步{'完成' if ok else '跳过（无远端/未启用）'}："
                     f"模板 {s['templates']}（同步副本 {s['synced']}）、"
                     f"待传 {s['pending']}、冲突 {s['conflicts']}")
        return ok, ("声纹模板已同步" if ok else "无声纹更新")
    except Exception as e:  # noqa: BLE001
        _vp_sync_log(f"启动同步异常（忽略）: {e}")
        return False, str(e)


def sync_voiceprint_on_exit():
    """退出：把本机录入/重录/删除产生的声纹增量推进通道。

    直接在本进程做（纯标准库、只有本地文件写，通常几条），**不派生子进程**——
    与校准退出上传（要跑 GitHub 网络请求，故用子进程）不同。失败只写日志，
    绝不阻塞退出。"""
    try:
        if os.environ.get("VT_NO_CALIB_SYNC") or not calib_sync_enabled():
            return
        import voiceprint_sync as _vps
        if not _vps.enabled():
            return
        n = _vps.push(quiet=True)
        if n:
            _vp_sync_log(f"退出推送 {n} 条声纹增量")
    except Exception as e:  # noqa: BLE001
        _vp_sync_log(f"退出推送异常（忽略）: {e}")


# ---------- 条目级三方合并（v1.10.8：纯函数核心抽到 calib_merge_core） ----------
# 多用户知识收敛的合并算法是纯函数、零副作用，统一放在 calib_merge_core，
# 便于 GUI 引擎、退出同步子进程与脚本/CI 复用；这里只做导入并保留向后兼容
# 别名（自检与外部仍以 engine.merge_* 调用），并把合并期日志接到同步日志。
#
# 同步语义保持 v1.10.7 的对等并集模型（用户最终拍板，不采用 contrib/CI
# 中心化方案）：启动自动拉取 GitHub main 最新校准知识并把其他用户沉淀的
# 新条目并入本地；退出时先把远程新内容并进来再推送，多用户互不覆盖，
# 所有人的脚本最终收敛到全体条目的并集。
from calib_merge_core import (
    _MERGE_MISSING,
    _ast_module_tables,
    _dict_entries,
    _entity_fields,
    _registry_conflicts,
    merge_calib_script,
    merge_learned_kb,
)
import calib_merge_core as _calib_core
_calib_core._log = _sync_log  # 合并期冲突日志写入 logs/calib_sync.log

__all__ = [
    "sync_env_into",
    "sync_calib_to_github",
    "sync_calib_push_local",
    "sync_calib_on_startup",
    "sync_calib_on_exit",
    "sync_voiceprint_on_startup",
    "sync_voiceprint_on_exit",
    "SYNC_LOG",
    "CALIB_SCRIPT",
    "CALIB_KB_PATH",
    "VP_SYNC_LOG",
    "VP_INBOX_SUB",
    "VP_INBOX_MAX_FILES",
    "GITHUB_PROXY_YAML",
    "_SYNC_CONN_DEFAULTS",
    "SYNC_REL_PATH",
    "SYNC_KB_REL_PATH",
    "CALIB_BASE_SNAPSHOT",
    "CALIB_KB_BASE_SNAPSHOT",
    "_sync_log",
    "_sync_conn",
    "_gh_token",
    "_gh_request",
    "_gh_request_any",
    "_gh_fetch_file",
    "_read_sync_text",
    "_atomic_write",
    "_pull_and_merge",
    "_local_delta_enabled",
    "_exit_sync_child_script",
    "_gh_remote_tree",
    "_vp_sync_log",
    "_calib_py",
    "_vp_inbox_local_files",
    "_gh_pull_vp_inbox",
    "_gh_push_vp_inbox",
    "SYNC_REMOTE_DIR",
    "SYNC_LOCAL_DIR",
    "merge_calib_script",
    "merge_learned_kb",
    "_MERGE_MISSING",
    "_ast_module_tables",
    "_dict_entries",
    "_entity_fields",
    "_registry_conflicts",
    "_SYNC_CONN_CACHE",
]
