# -*- coding: utf-8 -*-
# @version 2.3.0
"""审计 Inno 编译日志：核对「该进包的文件都进了、不该进的一个没进」。

用法：
  tools\\python\\python.exe scripts\\dev\\_audit_iscc_compile_log.py <日志路径>

典型流程（安装包验证）：
  ISCC.exe packaging\\视频工具箱.iss > iscc.log 2>&1
  tools\\python\\python.exe scripts\\dev\\_audit_iscc_compile_log.py iscc.log

为什么需要（2026-10-13 实测）：ISCC 退出码 0 **不等于**该装的都装了——
[Files] 段漏写的条目连警告都没有，因为 Inno 只按清单压缩。上一轮
"iss 漏装 4 个 src 模块" 就是这样漏过去的：正向/反向检查都过了（那两关
查的是「iss 写的都在」与「import 链上的都在 iss 里」），但**实际压缩了
哪些文件**没人核。故最后一关必须回到编译日志本身。
"""
import collections
import os
import re
import sys

#: 命中即视为可疑（构建垃圾 / 中间产物 / 下载缓存）
SUSPECT = ["__pycache__", ".pyc", ".pyo", ".bak", ".log", ".tmp", ".old",
           "_diag_embed", ".selftest", ".orig", ".rej", ".vtold",
           ".dlpart", ".dlstate"]

#: 允许误报的白名单（合法文件名里含可疑子串的）
ALLOW = ["script (dev).tmpl", "script.tmpl"]


def parse(path):
    raw = open(path, encoding="utf-8", errors="replace").read()
    # ISCC 日志换行可能是 \r\n 或纯 \r
    raw = raw.replace("\r\n", "\n").replace("\r", "\n")
    files = [m.strip() for m in re.findall(r"Compressing: (.+)", raw)]
    ok = "Successful compile" in raw
    return files, ok


def audit(path, expect_missing):
    files, compiled = parse(path)
    fails = []
    print("编译日志      :", path)
    print("Successful    :", "是" if compiled else "否（编译未成功）")
    if not compiled:
        fails.append("编译不成功")
    print("Compressing   : %d 条" % len(files))

    # 1) 不该进的
    sus = []
    for f in files:
        low = f.lower()
        if any(a in low for a in ALLOW):
            continue
        for p in SUSPECT:
            if p in low:
                sus.append((p, f))
                break
    print("\n[不该进包的文件] %s" % ("干净" if not sus else "命中 %d 条" % len(sus)))
    for p, f in sus[:20]:
        print("   [%s] %s" % (p, f))
        fails.append("包内可疑文件：%s（%s）" % (f, p))

    # 2) 该进的（调用方给定必须命中的路径片段）
    print("\n[必须进包的文件]")
    for frag in expect_missing:
        hit = any(frag.lower() in f.lower() for f in files)
        print("   %s %s" % ("[OK]" if hit else "[缺]", frag))
        if not hit:
            fails.append("应进包但未压缩：" + frag)

    # 3) 顶层目录分布（截到 packaging\.. 之后，即仓库根视角）
    def _top(f):
        f = re.sub(r"^[A-Za-z]:", "", f)
        for marker in ("packaging\\..", "packaging/.."):
            i = f.find(marker)
            if i >= 0:
                f = f[i + len(marker):]
                break
        return f.lstrip("\\/").split("\\")[0].split("/")[0]
    top = collections.Counter(_top(f) for f in files)
    print("\n[顶层目录分布]")
    for k, v in sorted(top.items(), key=lambda kv: -kv[1]):
        print("   %-28s %d" % (k, v))

    print("\n" + "=" * 60)
    if fails:
        print("失败 %d 项：" % len(fails))
        for f in fails:
            print("   -", f)
        return 1
    print("审计通过（%d 条目，无可疑命中，必进项齐全）" % len(files))
    return 0


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    # 默认必进项：主程序 + 上一轮补装的 4 个 src 模块
    expect = [r"dist\视频工具箱.exe",
              r"src\vt_update_check.py",
              r"src\auto_vision_core.py",
              r"src\bili_upload.py",
              r"src\calib_media_agent.py"]
    if len(argv) > 2:
        expect = argv[2:]
    return audit(os.path.abspath(argv[1]), expect)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
