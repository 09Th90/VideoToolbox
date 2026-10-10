#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# @version 1.19.0
"""主播声纹 · 准确性基准（真实语音语料：3 位说话人 × 录入/测试样本）

用 C:\\bld\\sv_ref\\wavs 的 15 段真实人声，量化「改造前 vs 改造后」的准确性：

  A. 模板质量 —— 单片段录入 vs 多片段均值录入：
       同人相似度下限 / 异人相似度上限 / 判定边际（下限-上限）
  B. 抗劣化   —— 测试片段或模板片段叠加劣化后再比对，边际还剩多少：
       pad   两侧各 1.5s 静音（模拟 ASR cue 的余量）
       click 0.5s 处一个 0.9 幅值爆音（模拟解码毛刺/音效）
       noise 加 15dB SNR 白底噪（模拟录音底噪）
  C. 聚类纯度 —— 无 [说话人N] 时本地聚类：pairwise purity
     （同说话人同簇 + 异说话人异簇 的 cue 对占比）与簇数。
  D. 多用户迭代 —— 甲乙各传同一主播一段，voiceprint_sync.fold_leaves
     折叠合并后的边际 vs 各自单传的边际（「不同用户上传 -> 更准」的直接验证）。

`--legacy` 用 monkeypatch 复现旧管线（峰值归一化 + 无 VAD + 旧贪心聚类），
用于改造前后同机对比；不加则为现行实现。

跑法：
  tools/python/python.exe scripts/dev/voiceprint_accuracy.py            # 现行
  tools/python/python.exe scripts/dev/voiceprint_accuracy.py --legacy   # 旧管线
"""
import argparse
import glob
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
SRC = os.path.join(ROOT, "src")
sys.path.insert(0, SRC)
os.environ.setdefault("VT_NO_PIPELINE", "1")
os.environ.setdefault("VT_NO_SYNC", "1")
os.environ.setdefault("VT_NO_VP_SYNC", "1")

import speaker_voiceprint as SV  # noqa: E402

#: 语料目录（sherpa-onnx speaker 测试集：fangjun / leijun / liudehua 三位说话人，
#: 每人 2~3 段录入样本（*-sr-*）与 2~3 段测试样本（*-test-sr-*），16k 单声道）
CORPUS = r"C:\bld\sv_ref\wavs"
SR = SV.SAMPLE_RATE


# ---------------------------------------------------------------- 语料读取


def load_corpus(corpus=CORPUS):
    """读语料 -> {说话人: {"enroll": [pcm...], "test": [(name, pcm)...]}}。"""
    out = {}
    for p in sorted(glob.glob(os.path.join(corpus, "*.wav"))):
        base = os.path.basename(p)
        spk = base.split("-")[0]
        kind = "test" if "-test-" in base else "enroll"
        pcm = SV.read_wav_mono(p)
        out.setdefault(spk, {"enroll": [], "test": []})
        out[spk][kind].append((base, pcm.astype(np.float32)))
    return out


# ---------------------------------------------------------------- 劣化


def deg_pad(x, sec=1.5):
    pad = np.zeros(int(sec * SR), dtype=np.float32)
    return np.concatenate([pad, x, pad])


def deg_click(x, at=0.5, amp=0.9):
    y = x.copy()
    i = int(at * SR)
    y[i:i + 5] = amp          # 5 个采样点的爆音脉冲
    return y


def deg_noise(x, snr_db=15.0, seed=7):
    rng = np.random.RandomState(seed)
    sig = float(np.sqrt(np.mean(x.astype(np.float64) ** 2)))
    nse = rng.randn(len(x)).astype(np.float32) * (sig / (10.0 ** (snr_db / 20.0)))
    return x + nse


DEGRADATIONS = [
    ("pad", deg_pad),
    ("click", deg_click),
    ("noise", deg_noise),
]


# ---------------------------------------------------------------- legacy 复现


