#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# @version 1.15.4
"""把「滚动式」字幕修干净 —— 用于整理**已经下载到本地**的那批字幕。

背景：YouTube 等平台的自动字幕是**滚动**结构 —— 同一条的结束时间会一直延伸到
"下一条的结束"，于是整份字幕大面积互相压住（实测某 3566 条的字幕里 3028 条与
下一条重叠，占比 84.9%）。后果是播放时同一时刻两条并行、切轴抖动，后续翻译与
打轴也跟着错乱。

（v1.13.7 起程序会在**下载时**自动整理；本脚本负责把历史上已经下好的补救回来。）

用法（本文件在 src 目录下）：
    python fix_rolling_srt.py <路径> [<路径> ...]      # 只体检：报告哪些需要修
    python fix_rolling_srt.py <路径> --apply           # 额外写出 <原名>.fixed.srt
    python fix_rolling_srt.py <路径> --inplace         # 原地改写（先备份 <原名>.bak）

安全约定：
  · **默认绝不改动任何文件**，先看清楚再决定；
  · `--apply` 只写新文件，原件一律不动；
  · `--inplace` 覆盖前必然先留 `.bak` 备份；
  · 只动结束时间，文本 / 起始时间 / 序号 / 换行风格 / BOM 全部原样保留。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import video_toolbox as engine  # noqa: E402

#: 目录扫描时跳过的名字（缓存 / 临时产物）
SKIP_DIRS = {"__pycache__", ".git", ".buildvenv", "node_modules"}

USAGE = __doc__


def iter_srt_files(paths):
    """把命令行给的路径摊平成 .srt 文件列表（目录递归、结果去重排序）。"""
    found = []
    for p in paths:
        p = os.path.abspath(p)
        if os.path.isfile(p):
            if p.lower().endswith(".srt"):
                found.append(p)
            continue
        if not os.path.isdir(p):
            print(f"[跳过] 不存在：{p}")
            continue
        for root, dirs, files in os.walk(p):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            for name in files:
                if name.lower().endswith(".srt"):
                    found.append(os.path.join(root, name))
    return sorted(set(found))


def probe(path):
    """体检一份字幕：返回 stats dict（含 needs_fix）。只读，不落盘。"""
    stats = {}
    try:
        stats["needs_fix"] = bool(engine.normalize_rolling_srt(
            path, dry_run=True, stats=stats))
    except Exception as e:  # noqa: BLE001
        stats["needs_fix"] = False
        stats["error"] = str(e)
    return stats


def fix_to_new(path):
    """把整理后的结果写成 <原名>.fixed.srt（不动原件）。返回新路径或 None。"""
    stem, ext = os.path.splitext(path)
    out = stem + ".fixed" + ext
    with open(path, "rb") as f:
        data = f.read()
    with open(out, "wb") as f:
        f.write(data)
    if engine.normalize_rolling_srt(out):
        return out
    os.remove(out)       # 没改成功/没需要改：别留垃圾
    return None


def fix_inplace(path):
    """原地改写，先备份 <原名>.bak。返回 True 表示写过。"""
    bak = path + ".bak"
    with open(path, "rb") as f:
        data = f.read()
    with open(bak, "wb") as f:
        f.write(data)
    if engine.normalize_rolling_srt(path):
        return True
    os.remove(bak)       # 不需要改：不要把备份留在那儿
    return False


def main(argv):
    args = [a for a in argv if not a.startswith("-")]
    apply_new = "--apply" in argv
    inplace = "--inplace" in argv
    if not args or "-h" in argv or "--help" in argv:
        print(USAGE)
        return 0

    files = iter_srt_files(args)
    if not files:
        print("没找到任何 .srt 文件")
        return 1

    mode = "原地改写（先备份 .bak）" if inplace else (
        "写出 .fixed.srt 新文件" if apply_new else "只体检，不改动任何文件")
    print(f"共 {len(files)} 份字幕；模式：{mode}")
    print("-" * 78)
    print("%-8s %7s %8s %8s  %s" % ("状态", "条数", "重叠", "占比", "文件"))

    need, written, failed = [], 0, 0
    for path in files:
        st = probe(path)
        ratio = st.get("ratio", 0.0) or 0.0
        flag = "需整理" if st["needs_fix"] else "OK"
        print("%-8s %7d %8d %7.1f%%  %s"
              % (flag, st.get("cues", 0), st.get("overlaps", 0),
                 ratio * 100, os.path.relpath(path, os.getcwd())))
        if st.get("error"):
            print("         └─ 读取失败：%s" % st["error"])
            failed += 1
            continue
        if not st["needs_fix"]:
            continue
        need.append(path)
        if inplace:
            try:
                if fix_inplace(path):
                    written += 1
                    print("         └─ 已原地改写，备份 %s" % (path + ".bak"))
            except OSError as e:
                failed += 1
                print("         └─ 写入失败：%s" % e)
        elif apply_new:
            try:
                out = fix_to_new(path)
                if out:
                    written += 1
                    print("         └─ 已写出 %s" % out)
            except OSError as e:
                failed += 1
                print("         └─ 写入失败：%s" % e)

    print("-" * 78)
    print("需要整理：%d 份；已处理：%d 份；失败：%d 份" % (len(need), written, failed))
    if need and not (inplace or apply_new):
        print("（当前是体检模式，什么都没改。确认无误后加 --apply 或 --inplace 再跑一次）")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
