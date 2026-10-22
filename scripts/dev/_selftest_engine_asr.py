# @version 2.5.4
"""自检：engine_asr 与第三方引擎 ASR 链路的逐行为兼容性。

P2 接缝验收脚本。ASR 是**唯一会产生费用且会产出最终字幕**的链路，因此判据
不能是「能跑通」，而必须逐行为一致：

**A 组：契约与缓存**（离线）
  · CRC32 缓存键（用**内容**而非路径 ⇒ 改名仍命中）；
  · ``WhisperAPI`` 子键形式 ``crc32-model-language-prompt``；
  · ``FasterWhisperASR`` 子键形式 ``crc32-md5(cmd)``；
  · 缓存键前缀 ``类名:``、expire 2 天；
  · 音频格式校验与异常类型；幻觉文本过滤；ASRStatus 百分比。

**B 组：分块合并算法**（离线，最关键）
  用构造的「两块重叠语音」场景，与引擎 ``ChunkMerger`` **逐段比对**
  ``(text, start_time, end_time)``：中点切分位置、词级精确匹配、
  句级模糊匹配、无匹配时的时间边界切分、offset 推断。

**C 组：HTTP 传输**（离线）
  对本地假 HTTP 服务验证：multipart 字段名、Authorization 头、
  空语言不传、错误响应抛异常且不返回空 dict。

结构
----
正向：A + B + C。
负向：故意弄坏，确认检查**确实能抓到**。

用法
----
    python scripts/dev/_selftest_engine_asr.py

退出码 0 = 通过。
"""

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
SRC = os.path.join(ROOT, "src")

PYPARSE = os.path.join(ROOT, "tools", "python", "python.exe")
if not os.path.exists(PYPARSE):
    PYPARSE = sys.executable


