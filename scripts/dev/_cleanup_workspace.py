# -*- coding: utf-8 -*-
# @version 2.5.4
"""工作区清理：开发临时文件 / 构建产物 / 校准报告。

安全约束（来自项目约定与 docs/程序说明书(开发版).md L1322）：
  1. 一律 **rename 到 history/_cleanup_<日期>/**，不做递归删除
     （本机 safe-delete shim 对 rmtree / 批量 unlink 会拦死，rename 不触发）；
  2. 移动前核对 git 跟踪状态，**任何受控路径一律跳过**；
  3. 唯一允许永久删除的是 __pycache__（约定唯一例外）；
  4. 只处理显式列出的路径，不做通配式扫描。

用法：python _cleanup_workspace.py --dry   仅打印计划
      python _cleanup_workspace.py --run   执行
"""
import os
import shutil
import subprocess
import sys
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT)
STAMP = time.strftime("%Y%m%d")
DEST = os.path.join("history", "_cleanup_%s" % STAMP)


def tracked_set():
    out = subprocess.run(["git", "ls-files"], capture_output=True, text=True)
    return {p.replace("\\", "/").strip() for p in out.stdout.splitlines() if p.strip()}


TRACKED = tracked_set()


def has_tracked(path):
    """路径本身或目录内任一文件受 git 跟踪 → 返回 True。"""
    p = path.replace("\\", "/").rstrip("/")
    if p in TRACKED:
        return True
    pref = p + "/"
    return any(t.startswith(pref) for t in TRACKED)


def size_of(path):
    if os.path.isfile(path):
        try:
            return os.path.getsize(path), 1
        except OSError:
            return 0, 1
    t = n = 0
    for b, _ds, fs in os.walk(path):
        for f in fs:
            try:
                t += os.path.getsize(os.path.join(b, f))
                n += 1
            except OSError:
                pass
    return t, n


# ---------------------------------------------------------------- 计划
# 组 1：开发临时文件
DEV_TMP = [
    "data/tmp",
    "_calib_tmp_cover",
    "-J",
    "aqtinstall.log",
    "_selftest_pipeline_result.txt",
    "data/GUI_SELFTEST_REPORT.txt",
    "data/GUI_SELFTEST_OK",
]

# 组 2：构建产物（只列未跟踪的产物子目录/文件，源码另行避让）
BUILD_ARTIFACTS = [
    "build/视频工具箱",
    "build/ifw_packages",
    "build/_home_probe_data",
    "build/vt_online_setup",
    "build/ifw_config",
    "packaging/build",
    "packaging/dist",
    "packaging/__pycache__",
    "dist",
    "installer_online",
    "installer_repository",
    "installer",
]

# 组 3：字幕校准报告（合并归档到同一处）
CALIB_REPORTS = [
    # calib_diff 系列（差异明细）
    "outbox/calib_diff_37_ko.md",
    "outbox/calib_diff_adhd_reacts_37_final.tsv",
    "outbox/calib_diff_endfield_ko_1.6_round2.md",
    "outbox/calib_diff_endfield_talos2.md",
    "outbox/calib_diff_wish_granted_hsin37.md",
    "outbox/calib_report_terms.md",
    "outbox/report3_section.md",
    "outbox/finesub_stabilize_gap_analysis.md",
    # 侧车修正表
    "outbox/side_37_criedagain_all.tsv",
    "outbox/side_wuwa_2a6_ja_subfix.tsv",
    # 校准报告
    "outbox/校准报告_adhd_reacts_37.md",
    "outbox/校准对照_WISH_GRANTED_Hsin3.7_r2.md",
    "outbox/校准终稿对照_WISH_GRANTED_Hsin3.7.tsv",
    "outbox/精校明细_Crashout_2026-10-15.tsv",
    "outbox/精校报告_Crashout_2026-10-15.md",
    "outbox/拆分明细_奈渡S2_2026-10-15.tsv",
    "outbox/校准拆分报告_奈渡S2_2026-10-15.md",
    "outbox/名词漏校三扫_Crashout精校稿_2026-10-16.md",
    "outbox/鸣潮3.7_IHaveCriedAgain_二次校准报告.md",
    "outbox/终末地丹青渡_RHODES_ISLAND_校准报告.md",
    "outbox/终末地丹青渡_RHODES_ISLAND_二次校准报告.md",
    "outbox/终末地1.6丹青渡_韩语官方直播_二次校准报告.md",
    "outbox/终末地_终极之罪_校准报告.md",
    "outbox/工具箱校准能力升级_2026-10-16.md",
    "outbox/【字幕】《명조》 오열주의： 3.7 몽주 4장 4막 「몽주의 궤적, 마음이 그리는 대로」🍓2026.10.05 월.ko-谷歌翻译.逐cue改动明细.md",
    "outbox/【字幕】《명조》 오열주의： 3.7 몽주 4장 4막 「몽주의 궤적, 마음이 그리는 대로」🍓2026.10.05 월.ko-谷歌翻译.校准报告.md",
]

