#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# @version 3.3.0
"""第二音色影子链路自检（WP2，离线：零真实模型、零网络、零 ffmpeg）。

覆盖：
  · second_voiceprint：开关默认 off / save 往返；SecondVoiceEncoder 模型缺失
    → BackendUnavailable；apply_feature_norm 两种减均值口径；对齐检查
    （mock 编码器，cos>=0.995 验收线 + 数量/维度守卫）与标记读写门；
  · run_shadow 门序：off → 对齐未过(off) → 模板缺第二路(degraded) →
    模型缺失(degraded) → 正常影子 → 缓存回放（零推理）；
  · filter_srt 接入（WP1 零回归口径）：off 时 res **键集与 WP1 逐键一致**
    且报告无第二音色内容；on 影子模式 verdict/decisions/speakers 与 off 完全
    一致、报告（除来源字幕文件名行）逐字节一致；异常 → degraded 摘要；
  · enroll_pcm 第二路顺手录入：models 命名空间 256 维向量、追加折叠、
    缺席静默跳过；save_template models 键守卫（坏结构剥掉、主向量不动）；
  · voiceprint_sync 域感知：leaf_fp（默认域=旧口径，其他域=sha256(model_id+vec)）、
    fold_leaves 按 (model_id, fp) 去重（旧输入逐字节兼容 + 同 fp 跨域不互斥 +
    全非默认域折叠）；apply_upserts 的 models 透传；
  · score_calibration 纯函数：percentile_rank / zscore / fit_platt（<200 禁用）
    / calibrate 退级 / fused_score（主路缺席 None、缺项重归一）/ 网格搜索 /
    apply_assist（默认影子 off；启用只 keep→review、永不 drop）。

运行：tools/python/python.exe src/_selftest_second_voiceprint.py
（环境：PYTHONPATH=src VT_NO_SYNC=1 VT_NO_VP_SYNC=1）
"""
import json
import math
import os
import shutil
import sys
import tempfile

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("VT_NO_PIPELINE", "1")
os.environ.setdefault("VT_NO_SYNC", "1")
os.environ.setdefault("VT_NO_VP_SYNC", "1")

import features.voiceprint.speaker_voiceprint as SV          # noqa: E402
import features.voiceprint.second_voiceprint as SV2          # noqa: E402
import features.voiceprint.score_calibration as SC           # noqa: E402
import features.voiceprint.voiceprint_sync as VPS            # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "data", "tmp", "dev_out", "_second_vp_test")
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


SR = SV.SAMPLE_RATE

# WP1 filter_srt 返回 dict 的**完整键集**（off 零漂移的验收口径：影子 off 时
# 一个键都不许多、一个键都不许少）。
WP1_RES_KEYS = {"out", "total", "keep", "review", "drop", "kept_total",
                "speakers", "threshold", "low", "threshold_source",
                "local_clusters", "templates", "mode", "review_path",
                "decisions", "decision", "review_reasons", "keep_ratio",
                "min_keep_ratio", "aborted", "kept_path"}


# ---------------------------------------------------------------- 假编码器

class FakeCamEncoder:
    """CAM++ 主路假编码器（192 维 one-hot，把 PCM 峰值当说话人编号）。
    与 WP1 自检的 FakeEncoder 同款——主路分数只有 1.0/0.0，可精确断言。"""

    def embed(self, samples, sample_rate=16000):
        s = np.asarray(samples, dtype=np.float32).reshape(-1)
        m = float(np.max(np.abs(s))) if s.size else 0.0
        if m < 1e-6:
            raise SV.VoiceprintError("几乎无声")
        v = np.zeros(SV.EMB_DIM, dtype=np.float32)
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


def _energy_jitter(v, samples):
    """小幅能量指纹扰动：同说话人、不同内容 -> 向量略异（fp 可分、
    方向几乎不变，cos≈0.9975 仍过同人守卫）。供追加折叠用例区分两个叶子。"""
    s = np.asarray(samples, dtype=np.float32).reshape(-1)
    tag = int(round(float(np.mean(np.abs(s))) * 1000)) % 97
    v = np.asarray(v, dtype=np.float32).copy()
    v[tag % v.size] += 0.05
    n = float(np.linalg.norm(v))
    return v / (n if n > 1e-9 else 1.0)


class FakeSecondEncoder:
    """第二路假编码器（256 维 one-hot，同口径），带调用计数供缓存断言。"""

    EMB_DIM = 256

    def __init__(self):
        self.calls = 0

    def embed(self, samples, sample_rate=16000):
        self.calls += 1
        s = np.asarray(samples, dtype=np.float32).reshape(-1)
        m = float(np.max(np.abs(s))) if s.size else 0.0
        if m < 1e-6:
            raise SV.VoiceprintError("几乎无声")
        v = np.zeros(self.EMB_DIM, dtype=np.float32)
        v[int(round(m * 10)) % self.EMB_DIM] = 1.0
        return v

    def embed_many(self, chunks, sample_rate=16000):
        out = []
        for c in chunks:
            try:
                out.append(self.embed(c, sample_rate))
            except SV.VoiceprintError:
                out.append(None)
        return out


class BrokenSecondEncoder:
    """构造即抛 BackendUnavailable——模拟「模型文件缺席」。"""

    def __init__(self, model_path=None):
        raise SV2.BackendUnavailable("第二路声纹模型缺失（自检注入）")


class JitCamEncoder(FakeCamEncoder):
    """带能量指纹扰动的 CAM++ 假编码器：同说话人不同片段 -> fp 可分。"""

    def embed(self, samples, sample_rate=16000):
        return _energy_jitter(super().embed(samples, sample_rate), samples)


