# -*- coding: utf-8 -*-
# @version 1.19.0
"""把 installer_repository/ 部署到 09Th90/VideoToolbox 的 gh-pages 分支并启用 GitHub Pages。

⚠⚠ 两种模式，**默认 git**（2026-10-08 起）：
  · `--mode git`（默认，推荐）：把 installer_repository/ 镜像到
    build/ghpages_push/，再作为**独立 git 仓库** `git push --force` 到 gh-pages，
    **内容位于分支根**（即 https://09th90.github.io/VideoToolbox/Updates.xml）。
    只有这条路推得动 100 MiB 级大归档——走 pack 协议，只要**单文件** ≤100 MiB 即可。
  · `--mode api`：走 GitHub Git Data API 逐个上传 blob。**对当前体积已不可用**：
    content.7z 已 98 MiB，base64 后单请求 >130MB，GitHub 直接 422 "input too large"
    （git/blobs 有体积上限）。保留仅为小体积仓库与历史参考。

⚠⚠ gh-pages 的**目录层级必须与安装器内嵌 URL 对齐**（2026-10-08 事故根因）：
  安装器 config.xml 写的是 `https://09th90.github.io/VideoToolbox/`，IFW 会在其后拼
  `Updates.xml`。所以仓库内容**必须放在 gh-pages 分支根**。
  历史上曾把整个 `installer_repository/` 目录（连目录名）推上去，实际路径就成了
  `.../VideoToolbox/installer_repository/Updates.xml`，而安装器去取
  `.../VideoToolbox/Updates.xml` 得 **404** ⇒ 向导 Welcome 页红字
  `Cannot retrieve remote tree`。**别把仓库目录名带进 gh-pages。**

⚠⚠ GitHub 单文件硬限 **100 MiB**（104,857,600 字节），超了 push 会被服务端拒绝。
  主程序 exe 是 PyInstaller onefile（内部已压缩）⇒ 7z 只能再压 0.06%，
  故 `content.7z` ≈ exe 体积。exe 一逼近 100 MiB 就会越线——v1.18.0 是靠剔掉
  8.2MB 无人引用的 Qt5Qml/Qt5Quick 才压回 98.24 MiB，**余量仅 1.76 MiB**。
  发布前务必先跑 `--check-size`。真要治本得改挂 GitHub Releases（单 asset 2GB）。

用法：
    python packaging/deploy_installer_ghpages.py --check-size   # 只量体积，不发布
    python packaging/deploy_installer_ghpages.py                # git 模式发布
    python packaging/deploy_installer_ghpages.py --dry-run      # 只镜像不推
    python packaging/deploy_installer_ghpages.py --mode api     # 旧通道（大文件会 422）
"""
import argparse
import base64
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

OWNER, REPO = "09Th90", "VideoToolbox"
BRANCH = "gh-pages"
# 仓库目录可通过 VT_REPO_DIR 覆盖（脚本被复制到其它位置运行时用）
_BASE = Path(os.environ.get("VT_REPO_DIR", Path(__file__).resolve().parent.parent))
REPO_DIR = Path(_BASE) / "installer_repository"
#: git 模式的发布暂存目录（独立 git 仓库；已被 .gitignore 忽略）
PUSH_DIR = _BASE / "build" / "ghpages_push"
REMOTE_URL = f"https://github.com/{OWNER}/{REPO}"
#: GitHub 单文件硬限
GIT_FILE_LIMIT = 100 * 1024 * 1024
API = f"repos/{OWNER}/{REPO}"
API_BASE = "https://api.github.com"

#: ⚠ token 改为**惰性获取**（2026-10-08）：原先在模块顶层就 `gh auth token`，
#:   取不到直接 sys.exit —— 于是 `--check-size` / `--mode git` 这些**根本不需要
#:   token** 的路径也被一起挡死。现在只在走 API 通道时才去取。
TOKEN = ""


def _ensure_token():
    global TOKEN
    if not TOKEN:
        TOKEN = subprocess.run(["gh", "auth", "token"], capture_output=True,
                               text=True).stdout.strip()
        if not TOKEN:
            sys.exit("无法从 gh keyring 获取 token，请先 gh auth login")
    return TOKEN

# 本机网络对 api.github.com 的写入请求存在间歇性中间层拦截（偶发 401）。
# 程序内置了 mihomo 代理（海外出口）作为回退通道，可绕开本机设备检测。
#
# ⚠️ 默认**不**启动它：实测代理通道对 api.github.com 写入完全不可用
# （curl 走代理 600s 收 0 字节），而且一旦拉起 mihomo 反而会让直连通道
# 出现 401/422/504 抖动。确需时显式设 VT_DEPLOY_PROXY=1。
PROXY = ""
if os.environ.get("VT_DEPLOY_PROXY") == "1":
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
        import video_toolbox as _vt
        PROXY = _vt.ensure_builtin_proxy() or ""
    except Exception:
        PROXY = ""

