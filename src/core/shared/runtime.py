# -*- coding: utf-8 -*-
# @version 2.3.1
"""内置运行时与字幕引擎（videocaptioner）环境探测/资源接驳（v2.3.1 拆分工程 · 自 video_toolbox.py 原样搬入）。

本模块是 src/core/shared/ 的组成部分；域间依赖规则见 core/__init__.py。
"""

import shutil

import os
import sys

from core.shared.log import _vc_log
from core.shared.paths import (APP_DIR, CACHE_DIR, DATA_DIR, DATA_ROOT,
                                DOCS_DIR, TMP_DIR, TOOLS_DIR)

# ========== 内置运行时（字幕处理） ==========
# tools\python 为随安装包分发的 CPython 3.12 运行时：faster-whisper、
# VideoCaptioner 及其依赖全部装在其 site-packages 下。
EMBEDDED_PYTHON_DIR = os.path.join(TOOLS_DIR, "python")
EMBEDDED_SITE_PACKAGES = os.path.join(EMBEDDED_PYTHON_DIR, "Lib", "site-packages")


def _is_self_exe(path):
    """path 是否就是本程序自身（打包后 sys.executable 指向 exe 自己）。

    一旦把自身 exe 当作「Python 解释器」去 Popen，Windows 会拉起一个全新的
    主程序实例——v1.12.0 的退出同步就是这么写的，结果退出时不断自启、表现为
    「关不掉的反复重启」。所有解析解释器 / 启动子进程的地方都必须过这道闸。
    """
    if not path or not getattr(sys, "frozen", False):
        return False
    try:
        return (os.path.normcase(os.path.abspath(path)) ==
                os.path.normcase(os.path.abspath(sys.executable)))
    except Exception:  # noqa: BLE001
        return False


def system_python():
    """运行字幕处理 / 投稿 worker 的 Python：优先用工具箱内 tools\\python\\python.exe；
    否则源码模式用当前解释器，打包后用系统 PATH 中的 python（找不到返回 ""）。"""
    embedded = os.path.join(EMBEDDED_PYTHON_DIR, "python.exe")
    if os.path.isfile(embedded):
        return embedded
    if not getattr(sys, "frozen", False):
        return sys.executable
    found = shutil.which("python") or ""
    return "" if _is_self_exe(found) else found


def worker_subprocess_env():
    """worker 子进程环境：内嵌解释器已完整自包含，无需注入 PYTHONPATH；
    仅当回退到系统 Python 时，把内嵌 site-packages 追加进去以免缺包。
    v1.10.6 起同时把 TEMP/TMP 指向数据根目录，避免子进程把中间产物
    写进系统盘；并传递 VT_DATA_ROOT 供子进程内的引擎解析同一根目录。
    缓存目录（XDG_CACHE_HOME / HF_HOME / HF_HUB_CACHE）同样显式下发，
    保证子进程里的 faster-whisper 不会退回去读 %USERPROFILE%\\.cache。"""
    env = os.environ.copy()
    if system_python() != os.path.join(EMBEDDED_PYTHON_DIR, "python.exe"):
        env["PYTHONPATH"] = (EMBEDDED_SITE_PACKAGES + os.pathsep +
                             env.get("PYTHONPATH", "")).rstrip(os.pathsep)
    try:
        os.makedirs(TMP_DIR, exist_ok=True)
        env["TEMP"] = TMP_DIR
        env["TMP"] = TMP_DIR
    except OSError:
        pass
    env["VT_DATA_ROOT"] = DATA_ROOT
    env["XDG_CACHE_HOME"] = CACHE_DIR
    env["HF_HOME"] = os.path.join(CACHE_DIR, "huggingface")
    env["HF_HUB_CACHE"] = os.path.join(CACHE_DIR, "huggingface", "hub")
    env["DENO_DIR"] = os.path.join(CACHE_DIR, "deno")
    env["MODELSCOPE_CACHE"] = os.path.join(CACHE_DIR, "modelscope")
    env["XDG_CONFIG_HOME"] = os.path.join(CACHE_DIR, "xdg-config")
    env["XDG_DATA_HOME"] = os.path.join(CACHE_DIR, "xdg-data")
    # v1.19.2：**剥掉标准代理环境变量**。requests / httpx 默认会读
    # https_proxy/http_proxy/ALL_PROXY 并静默套在所有请求上——而 IDE 注入的
    # 127.0.0.1:<随机端口> 往往只对特定流量生效（实测对微软翻译、moonshot
    # 等国内站点一律不通），于是「调用方以为在直连、实际走了坏代理」。
    # 2026-10-17 用户遇到的「252/252 segments failed」即此形态。
    # 本项目的代理都是**显式**传递的（yt-dlp 走 --proxy、AI/翻译走
    # translate_session_proxies/http_proxies_for），不依赖环境变量，
    # 因此剥掉是安全的；显式 VT_YTDLP_PROXY 是我们的通道，保留。
    for _k in ("https_proxy", "HTTPS_PROXY", "http_proxy", "HTTP_PROXY",
               "ALL_PROXY", "all_proxy"):
        env.pop(_k, None)
    return env
