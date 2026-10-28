# -*- coding: utf-8 -*-
# @version 2.8.0
"""P2 回归：分段/断点/校验下载器 + deps._download 原子替换（本地 fixture，无外网）。"""
from __future__ import annotations

import hashlib
import json
import os
import socket
import subprocess
import sys
import threading
import time
from collections import defaultdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

APP_DIR = Path(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))
SRC = APP_DIR / "src"
TMP = APP_DIR / "data" / "tmp" / "segment_selftest"
FIXTURES = TMP / "fixtures"
DOWNLOADS = TMP / "downloads"
for d in (TMP, FIXTURES, DOWNLOADS):
    d.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(SRC))
os.environ.setdefault("VT_DATA_ROOT", str(TMP / "data_root"))

BLOCK = bytes(range(256)) * 4096
RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append({"name": name, "ok": bool(ok), "detail": str(detail)})
    print(("[PASS] " if ok else "[FAIL] ") + name
          + (("  " + str(detail)) if detail else ""), flush=True)


def ensure_file(path: Path, size: int) -> Path:
    if path.is_file() and path.stat().st_size == size:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".creating")
    remain = size
    with open(tmp, "wb") as f:
        while remain > 0:
            chunk = BLOCK[:min(len(BLOCK), remain)]
            f.write(chunk)
            remain -= len(chunk)
    os.replace(tmp, path)
    return path


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class State:
    def __init__(self):
        self.lock = threading.Lock()
        self.stats = []
        self.fail = defaultdict(int)
        self.drop = defaultdict(int)

    def reset(self):
        with self.lock:
            self.stats.clear()
            self.fail.clear()
            self.drop.clear()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    @property
    def state(self):
        return self.server.state

    def log_message(self, *args):
        pass

    def _error(self, code, text="", headers=None):
        body = (text or str(code)).encode()
        self.send_response(code)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)
        self.close_connection = True

    def do_GET(self):
        parsed = urlparse(self.path)
        path, query = parsed.path, parse_qs(parsed.query)
        if path == "/stats":
            body = json.dumps(self.state.stats).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path == "/reset":
            self.state.reset()
            self._error(200, "ok")
            return
        route = ""
        name = ""
        for prefix in ("/f/", "/norange/", "/slow/", "/flaky/"):
            if path.startswith(prefix):
                route, name = prefix.strip("/"), path[len(prefix):]
                break
        if not route or not name:
            self._error(404)
            return
        fp = ensure_file(FIXTURES / Path(name).name, _size_of(name))
        size = fp.stat().st_size
        key = route + "/" + name
        with self.state.lock:
            n = self.state.fail[key]
            self.state.fail[key] += 1
            d = self.state.drop[key]
            self.state.drop[key] += 1
        if route == "flaky":
            fail = int(query.get("fail", ["0"])[0])
            skip = int(query.get("skip", ["0"])[0])
            code = int(query.get("code", ["500"])[0])
            drop = int(query.get("drop", ["0"])[0])
            if skip <= n < skip + fail:
                extra = {"Retry-After": query.get("retry_after", ["1"])[0]}
                self._error(code, "injected", extra if code == 429 else None)
                return
            drop_after = int(query.get("drop_after", [str(1 << 20)])[0]) if d < drop else 0
        else:
            drop_after = 0
        rng = None
        header = self.headers.get("Range", "")
        if route != "norange" and header.startswith("bytes="):
            try:
                left, right = header[6:].split("-", 1)
                start = int(left) if left else 0
                end = int(right) if right else size - 1
                if start >= size:
                    self.send_response(416)
                    self.send_header("Content-Range", "bytes */%d" % size)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                rng = (start, min(end, size - 1))
            except ValueError:
                rng = None
        start, end = (0, size - 1) if rng is None else rng
        length = end - start + 1
        self.send_response(206 if rng is not None else 200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(length))
        self.send_header("Accept-Ranges", "none" if route == "norange" else "bytes")
        self.send_header("ETag", '"%x-%s"' % (size, key))
        if rng is not None:
            self.send_header("Content-Range", "bytes %d-%d/%d" % (start, end, size))
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        bps = int(query.get("bps", ["0"])[0]) if route == "slow" else 0
        sent = 0
        try:
            with open(fp, "rb") as f:
                f.seek(start)
                remain = length
                while remain > 0:
                    chunk = f.read(min(64 * 1024, remain))
                    if not chunk:
                        break
                    if drop_after and sent + len(chunk) > drop_after:
                        allow = max(0, drop_after - sent)
                        if allow:
                            self.wfile.write(chunk[:allow])
                            sent += allow
                        raise ConnectionResetError("drop")
                    self.wfile.write(chunk)
                    sent += len(chunk)
                    remain -= len(chunk)
                    if bps:
                        time.sleep(len(chunk) / bps)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            self.state.stats.append({"path": path, "range": header, "bytes": sent,
                                     "total": size})


def _size_of(name):
    stem = Path(name).stem.lower()
    if stem.endswith("mb") and stem[:-2].isdigit():
        return int(stem[:-2]) * 1024 * 1024
    return 8 * 1024 * 1024


