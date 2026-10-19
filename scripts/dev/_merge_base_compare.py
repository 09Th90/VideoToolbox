# -*- coding: utf-8 -*-
# @version 2.4.0
"""三路合并对比：git-base / snapshot-base / 无base(全量并集)。

无 base 时会采纳所有「本地没有」的远端条目（含本地可能有意删掉的），
与带 base 的结果做差集，逐个审视"被 base 规则跳过"的条目是否该采纳。
"""
import os
import subprocess
import sys

ROOT = r"D:\Agent Work\软件开发\视频工具箱"
sys.path.insert(0, os.path.join(ROOT, "src"))
import calib_merge_core as mmc  # noqa: E402

CALIB = "subtitle_calib_merged.py"


def show(ref):
    p = subprocess.run(["git", "show", ref], cwd=ROOT, capture_output=True)
    if p.returncode != 0:
        raise SystemExit("git show %s failed" % ref)
    return p.stdout.decode("utf-8")


def main():
    local = show("HEAD:" + CALIB)
    remote = show("origin/main:" + CALIB)
    base_git = show("5c978b1:" + CALIB)
    with open(os.path.join(ROOT, "data", "calib_sync_base.py"), "rb") as f:
        base_snap = f.read().decode("utf-8")

    m_git, a_git, c_git = mmc.merge_calib_script(local, remote, base_git)
    m_snap, a_snap, c_snap = mmc.merge_calib_script(local, remote, base_snap)
    m_full, a_full, c_full = mmc.merge_calib_script(local, remote, "")
    print("git-base   : added=%d conflicts=%d len=%d" % (a_git, len(c_git), len(m_git)))
    print("snap-base  : added=%d conflicts=%d len=%d" % (a_snap, len(c_snap), len(m_snap)))
    print("no-base    : added=%d conflicts=%d len=%d" % (a_full, len(c_full), len(m_full)))
    if m_git == m_snap:
        print("git-base == snap-base ✓")
    if m_git == m_full:
        print("git-base == no-base ✓（无被跳过的远端条目）")
        return 0
    # 差集：no-base 比 git-base 多采纳了哪些行
    gset = set(m_git.replace("\r\n", "\n").split("\n"))
    extra = [l for l in m_full.replace("\r\n", "\n").split("\n") if l not in gset]
    print("\nno-base 多采纳的行（git-base 视为本地已删/本地改过）:")
    for l in extra:
        print("   +", l.strip()[:120])
    # 这些行的键在 base 和 local 里的状态
    print("\n这些行在 5c978b1(base) 与 HEAD(local) 中的存在性粗查：")
    bl = set(base_git.replace("\r\n", "\n").split("\n"))
    ll = set(local.replace("\r\n", "\n").split("\n"))
    for l in extra:
        s = l.strip()
        print("   in_base=%s in_local=%s | %s" % (s in bl, s in ll, s[:90]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
