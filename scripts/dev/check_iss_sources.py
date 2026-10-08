# -*- coding: utf-8 -*-
# @version 1.17.0
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
sys.exit(1 if missing else 0)