#: 强制直连的 urllib 通道：curl 在本机对 api.github.com 的**写**请求会被中间层
#: 拦成 401 "Bad credentials"（同一 token 走 urllib 却正常），因此 urllib 是首选。
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _api_urllib(method, path, payload=None):
    _ensure_token()
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


def api(method, path, payload=None, allow_missing=False):
    """访问 GitHub API。

    通道优先级：urllib 强制直连（实测唯一稳定）→ curl 直连 → 内置代理。
    curl 在本机对写请求存在中间层 401 拦截，故只作备选；curl 的代理通道
    在国内速率下对 92MB 级 blob 也会超时，因此把 urllib 放前面。

    allow_missing=True（v1.16.5 新增）：目标不存在（HTTP 404）时返回 None
    而不 sys.exit。此前首次部署时 gh-pages 分支尚不存在，api() 直接退出，
    于是 main() 里「if not exists: 创建分支」这一支**永不执行**，首次部署
    必然失败。
    """
    last = None
    for attempt in range(1, 5):
        try:
            return _api_urllib(method, path, payload)
        except Exception as e:  # noqa: BLE001
            last = str(e)
            if allow_missing and "404" in last:
                return None
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
                if allow_missing and code == 404:
                    return None
            except Exception as e:  # noqa: BLE001
                last = f"{label}: {e}"
            wait = min(2 ** attempt * 2, 20)
            print(f"  {method} {path} {label}失败（{str(last)[:60]}），"
                  f"{wait}s 后重试 {attempt}/2 ...")
            time.sleep(wait)
    if allow_missing:
        return None
    sys.exit(f"{method} {path} FAILED: {last}")


def main_api():
    head = api("GET", "git/ref/heads/main")
    parent_sha = head["object"]["sha"]
    print("main head:", parent_sha)

    # 检查 / 创建 gh-pages 分支
    # v1.16.5：首次部署时分支不存在，必须 allow_missing 拿到 None 才会走创建支
    exists = api("GET", f"git/ref/heads/{BRANCH}", allow_missing=True)
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


# ---------------------------------------------------------------- git 通道


def check_size():
    """量一遍待发布文件的体积，超 GitHub 100 MiB 硬限就报错退出。返回 0/2。"""
    if not REPO_DIR.is_dir():
        sys.exit(f"仓库目录不存在：{REPO_DIR}（先跑 build_online_installer.py）")
    rows = []
    for r, _d, fs in os.walk(REPO_DIR):
        for f in fs:
            p = Path(r) / f
            rows.append((p.stat().st_size, p.relative_to(REPO_DIR).as_posix()))
    if not rows:
        sys.exit("installer_repository 为空")
    rows.sort(reverse=True)
    total = sum(s for s, _ in rows)
    print(f"仓库：{len(rows)} 个文件，合计 {total} 字节（{total / 1048576:.1f} MiB）")
    for s, name in rows[:5]:
        print("   %11d  %-48s %7.2f MiB" % (s, name, s / 1048576))
    over = [(s, n) for s, n in rows if s > GIT_FILE_LIMIT]
    if over:
        print()
        for s, n in over:
            print("   ✗ 超 GitHub 单文件 100 MiB 硬限：%s（%.2f MiB）"
                  % (n, s / 1048576))
        print("   ⇒ git push 会被服务端拒绝。要么给 exe 瘦身，要么改挂 GitHub Releases。")
        return 2
    slack = GIT_FILE_LIMIT - rows[0][0]
    print("   ✓ 最大单文件 %.2f MiB，距硬限余量 %.2f MiB"
          % (rows[0][0] / 1048576, slack / 1048576))
    if slack < 2 * 1024 * 1024:
        print("   ⚠ 余量不足 2 MiB：exe 再涨一点就会越线，建议尽快改挂 GitHub Releases。")
    return 0


