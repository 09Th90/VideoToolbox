# -*- coding: utf-8 -*-
# @version 2.8.0
"""P1 回归：统一下载编排 job.py（离线 fake runner）。"""
from __future__ import annotations

import json
import os
import sys
import threading
from pathlib import Path

APP_DIR = Path(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))
SRC = APP_DIR / "src"
TMP = APP_DIR / "data" / "tmp" / "download_job_selftest"
for d in (TMP,):
    d.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(SRC))
os.environ.setdefault("VT_DATA_ROOT", str(TMP / "data_root"))

from core.download import job as jobmod  # noqa: E402
from core.download.job import (  # noqa: E402
    DownloadJob, JobHooks, RunResult, run_download_job,
)

RESULTS = []
INFO = {
    "title": "Test Video",
    "formats": [
        {"format_id": "137", "height": 1080, "vcodec": "avc1",
         "acodec": "none", "protocol": "https", "fps": 60, "tbr": 5000},
        {"format_id": "137h", "height": 1080, "vcodec": "avc1",
         "acodec": "none", "protocol": "m3u8_native", "fps": 60, "tbr": 5000},
        {"format_id": "140", "height": 0, "vcodec": "none",
         "acodec": "mp4a", "protocol": "https", "tbr": 128},
    ],
}
INFO_JSON = json.dumps(INFO, ensure_ascii=False)


def check(name, ok, detail=""):
    RESULTS.append({"name": name, "ok": bool(ok), "detail": str(detail)})
    print(("[PASS] " if ok else "[FAIL] ") + name
          + (("  " + str(detail)) if detail else ""), flush=True)


class FakeRunner:
    def __init__(self, folder, outcomes, cancel=None, on_call=None):
        self.folder = Path(folder)
        self.outcomes = list(outcomes)
        self.cancel = cancel
        self.on_call = on_call
        self.calls = []

    def run(self, cmd, *, phase="download"):
        cmd = list(cmd)
        self.calls.append((phase, cmd))
        if self.on_call:
            self.on_call(self, cmd)
        if self.cancel is not None and self.cancel.is_set():
            return RunResult(-9, ("已取消",))
        if self.outcomes:
            outcome = self.outcomes.pop(0)
        else:
            outcome = (0, ())
        rc, lines = outcome
        if rc == 0:
            if "--write-subs" in cmd:
                (self.folder / "test.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\nhi\n",
                                                      encoding="utf-8")
            else:
                (self.folder / "test.mp4").write_bytes(b"x" * 1024)
        return RunResult(rc, tuple(lines))


def make_hooks(runner, folder, cancel=None, *, with_cover=True):
    pack = []
    cover = []
    logs = []
    progress = []
    extract = {"n": 0}

    def do_extract(_ytdlp, _url):
        extract["n"] += 1
        return INFO_JSON

    hooks = JobHooks(
        run=runner,
        cancel=cancel,
        log=lambda m, lv="dim": logs.append((m, lv)),
        progress=progress.append,
        extract=do_extract,
        detect_language=lambda _t: "",
        make_cover=lambda ff, f: (cover.append(f) or with_cover),
        write_info=lambda f, d, q: pack.append((f, d, q)),
        normalize_srt=lambda _p: True,
    )
    return hooks, pack, cover, logs, progress, extract


def base_job(folder, *, info_path="", prefer_hls=True, with_subs=False,
             require_video=True, npe_mode="off", retry_attempts=1,
             max_reextract=2):
    return DownloadJob(
        url="https://example.test/video",
        folder=str(folder),
        meta=INFO,
        info_json_path=info_path,
        format_id="137",
        quality_label="1080p",
        prefer_hls=prefer_hls,
        with_subs=with_subs,
        require_video=require_video,
        npe_mode=npe_mode,
        retry_attempts=retry_attempts,
        max_reextract=max_reextract,
        lock_proxy=False,
    )


def new_folder(name):
    folder = TMP / name
    if folder.exists():
        for p in folder.iterdir():
            if p.is_file():
                p.unlink()
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def scenario_info_reuse():
    folder = new_folder("info_reuse")
    info_path = TMP / "info_reuse.json"
    info_path.write_text(INFO_JSON, encoding="utf-8")
    runner = FakeRunner(folder, [(0, ())])
    hooks, pack, cover, logs, progress, extract = make_hooks(runner, folder)
    job = base_job(folder, info_path=str(info_path), prefer_hls=True)
    res = run_download_job(job, hooks)
    cmd = runner.calls[0][1]
    check("info reuse + hls prefer",
          res.ok and res.video.endswith("test.mp4")
          and "--load-info-json" in cmd and "137h+ba/b" in cmd
          and pack and cover and extract["n"] == 0,
          f"calls={len(runner.calls)}")


