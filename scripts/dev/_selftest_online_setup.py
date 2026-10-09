#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# @version 1.18.3
"""自研「在线引导安装器」离线自检（不联网、不依赖任何第三方库）。

覆盖 packaging/online_release/ 的两个模块：
  · vt_update_core.py  —— 清单解析 / sha256 / 下载 / zip 解压（含 zip-slip 防护）
                           / 安装目录探测 / 空间检查 / 总流程
  · build_online_release.py —— 打包组件 zip、生成 manifest

全部在临时目录里跑，走 `file://` 通道，不需要网络、也不需要先发一版。

运行：tools/python/python.exe scripts/dev/_selftest_online_setup.py
"""
import hashlib
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import zipfile

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


import vt_update_core as core  # noqa: E402


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def main():
    print("=" * 62)
    print("  在线引导安装器 自检（vt_update_core / build_online_release）")
    print("=" * 62)
    tmp = tempfile.mkdtemp(prefix="vt_online_")
    try:
        # ---------------- 1) manifest ----------------
        print("\n== 1) 清单解析 ==")
        mf = os.path.join(tmp, "manifest.json")
        good = {"schema": 1, "app": "视频工具箱", "version": "9.9.9",
                "released": "2026-01-01 00:00:00",
                "base_url": "file:///" + tmp.replace("\\", "/"),
                "assets": [{"name": "base", "file": "a.zip", "size": 1,
                            "sha256": "x", "target": ""}]}
        open(mf, "w", encoding="utf-8").write(json.dumps(good))
        m = core.load_manifest(mf)
        check("本地路径可读", m["version"] == "9.9.9", m["version"])
        check("file:// 前缀可读",
              core.load_manifest("file:///" + mf.replace("\\", "/"))["version"]
              == "9.9.9")
        check("资产 URL 拼接正确",
              core.asset_url(m, m["assets"][0]).endswith("/a.zip"),
              core.asset_url(m, m["assets"][0]))
        check("缺 base_url 时明确报错",
              _raises(core.UpdateError, core.asset_url,
                      {"base_url": ""}, {"file": "a.zip"}))
        for bad, why in (({"schema": 2}, "schema 不符"),
                         ({"schema": 1}, "缺 version/assets"),
                         ({"schema": 1, "version": "1", "assets": "x"}, "assets 类型错")):
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

        # ---------------- 2) sha256 / human ----------------
        print("\n== 2) 工具函数 ==")
        f = os.path.join(tmp, "x.bin")
        open(f, "wb").write(b"hello")
        check("sha256 与 hashlib 一致",
              core.sha256_file(f) == hashlib.sha256(b"hello").hexdigest())
        seen = []
        core.sha256_file(f, progress=lambda d, t: seen.append((d, t)))
        check("sha256 进度回调被调用", seen and seen[-1] == (5, 5), seen)
        check("human 可读", core.human(1536) == "1.5 KB", core.human(1536))

        # ---------------- 3) 下载（file:// 通道） ----------------
        print("\n== 3) 下载 ==")
        src = os.path.join(tmp, "src.bin")
        open(src, "wb").write(b"x" * 4096)
        dst = os.path.join(tmp, "out", "dst.bin")
        core.download("file:///" + src.replace("\\", "/"), dst)
        check("下载后内容一致", sha(src) == sha(dst))
        check("不残留 .part 文件", not os.path.exists(dst + ".part"))
        check("大小不符时提前报错",
              _raises(core.UpdateError, core.download,
                      "file:///" + src.replace("\\", "/"),
                      os.path.join(tmp, "out", "d2.bin"), None, 999))
        check("失败后不留半成品",
              not os.path.exists(os.path.join(tmp, "out", "d2.bin")))

        # ---------------- 4) zip 解压与防护 ----------------
        print("\n== 4) zip 解压 ==")
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

        # ---------------- 5) 安装目录 / 空间 ----------------
        print("\n== 5) 安装目录与空间 ==")
        det = core.detect_install_dir()
        check("detect_install_dir 返回 str（可能为空）", isinstance(det, str), det)
        check("空间检查：需要 1 字节时通过", core.free_space_ok(tmp, 1))
        check("空间检查：需要 1PB 时不通过",
              core.free_space_ok(tmp, 1 << 50) is False)

        # ---------------- 6) 总流程（真 zip + 真校验） ----------------
        print("\n== 6) apply_update 总流程 ==")
        pkg = os.path.join(tmp, "pkg")
        os.makedirs(os.path.join(pkg, "src"))
        open(os.path.join(pkg, "视频工具箱.exe"), "wb").write(b"EXE" * 1000)
        open(os.path.join(pkg, "src", "a.py"), "w", encoding="utf-8").write("x=1")
        zp = os.path.join(tmp, "v9.9.9-base.zip")
        with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as zf:
            for r, _d, fs in os.walk(pkg):
                for fn in fs:
                    ap = os.path.join(r, fn)
                    zf.write(ap, os.path.relpath(ap, pkg).replace("\\", "/"))
        man = {"schema": 1, "version": "9.9.9",
               "base_url": "file:///" + tmp.replace("\\", "/"),
               "assets": [{"name": "base", "file": os.path.basename(zp),
                           "size": os.path.getsize(zp), "sha256": sha(zp),
                           "target": ""}]}
        tgt = os.path.join(tmp, "install")
        logs = []
        res = core.apply_update(man, tgt, os.path.join(tmp, "cache"),
                                log=logs.append)
        check("返回文件数 = 2", res["files"] == 2, res)
        check("exe 到位且一致",
              sha(os.path.join(tgt, "视频工具箱.exe"))
              == sha(os.path.join(pkg, "视频工具箱.exe")))
        check("子目录文件到位",
              os.path.isfile(os.path.join(tgt, "src", "a.py")))
        check("日志有内容", len(logs) > 0, len(logs))

        man2 = json.loads(json.dumps(man))
        man2["assets"][0]["sha256"] = "0" * 64
        check("sha256 不符时中止",
              _raises(core.UpdateError, core.apply_update, man2,
                      os.path.join(tmp, "install2"),
                      os.path.join(tmp, "cache2")))

        # 缓存命中：第二次跑不该重新下载（把 base_url 指向不存在的路径来验证）
        man3 = json.loads(json.dumps(man))
        man3["base_url"] = "file:///" + os.path.join(tmp, "nowhere").replace("\\", "/")
        res3 = core.apply_update(man3, tgt, os.path.join(tmp, "cache"))
        check("缓存命中时不重新下载", res3["files"] == 2, res3)

        # ---------------- 7) 打包侧（build_online_release） ----------------
        print("\n== 7) 打包侧 ==")
        bor = load("_bor", os.path.join(OREL, "build_online_release.py"))
        check("读到的版本号与 qt 源码一致",
              bor.read_version() == _qt_version(), bor.read_version())
        out = os.path.join(tmp, "rel")
        os.makedirs(out)
        # 用仓库真实文件打一个小包不合适（会写 100MB），这里直接调 build_zip 的
        # 迭代器验证「文件枚举 + 禁止项过滤」两件事
        items = list(bor.iter_files(os.path.join(ROOT, "src"), "src"))
        check("iter_files 能枚举 src/", len(items) > 5, len(items))
        check("iter_files 排除 __pycache__/.pyc",
              not any(p.endswith((".pyc", ".pyo")) or "__pycache__" in p
                      for _a, p in items))
        check("禁止项清单非空且含 github_proxy",
              "github_proxy.yaml" in bor.FORBIDDEN)
        check("STORE_OVER 阈值合理（>1MB）", bor.STORE_OVER > 1048576)
        check("默认 tag 是固定 tag（非版本号）",
              bor.DEFAULT_TAG == "repo-latest", bor.DEFAULT_TAG)
        check("组件清单与 IFW 版一致（同源校验函数存在）",
              callable(bor.check_components_in_sync))

        # ---------------- 8) 清单里的 base_url 与 tag 对应 ----------------
        print("\n== 8) URL 约定 ==")
        check("默认 manifest 指向固定 tag",
              "/releases/download/repo-latest/manifest.json"
              in core.DEFAULT_MANIFEST_URL, core.DEFAULT_MANIFEST_URL)
        check("默认安装目录与 iss 一致",
              core.DEFAULT_DIR.lower().endswith("videotoolbox"),
              core.DEFAULT_DIR)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + "=" * 62)
    if FAILS:
        print("  结果：%d 项失败" % len(FAILS))
        for f in FAILS:
            print("   · " + f)
    else:
        print("  结果：全部通过")
    print("=" * 62)
    return 1 if FAILS else 0


def _qt_version():
    import re
    p = os.path.join(ROOT, "src", "video_toolbox_qt.py")
    return re.search(r'VERSION\s*=\s*"([\d.]+)"',
                     open(p, encoding="utf-8").read()).group(1)


def _raises(exc, fn, *a, **kw):
    try:
        fn(*a, **kw)
    except exc:
        return True
    except Exception as e:  # noqa: BLE001
        print("      （抛了别的异常：%r）" % e)
        return False
    return False


if __name__ == "__main__":
    sys.exit(main())