def legacy_cluster_cues(pcm, cues, encoder=None, sample_rate=SV.SAMPLE_RATE,
                        threshold=SV.CLUSTER_THRESHOLD,
                        min_seconds=SV.CLUSTER_MIN_SECONDS):
    """旧版贪心聚类（v1.18.3 及之前）：等权簇心、无重指派、无合并。"""
    enc = encoder or SV.VoiceprintEncoder()
    chunks = SV._cue_chunks(pcm, cues, sample_rate)
    min_len = int(min_seconds * sample_rate)
    order = []
    for i, ch in enumerate(chunks):
        if ch is not None and len(ch) >= min_len:
            order.append((i, len(ch) / float(sample_rate)))
    order.sort(key=lambda t: -t[1])
    labels = [-1] * len(cues)
    centroids, sums, counts = [], [], []
    for idx, _dur in order:
        try:
            v = enc.embed(chunks[idx], sample_rate)
        except SV.VoiceprintError:
            continue
        if centroids:
            sims = [float(np.dot(v, c)) for c in centroids]
            best = int(np.argmax(sims))
            if sims[best] >= threshold:
                labels[idx] = best
                sums[best] = sums[best] + v
                counts[best] += 1
                n = sums[best]
                centroids[best] = n / (float(np.linalg.norm(n)) + 1e-9)
                continue
        labels[idx] = len(centroids)
        sums.append(v.copy())
        counts.append(1)
        centroids.append(v.copy())
    sizes = {}
    for lb in labels:
        if lb >= 0:
            sizes[lb] = sizes.get(lb, 0) + 1
    return labels, sizes


def set_legacy(on):
    """切换 旧管线（峰值归一化 + 无 VAD + 旧贪心聚类）/ 现行管线。"""
    if on:
        SV._orig_trim = getattr(SV, "trim_silence", None)
        SV._orig_nrms = getattr(SV, "normalize_rms", None)
        SV._orig_cluster = SV.cluster_cues
        # 旧管线：不做静音裁剪；用峰值归一化（normalize_peak 语义）
        SV.trim_silence = lambda x, sample_rate=SV.SAMPLE_RATE, **kw: \
            np.asarray(x, dtype=np.float32)
        SV.normalize_rms = lambda x, **kw: SV.normalize_peak(x)
        SV.cluster_cues = legacy_cluster_cues
    else:
        if getattr(SV, "_orig_trim", None) is not None:
            SV.trim_silence = SV._orig_trim
        if getattr(SV, "_orig_nrms", None) is not None:
            SV.normalize_rms = SV._orig_nrms
        if getattr(SV, "_orig_cluster", None) is not None:
            SV.cluster_cues = SV._orig_cluster


# ---------------------------------------------------------------- 指标


def margin_table(scores):
    """scores: {(tpl_spk, tpl_kind): {(test_spk, name): cos}} -> 汇总行。"""
    rows = []
    for (ts, kind), tests in sorted(scores.items()):
        same = [v for (s, _n), v in tests.items() if s == ts]
        cross = [v for (s, _n), v in tests.items() if s != ts]
        rows.append((ts, kind, min(same), max(cross),
                     min(same) - max(cross)))
    return rows


def print_margins(title, rows):
    print("\n== %s ==" % title)
    print("  模板说话人  模板      同人min  异人max   边际")
    for ts, kind, smin, xmax, mg in rows:
        print("  %-10s %-8s %7.3f  %7.3f  %7.3f" % (ts, kind, smin, xmax, mg))
    return [r[4] for r in rows]


def scenario_a(enc, corpus):
    """A. 单片段 vs 多片段录入模板，对全部测试片段打分。"""
    scores = {}
    tests = [(s, n, p) for s, d in corpus.items() for n, p in d["test"]]
    for spk, d in corpus.items():
        ems = [enc.embed(p) for _n, p in d["enroll"]]
        tpls = {"单片段": ems[0],
                "多片段": _mean_unit(ems)}
        for kind, tpl in tpls.items():
            scores[(spk, kind)] = {
                (s, n): SV.cosine(tpl, enc.embed(p)) for s, n, p in tests}
    return print_margins("A. 模板质量（单片段 vs 多片段录入）", margin_table(scores))


