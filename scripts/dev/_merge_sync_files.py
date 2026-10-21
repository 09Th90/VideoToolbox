# -*- coding: utf-8 -*-
# @version 2.5.1
"""把本地两个同步文件（校准脚本 / 学习库）与 origin/main 做一次应用同口径合并。

用 src/calib_merge_core.py 的 merge_calib_script / merge_learned_kb ——
与 App 退出推送前的 _pull_and_merge 完全一致，避免 git 三方合并在
EOL/条目顺序上制造噪声。

产物直接写回工作区（原子写）：
  · 校准脚本：合并结果按 CRLF 落盘（仓库 blob 现行风格，避免整文件 EOL 翻转）
  · 学习库：按 CRLF 落盘（learn 工具一贯输出形态，入库时 autocrlf 归一为 LF）
"""
import io
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "src"))
import calib_merge_core as mmc  # noqa: E402

CALIB = os.path.join(ROOT, "subtitle_calib_merged.py")
KB = os.path.join(ROOT, "subtitle_learned_kb.json")
BASE_SCRIPT = os.path.join(ROOT, "data", "calib_sync_base.py")


def git_show(ref):
    out = subprocess.run(["git", "show", ref], cwd=ROOT, capture_output=True)
    if out.returncode != 0:
        raise SystemExit("git show %s failed: %s" % (ref, out.stderr.decode("utf-8", "replace")))
    return out.stdout


def atomic_write_bytes(path, data):
    tmp = path + ".merge_tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)


def to_crlf(text):
    return text.replace("\r\n", "\n").replace("\n", "\r\n").encode("utf-8")


def kb_stats(data):
    d = json.loads(data.decode("utf-8"))
    c = d["candidates"]
    firsts = [v.get("first") for v in c.values() if v.get("first")]
    ns = sum(1 for v in c.values() if v.get("samples"))
    nt = sum(1 for v in c.values() if v.get("ref_tokens"))
    return "%d entries / %d samples / %d tokens / first %s~%s" % (
        len(c), ns, nt, min(firsts), max(firsts))


def main():
    # ---------- 1. 校准脚本 ----------
    local = open(CALIB, "rb").read().decode("utf-8")
    remote = git_show("origin/main:subtitle_calib_merged.py").decode("utf-8")
    base = ""
    if os.path.isfile(BASE_SCRIPT):
        base = open(BASE_SCRIPT, "rb").read().decode("utf-8")
    print("[calib] local :", kb_stats.__module__ and len(local), "bytes")
    print("[calib] remote:", len(remote), "bytes | base:", len(base) or "-", "bytes")
    merged, added, conflicts = mmc.merge_calib_script(local, remote, base)
    print("[calib] merge added=%d conflicts=%d changed=%s" % (
        added, len(conflicts), merged != local))
    for c in conflicts:
        print("   conflict:", c)
    if merged != local:
        compile(merged, CALIB, "exec")  # 双保险：模块内已验过，这里再验一次
        atomic_write_bytes(CALIB, to_crlf(merged))
        print("[calib] written back (CRLF):", os.path.getsize(CALIB), "bytes")

    # ---------- 2. 学习库 ----------
    local_kb = open(KB, "rb").read().decode("utf-8")
    remote_kb = git_show("origin/main:subtitle_learned_kb.json").decode("utf-8")
    print("[kb] local :", kb_stats(local_kb.encode("utf-8")))
    print("[kb] remote:", kb_stats(remote_kb.encode("utf-8")))
    merged_kb, kadded, kconf = mmc.merge_learned_kb(local_kb, remote_kb)
    print("[kb] merge added=%d conflicts=%d changed=%s" % (
        kadded, kconf, merged_kb != local_kb))
    if merged_kb != local_kb:
        json.loads(merged_kb)  # 解析失败直接抛，不落盘
        atomic_write_bytes(KB, to_crlf(merged_kb))
        print("[kb] written back (CRLF):", os.path.getsize(KB), "bytes")
        print("[kb] merged:", kb_stats(merged_kb.encode("utf-8")))


if __name__ == "__main__":
    main()
