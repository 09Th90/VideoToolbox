# -*- coding: utf-8 -*-
# @version 2.5.3
"""主播声纹 · 素材体检判据标定（决定 `speaker_voiceprint.QUALITY_*` 门槛取多少）

用途：`assess_material` 的告警门槛不是拍的，是按**真实素材实测值**定的。本脚本
把候选统计量在若干份素材上一次性测出来，并打印「可疑 - 可用」的区分力排序，
供定门槛与换素材后复核。门槛应当取在两组实测值之间并留余量。

为什么需要复核（2026-10-14 踩坑实录）：第一版判据里有两条在**正对照**上误报——
  · 「人声段 vs 背景音段落差 < 0.05 就告警」：对照段用严格档门控挑，在干净素材里
    那些段**仍然是人声**（擦音/笑声的谱平坦度本来就偏高），两侧都在测同一个人的
    嗓音，落差恒≈0（可用 +0.008 / 可疑 +0.001，毫无区分力）；
  · 「100% 窗口判为本人就告警」：单人连续说话的素材本来就该 100%。
两条叠加把已知可用的素材判成「有风险」。现改为：对照段取**松档**门控的补集
（连松档都不像人声才算背景音）、落差只保留「为负」这一强信号、「没有低分对照窗」
只在素材同时背景音偏重时才升级为告警，其余进「提示」。

依赖：tools/asr_model 下的声纹模型、tools/ffmpeg.exe、已录入的声纹模板。

用法：
  python scripts/dev/voiceprint_material_calib.py \
      --case "可用:미니보기:C:/path/干净素材.mp4" \
      --case "可疑:Pixel Tree:C:/path/带BGM素材.mp4" \
      [--json out.json]
每个 --case 是「标签:声纹名:素材路径」；标签只用于报表，第一个 case 作为
区分力表格的基准（其它 case 与它相减）。
"""
import argparse
import json
import os
import sys

import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "src"))

import speaker_voiceprint as SV  # noqa: E402

WIN = SV.AUTO_SCAN_WIN_SEC


def measure(src, name, encoder):
    """测一份素材的全部候选统计量（口径与 `assess_material` 一致）。"""
    pcm = SV.read_pcm(src)
    a = np.asarray(pcm, dtype=np.float32).reshape(-1)
    sr = SV.SAMPLE_RATE
    total = a.size / float(sr)
    tv = SV.load_template(name)["embedding"]

    mask, runs, (flat, hf, db) = SV.gate_speech_runs(a)
    pw = np.power(10.0, db / 10.0)
    loud = db >= np.percentile(db, 75) if db.size else np.zeros(0, dtype=bool)
    # 背景音对照段：**松档**门控补集里 ≥3 秒的最长几段
    bg_runs = sorted([(s * SV.GATE_FRAME_SEC, (e - s) * SV.GATE_FRAME_SEC)
                      for s, e in SV._runs(~mask)
                      if (e - s) * SV.GATE_FRAME_SEC >= SV.STRICT_MIN_RUN_SEC],
                     key=lambda r: -r[1])

    def sim(s, d):
        try:
            return float(SV.cosine(encoder.embed(a[int(s * sr):int((s + d) * sr)]), tv))
        except SV.VoiceprintError:
            return float("nan")

    seg_len = min(WIN, bg_runs[0][1]) if bg_runs else WIN
    grid, t = [], 0.0
    while t + seg_len <= total:
        i0 = int(t / SV.GATE_FRAME_SEC)
        i1 = min(int(mask.size), int((t + seg_len) / SV.GATE_FRAME_SEC))
        grid.append((t, float(mask[i0:i1].mean()) if i1 > i0 else 0.0))
        t += seg_len
    voice = [x for x, _r in sorted(sorted([g for g in grid
                                           if g[1] >= SV.QUALITY_VOICE_RATIO_MIN],
                                          key=lambda v: -v[1])
                                  [:SV.QUALITY_MAX_VOICE_SEGS])]
    ws, t = [], 0.0
    while t + WIN <= total:
        v = sim(t, WIN)
        if v == v:
            ws.append(v)
        t += WIN
    ws = np.array(ws) if ws else np.zeros(0)
    vsc = [x for x in (sim(s, seg_len) for s in voice) if x == x]
    bsc = [x for x in (sim(s, seg_len) for s, _d in
                       bg_runs[:SV.QUALITY_MAX_BG_SEGS]) if x == x]

    m = {"total_sec": round(total, 1),
         "speech_ratio": round(float(mask.mean()), 3) if mask.size else None,
         "voice_run_max": round(max((d for _s, d in runs), default=0.0), 1),
         "voice_run_p90": (round(float(np.percentile([d for _s, d in runs], 90)), 1)
                           if runs else 0.0),
         "bg_level_db": (round(float(np.median(db[~mask]) - db.max()), 1)
                         if (~mask).any() else None),
         "bg_energy_pct": (round(100.0 * float(pw[~mask].sum())
                                 / max(float(pw.sum()), 1e-12), 1) if pw.size else None),
         "flat_median": round(float(np.median(flat)), 4) if flat.size else None,
         "flat_p75": round(float(np.percentile(flat, 75)), 4) if flat.size else None,
         "flat_loud_median": (round(float(np.median(flat[loud])), 4)
                              if np.any(loud) else None),
         "hf_median": round(float(np.median(hf)), 1) if hf.size else None,
         "hf_loud_median": (round(float(np.median(hf[loud])), 1)
                            if np.any(loud) else None),
         "win_min": round(float(ws.min()), 3) if ws.size else None,
         "win_p10": round(float(np.percentile(ws, 10)), 3) if ws.size else None,
         "win_median": round(float(np.median(ws)), 3) if ws.size else None,
         "pct_below": (round(100.0 * float((ws < SV.DEFAULT_THRESHOLD).mean()), 1)
                       if ws.size else None),
         "n_bg_control": len(bg_runs),
         "bg_control_longest": round(bg_runs[0][1], 1) if bg_runs else 0.0,
         "seg_len": round(float(seg_len), 2),
         "voice_median": round(float(np.median(vsc)), 4) if vsc else None,
         "bg_median": round(float(np.median(bsc)), 4) if bsc else None,
         "margin": (round(float(np.median(vsc) - np.median(bsc)), 4)
                    if vsc and bsc else None)}
    q = SV.assess_material(a, tv, encoder=encoder)
    m["verdict"] = q["verdict"]
    m["n_warnings"] = len(q["warnings"])
    m["n_infos"] = len(q["infos"])
    return m


