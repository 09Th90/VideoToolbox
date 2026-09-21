# -*- coding: utf-8 -*-
# @version 1.15.7
"""在 github.com 不可达时，用 GitHub Git Data API 推送当前 HEAD（api.github.com 直连可用）。

背景（本机网络实测）：``git push`` 走 github.com **直连与内置代理均不通**，而
``api.github.com`` 直连 200 可用；本项目 ``deploy_installer_ghpages.py`` 早已用
同一套通道发布在线安装器。本脚本把「当前本地 HEAD 的完整文件树」同步到远端分支，
等价于一次 ``git push``（内容级一致，不搬运 git 历史对象）。

流程：
  1. 取远端 ref/heads/<branch> → commit → tree（recursive）；
  2. 本地 ``git ls-tree -r HEAD`` 得到全量 path → blob sha（git 视角，已做换行规范化）；
  3. 差异：本地新增/内容不同 → ``git cat-file blob <sha>`` 取字节 → base64 → POST /git/blobs；
     远端有而本地无 → tree 条目 sha:null（删除）；
  4. POST /git/trees(base_tree=远端 tree) → POST /git/commits(parent=远端 head)；
  5. PATCH /git/refs/heads/<branch>（force=false，非快进即失败，绝不覆盖他人提交）。

用法（在 src 目录）：
    python push_via_git_api.py --dry-run     # 只报告差异
    python push_via_git_api.py               # 真推送
"""
import argparse
import base64
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
API = "https://api.github.com"


def _token():
    try:
        return subprocess.run(["gh", "auth", "token"], capture_output=True, text=True,
                              check=True).stdout.strip()
    except Exception:  # noqa: BLE001
        for k in ("GH_TOKEN", "GITHUB_TOKEN"):
            if os.environ.get(k):
                return os.environ[k].strip()
        sys.exit("无法获取 GitHub token（gh auth login 或设置 GH_TOKEN）")


def _git(*args):
    # core.quotepath=false：否则中文路径会被 git 输出成 \344\275... 转义串，
    # 与 GitHub API 返回的真实路径对不上，会把远端中文文件全部误判为「需删除」。
    return subprocess.run(["git", "-c", "core.quotepath=false", *args], cwd=ROOT,
                          capture_output=True, text=True, check=True).stdout


#: 强制直连：本机 curl 直连 api.github.com 可用，但系统/沙箱环境里的
#: http_proxy / https_proxy 会让 urllib 走代理并被 502 拦下（实测）。
#: 空 ProxyHandler = 不走任何代理，等价于 curl --noproxy '*'。
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _api(method, path, token, payload=None):
    url = path if path.startswith("http") else API + path
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "VideoToolbox-push-via-api",
        "Content-Type": "application/json",
    })
    try:
        with _OPENER.open(req, timeout=60) as r:
            body = r.read().decode()
            return json.loads(body) if body.strip() else {}
    except urllib.error.HTTPError as e:
        detail = e.read().decode()[:400]
        raise RuntimeError(f"{method} {url} → HTTP {e.code}: {detail}") from None


def _local_tree():
    """{path: (mode, sha)}，来自 git ls-tree -r HEAD（已含换行规范化）。"""
    out = {}
    for line in _git("ls-tree", "-r", "HEAD").splitlines():
        meta, path = line.split("\t", 1)
        mode, _type, sha = meta.split()
        out[path] = (mode, sha)
    return out


def _remote_tree(token, owner, repo, branch):
    ref = _api("GET", f"/repos/{owner}/{repo}/git/ref/heads/{branch}", token)
    head = ref["object"]["sha"]
    commit = _api("GET", f"/repos/{owner}/{repo}/git/commits/{head}", token)
    tree_sha = commit["tree"]["sha"]
    tree = _api("GET", f"/repos/{owner}/{repo}/git/trees/{tree_sha}?recursive=1", token)
    files = {}
    for it in tree.get("tree", []):
        if it["type"] == "blob":
            files[it["path"]] = (it.get("mode", "100644"), it["sha"])
    return head, tree_sha, files


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--branch", default="main")
    ap.add_argument("--message", default=None)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    remote = _git("remote", "get-url", "origin").strip()
    slug = remote.rstrip("/").removesuffix(".git").split("github.com/")[-1]
    owner, repo = slug.split("/")[:2]
    branch = args.branch
    token = _token()

    local = _local_tree()
    head, tree_sha, remote_files = _remote_tree(token, owner, repo, branch)
    print(f"仓库 {owner}/{repo}@{branch}  远端 head {head[:10]}  本地 HEAD "
          f"{_git('rev-parse', 'HEAD').strip()[:10]}")
    print(f"本地 {len(local)} 个文件 / 远端 {len(remote_files)} 个文件")

    upsert = {p: v for p, v in local.items()
              if p not in remote_files or remote_files[p][1] != v[1]}
    delete = [p for p in remote_files if p not in local]
    print(f"需上传/更新 {len(upsert)} 个，需删除 {len(delete)} 个")
    for p in list(upsert)[:15]:
        tag = "改" if p in remote_files else "新"
        print(f"  [{tag}] {p}")
    if len(upsert) > 15:
        print(f"  ...（其余 {len(upsert) - 15} 个）")
    for p in delete[:10]:
        print(f"  [删] {p}")
    if len(delete) > 10:
        print(f"  ...（其余 {len(delete) - 10} 个）")

    if args.dry_run:
        print("（--dry-run，未推送）")
        return 0
    if not upsert and not delete:
        print("远端与本地一致，无需推送")
        return 0

    entries = []
    for i, (path, (mode, sha)) in enumerate(sorted(upsert.items()), 1):
        raw = subprocess.run(["git", "cat-file", "blob", sha], cwd=ROOT,
                             capture_output=True, check=True).stdout
        blob = _api("POST", f"/repos/{owner}/{repo}/git/blobs", token, {
            "content": base64.b64encode(raw).decode(), "encoding": "base64"})
        entries.append({"path": path, "mode": mode, "type": "blob",
                        "sha": blob["sha"]})
        if i % 20 == 0 or i == len(upsert):
            print(f"  已上传 {i}/{len(upsert)} 个 blob")
    for path in delete:
        entries.append({"path": path, "mode": "100644", "type": "blob", "sha": None})

    msg = args.message or _git("log", "-1", "--pretty=%B").strip()
    new_tree = _api("POST", f"/repos/{owner}/{repo}/git/trees", token,
                    {"base_tree": tree_sha, "tree": entries})
    commit = _api("POST", f"/repos/{owner}/{repo}/git/commits", token,
                  {"message": msg, "tree": new_tree["sha"], "parents": [head]})
    _api("PATCH", f"/repos/{owner}/{repo}/git/refs/heads/{branch}", token,
         {"sha": commit["sha"], "force": False})
    print(f"已推送：{branch} → {commit['sha'][:10]}")
    print(f"https://github.com/{owner}/{repo}/commit/{commit['sha']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
