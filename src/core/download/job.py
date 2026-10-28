# -*- coding: utf-8 -*-
# @version 2.8.0
"""统一下载编排（core/download 内部模块）。

core 负责阶段顺序、重试/换源/EOF/NPE/字幕/打包/清理；
进程执行、逐行日志、细粒度进度、EOF 主动杀进程仍由各面的 Runner 负责。
不依赖 Qt/qfluentwidgets/pipeline。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol, Sequence

from core.download import subtitles
from core.download.deps import ensure_ffmpeg, ensure_ytdlp
from core.download.npe import (
    npe_cookie_file, npe_engine_mode, npe_proxy_url,
)
from core.download.util import (
    format_size, make_cover_1280x720,
    sanitize_folder_name, unique_folder, write_info_txt,
)
from core.download.ytdlp_util import (
    YTDLP_CHUNK_SIZE, fetch_info_json, hls_alt_format,
    output_template, save_info_json, ytdlp_concurrent_fragments,
    ytdlp_cookie_args, ytdlp_dl_args, ytdlp_err_brief,
    ytdlp_error_needs_reextract, ytdlp_error_retryable,
    ytdlp_part_leftovers, ytdlp_prefer_hls,
)
from core.shared.config import get_saved_download_dir
from core.shared.proc import popen_process, sleep_cancellable
from core.shared.proxy import (
    proxy_lock_acquire, proxy_lock_release, ytdlp_proxy_args,
)
from core.shared.textio import decode_bytes_any

RC_CANCELLED = -9
RC_REEXTRACT = -10
RC_PAUSED = -11


def _noop_log(_message: str, _level: str = "dim") -> None:
    pass


def _noop_progress(_pct: float) -> None:
    pass


def _noop_register(_proc) -> None:
    pass


class _CombinedStop:
    """只暴露 is_set()，供 NPE/提取等只接受 cancel Event 的旧接口使用。"""

    def __init__(self, *events):
        self._events = [e for e in events if e is not None]

    def is_set(self) -> bool:
        return any(e.is_set() for e in self._events)


@dataclass(frozen=True)
class RunResult:
    rc: int
    lines: tuple[str, ...] = ()


class YtdlpRunner(Protocol):
    def run(self, cmd: Sequence[str], *, phase: str = "download") -> RunResult:
        ...


class StreamingRunner:
    """CLI 用：逐行输出 + 尾部保留；可选取消。"""

    def __init__(self, on_line: Callable[[str], None], keep: int = 600,
                 cancel: threading.Event | None = None):
        self.on_line = on_line
        self.keep = keep
        self.cancel = cancel

    def run(self, cmd, *, phase="download") -> RunResult:
        lines = deque(maxlen=self.keep)
        try:
            proc = popen_process(list(cmd), stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT, bufsize=1)
        except Exception as e:  # noqa: BLE001
            self.on_line(str(e))
            return RunResult(1, (str(e),))
        try:
            for raw in proc.stdout:
                if self.cancel is not None and self.cancel.is_set():
                    try:
                        proc.kill()
                    except Exception:  # noqa: BLE001
                        pass
                    break
                line = decode_bytes_any(raw).rstrip()
                if line:
                    lines.append(line)
                    self.on_line(line)
        finally:
            try:
                rc = proc.wait()
            except Exception:  # noqa: BLE001
                rc = 1
        return RunResult(rc, tuple(lines))


@dataclass
class JobHooks:
    run: YtdlpRunner
    cancel: threading.Event | None = None
    pause: threading.Event | None = None
    log: Callable[[str, str], None] = _noop_log
    progress: Callable[[float], None] = _noop_progress
    register: Callable[[object | None], None] = _noop_register
    extract: Callable[[str, str], str | None] | None = None
    detect_language: Callable[[str], str] | None = None
    make_cover: Callable[[str, str], bool] | None = None
    write_info: Callable[[str, dict, str], None] | None = None
    normalize_srt: Callable[[str], bool] | None = None
    on_ready: Callable[[str, str, dict], None] | None = None


@dataclass
class DownloadJob:
    url: str
    folder: str = ""
    dest_root: str = ""
    title: str = ""
    meta: dict | None = None
    raw_info: str = ""
    info_json_path: str = ""
    format_id: str = ""
    max_height: int = 0
    quality_label: str = ""
    ytdlp: str = ""
    ffmpeg: str = ""
    proxy_args: tuple[str, ...] | None = None
    with_subs: bool = False
    sub_langs: str = ""
    npe_mode: str = ""
    prefer_hls: bool | None = None
    lock_proxy: bool = False
    require_video: bool = False
    video_exts: tuple[str, ...] = (".mp4", ".mkv", ".webm")
    clean_info_json: bool = False
    max_reextract: int = 2
    retry_attempts: int = 4


@dataclass(frozen=True)
class DownloadJobResult:
    ok: bool
    cancelled: bool = False
    paused: bool = False
    folder: str = ""
    video: str = ""
    title: str = ""
    height: int = 0
    quality_label: str = ""
    subtitles: tuple[str, ...] = ()
    source: str = ""
    error: str = ""
    elapsed: float = 0.0
    resume_info: str = ""


class _JobRunner:
    def __init__(self, job: DownloadJob, hooks: JobHooks):
        self.job = job
        self.hooks = hooks
        self._tmp_info: list[str] = []
        self._last_error = ""
        self._meta: dict = job.meta or {}
        self._info_path = job.info_json_path if job.info_json_path and os.path.isfile(job.info_json_path) else ""
        self._title = job.title
        self._folder = job.folder
        self._ytdlp = job.ytdlp
        self._ffmpeg = job.ffmpeg
        if job.proxy_args is None:
            try:
                self._proxy_args = tuple(ytdlp_proxy_args() or ())
            except Exception:
                self._proxy_args = ()
        else:
            self._proxy_args = tuple(job.proxy_args or ())
        self._started = 0.0
        self._source = ""
        self._fid = str(job.format_id or "")
        self._download_done = False

    def _cancelled(self) -> bool:
        return bool(self.hooks.cancel is not None and self.hooks.cancel.is_set())

    def _paused(self) -> bool:
        return bool(self.hooks.pause is not None and self.hooks.pause.is_set())

    def _stop_kind(self) -> str:
        if self._cancelled():
            return "cancel"
        if not self._download_done and self._paused():
            return "pause"
        return ""

    def _stop_code(self) -> int:
        kind = self._stop_kind()
        return RC_CANCELLED if kind == "cancel" else (RC_PAUSED if kind == "pause" else 0)

    def _sleep_stop(self, seconds: float) -> int:
        end = time.time() + max(0.0, float(seconds))
        while time.time() < end:
            code = self._stop_code()
            if code:
                return code
            time.sleep(min(0.2, max(0.0, end - time.time())))
        return self._stop_code()

    def _stop_event(self):
        return _CombinedStop(self.hooks.cancel, self.hooks.pause)

    def _log(self, message: str, level: str = "dim") -> None:
        try:
            self.hooks.log(message, level)
        except Exception:
            pass

    def _progress(self, pct: float) -> None:
        try:
            self.hooks.progress(float(pct))
        except Exception:
            pass

    def _run(self, cmd: Sequence[str], phase="download"):
        code = self._stop_code()
        if code:
            return code, ("已取消",) if code == RC_CANCELLED else ("已暂停",)
        try:
            result = self.hooks.run.run(list(cmd), phase=phase)
        except Exception as e:  # noqa: BLE001
            self._log("[错误] 无法启动下载器: %s" % e, "err")
            return 1, (str(e),)
        return int(result.rc), tuple(result.lines)

    def _run_with_retry(self, cmd: Sequence[str], phase="download"):
        wait = 6
        rc, lines = 1, ()
        for i in range(max(1, int(self.job.retry_attempts))):
            code = self._stop_code()
            if code:
                return code, ("已暂停",) if code == RC_PAUSED else ("已取消",)
            rc, lines = self._run(cmd, phase)
            if rc == 0:
                return 0, lines
            code = self._stop_code()
            if code:
                return code, ("已暂停",) if code == RC_PAUSED else ("已取消",)
            joined = "\n".join(lines[-600:])
            if ytdlp_error_needs_reextract(joined):
                self._log("[下载] 下载链接已失效，准备重新提取", "err")
                return RC_REEXTRACT, lines
            if not ytdlp_error_retryable(joined):
                return rc, lines
            if i < max(1, int(self.job.retry_attempts)) - 1:
                self._log("[重试] 站点风控或直链失效（%s），%ss 后重试 (%d/%d) ..."
                          % (ytdlp_err_brief(joined), wait, i + 2,
                             max(1, int(self.job.retry_attempts))), "dim")
                code = self._sleep_stop(wait)
                if code:
                    return code, ("已暂停",) if code == RC_PAUSED else ("已取消",)
                wait *= 2
        return rc, lines

    def _extract(self) -> str:
        if self._stop_kind():
            return ""
        if self.hooks.extract is not None:
            try:
                raw = self.hooks.extract(self._ytdlp, self.job.url)
            except Exception as e:  # noqa: BLE001
                self._log("[提取] 失败：%s" % e, "err")
                return ""
        else:
            raw = fetch_info_json(
                self._ytdlp, self.job.url,
                log=lambda m: self._log(m),
                cancel=self._stop_event(),
                register=self.hooks.register,
            )
        if not raw:
            return ""
        try:
            self._meta = json.loads(raw) or {}
        except ValueError:
            self._meta = {}
        self._title = str(self._meta.get("title") or self._title or "video").strip() or "video"
        return raw

    def _save_temp_info(self, raw: str) -> str:
        if not raw:
            return ""
        path = save_info_json(raw)
        self._tmp_info.append(path)
        return path

    def _resolve_tools(self) -> bool:
        if not self._ytdlp:
            self._ytdlp = ensure_ytdlp()
        if self._stop_kind():
            return False
        if not self._ffmpeg:
            self._ffmpeg, _ = ensure_ffmpeg()
        return not bool(self._stop_kind())

    def _resolve_folder(self) -> bool:
        if self._folder:
            self._folder = os.path.abspath(self._folder)
        elif self.job.dest_root:
            root = os.path.abspath(self.job.dest_root)
            os.makedirs(root, exist_ok=True)
            self._folder = unique_folder(root, sanitize_folder_name(self._title, "video"))
        else:
            root = get_saved_download_dir()
            os.makedirs(root, exist_ok=True)
            self._folder = unique_folder(root, sanitize_folder_name(self._title, "video"))
        try:
            os.makedirs(self._folder, exist_ok=True)
        except OSError as e:
            self._last_error = "创建下载文件夹失败：%s" % e
            self._log(self._last_error, "err")
            return False
        if self.hooks.on_ready is not None:
            try:
                self.hooks.on_ready(self._folder, self._title, self._meta)
            except Exception:
                pass
        return True

    def _choose_format(self) -> tuple[str, int]:
        fid = str(self.job.format_id or "").strip()
        height = 0
        formats = (self._meta or {}).get("formats") or []
        if fid:
            cur = next((f for f in formats if str(f.get("format_id")) == fid), None)
            height = int((cur or {}).get("height") or 0)
            return fid, height
        candidates = [f for f in formats
                      if (f.get("vcodec") or "none") != "none"]
        if self.job.max_height > 0:
            candidates = [f for f in candidates
                          if int(f.get("height") or 0) <= int(self.job.max_height)]
        if candidates:
            candidates.sort(key=lambda f: (
                int(f.get("height") or 0),
                float(f.get("fps") or 0),
                float(f.get("tbr") or 0),
                float(f.get("filesize") or f.get("filesize_approx") or 0),
            ), reverse=True)
            pick = candidates[0]
            fid = str(pick.get("format_id") or "")
            height = int(pick.get("height") or 0)
        return fid, height

    def _common_opts(self) -> list[str]:
        ffmpeg_dir = os.path.dirname(self._ffmpeg) if self._ffmpeg else ""
        opts = [
            "--merge-output-format", "mp4",
            "--newline", "--no-playlist",
            "--http-chunk-size", YTDLP_CHUNK_SIZE,
            *ytdlp_dl_args(),
            "--write-thumbnail", "--convert-thumbnails", "jpg",
        ]
        if ffmpeg_dir:
            opts += ["--ffmpeg-location", ffmpeg_dir]
        opts += list(self._proxy_args)
        opts += list(ytdlp_cookie_args(log=lambda m: self._log(m)) or ())
        opts += ["-o", output_template(self._folder)]
        return opts

    def _cmd(self, selector: str, opts: list[str], info_path: str = "") -> list[str]:
        cmd = [self._ytdlp]
        if info_path and os.path.isfile(info_path):
            cmd += ["--load-info-json", info_path]
        cmd += ["-f", selector, *opts]
        if not (info_path and os.path.isfile(info_path)):
            cmd.append(self.job.url)
        return cmd

    def _fallback(self, selector: str, opts: list[str]):
        code = self._stop_code()
        if code:
            return code, ("已暂停",) if code == RC_PAUSED else ("已取消",)
        raw = self._extract()
        code = self._stop_code()
        if code:
            return code, ("已暂停",) if code == RC_PAUSED else ("已取消",)
        if raw:
            tmp = self._save_temp_info(raw)
            rc, lines = self._run(self._cmd(selector, opts, tmp), "download")
            if rc == 0:
                return 0, lines
            code = self._stop_code()
            if code:
                return code, ("已暂停",) if code == RC_PAUSED else ("已取消",)
        return self._run_with_retry(self._cmd(selector, opts, ""), "download")

    def _is_reextract(self, rc: int, lines: Sequence[str]) -> bool:
        if rc == RC_REEXTRACT:
            return True
        return ytdlp_error_needs_reextract("\n".join(lines[-600:]))

    def _download(self, selector: str, alt: str, prefer: bool, opts: list[str]) -> int:
        code = self._stop_code()
        if code:
            return code
        self._progress(3.0)
        info_path = self._info_path
        rc, lines = self._run(self._cmd(selector, opts, info_path), "download")
        self._source = "info" if info_path else "url"
        if rc == 0:
            # 已经拿到成品：完成优先，忽略同时到达的 pause。
            return 0
        code = self._stop_code()
        if code:
            return code
        self._progress(0.0)
        if self._is_reextract(rc, lines):
            reextract = 0
            while self._is_reextract(rc, lines):
                if self._stop_code():
                    return self._stop_code()
                reextract += 1
                if reextract > max(0, int(self.job.max_reextract)):
                    self._log("[下载] 已连续重新提取 %d 次仍未成功，改用其它下载源"
                              % max(0, int(self.job.max_reextract)), "err")
                    rc = 1
                    break
                self._log("[下载] 下载链接已失效，重新提取新链接（第 %d/%d 次）"
                          % (reextract, max(0, int(self.job.max_reextract))), "err")
                rc, lines = self._fallback(selector, opts)
                if rc in (RC_CANCELLED, RC_PAUSED):
                    return rc
                if rc == 0:
                    break
        else:
            rc, lines = self._fallback(selector, opts)
            if rc in (RC_CANCELLED, RC_PAUSED):
                return rc
        self._source = "fallback"
        if rc == 0:
            return 0
        code = self._stop_code()
        if code:
            return code
        other = ""
        if alt:
            other = self._fid if prefer else alt
        if not other and alt:
            other = alt
        if other:
            selectors = [("%s+ba/b" % other)]
            if alt and other == alt:
                selectors.append("%s+233/234/b" % alt)
            for selected in selectors:
                code = self._stop_code()
                if code:
                    return code
                self._progress(0.0)
                self._log("[下载] 改用备用源 %s 重试 ..." % selected)
                rc, lines = self._fallback(selected, opts)
                if rc in (RC_CANCELLED, RC_PAUSED):
                    return rc
                if rc == 0:
                    self._source = "alt"
                    return 0
        code = self._stop_code()
        if code:
            return code
        mode = (self.job.npe_mode or npe_engine_mode() or "auto").strip().lower()
        if mode != "off":
            rc = self._npe_fallback()
            if rc == 0:
                self._source = "npe"
            if rc in (RC_CANCELLED, RC_PAUSED):
                return rc
        return rc

    def _npe_fallback(self) -> int:
        code = self._stop_code()
        if code:
            return code
        try:
            import npe_backend
        except Exception as e:  # noqa: BLE001
            self._log("[NPE] 模块导入失败：%s" % e, "err")
            return 1
        ok, why = npe_backend.is_available()
        if not ok:
            self._log("[NPE] 不可用：%s" % why, "err")
            return 1
        self._log("[NPE] yt-dlp 各源均失败，改用 NewPipe Extractor 兜底解析 ...")
        target = 0
        m = re.search(r"(\d{3,4})\s*p", str(self.job.quality_label or ""))
        if m:
            target = int(m.group(1))
        proxy = npe_proxy_url()
        cookie = npe_cookie_file(log=lambda m: self._log(m))
        stop = self._stop_event()
        info = npe_backend.probe(
            self.job.url, proxy=proxy, cookie_file=cookie,
            cancel=stop, register=self.hooks.register,
        )
        code = self._stop_code()
        if code:
            return code
        if info.get("errorType") == "cancelled":
            return RC_PAUSED if self._paused() else RC_CANCELLED
        if not info.get("ok"):
            self._log("[NPE] 解析失败：%s" % npe_backend.error_hint(info), "err")
            return 1
        ok2, out_path, err = npe_backend.download(
            info, self._folder, self._ffmpeg, proxy=proxy,
            referer="https://www.youtube.com/", max_height=target,
            log=lambda m, lv="dim": self._log(m, lv),
            progress=self._progress,
            cancel=stop,
            sanitize=lambda t: sanitize_folder_name(t, "video"),
            title_fallback=str((self._meta or {}).get("title") or "video"),
        )
        code = self._stop_code()
        if code:
            return code
        if not ok2:
            if err == "已取消":
                return RC_PAUSED if self._paused() else RC_CANCELLED
            self._log("[NPE] 兜底下载失败：%s" % err, "err")
            return 1
        self._log("[NPE] 兜底下载成功：%s（%s）"
                  % (os.path.basename(out_path), format_size(os.path.getsize(out_path))), "ok")
        return 0

    def _find_video(self) -> str:
        best = ""
        best_size = -1
        try:
            names = os.listdir(self._folder)
        except OSError:
            return ""
        for name in names:
            if not name.lower().endswith(tuple(self.job.video_exts)):
                continue
            path = os.path.join(self._folder, name)
            try:
                size = os.path.getsize(path)
            except OSError:
                continue
            if size > best_size:
                best, best_size = path, size
        return best

    def _pack(self) -> None:
        data = self._meta if isinstance(self._meta, dict) else {}
        try:
            if self.hooks.write_info is not None:
                self.hooks.write_info(self._folder, data, self.job.quality_label)
            else:
                write_info_txt(self._folder, data, self.job.quality_label)
            self._log("[打包] 视频信息.txt 已生成")
        except Exception as e:  # noqa: BLE001
            self._log("[打包] 视频信息.txt 写入失败: %s" % e, "err")
        try:
            if self.hooks.make_cover is not None:
                made = self.hooks.make_cover(self._ffmpeg, self._folder)
            else:
                made = make_cover_1280x720(
                    self._ffmpeg, self._folder,
                    cancel=self.hooks.cancel, register=self.hooks.register)
            if made:
                self._log("[打包] 封面.jpg（1280x720）已生成")
            elif self._cancelled():
                self._log("[打包] 已取消，跳过封面", "err")
            else:
                self._log("[打包] 该视频无可用封面，已跳过封面步骤")
        except Exception as e:  # noqa: BLE001
            self._log("[打包] 封面生成失败: %s" % e, "err")

    def _cleanup_cancelled(self) -> None:
        removed = 0
        try:
            names = os.listdir(self._folder)
        except OSError:
            names = []
        for name in names:
            low = name.lower()
            if low.endswith((".part", ".ytdl", ".vtdl.json", ".vtdl.single",
                             ".vtdl.assembling", ".vtdl.resume.json",
                             ".npe_v.mp4", ".npe_a.m4a",
                             ".npe_v.m4v", ".npe_a.mp4", ".npe_v.webm",
                             ".npe_a.webm", ".npe_v.mp2t", ".npe_a.mp2t")):
                try:
                    os.remove(os.path.join(self._folder, name))
                    removed += 1
                except OSError:
                    pass
        if removed:
            self._log("[清理] 已删除 %d 个未完成的临时文件" % removed)
        try:
            if not os.listdir(self._folder):
                os.rmdir(self._folder)
        except OSError:
            pass

    def _cleanup_success(self) -> None:
        for path in ytdlp_part_leftovers(self._folder):
            try:
                os.remove(path)
            except OSError:
                pass
        try:
            for name in os.listdir(self._folder):
                if name.lower().endswith((".vtdl.json", ".vtdl.single", ".vtdl.assembling",
                                          ".vtdl.resume.json")):
                    try:
                        os.remove(os.path.join(self._folder, name))
                    except OSError:
                        pass
        except OSError:
            pass

    def _persist_resume(self) -> str:
        if not self._folder:
            return ""
        data = ""
        if self._meta:
            try:
                data = json.dumps(self._meta, ensure_ascii=False)
            except Exception:
                data = ""
        if not data and self._info_path and os.path.isfile(self._info_path):
            try:
                data = Path(self._info_path).read_text(encoding="utf-8")
            except OSError:
                data = ""
        if not data and self.job.raw_info:
            data = self.job.raw_info
        if not data:
            return ""
        path = os.path.join(self._folder, ".vtdl.resume.json")
        tmp = path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(data)
            os.replace(tmp, path)
            return path
        except OSError:
            try:
                os.remove(tmp)
            except OSError:
                pass
            return ""

    def _result(self, ok: bool, **kwargs) -> DownloadJobResult:
        return DownloadJobResult(
            ok=ok, folder=self._folder, title=self._title,
            quality_label=self.job.quality_label, source=self._source,
            elapsed=time.perf_counter() - self._started, **kwargs)

    def run(self) -> DownloadJobResult:
        self._started = time.perf_counter()
        locked = ""
        try:
            if not self._resolve_tools():
                kind = self._stop_kind()
                return self._result(
                    False, cancelled=kind == "cancel", paused=kind == "pause",
                    error="已取消" if kind == "cancel" else (
                        "已暂停" if kind == "pause" else "下载器不可用"))
            if self.job.lock_proxy:
                try:
                    locked = proxy_lock_acquire()
                    if locked:
                        self._log("[代理] 已锁定出口节点 %s" % locked)
                except Exception as e:  # noqa: BLE001
                    self._log("[代理] 锁定失败：%s" % e, "dim")
            raw = self.job.raw_info
            if not self._meta:
                if raw:
                    try:
                        self._meta = json.loads(raw) or {}
                    except ValueError:
                        self._meta = {}
                elif self._info_path:
                    try:
                        raw = Path(self._info_path).read_text(encoding="utf-8")
                        self._meta = json.loads(raw) or {}
                    except Exception:
                        self._meta = {}
                else:
                    raw = self._extract()
            if not self._title:
                self._title = str((self._meta or {}).get("title") or "video").strip() or "video"
            kind = self._stop_kind()
            if kind:
                return self._result(False, cancelled=kind == "cancel",
                                    paused=kind == "pause",
                                    error="已取消" if kind == "cancel" else "已暂停")
            if not self._resolve_folder():
                return self._result(False, error=self._last_error or "创建下载目录失败")
            if raw and not self._info_path:
                self._info_path = self._save_temp_info(raw)
            fid, height = self._choose_format()
            self._fid = fid
            if not self.job.quality_label and height:
                self.job.quality_label = "%dp" % height
            alt = hls_alt_format(self._meta, fid) if fid else None
            prefer = self.job.prefer_hls if self.job.prefer_hls is not None else ytdlp_prefer_hls()
            use_fid = alt if (prefer and alt) else fid
            if use_fid:
                selector = "%s+ba/b" % use_fid
            elif self.job.max_height:
                selector = "bv*[height<=%d]+ba/b" % self.job.max_height
            else:
                selector = "bv*+ba/b"
            if prefer and alt:
                self._log("[策略] 直链单条服务能力有限，改用 HLS 分片源 %s（分片并发 %s）"
                          % (alt, ytdlp_concurrent_fragments()))
            opts = self._common_opts()
            rc = self._download(selector, alt or "", bool(prefer), opts)
            if self._cancelled():
                self._cleanup_cancelled()
                return self._result(False, cancelled=True, error="已取消")
            if rc == RC_PAUSED or (self._paused() and rc != 0):
                resume = self._persist_resume()
                return self._result(False, paused=True, resume_info=resume,
                                    error="已暂停，分片已保留")
            if rc != 0:
                if rc == RC_CANCELLED:
                    self._cleanup_cancelled()
                    return self._result(False, cancelled=True, error="已取消")
                return self._result(False, error=self._last_error or "视频下载失败")
            self._download_done = True
            self._cleanup_success()
            self._pack()
            subs = ()
            if self.job.with_subs and not self._cancelled():
                subs = tuple(subtitles.fetch_subtitles(
                    ytdlp=self._ytdlp, url=self.job.url, folder=self._folder,
                    info_json_path=self._info_path, title=self._title,
                    sub_langs=self.job.sub_langs, proxy_args=self._proxy_args,
                    run_once=lambda cmd: self._run(cmd, "subtitle"),
                    run_retry=lambda cmd: self._run_with_retry(cmd, "subtitle"),
                    detect_language=self.hooks.detect_language,
                    normalize=self.hooks.normalize_srt,
                    log=self.hooks.log, cancel=self.hooks.cancel,
                ))
            if self._cancelled():
                self._cleanup_cancelled()
                return self._result(False, cancelled=True, subtitle=subs,
                                    error="已取消")
            video = self._find_video()
            if self.job.require_video and not video:
                return self._result(False, subtitles=subs,
                                    error="下载完成但未找到视频文件")
            self._progress(100.0)
            return self._result(True, video=video, height=height,
                                subtitles=subs)
        finally:
            if locked:
                try:
                    proxy_lock_release()
                except Exception:
                    pass
            for path in self._tmp_info:
                try:
                    os.remove(path)
                except OSError:
                    pass
            if self.job.clean_info_json and self.job.info_json_path:
                try:
                    os.remove(self.job.info_json_path)
                except OSError:
                    pass


def run_download_job(job: DownloadJob, hooks: JobHooks) -> DownloadJobResult:
    try:
        return _JobRunner(job, hooks).run()
    except Exception as e:  # noqa: BLE001
        try:
            hooks.log("[错误] 下载编排异常：%s" % e, "err")
        except Exception:
            pass
        return DownloadJobResult(
            ok=False, folder=job.folder or job.dest_root,
            title=job.title, error=str(e) or "下载编排异常",
        )


def download_orchestrator(default: str = "legacy") -> str:
    value = (os.environ.get("VT_DL_ORCH") or "").strip().lower()
    return value if value in ("legacy", "job") else default


__all__ = [
    "RunResult", "YtdlpRunner", "StreamingRunner",
    "JobHooks", "DownloadJob", "DownloadJobResult",
    "run_download_job", "download_orchestrator",
]
