# -*- coding: utf-8 -*-
# @version 2.6.0
"""End-to-end: vt_update_check.check_update against a local file:// repo.

覆盖：源码模式（默认）、安装版四种版本方向、安装记录陈旧自动校正、
同版本修复安装、同版本短路。全程离线，只读 manifest，不下载任何资产。
"""
import hashlib
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


def sha(data):
    return hashlib.sha256(data).hexdigest()


def write_manifest(repo, version, content):
    """schema 2 清单：资产大小固定 99.4 MB（只影响下载量显示），
    files 用真实内容 sha（决定增量与记录校正）。"""
    m = {
        "schema": 2, "app": "视频工具箱", "version": version,
        "released": "2026-10-10 23:03:23",
        "base_url": furi(repo),
        "assets": [{
            "name": "base", "file": "v%s-base.zip" % version,
            "size": 104239406, "sha256": "a" * 64, "entries": 1,
            "target": "", "desc": "主程序（必装）",
        }],
        "files": {"视频工具箱.exe": {"size": len(content),
                                    "sha256": sha(content),
                                    "pkg": "base"}},
        "parts": [], "updater": {"version": "1.19.0"}, "remove": [],
    }
    p = os.path.join(repo, "manifest-%s.json" % version)
    with open(p, "w", encoding="utf-8") as fh:
        json.dump(m, fh, ensure_ascii=False, indent=1)
    return p


def write_installed(install_dir, version, exe_sha):
    os.makedirs(install_dir, exist_ok=True)
    with open(os.path.join(install_dir, "vt_installed.json"), "w",
              encoding="utf-8") as fh:
        json.dump({"version": version, "written": "2026-10-10 23:03:23",
                   "files": {"视频工具箱.exe": {"size": 1024,
                                                "sha256": exe_sha}}},
                  fh, ensure_ascii=False, indent=1)


def installed_version(install_dir):
    core = u.load_core()[0]
    return (core.read_installed(install_dir) or {}).get("version", "")


def write_exe(install_dir, data):
    os.makedirs(install_dir, exist_ok=True)
    with open(os.path.join(install_dir, "视频工具箱.exe"), "wb") as fh:
        fh.write(data)


def write_src_version(install_dir, version):
    p = os.path.join(install_dir, "src", "video_toolbox_qt.py")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as fh:
        fh.write('# test fixture\nVERSION = "%s"\n' % version)


def check(install_dir, manifest, repo):
    return u.check_update(install_dir=install_dir, manifest_url=manifest,
                          base_url=furi(repo), source_mode=False)


def report(r):
    print("   local=%r record=%r remote=%r full=%s baseline=%r update=%s "
          "down=%s label=%s dl=%s" % (
              r.local_ver, r.record_ver, r.remote_ver, r.full,
              r.baseline_ver, r.update, r.downgrade(), r.action_label(),
              u._human(r.download_bytes)))


tmp = tempfile.mkdtemp(prefix="vt_upd_e2e_")
repo = os.path.join(tmp, "repo")
os.makedirs(repo)
RUN = u.SELF_VERSION
GOOD = b"z" * 1024
WRONG = b"w" * 1024
m_old = write_manifest(repo, "1.19.0", b"x" * 1024)
m_new = write_manifest(repo, "99.0.0", b"y" * 1024)
m_cur = write_manifest(repo, RUN, GOOD)

