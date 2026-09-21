# -*- coding: utf-8 -*-
# @version 1.15.7
"""ASR 全协议适配自检（离线：全部 mock requests，不联网、不消耗额度）。

覆盖：协议自动识别（两侧规则一致性）、实时模型守卫、六条协议的请求构造、
响应归一化（词级时间轴 → 句级 segments）、错误提示文案。
运行：tools/python/python.exe _selftest_asr_proto.py
结果写 C:\\bld\\_asr_proto_test\\result.txt（本机 PowerShell 无 stdout）。
"""
import base64
import importlib.util
import json
import os
import sys
import time
import types

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("VT_NO_PIPELINE", "1")
os.environ.setdefault("VT_NO_SYNC", "1")
os.environ.setdefault("VT_NO_CALIB_SYNC", "1")

import video_toolbox as engine  # noqa: E402

OUT = r"C:\bld\_asr_proto_test"
os.makedirs(OUT, exist_ok=True)
LINES, FAILS = [], []


def say(m):
    LINES.append(str(m))


def check(name, cond, extra=""):
    line = "  [%s] %s%s" % ("PASS" if cond else "FAIL", name,
                            (" -> " + str(extra)) if extra else "")
    say(line)
    if not cond:
        FAILS.append(name)


# ---------------------------------------------------------------- 假 requests
CALLS = []
ROUTES = {}          # POST 路由（url 子串匹配）
ROUTES_GET = {}      # GET 路由

_REAL_SLEEP = time.sleep


def _patch_sleep(on):
    """轮询里的 time.sleep(3) 在自检里太慢 —— 临时换成 no-op。"""
    time.sleep = (lambda *_a, **_k: None) if on else _REAL_SLEEP


class _Resp:
    def __init__(self, status=200, payload=None, text="", headers=None):
        self.status_code = status
        self._payload = payload
        self.text = text
        self.headers = headers or {}

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


def _fake_post(url, **kw):
    CALLS.append({"url": url, "kw": kw, "method": "POST"})
    for key, resp in ROUTES.items():
        if key in url:
            return resp() if callable(resp) else resp
    return _Resp(404, None, "no route: " + url)


def _fake_get(url, **kw):
    CALLS.append({"url": url, "kw": kw, "method": "GET"})
    for key, resp in ROUTES_GET.items():
        if key in url:
            return resp() if callable(resp) else resp
    return _Resp(404, None, "no route: " + url)


def _install_fake_requests():
    mod = types.ModuleType("requests")
    mod.post = _fake_post
    mod.get = _fake_get
    sys.modules["requests"] = mod


# ------------------------------------------------------------ 假 websocket
class _FakeWS:
    """按脚本回放服务端事件；记录客户端发的每一帧（文本/二进制）。"""

    def __init__(self, script, log):
        self._script = list(script)
        self._log = log

    def send(self, data):
        self._log.setdefault("sent", []).append(data)

    def close(self):
        self._log["closed"] = True

    def recv(self):
        if not self._script:
            raise RuntimeError("script exhausted")
        item = self._script.pop(0)
        if isinstance(item, tuple) and item[0] == "bin":
            return item[1]
        if isinstance(item, dict):
            return json.dumps(item)
        raise RuntimeError(str(item))


def _install_fake_websocket(script, log):
    mod = types.ModuleType("websocket")

    def create_connection(url, **kw):
        log["url"] = url
        log["header"] = kw.get("header") or {}
        return _FakeWS(script, log)

    mod.create_connection = create_connection
    sys.modules["websocket"] = mod


WAV = b"RIFF\x24\x00\x00\x00WAVEfmt \x10\x00\x00\x00" + b"\x00" * 32


class FakeASR:
    """Stand-in for videocaptioner 的 WhisperAPI 实例（只用到这几个属性）。"""

    def __init__(self, base, model, key="sk-test-1234", lang="zh", prompt=""):
        self.base_url = base
        self.model = model
        self.api_key = key
        self.language = lang
        self.prompt = prompt
        self.file_binary = WAV


