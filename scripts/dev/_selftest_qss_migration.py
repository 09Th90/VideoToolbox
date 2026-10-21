# -*- coding: utf-8 -*-
# @version 2.4.1
"""qfluentwidgets → 自写 QSS 主题（vt_fluent）· 迁移 parity 测试。

为什么需要（v2.3.1 起）：
    随包分发 qfluentwidgets（GPL-3.0）与整仓 CC BY-SA 4.0 的合规组合是长期
    负担；用户拍板「改用自写 QSS 主题，且不允许损失 Fluent 风格的任何一部分」。
    迁移是**渐变**过程：vt_fluent 逐个控件补齐，src/ 逐个文件切换 import。

    本测试管三件事：
      1. **使用面基线**（AST 快照 → ``_golden/qss_usage.json``）：迁移前全量
         qfluentwidgets 符号与落点 = 自研主题库的需求清单（parity 对象）；
      2. **只许收缩不许新增**：新代码再 import qfluentwidgets = 回归 FAIL；
         基线里的符号/文件消失 = 迁移进度（打点不报错）；
      3. **parity 断言**：vt_fluent 包一旦存在，使用面残留的每个符号都必须
         能 ``from vt_fluent import <符号>``（缺一个即 FAIL）——「Fluent 风格
         零损失」的最低可执行判据。

用法（程序根为 cwd）：
    VT_NO_SYNC=1 tools\\python\\python.exe scripts\\dev\\_selftest_qss_migration.py

退出码：0 = PASS（无新增 + parity 满足）；1 = FAIL。
"""
import ast
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
SRC = os.path.join(ROOT, "src")
GOLDEN = os.path.join(HERE, "_golden", "qss_usage.json")
FLUENT_PKG = os.path.join(SRC, "vt_fluent")

sys.path.insert(0, SRC)

#: 扫描范围：src 下全部 .py（含子包），排除缓存
_SKIP_DIRS = {"__pycache__"}


def _src_files():
    out = []
    for dirpath, dirs, files in os.walk(SRC):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
        out += [os.path.join(dirpath, f) for f in sorted(files)
                if f.endswith(".py")]
    return sorted(out)


def _rel(p):
    return os.path.relpath(p, ROOT).replace("\\", "/")


def scan_usage():
    """{符号全名: {"count": n, "files": [rel...]}}——含 from-import 与 import 两种。"""
    usage = {}
    for path in _src_files():
        rel = _rel(path)
        try:
            with open(path, encoding="utf-8") as f:
                tree = ast.parse(f.read(), path)
        except (SyntaxError, OSError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level == 0 \
                    and node.module and node.module.split(".")[0] == "qfluentwidgets":
                for a in node.names:
                    key = f"{node.module}::{a.name}" if a.name != "*" \
                        else f"{node.module}::*"
                    rec = usage.setdefault(key, {"count": 0, "files": []})
                    rec["count"] += 1
                    if rel not in rec["files"]:
                        rec["files"].append(rel)
            elif isinstance(node, ast.Import):
                for a in node.names:
                    if a.name.split(".")[0] == "qfluentwidgets":
                        rec = usage.setdefault(f"module::{a.name}",
                                               {"count": 0, "files": []})
                        rec["count"] += 1
                        if rel not in rec["files"]:
                            rec["files"].append(rel)
    return usage


def _load_golden():
    with open(GOLDEN, encoding="utf-8") as f:
        return json.load(f)


def _save_golden(data):
    os.makedirs(os.path.dirname(GOLDEN), exist_ok=True)
    with open(GOLDEN, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1, sort_keys=True)


def _vt_fluent_symbols():
    """vt_fluent 包存在则 import，返回其 __all__ 符号集；不存在返回 None。"""
    if not os.path.isdir(FLUENT_PKG):
        return None
    try:
        import vt_fluent
        return set(getattr(vt_fluent, "__all__", []) or dir(vt_fluent))
    except Exception as e:
        print(f"[PARITY] vt_fluent 存在但导入失败: {e!r}")
        return set()


def main():
    fails = []
    usage = scan_usage()
    n_files = len({f for r in usage.values() for f in r["files"]})

    if not os.path.isfile(GOLDEN):
        _save_golden(usage)
        print(f"[BASELINE] 已生成 {os.path.relpath(GOLDEN, ROOT)}"
              f"（{len(usage)} 符号 / {n_files} 文件）")
        golden = usage
    else:
        golden = _load_golden()
        print(f"[BASELINE] 使用面比对完成（基线 {len(golden)} 符号）")

    # ① 只许收缩不许新增
    new_keys = sorted(set(usage) - set(golden))
    if new_keys:
        fails.append(f"新增 qfluentwidgets 依赖（迁移期禁止）: {new_keys}")
    gone = sorted(set(golden) - set(usage))
    print(f"[PROGRESS] 已迁移 {len(gone)}/{len(golden)} 符号；"
          f"残留 {len(usage)} 符号 / {n_files} 文件")

    # ② parity：vt_fluent 必须覆盖残留使用面
    fsyms = _vt_fluent_symbols()
    if fsyms is not None:
        missing = []
        for key in sorted(usage):
            sym = key.split("::")[-1]
            if sym in ("*",):
                continue
            if sym not in fsyms:
                missing.append(key)
        if missing:
            fails.append(f"vt_fluent 缺符号（Fluent 风格损失）: {missing}")
        else:
            print(f"[PARITY] vt_fluent 覆盖残留使用面 {len(usage)} 符号 ✓")

    # ③ 残留清单（迁移施工顺序的依据）
    if usage:
        print("[REMAIN] 仍依赖 qfluentwidgets 的文件:")
        for f in sorted({f for r in usage.values() for f in r["files"]}):
            print("   -", f)

    print("=" * 56)
    if fails:
        print(f"QSS-MIGRATION RESULT: FAIL ({len(fails)} 项)")
        for x in fails:
            print("  -", x)
        return 1
    print("QSS-MIGRATION RESULT: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
