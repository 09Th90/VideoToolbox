# -*- coding: utf-8 -*-
# @version 1.15.0
"""目录感知层（引擎侧，v1.14.0 新增）：监视下载目录，维护文件索引，变更即发信号。

设计要点
--------
* 双通道感知：`QFileSystemWatcher` 即时感知 + 每 5 秒「大小 + mtime」轮询兜底。
  Windows 网络盘 / 部分虚拟盘上 watcher 会静默失效，只靠它会漏事件，所以轮询
  是必须的第二条腿（只负责"感知"，**不负责驱动流水线**）。
* 只做索引，不做业务判断：配对一律转交 `engine.smart_pair()`，本模块不重写、
  不复制任何配对规则（自检会断言 `smart_pair` 被真实调用）。
* 零 Qt 控件依赖：只用 QtCore（QFileSystemWatcher / QTimer / pyqtSignal）。
  PyQt5 缺失或无事件循环时自动退化为"无信号 + 手动 poll_once()"实现，
  纯 CLI 下也能 import 与跑通（自检依赖这一点）。
"""

import os
import threading
import time

try:  # QtCore 可选：无 PyQt5 时退化，逻辑照常可用
    from PyQt5.QtCore import QFileSystemWatcher, QObject, QTimer, pyqtSignal
    _HAS_QT = True
except Exception:  # noqa: BLE001 - 纯 CLI 自检环境
    _HAS_QT = False
    QFileSystemWatcher = None
    QTimer = None
    QObject = object

    def pyqtSignal(*_a, **_k):  # noqa: N802 - 占位，保持类定义语法一致
        return None

import video_toolbox as engine

# ---------- 类型白名单（按扩展名分类） ----------
VIDEO_EXTS = {".mp4", ".mkv", ".webm", ".mov", ".flv", ".avi", ".ts", ".m4v"}
AUDIO_EXTS = {".m4a", ".weba", ".mp3", ".aac", ".wav", ".ogg", ".opus", ".flac"}
SUBTITLE_EXTS = {".srt", ".ass", ".ssa", ".vtt"}
INFO_EXTS = {".txt", ".json"}
COVER_EXTS = {".jpg", ".jpeg", ".png", ".webp"}

KIND_BY_EXT = {}
for _kind, _exts in (("video", VIDEO_EXTS), ("audio", AUDIO_EXTS),
                     ("subtitle", SUBTITLE_EXTS), ("info", INFO_EXTS),
                     ("cover", COVER_EXTS)):
    for _e in _exts:
        KIND_BY_EXT[_e] = _kind

#: smart_pair 的口径（只吃这五种扩展名），索引里其余类型仅供打包阶段附带
PAIR_EXTS = {".mp4", ".m4a", ".weba", ".srt", ".ass"}
#: 扫描时不进入的目录（流水线自身的产物目录，避免"产物又触发一轮"）
SKIP_DIRS = {"成品", "合成结果", "合成输出", "pipeline_work", ".git", "__pycache__"}
#: 轮询兜底间隔（秒）
POLL_INTERVAL = 5.0
#: 「落盘完成」判定：连续观察到同一份内容、且期间稳定超过这么久（秒）
SETTLE_SECS = 2.0
#: 扫描深度（下载目录是「根/视频名/文件」两层，留一层余量）
SCAN_MAX_DEPTH = 3
#: 单个 watcher 最多挂这么多目录（超出只靠轮询）
WATCH_MAX_DIRS = 200


class _Emitter(QObject):
    """Qt 信号 + 普通回调双通道：GUI 用信号，自检/CLI 用回调。"""

    if _HAS_QT:
        files_changed = pyqtSignal(object)   # list[str]

    def __init__(self):
        if _HAS_QT:
            super().__init__()
        self._listeners = []
        if not _HAS_QT:
            self.files_changed = None

    def add_listener(self, cb):
        if callable(cb) and cb not in self._listeners:
            self._listeners.append(cb)
        return cb

    def remove_listener(self, cb):
        if cb in self._listeners:
            self._listeners.remove(cb)

    def _emit_changed(self, paths):
        paths = sorted(paths or ())
        if not paths:
            return
        for cb in list(self._listeners):
            try:
                cb(paths)
            except Exception:  # noqa: BLE001 - 监听者异常不得影响索引
                pass
        if _HAS_QT and self.files_changed is not None:
            try:
                self.files_changed.emit(paths)
            except Exception:  # noqa: BLE001
                pass


