# -*- coding: utf-8 -*-
# @version 3.3.1
"""开发版校准观测总线（只读遥测，JSONL 事件文件）。

第三方 AgentWork 经 ``logs/trace/<session>/`` 下的 JSONL 事件文件 + 统一 CLI
``trace`` 子命令，实时读取校准过程的四类事件：

- ``workflow``  工作流阶段（session_start / stage / session_end）
- ``ai``        AI 思考链（prompt / response / 逐条裁决 / 影子审核）
- ``direction`` 校准方向（模式归一 / 术语表装配 / learned 注入 / hits 统计）
- ``data``      数据访问（srt 读写 / 侧车加载 / 配置读取，密钥脱敏）

门控（仅开发版默认开启）：
- 源码态（非 ``sys.frozen``）且非自检进程 → 默认开；
- ``VT_TRACE=1`` 强开 / ``VT_TRACE=0`` 强关；安装版（frozen）默认关。

安全纪律：
- ``emit`` 永不抛异常（校准主路零风险）、永不写 stdout（保 --json 单信封契约）；
- api_key/token/secret/password 类字段统一脱敏；单字符串 64KB 截断带标记；
- 会话目录保留最近 30 个；每进程写自己的 jsonl（避免跨进程 append 竞争），
  读取端按 (ts, pid, seq) 归并。

事件 schema（每行一个 JSON 对象）::

    {"ts": "...", "session": "...", "seq": 1, "pid": 1234,
     "kind": "workflow|ai|direction|data", "event": "...", "payload": {...}}

引擎接缝：``calib_core.engine.TRACE_HOOK``（默认 None＝零行为改动）由
:func:`start_session` 安装、:func:`end_session` 卸载；外部 monolith 工作流
不设钩子，天然关闭。VT_CALIB_SUBPROCESS=1 回退通路只有父进程会话级事件
（子进程 monolith 不装钩子），属已知边界。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
import threading
import time
from datetime import datetime

__all__ = ["enabled", "start_session", "end_session", "emit", "current_session",
           "trace_root", "latest_session", "list_sessions", "read_events",
           "session_summary"]

_MAX_STR = 64 * 1024          # 单字符串截断上限（prompt 类大字段）
_KEEP_SESSIONS = 30           # 会话目录保留数
_SECRET_RX = re.compile(r"(api[_-]?key|token|secret|password|authorization)", re.I)

_lock = threading.Lock()
_session: str | None = None   # 当前会话 id
_seq = 0                      # 本进程事件序号
_file: str | None = None      # 本进程事件文件


# ---------------------------------------------------------------- 门控与路径

def enabled() -> bool:
    """开发版门控：VT_TRACE 显式优先；否则源码态且非自检进程才开。"""
    v = (os.environ.get("VT_TRACE") or "").strip()
    if v == "0":
        return False
    if v == "1":
        return True
    if getattr(sys, "frozen", False):
        return False
    try:
        from core.shared.log import _is_selftest_run  # noqa: PLC0415
        return not _is_selftest_run()
    except Exception:
        return True


def trace_root() -> str:
    """事件根目录 ``<LOGS_DIR>/trace``（路径锚点走 core.shared.paths）。"""
    from core.shared.paths import LOGS_DIR  # noqa: PLC0415
    return os.path.join(LOGS_DIR, "trace")


def current_session() -> str | None:
    return _session


# ---------------------------------------------------------------- 写入侧

def _ts() -> str:
    return datetime.now().isoformat(timespec="milliseconds")


def _clean(obj, depth=0):
    """脱敏 + 截断：密钥类键值替换为掩码，超长字符串截断带标记。"""
    if depth > 6:
        return str(obj)[:200]
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if isinstance(k, str) and _SECRET_RX.search(k):
                out[k] = "***masked***"
            else:
                out[k] = _clean(v, depth + 1)
        return out
    if isinstance(obj, (list, tuple)):
        return [_clean(v, depth + 1) for v in obj[:2000]]
    if isinstance(obj, str) and len(obj) > _MAX_STR:
        return obj[:_MAX_STR] + "…[clipped %d chars]" % (len(obj) - _MAX_STR)
    return obj


def emit(kind: str, event: str, **payload) -> None:
    """追加一条事件。永不抛异常、永不写 stdout；无会话时静默 no-op。"""
    global _seq
    if not _session or not _file:
        return
    try:
        with _lock:
            _seq += 1
            rec = {"ts": _ts(), "session": _session, "seq": _seq,
                   "pid": os.getpid(), "kind": kind, "event": event,
                   "payload": _clean(payload)}
            line = json.dumps(rec, ensure_ascii=False, default=str)
            with open(_file, "a", encoding="utf-8", newline="\n") as f:
                f.write(line + "\n")
    except Exception:
        pass


def _hook(kind, event, payload) -> None:
    """calib_core.engine.TRACE_HOOK 适配器（引擎侧零 import 依赖）。"""
    emit(kind, event, **(payload or {}))


def _install_engine_hook() -> None:
    try:
        from calib_core import engine as _eng  # noqa: PLC0415
        if getattr(_eng, "TRACE_HOOK", None) is None:
            _eng.TRACE_HOOK = _hook
    except Exception:
        pass


def _uninstall_engine_hook() -> None:
    try:
        from calib_core import engine as _eng  # noqa: PLC0415
        if getattr(_eng, "TRACE_HOOK", None) is _hook:
            _eng.TRACE_HOOK = None
    except Exception:
        pass


def _prune(root: str) -> None:
    """会话目录保留最近 _KEEP_SESSIONS 个（名字以时间戳开头，降序即新旧）。"""
    try:
        dirs = sorted((d for d in os.listdir(root)
                       if os.path.isdir(os.path.join(root, d))), reverse=True)
        for old in dirs[_KEEP_SESSIONS:]:
            shutil.rmtree(os.path.join(root, old), ignore_errors=True)
    except Exception:
        pass


def start_session(command: str = "calibrate", **meta) -> str | None:
    """开一个观测会话（幂等：已有会话则复用）。返回会话 id，未启用返回 None。

    子进程经 ``VT_TRACE_SESSION`` 环境变量继承会话 id，写 ``p<pid>.jsonl``；
    会话所有者写 ``main.jsonl``。
    """
    global _session, _seq, _file
    if not enabled():
        return None
    try:
        with _lock:
            if _session:
                return _session
            sid = (os.environ.get("VT_TRACE_SESSION") or "").strip()
            owner = not sid
            if not sid:
                sid = "%s-%d-%s" % (time.strftime("%Y%m%d-%H%M%S"),
                                    os.getpid(), os.urandom(2).hex())
            sdir = os.path.join(trace_root(), sid)
            os.makedirs(sdir, exist_ok=True)
            _session = sid
            _seq = 0
            _file = os.path.join(sdir, "main.jsonl" if owner
                                 else "p%d.jsonl" % os.getpid())
            os.environ["VT_TRACE_SESSION"] = sid
            _prune(trace_root())
            _install_engine_hook()
        emit("workflow", "session_start" if owner else "process_attach",
             command=command, pid=os.getpid(), owner=owner, **meta)
        return sid
    except Exception:
        return None


def end_session(**stats) -> None:
    """写 session_end 并卸载引擎钩子。无会话时 no-op。"""
    global _session, _file
    if not _session:
        return
    try:
        emit("workflow", "session_end", **stats)
    finally:
        with _lock:
            _session = None
            _file = None
        os.environ.pop("VT_TRACE_SESSION", None)
        _uninstall_engine_hook()


# ---------------------------------------------------------------- 读取侧

def _iter_session_files(sdir: str):
    try:
        for fn in sorted(os.listdir(sdir)):
            if fn.endswith(".jsonl"):
                yield os.path.join(sdir, fn)
    except OSError:
        return


def _load_events(sdir: str) -> list[dict]:
    """读一个会话的全部事件，按 (ts, pid, seq) 归并排序。"""
    events = []
    for path in _iter_session_files(sdir):
        try:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        events.append(json.loads(line))
                    except ValueError:
                        continue
        except OSError:
            continue
    events.sort(key=lambda e: (e.get("ts", ""), e.get("pid", 0), e.get("seq", 0)))
    return events


def latest_session() -> str | None:
    try:
        dirs = sorted((d for d in os.listdir(trace_root())
                       if os.path.isdir(os.path.join(trace_root(), d))),
                      reverse=True)
        return dirs[0] if dirs else None
    except OSError:
        return None


def list_sessions(limit: int = 50) -> list[dict]:
    """会话清单（新→旧）：事件数 / 命令 / 输入 / 模式 / 起止时间。"""
    root = trace_root()
    out = []
    try:
        names = sorted(os.listdir(root), reverse=True)
    except OSError:
        return out
    for sid in names[:limit]:
        sdir = os.path.join(root, sid)
        if not os.path.isdir(sdir):
            continue
        info = {"session": sid, "events": 0, "command": None, "input": None,
                "mode": None, "started": None, "ended": None, "ok": None}
        for path in _iter_session_files(sdir):
            try:
                with open(path, encoding="utf-8") as f:
                    for line in f:
                        info["events"] += 1
                        if '"session_start"' not in line and '"session_end"' not in line:
                            continue
                        try:
                            rec = json.loads(line)
                        except ValueError:
                            continue
                        ev, pl = rec.get("event"), rec.get("payload") or {}
                        if ev == "session_start":
                            info["command"] = pl.get("command")
                            info["input"] = pl.get("input")
                            info["mode"] = pl.get("mode")
                            info["started"] = rec.get("ts")
                        elif ev == "session_end":
                            info["ended"] = rec.get("ts")
                            info["ok"] = pl.get("ok")
            except OSError:
                continue
        out.append(info)
    return out


def read_events(session: str | None = None, kind: str | None = None,
                limit: int | None = None, after: dict | None = None) -> list[dict]:
    """读事件（默认最新会话）。kind 过滤；limit 取末尾 N 条；after 增量游标。

    after = {"ts":…, "pid":…, "seq":…}：只返回严格大于该游标的事件（--follow 用）。
    """
    sid = session or latest_session()
    if not sid:
        return []
    events = _load_events(os.path.join(trace_root(), sid))
    if kind:
        events = [e for e in events if e.get("kind") == kind]
    if after:
        key = (after.get("ts", ""), after.get("pid", 0), after.get("seq", 0))
        events = [e for e in events
                  if (e.get("ts", ""), e.get("pid", 0), e.get("seq", 0)) > key]
    if limit is not None and limit > 0:
        events = events[-limit:]
    return events


def session_summary(session: str | None = None) -> dict:
    """单会话摘要：工作流时间线 / AI 轮次统计 / 方向决策 / 数据访问 / 终局。"""
    sid = session or latest_session()
    if not sid:
        return {"error": "无观测会话（开发版跑一次 calibrate 后才有事件）"}
    events = _load_events(os.path.join(trace_root(), sid))
    if not events:
        return {"error": "会话不存在或无事件：%s" % sid}
    timeline, ai, direction, data = [], {}, [], []
    start = end = None
    for e in events:
        k, ev, pl = e.get("kind"), e.get("event"), e.get("payload") or {}
        if k == "workflow":
            timeline.append({"ts": e.get("ts"), "event": ev, **pl})
            if ev == "session_start":
                start = pl
            elif ev == "session_end":
                end = pl
        elif k == "ai":
            ai[ev] = ai.get(ev, 0) + 1
        elif k == "direction":
            direction.append({"ts": e.get("ts"), "event": ev, **pl})
        elif k == "data":
            data.append({"ts": e.get("ts"), "event": ev, **pl})
    return {"session": sid, "events": len(events), "start": start, "end": end,
            "workflow": timeline, "ai_counts": ai,
            "direction": direction, "data_access": data}