def _run(code, extra_env=None):
    env = dict(os.environ)
    env["PYTHONPATH"] = SRC + os.pathsep + env.get("PYTHONPATH", "")
    if extra_env:
        env.update(extra_env)
    p = subprocess.run([PYPARSE, "-c", code], env=env,
                       capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


# ================================================================ A 契约
def positive_contract():
    code = r'''
import sys, os, zlib, tempfile
from engine_asr import BaseASR, WhisperAPI, ASRStatus, ASR_CACHE_EXPIRE
from engine_asr_local import (FasterWhisperASR, HALLUCINATION_KEYWORDS,
                              is_rtx_50_series)

fails = []
def chk(name, cond, detail=""):
    if cond:
        print("OK  ", name)
    else:
        fails.append(name); print("FAIL", name, detail)

# ---------- 假音频（无需真实音频文件）----------
tmp = tempfile.mkdtemp(prefix="vt_asr_")
audio = os.path.join(tmp, "a.mp3")
blob = b"ID3" + os.urandom(4096)
with open(audio, "wb") as f:
    f.write(blob)

# ── 1. CRC32 用内容：改名仍同键 ──
a2 = os.path.join(tmp, "renamed.mp3")
with open(a2, "wb") as f:
    f.write(blob)
class Dummy(BaseASR):
    def _run(self, callback=None, **kw): return {}
    def _make_segments(self, resp): return []
d1 = Dummy(audio)
d2 = Dummy(a2)
expect_crc = format(zlib.crc32(blob) & 0xFFFFFFFF, "08x")
chk("CRC32 用内容而非路径", d1.crc32_hex == d2.crc32_hex,
    "%s vs %s" % (d1.crc32_hex, d2.crc32_hex))
chk("CRC32 值正确", d1.crc32_hex == expect_crc,
    "%s != %s" % (d1.crc32_hex, expect_crc))
chk("CRC32 为 8 位小写 hex",
    len(d1.crc32_hex) == 8 and all(c in "0123456789abcdef" for c in d1.crc32_hex),
    d1.crc32_hex)

# ── 2. 缓存键形式 ──
w = WhisperAPI(audio, whisper_model="whisper-1", language="zh",
               base_url="https://x.example/v1", api_key="k", use_cache=True)
k = w._get_key()
chk("WhisperAPI 子键 4 段连字符", k.count("-") >= 4, k)
chk("WhisperAPI 子键含模型", "-whisper-1-" in k, k)
chk("WhisperAPI 子键含语言", k.endswith("-zh-") or "-zh-" in k, k)
chk("WhisperAPI 子键以 crc 开头", k.startswith(d1.crc32_hex), k)
# 换模型必须换键（否则会命中别的模型的缓存，字幕完全错位）
w2 = WhisperAPI(audio, whisper_model="large-v3", language="zh",
                base_url="https://x.example/v1", api_key="k")
chk("换模型换缓存键", w._get_key() != w2._get_key())
# 换提示词必须换键
w3 = WhisperAPI(audio, whisper_model="whisper-1", language="zh", prompt="字幕",
                base_url="https://x.example/v1", api_key="k")
chk("换提示词换缓存键", w._get_key() != w3._get_key())

chk("ASR 缓存 expire = 2 天", ASR_CACHE_EXPIRE == 86400 * 2, str(ASR_CACHE_EXPIRE))
chk("expire 为整数", isinstance(ASR_CACHE_EXPIRE, int))

# ── 3. base_url 规整 ──
chk("base_url 去尾斜杠",
    WhisperAPI(audio, base_url="https://x.example/v1/", api_key="k").base_url
    == "https://x.example/v1")
chk("base_url 补 /v1",
    WhisperAPI(audio, base_url="https://x.example", api_key="k").base_url
    == "https://x.example/v1")

# ── 4. 缺配置必须报错 ──
for bad, kw in (("缺 base_url", {"base_url": "", "api_key": "k"}),
                ("缺 api_key", {"base_url": "https://x/v1", "api_key": ""})):
    try:
        WhisperAPI(audio, **kw)
        chk(bad + " 抛 ValueError", False, "未抛")
    except ValueError:
        chk(bad + " 抛 ValueError", True)

# ── 5. 音频格式校验与异常类型 ──
bad_ext = os.path.join(tmp, "x.ogg")
with open(bad_ext, "wb") as f:
    f.write(b"x")
try:
    Dummy(bad_ext)
    chk("不支持格式抛 ValueError", False, "未抛")
except ValueError:
    chk("不支持格式抛 ValueError", True)
try:
    Dummy(os.path.join(tmp, "missing.mp3"))
    chk("文件不存在抛 FileNotFoundError", False, "未抛")
except FileNotFoundError:
    chk("文件不存在抛 FileNotFoundError", True)
try:
    Dummy(None)
    chk("无输入抛 ValueError", False, "未抛")
except ValueError:
    chk("无输入抛 ValueError", True)
# bytes 直传（分块转录时每块就是 bytes）
try:
    db = Dummy(blob)
    chk("bytes 输入可用", db.crc32_hex == expect_crc,
        "%s != %s" % (db.crc32_hex, expect_crc))
except Exception as e:  # noqa: BLE001
    chk("bytes 输入可用", False, repr(e))

# ── 6. 幻觉文本与音乐标记过滤 ──
SRT = ("1\n00:00:00,000 --> 00:00:01,000\n正常的台词\n\n"
       "2\n00:00:01,000 --> 00:00:02,000\n请不吝点赞 订阅 转发\n\n"
       "3\n00:00:02,000 --> 00:00:03,000\n【音乐】\n\n"
       "4\n00:00:03,000 --> 00:00:04,000\n另一句台词\n")
class FakeFW(FasterWhisperASR):
    def __init__(self):  # 绕过程序查找（自检不装 faster-whisper）
        from engine_asr import BaseASR as _B
        _B.__init__(self, blob, False, False)
        self.model_path="base"; self.model_dir=""; self.faster_whisper_program="fw"
        self.language="zh"; self.device="cpu"; self.output_dir=None
        self.output_format="srt"; self.vad_filter=True; self.vad_threshold=0.4
        self.vad_method=""; self.ff_mdx_kim2=False; self.prompt=""
        self.one_word=0; self.sentence=False; self.max_line_width=100
        self.max_line_count=1; self.max_comma=20; self.max_comma_cent=50
        self.process=None
segs = FakeFW()._make_segments(SRT)
texts = [s.text for s in segs]
chk("过滤幻觉文本", "请不吝点赞 订阅 转发" not in texts, str(texts))
chk("过滤音乐标记", not any(t.startswith(("【","[","(","（")) for t in texts), str(texts))
chk("保留正常台词", "正常的台词" in texts and "另一句台词" in texts, str(texts))
chk("幻觉词表非空", len(HALLUCINATION_KEYWORDS) >= 2)
chk("RTX 检测不崩", is_rtx_50_series() in (True, False))

# ── 7. ASRStatus 百分比契约 ──
chk("TRANSCRIBING 在 60%", ASRStatus.TRANSCRIBING.progress == 60,
    str(ASRStatus.TRANSCRIBING.progress))
chk("COMPLETED = 100%", ASRStatus.COMPLETED.progress == 100)
chk("with_progress 返回 (进度,消息)",
    ASRStatus.TRANSCRIBING.with_progress(42) == (42, "transcribing"),
    str(ASRStatus.TRANSCRIBING.with_progress(42)))
chk("message 属性", ASRStatus.UPLOADING.message == "uploading")
# 阶段百分比必须单调不减（否则进度条会「倒退」，看起来像卡死）
chk("进度单调不减",
    ASRStatus.TRANSCRIBING.progress <= ASRStatus.PROCESSING.progress
    <= ASRStatus.PARSING_RESULT.progress <= ASRStatus.COMPLETED.progress,
    "%s" % [ASRStatus.TRANSCRIBING.progress, ASRStatus.PROCESSING.progress,
            ASRStatus.PARSING_RESULT.progress, ASRStatus.COMPLETED.progress])

print()
print("FAIL:", len(fails), fails if fails else "契约全部成立")
sys.exit(1 if fails else 0)
'''
    rc, out = _run(code)
    print(out.rstrip())
    return rc == 0


# ================================================================ B 分块合并
def positive_merger_parity():
    """分块合并与引擎 ChunkMerger 逐段比对（最关键的一组）。"""
    code = r'''
import sys
from engine_asr import ChunkMerger, ChunkedASR, CHUNK_LENGTH_SEC, \
    CHUNK_OVERLAP_SEC, CHUNK_CONCURRENCY
from engine_asr_data import ASRData, ASRDataSeg

fails = []
def chk(name, cond, detail=""):
    if cond:
        print("OK  ", name)
    else:
        fails.append(name); print("FAIL", name, detail)

def seg(text, s, e):
    return ASRDataSeg(text=text, start_time=s, end_time=e)

# ── 分块几何必须锁定（改了会同时影响时间轴与去重质量）──
chk("块长 10 分钟", CHUNK_LENGTH_SEC == 600, str(CHUNK_LENGTH_SEC))
chk("重叠 10 秒", CHUNK_OVERLAP_SEC == 10, str(CHUNK_OVERLAP_SEC))
chk("并发 3", CHUNK_CONCURRENCY == 3, str(CHUNK_CONCURRENCY))
chk("重叠 < 块长（否则切片不前进）", CHUNK_OVERLAP_SEC < CHUNK_LENGTH_SEC)

try:
    from videocaptioner.core.asr.chunk_merger import ChunkMerger as Theirs
    from videocaptioner.core.asr import chunked_asr as their_mod
except Exception as e:
    print("SKIP  第三方引擎不可用（%s）" % type(e).__name__)
    raise SystemExit(0)

# 引擎的几何常量同样必须一致
chk("引擎块长一致",
    their_mod.DEFAULT_CHUNK_LENGTH_SEC == CHUNK_LENGTH_SEC,
    "%s vs %s" % (their_mod.DEFAULT_CHUNK_LENGTH_SEC, CHUNK_LENGTH_SEC))
chk("引擎重叠一致",
    their_mod.DEFAULT_CHUNK_OVERLAP_SEC == CHUNK_OVERLAP_SEC)
chk("引擎并发一致",
    their_mod.DEFAULT_CHUNK_CONCURRENCY == CHUNK_CONCURRENCY)

# ── 构造「两块重叠」场景 ──
# 块0（offset=0）：0-3s 独白 + 3-5s 重叠内容
# 块1（offset=295s）：0-2s 重叠内容(同文本) + 2-4s 后续独白
OV = 10000
L = ASRData([seg("第一句独白", 0, 2000),
             seg("重叠的内容甲", 2000, 4000),
             seg("重叠的内容乙", 4000, 6000),
             seg("块零结尾", 6000, 8000)])
R = ASRData([seg("重叠的内容甲", 0, 2000),
             seg("重叠的内容乙", 2000, 4000),
             seg("块一开头之后", 4000, 6000)])
chunks = [L, R]
offsets = [0, 295000]

def norm(d):
    return [(s.text, s.start_time, s.end_time) for s in d.segments]

for label, mkw in (("句级模糊匹配", dict(min_match_count=2, fuzzy_threshold=0.7)),
                   ("更严阈值", dict(min_match_count=2, fuzzy_threshold=0.95))):
    mine = ChunkMerger(**mkw).merge_chunks(chunks, offsets, OV)
    theirs = Theirs(**mkw).merge_chunks(chunks, offsets, OV)
    chk("合并结果逐段一致-" + label, norm(mine) == norm(theirs),
        "\n  自研 %s\n  引擎 %s" % (norm(mine), norm(theirs)))

# ── 无重叠区域 ⇒ 直接拼接 ──
a = ASRData([seg("甲", 0, 1000)])
b = ASRData([seg("乙", 0, 1000)])
mine = ChunkMerger().merge_chunks([a, b], [0, 500000], OV)
theirs = Theirs().merge_chunks([a, b], [0, 500000], OV)
chk("无重叠时直接拼接", norm(mine) == norm(theirs),
    "%s vs %s" % (norm(mine), norm(theirs)))

# ── 完全无文本匹配 ⇒ 时间边界切分 ──
c1 = ASRData([seg("完全不同的甲", 0, 2000)])
c2 = ASRData([seg("毫不相干的乙", 0, 2000)])
mine = ChunkMerger().merge_chunks([c1, c2], [0, 5000], OV)
theirs = Theirs().merge_chunks([c1, c2], [0, 5000], OV)
chk("无匹配时时间边界切分一致", norm(mine) == norm(theirs),
    "%s vs %s" % (norm(mine), norm(theirs)))

# ── offset 自动推断一致 ──
mine = ChunkMerger().infer if False else None
m_offs = ChunkMerger()._infer_chunk_offsets(chunks, OV)
t_offs = Theirs()._infer_chunk_offsets(chunks, OV)
chk("offset 自动推断一致", m_offs == t_offs, "%s vs %s" % (m_offs, t_offs))

# ── 词级时间戳分支 ──
w1 = ASRData([seg("词", 0, 1000), seg("级", 1000, 2000)])
w2 = ASRData([seg("词", 0, 1000), seg("级", 1000, 2000)])
mine = ChunkMerger().merge_chunks([w1, w2], [0, 500], OV)
theirs = Theirs().merge_chunks([w1, w2], [0, 500], OV)
chk("词级分支一致", norm(mine) == norm(theirs),
    "%s vs %s" % (norm(mine), norm(theirs)))

# ── 异常契约 ──
for bad, exc in (("空 chunks", "ValueError"),
                 ("offsets 数量不匹配", "ValueError")):
    try:
        if bad == "空 chunks":
            ChunkMerger().merge_chunks([], None, OV)
        else:
            ChunkMerger().merge_chunks(chunks, [0], OV)
        chk(bad + " 抛 ValueError", False, "未抛")
    except ValueError:
        chk(bad + " 抛 ValueError", True)
    except Exception as e:
        chk(bad + " 抛 ValueError", False, type(e).__name__)

# 单块直通
one = ASRData([seg("唯一", 0, 100)])
chk("单块直通", ChunkMerger().merge_chunks([one], None, OV) is one)

print()
print("FAIL:", len(fails), fails if fails else "分块合并与引擎逐段一致")
sys.exit(1 if fails else 0)
'''
    rc, out = _run(code)
    print(out.rstrip())
    return rc == 0


# ================================================================ C HTTP
def positive_http():
    """用本地假 HTTP 服务验证传输层。"""
    code = r'''
import sys, json, threading, os, tempfile
from http.server import BaseHTTPRequestHandler, HTTPServer
from engine_asr_http import post_transcription, transcription_url, AsrHttpError

fails = []
def chk(name, cond, detail=""):
    if cond:
        print("OK  ", name)
    else:
        fails.append(name); print("FAIL", name, detail)

# ── URL 推导 ──
chk("完整端点不重复拼",
    transcription_url("https://x/v1/audio/transcriptions")
    == "https://x/v1/audio/transcriptions")
chk("补 /audio/transcriptions",
    transcription_url("https://x/v1") == "https://x/v1/audio/transcriptions")
chk("/audio 补 /transcriptions",
    transcription_url("https://x/v1/audio") == "https://x/v1/audio/transcriptions")
chk("去尾斜杠",
    transcription_url("https://x/v1/") == "https://x/v1/audio/transcriptions")

RECV = {}

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        RECV["body"] = self.rfile.read(n)
        RECV["headers"] = dict(self.headers)
        mode = RECV.get("mode", "ok")
        if mode == "http_error":
            self.send_response(401); self.end_headers()
            self.wfile.write(b'{"error":{"message":"bad key"}}'); return
        if mode == "html":
            self.send_response(200); self.end_headers()
            self.wfile.write(b"<html>nope</html>"); return
        if mode == "plain_text":
            self.send_response(200); self.end_headers()
            self.wfile.write(b"just some text"); return
        payload = {"text": "整体", "segments": [
            {"start": 0.0, "end": 1.5, "text": " 你好 "},
            {"start": 1.5, "end": 3.0, "text": "世界"}],
            "words": [{"word": "你", "start": 0.0, "end": 0.5}]}
        b = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers(); self.wfile.write(b)

srv = HTTPServer(("127.0.0.1", 0), H)
port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = "http://127.0.0.1:%d/v1" % port

# ── 正常请求 ──
RECV["mode"] = "ok"
data = post_transcription(base_url=BASE, api_key="sk-test", model="whisper-1",
                          audio_bytes=b"AUDIODATA", prompt="提示", language="zh",
                          timeout=20)
chk("返回 segments", "segments" in data)
chk("段数正确", len(data["segments"]) == 2, str(len(data["segments"])))
body = RECV["body"].decode("utf-8", "replace")
chk("multipart boundary", "multipart/form-data" in
    RECV["headers"].get("Content-Type", ""), RECV["headers"].get("Content-Type"))
chk("Authorization Bearer", RECV["headers"].get("Authorization") == "Bearer sk-test",
    str(RECV["headers"].get("Authorization")))
chk("携带 model 字段", 'name="model"' in body and "whisper-1" in body)
chk("携带 response_format=verbose_json", "verbose_json" in body, body[:200])
chk("携带 language=zh", 'name="language"' in body)
chk("携带 prompt", "提示" in body)
chk("携带文件字节", "AUDIODATA" in body)
chk("未请求词级则不带 granularities", "timestamp_granularities" not in body)

# ── 自动检测：空语言不传字段 ──
RECV["body"] = b""
post_transcription(base_url=BASE, api_key="k", model="m",
                   audio_bytes=b"A", language="", timeout=20)
chk("空语言不传 language 字段",
    'name="language"' not in RECV["body"].decode("utf-8", "replace"))

# ── 词级时间戳才带 granularities ──
RECV["body"] = b""
post_transcription(base_url=BASE, api_key="k", model="m", audio_bytes=b"A",
                   need_word_time_stamp=True, timeout=20)
b2 = RECV["body"].decode("utf-8", "replace")
chk("词级带 granularities", "timestamp_granularities" in b2, b2[:300])
chk("granularities 含 word", ">word<" in b2 or "word" in b2)

# ── 错误路径：必须抛异常，不得返回空 dict ──
RECV["mode"] = "http_error"
try:
    post_transcription(base_url=BASE, api_key="bad", model="m",
                       audio_bytes=b"A", timeout=20)
    chk("HTTP 401 抛 AsrHttpError", False, "未抛")
except AsrHttpError as e:
    chk("HTTP 401 抛 AsrHttpError", True)
    chk("异常带 status", e.status == 401, str(e.status))
    chk("异常带响应体", "bad key" in e.body, e.body[:80])

RECV["mode"] = "html"
try:
    post_transcription(base_url=BASE, api_key="k", model="m",
                       audio_bytes=b"A", timeout=20)
    chk("HTML 响应抛异常", False, "未抛")
except AsrHttpError:
    chk("HTML 响应抛异常", True)

RECV["mode"] = "plain_text"
try:
    post_transcription(base_url=BASE, api_key="k", model="m",
                       audio_bytes=b"A", timeout=20)
    chk("纯文本响应抛异常", False, "未抛")
except AsrHttpError:
    chk("纯文本响应抛异常", True)

# ── 入参校验 ──
for name, kw in (
    ("空 base_url", dict(base_url="", api_key="k", model="m", audio_bytes=b"A")),
    ("空 api_key", dict(base_url=BASE, api_key="", model="m", audio_bytes=b"A")),
    ("空音频", dict(base_url=BASE, api_key="k", model="m", audio_bytes=b"")),
):
    try:
        post_transcription(timeout=10, **kw)
        chk(name + " 抛 AsrHttpError", False, "未抛")
    except AsrHttpError:
        chk(name + " 抛 AsrHttpError", True)
    except Exception as e:
        chk(name + " 抛 AsrHttpError", False, type(e).__name__)

# ── 端点不通也要抛异常 ──
try:
    post_transcription(base_url="http://127.0.0.1:1/v1", api_key="k",
                       model="m", audio_bytes=b"A", timeout=3)
    chk("端点不通抛 AsrHttpError", False, "未抛")
except AsrHttpError:
    chk("端点不通抛 AsrHttpError", True)
except Exception as e:
    chk("端点不通抛 AsrHttpError", False, type(e).__name__)

srv.shutdown()

# ── 与引擎 WhisperAPI._make_segments 的段转换一致性 ──
try:
    from videocaptioner.core.asr.whisper_api import WhisperAPI as TheirAPI
    from engine_asr import WhisperAPI as MineAPI
    import tempfile as tf
    tmp = tf.mkdtemp()
    ap = os.path.join(tmp, "a.mp3")
    with open(ap, "wb") as f: f.write(b"ID3" + os.urandom(2048))
    resp = {"segments": [{"start": 0.0, "end": 1.5, "text": " 你好 "},
                         {"start": 1.5, "end": 3.0, "text": "世界"}],
            "words": [{"word": "你", "start": 0.0, "end": 0.5},
                      {"word": "好", "start": 0.5, "end": 1.5}]}
    mine = MineAPI(ap, base_url="https://x/v1", api_key="k", need_word_time_stamp=False)
    theirs = TheirAPI(ap, whisper_model="m", need_word_time_stamp=False,
                      base_url="https://x/v1", api_key="k")
    m = [(s.text, s.start_time, s.end_time) for s in mine._make_segments(resp)]
    t = [(s.text, s.start_time, s.end_time) for s in theirs._make_segments(resp)]
    chk("句级段转换与引擎一致", m == t, "%s vs %s" % (m, t))

    mine_w = MineAPI(ap, base_url="https://x/v1", api_key="k", need_word_time_stamp=True)
    theirs_w = TheirAPI(ap, whisper_model="m", need_word_time_stamp=True,
                        base_url="https://x/v1", api_key="k")
    mw = [(s.text, s.start_time, s.end_time) for s in mine_w._make_segments(resp)]
    tw = [(s.text, s.start_time, s.end_time) for s in theirs_w._make_segments(resp)]
    chk("词级段转换与引擎一致", mw == tw, "%s vs %s" % (mw, tw))
    chk("词级文本不 strip（引擎同款）", mw[0][0] == "你", str(mw[0]))
    chk("句级文本 strip", m[0][0] == "你好", str(m[0]))
except ImportError:
    print("SKIP  第三方引擎不可用，跳过段转换交叉项")
except Exception as e:
    fails.append("段转换交叉")
    print("FAIL 段转换交叉", repr(e))

print()
print("FAIL:", len(fails), fails if fails else "HTTP 传输全部成立")
sys.exit(1 if fails else 0)
'''
    rc, out = _run(code)
    print(out.rstrip())
    return rc == 0


# ================================================================ 负向
def negative():
    import shutil
    import tempfile
    tmp = tempfile.mkdtemp(prefix="vt_asr_neg_")
    src_file = os.path.join(SRC, "engine_asr.py")
    dst = os.path.join(tmp, "engine_asr.py")
    ok = True
    try:
        with open(src_file, encoding="utf-8") as f:
            txt = f.read()
        # ⚠ 必须**合并**进 os.environ，不能用字面 dict 当整个环境：
        #   只给 {"PYTHONPATH": ...} 会丢掉 SystemRoot/COMSPEC 等 Windows
        #   必需变量，子进程可能在启动阶段就失败（表现为「污染后仍判通过」）。
        env = dict(os.environ)
        env["PYTHONPATH"] = tmp + os.pathsep + SRC + os.pathsep + \
            env.get("PYTHONPATH", "")

        # ① 破坏「重叠提取」——去掉 from_end 分支的时间阈值
        #    ⚠ 用例必须选能让「重叠区被误扩成全量」显形的数据：
        #    若左侧只有 4 段且全落在重叠窗内，扩成全量与不扩结果相同 ⇒ 假绿。
        #    这里让左侧前段**远早于**重叠窗（0-1s，而重叠窗从 80s 起算），
        #    正确实现只取末尾两条，污染实现会多带上「甲」，切点随之偏移。
        anchor = ("                if seg.start_time >= threshold:\n"
                  "                    out.insert(0, seg)")
        if anchor not in txt:
            print("负向①：未找到注入点，跳过（不代表检查无效）")
            return False
        p1 = txt.replace(anchor,
                         "                if True:\n"
                         "                    out.insert(0, seg)", 1)
        if p1 == txt:
            print("负向①：污染未生效，跳过（不代表检查无效）")
            return False
        with open(dst, "w", encoding="utf-8") as f:
            f.write(p1)
        code = (
            "import sys\n"
            "from engine_asr import ChunkMerger\n"
            "from engine_asr_data import ASRDataSeg\n"
            "def s(t, a, b): return ASRDataSeg(text=t, start_time=a, end_time=b)\n"
            "OV = 10000\n"
            # 末段结束于 90000 ⇒ 重叠窗起点 80000；
            # 「甲」(0-1000) 远在窗外，正确实现**不得**把它纳入重叠区。
            "segs = [s('甲', 0, 1000), s('乙', 1000, 2000),\n"
            "        s('重叠甲', 80000, 82000), s('重叠乙', 82000, 84000),\n"
            "        s('重叠丙', 84000, 86000), s('尾', 86000, 90000)]\n"
            "got = ChunkMerger()._extract_overlap_segments(\n"
            "    segs, from_end=True, duration=OV)\n"
            "print('提取到:', [x.text for x in got])\n"
            # 判据直接检「目标行为」：窗外段不得被纳入重叠区。
            # ⚠ 不能用「与引擎整体合并结果是否相同」当判据——滑动窗口会重新
            #    定位切点，两边仍可能一致 ⇒ 假绿（本次实测确实一致）。
            "bad = [x.text for x in got if x.text in ('甲', '乙')]\n"
            "sys.exit(3 if bad else 0)\n"
        )
        r = subprocess.run([PYPARSE, "-c", code], env={**os.environ, **env},
                           capture_output=True, text=True)
        if r.returncode == 3:
            print("OK   负向①：重叠提取被破坏后成功检出")
        else:
            print("FAIL 负向①：合并一致性检查形同虚设")
            ok = False

        # ② 破坏缓存键形式（去掉 crc 前缀）
        #    ⚠ 判据必须是「键里还有没有 crc32」，不能拿整串去比——
        #    污染后键是 "whisper-1-zh"，与任何整串常量都不等 ⇒ 永远「通过」。
        anchor2 = ('        return "%s-%s-%s-%s" % (self.crc32_hex, self.model, '
                   'self.language,\n                                self.prompt)')
        if anchor2 not in txt:
            print("负向②：未找到注入点，跳过")
            return False
        p2 = txt.replace(anchor2,
                         '        return "%s-%s" % (self.model, self.language)', 1)
        if p2 == txt:
            print("负向②：污染未生效，跳过（不代表检查无效）")
            return False
        with open(dst, "w", encoding="utf-8") as f:
            f.write(p2)
        code2 = (
            "import sys, os, tempfile\n"
            "from engine_asr import WhisperAPI\n"
            "tmp = tempfile.mkdtemp(); p = os.path.join(tmp, 'a.mp3')\n"
            "open(p, 'wb').write(b'ID3' + os.urandom(512))\n"
            "w = WhisperAPI(p, base_url='https://x/v1', api_key='k')\n"
            # 退出码即判据：键里**没有** crc32 ⇒ 正向检查失效 ⇒ 3（检出）
            "sys.exit(0 if w._get_key().startswith(w.crc32_hex) else 3)\n"
        )
        r2 = subprocess.run([PYPARSE, "-c", code2], env={**os.environ, **env},
                            capture_output=True, text=True)
        if r2.returncode == 3:
            print("OK   负向②：缓存键丢 crc 前缀被成功检出")
        else:
            print("FAIL 负向②：缓存键检查形同虚设")
            ok = False
        return ok
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    print("=" * 60)
    print("engine_asr ASR 链路逐行为兼容性自检")
    print("=" * 60)
    print("\n[1/4] 正向 A：契约与缓存键")
    ok1 = positive_contract()
    print("\n[2/4] 正向 B：分块合并与引擎逐段比对")
    ok2 = positive_merger_parity()
    print("\n[3/4] 正向 C：HTTP 传输（本地假服务）")
    ok3 = positive_http()
    print("\n[4/4] 负向校验（故意弄坏）")
    ok4 = negative()
    print("\n" + "=" * 60)
    allok = ok1 and ok2 and ok3 and ok4
    print("结论：", "PASS" if allok else "FAIL")
    return 0 if allok else 1


if __name__ == "__main__":
    sys.exit(main())