# -*- coding: utf-8 -*-
# @version 2.1.0
"""极简未定义名扫描（无 pyflakes 时的兜底）。

对 vt_engine_ui 每个模块：收集模块级全局名 + 每个函数内的局部绑定，找出函数体内
以 Load 方式引用、但既非局部、非全局、非内建的名字——这些是运行到该分支才会炸的
NameError 隐患（py_compile / import 都查不出，因为方法体不在导入期执行）。
"""
import ast
import builtins
import os
import sys

SRC = os.path.join(os.getcwd(), "src", "vt_engine_ui")
BUILTINS = set(dir(builtins))


def _bind_targets(node, out):
    """收集一个节点里所有被绑定的名字（赋值/for/with/except/import/推导式/形参）。"""
    if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
        out.add(node.id)
    elif isinstance(node, (ast.Tuple, ast.List)):
        for e in node.elts:
            _bind_targets(e, out)
    elif isinstance(node, ast.Starred):
        _bind_targets(node.value, out)


def _func_locals(fn):
    loc = set()
    a = fn.args
    for arg in list(a.posonlyargs) + list(a.args) + list(a.kwonlyargs):
        loc.add(arg.arg)
    if a.vararg:
        loc.add(a.vararg.arg)
    if a.kwarg:
        loc.add(a.kwarg.arg)
    for sub in ast.walk(fn):
        if isinstance(sub, ast.Assign):
            for t in sub.targets:
                _bind_targets(t, loc)
        elif isinstance(sub, (ast.AnnAssign, ast.AugAssign)):
            _bind_targets(sub.target, loc)
        elif isinstance(sub, ast.For):
            _bind_targets(sub.target, loc)
        elif isinstance(sub, (ast.Import, ast.ImportFrom)):
            for al in sub.names:
                loc.add((al.asname or al.name).split(".")[0])
        elif isinstance(sub, ast.With):
            for it in sub.items:
                if it.optional_vars is not None:
                    _bind_targets(it.optional_vars, loc)
        elif isinstance(sub, ast.ExceptHandler) and sub.name:
            loc.add(sub.name)
        elif isinstance(sub, (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)):
            for g in sub.generators:
                _bind_targets(g.target, loc)
        elif isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            loc.add(sub.name)
        elif isinstance(sub, ast.Global):
            loc.update(sub.names)
        elif isinstance(sub, ast.NamedExpr):
            _bind_targets(sub.target, loc)
        elif isinstance(sub, ast.Lambda):
            la = sub.args
            for arg in list(la.posonlyargs) + list(la.args) + list(la.kwonlyargs):
                loc.add(arg.arg)
            if la.vararg:
                loc.add(la.vararg.arg)
            if la.kwarg:
                loc.add(la.kwarg.arg)
    return loc


def module_globals(tree):
    g = set()
    for n in tree.body:
        if isinstance(n, (ast.Import, ast.ImportFrom)):
            for al in n.names:
                g.add((al.asname or al.name).split(".")[0])
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            g.add(n.name)
        elif isinstance(n, ast.Assign):
            for t in n.targets:
                _bind_targets(t, g)
        elif isinstance(n, ast.AnnAssign):
            _bind_targets(n.target, g)
        elif isinstance(n, (ast.If, ast.Try, ast.For, ast.While, ast.With)):
            # 条件/try 内的顶层绑定也算全局
            for sub in ast.walk(n):
                if isinstance(sub, ast.Assign):
                    for t in sub.targets:
                        _bind_targets(t, g)
                elif isinstance(sub, (ast.Import, ast.ImportFrom)):
                    for al in sub.names:
                        g.add((al.asname or al.name).split(".")[0])
                elif isinstance(sub, (ast.FunctionDef, ast.ClassDef)):
                    g.add(sub.name)
    return g


def _shallow_walk(node):
    """遍历 node 的子树，但**不进入**嵌套的函数/类（它们有自己的作用域）。"""
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef,
                              ast.Lambda)):
            continue
        yield child
        yield from _shallow_walk(child)


def _nested_scopes(node):
    """直接嵌套在 node 里的函数/类/lambda（下一层作用域）。"""
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef,
                              ast.Lambda)):
            yield child


def scan(path):
    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read(), path)
    globs = module_globals(tree) | BUILTINS | {"__name__", "__file__"}
    issues = []

    def _params(fn):
        a = fn.args
        loc = set()
        for arg in list(a.posonlyargs) + list(a.args) + list(a.kwonlyargs):
            loc.add(arg.arg)
        if a.vararg:
            loc.add(a.vararg.arg)
        if a.kwarg:
            loc.add(a.kwarg.arg)
        return loc

    def visit(fn, chain):
        # 本作用域绑定的名字（形参 + 局部赋值 + 内部 import + 嵌套 def 名）
        loc = _params(fn) | (_func_locals(fn) if not isinstance(fn, ast.Lambda) else set())
        visible = globs | loc | set(chain)
        # 收集本作用域「直接」引用的 Load 名（不进入嵌套作用域）
        bodies = fn.body if isinstance(fn.body, list) else [fn.body]
        for stmt in bodies:
            # stmt 本身若是嵌套 def/class/lambda，交由递归处理，不在此下钻
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef,
                                 ast.ClassDef, ast.Lambda)):
                subs = [stmt]
            else:
                subs = [stmt] + list(_shallow_walk(stmt))
            for sub in subs:
                if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Load):
                    if sub.id not in visible:
                        issues.append((getattr(fn, "name", "<lambda>"),
                                       sub.lineno, sub.id))
        # 递归进入直接嵌套的函数/lambda（类体单独处理，见 top）
        for nested in _nested_scopes(fn):
            if isinstance(nested, ast.ClassDef):
                for m in _nested_scopes(nested):
                    visit(m, chain | loc)
            else:
                visit(nested, chain | loc)

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            visit(node, set())
        elif isinstance(node, ast.ClassDef):
            for m in _nested_scopes(node):
                visit(m, set())
    return issues


def main():
    total = 0
    for fname in sorted(os.listdir(SRC)):
        if not fname.endswith(".py"):
            continue
        iss = scan(os.path.join(SRC, fname))
        if iss:
            # 去重
            seen = set()
            for fnname, line, name in iss:
                key = (fnname, name)
                if key in seen:
                    continue
                seen.add(key)
                print(f"[UNDEF] {fname}:{line} in {fnname}() -> {name!r}")
                total += 1
        else:
            print(f"[clean] {fname}")
    print("=" * 40)
    print("LINT RESULT:", "CLEAN" if total == 0 else f"{total} potential undefined names")
    return 0 if total == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
