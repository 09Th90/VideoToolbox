# @version 2.8.0
"""OpenAI 兼容 ASR 的 HTTP 传输层（自研）。

P2 接缝配套模块：``engine_asr.WhisperAPI`` 只管协议语义（字段、缓存键、
时间戳分支），真正的 multipart 上传放在这里。

为什么单列
----------
1. **可独立测试**：传输层用「假 HTTP 服务」就能覆盖（字段名、boundary、
   Authorization 头、错误响应），不必真调 ASR 服务。
2. **零强制依赖**：``requests`` 有就用（跟随项目代理策略），没有则退回标准库
   ``urllib``——与 ``calib_media_agent._multipart_post`` 同一套写法，
   后者是本项目既有的「零依赖 multipart」事实来源。

协议要点（OpenAI ``/audio/transcriptions``）
--------------------------------------------
* ``response_format=verbose_json`` 才会返回 ``segments``（含 start/end）与
  可选 ``words``（词级时间戳）；``json`` 格式只有纯文本，无法出字幕。
* ``timestamp_granularities=["word","segment"]`` 要与 verbose_json 同时用；
  部分服务端不支持该字段，会在**表单校验**阶段报错，因此按需携带。
* ``language`` 为空表示自动检测 ⇒ **不传该字段**（传空串可能被服务端判为非法）。
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

__all__ = ["post_transcription", "transcription_url", "AsrHttpError"]

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")


class AsrHttpError(RuntimeError):
    """ASR 服务端返回错误。

    与 ``RuntimeError`` 同族，便于上层 ``except RuntimeError`` 兜底，
    同时保留 ``status`` / ``body`` 供日志定位。
    """

    def __init__(self, message, status=None, body=""):
        super().__init__(message)
        self.status = status
        self.body = body


def transcription_url(base_url: str) -> str:
    """由 base_url 推出转写端点。"""
    u = (base_url or "").strip().rstrip("/")
    if not u:
        raise AsrHttpError("ASR base_url 为空")
    if u.endswith("/audio/transcriptions"):
        return u
    if u.endswith("/audio"):
        return u + "/transcriptions"
    return u + "/audio/transcriptions"


def _multipart_body(fields, files):
    """零依赖拼 multipart/form-data。fields 为 ``[(名, 值)]``。"""
    boundary = "----vtAsr%d" % (time.time() * 1000)
    body = bytearray()
    for name, value in fields:
        if value is None:
            continue                      # 空值不传（自动检测语言即靠此）
        body += (
            '--%s\r\nContent-Disposition: form-data; name="%s"\r\n\r\n%s\r\n'
            % (boundary, name, value)).encode("utf-8")
    for name, filename, data, mime in files:
        body += (
            '--%s\r\nContent-Disposition: form-data; name="%s"; '
            'filename="%s"\r\nContent-Type: %s\r\n\r\n'
            % (boundary, name, filename, mime)).encode("utf-8")
        body += data
        body += b"\r\n"
    body += ("--%s--\r\n" % boundary).encode("utf-8")
    return bytes(body), "multipart/form-data; boundary=%s" % boundary


def post_transcription(base_url: str, api_key: str, model: str,
                       audio_bytes: bytes, prompt: str = "",
                       language: str = "", need_word_time_stamp: bool = False,
                       timeout: int = 300) -> dict:
    """POST /audio/transcriptions 并返回 ``verbose_json`` 字典。

    失败一律抛 :class:`AsrHttpError`（含 status 与响应体片段）——
    绝不返回空 dict：那会让上层把「转写失败」当成「这段音频没有语音」，
    产出空字幕且不报错。
    """
    url = transcription_url(base_url)
    if not audio_bytes:
        raise AsrHttpError("音频数据为空")
    if not (api_key or "").strip():
        raise AsrHttpError("ASR api_key 为空")

    fields = [("model", model),
              ("response_format", "verbose_json"),
              ("prompt", prompt or None)]
    if need_word_time_stamp:
        fields.append(("timestamp_granularities[]", "word"))
        fields.append(("timestamp_granularities[]", "segment"))
    if language:
        fields.append(("language", language))

    body, content_type = _multipart_body(
        fields, [("file", "audio.mp3", audio_bytes, "audio/mpeg")])

    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", content_type)
    req.add_header("Authorization", "Bearer %s" % api_key.strip())
    req.add_header("User-Agent", _UA)
    req.add_header("Accept", "application/json")

    timeout = int(timeout or 300)
    try:
        # 显式不走系统代理的可选开关：ASR 常在境内可达，跟代理反而变慢/失败。
        opener = _opener()
        with opener.open(req, timeout=timeout) as r:
            raw = r.read()
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", "replace")[:500]
        except Exception:  # noqa: BLE001
            pass
        raise AsrHttpError(
            "ASR 服务返回 HTTP %s：%s" % (e.code, detail),
            status=e.code, body=detail) from e
    except urllib.error.URLError as e:
        raise AsrHttpError("ASR 服务不可达：%s" % e.reason) from e
    except OSError as e:
        raise AsrHttpError("ASR 请求失败：%s" % e) from e

    return _parse_transcription_response(raw)


def _opener():
    """按 :env:`VT_ASR_DIRECT` 决定是否绕过系统代理。"""
    direct = (os.environ.get("VT_ASR_DIRECT") or "").strip().lower() \
        in ("1", "true", "yes")
    if direct:
        return urllib.request.build_opener(urllib.request.ProxyHandler({}))
    return urllib.request.build_opener()


def _parse_transcription_response(raw: bytes) -> dict:
    """解析响应。

    返回字符串说明端点忽略了 ``response_format``（拿到的不是分镜数据）⇒
    抛错而非当结果用——否则后续会在「没有 segments」处以别的错误码报错，
    排查方向完全跑偏。
    """
    text = raw.decode("utf-8", "replace").strip()
    if not text:
        raise AsrHttpError("ASR 返回空响应")
    try:
        data = json.loads(text)
    except ValueError:
        # 非 JSON：可能是 HTML 错误页或纯文本（端点不对）
        raise AsrHttpError(
            "ASR 返回非 JSON（端点可能不是 OpenAI 兼容）：%s" % text[:200],
            body=text[:500])
    if isinstance(data, str):
        raise AsrHttpError("ASR 返回字符串而非分镜数据，请检查 base_url")
    if not isinstance(data, dict):
        raise AsrHttpError("ASR 响应结构异常：%s" % type(data).__name__)
    # 服务端可能把 verbose_json 参数降级成 json ⇒ 只有 text 没有 segments。
    # 这类情况下抛出明确错误，好过让调用方在别处撞 KeyError。
    if "segments" not in data and "text" not in data:
        raise AsrHttpError("ASR 响应缺少 segments/text 字段：%s"
                           % ", ".join(sorted(data.keys()))[:200],
                           body=text[:500])
    return data