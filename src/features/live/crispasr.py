# -*- coding: utf-8 -*-
# @version 3.3.1
"""crispasr.exe 本地引擎生命周期与 OpenAI 兼容转录接口。

关键约束（源：vt-web-server/itxw/engine.py，沿用实测结论）：
  * C++ 引擎 fopen 读不了含中文的绝对路径 → ``-m`` 只传纯文件名 + cwd=模型目录。
  * 就绪判定必须 GET /health 且校验 backend，禁止只做 TCP 连通性探测
    （原项目因此把 WAV POST 给了占用 8899 的 MiPCAudio.exe）。
  * 所有 loopback 请求禁用桌面 HTTP 代理。
  * 合并期新增 ``configured``：引擎/模型未安装时不再假启动。
"""
from __future__ import annotations

import json
import socket
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

from .audio import to_wav


class EngineError(RuntimeError):
    pass


class Engine:
    def __init__(self, cfg, log_path: Path | None = None):
        e = cfg.section("engine")
        self.exe = Path(cfg.resolve(e.get("exe", ""))) if e.get("exe") else Path()
        self.model_dir = Path(cfg.resolve(e.get("model_dir", ""))) if e.get("model_dir") else Path()
        self.model = e.get("model", "")
        self.backend = e.get("backend", "index-echo")
        self.host = e.get("host", "127.0.0.1")
        self.port = int(e.get("port", 18899))
        self.threads = str(e.get("threads", 7))
        self.target_lang = e.get("target_lang", "en")
        self.ask = e.get("ask", "")
        self.max_tokens = int(e.get("max_tokens", 160))
        self.response_format = e.get("response_format", "json")
        self.startup_timeout = float(e.get("startup_timeout_s", 180))
        self.request_timeout = float(e.get("request_timeout_s", 180))
        self.base = f"http://{self.host}:{self.port}"
        self.log_path = log_path or (cfg.path("sinks", "text_dir") / "engine.log")
        self.proc: subprocess.Popen | None = None
        self.external = False          # 复用了已存在的健康引擎，stop() 不 terminate
        self._log_file = None
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    # ------------------------------------------------------------------ health
    @property
    def configured(self) -> bool:
        return bool(self.exe.is_file()
                    and self.model_dir.is_dir()
                    and self.model
                    and (self.model_dir / self.model).is_file())

    def _get(self, path: str, timeout: float = 2.0):
        req = urllib.request.Request(self.base + path,
                                     headers={"Accept": "application/json"})
        with self._opener.open(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8", "replace")
        try:
            return json.loads(raw)
        except ValueError:
            return {"_raw": raw[:200]}

    def health(self) -> dict | None:
        """返回健康信息；仅当 backend 校验通过才视为就绪。"""
        try:
            data = self._get("/health", timeout=2.0)
        except Exception:  # noqa: BLE001
            return None
        backend = str(data.get("backend", ""))
        if self.backend and self.backend not in backend:
            return {"_invalid": True, "backend": backend, "raw": data}
        return data

    def _port_bindable(self) -> bool:
        s = socket.socket()
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((self.host, self.port))
            return True
        except OSError:
            return False
        finally:
            s.close()

    # ------------------------------------------------------------------ lifecycle
    def start(self) -> dict:
        if not self.configured:
            raise EngineError(
                "本地引擎未安装：需要 crispasr.exe 与 Index-Echo 模型。"
                "可在实时字幕页「高级」里下载/指定目录，或只用云端模式。")
        existing = self.health()
        if existing and not existing.get("_invalid"):
            self.external = True
            return existing
        if not self._port_bindable():
            raise EngineError(
                f"port {self.port} is occupied by a non-{self.backend} service; "
                "refusing to start (would cause a silent mis-connect)")

        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._log_file = self.log_path.open("ab")
        cmd = [
            str(self.exe), "--server", "-m", self.model,
            "--backend", self.backend,
            "--target-lang", self.target_lang,
            "--ask", self.ask,
            "-t", self.threads,
            "--host", self.host, "--port", str(self.port),
            "--no-warmup",
        ]
        self.proc = subprocess.Popen(cmd, cwd=str(self.model_dir),
                                     stdout=self._log_file, stderr=self._log_file)
        deadline = time.time() + self.startup_timeout
        while time.time() < deadline:
            if self.proc.poll() is not None:
                raise EngineError(f"engine exited rc={self.proc.returncode}; "
                                  f"see {self.log_path}")
            h = self.health()
            if h and not h.get("_invalid"):
                return h
            time.sleep(0.5)
        self.stop()
        raise EngineError(f"engine not ready within {self.startup_timeout}s; "
                          f"see {self.log_path}")

    def transcribe(self, pcm: bytes, timeout: float | None = None) -> dict:
        if not self.health():
            raise EngineError("engine not healthy")
        body_wav = to_wav(pcm)
        boundary = "----itxwboundary0123456789"
        head = (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="file"; filename="seg.wav"\r\n'
            "Content-Type: audio/wav\r\n\r\n"
        ).encode()
        fields = ""
        for name, value in (("max_tokens", str(self.max_tokens)),
                            ("response_format", self.response_format)):
            fields += (f"\r\n--{boundary}\r\n"
                       f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
                       f"{value}\r\n")
        tail = (fields + f"--{boundary}--\r\n").encode()
        req = urllib.request.Request(
            self.base + "/v1/audio/transcriptions",
            data=head + body_wav + tail,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
        try:
            with self._opener.open(req, timeout=timeout or self.request_timeout) as r:
                raw = r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            raise EngineError(f"transcribe HTTP {e.code}: {e.read()[:200]!r}") from e
        except Exception as e:  # noqa: BLE001
            raise EngineError(f"transcribe failed: {e!r}") from e
        try:
            return json.loads(raw)
        except ValueError as e:
            raise EngineError(f"non-JSON response: {raw[:200]!r}") from e

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                try:
                    self.proc.wait(3)
                except subprocess.TimeoutExpired:
                    pass
        self.proc = None
        if self._log_file:
            try:
                self._log_file.close()
            except OSError:
                pass
            self._log_file = None
        self.external = False

    @property
    def running(self) -> bool:
        return self.external or bool(self.proc and self.proc.poll() is None)

    def stats(self) -> dict:
        return {"running": self.running, "external": self.external,
                "configured": self.configured, "base": self.base,
                "model": self.model, "max_tokens": self.max_tokens,
                "log": str(self.log_path)}
