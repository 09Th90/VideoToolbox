#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# @version 1.16.5
"""说话人（diarization / separation）链路自检（离线，不联网）。

覆盖 v1.15.9 新增能力：
  · Cue.speaker 结构化字段 + SRT / ASS 读写往返
  · [说话人N] 前缀解析 / 生成
  · 按说话人分轨（独立字幕轨）、配色板、逐人统计与声线分配
  · render_ass 彩色多人字幕（每说话人一条 Style + Name 列）
  · 预览层 SubtitleStage 按说话人取色
  · 引擎 asr_separate_of / _asr_separate_audio 接口占位
  · ai_client.asr_config 暴露 separate

运行：tools/python/python.exe _selftest_speaker.py
结果同时打印到 stdout 并写入 C:\\bld\\_speaker_test\\result.txt。
"""
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("VT_NO_PIPELINE", "1")
os.environ.setdefault("VT_NO_SYNC", "1")
os.environ.setdefault("VT_NO_CALIB_SYNC", "1")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import video_toolbox as engine  # noqa: E402
import subtitle_editor_core as secore  # noqa: E402

# 与 _selftest_gui.py 同一套 Qt 插件路径（否则预览层构造时找不到平台插件）
os.environ.setdefault(
    "QT_QPA_PLATFORM_PLUGIN_PATH",
    os.path.join(engine.EMBEDDED_SITE_PACKAGES, "PyQt5", "Qt5", "plugins"))

OUT = r"C:\bld\_speaker_test"
LINES, FAILS = [], []


def say(m):
    LINES.append(str(m))
    print(m)


def check(name, cond, extra=""):
    line = "  [%s] %s%s" % ("PASS" if cond else "FAIL", name,
                            (" -> " + str(extra)) if extra else "")
    say(line)
    if not cond:
        FAILS.append(name)


SRT = """1
00:00:01,000 --> 00:00:03,000
[说话人1] 我觉得这个方案不行

2
00:00:03,200 --> 00:00:05,000
[说话人2] 我也这么看

3
00:00:05,100 --> 00:00:07,000
那你们说怎么办

4
00:00:07,200 --> 00:00:09,000
[说话人1] 那我们再想想
"""


