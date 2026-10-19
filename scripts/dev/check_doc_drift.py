#!/usr/bin/env python3
# @version 2.4.0
"""文档漂移门禁：README / LICENSE 与代码事实不一致时，让检查直接失败。

为什么需要这个脚本
------------------
三天发四个版本的节奏下，README 曾长期落后于代码：
  · 代码早在 v2.1.0 迁到 PySide6，README 技术栈表仍写「PyQt5 + qfluentwidgets」；
  · 第三方许可表把 qfluentwidgets 标成 MIT，而 PySide6-Fluent-Widgets 实为 GPL-3.0；
  · 下载区预告了 `视频工具箱_Setup_v2.3.1.exe`，但该产物从未构建、Releases 里也不存在。

这些都是「同一事实存在多个版本」的问题，靠人肉 review 守不住。本脚本把
几条硬约束变成可执行检查：CI 每次 push 都跑一遍，漂移当场变红。

用法
----
    python scripts/dev/check_doc_drift.py          # 本地全量（含产物实物核对）
    python scripts/dev/check_doc_drift.py --ci     # CI 模式，跳过需要本地二进制的项

退出码：0 = 全绿；1 = 有漂移。
"""
from __future__ import annotations

import argparse
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

README = os.path.join(ROOT, "README.md")
LICENSE = os.path.join(ROOT, "LICENSE")
QT_ENTRY = os.path.join(ROOT, "src", "video_toolbox_qt.py")
REQUIREMENTS = os.path.join(ROOT, "requirements.txt")

# README 里可能承诺的安装包会落在这些目录（均为 gitignore 的本机构建产物）
ARTIFACT_DIRS = ("installer", "installer_online", "dist")

results: list[tuple[bool, str, str]] = []


def check(ok: bool, name: str, detail: str = "") -> None:
    results.append((ok, name, detail))


def read(path: str) -> str:
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        return fh.read()


def check_version_consistency(readme: str) -> None:
    """README 顶部 @version 必须等于代码里的 VERSION。"""
    m_code = re.search(r'^VERSION\s*=\s*"([\d.]+)"', read(QT_ENTRY), re.MULTILINE)
    m_doc = re.search(r"<!--\s*@version\s*([\d.]+)\s*-->", readme)
    if not m_code:
        check(False, "版本号一致性", "src/video_toolbox_qt.py 里找不到 VERSION = \"x.y.z\"")
        return
    if not m_doc:
        check(False, "版本号一致性", "README.md 顶部缺少 <!-- @version x.y.z --> 标记")
        return
    code_v, doc_v = m_code.group(1), m_doc.group(1)
    check(
        code_v == doc_v,
        "版本号一致性",
        f"代码 VERSION={code_v}，README @version={doc_v}",
    )


def check_tech_stack(readme: str) -> None:
    """技术栈表不得再出现已下线的 PyQt5。"""
    stale = re.findall(r"^\|\s*界面\s*\|.*PyQt5.*$", readme, re.MULTILINE)
    check(
        not stale,
        "技术栈表已迁移 PySide6",
        "技术栈「界面」行仍写 PyQt5，代码实际用的是 PySide6",
    )


def check_license_table(readme: str) -> None:
    """第三方许可表不得把 Fluent Widgets 标成 MIT，也不得漏掉 GPL-3.0。"""
    bad_mit = re.findall(r"^\|.*qfluentwidgets.*\|\s*MIT\s*\|", readme, re.MULTILINE | re.IGNORECASE)
    check(
        not bad_mit,
        "qfluentwidgets 许可未误标 MIT",
        "PySide6-Fluent-Widgets 是 GPL-3.0，不是 MIT",
    )
    has_fluent = "PySide6-Fluent-Widgets" in readme
    check(has_fluent, "许可表登记 PySide6-Fluent-Widgets", "第三方表缺少该组件条目")


def check_license_compat() -> None:
    """LICENSE 必须含 CC BY-SA 4.0 -> GPL-3.0 的组合作品兼容声明。"""
    text = read(LICENSE)
    has_compat = ("BY-SA Compatible License" in text) and ("组合作品" in text)
    check(
        has_compat,
        "LICENSE 含 GPL-3.0 兼容声明",
        "缺少「组合作品整体按 GPL-3.0 提供」的条款",
    )
    has_spdx_gpl = "GPL-3.0-only" in text
    check(has_spdx_gpl, "LICENSE 标注组合作品 SPDX", "SPDX 行未列出 GPL-3.0-only")


def check_requirements() -> None:
    """源码方式必须有可用的依赖清单。"""
    if not os.path.exists(REQUIREMENTS):
        check(False, "requirements.txt 存在", "README 的源码方式引用了它，但文件不存在")
        return
    body = read(REQUIREMENTS)
    has_pyside = "PySide6" in body
    check(has_pyside, "requirements.txt 含 PySide6", "界面框架依赖缺失")


def check_promised_artifacts(readme: str, ci_mode: bool) -> None:
    """README 提到的安装包文件名，必须真有实物（CI 环境无二进制，跳过）。"""
    # 发布产物一律 ASCII 名（GitHub 会截断中文附件名），兼容旧的中文名写法
    names = re.findall(r"`((?:VideoToolbox|视频工具箱)_[^`]*?\.exe)`", readme)
    if not names:
        return
    if ci_mode:
        results.append((True, "安装包实物核对", f"CI 模式跳过（{len(names)} 个文件名）"))
        return
    for name in sorted(set(names)):
        found = any(os.path.exists(os.path.join(ROOT, d, name)) for d in ARTIFACT_DIRS)
        check(found, f"安装包实物：{name}", "README 承诺了这个产物，但 installer*/dist 下没有")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ci", action="store_true", help="跳过需要本地二进制的检查")
    args = ap.parse_args()

    readme = read(README)
    check_version_consistency(readme)
    check_tech_stack(readme)
    check_license_table(readme)
    check_license_compat()
    check_requirements()
    check_promised_artifacts(readme, args.ci)

    failed = [r for r in results if not r[0]]
    for ok, name, detail in results:
        mark = "OK  " if ok else "FAIL"
        line = f"[{mark}] {name}"
        # 通过时不打印「失败原因」，否则读起来自相矛盾；跳过说明照常打印
        if detail and (not ok or detail.startswith("CI 模式")):
            line += f" —— {detail}"
        print(line)

    print()
    if failed:
        print(f"发现 {len(failed)} 处文档漂移，请修正后再提交。")
        return 1
    print(f"全部 {len(results)} 项通过。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
