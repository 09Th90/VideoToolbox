# -*- coding: utf-8 -*-
# @version 1.15.3
"""把 installer_repository/ 部署到 09Th90/VideoToolbox 的 gh-pages 分支并启用 GitHub Pages。

走 GitHub Git Data API：token 取自 gh keyring（gh auth token），用 curl 直连
api.github.com。规避两个问题：git 协议在此网络下不可达；gh CLI 在子进程中偶发
401 认证异常。gh-pages 分支只包含安装器仓库内容，不污染 main。
"""
import base64
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

OWNER, REPO = "09Th90", "VideoToolbox"
BRANCH = "gh-pages"
# 仓库目录可通过 VT_REPO_DIR 覆盖（脚本被复制到其它位置运行时用）
_BASE = Path(os.environ.get("VT_REPO_DIR", Path(__file__).resolve().parent))
REPO_DIR = Path(_BASE) / "installer_repository"
API = f"repos/{OWNER}/{REPO}"
API_BASE = "https://api.github.com"

TOKEN = subprocess.run(["gh", "auth", "token"], capture_output=True,
                       text=True).stdout.strip()
if not TOKEN:
    sys.exit("无法从 gh keyring 获取 token，请先 gh auth login")

# 本机网络对 api.github.com 的写入请求存在间歇性中间层拦截（偶发 401）。
# 程序内置了 mihomo 代理（海外出口）作为回退通道，可绕开本机设备检测。
#
# ⚠️ 默认**不**启动它：实测代理通道对 api.github.com 写入完全不可用
# （curl 走代理 600s 收 0 字节），而且一旦拉起 mihomo 反而会让直连通道
# 出现 401/422/504 抖动。确需时显式设 VT_DEPLOY_PROXY=1。
PROXY = ""
if os.environ.get("VT_DEPLOY_PROXY") == "1":
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
        import video_toolbox as _vt
        PROXY = _vt.ensure_builtin_proxy() or ""
    except Exception:
        PROXY = ""

#: 强制直连的 urllib 通道：curl 在本机对 api.github.com 的**写**请求会被中间层
#: 拦成 401 "Bad credentials"（同一 token 走 urllib 却正常），因此 urllib 是首选。
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _api_urllib(method, path, payload=None):
    url = f"{API_BASE}/{API}/{path}"
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "VideoToolbox-deploy",
        "Content-Type": "application/json",
    })
    with _OPENER.open(req, timeout=900) as r:
        body = r.read().decode(errors="replace")
    return json.loads(body) if body.strip() else {}


def _curl(method, path, payload, proxy=""):
    # --max-time 放宽到 60 分钟：92MB 级组件 blob 走国内直连上传可能需要几十分钟，
    # 旧值 600s 会在传完之前就被掐断（实测报 "0 bytes received" 超时）。
    cmd = ["curl", "-sS", "--max-time", "3600", "-X", method]
    if proxy:
        cmd += ["-x", proxy]
    else:
        # 直连必须 --noproxy：本机/沙箱若设了 http_proxy，curl 会悄悄走代理，
        # Authorization 头被中间层破坏 → 直连反而回 401 "Bad credentials"（实测）。
        cmd += ["--noproxy", "*"]
    cmd += ["-H", f"Authorization: Bearer {TOKEN}",
            "-H", "Accept: application/vnd.github+json",
            "-H", "X-GitHub-Api-Version: 2022-11-28",
            "-H", "User-Agent: VideoToolbox-deploy",
            "-w", "\n%{http_code}"]
    stdin = b""
    if payload is not None:
        cmd += ["-H", "Content-Type: application/json", "--data-binary", "@-"]
        stdin = json.dumps(payload).encode()
    cmd.append(f"{API_BASE}/{API}/{path}")
    return subprocess.run(cmd, input=stdin, capture_output=True, timeout=3700)


def api(method, path, payload=None):
    """访问 GitHub API。

    通道优先级：urllib 强制直连（实测唯一稳定）→ curl 直连 → 内置代理。
    curl 在本机对写请求存在中间层 401 拦截，故只作备选；curl 的代理通道
    在国内速率下对 92MB 级 blob 也会超时，因此把 urllib 放前面。
    """
    last = None
    for attempt in range(1, 5):
        try:
            return _api_urllib(method, path, payload)
        except Exception as e:  # noqa: BLE001
            last = str(e)
            wait = min(2 ** attempt * 2, 20)
            print(f"  {method} {path} urllib直连失败（{last[:70]}），"
                  f"{wait}s 后重试 {attempt}/4 ...")
            time.sleep(wait)

    channels = [("curl直连", "")]
    if PROXY:
        channels.append(("内置代理", PROXY))
    for label, proxy in channels:
        for attempt in range(1, 3):
            try:
                p = _curl(method, path, payload, proxy)
                if p.returncode != 0:
                    raise RuntimeError(p.stderr.decode(errors="replace")[:150])
                body, _, code = p.stdout.decode(errors="replace").rpartition("\n")
                code = int(code.strip() or 0)
                if code < 400:
                    return json.loads(body) if body.strip() else {}
                last = f"{label} HTTP {code}: {body[:150]}"
            except Exception as e:  # noqa: BLE001
                last = f"{label}: {e}"
            wait = min(2 ** attempt * 2, 20)
            print(f"  {method} {path} {label}失败（{str(last)[:60]}），"
                  f"{wait}s 后重试 {attempt}/2 ...")
            time.sleep(wait)
    sys.exit(f"{method} {path} FAILED: {last}")


def main():
    head = api("GET", "git/ref/heads/main")
    parent_sha = head["object"]["sha"]
    print("main head:", parent_sha)

    # 检查 / 创建 gh-pages 分支
    exists = api("GET", f"git/ref/heads/{BRANCH}")
    if not exists:
        api("POST", "git/refs", {"ref": f"refs/heads/{BRANCH}", "sha": parent_sha})
        print(f"created branch {BRANCH} at {parent_sha}")
    else:
        print(f"branch {BRANCH} already exists")

    # 上传所有文件为 blob
    files = sorted(p for p in REPO_DIR.rglob("*") if p.is_file())
    if not files:
        sys.exit("installer_repository 为空")
    tree = []
    for i, f in enumerate(files, 1):
        rel = f.relative_to(REPO_DIR).as_posix()
        data = f.read_bytes()
        blob = api("POST", "git/blobs", {
            "content": base64.b64encode(data).decode("ascii"),
            "encoding": "base64",
        })
        tree.append({"path": rel, "mode": "100644", "type": "blob", "sha": blob["sha"]})
        print(f"  [{i}/{len(files)}] {rel} ({len(data)} B)")

    new_tree = api("POST", "git/trees", {"tree": tree})
    print("tree:", new_tree["sha"])

    commit = api("POST", "git/commits", {
        "message": "deploy: video toolbox installer repository (GitHub Pages)",
        "tree": new_tree["sha"],
        "parents": [parent_sha],
    })
    print("commit:", commit["sha"])

    api("PATCH", f"git/refs/heads/{BRANCH}", {"sha": commit["sha"], "force": True})
    print(f"DONE: {OWNER}/{REPO}@{BRANCH} updated")

    api("PUT", "pages", {"source": {"branch": BRANCH, "path": "/"}})
    print("Pages enabled: https://09th90.github.io/VideoToolbox/")


if __name__ == "__main__":
    main()
