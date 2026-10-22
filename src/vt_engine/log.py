# @version 2.5.3
"""日志器（自研，替代 videocaptioner.core.utils.logger.setup_logger）。

可观察契约：``setup_logger(name)`` 返回可用 ``logging.Logger``，
INFO 用简化格式、其余级别带时间戳；文件日志落在引擎数据目录的
``logs`` 下，控制台副本可选。落盘失败（只读介质/权限）时**不抛**——
日志不可用不能拖垮转录主链。

自检隔离：``VT_SELFTEST=1`` 或脚本名以 ``_selftest`` / ``_smoke`` 开头时
写独立日志文件，避免自检污染正式日志（与 ``tools/ai_client.py`` 同一判据）。
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import sys

__all__ = ["setup_logger", "engine_log_dir"]

_LEVEL = logging.INFO


def _is_selftest_run() -> bool:
    if (os.environ.get("VT_SELFTEST") or "").strip() == "1":
        return True
    name = os.path.basename(sys.argv[0] or "")
    return name.startswith(("_selftest", "_smoke"))


def engine_log_dir() -> str:
    """引擎日志目录：``<数据根>/data/VideoCaptioner/logs``。

    与引擎同址——排障时两类日志在同一目录下对照。数据根解析优先
    复用项目 ``core.shared.paths``（单一事实来源），缺失时自行推导。
    """
    try:
        from core.shared.paths import DATA_DIR  # type: ignore
        return os.path.join(DATA_DIR, "VideoCaptioner", "logs")
    except Exception:
        pass
    from vt_engine.paths import default_engine_paths
    return str(default_engine_paths().log_path)


class _LevelSpecificFormatter(logging.Formatter):
    """按级别选用格式（INFO 简化、其余详细）。线程安全：不mutate共享 _style。"""

    def __init__(self, info_fmt, default_fmt, datefmt):
        super().__init__(default_fmt, datefmt)
        self._info_fmt = info_fmt
        self._datefmt = datefmt

    def format(self, record):
        fmt = self._info_fmt if record.levelno == logging.INFO \
            else self._fmt
        return logging.Formatter(fmt, self._datefmt).format(record)


def setup_logger(name: str, level: int = _LEVEL, console_output: bool = True,
                 log_file: str = "") -> logging.Logger:
    """创建/获取一个配置好的日志器（幂等：重复调用不重复挂 handler）。"""
    logger = logging.getLogger(name)
    logger.setLevel(level)
    if logger.handlers:
        return logger

    formatter = _LevelSpecificFormatter(
        info_fmt="%(message)s",
        default_fmt="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    if console_output:
        console = logging.StreamHandler()
        console.setFormatter(formatter)
        logger.addHandler(console)

    tag = "selftest" if _is_selftest_run() else "app"
    path = log_file or os.path.join(engine_log_dir(),
                                    "vt_engine_%s.log" % tag)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        fh = logging.handlers.RotatingFileHandler(
            path, maxBytes=8 * 1024 * 1024, backupCount=3,
            encoding="utf-8")
        fh.setFormatter(formatter)
        logger.addHandler(fh)
    except OSError:
        # 日志盘不可写：保留控制台副本即可，绝不因此抛异常
        pass
    return logger
