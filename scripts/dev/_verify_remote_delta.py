# -*- coding: utf-8 -*-
# @version 2.5.4
"""核实 origin/main 相对 HEAD 是否真有未合并条目（行集合 / 候选键集合差集）。"""
import json
import os
import subprocess
import sys

ROOT = r"D:\Agent Work\软件开发\视频工具箱"
CALIB = "subtitle_calib_merged.py"
KB = "subtitle_learned_kb.json"


def show(ref):
    p = subprocess.run(["git", "show", ref], cwd=ROOT, capture_output=True)
    if p.returncode != 0:
        raise SystemExit("git show %s failed" % ref)
    return p.stdout.decode("utf-8")


def main():
    # --- calib：行集合差集（去空白与引号风格差异，只看"整行是否出现过"）---
    lc = [l.rstrip() for l in show("HEAD:" + CALIB).replace("\r\n", "\n").split("\n")]
    rc = [l.rstrip() for l in show("origin/main:" + CALIB).replace("\r\n", "\n").split("\n")]
    lset = set(lc)
    remote_only = [l for l in rc if l not in lset]
    print("calib: local lines=%d remote lines=%d remote-only lines=%d"
          % (len(lc), len(rc), len(remote_only)))
    for l in remote_only[:40]:
        print("   R-only:", l.strip()[:110])
    if len(remote_only) > 40:
        print("   ... (%d more)" % (len(remote_only) - 40))

    # --- kb：候选键集合差集 ---
    lk = json.loads(show("HEAD:" + KB))
    rk = json.loads(show("origin/main:" + KB))
    lkeys, rkeys = set(lk["candidates"]), set(rk["candidates"])
    print("\nkb: local candidates=%d remote candidates=%d" % (len(lkeys), len(rkeys)))
    print("remote-only keys:", len(rkeys - lkeys))
    for k in sorted(rkeys - lkeys)[:30]:
        print("   R-only:", k, "->", rk["candidates"][k].get("right"))
    print("local-only keys:", len(lkeys - rkeys))
    # 内容真有差异的同键数
    diff_same = [k for k in (lkeys & rkeys) if lk["candidates"][k] != rk["candidates"][k]]
    print("same-key different-content:", len(diff_same))
    return 0


if __name__ == "__main__":
    sys.exit(main())