def scenario_direct_prefer():
    folder = new_folder("direct_prefer")
    info_path = TMP / "direct_prefer.json"
    info_path.write_text(INFO_JSON, encoding="utf-8")
    runner = FakeRunner(folder, [(0, ())])
    hooks, *_ = make_hooks(runner, folder)
    job = base_job(folder, info_path=str(info_path), prefer_hls=False)
    res = run_download_job(job, hooks)
    cmd = runner.calls[0][1]
    check("direct prefer", res.ok and "137+ba/b" in cmd and "137h+ba/b" not in cmd)


def scenario_info_expired():
    folder = new_folder("info_expired")
    info_path = TMP / "info_expired.json"
    info_path.write_text(INFO_JSON, encoding="utf-8")
    runner = FakeRunner(folder, [(1, ("ERROR: Unable to download webpage",)), (0, ())])
    hooks, pack, cover, logs, progress, extract = make_hooks(runner, folder)
    job = base_job(folder, info_path=str(info_path))
    res = run_download_job(job, hooks)
    check("info reuse fail -> reextract",
          res.ok and extract["n"] == 1 and len(runner.calls) >= 2
          and "--load-info-json" in runner.calls[1][1])


def scenario_retry_412():
    folder = new_folder("retry_412")
    runner = FakeRunner(folder, [
        (1, ("HTTP Error 412",)),
        (1, ("HTTP Error 412",)),
        (1, ("HTTP Error 412",)),
        (0, ()),
    ])
    hooks, pack, cover, logs, progress, extract = make_hooks(runner, folder)
    old = jobmod.sleep_cancellable
    jobmod.sleep_cancellable = lambda _s, _c=None: False
    try:
        job = base_job(folder, retry_attempts=2)
        res = run_download_job(job, hooks)
    finally:
        jobmod.sleep_cancellable = old
    check("412 retry", res.ok and len(runner.calls) >= 4, f"calls={len(runner.calls)}")


def scenario_eof_success():
    folder = new_folder("eof_success")
    info_path = TMP / "eof_success.json"
    info_path.write_text(INFO_JSON, encoding="utf-8")
    runner = FakeRunner(folder, [
        (1, ("ERROR: Got error: EOF occurred in violation of protocol",)),
        (0, ()),
    ])
    hooks, pack, cover, logs, progress, extract = make_hooks(runner, folder)
    job = base_job(folder, info_path=str(info_path), max_reextract=2)
    res = run_download_job(job, hooks)
    check("EOF reextract success", res.ok and extract["n"] == 1
          and len(runner.calls) >= 2, f"calls={len(runner.calls)}")


def scenario_eof_exhaust():
    folder = new_folder("eof_exhaust")
    info_path = TMP / "eof_exhaust.json"
    info_path.write_text(INFO_JSON, encoding="utf-8")
    runner = FakeRunner(folder, [
        (1, ("ERROR: Got error: EOF occurred in violation of protocol",)),
        (1, ("ERROR: Got error: EOF occurred in violation of protocol",)),
        (1, ("HTTP Error 403",)),
    ])
    hooks, pack, cover, logs, progress, extract = make_hooks(runner, folder)
    job = base_job(folder, info_path=str(info_path), max_reextract=1)
    job.format_id = "140"  # no HLS alt, isolate EOF exhaustion
    res = run_download_job(job, hooks)
    check("EOF exhaust fails cleanly", (not res.ok) and not (folder / "test.mp4").exists(),
          res.error)


def scenario_hls_hidden_audio():
    folder = new_folder("hls_hidden")
    runner = FakeRunner(folder, [
        (1, ("HTTP Error 500",)),       # primary direct
        (1, ("HTTP Error 500",)),       # fallback load-info
        (1, ("HTTP Error 500",)),       # fallback URL
        (1, ("HTTP Error 500",)),       # alt+ba/b load-info
        (1, ("HTTP Error 500",)),       # alt+ba/b URL
        (0, ()),                        # alt+233/234/b load-info
    ])
    hooks, pack, cover, logs, progress, extract = make_hooks(runner, folder)
    job = base_job(folder, prefer_hls=False, retry_attempts=1)
    res = run_download_job(job, hooks)
    selectors = [c[1][c[1].index("-f") + 1] for c in runner.calls if "-f" in c[1]]
    check("HLS hidden audio fallback", res.ok and "137h+233/234/b" in selectors,
          f"selectors={selectors}")