def start_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    server.state = State()
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, "http://127.0.0.1:%d" % server.server_address[1]


def clean(dest: Path):
    dest.parent.mkdir(parents=True, exist_ok=True)
    for p in (dest, Path(str(dest) + ".vtdl.json"),
              Path(str(dest) + ".vtdl.single"), Path(str(dest) + ".vtdl.assembling"),
              Path(str(dest) + ".part")):
        p.unlink(missing_ok=True)
    for p in dest.parent.glob(dest.name + ".vtdl.part.*"):
        p.unlink(missing_ok=True)


def check_ensure_paths(deps):
    import hashlib
    import zipfile
    root = TMP / "ensure"
    root.mkdir(parents=True, exist_ok=True)
    ffzip = root / "ff.zip"
    with zipfile.ZipFile(ffzip, "w") as z:
        z.writestr("build/bin/ffmpeg.exe", b"FFMPEG")
        z.writestr("build/bin/ffprobe.exe", b"FFPROBE")
    mpvzip = root / "mpv.zip"
    with zipfile.ZipFile(mpvzip, "w") as z:
        z.writestr("pkg/libmpv-2.dll", b"DLLDATA" * 1000)
    exe = root / "yt-dlp.exe"
    exe.write_bytes(b"YTDLP" * 100000)

    saved = {k: getattr(deps, k) for k in (
        "TOOLS_DIR", "FFMPEG_ZIP_URL", "FFMPEG_PATH", "FFPROBE_PATH",
        "MPV_DLL_URL", "_MPV_DLL_SHA256", "YTDLP_URL", "YTDLP_PATH",
        "_MIN_FFMPEG_SIZE", "_MIN_YTDLP_SIZE",
    )}
    orig_which = deps.shutil.which
    try:
        deps.TOOLS_DIR = str(root / "tools")
        os.makedirs(deps.TOOLS_DIR, exist_ok=True)
        deps.FFMPEG_ZIP_URL = ffzip.resolve().as_uri()
        deps.FFMPEG_PATH = str(root / "tools" / "ffmpeg.exe")
        deps.FFPROBE_PATH = str(root / "tools" / "ffprobe.exe")
        deps.MPV_DLL_URL = mpvzip.resolve().as_uri()
        deps._MPV_DLL_SHA256 = hashlib.sha256(b"DLLDATA" * 1000).hexdigest()
        deps.YTDLP_URL = exe.resolve().as_uri()
        deps.YTDLP_PATH = str(root / "tools" / "yt-dlp.exe")
        deps._MIN_FFMPEG_SIZE = 1
        deps._MIN_YTDLP_SIZE = 1
        deps._fetch_ytdlp_sha256 = lambda log=None: hashlib.sha256(exe.read_bytes()).hexdigest()
        deps.shutil.which = lambda name: None
        p1 = deps.ensure_ytdlp()
        check("ensure_ytdlp atomic", Path(p1).read_bytes() == exe.read_bytes())
        p2, p3 = deps.ensure_ffmpeg()
        check("ensure_ffmpeg extracts", Path(p2).read_bytes() == b"FFMPEG"
              and Path(p3).read_bytes() == b"FFPROBE")
        ok, err = deps.ensure_mpv_dll(str(root / "mpv"))
        check("ensure_mpv_dll sha256", ok and Path(root / "mpv" / "libmpv-2.dll").read_bytes() == b"DLLDATA" * 1000,
              err)
    finally:
        deps.shutil.which = orig_which
        for k, v in saved.items():
            setattr(deps, k, v)