def deploy_via_git(dry_run=False):
    """镜像 installer_repository/ 到 PUSH_DIR，再作为独立 git 仓库推到 gh-pages。

    ⚠ 内容是镜像到 PUSH_DIR 的**根**（不是 PUSH_DIR/installer_repository），
      这样 gh-pages 根下直接就是 Updates.xml —— 与安装器内嵌 URL 对齐。
    """
    rc = check_size()
    if rc:
        return rc
    if PUSH_DIR.exists():
        for name in os.listdir(PUSH_DIR):
            p = PUSH_DIR / name
            if p.is_dir():
                shutil.rmtree(p, ignore_errors=True)
            else:
                p.unlink()
    else:
        PUSH_DIR.mkdir(parents=True)

    n = 0
    for r, _d, fs in os.walk(REPO_DIR):
        rel = os.path.relpath(r, REPO_DIR)
        out = PUSH_DIR if rel == "." else PUSH_DIR / rel
        out.mkdir(parents=True, exist_ok=True)
        for f in fs:
            src, dst = Path(r) / f, out / f
            if not dst.exists() or not filecmp.cmp(src, dst, shallow=False):
                shutil.copy2(src, dst)
            n += 1
    print(f"已镜像 {n} 个文件到 {PUSH_DIR}（gh-pages 根）")
    if dry_run:
        print("（--dry-run，未提交、未推送）")
        return 0

    def git(*args, check=True):
        r = subprocess.run(["git", "-c", "core.quotepath=false", *args],
                           cwd=str(PUSH_DIR), capture_output=True)
        out = (r.stdout or b"").decode("utf-8", "replace")
        err = (r.stderr or b"").decode("utf-8", "replace")
        if check and r.returncode != 0:
            print(f"!! git {' '.join(args)} 失败 rc={r.returncode}\n{err[:2000]}")
            sys.exit(1)
        return out + err

    if not (PUSH_DIR / ".git").is_dir():
        print(git("init", "-q"))
        git("remote", "add", "origin", REMOTE_URL, check=False)

    # ⚠⚠ 2026-10-09 补：暂存仓库必须**自带身份**，否则 `git commit` 报
    #   "Author identity unknown" 直接 rc=128 中断整个发布。
    # 起因：本机只在**主仓库**配了 user.name/email（仓库级 config），而
    # build/ghpages_push 是独立仓库，既读不到仓库级、也没有 --global ——
    # 于是「本地一切正常，一部署就挂」。取值优先级：主仓库 config →
    # 环境变量 → 固定兜底（GitHub noreply 邮箱，不泄露真实邮箱）。
    def _ident(key, env, default):
        r = subprocess.run(["git", "-C", str(_BASE), "config", "--get", key],
                           capture_output=True, text=True)
        v = (r.stdout or "").strip()
        return v or os.environ.get(env, "").strip() or default

    git("config", "user.name",
        _ident("user.name", "VT_DEPLOY_GIT_NAME", "VideoToolbox Deploy"))
    git("config", "user.email",
        _ident("user.email", "VT_DEPLOY_GIT_EMAIL",
               "09Th90@users.noreply.github.com"))

    git("add", "-A")
    st = git("status", "--porcelain")
    if not st.strip():
        print("发布目录无变化，无需提交")
        return 0
    ver = "?"
    upd = REPO_DIR / "Updates.xml"
    if upd.is_file():
        import re as _re
        m = _re.search(r"<Version>([^<]+)</Version>",
                       upd.read_text(encoding="utf-8", errors="replace"))
        ver = m.group(1) if m else "?"
    print(git("commit", "-q", "-m",
              f"deploy: 视频工具箱 v{ver} 在线安装器组件仓库"
              f"（内容位于 gh-pages 根，与安装器内嵌 URL 对齐）"))
    print("   新提交:", git("log", "--oneline", "-1").strip())

    t0 = time.time()
    r = subprocess.run(["git", "-c", "core.quotepath=false", "push",
                        "--force", "origin", "HEAD:" + BRANCH],
                       cwd=str(PUSH_DIR), capture_output=True)
    out = ((r.stdout or b"") + (r.stderr or b"")).decode("utf-8", "replace")
    print("   rc = %d  用时 %.1fs" % (r.returncode, time.time() - t0))
    print(out[-2500:])
    if r.returncode:
        return 1
    print(f"✅ gh-pages 已更新：{REMOTE_URL.replace('github.com', 'github.io')}/"
          f"{REPO}/  （CDN 生效通常需 30~60s）")
    return 0


def main():
    ap = argparse.ArgumentParser(description="部署在线安装器组件仓库到 gh-pages")
    ap.add_argument("--mode", choices=("git", "api"), default="git",
                    help="git=独立仓库 git push（默认，能推大归档）；"
                         "api=GitHub Git Data API（大文件会 422）")
    ap.add_argument("--check-size", action="store_true",
                    help="只量体积并检查 GitHub 100 MiB 硬限，不发布")
    ap.add_argument("--dry-run", action="store_true",
                    help="只镜像到 build/ghpages_push/，不提交不推送")
    args = ap.parse_args()
    if args.check_size:
        return check_size()
    if args.mode == "git":
        return deploy_via_git(dry_run=args.dry_run)
    return main_api()


if __name__ == "__main__":
    raise SystemExit(main())
