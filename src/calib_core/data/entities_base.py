# -*- coding: utf-8 -*-
# @version 2.7.0
"""术语/实体数据表

源：subtitle_calib_merged.py L7341-L7368 @ 97d7d463（2026-10-24 冻结快照）
"""
import io
import os
import re
import shutil
import sys
import unicodedata



class Entity:
    """对象级知识单元：一个角色/地点/势力/术语的全部校准知识。

    canonical  官方中文名（替换目标，唯一标识）
    modes      适用片源模式（bi/ja/jpe/ko/ak/akko/endo/zho/pgren/wwoc/react）
    en/ja/ko   官方外文原名（知识属性与投喂元数据，不直接参与替换）
    category   角色/地点/势力/术语/作品/主播/乐理…（对象级检索用）
    variants   无条件变体（ASR/机翻错形，出现即改 -> canonical）
    ctx        条件变体 ((参考行正则, 错形), ...)，佐证命中才把 错形->canonical
    exclude    负向排除正则（仅双语模式）：替换后参考行命中则回滚
    note       来源/依据/戒律（官方文本出处、易混对象提醒）
    """

    def __init__(self, canonical, modes=("bi",), en="", ja="", ko="",
                 category="", variants=(), ctx=(), exclude=(), note=""):
        self.canonical = canonical
        self.modes = tuple(modes)
        self.en, self.ja, self.ko = en, ja, ko
        self.category = category
        self.variants = tuple(variants)
        self.ctx = tuple(ctx)
        self.exclude = tuple(exclude)
        self.note = note

    def __repr__(self):
        return f"Entity({self.canonical!r}, modes={self.modes!r}, variants={len(self.variants)})"

