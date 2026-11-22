# -*- coding: utf-8 -*-
# @version 3.2.5
"""目录感知层（引擎侧，v1.14.0 新增）：监视下载目录，维护文件索引，变更即发信号。

设计要点
--------
* 双通道感知：`QFileSystemWatcher` 即时感知 + 每 5 秒「大小 + mtime」轮询兜底。
  Windows 网络盘 / 部分虚拟盘上 watcher 会静默失效，只靠它会漏事件，所以轮询
  是必须的第二条腿（只负责"感知"，**不负责驱动流水线**）。
* 只做索引，不做业务判断：配对一律转交 `engine.smart_pair()`，本模块不重写、
  不复制任何配对规则（自检会断言 `smart_pair` 被真实调用）。
* 零 Qt 控件依赖：只用 QtCore（QFileSystemWatcher / QTimer / Signal）。
  PySide6 缺失或无事件循环时自动退化为"无信号 + 手动 poll_once()"实现，
  纯 CLI 下也能 import 与跑通（自检依赖这一点）。
"""

import os
import threading
import time

try:  # QtCore 可选：无 PySide6 时退化，逻辑照常可用
    from PySide6.QtCore import QFileSystemWatcher, QObject, QTimer, Signal
    _HAS_QT = True
except Exception:  # noqa: BLE001 - 纯 CLI 自检环境
    _HAS_QT = False
    QFileSystemWatcher = None
    QTimer = None
    QObject = object

    def Signal(*_a, **_k):  # noqa: N802 - 占位，保持类定义语法一致
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