class FakeNpe:
    @staticmethod
    def is_available():
        return True, ""

    @staticmethod
    def probe(*_a, **_k):
        return {"ok": True, "title": "NPE"}

    @staticmethod
    def download(_info, folder, _ffmpeg, **_k):
        path = Path(folder) / "npe.mp4"
        path.write_bytes(b"n" * 1024)
        return True, str(path), ""

    @staticmethod
    def error_hint(_info):
        return "nope"


def scenario_npe():
    folder = new_folder("npe")
    runner = FakeRunner(folder, [
        (1, ("HTTP Error 500",)),  # primary URL
        (1, ("HTTP Error 500",)),  # fallback load-info
        (1, ("HTTP Error 500",)),  # fallback URL
    ])
    hooks, pack, cover, logs, progress, extract = make_hooks(runner, folder)
    old_mod = sys.modules.get("npe_backend")
    sys.modules["npe_backend"] = FakeNpe
    old_mode = jobmod.npe_engine_mode
    old_proxy = jobmod.npe_proxy_url
    old_cookie = jobmod.npe_cookie_file
    jobmod.npe_engine_mode = lambda: "auto"
    jobmod.npe_proxy_url = lambda: ""
    jobmod.npe_cookie_file = lambda log=None: ""
    try:
        job = base_job(folder, npe_mode="auto", max_reextract=0)
        job.format_id = "140"  # no HLS alt, isolate NPE
        res = run_download_job(job, hooks)
    finally:
        jobmod.npe_engine_mode = old_mode
        jobmod.npe_proxy_url = old_proxy
        jobmod.npe_cookie_file = old_cookie
        if old_mod is None:
            sys.modules.pop("npe_backend", None)
        else:
            sys.modules["npe_backend"] = old_mod
    check("NPE fallback", res.ok and res.video.endswith("npe.mp4")
          and res.source == "npe", f"source={res.source} err={res.error}")


def scenario_cancel():
    folder = new_folder("cancel")
    (folder / "junk.part").write_bytes(b"junk")
    cancel = threading.Event()
    runner = FakeRunner(folder, [], cancel=cancel)
    runner.on_call = lambda _r, _cmd: cancel.set()
    hooks, pack, cover, logs, progress, extract = make_hooks(runner, folder, cancel)
    job = base_job(folder)
    res = run_download_job(job, hooks)
    check("cancel cleanup", res.cancelled and not folder.exists(),
          f"folder_exists={folder.exists()} err={res.error}")


def scenario_subs_pack():
    folder = new_folder("subs_pack")
    (folder / "leftover.part").write_bytes(b"junk")
    runner = FakeRunner(folder, [(0, ()), (0, ())])
    hooks, pack, cover, logs, progress, extract = make_hooks(runner, folder)
    job = base_job(folder, with_subs=True)
    res = run_download_job(job, hooks)
    check("subs + pack + leftover cleanup",
          res.ok and len(res.subtitles) == 1 and pack and cover
          and not (folder / "leftover.part").exists(),
          f"subs={res.subtitles}")


def source_checks():
    text = Path(jobmod.__file__).read_text(encoding="utf-8")
    sub = Path(jobmod.__file__).with_name("subtitles.py").read_text(encoding="utf-8")
    forbidden = ("import PySide6", "from PySide6", "import PyQt", "from PyQt",
                 "import qfluentwidgets", "from qfluentwidgets",
                 "from core.pipeline", "import core.pipeline",
                 "from pipeline", "import pipeline")
    ok = all(x not in text for x in forbidden) and "normalize_rolling_srt(" not in text
    ok = ok and all(x not in sub for x in forbidden)
    check("job/subtitles no Qt/pipeline", ok)


def main():
    source_checks()
    for fn in (
        scenario_info_reuse, scenario_direct_prefer, scenario_info_expired,
        scenario_retry_412, scenario_eof_success, scenario_eof_exhaust,
        scenario_hls_hidden_audio, scenario_npe, scenario_cancel,
        scenario_subs_pack,
    ):
        try:
            fn()
        except Exception as e:  # noqa: BLE001
            check(fn.__name__, False, repr(e))
    passed = sum(1 for r in RESULTS if r["ok"])
    print("\n%d/%d passed" % (passed, len(RESULTS)))
    out = TMP / "selftest_result.json"
    out.write_text(json.dumps(RESULTS, ensure_ascii=False, indent=2), encoding="utf-8")
    if passed != len(RESULTS):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
