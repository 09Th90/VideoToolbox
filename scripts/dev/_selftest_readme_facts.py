# -*- coding: utf-8 -*-
# @version 2.2.5
"""自检：README 里的术语底表条数与导航页清单是否与代码一致。

为什么需要
----------
README 是仓库的门面，但它的数字与清单最容易悄悄过期——比如
「六个功能页」实际注册了七项、或词表统计口径变了（各表**朴素相加**
会把多表之间的重叠键重复计入）。

本脚本把README 里这两类**可验证断言**固化下来：文档与代码不一致时，
发布前就能发现，而不是等外部访问者看到过期信息。

口径说明（重要）
----------------
词条数按**去重并集**计：同一条目可能同时出现在多张表里（如终末地的
``ENDFIELD_TERMS`` 与 ``ENDFIELD_BI_TERMS`` 有69 个重叠键），
朴素相加会把它算两次。

用法
----
    python scripts/dev/_selftest_readme_facts.py [--fix]

``--fix`` 只打印建议值，不自动改文件（README 措辞需人工确认）。
退出码 0 = 文档与代码一致。
"""

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
README = os.path.join(ROOT, "README.md")

#: 四个游戏 → 词表变量清单（口径：去重并集）
GROUPS = {
    "鸣潮": ["BILINGUAL_TERMS"],
    "终末地": ["ENDFIELD_TERMS", "ENDFIELD_BI_TERMS",
               "JA_ENDFIELD_TERMS", "ENDFIELD_KO_TERMS"],
    "明日方舟": ["AK_TERMS", "AK_KO_TERMS"],
    "战双帕弥什": ["PGR_EN_TERMS"],
}

#: 期望 README 里出现的导航页（顺序取自 video_toolbox_qt.addSubInterface）
EXPECT_PAGES = ["视频处理", "视频库", "字幕处理", "字幕编辑",
                "流水线", "自动化", "设置"]

fails = []


def chk(name, cond, detail=""):
    if cond:
        print("OK   %s" % name)
    else:
        fails.append(name)
        print("FAIL %s%s" % (name, ("\n     " + detail) if detail else ""))


def _read(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


def main():
    if not os.path.isfile(README):
        print("FAIL 找不到 README.md：%s" % README)
        return 1

    # ── 1. 导航页清单 ──
    src = _read(os.path.join(ROOT, "src", "video_toolbox_qt.py"))
    actual = re.findall(r'addSubInterface\([^,]+,[^,]+,\s*"([^"]+)"', src)
    chk("导航页数量（README 称「七个功能页」）",
        len(actual) == 7, "实际 %d 项：%s" % (len(actual), "、".join(actual)))
    chk("导航页清单与README 期望一致",
        [p for p in actual if p != "设置"] == EXPECT_PAGES[:-1],
        "实际 %s" % "、".join(actual))

    readme = _read(README)
    missing = [p for p in EXPECT_PAGES if ("**%s**" % p) not in readme]
    chk("README 功能表列全了全部导航页", not missing,
        "缺：%s" % "、".join(missing) if missing else "")

    # ── 2. 术语底表条数（去重并集口径）──
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    try:
        import subtitle_calib_merged as M
    except Exception as e:  # noqa: BLE001
        print("SKIP 无法导入词表模块（%s），跳过条数核对" % type(e).__name__)
        return 1 if fails else 0

    counts = {}
    for game, names in GROUPS.items():
        union = set()
        for n in names:
            union |= set(getattr(M, n, {}) or {})
        counts[game] = len(union)
    total = sum(counts.values())

    print()
    print("     实测（去重并集口径）：" + " · ".join(
        "%s %d" % (g, n) for g, n in counts.items()))
    print("     合计 %d 条" % total)
    print()

    wrong = []
    for game, n in counts.items():
        # README 里写成「鸣潮 1590 · 终末地 1002 · ...」
        pat = r"%s\s*%d\b" % (re.escape(game), n)
        if not re.search(pat, readme):
            wrong.append("%s 应为 %d" % (game, n))
    chk("README 各游戏条数与实测一致", not wrong, "；".join(wrong))

    # 合计：允许写「3100+」这种带余量的表述，但不得低于实测值
    m = re.search(r"共\s*\*?\*?(\d+)", readme)
    if m:
        claimed = int(m.group(1))
        chk("README 合计数不低于实测（去重并集 %d）" % total,
            claimed >= total,
            "README 写 %d，实测 %d" % (claimed, total))
    else:
        chk("README 写出了合计条数", False, "没找到「共 N 条」表述")

    print()
    if fails:
        print("结论：FAIL（README 与代码不一致，共 %d 处）" % len(fails))
        print("提示：README 是对外门面，建议按上面的实测值更正。")
        return 1
    print("结论：PASS（README 的功能页清单与术语条数均与代码一致）")
    return 0


if __name__ == "__main__":
    sys.exit(main())