def scenario_b(enc, corpus):
    """B. 劣化下的边际。B1 干净模板 vs 劣化测试；B2 劣化模板 vs 干净测试。"""
    margins = {}
    tests = [(s, n, p) for s, d in corpus.items() for n, p in d["test"]]
    for dname, fn in DEGRADATIONS:
        scores = {}
        for spk, d in corpus.items():
            tpl = enc.embed(d["enroll"][0][1])                 # 干净模板
            scores[(spk, "tpl_clean")] = {
                (s, n): SV.cosine(tpl, enc.embed(fn(p)))
                for s, n, p in tests}
            scores[(spk, "tpl_" + dname)] = {
                (s, n): SV.cosine(enc.embed(fn(d["enroll"][0][1])), enc.embed(p))
                for s, n, p in tests}
        rows = margin_table(scores)
        margins[dname] = {
            "clean_tpl": [r[4] for r in rows if r[1] == "tpl_clean"],
            "deg_tpl": [r[4] for r in rows if r[1] != "tpl_clean"],
        }
    print("\n== B. 抗劣化（边际 = 同人min - 异人max）==")
    for dname, m in margins.items():
        c = min(m["clean_tpl"])
        d = min(m["deg_tpl"])
        print("  %-6s 干净模板->劣化测试 最小边际 %6.3f | 劣化模板->干净测试 最小边际 %6.3f"
              % (dname, c, d))
    return margins


def scenario_c(enc, corpus, snr_db=25.0):
    """C. 本地聚类纯度：三位说话人各 3 段（另有 3 段过短应被排除）。"""
    segs = []                      # (spk, pcm)
    for spk, d in corpus.items():
        for i, (_n, p) in enumerate(d["test"]):
            a = int(0.4 * SR) + i * int(0.7 * SR)
            dur = (1.6, 0.9, 2.2)[i % 3]
            segs.append((spk, p[a:a + int(dur * SR)]))
        short = d["test"][0][1][int(0.2 * SR):int(0.4 * SR)]
        segs.append((spk + "#short", short))                   # 0.2s，应标 -1
    rng = np.random.RandomState(3)
    gap = int(0.35 * SR)
    total = sum(len(p) for _s, p in segs) + gap * (len(segs) + 1)
    pcm = np.zeros(total, dtype=np.float32)
    rows, pos = [], gap
    for i, (spk, p) in enumerate(segs, 1):
        pcm[pos:pos + len(p)] = p
        rows.append("%d\n%s --> %s\n第 %d 句\n" % (
            i, _ts(pos / float(SR)), _ts((pos + len(p)) / float(SR)), i))
        pos += len(p) + gap
    # 加底噪让短段向量更不稳（贴近真实转录片段）
    sig = float(np.sqrt(np.mean(pcm.astype(np.float64) ** 2)))
    pcm += (rng.randn(len(pcm)).astype(np.float32)
            * (sig / (10.0 ** (snr_db / 20.0))))
    doc = SV.secore.SubtitleDoc()
    doc.load_bytes("\n".join(rows).encode("utf-8"))
    cues = list(doc.cues)
    labels, sizes = SV.cluster_cues(pcm, cues, enc)
    purity, npairs = _pairwise_purity([s.split("#")[0] for s, _ in segs], labels)
    n_clustered = sum(1 for x in labels if x >= 0)
    print("\n== C. 聚类纯度（%d 条 cue，%d 条参与聚类，%d 簇）=="
          % (len(cues), n_clustered, len(sizes)))
    print("  pairwise purity = %.3f（%d 对）" % (purity, npairs))
    print("  过短段全部排除：%s"
          % all(labels[i] < 0 for i, s in enumerate([s for s, _ in segs])
                if "#" in s))
    return purity, len(sizes)


