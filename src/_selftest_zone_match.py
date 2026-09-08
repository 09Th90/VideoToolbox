# -*- coding: utf-8 -*-
"""离线自检：投稿「先上传再检测」现场分区匹配逻辑（v1.9.1）。

不联网、不开浏览器，只验证纯函数与导入链：
① match_zone_name 的精确/包含/归一化/未命中匹配；
② runner 的 detect_and_match_zone 各分支（AI 关闭、分区为空、未命中）；
③ STAGE_LABELS / GUI STAGE_HINTS 已包含新阶段。
运行：python _selftest_zone_match.py
"""
import asyncio
import logging
import os
import sys

logging.basicConfig(level=logging.CRITICAL)

SRC = os.path.dirname(os.path.abspath(__file__))
UP = os.path.join(SRC, "..", "tools", "uploader_src")
sys.path.insert(0, os.path.abspath(UP))
sys.dont_write_bytecode = True

import video_toolbox as engine  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.abspath(engine.__file__)))

FAILS = []


def check(name, cond, extra=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}{(' -> ' + extra) if extra else ''}")
    if not cond:
        FAILS.append(name)


def main():
    print("=" * 62)
    print("  投稿「先上传再检测」现场分区匹配自检（v1.9.1）")
    print("=" * 62)

    from modules.catalog import match_zone_name

    live = ["动画", "游戏", "音乐", "舞蹈", "影视", "纪录片", "知识", "科技",
            "数码", "汽车", "时尚美妆", "运动户外", "动物圈"]
    # ① 精确匹配
    check("精确匹配", match_zone_name("游戏", live) == "游戏")
    check("精确匹配（长名）", match_zone_name("时尚美妆", live) == "时尚美妆")
    # ② 归一化匹配（全角/空格/大小写）
    check("全角空格归一化", match_zone_name(" 游戏 ", live) == "游戏")
    check("全角字符归一化", match_zone_name("ｇａｍｅ", ["GAME", "动画"]) == "GAME")
    # ③ 包含匹配（输入不全/带后缀）
    check("包含匹配（任务名是现场名前缀）",
          match_zone_name("纪录", live) == "纪录片")
    check("包含匹配（任务名带冗余后缀）",
          match_zone_name("运动户外频道", live) == "运动户外")
    # ④ 未命中
    check("未命中返回 None", match_zone_name("番剧", live) is None)
    check("空目标返回 None", match_zone_name("  ", live) is None)
    check("空列表返回 None", match_zone_name("游戏", []) is None)

    # ② runner 分支逻辑（AI 关闭/分区为空/未命中）——agent 传 None 走轻量分支
    import uploader_runner as runner

    async def case_ai_off_with_zone():
        task = {"zone": "游戏", "submit": True}
        await runner.detect_and_match_zone(None, None, task)
        return task

    async def case_ai_off_no_zone_formal():
        task = {"zone": "", "submit": True}
        await runner.detect_and_match_zone(None, None, task)

    async def case_ai_off_no_zone_preview():
        task = {"zone": "", "submit": False}
        await runner.detect_and_match_zone(None, None, task)

    loop = asyncio.new_event_loop()
    try:
        t = loop.run_until_complete(case_ai_off_with_zone())
        check("AI关闭+有分区：直接通过", t["zone"] == "游戏")

        raised = False
        try:
            loop.run_until_complete(case_ai_off_no_zone_formal())
        except RuntimeError:
            raised = True
        check("AI关闭+无分区+正式投稿：终止", raised)

        raised = False
        try:
            loop.run_until_complete(case_ai_off_no_zone_preview())
        except RuntimeError:
            raised = True
        check("AI关闭+无分区+预览：继续", not raised)
    finally:
        loop.close()

    # ③ 阶段标签
    check("runner 阶段含 detect", runner.STAGE_LABELS.get("detect") == "现场检测分区")
    import video_toolbox_gui as gui
    all_kws = "".join(k for k, _ in gui.UploadTab.STAGE_HINTS)
    check("GUI 阶段提示含现场检测", "现场检测分区" in all_kws)
    check("GUI 阶段提示含分区已匹配", "已匹配现场分区" in all_kws)

    print("\n" + "=" * 62)
    if FAILS:
        print(f"  结果：{len(FAILS)} 项失败")
        for f in FAILS:
            print(f"    - {f}")
        print("=" * 62)
        return 1
    print("  结果：全部通过")
    print("=" * 62)
    return 0


if __name__ == "__main__":
    sys.exit(main())
