# -*- coding: utf-8 -*-
# @version 2.5.1
"""依赖闭合自检：把「自研 src + 内嵌字幕引擎」用到的顶层模块在当前解释器里
逐个解析，列出**解析不到的第三方模块**。

为什么需要（v1.15.2 的教训）：
    本机有两份 Python 环境——运行副本 `tools\\python` 与打包副本
    `C:\\bld\\qt_build`。第三方包**只装在其中一份**是隐形缺口：
    exe 内嵌的模块按**打包副本**的 sys.path 收集，运行副本有、打包副本没有的包
    （例如 `websocket-client`）在源码模式下一切正常，打包后一跑到那条代码路径
    就 ImportError。本脚本在**打包环境**下跑，就能在打包前把这类缺口挑出来。

用法（**必须用打包环境的解释器**，否则测的是运行副本、结论无效）：
    C:\\bld\\qt_build\\Scripts\\python.exe src\\check_deps.py
    python src\\check_deps.py --list          # 顺便打印全部顶层模块
返回码：0 = 闭合；1 = 有缺失。
"""
import argparse
import ast
import importlib.util
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
#: 脚本位于 <仓库根>/scripts/dev/，仓库根再上一级
ROOT = HERE.parent.parent

#: 开发期脚本/自检脚本不进 exe，扫描时跳过（减少噪声）
SKIP_PREFIX = ("_selftest", "_prof_", "check_", "stamp_", "apply_", "push_via_")

#: 已知的**软依赖**：代码里 try/except 包裹，缺了会走别的分支，不算缺口
SOFT_OK = {
    "tomli",      # py>=3.11 有 tomllib，引擎 config.py 只在旧解释器上用 tomli
    "vlc",        # 引擎的 VLC 播放后端，本工具箱走 libmpv，不依赖它
    "playwright", # CDP 连已装浏览器（sync_playwright 函数内延迟 import + 降级
                  # 提示）；v1.10.1 起浏览器引擎不随包分发，缺库属预期
}


def top_level_imports(paths):
    """{顶层模块名: {引用它的文件名}}"""
    hits = {}
    for p in paths:
        try:
            tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
        except (SyntaxError, OSError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    hits.setdefault(a.name.split(".")[0], set()).add(p.name)
            elif isinstance(node, ast.ImportFrom):
                if node.level == 0 and node.module:
                    hits.setdefault(node.module.split(".")[0], set()).add(p.name)
    return hits


def own_modules(src):
    """本项目自研的顶层模块名集合（= spec 会打进 exe 的那些）。

    口径必须与 ``视频工具箱.spec`` 的 pathex 一致，否则发布前检查永远红：

    * ``src/*.py`` 的文件级模块；
    * ``src/<子包>/``（如 ``vt_engine_ui``、``core/download``）的**包**——它们由
      ``collect_submodules('vt_engine_ui')`` / ``collect_submodules('core')``
      收进 PYZ，物理上在``src`` 下但**不是** ``src`` 的直接子文件。此前只取
      ``src.glob('*.py')``，于是把自研子包报成「缺失的第三方模块」——假阳性
      （v2.1.0 实测：``vt_engine_ui`` 被报缺失，而它 import 成功、spec 也已
      登记）；
    * **嵌套子包递归**（v2.3.1 拆分工程）：``core/download`` 这类两层及以上的
      包，只扫一层同样误报——``top_level_imports`` 记的是 ``core.download``
      拆点前的顶层名 ``core``，递归把每层目录名都收进 own 集合才闭合；
    * ``packaging/online_release/*.py``（vt_dl / vt_update_core /
      vt_version_index）——由 pathex + hiddenimports 收进 PYZ。
    """
    names = {p.stem for p in src.glob("*.py")}
    for pkg in src.iterdir():
        if not pkg.is_dir():
            continue
        if pkg.name == "__pycache__":
            continue
        # 目录名本身即包名；以 __init__.py 确认，避免把普通文件夹当包。
        # v2.3.1：包**自身**与**嵌套子孙**都要收——core/download 这类两层及
        # 以上的包，只收一层或只收子孙都会漏（前者漏 core.download、后者漏
        # vt_engine_ui 自身），报成第三方缺失就是假阳性。
        if (pkg / "__init__.py").is_file():
            names.add(pkg.name)
        for sub in sorted(pkg.rglob("*")):
            if sub.is_dir() and (sub / "__init__.py").is_file():
                names.add(sub.name)
    orel = ROOT / "packaging" / "online_release"
    if orel.is_dir():
        names |= {p.stem for p in orel.glob("*.py")}
    return names


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true", help="打印全部顶层模块")
    args = ap.parse_args()

    src = ROOT / "src"
    targets = [p for p in src.glob("*.py")
               if not p.name.startswith(SKIP_PREFIX)]
    n_own_files = len(targets)
    # 自研**子包**（如 vt_engine_ui）也要扫：里面的 import 同样是打包依赖。
    # 排除 __pycache__ 与开发期脚本目录。
    for pkg in src.iterdir():
        if not pkg.is_dir() or pkg.name == "__pycache__":
            continue
        for f in pkg.rglob("*.py"):
            if "__pycache__" in f.parts or f.name.startswith(SKIP_PREFIX):
                continue
            targets.append(f)
    n_self_pkg = len(targets) - n_own_files
    # 引擎取**当前解释器**能 import 到的那份（打包环境=打包副本，tools\python=运行副本）
    try:
        spec = importlib.util.find_spec("videocaptioner")
        engine_dir = Path(spec.origin).parent if spec and spec.origin else None
    except Exception:  # noqa: BLE001
        engine_dir = None
    n_engine = 0
    if engine_dir:
        engine_files = list(engine_dir.rglob("*.py"))
        n_engine = len(engine_files)
        targets += engine_files
        print("自研脚本 %d 个 + 自研子包 %d 个 + 引擎 %s"
              % (n_own_files, n_self_pkg, engine_dir))
    else:
        print("⚠ 当前解释器下解析不到 videocaptioner，只检查自研脚本")

    hits = top_level_imports(targets)
    own = own_modules(src)
    # 引擎自身的子包
    own |= {"videocaptioner"}

    stdlib = set(getattr(sys, "stdlib_module_names", ()))
    missing = []
    for m in sorted(hits):
        if m in stdlib or m in own or m in SOFT_OK or m.startswith("_"):
            continue
        try:
            found = importlib.util.find_spec(m) is not None
        except Exception:  # noqa: BLE001
            found = False
        if not found:
            missing.append((m, sorted(hits[m])))
        elif args.list:
            print("  [ok] %s" % m)

    print()
    if not missing:
        print("依赖闭合：全部可解析 ✅（软依赖 %s 已豁免）"
              % "、".join(sorted(SOFT_OK)))
        return 0
    print("**缺失 %d 个模块**（跑到对应代码路径会 ImportError）：" % len(missing))
    for m, srcs in missing:
        print("  %-24s <- %s" % (m, ", ".join(srcs[:3])))
    print("\n处置：把缺的包装到**当前这个解释器**的环境里，并在 视频工具箱.spec 的 "
          "hiddenimports 里显式声明。")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
