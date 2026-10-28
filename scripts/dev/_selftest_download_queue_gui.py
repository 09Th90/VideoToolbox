# -*- coding: utf-8 -*-
"""P3b offscreen GUI 队列回归（不启动真实下载线程）。"""
from __future__ import annotations

import json
import os
import queue
import sys
import tempfile
from pathlib import Path

APP_DIR = Path(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))
TMP = APP_DIR / "data" / "tmp" / "download_queue_gui_selftest"
TMP.mkdir(parents=True, exist_ok=True)
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.setdefault("VT_DATA_ROOT", str(TMP / "data_root"))
os.environ["VT_DL_QUEUE"] = "1"
os.environ["VT_DL_ORCH"] = "job"
sys.path.insert(0, str(APP_DIR / "src"))

from PySide6.QtWidgets import QApplication  # noqa: E402
import video_toolbox_qt as gui  # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append({"name": name, "ok": bool(ok), "detail": str(detail)})
    print(("[PASS] " if ok else "[FAIL] ") + name
          + (("  " + str(detail)) if detail else ""), flush=True)


class LibStub:
    def __init__(self):
        self.dirs = []

    def set_dir(self, d):
        self.dirs.append(d)

    def refresh(self):
        pass


class AppStub:
    def __init__(self):
        self.q = queue.Queue()
        self.library_page = LibStub()


def drain(page, app):
    while True:
        try:
            msg = app.q.get_nowait()
        except queue.Empty:
            return
        kind, args = msg[0], msg[1:]
        if kind == "dl_queue_event":
            page.on_queue_event(args[0])
        elif kind == "dl_progress":
            page.on_dl_progress(*args)
        elif kind == "dl_log":
            page.on_dl_log(*args)
        elif kind == "dl_done":
            page.on_dl_done(*args)


def main():
    app = QApplication.instance() or QApplication([])
    gui.engine.open_folder = lambda *a, **k: None
    appstub = AppStub()
    page = gui.DownloadPage(appstub)
    check("8 columns", page.task_table.columnCount() == 8
          and page.task_table.horizontalHeaderItem(4).text() == "速度"
          and page.task_table.horizontalHeaderItem(7).text() == "保存位置")
    check("queue mode", page._queue_mode and page.dl_queue is not None)
    check("pause button initial", not page.pause_btn.isEnabled())
    page.dl_queue.set_max_concurrent(2)
    page.max_spin.blockSignals(True)
    page.max_spin.setValue(2)
    page.max_spin.blockSignals(False)

    starts = []
    def fake_start(tid, run_id):
        starts.append((tid, run_id))
        page._run_ids[tid] = run_id
    page._start_task_worker = fake_start
    info = {"title": "GUI Queue", "formats": [
        {"format_id": "137", "height": 1080, "vcodec": "avc1",
         "acodec": "none", "protocol": "https"},
    ]}
    info_path = TMP / "info.json"
    info_path.write_text(json.dumps(info), encoding="utf-8")
    page.detected_url = ""
    page.qualities = [{"format_id": "137", "height": 1080}]
    page.info_json_path = str(info_path)
    page.dest_edit.setText(str(TMP / "out"))
    page.qlist.clear()
    page.qlist.addItem("1080p")
    page.qlist.setCurrentRow(0)

    urls = [f"http://example.test/{i}" for i in range(5)]
    for u in urls:
        page.detected_url = u
        page.url_edit.setText(u)
        page.start_download()
        drain(page, appstub)
    check("5 queued / 2 running", len(page.tasks) == 5
          and len(starts) == 2 and page.dl_queue.queued_count() == 3,
          f"starts={starts} queued={page.dl_queue.queued_count()}")

    first = starts[0]
    item = page.tasks[first[0]]
    page.on_dl_done(first[0], 0, item["folder"], first[1], "")
    drain(page, appstub)
    check("completion starts next", page.tasks[first[0]]["status"] == "完成"
          and len(starts) == 3, f"starts={len(starts)}")
    check("old run progress ignored", not page.dl_queue.progress(first[0], first[1], 90))

    # 选中一个正在下载的任务并暂停
    running = list(page.dl_queue.snapshot()["running"])
    tid = next((t for t in running if page.tasks[t]["status"] == "下载中"), running[0])
    row = page._row_of[tid]
    page.task_table.selectRow(row)
    run_id = page._run_ids[tid]
    page.pause_selected_task()
    drain(page, appstub)
    page.on_dl_done(tid, page.RC_PAUSED, page.tasks[tid]["folder"], run_id,
                    str(TMP / "resume.json"))
    drain(page, appstub)
    check("pause -> paused", page.tasks[tid]["status"] == "已暂停"
          and page.pause_btn.text() == "继续",
          page.tasks[tid]["status"])

    # 继续（腾出一个槽位，避免被其它运行任务挡住）
    page.dl_queue.set_max_concurrent(4)
    page.task_table.selectRow(row)
    page.pause_selected_task()
    drain(page, appstub)
    check("resume starts new run", page.tasks[tid]["status"] == "下载中"
          and any(t == tid and r != run_id for t, r in starts),
          starts[-3:])

    # 再加一个任务造出排队项，然后取消排队任务
    extra = "http://example.test/extra"
    page.detected_url = extra
    page.url_edit.setText(extra)
    page.start_download()
    drain(page, appstub)
    waiting = list(page.dl_queue.snapshot()["waiting"])
    if waiting:
        wtid = waiting[0]
        page.task_table.selectRow(page._row_of[wtid])
        page.cancel_selected_task()
        drain(page, appstub)
        check("cancel queued", page.tasks[wtid]["status"] == "已取消")
    else:
        check("cancel queued", False, "no waiting task")

    # 并发上限
    page.max_spin.setValue(1)
    drain(page, appstub)
    check("max spin", page.dl_queue.snapshot()["max"] == 1)

    passed = sum(1 for r in RESULTS if r["ok"])
    print("\n%d/%d passed" % (passed, len(RESULTS)))
    out = TMP / "result.json"
    out.write_text(json.dumps(RESULTS, ensure_ascii=False, indent=2), encoding="utf-8")
    page.deleteLater()
    if passed != len(RESULTS):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
