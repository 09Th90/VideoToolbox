#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# @version 2.7.0
"""自研「在线引导安装器」离线自检（不联网、不依赖任何第三方库）。

覆盖 packaging/online_release/ 的五个模块：
  · vt_dl.py            —— 多线程分块下载 / 断点续传 / 取消 / 镜像源链
  · vt_update_core.py   —— 清单解析 / 增量计划 / 分卷拼接 / 解压防护 /
                            暂存校验 / 原子落地与回滚 / 更新器自更新 / 安装目录
  · vt_version_index.py —— 版本号解析与比较 / 选择器 / 索引读写 / 通道解析
  · vt_online_setup.py  —— --check / --list-versions 两个无 UI 入口
  · build_online_release.py —— 组件打包（含分卷）/ 文件清单 / IFW 一致性

全部在临时目录里跑，走 `file://` 通道，不需要网络、也不需要先发一版。

铁律（项目口径）：只做正向校验的检查 = 没检查。本脚本每个关键路径都配了
「故意弄坏」的负向用例（坏 sha / 缺文件 / 篡改清单 / 落地失败回滚），
并对两个已修 bug 各配一条回归（3-arg progress 契约 ×2、换源后重试）。

运行：tools/python/python.exe scripts/dev/_selftest_online_setup.py
"""
import hashlib
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest.mock as mock
import zipfile
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OREL = os.path.join(ROOT, "packaging", "online_release")
sys.path.insert(0, OREL)

FAILS = []


def check(name, cond, extra=""):
    print("  [%s] %s%s" % ("PASS" if cond else "FAIL", name,
                          (" -> " + str(extra)) if extra else ""))
    if not cond:
        FAILS.append(name)


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


import vt_dl  # noqa: E402
import vt_update_core as core  # noqa: E402
import vt_version_index as vindex  # noqa: E402

_BOR = None


def bor():
    """build_online_release 单例（import 有打印副作用，只载一次）。"""
    global _BOR
    if _BOR is None:
        _BOR = load("_bor", os.path.join(OREL, "build_online_release.py"))
    return _BOR


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def furi(p):
    """本地路径 → file:// URL（Windows 安全）。"""
    return "file:///" + os.path.abspath(p).replace("\\", "/")


def _raises(exc, fn, *a, **kw):
    try:
        fn(*a, **kw)
    except exc:
        return True
    except Exception as e:  # noqa: BLE001
        print("      （抛了别的异常：%r）" % e)
        return False
    return False


def _qt_version():
    import re
    p = os.path.join(ROOT, "src", "video_toolbox_qt.py")
    return re.search(r'VERSION\s*=\s*"([\d.]+)"',
                     open(p, encoding="utf-8").read()).group(1)


def main():
    print("=" * 66)
    print("  在线引导安装器 自检（vt_dl / vt_update_core / vt_version_index"
          " / vt_online_setup / build）")
    print("=" * 66)
    tmp = tempfile.mkdtemp(prefix="vt_online_")
    try:
        t_manifest(tmp)
        t_utils(tmp)
        t_dl_engine(tmp)
        t_zip(tmp)
        t_install_dir(tmp)
        t_schema2_e2e(tmp)
        t_version_index(tmp)
        t_build_side(tmp)
        t_setup_cli(tmp)
        t_urls(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + "=" * 66)
    if FAILS:
        print("  结果：%d 项失败" % len(FAILS))
        for f in FAILS:
            print("   · " + f)
    else:
        print("  结果：全部通过")
    print("=" * 66)
    return 1 if FAILS else 0


# ---------------------------------------------------------------- 1) 清单
def t_manifest(tmp):
    print("\n== 1) 清单解析 ==")
    mf = os.path.join(tmp, "manifest.json")
    good = {"schema": 1, "app": "视频工具箱", "version": "9.9.9",
            "released": "2026-01-01 00:00:00",
            "base_url": furi(tmp),
            "assets": [{"name": "base", "file": "a.zip", "size": 1,
                        "sha256": "x", "target": ""}]}
    open(mf, "w", encoding="utf-8").write(json.dumps(good))
    m = core.load_manifest(mf)
    check("本地路径可读", m["version"] == "9.9.9", m["version"])
    check("file:// 前缀可读",
          core.load_manifest(furi(mf))["version"] == "9.9.9")
    check("资产 URL 拼接正确",
          core.asset_url(m, m["assets"][0]).endswith("/a.zip"),
          core.asset_url(m, m["assets"][0]))
    check("缺 base_url 时明确报错",
          _raises(core.UpdateError, core.asset_url,
                  {"base_url": ""}, {"file": "a.zip"}))
    for bad, why in (({"schema": 2}, "schema 不符"),
                     ({"schema": 1}, "缺 version/assets"),
                     ({"schema": 1, "version": "1", "assets": "x"},
                      "assets 类型错"),
                     ({"schema": 1, "version": "1", "assets": [],
                       "files": "x"}, "files 类型错")):
        p = os.path.join(tmp, "bad.json")
        open(p, "w", encoding="utf-8").write(json.dumps(bad))
        check("坏清单被拒（%s）" % why,
              _raises(core.UpdateError, core.load_manifest, p))
    p = os.path.join(tmp, "notjson.json")
    open(p, "w", encoding="utf-8").write("{oops")
    check("非 JSON 被拒", _raises(core.UpdateError, core.load_manifest, p))
    check("不存在的清单被拒",
          _raises(core.UpdateError, core.load_manifest,
                  os.path.join(tmp, "nope.json")))
    # 取不到远端清单必须报可读错误（走镜像链全败），不是崩溃
    check("远端清单取不到报 UpdateError（镜像链全败）",
          _raises(core.UpdateError, core.load_manifest,
                  "https://127.0.0.1:1/nonexistent-manifest.json"))