def scenario_d(enc, corpus):
    """D. 多用户数据迭代：甲乙各传同一主播的一段 -> 折叠合并后是否更准。"""
    import voiceprint_sync as V
    spk = next((s for s in sorted(corpus) if len(corpus[s]["enroll"]) >= 2), None)
    if spk is None:
        print("\n== D. 多用户迭代（跳过：语料无 ≥2 段录入样本的说话人）==")
        return None
    d = corpus[spk]
    ea = enc.embed(d["enroll"][0][1])
    eb = enc.embed(d["enroll"][1][1])
    obj_a = {"name": spk, "embedding": [float(x) for x in ea],
             "weight": 1.0, "clips": 1}
    obj_b = {"name": spk, "embedding": [float(x) for x in eb],
             "weight": 1.0, "clips": 1}
    leaves = (V.template_leaves(obj_a, author="userA")
              + V.template_leaves(obj_b, author="userB"))
    merged, rejected = V.fold_leaves(leaves)
    print("\n== D. 多用户迭代（%s：甲传 %s，乙传 %s -> 折叠）=="
          % (spk, d["enroll"][0][0], d["enroll"][1][0]))
    print("  折叠守卫拒绝叶数 = %d（应为 0：同一主播）" % len(rejected))
    if merged is None:
        print("  折叠失败（守卫全拒），跳过")
        return None
    tests = [(s, n, p) for s, dd in corpus.items() for n, p in dd["test"]]
    tpls = {"甲单传": ea, "乙单传": eb,
            "折叠合并": np.asarray(merged["embedding"], dtype=np.float32)}
    rows = []
    for kind, tpl in tpls.items():
        same = [SV.cosine(tpl, enc.embed(p)) for s, n, p in tests if s == spk]
        cross = [SV.cosine(tpl, enc.embed(p)) for s, n, p in tests if s != spk]
        rows.append((kind, min(same), max(cross), min(same) - max(cross)))
    print("  模板        同人min  异人max   边际")
    for kind, smin, xmax, mg in rows:
        print("  %-10s %7.3f  %7.3f  %7.3f" % (kind, smin, xmax, mg))
    best_single = max(r[3] for r in rows[:2])
    print("  折叠边际 %.3f vs 单传最优 %.3f -> %s"
          % (rows[2][3], best_single,
             "提升" if rows[2][3] > best_single else "未提升（语料太小，仅供参考）"))
    return rows


def _pairwise_purity(spks, labels):
    ok = tot = 0
    for i in range(len(labels)):
        for j in range(i + 1, len(labels)):
            if labels[i] < 0 or labels[j] < 0:
                continue
            tot += 1
            if (spks[i] == spks[j]) == (labels[i] == labels[j]):
                ok += 1
    return (ok / float(tot) if tot else 0.0), tot


def _mean_unit(vecs):
    v = np.mean(np.stack(vecs, axis=0), axis=0)
    return v / (float(np.linalg.norm(v)) + 1e-9)


def _ts(sec):
    h = int(sec // 3600)
    m = int(sec % 3600 // 60)
    s = sec % 60
    return ("%02d:%02d:%06.3f" % (h, m, s)).replace(".", ",")


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    ap = argparse.ArgumentParser(description="主播声纹准确性基准")
    ap.add_argument("--legacy", action="store_true",
                    help="复现旧管线（峰值归一化 + 无 VAD + 旧贪心聚类）")
    ap.add_argument("--corpus", default=CORPUS)
    args = ap.parse_args()

    if not os.path.isdir(args.corpus):
        print("语料目录不存在：%s（跳过基准）" % args.corpus)
        return 0
    set_legacy(args.legacy)
    print("管线模式：%s" % ("legacy（峰值归一化 + 无 VAD + 旧贪心聚类）"
                         if args.legacy else "现行"))
    corpus = load_corpus(args.corpus)
    for spk, d in sorted(corpus.items()):
        print("  语料 %s：录入 %d 段 / 测试 %d 段"
              % (spk, len(d["enroll"]), len(d["test"])))
    enc = SV.VoiceprintEncoder()
    scenario_a(enc, corpus)
    scenario_b(enc, corpus)
    scenario_c(enc, corpus)
    if not args.legacy:
        scenario_d(enc, corpus)      # 折叠属现行管线语义，legacy 下无对照意义
    print("\n基准完成。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
