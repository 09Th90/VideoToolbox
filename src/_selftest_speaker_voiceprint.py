#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# @version 1.18.0
"""主播声纹链路自检（离线，不联网、不依赖 ffmpeg）。

覆盖 src/speaker_voiceprint.py：
  · kaldi 兼容 fbank 的形状 / 有限性 / 黄金值（防实现回归）
  · 余弦相似度边界（含 NaN 与零向量）
  · 声纹模板落盘 -> 读回 往返
  · 按说话人聚簇打分 / 逐条打分
  · decide() 的 keep / drop / review 三分支
  · filter_srt() 端到端（注入假编码器 + 假 PCM，绕开 ffmpeg）
  · 真模型（存在才跑）：单位范数、同段自比 1.0

fbank 的正确性另有**外部基准**验证：与 kaldi-native-fbank 逐元素比对，
高能量帧 max|Δ| < 1e-3、最终 embedding 余弦 > 0.999（2026-10-08 实测），
本文件用黄金值把该结论固化下来，避免每次都要联网拉基准包。

运行：tools/python/python.exe _selftest_speaker_voiceprint.py
结果同时打印到 stdout 并写入 C:\\bld\\_speaker_vp_test\\result.txt。
"""
import os
import shutil
import sys
import tempfile

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("VT_NO_PIPELINE", "1")
os.environ.setdefault("VT_NO_SYNC", "1")

import speaker_voiceprint as SV  # noqa: E402

OUT = r"C:\bld\_speaker_vp_test"
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


def golden_signal():
    """固定合成信号（三正弦叠加），用于黄金值回归。"""
    t = np.arange(8000, dtype=np.float32) / 16000.0
    return (0.6 * np.sin(2 * np.pi * 440 * t)
            + 0.3 * np.sin(2 * np.pi * 1000 * t)
            + 0.1 * np.sin(2 * np.pi * 2500 * t)).astype(np.float32)


#: 黄金值：frame10 的选定 bin（2026-10-08 生成，与 kaldi 基准对齐后固化）
GOLD_BINS = (0, 10, 20, 30, 40, 50, 60, 70, 79)
GOLD_VALS = (-10.57904, -4.45348, -6.56399, -2.91711, -12.13107,
             -2.25567, -15.25596, -15.94238, -14.16995)


class FakeEncoder:
    """假编码器：把 PCM 首样本值当作「说话人编号」，返回 one-hot 向量。

    这样相似度只有 1.0 / 0.0 两种，聚簇与判定逻辑可被精确断言，
    不需要真模型、也不需要任何音频文件。
    """

    def embed(self, samples, sample_rate=16000):
        v = np.zeros(SV.EMB_DIM, dtype=np.float32)
        s = np.asarray(samples, dtype=np.float32).reshape(-1)
        if s.size == 0:
            raise SV.VoiceprintError("空音频")
        # 用**峰值**而非首样本：切片两侧有 0.05s 补白，首样本恒为 0
        m = float(np.max(np.abs(s)))
        if m < 1e-6:
            raise SV.VoiceprintError("几乎无声")
        v[int(round(m * 10)) % SV.EMB_DIM] = 1.0
        return v

    def embed_many(self, chunks, sample_rate=16000):
        out = []
        for c in chunks:
            try:
                out.append(self.embed(c, sample_rate))
            except SV.VoiceprintError:
                out.append(None)
        return out


def fake_pcm(spk_id, seconds=2.0):
    """构造「说话人 spk_id」的假 PCM（值恒为 spk_id/10）。"""
    return np.full(int(16000 * seconds), spk_id / 10.0, dtype=np.float32)


SRT = """1
00:00:01,000 --> 00:00:02,000
[说话人1] 大家好我是主播

2
00:00:02,500 --> 00:00:03,500
[说话人2] 我是嘉宾

3
00:00:04,000 --> 00:00:05,000
[说话人1] 今天我们聊点别的

4
00:00:05,500 --> 00:00:06,500
[说话人3] 我也来说两句
"""


