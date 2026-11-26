# -*- coding: utf-8 -*-
# @version 3.3.1
"""实时字幕配置：``data/live_config.json`` + 项目一全局 AI/ASR 只读配置。

设计约束
--------
* **密钥只有一个真源**：ASR Key 只从 ``data/credentials.json``（credential_store）
  读取；本模块只读、不写、不落盘、不进日志。
* **ASR 端点/模型复用项目一设置**：``ai_config.json`` 的 ``asr_base_url`` /
  ``asr_model`` 是唯一来源；``live_config`` 只保留协议细节与超时/重试。
* **实时参数独立**：VAD、队列、并发、悬浮层、SRT 等只属于实时链路，
  不塞进 ``ai_config.json``，避免污染批量流水线。
* 路径用 ``{app}`` / ``{data}`` 占位，换机器/绿色版无需改绝对路径。
"""
from __future__ import annotations

import copy
import json
import os
import sys
import threading
from pathlib import Path

#: 默认配置。密钥相关字段**刻意不存在**（只读 credential_store）。
DEFAULTS: dict = {
    "engine": {
        "exe": "{app}/tools/live_engine/crispasr/crispasr.exe",
        "model_dir": "{app}/tools/live_model/index-echo",
        "model": "index-echo-2b-q8_0.gguf",
        "backend": "index-echo",
        "host": "127.0.0.1",
        "port": 18899,
        "threads": 7,
        "target_lang": "en",
        "ask": ("Output exactly two lines for each sentence, with no timestamps.\n"
                "Line 1: the transcript in the language actually spoken.\n"
                "Line 2: the translation into the other language. If line 1 contains "
                "Chinese characters, line 2 must be English. If line 1 is fully English, "
                "line 2 must be Chinese. Never repeat line 1 as line 2."),
        "max_tokens": 160,
        "response_format": "json",
        "startup_timeout_s": 180,
        "request_timeout_s": 180,
        "preload": False,
    },
    "audio": {
        "sample_rate": 16000,
        "frame_ms": 100,
        "gain": 8.0,
        "vad_min_rms": 110,
        "noise_ratio": 2.2,
        "silence_ms": 400,
        "interim_enabled": True,
        "interim_interval_ms": 2000,
        "min_speech_ms": 400,
        "max_segment_ms": 5000,
        "preroll_ms": 300,
    },
    "queue": {"max_pending": 3, "stale_s": 20},
    "source": {
        "type": "loopback",          # loopback | mic | wav
        "device": "",
        "wav": "",
        "realtime": True,
        "loop": False,
    },
    "backend": {"cloud_workers": 3, "local_workers": 1},
    "asr": {
        "protocol": "dashscope_native",
        "native_path": "/api/v1/services/aigc/multimodal-generation/generation",
        "model": "qwen-audio-3.0-asr-flash",
        "timeout_s": 15,
        "retries": 1,
    },
    "translate": {
        "protocol": "edge",
        "enabled": True,
        "endpoint": "https://edge.microsoft.com/translate/translatetext",
        "target_lang": "zh-Hans",
        "zh_code": "zh-Hans",
        "en_code": "en",
        "timeout_s": 8,
        "retries": 1,
    },
    "calib": {
        "enabled": True,
        "mode": "bi",
        "extra_terms": {"俯冲攻击": "下落攻击"},
    },
    "state": {
        "fail_threshold": 3,
        "local_min_hold_s": 60,
        "probe_interval_s": 30,
        "recover_success": 2,
        "no_probe_status": [401, 403],
    },
    "sinks": {
        "console": False,
        "text_files": True,
        "jsonl": True,
        "srt": True,
        "text_dir": "{data}/live_out",
    },
    "srt": {
        "enabled": True,
        "bilingual": True,
        "min_duration_ms": 1200,
        "filename": "live.srt",
    },
    "ui": {
        "enabled": True,
        "font": "Microsoft YaHei UI",
        "size_main": 32,
        "size_sub": 25,
        "alpha": 0.88,
        "click_through": False,
        "position": "bottom",
        "margin_px": 40,
        "width_ratio": 0.8,
        "history_lines": 2,
        "bg": "#101010",
        "fg_main": "#FFFFFF",
        "fg_sub": "#9CDCFE",
        "fg_degraded": "#FFB86C",
        "width_px": 665,
        "height_px": 505,
    },
}

