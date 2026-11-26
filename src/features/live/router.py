# -*- coding: utf-8 -*-
# @version 3.3.1
"""后端路由与降级状态机：CLOUD → LOCAL → PROBING → CLOUD。

设计要点（源：vt-web-server/itxw/state.py，补两处合并期修复）：

* 云端失败用**同一段 PCM** 重喂本地后端，不重采、不重切，Cue 标 fallback_from。
* 401/403/空 key → 直接 LOCAL 且不回探；用户更新凭据后经 ``cred_revision`` 重新评估。
* 连续 fail_threshold 次失败降级；本地最短保持 local_min_hold_s；
  每 probe_interval_s 回探 1 段；连续 recover_success 次成功回切云端。
* **修复**：本地引擎未安装时不再“假降级”——直接抛回云端错误，由服务层
  记日志并在界面显示「本地引擎未安装」，避免每段都空转。
"""
from __future__ import annotations

import threading
import time

from .audio import Segment
from .backends.base import CloudError, mark_fallback
from .cue import Cue

CLOUD = "CLOUD"
LOCAL = "LOCAL"
PROBING = "PROBING"


class BackendRouter:
    def __init__(self, cfg, local, cloud=None):
        self.cfg = cfg
        self.local = local
        self.cloud = cloud
        s = cfg.section("state")
        self.fail_threshold = max(1, int(s.get("fail_threshold", 3)))
        self.local_min_hold = float(s.get("local_min_hold_s", 60))
        self.probe_interval = float(s.get("probe_interval_s", 30))
        self.recover_success = max(1, int(s.get("recover_success", 2)))
        self.no_probe_status = {int(x) for x in s.get("no_probe_status", [401, 403])}
        prefer_cloud = bool(cloud and cloud.configured)
        self._state = CLOUD if prefer_cloud else LOCAL
        self._no_probe = not prefer_cloud
        self._fail_streak = 0
        self._success_streak = 0
        self._local_since = time.time()
        self._last_probe = 0.0
        self._cred_rev = cfg.cred_revision
        self._lock = threading.RLock()
        self.events: list[dict] = []
        self.cloud_failures = 0
        self.cloud_calls = 0
        self.local_calls = 0
        self._log("init", self._state)

    # ------------------------------------------------------------------ helpers
    def _log(self, event: str, state: str, detail: str = "") -> None:
        self.events.append({"t": round(time.time(), 2), "event": event,
                            "state": state, "detail": detail[:160]})
        if len(self.events) > 50:
            self.events = self.events[-50:]

    def _transition(self, new: str, reason: str = "") -> None:
        old = self._state
        self._state = new
        if new == LOCAL:
            self._local_since = time.time()
        self._log("transition", new, f"{old}->{new} {reason}")

    # ------------------------------------------------------------------ routing
    def produce(self, seg: Segment) -> list[Cue]:
        with self._lock:
            if self.cfg.cred_revision != self._cred_rev:
                self._cred_rev = self.cfg.cred_revision
                if self.cloud and self.cloud.configured:
                    self._no_probe = False
                    self._last_probe = 0.0
                    self._log("credentials_updated", self._state)
            use_cloud = self._state in (CLOUD, PROBING)
            if seg.interim and not use_cloud:
                return []          # 预识别是云端加速机制，本地推理慢不陪跑
        return self._try_cloud(seg) if use_cloud else self._local_path(seg)

    def _try_cloud(self, seg: Segment) -> list[Cue]:
        assert self.cloud is not None
        with self._lock:
            self.cloud_calls += 1
        try:
            cues = self.cloud.produce(seg)
        except CloudError as e:
            return self._on_cloud_failure(seg, e)
        except Exception as e:  # noqa: BLE001
            return self._on_cloud_failure(seg, CloudError(repr(e)))
        with self._lock:
            self._fail_streak = 0
            if self._state == PROBING:
                self._success_streak += 1
                if self._success_streak >= self.recover_success:
                    self._transition(CLOUD, "probe recovered")
        return cues

    def _on_cloud_failure(self, seg: Segment, err: CloudError) -> list[Cue]:
        with self._lock:
            self.cloud_failures += 1
            self._fail_streak += 1
            was_probing = self._state == PROBING
            fatal = err.fatal or (err.status in self.no_probe_status if err.status else False)
            if fatal:
                self._no_probe = True
                self._transition(LOCAL, f"fatal {err.status or err.kind}")
            elif was_probing or self._fail_streak >= self.fail_threshold:
                self._transition(LOCAL, f"fail_streak={self._fail_streak}")
            self._success_streak = 0
            cloud_name = self.cloud.name if self.cloud else "cloud"
            local_ready = bool(getattr(self.local, "configured", True))
            if local_ready:
                self.local_calls += 1
        if not local_ready:
            # 本地引擎未安装：不伪装成降级成功，把原始云端错误抛回服务层。
            raise err
        cues = self.local.produce(seg)
        return mark_fallback(cues, cloud_name)

    def _local_path(self, seg: Segment) -> list[Cue]:
        now = time.time()
        with self._lock:
            probe = (self.cloud is not None and self.cloud.configured
                     and not self._no_probe
                     and now - self._local_since >= self.local_min_hold
                     and now - self._last_probe >= self.probe_interval)
            if probe:
                self._last_probe = now
                self._success_streak = 0
                self._transition(PROBING, "scheduled probe")
            else:
                self.local_calls += 1
        if probe:
            return self._try_cloud(seg)
        return self.local.produce(seg)

    # ------------------------------------------------------------------ status
    @property
    def state(self) -> str:
        with self._lock:
            return self._state

    def stats(self) -> dict:
        with self._lock:
            return {"state": self._state,
                    "prefer_cloud": self._state in (CLOUD, PROBING),
                    "no_probe": self._no_probe,
                    "fail_streak": self._fail_streak,
                    "success_streak": self._success_streak,
                    "local_since": round(self._local_since, 1),
                    "cloud_calls": self.cloud_calls,
                    "cloud_failures": self.cloud_failures,
                    "local_calls": self.local_calls,
                    "cloud_configured": bool(self.cloud and self.cloud.configured),
                    "local_configured": bool(getattr(self.local, "configured", True)),
                    "backend": (self.cloud.name if self._state in (CLOUD, PROBING)
                                and self.cloud else self.local.name),
                    "events": list(self.events[-8:])}
