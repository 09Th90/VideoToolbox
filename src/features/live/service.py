# -*- coding: utf-8 -*-
# @version 3.3.1
"""编排层：采集 → VAD → 有界队列 → 并发 worker → 路由 → 广播 + SRT。

线程模型（源：vt-web-server/itxw/app.py，UI 从 tkinter 改为 Qt 的队列轮询）：
  * 采集线程 1 条：source.iter_frames → VAD → bus.submit（不做网络/推理）。
  * 分发线程 1 条：bus.get → 提交线程池。
  * 线程池 cloud_workers 条：router.produce。云端并发吸收长尾；本地引擎推理
    由 LazyLocal 内部锁串行。
  * UI 在主线程跑 Qt，经 ``queue.Queue`` 收字幕与状态，QTimer 轮询，互不阻塞。

Cue 按 seq 幂等 upsert：并发下乱序到达也不会重复或回退；SRT/文本接力只写
同一 seq 的最终版本。**合并期修复**：发布前先比较文本，补译文时一定重发；
本地引擎未安装时路由不再假降级。
"""
from __future__ import annotations

import atexit
import queue
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from .audio import Segment, VAD
from .backends import build_backends
from .backends.local import LocalBackend
from .bus import BoundedBus
from .calib_adapter import Calibrator
from .config import LiveConfig
from .crispasr import Engine
from .cue import Cue
from .router import BackendRouter
from .sinks import Broadcast, build_sinks
from .sources import build_source


class LazyLocal:
    """本地后端懒启动：preload=false 时首次降级才拉起引擎（冷启动约 4.7s）。

    引擎推理串行，云端并发 worker 同时降级时在此排队，不会并发打引擎。
    """

    name = "local-index-echo"

    def __init__(self, engine: Engine, cfg: LiveConfig):
        self.engine = engine
        self.cfg = cfg
        self.inner = LocalBackend(engine)
        self._lock = threading.Lock()
        self._started = False
        self.start_error = ""

    @property
    def configured(self) -> bool:
        return self.engine.configured

    def produce(self, seg: Segment) -> list[Cue]:
        with self._lock:
            if not self._started:
                try:
                    self.engine.start()
                    self._started = True
                    self.start_error = ""
                except Exception as e:  # noqa: BLE001
                    self.start_error = repr(e)[:200]
                    raise
            return self.inner.produce(seg)

    def stats(self) -> dict:
        s = self.inner.stats()
        s.update({"engine_started": self._started,
                  "engine_running": self.engine.running,
                  "start_error": self.start_error})
        return s


