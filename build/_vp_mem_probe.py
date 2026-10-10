# @version 1.19.0
# 复现「声纹筛选 bad allocation」：CAM++ 单次推理内存随输入时长 T 的变化。
# 用法：tools/python/python.exe build/_vp_mem_probe.py <秒数>
import os
import sys
import time

import numpy as np
import onnxruntime as ort
import psutil

MP = os.path.join("tools", "asr_model",
                  "3dspeaker_speech_campplus_sv_zh-cn_16k-common.onnx")

dur = float(sys.argv[1])
T = int(dur * 100)          # 100 帧/秒（16k 采样、10ms 帧移）

so = ort.SessionOptions()
so.log_severity_level = 3
so.intra_op_num_threads = max(1, min(4, (os.cpu_count() or 2)))
sess = ort.InferenceSession(MP, sess_options=so,
                            providers=["CPUExecutionProvider"])
name = sess.get_inputs()[0].name
print("input shape:", sess.get_inputs()[0].shape)

proc = psutil.Process()
base = proc.memory_info().rss
rng = np.random.default_rng(0)
x = rng.standard_normal((1, T, 80), dtype=np.float32)
t0 = time.time()
try:
    y = sess.run(None, {name: x})[0]
    ok = True
    err = ""
except Exception as e:  # noqa: BLE001
    ok = False
    err = str(e)[:160]
    y = None
peak = proc.memory_info().rss
dt = time.time() - t0
print("dur=%.0fs T=%d ok=%s rss_delta=%.0fMB time=%.1fs %s"
      % (dur, T, ok, (peak - base) / 1e6, dt, err))
