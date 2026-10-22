#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# @version 2.5.4
"""主播声纹链路自检（离线，不联网、不依赖 ffmpeg）。

覆盖 src/speaker_voiceprint.py：
  · kaldi 兼容 fbank 的形状 / 有限性 / 黄金值（防实现回归）
  · 余弦相似度边界（含 NaN 与零向量）
  · 声纹模板落盘 -> 读回 往返
  · 多片段录入（enroll_pcm：同人一致性校验 + 均值、拒落盘）
  · 追加录入（enroll_pcm(base=)：与已有模板折叠、守卫拒绝异人）
  · 命令行回显编码（GBK 流下打印韩文声纹名不崩、不乱码）
  · 频谱门控（谐波音 vs 白噪声的判据分离、静音地板、严格档）
  · 参考片段拼接（时间分箱、拼接淡变、越界/过短 run 的处理）
  · 素材体检判读（_quality_verdict 的 clean/caution/risky 与逐条告警）
  · 库内混淆检查与库体检（check_confusion / format_confusion / audit_library）
  · 自动选段与自动录入（suggest_clips 只取主说话人、enroll_auto 落溯源元信息）
  · 按说话人聚簇打分 / 逐条打分
  · 本地声纹聚类：基本纯度 + 时长加权簇心 / 歧义拒分的几何关系用例
  · decide() 的 keep / drop / review 三分支
  · filter_srt() 端到端（注入假编码器 + 假 PCM，绕开 ffmpeg）
  · 长音频分块推理（假会话钉块数/边界/均值算术；真模型钉单跑一致性）
  · RMS 归一化（增益不变 / 抗爆音）与能量 VAD（剪静音 / 保停顿 / 去毛刺）
  · 真模型（存在才跑）：单位范数、同段自比 1.0、padding/爆音不变性

fbank 的正确性另有**外部基准**验证：与 kaldi-native-fbank 逐元素比对，
高能量帧 max|Δ| < 1e-3、最终 embedding 余弦 > 0.999（2026-10-08 实测），
本文件用黄金值把该结论固化下来，避免每次都要联网拉基准包。

运行：tools/python/python.exe _selftest_speaker_voiceprint.py
结果同时打印到 stdout 并写入 C:\\bld\\_speaker_vp_test\\result.txt。
"""
import io
import os
import shutil
import sys
import tempfile

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("VT_NO_PIPELINE", "1")
os.environ.setdefault("VT_NO_SYNC", "1")
# 声纹同步是**独立通道**（src/voiceprint_sync.py，开关 VT_NO_VP_SYNC，与上面
# 的 VT_NO_SYNC 互不影响）：自检里录入/删除模板会触发排队列，必须单独关掉，
# 否则会往真实的 data/vp_sync/voiceprint_pending.jsonl 里写测试条目。
os.environ.setdefault("VT_NO_VP_SYNC", "1")

import speaker_voiceprint as SV  # noqa: E402

#: 自检输出落仓库 data/tmp/dev_out/（2026-10-21 自 C:\bld 迁回仓库内）
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "data", "tmp", "dev_out", "_speaker_vp_test")
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

SR1 = SV.SAMPLE_RATE


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


def tone_pcm(f0=150.0, seconds=2.0, peak=0.1, n_harm=8, sample_rate=SR1):
    """谐波叠加音：能量集中在低频少数几根谐波上——**频谱门控眼里「像人声」**
    （谱平坦度低、4k-8k 迅速衰减）。按峰值归一，方便 `FakeEncoder` 分辨说话人。
    """
    t = np.arange(int(seconds * sample_rate), dtype=np.float64) / sample_rate
    x = np.zeros_like(t)
    for k in range(1, n_harm + 1):
        x += np.sin(2 * np.pi * f0 * k * t) / float(k ** 2)
    x *= float(peak) / max(float(np.max(np.abs(x))), 1e-9)
    return x.astype(np.float32)


def noise_pcm(seconds=2.0, peak=0.1, seed=7, sample_rate=SR1):
    """白噪声：谱平坦度≈1、高频不衰减——**门控眼里「像音乐/游戏音」**。"""
    x = np.random.RandomState(seed).randn(int(seconds * sample_rate))
    x *= float(peak) / max(float(np.max(np.abs(x))), 1e-9)
    return x.astype(np.float32)