# ---------------------------------------------------------------- 2) 工具
def t_utils(tmp):
    print("\n== 2) 工具函数 ==")
    f = os.path.join(tmp, "x.bin")
    open(f, "wb").write(b"hello")
    check("sha256 与 hashlib 一致",
          core.sha256_file(f) == hashlib.sha256(b"hello").hexdigest())
    seen = []
    core.sha256_file(f, progress=lambda d, t: seen.append((d, t)))
    check("sha256 进度回调被调用", seen and seen[-1] == (5, 5), seen)
    check("human 可读", core.human(1536) == "1.5 KB", core.human(1536))
    check("ver_tuple", core.ver_tuple("1.20.3") == (1, 20, 3)
          and core.ver_tuple("x") == (0, 0, 0))
    a = {"name": "p", "file": "v1-p.zip",
         "parts": ["v1-p.zip.001", "v1-p.zip.002"]}
    check("asset_parts 取 parts", core.asset_parts({}, a) == a["parts"])
    check("asset_parts 无 parts 时退化",
          core.asset_parts({}, {"file": "z.zip"}) == ["z.zip"])


# ---------------------------------------------------------------- 3) 下载引擎
def t_dl_engine(tmp):
    print("\n== 3) 下载引擎 vt_dl ==")
    check("空文件返回空块表", vt_dl.plan_chunks(0) == [])
    check("小文件单块", vt_dl.plan_chunks(4096) == [(0, 4096)])
    big = vt_dl.plan_chunks(200 * 1024 * 1024, threads=8)
    check("大文件分块数 ≈ 线程×16", len(big) == 128, len(big))
    check("分块全覆盖不重叠",
          sum(e - s for s, e in big) == 200 * 1024 * 1024
          and big[0][0] == 0 and big[-1][1] == 200 * 1024 * 1024
          and all(big[i][1] == big[i + 1][0] for i in range(len(big) - 1)))
    check("块长夹在 [MIN,MAX]",
          all(vt_dl.MIN_CHUNK <= (e - s) <= vt_dl.MAX_CHUNK for s, e in big))

    sp = os.path.join(tmp, "st.dlstate")
    st = vt_dl.DlState(sp, 100)
    st.mark(2)
    st.mark(5)
    st.save()
    st2 = vt_dl.DlState.load(sp, 100)
    check("DlState 存取 done", sorted(st2.done) == [2, 5], st2.done)
    check("size 变了旧状态作废", not vt_dl.DlState.load(sp, 200).done)
    st.drop()
    check("DlState.drop 清文件", not os.path.exists(sp))
    open(sp, "w", encoding="utf-8").write("{oops")
    check("DlState 损坏从头下", not vt_dl.DlState.load(sp, 100).done)

    ch = vt_dl.source_chain(furi(tmp), allow_proxy=False)
    check("file:// 单源不套镜像",
          len(ch) == 1 and ch[0].label == "本地文件")
    ch = vt_dl.source_chain(
        "https://github.com/o/r/releases/download/t/a.zip", allow_proxy=False)
    check("GitHub URL 带 gh-proxy 镜像",
          [s.label for s in ch] == ["直连", "gh-proxy 镜像"],
          [s.label for s in ch])
    ch = vt_dl.source_chain("https://example.com/a.zip", allow_proxy=False)
    check("非 GitHub 不套镜像", len(ch) == 1)
    check("is_github_url",
          vt_dl.is_github_url("https://github.com/a/b")
          and vt_dl.is_github_url("https://raw.githubusercontent.com/a/b")
          and not vt_dl.is_github_url("https://example.com/github.com/x"))

    src9 = os.path.join(tmp, "src9.bin")
    open(src9, "wb").write(os.urandom(9 * 1024 * 1024 + 12345))
    pr = vt_dl.probe_source(vt_dl.Source("f", furi(src9), None))
    check("probe file:// 拿得到大小与 Range",
          pr.size == os.path.getsize(src9) and pr.ranged and not pr.err,
          (pr.size, pr.ranged, pr.err))

    dst = os.path.join(tmp, "out", "dst9.bin")
    prog_seen = []
    vt_dl.download_file(furi(src9), dst,
                        progress=lambda d, t: prog_seen.append((d, t)))
    check("多线程下载内容一致", sha(dst) == sha(src9))
    check("引擎 progress 是 (done,total) 2 arg 且总量正确",
          prog_seen and prog_seen[-1][1] == os.path.getsize(src9)
          and all(isinstance(d, int) and isinstance(t, int)
                  for d, t in prog_seen), len(prog_seen))
    check("成功后不留 .dlpart/.dlstate",
          not os.path.exists(dst + ".dlpart")
          and not os.path.exists(dst + ".dlstate"))

    # -- 取消 + 续传 --
    evt = threading.Event()
    orig_read = vt_dl._read_range
    hook = {"done": False}

    def hooked(s, a, b, cancel):
        if not hook["done"]:
            hook["done"] = True
            cancel.set()      # 第一块读到一半就取消
        return orig_read(s, a, b, cancel)

    vt_dl._read_range = hooked
    try:
        check("取消抛 Canceled",
              _raises(vt_dl.Canceled, vt_dl.download_file, furi(src9),
                      os.path.join(tmp, "out", "c.bin"), cancel=evt))
    finally:
        vt_dl._read_range = orig_read
    cbin = os.path.join(tmp, "out", "c.bin")
    check("取消后保留续传状态",
          os.path.exists(cbin + ".dlpart") and os.path.exists(cbin + ".dlstate"))
    check("取消后不落地正式文件", not os.path.exists(cbin))
    vt_dl.download_file(furi(src9), cbin, cancel=threading.Event())
    check("续跑补块后完整", sha(cbin) == sha(src9))

    # -- sha256 不符：整文件重下后仍不符才报错 --
    bad = os.path.join(tmp, "out", "bad.bin")
    check("sha256 不符报 DlError",
          _raises(vt_dl.DlError, vt_dl.download_file, furi(src9), bad,
                  expect_sha256="0" * 64))
    check("sha256 不符不落地", not os.path.exists(bad))

    # -- download_simple（无 Range 退化通道；file:// 也可跑）--
    src_small = os.path.join(tmp, "small.bin")
    open(src_small, "wb").write(os.urandom(300000))
    d2 = os.path.join(tmp, "out", "small.bin")
    vt_dl.download_simple(furi(src_small), d2)
    check("download_simple 内容一致", sha(d2) == sha(src_small))
    check("download_simple sha 不符报错",
          _raises(vt_dl.DlError, vt_dl.download_simple, furi(src_small),
                  os.path.join(tmp, "out", "s2.bin"), expect_sha256="1" * 64))


