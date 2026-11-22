# -*- coding: utf-8 -*-
# @version 3.1.6
"""门禁片源表（T7 family_gap 验收 + T10 门禁编排共用）：7 片 10 组。

7 片 = 本机 D:\\原片 下已有**校准产物**的 7 部片（ak/bi×2/ja×2/zho×2），
       family_gap 双轨验收跑的就是这 7 片的现行产物（cur）；
10 组 = 上述 7 组（cur）+ 3 组上一版产物（prev：ak-idr-v1 / ja-wuwa40ja-v1 /
       ja-yaba-v1），onepass/verify 门禁跑 10 组。

铁律：片源是外部资产（不在仓库内、不随包分发）。任何一台机器缺哪部片，
对应组一律 SKIP 并在输出里点名，不得让门禁假绿、也不得误红。
"""
from __future__ import annotations

import os

#: (组名, 模式, 说明, 现行产物, 上一版产物或 None)
FILMS = [
    ("ak-idr", "ak", "明日方舟周边开箱（Arknights Fan Merch）",
     r"D:\原片\I Spent 10000000 IDR For Arknights Fan Merch"
     r"\【字幕】I Spent 10000000 IDR For Arknights Fan Merch.en-微软翻译_calibrated_v2.srt",
     r"D:\原片\I Spent 10000000 IDR For Arknights Fan Merch"
     r"\【字幕】I Spent 10000000 IDR For Arknights Fan Merch.en-微软翻译_calibrated.srt"),
    ("bi-tell", "bi", "鸣潮叙事短片 Reaction（How You Tell a Great Story）",
     r"D:\原片\Now THIS Is How You Tell a Great Story"
     r"\【字幕】Now THIS Is How You Tell a Great Story.en-微软翻译_calibrated_v2.srt",
     None),
    ("bi-wuwaall", "bi", "鸣潮全短片 Reaction 合集（Star Rail Player REACTS）",
     r"D:\原片\Star Rail Player REACTS To ALL Wuthering Waves Cinematic Shorts"
     r"\【字幕】Star Rail Player REACTS To ALL Wuthering Waves Cinematic Shorts-谷歌翻译_calibrated_v2.srt",
     None),
    ("ja-yaba", "ja", "鸣潮 4.0 先行映像日文实况（やばすぎる）",
     r"D:\原片\【鳴潮】Ver4.0の先行映像がやばすぎる！！！【Wuthering Waves】"
     r"\【字幕】【鳴潮】Ver4.0の先行映像がやばすぎる！！！【Wuthering Waves】.ja-精校.r2.srt",
     r"D:\原片\【鳴潮】Ver4.0の先行映像がやばすぎる！！！【Wuthering Waves】"
     r"\【字幕】【鳴潮】Ver4.0の先行映像がやばすぎる！！！【Wuthering Waves】.ja-精校.srt"),
    ("ja-wuwa40ja", "ja", "鸣潮 4.0 先行映像日文实况（ぶっ飛んでる）",
     r"D:\原片\【鳴潮】Ver4.0先行映像がぶっ飛んでる【Wuthering Waves】 (2)"
     r"\【字幕】【鳴潮】Ver4.0先行映像がぶっ飛んでる【Wuthering Waves】.ja-微软翻译_calibrated_v2.srt",
     r"D:\原片\【鳴潮】Ver4.0先行映像がぶっ飛んでる【Wuthering Waves】 (2)"
     r"\【字幕】【鳴潮】Ver4.0先行映像がぶっ飛んでる【Wuthering Waves】.ja-微软翻译_calibrated.srt"),
    ("zho-minshi1", "zho", "二游人民史观评论文（一定能写出）",
     r"D:\原片\凭什么二游一定能写出人民史观！\凭什么二游一定能写出人民史观！_校准.srt",
     None),
    ("zho-minshi2", "zho", "二游人民史观评论文（不可能写出）",
     r"D:\原片\凭什么说二游不可能写出人民史观？\凭什么说二游不可能写出人民史观？_校准.srt",
     None),
]

#: 10 组门禁夹具 = 7 组现行产物 + 3 组上一版产物（组名带 -v1 后缀）
PREV_GROUPS = ("ak-idr", "ja-wuwa40ja", "ja-yaba")


def audit_films():
    """7 片现行产物 → [(name, mode, path|None, note)]；缺片 path=None（调用方 skip）。"""
    out = []
    for name, mode, note, cur, _prev in FILMS:
        out.append((name, mode, cur if os.path.isfile(cur) else None, note))
    return out


def gate_groups():
    """10 组门禁夹具 → [(group, mode, path|None)]；缺片 path=None（调用方 skip）。"""
    out = []
    for name, mode, _note, cur, prev in FILMS:
        out.append((name, mode, cur if os.path.isfile(cur) else None))
        if name in PREV_GROUPS and prev:
            out.append((name + "-v1", mode, prev if os.path.isfile(prev) else None))
    return out