class LiveService:
    def __init__(self, cfg: LiveConfig | None = None,
                 ui_queue: queue.Queue | None = None):
        self.cfg = cfg or LiveConfig.load()
        self.ui_queue = ui_queue
        self.engine = Engine(self.cfg)
        self.calibrator = Calibrator(
            mode=self.cfg.get("calib", "mode", "bi"),
            enabled=bool(self.cfg.get("calib", "enabled", True)),
            extra_terms=self.cfg.get("calib", "extra_terms", {}))
        self.local = LazyLocal(self.engine, self.cfg)
        _, self.cloud = build_backends(self.cfg, engine=None,
                                       calibrator=self.calibrator)
        if self.cloud is not None:
            self.cloud.on_partial = self._emit
        self.router = BackendRouter(self.cfg, self.local, self.cloud)
        self.bus = BoundedBus(max_pending=int(self.cfg.get("queue", "max_pending", 3)),
                              stale_s=float(self.cfg.get("queue", "stale_s", 20)),
                              on_drop=self._on_drop)
        self.last_error = ""
        try:
            self.sinks = build_sinks(self.cfg)
        except Exception as e:  # noqa: BLE001
            self.sinks = Broadcast()
            self.last_error = f"输出初始化失败: {e!r}"
        self.vad = VAD(self.cfg.section("audio"))
        self.source = None
        self._pool: ThreadPoolExecutor | None = None
        self._threads: list[threading.Thread] = []
        self._stopping = threading.Event()
        self._running = False
        self._cues: dict[int, Cue] = {}
        self._cues_lock = threading.Lock()
        self._seq = 0
        self._t0_ms = 0
        self._elapsed_ms = 0          # 音频时钟（含静音），SRT 时间轴基准
        self._seg_start_ms = 0        # 当前语音段在音频时钟上的起点
        self._started_at = 0.0
        self.segments_produced = 0
        self._atexit_armed = False
        try:
            atexit.register(self.stop)
            self._atexit_armed = True
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------------ 生命周期
    @property
    def is_running(self) -> bool:
        return self._running and not self._stopping.is_set()

    def start(self, source_kind: str | None = None, device: str | None = None) -> None:
        if self.is_running:
            return
        self._stopping.clear()
        self._started_at = time.time()
        self._running = True
        self._cues.clear()
        self._seq = 0
        self._t0_ms = 0
        self._elapsed_ms = 0
        self._seg_start_ms = 0
        self.segments_produced = 0
        self.last_error = ""
        self.bus = BoundedBus(
            max_pending=int(self.cfg.get("queue", "max_pending", 3)),
            stale_s=float(self.cfg.get("queue", "stale_s", 20)),
            on_drop=self._on_drop)
        self.vad = VAD(self.cfg.section("audio"))
        self.sinks.new_session()
        if self.cfg.get("engine", "preload", False) and self.local.configured:
            try:
                self.engine.start()
                self.local._started = True
            except Exception as e:  # noqa: BLE001
                self.last_error = f"引擎预启动失败: {e!r}"
        self._pool = ThreadPoolExecutor(
            max_workers=max(1, int(self.cfg.get("backend", "cloud_workers", 3))),
            thread_name_prefix="vtlive-worker")
        # 分发线程必须先于采集线程启动：WAV 回归（realtime=False）可能在
        # 毫秒级读完并自然结束，若分发还没起来，末尾语音段会留在队列里没人收。
        t = threading.Thread(target=self._dispatch_loop, name="vtlive-dispatch",
                             daemon=True)
        t.start()
        self._threads.append(t)
        try:
            self._start_source(source_kind, device)
        except Exception:
            # 设备被占用/依赖缺失：不让服务停在「running 但没有采集线程」的
            # 假运行态，回滚到可重试的停止态后把错误交给页面。
            self._stopping.set()
            self._running = False
            try:
                self._pool.shutdown(wait=False, cancel_futures=True)
            except Exception:  # noqa: BLE001
                pass
            self._pool = None
            try:
                self.engine.stop()
            except Exception:  # noqa: BLE001
                pass
            raise
        self._push(kind="started")

    def _start_source(self, kind: str | None = None, device: str | None = None) -> None:
        self._threads = [t for t in self._threads if t.is_alive()]
        overrides = {}
        if device is not None:
            overrides["device"] = device
        if kind:
            # 记住用户本次选择：下次启动/切源按同一设备，不用回到默认口。
            self.cfg.hot_update({"source.type": kind,
                                 "source.device": device or ""})
        self.source = build_source(self.cfg, kind, **overrides)
        self.vad.reset()
        t = threading.Thread(target=self._capture_loop, name="vtlive-capture",
                             daemon=True)
        t.start()
        self._threads.append(t)

    def switch_source(self, kind: str, device: str = "") -> None:
        """独立切换内录/麦克风与具体设备，不重启进程、不动云端状态。"""
        if not self.is_running:
            self.cfg.hot_update({"source.type": kind, "source.device": device})
            return
        if self.source:
            self.source.stop()
        self.bus.clear()
        self._start_source(kind, device)
        self._push(kind="source_switched")

    def stop(self, drain: bool = False) -> None:
        """停止采集与 worker。

        ``drain=True`` 用于音源自然结束（WAV 回归）：先把已在队列的语音段
        交给云端/本地处理完，再关；普通「停止」按钮仍走立即取消，保证手感。
        """
        if not self._running and not self.source:
            return
        if drain:
            deadline = time.time() + 12.0
            while (self.bus.pending and not self._stopping.is_set()
                   and time.time() < deadline):
                time.sleep(0.1)
        self._stopping.set()
        if self.source:
            try:
                self.source.stop()
            except Exception:  # noqa: BLE001
                pass
        self.bus.set_stopping()
        if self._pool is not None:
            try:
                self._pool.shutdown(wait=bool(drain),
                                    cancel_futures=not bool(drain))
            except Exception:  # noqa: BLE001
                pass
            self._pool = None
        for t in list(self._threads):
            if t is threading.current_thread():
                continue
            t.join(timeout=2.0)
        self._threads.clear()
        try:
            self.sinks.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            self.engine.stop()
        except Exception:  # noqa: BLE001
            pass
        self.local._started = False
        self._running = False
        self._push(kind="stopped")

    # ------------------------------------------------------------------ 采集
    def _capture_loop(self) -> None:
        src = self.source
        try:
            for frame in src.iter_frames():
                if self._stopping.is_set():
                    break
                was_speaking = self.vad.speaking
                seg_pcm = self.vad.feed(self.vad.process_frame(frame))
                self._elapsed_ms += self.vad.frame_ms
                if self.vad.speaking and not was_speaking:
                    # 段起点按**音频时钟**回推，而不是「已识别语音时长」累加：
                    # 静音期也占时间轴，否则 SRT 会越播越早（现场 3 分钟可差十几秒）。
                    self._seg_start_ms = max(
                        0, self._elapsed_ms - len(self.vad.segment) // 32)
                if seg_pcm is None:
                    ipcm = self.vad.poll_interim()
                    if ipcm:
                        self.bus.submit_interim(Segment(
                            seq=self._seq + 1, pcm=ipcm, t0_ms=self._seg_start_ms,
                            created=time.time(), interim=True))
                    continue
                self._seq += 1
                duration_ms = int(len(seg_pcm) / 32)
                seg = Segment(seq=self._seq, pcm=seg_pcm,
                              t0_ms=self._seg_start_ms, created=time.time())
                self._t0_ms = self._seg_start_ms + duration_ms
                self.segments_produced += 1
                self.bus.submit(seg)
        except Exception as e:  # noqa: BLE001
            self.last_error = f"采集中断: {e!r}"
            self._push(kind="error", message=self.last_error)
            self._running = False
            self._push(kind="stopped")
        finally:
            # WAV 回归文件播完后音源会自然结束；不在这里收口的话界面会一直
            # 显示「运行中」。回调 stop() 会跳过当前采集线程自身，不会自锁。
            if not self._stopping.is_set() and self._running:
                self.stop(drain=True)

    def _dispatch_loop(self) -> None:
        while not self._stopping.is_set():
            seg = self.bus.get(timeout=0.3)
            if seg is None:
                continue
            pool = self._pool
            if pool is None:
                break
            try:
                pool.submit(self._handle, seg)
            except RuntimeError:
                break

    def _handle(self, seg: Segment) -> None:
        if self._stopping.is_set():
            return
        try:
            cues = self.router.produce(seg)
        except Exception as e:  # noqa: BLE001
            self.last_error = f"处理失败 seq={seg.seq}: {e!r}"
            self._push(kind="error", message=self.last_error)
            return
        if cues:
            self._emit(cues)

    def _on_drop(self, reason: str, seg: Segment) -> None:
        self._push(kind="drop", message=f"{reason} seq={seg.seq}")

    # ------------------------------------------------------------------ 输出
    def _emit(self, cues: list[Cue]) -> None:
        publish: list[Cue] = []
        with self._cues_lock:
            for c in cues:
                old = self._cues.get(c.seq)
                if old is not None and not old.interim and c.interim:
                    continue       # 迟到的预识别不得覆盖已到的终版
                changed = (old is None or old.main != c.main or old.sub != c.sub
                           or old.interim != c.interim)
                self._cues[c.seq] = c
                if changed:
                    publish.append(c)
            if len(self._cues) > 500:
                for k in sorted(self._cues)[:-500]:
                    del self._cues[k]
            newest = max(self._cues)
            history = max(1, int(self.cfg.get("ui", "history_lines", 2)))
            recent = [self._cues[k] for k in sorted(self._cues)[-history:]]
        for c in publish:
            self.sinks.publish(c)
        self._push(kind="cues", cues=[c.to_dict() for c in recent],
                   newest=newest)

    def _push(self, kind: str, **extra) -> None:
        if self.ui_queue is None:
            return
        msg = {"type": kind, "t": round(time.time(), 2),
               "state": self.router.state, "stats": self.stats(), **extra}
        try:
            self.ui_queue.put_nowait(msg)
        except queue.Full:
            pass

    # ------------------------------------------------------------------ 状态
    def apply_hot_update(self, payload: dict):
        applied, rejected = self.cfg.hot_update(payload)
        if any(k.startswith("audio.") for k in applied):
            a = self.cfg.section("audio")
            for f in ("gain", "vad_min_rms", "noise_ratio", "silence_ms",
                      "min_speech_ms", "max_segment_ms", "preroll_ms",
                      "interim_enabled", "interim_interval_ms"):
                if f in a:
                    try:
                        setattr(self.vad, f, type(getattr(self.vad, f))(a[f]))
                    except (TypeError, ValueError):
                        pass
        if "calib.mode" in applied:
            self.calibrator.set_mode(applied["calib.mode"])
        if "calib.enabled" in applied:
            self.calibrator.enabled = bool(applied["calib.enabled"])
        if any(k.startswith("source.") for k in applied) and self.is_running:
            self.switch_source(
                self.cfg.get("source", "type", "loopback"),
                self.cfg.get("source", "device", ""))
        self._push(kind="config",
                   message=f"applied={list(applied)} rejected={rejected}")
        return applied, rejected

    def srt_path(self) -> str:
        for sink in self.sinks.sinks:
            if getattr(sink, "name", "") == "srt":
                return str(getattr(sink, "path", ""))
        return ""

    def stats(self) -> dict:
        return {"running": self.is_running,
                "router": self.router.stats(), "bus": self.bus.stats(),
                "source": self.source.stats() if self.source else {},
                "vad": self.vad.stats(), "local": self.local.stats(),
                "cloud": self.cloud.stats() if self.cloud else {},
                "calib": self.calibrator.stats(),
                "sinks": self.sinks.stats(),
                "srt": self.srt_path(),
                "asr_configured": self.cfg.asr_configured(),
                "local_configured": self.local.configured,
                "segments_produced": self.segments_produced,
                "uptime_s": round(time.time() - self._started_at, 1)
                if self._started_at else 0.0,
                "last_error": self.last_error}