def main():
    say("=" * 62)
    say("  主播声纹链路自检（speaker_voiceprint）")
    say("=" * 62)

    # ---------------- 1) fbank 形状 / 有限性 ----------------
    say("\n== 1) fbank 基本形态 ==")
    sig = golden_signal()
    f = SV.fbank(sig)
    check("输出形状 = (帧数, 80)", f.shape == (50, 80), f.shape)
    check("dtype = float32", f.dtype == np.float32, f.dtype)
    check("无 NaN / Inf", bool(np.isfinite(f).all()))
    check("帧数符合 (N+shift/2)//shift（snip_edges=False）",
          SV.fbank(np.zeros(16000, dtype=np.float32)).shape[0] == 100,
          SV.fbank(np.zeros(16000, dtype=np.float32)).shape[0])
    check("空输入返回 0 帧", SV.fbank(np.zeros(0, dtype=np.float32)).shape == (0, 80))
    check("过短输入不报错（< 1 帧）",
          SV.fbank(np.zeros(50, dtype=np.float32)).shape[0] == 0)

    # ---------------- 2) fbank 黄金值 ----------------
    say("\n== 2) fbank 黄金值（防实现回归）==")
    row = f[10]
    worst = max(abs(float(row[b]) - g) for b, g in zip(GOLD_BINS, GOLD_VALS))
    check("frame10 选定 bin 与黄金值一致（容差 1e-3）", worst < 1e-3,
          "max|Δ|=%.2e" % worst)
    check("全帧均值与黄金值一致",
          abs(float(f.mean()) - (-8.11547)) < 1e-3, "%.5f" % float(f.mean()))

    # ---------------- 3) 余弦相似度 ----------------
    say("\n== 3) 余弦相似度 ==")
    a = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    b = np.array([0.0, 1.0, 0.0], dtype=np.float32)
    check("正交向量 = 0", abs(SV.cosine(a, b)) < 1e-6, SV.cosine(a, b))
    check("同向量 = 1", abs(SV.cosine(a, a) - 1.0) < 1e-6, SV.cosine(a, a))
    check("反向量 = -1", abs(SV.cosine(a, -a) + 1.0) < 1e-6, SV.cosine(a, -a))
    check("未归一化也按余弦算",
          abs(SV.cosine(a * 7.0, a * 3.0) - 1.0) < 1e-6)
    check("零向量返回 NaN", SV.cosine(a, np.zeros(3, dtype=np.float32)) !=
          SV.cosine(a, np.zeros(3, dtype=np.float32)))
    check("None 返回 NaN", SV.cosine(None, a) != SV.cosine(None, a))

    # ---------------- 3b) 峰值归一化 ----------------
    say("\n== 3b) 峰值归一化（增益不变性）==")
    x = np.array([0.1, -0.05, 0.2], dtype=np.float32)
    n = SV.normalize_peak(x)
    check("峰值被拉到 1.0", abs(float(np.max(np.abs(n))) - 1.0) < 1e-6,
          float(np.max(np.abs(n))))
    check("归一化后与原信号同向",
          abs(SV.cosine(x, n) - 1.0) < 1e-6, SV.cosine(x, n))
    check("缩放后再归一化结果一致",
          np.allclose(SV.normalize_peak(x * 0.03), n, atol=1e-6))
    check("全零音频报 VoiceprintError",
          _raises(SV.VoiceprintError, SV.normalize_peak,
                  np.zeros(100, dtype=np.float32)))
    check("空音频报 VoiceprintError",
          _raises(SV.VoiceprintError, SV.normalize_peak,
                  np.zeros(0, dtype=np.float32)))

    # ---------------- 4) 模板落盘往返 ----------------
    say("\n== 4) 声纹模板存取 ==")
    tmpdir = tempfile.mkdtemp(prefix="vt_vp_")
    old_tpl_dir = SV.TEMPLATE_DIR
    SV.TEMPLATE_DIR = tmpdir
    try:
        emb = np.random.RandomState(0).randn(SV.EMB_DIM).astype(np.float32)
        emb /= np.linalg.norm(emb)
        p = SV.save_template("测试主播", emb, source="demo.mp4", seconds=12.5)
        check("模板文件已写出", os.path.isfile(p), p)
        t = SV.load_template("测试主播")
        check("维数保持 192", t["dim"] == SV.EMB_DIM, t["dim"])
        check("embedding 读回一致（1e-5 精度）",
              float(np.max(np.abs(t["embedding"] - emb))) < 1e-5)
        check("附加元信息保留", t.get("source") == "demo.mp4", t.get("source"))
        check("list_templates 能列出", SV.list_templates() == ["测试主播"],
              SV.list_templates())
        check("不存在的模板报 VoiceprintError",
              _raises(SV.VoiceprintError, SV.load_template, "不存在"))
    finally:
        SV.TEMPLATE_DIR = old_tpl_dir
        shutil.rmtree(tmpdir, ignore_errors=True)

    # ---------------- 4b) 多声纹启用名单 ----------------
    say("\n== 4b) 多声纹启用名单 ==")
    tmpdir = tempfile.mkdtemp(prefix="vt_vp_sel_")
    old_tpl_dir, old_sel = SV.TEMPLATE_DIR, SV.SELECTION_PATH
    SV.TEMPLATE_DIR = tmpdir
    SV.SELECTION_PATH = os.path.join(tmpdir, "selection.json")
    try:
        for i, n in enumerate(("主播甲", "主播乙", "嘉宾丙")):
            e = np.zeros(SV.EMB_DIM, dtype=np.float32)
            e[i] = 1.0
            SV.save_template(n, e)
        check("默认启用名单为空", SV.load_selection() == [], SV.load_selection())
        check("可同时启用多个（并集）",
              SV.save_selection(["主播甲", "主播乙"]) == ["主播甲", "主播乙"],
              SV.save_selection(["主播甲", "主播乙"]))
        check("读回顺序保持", SV.load_selection() == ["主播甲", "主播乙"],
              SV.load_selection())
        check("不存在的模板被过滤",
              SV.save_selection(["主播甲", "查无此人"]) == ["主播甲"])
        check("重复项去重", SV.save_selection(["主播乙", "主播乙"]) == ["主播乙"])
        check("传空 = 清空启用", SV.save_selection([]) == [])
        check("名单文件已落盘", os.path.isfile(SV.SELECTION_PATH))
        SV.save_selection(["主播甲", "嘉宾丙"])
        check("delete_template 会同时从启用名单摘掉",
              SV.delete_template("主播甲") and SV.load_selection() == ["嘉宾丙"],
              SV.load_selection())
        check("删除不存在的模板返回 False", SV.delete_template("查无此人") is False)
    finally:
        SV.TEMPLATE_DIR, SV.SELECTION_PATH = old_tpl_dir, old_sel
        shutil.rmtree(tmpdir, ignore_errors=True)

    # ---------------- 5) 按说话人聚簇打分 ----------------
    say("\n== 5) 按说话人聚簇打分 ==")
    doc = SV.secore.SubtitleDoc()
    doc.load_bytes(SRT.encode("utf-8"))
    cues = list(doc.cues)
    check("SRT 解析出 4 条 cue", len(cues) == 4, len(cues))
    check("说话人标签解析正确",
          [c.speaker for c in cues] == ["说话人1", "说话人2", "说话人1", "说话人3"],
          [c.speaker for c in cues])

    # 假 PCM：全片 3 秒以上，说话人1 段返回 spk1 的音频
    pcm = np.zeros(int(16000 * 7.0), dtype=np.float32)
    for c, sid in zip(cues, (1, 2, 1, 3)):
        a = int(c.start / 1000.0 * 16000)
        b = int(c.end / 1000.0 * 16000)
        pcm[a:b] = sid / 10.0
    enc = FakeEncoder()
    tpl = np.zeros(SV.EMB_DIM, dtype=np.float32)
    tpl[1] = 1.0                                   # 主播 = spk1
    sc = SV.score_by_speaker(pcm, cues, tpl, enc)
    check("聚簇出 3 个说话人", len(sc) == 3, sorted(sc))
    check("说话人1 相似度 = 1", abs(sc["说话人1"]["score"] - 1.0) < 1e-6,
          sc["说话人1"])
    check("说话人2 相似度 = 0", abs(sc["说话人2"]["score"]) < 1e-6, sc["说话人2"])
    check("说话人1 条数 = 2", sc["说话人1"]["n"] == 2, sc["说话人1"])
    check("说话人1 累计时长 ≈ 2 秒（含两侧 0.05s 补白）",
          1.9 < sc["说话人1"]["seconds"] < 2.5, sc["说话人1"]["seconds"])

    # ---------------- 5b) 多声纹（并集）打分 ----------------
    say("\n== 5b) 多声纹并集打分 ==")
    check("_as_template_list 接受单个向量",
          len(SV._as_template_list(tpl)) == 1)
    check("_as_template_list 幂等（已归一化结果再传不变）",
          SV._as_template_list(SV._as_template_list(tpl))[0][1].shape
          == (SV.EMB_DIM,))
    check("_as_template_list 接受 (名称, 向量) 二元组",
          SV._as_template_list(("甲", tpl))[0][0] == "甲")
    tpl_b = np.zeros(SV.EMB_DIM, dtype=np.float32)
    tpl_b[2] = 1.0                                  # 第二位「主播」
    multi = [("主播", tpl), ("嘉宾主播", tpl_b)]
    sc_m = SV.score_by_speaker(pcm, cues, multi, enc)
    check("多声纹：说话人1 命中第 1 个模板",
          abs(sc_m["说话人1"]["score"] - 1.0) < 1e-6
          and sc_m["说话人1"]["best"] == "主播", sc_m["说话人1"])
    check("多声纹：说话人2 命中第 2 个模板（并集）",
          abs(sc_m["说话人2"]["score"] - 1.0) < 1e-6
          and sc_m["说话人2"]["best"] == "嘉宾主播", sc_m["说话人2"])
    check("多声纹：未覆盖的说话人3 仍为 0",
          abs(sc_m["说话人3"]["score"]) < 1e-6, sc_m["说话人3"])
    check("单模板与多模板对同一簇结果一致（best 除外）",
          abs(sc_m["说话人1"]["score"] - sc["说话人1"]["score"]) < 1e-6)
    verdict_m = SV.decide(cues, sc_m, threshold=0.5, low=0.35)
    check("多声纹下判定：说话人1/2 保留、3 丢弃",
          [st for _, st, _ in verdict_m] == ["keep", "keep", "keep", "drop"],
          [st for _, st, _ in verdict_m])

    # ---------------- 6) decide() 三分支 ----------------
    say("\n== 6) decide() 判定 ==")
    verdict = SV.decide(cues, sc, threshold=0.5, low=0.35)
    got = [st for _, st, _ in verdict]
    check("三分支判定正确 keep/drop/keep/drop",
          got == ["keep", "drop", "keep", "drop"], got)
    sc2 = dict(sc)
    sc2["说话人2"] = {"score": 0.42, "n": 1, "seconds": 1.0}
    verdict2 = SV.decide(cues, sc2, threshold=0.5, low=0.35)
    check("存疑区(0.35~0.5)判 review",
          [st for _, st, _ in verdict2][1] == "review",
          [st for _, st, _ in verdict2])
    sc3 = {"说话人1": {"score": float("nan"), "n": 1, "seconds": 1.0}}
    verdict3 = SV.decide(cues, sc3, threshold=0.5, low=0.35)
    check("分数为 NaN 时保守判 review（保留待人工）",
          all(st == "review" for _, st, _ in verdict3),
          [st for _, st, _ in verdict3])

    # ---------------- 7) filter_srt 端到端 ----------------
    say("\n== 7) filter_srt 端到端（注入假 PCM / 假编码器）==")
    tmpdir = tempfile.mkdtemp(prefix="vt_vp_e2e_")
    old_read_pcm = SV.read_pcm
    SV.read_pcm = lambda src, **kw: pcm
    try:
        srt_path = os.path.join(tmpdir, "in.srt")
        with open(srt_path, "w", encoding="utf-8") as fh:
            fh.write(SRT)
        out_path = os.path.join(tmpdir, "out.srt")
        res = SV.filter_srt("fake.mp4", srt_path, {"embedding": tpl},
                            threshold=0.5, low=0.35, out_path=out_path,
                            encoder=enc)
        check("保留 2 条（说话人1 的两句）", res["kept_total"] == 2, res)
        check("丢弃 2 条", res["drop"] == 2, res)
        out = open(out_path, encoding="utf-8-sig").read()
        check("产物含主播台词", "大家好我是主播" in out and "今天我们聊点别的" in out)
        check("产物不含嘉宾台词", "我是嘉宾" not in out and "我也来说两句" not in out)
        check("序号已重排（1,2）", out.strip().startswith("1") and "\n2\n" in out, out[:40])
        check("时间轴原样保留（未被重算）",
              "00:00:01,000 --> 00:00:02,000" in out
              and "00:00:04,000 --> 00:00:05,000" in out)
        rep = os.path.splitext(out_path)[0] + ".报告.txt"
        check("同时产出复核报告", os.path.isfile(rep), rep)
        check("报告含各说话人得分", "说话人1" in open(rep, encoding="utf-8").read())

        strict_out = os.path.join(tmpdir, "strict.srt")
        # ⚠ 注入分数必须落在**现行默认存疑区** [low, threshold) = [0.45, 0.55)
        #   之内。原先取 0.42 是配旧的 (threshold=0.5, low=0.35)；阈值收紧后
        #   0.42 掉到 low 之下、判 drop，本组就测不到 keep_review 这个分支了。
        #   这里改用 0.50（区间正中），并把阈值显式写死，不依赖默认值。
        sc4 = {"说话人1": {"score": 1.0, "n": 2, "seconds": 2.0},
               "说话人2": {"score": 0.50, "n": 1, "seconds": 1.0},
               "说话人3": {"score": 0.05, "n": 1, "seconds": 1.0}}
        old_sbs = SV.score_by_speaker
        SV.score_by_speaker = lambda *a, **k: sc4
        try:
            res2 = SV.filter_srt("fake.mp4", srt_path, {"embedding": tpl},
                                 out_path=strict_out, encoder=enc,
                                 threshold=0.55, low=0.45,
                                 keep_review=False)
            check("keep_review=False 时存疑条也被丢弃",
                  res2["kept_total"] == 2 and res2["review"] == 1, res2)
        finally:
            SV.score_by_speaker = old_sbs

        # 钉住出厂默认阈值本身：这次调参（0.5→0.55 / 0.35→0.45）是真实素材
        # 踩坑后的决定（游戏官方旁白相似度 0.390 落在旧存疑区里被误保留）。
        # 断言写死数值，防止以后有人"看着宽松点好"又调回去。
        check("出厂默认阈值 = 0.55（异人上限 0.450 与同人下限 0.681 的中点）",
              SV.DEFAULT_THRESHOLD == 0.55, SV.DEFAULT_THRESHOLD)
        check("出厂默认存疑区下界 = 0.45（贴着异人实测上限，不再宽到 0.35）",
              SV.DEFAULT_LOW == 0.45, SV.DEFAULT_LOW)
        # 回归：0.390 的「游戏官方中文旁白」必须落在存疑区之下被丢弃。
        # 期望 keep/drop/keep/drop：说话人1 占 cues[0] 与 cues[2] 两条（都保留），
        # 0.390 的旁白与 0.05 的路人两条都是 drop。
        sc_narr = {"说话人1": {"score": 1.0, "n": 2, "seconds": 2.0},
                   "说话人2": {"score": 0.390, "n": 1, "seconds": 2.7},
                   "说话人3": {"score": 0.05, "n": 1, "seconds": 1.0}}
        vd_narr = SV.decide(cues, sc_narr)
        check("回归：相似度 0.390 的官方旁白被判 drop（旧阈值会误判 review 保留）",
              [st for _, st, _ in vd_narr] == ["keep", "drop", "keep", "drop"],
              [st for _, st, _ in vd_narr])
    finally:
        SV.read_pcm = old_read_pcm
        shutil.rmtree(tmpdir, ignore_errors=True)

    # ---------------- 8) 真模型（存在才跑） ----------------
    say("\n== 8) 真模型（CAM++ ONNX）==")
    if not os.path.isfile(SV.MODEL_PATH):
        say("  [SKIP] 模型不存在：%s" % SV.MODEL_PATH)
        say("         运行 tools/download_open_source_deps.py --only speaker-model")
    else:
        try:
            enc2 = SV.VoiceprintEncoder()
            e1 = enc2.embed(sig)
            check("embedding 维数 = 192", e1.shape == (SV.EMB_DIM,), e1.shape)
            check("已 L2 归一化", abs(float(np.linalg.norm(e1)) - 1.0) < 1e-5,
                  float(np.linalg.norm(e1)))
            e2 = enc2.embed(sig)
            check("同段音频两次结果完全一致",
                  float(np.max(np.abs(e1 - e2))) < 1e-6)
            sig2 = (sig * 0.5).astype(np.float32)
            check("同段音频缩放后完全一致（峰值归一化的作用）",
                  SV.cosine(e1, enc2.embed(sig2)) > 0.99999,
                  SV.cosine(e1, enc2.embed(sig2)))
            other = np.random.RandomState(1).randn(16000).astype(np.float32) * 0.1
            check("与白噪声不相似（<0.5）", SV.cosine(e1, enc2.embed(other)) < 0.5,
                  SV.cosine(e1, enc2.embed(other)))
            check("过短音频抛 VoiceprintError",
                  _raises(SV.VoiceprintError, enc2.embed,
                          np.zeros(100, dtype=np.float32)))
        except SV.VoiceprintError as e:
            check("真模型可运行", False, str(e)[:120])

    # ---------------- 9) 路径解析（不落 C 盘 / 打包形态） ----------------
    say("\n== 9) 路径解析 ==")
    check("TOOLS_DIR 在 tools 下",
          os.path.basename(SV.TOOLS_DIR) == "tools", SV.TOOLS_DIR)
    check("MODEL_PATH 落在 TOOLS_DIR\\asr_model",
          os.path.dirname(SV.MODEL_PATH) == SV.MODEL_DIR
          and os.path.basename(SV.MODEL_DIR) == "asr_model", SV.MODEL_PATH)
    check("TEMPLATE_DIR 落在 DATA_DIR\\voiceprint",
          os.path.dirname(SV.TEMPLATE_DIR) == SV.DATA_DIR
          and os.path.basename(SV.TEMPLATE_DIR) == "voiceprint",
          SV.TEMPLATE_DIR)
    check("FFMPEG 落在 TOOLS_DIR",
          os.path.dirname(SV.FFMPEG) == SV.TOOLS_DIR, SV.FFMPEG)
    _sysdrive = (os.environ.get("SystemDrive") or "C:").lower()
    _on_c = [p for p in (SV.TOOLS_DIR, SV.DATA_DIR, SV.MODEL_PATH,
                         SV.TEMPLATE_DIR, SV.FFMPEG)
             if os.path.splitdrive(p)[0].lower() == _sysdrive]
    check("所有落盘路径都不在系统盘（%s）" % _sysdrive, not _on_c, _on_c)
    check("TOOLS_DIR 优先取自引擎（而非按 __file__ 推）",
          _engine_tools_matches(), SV.TOOLS_DIR)
    check("model_present() 返回布尔", isinstance(SV.model_present(), bool),
          SV.model_present())
    if SV.model_present():
        check("模型已就位时 download_model 直接返回、不联网",
              SV.download_model() == SV.MODEL_PATH)

    # ---------------- 汇总 ----------------
    say("\n" + "=" * 62)
    if FAILS:
        say("  结果：%d 项失败" % len(FAILS))
        for x in FAILS:
            say("   · " + x)
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


def _engine_tools_matches():
    """确认声纹模块的 TOOLS_DIR 与引擎解析结果一致。

    这条是**回归防线**：早先声纹模块按 `__file__` 自己推层级，源码运行没事，
    打包后 `__file__` 指向 PyInstaller 的 `_MEIPASS` 临时目录，于是模型路径
    变成 `%TEMP%\\tools\\asr_model\\…`（C 盘），用户侧表现就是「声纹模型缺失」。
    """
    try:
        import video_toolbox as _e
        return (os.path.normcase(os.path.abspath(SV.TOOLS_DIR))
                == os.path.normcase(os.path.abspath(_e.TOOLS_DIR)))
    except Exception:  # noqa: BLE001
        return False


def _raises(exc, fn, *a, **kw):
    try:
        fn(*a, **kw)
    except exc:
        return True
    except Exception:  # noqa: BLE001
        return False
    return False


if __name__ == "__main__":
    sys.exit(main())