def main():
    _install_fake_requests()

    say("== 1) 协议自动识别（auto 档）==")
    CASES = [
        ("https://llm-ukmkj60gxr2wms1f.cn-beijing.maas.aliyuncs.com/"
         "compatible-mode/v1", "qwen3-asr-flash", "chat_audio"),
        ("https://dashscope.aliyuncs.com/compatible-mode/v1",
         "qwen3-asr-flash", "chat_audio"),
        ("https://dashscope.aliyuncs.com/api/v1", "paraformer-v2", "chat_audio"),
        ("https://api.xiaomimimo.com/v1", "mimo-v2.5-asr", "chat_audio"),
        ("https://api.deepgram.com", "nova-3", "deepgram"),
        ("https://api.elevenlabs.io", "scribe_v1", "elevenlabs"),
        ("https://generativelanguage.googleapis.com", "gemini-2.5-flash",
         "gemini"),
        ("https://myres.openai.azure.com", "whisper", "azure"),
        ("https://api.openai.com/v1", "whisper-1", "openai"),
        ("https://api.siliconflow.cn/v1", "FunAudioLLM/SenseVoiceSmall",
         "openai"),
        ("https://api.groq.com/openai/v1", "whisper-large-v3", "openai"),
        ("https://openspeech.bytedance.com/api/v3/auc/bigmodel/recognize/flash",
         "volc.bigasr.auc_turbo", "volcengine"),
        ("https://api.assemblyai.com", "universal-3-pro", "assemblyai"),
    ]
    for base, model, want in CASES:
        got = engine._infer_asr_protocol(base, model)
        check("识别 %s + %s → %s" % (base.split("/")[2], model, want),
              got == want, got)

    say("")
    say("== 2) 两侧规则一致性（引擎 vs tools/ai_client）==")
    spec = importlib.util.spec_from_file_location(
        "_ai_client_probe", os.path.join(engine.TOOLS_DIR, "ai_client.py"))
    aim = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(aim)
    same = True
    diff = ""
    for base, model, want in CASES:
        a = engine._infer_asr_protocol(base, model)
        b = aim.resolve_asr_protocol({"base_url": base, "model": model,
                                      "protocol": "auto"})
        if a != b:
            same = False
            diff = "%s：引擎 %s / ai_client %s" % (base, a, b)
    check("十三组样例两侧推断完全一致", same, diff)
    check("显式协议优先于推断",
          aim.resolve_asr_protocol({"base_url": "https://api.deepgram.com",
                                    "model": "x", "protocol": "openai"})
          == "openai")
    check("历史键 dashscope 两侧都归一成 chat_audio",
          aim.resolve_asr_protocol({"base_url": "https://x",
                                    "model": "y", "protocol": "dashscope"})
          == "chat_audio"
          and engine.asr_protocol_of({"asr_mode": "service",
                                      "asr_base_url": "https://x",
                                      "asr_model": "y",
                                      "asr_protocol": "dashscope"})
          == "chat_audio")

    say("")
    say("== 3) 实时（流式）模型守卫 ==")
    g = engine.asr_model_guard("fun-asr-flash-8k-realtime")
    check("拦下 fun-asr-flash-8k-realtime", bool(g), g[:60])
    check("提示里给出了替代模型", "qwen3-asr-flash" in g)
    check("放行 qwen3-asr-flash", engine.asr_model_guard("qwen3-asr-flash") == "")
    check("放行 paraformer-v2", engine.asr_model_guard("paraformer-v2") == "")
    check("放行 scribe_v1", engine.asr_model_guard("scribe_v1") == "")
    check("放行 nova-3", engine.asr_model_guard("nova-3") == "")

    say("")
    say("== 4) Chat 音频转写（chat/completions + input_audio）==")
    CALLS.clear()
    ROUTES.clear()
    ROUTES["/chat/completions"] = _Resp(200, {"choices": [
        {"message": {"content": "你好世界。第二句。"}}]})
    out = engine._asr_chat_audio_submit(FakeASR(
        "https://dashscope.aliyuncs.com/compatible-mode/v1", "qwen3-asr-flash"))
    call = CALLS[-1]
    body = call["kw"].get("json") or {}
    data = body["messages"][0]["content"][0]["input_audio"]["data"]
    check("打到 /chat/completions", call["url"].endswith("/chat/completions"),
          call["url"])
    check("鉴权用 Bearer", call["kw"]["headers"].get("Authorization", "")
          .startswith("Bearer "))
    check("音频以 Data URL 上传（自带 MIME）",
          data.startswith("data:audio/wav;base64,") and len(data) > 40)
    check("显式 stream=False", body.get("stream") is False)
    norm = engine._asr_normalize_resp(out, None)
    segs = norm.get("segments") or []
    check("纯文本响应按句切分出 segments", len(segs) == 2
          and segs[0]["text"] == "你好世界。", segs)

    say("")
    say("== 5) Deepgram（/v1/listen + Token 头 + 原始音频）==")
    CALLS.clear()
    ROUTES.clear()
    ROUTES["/v1/listen"] = _Resp(200, {"results": {"channels": [
        {"alternatives": [{
            "transcript": "hello world 你好",
            "words": [
                {"word": "hello", "punctuated_word": "Hello", "start": 0.1,
                 "end": 0.5},
                {"word": "world", "punctuated_word": "world.", "start": 0.5,
                 "end": 0.9},
                {"word": "你", "punctuated_word": "你", "start": 1.0,
                 "end": 1.2},
                {"word": "好", "punctuated_word": "好", "start": 1.2,
                 "end": 1.4}]}]}]}})
    out = engine._asr_deepgram_submit(FakeASR("https://api.deepgram.com",
                                              "nova-3"))
    call = CALLS[-1]
    check("自动补 /v1/listen", call["url"].endswith("/v1/listen"), call["url"])
    check("鉴权用 Token 头",
          call["kw"]["headers"].get("Authorization", "").startswith("Token "))
    check("中文片源带 language=zh-CN",
          call["kw"]["params"].get("language") == "zh-CN", call["kw"]["params"])
    check("body 是原始音频字节（不是 multipart）",
          call["kw"].get("data") == WAV)
    norm = engine._asr_normalize_resp(out, None)
    segs = norm.get("segments") or []
    check("词级时间轴被聚合成句（两条：英文句 + 中文）", len(segs) == 2, segs)
    check("时间轴来自原生 word（0.1-0.9）",
          segs and abs(segs[0]["start"] - 0.1) < 1e-6
          and abs(segs[0]["end"] - 0.9) < 1e-6, segs[:1])
    check("拉丁词之间加空格、中文不加",
          segs and segs[0]["text"] == "Hello world."
          and segs[1]["text"] == "你好", [s["text"] for s in segs])

    say("")
    say("== 6) ElevenLabs Scribe（multipart + xi-api-key）==")
    CALLS.clear()
    ROUTES.clear()
    ROUTES["/speech-to-text"] = _Resp(200, {
        "text": "一句话。",
        "words": [{"text": "一句话", "start": 0.2, "end": 1.0},
                  {"text": "。", "start": 1.0, "end": 1.1}]})
    out = engine._asr_elevenlabs_submit(FakeASR("https://api.elevenlabs.io",
                                                "scribe_v1"))
    call = CALLS[-1]
    check("打到 /v1/speech-to-text",
          call["url"].endswith("/v1/speech-to-text"), call["url"])
    check("鉴权用 xi-api-key", "xi-api-key" in call["kw"]["headers"])
    check("表单带 model_id=scribe_v1",
          (call["kw"].get("data") or {}).get("model_id") == "scribe_v1",
          call["kw"].get("data"))
    check("文件走 multipart", "file" in (call["kw"].get("files") or {}))
    norm = engine._asr_normalize_resp(out, None)
    check("词级 → 句级", (norm.get("segments") or [{}])[0].get("text") == "一句话。",
          norm.get("segments"))

    say("")
    say("== 7) Google Gemini（generateContent + inline_data）==")
    CALLS.clear()
    ROUTES.clear()
    ROUTES[":generateContent"] = _Resp(200, {"candidates": [
        {"content": {"parts": [{"text": "第一句。第二句。"}]}}]})
    out = engine._asr_gemini_submit(FakeASR(
        "https://generativelanguage.googleapis.com", "gemini-2.5-flash"))
    call = CALLS[-1]
    check("打到 models/<model>:generateContent",
          ":generateContent" in call["url"] and "gemini-2.5-flash" in call["url"],
          call["url"])
    check("鉴权用 x-goog-api-key", "x-goog-api-key" in call["kw"]["headers"])
    parts = call["kw"]["json"]["contents"][0]["parts"]
    check("音频以 inline_data + base64 传入",
          parts[0]["inline_data"]["data"] == base64.b64encode(WAV).decode())
    check("中文片源默认加逐字转写指令", "转写" in parts[1]["text"])
    norm = engine._asr_normalize_resp(out, None)
    check("纯文本按句切分", len(norm.get("segments") or []) == 2,
          norm.get("segments"))

    say("")
    say("== 7b) 火山引擎（豆包）录音识别极速版 ==")
    CALLS.clear()
    ROUTES.clear()
    ROUTES_GET.clear()
    ROUTES["recognize/flash"] = _Resp(
        200, {"audio_info": {"duration": 6312},
              "result": {"text": "刚刚还在想你。",
                         "utterances": [{"start_time": 480, "end_time": 5880,
                                         "text": "刚刚还在想你。"}]}},
        headers={"X-Api-Status-Code": "20000000"})
    out = engine._asr_volcengine_submit(FakeASR(
        "https://openspeech.bytedance.com", "volc.bigasr.auc_turbo",
        key="1234567890:my-access-token"))
    call = CALLS[-1]
    hdrs = call["kw"]["headers"]
    check("自动补 /api/v3/auc/bigmodel/recognize/flash",
          call["url"].endswith("/api/v3/auc/bigmodel/recognize/flash"),
          call["url"])
    check("旧版形态：APPID:Token 拆成两个头",
          hdrs.get("X-Api-App-Key") == "1234567890"
          and hdrs.get("X-Api-Access-Key") == "my-access-token")
    check("带 X-Api-Resource-Id / Request-Id / Sequence",
          hdrs.get("X-Api-Resource-Id") == "volc.bigasr.auc_turbo"
          and bool(hdrs.get("X-Api-Request-Id"))
          and hdrs.get("X-Api-Sequence") == "-1")
    import json as _json
    vbody = _json.loads(call["kw"]["data"])
    check("音频以 base64 放进 audio.data",
          vbody["audio"]["data"] == base64.b64encode(WAV).decode())
    check("show_utterances=true（才给时间轴）",
          vbody["request"].get("show_utterances") is True)
    vnorm = engine._asr_normalize_resp(out, None)
    vsegs = vnorm.get("segments") or []
    check("utterances 的毫秒时间轴已换算成秒",
          len(vsegs) == 1 and abs(vsegs[0]["start"] - 0.48) < 1e-6
          and abs(vsegs[0]["end"] - 5.88) < 1e-6, vsegs)

    CALLS.clear()
    engine._asr_volcengine_submit(FakeASR(
        "https://openspeech.bytedance.com", "volc.bigasr.auc_turbo",
        key="new-style-key"))
    check("新版形态：单个 API Key 走 X-Api-Key",
          CALLS[-1]["kw"]["headers"].get("X-Api-Key") == "new-style-key"
          and "X-Api-Access-Key" not in CALLS[-1]["kw"]["headers"])

    ROUTES["recognize/flash"] = _Resp(
        200, {}, headers={"X-Api-Status-Code": "45000001",
                          "X-Api-Message": "quota exceeded"})
    volc_fail = False
    try:
        engine._asr_volcengine_submit(FakeASR(
            "https://openspeech.bytedance.com", "volc.bigasr.auc_turbo",
            key="k:x"))
    except RuntimeError as e:
        volc_fail = "45000001" in str(e)
    check("非 20000000 的状态码按失败抛出（状态在响应头里）", volc_fail)

    say("")
    say("== 7c) AssemblyAI（上传 → 提交 → 轮询）==")
    CALLS.clear()
    ROUTES.clear()
    ROUTES_GET.clear()
    ROUTES["/v2/upload"] = _Resp(200, {"upload_url": "https://cdn/x.wav"})
    ROUTES["/v2/transcript"] = _Resp(200, {"id": "tid-123",
                                           "status": "queued"})
    ROUTES_GET["/v2/transcript/"] = _Resp(200, {
        "status": "completed", "text": "Hello world. 你好",
        "words": [{"text": "Hello", "start": 100, "end": 500},
                  {"text": "world.", "start": 500, "end": 900},
                  {"text": "你", "start": 1000, "end": 1200},
                  {"text": "好", "start": 1200, "end": 1400}]})
    _patch_sleep(True)
    try:
        out = engine._asr_assemblyai_submit(FakeASR(
            "https://api.assemblyai.com", "universal-3-pro,universal-2"))
    finally:
        _patch_sleep(False)
    up_call = CALLS[0]
    sub_call = [c for c in CALLS
                if c["method"] == "POST" and c["url"].endswith("/v2/transcript")][0]
    check("上传走 raw bytes（不是 multipart）",
          up_call["url"].endswith("/v2/upload")
          and up_call["kw"].get("data") == WAV)
    check("鉴权头 authorization 且不带 Bearer",
          up_call["kw"]["headers"].get("authorization") == "sk-test-1234")
    check("提交带 speech_models（官方必填）",
          sub_call["kw"]["json"].get("speech_models")
          == ["universal-3-pro", "universal-2"])
    check("本地文件先上传、再引用 upload_url",
          sub_call["kw"]["json"].get("audio_url") == "https://cdn/x.wav")
    check("轮询用 GET /v2/transcript/<id>",
          any(c["method"] == "GET" and "/v2/transcript/tid-123" in c["url"]
              for c in CALLS))
    anorm = engine._asr_normalize_resp(out, None)
    asegs = anorm.get("segments") or []
    check("词级毫秒时间轴 → 秒级句",
          len(asegs) == 2 and abs(asegs[0]["start"] - 0.1) < 1e-6
          and abs(asegs[0]["end"] - 0.9) < 1e-6, asegs)
    check("英文句点断句、中文不加空格",
          asegs and asegs[0]["text"] == "Hello world." and asegs[1]["text"] == "你好",
          [s["text"] for s in asegs])

    say("")
    say("== 8) 词级 → 句级 断句规则 ==")
    words = [{"word": w, "start": i * 0.3, "end": i * 0.3 + 0.25}
             for i, w in enumerate(["这", "是", "一句", "话"])]
    segs = engine._asr_words_to_segments(words)
    check("无标点无停顿时不断句（合成一条）", len(segs) == 1
          and segs[0]["text"] == "这是一句话", segs)
    words2 = [{"word": "好", "start": 0, "end": 0.3},
              {"word": "的", "start": 0.3, "end": 0.6},
              {"word": "我", "start": 2.2, "end": 2.5},      # 停顿 1.6s
              {"word": "知道", "start": 2.5, "end": 2.9}]
    segs2 = engine._asr_words_to_segments(words2)
    check("停顿超过 0.9s 断句", len(segs2) == 2, segs2)
    long_words = [{"word": "字", "start": i * 0.1, "end": i * 0.1 + 0.09}
                  for i in range(30)]
    check("超长自动断（按 42 字上限）",
          len(engine._asr_words_to_segments(long_words)) >= 1)
    dec = [{"word": "版本", "start": 0, "end": 0.3},
           {"word": "3.5", "start": 0.3, "end": 0.6},
           {"word": "倍", "start": 0.6, "end": 0.9}]
    check("小数点（3.5）不被当成句末",
          len(engine._asr_words_to_segments(dec)) == 1,
          engine._asr_words_to_segments(dec))
    dot = [{"word": "Version", "start": 0, "end": 0.3},
           {"word": "3.5.", "start": 0.3, "end": 0.6},
           {"word": "Next", "start": 0.6, "end": 0.9}]
    check("英文句末（3.5.）仍能断句",
          len(engine._asr_words_to_segments(dot)) == 2,
          engine._asr_words_to_segments(dot))
    check("is_end 逐例：world./3.5./12./a. 断；3.5/.5 不断",
          all(engine._asr_is_sentence_end(t)
              for t in ("world.", "3.5.", "12.", "a.", "一句话。"))
          and not any(engine._asr_is_sentence_end(t) for t in ("3.5", ".5")),
          [engine._asr_is_sentence_end(t)
           for t in ("world.", "3.5.", "12.", "a.", "3.5", ".5")])

    say("")
    say("== 8b) 超限音频自动压缩（Data URL / inline_data 载荷上限）==")
    orig_shrink = engine._asr_shrink_audio_blob
    engine._asr_shrink_audio_blob = (
        lambda blob, mr: (blob[:64] if len(blob) > mr else blob))
    try:
        big = WAV + b"\x00" * (7 * 1024 * 1024)   # 7MB 假音频（> chat_audio 6.5MB）
        CALLS.clear()
        ROUTES.clear()
        ROUTES["/chat/completions"] = _Resp(200, {"choices": [
            {"message": {"content": "ok"}}]})
        engine._asr_chat_audio_submit(FakeASR(
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "qwen3-asr-flash"))
        data = (CALLS[-1]["kw"]["json"]["messages"][0]["content"][0]
                ["input_audio"]["data"])
        check("chat_audio 超限音频被压缩后上传", len(data) < 200, len(data))
        CALLS.clear()
        ROUTES.clear()
        ROUTES[":generateContent"] = _Resp(200, {"candidates": [
            {"content": {"parts": [{"text": "ok"}]}}]})
        engine._asr_gemini_submit(FakeASR(
            "https://generativelanguage.googleapis.com", "gemini-2.5-flash"))
        parts = CALLS[-1]["kw"]["json"]["contents"][0]["parts"]
        check("gemini 超限音频同样先压缩",
              len(parts[0]["inline_data"]["data"]) < 200)
        CALLS.clear()
        ROUTES["/chat/completions"] = _Resp(200, {"choices": [
            {"message": {"content": "ok"}}]})
        engine._asr_chat_audio_submit(FakeASR(
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "qwen3-asr-flash"))
        data = (CALLS[-1]["kw"]["json"]["messages"][0]["content"][0]
                ["input_audio"]["data"])
        check("未超限音频原样上传（不动）",
              data == "data:audio/wav;base64,"
              + base64.b64encode(WAV).decode())
    finally:
        engine._asr_shrink_audio_blob = orig_shrink

    # 真实 ffmpeg 转码（tools 下自带二进制；转码失败会让断言红）
    import io as _io
    import math as _math
    import struct as _struct
    import wave as _wave
    buf = _io.BytesIO()
    with _wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        frames = bytearray()
        for i in range(8000 * 90):                    # 90 秒 8kHz → wav 1.44MB
            frames += _struct.pack(
                "<h", int(8000 * _math.sin(2 * _math.pi * 220 * i / 8000)))
        w.writeframes(bytes(frames))
    blob = buf.getvalue()
    shrunk = engine._asr_shrink_audio_blob(blob, 1_000_000)
    check("真实转码：90s 正弦 wav（1.44MB）→ ≤1MB mp3",
          len(shrunk) <= 1_000_000 and shrunk[:3] in (b"ID3", b"\xff\xfb",
                                                      b"\xff\xf3"),
          "%d bytes, head=%r" % (len(shrunk), shrunk[:4]))
    check("小音频不触发转码",
          engine._asr_shrink_audio_blob(WAV, 6_500_000) == WAV)
    check("压缩失败（坏数据）原样返回不炸",
          engine._asr_shrink_audio_blob(b"\x00" * 8_000_000, 1_000_000)
          == b"\x00" * 8_000_000)

    say("")
    say("== 8b2) 单次音频超长（The audio is too long）自动对半切分 ==")
    CALLS.clear()
    ROUTES.clear()
    _queue = [
        _Resp(400, None, '{"error":{"message":"<400> InternalError.Algo.'
                         'InvalidParameter: The audio is too long"}}'),
        _Resp(200, {"choices": [{"message": {"content": "前半段。"}}]}),
        _Resp(200, {"choices": [{"message": {"content": "后半段。"}}]}),
    ]

    def _route():
        return _queue.pop(0)

    ROUTES["/chat/completions"] = _route
    # 真实可解码的 4 秒音频：切分靠 ffmpeg，坏数据切不出两段
    _buf = _io.BytesIO()
    with _wave.open(_buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        frames = bytearray()
        for i in range(8000 * 4):
            frames += _struct.pack(
                "<h", int(8000 * _math.sin(2 * _math.pi * 220 * i / 8000)))
        w.writeframes(bytes(frames))
    _obj = FakeASR("https://dashscope.aliyuncs.com/compatible-mode/v1",
                   "qwen-audio-3.0-asr-flash")
    _obj.file_binary = _buf.getvalue()
    _obj.audio_duration = 4.0
    try:
        _out = engine._asr_chat_audio_submit(_obj)
        _split_ok = ("前半段" in str(_out) and "后半段" in str(_out))
        _extra = _out
    except Exception as _e:  # noqa: BLE001
        _split_ok, _extra = False, _e
    check("超长 400 → 自动对半切开、两段文本拼回", _split_ok, _extra)
    check("切分后共 3 次请求（1 次失败 + 2 段）", len(CALLS) == 3, len(CALLS))
    ROUTES["/chat/completions"] = _Resp(
        400, None, '{"error":{"message":"The audio is too long"}}')
    _deep_fail = False
    try:
        engine._asr_chat_audio_submit(_obj, 3)     # 已到递归上限
    except RuntimeError as _e:
        _deep_fail = "时长" in str(_e) or "too long" in str(_e).lower()
    check("递归到底仍失败时报可读错误（不再无限切）", _deep_fail)
    _hint = engine._asr_err_hint(_Resp(
        400, None, '{"error":{"message":"The audio is too long"}}'))
    check("too long 的提示指向切短/换模型", "时长" in _hint and "切短" in _hint,
          _hint[:70])

    say("")
    say("== 8b3) chat_audio 分块长度按协议压到 3 分钟内 ==")
    try:
        import importlib as _il
        # ⚠️ 同名函数覆盖了模块属性，必须按模块名取
        _tr = _il.import_module("videocaptioner.core.asr.transcribe")
        check("分块补丁已挂", engine.vc_asr_chunk_patch() is True
              and getattr(_tr, "_vt_chunk_patched", False) is True)
        _orig_p = engine.asr_protocol_of

        class _Cfg:
            need_word_time_stamp = False
            transcribe_language = ""
            whisper_api_model = "qwen-audio-3.0-asr-flash"
            whisper_api_key = "sk-x"
            whisper_api_base = "https://dashscope.aliyuncs.com/compatible-mode/v1"
            whisper_api_prompt = ""

        engine.asr_protocol_of = lambda *a, **k: "chat_audio"
        try:
            # ChunkedASR 构造只读字节、不解析音频，用脚本自身当"音频路径"
            _inst = _tr._create_whisper_api_asr(__file__, _Cfg())
        finally:
            engine.asr_protocol_of = _orig_p
        check("chat_audio：块长 170s（引擎默认 600s 会超百炼时长上限）",
              getattr(_inst, "chunk_length_ms", 0) == 170000,
              getattr(_inst, "chunk_length_ms", None))
    except Exception as _e:  # noqa: BLE001
        check("分块补丁用例", False, _e)

    say("")
    say("== 8c) 非中英字符占比（默认接口语言提示依据）==")
    check("纯中文 → 0", engine.asr_non_zh_en_ratio("你好，世界！") == 0.0)
    check("纯英文 → 0",
          engine.asr_non_zh_en_ratio("Hello, world! 123") == 0.0)
    jp = engine.asr_non_zh_en_ratio("こんにちは、世界です。今日はいい天気ですね。")
    check("纯日文 → 高占比（汉字计入中英，假名为主仍过半）", jp >= 0.6, jp)
    kr = engine.asr_non_zh_en_ratio("안녕하세요, 세계!")
    check("纯韩文 → 高占比", kr >= 0.8, kr)
    mix = engine.asr_non_zh_en_ratio("これはペンです and this is a pen 你好")
    check("混排按字符占比", 0.3 <= mix <= 0.7, mix)

    say("")
    say("== 9) 错误提示可操作 ==")
    h401 = engine._asr_err_hint(_Resp(401, None, '{"code":30014,'
                                            '"message":"Token is invalid."}'))
    check("401 提示指向密钥与「保存并应用」",
          "401" in h401 and "保存并应用" in h401, h401[:80])
    h400 = engine._asr_err_hint(_Resp(400, None,
                                      '{"code":"InvalidParameter",'
                                      '"message":"model not supported"}'))
    check("参数/模型名错误提示提到实时模型", "实时" in h400, h400[:80])
    hbig = engine._asr_err_hint(_Resp(
        400, None, "<400> InternalError.Algo.InvalidParameter: "
                   "Multimodal file size is too large"))
    check("体积超限提示给出切短/换模型建议",
          "体积" in hbig and "切短" in hbig, hbig[:80])

    say("")
    say("== 10) 引擎补丁已挂 + 分流清单 ==")
    ok = engine.vc_asr_protocol_patch()
    check("vc_asr_protocol_patch 返回 True", ok is True)
    try:
        from videocaptioner.core.asr.whisper_api import WhisperAPI
        check("WhisperAPI._submit 已被替换",
              getattr(WhisperAPI, "_vt_proto_patched", False) is True)

        # 实时模型 + 百炼系域名：协议被判成非实时（旧配置/旧进程常见）时
        # 必须自动改走 WebSocket，不能拿 OpenAI SDK 去打（服务端直接断连）
        obj = WhisperAPI.__new__(WhisperAPI)
        obj.base_url = ("https://llm-ukmkj60gxr2wms1f.cn-beijing."
                        "maas.aliyuncs.com/compatible-mode/v1")
        obj.model = "qwen3.8-livetranslate-flash-realtime"
        obj.api_key = "sk-test-1234"
        obj.language = ""
        obj.prompt = ""
        obj.file_binary = WAV
        # v1.15.5：实时对话/翻译模型不再进任何协议，_submit 直接拦下给改法
        try:
            obj._submit()
            _lt_block = None
        except RuntimeError as e:
            _lt_block = str(e)
        check("实时翻译模型在 _submit 被拦并给改法（不再等空体 400/500）",
              bool(_lt_block) and "实时对话/翻译" in _lt_block, _lt_block or "")
        # 换真实时转写模型，继续验证「非实时协议 → 自动改走 WebSocket」纠偏
        obj.model = "qwen3-asr-flash-realtime"
        _ws_log = {}
        _install_fake_websocket([
            {"header": {"event": "task-started"}, "payload": {}},
            {"header": {"event": "result-generated"},
             "payload": {"output": {"sentence": {"text": "你好",
                                                 "begin_time": 100,
                                                 "end_time": 900}}}},
            {"header": {"event": "task-finished"}, "payload": {}},
        ], _ws_log)
        engine._ASR_WS_DEGRADED = False
        orig_p = engine.asr_protocol_of
        engine.asr_protocol_of = lambda *a, **k: "openai"
        try:
            obj._submit()
        finally:
            engine.asr_protocol_of = orig_p
        check("实时模型+百炼域名：非实时协议自动改走 WebSocket（不再断连）",
              str(_ws_log.get("url", "")).startswith("wss://"),
              _ws_log.get("url"))

        # 百炼/兼容模式端点被判成 openai（旧配置/兜底）→ 改走 chat_audio
        obj.model = "qwen3-asr-flash"
        obj.language = ""
        obj.prompt = ""
        CALLS.clear()
        ROUTES.clear()
        ROUTES["/chat/completions"] = _Resp(200, {"choices": [
            {"message": {"content": "你好。"}}]})
        orig_p = engine.asr_protocol_of
        engine.asr_protocol_of = lambda *a, **k: "openai"
        try:
            obj._submit()
        finally:
            engine.asr_protocol_of = orig_p
        check("百炼端点+openai 协议 → 自动改走 chat/completions（不再断连）",
              CALLS and CALLS[-1]["url"].endswith("/chat/completions"),
              (CALLS or [{}])[-1].get("url"))
        check("非 openai 协议不再注入中文提示词（专属实例混合输入会 400）",
              obj.prompt == "", obj.prompt)

        # v1.15.6：原生端点专用模型被判成 openai/chat_audio → 改走原生端点
        obj.model = "qwen-audio-3.0-asr-flash"
        CALLS.clear()
        ROUTES.clear()
        ROUTES["multimodal-generation/generation"] = _Resp(
            200, {"output": {"sentence": {"text": "原生端点你好。"}}})
        orig_p = engine.asr_protocol_of
        engine.asr_protocol_of = lambda *a, **k: "openai"
        try:
            _nres = obj._submit()
        finally:
            engine.asr_protocol_of = orig_p
        check("百炼端点+openai 协议+原生 ASR 模型 → 自动改走原生端点",
              CALLS and engine.ASR_NATIVE_PATH in CALLS[-1]["url"],
              (CALLS or [{}])[-1].get("url"))
        check("改走原生端点后能出文本（不再空体 400）",
              (_nres or {}).get("text") == "原生端点你好。", _nres)
    except Exception as e:  # noqa: BLE001
        check("引擎可导入（跳过补丁断言）", False, e)
    check("协议清单含 12 条实现 + auto（dashscope 为历史键、同实现）",
          set(engine.ASR_PROTOCOLS) == {"auto", "openai", "azure", "chat_audio",
                                        "dashscope", "deepgram", "elevenlabs",
                                        "gemini", "volcengine", "assemblyai",
                                        "dashscope_realtime",
                                        "dashscope_native"},
          engine.ASR_PROTOCOLS)
    check("每条协议都有说明文案",
          all(k in engine.ASR_PROTOCOL_NOTES
              for k in engine.ASR_PROTOCOLS if k != "auto"))

    say("")
    say("== 10b) 协议解析兜底（不再盲返 openai）==")
    orig_aimod = engine.ai_mod
    orig_load = engine.ai_load_config

    class _Boom:
        def asr_config(self, *a, **k):
            raise RuntimeError("boom")

    engine.ai_mod = lambda: _Boom()
    engine.ai_load_config = lambda: {
        "asr_base_url": ("https://llm-ukmkj60gxr2wms1f.cn-beijing."
                         "maas.aliyuncs.com/compatible-mode/v1"),
        "asr_model": "qwen3.8-livetranslate-flash-realtime"}
    try:
        got = engine.asr_protocol_of()
    finally:
        engine.ai_mod = orig_aimod
        engine.ai_load_config = orig_load
    check("配置读取失败时按磁盘字段推断（实时模型仍落实时协议）",
          got == "dashscope_realtime", got)

    say("")
    say("== 11) 非流式调用示例（curl / Python）==")
    EX_CASES = [
        ("openai", "https://api.siliconflow.cn/v1", "whisper-1",
         ["/audio/transcriptions", "Bearer", "openai"]),
        ("azure", "https://myres.openai.azure.com", "whisper",
         ["/openai/deployments/", "api-key", "AzureOpenAI"]),
        ("dashscope", "https://dashscope.aliyuncs.com/compatible-mode/v1",
         "qwen3-asr-flash",
         ["/chat/completions", "input_audio", "stream=False", "data:audio/"]),
        ("deepgram", "https://api.deepgram.com", "nova-3",
         ["/v1/listen", "Token", "transcript", "words"]),
        ("elevenlabs", "https://api.elevenlabs.io", "scribe_v1",
         ["/v1/speech-to-text", "xi-api-key", "speech_to_text"]),
        ("gemini", "https://generativelanguage.googleapis.com",
         "gemini-2.5-flash",
         [":generateContent", "x-goog-api-key", "inline_data"]),
        ("volcengine", "https://openspeech.bytedance.com",
         "volc.bigasr.auc_turbo",
         ["recognize/flash", "X-Api-Resource-Id", "X-Api-Status-Code"]),
        ("assemblyai", "https://api.assemblyai.com", "universal-3-pro",
         ["/v2/upload", "/v2/transcript", "authorization", "speech_models"]),
    ]
    SECRET = "sk-SECRET-must-not-leak"
    leaks = []
    for proto, base, model, wants in EX_CASES:
        cfg2 = {"asr_mode": "service", "asr_base_url": base,
                "asr_model": model, "asr_api_key": SECRET,
                "asr_protocol": proto}
        ex = engine.asr_examples(cfg2)
        text = engine.asr_examples_text(cfg2)
        miss = [w for w in wants if w not in text]
        check("示例 %s：要点齐全且两版都有" % proto,
              not miss and bool(ex.get("curl")) and bool(ex.get("python")),
              ("缺 " + str(miss)) if miss else "ok")
        check("示例 %s：标了「非流式」" % proto, "非流式" in text)
        if SECRET in text:
            leaks.append(proto)
    check("示例不泄露密钥明文（只给环境变量占位）", not leaks, leaks)

    exl = engine.asr_examples({"asr_mode": "local",
                               "asr_local_model": "large-v3",
                               "asr_local_model_dir": ""})
    check("本地模式：说明不涉及 HTTP，并给 faster-whisper 片段",
          exl.get("protocol") == "local"
          and "faster_whisper" in exl.get("python", "")
          and "HTTP" in exl.get("curl", ""))

    say("")
    say("== 12) 地址栏填「完整端点」也能用（智谱那类）==")
    ZP = "https://open.bigmodel.cn/api/paas/v4/audio/transcriptions"
    check("削尾：完整端点 → base",
          engine.asr_strip_endpoint_tail(ZP)
          == "https://open.bigmodel.cn/api/paas/v4",
          engine.asr_strip_endpoint_tail(ZP))
    check("削尾：本来就是 base 的地址保持不变",
          engine.asr_strip_endpoint_tail("https://api.openai.com/v1")
          == "https://api.openai.com/v1")
    check("削尾：重复尾巴一次削干净",
          engine.asr_strip_endpoint_tail(ZP + "/audio/transcriptions")
          == "https://open.bigmodel.cn/api/paas/v4",
          engine.asr_strip_endpoint_tail(ZP + "/audio/transcriptions"))
    check("削尾：chat/completions 与 assemblyai 端点同样处理",
          engine.asr_strip_endpoint_tail("https://x/v1/chat/completions")
          == "https://x/v1"
          and engine.asr_strip_endpoint_tail(
              "https://api.assemblyai.com/v2/transcript")
          == "https://api.assemblyai.com")

    _zg = engine.asr_examples({"asr_mode": "service", "asr_base_url": ZP,
                               "asr_api_key": "k", "asr_model": "glm-asr-2512",
                               "asr_protocol": "auto"})
    check("智谱地址（auto）识别为 openai 协议",
          _zg["protocol"] == "openai", _zg["protocol"])
    check("示例 URL 不会重复拼接 /audio/transcriptions",
          _zg["curl"].count("/audio/transcriptions") == 1,
          [ln for ln in _zg["curl"].splitlines() if "curl" in ln])
    check("探测地址也先削尾（不再拼成 …/transcriptions/v1/models）",
          aim._models_url(ZP) == "https://open.bigmodel.cn/api/paas/v4/models",
          aim._models_url(ZP))

    say("")
    say("== 13) 地址守卫与模型存在性核对 ==")
    g = engine.asr_base_guard(
        "https://llm-xxx.cn-beijing.maas.aliyuncs.com/apps/anthropic")
    check("Anthropic 端点被点名并给出正确填法",
          "Anthropic" in g and "compatible-mode" in g, g[:70])
    check("正常地址不受地址守卫影响",
          engine.asr_base_guard(
              "https://dashscope.aliyuncs.com/compatible-mode/v1") == "")
    say("")
    say("== 13b) 套餐端点与实时对话模型守卫（v1.15.5）==")
    _vg = engine.asr_base_guard("https://ark.cn-beijing.volces.com/api/coding")
    check("火山 Anthropic-only 端点 /api/coding 被地址守卫点名并给出 v3 改法",
          "v3" in _vg, _vg[:70])
    check("火山 OpenAI 协议 /api/coding/v3 不受地址守卫影响",
          engine.asr_base_guard(
              "https://ark.cn-beijing.volces.com/api/coding/v3") == "")
    check("实时翻译模型不论协议都被硬守卫拦下",
          bool(engine.asr_model_hard_guard(
              "qwen3.8-livetranslate-flash-realtime")))
    check("实时转写模型不受硬守卫影响",
          engine.asr_model_hard_guard("qwen3-asr-flash-realtime") == "")
    check("TTS 模型被硬守卫点名「语音合成」",
          "语音合成" in engine.asr_model_hard_guard("qwen-audio-3.0-tts-plus"))
    check("ASR 族 qwen-audio-3.0-asr-flash 不被硬守卫误伤",
          engine.asr_model_hard_guard("qwen-audio-3.0-asr-flash") == "")
    check("套餐端点配套提示对 Token Plan 非空、对普通端点为空",
          bool(engine._asr_plan_endpoint_hint(type(
              "_o", (), {"base_url": "https://token-plan.cn-beijing.maas."
                                     "aliyuncs.com/compatible-mode/v1"})()))
          and engine._asr_plan_endpoint_hint(type(
              "_o2", (), {"base_url": "https://api.siliconflow.cn/v1"})()) == "")
    try:
        aim.AIClient({"base_url": "https://ark.cn-beijing.volces.com/api/coding",
                      "api_key": "k", "model": "m"})
        _volc_block = False
    except aim.AIClientError:
        _volc_block = True
    check("ai_client 对火山 Anthropic-only 端点同样拦截", _volc_block)
    check("百炼 Token Plan 端点拼出 chat/completions",
          aim._chat_url("https://token-plan.cn-beijing.maas.aliyuncs.com/"
                        "compatible-mode/v1").endswith("/chat/completions"))
    check("硬守卫接入连通性自检（测试连接直接给改法）",
          aim.asr_test_connection({
              "asr_mode": "service", "asr_protocol": "auto",
              "asr_base_url": "https://ws-x.cn-beijing.maas.aliyuncs.com/"
                              "compatible-mode/v1",
              "asr_api_key": "k",
              "asr_model": "qwen3.8-livetranslate-flash-realtime"})[0] is False)
    hit, names = aim.asr_model_visible(
        json.dumps({"data": [{"id": "mimo-v2.5-asr"},
                             {"id": "qwen3-asr-flash"}]}),
        "mimo-v2.5-asr")
    check("配置的模型在列表里 → 判定可见", hit is True and len(names) == 2)
    hit2, _ = aim.asr_model_visible(
        json.dumps({"data": [{"id": "qwen3-asr-flash"}]}),
        "fun-asr-flash-8k-realtime")
    check("模型不在列表里 → 明确判定不可见（实例没部署）", hit2 is False)
    hit3, _ = aim.asr_model_visible(
        json.dumps({"data": [{"id": "FunAudioLLM/SenseVoiceSmall"}]}),
        "SenseVoiceSmall")
    check("带组织前缀的模型按末段匹配", hit3 is True)
    hit4, _ = aim.asr_model_visible("not-json", "x")
    check("列表解析不了时不判定（None，不误报）", hit4 is None)

    say("")
    say("== 13c) 百炼原生协议 + maas 列表核对不可信（v1.15.6）==")
    _maas = "https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
    _native_url = ("https://token-plan.cn-beijing.maas.aliyuncs.com"
                   + engine.ASR_NATIVE_PATH)
    check("_is_maas_base 认 token-plan/专属实例、放过公共百炼",
          aim._is_maas_base(_maas)
          and aim._is_maas_base("https://llm-x.cn-beijing.maas.aliyuncs.com")
          and not aim._is_maas_base(
              "https://dashscope.aliyuncs.com/compatible-mode/v1"))
    check("原生端点专用 ASR 模型识别（两侧同规则，不误伤 tts/realtime/filetrans）",
          engine.is_dashscope_native_asr("qwen-audio-3.0-asr-flash")
          and aim.is_dashscope_native_asr("qwen-audio-3.0-asr-flash")
          and not engine.is_dashscope_native_asr("qwen-audio-3.0-tts-plus")
          and not engine.is_dashscope_native_asr(
              "qwen-audio-3.0-asr-flash-filetrans")
          and not engine.is_dashscope_native_asr("qwen3-asr-flash"))
    check("auto 推断：百炼系 + qwen-audio-3.0-asr-flash → dashscope_native"
          "（引擎/ai_client 一致）",
          engine._infer_asr_protocol(_maas, "qwen-audio-3.0-asr-flash")
          == "dashscope_native"
          and aim.resolve_asr_protocol({"base_url": _maas,
                                        "model": "qwen-audio-3.0-asr-flash",
                                        "protocol": "auto"}) == "dashscope_native"
          and engine._infer_asr_protocol(
              "https://dashscope.aliyuncs.com/compatible-mode/v1",
              "qwen-audio-3.0-asr-flash") == "dashscope_native", "")
    check("显式 chat_audio + 原生模型 → 纠偏改走原生协议（否则恒 400 空体）",
          engine.asr_protocol_fix("chat_audio", _maas,
                                  "qwen-audio-3.0-asr-flash")[0]
          == "dashscope_native")
    check("原生端点 URL 推导：兼容模式/裸域名换路径、已填原生端点不重复",
          engine._asr_native_url(_maas) == _native_url
          and engine._asr_native_url("https://dashscope.aliyuncs.com")
          == "https://dashscope.aliyuncs.com" + engine.ASR_NATIVE_PATH
          and engine._asr_native_url(_native_url) == _native_url, "")

    # ---- 原生端点请求构造 + 响应解析（响应没有 choices）----
    CALLS.clear()
    ROUTES.clear()
    _native_payload = {
        "sentence": {"sentence_id": 1, "begin_time": 600, "end_time": 1800,
                     "text": "你好世界。",
                     "words": [{"text": "你好", "punctuation": "，",
                                "begin_time": 600, "end_time": 1000},
                               {"text": "世界", "punctuation": "。",
                                "begin_time": 1000, "end_time": 1800}]},
        "text": "你好世界。",
        "output": {"sentence": {"begin_time": 600, "end_time": 1800,
                                "text": "你好世界。",
                                "words": [{"text": "你好", "punctuation": "，",
                                           "begin_time": 600, "end_time": 1000},
                                          {"text": "世界", "punctuation": "。",
                                           "begin_time": 1000,
                                           "end_time": 1800}]}},
    }
    ROUTES["multimodal-generation/generation"] = _Resp(200, _native_payload)
    _nat = engine._asr_dashscope_native_submit(
        FakeASR(_maas, "qwen-audio-3.0-asr-flash"))
    _ncall = CALLS[-1]
    _nbody = _ncall["kw"].get("json") or {}
    _ndata = _nbody["input"]["messages"][0]["content"][0]["input_audio"]["data"]
    check("打到百炼原生端点（不是 chat/completions）",
          _ncall["url"] == _native_url and engine.ASR_NATIVE_PATH in _ncall["url"],
          _ncall["url"])
    check("音频以 base64 Data URL 进 input.messages",
          _ndata.startswith("data:audio/wav;base64,") and len(_ndata) > 40)
    check("parameters 带 format / sample_rate（官方要求）",
          _nbody["parameters"].get("format") == "wav"
          and _nbody["parameters"].get("sample_rate") == "16000",
          _nbody.get("parameters"))
    _nsegs = (_nat or {}).get("segments") or []
    check("响应无 choices 也拿到文本 + 词级时间轴（毫秒→秒）",
          (_nat or {}).get("text") == "你好世界。"
          and _nsegs and abs(_nsegs[0]["start"] - 0.6) < 1e-6
          and abs(_nsegs[0]["end"] - 1.8) < 1e-6, _nsegs)
    check("词级文本带标点（punctuation 独立字段已合并）",
          "你好" in _nsegs[0]["text"] or "你好，" in _nsegs[0]["text"],
          _nsegs[0]["text"] if _nsegs else "")

    # ---- chat_audio 空体 → 原生端点兜底（Fun-ASR-Flash 等）----
    check("_asr_empty_body_err 只认空体 400/500",
          engine._asr_empty_body_err("HTTP 400: {}")
          and engine._asr_empty_body_err(
              "HTTP 400（端点返回空体/未知错误：…）: {}")
          and not engine._asr_empty_body_err("HTTP 401: bad key"))
    CALLS.clear()
    ROUTES.clear()
    ROUTES["multimodal-generation/generation"] = _Resp(
        200, {"output": {"sentence": {"text": "兜底成功。"}}})
    _fb = engine._asr_retry_native(FakeASR(_maas, "fun-asr-flash"),
                                   "HTTP 400: {}")
    check("chat_audio 空体失败 → 原生端点兜底并取到文本",
          (_fb or {}).get("text") == "兜底成功。", _fb)
    _fb_obj = FakeASR(_maas, "fun-asr-flash")
    engine._asr_retry_native(_fb_obj, "HTTP 400: {}")
    try:
        engine._asr_retry_native(_fb_obj, "HTTP 400: {}")
        _once = False
    except RuntimeError as e:
        _once = "HTTP 400" in str(e)
    check("同一任务只兜一次（_vt_native_retried 生效，不再反复打）", _once)

    # ---- 测试连接：原生协议走真实语音探测，不再按 /models 判死 ----
    _asr_cfg = {"asr_mode": "service", "asr_protocol": "auto",
                "asr_base_url": _maas, "asr_api_key": "k",
                "asr_model": "qwen-audio-3.0-asr-flash"}
    _orig_native_probe = aim._asr_native_probe
    try:
        aim._asr_native_probe = lambda *a, **k: (True, "hello world，这里是阿里巴巴语音实验室。")
        _p1 = aim.asr_test_connection(dict(_asr_cfg))
        check("原生协议实测识别通过 → 判正常并回显识别文本",
              _p1[0] is True and "实测识别通过" in _p1[1], _p1[1][:90])
        aim._asr_native_probe = lambda *a, **k: ("missing", "HTTP 404: Model not exist.")
        _p2 = aim.asr_test_connection(dict(_asr_cfg))
        check("原生探测 404 → 判不可用并引导控制台/公共百炼",
              _p2[0] is False and "不存在" in _p2[1] and "控制台" in _p2[1],
              _p2[1][:90])
        aim._asr_native_probe = lambda *a, **k: (None, "网络错误")
        _p3 = aim.asr_test_connection(dict(_asr_cfg))
        check("原生探测网络失败 → 判连通但不夸大结论",
              _p3[0] is True and "主动探测未完成" in _p3[1], _p3[1][:90])
        aim._asr_native_probe = lambda *a, **k: (False, "HTTP 403: forbidden")
        _p4 = aim.asr_test_connection(dict(_asr_cfg))
        check("原生探测被拒（403）→ 判不可用并说明原因",
              _p4[0] is False and "探测识别被拒" in _p4[1], _p4[1][:90])
    finally:
        aim._asr_native_probe = _orig_native_probe

    class _FakeModelsResp:
        """伪装 /models 响应（context manager 形态，与 urllib 一致）。"""
        def __init__(self, body):
            self._b = body
        def read(self):
            return self._b
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False

    # /models 返回不含 ASR 模型的列表（复刻 token-plan 实测：只有非 ASR 模型）
    _fake_models = json.dumps({"data": [
        {"id": "deepseek-v4-pro"}, {"id": "glm-5.3"},
        {"id": "qwen-audio-3.0-realtime-plus"},
        {"id": "qwen-audio-3.0-tts-plus"}]}).encode()
    # ⚠️ mock 点必须是 ai_client 自己的 urlopen_endpoint：国内端点会走
    # build_opener(空 ProxyHandler) 强制直连，不再经过 urllib.request.urlopen。
    _orig_urlopen = aim.urlopen_endpoint
    try:
        aim.urlopen_endpoint = (
            lambda req, timeout=0: _FakeModelsResp(_fake_models))
        _r5 = aim.asr_test_connection({
            "asr_mode": "service", "asr_protocol": "auto",
            "asr_base_url": _maas, "asr_api_key": "k",
            "asr_model": "qwen3-asr-flash"})
        check("maas + chat_audio 模型不在列表 → 不再误判「没有可用 ASR 模型」",
              _r5[0] is True and "列表核对不可信" in _r5[1], _r5[1][:90])
        _r6 = aim.asr_test_connection({
            "asr_mode": "service", "asr_protocol": "auto",
            "asr_base_url": "https://api.example.com/v1",
            "asr_api_key": "k", "asr_model": "qwen3-asr-flash"})
        check("非 dashscope 网关不在列表 → 维持原「看不到模型」判定",
              _r6[0] is False and "看不到模型" in _r6[1], _r6[1][:90])
    finally:
        aim.urlopen_endpoint = _orig_urlopen

    # ---- 系统代理劫持回归（v1.15.6）------------------------------------
    # 实测：requests/urllib 默认 trust_env，Windows 下读注册表 Internet
    # Settings，把 FlClash 的 127.0.0.1:7890 套给国内百炼端点；该订阅规则
    # 兜底 MATCH,SELECT ⇒ 走海外节点 ⇒ ProxyError/RemoteDisconnected。
    say("")
    say("== 13d) 系统代理劫持：国内端点强制直连 ==")
    _dom = ("https://token-plan.cn-beijing.maas.aliyuncs.com/x",
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "https://openspeech.bytedance.com/api/v3/auc",
            "https://open.bigmodel.cn/api/paas/v4")
    _abroad = ("https://api.openai.com/v1/audio/transcriptions",
               "https://api.deepgram.com/v1/listen",
               "https://api.elevenlabs.io/v1/speech-to-text")
    check("引擎：国内端点（百炼/火山/智谱）一律显式直连",
          all(engine.http_proxies_for(u) == {"http": None, "https": None,
                                              "all": None}
              for u in _dom),
          str([engine.http_proxies_for(u) for u in _dom]))
    check("直连取值含 all 键（只写 http/https 挡不住 ALL_PROXY）",
          all("all" in (engine.http_proxies_for(u) or {}) for u in _dom), "")
    check("ai_client：同一批国内端点判为直连",
          all(aim.is_domestic_ai_endpoint(u) for u in _dom), "")
    check("引擎：国外端点仍跟随系统代理（它们反而需要代理）",
          all(engine.http_proxies_for(u) is None for u in _abroad),
          str([engine.http_proxies_for(u) for u in _abroad]))
    check("ai_client：国外端点不被误判为国内",
          not any(aim.is_domestic_ai_endpoint(u) for u in _abroad), "")
    check("两侧国内端点后缀清单逐项相同（引擎 vs ai_client）",
          tuple(engine.DOMESTIC_AI_ENDPOINT_SUFFIXES)
          == tuple(aim.DOMESTIC_AI_ENDPOINT_SUFFIXES),
          str(aim.DOMESTIC_AI_ENDPOINT_SUFFIXES))

    # ---- 调用示例（设置页「查看示例」弹窗）也要跟着原生端点 ----
    _ex = engine.asr_examples({"asr_mode": "service", "asr_protocol": "auto",
                               "asr_base_url": _maas, "asr_api_key": "k",
                               "asr_model": "qwen-audio-3.0-asr-flash"})
    check("示例生成：原生模型 → 协议判为 dashscope_native，"
          "curl 打 multimodal-generation 而非 chat/completions",
          _ex["protocol"] == "dashscope_native"
          and engine.ASR_NATIVE_PATH in _ex["curl"]
          and "chat/completions" not in _ex["curl"], _ex["protocol"])
    check("示例标题有中文名（不再露出原始协议串）",
          "原生" in _ex["title"], _ex["title"])
    _ex2 = engine.asr_examples({"asr_mode": "service", "asr_protocol": "auto",
                                "asr_base_url": _maas, "asr_api_key": "k",
                                "asr_model": "qwen3-asr-flash"})
    check("qwen3-asr-flash 示例仍走 chat_audio（原生分支不误伤兼容模式模型）",
          _ex2["protocol"] == "chat_audio"
          and "/chat/completions" in _ex2["curl"], _ex2["protocol"])

    say("")
    say("== 14) 百炼实时（WebSocket）协议 ==")
    _ws_script = [
        {"header": {"event": "task-started"}, "payload": {}},
        {"header": {"event": "result-generated"},
         "payload": {"output": {"sentence": {"text": "你",
                                             "begin_time": 100,
                                             "end_time": None}}}},   # 中间态
        {"header": {"event": "result-generated"},
         "payload": {"output": {"sentence": {"text": "你好，",
                                             "begin_time": 100,
                                             "end_time": 900}}}},
        {"header": {"event": "result-generated"},
         "payload": {"output": {"sentence": {"text": "世界。",
                                             "begin_time": 900,
                                             "end_time": 1500}}}},
        {"header": {"event": "task-finished"}, "payload": {}},
    ]
    _ws_log = {}
    _install_fake_websocket(_ws_script, _ws_log)
    out = engine._asr_dashscope_realtime_submit(FakeASR(
        "https://llm-ukmkj60gxr2wms1f.cn-beijing.maas.aliyuncs.com",
        "fun-asr-flash-8k-realtime", key="sk-demo"))
    check("专属实例域名 → wss://…/api-ws/v1/inference/",
          _ws_log["url"] == "wss://llm-ukmkj60gxr2wms1f.cn-beijing."
                            "maas.aliyuncs.com/api-ws/v1/inference/",
          _ws_log["url"])
    check("握手带 Bearer 鉴权",
          str(_ws_log["header"].get("Authorization", "")).startswith("Bearer "))
    sent = _ws_log.get("sent", [])
    first = json.loads(sent[0])
    check("首帧是 run-task（audio/asr/recognition，duplex）",
          first["header"]["action"] == "run-task"
          and first["payload"]["task_group"] == "audio"
          and first["payload"]["function"] == "recognition"
          and first["header"]["streaming"] == "duplex")
    check("模型与音频格式进 parameters",
          first["payload"]["model"] == "fun-asr-flash-8k-realtime"
          and first["payload"]["parameters"]["format"] == "wav")
    bins = [x for x in sent if isinstance(x, bytes)]
    check("音频以二进制帧发送且完整无缺", bins and b"".join(bins) == WAV)
    check("发完音频后发 finish-task",
          any(isinstance(x, str) and "finish-task" in x for x in sent))
    check("结束显式关闭连接", _ws_log.get("closed") is True)
    wnorm = engine._asr_normalize_resp(out, None)
    wsegs = wnorm.get("segments") or []
    check("中间态（无 end_time）不算句，只收最终句",
          len(wsegs) == 2 and [s["text"] for s in wsegs] == ["你好，", "世界。"],
          wsegs)
    check("句级时间轴来自原生 begin/end（毫秒→秒）",
          abs(wsegs[0]["start"] - 0.1) < 1e-6
          and abs(wsegs[0]["end"] - 0.9) < 1e-6, wsegs)
    check("auto 识别：百炼域名 + realtime 模型 → 实时协议",
          engine._infer_asr_protocol(
              "https://llm-x.cn-beijing.maas.aliyuncs.com",
              "fun-asr-flash-8k-realtime") == "dashscope_realtime")
    check("auto 识别：公共百炼 + 非实时模型 → 仍是 chat_audio",
          engine._infer_asr_protocol(
              "https://dashscope.aliyuncs.com/compatible-mode/v1",
              "qwen3-asr-flash") == "chat_audio")
    _ws_fail_log = {}
    _install_fake_websocket([{"header": {"event": "task-failed",
                                         "error_code": "Throttling",
                                         "error_message": "请求过于频繁"},
                              "payload": {}}], _ws_fail_log)
    ws_failed = False
    try:
        engine._asr_dashscope_realtime_submit(FakeASR(
            "https://dashscope.aliyuncs.com", "fun-asr-realtime"))
    except RuntimeError as e:
        ws_failed = "Throttling" in str(e)
    check("task-failed 的错误码/信息透传给用户", ws_failed)

    say("")
    say("== 13) 小米 MiMo（mimo-v2.5-asr）==")
    MIMO = "https://api.xiaomimimo.com/v1"
    check("auto 判为 chat_audio（**不是** openai：MiMo 没有 /audio/transcriptions）",
          engine._infer_asr_protocol(MIMO, "mimo-v2.5-asr") == "chat_audio",
          engine._infer_asr_protocol(MIMO, "mimo-v2.5-asr"))
    CALLS.clear()
    ROUTES.clear()
    ROUTES_GET.clear()
    ROUTES["/chat/completions"] = _Resp(200, {"choices": [
        {"message": {"content": "小米语音识别结果。"}}]})
    out = engine._asr_chat_audio_submit(FakeASR(MIMO, "mimo-v2.5-asr"))
    call = CALLS[-1]
    mbody = call["kw"].get("json") or {}
    check("打到 /v1/chat/completions",
          call["url"].endswith("/chat/completions"), call["url"])
    check("Bearer 鉴权",
          call["kw"]["headers"].get("Authorization", "").startswith("Bearer "))
    check("input_audio 用 Data URL",
          mbody["messages"][0]["content"][0]["input_audio"]["data"]
          .startswith("data:audio/wav;base64,"))
    check("显式 stream=False（非流式）", mbody.get("stream") is False)
    mnorm = engine._asr_normalize_resp(out, None)
    check("只回纯文本时按句切分（不会崩）",
          (mnorm.get("segments") or [{}])[0].get("text") == "小米语音识别结果。",
          mnorm.get("segments"))
    mm = engine.asr_examples({"asr_mode": "service", "asr_base_url": MIMO,
                              "asr_model": "mimo-v2.5-asr",
                              "asr_api_key": "k", "asr_protocol": "auto"})
    check("MiMo 示例：协议 chat_audio 且提醒没有 /audio/transcriptions",
          mm["protocol"] == "chat_audio"
          and "没有" in " ".join(mm["notes"]), mm["protocol"])
    check("MiMo 不是实时模型（不会被守卫误拦）",
          engine.asr_model_guard("mimo-v2.5-asr") == "")

    say("== 14) 协议纠偏（双向）==")
    _MAAS = ("https://llm-ukmkj60gxr2wms1f.cn-beijing.maas.aliyuncs.com"
             "/compatible-mode/v1")
    p, note = engine.asr_protocol_fix("dashscope_realtime", _MAAS,
                                      "qwen-audio-3.0-asr-flash-filetrans")
    check("文件识别模型 + 实时协议 → 改走 chat_audio（否则服务端只回 url error）",
          p == "chat_audio" and "不是实时模型" in note, (p, note[:36]))
    p, note = engine.asr_protocol_fix("dashscope_realtime", _MAAS,
                                      "fun-asr-flash-realtime")
    check("真实时模型 + 实时协议 → 不纠偏", p == "dashscope_realtime" and not note)
    p, note = engine.asr_protocol_fix("dashscope_realtime", _MAAS,
                                      "qwen3-asr-flash-realtime")
    check("qwen3 实时模型 → 不纠偏", p == "dashscope_realtime" and not note)
    p, note = engine.asr_protocol_fix("openai", _MAAS, "qwen3-asr-flash")
    check("openai 协议 + 百炼端点 → 仍按推断改走 chat_audio（旧纠偏不退化）",
          p == "chat_audio" and "openai" in note, (p, note[:30]))
    p, note = engine.asr_protocol_fix("chat_audio", _MAAS, "qwen3-asr-flash")
    check("正常组合不纠偏", p == "chat_audio" and not note)
    p, note = engine.asr_protocol_fix("openai", "https://api.openai.com/v1",
                                      "whisper-1")
    check("纯 openai 组合不误伤", p == "openai" and not note)


try:
    main()
except Exception as exc:  # noqa: BLE001
    import traceback
    LINES.append("!! 异常中断：%s" % exc)
    LINES.append(traceback.format_exc())
    FAILS.append("异常中断")

head = "PASS=%d FAIL=%d" % (
    sum(1 for ln in LINES if ln.startswith("  [PASS]")), len(FAILS))
with open(os.path.join(OUT, "result.txt"), "w", encoding="utf-8") as fh:
    fh.write(head + "\n" + "\n".join(LINES))
    if FAILS:
        fh.write("\n--- FAILS ---\n" + "\n".join("  " + x for x in FAILS))
