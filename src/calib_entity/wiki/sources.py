# @version 2.7.0
"""四站配置 + 标题规范化。

| 作品 | 源 | 分类 | 标题形态 |
|---|---|---|---|
| 明日方舟 | wiki.biligame.com/arknights | Category:干员 | 中文名（12F / 阿 / 阿兰娜） |
| 战双帕弥什 | wiki.biligame.com/zspms | Category:构造体 | 机体名（21号·森息 / 阿德莱德·破渊） |
| 鸣潮 | wiki.biligame.com/wutheringwaves | Category:共鸣者 | 命名空间式（共鸣者/爱弥斯） |
| 终末地 | endfield.wiki.gg | Category:Operators | 英文名（Akekuri / Alesh） |

终末地在 B 站 wiki 体系里没有独立站点（`wiki.biligame.com/endfield` 301 到总首页），
PRTS 也没有对应分类，所以只能取英文站，中文名靠库内已有条目匹配。
"""
from __future__ import annotations

import re
from typing import Dict, List, Tuple

SITES: Dict[str, dict] = {
    "明日方舟": {
        "api": "https://wiki.biligame.com/arknights/api.php",
        "categories": ["Category:干员"],
        "lang": "zh",
    },
    "战双帕弥什": {
        "api": "https://wiki.biligame.com/zspms/api.php",
        "categories": ["Category:构造体", "Category:人物", "Category:世界观人物"],
        # `世界观/` 616 条：地名、势力、设定词条的集中地
        "prefixes": ["世界观/", "人物档案/"],
        "lang": "zh",
    },
    "鸣潮": {
        "api": "https://wiki.biligame.com/wutheringwaves/api.php",
        # 共鸣者=可玩角色；声骸/敌人/武器 是专名密度最高的三块
        "categories": ["Category:共鸣者", "Category:声骸", "Category:敌人", "Category:武器"],
        # `名词注释/` 409 条：鸣潮地名/术语的官方解释
        "prefixes": ["名词注释/", "设定拾遗/"],
        "lang": "zh",
    },
    "终末地": {
        "api": "https://endfield.wiki.gg/api.php",
        "categories": ["Category:Operators", "Category:Characters"],
        "lang": "en",
    },
}

#: 需要剔除的页面（分类里混入的列表页/说明页）
_SKIP_TITLE = re.compile(
    r"^(?:分类|Category|模板|Template|文件|File|沙盒|Sandbox|首页|Main Page)[:：/]"
    r"|(?:一览|列表|图鉴|导航|说明)$")


def normalize_title(work: str, title: str) -> List[str]:
    """把 wiki 标题规范成可匹配的中文名候选。

    * 鸣潮 `共鸣者/爱弥斯` -> `爱弥斯`
    * 战双 `21号·森息` -> `21号`（主名）+ `21号·森息`（全名），两个都留
    * 明日方舟 `阿兰娜` -> `阿兰娜`
    * 终末地 `Akekuri` -> 原样（英文，供 en 字段）
    """
    t = (title or "").strip()
    if not t or _SKIP_TITLE.search(t):
        return []
    if "/" in t:
        t = t.split("/")[-1].strip()
    # 占位名/纯符号（如 `■■`）没有检索价值
    if not re.search(r"[\u4e00-\u9fffA-Za-z0-9]", t):
        return []
    out = [t]
    # 明日方舟：`阿米娅（近卫）` / `阿米娅(医疗)` -> 主名
    base = re.sub(r"[（(][^（()）]{1,8}[)）]\s*$", "", t).strip()
    if base and base != t:
        out.append(base)
    if work == "战双帕弥什" and "·" in t:
        head = t.split("·")[0].strip()
        if head and head not in out:
            out.append(head)
    return [x for x in out if x]


def is_latin(s: str) -> bool:
    return bool(s) and all(ord(c) < 128 for c in s)
