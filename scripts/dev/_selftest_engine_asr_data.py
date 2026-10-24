# @version 2.7.0
"""自检：engine_asr_data 与第三方引擎 asr_data 的逐行为兼容性。

P1 接缝验收脚本（第二个）。判定口径同 ``_selftest_engine_entities.py``：
不是「能 import」而是**同一输入下逐字节/逐字段一致**——

* ``to_json`` / ``from_json`` 的 JSON 形状是引擎字幕表格模型
  ``SubtitleTableModel._data`` 的交换契约（调用方
  ``ASRData.from_json(iface.model._data).to_srt(save_path=...)`` 依赖它）；
* ``to_srt`` / ``to_txt`` / ``to_ass`` / ``from_srt`` / ``from_vtt`` /
  ``from_youtube_vtt`` / ``from_ass`` 等是落盘与解析行为，调用方以输出
  文件内容为事实。

结构
----
正向：一个 probe 子进程分别以 mine / engine 两种模式跑全部用例，产出
行为快照 JSON，主进程逐键比对。
负向：污染自研源码副本（改契约字段/改格式/改分词区间），确认正向比对
**确实会失败**（防「绿屏假象」）。

已知有意差异（模块文档「与引擎行为的有意差异」）：
* ``to_ass`` 输出不含上游品牌注释两行（比对前由 probe 从 engine 侧剥离，
  并单独断言差异行集合恰为品牌注释）；
* 负时间格式化钳 0、``remove_punctuation`` 对 None 译文兜底——均为异常
  输入，本脚本不构造此类输入。

用法
----
    python scripts/dev/_selftest_engine_asr_data.py

依赖第三方包（仅校验期需要）。退出码 0 = 通过。
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
SRC = os.path.join(ROOT, "src")

#: 用随包 CPython 跑（托管 python 无 videocaptioner 依赖树）
PYPARSE = os.path.join(ROOT, "tools", "python", "python.exe")
if not os.path.exists(PYPARSE):  # 退化：当前解释器
    PYPARSE = sys.executable

#: probe：同一份用例代码，按 mode 切换 import 来源，输出行为快照 JSON。
PROBE = r'''
import json, os, sys, tempfile, shutil

mode = sys.argv[1]
if mode == "mine":
    from engine_asr_data import ASRData, ASRDataSeg, handle_long_path
    from engine_entities import SubtitleLayoutEnum
else:
    from videocaptioner.core.asr.asr_data import ASRData, ASRDataSeg, handle_long_path
    from videocaptioner.core.entities import SubtitleLayoutEnum

def ser_seg(s):
    return [s.text, s.translated_text, s.start_time, s.end_time]

def ser(d):
    return [ser_seg(s) for s in d.segments]

def exc(fn):
    """返回异常类型名（无异常返回 None）。"""
    try:
        fn()
        return None
    except Exception as e:
        return type(e).__name__

out = {}

# ---------- ASRDataSeg ----------
seg = ASRDataSeg("Hello world", 1000, 2500, "你好世界")
out["seg_attrs"] = ser_seg(seg)
out["seg_to_srt_ts"] = seg.to_srt_ts()
out["seg_to_lrc_ts"] = seg.to_lrc_ts()
out["seg_to_ass_ts"] = list(seg.to_ass_ts())
out["seg_transcript"] = seg.transcript
out["seg_str"] = str(seg)
out["seg_ms_conv"] = [
    ASRDataSeg._ms_to_srt_time(3661500),
    ASRDataSeg._ms_to_ass_ts(3661500),
    ASRDataSeg._ms_to_lrc_time(3661500),
    ASRDataSeg._ms_to_lrc_time(61500),
    ASRDataSeg._ms_to_lrc_time(999),
    ASRDataSeg._ms_to_srt_time(0),
    ASRDataSeg._ms_to_ass_ts(0),
]
out["handle_long_path_short"] = handle_long_path("rel/path.srt")

# ---------- ASRData 构造（过滤空文本 + 按起点排序） ----------
raw = [
    ASRDataSeg("third", 5000, 6000, "三"),
    ASRDataSeg("  ", 100, 200),
    ASRDataSeg("first", 1000, 2500, "一"),
    ASRDataSeg("", 300, 400),
    ASRDataSeg("second", 2600, 4000, ""),
]
d = ASRData(raw)
out["data_construct"] = ser(d)
out["data_len"] = len(d)
out["data_has_data"] = d.has_data()
out["data_iter"] = [ser_seg(s) for s in d]

# ---------- to_json / from_json（表格模型 _data 交换契约） ----------
out["to_json"] = d.to_json()
out["from_json_roundtrip"] = ser(ASRData.from_json(d.to_json()))
# 表格模型真实形状：键为字符串序号（无序字典也要按 int 排序）
model_data = {
    "2": {"start_time": 2600, "end_time": 4000,
          "original_subtitle": "second", "translated_subtitle": "二"},
    "1": {"start_time": 1000, "end_time": 2500,
          "original_subtitle": "first", "translated_subtitle": "一"},
}
out["from_json_model_shape"] = ser(ASRData.from_json(model_data))

# ---------- 导出：四种 layout ----------
for name, layout in [
    ("srt_default", SubtitleLayoutEnum.ORIGINAL_ON_TOP),
    ("srt_translate_top", SubtitleLayoutEnum.TRANSLATE_ON_TOP),
    ("srt_only_orig", SubtitleLayoutEnum.ONLY_ORIGINAL),
    ("srt_only_trans", SubtitleLayoutEnum.ONLY_TRANSLATE),
    ("txt_default", SubtitleLayoutEnum.ORIGINAL_ON_TOP),
    ("txt_translate_top", SubtitleLayoutEnum.TRANSLATE_ON_TOP),
    ("txt_only_orig", SubtitleLayoutEnum.ONLY_ORIGINAL),
    ("txt_only_trans", SubtitleLayoutEnum.ONLY_TRANSLATE),
    ("ass_default", SubtitleLayoutEnum.ORIGINAL_ON_TOP),
    ("ass_translate_top", SubtitleLayoutEnum.TRANSLATE_ON_TOP),
    ("ass_only_orig", SubtitleLayoutEnum.ONLY_ORIGINAL),
    ("ass_only_trans", SubtitleLayoutEnum.ONLY_TRANSLATE),
]:
    if name.startswith("srt"):
        out[name] = d.to_srt(layout=layout)
    elif name.startswith("txt"):
        out[name] = d.to_txt(layout=layout)
    else:
        out[name] = d.to_ass(layout=layout)

# ---------- save 分发（写临时文件读回） ----------
tmp = tempfile.mkdtemp(prefix="vt_asr_")
try:
    for ext, fn in [("srt", lambda p: d.save(p)),
                    ("txt", lambda p: d.save(p)),
                    ("json", lambda p: d.save(p)),
                    ("ass", lambda p: d.save(p))]:
        p = os.path.join(tmp, "out." + ext)
        fn(p)
        with open(p, encoding="utf-8") as f:
            out["save_" + ext] = f.read()
    out["save_bad_ext"] = exc(lambda: d.save(os.path.join(tmp, "out.mp4")))
finally:
    shutil.rmtree(tmp, ignore_errors=True)

# ---------- from_srt ----------
# ⚠️ 双语判定走 langdetect，其 detect() 依赖进程内 DetectorFactory 单例的
# random 状态，短拉丁文本跨进程不稳定（引擎自身同样不稳定）。因此用例只
# 覆盖两类：（a）不过 detect 的路径（非 4 行块）；（b）跨进程稳定的语言对
# （纯中文 vs 纯韩文，实测三个进程一致）。「同为英语短文本被误判为双语」
# 的非确定性场景不做逐字节断言——引擎在该场景下自身也不稳定。
srt_single = (
    "1\n00:00:01,000 --> 00:00:02,500\nHello world\n\n"
    "2\n00:00:02,600 --> 00:00:04,000\nSecond line\n"
)
out["from_srt_single"] = ser(ASRData.from_srt(srt_single))

srt_bilingual = (
    "1\n00:00:01,000 --> 00:00:02,500\n你好世界\n안녕하세요\n\n"
    "2\n00:00:02,600 --> 00:00:04,000\n问候语\n반갑습니다\n"
)
out["from_srt_bilingual"] = ser(ASRData.from_srt(srt_bilingual))

# 5 行块（序号+时间+3 文本）：all_four_lines=False，不过语言检测，
# 测多行文本合并路径
srt_multiline = (
    "1\n00:00:01,000 --> 00:00:02,500\nLine one\nLine two\nLine three\n\n"
    "2\n00:00:02,600 --> 00:00:04,000\nAnother\nMore\nText\n"
)
out["from_srt_multiline"] = ser(ASRData.from_srt(srt_multiline))

# 4 行块 + 同行文两行（纯中文，跨进程稳定同判 zh-cn）：is_different_lang
# 返回 False 的路径（4 行块但非双语 → 多行合并）
srt_four_cjk = (
    "1\n00:00:01,000 --> 00:00:02,500\n你好啊\n朋友们\n\n"
    "2\n00:00:02,600 --> 00:00:04,000\n好的吗\n可以呀\n"
)
out["from_srt_four_cjk"] = ser(ASRData.from_srt(srt_four_cjk))

# ---------- from_vtt / from_youtube_vtt ----------
vtt = (
    "WEBVTT\n\n"
    "00:00:01.000 --> 00:00:02.500\nHello world\n\n"
    "cue-2\n00:02.600 --> 00:04.000 align:start position:0%\nSecond <b>line</b>\n"
)
out["from_vtt"] = ser(ASRData.from_vtt(vtt))

yt_vtt = (
    "WEBVTT\nKind: captions\nLanguage: en\n\n"
    "00:00:01.000 --> 00:00:02.500\n"
    "<00:00:01.000><c>Hello</c> <00:00:01.500><c>world</c>\n\n"
    "00:00:02.600 --> 00:00:04.000\n"
    "<00:00:02.600><c>Second</c> <00:00:03.200><c>line</c>\n"
)
out["from_youtube_vtt"] = ser(ASRData.from_youtube_vtt(yt_vtt))

# ---------- from_ass：单样式 / Default+Secondary 配对 ----------
ass_single = (
    "[Script Info]\nScriptType: v4.00+\n\n"
    "[V4+ Styles]\nFormat: Name, Fontname\nStyle: Default,Arial\n\n"
    "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    "Dialogue: 0,0:00:01.00,0:00:02.50,Default,,0,0,0,,Hello world\n"
    "Dialogue: 0,0:00:02.60,0:00:04.00,Default,,0,0,0,,Second line\n"
)
out["from_ass_single"] = ser(ASRData.from_ass(ass_single))

ass_paired = (
    "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    "Dialogue: 0,0:00:01.00,0:00:02.50,Default,,0,0,0,,Hello world\n"
    "Dialogue: 0,0:00:01.00,0:00:02.50,Secondary,,0,0,0,,你好世界\n"
    "Dialogue: 0,0:00:02.60,0:00:04.00,Default,,0,0,0,,Second line\n"
    "Dialogue: 0,0:00:02.60,0:00:04.00,Secondary,,0,0,0,,第二行\n"
)
out["from_ass_paired"] = ser(ASRData.from_ass(ass_paired))

# ---------- from_subtitle_file：四种后缀 + 异常契约 ----------
tmp = tempfile.mkdtemp(prefix="vt_asr_")
try:
    for ext, content in [("srt", srt_single), ("json", json.dumps(d.to_json())),
                         ("vtt", vtt), ("ass", ass_single)]:
        p = os.path.join(tmp, "in." + ext)
        with open(p, "w", encoding="utf-8") as f:
            f.write(content)
        out["from_file_" + ext] = ser(ASRData.from_subtitle_file(p))
    out["from_file_missing"] = exc(
        lambda: ASRData.from_subtitle_file(os.path.join(tmp, "nope.srt")))
    bad = os.path.join(tmp, "in.mp4")
    with open(bad, "w", encoding="utf-8") as f:
        f.write("x")
    out["from_file_bad_ext"] = exc(lambda: ASRData.from_subtitle_file(bad))
finally:
    shutil.rmtree(tmp, ignore_errors=True)

# ---------- 行为方法 ----------
sent = ASRData([ASRDataSeg("This is a full sentence here", 0, 3000, "")])
out["is_word_sentence"] = sent.is_word_timestamp()
word = ASRData([ASRDataSeg("hello", 0, 500), ASRDataSeg("world", 500, 1000)])
out["is_word_word"] = word.is_word_timestamp()
out["is_word_empty"] = ASRData([]).is_word_timestamp()

out["split_word_en"] = ser(ASRData(
    [ASRDataSeg("Hello world", 0, 2000)]).split_to_word_segments())
out["split_word_cjk"] = ser(ASRData(
    [ASRDataSeg("你好世界", 0, 2000)]).split_to_word_segments())

punct = ASRData([ASRDataSeg("你好，世界。", 0, 1000, "Hello, world。")])
out["remove_punctuation"] = ser(punct.remove_punctuation())

opt = ASRData([ASRDataSeg("first", 0, 2000, ""), ASRDataSeg("second", 2500, 4000, "")])
out["optimize_timing"] = ser(opt.optimize_timing())
opt_wide = ASRData([ASRDataSeg("first", 0, 2000, ""),
                    ASRDataSeg("second", 9000, 11000, "")])
out["optimize_timing_wide_gap"] = ser(opt_wide.optimize_timing())

mg = ASRData([ASRDataSeg("first", 0, 2000, "一"),
              ASRDataSeg("second", 2000, 4000, "二")])
mg.merge_segments(0, 1)
out["merge_segments"] = ser(mg)
mg2 = ASRData([ASRDataSeg("first", 0, 2000, "一"),
               ASRDataSeg("second", 2000, 4000, "二")])
mg2.merge_segments(0, 1, "custom")
out["merge_segments_custom"] = ser(mg2)
mn = ASRData([ASRDataSeg("first", 0, 2000, "一"),
              ASRDataSeg("second", 2000, 4000, "")])
mn.merge_with_next_segment(0)
out["merge_with_next"] = ser(mn)
out["merge_index_error"] = exc(
    lambda: ASRData([ASRDataSeg("only", 0, 100)]).merge_segments(5, 6))
out["merge_next_index_error"] = exc(
    lambda: ASRData([ASRDataSeg("only", 0, 100)]).merge_with_next_segment(0))

# ---------- 未实现格式 ----------
out["to_lrc_error"] = exc(lambda: d.to_lrc())
out["to_vtt_error"] = exc(lambda: d.to_vtt())

print(json.dumps(out, ensure_ascii=False))
'''

#: to_ass 上游品牌注释（唯一有意差异，比对前从 engine 侧剥离并单独断言）
BRAND_COMMENT = "; Script generated by VideoCaptioner\n; https://github.com/weifeng2333\n"


def _run_probe(mode, src_override=None, allow_fail=False):
    env = dict(os.environ)
    # src_override 只放被污染的副本；项目其余模块（engine_entities /
    # subtitle_editor_core）仍从 SRC 找
    paths = (src_override + os.pathsep + SRC) if src_override else SRC
    env["PYTHONPATH"] = paths + os.pathsep + env.get("PYTHONPATH", "")
    p = subprocess.run([PYPARSE, "-c", PROBE, mode], env=env,
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    if p.returncode != 0:
        if allow_fail:
            return None  # 污染导致 probe 崩在用例上，同样视为「被检出」
        print(p.stdout + p.stderr)
        raise SystemExit(f"probe 运行失败（mode={mode}）")
    return json.loads(p.stdout)


def positive():
    """正向：同一输入下逐键比对 mine / engine 行为快照。"""
    mine = _run_probe("mine")
    theirs = _run_probe("engine")

    # to_ass 品牌注释差异：先从 engine 侧剥离，并断言差异行恰为品牌注释
    brand_ok = True
    for k, v in mine.items():
        if not k.startswith("ass_") and not k.startswith("save_ass"):
            continue
        if not isinstance(v, str):
            continue
        ev = theirs.get(k, "")
        if BRAND_COMMENT not in ev:
            brand_ok = False
            print("MISMATCH", k, "engine 侧未见预期品牌注释（差异口径变了？）")
            continue
        theirs[k] = ev.replace(BRAND_COMMENT, "")

    fails = []
    for k, v in mine.items():
        if theirs.get(k) != v:
            fails.append(k)
            print("MISMATCH", k)
            print("  mine  :", repr(v)[:300])
            print("  engine:", repr(theirs.get(k))[:300])
        else:
            print("OK  ", k)
    if not brand_ok:
        fails.append("brand_comment")
    return fails


#: 负向用例：(名称, 旧串, 新串, 预期会 MISMATCH 的键)
NEGATIVE_CASES = [
    ("to_json 契约字段被改",
     '"original_subtitle": segment.text,',
     '"original_sub": segment.text,',
     ["to_json", "from_json_roundtrip", "from_json_model_shape"]),
    ("SRT 时间分隔符被改",
     'return f"{self._ms_to_srt_time(self.start_time)} --> {self._ms_to_srt_time(self.end_time)}"',
     'return f"{self._ms_to_srt_time(self.start_time)} .. {self._ms_to_srt_time(self.end_time)}"',
     ["seg_to_srt_ts"]),
    ("分词区间丢掉中文",
     'r"|[\\u4e00-\\u9fff]"                        # 中文',
     '',
     ["split_word_cjk"]),
    ("merge 译文连接符被改",
     'merged_translated = " ".join(',
     'merged_translated = "".join(',
     ["merge_segments"]),
]


def negative():
    """负向：污染自研源码副本，确认正向比对确实会失败。"""
    ok = True
    with open(os.path.join(SRC, "engine_asr_data.py"), encoding="utf-8") as f:
        original = f.read()
    for name, old, new, expect_keys in NEGATIVE_CASES:
        poisoned = original.replace(old, new, 1)
        if poisoned == original:
            print(f"MISMATCH 负向[{name}]：未找到注入点 {old!r}，跳过"
                  "（不代表检查有效）")
            ok = False
            continue
        tmp = tempfile.mkdtemp(prefix="vt_asr_neg_")
        try:
            shutil.copy(os.path.join(SRC, "engine_asr_data.py"),
                        os.path.join(tmp, "engine_asr_data.py"))
            with open(os.path.join(tmp, "engine_asr_data.py"), "w",
                      encoding="utf-8") as f:
                f.write(poisoned)
            # engine 基线（未污染）
            theirs = _run_probe("engine")
            for k, v in theirs.items():
                if k.startswith("ass_") or k.startswith("save_ass"):
                    if isinstance(v, str) and BRAND_COMMENT in v:
                        theirs[k] = v.replace(BRAND_COMMENT, "")
            mine = _run_probe("mine", src_override=tmp, allow_fail=True)
            if mine is None:
                print(f"OK   负向[{name}]：污染被成功检出（probe 运行期异常）")
                continue
            bad_keys = [k for k, v in mine.items() if theirs.get(k) != v]
            hit = [k for k in expect_keys if k in bad_keys]
            if hit and set(expect_keys) <= set(bad_keys):
                print(f"OK   负向[{name}]：污染被成功检出（{', '.join(hit)}）")
            else:
                print(f"MISMATCH 负向[{name}]：预期 {expect_keys} 失败，"
                      f"实际失败 {bad_keys or '无'} —— 检查形同虚设")
                ok = False
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    return ok


def main():
    print("=" * 60)
    print("engine_asr_data 逐行为兼容性自检")
    print("=" * 60)
    print("\n[1/2] 正向校验（同一输入，逐键比对）")
    fails = positive()
    print("\n[2/2] 负向校验（故意弄坏）")
    ok_neg = negative()
    print("\n" + "=" * 60)
    print("结论：", "PASS" if (not fails and ok_neg) else f"FAIL（正向失败 {len(fails)} 项）")
    return 0 if (not fails and ok_neg) else 1


if __name__ == "__main__":
    sys.exit(main())
