# -*- coding: utf-8 -*-
# @version 3.3.1
"""云端后端：Qwen-Audio ASR（百炼原生协议）→ Edge 翻译 → 术语校准。

端点契约（源：vt-web-server/itxw/backends/cloud.py，改用项目一设置）：
  * ``qwen-audio-3.0-asr-flash`` 没有 ``/audio/transcriptions``（恒 404），
    也打不了 compatible-mode 的 ``chat/completions``（恒 400 空体）。
    必须走同域名的 ``/api/v1/services/aigc/multimodal-generation/generation``。
  * 音频用 base64 Data URL，``parameters`` 带 format 与 sample_rate。
  * **400 空体 = 该段无可识别语音**（静音/纯音乐），返回空结果而非判失败；
    密钥/权限问题回 401/403，两者必须分开，否则静音段会打断整条链路。

合并期改动：
  * ``base_url`` / ``model`` 读项目一 ``ai_config.json``（唯一真源）；
  * ``api_key`` 只读 ``credential_store``，不再接受 app.json 明文；
  * 模型/端点变化由 ``LiveConfig.cred_revision`` 触发路由重新评估。
"""
from __future__ import annotations

import base64
import json
import threading
import time
import urllib.error
import urllib.request

from ..audio import Segment, to_wav
from ..cue import Cue
from ..edge import EdgeTranslator
from .base import CloudError, SubtitleBackend

NATIVE_PATH = "/api/v1/services/aigc/multimodal-generation/generation"
_ENDPOINT_TAILS = ("/compatible-mode/v1", "/api/v1", "/v1",
                   "/audio/transcriptions", "/chat/completions")
_DEFAULT_BASE = "https://dashscope.aliyuncs.com/compatible-mode/v1"
_DEFAULT_MODEL = "qwen-audio-3.0-asr-flash"


