# -*- coding: utf-8 -*-
# @version 2.8.0
"""P3a 回归：job 协作式暂停 / 恢复 / 取消（无 Qt、无网络）。"""
from __future__ import annotations

import json
import os
import sys
import threading
from pathlib import Path

APP_DIR = Path(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))
sys.path.insert(0, str(APP_DIR / "src"))
os.environ.setdefault("VT_DATA_ROOT", str(APP_DIR / "data" / "tmp" / "download_pause_selftest"))

from core.download.job import (  # noqa: E402
    DownloadJob, JobHooks, RC_CANCELLED, RC_PAUSED, RunResult,
    run_download_job,
)

RESULTS = []
INFO = {"title": "Pause Video", "formats": [
    {"format_id": "137", "height": 1080, "vcodec": "avc1",
     "acodec": "none", "protocol": "https"},
]}


def check(name, ok, detail=""):
    RESULTS.append({"name": name, "ok": bool(ok), "detail": str(detail)})
    print(("[PASS] " if ok else "[FAIL] ") + name
          + (("  " + str(detail)) if detail else ""), flush=True)


class Runner:
    def __init__(self, folder, *, pause=None, cancel=None, set_pause=False,
                 set_cancel=False, success=False):
        self.folder = Path(folder)
        self.pause = pause
        self.cancel = cancel
        self.set_pause = set_pause
        self.set_cancel = set_cancel
        self.success = success

    def run(self, cmd, *, phase="download"):
        if self.success:
            (self.folder / "video.mp4").write_bytes(b"v" * 1024)
            return RunResult(0, ("ok",))
        (self.folder / "video.mp4.part").write_bytes(b"part")
        if self.set_pause and self.pause is not None:
            self.pause.set()
        if self.set_cancel and self.cancel is not None:
            self.cancel.set()
        return RunResult(1, ("injected",))


def hooks(runner, pause=None, cancel=None, write_info=None):
    return JobHooks(
        run=runner,
        pause=pause,
        cancel=cancel,
        write_info=write_info or (lambda *a: None),
        make_cover=lambda *a: True,
        normalize_srt=lambda p: True,
    )


def folder_for(name):
    folder = APP_DIR / "data" / "tmp" / "download_pause_selftest" / name
    folder.mkdir(parents=True, exist_ok=True)
    for p in folder.iterdir():
        if p.is_file():
            p.unlink()
    return folder


def info_path_for(name):
    path = APP_DIR / "data" / "tmp" / "download_pause_selftest" / f"{name}.json"
    path.write_text(json.dumps(INFO), encoding="utf-8")
    return path


def test_pause_and_resume():
    folder = folder_for("pause")
    pause = threading.Event()
    cancel = threading.Event()
    job = DownloadJob(url="https://example.test/v", folder=str(folder),
                      meta=INFO, format_id="137", require_video=False)
    res = run_download_job(job, hooks(Runner(folder, pause=pause, cancel=cancel,
                                            set_pause=True), pause, cancel))
    resume = folder / ".vtdl.resume.json"
    check("pause keeps part+resume",
          res.paused and not res.cancelled and (folder / "video.mp4.part").exists()
          and resume.exists() and folder.exists(),
          f"paused={res.paused} resume={resume.exists()}")
    # resume with same folder + resume info
    pause.clear()
    cancel.clear()
    job2 = DownloadJob(url="https://example.test/v", folder=str(folder),
                       meta=INFO, format_id="137", info_json_path=str(resume),
                       require_video=True)
    res2 = run_download_job(job2, hooks(Runner(folder, success=True), pause, cancel))
    check("resume completes and cleans",
          res2.ok and (folder / "video.mp4").exists() and not resume.exists(),
          f"ok={res2.ok} err={res2.error}")


def test_cancel():
    folder = folder_for("cancel")
    cancel = threading.Event()
    pause = threading.Event()
    job = DownloadJob(url="https://example.test/v", folder=str(folder),
                      meta=INFO, format_id="137")
    res = run_download_job(job, hooks(Runner(folder, pause=pause, cancel=cancel,
                                            set_cancel=True), pause, cancel))
    check("cancel cleans", res.cancelled and not folder.exists()
          and not (folder / "video.mp4.part").exists(), res.error)


def test_cancel_beats_pause():
    folder = folder_for("cancel_pause")
    cancel = threading.Event()
    pause = threading.Event()
    job = DownloadJob(url="https://example.test/v", folder=str(folder),
                      meta=INFO, format_id="137")
    runner = Runner(folder, pause=pause, cancel=cancel,
                    set_pause=True, set_cancel=True)
    res = run_download_job(job, hooks(runner, pause, cancel))
    check("cancel beats pause", res.cancelled and not res.paused
          and not folder.exists(), res.error)


def test_extract_pause():
    folder = folder_for("extract_pause")
    pause = threading.Event()
    cancel = threading.Event()
    job = DownloadJob(url="https://example.test/v", folder=str(folder))

    def extract(_ytdlp, _url):
        pause.set()
        return json.dumps(INFO)

    h = hooks(Runner(folder, success=True), pause, cancel)
    h.extract = extract
    res = run_download_job(job, h)
    check("pause during extract", res.paused and not (folder / "video.mp4").exists())


def test_pause_after_download_ignored():
    folder = folder_for("pack_pause")
    pause = threading.Event()
    cancel = threading.Event()
    job = DownloadJob(url="https://example.test/v", folder=str(folder),
                      meta=INFO, format_id="137", require_video=True)

    def write_info(*_args):
        pause.set()

    res = run_download_job(job, hooks(Runner(folder, success=True), pause, cancel,
                                      write_info=write_info))
    check("pause after download ignored", res.ok and (folder / "video.mp4").exists(),
          res.error)


def test_pause_none_unchanged():
    folder = folder_for("no_pause")
    job = DownloadJob(url="https://example.test/v", folder=str(folder),
                      meta=INFO, format_id="137", require_video=True)
    res = run_download_job(job, hooks(Runner(folder, success=True)))
    check("pause=None matches P1", res.ok and res.video.endswith("video.mp4"))


def main():
    for fn in (test_pause_and_resume, test_cancel, test_cancel_beats_pause,
               test_extract_pause, test_pause_after_download_ignored,
               test_pause_none_unchanged):
        try:
            fn()
        except Exception as e:  # noqa: BLE001
            check(fn.__name__, False, repr(e))
    passed = sum(1 for r in RESULTS if r["ok"])
    print("\n%d/%d passed" % (passed, len(RESULTS)))
    if passed != len(RESULTS):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