# =============================


# ========== 字幕处理：内嵌第三方字幕引擎（GPL-3.0 组件，随包分发） ==========
# v1.10.2 起，字幕引擎界面直接内嵌在主程序「字幕处理」页中（不再唤起独立
# 窗口）。引擎以第三方开源组件形式随包分发：打包形态打进 exe（见
# 视频工具箱.spec），源码形态装在 tools\python\Lib\site-packages 下。
# 工具箱负责：环境探测 → 引擎界面内嵌 → 用户可见文案中性化（品牌水印、
# 捐助入口等在嵌入层隐藏；许可与来源见 docs\ 下声明文件）。
VC_NAME = "VideoCaptioner"
VC_VERSION = "1.4.2"
VC_LICENSE = "GPL-3.0"
VC_HOMEPAGE = "https://github.com/WEIFENG2333/VideoCaptioner"
VC_DOCS = "https://weifeng2333.github.io/VideoCaptioner/"
VC_PKG_DIR = os.path.join(EMBEDDED_SITE_PACKAGES, "videocaptioner")
# 许可与来源声明文件（docs\ 下实际文件名——2026-10-12 修正：此前指向重命名前的
# 旧文件名，而 packaging\视频工具箱.iss 早已跟随新名，GUI 自检「许可随包」一项
# 因此长期误报；两处文件名以 docs\ 与 iss 为准保持一致）。
VC_LICENSE_FILE = os.path.join(DOCS_DIR, "开源许可_GPL-3.0.txt")
VC_SOURCE_FILE = os.path.join(DOCS_DIR, "第三方组件来源与许可声明.txt")


def vc_importable():
    """内嵌字幕引擎在当前进程是否可用（源码模式依赖 tools\\python 的包）。"""
    try:
        import importlib.util
        return importlib.util.find_spec("videocaptioner") is not None
    except Exception:
        return False


def vc_missing_deps():
    """引擎界面运行所需依赖缺哪些（PySide6 / qfluentwidgets）；齐全返回空列表。"""
    import importlib.util
    need = {"PySide6": "PySide6", "qfluentwidgets": "PySide6-Fluent-Widgets"}
    return [pip_name for mod, pip_name in need.items()
            if importlib.util.find_spec(mod) is None]


def vc_env_ready():
    """字幕引擎是否可在当前进程内嵌：包与 Qt 依赖齐全。"""
    return vc_importable() and not vc_missing_deps()


def vc_state():
    """环境状态文案，供 GUI 显示。返回 (是否就绪, 主文案, 细节文案)。"""
    if vc_env_ready():
        return True, "字幕引擎已就绪（内嵌运行）", ""
    if not vc_importable():
        return (False, "未安装字幕引擎组件",
                "当前进程找不到字幕引擎组件。安装版自带（打进主程序）；"
                "源码方式运行请用 src\\视频工具箱.bat（走 tools\\python 运行时）。")
    return (False, "字幕引擎依赖不完整：缺少 " + "、".join(vc_missing_deps()),
            "请使用完整版安装包重新安装（依赖随机带运行时分发）")


def vc_data_dir():
    """字幕引擎的配置/日志数据目录。

    v1.10.6 起不再使用 platformdirs 的 %LOCALAPPDATA%（C 盘）约定，
    改为数据根目录下的 data/VideoCaptioner，与工具箱其余运行期产物同处，
    便于整体搬迁与清理。
    """
    return os.path.join(DATA_DIR, VC_NAME)


# 字幕引擎在 C 盘的历史数据位置（用于一次性迁移与"残留检测"）
_VC_LEGACY_DIRS = (
    os.path.join(os.environ.get("LOCALAPPDATA", ""), VC_NAME),
    os.path.join(os.environ.get("APPDATA", ""), VC_NAME),
    os.path.join(os.path.expanduser("~"), VC_NAME),
)