try:
    print("== 1) 安装版：目录空、远端 1.19.0（低于当前 %s）==" % RUN)
    empty = os.path.join(tmp, "install_empty")
    os.makedirs(empty)
    r = check(empty, m_old, repo)
    chk("检测成功", r.ok is True, r.err)
    report(r)
    chk("本地=未安装", r.local_ver == "未安装", r.local_ver)
    chk("远端=1.19.0", r.remote_ver == "1.19.0", r.remote_ver)
    chk("判为全新安装", r.full is True)
    chk("基准=运行版本", r.baseline_ver == RUN, r.baseline_ver)
    chk("判降级（1.19.0 < %s）" % RUN, r.downgrade() is True)
    chk("标题=安装较旧版本", r.action_label() == "安装较旧版本",
        r.action_label())
    chk("下载量=99.4 MB", u._human(r.download_bytes) == "99.4 MB",
        u._human(r.download_bytes))
    chk("组件=base", [n for n, _ in r.packages] == ["base"], r.packages)
    lines = "\n".join(r.detail_lines())
    chk("正文无 v未安装", "v未安装" not in lines, lines)
    chk("首行写当前运行版本 v%s" % RUN, ("v%s" % RUN) in lines, lines)
    chk("正文标明降级", "低于当前" in lines)

    print("\n== 2) 安装版：目录空、远端 99.0.0（高于当前）==")
    r = check(empty, m_new, repo)
    chk("检测成功", r.ok is True, r.err)
    report(r)
    chk("标题=全新安装", r.action_label() == "全新安装", r.action_label())
    chk("最新版本高于当前", r.downgrade() is False)

    print("\n== 3) 安装版：已装 %s、远端 1.19.0（回滚）==" % RUN)
    inst2 = os.path.join(tmp, "install_cur")
    write_installed(inst2, RUN, "a" * 64)
    r = check(inst2, m_old, repo)
    chk("检测成功", r.ok is True, r.err)
    report(r)
    chk("本地=%s" % RUN, r.local_ver == RUN, r.local_ver)
    chk("基准=%s" % RUN, r.baseline_ver == RUN, r.baseline_ver)
    chk("标题=回滚到旧版本", r.action_label() == "回滚到旧版本",
        r.action_label())
    chk("非全新安装", r.full is False)
    lines = r.detail_lines()
    chk("首行=当前版本：v%s" % RUN,
        lines[0] == "当前版本：v%s" % RUN, lines[0])

    print("\n== 4) 安装版：已装 1.18.0、远端 1.19.0（普通升级）==")
    inst1 = os.path.join(tmp, "install_118")
    write_installed(inst1, "1.18.0", "a" * 64)
    real_self = u.SELF_VERSION
    u.SELF_VERSION = "1.18.0"
    try:
        r = check(inst1, m_old, repo)
        chk("检测成功", r.ok is True, r.err)
        report(r)
        chk("标题=发现新版本", r.action_label() == "发现新版本",
            r.action_label())
        chk("基准=1.18.0", r.baseline_ver == "1.18.0", r.baseline_ver)
        lines = r.detail_lines()
    finally:
        u.SELF_VERSION = real_self
    chk("首行=当前版本：v1.18.0", lines[0] == "当前版本：v1.18.0", lines[0])
    chk("第二行=最新版本：v1.19.0", lines[1] == "最新版本：v1.19.0",
        lines[1])

    print("\n== 5) 源码模式：以本地开发版为准，不探测安装目录 ==")
    r = u.check_update(install_dir=os.path.join(tmp, "no_such_dir"),
                       manifest_url=m_new, base_url=furi(repo))
    chk("检测成功", r.ok is True, r.err)
    report(r)
    chk("source_mode=True", r.source_mode is True, r.source_mode)
    chk("判无更新", r.update is False, r.update)
    chk("基准=本地开发版 %s" % RUN, r.baseline_ver == RUN, r.baseline_ver)
    chk("当前版本=本地开发版", r.local_ver == RUN, r.local_ver)
    chk("不设置安装目录", r.install_dir == "", r.install_dir)
    chk("远端版本已读取", r.remote_ver == "99.0.0", r.remote_ver)
    chk("提示远端不同", r.remote_differs() is True)
    lines = r.detail_lines()
    chk("首行=当前版本：v%s（源码运行）" % RUN,
        lines[0] == "当前版本：v%s（源码运行）" % RUN, lines[0])
    chk("正文说明以本地为准", any("以本地开发版为准" in x for x in lines),
        lines)

    print("\n== 6) 安装版：记录 2.5.3、目录实际 %s（自动校正记录）==" % RUN)
    d = os.path.join(tmp, "install_reconcile")
    write_exe(d, GOOD)
    write_src_version(d, RUN)
    write_installed(d, "2.5.3", "c" * 64)
    r = check(d, m_cur, repo)
    chk("检测成功", r.ok is True, r.err)
    report(r)
    chk("判无更新（磁盘已一致）", r.update is False, r.update)
    chk("本地版本校正为 %s" % RUN, r.local_ver == RUN, r.local_ver)
    chk("记录版本回写为 %s" % RUN, r.record_ver == RUN, r.record_ver)
    chk("文件变迁=0", r.changed == 0, r.changed)
    chk("下载量=0", r.download_bytes == 0, r.download_bytes)
    chk("vt_installed.json 已更新", installed_version(d) == RUN,
        installed_version(d))

    print("\n== 7) 安装版：同版本但文件不一致（修复安装）==")
    d2 = os.path.join(tmp, "install_repair")
    write_exe(d2, WRONG)
    write_src_version(d2, RUN)
    write_installed(d2, "2.5.3", "c" * 64)
    r = check(d2, m_cur, repo)
    chk("检测成功", r.ok is True, r.err)
    report(r)
    chk("判为需修复", r.update is True, r.update)
    chk("标题=修复安装", r.action_label() == "修复安装", r.action_label())
    lines = r.detail_lines()
    chk("首行带安装记录版本",
        lines[0] == "当前版本：v%s（安装目录记录 v2.5.3）" % RUN, lines[0])
    chk("第二行标修复",
        lines[1] == "目标版本：v%s（与当前相同，将修复不一致文件）" % RUN,
        lines[1])
    chk("记录不被误写", installed_version(d2) == "2.5.3",
        installed_version(d2))

    print("\n== 8) 安装版：同版本且记录一致（短路，不哈希）==")
    d3 = os.path.join(tmp, "install_same")
    write_exe(d3, GOOD)
    write_src_version(d3, RUN)
    write_installed(d3, RUN, sha(GOOD))
    r = check(d3, m_cur, repo)
    chk("检测成功", r.ok is True, r.err)
    report(r)
    chk("判无更新", r.update is False, r.update)
    chk("下载量=0", r.download_bytes == 0, r.download_bytes)
    chk("安装目录已识别", r.install_dir == d3, r.install_dir)

    print("\n%s passed, %s failed" % (ok[0], bad[0]))
finally:
    shutil.rmtree(tmp, ignore_errors=True)

sys.exit(1 if bad[0] else 0)
