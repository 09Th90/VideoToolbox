# -*- coding: utf-8 -*-
# @version 2.8.0
"""Range segmented / resumable / checksum downloader (internal core/download module).

Only single-file HTTP(S) resources that support Range. No HLS/DASH, muxing,
DRM, or live streams. Naming is intentionally distinct from Ghost-Downloader-3:
SegmentDownloader / .vtdl.*.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class ProbeResult:
    ok: bool
    url: str = ""
    status: int = 0
    total_size: int = 0
    range_supported: bool = False
    etag: str = ""
    last_modified: str = ""
    content_type: str = ""
    final_url: str = ""
    error: str = ""
    elapsed: float = 0.0


@dataclass
class SegmentState:
    index: int
    start: int
    end: int
    received: int = 0
    done: bool = False


@dataclass(frozen=True)
class SegmentProgress:
    downloaded: int
    total: int
    speed: float = 0.0
    eta: float = -1.0
    segments_done: int = 0
    segments_total: int = 0
    wasted_bytes: int = 0
    source_url: str = ""


@dataclass(frozen=True)
class DownloadRequest:
    url: str
    dest: Path
    mirrors: tuple[str, ...] = ()
    headers: dict[str, str] = field(default_factory=dict)
    expected_size: int | None = None
    expected_sha256: str = ""
    connections: int = 4
    timeout: tuple[float, float] = (5.0, 20.0)
    proxies: dict[str, str] | None = None
    chunk_min: int = 1 << 20
    chunk_max: int = 16 << 20
    overwrite: bool = True
    min_segment_size: int = 2 << 20


@dataclass
class DownloadResult:
    ok: bool
    dest: Path
    cancelled: bool = False
    paused: bool = False
    downloaded: int = 0
    total: int = 0
    sha256: str = ""
    error: str = ""
    elapsed: float = 0.0
    wasted_bytes: int = 0
    source_url: str = ""
    ranges: int = 0


class PermanentError(Exception):
    pass


class TransientError(Exception):
    pass


class RangeIgnored(Exception):
    pass


class MirrorNeeded(Exception):
    pass


class Aborted(Exception):
    pass


class Cancelled(Exception):
    pass


class Paused(Exception):
    pass


PERMANENT_STATUS = frozenset({400, 401, 403, 404, 405, 410, 451})
TRANSIENT_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})
BLOCK = 64 * 1024


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _url_key(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]


def _parse_total(value: str) -> int:
    try:
        return int(value.rsplit("/", 1)[-1])
    except (ValueError, TypeError):
        return 0


def _new_session(req: DownloadRequest):
    # Lazy import: dependency bootstrap should not pay the requests import cost.
    import requests

    s = requests.Session()
    s.trust_env = False
    if req.proxies:
        s.proxies.update(req.proxies)
    return s


def probe_http_range(url: str, *, headers: dict[str, str] | None = None,
                     proxies: dict[str, str] | None = None,
                     timeout=(5.0, 20.0), cancel: threading.Event | None = None) -> ProbeResult:
    """Range 探测：0-0 优先，200 时用 1-1 / HEAD 交叉确认。"""
    started = time.perf_counter()
    h = {**(headers or {}), "Accept-Encoding": "identity"}
    req = DownloadRequest(url=url, dest=Path(os.devnull), headers=h, proxies=proxies, timeout=timeout)
    session = _new_session(req)
    try:
        def one(range_value: str):
            hh = dict(h)
            if range_value:
                hh["Range"] = range_value
            r = session.get(url, headers=hh, stream=True, timeout=timeout)
            try:
                status = r.status_code
                total = 0
                if status == 206:
                    total = _parse_total(r.headers.get("Content-Range", ""))
                elif status == 416:
                    total = _parse_total(r.headers.get("Content-Range", ""))
                elif status in (200, 201):
                    total = int(r.headers.get("Content-Length") or 0)
                return r, status, total, dict(r.headers), str(r.url)
            finally:
                r.close()

        r, status, total, rh, final = one("bytes=0-0")
        if status in PERMANENT_STATUS or status in TRANSIENT_STATUS or status >= 400:
            return ProbeResult(False, url, status, error=f"HTTP {status}",
                               elapsed=time.perf_counter() - started)
        if status == 206:
            return ProbeResult(True, url, status, total, True,
                               etag=rh.get("ETag", ""), last_modified=rh.get("Last-Modified", ""),
                               content_type=rh.get("Content-Type", ""), final_url=final,
                               elapsed=time.perf_counter() - started)
        # 200：服务器忽略 Range；再用 1-1 与 HEAD 交叉确认
        r2, status2, total2, rh2, final2 = one("bytes=1-1")
        if status2 == 206:
            return ProbeResult(True, url, status2, total2, True,
                               etag=rh2.get("ETag", ""), last_modified=rh2.get("Last-Modified", ""),
                               content_type=rh2.get("Content-Type", ""), final_url=final2,
                               elapsed=time.perf_counter() - started)
        if total <= 0:
            try:
                hr = session.head(url, headers=h, timeout=timeout, allow_redirects=True)
                total = int(hr.headers.get("Content-Length") or 0)
                rh = dict(hr.headers)
                final = str(hr.url)
            except Exception:
                pass
        return ProbeResult(True, url, status, total, False,
                           etag=rh.get("ETag", ""), last_modified=rh.get("Last-Modified", ""),
                           content_type=rh.get("Content-Type", ""), final_url=final,
                           elapsed=time.perf_counter() - started)
    except Exception as e:  # noqa: BLE001
        return ProbeResult(False, url, error=str(e), elapsed=time.perf_counter() - started)
    finally:
        session.close()


@dataclass
class _Manifest:
    schema: int
    url_key: str
    total: int
    etag: str
    segments: list[dict]
    expected_sha256: str = ""

    @classmethod
    def load(cls, path: Path) -> "_Manifest | None":
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("schema") != 1:
                return None
            return cls(
                schema=1,
                url_key=str(data.get("url_key") or ""),
                total=int(data.get("total") or 0),
                etag=str(data.get("etag") or ""),
                segments=list(data.get("segments") or []),
                expected_sha256=str(data.get("expected_sha256") or ""),
            )
        except Exception:
            return None

    def to_dict(self) -> dict:
        return asdict(self)


class SegmentDownloader:
    def __init__(self, req: DownloadRequest, *, progress=None, log=None):
        self.req = req
        self.progress_callback = progress
        self.log = log or (lambda _m: None)
        self.cancel_event = threading.Event()
        self.pause_event = threading.Event()
        self._abort_event = threading.Event()
        self._state_lock = threading.Lock()
        self._segments: list[SegmentState] = []
        self._wasted = 0
        self._ranges = 0
        self._last_progress = 0.0
        self._speed_samples: list[tuple[float, int]] = []
        self._last_bytes = 0
        self._started = 0.0
        self._active_url = req.url
        self._total = 0
        self._etag = ""
        self._range_supported = False

    # ---------- public ----------
    def cancel(self) -> None:
        self.cancel_event.set()

    def pause(self) -> None:
        self.pause_event.set()

    def run(self) -> DownloadResult:
        started = time.perf_counter()
        self._started = started
        dest = self.req.dest
        dest.parent.mkdir(parents=True, exist_ok=True)

        if not self.req.overwrite and self._already_complete(dest):
            return DownloadResult(True, dest, downloaded=dest.stat().st_size,
                                  total=dest.stat().st_size,
                                  sha256=self.req.expected_sha256,
                                  elapsed=time.perf_counter() - started)

        candidates = [self.req.url, *self.req.mirrors]
        candidates = list(dict.fromkeys(u for u in candidates if u))
        last_error = ""
        for idx, candidate in enumerate(candidates):
            if self.cancel_event.is_set():
                return self._result(False, dest, cancelled=True, error="cancelled")
            probe = probe_http_range(
                candidate, headers=self.req.headers, proxies=self.req.proxies,
                timeout=self.req.timeout, cancel=self.cancel_event,
            )
            if not probe.ok:
                last_error = f"probe failed: {probe.error}"
                self.log(f"[probe] {candidate} -> {last_error}")
                continue
            self._active_url = candidate
            self._total = probe.total_size
            self._etag = probe.etag
            self._range_supported = probe.range_supported
            self._abort_event.clear()
            self.log(f"[probe] {candidate} total={probe.total_size} range={probe.range_supported}")
            try:
                if probe.range_supported and probe.total_size >= self.req.min_segment_size:
                    return self._run_segmented(probe)
                return self._run_single(probe)
            except MirrorNeeded as e:
                last_error = str(e)
                self.log(f"[mirror] {candidate} -> {last_error}")
                if idx + 1 >= len(candidates):
                    break
                continue
            except (Cancelled, Paused) as e:
                return self._result(False, dest,
                                    cancelled=isinstance(e, Cancelled),
                                    paused=isinstance(e, Paused),
                                    error=str(e) or type(e).__name__)
            except Exception as e:  # noqa: BLE001
                last_error = str(e) or type(e).__name__
                self.log(f"[error] {candidate} -> {last_error}")
                if idx + 1 >= len(candidates):
                    break
                self._abort_event.clear()
                continue
        return self._result(False, dest, error=last_error or "all sources failed")

    # ---------- probing / resume ----------
    def _already_complete(self, dest: Path) -> bool:
        if not dest.is_file():
            return False
        if self.req.expected_size is not None and dest.stat().st_size != self.req.expected_size:
            return False
        if self.req.expected_sha256:
            return _sha256_file(dest).lower() == self.req.expected_sha256.lower()
        return True

    def _record_path(self, dest: Path) -> Path:
        return Path(str(dest) + ".vtdl.json")

    def _part_path(self, dest: Path, index: int) -> Path:
        return Path(str(dest) + f".vtdl.part.{index:05d}")

    def _assemble_path(self, dest: Path) -> Path:
        return Path(str(dest) + ".vtdl.assembling")

    def _save_manifest(self, dest: Path, manifest: _Manifest) -> None:
        path = self._record_path(dest)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)

    def _cleanup_parts(self, dest: Path, manifest: _Manifest | None = None) -> None:
        segs = manifest.segments if manifest else []
        for i in range(max(len(segs), 1)):
            try:
                self._part_path(dest, i).unlink(missing_ok=True)
            except OSError:
                pass
        for p in (self._record_path(dest), self._assemble_path(dest)):
            try:
                p.unlink(missing_ok=True)
            except OSError:
                pass

    def _build_manifest(self, dest: Path, total: int, etag: str) -> _Manifest:
        connections = max(1, int(self.req.connections))
        target = max(self.req.chunk_min, math.ceil(total / (connections * 8)))
        target = min(self.req.chunk_max, target)
        target = max(1, target)
        segments = []
        start = 0
        index = 0
        while start < total:
            end = min(total - 1, start + target - 1)
            segments.append({"i": index, "start": start, "end": end, "done": False})
            start = end + 1
            index += 1
        return _Manifest(1, _url_key(self._active_url), total, etag, segments,
                         self.req.expected_sha256)

    def _load_or_build(self, dest: Path, total: int, etag: str) -> _Manifest:
        manifest = _Manifest.load(self._record_path(dest))
        same_source = bool(manifest) and manifest.url_key == _url_key(self._active_url)
        same_shape = bool(manifest) and manifest.total == total and (
            not manifest.etag or not etag or manifest.etag == etag)
        if manifest and (same_source or same_shape):
            if not manifest.etag or not etag or manifest.etag == etag:
                manifest.url_key = _url_key(self._active_url)
                # 以实际 part 文件大小校正 received，避免上次截断/写坏
                changed = False
                for seg in manifest.segments:
                    part = self._part_path(dest, int(seg["i"]))
                    expected = int(seg["end"]) - int(seg["start"]) + 1
                    actual = part.stat().st_size if part.is_file() else 0
                    if actual > expected:
                        with open(part, "r+b") as f:
                            f.truncate(expected)
                        actual = expected
                    seg["done"] = actual >= expected
                    seg["received"] = actual
                    changed = changed or actual != int(seg.get("received", -1)) or seg["done"] != bool(seg.get("done"))
                if changed:
                    self._save_manifest(dest, manifest)
                return manifest
        if manifest:
            self.log("[resume] manifest 与当前 URL/ETag/大小不匹配，重新开始")
        self._cleanup_parts(dest, manifest)
        manifest = self._build_manifest(dest, total, etag)
        self._save_manifest(dest, manifest)
        return manifest

    def _init_segments(self, manifest: _Manifest) -> None:
        self._segments = [
            SegmentState(
                index=int(s["i"]), start=int(s["start"]), end=int(s["end"]),
                received=int(s.get("received", 0)), done=bool(s.get("done")),
            )
            for s in manifest.segments
        ]

    def _persist_segments(self, dest: Path, manifest: _Manifest) -> None:
        with self._state_lock:
            by_i = {s.index: s for s in self._segments}
            for seg in manifest.segments:
                state = by_i.get(int(seg["i"]))
                if state is not None:
                    seg["received"] = state.received
                    seg["done"] = state.done
            self._save_manifest(dest, manifest)

    # ---------- segmented ----------
    def _run_segmented(self, probe: ProbeResult) -> DownloadResult:
        dest = self.req.dest
        self._abort_event.clear()
        manifest = self._load_or_build(dest, probe.total_size, probe.etag)
        self._init_segments(manifest)
        if all(s.done for s in self._segments):
            return self._finish(dest, manifest)
        self._save_manifest(dest, manifest)

        stop = threading.Event()
        writer = threading.Thread(target=self._manifest_loop, args=(dest, manifest, stop), daemon=True)
        writer.start()
        try:
            with ThreadPoolExecutor(max_workers=max(1, int(self.req.connections))) as pool:
                futures = {
                    pool.submit(self._worker, seg, dest): seg
                    for seg in self._segments if not seg.done
                }
                for fut in as_completed(futures):
                    exc = fut.exception()
                    if exc is None:
                        continue
                    if isinstance(exc, (Cancelled, Paused, RangeIgnored)):
                        raise exc
                    # 有分片失败：中止其余分片，让上层决定换镜像/失败。
                    # abort 保持到 WorkerPool 退出，避免其余 worker 继续写盘。
                    self._abort_event.set()
                    for other in futures:
                        other.cancel()
                    raise exc
            if self.cancel_event.is_set() or self.pause_event.is_set():
                raise Cancelled() if self.cancel_event.is_set() else Paused()
            self._persist_segments(dest, manifest)
            return self._finish(dest, manifest)
        except RangeIgnored:
            self._cleanup_parts(dest, manifest)
            return self._run_single(probe)
        finally:
            stop.set()
            writer.join(timeout=2)

    def _manifest_loop(self, dest: Path, manifest: _Manifest, stop: threading.Event) -> None:
        while not stop.wait(0.5):
            try:
                self._persist_segments(dest, manifest)
                self._emit_progress(force=True)
            except Exception:
                pass

    def _worker(self, seg: SegmentState, dest: Path) -> None:
        part = self._part_path(dest, seg.index)
        expected = seg.end - seg.start + 1
        if part.is_file():
            actual = part.stat().st_size
            if actual > expected:
                with open(part, "r+b") as f:
                    f.truncate(expected)
                actual = expected
            seg.received = actual
            if actual >= expected:
                seg.done = True
                return
        else:
            part.touch()
            seg.received = 0
        attempts = 0
        while not seg.done:
            if self._abort_event.is_set():
                raise Aborted()
            if self.cancel_event.is_set():
                raise Cancelled()
            if self.pause_event.is_set():
                raise Paused()
            attempts += 1
            try:
                self._download_segment(seg, part)
                if seg.received < expected:
                    raise TransientError(f"short segment {seg.index}: {seg.received}/{expected}")
                seg.done = True
                return
            except (Cancelled, Paused, Aborted, PermanentError, RangeIgnored):
                raise
            except Exception as e:  # noqa: BLE001
                if attempts >= 3:
                    raise PermanentError(f"segment {seg.index} failed after {attempts}: {e}") from e
                delay = min(4.0, 0.5 * (2 ** (attempts - 1))) + random.random() * 0.2
                self.log(f"[retry] segment {seg.index} attempt {attempts}: {e}; {delay:.1f}s")
                if self.cancel_event.wait(delay):
                    raise Cancelled()
                if self.pause_event.is_set():
                    raise Paused()

    def _download_segment(self, seg: SegmentState, part: Path) -> None:
        session = _new_session(self.req)
        start = seg.start + seg.received
        if start > seg.end:
            seg.done = True
            return
        headers = {**self.req.headers, "Range": f"bytes={start}-{seg.end}",
                   "Accept-Encoding": "identity"}
        if self._etag:
            headers["If-Range"] = self._etag
        try:
            self._ranges += 1
            r = session.get(self._active_url, headers=headers, stream=True,
                            timeout=self.req.timeout, allow_redirects=True)
            try:
                status = r.status_code
                if status == 200:
                    raise RangeIgnored()
                if status == 416:
                    if seg.received >= (seg.end - seg.start + 1):
                        seg.done = True
                        return
                    raise PermanentError("416 with incomplete segment")
                if status in PERMANENT_STATUS:
                    raise PermanentError(f"HTTP {status}")
                if status in TRANSIENT_STATUS:
                    if status == 429:
                        retry_after = r.headers.get("Retry-After", "")
                        try:
                            wait = min(30.0, float(retry_after))
                        except ValueError:
                            wait = 2.0
                        time.sleep(wait)
                    raise TransientError(f"HTTP {status}")
                if status != 206:
                    raise TransientError(f"unexpected HTTP {status}")
                with open(part, "ab") as f:
                    for chunk in r.iter_content(BLOCK):
                        if self._abort_event.is_set():
                            raise Aborted()
                        if self.cancel_event.is_set():
                            raise Cancelled()
                        if self.pause_event.is_set():
                            raise Paused()
                        if not chunk:
                            continue
                        remaining = seg.end - seg.start + 1 - seg.received
                        if remaining <= 0:
                            break
                        if len(chunk) > remaining:
                            chunk = chunk[:remaining]
                        f.write(chunk)
                        f.flush()
                        seg.received += len(chunk)
                        self._emit_progress()
                        if seg.received >= (seg.end - seg.start + 1):
                            break
            finally:
                r.close()
        finally:
            session.close()

    # ---------- single ----------
    def _run_single(self, probe: ProbeResult) -> DownloadResult:
        dest = self.req.dest
        tmp = Path(str(dest) + ".vtdl.single")
        session = _new_session(self.req)
        try:
            headers = {**self.req.headers, "Accept-Encoding": "identity"}
            r = session.get(self._active_url, headers=headers, stream=True,
                            timeout=self.req.timeout, allow_redirects=True)
            try:
                r.raise_for_status()
                total = int(r.headers.get("Content-Length") or 0) or probe.total_size
                received = 0
                with open(tmp, "wb") as f:
                    for chunk in r.iter_content(BLOCK):
                        if self.cancel_event.is_set():
                            raise Cancelled()
                        if self.pause_event.is_set():
                            raise Paused()
                        if not chunk:
                            continue
                        f.write(chunk)
                        received += len(chunk)
                        self._total = total
                        self._emit_progress(received_override=received)
                if total and received != total:
                    raise TransientError(f"incomplete single stream {received}/{total}")
            finally:
                r.close()
        except (Cancelled, Paused):
            raise
        finally:
            session.close()
        if self.req.expected_size is not None and tmp.stat().st_size != self.req.expected_size:
            raise PermanentError("size mismatch")
        if self.req.expected_sha256 and _sha256_file(tmp).lower() != self.req.expected_sha256.lower():
            raise PermanentError("checksum mismatch")
        os.replace(tmp, dest)
        return DownloadResult(True, dest, downloaded=dest.stat().st_size,
                              total=dest.stat().st_size,
                              sha256=self.req.expected_sha256,
                              elapsed=time.perf_counter() - self._started,
                              ranges=1, source_url=self._active_url)

    # ---------- finish/progress ----------
    def _finish(self, dest: Path, manifest: _Manifest) -> DownloadResult:
        for seg in self._segments:
            if not seg.done:
                raise TransientError(f"segment {seg.index} not done")
        assemble = self._assemble_path(dest)
        h = hashlib.sha256()
        total = 0
        with open(assemble, "wb") as out:
            for seg in sorted(self._segments, key=lambda s: s.index):
                part = self._part_path(dest, seg.index)
                with open(part, "rb") as f:
                    while True:
                        chunk = f.read(1 << 20)
                        if not chunk:
                            break
                        out.write(chunk)
                        h.update(chunk)
                        total += len(chunk)
        if self.req.expected_size is not None and total != self.req.expected_size:
            raise PermanentError(f"size mismatch {total}/{self.req.expected_size}")
        if self.req.expected_sha256 and h.hexdigest().lower() != self.req.expected_sha256.lower():
            raise PermanentError("checksum mismatch")
        os.replace(assemble, dest)
        self._cleanup_parts(dest, manifest)
        return DownloadResult(True, dest, downloaded=total, total=total,
                              sha256=h.hexdigest(), elapsed=time.perf_counter() - self._started,
                              wasted_bytes=self._wasted, source_url=self._active_url,
                              ranges=self._ranges)

    def _result(self, ok: bool, dest: Path, **kwargs) -> DownloadResult:
        return DownloadResult(ok, dest, elapsed=time.perf_counter() - self._started,
                              wasted_bytes=self._wasted, source_url=self._active_url,
                              ranges=self._ranges, **kwargs)

    def _emit_progress(self, *, force: bool = False, received_override: int | None = None) -> None:
        now = time.perf_counter()
        if not force and now - self._last_progress < 0.2:
            return
        with self._state_lock:
            received = received_override if received_override is not None else sum(s.received for s in self._segments)
            total = self._total or (self.req.expected_size or 0)
            done = sum(1 for s in self._segments if s.done)
            count = len(self._segments) or 1
        dt = now - self._last_progress if self._last_progress else 0.0
        if dt > 0:
            inst = max(0, received - self._last_bytes) / dt
            self._speed_samples.append((now, inst))
            self._speed_samples = [(t, v) for t, v in self._speed_samples if now - t < 3.0][-12:]
        speed = sum(v for _, v in self._speed_samples) / len(self._speed_samples) if self._speed_samples else 0.0
        eta = (total - received) / speed if speed > 0 and total > 0 else -1.0
        self._last_progress = now
        self._last_bytes = received
        if self.progress_callback:
            self.progress_callback(SegmentProgress(
                downloaded=received, total=total, speed=speed, eta=eta,
                segments_done=done, segments_total=count,
                wasted_bytes=self._wasted, source_url=self._active_url,
            ))


def download_file(req: DownloadRequest, *, progress=None, log=None) -> DownloadResult:
    return SegmentDownloader(req, progress=progress, log=log).run()
