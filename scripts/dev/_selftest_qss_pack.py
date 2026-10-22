# -*- coding: utf-8 -*-
# @version 2.5.4
"""检查 onefile exe 内 QSS 的打包路径是否与运行期读取路径一致。

2026-10-22 实测事故：spec datas 把目标写成完整文件路径，exe 里出现
`vt_fluent/_qss/app.qss/app.qss`；冻结后 `_theme._QSS_DIR` 按
`_MEIPASS/vt_fluent/_qss/app.qss` 读取，四个 QSS 全部失败，安装版 UI
退化为原生样式。构建成功、日志无异常，只有实际启动才暴露。

用法（构建环境解释器）：
    D:\\Agent Work\\_bld\\qt_build\\Scripts\\python.exe scripts\\dev\\_selftest_qss_pack.py [exe]
默认检查 dist\\视频工具箱.exe。
"""
import os
import sys

from PyInstaller.archive.readers import CArchiveReader

EXE = sys.argv[1] if len(sys.argv) > 1 else os.path.join("dist", "视频工具箱.exe")
WANT = {"vt_fluent/_qss/%s.qss" % n for n in ("app", "common", "light", "dark")}

if not os.path.isfile(EXE):
    print("!! 找不到 exe：", EXE)
    raise SystemExit(2)

a = CArchiveReader(EXE)
names = [n.replace("\\", "/") for n in a.toc if n.lower().endswith(".qss")]
actual = set(names)
nested = [n for n in names if ".qss/" in n.lower()]
missing = WANT - actual

print("exe:", EXE)
print("QSS entries:", names)
if missing or nested:
    print("FAIL  missing=%s nested=%s" % (sorted(missing), nested))
    raise SystemExit(1)
print("PASS  4 个 QSS 均在 vt_fluent/_qss/<name>.qss，无嵌套目录")