# 组 4：其他类型报告（按类别分开清除）
OTHER_REPORTS = {
    "release": [
        "outbox/发布校准报告_2026-10-13_v2.0.0.md",
    ],
    "install": [
        "outbox/安装版与仓库核对报告_2026-09-19.md",
        "outbox/在线安装更新核验报告_2026-09-28.md",
    ],
    "download": [
        "outbox/下载监控报告_2026-10-17_23点前.md",
        "outbox/下载EOF报错_根因与修复_2026-10-08.md",
        "outbox/版本对比_1.18_vs_当前_下载链路.md",
    ],
    "cleanup": [
        "outbox/清理清单_2026-10-08.md",
        "outbox/工作区清理报告_2026-10-12.md",
    ],
    "misc": [
        "outbox/文件一致性核对报告_2026-09-19.md",
        "outbox/主播声纹筛选_组件验收_2026-10-08.md",
    ],
}

# 永久删除（约定唯一例外）
PYCACHE = ["__pycache__"]

# 明确保留（仅用于报告说明，不参与移动）
KEEP_NOTE = [
    "outbox/*.srt（校准成品，可能尚未同步到 D:/原片）",
    "outbox/*.png（界面截图）",
    "outbox/弃保声明*.pdf / 附件5弃保声明*.docx（个人文档，非项目产物）",
    "outbox/vt-release-calibration_skill_v1.zip",
    "data/calib_sync_base.py、data/calib_sync_kb_base.json（被 src/core/calibrate/sync.py 引用）",
    "data/data/（运行期数据，昨日仍有写入）",
    "data/browser_login、data/uploader_profile（登录态 / 上传配置）",
    "packaging/ 下 16 个受控源文件（spec / iss / installer_src / online_release 等）",
    "build/ 下 7 个受控文件（探针脚本 / sha256 / calib_trash_20261013）",
]


def plan():
    """返回 [(组名, 源路径, 目标相对路径, 是否跳过, 原因)]。"""
    items = []
    for p in DEV_TMP:
        items.append(("dev_tmp", p, os.path.join(DEST, "dev_tmp", os.path.basename(p))))
    for p in BUILD_ARTIFACTS:
        items.append(("build_artifacts", p,
                      os.path.join(DEST, "build_artifacts", p.replace("/", "__"))))
    for p in CALIB_REPORTS:
        items.append(("calib_reports", p, os.path.join(DEST, "calib_reports", os.path.basename(p))))
    for grp, lst in OTHER_REPORTS.items():
        for p in lst:
            items.append(("other_reports/" + grp, p,
                          os.path.join(DEST, "other_reports", grp, os.path.basename(p))))
    out = []
    for grp, src, dst in items:
        if not os.path.exists(src):
            out.append((grp, src, dst, True, "不存在"))
        elif has_tracked(src):
            out.append((grp, src, dst, True, "受 git 跟踪，跳过"))
        else:
            out.append((grp, src, dst, False, ""))
    return out


def move_one(src, dst):
    """用 rename 移动；跨盘时才退回 copytree+rename。"""
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if os.path.exists(dst):
        base, ext = os.path.splitext(dst)
        dst = "%s__dup%d%s" % (base, int(time.time() * 1000) % 100000, ext)
    try:
        os.rename(src, dst)
        return dst, "rename"
    except OSError:
        shutil.move(src, dst)
        return dst, "move"


def main():
    dry = "--run" not in sys.argv
    items = plan()
    print("=" * 74)
    print("工作区清理%s  目标根: %s" % ("（DRY-RUN）" if dry else "", DEST))
    print("=" * 74)

    groups = {}
    for grp, src, dst, skip, why in items:
        groups.setdefault(grp, []).append((src, dst, skip, why))

    total_mb = total_n = 0
    moved_mb = moved_n = 0
    skipped = []
    for grp in sorted(groups):
        print("\n[%s]" % grp)
        for src, dst, skip, why in groups[grp]:
            mb, n = (0, 0) if not os.path.exists(src) else size_of(src)
            total_mb += mb
            total_n += n
            if skip:
                print("  SKIP  %-56s (%s)" % (src[:56], why))
                skipped.append((src, why))
                continue
            moved_mb += mb
            moved_n += n
            print("  MOVE  %-56s %8.1f MB %5d" % (src[:56], mb / 1048576, n))
            if not dry:
                try:
                    real, how = move_one(src, dst)
                    print("        -> %s  (%s)" % (real, how))
                except Exception as e:
                    print("        !! 失败: %r" % (e,))
                    skipped.append((src, "移动失败: %r" % (e,)))

    print("\n" + "-" * 74)
    print("拟处理: %.1f MB / %d 文件（含受控跳过项共 %.1f MB / %d）"
          % (moved_mb / 1048576, moved_n, total_mb / 1048576, total_n))

    # __pycache__ 永久删除
    print("\n[__pycache__ 永久删除]")
    pyc = []
    for base, dirs, _files in os.walk("."):
        if any(x in base.replace("\\", "/") for x in ("/.git", "history/")):
            continue
        for d in list(dirs):
            if d == "__pycache__":
                pyc.append(os.path.join(base, d))
    for p in pyc:
        mb, n = size_of(p)
        print("  DEL   %-56s %8.1f MB %5d" % (p[:56], mb / 1048576, n))
        if not dry:
            shutil.rmtree(p, ignore_errors=True)
    print("  共 %d 个 __pycache__ 目录" % len(pyc))

    if skipped:
        print("\n跳过项:")
        for s, w in skipped:
            print("  - %s (%s)" % (s, w))

    print("\n保留项:")
    for k in KEEP_NOTE:
        print("  * %s" % k)

    if dry:
        print("\n这是 DRY-RUN。确认无误后加 --run 执行。")


if __name__ == "__main__":
    main()
