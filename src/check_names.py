# -*- coding: utf-8 -*-
# @version 1.15.1
"""静态体检：找出「引用了但整个模块里没有定义」的全局名字。

为什么需要它：PyQt5 里**槽函数/回调里抛出的未捕获异常默认会让进程直接 abort**，
表现就是「点一下按钮程序突然没了」。而这类异常最常见的原因就是写错/漏定义了一个
全局常量或函数（例如 `duration=INFOBAR_DURATION_SUCCESS` 但该常量从未定义）——
`python -m py_compile` 查不出来（语法没错），只有真的点到那行才炸。

本工具用标准库 `symtable` 做**作用域级**静态分析，无需第三方依赖：
在函数/类作用域里以「全局」身份被引用、但模块顶层既没定义也没有 import、
且不是内置名的标识符，一律报出来。

用法（在 src 目录，或任意位置）：
    python check_names.py                  # 扫描本目录下所有 .py
    python check_names.py video_toolbox_qt.py
    python check_names.py -q               # 只输出汇总
退出码：0 = 干净，1 = 发现问题（可直接接进自检 / CI）。
"""
import argparse
import builtins
import os
import symtable
import sys

#: 模块顶层由解释器/导入系统自动注入的名字，不算未定义
IMPLICIT = {
    "__file__", "__name__", "__doc__", "__spec__", "__loader__",
    "__package__", "__builtins__", "__path__", "__annotations__",
    "__debug__", "__cached__",
}


def scan_source(src, filename="<string>"):
    """返回 [(作用域, 行号, 名字), ...]：函数/类作用域里引用了但没有定义的全局名。"""
    try:
        top = symtable.symtable(src, filename, "exec")
    except SyntaxError as e:                     # 语法错由 py_compile 负责，这里只提示
        return [(f"<SyntaxError> {e.msg}", e.lineno or 0, filename)]

    defined = set(top.get_identifiers()) | IMPLICIT
    problems = []

    def walk(table):
        name = table.get_name()
        for sym in table.get_symbols():
            ident = sym.get_name()
            if ident in defined or hasattr(builtins, ident):
                continue
            if sym.is_global() and not sym.is_assigned():
                # is_global(): 该作用域里按「全局」解析；is_assigned(): 该作用域里给它赋过值
                problems.append((name, table.get_lineno(), ident))
        for child in table.get_children():
            walk(child)

    for child in top.get_children():
        walk(child)
    return problems


def scan_file(path, quiet=False):
    with open(path, encoding="utf-8") as f:
        src = f.read()
    problems = scan_source(src, path)
    if problems and not quiet:
        print(f"\n[{os.path.relpath(path)}]")
        seen = set()
        for scope, lineno, ident in problems:
            key = (scope, ident)
            if key in seen:
                continue
            seen.add(key)
            print(f"  第 {lineno} 行附近  {scope}()  ->  {ident}  未定义")
    return problems


def main():
    ap = argparse.ArgumentParser(description="扫描未定义的全局名（PyQt5 回调闪退的头号成因）")
    ap.add_argument("files", nargs="*", help="要扫描的 .py（默认扫描脚本所在目录）")
    ap.add_argument("-q", "--quiet", action="store_true", help="只打印汇总")
    args = ap.parse_args()

    here = os.path.dirname(os.path.abspath(__file__))
    targets = [os.path.abspath(p) for p in args.files] or \
        sorted(os.path.join(here, f) for f in os.listdir(here)
               if f.endswith(".py") and not f.startswith("__"))

    total = 0
    bad_files = 0
    for path in targets:
        if not os.path.isfile(path):
            print(f"跳过（不是文件）：{path}")
            continue
        n = len(scan_file(path, args.quiet))
        total += n
        bad_files += 1 if n else 0

    print(f"\n扫描 {len(targets)} 个文件：{bad_files} 个文件有未定义名，共 {total} 处")
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