def default_dirs():
    """默认监视目录：用户上次使用的下载目录 + data\\downloads（去重、去无效）。"""
    out = []
    for d in (engine.get_saved_download_dir(), engine.DEFAULT_DOWNLOAD_DIR):
        d = str(d or "").strip()
        if not d:
            continue
        try:
            d = os.path.abspath(d)
        except OSError:
            continue
        nd = os.path.normcase(d)
        if d not in out and not any(os.path.normcase(x) == nd for x in out):
            out.append(d)
    return out


class MediaRegistry(_Emitter):
    """文件索引 + 变更通知。

    index: {绝对路径: {path,name,ext,kind,size,mtime,dir}}
    """

    def __init__(self, dirs=None, poll_interval=POLL_INTERVAL, use_watcher=True,
                 max_depth=SCAN_MAX_DEPTH, excludes=None,
                 settle_seconds=SETTLE_SECS):
        _Emitter.__init__(self)
        self.dirs = [os.path.abspath(d) for d in (dirs if dirs is not None
                                                  else default_dirs()) if d]
        self.poll_interval = float(poll_interval or POLL_INTERVAL)
        self.settle_seconds = float(settle_seconds)
        self.max_depth = int(max_depth or SCAN_MAX_DEPTH)
        self.excludes = set()
        for e in (excludes or ()):
            try:
                self.excludes.add(os.path.normcase(os.path.abspath(e)))
            except OSError:
                pass
        self.index = {}
        self._last_sig = {}      # path -> (size, mtime)
        self._stable_from = {}   # path -> 首次观察到"内容不再变化"的时间
        self._seen_count = {}    # path -> 连续观察到相同签名的次数
        self._announced = set()  # 已宣告过"落盘完成"的路径（只宣告一次）
        self._pairs_cache = None
        self._pairs_sig = None
        self._lock = threading.RLock()
        self._running = False
        self._watcher = None
        self._timer = None
        if use_watcher and _HAS_QT and QFileSystemWatcher is not None:
            try:
                self._watcher = QFileSystemWatcher()
                self._watcher.directoryChanged.connect(self._on_watched)
                self._watcher.fileChanged.connect(self._on_watched)
            except Exception:  # noqa: BLE001
                self._watcher = None

    # ---------- 目录集合 ----------
    def set_dirs(self, dirs):
        with self._lock:
            self.dirs = [os.path.abspath(d) for d in (dirs or []) if d]
            self._pairs_cache = None
        self._sync_watch_paths()
        return self.refresh()

    def add_exclude(self, path):
        try:
            self.excludes.add(os.path.normcase(os.path.abspath(path)))
        except OSError:
            pass

    def _iter_dirs(self):
        """监视用目录清单：根 + 限定深度内的子目录（跳过排除项）。"""
        out = []
        for root in self.dirs:
            if not os.path.isdir(root):
                continue
            out.append(root)
            base = root.rstrip(os.sep).count(os.sep)
            for cur, dirs, _files in os.walk(root):
                depth = cur.rstrip(os.sep).count(os.sep) - base
                if depth + 1 >= self.max_depth:
                    dirs[:] = []
                keep = []
                for d in dirs:
                    if d.startswith(".") or d in SKIP_DIRS:
                        continue
                    p = os.path.join(cur, d)
                    if os.path.normcase(p) in self.excludes:
                        continue
                    keep.append(d)
                    out.append(p)
                dirs[:] = keep
                if len(out) >= WATCH_MAX_DIRS:
                    return out[:WATCH_MAX_DIRS]
        return out

    def _iter_files(self):
        """索引用文件清单（限定深度，跳过隐藏文件与排除目录）。"""
        for root in self.dirs:
            if not os.path.isdir(root):
                continue
            base = root.rstrip(os.sep).count(os.sep)
            for cur, dirs, files in os.walk(root):
                depth = cur.rstrip(os.sep).count(os.sep) - base
                if depth >= self.max_depth:
                    dirs[:] = []
                keep = []
                for d in dirs:
                    if d.startswith(".") or d in SKIP_DIRS:
                        continue
                    if os.path.normcase(os.path.join(cur, d)) in self.excludes:
                        continue
                    keep.append(d)
                dirs[:] = keep
                for fn in files:
                    if fn.startswith(".") or fn.endswith(".vt_tmp"):
                        continue
                    yield os.path.join(cur, fn)

    # ---------- 生命周期 ----------
    def start(self):
        with self._lock:
            if self._running:
                return self
            self._running = True
        self.refresh()
        self._sync_watch_paths()
        if _HAS_QT and QTimer is not None:
            try:
                self._timer = QTimer()
                self._timer.setInterval(max(200, int(self.poll_interval * 1000)))
                self._timer.timeout.connect(self.poll_once)
                self._timer.start()
            except Exception:  # noqa: BLE001 - 无 QCoreApplication 时静默降级
                self._timer = None
        return self

    def stop(self):
        with self._lock:
            self._running = False
        try:
            if self._timer is not None:
                self._timer.stop()
        except Exception:  # noqa: BLE001
            pass
        if self._watcher is not None:
            try:
                have = self._watcher.directories() + self._watcher.files()
                if have:
                    self._watcher.removePaths(have)
            except Exception:  # noqa: BLE001
                pass

    def _on_watched(self, _path=""):
        """watch 通道：目录/文件变化 → 立刻重扫（主线程回调）。"""
        self.refresh()

    def poll_once(self):
        """轮询通道：重扫一次并返回变更集合（无 Qt 事件循环时手动驱动）。"""
        return self.refresh()

    # ---------- 索引 ----------
    def refresh(self):
        """重扫目录，返回本次变更的文件路径集合（新增/删除/大小或 mtime 变化）。"""
        new_index, changed = {}, set()
        with self._lock:
            part_dirs = self._scan_part_dirs()
            for p in self._iter_files():
                ext = os.path.splitext(p)[1].lower()
                kind = KIND_BY_EXT.get(ext)
                if kind is None:
                    continue
                try:
                    st = os.stat(p)
                except OSError:
                    continue
                sig = (int(st.st_size), int(st.st_mtime))
                entry = {"path": p, "name": os.path.splitext(os.path.basename(p))[0],
                         "ext": ext, "kind": kind, "size": sig[0],
                         "mtime": sig[1], "dir": os.path.dirname(p)}
                new_index[p] = entry
                # 稳定性：签名变了就重置计时点/计数，没变就累加
                if self._last_sig.get(p) == sig:
                    self._stable_from.setdefault(p, time.time())
                    self._seen_count[p] = self._seen_count.get(p, 1) + 1
                else:
                    self._stable_from[p] = time.time()
                    self._seen_count[p] = 1
                    self._announced.discard(p)
                old = self.index.get(p)
                if old is None or (old["size"], old["mtime"]) != sig:
                    changed.add(p)
                # 「落盘完成」是一次状态跃迁：连续两次看到同一份内容、稳定时间
                # 达标、且同目录没有下载临时文件 → 宣告一次变更。否则下载完成后
                # 就再也不会有任何文件事件，流水线永远等不到"文件齐了"这个信号。
                # 只宣告一次；未达标前不宣告，留待后续轮询继续观察。
                elif (p not in self._announced and self._is_settled_locked(p, part_dirs)):
                    self._announced.add(p)
                    changed.add(p)
            for p in self.index:
                if p not in new_index:
                    changed.add(p)
                    self._stable_from.pop(p, None)
                    self._seen_count.pop(p, None)
                    self._announced.discard(p)
            self.index = new_index
            self._last_sig = {p: (e["size"], e["mtime"]) for p, e in new_index.items()}
            if changed:
                self._pairs_cache = None
        if changed:
            self._sync_watch_paths()
            self._emit_changed(changed)
        return changed

    def _sync_watch_paths(self):
        if self._watcher is None:
            return
        try:
            want = set(self._iter_dirs())
            have = set(self._watcher.directories())
            add = [p for p in (want - have)][:WATCH_MAX_DIRS]
            if add:
                self._watcher.addPaths(add)
            rm = [p for p in (have - want)]
            if rm:
                self._watcher.removePaths(rm)
        except Exception:  # noqa: BLE001
            pass

    # ---------- 查询 ----------
    def files(self, kind=None, exts=None):
        """按类型/扩展名取路径列表（排序稳定，便于比对）。"""
        with self._lock:
            items = list(self.index.values())
        if kind is not None:
            kinds = {kind} if isinstance(kind, str) else set(kind)
            items = [e for e in items if e["kind"] in kinds]
        if exts:
            want = {e.lower() for e in exts}
            items = [e for e in items if e["ext"] in want]
        return sorted(e["path"] for e in items)

    def entry(self, path):
        with self._lock:
            return dict(self.index.get(path) or {})

    def _scan_part_dirs(self):
        """含下载临时文件（.part / .ytdl）的目录集合——这些目录里的文件还没落盘。"""
        out = set()
        for d in self._iter_dirs():
            try:
                for fn in os.listdir(d):
                    low = fn.lower()
                    if low.endswith((".part", ".ytdl")) or ".part" in low:
                        out.add(d)
                        break
            except OSError:
                continue
        return out

    def _is_settled_locked(self, path, part_dirs):
        """（调用方持锁）落盘完成判定。"""
        if self._seen_count.get(path, 0) < 2:
            return False
        t0 = self._stable_from.get(path)
        if not t0 or (time.time() - t0) < self.settle_seconds:
            return False
        return os.path.dirname(path) not in part_dirs

    def is_settled(self, path, min_observations=2):
        """下载是否落盘完成：连续观察到 min_observations 次内容未变、稳定时间
        达标（settle_seconds）、且同目录没有 .part / .ytdl 临时文件。"""
        with self._lock:
            if self._seen_count.get(path, 0) < int(min_observations):
                return False
            t0 = self._stable_from.get(path)
            if not t0 or (time.time() - t0) < self.settle_seconds:
                return False
        return os.path.dirname(path) not in self._scan_part_dirs()

    def stable_seconds(self, path):
        """文件自"内容不再变化"起已经过去多少秒（下载中的文件会一直是 0）。"""
        with self._lock:
            t0 = self._stable_from.get(path)
        return 0.0 if not t0 else max(0.0, time.time() - t0)

    def is_stable(self, path, seconds=2.0):
        return self.stable_seconds(path) >= float(seconds)

    def find_pairs(self, ffprobe=None, force=False):
        """配对：**内部转交 engine.smart_pair**，本模块不实现任何配对规则。

        同一份索引内容只算一次（smart_pair 会为每个文件跑一次 ffprobe，很贵）；
        索引一变缓存即失效。ffprobe 由调用方注入，避免隐式触发联网下载。
        """
        with self._lock:
            sig = tuple(sorted(
                (p, e["size"], e["mtime"]) for p, e in self.index.items()
                if e["ext"] in PAIR_EXTS))
            if not force and self._pairs_cache is not None and self._pairs_sig == sig:
                return self._pairs_cache
            mp4s = self.files(exts={".mp4"})
            m4as = self.files(exts={".m4a"})
            webas = self.files(exts={".weba"})
            srts = self.files(exts={".srt"})
            asss = self.files(exts={".ass"})
        if ffprobe is None:
            try:
                _ff, ffprobe = engine.ensure_ffmpeg()
            except Exception:  # noqa: BLE001
                ffprobe = engine.FFPROBE_PATH
        pairs = engine.smart_pair(mp4s, m4as, webas, srts, asss, ffprobe)
        # smart_pair 返回 (pairs, remaining_mp4, remaining_m4a, remaining_weba)：
        # 对外只暴露 pairs；兼容被 mock 成"只返回列表"的情况
        if isinstance(pairs, tuple) and pairs and isinstance(pairs[0], list):
            pairs = pairs[0]
        with self._lock:
            self._pairs_cache, self._pairs_sig = pairs, sig
        return pairs

    def snapshot(self):
        with self._lock:
            return {p: dict(e) for p, e in self.index.items()}
