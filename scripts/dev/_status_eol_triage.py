# -*- coding: utf-8 -*-
# @version 2.2.5
"""核对 git status 报 M 的文件是真差异还是 autocrlf 幻影。

判据：`git hash-object <path>`（走 clean 过滤）与 HEAD blob 比对。
- 相等 → 幻影（stat 缓存大小不匹配，内容无差异）
- 不等 → 真差异（例如 blob 是 API 推送的 CRLF，worktree CRLF 会被过滤成 LF）
"""
import subprocess
import sys

ROOT = r"D:\Agent Work\软件开发\视频工具箱"


def run(args):
    return subprocess.run(args, cwd=ROOT, capture_output=True)


def main():
    out = run(["git", "status", "--porcelain", "-z"]).stdout.decode("utf-8")
    entries = [e for e in out.split("\0") if e]
    real, phantom = [], []
    for e in entries:
        code, path = e[:2], e[3:]
        if "??" in code:
            print("untracked:", path)
            continue
        if "M" not in code and "A" not in code:
            continue
        h = run(["git", "hash-object", path]).stdout.decode().strip()
        b = run(["git", "rev-parse", "HEAD:" + path])
        blob = b.stdout.decode().strip() if b.returncode == 0 else None
        if blob is None:
            real.append((path, "no blob"))
            continue
        (phantom if h == blob else real).append((path, h[:8] + " vs " + blob[:8]))
    print("phantom (identical after clean filter):", len(phantom))
    print("REAL differences:", len(real))
    for p, h in real:
        print("  REAL:", p, h)
    # 危险名单：blob 本身带 CR 的文件（API 推送产物），git add 会造成 EOL 翻转
    print("=== CRLF-blob danger check (all tracked files) ===")
    danger = []
    for e in entries:
        code, path = e[:2], e[3:]
        if "??" in code:
            continue
        b = run(["git", "cat-file", "blob", "HEAD:" + path])
        if b.returncode == 0 and b"\r" in b.stdout:
            danger.append(path)
    print("files whose HEAD blob contains CR:", danger or "none")


if __name__ == "__main__":
    sys.exit(main())