def main():
    from core.download import segment as seg
    import core.download.deps as deps

    server, base = start_server()
    try:
        src = ensure_file(FIXTURES / "8mb.bin", 8 * 1024 * 1024)
        sha = sha256_file(src)
        size = src.stat().st_size
        dest = DOWNLOADS / "basic.bin"
        clean(dest)
        r = seg.download_file(seg.DownloadRequest(
            base + "/f/8mb.bin", dest, expected_size=size,
            expected_sha256=sha, connections=4))
        check("basic segmented", r.ok and dest.is_file() and sha256_file(dest) == sha,
              "ranges=%s" % r.ranges)
        clean(dest)

        dest = DOWNLOADS / "norange.bin"
        clean(dest)
        r = seg.download_file(seg.DownloadRequest(
            base + "/norange/8mb.bin", dest, expected_size=size,
            expected_sha256=sha, connections=4))
        check("no-range fallback", r.ok and dest.is_file() and sha256_file(dest) == sha)
        clean(dest)

        dest = DOWNLOADS / "badsha.bin"
        clean(dest)
        r = seg.download_file(seg.DownloadRequest(
            base + "/f/8mb.bin", dest, expected_size=size,
            expected_sha256="0" * 64, connections=4))
        check("checksum mismatch rejected", (not r.ok) and not dest.exists(), r.error)
        clean(dest)

        dest = DOWNLOADS / "flaky.bin"
        clean(dest)
        server.state.reset()
        r = seg.download_file(seg.DownloadRequest(
            base + "/flaky/8mb.bin?fail=0&drop=1", dest, expected_size=size,
            expected_sha256=sha, connections=2))
        check("drop retry recovers", r.ok and dest.is_file() and sha256_file(dest) == sha)
        clean(dest)

        dest = DOWNLOADS / "rate429.bin"
        clean(dest)
        server.state.reset()
        t0 = time.perf_counter()
        r = seg.download_file(seg.DownloadRequest(
            base + "/flaky/8mb.bin?skip=1&fail=1&code=429&retry_after=1",
            dest, expected_size=size, expected_sha256=sha, connections=2))
        check("429 retry-after recovers", r.ok and dest.is_file()
              and sha256_file(dest) == sha and time.perf_counter() - t0 >= 0.8)
        clean(dest)

        dest = DOWNLOADS / "cancel.bin"
        clean(dest)
        dl = seg.SegmentDownloader(seg.DownloadRequest(
            base + "/slow/32mb.bin?bps=1048576", dest, connections=4,
            expected_size=32 * 1024 * 1024))
        thread = threading.Thread(target=dl.run, daemon=True)
        thread.start()
        time.sleep(1.0)
        dl.cancel()
        thread.join(timeout=4)
        parts = list(dest.parent.glob(dest.name + ".vtdl.part.*"))
        check("cancel keeps parts", (not thread.is_alive()) and not dest.exists() and bool(parts),
              "parts=%s" % len(parts))

        # 取消后的分片继续下载，验证 manifest 复用（不重新拉全部 32MB）
        server.state.reset()
        r = seg.download_file(seg.DownloadRequest(
            base + "/slow/32mb.bin?bps=1048576", dest,
            expected_size=32 * 1024 * 1024, expected_sha256=sha256_file(
                ensure_file(FIXTURES / "32mb.bin", 32 * 1024 * 1024)),
            connections=4))
        served = sum(x["bytes"] for x in server.state.stats)
        check("resume after cancel", r.ok and served < 32 * 1024 * 1024
              and dest.is_file(), "served=%s" % served)
        clean(dest)

        dest = DOWNLOADS / "mirror.bin"
        clean(dest)
        server.state.reset()
        r = seg.download_file(seg.DownloadRequest(
            base + "/flaky/8mb.bin?fail=3", dest,
            mirrors=(base + "/f/8mb.bin",), expected_size=size,
            expected_sha256=sha, connections=4))
        check("mirror fallback", r.ok and dest.is_file() and sha256_file(dest) == sha)
        clean(dest)

        dest = DOWNLOADS / "deps_atomic.bin"
        clean(dest)
        d = sha256_file(ensure_file(FIXTURES / "8mb.bin", 8 * 1024 * 1024))
        deps._download(base + "/f/8mb.bin", dest, "deps-test",
                       expected_size=size, expected_sha256=d)
        check("deps._download segmented atomic",
              dest.is_file() and sha256_file(dest) == d)

        os.environ["VT_DEPS_SEGMENTED"] = "0"
        dest = DOWNLOADS / "deps_single.bin"
        clean(dest)
        deps._download(base + "/f/8mb.bin", dest, "deps-single",
                       expected_size=size, expected_sha256=d)
        check("deps._download single fallback",
              dest.is_file() and sha256_file(dest) == d)
        os.environ.pop("VT_DEPS_SEGMENTED", None)
        clean(dest)

        # MPV 校验函数（不下载 39MB）：正确/错误 SHA
        fake = DOWNLOADS / "fake_mpv.bin"
        fake.write_bytes(b"fake dll")
        good = hashlib.sha256(fake.read_bytes()).hexdigest()
        deps._verify(fake, expected_sha256=good)
        try:
            deps._verify(fake, expected_sha256="0" * 64)
            bad_ok = False
        except RuntimeError:
            bad_ok = True
        check("mpv/deps sha256 verify helper", bad_ok)
        # 旧完整文件保护：错误 SHA 不得覆盖已有 dest
        dest = DOWNLOADS / "deps_keep_old.bin"
        clean(dest)
        dest.write_bytes(b"OLD-GOOD-FILE")
        try:
            deps._download(base + "/f/8mb.bin", dest, "deps-bad-sha",
                           expected_size=size, expected_sha256="0" * 64)
            kept = False
        except Exception:
            kept = dest.is_file() and dest.read_bytes() == b"OLD-GOOD-FILE"
        check("deps._download keeps old file on failure", kept)
        clean(dest)
        check_ensure_paths(deps)
        fake.unlink(missing_ok=True)

    finally:
        server.shutdown()
        server.server_close()

    passed = sum(1 for r in RESULTS if r["ok"])
    print("\n%d/%d passed" % (passed, len(RESULTS)))
    out = TMP / "selftest_result.json"
    out.write_text(json.dumps(RESULTS, ensure_ascii=False, indent=2), encoding="utf-8")
    if passed != len(RESULTS):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