def main():
    say("=" * 62)
    say("  说话人链路自检（diarization / separation）")
    say("=" * 62)

    # ---------------- 1) 前缀解析 / 生成 ----------------
    say("\n== 1) [说话人N] 前缀解析与生成 ==")
    check("前缀拆出标签与纯台词",
          secore.split_speaker_prefix("[说话人2] 在的什么事")
          == ("说话人2", "在的什么事"))
    check("全角方括号也认",
          secore.split_speaker_prefix("［说话人3］台词")
          == ("说话人3", "台词"))
    check("无前缀时原样返回",
          secore.split_speaker_prefix("普通台词") == ("", "普通台词"))
    check("空标签生成空前缀", secore.speaker_prefix("") == "")
    check("标签生成前缀", secore.speaker_prefix("说话人1") == "[说话人1] ")

    # ---------------- 2) SRT 往返 ----------------
    say("\n== 2) SRT 往返（前缀 <-> speaker 字段）==")
    doc = secore.SubtitleDoc()
    n, skipped = doc.load_bytes(SRT.encode("utf-8"))
    # 注：SRT 的序号行（"1"/"2"…）会被宽松解析计入 skipped，属既有口径
    check("解析条数正确", n == 4, (n, skipped))
    check("speaker 落进结构化字段、text 只剩纯台词",
          [(c.speaker, c.text) for c in doc.cues]
          == [("说话人1", "我觉得这个方案不行"), ("说话人2", "我也这么看"),
              ("", "那你们说怎么办"), ("说话人1", "那我们再想想")],
          [(c.speaker, c.text) for c in doc.cues])
    out = doc.dump()
    check("dump 把前缀补回 SRT（进出对称）",
          "[说话人1] 我觉得这个方案不行" in out
          and "[说话人2] 我也这么看" in out
          and out.count("[说话人") == 3, out.count("[说话人"))
    doc2 = secore.SubtitleDoc()
    doc2.load_bytes(out.encode("utf-8"))
    check("二次往返不漂移",
          [(c.speaker, c.text) for c in doc2.cues]
          == [(c.speaker, c.text) for c in doc.cues])

    # ---------------- 3) 分轨 / 配色 / 统计 / 声线 ----------------
    say("\n== 3) 独立字幕轨 / 配色 / 逐人统计 / 声线 ==")
    check("cue_speakers 按出场顺序去重",
          secore.cue_speakers(doc.cues) == ["说话人1", "说话人2"],
          secore.cue_speakers(doc.cues))
    tracks = secore.split_by_speaker(doc.cues)
    check("分轨顺序 = 出场顺序，无归属轨排最后",
          [s for s, _ in tracks] == ["说话人1", "说话人2", ""],
          [s for s, _ in tracks])
    check("每轨条目数正确（A 2 / B 1 / 无归属 1）",
          [len(cs) for _, cs in tracks] == [2, 1, 1],
          [len(cs) for _, cs in tracks])
    check("每轨各自保留独立时间轴",
          [c.start for c in tracks[0][1]] == [1000, 7200],
          [c.start for c in tracks[0][1]])
    cmap = secore.speaker_color_map(secore.cue_speakers(doc.cues))
    check("两个说话人拿到不同颜色",
          cmap["说话人1"] != cmap["说话人2"], cmap)
    check("配色板循环取色（超出长度后回绕）",
          secore.speaker_color_map(
              ["s%d" % i for i in range(len(secore.SPEAKER_PALETTE) + 2)]
          )["s%d" % len(secore.SPEAKER_PALETTE)] == secore.SPEAKER_PALETTE[0])
    stats = secore.speaker_stats(doc.cues)
    check("逐人统计：条数 / 时长 / 字数",
          stats[0][0] == "说话人1" and stats[0][1] == 2
          and stats[0][2] == 2000 + 1800, stats)
    vmap = secore.speaker_voice_map(["说话人1", "说话人2"], ["v1", "v2"])
    check("声线按说话人分配", vmap == {"说话人1": "v1", "说话人2": "v2"}, vmap)
    check("无声线候选返回空字典",
          secore.speaker_voice_map(["说话人1"], []) == {})

    # ---------------- 4) 彩色 ASS ----------------
    say("\n== 4) 彩色多人字幕 ASS ==")
    ass = secore.render_ass(doc.cues)
    check("每个说话人一条独立 Style（Spk1 / Spk2）",
          "Style: Spk1," in ass and "Style: Spk2," in ass)
    check("无归属条目仍走 Default",
          ",Default,,0,0,0,," in ass)
    check("Dialogue 引用说话人 Style 且 Name 列写标签",
          "Dialogue: 0,0:00:01.00,0:00:03.00,Spk1,说话人1,0,0,0,," in ass
          and "Spk2,说话人2," in ass)
    check("Spk1 主色 = 调色板第 1 色（BGR 序）",
          secore._ass_color(secore.SPEAKER_PALETTE[0]) in ass,
          secore._ass_color(secore.SPEAKER_PALETTE[0]))
    doc3 = secore.SubtitleDoc()
    doc3.load_bytes(ass.encode("utf-8"))
    check("ASS 往返：从 Name 列还原说话人",
          [c.speaker for c in doc3.cues] == ["说话人1", "说话人2", "", "说话人1"],
          [c.speaker for c in doc3.cues])
    check("ASS 往返：正文不带前缀（已剥离）",
          all("[说话人" not in c.text for c in doc3.cues))

    # ---------------- 5) 向后兼容（无说话人） ----------------
    say("\n== 5) 向后兼容：无说话人时与旧版一致 ==")
    plain = [secore.Cue(0, 1000, "甲"), secore.Cue(1000, 2000, "乙")]
    pass_ = secore.render_ass(plain)
    _styles = [ln for ln in pass_.split("\n") if ln.startswith("Style: ")]
    check("只生成 Default 一条 Style", len(_styles) == 1, _styles)
    check("Dialogue 仍是 Default + 空 Name",
          "Dialogue: 0,0:00:00.00,0:00:01.00,Default,,0,0,0,,甲" in pass_)
    check("无说话人 dump 不产生前缀",
          "[说话人" not in secore.SubtitleDoc(cues=plain).dump())

    # ---------------- 6) 预览层按说话人取色 ----------------
    say("\n== 6) 预览层 SubtitleStage 分色 ==")
    try:
        from PyQt5.QtWidgets import QApplication, QWidget
        import subtitle_overlay as so
        app = QApplication.instance() or QApplication([])
        host = QWidget()
        stage = so.SubtitleStage(host, None, lambda: None)
        stage.set_style({"color": "#FFFFFF", "size": 40})
        stage.set_speaker_colors(secore.speaker_color_map(["说话人1", "说话人2"]))
        c_a = secore.Cue(0, 1000, "甲", "说话人1")
        c_n = secore.Cue(1000, 2000, "乙")
        st_a = stage._style_for_cue(c_a)
        st_n = stage._style_for_cue(c_n)
        check("带说话人的条目主色被覆盖",
              st_a["color"] == secore.SPEAKER_PALETTE[0], st_a.get("color"))
        check("无归属条目沿用面板主色",
              st_n["color"] == "#FFFFFF", st_n.get("color"))
        check("覆盖只动 color，不改字号/位置",
              st_a["size"] == 40 and "pos_x" not in st_a)
        stage.set_speaker_colors({})
        check("清空映射后回到面板主色",
              stage._style_for_cue(c_a)["color"] == "#FFFFFF")
    except Exception as e:  # noqa: BLE001
        check("预览层分色可运行", False, repr(e))

    # ---------------- 7) 引擎：语音分离接口占位 ----------------
    say("\n== 7) 引擎语音分离（Separation）接口 ==")
    check("asr_separate_of 默认关",
          engine.asr_separate_of({}) is False)
    check("asr_separate_of 认 asr_separate 各种真值",
          all(engine.asr_separate_of({"asr_separate": v})
              for v in (True, 1, "true", "yes", "on", "1")))
    check("asr_separate_of 认假值",
          not any(engine.asr_separate_of({"asr_separate": v})
                  for v in (False, 0, "no", "", None)))
    obj = types.SimpleNamespace(separate=True)
    check("_asr_separate_on 优先读实例值", engine._asr_separate_on(obj) is True)
    obj2 = types.SimpleNamespace()
    check("_asr_separate_on 实例无值时回落配置",
          engine._asr_separate_on(obj2) is False)
    res = engine._asr_separate_audio("demo.mp3")
    check("分离接口占位：直通返回原轨（不引入模型）",
          res == [(None, "demo.mp3")], res)

    # ---------------- 8) 配置贯通 ----------------
    say("\n== 8) 配置贯通（ai_client / 引擎）==")
    try:
        ai = engine.ai_mod()
        ac = ai.asr_config({"asr_separate": True, "asr_diarize": True})
        check("ai_client.asr_config 暴露 separate",
              ac.get("separate") is True and ac.get("diarize") is True, ac)
        ac2 = ai.asr_config({})
        check("默认 separate 为 False", ac2.get("separate") is False)
    except Exception as e:  # noqa: BLE001
        check("ai_client.asr_config 可读", False, repr(e))

    # ---------------- 9) 翻译锚定已写入归档源 ----------------
    say("\n== 9) 翻译一致性锚定 ==")
    try:
        p = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "docs", "vc_translate_impl",
            "subtitle_thread.py")
        src = open(p, encoding="utf-8").read()
        check("归档源含说话人一致性提示词注入",
              "speaker_info" in src and "Speaker diarization" in src)
        check("运行时引擎已同步该改动",
              "speaker_info" in open(os.path.join(
                  engine.EMBEDDED_SITE_PACKAGES, "videocaptioner", "ui",
                  "thread", "subtitle_thread.py"), encoding="utf-8").read())
    except Exception as e:  # noqa: BLE001
        check("翻译锚定源可读", False, repr(e))

    # ---------------- 汇总 ----------------
    say("\n" + "=" * 62)
    if FAILS:
        say("  结果：%d 项失败" % len(FAILS))
        for f in FAILS:
            say("   · " + f)
    else:
        say("  结果：全部通过")
    say("=" * 62)
    try:
        os.makedirs(OUT, exist_ok=True)
        with open(os.path.join(OUT, "result.txt"), "w", encoding="utf-8") as fh:
            fh.write("\n".join(LINES) + "\n")
    except OSError:
        pass
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