def vc_bundled_resource_dir():
    """随包分发的引擎只读静态资源目录（assets/fonts/subtitle_style/translations）。

    VideoCaptioner 的纯代码 wheel 只含 .py、不含 resource/，故我们把与所集成
    版本一致的上游 resource 静态文件随包放在 tools/videocaptioner/resource 下，
    既不落到系统盘，也保证离线环境下界面图片、默认字幕样式、烧录字体齐全。
    """
    return os.path.join(TOOLS_DIR, "videocaptioner", "resource")


def vc_redirect_paths():
    """在导入 videocaptioner 之前，把引擎的数据/工作/日志目录重定向到数据根目录，
    并把静态资源、ffmpeg 接到随包目录，使字幕引擎真正自包含、成为程序的一部分。

    上游 config.py 在导入时即固化一批常量：
      · ROOT_PATH  = platformdirs.user_data_dir("VideoCaptioner")  → AppData\\Local
      · WORK_PATH  = Path.home() / "VideoCaptioner"                → 用户目录
      · RESOURCE_PATH/ASSETS_PATH/BIN_PATH/FONTS_PATH/...          → 上述目录下
    pip 形态下 wheel 只有代码、没有 resource（界面图片/默认样式缺失），且空的
    BIN_PATH 不会被加入 PATH，导致引擎内部裸调 "ffmpeg" 时找不到二进制。这里在不
    改动第三方源码的前提下统一打补丁：
      · 可写运行数据（日志/缓存/模型/工作目录/设置/用户字幕样式）→ data\\VideoCaptioner
      · 只读静态资源（图片/字体/翻译/默认样式）→ tools\\videocaptioner\\resource
      · ffmpeg/ffprobe 复用工具箱自带 tools\\ffmpeg.exe（BIN_PATH=TOOLS_DIR 并加入 PATH）
    """
    import sys as _sys
    from engine_paths import (REDIRECT_FLAG, apply_engine_paths,
                              ensure_runtime_dirs)

    _cfg_mod = _sys.modules.get("videocaptioner.config")
    if _cfg_mod is not None:
        if getattr(_cfg_mod, REDIRECT_FLAG, False):
            return  # 本进程已重定向过，幂等
        # 已导入但没重定向过 = 有补丁抢跑了（见 prepare_runtime_env 里的顺序说明）。
        # 此时部分模块可能已把默认常量固化成 AppData，仍尽量覆盖可动态读取的部分，
        # 并留下日志，避免这类问题再次静默发生。
        try:
            _vc_log("警告：videocaptioner.config 在重定向前已被导入，"
                    "引擎部分模块可能仍指向默认（AppData）路径")
        except Exception:
            pass

    from videocaptioner import config as _vc_cfg

    # 路径取值的唯一事实来源是自研 engine_paths（v1.20.0 起接管 config 接缝）：
    # 本函数只负责「取第三方模块 → 交给自研模块写 → 建目录 / 注 PATH」。
    # 引擎侧日后新增路径常量，只需改 engine_paths 一处，不必在这里人肉维护。
    _paths = _engine_paths()
    try:
        from videocaptioner.cli import config as _vc_cli
    except Exception:
        _vc_cli = None
    apply_engine_paths(
        _vc_cfg, _paths,
        cli_cfg=_vc_cli,
        fallback_fonts_dir=getattr(_vc_cfg, "_BUNDLED_FONTS", None),
    )
    ensure_runtime_dirs(
        _paths,
        fallback_fonts_dir=getattr(_vc_cfg, "_BUNDLED_FONTS", None),
    )


def _engine_paths():
    """构造引擎路径视图（``engine_paths.EnginePaths``）。

    单独一个小函数是为了让自检能直接复用同一套取值，而不必重复拼
    ``DATA_DIR`` / ``TOOLS_DIR`` / 随包资源目录这三处。
    """
    from engine_paths import EnginePaths
    return EnginePaths(
        data_dir=vc_data_dir(),
        tools_dir=TOOLS_DIR,
        bundled_resource_dir=vc_bundled_resource_dir(),
        vc_name=VC_NAME,
    )


__all__ = [
    "EMBEDDED_PYTHON_DIR",
    "EMBEDDED_SITE_PACKAGES",
    "system_python",
    "worker_subprocess_env",
    "VC_NAME",
    "VC_VERSION",
    "VC_LICENSE",
    "VC_HOMEPAGE",
    "VC_DOCS",
    "VC_PKG_DIR",
    "VC_LICENSE_FILE",
    "VC_SOURCE_FILE",
    "vc_importable",
    "vc_missing_deps",
    "vc_env_ready",
    "vc_state",
    "vc_data_dir",
    "vc_bundled_resource_dir",
    "vc_redirect_paths",
]