#: 热更新白名单：dotted key -> 类型。数值必须为正；bool 严格校验。
HOT_KEYS: dict[str, type] = {
    "audio.gain": float,
    "audio.vad_min_rms": float,
    "audio.noise_ratio": float,
    "audio.silence_ms": int,
    "audio.max_segment_ms": int,
    "audio.min_speech_ms": int,
    "audio.preroll_ms": int,
    "audio.interim_enabled": bool,
    "audio.interim_interval_ms": int,
    "queue.max_pending": int,
    "queue.stale_s": float,
    "calib.enabled": bool,
    "calib.mode": str,
    "translate.enabled": bool,
    "translate.timeout_s": float,
    "state.fail_threshold": int,
    "state.local_min_hold_s": float,
    "state.probe_interval_s": float,
    "state.recover_success": int,
    "source.type": str,
    "source.device": str,
    "source.wav": str,
    "source.realtime": bool,
    "source.loop": bool,
    "backend.cloud_workers": int,
    "sinks.console": bool,
    "sinks.text_files": bool,
    "sinks.jsonl": bool,
    "sinks.srt": bool,
    "srt.enabled": bool,
    "srt.bilingual": bool,
    "srt.min_duration_ms": int,
    "ui.click_through": bool,
    "ui.alpha": float,
    "ui.size_main": int,
    "ui.size_sub": int,
    "ui.width_px": int,
    "ui.height_px": int,
    "ui.history_lines": int,
}


