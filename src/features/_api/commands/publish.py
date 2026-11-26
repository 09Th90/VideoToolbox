# -*- coding: utf-8 -*-
# @version 3.3.1
"""publish 命令编排：从字幕生成发布素材（时间轴/tag/标题）。

与 GUI 发布素材页共用 features/publish/publish_material.py（L0 纯标准库）。
"""
from __future__ import annotations

import os

from features._api.errors import fail


def run(params: dict, log) -> dict:
    import features.publish.publish_material as pm  # noqa: PLC0415

    srt = os.path.abspath(params.get("srt", ""))
    if not os.path.isfile(srt):
        return fail("字幕不存在：%s" % srt)
    res = pm.generate_material(
        srt, video=params.get("video") or None,
        game=params.get("game") or None,
        streamer=params.get("streamer") or None,
        title_en=params.get("title_en") or None,
        out=params.get("out") or None, log=log)
    if not res.get("ok"):
        return fail(res.get("error") or "发布素材生成失败")
    return {"ok": True, "folder": res["folder"], "title": res["title"],
            "tags": res["tags"], "chapters": res["chapters"], "desc": res["desc"]}