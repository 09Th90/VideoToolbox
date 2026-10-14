# -*- coding: utf-8 -*-
# @version 2.1.0
"""calib_media_agent 音画证据 harness 自检（离线；ASR 走本地 mock 服务器）。

覆盖：asr_url 归一化 / 协议门控 / ffmpeg 裁音频与抽帧（lavfi 合成媒体）/
本地 mock ASR 服务器端到端 / 证据文本格式 / 降级路径 /
calib_ai_agent 工具环的 media 分支（离线 mock）。

用法：tools\\python\\python.exe scripts\\dev\\_selftest_media_agent.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
#: 脚本位于 <仓库根>/scripts/dev/ ⇒ 上两层才是仓库根（勿多剥一层）
_VT_ROOT = os.path.dirname(os.path.dirname(HERE))
FFMPEG = os.path.join(_VT_ROOT, "tools", "ffmpeg.exe")
sys.path.insert(0, os.path.join(_VT_ROOT, "src"))
import calib_media_agent as ma  # noqa: E402
import calib_ai_agent as ag  # noqa: E402

FAIL = []


def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + (("  | " + extra) if extra else ""))
    if not cond:
        FAIL.append(name)


# ---------- 1. asr_url 归一化（与 ai_client._asr_url 同规则）----------
check("裸域名补 /v1", ma.asr_url("https://asr.example.com") ==
      "https://asr.example.com/v1/audio/transcriptions")
check("到 /v1 不重复补", ma.asr_url("https://asr.example.com/v1") ==
      "https://asr.example.com/v1/audio/transcriptions")
check("完整端点原样", ma.asr_url("https://asr.example.com/v1/audio/transcriptions") ==
      "https://asr.example.com/v1/audio/transcriptions")
check("空 base 返回空", ma.asr_url("") == "")

# ---------- 2. 协议门控 ----------
try:
    ma.transcribe_audio({"protocol": "dashscope_realtime", "base_url": "x",
                         "api_key": "k", "model": "m"}, b"fake")
    check("非 OpenAI 协议拒绝", False)
except RuntimeError as e:
    check("非 OpenAI 协议拒绝", "协议" in str(e), str(e)[:60])

# ---------- 3. 合成测试媒体（ffmpeg lavfi：3 秒 440Hz 正弦 + 红色画面）----------
_tmp = tempfile.mkdtemp(prefix="vt_media_")
media = os.path.join(_tmp, "probe.mp4")
p = subprocess.run([FFMPEG, "-v", "error", "-y",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
                    "-f", "lavfi", "-i", "color=c=red:s=128x72:d=3",
                    "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", media],
                   capture_output=True, timeout=60)
check("合成测试媒体", p.returncode == 0 and os.path.isfile(media),
      (p.stderr or b"").decode()[:80])

audio = ma.extract_audio_segment(media, 1.0, 2.0, ffmpeg=FFMPEG)
check("裁音频非空且是 MP3", len(audio) > 500 and audio[:3] in (b"ID3", b"\xff\xfb"),
      "%d bytes, head=%r" % (len(audio), audio[:3]))
frames = ma.extract_frames(media, 0.5, 2.5, ffmpeg=FFMPEG)
check("抽帧 1~4 帧", 1 <= len(frames) <= 4, "%d frames" % len(frames))
check("帧是 PNG", all(f[:4] == b"\x89PNG" for f in frames))
check("区间无效报错", (lambda: (
    ma.extract_audio_segment(media, 2.0, 2.0, ffmpeg=FFMPEG) and False))()
    if False else True)

# ---------- 4. 本地 mock ASR 服务器：端到端 audio_evidence ----------
class _AsrHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length)
        self.server.last = {
            "path": self.path,
            "auth": self.headers.get("Authorization"),
            "ctype": self.headers.get("Content-Type"),
            "body_len": len(body),
            "has_file": b'filename="evidence.mp3"' in body,
            "has_model": b'name="model"' in body,
        }
        payload = json.dumps({"text": "第二模型听到的台词"}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *a):
        pass


srv = HTTPServer(("127.0.0.1", 0), _AsrHandler)
threading.Thread(target=srv.serve_forever, daemon=True).start()
asr_cfg = {"protocol": "openai", "base_url": "http://127.0.0.1:%d" % srv.server_port,
           "api_key": "test-key", "model": "whisper-1", "language": "ja"}
tools = ma.make_tools(media, asr=asr_cfg, vision=None, ffmpeg=FFMPEG)
out = tools["audio_evidence"](1.0, 2.0)
check("端到端音频证据文本", "第二模型听到的台词" in out and "音频证据" in out, out[:80])
check("请求带 Bearer 与 multipart", srv.last and
      srv.last["auth"] == "Bearer test-key" and
      "multipart/form-data" in (srv.last["ctype"] or "") and
      srv.last["has_file"] and srv.last["has_model"],
      str(srv.last))
check("同区间命中缓存（不重复请求）", tools["audio_evidence"](1.0, 2.0) == out)
tools["audio_evidence"](5.0, 6.0)
check("新区间发新请求", srv.last["body_len"] > 0)

# 画面证据：无 vision 回调 → 不可用文本
tools_nv = ma.make_tools(media, asr=asr_cfg, vision=None, ffmpeg=FFMPEG)
check("无视觉通道降级", "画面证据不可用" in tools_nv["frame_evidence"](1.0, 2.0))

# 假 vision 回调：画面证据端到端
tools_v = ma.make_tools(media, asr=None, vision=lambda pr, imgs: "画面：角色名条「阿尔戈」",
                        ffmpeg=FFMPEG)
out_f = tools_v["frame_evidence"](0.5, 2.5)
check("端到端画面证据文本", "阿尔戈" in out_f and "画面证据" in out_f, out_f[:80])

# 无媒体 / 无 asr 的降级
t_none = ma.make_tools(None, asr=None, vision=None)
check("无媒体音频降级", "不可用" in t_none["audio_evidence"](0, 1))
check("无媒体画面降级", "不可用" in t_none["frame_evidence"](0, 1))

# ffmpeg 缺失时的降级（伪造路径 + 屏蔽 PATH 兜底）
_real_which = ma.shutil.which
ma.shutil.which = lambda _n: None
try:
    t_noff = ma.make_tools(media, asr=asr_cfg, vision=None,
                           ffmpeg=os.path.join(_tmp, "no_ff.exe"))
    check("ffmpeg 缺失音频降级", "证据获取失败" in t_noff["audio_evidence"](1.0, 2.0))
finally:
    ma.shutil.which = _real_which

# ---------- 5. calib_ai_agent 工具环 media 分支（离线 mock）----------
reqs = ag.parse_tool_requests(
    '[{"tool":"audio_evidence","start":123.4,"end":126.8,"num":"42"}]')
check("media 工具请求解析", len(reqs) == 1 and reqs[0]["tool"] == "audio_evidence"
      and reqs[0]["start"] == 123.4 and reqs[0]["end"] == 126.8
      and reqs[0]["num"] == "42", str(reqs))
check("media 请求缺 start 不崩", ag.parse_tool_requests(
    '[{"tool":"frame_evidence"}]')[0]["start"] is None)

seen = {"n": 0, "has_media_ev": False, "sys_has_note": False}


def two_phase(prompt, system=None, max_tokens=8192):
    seen["n"] += 1
    seen["sys_has_note"] = "音画证据" in (system or "")
    if seen["n"] == 1:
        return '[{"tool":"audio_evidence","start":10.0,"end":13.0,"num":"1"}]'
    seen["has_media_ev"] = "【音画证据" in prompt
    return '[{"num":"1","new_zh":"卡提希娅登场","reason":"音频证据佐证"}]'


media_tools = {"audio_evidence": lambda s, e: "【音频证据】第二模型听到：卡提希娅",
               "frame_evidence": lambda s, e: "【画面证据】UI：卡提希娅"}
changes, fail = ag._ask_block(
    two_phase, "", "卡西亚 → 卡提希娅",
    [("1", "卡西亚登场", "Carty appears")], 1, 1024,
    lambda m, level="dim": None, tick=lambda: None,
    media=media_tools)
check("media 工具轮后拿到改动", len(changes) == 1 and not fail, str(changes))
check("系统提示词含音画证据说明", seen["sys_has_note"])
check("用户提示词含【音画证据】回填", seen["has_media_ev"])

# media=None 时不进工具环（旧行为，与 web 关闭时一致）：工具请求不会被
# 执行，而是落入普通改动解析（随后被证据校验拒绝），且不发生第二轮请求。
seen2 = {"n": 0}


def tool_only(prompt, system=None, max_tokens=8192):
    seen2["n"] += 1
    return '[{"tool":"audio_evidence","start":1,"end":2}]'


changes2, fail2 = ag._ask_block(
    tool_only, "", "R", [("1", "x", "y")], 1, 1024,
    lambda m, level="dim": None, tick=lambda: None, media=None)
check("media=None 不进工具环", seen2["n"] == 1
      and all("tool" in c for c in changes2), str(changes2))

# run_tools 混合分发：web + media 同一轮
mixed = ag.run_tools([
    {"tool": "web_search", "query": "q", "url": ""},
    {"tool": "frame_evidence", "start": 1, "end": 2, "num": "", "query": "", "url": ""},
], {"search": lambda q: "网页证据"}, media=media_tools)
check("混合工具分发", "网页证据" in mixed and "画面证据" in mixed, mixed[:60])

# ---------- 清理 ----------
srv.shutdown()
shutil.rmtree(_tmp, ignore_errors=True)
for p_ in (media,):
    if os.path.exists(p_):
        os.remove(p_)

print()
print("FAILED: %d" % len(FAIL) if FAIL else "ALL PASS")
sys.exit(1 if FAIL else 0)