class JitSecondEncoder(FakeSecondEncoder):
    """带能量指纹扰动的第二路假编码器（调用计数由父类维护）。"""

    def embed(self, samples, sample_rate=16000):
        return _energy_jitter(super().embed(samples, sample_rate), samples)


def clip_variant(seconds=1.5):
    """同一说话人（峰值 0.1）、不同能量指纹的内容（均值 0.09）。"""
    n = int(SR * seconds)
    x = np.full(n, 0.1, dtype=np.float32)
    x[:n // 2] = 0.08
    return x


def fake_pcm(spk_id, seconds=2.0):
    return np.full(int(SR * seconds), spk_id / 10.0, dtype=np.float32)


def onehot(dim, idx):
    v = np.zeros(dim, dtype=np.float32)
    v[idx % dim] = 1.0
    return v


class _Cue:
    """轻量 cue 桩（start/end 毫秒、speaker、num）。"""

    def __init__(self, start, end, speaker="", num=None, text=""):
        self.start, self.end = int(start), int(end)
        self.speaker = speaker
        self.num = num
        self.text = text


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


def _pcm_for_srt():
    """7 秒恒值 PCM：说话人1=0.1、说话人2=0.2、说话人3=0.3（峰值→one-hot）。"""
    pcm = np.zeros(7 * SR, dtype=np.float32)
    for lo, hi, val in ((1.0, 2.0, 0.1), (2.5, 3.5, 0.2),
                        (4.0, 5.0, 0.1), (5.5, 6.5, 0.3)):
        pcm[int(lo * SR):int(hi * SR)] = val
    return pcm


def main():
    say("=" * 62)
    say("  第二音色影子链路自检（second_voiceprint / score_calibration）")
    say("=" * 62)

    tmpdir = tempfile.mkdtemp(prefix="vt_vp2_")
    tpl_dir = os.path.join(tmpdir, "voiceprint")
    cache_dir = os.path.join(tmpdir, "shadow_cache")
    calib_dir = os.path.join(tmpdir, "calibration")
    os.makedirs(tpl_dir, exist_ok=True)
    os.environ["VT_VP_SHADOW_CACHE_DIR"] = cache_dir
    os.environ["VT_VP_CALIB_DIR"] = calib_dir
    old_tpl_dir, old_sel = SV.TEMPLATE_DIR, SV.SELECTION_PATH
    old_read_pcm = SV.read_pcm
    SV.TEMPLATE_DIR = tpl_dir
    SV.SELECTION_PATH = os.path.join(tpl_dir, "selection.json")
    pcm = _pcm_for_srt()
    SV.read_pcm = lambda src, **kw: pcm

    try:
        # ---------------- 1) 开关默认 off ----------------
        say("\n== 1) 第二音色开关（默认 off / 读-改-写）==")
        check("出厂默认 off（selection.json 无 second_voice 键）",
              SV2.second_voice_enabled() is False)
        check("save(True) 后读到 True",
              SV2.save_second_voice_enabled(True) is True
              and SV2.second_voice_enabled() is True)
        check("save(False) 后读到 False",
              SV2.save_second_voice_enabled(False) is False
              and SV2.second_voice_enabled() is False)
        with open(SV.SELECTION_PATH, encoding="utf-8") as fh:
            raw = json.load(fh)
        check("开关写盘只动自己的键（enabled/auto_filter 等未知键保留）",
              "second_voice" in raw and "updated" in raw, sorted(raw))

        # ---------------- 2) 编码器与预处理口径 ----------------
        say("\n== 2) SecondVoiceEncoder 与减均值口径 ==")
        try:
            SV2.SecondVoiceEncoder()
            _missing = False
        except SV2.BackendUnavailable:
            _missing = True
        check("模型缺失 -> BackendUnavailable（graceful degraded 的来源）",
              _missing)
        feats = np.array([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]], dtype=np.float32)
        g = SV2.apply_feature_norm(feats, "global-mean")
        check("global-mean 口径：整块减一个标量（CAM++ 元数据语义）",
              abs(float(g.mean())) < 1e-6
              and abs(float(g[0, 0]) - (1.0 - 3.5)) < 1e-6, g[0, 0])
        c = SV2.apply_feature_norm(feats, "1")
        check("CMN 口径（wespeaker 常见）：逐维减时间均值",
              float(np.max(np.abs(c.mean(axis=0)))) < 1e-6)
        c2 = SV2.apply_feature_norm(feats, None)
        check("元数据缺省按 CMN 走（不盲抄 CAM++）",
              float(np.max(np.abs(c2.mean(axis=0)))) < 1e-6)

        # ---------------- 3) 对齐检查（mock 参考向量） ----------------
        say("\n== 3) 前处理对齐检查架构（一次性沙箱口径）==")
        enc2 = FakeSecondEncoder()
        s_a = fake_pcm(1, 1.5)
        ref_ok = [enc2.embed(s_a)]
        r1 = SV2.check_preproc_alignment([s_a], ref_ok, encoder2=enc2)
        check("参考=本模块输出（理想对齐）-> ok 且 cos=1.0",
              r1["ok"] is True and r1["min_cos"] == 1.0, r1)
        r2 = SV2.check_preproc_alignment([s_a], [onehot(256, 9)],
                                         encoder2=enc2)
        check("参考向量无关 -> 不达标（cos 0 < 0.995）且带原因",
              r2["ok"] is False and r2["min_cos"] == 0.0
              and "验收线" in r2["reason"], r2["reason"])
        r3 = SV2.check_preproc_alignment([s_a], [], encoder2=enc2)
        check("数量不一致 -> ok=False（不猜）",
              r3["ok"] is False and "数量不一致" in r3["reason"], r3["reason"])
        check("对齐标记未写 -> alignment_ok()=False（off 的门）",
              SV2.alignment_ok() is False)
        check("save_alignment_result 落标记 + preproc 版本绑定",
              SV2.save_alignment_result(
                  {"ok": True, "min_cos": 1.0, "per_item": [1.0]})
              and SV2.alignment_ok() is True)
        st = SV2.load_alignment_state()
        check("标记带 model_id / preproc / checked",
              st and st.get("model_id") == SV2.MODEL_ID
              and st.get("preproc") == SV2.PREPROC_VERSION
              and bool(st.get("checked")), st)
        st2 = dict(st)
        st2["preproc"] = "fbank80-cmn@v0"
        SV2.save_alignment_result(st2)
        check("preproc 版本不一致 -> 对齐门失效（升版即重查）",
              SV2.alignment_ok() is False)
        SV2.save_alignment_result({"ok": True, "min_cos": 1.0})

        # ---------------- 4) enroll 第二路顺手录入 + models 命名空间 --------
        say("\n== 4) enroll_pcm 第二路（models 命名空间，加键不换锁）==")
        clips = [fake_pcm(1, 1.5)]
        r = SV.enroll_pcm(clips, name="影子主播", encoder=FakeCamEncoder(),
                          second_encoder=FakeSecondEncoder(),
                          source="demo.mp4")
        t = SV.load_template("影子主播")
        check("顶层 embedding 仍是 CAM++ 192 维主向量（锁不动）",
              len(t["embedding"]) == SV.EMB_DIM and
              np.allclose(np.asarray(t["embedding"]), onehot(SV.EMB_DIM, 1)))
        models = t.get("models") or {}
        entry = models.get(SV2.MODEL_ID)
        check("models 命名空间写入第二路（键 = MODEL_ID）",
              isinstance(entry, dict), sorted(models))
        check("第二路条目：dim=256 / 版本与 preproc / embedding 256 维",
              entry and entry.get("dim") == 256
              and entry.get("model_version") == SV2.MODEL_VERSION
              and entry.get("preproc_version") == SV2.PREPROC_VERSION
              and len(entry.get("embedding") or []) == 256,
              (entry or {}).get("dim"))
        check("第二路 mix 叶子带 model_id 域标记",
              entry and entry.get("mix")
              and entry["mix"][0].get("model_id") == SV2.MODEL_ID,
              (entry.get("mix") or [{}])[0] if entry else None)
        # 缺席：不注入第二路编码器且模型缺失 -> 无 models 键，录入照常
        r2 = SV.enroll_pcm([fake_pcm(1, 1.5)], name="纯CAM",
                           encoder=FakeCamEncoder(), source="demo.mp4")
        t2 = SV.load_template("纯CAM")
        check("第二路缺席 -> 无 models 键、录入不受阻（192 维主向量照写）",
              "models" not in t2 and len(t2["embedding"]) == SV.EMB_DIM)
        # 追加：第二路叶子与新叶子走同一 fold 数学路径。
        # ⚠ 直接调 enroll_pcm 时，追加语义由 `base=` 承载（append 旗标属于
        #   enroll/enroll_auto 包装层）；用内容不同但同人稳定的片段 + 扰动
        #   编码器——同内容片段的向量逐位相同、fp 相同，会被 fold 幂等去重
        #   （那也是正确行为）。
        enc_a = JitCamEncoder()
        enc_b = JitSecondEncoder()
        SV.enroll_pcm([fake_pcm(1, 1.5)], name="追加主播", encoder=enc_a,
                      second_encoder=enc_b, source="demo.mp4")
        base = SV.load_template("追加主播")
        r3 = SV.enroll_pcm([clip_variant(1.5)], name="追加主播", encoder=enc_a,
                           second_encoder=enc_b, base=base)
        t3 = SV.load_template("追加主播")
        entry3 = (t3.get("models") or {}).get(SV2.MODEL_ID) or {}
        check("追加后顶层 CAM++ mix 折叠为 2 叶",
              len(t3.get("mix") or []) == 2 and t3.get("clips") == 2,
              (len(t3.get("mix") or []), t3.get("clips")))
        check("追加后第二路 mix 同步折叠为 2 叶（同一数学路径）",
              len(entry3.get("mix") or []) == 2
              and entry3.get("clips") == 2,
              (len(entry3.get("mix") or []), entry3.get("clips")))
        check("追加后第二路叶子仍带域标记、顶层叶子不带",
              entry3.get("mix") and entry3["mix"][0].get("model_id")
              == SV2.MODEL_ID
              and "model_id" not in (t3.get("mix") or [{}])[0])
        # save_template 对坏 models 结构的守卫
        SV.save_template("坏键", onehot(SV.EMB_DIM, 1), models="垃圾字符串")
        t4 = SV.load_template("坏键")
        check("save_template models 坏结构整体剥掉",
              "models" not in t4 and len(t4["embedding"]) == SV.EMB_DIM)
        SV.save_template("坏键2", onehot(SV.EMB_DIM, 1),
                         models={"x": {"embedding": []}, "y": "也垃圾"})
        t5 = SV.load_template("坏键2")
        check("save_template 剥掉缺 embedding 的域条目",
              not (t5.get("models") or {}))

        # ---------------- 5) filter_srt 接入：off 零漂移 ----------------
        say("\n== 5) filter_srt off 零漂移（WP1 逐字节一致口径）==")
        srt_path = os.path.join(tmpdir, "in.srt")
        with open(srt_path, "w", encoding="utf-8") as fh:
            fh.write(SRT)
        out_off = os.path.join(tmpdir, "out_off.srt")
        res_off = SV.filter_srt("fake.mp4", srt_path, "影子主播", threshold=0.5,
                                low=0.35, out_path=out_off,
                                encoder=FakeCamEncoder())
        check("off：res 不出现 second_voice 键",
              "second_voice" not in res_off)
        check("off：res 键集与 WP1 完全一致（多一个/少一个都算漂移）",
              set(res_off.keys()) == WP1_RES_KEYS,
              set(res_off.keys()) ^ WP1_RES_KEYS)
        check("off：筛选结果正确（说话人1 两句保留、其余丢弃）",
              res_off["kept_total"] == 2 and res_off["drop"] == 2,
              (res_off["kept_total"], res_off["drop"]))
        rep_off = os.path.splitext(out_off)[0] + ".报告.txt"
        rep_off_text = open(rep_off, encoding="utf-8").read()
        check("off：报告无第二音色内容", "第二音色" not in rep_off_text
              and "second_voice" not in rep_off_text)

        # ---------------- 6) filter_srt 接入：on 影子不改 verdict ----------
        say("\n== 6) filter_srt on 影子：只记录、verdict 逐字不动 ==")
        SV2.save_second_voice_enabled(True)
        # filter_srt 不注入第二路编码器（真实接入走模型路径）；自检里把
        # SecondVoiceEncoder 换成假编码器工厂，模拟「模型已就位」。
        old_enc2 = SV2.SecondVoiceEncoder
        SV2.SecondVoiceEncoder = lambda model_path=None: FakeSecondEncoder()
        try:
            out_on1 = os.path.join(tmpdir, "out_on1.srt")
            res_on1 = SV.filter_srt("fake.mp4", srt_path, "影子主播",
                                    threshold=0.5, low=0.35, out_path=out_on1,
                                    encoder=FakeCamEncoder())
            # 缓存回放：同输入第二次 filter_srt 直接回放，verdict 仍不变
            out_on2 = os.path.join(tmpdir, "out_on2.srt")
            res_on2 = SV.filter_srt("fake.mp4", srt_path, "影子主播",
                                    threshold=0.5, low=0.35, out_path=out_on2,
                                    encoder=FakeCamEncoder())
        finally:
            SV2.SecondVoiceEncoder = old_enc2
        sv_res = res_on1.get("second_voice") or {}
        check("on：res 恰好多出 second_voice 一个键",
              set(res_on1.keys()) == WP1_RES_KEYS | {"second_voice"},
              set(res_on1.keys()) ^ (WP1_RES_KEYS | {"second_voice"}))
        check("on：影子状态 ok、mode=shadow、未走缓存",
              sv_res.get("status") == "ok" and sv_res.get("mode") == "shadow"
              and sv_res.get("cached") is False, sv_res.get("status"))
        check("on：trace schema / model_id / preproc 对齐",
              sv_res.get("schema") == SV2.TRACE_SCHEMA
              and sv_res.get("model_id") == SV2.MODEL_ID
              and sv_res.get("preproc") == SV2.PREPROC_VERSION)
        check("on：簇级影子打分按说话人标签分组（3 簇），target 命中主播=1.0",
              sv_res.get("n_clusters") == 3
              and abs((sv_res["clusters"].get("s:说话人1") or {})
                      .get("target") - 1.0) < 1e-9,
              sv_res.get("clusters"))
        check("on：影子 trace 记录启用模板名",
              sv_res.get("template_names") == ["影子主播"],
              sv_res.get("template_names"))
        check("on：影子缓存文件已落盘",
              any(f.endswith(".json") for f in os.listdir(cache_dir))
              if os.path.isdir(cache_dir) else False)

        def _verdict_fingerprint(res):
            return [(d.get("num"), d.get("state"), d.get("score"),
                     d.get("source")) for d in (res.get("decisions") or [])]

        check("on：verdict/decisions 与 off 逐字一致（影子不改判定）",
              _verdict_fingerprint(res_on1) == _verdict_fingerprint(res_off)
              and res_on1["keep"] == res_off["keep"]
              and res_on1["drop"] == res_off["drop"]
              and res_on1["review"] == res_off["review"])
        check("on：speakers 主路得分与 off 一致",
              res_on1["speakers"] == res_off["speakers"])
        sv_res2 = res_on2.get("second_voice") or {}
        check("on 二跑：缓存命中回放（cached=True），verdict 仍与 off 一致",
              sv_res2.get("cached") is True
              and sv_res2.get("status") == "ok"
              and _verdict_fingerprint(res_on2) == _verdict_fingerprint(res_off),
              sv_res2.get("cached"))
        rep_on1 = os.path.splitext(out_on1)[0] + ".报告.txt"
        rep_on1_text = open(rep_on1, encoding="utf-8").read()

        def _strip_src(text):
            return "\n".join(l for l in text.split("\n")
                             if not l.strip().startswith("来源字幕"))

        check("on：报告除「来源字幕」行外与 off 逐字节一致（影子不增删产物）",
              _strip_src(rep_on1_text) == _strip_src(rep_off_text))
        check("on：报告仍无第二音色内容",
              "第二音色" not in rep_on1_text
              and "second_voice" not in rep_on1_text)

        # ---------------- 7) 降级路径（模板缺第二路 / 模型缺失 / 对齐缺） ----
        say("\n== 7) run_shadow 降级门序 ==")
        out_dn = os.path.join(tmpdir, "out_dn.srt")
        res_dn = SV.filter_srt("fake.mp4", srt_path, "纯CAM", threshold=0.5,
                               low=0.35, out_path=out_dn,
                               encoder=FakeCamEncoder())
        sv_dn = res_dn.get("second_voice") or {}
        check("启用模板无第二路向量 -> degraded no_second_templates",
              sv_dn.get("status") == "degraded"
              and sv_dn.get("reason") == "no_second_templates",
              sv_dn.get("reason"))
        check("degraded 时 verdict 仍不变",
              _verdict_fingerprint(res_dn) == _verdict_fingerprint(res_off))
        old_enc = SV2.SecondVoiceEncoder
        SV2.SecondVoiceEncoder = BrokenSecondEncoder
        try:
            out_dm = os.path.join(tmpdir, "out_dm.srt")
            res_dm = SV.filter_srt("fake.mp4", srt_path, "影子主播", threshold=0.5,
                                   low=0.35, out_path=out_dm,
                                   encoder=FakeCamEncoder())
            sv_dm = res_dm.get("second_voice") or {}
            check("模型缺失（缓存也拦不住）-> degraded model_missing",
                  sv_dm.get("status") == "degraded"
                  and str(sv_dm.get("reason")).startswith("model_missing"),
                  sv_dm.get("reason"))
            check("模型缺失时 verdict 仍不变",
                  _verdict_fingerprint(res_dm)
                  == _verdict_fingerprint(res_off))
        finally:
            SV2.SecondVoiceEncoder = old_enc
        # 对齐标记缺失 -> off（不是 degraded：未验收的链路不该跑）
        mark = SV2.alignment_state_path()
        bak = open(mark, encoding="utf-8").read() if os.path.isfile(mark) \
            else None
        if os.path.isfile(mark):
            os.remove(mark)
        try:
            out_al = os.path.join(tmpdir, "out_al.srt")
            res_al = SV.filter_srt("fake.mp4", srt_path, "影子主播", threshold=0.5,
                                   low=0.35, out_path=out_al,
                                   encoder=FakeCamEncoder())
            sv_al = res_al.get("second_voice") or {}
            check("对齐标记缺失 -> off + preproc_alignment_pending",
                  sv_al.get("status") == "off"
                  and sv_al.get("reason") == "preproc_alignment_pending",
                  sv_al.get("reason"))
            check("对齐未过时 verdict 仍不变",
                  _verdict_fingerprint(res_al)
                  == _verdict_fingerprint(res_off))
        finally:
            if bak is not None:
                with open(mark, "w", encoding="utf-8") as fh:
                    fh.write(bak)
        SV2.save_second_voice_enabled(False)
        out_off2 = os.path.join(tmpdir, "out_off2.srt")
        res_off2 = SV.filter_srt("fake.mp4", srt_path, "影子主播", threshold=0.5,
                                 low=0.35, out_path=out_off2,
                                 encoder=FakeCamEncoder())
        check("on 再切回 off：res 恢复 WP1 键集（无 second_voice）",
              "second_voice" not in res_off2
              and set(res_off2.keys()) == WP1_RES_KEYS)

        # ---------------- 8) run_shadow 直调：缓存零推理 / 逐条兜底 --------
        say("\n== 8) run_shadow 直调（缓存回放零推理 / review cue 兜底）==")
        SV2.save_second_voice_enabled(True)

        def _clear_trace_cache():
            """清掉 trace 缓存（保留对齐标记）——各用例要独立的「首跑」。"""
            if os.path.isdir(cache_dir):
                for f in os.listdir(cache_dir):
                    if f.endswith(".json") and not f.startswith("alignment_"):
                        os.remove(os.path.join(cache_dir, f))

        _clear_trace_cache()
        SV2.save_alignment_result({"ok": True, "min_cos": 1.0})
        cues = [_Cue(1000, 2000, "说话人1", 1), _Cue(2500, 3500, "说话人2", 2),
                _Cue(4000, 5000, "说话人1", 3)]
        labels = [-1, -1, -1]
        decisions = [{"num": 1, "state": "keep", "score": 1.0},
                     {"num": 2, "state": "review", "score": 0.5},
                     {"num": 3, "state": "keep", "score": 1.0}]
        e_cnt = FakeSecondEncoder()
        s1 = SV2.run_shadow("fake.mp4", pcm, cues, labels, None, decisions,
                            ["影子主播"], encoder2=e_cnt)
        n_first = e_cnt.calls
        check("直调影子 ok：2 簇（无标签走说话人分组）+ 1 条 review 兜底",
              s1["status"] == "ok" and s1["n_clusters"] == 2
              and s1["n_cues"] == 1, (s1["n_clusters"], s1["n_cues"]))
        check("review cue 兜底记录了 index/num/target",
              s1["cues"] and s1["cues"][0]["index"] == 1
              and s1["cues"][0]["num"] == 2
              and s1["cues"][0]["target"] is not None, s1["cues"])
        e_cnt2 = FakeSecondEncoder()
        s2 = SV2.run_shadow("fake.mp4", pcm, cues, labels, None, decisions,
                            ["影子主播"], encoder2=e_cnt2)
        check("缓存回放：cached=True、cluster/cue 内容一致、零推理",
              s2["cached"] is True and s2["status"] == "ok"
              and s2["clusters"] == s1["clusters"]
              and s2["cues"] == s1["cues"] and e_cnt2.calls == 0,
              (e_cnt2.calls, e_cnt2.calls != 0))
        check("首跑确实发生过推理（缓存命中的对照面）", n_first > 0, n_first)
        SV2.save_second_voice_enabled(False)
        s3 = SV2.run_shadow("fake.mp4", pcm, cues, labels, None, decisions,
                            ["影子主播"], encoder2=FakeSecondEncoder())
        check("开关 off 直调 -> off + second_voice_disabled（防呆）",
              s3["status"] == "off"
              and s3["reason"] == "second_voice_disabled", s3["reason"])

        # ---------------- 9) 竞争者底噪池 + 校准建档联动 ----------------
        say("\n== 9) 竞争者底噪池与校准建档 ==")
        SV.enroll_pcm([fake_pcm(5, 1.5)], name="路人甲",
                      encoder=FakeCamEncoder(), second_encoder=enc2,
                      source="demo.mp4")
        SV2.save_second_voice_enabled(True)
        SV2.save_alignment_result({"ok": True, "min_cos": 1.0})
        _clear_trace_cache()          # 路人甲入池后重新首跑，底噪池才算数
        e_cmp = FakeSecondEncoder()
        s4 = SV2.run_shadow("fake2.mp4", pcm, cues, labels, None, decisions,
                            ["影子主播"], encoder2=e_cmp)
        row = (s4.get("clusters") or {}).get("s:说话人1") or {}
        check("非启用模板进底噪池：competitors 记录、margin=target-comp",
              row.get("competitors") is not None
              and row.get("margin") is not None
              and abs(row["margin"] - (row["target"] - row["competitors"]))
              < 1e-6, row)
        cal_file = os.path.join(calib_dir, SV2.MODEL_ID + ".json")
        check("簇级 (target, competitor) 已进校准建档（影子期累积）",
              os.path.isfile(cal_file))
        stats = SC.load_stats(SV2.MODEL_ID)
        n_t = sum(len(b.get("target") or []) for b in stats.values())
        n_c = sum(len(b.get("competitor") or []) for b in stats.values())
        check("建档：target 与 competitor 成对累积", n_t >= 1 and n_c >= 1,
              (n_t, n_c))
        SV2.save_second_voice_enabled(False)

        # ---------------- 10) score_calibration 纯函数 ----------------
        say("\n== 10) score_calibration 纯函数 ==")
        pool = [0.1, 0.2, 0.3]
        check("percentile_rank：低于全部=0 / 高于全部=1 / 中间=占比",
              SC.percentile_rank(0.05, pool) == 0.0
              and SC.percentile_rank(0.9, pool) == 1.0
              and abs(SC.percentile_rank(0.15, pool) - 1.0 / 3.0) < 1e-9)
        check("percentile_rank：并列值不给自己加分（严格小于口径）",
              abs(SC.percentile_rank(0.3, pool) - 2.0 / 3.0) < 1e-9)
        check("percentile_rank：空池/NaN -> 0.5 中性",
              SC.percentile_rank(0.5, []) == 0.5
              and SC.percentile_rank(float("nan"), pool) == 0.5)
        check("zscore：零方差池 -> 0.0；NaN -> None",
              SC.zscore(0.5, [1.0, 1.0, 1.0]) == 0.0
              and SC.zscore(float("nan"), pool) is None)
        check("zscore：正态口径下 x=均值+1σ -> 1.0",
              abs(SC.zscore(2.0 + math.sqrt(2.0 / 3.0), [1.0, 2.0, 3.0])
                  - 1.0) < 1e-9)
        rng = np.random.RandomState(11)
        xs = list(rng.uniform(0.0, 1.0, 300))
        ys = [1 if x > 0.5 else 0 for x in xs]
        ab = SC.fit_platt(xs, ys)
        check("fit_platt：可分数据拟合并两端极化",
              ab is not None and SC.platt_apply(0.95, ab) > 0.9
              and SC.platt_apply(0.05, ab) < 0.1, ab)
        check("fit_platt：样本<200 禁用（退回分位）",
              SC.fit_platt(xs[:150], ys[:150]) is None)
        check("fit_platt：单一类禁用",
              SC.fit_platt(xs, [1] * 300) is None)
        rr = SC.record(SV2.MODEL_ID, "fp_demo", "zh", 0.8, 0.2)
        rr2 = SC.record(SV2.MODEL_ID, "fp_demo", "zh", 0.7, 0.3, label=True)
        stats = SC.load_stats(SV2.MODEL_ID)
        b = stats.get(SC.key_of("fp_demo", "zh")) or {}
        check("record/load_stats 往返：2 条 target、margin 现算、label 入档",
              rr and rr2 and len(b.get("target") or []) == 2
              and b.get("margin") == [0.6, 0.4]
              and b.get("labels") == [1],
              (b.get("target"), b.get("margin"), b.get("labels")))
        check("record：NaN target 拒收", SC.record(SV2.MODEL_ID, "fp_demo",
                                                  "zh", float("nan"), 0.1)
              is False)
        cal = SC.calibrate(SV2.MODEL_ID, "fp_demo", "zh", 0.85)
        check("calibrate auto：底噪池分位（0.85 高于全部 competitor -> 1.0）",
              cal["method"] == "percentile" and cal["score"] == 1.0, cal)
        cal2 = SC.calibrate(SV2.MODEL_ID, "fp_none", "zh", 0.5)
        check("calibrate：完全无数据 -> method=none 且 score=None（不臆造）",
              cal2["method"] == "none" and cal2["score"] is None, cal2)
        cal3 = SC.calibrate(SV2.MODEL_ID, "fp_demo", "zh", 0.8, method="platt")
        check("calibrate platt：样本不足退回/禁用（disabled_reason）",
              cal3["method"] in ("none", "percentile")
              and bool(cal3.get("disabled_reason")), cal3)
        f1 = SC.fused_score(0.8, 0.6, None, w=(0.7, 0.3, 0.0))
        check("fused_score：线性加权 0.7*0.8+0.3*0.6=0.74",
              abs(f1 - 0.74) < 1e-9, f1)
        f2 = SC.fused_score(0.8, None, None, w=(0.7, 0.3, 0.0))
        check("fused_score：第二路缺项 -> 剩余权重重归一（=0.8）",
              abs(f2 - 0.8) < 1e-9, f2)
        check("fused_score：主路缺席 -> None（无判定资格）",
              SC.fused_score(None, 0.6, None) is None
              and SC.fused_score(float("nan"), 0.6, None) is None)
        check("fused_score：全空 -> None",
              SC.fused_score(None, None, None) is None)
        rows = [(0.9, 0.85, None, True), (0.3, 0.2, None, False),
                (0.8, 0.7, None, True), (0.25, 0.3, None, False)]
        gs = SC.grid_search_fused(rows)
        check("grid_search_fused：返回按分离度降序、权重三元组",
              gs and gs[0][2] == 4 and all(len(w) == 3 for w, _s, _n in gs)
              and all(gs[i][1] >= gs[i + 1][1] for i in range(len(gs) - 1)),
              gs[:3])
        # apply_assist：默认影子不启用
        c1, c2_, c3_ = _Cue(0, 1000), _Cue(1000, 2000), _Cue(2000, 3000)
        dec = [(c1, "keep", 0.9), (c2_, "drop", 0.1), (c3_, "review", None)]
        out_ne, sum_ne = SC.apply_assist(dec, [0.0, 0.0, 0.0], enabled=False)
        check("apply_assist 默认影子：verdict 原样、disabled_reason=shadow_only",
              out_ne == dec and sum_ne["applied"] == 0
              and sum_ne["disabled_reason"] == "shadow_only", sum_ne)
        out_as, sum_as = SC.apply_assist(
            dec, [0.10, 0.40, None], enabled=True, threshold=0.55, low=0.45,
            assist_margin=0.10)
        check("apply_assist：真冲突 keep→review（reason 固定字符串）",
              out_as[0][1] == "review" and out_as[1][1] == "drop"
              and out_as[2][1] == "review" and sum_as["applied"] == 1
              and sum_as["reason"] == "second_voice_conflict",
              (sum_as, [r[1] for r in out_as]))
        check("apply_assist：永不产生新 drop（降级只到 review）",
              all(new[1] != "drop" or orig[1] == "drop"
                  for orig, new in zip(dec, out_as)))
        out_fus, sum_fus = SC.apply_assist(
            [(c1, "keep", 0.9)], [None], enabled=True, threshold=0.55,
            low=0.45, fused=[0.20])
        check("apply_assist：第二路缺席时可用融合分触发（fused 路径）",
              out_fus[0][1] == "review" and sum_fus["applied"] == 1, sum_fus)

        # ---------------- 11) sync 域感知（fp / fold / 落地透传） ----------
        say("\n== 11) voiceprint_sync 域感知 ==")
        v = [0.5, 0.25, 0.125]
        check("leaf_fp：默认域沿用旧口径 embedding_fp（绝不改）",
              VPS.leaf_fp(None, v) == VPS.embedding_fp(v)
              and VPS.leaf_fp(VPS.DEFAULT_MODEL_ID, v) == VPS.embedding_fp(v))
        fp2 = VPS.leaf_fp(SV2.MODEL_ID, v)
        import hashlib as _hl
        expect = _hl.sha256((SV2.MODEL_ID + "|" + json.dumps(
            [round(float(x), 6) for x in v])).encode("utf-8")).hexdigest()[:16]
        check("leaf_fp：第二路域 = sha256(model_id+vec) 前 16 位",
              fp2 == expect and fp2 != VPS.embedding_fp(v), fp2)
        # 旧口径逐字节兼容：两叶折叠结果与旧实现数学一致（同人守卫放行
        # cos=0.6 ≥ 0.55 的同方向叶子；正交叶会被守卫拒——那是旧语义）。
        la = {"fp": "a", "v": [1.0, 0.0], "w": 1.0, "n": 1, "author": "x"}
        lb = {"fp": "b", "v": [0.6, 0.8], "w": 2.0, "n": 1, "author": "y"}
        obj, rej = VPS.fold_leaves([la, lb])
        _s = [1.0 * 1.0 + 2.0 * 0.6, 1.0 * 0.0 + 2.0 * 0.8]
        _r = math.sqrt(_s[0] ** 2 + _s[1] ** 2)
        _emb = [round(x / _r, 6) for x in _s]
        check("fold 旧口径逐字节兼容：embedding/weight/clips/consistency/sources",
              obj["embedding"] == _emb
              and obj["weight"] == round(_r, 6) and obj["clips"] == 2
              and obj.get("consistency") == 0.6
              and obj["sources"] == ["x", "y"]
              and set(obj["mix"][0].keys()) == {"fp", "v", "w", "n", "author"}
              and "models" not in obj, obj)
        obj1, _ = VPS.fold_leaves([{"fp": "a", "v": [0.5, 0.5], "w": 1.5,
                                    "n": 2, "author": ""}])
        check("fold 单叶透传（不重归一化）",
              obj1["embedding"] == [0.5, 0.5] and obj1["weight"] == 1.5
              and obj1["clips"] == 2 and "consistency" not in obj1, obj1)
        check("fold 同 fp 同域去重",
              len(VPS.fold_leaves([la, dict(la)])[0]["mix"]) == 1)
        # 同 fp 跨域不互斥
        lx = {"fp": "z", "v": [1.0, 0.0], "w": 1.0, "n": 1, "author": ""}
        ly = {"fp": "z", "v": [1.0, 0.0], "w": 1.0, "n": 1, "author": "",
              "model_id": SV2.MODEL_ID}
        objz, _ = VPS.fold_leaves([lx, ly])
        check("fold 按 (model_id, fp) 去重：同 fp 跨域两存",
              objz is not None and len(objz["mix"]) == 1
              and isinstance(objz.get("models"), dict)
              and SV2.MODEL_ID in objz["models"]
              and objz["models"][SV2.MODEL_ID]["mix"][0]["fp"] == "z", objz)
        # 全非默认域折叠（第二路命名空间的追加路径）
        lm1 = {"fp": "m1", "v": onehot(256, 1).tolist(), "w": 1.0, "n": 1,
               "author": "x", "model_id": SV2.MODEL_ID}
        lm2 = {"fp": "m2", "v": onehot(256, 1).tolist(), "w": 1.0, "n": 1,
               "author": "y", "model_id": SV2.MODEL_ID}
        objs, rejs = VPS.fold_leaves([lm1, lm2])
        check("全非默认域：obj 本体带 model_id、256 维聚合、叶子带域标记",
              objs is not None and objs.get("model_id") == SV2.MODEL_ID
              and len(objs["embedding"]) == 256
              and objs["mix"][0].get("model_id") == SV2.MODEL_ID
              and objs["sources"] == ["x", "y"], objs.get("model_id"))
        check("全非默认域：同人守卫照常（异人叶被拒）",
              VPS.fold_leaves([lm1, {"fp": "m9", "v": onehot(256, 77).tolist(),
                                     "w": 1.0, "n": 1, "author": "q",
                                     "model_id": SV2.MODEL_ID}])[1] != [])
        # template_leaves 域参数
        tl0 = VPS.template_leaves({"mix": [dict(la)]})
        check("template_leaves 缺省读顶层（CAM++ 域，叶子无 model_id 键）",
              len(tl0) == 1 and "model_id" not in tl0[0]
              and tl0[0]["fp"] == "a")
        tl1 = VPS.template_leaves(t, model_id=SV2.MODEL_ID)
        check("template_leaves(model_id=) 读 models 命名空间（256 维 + 域标记）",
              len(tl1) == 1 and tl1[0].get("model_id") == SV2.MODEL_ID
              and len(tl1[0]["v"]) == 256, (len(tl1), len(tl1[0]["v"])))
        tl1b = VPS.template_leaves(t3, model_id=SV2.MODEL_ID)
        check("template_leaves：追加主播的第二路命名空间读到 2 叶",
              len(tl1b) == 2, len(tl1b))
        tl2 = VPS.template_leaves(t2, model_id=SV2.MODEL_ID)
        check("template_leaves：命名空间缺席返回空（不臆造叶子）", tl2 == [])
        # apply_upserts 的 models 透传
        _orig_tpl = (VPS.template_dir, VPS.config)
        VPS.template_dir = lambda: tpl_dir
        VPS.config = lambda: {"client_id": "abcdef12-0000"}
        try:
            name = "透传测试"
            entry_t = (t.get("models") or {}).get(SV2.MODEL_ID) or {}
            val = json.dumps({"name": name, "dim": SV.EMB_DIM,
                              "embedding": [float(x) for x in
                                            np.asarray(t["embedding"])
                                            .reshape(-1)],
                              "weight": t.get("weight") or 1.0,
                              "clips": t.get("clips") or 1,
                              "mix": t.get("mix") or [],
                              "models": {SV2.MODEL_ID: entry_t}},
                             ensure_ascii=False)
            es = [VPS.make_entry("abcdef12", name, "upsert", val)]
            n_act, _conf = VPS.apply_upserts(name, es)
            landed = SV.load_template(name)
            got = (landed.get("models") or {}).get(SV2.MODEL_ID) or {}
            check("落地透传：远端 value 的 models 命名空间不丢失",
                  n_act == 1 and got.get("dim") == 256
                  and len(got.get("embedding") or []) == 256,
                  sorted(landed.get("models") or {}))
            check("落地后顶层仍是 CAM++ 主向量（fold 语义不变）",
                  len(landed["embedding"]) == SV.EMB_DIM)
        finally:
            VPS.template_dir, VPS.config = _orig_tpl

        # ---------------- 12) run_shadow 防御性（永不抛出） ---------------
        say("\n== 12) run_shadow 防御性 ==")
        SV2.save_second_voice_enabled(True)
        SV2.save_alignment_result({"ok": True, "min_cos": 1.0})
        s_bad = SV2.run_shadow("fake.mp4", None, cues, labels, None, None,
                               ["影子主播"], encoder2=FakeSecondEncoder())
        check("pcm=None 等脏输入 -> degraded 摘要而非异常",
              s_bad.get("status") == "degraded"
              and bool(s_bad.get("reason")), s_bad.get("status"))
        s_bad2 = SV2.run_shadow("fake.mp4", pcm, cues, labels, None, None,
                                ["不存在的模板"], encoder2=FakeSecondEncoder())
        check("启用名单无有效模板 -> degraded no_second_templates",
              s_bad2.get("status") == "degraded"
              and s_bad2.get("reason") == "no_second_templates",
              s_bad2.get("reason"))
        SV2.save_second_voice_enabled(False)

    finally:
        SV.TEMPLATE_DIR, SV.SELECTION_PATH = old_tpl_dir, old_sel
        SV.read_pcm = old_read_pcm
        os.environ.pop("VT_VP_SHADOW_CACHE_DIR", None)
        os.environ.pop("VT_VP_CALIB_DIR", None)
        shutil.rmtree(tmpdir, ignore_errors=True)

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


if __name__ == "__main__":
    sys.exit(main())