class CloudBackend(SubtitleBackend):
    name = "cloud-qwen-audio"

    def __init__(self, cfg, calibrator=None, translator=None):
        self.cfg = cfg
        a = cfg.section("asr")
        base, model, protocol = cfg.global_asr()
        self.base_url = (base or a.get("base_url") or _DEFAULT_BASE).strip()
        self.model = (model or a.get("model") or _DEFAULT_MODEL).strip()
        self.protocol = protocol or "auto"
        self.native_path = a.get("native_path") or NATIVE_PATH
        self.timeout = float(a.get("timeout_s", 15))
        self.retries = max(0, int(a.get("retries", 1)))
        self.calibrator = calibrator
        self.translator = translator or EdgeTranslator(cfg)
        #: ASR 出原文后立即回调（先上屏），翻译完成后再由 produce 返回完整 cue。
        self.on_partial = None
        self._local = threading.local()
        self.calls = 0
        self.empty_segments = 0
        self.errors = 0
        self.last_error = ""
        self.last_latency = 0.0

    # ------------------------------------------------------------------ 凭据
    @property
    def api_key(self) -> str:
        """只读项目一 credential_store；不缓存明文、不进日志。"""
        return self.cfg.asr_api_key()

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.base_url and self.model)

    def native_url(self) -> str:
        b = self.base_url or ""
        for tail in _ENDPOINT_TAILS:
            if b.endswith(tail):
                b = b[: -len(tail)]
                break
        if "//" in b:
            scheme, rest = b.split("//", 1)
            host = rest.split("/", 1)[0]
        else:
            scheme, host = "https:", b.split("/", 1)[0]
        return f"{scheme}//{host}{self.native_path}"

    def _opener(self):
        op = getattr(self._local, "op", None)
        if op is None:
            op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            self._local.op = op
        return op

    # ------------------------------------------------------------------ 请求
    def _post(self, wav: bytes) -> dict:
        body = {
            "model": self.model,
            "input": {"messages": [{"role": "user", "content": [
                {"type": "input_audio",
                 "input_audio": {"data": "data:audio/wav;base64,"
                                         + base64.b64encode(wav).decode("ascii")}}]}]},
            "parameters": {"format": "wav", "sample_rate": "16000"},
        }
        req = urllib.request.Request(
            self.native_url(), data=json.dumps(body).encode("utf-8"), method="POST",
            headers={"Authorization": "Bearer " + self.api_key,
                     "Content-Type": "application/json",
                     "Accept": "application/json"})
        with self._opener().open(req, timeout=self.timeout) as r:
            return json.loads(r.read().decode("utf-8", "replace"))

    @staticmethod
    def _extract_text(data: dict) -> str:
        out = data.get("output")
        if isinstance(out, dict):
            s = out.get("sentence")
            if isinstance(s, dict) and s.get("text"):
                return str(s["text"]).strip()
            ss = out.get("sentences")
            if isinstance(ss, list) and ss:
                return " ".join(str(x.get("text", "")) for x in ss
                                if isinstance(x, dict)).strip()
            if out.get("text"):
                return str(out["text"]).strip()
            ch = out.get("choices")
            if isinstance(ch, list) and ch:
                content = (ch[0].get("message") or {}).get("content")
                if isinstance(content, str):
                    return content.strip()
                if isinstance(content, list):
                    return " ".join(str(x.get("text", "")) for x in content
                                    if isinstance(x, dict)).strip()
        return str(data.get("text") or "").strip()

    def _refresh_global_asr(self) -> None:
        """每次请求前对齐设置页：AI 配置可能在运行中被改，端点/模型不能只在
        构造时读一次，否则用户改完设置要重启整个实时服务才生效。"""
        base, model, protocol = self.cfg.global_asr()
        if base:
            self.base_url = base.strip()
        if model:
            self.model = model.strip()
        if protocol:
            self.protocol = protocol.strip() or "auto"

    def produce(self, seg: Segment) -> list[Cue]:
        self._refresh_global_asr()
        if not self.api_key:
            raise CloudError("ASR 凭据未配置（设置 → ASR 语音识别）",
                             kind="unconfigured")
        if not self.base_url or not self.model:
            raise CloudError("ASR base_url/model 未配置（设置 → ASR 语音识别）",
                             kind="unconfigured")
        wav = to_wav(seg.pcm)
        data = None
        last_err = ""
        for attempt in range(self.retries + 1):
            t0 = time.time()
            try:
                data = self._post(wav)
                self.last_latency = round(time.time() - t0, 2)
                break
            except urllib.error.HTTPError as e:
                try:
                    detail = e.read().decode("utf-8", "replace")[:300]
                except Exception:  # noqa: BLE001
                    detail = ""
                self.last_latency = round(time.time() - t0, 2)
                if e.code in (401, 403):
                    self.errors += 1
                    self.last_error = f"HTTP {e.code}"
                    raise CloudError(f"ASR 凭据被拒 HTTP {e.code}", status=e.code,
                                     kind="auth") from e
                if e.code == 400 and detail.strip() in ("", "{}"):
                    self.empty_segments += 1
                    return []
                last_err = f"HTTP {e.code}: {detail[:120]}"
                if e.code < 500:
                    break
            except Exception as e:  # noqa: BLE001
                self.last_latency = round(time.time() - t0, 2)
                last_err = repr(e)[:160]
        if data is None:
            self.errors += 1
            self.last_error = last_err
            raise CloudError(f"ASR 失败 {last_err}", kind="network")

        self.calls += 1
        text = self._extract_text(data)
        if not text:
            self.empty_segments += 1
            return []
        if self.calibrator:
            text = self.calibrator.calibrate(text)
        if seg.interim:
            return [Cue.from_cloud(text, "", seq=seg.seq, t0_ms=seg.t0_ms,
                                   duration_ms=seg.duration_ms,
                                   backend=self.name, interim=True)]
        if self.on_partial and getattr(self.translator, "enabled", False):
            self.on_partial([Cue.from_cloud(text, "", seq=seg.seq,
                                            t0_ms=seg.t0_ms,
                                            duration_ms=seg.duration_ms,
                                            backend=self.name)])
        translated = self.translator.translate(text)
        if translated and self.calibrator:
            translated = self.calibrator.calibrate(translated)
        return [Cue.from_cloud(text, translated, seq=seg.seq, t0_ms=seg.t0_ms,
                               duration_ms=seg.duration_ms, backend=self.name)]

    def stats(self) -> dict:
        self._refresh_global_asr()
        return {"name": self.name, "configured": self.configured,
                "model": self.model, "protocol": self.protocol,
                "url": self.native_url() if self.base_url else "",
                "calls": self.calls, "empty_segments": self.empty_segments,
                "errors": self.errors, "last_error": self.last_error,
                "last_latency_s": self.last_latency,
                "translator": self.translator.stats()}