#: smart_pair 的口径，索引里其余类型仅供打包阶段附带。
#: v1.18.0：视频侧改为跟随 engine.MERGE_VIDEO_EXTS（不再只 .mp4），否则
#: 「同名 webm + m4a」目录在流水线里恒配不出对（find_pairs 只喂 mp4）。
PAIR_EXTS = set(engine.MERGE_VIDEO_EXTS) | {".m4a", ".weba", ".srt", ".ass"}
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
        files_changed = Signal(object)   # list[str]

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

    线程模型（v3.1.5 卡死修复）
    --------------------------
    * 全量扫描（os.scandir + 逐文件 stat）是重 IO，**绝不持 self._lock 做**，
      也绝不在主线程同步跑——否则主线程查询/事件循环会被占住或等锁 >5s，
      触发 hang_watchdog。扫描放后台合并式 worker（_request_scan/_scan_loop）。
    * refresh()/poll_once() 保留**同步**语义（自检 CLI 与 Pipeline.evaluate
      的 refresh→snapshot 同步链依赖）：调用线程内完成扫描+索引合并再返回。
    * Qt 亲和尾部（QFileSystemWatcher 增删路径、发变更通知）经 _scan_tail
      信号 marshaling 回主线程（跨线程 emit 自动 queued）。
    """

    if _HAS_QT:
        _scan_tail = Signal(object)   # 后台扫描结果 → 主线程做 watcher/emit 尾部

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
        self._debounce = None
        # 后台合并式扫描 worker 状态（锁内登记+启动，与 pipeline._schedule_evaluate 同构）
        self._scan_pending = False
        self._scan_force = False
        self._scan_thread = None
        # 轮询快路径：上次扫描访问到的目录 mtime 签名 + 是否仍有未落盘文件
        self._dir_mtime = {}
        self._has_unsettled = False
        if _HAS_QT:
            self._scan_tail.connect(self._on_scan_tail)
        else:
            self._scan_tail = None
        if use_watcher and _HAS_QT and QFileSystemWatcher is not None:
            try:
                self._watcher = QFileSystemWatcher()
                self._watcher.directoryChanged.connect(self._on_watched)
                self._watcher.fileChanged.connect(self._on_watched)
                # 去抖合并：一次任务完成（改名/封面/信息txt/字幕…）会连发多个
                # directoryChanged，每个都全量重扫会把主线程连续占住——
                # 800ms 内的突发合并为一次**后台**重扫（watcher 触发强制扫描）。
                self._debounce = QTimer()
                self._debounce.setSingleShot(True)
                self._debounce.setInterval(800)
                self._debounce.timeout.connect(self._watch_scan)
            except Exception:  # noqa: BLE001
                self._watcher = None
                self._debounce = None

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

    def _iter_files(self, dir_mtime_out=None):
        """索引用文件清单（限定深度，跳过隐藏文件与排除目录），yield (path, stat)。

        用 os.scandir + DirEntry.stat()（结果缓存）替代 os.walk + 独立 os.stat，
        省一半 syscall；深度/跳过语义与旧 os.walk 版逐条对齐（相对深度 0 起，
        depth>=max_depth 不再下钻，但该层文件仍产出；不跟随符号链接下钻）。
        dir_mtime_out 非 None 时顺带记录每个访问目录的 mtime（供轮询快路径）。
        """
        with self._lock:
            dirs = list(self.dirs)
            excludes = set(self.excludes)
            max_depth = self.max_depth
        for root in dirs:
            if not os.path.isdir(root):
                continue
            stack = [(root, 0)]
            while stack:
                cur, depth = stack.pop()
                if dir_mtime_out is not None:
                    try:
                        # 纳秒精度：整秒截断会漏检「同一秒内新增/删除文件」
                        dir_mtime_out[cur] = os.stat(cur).st_mtime_ns
                    except OSError:
                        pass
                try:
                    it = os.scandir(cur)
                except OSError:
                    continue
                with it:
                    subdirs = []
                    for entry in it:
                        name = entry.name
                        try:
                            is_dir = entry.is_dir(follow_symlinks=False)
                        except OSError:
                            continue
                        if is_dir:
                            if depth >= max_depth:
                                continue
                            if name.startswith(".") or name in SKIP_DIRS:
                                continue
                            if os.path.normcase(entry.path) in excludes:
                                continue
                            subdirs.append((entry.path, depth + 1))
                        else:
                            # 指向目录的符号链接：os.walk 既不下钻也不当文件，跳过
                            if entry.is_symlink():
                                try:
                                    if entry.is_dir():
                                        continue
                                except OSError:
                                    continue
                            if name.startswith(".") or name.endswith(".vt_tmp"):
                                continue
                            try:
                                st = entry.stat()
                            except OSError:
                                continue
                            yield entry.path, st
                    stack.extend(subdirs)

    # ---------- 生命周期 ----------
    def start(self):
        with self._lock:
            if self._running:
                return self
            self._running = True
        # 不在主线程同步全量扫描：watcher 装配（主线程亲和）+ 后台首扫。
        # GUI 侧首扫已由 pipeline-boot 线程完成，这里 force=False 命中快路径即跳过。
        self._sync_watch_paths()
        self._request_scan(force=False)
        if _HAS_QT and QTimer is not None:
            try:
                self._timer = QTimer()
                self._timer.setInterval(max(200, int(self.poll_interval * 1000)))
                self._timer.timeout.connect(self._poll_tick)
                self._timer.start()
            except Exception:  # noqa: BLE001 - 无 QCoreApplication 时静默降级
                self._timer = None
        return self

    def stop(self):
        with self._lock:
            self._running = False
            self._scan_pending = False
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
        """watch 通道：目录/文件变化 → 去抖窗口（800ms）后统一**后台**重扫。

        主线程回调只做去抖登记，绝不在此同步全量扫描（突发事件风暴会占住主线程）。
        watcher 触发意味着确有变化，force=True 绕过快路径。
        """
        if self._debounce is not None:
            self._debounce.start()
        else:
            self._request_scan(force=True)

    def _watch_scan(self):
        """去抖 QTimer 到期：强制后台重扫。"""
        self._request_scan(force=True)

    def _poll_tick(self):
        """周期 QTimer（主线程）：只登记一次后台扫描，force=False 允许快路径跳过。"""
        self._request_scan(force=False)

    def poll_once(self):
        """手动驱动（自检/CLI，无 Qt 事件循环）：**同步**重扫并返回变更集合。"""
        return self.refresh()

    # ---------- 后台合并式扫描 worker ----------
    def _request_scan(self, force=False):
        """登记一次待扫描：已有 worker 在跑就合并（force 取或），否则起一个。

        锁内登记+启动（与 pipeline._schedule_evaluate 同构）：pending 先置 True
        再判线程存活，避免「首次调度/线程刚结束」间隙漏扫或重复起线程。
        """
        with self._lock:
            self._scan_pending = True
            self._scan_force = self._scan_force or bool(force)
            alive = self._scan_thread is not None and self._scan_thread.is_alive()
            if alive:
                return
            self._scan_thread = threading.Thread(target=self._scan_loop,
                                                 daemon=True, name="media-scan")
            self._scan_thread.start()

    def _scan_loop(self):
        try:
            while True:
                with self._lock:
                    if not self._scan_pending:
                        self._scan_thread = None
                        return
                    self._scan_pending = False
                    force = self._scan_force
                    self._scan_force = False
                try:
                    self.refresh(force=force)
                except Exception:  # noqa: BLE001 - 扫描异常不得杀死 worker
                    pass
        finally:
            with self._lock:
                if self._scan_thread is threading.current_thread():
                    self._scan_thread = None

    # ---------- 索引 ----------
    def refresh(self, force=True):
        """重扫目录，返回本次变更的文件路径集合（新增/删除/大小或 mtime 变化）。

        **同步**完成扫描+索引合并再返回（自检 CLI / Pipeline.evaluate 依赖）。
        重 IO 在 _collect_index 里**不持锁**执行；仅 _apply_index 短暂持锁合并。
        force=False 时允许「目录 mtime 未变且全部已落盘」快路径跳过整轮扫描。
        Qt 亲和尾部（watcher/emit）经 _dispatch_tail marshaling 回主线程。
        """
        new_index, part_dirs = self._collect_index(force)
        if new_index is None:      # 快路径跳过
            return set()
        changed = self._apply_index(new_index, part_dirs)
        self._dispatch_tail(changed)
        return changed

    def _collect_index(self, force):
        """纯 IO 扫描（**不持 self._lock** 做 walk/stat），返回 (new_index, part_dirs)。

        force=False 且上次目录 mtime 签名未变且无未落盘文件 → 返回 (None, None) 跳过。
        快路径只对上次扫到的目录复 stat mtime（不 walk）：任何新增/删除/改名都会
        改动某个祖先目录 mtime，故签名一致即可安全跳过；仍在下载（未落盘）时不跳过。
        """
        with self._lock:
            dir_mtime = dict(self._dir_mtime)
            has_unsettled = self._has_unsettled
        if not force and dir_mtime and not has_unsettled:
            same = True
            for d, mt in dir_mtime.items():
                try:
                    if os.stat(d).st_mtime_ns != mt:
                        same = False
                        break
                except OSError:
                    same = False
                    break
            if same:
                return None, None
        new_index = {}
        new_dir_mtime = {}
        for p, st in self._iter_files(dir_mtime_out=new_dir_mtime):
            ext = os.path.splitext(p)[1].lower()
            kind = KIND_BY_EXT.get(ext)
            if kind is None:
                continue
            sig = (int(st.st_size), int(st.st_mtime))
            new_index[p] = {"path": p, "name": os.path.splitext(os.path.basename(p))[0],
                            "ext": ext, "kind": kind, "size": sig[0],
                            "mtime": sig[1], "dir": os.path.dirname(p)}
        part_dirs = self._scan_part_dirs()
        with self._lock:
            self._dir_mtime = new_dir_mtime
        return new_index, part_dirs

    def _apply_index(self, new_index, part_dirs):
        """（短暂持锁，无 IO）合并扫描结果：算变更集、维护落盘稳定状态机、交换索引。"""
        changed = set()
        with self._lock:
            for p, entry in new_index.items():
                sig = (entry["size"], entry["mtime"])
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
            # 仍有未宣告落盘的文件 → 轮询快路径不得跳过（要继续观察下载进度）
            self._has_unsettled = any(p not in self._announced for p in new_index)
        return changed

    def _dispatch_tail(self, changed):
        """把 Qt 亲和尾部 marshaling 回主线程：跨线程 emit 自动 queued，主线程则直发。"""
        if not changed:
            return
        if _HAS_QT and self._scan_tail is not None:
            try:
                self._scan_tail.emit(changed)
                return
            except Exception:  # noqa: BLE001
                pass
        self._finish_tail(changed)

    def _on_scan_tail(self, changed):
        """主线程槽：接收后台扫描结果，做 watcher 同步 + 变更通知。"""
        self._finish_tail(changed)

    def _finish_tail(self, changed):
        self._sync_watch_paths()
        self._emit_changed(changed)

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
            videos = self.files(exts=set(engine.MERGE_VIDEO_EXTS))
            m4as = self.files(exts={".m4a"})
            webas = self.files(exts={".weba"})
            srts = self.files(exts={".srt"})
            asss = self.files(exts={".ass"})
        if ffprobe is None:
            try:
                _ff, ffprobe = engine.ensure_ffmpeg()
            except Exception:  # noqa: BLE001
                ffprobe = engine.FFPROBE_PATH
        pairs = engine.smart_pair(videos, m4as, webas, srts, asss, ffprobe)
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