def program_root() -> Path:
    """程序根：源码形态 = src 的上一级；冻结形态 = exe 所在目录。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[3]


def data_dir() -> Path:
    """数据根/data：与 ``ai_client`` / ``credential_store`` 同口径。"""
    env = (os.environ.get("VT_DATA_ROOT") or "").strip().strip('"')
    if env:
        return Path(env) / "data"
    root = program_root()
    pointer = root / "data_dir.txt"
    try:
        if pointer.is_file():
            value = pointer.read_text(encoding="utf-8-sig").strip().strip('"')
            if value:
                return Path(value) / "data"
    except OSError:
        pass
    return root / "data"


def _ai_config_path() -> Path:
    try:
        import ai_client  # noqa: PLC0415 —— 惰性，避免 feature.py 重依赖
        return Path(ai_client.CONFIG_PATH)
    except Exception:  # noqa: BLE001
        return data_dir() / "ai_config.json"


def _cred_path() -> Path:
    try:
        import credential_store  # noqa: PLC0415
        return Path(credential_store.CRED_PATH)
    except Exception:  # noqa: BLE001
        return data_dir() / "credentials.json"


def _merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if key.startswith("_"):
            continue
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


class LiveConfig:
    """实时字幕配置对象（线程安全读；写只走 :meth:`hot_update` / :meth:`save`）。"""

    def __init__(self, payload: dict | None = None, path: Path | None = None):
        self._data = _merge(DEFAULTS, payload or {})
        self.file_path = Path(path) if path else data_dir() / "live_config.json"
        self._lock = threading.RLock()
        self._asr_sig = None
        self._asr_cache = ("", "", "auto")

    @classmethod
    def load(cls, path: str | Path | None = None) -> "LiveConfig":
        p = Path(path) if path else data_dir() / "live_config.json"
        if not p.is_file():
            return cls({}, p)
        try:
            payload = json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 —— 配置损坏时用默认值启动，不影响主程序
            payload = {}
        return cls(payload, p)

    # ------------------------------------------------------------------ read
    def get(self, section: str, key: str, default=None):
        with self._lock:
            return copy.deepcopy(self._data.get(section, {}).get(key, default))

    def section(self, name: str) -> dict:
        with self._lock:
            return copy.deepcopy(self._data.get(name, {}))

    def snapshot(self, redacted: bool = True) -> dict:
        with self._lock:
            data = copy.deepcopy(self._data)
        return data

    def resolve(self, value):
        if not isinstance(value, str):
            return value
        out = value.replace("{app}", str(program_root())).replace(
            "{data}", str(data_dir()))
        if out.startswith("./") or out.startswith(".\\"):
            out = str(program_root() / out[2:])
        return out

    def path(self, section: str, key: str, default=None) -> Path:
        raw = self.get(section, key, default)
        return Path(self.resolve(raw)) if raw else Path()

    # ------------------------------------------------------------------ global ASR
    def global_asr(self) -> tuple[str, str, str]:
        """(base_url, model, protocol)，来自项目一 ``ai_config.json``。

        以 ai_config 的 mtime/size 做缓存，避免每次请求都读盘。
        """
        p = _ai_config_path()
        try:
            st = p.stat()
            sig = (st.st_mtime_ns, st.st_size)
        except OSError:
            sig = None
        with self._lock:
            if sig is not None and sig == self._asr_sig:
                return self._asr_cache
        base, model, protocol = "", "", "auto"
        try:
            import video_toolbox as engine  # noqa: PLC0415
            cfg = engine.ai_load_config() or {}
            base = str(cfg.get("asr_base_url") or "").strip()
            model = str(cfg.get("asr_model") or "").strip()
            protocol = str(cfg.get("asr_protocol") or "auto").strip()
        except Exception:  # noqa: BLE001
            pass
        with self._lock:
            self._asr_sig = sig
            self._asr_cache = (base, model, protocol)
            return self._asr_cache

    def asr_api_key(self) -> str:
        """只读项目一凭据；不写回、不缓存明文到本对象。"""
        try:
            from credential_store import get  # noqa: PLC0415
        except Exception:  # noqa: BLE001
            try:
                sys.path.insert(0, str(program_root() / "tools"))
                from credential_store import get  # noqa: PLC0415
            except Exception:  # noqa: BLE001
                get = None
        if get is not None:
            try:
                key = str(get("asr_api_key") or "").strip()
                if key:
                    return key
            except Exception:  # noqa: BLE001
                pass
        return (os.environ.get("VT_ASR_KEY")
                or os.environ.get("ITXW_ASR_KEY") or "").strip()

    def asr_configured(self) -> bool:
        base, model, _ = self.global_asr()
        return bool(self.asr_api_key() and (base or self.get("asr", "base_url", ""))
                    and (model or self.get("asr", "model", "")))

    @property
    def cred_revision(self):
        """凭据/端点变化时递增的指纹（供路由状态机重新评估云端可用性）。"""
        try:
            st = _cred_path().stat()
            stamp = (st.st_mtime_ns, st.st_size)
        except OSError:
            stamp = (0, 0)
        base, model, _ = self.global_asr()
        return stamp + (base, model)

    # ------------------------------------------------------------------ write
    def hot_update(self, payload: dict) -> tuple[dict, list[str]]:
        applied: dict = {}
        rejected: list[str] = []
        with self._lock:
            for dotted, raw in (payload or {}).items():
                typ = HOT_KEYS.get(dotted)
                if typ is None or "." not in dotted:
                    rejected.append(dotted)
                    continue
                section, key = dotted.split(".", 1)
                try:
                    if typ is bool:
                        if not isinstance(raw, bool):
                            raise ValueError("expected bool")
                        value = raw
                    elif typ is str:
                        if not isinstance(raw, str):
                            raise ValueError("expected str")
                        value = raw
                    else:
                        value = typ(raw)
                        if value <= 0:
                            raise ValueError("must be positive")
                except (TypeError, ValueError):
                    rejected.append(dotted)
                    continue
                self._data.setdefault(section, {})[key] = value
                applied[dotted] = value
        if applied:
            try:
                self.save()
            except OSError:
                pass
        return applied, rejected

    def save(self, path: str | Path | None = None) -> None:
        p = Path(path) if path else self.file_path
        with self._lock:
            data = copy.deepcopy(self._data)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, p)
