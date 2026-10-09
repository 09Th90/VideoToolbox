# -*- coding: utf-8 -*-
# @version 1.18.3
"""主播声纹 · 分离度探针（决定「阈值取多少」以及「这条路走不走得通」）

用途：正式用「声纹筛选」之前，先拿**真实素材**量一次分离度。
      做法是拿主播的一段参考音频当模板，再看片子里各个说话人 / 各个时间窗
      与模板的相似度分布：**主播簇聚在高位、其他人散在低位、中间留出空档**，
      才说明阈值可靠；若分布糊成一片，多半是重叠说话或 BGM 太重，需先解决
      声源分离，光靠声纹救不回来。

两种模式：
  ① 有说话人标注（ASR 开了 diarization）——按 [说话人N] 聚簇打分，最准
  ② 无标注——按固定时长滑窗逐段打分，看分数分布是否天然分层

依赖：tools/python/python.exe、tools/ffmpeg.exe、
      tools/asr_model/3dspeaker_speech_campplus_sv_zh-cn_16k-common.onnx

用法：
  # ① 用参考片段当模板，按说话人打分
  python scripts/dev/voiceprint_probe.py --src 视频.mp4 --srt 字幕.srt \
         --ref-start 12 --ref-dur 20
  # ② 无 SRT：滑窗扫全片，看分布
  python scripts/dev/voiceprint_probe.py --src 视频.mp4 --ref-start 12 --ref-dur 20
  # ③ 直接出筛选结果（顺带写复核报告）
  python scripts/dev/voiceprint_probe.py --src 视频.mp4 --srt 字幕.srt \
         --ref-start 12 --ref-dur 20 --out 主播.srt
"""
import argparse
import os
import sys

import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "src"))

import speaker_voiceprint as SV  # noqa: E402

#: 分离度判定门槛（按「排序后最大空档」衡量）
GAP_GOOD = 0.15
GAP_WEAK = 0.08


def suggest_threshold(scores):
    """从一列相似度里找**排序后最大空档**，返回 (阈值, 空档大小)。

    空档越大越说明「主播 / 非主播」天然分成两拨；阈值取空档中点。
    """
    s = sorted((x for x in scores if x == x), reverse=True)
    if len(s) < 2:
        return SV.DEFAULT_THRESHOLD, 0.0
    gaps = [(s[i] - s[i + 1], i) for i in range(len(s) - 1)]
    gap, idx = max(gaps)
    return round((s[idx] + s[idx + 1]) / 2.0, 3), round(gap, 3)


def bar(v, lo=-0.2, hi=1.0, width=28):
    if v != v:
        return " " * width + "  n/a"
    t = int(round((min(max(v, lo), hi) - lo) / (hi - lo) * width))
    return "#" * t + "." * (width - t) + " %6.3f" % v


def probe_speakers(src, srt_path, ref_start, ref_dur, template_name=None):
    """按说话人聚簇打分。返回 (模板向量, 各说话人得分 dict, pcm 时长秒)。"""
    enc = SV.VoiceprintEncoder()
    if template_name:
        tpl = SV.load_template(template_name)["embedding"]
        print("模板：已录入声纹「%s」" % template_name)
    else:
        tpl = enc.embed(SV.read_pcm(src, start=ref_start, dur=ref_dur))
        print("模板：%s 的 %.1fs ~ %.1fs 片段（%.1f 秒）"
              % (os.path.basename(src), ref_start, ref_start + (ref_dur or 0),
                 ref_dur or 0))

    text = open(srt_path, encoding="utf-8-sig", errors="replace").read()
    doc = SV.secore.SubtitleDoc()
    doc.load_bytes(text.encode("utf-8"))
    cues = list(doc.cues)
    labeled = sum(1 for c in cues if str(getattr(c, "speaker", "") or ""))
    print("字幕：%d 条 cue，其中 %d 条带 [说话人N] 标注" % (len(cues), labeled))
    if labeled == 0:
        print("  !! 没有说话人标注，退化为逐条 cue 打分"
              "（建议 ASR 时开「说话人分离」，或改用无 SRT 的滑窗模式）")

    pcm = SV.read_pcm(src)
    print("音频：%.1f 秒 @16kHz 单声道" % (len(pcm) / 16000.0))
    scores = SV.score_by_speaker(pcm, cues, tpl, enc)
    if labeled == 0:
        per = SV.score_by_cue(pcm, cues, tpl, enc)
        scores = {"(逐条 cue)": {"score": float(np.nanmean(per)), "n": len(per),
                               "seconds": sum((c.end - c.start) / 1000.0
                                              for c in cues)}}
    return tpl, scores, len(pcm) / 16000.0


