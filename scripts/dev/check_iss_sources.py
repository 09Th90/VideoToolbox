# -*- coding: utf-8 -*-
# @version 1.18.3
"""校验 视频工具箱.iss 里所有 Source 路径是否真实存在（打包前必做）。

Inno 对缺失 Source 只在编译期报错，且错误信息不便定位；这里提前把
「文件已移走但 iss 还引用」这类问题挑出来（2026-10-08 就踩到过：
apply_vc_official.py 移到 scripts/dev/ 后 iss 仍写 src/）。
"""
import io
import os
import re
import sys

ISS = os.path.join("packaging", "视频工具箱.iss")
base = os.path.dirname(os.path.abspath(ISS))

SRC_RE = re.compile(r'^\s*Source:\s*"([^"]+)"')

missing = []
ok = 0
for raw in io.open(ISS, encoding="utf-8", errors="replace"):
    m = SRC_RE.match(raw)
    if not m:
        continue
    spec = m.group(1)
    if spec.startswith("#") or "%" in spec:
        continue
    norm = spec.replace("\\", os.sep).replace("/", os.sep)
    full = os.path.normpath(os.path.join(base, norm))
    if "*" in norm:
        # 目录通配：检查去掉通配部分后的目录
        d = full[:full.index("*")].rstrip(os.sep) or os.sep
        if os.path.isdir(d):
            ok += 1
        else:
            missing.append((spec, "目录不存在"))
        continue
    if os.path.exists(full):
        ok += 1
    else:
        missing.append((spec, "缺失"))

print("检查通过 =", ok)
print("缺失/异常 =", len(missing))
for spec, why in missing:
    print("   [%s] %s" % (why, spec))

# ---------------------------------------------------------------------------
# 反向检查：video_toolbox_qt.py 的**模块级** import 是否都在 iss 里列出？
#
# ⚠⚠ 为什么必须查（2026-10-09 实测踩坑）：上面的正向检查只保证
#   「iss 里写的文件都存在」，但**保证不了该装的都装了**。
#   当时 media_registry.py / pipeline.py 就是漏装的——它们是
#   video_toolbox_qt.py 第 136-137 行的**模块级** import，缺了必 ImportError；
#   而 exe 侧靠 spec 的 PYZ 副本照样能跑（只是多容器配对静默失效），
#   更坑的是 check_install_sync 从 iss 提取清单 ⇒ 这两个压根不在
#   比对范围，28/28 全绿也照样漏。**三个环节互相掩护，只能靠本检查兜底。**
# ---------------------------------------------------------------------------
import ast

QT = os.path.join(base, "..", "src", "video_toolbox_qt.py")
qt = os.path.normpath(QT)
if os.path.isfile(qt):
    tree = ast.parse(open(qt, encoding="utf-8").read())
    mods = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            for a in n.names:
                mods.add(a.name.split(".")[0])
        elif isinstance(n, ast.ImportFrom) and n.module and n.col_offset == 0:
            mods.add(n.module.split(".")[0])
    srcdir = os.path.normpath(os.path.join(base, "..", "src"))
    local = sorted(m for m in mods
                   if os.path.isfile(os.path.join(srcdir, m + ".py")))
    # iss 里所有 ..\src\*.py 条目的文件名
    iss_text = open(ISS, encoding="utf-8").read()
    installed = set(re.findall(r"\.\.[\\/]src[\\/]([a-z_0-9]+\.py)", iss_text))
    absent = [m + ".py" for m in local if m + ".py" not in installed]
    print("模块级依赖覆盖 = %d/%d" % (len(local) - len(absent), len(local)))
    for f in absent:
        print("   [未随包分发] src\\%s"
              "（video_toolbox_qt.py 模块级 import，缺了 src\\ 方式运行会 ImportError）" % f)
    if absent:
        missing += [(f, "模块级依赖未随包分发") for f in absent]

sys.exit(1 if missing else 0)