def talk_pcm(f0=150.0, peak=0.1, chunks=10, chunk_sec=4.0, gap_sec=0.6,
             sample_rate=SR1):
    """合成「某人在说话」：一段段谐波音夹静音停顿。

    必须带停顿——真实语音有句间停顿，门控因此切出多个 run；纯连续音会整片连成
    **一个** run，`_clip_to_intervals` 的裁剪逻辑与体检的对照段就都测不到了。
    """
    parts = []
    for _i in range(chunks):
        parts.append(tone_pcm(f0, chunk_sec, peak, sample_rate=sample_rate))
        parts.append(np.zeros(int(gap_sec * sample_rate), dtype=np.float32))
    return np.concatenate(parts).astype(np.float32)


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

    # ---------------- 3b2) RMS 归一化 ----------------
    say("\n== 3b2) RMS 归一化（对爆音稳健，同为增益不变）==")
    body = (0.3 * np.sin(2 * np.pi * 440 * np.arange(16000) / 16000.0)
            ).astype(np.float32)
    clicked = body.copy()
    clicked[100:105] = 0.9                       # 一个 0.9 的爆音脉冲
    nb = SV.normalize_rms(body)
    check("干净片段 RMS 拉到目标电平 0.1",
          abs(float(np.sqrt(np.mean(nb.astype(np.float64) ** 2))) - 0.1) < 1e-3,
          float(np.sqrt(np.mean(nb.astype(np.float64) ** 2))))
    check("缩放后归一化结果一致（增益不变）",
          np.allclose(SV.normalize_rms(body * 0.05), nb, atol=1e-6))
    check("干净片段不触顶（峰值 = 0.1×crest < 1）",
          float(np.max(np.abs(nb))) < 1.0, float(np.max(np.abs(nb))))
    nc = SV.normalize_rms(clicked)
    body_after = float(np.sqrt(np.mean(nc[480:].astype(np.float64) ** 2)))
    check("带爆音片段：主体能量仍 ≈ 目标电平（不被爆音吃掉）",
          abs(body_after - 0.1) < 0.01, "%.4f" % body_after)
    pc = SV.normalize_peak(clicked)
    body_peak = float(np.sqrt(np.mean(pc[480:].astype(np.float64) ** 2)))
    clean_pk_body = float(np.sqrt(np.mean(
        SV.normalize_peak(body)[480:].astype(np.float64) ** 2)))
    check("对照：峰值归一化下主体被爆音压掉约 9dB（0.707 -> 0.236）",
          body_peak < clean_pk_body * 0.4, "%.4f" % body_peak)
    silent = np.full(16000, 3e-7, dtype=np.float32)
    check("近静音报 VoiceprintError",
          _raises(SV.VoiceprintError, SV.normalize_rms, silent))
    check("空音频报 VoiceprintError",
          _raises(SV.VoiceprintError, SV.normalize_rms,
                  np.zeros(0, dtype=np.float32)))

    # ---------------- 3c) 能量 VAD ----------------
    say("\n== 3c) trim_silence 能量 VAD ==")
    one_sec = (0.3 * np.sin(2 * np.pi * 440 * np.arange(SR1) / 16000.0)
               ).astype(np.float32)
    padded = np.concatenate([np.zeros(SR1, np.float32), one_sec,
                             np.zeros(SR1, np.float32)])
    kept = SV.trim_silence(padded)
    kept_s = len(kept) / float(SV.SAMPLE_RATE)
    check("剪掉两侧 1s 静音（保留 0.85~1.25s，帧边界有余量）",
          0.85 < kept_s < 1.25, "%.2fs" % kept_s)

    def _max_zero_run(a):
        best = cur = 0
        for v in a:
            cur = cur + 1 if abs(float(v)) < 1e-6 else 0
            best = max(best, cur)
        return best / float(SV.SAMPLE_RATE)

    check("保留段内无超过 0.5s 的连续静音",
          _max_zero_run(kept) < 0.5, "%.2fs" % _max_zero_run(kept))
    # 句间 0.3s 停顿保留（填缝）、0.8s 长停顿剪掉
    gap_short = np.concatenate([one_sec, np.zeros(int(0.3 * SR1), np.float32),
                                one_sec])
    gs = SV.trim_silence(gap_short)
    check("0.3s 句间停顿被保留（语句连续性）",
          len(gs) > 1.9 * SR1, "%.2fs" % (len(gs) / float(SV.SAMPLE_RATE)))
    gap_long = np.concatenate([one_sec, np.zeros(int(0.8 * SR1), np.float32),
                               one_sec])
    gl = SV.trim_silence(gap_long)
    check("0.8s 长停顿被剪掉",
          len(gl) < len(gap_long) - 0.5 * SR1,
          "%.2fs" % (len(gl) / float(SV.SAMPLE_RATE)))
    # 孤立爆点（0.05s 响、其余静音）作为毛刺丢弃后，整段不足 0.2s -> 报错
    blip = np.zeros(SR1, np.float32)
    blip[8000:8800] = 0.5
    check("孤立爆点不构成「人声」（不足 0.2s 报错）",
          _raises(SV.VoiceprintError, SV.trim_silence, blip))
    check("纯静音报错（数字静音 < -75dB）",
          _raises(SV.VoiceprintError, SV.trim_silence,
                  np.zeros(2 * SR1, np.float32)))
    check("短于 1 帧的输入原样返回（无从判断）",
          SV.trim_silence(np.full(100, 0.1, np.float32)).shape == (100,))
    check("确定性：两次结果一致",
          np.array_equal(SV.trim_silence(padded), kept))

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

    # ---------------- 4c) 多片段录入 ----------------
    say("\n== 4c) 多片段录入（enroll_pcm：一致性校验 + 均值）==")
    tmpdir = tempfile.mkdtemp(prefix="vt_vp_enc_")
    old_tpl_dir = SV.TEMPLATE_DIR
    SV.TEMPLATE_DIR = tmpdir
    try:
        enc4 = FakeEncoder()
        r = SV.enroll_pcm([fake_pcm(1, 2.0), fake_pcm(1, 3.0)],
                          name="多段主播", encoder=enc4)
        check("两段同人录入成功", r["clips"] == 2 and r["consistency"] == 1.0, r)
        t = SV.load_template("多段主播")
        emb1 = np.zeros(SV.EMB_DIM, dtype=np.float32)
        emb1[1] = 1.0
        check("均值模板 = 单人向量", abs(SV.cosine(t["embedding"], emb1) - 1.0)
              < 1e-6, SV.cosine(t["embedding"], emb1))
        check("元信息记录片段数", t.get("clips") == 2, t.get("clips"))
        check("混入他人即拒绝落盘（相似度 0 < 0.55）",
              _raises(SV.VoiceprintError, SV.enroll_pcm,
                      [fake_pcm(1, 2.0), fake_pcm(2, 2.0)],
                      name="坏模板", encoder=enc4))
        check("拒绝时不落盘", not os.path.isfile(SV.template_path("坏模板")))
        check("过短片段报错",
              _raises(SV.VoiceprintError, SV.enroll_pcm,
                      [fake_pcm(1, 0.1)], encoder=enc4))
        check("空片段列表报错",
              _raises(SV.VoiceprintError, SV.enroll_pcm, [], encoder=enc4))
    finally:
        SV.TEMPLATE_DIR = old_tpl_dir
        shutil.rmtree(tmpdir, ignore_errors=True)

    # ---------------- 4d) 追加录入（base 折叠） ----------------
    say("\n== 4d) 追加录入（enroll_pcm(base=)：与已有模板折叠）==")

    class WiggleEncoder:
        """同人但每次略抖动的向量（每次 +4°，模拟同一主播不同片段）。

        FakeEncoder 的 one-hot 会让「两段不同片段」产生**完全相同**的向量，
        折叠按 fp 去重后 clips 不会累加——测不到追加语义，故这里给同人的
        连续片段加一个确定性小角度漂移（cos4°≈0.998，远高于 0.55 守卫）。"""

        def __init__(self):
            self.n = 0

        def embed(self, samples, sample_rate=16000):
            s = np.asarray(samples, dtype=np.float32).reshape(-1)
            if s.size == 0 or float(np.max(np.abs(s))) < 1e-6:
                raise SV.VoiceprintError("无声")
            k = int(round(float(np.max(np.abs(s))) * 10))
            ang = (self.n * 4.0) % 30.0
            self.n += 1
            v = np.zeros(SV.EMB_DIM, dtype=np.float32)
            if k == 1:
                v[0] = float(np.cos(np.radians(ang)))
                v[1] = float(np.sin(np.radians(ang)))
            else:
                v[k % SV.EMB_DIM] = 1.0             # 其他「人」：正交 one-hot
            return v

    tmpdir = tempfile.mkdtemp(prefix="vt_vp_app_")
    old_tpl_dir = SV.TEMPLATE_DIR
    SV.TEMPLATE_DIR = tmpdir
    try:
        enc5 = WiggleEncoder()
        emb0 = np.zeros(SV.EMB_DIM, dtype=np.float32)
        emb0[0] = 1.0
        r1 = SV.enroll_pcm([fake_pcm(1, 2.0)], name="主播A", encoder=enc5)
        t1 = SV.load_template("主播A")
        check("单片段录入带 mix（1 叶）", len(t1["mix"]) == 1, t1["mix"])
        check("weight = 合成长度 1.0（单片段）", abs(t1["weight"] - 1.0) < 1e-3,
              t1["weight"])
        check("clips = 1", t1["clips"] == 1, t1["clips"])
        # 多片段批次的 consistency 必须落盘（曾只进返回值、文件里没有）
        enc5b = WiggleEncoder()
        SV.enroll_pcm([fake_pcm(1, 2.0), fake_pcm(1, 3.0)],
                      name="主播B", encoder=enc5b)
        check("多片段录入的 consistency 已落盘",
              SV.load_template("主播B").get("consistency") is not None,
              SV.load_template("主播B").get("consistency"))
        r2 = SV.enroll_pcm([fake_pcm(1, 3.0)], name="主播A", encoder=enc5,
                           base=t1)
        check("追加同一人：appended 标记", r2["appended"] is True, r2)
        t2 = SV.load_template("主播A")
        check("追加后 clips 累加 = 2", t2["clips"] == 2, t2["clips"])
        check("追加后 consistency 落盘（跨叶最低余弦）",
              t2.get("consistency") is not None
              and 0.9 < t2["consistency"] <= 1.0, t2.get("consistency"))
        check("追加后向量仍与首片同向（余弦 > 0.99）",
              SV.cosine(t2["embedding"], emb0) > 0.99,
              SV.cosine(t2["embedding"], emb0))
        check("两片不同内容各计一叶（mix 2 叶）", len(t2["mix"]) == 2,
              len(t2["mix"]))
        check("seconds 累加", t2["seconds"] == 5.0, t2["seconds"])
        check("追加异人被拒绝（守卫）",
              _raises(SV.VoiceprintError, SV.enroll_pcm, [fake_pcm(2, 2.0)],
                      name="主播A", encoder=enc5, base=SV.load_template("主播A")))
        check("被拒时原模板未被改写（clips 仍 2）",
              SV.load_template("主播A")["clips"] == 2)
    finally:
        SV.TEMPLATE_DIR = old_tpl_dir
        shutil.rmtree(tmpdir, ignore_errors=True)

    # ---------------- 4e) 命令行回显编码（GBK 流 / 管道）----------------
    say("\n== 4e) 命令行回显编码（韩文声纹名）==")
    tmpdir = tempfile.mkdtemp(prefix="vt_vp_cli_")
    old_tpl_dir, old_sel = SV.TEMPLATE_DIR, SV.SELECTION_PATH
    SV.TEMPLATE_DIR = tmpdir
    SV.SELECTION_PATH = os.path.join(tmpdir, "selection.json")
    old_out, old_err = sys.stdout, sys.stderr

    def _run_cli(argv):
        """在「编码 gbk + 严格报错」的假标准流上跑 CLI，返回 (rc, out字节, err字节)。

        模拟 Windows 下**管道 / 重定向**的口径：此时 Python 按 locale（中文系统
        cp936）编码 stdout，韩文声纹名会直接 UnicodeEncodeError —— 真实控制台
        走 WriteConsoleW 反而不崩，所以这个坑只在 `| head`、`> log` 时暴露。
        """
        bo, be = io.BytesIO(), io.BytesIO()
        wo = io.TextIOWrapper(bo, encoding="gbk", errors="strict")
        we = io.TextIOWrapper(be, encoding="gbk", errors="strict")
        sys.stdout, sys.stderr = wo, we
        try:
            rc = SV.main(argv)
            wo.flush()
            we.flush()
        finally:
            sys.stdout, sys.stderr = old_out, old_err
        # ⚠ 必须在 wo/we 还活着时取字节：包装器被 GC 会连带关掉底层 BytesIO
        out_b, err_b = bo.getvalue(), be.getvalue()
        del wo, we
        return rc, out_b, err_b

    try:
        e6 = np.zeros(SV.EMB_DIM, dtype=np.float32)
        e6[0] = 1.0
        SV.save_template("미니보기", e6)
        probe = io.TextIOWrapper(io.BytesIO(), encoding="gbk", errors="strict")
        check("假流有效：GBK 严格流直写韩文必崩（否则本节断言无意义）",
              _raises(UnicodeEncodeError,
                      lambda: (probe.write("미니보기"), probe.flush())))

        rc, out_b, _err_b = _run_cli(["list"])
        text = out_b.decode("utf-8", "replace")
        check("list 在 GBK 流下不崩（rc=0）", rc == 0, rc)
        check("list 完整回显韩文声纹名", "미니보기" in text,
              text.strip().replace("\n", " | ")[:120])
        check("回显不是问号占位（真按 UTF-8 写出）", "??" not in text)

        rc2, o2, err2 = _run_cli(["delete", "미니보기_查无此人"])
        dtext = (o2 + err2).decode("utf-8", "replace")
        check("delete 查无此人返回 1", rc2 == 1, rc2)
        check("delete 回显里的韩文名不崩、不乱码", "미니보기_查无此人" in dtext,
              dtext.strip()[:100])
        check("同名真模板未被误删", os.path.isfile(SV.template_path("미니보기")))

        # VoiceprintError 走 stderr：模板缺失的提示里同样带韩文名
        rc3, o3, err3 = _run_cli(["score", "--src", "无此素材.mp4",
                                  "--srt", "无此字幕.srt", "--name", "미니보기2"])
        etext = err3.decode("utf-8", "replace")
        check("模板缺失按可预期失败返回 2", rc3 == 2, rc3)
        check("stderr 的失败提示里韩文名不崩、不乱码", "미니보기2" in etext,
              etext.strip()[:100])
    finally:
        sys.stdout, sys.stderr = old_out, old_err
        SV.TEMPLATE_DIR, SV.SELECTION_PATH = old_tpl_dir, old_sel
        shutil.rmtree(tmpdir, ignore_errors=True)

    # ---------------- 4f) 频谱门控 ----------------
    say("\n== 4f) 频谱门控（排 BGM 的选段判据）==")
    n_fr = int(SV.GATE_FRAME_SEC * SR1)
    seg_sp, seg_nz = tone_pcm(150.0, 2.0, 0.1), noise_pcm(2.0, 0.1)
    mixed = np.concatenate([seg_sp, seg_nz, seg_sp])
    flat, hf, db = SV.spectral_frame_features(mixed)
    k = int(round(2.0 / SV.GATE_FRAME_SEC))          # 每段的帧数
    check("逐帧特征三列同长且帧数 = 时长/帧长",
          flat.shape == hf.shape == db.shape and flat.size == len(mixed) // n_fr,
          (flat.size, len(mixed) // n_fr))
    check("谐波音谱平坦度低（< %.2f）" % SV.SPEECH_FLAT_MAX,
          float(np.median(flat[:k])) < SV.SPEECH_FLAT_MAX,
          round(float(np.median(flat[:k])), 4))
    check("白噪声谱平坦度高（> 0.5）", float(np.median(flat[k:2 * k])) > 0.5,
          round(float(np.median(flat[k:2 * k])), 4))
    check("谐波音高频衰减够（< %.0f dB）" % SV.SPEECH_HF_MAX_DB,
          float(np.median(hf[:k])) < SV.SPEECH_HF_MAX_DB,
          round(float(np.median(hf[:k])), 1))
    check("白噪声高频不衰减（> %.0f dB）" % SV.SPEECH_HF_MAX_DB,
          float(np.median(hf[k:2 * k])) > SV.SPEECH_HF_MAX_DB,
          round(float(np.median(hf[k:2 * k])), 1))
    mask6, runs6, _f6 = SV.gate_speech_runs(mixed)
    check("门控留下两段谐波音、排掉中间的白噪声", len(runs6) == 2, runs6)
    check("第一段起点贴着 0、时长≈2 秒",
          runs6 and runs6[0][0] <= 0.4 and 1.4 <= runs6[0][1] <= 2.4,
          runs6[:1])
    check("第二段落在 4~6 秒（跳过噪声段）",
          len(runs6) == 2 and 3.6 <= runs6[1][0] <= 4.4
          and 1.4 <= runs6[1][1] <= 2.4, runs6[1:2])
    check("纯静音不产生人声段（绝对电平地板生效）",
          SV.gate_speech_runs(np.zeros(int(3.0 * SR1), dtype=np.float32))[1] == [])
    # 整段录音都比数字静音地板还轻：纯相对判据（最响帧 -45dB）会把它**全部**
    # 放进来（-83dB 的帧确实高于 -128dB），绝对地板 -75dB 必须拦住
    quiet = np.concatenate([tone_pcm(150.0, 3.0, 1e-4),
                            np.zeros(int(1.0 * SR1), dtype=np.float32)]
                           ).astype(np.float32)
    q_runs = SV.gate_speech_runs(quiet)[1]
    check("极轻录音不被相对判据放行（绝对地板 %.0f dB 生效）" % SV.VAD_ABS_SILENCE_DB,
          q_runs == [], q_runs[:2])
    check("音频不足一帧时返回空而不是崩", SV.gate_speech_runs(
        np.zeros(10, dtype=np.float32))[1] == [])
    check("门控判据可加严（严格档留下更少人声）",
          SV.gate_speech_runs(mixed, flat_max=SV.STRICT_FLAT_MAX,
                              hf_max=SV.STRICT_HF_MAX_DB,
                              min_run=SV.STRICT_MIN_RUN_SEC)[1] == [])

    # ---------------- 4g) 参考片段拼接 ----------------
    say("\n== 4g) 参考片段拼接（分箱铺满全片 + 拼接淡变）==")
    pcm7 = tone_pcm(150.0, 20.0, 0.1)
    runs7 = [(0.5, 2.0), (5.0, 2.0), (10.0, 2.0), (15.0, 2.0)]
    packed = SV.stitch_runs(pcm7, runs7, target_sec=3.0, n_bins=2, min_sec=1.5)
    check("按箱出片段（2 箱 -> 2 片）", len(packed) == 2, len(packed))
    check("第 1 箱只收前半段的 run", packed
          and all(s < 10.0 for s, _d in packed[0][1]), packed[0][1] if packed else None)
    check("第 2 箱只收后半段的 run", len(packed) == 2
          and all(s >= 10.0 for s, _d in packed[1][1]),
          packed[1][1] if len(packed) == 2 else None)
    check("片段采样数 = 所含 run 时长之和", packed
          and abs(len(packed[0][0]) / float(SR1)
                  - sum(d for _s, d in packed[0][1])) < 0.02,
          len(packed[0][0]) / float(SR1) if packed else None)
    check("拼接处已淡变（首尾样本≈0，不留咔哒声）", packed
          and abs(float(packed[0][0][0])) < 1e-4
          and abs(float(packed[0][0][-1])) < 1e-4)
    check("人声不足 min_sec 的箱被跳过（宁缺毋滥）",
          SV.stitch_runs(pcm7, [(0.5, 1.0)], target_sec=3.0, n_bins=2,
                         min_sec=1.5) == [])
    check("越界 run 与零长 run 被忽略",
          SV.stitch_runs(pcm7, [(19.5, 5.0), (0.5, 0.0)], n_bins=1,
                         min_sec=0.5) == [])
    check("不给 n_bins 时全部 run 拼成一片",
          len(SV.stitch_runs(pcm7, runs7, target_sec=100.0, n_bins=None,
                             min_sec=1.0)) == 1)

    # ---------------- 4h) 素材体检判读 ----------------
    say("\n== 4h) 素材体检判读（_quality_verdict，门槛按实测标定）==")
    # 下面两组数是 2026-10-14 两份真实主播录播的实测值（`_vp_tmp_pixeltree/calib.py`
    # 可复跑）：一份干净人声素材（应判 clean）、一份全程铺 BGM（应判 risky）。
    # 用真实测得的数当夹具，判据漂了自检就会红——比手编的漂亮数字有用。
    good = {"margin": 0.0078, "windows": 40, "pct_below_threshold": 1.4,
            "flat_median": 0.0049, "flat_p75": 0.0172, "hf_median": -19.6,
            "bg_level_db": -14.8, "bg_energy_pct": 1.6, "voice_run_max": 150.6,
            "voice_median": 0.9269, "voice_min": 0.79, "bg_median": 0.9191,
            "bg_max": 0.94, "win_min": 0.255, "win_median": 0.920,
            "bg_kind": "windows", "seg_len": 12.0}
    v, w, info = SV._quality_verdict(good)
    check("干净素材（实测）判 clean 且无告警", v == "clean" and w == [], (v, w))
    bad = {"margin": 0.0502, "windows": 40, "pct_below_threshold": 0.0,
           "flat_median": 0.030, "flat_p75": 0.0803, "hf_median": -9.1,
           "bg_level_db": -6.9, "bg_energy_pct": 31.1, "voice_run_max": 13.6,
           "voice_median": 0.9513, "voice_min": 0.944, "bg_median": 0.9011,
           "bg_max": 0.96, "win_min": 0.909, "win_median": 0.950,
           "bg_kind": "windows", "seg_len": 12.0}
    v2, w2, info2 = SV._quality_verdict(bad)
    check("BGM 压人声的素材（实测）判 risky", v2 == "risky", (v2, len(w2)))
    check("点出背景音能量占比", any("能量" in x for x in w2), [x[:22] for x in w2])
    check("点出人声被打碎", any("打碎" in x for x in w2))
    check("点出背景音几乎不停", any("背景音几乎不停" in x for x in w2))
    check("点出频谱不像干净人声", any("频谱不像干净人声" in x for x in w2))
    check("点出没有低分对照窗", any("对照窗" in x for x in w2))
    check("落差为正（+0.05）不误报「更认背景音」",
          not any("声学底" in x for x in w2), [x[:22] for x in w2])
    check("每条判据都在两份实测值之间留了余量",
          SV.QUALITY_BG_ENERGY_WARN_PCT > 15.0 * 0.5
          and SV.QUALITY_VOICE_RUN_WARN_SEC < 150.6
          and SV.QUALITY_WIN_MIN_WARN < 0.909 and SV.QUALITY_WIN_MIN_WARN > 0.255
          and SV.QUALITY_HF_WARN_DB < -9.1 and SV.QUALITY_HF_WARN_DB > -19.6
          and SV.QUALITY_FLAT_P75_WARN < 0.0803 and SV.QUALITY_FLAT_P75_WARN > 0.0172,
          (SV.QUALITY_BG_ENERGY_WARN_PCT, SV.QUALITY_VOICE_RUN_WARN_SEC,
           SV.QUALITY_WIN_MIN_WARN, SV.QUALITY_HF_WARN_DB, SV.QUALITY_FLAT_P75_WARN))
    # 落差为负 = 背景音比人声还像本人，这才是强信号
    v3, w3, _i3 = SV._quality_verdict(dict(bad, margin=-0.081))
    check("落差为负时点出「认的可能是声学底」",
          any("声学底" in x for x in w3), [x[:22] for x in w3])
    v4, w4, _i4 = SV._quality_verdict(dict(good, bg_energy_pct=40.0))
    check("单条告警判 caution", v4 == "caution" and len(w4) == 1, (v4, w4))
    # 没有对照段 / 单人素材 100% 判为本人 -> 只进「提示」，不算告警
    v5, w5, i5 = SV._quality_verdict(dict(good, bg_kind="none", bg_median=None,
                                          margin=None, pct_below_threshold=0.0,
                                          win_min=0.717))
    check("无对照段 + 单人素材：不告警（不误判好素材）",
          v5 == "clean" and w5 == [], (v5, w5))
    check("无对照段进「提示」而不是「告警」",
          len(i5) == 2 and any("没测到" in x for x in i5), [x[:24] for x in i5])
    # assess_material 端到端（注入假编码器，不碰真模型 / ffmpeg）：
    #   「人声区 + 一段纯噪声对照区」-> 应量出明显落差；
    #   「全程人声、没有对照段」  -> bg_kind=none，必须明说「这一项没测到」，
    #                                  且只进提示、不算告警（干净素材本该如此）。
    enc8 = FakeEncoder()
    vvec = enc8.embed(tone_pcm(150.0, 4.0, 0.1))
    pcm_h = np.concatenate([talk_pcm(150.0, 0.1, 8),       # 0~36.8 秒 人声
                            noise_pcm(6.0, 0.3),           # 36.8~42.8 秒 纯背景音
                            talk_pcm(150.0, 0.1, 4)]       # 尾部再接人声
                           ).astype(np.float32)
    q = SV.assess_material(pcm_h, vvec, encoder=enc8)
    check("体检返回档位与告警列表",
          q["verdict"] in ("clean", "caution", "risky")
          and isinstance(q["warnings"], list), q["verdict"])
    check("对照段两侧等长（seg_len = 背景段长，≤ 窗长）",
          q["bg_kind"] == "windows" and 0 < q["seg_len"] <= SV.AUTO_SCAN_WIN_SEC,
          (q["bg_kind"], q["seg_len"]))
    check("人声段得分远高于背景音段（假编码器下应完全分开）",
          q["margin"] is not None and q["margin"] > 0.5,
          (q["voice_median"], q["bg_median"], q["margin"]))
    check("有对照且分得开时不误报「认的是声学底」",
          not any("声学底" in x for x in q["warnings"]),
          [x[:30] for x in q["warnings"]])
    check("逐窗指标齐全", all(k in q for k in ("windows", "win_min", "win_median",
                                               "win_max", "pct_below_threshold")),
          q["windows"])
    # 干净但「没有对照段」的素材：人声连续段够长（>30 秒）、背景音能量极低，
    # 只是全程都有人在说话 —— 应当判 clean，两条「没测到」只进提示。
    q2 = SV.assess_material(talk_pcm(150.0, 0.1, 3, chunk_sec=40.0), vvec,
                            encoder=enc8)
    check("无对照段时 bg_kind=none 且 margin 为空",
          q2["bg_kind"] == "none" and q2["margin"] is None, q2["bg_kind"])
    check("干净素材不因「没有对照」被判有风险",
          q2["verdict"] == "clean" and q2["warnings"] == [],
          (q2["verdict"], [x[:26] for x in q2["warnings"]]))
    check("无对照段 / 无低分窗只进「提示」，不算成告警",
          len(q2["infos"]) == 2 and all("没测" in x for x in q2["infos"]),
          [x[:30] for x in q2["infos"]])
    cq = SV._compact_quality(dict(good, verdict="clean", warnings=[],
                                  win_list=[1, 2, 3], extra_key="不该进模板"))
    check("体检精简版只留判读字段",
          "extra_key" not in cq and "win_list" not in cq
          and cq["verdict"] == "clean", sorted(cq))
    check("体检精简版保留告警列表", cq["warnings"] == [])
    check("没有体检结果时精简版为 None", SV._compact_quality(None) is None)

    # ---------------- 4i) 库内混淆检查与库体检 ----------------
    say("\n== 4i) 库内混淆检查与库体检 ==")
    tmpdir = tempfile.mkdtemp(prefix="vt_vp_conf_")
    old_tpl_dir = SV.TEMPLATE_DIR
    SV.TEMPLATE_DIR = tmpdir
    try:
        e_a = np.zeros(SV.EMB_DIM, dtype=np.float32)
        e_a[0] = 1.0
        e_c = np.zeros(SV.EMB_DIM, dtype=np.float32)
        e_c[1] = 1.0
        e_d = (e_a * 0.5 + e_c * 0.866).astype(np.float32)      # 余弦 0.5 -> 存疑区
        for nm, ev in (("甲", e_a), ("乙", e_a.copy()), ("丙", e_c), ("丁", e_d)):
            SV.save_template(nm, ev)
        rows = SV.check_confusion("甲")
        check("按相似度降序列出全部对比对象",
              [r[0] for r in rows] == ["乙", "丁", "丙"], rows)
        check("同向量判 keep（≥%.2f）" % SV.DEFAULT_THRESHOLD,
              rows[0][2] == "keep" and rows[0][1] >= SV.DEFAULT_THRESHOLD, rows[0])
        check("0.5 判 review（存疑区）", rows[1][2] == "review", rows[1])
        check("正交判 ok", rows[2][2] == "ok" and rows[2][1] < SV.DEFAULT_LOW, rows[2])
        check("传裸向量时靠 skip 排掉自己",
              [r[0] for r in SV.check_confusion(e_a, skip="甲")] == ["乙", "丁", "丙"])
        fw = SV.format_confusion(rows)
        check("只有 keep 级出人话告警", len(fw) == 1 and "乙" in fw[0],
              [x[:40] for x in fw])
        check("告警点明后果与处置", "当主播保留" in fw[0] and "别同时启用" in fw[0])
        rep = SV.audit_library()
        check("库体检列出全部模板", rep["names"] == ["丁", "丙", "乙", "甲"],
              rep["names"])
        check("矩阵对称", rep["matrix"]["甲"]["乙"] == rep["matrix"]["乙"]["甲"])
        check("矩阵不含自比", "甲" not in rep["matrix"]["甲"])
        check("≥keep 的对进告警", any("甲" in x and "乙" in x for x in rep["warnings"]),
              [x[:36] for x in rep["warnings"][:2]])
        check("告警按相似度降序（最危险的在前）",
              bool(rep["warnings"]) and "1.000" in rep["warnings"][0],
              [x[:40] for x in rep["warnings"][:2]])
        check("元信息带 clips / seconds / 录入方式",
              rep["meta"]["甲"]["clips"] == 1 and rep["meta"]["甲"]["auto"] is False)
    finally:
        SV.TEMPLATE_DIR = old_tpl_dir
        shutil.rmtree(tmpdir, ignore_errors=True)

    # ---------------- 4j) 自动选段（suggest_clips / enroll_auto）----------------
    say("\n== 4j) 自动选段（suggest_clips / enroll_auto，注入假编码器）==")

    # 0~46 秒「说话人A」（峰值 0.1），46 秒起「说话人B」（峰值 0.2）。
    # FakeEncoder 按峰值给 one-hot，A/B 向量正交——聚簇必须把 B 剔掉。
    pcm_a = talk_pcm(150.0, 0.1, 10)
    pcm_ab = np.concatenate([pcm_a, talk_pcm(220.0, 0.2, 2)]).astype(np.float32)
    a_end = len(pcm_a) / float(SR1)
    enc9 = FakeEncoder()
    short_msg = ""
    try:
        SV.suggest_clips("假素材.mp4", pcm=pcm_ab[:int(20.0 * SR1)], encoder=enc9)
    except SV.VoiceprintError as e:
        short_msg = str(e)
    check("素材过短明确拒绝（< %.0f 秒，聚不出主说话人）" % SV.AUTO_MIN_TOTAL_SEC,
          bool(short_msg), short_msg[:60])
    check("过短报错指路手工选段", "手工选段" in short_msg, short_msg[:60])
    sug = SV.suggest_clips("假素材.mp4", n_clips=4, clip_sec=3.0,
                           encoder=enc9, pcm=pcm_ab)
    check("选出片段非空", len(sug["clips"]) >= 2, len(sug["clips"]))
    check("片段数不超过请求的箱数", len(sug["clips"]) <= 4, len(sug["clips"]))
    check("只取主说话人（B 在 %.0f 秒后，选段全落在其之前）" % a_end,
          all(s + d <= a_end for s, d in sug["spans"]),
          ["%.1f+%.1f" % sd for sd in sug["spans"]][:6])
    check("剔除非主说话人时给出告警",
          any("多个说话人" in x for x in sug["warnings"]),
          [x[:40] for x in sug["warnings"]])
    check("主簇占比 < 1（确实识别出第二人）",
          sug["dominant"]["share"] < 1.0, sug["dominant"])
    check("门控统计齐全", all(k in sug["speech"] for k in
                              ("sec", "ratio", "runs", "longest_run", "flat_median")),
          sug["speech"])
    check("门控按停顿切出多个 run（不是一整段）", sug["speech"]["runs"] >= 8,
          sug["speech"]["runs"])
    check("片段样本数与 spans 时长一致",
          all(abs(len(c) / float(SR1) - sum(d for _s, d in sp)) < 0.02
              for c, sp in sug["clips"]))

    tmpdir = tempfile.mkdtemp(prefix="vt_vp_auto_")
    old_tpl_dir = SV.TEMPLATE_DIR
    SV.TEMPLATE_DIR = tmpdir
    try:
        r = SV.enroll_auto("假素材.mp4", name="主播AUTO", n_clips=4,
                           clip_sec=3.0, encoder=enc9, pcm=pcm_ab)
        check("自动录入已落盘", os.path.isfile(r["path"]), r["path"])
        check("片段数与选段一致", r["clips"] == len(sug["clips"]),
              (r["clips"], len(sug["clips"])))
        check("假编码器下同一说话人一致性 = 1.0", r["consistency"] == 1.0,
              r["consistency"])
        t = SV.load_template("主播AUTO")
        check("模板记录自动选段溯源（auto 元信息）",
              bool(t.get("auto")) and t["auto"]["bins"] == 4, t.get("auto"))
        check("模板记录素材体检结论",
              (t.get("quality") or {}).get("verdict") in ("clean", "caution", "risky"),
              (t.get("quality") or {}).get("verdict"))
        check("返回体带 warnings / confusion / quality / spans",
              all(k in r for k in ("warnings", "confusion", "quality", "spans")))
        check("seconds = 各片段之和", abs(r["seconds"] - sum(
            d for _s, d in r["spans"])) < 1.0, (r["seconds"], r["spans"][:2]))
        r2 = SV.enroll_auto("假素材.mp4", name="主播AUTO", n_clips=4,
                            clip_sec=3.0, encoder=enc9, pcm=pcm_ab, append=True)
        check("追加模式返回 appended=True", r2.get("appended") is True)
        check("同一批片段重复追加被指纹去重（clips 不变）",
              r2["clips"] == r["clips"], (r["clips"], r2["clips"]))
        check("追加到不存在的声纹明确报错",
              _raises(SV.VoiceprintError, SV.enroll_auto, "假素材.mp4",
                      name="查无此人", encoder=enc9, pcm=pcm_ab, append=True))
        check("assess=False 时跳过体检（quality 为 None）",
              SV.enroll_auto("假素材.mp4", name="主播NOQ", n_clips=4, clip_sec=3.0,
                             encoder=enc9, pcm=pcm_ab, assess=False)["quality"] is None)
    finally:
        SV.TEMPLATE_DIR = old_tpl_dir
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

    # ---------------- 5c) 本地声纹聚类（无 [说话人N] 时） ----------------
    say("\n== 5c) 本地声纹聚类 ==")
    # 造 3 位「说话人」交替的假音频 + 对应 cue（cue 2 故意很短，应不参与聚类）
    plan = [(0.0, 1.0, 1), (1.5, 1.0, 2), (3.0, 1.2, 1), (5.0, 1.0, 3),
            (6.5, 1.0, 2), (8.0, 0.25, 3)]
    pcm2 = np.zeros(int(11.0 * 16000), dtype=np.float32)
    doc2 = SV.secore.SubtitleDoc()
    rows = []
    for i, (st, dur, sid) in enumerate(plan, 1):
        a, b = int(st * 16000), int((st + dur) * 16000)
        pcm2[a:b] = sid / 10.0
        rows.append("%d\n%s --> %s\n第 %d 句\n" % (
            i, _ts(st), _ts(st + dur), i))
    doc2.load_bytes("\n".join(rows).encode("utf-8"))
    cues2 = list(doc2.cues)
    check("假素材解析出 6 条 cue", len(cues2) == 6, len(cues2))

    labels2, sizes2 = SV.cluster_cues(pcm2, cues2, enc)
    check("聚出 3 个说话人簇", len(sizes2) == 3, sizes2)
    check("过短 cue 不参与聚类（标 -1）", labels2[5] == -1, labels2)
    check("同说话人落同一簇",
          labels2[0] == labels2[2] and labels2[1] == labels2[4]
          and labels2[0] != labels2[1], labels2)
    check("聚类结果可复现（两次一致）",
          SV.cluster_cues(pcm2, cues2, enc)[0] == labels2)

    sc2 = SV.score_clusters(pcm2, cues2, labels2, tpl, enc)
    hit = [v for v in sc2.values() if abs(v["score"] - 1.0) < 1e-6]
    check("簇分：spk1 的簇命中模板 = 1.0", len(hit) == 1 and hit[0]["n"] == 2,
          sc2)
    check("簇分：其余簇 = 0",
          all(abs(v["score"]) < 1e-6 for v in sc2.values()
              if not abs(v["score"] - 1.0) < 1e-6), sc2)
    cue_scores2 = SV._labels_to_cue_scores(cues2, labels2, sc2)
    check("簇分摊回每条 cue（长度一致）", len(cue_scores2) == 6, len(cue_scores2))
    check("过短 cue 摊回 NaN",
          cue_scores2[5] != cue_scores2[5], cue_scores2[5])
    v2 = SV.decide(cues2, {}, 0.55, 0.45, cue_scores2)
    check("按簇判定：spk1 保留、其余丢弃/存疑",
          [st for _c, st, _s in v2] == ["keep", "drop", "keep", "drop",
                                        "drop", "review"],
          [st for _c, st, _s in v2])

    # ---------------- 5d) 两遍聚类：时长加权 + 歧义拒分 ----------------
    say("\n== 5d) 两遍聚类（预置向量的几何关系用例）==")

    def _unit(deg):
        v = np.zeros(SV.EMB_DIM, dtype=np.float32)
        v[0] = float(np.cos(np.radians(deg)))
        v[1] = float(np.sin(np.radians(deg)))
        return v

    class TableEncoder:
        """按波形峰值查表返回预置单位向量（构造特定几何关系的「假模型」）。"""

        def __init__(self, table):
            self.table = table            # {round(峰值×10): 向量}

        def embed(self, samples, sample_rate=16000):
            s = np.asarray(samples, dtype=np.float32).reshape(-1)
            if s.size == 0:
                raise SV.VoiceprintError("空音频")
            m = float(np.max(np.abs(s)))
            if m < 1e-6:
                raise SV.VoiceprintError("几乎无声")
            k = int(round(m * 10))
            if k not in self.table:
                raise SV.VoiceprintError("表外峰值 %d" % k)
            return self.table[k]

    def _tab_cues(plan, seconds):
        """按 (start, dur, level) 造 PCM + 无说话人标注的 SRT，返回 (pcm, cues)。"""
        buf = np.zeros(int(seconds * 16000), dtype=np.float32)
        rows = []
        for i, (st, du, lv) in enumerate(plan, 1):
            buf[int(st * 16000):int((st + du) * 16000)] = lv
            rows.append("%d\n%s --> %s\n第 %d 句\n"
                        % (i, _ts(st), _ts(st + du), i))
        d = SV.secore.SubtitleDoc()
        d.load_bytes("\n".join(rows).encode("utf-8"))
        return buf, list(d.cues)

    # 场景 1（时长加权）：A 长 cue 方向 0° + A 短 cue 方向 30°（同人抖动），
    # B 长 cue 方向 70°。等权簇心被 30° 短 cue 拖到 ~15°，B(70°) 余弦 0.57
    # 会被归进 A；√时长加权后簇心 ≈ 5.4°，B 余弦 0.43 自立 → A/B 正确分开。
    pcm_t1, cues_t1 = _tab_cues(
        [(0.0, 10.0, 0.10), (11.0, 0.5, 0.30), (12.5, 6.0, 0.70)], 20.0)
    lab_t1, sz_t1 = SV.cluster_cues(
        pcm_t1, cues_t1, TableEncoder({1: _unit(0), 3: _unit(30), 7: _unit(70)}))
    check("时长加权：A 的两条 cue 同簇", lab_t1[0] == lab_t1[1], lab_t1)
    check("时长加权：B 不被短 cue 拖进 A（簇心不被带偏）",
          lab_t1[2] != lab_t1[0], lab_t1)
    check("时长加权：恰成 2 簇", len(sz_t1) == 2, sz_t1)

    # 场景 2（歧义拒分）：X 方向 0°、W 方向 100°（差异极大），S 方向 51°
    # 卡在中间：与 X 余弦 0.629、与 W 余弦 0.656，差 0.027 < 裕量 0.04。
    # 旧贪心会把它归给 W（污染 W 的簇心与得分）；新算法自成一簇、单独打分。
    pcm_t2, cues_t2 = _tab_cues(
        [(0.0, 5.0, 0.50), (6.0, 5.0, 0.60), (12.0, 1.0, 0.20)], 14.0)
    enc_t2 = TableEncoder({5: _unit(0), 6: _unit(100), 2: _unit(51)})
    lab_t2, sz_t2 = SV.cluster_cues(pcm_t2, cues_t2, enc_t2)
    check("歧义拒分：中间 cue 自成一簇",
          lab_t2[2] != lab_t2[0] and lab_t2[2] != lab_t2[1], lab_t2)
    check("歧义拒分：恰成 3 簇", len(sz_t2) == 3, sz_t2)
    check("两遍聚类可复现（两次结果一致）",
          SV.cluster_cues(pcm_t2, cues_t2, enc_t2)[0] == lab_t2)
    check("出厂聚类参数：阈值 0.5 / 裕量 0.04 / 合并 0.6 / 权重指数 0.5",
          (SV.CLUSTER_THRESHOLD, SV.CLUSTER_ASSIGN_MARGIN,
           SV.CLUSTER_MERGE_THRESHOLD, SV.CLUSTER_LENGTH_WEIGHT)
          == (0.5, 0.04, 0.6, 0.5),
          (SV.CLUSTER_THRESHOLD, SV.CLUSTER_ASSIGN_MARGIN,
           SV.CLUSTER_MERGE_THRESHOLD, SV.CLUSTER_LENGTH_WEIGHT))

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

    # ---------------- 7b) 长音频分块推理（假会话） ----------------
    say("\n== 7b) 长音频分块推理（假会话，防 bad allocation 回归）==")

    class _RecSess:
        """假 onnx 会话：记录每次推理的帧数，输出由帧矩阵确定性导出。"""

        def __init__(self):
            self.calls = []

        def run(self, _out, feed):
            x = list(feed.values())[0]                 # (1, T, 80)
            self.calls.append(int(x.shape[1]))
            m = x[0].mean(axis=0)                      # (80,)
            return [np.tile(m, 3)[:SV.EMB_DIM][None, :]]

    def _rec_encoder(sess):
        e = SV.VoiceprintEncoder.__new__(SV.VoiceprintEncoder)
        e._sess, e._in = sess, "x"
        return e

    sig_long = np.tile(sig, 40)                        # 0.5s × 40 = 20 秒
    n_frames = SV.fbank(sig_long).shape[0]
    check("20 秒素材帧数 = 2000", n_frames == 2000, n_frames)
    old_mf = SV.EMBED_MAX_FRAMES
    try:
        SV.EMBED_MAX_FRAMES = 700                      # 7 秒/块
        rs = _RecSess()
        v = _rec_encoder(rs).embed(sig_long)
        check("长输入被分块：3 次推理，块界 700/700/600",
              rs.calls == [700, 700, 600], rs.calls)
        # 期望 = 对「整段减全局均值后」的各块分别过假会话、归一化、取均值再归一化
        # （预处理须与 embed() 内部一致：trim_silence 对恒定能量信号不剪、
        #   normalize_rms 对周期信号给恒定增益）
        feats = SV.fbank(SV.normalize_rms(SV.trim_silence(sig_long)))
        feats = feats - feats.mean(axis=0, keepdims=True)
        sub = []
        for s in range(0, feats.shape[0], 700):
            blk = np.asarray(rs.run(None, {"x": feats[s:s + 700][None]})[0][0],
                             dtype=np.float32)
            sub.append(blk / float(np.linalg.norm(blk)))
        exp = np.mean(np.stack(sub, axis=0), axis=0)
        exp = exp / float(np.linalg.norm(exp))
        check("分块结果 = 子向量均值再归一化（均值在分块**前**对整段减）",
              float(np.max(np.abs(v - exp))) < 1e-6,
              float(np.max(np.abs(v - exp))))
        check("结果 L2 归一化", abs(float(np.linalg.norm(v)) - 1.0) < 1e-5,
              float(np.linalg.norm(v)))
        rs2 = _RecSess()
        _rec_encoder(rs2).embed(sig)                   # 0.5 秒 = 50 帧 < 700
        check("短输入仍单次推理（行为不变）", rs2.calls == [50], rs2.calls)
    finally:
        SV.EMBED_MAX_FRAMES = old_mf
    check("出厂单次推理上限 = 6000 帧（60 秒 ≈ 150MB 封顶）",
          SV.EMBED_MAX_FRAMES == 6000, SV.EMBED_MAX_FRAMES)

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
            check("同段音频缩放后完全一致（RMS 归一化的作用）",
                  SV.cosine(e1, enc2.embed(sig2)) > 0.99999,
                  SV.cosine(e1, enc2.embed(sig2)))
            padded_sig = np.concatenate([np.zeros(16000, np.float32), sig,
                                         np.zeros(16000, np.float32)])
            c_pad = SV.cosine(e1, enc2.embed(padded_sig))
            # 阈值只定 0.9：0.5s 合成纯音是 CAM++ 的病态输入（训练域是语音），
            # 真实语音下的 padding 不变性以 build/_vp_accuracy_* 基准为准
            check("VAD：两侧 1s 静音 padding 后嵌入仍接近原版（余弦 > 0.9）",
                  c_pad > 0.9, c_pad)
            clicked = sig.copy()
            clicked[100:105] = 0.9
            c_clk = SV.cosine(e1, enc2.embed(clicked))
            check("VAD+RMS：0.9 爆音后嵌入仍接近原版（余弦 > 0.9）",
                  c_clk > 0.9, c_clk)
            other = np.random.RandomState(1).randn(16000).astype(np.float32) * 0.1
            check("与白噪声不相似（<0.5）", SV.cosine(e1, enc2.embed(other)) < 0.5,
                  SV.cosine(e1, enc2.embed(other)))
            check("过短音频抛 VoiceprintError",
                  _raises(SV.VoiceprintError, enc2.embed,
                          np.zeros(100, dtype=np.float32)))
            # 长输入分块与单跑的一致性（周期性内容下两种池化应几乎重合；
            # 240 秒单跑约需 0.5GB 内存，正是要防的 bad allocation 量级）
            per = np.tile(sig, 480)                    # 0.5s × 480 = 240 秒
            old_mf2 = SV.EMBED_MAX_FRAMES
            try:
                SV.EMBED_MAX_FRAMES = 10 ** 9
                e_full = enc2.embed(per)
                SV.EMBED_MAX_FRAMES = 6000
                e_chunk = enc2.embed(per)
            finally:
                SV.EMBED_MAX_FRAMES = old_mf2
            # 阈值定在 0.995/0.05：周期纯音上分块 vs 单跑的差异是 onnxruntime
            # 多线程数值噪声（峰值/RMS 预处理下同为 ~0.9995，见 build/
            # _vp_margin_check.py 真实语音验证），不是分块算法的系统性偏差。
            check("240 秒长音频：分块与单跑余弦 > 0.995",
                  SV.cosine(e_full, e_chunk) > 0.995,
                  SV.cosine(e_full, e_chunk))
            dev = abs(SV.cosine(e1, e_full) - SV.cosine(e1, e_chunk))
            check("分块对模板得分偏差 < 0.05（判定边际 0.13 内可接受）",
                  dev < 0.05, "%.5f" % dev)
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

    # ---------------- 声纹同步状态分类（2026-10-13 回归） ----------------
    # ⚠⚠ 曾有 bug：`voiceprint_sync.status()` 只看 `sync` 标记就把模板分成
    #   「同步副本 / 本地自录」，而**本人录入的模板经通道折叠回来后同样带**
    #   sync 标记（v1.19.0 的 backfill 就是先把本机老模板补传进通道，sync 时
    #   按 fp 序折叠、最后一条作者恰好是本机）。后果：开发版 3 个自己录的
    #   模板全被计成「同步副本」，状态显示「本地自录 0」——用户看到的就是
    #   「声纹数据数量不对」。
    #   正确口径与合并端 `_apply_upserts` 判「本地在野叶子」同源：
    #     · 无 sync 标记            ⇒ 本人录入
    #     · 有标记且 mix 含本机叶子  ⇒ 本人录入（绕通道一圈回来的）
    #     · 有标记且 sync_author 本机 ⇒ 本人录入
    #     · 其余                     ⇒ 他人同步
    try:
        import json as _json
        import voiceprint_sync as vps
        _me = "abcd1234-0000-0000-0000-000000000000"
        _other = "ffff9999-0000-0000-0000-000000000000"
        _tmp = tempfile.mkdtemp(prefix="vp_status_")
        _tpl = os.path.join(_tmp, "voiceprint")
        os.makedirs(_tpl, exist_ok=True)

        def _wt(name, obj):
            with open(os.path.join(_tpl, name + ".json"), "w",
                      encoding="utf-8") as fh:
                _json.dump(obj, fh, ensure_ascii=False)

        _b = {"dim": 192, "embedding": [0.0] * 192, "seconds": 1.0, "clips": 1}
        _leaf_mine = {"fp": "a", "v": [0.0] * 192, "w": 1.0, "n": 1, "author": _me[:8]}
        _leaf_other = {"fp": "b", "v": [0.0] * 192, "w": 1.0, "n": 1, "author": _other[:8]}
        _wt("mine_local", dict(_b, name="mine_local"))            # 本机自录、未进通道
        _wt("mine_roundtrip", dict(_b, name="mine_roundtrip", sync=True,
                                   sync_id="x1", sync_author=_me[:8],
                                   sync_ts="2026-10-13T00:00:00Z",
                                   mix=[dict(_leaf_mine)]))        # 本机录入绕通道一圈
        _wt("theirs", dict(_b, name="theirs", sync=True, sync_id="x2",
                           sync_author=_other[:8], mix=[dict(_leaf_other)]))
        _wt("mixed", dict(_b, name="mixed", sync=True, sync_id="x3",
                          sync_author=_other[:8],
                          mix=[dict(_leaf_other), dict(_leaf_mine)]))  # 含本机叶子
        with open(os.path.join(_tpl, "selection.json"), "w",
                  encoding="utf-8") as fh:
            _json.dump({"enabled": []}, fh)

        _orig = (vps.template_dir, vps.remote_root, vps._conflicts_path,
                 vps._pending_path, vps.config)
        vps.template_dir = lambda: _tpl
        vps.remote_root = lambda: os.path.join(_tmp, "no_remote")
        vps._conflicts_path = lambda: os.path.join(_tmp, "conflicts.json")
        vps._pending_path = lambda: os.path.join(_tmp, "pending.jsonl")
        vps.config = lambda: {"client_id": _me}
        try:
            s = vps.status()
        finally:
            (vps.template_dir, vps.remote_root, vps._conflicts_path,
             vps._pending_path, vps.config) = _orig
        shutil.rmtree(_tmp, ignore_errors=True)
        check("status 模板总数 = 4", s["templates"] == 4, s["templates"])
        check("status 他人同步只算 1（纯他人）", s["synced"] == 1, s["synced"])
        check("status 本人录入 = 3（自录/绕圈/含本机叶子）",
              s["local_only"] == 3, s["local_only"])
    except Exception as _e:  # noqa: BLE001
        check("status 分类回归", False, repr(_e))

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


def _ts(sec):
    """秒 -> SRT 时间戳（00:00:01,500）。"""
    h = int(sec // 3600)
    m = int(sec % 3600 // 60)
    s = sec % 60
    return ("%02d:%02d:%06.3f" % (h, m, s)).replace(".", ",")


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
