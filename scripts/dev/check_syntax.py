#!/usr/bin/env python3
# @version 2.6.0
"""语法门禁：对仓库里所有**受 git 跟踪**的 .py 做 AST 解析。

为什么不直接用 `python -m compileall src tools scripts`
------------------------------------------------------
`tools/python/` 是完整的 CPython 运行时（被 .gitignore 排除），本地跑
compileall 会把标准库和 site-packages 一起编译，既慢又会撞上第三方文件
自带的语法告警（modelscope 的 TabError 等）。CI 里那个目录不存在，本地
却存在——同一个命令两种结果，不能当门禁。

所以这里只取 `git ls-files '*.py'`：本地与 CI 的输入集合完全一致。

用法：
    python scripts/dev/check_syntax.py
退出码：0 = 全绿；1 = 有语法错误。
"""
from __future__ import annotations

import ast
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def tracked_py_files() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "-z", "*.py"],
        cwd=ROOT,
        capture_output=True,
        check=True,
    ).stdout
    return [p for p in out.decode("utf-8", "replace").split("\0") if p]


def main() -> int:
    files = tracked_py_files()
    if not files:
        print("没有取到受跟踪的 .py 文件（是否不在 git 仓库里？）")
        return 1

    broken: list[tuple[str, str]] = []
    for rel in files:
        path = os.path.join(ROOT, rel)
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                ast.parse(fh.read(), filename=rel)
        except SyntaxError as exc:
            broken.append((rel, f"{exc.msg} (line {exc.lineno})"))
        except OSError as exc:
            broken.append((rel, f"读取失败：{exc}"))

    for rel, msg in broken:
        print(f"[FAIL] {rel} —— {msg}")

    print()
    if broken:
        print(f"{len(broken)} / {len(files)} 个文件语法有误。")
        return 1
    print(f"全部 {len(files)} 个受跟踪的 .py 通过语法解析。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