def main():
    ap = argparse.ArgumentParser(description="声纹素材体检判据标定")
    ap.add_argument("--case", action="append", required=True,
                    help="\"标签:声纹名:素材路径\"，可多给；第一个作为区分力基准")
    ap.add_argument("--json", default=None, help="完整指标另写 JSON")
    args = ap.parse_args()

    enc = SV.VoiceprintEncoder()
    out = {}
    for raw in args.case:
        parts = str(raw).split(":", 2)
        if len(parts) != 3:
            print("[标定] --case 格式应为 \"标签:声纹名:素材路径\"：%s" % raw,
                  file=sys.stderr)
            return 2
        label, name, src = parts[0].strip(), parts[1].strip(), parts[2].strip()
        print("=== %s（声纹「%s」）===" % (label, name), flush=True)
        print("  素材：%s" % src, flush=True)
        m = measure(src, name, enc)
        for k, v in m.items():
            print("  %-20s %s" % (k, v))
        print("  → 体检判定：%s（告警 %d 条 / 提示 %d 条）"
              % (SV.verdict_text(m["verdict"]), m["n_warnings"], m["n_infos"]))
        print("", flush=True)
        out[label] = m

    labels = list(out)
    if len(labels) >= 2:
        base, other = out[labels[0]], out[labels[1]]
        print("=== 区分力（%s - %s）===" % (labels[1], labels[0]))
        keys = [k for k in base
                if isinstance(base[k], (int, float)) and isinstance(other.get(k), (int, float))]
        for k in sorted(keys, key=lambda k: -abs(float(other[k]) - float(base[k]))
                        / max(abs(float(base[k])), 1e-6)):
            print("  %-20s %-12s %-12s 差 %+.4g"
                  % (k, base[k], other[k], float(other[k]) - float(base[k])))
        print("\n当前门槛：%s" % json.dumps({
            k: getattr(SV, k) for k in dir(SV)
            if k.startswith("QUALITY_") and isinstance(getattr(SV, k), (int, float))},
            ensure_ascii=False))
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(out, fh, ensure_ascii=False, indent=1)
        print("\n已写 %s" % args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