def probe_windows(src, ref_start, ref_dur, win=3.0, hop=None):
    """无 SRT 模式：固定时长滑窗逐段打分，看分布能否天然分层。"""
    enc = SV.VoiceprintEncoder()
    tpl = enc.embed(SV.read_pcm(src, start=ref_start, dur=ref_dur))
    pcm = SV.read_pcm(src)
    hop = hop or win
    step = int(win * 16000)
    stride = int(hop * 16000)
    vals, times = [], []
    for a in range(0, max(1, len(pcm) - step), stride):
        seg = pcm[a:a + step]
        if len(seg) < step:
            break
        try:
            vals.append(SV.cosine(tpl, enc.embed(seg)))
            times.append(a / 16000.0)
        except SV.VoiceprintError:
            pass
    return tpl, vals, times, len(pcm) / 16000.0


def report_speakers(scores):
    print("\n=== 各说话人与主播模板的相似度（按相似度降序）===")
    print("  说话人       相似度条                                       条数  时长")
    for spk, info in sorted(scores.items(),
                            key=lambda kv: -(kv[1]["score"] if kv[1]["score"] == kv[1]["score"] else -9)):
        print("  %-10s %s  %4d  %5.1fs"
              % (spk or "(无标签)", bar(info["score"]), info["n"], info["seconds"]))
    vals = [i["score"] for i in scores.values()]
    return vals


def report_windows(vals, times):
    print("\n=== 滑窗相似度分布（%d 个窗）===" % len(vals))
    arr = np.array([v for v in vals if v == v])
    if arr.size:
        print("  min %.3f  p25 %.3f  中位 %.3f  p75 %.3f  max %.3f"
              % (arr.min(), np.percentile(arr, 25), np.median(arr),
                 np.percentile(arr, 75), arr.max()))
    print("\n  低分窗（疑似非主播，前 15 个）：")
    for v, t in sorted(zip(vals, times))[:15]:
        print("    %7.1fs  %s" % (t, bar(v)))
    return list(vals)


def verdict(vals, threshold, gap):
    print("\n=== 结论 ===")
    print("  建议阈值 = %.3f（排序后最大空档 = %.3f）" % (threshold, gap))
    if gap >= GAP_GOOD:
        print("  分离度：良好 —— 分数天然分层，阈值可靠，可以上。")
    elif gap >= GAP_WEAK:
        print("  分离度：偏窄 —— 能跑但边界模糊，务必保留「存疑区」并人工复核。")
    else:
        print("  分离度：不足 —— 分数糊成一片，多半是重叠说话 / BGM 太重；")
        print("            先解决声源分离（_asr_separate_audio 目前仍是占位），")
        print("            单靠声纹会大量误杀主播。")
    n_hi = sum(1 for v in vals if v == v and v >= threshold)
    print("  按该阈值：%d/%d 判为主播（%.0f%%）"
          % (n_hi, len([v for v in vals if v == v]),
             100.0 * n_hi / max(1, len([v for v in vals if v == v]))))


def main():
    ap = argparse.ArgumentParser(description="主播声纹分离度探针")
    ap.add_argument("--src", required=True, help="音频或视频文件")
    ap.add_argument("--srt", help="带 [说话人N] 标注的字幕（不给则滑窗模式）")
    ap.add_argument("--ref-start", type=float, default=0.0,
                    help="主播参考片段起点（秒）")
    ap.add_argument("--ref-dur", type=float, default=20.0,
                    help="主播参考片段时长（秒）")
    ap.add_argument("--template", help="改用已录入的声纹模板名（省去 --ref-*）")
    ap.add_argument("--win", type=float, default=3.0, help="滑窗时长（秒）")
    ap.add_argument("--out", help="顺带写出筛选后的 SRT")
    ap.add_argument("--threshold", type=float, default=None,
                    help="指定阈值（默认用建议值）")
    args = ap.parse_args()

    if args.srt:
        tpl, scores, _ = probe_speakers(args.src, args.srt, args.ref_start,
                                        args.ref_dur, args.template)
        vals = report_speakers(scores)
        thr, gap = suggest_threshold(vals)
        verdict(vals, thr, gap)
        if args.out:
            res = SV.filter_srt(args.src, args.srt, {"embedding": tpl},
                                threshold=args.threshold or thr,
                                out_path=args.out)
            print("\n已写出 %s（保留 %d / 存疑 %d / 丢弃 %d）"
                  % (args.out, res["keep"], res["review"], res["drop"]))
    else:
        tpl, vals, times, dur = probe_windows(args.src, args.ref_start,
                                              args.ref_dur, args.win)
        print("音频：%.1f 秒；模板取自 %.1fs 起 %.1fs" % (dur, args.ref_start,
                                                        args.ref_dur))
        vals = report_windows(vals, times)
        thr, gap = suggest_threshold(vals)
        verdict(vals, thr, gap)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
