# -*- coding: utf-8 -*-
# @version 2.5.1
"""日志卫生（轮转/去重/级别标记/自检隔离）（v2.3.1 拆分工程 · 自 video_toolbox.py 原样搬入）。

本模块是 src/core/shared/ 的组成部分；域间依赖规则见 core/__init__.py。
"""
import os
import sys
import threading
from datetime import datetime

from core.shared.paths import LOGS_DIR

# ---------- 日志卫生（v1.16.2）：轮转 / 去重 / 级别标记 / 自检隔离 ----------
#: 单个日志文件超过该字节数即轮转：旧内容挪到 ``<name>.1``（只留一代，
#: 总量封顶 2×）。日志是用来定位**最近**问题的，无限累积只会把新信息埋掉
#: ——vc_fallback.log 曾长到 160KB+，翻十屏全是两周前的自检噪音。
LOG_MAX_BYTES = 1_500_000
#: 本进程内已落盘过的消息（去重键 = 文件名 + 正文）。
_LOGGED_MSGS = set()
_LOGGED_LOCK = threading.Lock()

#: 关键词 → 级别标记。调用点不必逐个改造：扫日志时 [E]/[W] 一眼可见。
_LOG_ERR_WORDS = ("失败", "异常", "错误", "Error", "error", "Exception",
                  "Traceback", "不可用", "无法", "拒绝")
_LOG_WARN_WORDS = ("警告", "降级", "回退", "兜底", "重试", "超时", "跳过")


def _log_level_tag(msg):
    """按消息关键词推断级别标记（E=错 / W=警 / I=常）。"""
    s = str(msg)
    if any(w in s for w in _LOG_ERR_WORDS):
        return "E"
    if any(w in s for w in _LOG_WARN_WORDS):
        return "W"
    return "I"


def _rotate_log(path, max_bytes=None):
    """超限即把 ``<path>`` 挪成 ``<path>.1``（覆盖上一代），只保留一代历史。"""
    limit = LOG_MAX_BYTES if max_bytes is None else max_bytes
    try:
        if os.path.exists(path) and os.path.getsize(path) > limit:
            bak = path + ".1"
            try:
                if os.path.exists(bak):
                    os.remove(bak)
            except OSError:
                pass
            os.replace(path, bak)
    except OSError:
        pass


def _is_selftest_run():
    """当前进程是否自检/冒烟脚本（脚本名以 ``_selftest``/``_smoke`` 开头）。

    自检会反复触发协议纠偏与补丁挂载，日志混进生产日志后真问题就找不着
    ——自动改写到 ``*_selftest.log``，不必逐个脚本自己设环境变量。
    显式设 ``VT_SELFTEST=1`` 亦可强制开启。
    """
    if os.environ.get("VT_SELFTEST"):
        return True
    try:
        base = os.path.basename(sys.argv[0] or "").lower()
    except Exception:  # noqa: BLE001
        return False
    return base.startswith("_selftest") or base.startswith("_smoke")


def _append_log(filename, msg, dedup=True):
    """统一日志落盘：轮转 + 同进程去重 + 级别标记 + 自检隔离（best-effort）。

    · 自检/测试进程（脚本名 ``_selftest*``/``_smoke*`` 或 ``VT_SELFTEST=1``）
      写 ``<name>_selftest.log``——自检会反复触发协议纠偏、补丁挂载，混进
      生产日志后真问题就找不着了；
    · 同进程内完全相同的消息只落**首次**（跨进程/重启仍各记一次）；
      协议探测与自检会把同一条「已挂」「自动改走」重放几十次，去重后日志
      才读得下去；
    · 任何异常都吞掉——日志永远不能反过来影响主流程。
    """
    try:
        name = filename
        if _is_selftest_run():
            name = (filename[:-4] + "_selftest.log"
                    if filename.endswith(".log") else filename + "_selftest.log")
        if dedup:
            key = (name, str(msg))
            with _LOGGED_LOCK:
                if key in _LOGGED_MSGS:
                    return
                _LOGGED_MSGS.add(key)
        os.makedirs(LOGS_DIR, exist_ok=True)
        path = os.path.join(LOGS_DIR, name)
        _rotate_log(path)
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(path, "a", encoding="utf-8") as f:
            f.write("[%s] [%s] %s\n" % (stamp, _log_level_tag(msg), msg))
    except OSError:
        pass


def _vc_log(msg):
    """引擎侧运行期补丁日志（logs\\vc_fallback.log，best-effort）。

    轮转/去重/级别/自检隔离见 `_append_log`。
    """
    _append_log("vc_fallback.log", msg)




__all__ = ["LOG_MAX_BYTES"]  # 其余全私有；调用方按需 from core.shared.log import _append_log
