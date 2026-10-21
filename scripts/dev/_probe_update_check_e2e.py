# -*- coding: utf-8 -*-
# @version 2.4.1
"""End-to-end: vt_update_check.check_update against a local file:// repo.

复现用户截图场景（开发版 v2.0.0 运行、安装目录是空的、远端最新
v1.19.0）与两个对照场景（全新安装新版 / 已装 v2.0.0 回滚）。
全程离线，只读 manifest，不下载任何资产。
"""
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "src"))

import vt_update_check as u  # noqa: E402

ok = [0]
bad = [0]


def chk(name, cond, extra=""):
    if cond:
        ok[0] += 1
        print("  PASS  %s" % name)
    else:
        bad[0] += 1
        print("  FAIL  %s   %s" % (name, extra))


def furi(p):
    return "file:///" + os.path.abspath(p).replace("\\", "/")


def write_manifest(repo, version, sha="a" * 64):
    """schema 2 清单（带 files，才能算出本地已装版本）。"""
    m = {
        "schema": 2, "app": "视频工具箱", "version": version,
        "released": "2026-10-10 23:03:23",
        "base_url": furi(repo),
        "assets": [{
            "name": "base", "file": "v%s-base.zip" % version,
            "size": 104239406, "sha256": sha, "entries": 1,
            "target": "", "desc": "主程序（必装）",
        }],
        "files": {"视频工具箱.exe": {"size": 1024, "sha256": sha,
                                    "pkg": "base"}},
        "parts": [], "updater": {"version": "1.19.0"}, "remove": [],
    }
    p = os.path.join(repo, "manifest-%s.json" % version)
    with open(p, "w", encoding="utf-8") as fh:
        json.dump(m, fh, ensure_ascii=False, indent=1)
    return p


def write_installed(install_dir, version, sha="a" * 64):
    os.makedirs(install_dir, exist_ok=True)
    with open(os.path.join(install_dir, "vt_installed.json"), "w",
              encoding="utf-8") as fh:
        json.dump({"version": version, "written": "2026-10-10 23:03:23",
                   "files": {"视频工具箱.exe": {"size": 1024,
                                                "sha256": sha}}},
                  fh, ensure_ascii=False, indent=1)


def report(r):
    print("   local_ver=%r remote_ver=%r full=%s baseline=%r update=%s "
          "down=%s label=%s dl=%s" % (
              r.local_ver, r.remote_ver, r.full, r.baseline_ver, r.update,
              r.downgrade(), r.action_label(), u._human(r.download_bytes)))


tmp = tempfile.mkdtemp(prefix="vt_upd_e2e_")
repo = os.path.join(tmp, "repo")
os.makedirs(repo)
m119 = write_manifest(repo, "1.19.0")
m118 = write_manifest(repo, "2.1.0", sha="b" * 64)

#: 「正在运行的版本」一律取自模块的 SELF_VERSION，**不硬编码**。
#: 2026-10-13教训：升版到 2.1.0 后本探针里 6 处写死的 "2.0.0" 全部失配，
#: 报出 3 个 FAIL ——看起来像更新逻辑坏了，其实是探针自己过期。
#: 期望值绑定到被测对象的真实取值，升版后无需再改探针。
RUN = u.SELF_VERSION

try:
    print("== 1) 截图场景：开发版 %s 在跑、安装目录空、远端 1.19.0 ==" % RUN)
    empty = os.path.join(tmp, "install_empty")
    os.makedirs(empty)
    r = u.check_update(install_dir=empty, manifest_url=m119,
                       base_url=furi(repo))
    chk("检测成功", r.ok is True, r.err)
    report(r)
    chk("本地=未安装", r.local_ver == "未安装", r.local_ver)
    chk("远端=1.19.0", r.remote_ver == "1.19.0", r.remote_ver)
    chk("判为全新安装", r.full is True)
    chk("基准=运行版本", r.baseline_ver == RUN, r.baseline_ver)
    chk("判降级（1.19.0 < %s）" % RUN, r.downgrade() is True)
    chk("标题=安装较旧版本", r.action_label() == "安装较旧版本")
    chk("下载量=99.4 MB", u._human(r.download_bytes) == "99.4 MB",
        u._human(r.download_bytes))
    chk("组件=base", [n for n, _ in r.packages] == ["base"], r.packages)
    lines = "\n".join(r.detail_lines())
    chk("正文无 v未安装", "v未安装" not in lines, lines)
    chk("正文写明『正在运行 v%s』" % RUN,
        ("正在运行 v%s" % RUN) in lines, lines)
    chk("正文标明降级", "低于当前" in lines)

    print("\n== 2) 对照：安装目录空、远端比运行版本新 ==")
    r = u.check_update(install_dir=empty, manifest_url=m118,
                       base_url=furi(repo))
    chk("检测成功", r.ok is True, r.err)
    report(r)
    chk("标题=全新安装", r.action_label() == "全新安装", r.action_label())

    print("\n== 3) 对照：已装 v%s、远端 1.19.0（回滚）==" % RUN)
    inst2 = os.path.join(tmp, "install_cur")
    write_installed(inst2, RUN)
    r = u.check_update(install_dir=inst2, manifest_url=m119,
                       base_url=furi(repo))
    chk("检测成功", r.ok is True, r.err)
    report(r)
    chk("本地=%s" % RUN, r.local_ver == RUN, r.local_ver)
    chk("基准=%s" % RUN, r.baseline_ver == RUN, r.baseline_ver)
    chk("标题=回滚到旧版本", r.action_label() == "回滚到旧版本")
    chk("非全新安装", r.full is False)
    lines = r.detail_lines()
    chk("首行=当前版本：v%s" % RUN,
        lines[0] == "当前版本：v%s" % RUN, lines[0])

    print("\n== 4) 对照：已装 1.18.0、远端 1.19.0（普通升级，SELF 压低复现）==")
    inst1 = os.path.join(tmp, "install_118")
    write_installed(inst1, "1.18.0")
    real_self = u.SELF_VERSION
    u.SELF_VERSION = "1.18.0"
    try:
        r = u.check_update(install_dir=inst1, manifest_url=m119,
                           base_url=furi(repo))
        chk("检测成功", r.ok is True, r.err)
        report(r)
        chk("标题=发现新版本", r.action_label() == "发现新版本", r.action_label())
        chk("基准=1.18.0", r.baseline_ver == "1.18.0", r.baseline_ver)
        lines = r.detail_lines()
    finally:
        u.SELF_VERSION = real_self
    chk("首行=当前版本：v1.18.0", lines[0] == "当前版本：v1.18.0", lines[0])
    chk("含『最新版本：v1.19.0』", lines[1] == "最新版本：v1.19.0", lines[1])

    print("\n%s passed, %s failed" % (ok[0], bad[0]))
finally:
    shutil.rmtree(tmp, ignore_errors=True)

sys.exit(1 if bad[0] else 0)
