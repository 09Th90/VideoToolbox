# -*- coding: utf-8 -*-
# @version 2.5.0
"""NPE 第二解析引擎（NewPipe Extractor，yt-dlp 失败兜底）（v2.3.1 拆分工程 · 自 video_toolbox.py 原样搬入）。

core/download 域：yt-dlp 全链 / cookie / NPE / 媒体合并；依赖规则见 core/__init__.py。
"""

from core.download.cookies import GUEST_COOKIES_PATH, ytdlp_cookie_args


from core.shared.config import load_config

import os

import npe_backend

from core.download.cookies import ytdlp_cookie_args
from core.shared.proxy import ytdlp_proxy_args

# ========== NPE 第二解析引擎（NewPipe Extractor，2026-10-08 接入） ==========
#: NPE 引擎模式：auto（yt-dlp 各源失败后兜底，默认）/ off（完全不用）/ only（直接用）
CFG_NPE_ENGINE = "npe_engine"


def npe_engine_mode():
    """当前 NPE 引擎模式：auto（默认，yt-dlp 失败后兜底）/ off / only。

    配置项 `npe_engine`（data/ai_config.json）为主；环境变量
    `VT_NPE_ENGINE` 可临时覆盖（排查问题时不必改配置文件）。

    ⚠️ 当前实现里 **only 与 auto 行为相同**（yt-dlp 仍先跑，只在它全失败后
    才启用 NPE 兜底）——见 video_toolbox_qt 里 `!= "off"` 的判定。`only`
    是为「强制只走 NPE」预留的取值，尚未接线，届时可在此处做分流。
    """
    env = os.environ.get("VT_NPE_ENGINE", "").strip().lower()
    if env in ("auto", "off", "only"):
        return env
    try:
        m = str((load_config() or {}).get(CFG_NPE_ENGINE) or "auto").strip().lower()
    except Exception:  # noqa: BLE001
        m = "auto"
    return m if m in ("auto", "off", "only") else "auto"


def npe_available():
    """(是否可用, 说明)。缺 java 或未构建 jar 时返回 False。"""
    try:
        import npe_backend
        return npe_backend.is_available()
    except Exception as e:  # noqa: BLE001
        return False, f"NPE 模块不可用：{e}"


def npe_proxy_url():
    """NPE / ffmpeg 要用的代理 URL（拿不到返回空串）。"""
    try:
        args = ytdlp_proxy_args()
    except Exception:  # noqa: BLE001
        return ""
    return args[1] if args else ""




def npe_cookie_file(log=None):
    """给 NPE 用的 **cookie 文件**路径（Netscape 格式）。

    与 yt-dlp 的 cookie 来源刻意不同：yt-dlp 可以用 `--cookies-from-browser`
    直接读浏览器 cookie 库，而 NPE 只吃文件。所以这里复用 `ytdlp_cookie_args()`
    的解析结果，只在它是「文件型」时采用；若它给的是浏览器模式，则回落到
    游客 cookie 文件（data/guest_cookies.txt），实在没有才返回空串。
    """
    try:
        args = ytdlp_cookie_args(log=log)
    except Exception:  # noqa: BLE001
        args = []
    if args and len(args) > 1 and args[0] == "--cookies" and os.path.isfile(args[1]):
        return args[1]
    return GUEST_COOKIES_PATH if os.path.isfile(GUEST_COOKIES_PATH) else ""




__all__ = [
    "CFG_NPE_ENGINE",
    "npe_engine_mode",
    "npe_available",
    "npe_proxy_url",
    "npe_cookie_file",
]