# ---------------------------------------------------------------- 4) zip
def t_zip(tmp):
    print("\n== 4) zip 解压与防护 ==")
    z = os.path.join(tmp, "t.zip")
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("a.txt", "A")
        zf.writestr("sub/b.txt", "B")
        zf.writestr("__MACOSX/._junk", "junk")
    dest = os.path.join(tmp, "ex")
    n = core.extract_zip(z, dest)
    check("解开文件数 = 2（__MACOSX 被跳过）", n == 2, n)
    check("顶层文件到位", open(os.path.join(dest, "a.txt")).read() == "A")
    check("子目录文件到位",
          open(os.path.join(dest, "sub", "b.txt")).read() == "B")

    evil = os.path.join(tmp, "evil.zip")
    with zipfile.ZipFile(evil, "w") as zf:
        zf.writestr("../escaped.txt", "bad")
    check("路径穿越被拒绝",
          _raises(core.UpdateError, core.extract_zip, evil,
                  os.path.join(tmp, "ex2")))
    check("穿越文件没被写出",
          not os.path.exists(os.path.join(tmp, "escaped.txt")))
    abs_zip = os.path.join(tmp, "abs.zip")
    with zipfile.ZipFile(abs_zip, "w") as zf:
        zf.writestr("/abs.txt", "bad")
    check("绝对路径被拒绝",
          _raises(core.UpdateError, core.extract_zip, abs_zip,
                  os.path.join(tmp, "ex3")))
    badzip = os.path.join(tmp, "bad.zip")
    open(badzip, "wb").write(b"not a zip")
    check("损坏 zip 报可读错误",
          _raises(core.UpdateError, core.extract_zip, badzip,
                  os.path.join(tmp, "ex4")))


# ---------------------------------------------------------------- 5) 安装目录
def t_install_dir(tmp):
    print("\n== 5) 安装目录与空间 ==")
    check("detect_install_dir 返回 str", isinstance(core.detect_install_dir(), str))
    check("default_install_dir 返回 str",
          isinstance(core.default_install_dir(), str))
    d = core.pick_default_dir(drives=("Z:",))
    check("pick_default_dir 无可用盘时兜 LOCALAPPDATA", "Programs" in d, d)
    check("DEFAULT_DIR 是 D 盘（产品口径）",
          core.DEFAULT_DIR.lower().startswith("d:"), core.DEFAULT_DIR)
    check("FALLBACK_DRIVES D 优先", core.FALLBACK_DRIVES[0] == "D:")
    check("空间检查：需要 1 字节时通过", core.free_space_ok(tmp, 1))
    check("空间检查：需要 1PB 时不通过",
          core.free_space_ok(tmp, 1 << 50) is False)
    check("app_running 返回 bool", isinstance(core.app_running(tmp), bool))
    check("create_shortcuts(False,False) 不建也不炸",
          core.create_shortcuts(tmp, desktop=False, start_menu=False) == 0)
    check("_drive_usable 对可写目录为真", core._drive_usable(tmp))


