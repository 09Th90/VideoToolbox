# @version 1.18.3
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
os.environ.setdefault("VT_NO_PIPELINE", "1"); os.environ.setdefault("VT_NO_SYNC", "1")
import glob, wave
import numpy as np, psutil
import speaker_voiceprint as SV

mf = int(sys.argv[1])
SV.EMBED_MAX_FRAMES = mf
base = os.path.join("history", "_cleanup_20261008", "outputs",
                    "arknights_endfield", "_audio_probe")
parts = []
for p in sorted(glob.glob(os.path.join(base, "_clip_[0-9]*.wav")))[:8]:
    with wave.open(p, "rb") as w:
        raw = w.readframes(w.getnframes()); ch = w.getnchannels()
    x = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if ch > 1: x = x.reshape(-1, ch).mean(axis=1)
    parts.append(x)
huge = np.tile(np.concatenate(parts).astype(np.float32), 5)  # ~647 秒
enc = SV.VoiceprintEncoder()
proc = psutil.Process(); base_rss = proc.memory_info().rss
enc.embed(huge)
print("max_frames=%d  dur=%.0fs  peak rss delta=%.0fMB"
      % (mf, len(huge)/16000.0, (proc.memory_info().rss - base_rss)/1e6))
