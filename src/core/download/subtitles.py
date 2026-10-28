# -*- coding: utf-8 -*-
"""字幕拉取/补拉/归一化（core/download 内部模块）。"""
from __future__ import annotations

import os
from collections.abc import Callable

from core.download.urls import ytdlp_sub_langs
from core.download.ytdlp_util import output_template, ytdlp_cookie_args

DEFAULT_SUB_LANGS = "en,zh,ja,zh-Hans,zh-Hant,ko,es,fr,de"


def srt_snapshot(folder: str, before=None):
    """目录里 .srt 的 {路径: (mtime_ns, 大小)} 快照；before 非空时返回新增/改写项。"""
    now = {}
    try:
        names = os.listdir(folder)
    except OSError:
        return {} if before is None else []
    for name in names:
        if not name.lower().endswith(".srt"):
            continue
        path = os.path.join(folder, name)
        try:
            st = os.stat(path)
        except OSError:
            continue
        now[path] = (st.st_mtime_ns, st.st_size)
    if before is None:
        return now
    return sorted(p for p, sig in now.items() if before.get(p) != sig)


def _log(log, message: str, level: str = "dim") -> None:
    if log:
        try:
            log(message, level)
        except Exception:
            pass


def fetch_subtitles(
    *,
    ytdlp: str,
    url: str,
    folder: str,
    info_json_path: str = "",
    title: str = "",
    sub_langs: str = "",
    proxy_args=(),
    run_once: Callable,
    run_retry: Callable,
    detect_language: Callable[[str], str] | None = None,
    normalize: Callable[[str], bool] | None = None,
    log=None,
    cancel=None,
) -> list[str]:
    """下载字幕；失败/无字幕不抛异常，返回本轮新增的 .srt 路径。"""
    if cancel is not None and cancel.is_set():
        return []
    langs = (sub_langs or "").strip() or DEFAULT_SUB_LANGS
    if title and detect_language is not None:
        try:
            code = detect_language(title) or ""
        except Exception:
            code = ""
        if code:
            guessed = ytdlp_sub_langs(code)
            if guessed:
                langs = guessed
                _log(log, "[字幕] AI 识别标题语言为 %s，按标题语言拉取字幕（%s）"
                     % (code, guessed))
        else:
            _log(log, "[字幕] AI 语言识别不可用，按多语言列表拉取字幕")

    proxy_args = tuple(proxy_args or ())
    cookie_args = tuple(ytdlp_cookie_args(log=lambda m: _log(log, m)) or ())
    base_opts = ["--skip-download", "--newline", "--no-playlist",
                 "--socket-timeout", "15", "--retries", "3",
                 "--write-subs", "--write-auto-subs", "--sub-langs", langs,
                 "--sub-format", "srt/best", "--convert-subs", "srt",
                 *proxy_args, *cookie_args, "-o", output_template(folder)]

    before = srt_snapshot(folder)

    def one(language_list: str) -> None:
        opts = list(base_opts)
        try:
            opts[opts.index("--sub-langs") + 1] = language_list
        except (ValueError, IndexError):
            opts += ["--sub-langs", language_list]
        if cancel is not None and cancel.is_set():
            return
        rc = 1
        if info_json_path and os.path.isfile(info_json_path):
            rc, _lines = run_once([ytdlp, "--load-info-json", info_json_path, *opts])
            if rc == 0:
                return
        if cancel is not None and cancel.is_set():
            return
        run_retry([ytdlp, *opts, url])

    one(langs)
    fresh = srt_snapshot(folder, before)
    if not fresh and langs != DEFAULT_SUB_LANGS and (cancel is None or not cancel.is_set()):
        _log(log, "[字幕] 首轮没取到字幕，改用多语言列表补拉一次")
        one(DEFAULT_SUB_LANGS)
        fresh = srt_snapshot(folder, before)

    fixed = 0
    for path in fresh:
        if normalize is None:
            continue
        try:
            if normalize(path):
                fixed += 1
        except Exception as e:  # noqa: BLE001
            _log(log, "[字幕] 整理 %s 失败：%s" % (os.path.basename(path), e), "err")
    if fresh:
        extra = "，其中 %d 份做了去重叠整理" % fixed if fixed else ""
        _log(log, "[字幕] 已下载 %d 份字幕（.srt）%s，已存入该视频文件夹"
             % (len(fresh), extra), "ok")
    else:
        _log(log, "[字幕] 该视频没有可用字幕，或字幕拉取失败——不影响视频/封面/信息文件，任务仍算完成")
    return fresh


__all__ = ["DEFAULT_SUB_LANGS", "srt_snapshot", "fetch_subtitles"]