# ---------------------------------------------------------------- 6) schema 2 端到端
def t_schema2_e2e(tmp):
    print("\n== 6) schema 2 端到端（真打包→安装→增量→降级→回滚）==")
    b = bor()

    src = os.path.join(tmp, "srcdata")
    os.makedirs(os.path.join(src, "app"))
    os.makedirs(os.path.join(src, "code", "sub"))
    os.makedirs(os.path.join(src, "docs"))
    open(os.path.join(src, "app", "视频工具箱.exe"), "wb").write(os.urandom(300000))
    open(os.path.join(src, "code", "a.py"), "w",
         encoding="utf-8").write("x=1\n")
    open(os.path.join(src, "code", "sub", "b.py"), "w",
         encoding="utf-8").write("y=2\n")
    open(os.path.join(src, "docs", "readme.txt"), "w",
         encoding="utf-8").write("hello\n")
    out = os.path.join(tmp, "rel")
    os.makedirs(out)

    def build_all():
        a_app, f_app = b.build_package(
            "app", [(os.path.join(src, "app"), "app")], out, 1 << 30)
        a_code, f_code = b.build_package(
            "code", [(os.path.join(src, "code"), "code")], out, 1 << 30)
        a_docs, f_docs = b.build_package(
            "docs", [(os.path.join(src, "docs"), "docs")], out, 1 << 30)
        files = {}
        files.update(f_app)
        files.update(f_code)
        files.update(f_docs)
        return [a_app, a_code, a_docs], files

    assets, files_all = build_all()
    man = {"schema": 2, "version": "9.9.9", "base_url": furi(out),
           "assets": assets, "files": files_all, "remove": [], "notes": "t"}
    logs = []

    # ---- 全量安装 ----
    tgt = os.path.join(tmp, "install")
    res = core.apply_update(man, tgt, os.path.join(tmp, "cache"), log=logs.append)
    check("全量安装文件数正确", res["files"] == len(files_all),
          (res["files"], len(files_all)))
    check("exe 字节一致",
          sha(os.path.join(tgt, "app", "视频工具箱.exe")) == sha(
              os.path.join(src, "app", "视频工具箱.exe")))
    check("子目录文件到位",
          os.path.isfile(os.path.join(tgt, "code", "sub", "b.py")))
    check("写入本地安装清单",
          os.path.isfile(os.path.join(tgt, core.INSTALLED_NAME)))
    check("成功后清掉下载缓存",
          not os.path.isfile(os.path.join(tmp, "cache", assets[0]["file"])))

    # ---- 无变化 → 什么都不下 ----
    res2 = core.apply_update(man, tgt, os.path.join(tmp, "cache2"),
                             log=logs.append)
    check("无变化时 files=0", res2["files"] == 0 and res2["downloaded"] == 0,
          res2)

    # ---- 增量：只改 code 包一个文件 ----
    open(os.path.join(src, "code", "a.py"), "w",
         encoding="utf-8").write("x=999\n")
    assets2, files2 = build_all()
    man2 = dict(man, assets=assets2, files=files2)
    plan = core.plan_update(man2, tgt)
    check("增量计划只下 code 包",
          [a["name"] for a in plan["need"]] == ["code"],
          [a["name"] for a in plan["need"]])
    check("增量计划 changed 只列变动文件",
          plan["changed"] == ["code/a.py"], plan["changed"])
    check("app 包计入跳过", plan["skip_bytes"] > 0, plan["skip_bytes"])
    exe_mtime = os.path.getmtime(os.path.join(tgt, "app", "视频工具箱.exe"))
    core.apply_update(man2, tgt, os.path.join(tmp, "cache3"), log=logs.append)
    check("未变文件不被重下（mtime 不变）",
          os.path.getmtime(os.path.join(tgt, "app", "视频工具箱.exe"))
          == exe_mtime)
    check("变动文件已更新",
          open(os.path.join(tgt, "code", "a.py"), encoding="utf-8").read()
          == "x=999\n")

    # ---- remove 列表 ----
    core.apply_update(dict(man2, remove=["docs/readme.txt"]), tgt,
                      os.path.join(tmp, "cache4"), log=logs.append)
    check("remove 列表生效",
          not os.path.exists(os.path.join(tgt, "docs", "readme.txt")))

    # ---- 降级：目标版本不含 docs → 孤儿清理 ----
    # ⚠ build_all() 是确定性文件名覆盖写：manifest 必须始终引用「out 目录
    # 当前内容」。前面 416 行重建过 code.zip（a.py 变了），第一次构建的
    # man/assets 里的 code 包 sha 已失效——直接拿来装，引擎会正确地报
    # sha 不符（那等于测试自己制造了一个坏资产）。所以这里先重建再装。
    tgt2 = os.path.join(tmp, "install2")
    assets_f, files_f = build_all()
    man_full = {"schema": 2, "version": "9.9.9", "base_url": furi(out),
                "assets": assets_f, "files": files_f, "remove": []}
    core.apply_update(man_full, tgt2, os.path.join(tmp, "cache5"),
                      log=logs.append)
    files_nd = {k: v for k, v in files_f.items() if not k.startswith("docs/")}
    assets_nd = [a for a in assets_f if a["name"] != "docs"]
    man_down = {"schema": 2, "version": "9.9.8", "base_url": furi(out),
                "assets": assets_nd, "files": files_nd, "remove": []}
    plan_d = core.plan_update(man_down, tgt2)
    check("降级算出孤儿文件", "docs/readme.txt" in plan_d["orphans"],
          plan_d["orphans"])
    core.apply_update(man_down, tgt2, os.path.join(tmp, "cache6"),
                      log=logs.append)
    check("孤儿文件被清理",
          not os.path.exists(os.path.join(tgt2, "docs", "readme.txt")))

    # ---- updater 自更新（3-arg progress 契约回归）----
    up_name = "视频工具箱_在线安装_v9.9.9.exe"
    up_path = os.path.join(out, up_name)
    open(up_path, "wb").write(os.urandom(2048))
    up_sha = sha(up_path)
    man_u = dict(man, updater={"file": up_name, "size": 2048, "sha256": up_sha})
    tgt3 = os.path.join(tmp, "install3")
    prog3 = []
    p = core.ensure_updater(man_u, tgt3, os.path.join(tmp, "cache7"),
                            progress=lambda s, d, t: prog3.append((s, d, t)))
    check("updater 下载落地",
          p == os.path.join(tgt3, up_name) and sha(p) == up_sha)
    check("updater progress 是 (str,int,int)（回归：曾经的 TypeError）",
          prog3 and all(isinstance(s, str) and isinstance(d, int)
                        and isinstance(t, int) for s, d, t in prog3), prog3[:2])
    man_u2 = dict(man_u, base_url=furi(os.path.join(tmp, "nowhere")))
    check("updater 已最新时不重下",
          core.ensure_updater(man_u2, tgt3, os.path.join(tmp, "cache7")) == p)
    man_u3 = dict(man_u, updater={"file": up_name, "size": 2048,
                                  "sha256": "0" * 64})
    check("updater sha 不符报错",
          _raises(core.UpdateError, core.ensure_updater, man_u3,
                  os.path.join(tmp, "install4"), os.path.join(tmp, "cache8")))

    # ---- 分卷：切卷 + 客户端拼接还原 ----
    bigsrc = os.path.join(tmp, "bigsrc")
    os.makedirs(bigsrc)
    open(os.path.join(bigsrc, "data.bin"), "wb").write(os.urandom(2500000))
    out2 = os.path.join(tmp, "rel2")
    os.makedirs(out2)
    a_big, f_big = b.build_package(
        "big", [(os.path.join(bigsrc, "data.bin"), "big/data.bin")],
        out2, 1 << 20)
    check("超限包被切卷", len(a_big.get("parts") or []) >= 2, a_big.get("parts"))
    check("切卷后 file 是还原名",
          a_big["file"] == "v%s-big.zip" % _qt_version(), a_big["file"])
    man_p = {"schema": 2, "version": "9.9.9", "base_url": furi(out2),
             "assets": [a_big], "files": f_big, "remove": []}
    prog_p = []

    def prog_pf(stage, d, t):
        prog_p.append((stage, d, t))

    tgt5 = os.path.join(tmp, "install5")
    res_p = core.apply_update(man_p, tgt5, os.path.join(tmp, "cache9"),
                              progress=prog_pf, log=logs.append)
    check("分卷包安装成功", res_p["files"] == 1, res_p)
    check("分卷拼接后内容一致",
          sha(os.path.join(tgt5, "big", "data.bin")) == sha(
              os.path.join(bigsrc, "data.bin")))
    check("分卷路径 progress 也是 (str,int,int)（回归：曾经的 UI TypeError）",
          prog_p and all(isinstance(s, str) and isinstance(d, int)
                         and isinstance(t, int) for s, d, t in prog_p),
          prog_p[:2])

    # ---- 负向：坏 asset sha / 篡改 files sha / 清单缺文件 ----
    man_bad_zip = dict(man, assets=[dict(assets[0], sha256="0" * 64)]
                       + assets[1:])
    check("asset sha 不符时中止",
          _raises(core.UpdateError, core.apply_update, man_bad_zip,
                  os.path.join(tmp, "i_bad1"), os.path.join(tmp, "c_bad1")))
    check("asset sha 不符不落地",
          not os.path.exists(os.path.join(tmp, "i_bad1", "app")))
    files_liar = dict(files_all)
    files_liar["code/a.py"] = dict(files_all["code/a.py"], sha256="1" * 64)
    check("files 清单被篡改时落地前拦截",
          _raises(core.UpdateError, core.apply_update,
                  dict(man, files=files_liar),
                  os.path.join(tmp, "i_bad2"), os.path.join(tmp, "c_bad2")))
    check("拦截后不落任何文件",
          not os.path.exists(os.path.join(tmp, "i_bad2", "code", "a.py")))
    files_ghost = dict(files_all)
    files_ghost["code/ghost.py"] = {"size": 1, "sha256": "2" * 64,
                                    "pkg": "code"}
    check("清单里有、包里没有的文件被拒",
          _raises(core.UpdateError, core.apply_update,
                  dict(man, files=files_ghost),
                  os.path.join(tmp, "i_bad3"), os.path.join(tmp, "c_bad3")))

    # ---- 落地失败整体回滚（mock shutil.move 第二步炸）----
    tgt6 = os.path.join(tmp, "install6")
    os.makedirs(os.path.join(tgt6, "code"))
    open(os.path.join(tgt6, "code", "a.py"), "w",
         encoding="utf-8").write("OLD\n")
    open(os.path.join(tgt6, "code", "sub_b.py"), "w",
         encoding="utf-8").write("OLD2\n")
    stg6 = os.path.join(tmp, "stg6", "code")
    os.makedirs(stg6)
    open(os.path.join(stg6, "a.py"), "w", encoding="utf-8").write("NEW\n")
    open(os.path.join(stg6, "sub_b.py"), "w", encoding="utf-8").write("NEW2\n")
    files6 = {"code/a.py": {"size": 4, "sha256": sha(os.path.join(stg6,
                                                                 "a.py")),
                            "pkg": "code"},
              "code/sub_b.py": {"size": 5,
                                "sha256": sha(os.path.join(stg6, "sub_b.py")),
                                "pkg": "code"}}
    real_move = shutil.move
    calls = {"n": 0}

    def flaky(s, d):
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("磁盘被故意弄坏")
        return real_move(s, d)

    with mock.patch.object(shutil, "move", flaky):
        check("落地失败抛 UpdateError",
              _raises(core.UpdateError, core.apply_staging,
                      os.path.join(tmp, "stg6"), tgt6,
                      dict(man, files=files6), {"code"}))
    check("回滚后旧文件原样恢复",
          open(os.path.join(tgt6, "code", "a.py"), encoding="utf-8").read()
          == "OLD\n"
          and open(os.path.join(tgt6, "code", "sub_b.py"),
                   encoding="utf-8").read() == "OLD2\n")
    check("回滚后不留 .vtold 残骸",
          not os.path.exists(os.path.join(tgt6, "code", "a.py.vtold"))
          and not os.path.exists(os.path.join(tgt6, "code", "sub_b.py.vtold")))

    # ---- schema 1 兼容（无 files → 全量直解）----
    pkg1 = os.path.join(tmp, "pkg1")
    os.makedirs(pkg1)
    open(os.path.join(pkg1, "old.txt"), "w", encoding="utf-8").write("v1\n")
    zp1 = os.path.join(tmp, "v9.9.9-base.zip")
    with zipfile.ZipFile(zp1, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(os.path.join(pkg1, "old.txt"), "old.txt")
    man_s1 = {"schema": 1, "version": "9.9.9", "base_url": furi(tmp),
              "assets": [{"name": "base", "file": os.path.basename(zp1),
                          "size": os.path.getsize(zp1), "sha256": sha(zp1),
                          "target": ""}]}
    tgt7 = os.path.join(tmp, "install7")
    res7 = core.apply_update(man_s1, tgt7, os.path.join(tmp, "cache10"),
                             log=logs.append)
    check("schema 1 全量直解", res7["files"] == 1
          and open(os.path.join(tgt7, "old.txt"), encoding="utf-8").read()
          == "v1\n", res7)
    check("schema 1 判全量", core.plan_update(man_s1, tgt7)["full"] is True)


# ---------------------------------------------------------------- 7) 版本索引
def t_version_index(tmp):
    print("\n== 7) 版本索引（全版本通用）==")
    check("parse 缺位补 0", vindex.parse_version("1.20") == ((1, 20, 0), ()))
    check("cmp 正式版 > 预发布",
          vindex.cmp_version("1.20.0", "1.20.0-beta.1") > 0)
    check("cmp 预发布按段数值",
          vindex.cmp_version("1.0.0-beta.2", "1.0.0-beta.10") < 0)
    check("cmp 1.20 == 1.20.0", vindex.cmp_version("1.20", "1.20.0") == 0)
    check("cmp 主版本优先", vindex.cmp_version("2.0.0", "1.99.99") > 0)
    check("v 前缀可解析", vindex.parse_version("v1.2.3") == ((1, 2, 3), ()))
    check("坏版本号当场炸（不静默降级）",
          _raises(vindex.VersionError, vindex.parse_version, "abc"))

    for sel, ver, want in (("^1.20.0", "1.20.5", True),
                           ("^1.20.0", "2.0.0", False),
                           ("~1.20.0", "1.20.9", True),
                           ("~1.20.0", "1.21.0", False),
                           (">=1.19", "1.19.0", True),
                           (">=1.19", "1.18.9", False),
                           ("<2.0.0", "1.99.99", True),
                           ("==1.20.0", "1.20.0", True),
                           ("!=1.20.0", "1.20.0", False),
                           ("1.20", "1.20.7", True),
                           ("1.20", "1.21.0", False),
                           ("1.20.0", "1.20.0", True),
                           ("1.20.0", "1.20.1", False),
                           ("", "9.9.9", True)):
        check("选择器 %-9s vs %-8s → %s" % (sel, ver, want),
              vindex.match_selector(ver, sel) is want)
    check("坏选择器抛错",
          _raises(vindex.VersionError, vindex.match_selector, "1.0.0", "~~x"))

    idx = vindex.new_index("视频工具箱", "https://example.invalid/rel/")
    vindex.upsert_version(idx, {"version": "1.19.0", "state": "stable"})
    vindex.upsert_version(idx, {"version": "1.20.0", "state": "stable"})
    vindex.upsert_version(idx, {"version": "1.21.0-beta.1",
                                "state": "prerelease"})
    check("upsert 后降序",
          [e["version"] for e in idx["versions"]]
          == ["1.21.0-beta.1", "1.20.0", "1.19.0"],
          [e["version"] for e in idx["versions"]])
    check("latest 指向最高版", idx["channels"]["latest"] == "1.21.0-beta.1")
    check("stable 指向最高正式版", idx["channels"]["stable"] == "1.20.0")
    check("默认补 manifest 名",
          vindex.find_version(idx, "1.19.0")["manifest"]
          == "manifest-1.19.0.json")
    vindex.upsert_version(idx, {"version": "1.18.0", "state": "stable"})
    check("回滚发布不动 latest", idx["channels"]["latest"] == "1.21.0-beta.1")
    check("resolve latest", vindex.resolve(idx)["version"] == "1.21.0-beta.1")
    check("resolve stable", vindex.resolve(idx, "stable")["version"]
          == "1.20.0")
    check("resolve 精确", vindex.resolve(idx, "1.19.0")["version"] == "1.19.0")
    check("resolve 范围取最高",
          vindex.resolve(idx, "<1.20")["version"] == "1.19.0")
    check("resolve 不存在抛错",
          _raises(vindex.VIndexError, vindex.resolve, idx, "7.7.7"))

    vindex.upsert_version(idx, {"version": "1.20.1", "state": "yanked"})
    check("yanked 默认不可选",
          _raises(vindex.VIndexError, vindex.resolve, idx, "1.20.1"))
    check("yanked allow_hidden 可选",
          vindex.resolve(idx, "1.20.1", allow_hidden=True)["version"]
          == "1.20.1")
    check("visible_versions 滤掉 yanked",
          "1.20.1" not in [e["version"]
                           for e in vindex.visible_versions(idx)])
    idx2 = vindex.new_index()
    vindex.upsert_version(idx2, {"version": "1.20.0", "state": "stable"})
    vindex.upsert_version(idx2, {"version": "1.21.0", "state": "yanked"})
    check("latest 被撤回时退化到可见最高",
          vindex.resolve(idx2)["version"] == "1.20.0")
    idx3 = vindex.new_index()
    vindex.upsert_version(idx3, {"version": "1.19.0", "state": "stable"})
    vindex.upsert_version(idx3, {"version": "1.20.0", "state": "yanked"})
    idx3["channels"]["stable"] = "1.20.0"
    check("stable 被撤回时退化（回归）",
          vindex.resolve(idx3, "stable")["version"] == "1.19.0")

    p = os.path.join(tmp, "index.json")
    vindex.save_index(idx, p)
    check("save→load 往返一致",
          [e["version"] for e in vindex.load_index(p)["versions"]]
          == [e["version"] for e in idx["versions"]])
    check("load_index 认 file://", vindex.load_index(furi(p))["schema"] == 1)
    bad = os.path.join(tmp, "bad_index.json")
    open(bad, "w", encoding="utf-8").write('{"schema": 99, "versions": []}')
    check("坏 schema 索引被拒",
          _raises(vindex.VIndexError, vindex.load_index, bad))
    open(bad, "w", encoding="utf-8").write('{"schema": 1}')
    check("缺 versions 被拒",
          _raises(vindex.VIndexError, vindex.load_index, bad))
    open(bad, "w", encoding="utf-8").write(
        '{"schema":1,"versions":[{"version":"x"}]}')
    check("非法版本号被拒",
          _raises(vindex.VIndexError, vindex.load_index, bad))
    check("manifest_url / index_url",
          vindex.manifest_url(idx, {"version": "1.20.0"})
          == "https://example.invalid/rel/manifest-1.20.0.json"
          and vindex.index_url("https://example.invalid/rel")
          == "https://example.invalid/rel/index.json")
    check("summarize 有文本", "v1.20.0" in vindex.summarize(idx))

    # -- resolve_manifest：装任意版本（本地索引 + 每版本清单）--
    # ⚠ build_package 的文件名是 v<项目版本>-<包名>.zip 确定性生成：同一
    # out 目录下打第二个「逻辑版本」会覆盖第一个的 zip。每个版本用独立
    # 子目录放资产，manifest 自己的 base_url 指向它（resolve_manifest 里
    # manifest 自带 base_url 优先于索引 base_url），清单 JSON 仍放索引目录。
    out3 = os.path.join(tmp, "rel3")
    os.makedirs(out3)

    def pub(ver, content):
        sd = os.path.join(tmp, "src_" + ver)
        os.makedirs(sd)
        open(os.path.join(sd, "mark.txt"), "w",
             encoding="utf-8").write(content)
        vdir = os.path.join(out3, "v" + ver)
        os.makedirs(vdir)
        a_v, f_v = bor().build_package(
            "app", [(os.path.join(sd, "mark.txt"), "mark.txt")], vdir, 1 << 30)
        mv = {"schema": 2, "version": ver, "base_url": furi(vdir),
              "assets": [a_v], "files": f_v, "remove": []}
        open(os.path.join(out3, "manifest-%s.json" % ver), "w",
             encoding="utf-8").write(json.dumps(mv, ensure_ascii=False))

    pub("9.9.8", "EIGHT")
    pub("9.9.9", "NINE")
    idx4 = vindex.new_index("视频工具箱", furi(out3))
    vindex.upsert_version(idx4, {"version": "9.9.8", "state": "stable"})
    vindex.upsert_version(idx4, {"version": "9.9.9", "state": "stable"})
    vindex.save_index(idx4, os.path.join(out3, "index.json"))
    m8, e8 = core.resolve_manifest(
        "9.9.8", index_url=os.path.join(out3, "index.json"))
    check("resolve_manifest 精确版本",
          m8["version"] == "9.9.8" and e8["version"] == "9.9.8",
          m8.get("version"))
    m9, _ = core.resolve_manifest(
        "latest", index_url=os.path.join(out3, "index.json"))
    check("resolve_manifest latest 走索引", m9["version"] == "9.9.9")
    # min_updater 门槛
    pub("9.9.7", "SEVEN")
    idx_hi = vindex.load_index(os.path.join(out3, "index.json"))
    vindex.upsert_version(idx_hi, {"version": "9.9.7", "state": "stable",
                                   "min_updater": "99.0.0"})
    vindex.save_index(idx_hi, os.path.join(out3, "index.json"))
    check("min_updater 不满足被拒",
          _raises(core.UpdateError, core.resolve_manifest, "9.9.7",
                  index_url=os.path.join(out3, "index.json")))
    idx_lo = vindex.load_index(os.path.join(out3, "index.json"))
    vindex.find_version(idx_lo, "9.9.7")["min_updater"] = "1.0.0"
    vindex.save_index(idx_lo, os.path.join(out3, "index.json"))
    m7, _ = core.resolve_manifest(
        "9.9.7", index_url=os.path.join(out3, "index.json"))
    check("min_updater 满足后可装", m7["version"] == "9.9.7")
    tgt8 = os.path.join(tmp, "install8")
    core.apply_update(m8, tgt8, os.path.join(tmp, "cache11"))
    check("装 9.9.8 得到 9.9.8 的内容",
          open(os.path.join(tgt8, "mark.txt"), encoding="utf-8").read()
          == "EIGHT")


# ---------------------------------------------------------------- 8) 打包侧
def t_build_side(tmp):
    print("\n== 8) 打包侧 ==")
    b = bor()
    check("读到的版本号与 qt 源码一致",
          b.read_version() == _qt_version(), b.read_version())
    items = list(b.iter_files(os.path.join(ROOT, "src"), "src"))
    check("iter_files 能枚举 src/", len(items) > 5, len(items))
    check("iter_files 排除 __pycache__/.pyc",
          not any(p.endswith((".pyc", ".pyo")) or "__pycache__" in p
                  for _a, p in items))
    check("禁止项清单非空且含 github_proxy",
          "github_proxy.yaml" in b.FORBIDDEN)
    check("STORE_OVER 阈值合理（>1MB）", b.STORE_OVER > 1048576)
    check("默认 tag 是固定 tag（非版本号）", b.DEFAULT_TAG == "repo-latest")
    check("单卷上限 1.5GB（留足 GitHub 2GB 余量）",
          b.DEFAULT_VOLUME_MAX == int(1.5 * 1024 ** 3))
    check("zip 时间戳固定（同内容可判等）",
          b.ZIP_DATE_TIME == (2026, 1, 1, 0, 0, 0))
    check("PACKAGES 四包且源不重叠",
          set(b.PACKAGES) == {"app", "code", "docs", "tools"}
          and len([x for v in b.PACKAGES.values() for x in v])
          == len({x for v in b.PACKAGES.values() for x in v}))
    try:
        b.check_packages_in_sync()
        check("发布清单与 IFW 版一致（同源校验通过）", True)
    except SystemExit as e:
        check("发布清单与 IFW 版一致（同源校验通过）", False, e)


# ---------------------------------------------------------------- 9) setup CLI
def t_setup_cli(tmp):
    print("\n== 9) vt_online_setup 无 UI 入口 ==")
    import vt_online_setup as setup
    # 造一个最小的 schema 2 发布（文件 + zip + manifest）
    sd = os.path.join(tmp, "cli_src")
    os.makedirs(sd)
    open(os.path.join(sd, "mark.txt"), "w", encoding="utf-8").write("CLI\n")
    cli_rel = os.path.join(tmp, "cli_rel")
    os.makedirs(cli_rel)
    a_v, f_v = bor().build_package(
        "app", [(os.path.join(sd, "mark.txt"), "mark.txt")],
        cli_rel, 1 << 30)
    mf = os.path.join(cli_rel, "manifest.json")
    man = {"schema": 2, "version": "9.9.9",
           "base_url": furi(cli_rel),
           "assets": [a_v], "files": f_v, "remove": []}
    open(mf, "w", encoding="utf-8").write(json.dumps(man, ensure_ascii=False))

    def args(**kw):
        base = dict(version="", index="", manifest=mf, base_url="", dir="",
                    allow_hidden=False)
        base.update(kw)
        return SimpleNamespace(**base)

    tgt = os.path.join(tmp, "cli_install")
    check("--check 未安装 → 10（有更新）",
          setup.run_check(args(dir=tgt)) == 10)
    core.apply_update(man, tgt, os.path.join(tmp, "cli_cache"))
    check("--check 已最新 → 0",
          setup.run_check(args(dir=tgt)) == 0)
    check("--check 坏清单 → 2",
          setup.run_check(args(manifest=os.path.join(tmp, "nope.json"))) == 2)

    # -- 带 --version 的检查必须走索引（resolve_manifest 既定路由：具体
    #    版本 ⇒ index；不给 index 会去打默认远端地址，离线自检里那是纯
    #    网络噪音）。造一个含 9.9.8/9.9.9 的真索引 + 每版本清单。
    #    ⚠ build_package 文件名确定性：9.9.8 的资产放独立子目录。
    sd8 = os.path.join(tmp, "cli_src8")
    os.makedirs(sd8)
    open(os.path.join(sd8, "mark.txt"), "w",
         encoding="utf-8").write("EIGHT\n")
    rel8 = os.path.join(tmp, "cli_rel8")
    os.makedirs(rel8)
    a8, f8 = bor().build_package(
        "app", [(os.path.join(sd8, "mark.txt"), "mark.txt")], rel8, 1 << 30)
    man8 = {"schema": 2, "version": "9.9.8", "base_url": furi(rel8),
            "assets": [a8], "files": f8, "remove": []}
    open(os.path.join(cli_rel, "manifest-9.9.8.json"), "w",
         encoding="utf-8").write(json.dumps(man8, ensure_ascii=False))
    open(os.path.join(cli_rel, "manifest-9.9.9.json"), "w",
         encoding="utf-8").write(json.dumps(man, ensure_ascii=False))
    idx4 = vindex.new_index("视频工具箱", furi(cli_rel))
    vindex.upsert_version(idx4, {"version": "9.9.8", "state": "stable"})
    vindex.upsert_version(idx4, {"version": "9.9.9", "state": "stable"})
    idxp = os.path.join(cli_rel, "index.json")
    vindex.save_index(idx4, idxp)
    check("--check 指定已装版本 → 0",
          setup.run_check(args(dir=tgt, version="9.9.9", index=idxp)) == 0)
    check("--check 指定别的版本 → 10",
          setup.run_check(args(dir=tgt, version="9.9.8", index=idxp)) == 10)
    check("--check 范围选择器也走索引 → 10",
          setup.run_check(args(dir=tgt, version="<9.9.9", index=idxp)) == 10)
    # --list-versions
    check("--list-versions 正常 → 0", setup.run_list(args(index=idxp)) == 0)
    check("--list-versions 坏索引 → 2",
          setup.run_list(args(index=os.path.join(tmp, "nope.json"))) == 2)


# ---------------------------------------------------------------- 10) URL 约定
def t_urls(tmp):
    print("\n== 10) URL 与默认目录约定 ==")
    check("默认 manifest 指向固定 tag",
          "/releases/download/repo-latest/manifest.json"
          in core.DEFAULT_MANIFEST_URL, core.DEFAULT_MANIFEST_URL)
    check("默认 index 指向固定 tag",
          "/releases/download/repo-latest/index.json"
          in core.DEFAULT_INDEX_URL, core.DEFAULT_INDEX_URL)
    check("默认安装目录 D:\\VideoToolbox（与 iss 一致）",
          core.DEFAULT_DIR == r"D:\VideoToolbox", core.DEFAULT_DIR)
    check("安装清单文件名", core.INSTALLED_NAME == "vt_installed.json")


if __name__ == "__main__":
    sys.exit(main())
