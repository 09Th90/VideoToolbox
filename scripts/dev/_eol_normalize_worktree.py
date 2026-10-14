# -*- coding: utf-8 -*-
# @version 2.2.5
"""把 5c978b1..HEAD 改动文件的工作区副本行尾归一化为 CRLF。

背景：autocrlf=true 下 blob 统一存 LF，checkout 出来是 CRLF；工具直写会把
worktree 副本写成 LF / 混合行尾。git 层面无差异（add 时归一），但直读
worktree 的工具（如同步合并脚本、App）会遇到 EOL 不一致，故恢复惯例形态。
二进制文件（含 NUL）跳过。
"""
import os
import subprocess
import sys

ROOT = r"D:\Agent Work\软件开发\视频工具箱"


def main():
    p = subprocess.run(
        ["git", "diff", "--name-only", "-z", "5c978b1", "HEAD"],
        cwd=ROOT, capture_output=True, check=True)
    files = [f for f in p.stdout.decode("utf-8").split("\0") if f]
    conv = mixed = 0
    done = []
    for rel in files:
        path = os.path.join(ROOT, rel)
        if not os.path.isfile(path):
            continue
        with open(path, "rb") as f:
            data = f.read()
        if b"\x00" in data:
            continue  # 二进制
        if b"\r" in data:
            # 混合行尾：把裸 \n 统一补 \r
            fixed = data.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
            if fixed != data:
                with open(path, "wb") as f:
                    f.write(fixed)
                mixed += 1
                done.append(rel)
            continue
        if b"\n" in data:
            fixed = data.replace(b"\n", b"\r\n")
            with open(path, "wb") as f:
                f.write(fixed)
            conv += 1
            done.append(rel)
    print("pure-LF -> CRLF:", conv)
    print("mixed -> CRLF:", mixed)
    print("total touched:", len(done))
    for d in done:
        print("   ", d)


if __name__ == "__main__":
    sys.exit(main())
