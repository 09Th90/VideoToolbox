# 同人/异人余弦 + 分块对判定边际的影响（真实语音）。
# 用法：tools/python/python.exe build/_vp_margin_check.py
import glob
import os
import sys
import wave

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
os.environ.setdefault("VT_NO_PIPELINE", "1")
os.environ.setdefault("VT_NO_SYNC", "1")
import speaker_voiceprint as SV  # noqa: E402


def read_wav(p):
    with wave.open(p, "rb") as w:
        n = w.getnframes()
        sw = w.getsampwidth()
        ch = w.getnchannels()
        raw = w.readframes(n)
    x = np.frombuffer(raw, dtype=np.int16 if sw == 2 else np.uint8)
    x = ((x.astype(np.float32) - 128.0) / 128.0 if sw == 1
         else x.astype(np.float32) / 32768.0)
    if ch > 1:
        x = x.reshape(-1, ch).mean(axis=1)
    return x


def emax(enc, pcm, mf):
    old = SV.EMBED_MAX_FRAMES
    SV.EMBED_MAX_FRAMES = mf
    try:
        return enc.embed(pcm)
    finally:
        SV.EMBED_MAX_FRAMES = old


enc = SV.VoiceprintEncoder()
base = os.path.join("history", "_cleanup_20261008", "outputs",
                    "arknights_endfield", "_audio_probe")
# 只取足 30 秒的整段（短段多为音效/静默）
clips = {}
for p in sorted(glob.glob(os.path.join(base, "_clip_*.wav"))):
    x = read_wav(p)
    if len(x) >= 30 * 16000 - 100:
        clips[os.path.basename(p)] = x.astype(np.float32)
names = sorted(clips)
print("30s clips:", names)

embs = {n: enc.embed(clips[n]) for n in names}
print("\npairwise cosine:")
for i in range(len(names)):
    row = []
    for j in range(len(names)):
        row.append("%5.3f" % SV.cosine(embs[names[i]], embs[names[j]]))
    print("  %-14s %s" % (names[i], " ".join(row)))

# 找最相似的一对（视作同人）和最不相似的（异人）
best, worst = None, None
for i in range(len(names)):
    for j in range(i + 1, len(names)):
        c = SV.cosine(embs[names[i]], embs[names[j]])
        if best is None or c > best[0]:
            best = (c, names[i], names[j])
        if worst is None or c < worst[0]:
            worst = (c, names[i], names[j])
print("\n最相似对（同人候选）: %.3f  %s vs %s" % best)
print("最不相似对（异人候选）: %.3f  %s vs %s" % worst)

# 同人长轨：同人候选两段互拼 + 复制 => 240 秒；模板 = 第一段的前 20 秒
c, n1, n2 = best
tpl = enc.embed(clips[n1][:20 * 16000])
long_same = np.tile(np.concatenate([clips[n1], clips[n2]]), 4)
print("\n同人长轨 %.0f 秒（模板 = %s 前 20 秒）" % (len(long_same) / 16000.0, n1))
for mf in (10 ** 9, 6000, 3000):
    e = emax(enc, long_same, mf)
    print("  max_frames=%9s : cosine(模板, 长轨) = %.4f" % (mf, SV.cosine(tpl, e)))

# 异人对照：异人候选音频拼成的长轨
c2, m1, m2 = worst
long_diff = np.tile(clips[m1], 8)
for mf in (10 ** 9, 6000):
    e = emax(enc, long_diff, mf)
    print("  异人 max_frames=%9s : cosine(模板, 长轨) = %.4f"
          % (mf, SV.cosine(tpl, e)))
