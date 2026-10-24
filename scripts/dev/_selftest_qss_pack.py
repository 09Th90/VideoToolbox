# -*- coding: utf-8 -*-
# @version 2.6.0
"""检查打包产物内 QSS 路径是否与运行期读取路径一致。

2026-10-22 实测事故：spec datas 把目标写成完整文件路径，exe 里出现
`vt_fluent/_qss/app.qss/app.qss`；冻结后 `_theme._QSS_DIR` 按
`_MEIPASS/vt_fluent/_qss/app.qss` 读取，四个 QSS 全部失败，安装版 UI
退化为原生样式。构建成功、日志无异常，只有实际启动才暴露。

同时支持 onedir（检查 `<exe 同级>\\_internal\\vt_fluent\\_qss`）与 onefile
（CArchiveReader）。默认检查 dist\\视频工具箱\\视频工具箱.exe。
"""
import os
import sys

EXE = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    "dist", "视频工具箱", "视频工具箱.exe")
WANT = {"vt_fluent/_qss/%s.qss" % n for n in ("app", "common", "light", "dark")}

if not os.path.isfile(EXE):
    print("!! 找不到 exe：", EXE)
    raise SystemExit(2)

internal = os.path.join(os.path.dirname(os.path.abspath(EXE)), "_internal")
if os.path.isdir(internal):
    names = []
    for rel in sorted(WANT):
        p = os.path.join(internal, rel.replace("/", os.sep))
        if os.path.isfile(p):
            names.append(rel)
    missing = WANT - set(names)
    nested = []
    print("onedir:", internal)
else:
    from PyInstaller.archive.readers import CArchiveReader
    a = CArchiveReader(EXE)
    names = [n.replace("\\", "/") for n in a.toc if n.lower().endswith(".qss")]
    missing = WANT - set(names)
    nested = [n for n in names if ".qss/" in n.lower()]
    print("onefile:", EXE)

print("QSS entries:", names)
if missing or nested:
    print("FAIL  missing=%s nested=%s" % (sorted(missing), nested))
    raise SystemExit(1)
print("PASS  4 个 QSS 均在 vt_fluent/_qss/<name>.qss，无嵌套目录")
