# -*- coding: utf-8 -*-
# @version 2.1.0
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
# 反向检查：src\ 下的**自研模块**是否都在 iss 里列出？
#
# ⚠⚠ 为什么必须查（2026-10-09 实测踩坑）：上面的正向检查只保证
#   「iss 里写的文件都存在」，但**保证不了该装的都装了**。
#   当时 media_registry.py / pipeline.py 就是漏装的——它们是
#   video_toolbox_qt.py 第 136-137 行的**模块级** import，缺了必 ImportError；
#   而 exe 侧靠 spec 的 PYZ 副本照样能跑（只是多容器配对静默失效），
#   更坑的是 check_install_sync 从 iss 提取清单 ⇒ 这两个压根不在
#   比对范围，28/28 全绿也照样漏。**三个环节互相掩护，只能靠本检查兜底。**
#
# ⚠⚠ 2026-10-12 二轮补漏：只看 video_toolbox_qt.py 的**直接** import 不够——
#   auto_vision_page.py（qt 顶层导入）自己又模块级导入 auto_vision_core /
#   bili_upload，本轮 AST 传递闭包复查才揪出来。故改成**闭包**：
#   从 video_toolbox_qt.py 与 video_toolbox.py 两个入口出发，
#   沿 import（模块级 + 函数体内延迟）走完整条链，链上任一 src 模块缺失即报错。
#   延迟导入（col_offset>0）单列一档「建议随包分发」：它的症状同样是静默的
#   （音画证据 / 联网查证 / 声纹同步都走 try/except 降级），故也计入缺失。
# ---------------------------------------------------------------------------
import ast

BASE = os.path.normpath(os.path.join(base, ".."))
ROOTS = ["video_toolbox_qt", "video_toolbox"]
SRCDIR = os.path.normpath(os.path.join(BASE, "src"))


def _imported_names(tree):
    """返回 (模块级顶层 import 的模块名集合, 函数体内延迟 import 的模块名集合)。"""
    top, lazy = set(), set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [a.name.split(".")[0] for a in node.names]
            (top if node.col_offset == 0 else lazy).update(names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.col_offset == 0:
            # ImportFrom 只在顶层层级算（缩进的 from-import 也满足 col_offset==0，
            # 无法区分行内缩进，统一按顶层处理，宁可多报不可漏报）
            top.add(node.module.split(".")[0])
    return top, lazy


missing = []
ok = 0
qt_present = os.path.isfile(os.path.join(SRCDIR, "video_toolbox_qt.py"))
if qt_present:
    closure, seen, stack = {}, set(), list(ROOTS)
    while stack:
        mod = stack.pop()
        if mod in seen or not os.path.isfile(os.path.join(SRCDIR, mod + ".py")):
            continue
        seen.add(mod)
        try:
            tree = ast.parse(open(os.path.join(SRCDIR, mod + ".py"),
                                  encoding="utf-8").read())
        except (SyntaxError, UnicodeDecodeError) as exc:
            missing.append(("src\\%s.py" % mod, "AST 解析失败：%s" % exc))
            continue
        top, lazy = _imported_names(tree)
        closure[mod] = (top, lazy)
        for dep in top | lazy:
            if os.path.isfile(os.path.join(SRCDIR, dep + ".py")) and dep not in seen:
                stack.append(dep)

    # iss 里所有 ..\src\*.py 条目的文件名（兼容非 ASCII 文件名）
    iss_text = open(ISS, encoding="utf-8").read()
    installed = set(re.findall(r"\.\.[\\/]src[\\/]([^\";]+\.py)", iss_text))

    # 谁在**模块级**导入 mod（不是 mod 自己导入谁）
    imported_at_top = set()
    for top, _lazy in closure.values():
        imported_at_top |= top

    hard_absent, lazy_absent = [], []
    for mod in sorted(closure):
        if mod + ".py" in installed:
            continue
        if mod in imported_at_top:
            hard_absent.append(mod + ".py")
        else:
            lazy_absent.append(mod + ".py")
    print("src 模块闭包 = %d 个（自 video_toolbox_qt.py / video_toolbox.py 沿 import 传递）"
          % len(closure))
    print("模块级依赖覆盖 = %d/%d"
          % (len(closure) - len(hard_absent) - len(lazy_absent), len(closure)))
    for f in hard_absent:
        print("   [未随包分发·模块级] src\\%s"
              "（闭包内某模块顶层 import 它，缺了 src\\ 方式运行会 ImportError）" % f)
    for f in lazy_absent:
        print("   [未随包分发·延迟导入] src\\%s"
              "（闭包内某模块函数体内 import 它，缺了功能静默降级）" % f)
    missing += [(f, "模块级依赖未随包分发") for f in hard_absent]
    missing += [(f, "延迟导入依赖未随包分发") for f in lazy_absent]

sys.exit(1 if missing else 0)
