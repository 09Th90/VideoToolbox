# -*- coding: utf-8 -*-
# @version 1.15.7
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
ROOT = HERE.parent

#: 开发期脚本/自检脚本不进 exe，扫描时跳过（减少噪声）
SKIP_PREFIX = ("_selftest", "_prof_", "check_", "stamp_", "apply_", "push_via_")

#: 已知的**软依赖**：代码里 try/except 包裹，缺了会走别的分支，不算缺口
SOFT_OK = {
    "tomli",    # py>=3.11 有 tomllib，引擎 config.py 只在旧解释器上用 tomli
    "vlc",      # 引擎的 VLC 播放后端，本工具箱走 libmpv，不依赖它
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true", help="打印全部顶层模块")
    args = ap.parse_args()

    src = HERE
    targets = [p for p in src.glob("*.py")
               if not p.name.startswith(SKIP_PREFIX)]
    # 引擎取**当前解释器**能 import 到的那份（打包环境=打包副本，tools\python=运行副本）
    try:
        spec = importlib.util.find_spec("videocaptioner")
        engine_dir = Path(spec.origin).parent if spec and spec.origin else None
    except Exception:  # noqa: BLE001
        engine_dir = None
    if engine_dir:
        targets += list(engine_dir.rglob("*.py"))
        print("自研脚本 %d 个 + 引擎 %s"
              % (len(targets) - len(list(engine_dir.rglob('*.py'))), engine_dir))
    else:
        print("⚠ 当前解释器下解析不到 videocaptioner，只检查自研脚本")

    hits = top_level_imports(targets)
    own = {p.stem for p in src.glob("*.py")}          # 自研兄弟模块
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
