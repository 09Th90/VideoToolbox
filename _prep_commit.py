# -*- coding: utf-8 -*-
"""准备 main 分支提交：移除超限中间产物，检查暂存区是否有 >95MB 文件。"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def git(*args, check=True):
    r = subprocess.run(["git", "-c", "core.quotepath=false", *args],
                       cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if check and r.returncode:
        print("GIT FAIL:", args, r.stderr[:300])
        sys.exit(1)
    return r.stdout


# 1) 从 index 移除打包中间产物目录（磁盘保留）
git("rm", "-r", "--cached", "-f", "-q", "build/视频工具箱")

# 2) 重新暂存全部（含瘦身后的 dist exe）
git("add", "-A")

# 3) 检查暂存区所有 blob 大小（用 git cat-file -s 读 index，避免路径编码问题）
out = git("ls-files", "-s", "-z")
entries = [e for e in out.split("\0") if e.strip()]
big = []
for e in entries:
    meta, _, path = e.partition("\t")
    mode, sha, stage = meta.split()
    if stage != "0":
        continue
    size = int(git("cat-file", "-s", sha).strip())
    if size > 95 * 1024 * 1024:
        big.append((size, path))

print(f"index entries: {len(entries)}")
if big:
    print("!! OVER-LIMIT (>95MB) files still in index:")
    for s, p in sorted(big, reverse=True):
        print(f"   {s/1048576:7.1f} MB  {p}")
else:
    print("OK: no file over 95MB in index")

print("\n--- staged changes ---")
print(git("diff", "--cached", "--stat").splitlines()[-1])
