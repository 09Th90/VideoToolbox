# @version 2.5.0
"""路径契约收口（复用自研接缝模块 ``engine_paths``）。

``vt_engine`` 的路径事实来源与主程序共用同一份实现，避免两处漂移：
引擎的数据目录名（``VideoCaptioner``）同时是**用户已有数据的目录名**，
任何一侧单独改名都会让老用户「设置与历史全丢」。

新增 :func:`default_engine_paths`——按项目数据根解析约定构造
:class:`EnginePaths`（优先 ``core.shared.paths``，缺失时自行推导），
供本包各模块在无主程序上下文时使用。
"""

from __future__ import annotations

from vt_engine._bootstrap import SRC_DIR  # noqa: F401  （确保平铺模块可导入）

from engine_paths import (  # noqa: E402
    EnginePaths,
    REDIRECT_FLAG,
    apply_engine_paths,
    ensure_runtime_dirs,
)

__all__ = [
    "EnginePaths",
    "REDIRECT_FLAG",
    "apply_engine_paths",
    "ensure_runtime_dirs",
    "default_engine_paths",
]


def _resolve_data_dir_and_tools():
    """数据目录与 tools 目录的解析（单一事实来源优先，其次自行推导）。

    返回 ``(data_dir, tools_dir)``。解析失败时退化为 src 上两级目录下的
    常规布局——与 ``tools/ai_client.py`` 的兜底同构。
    """
    try:
        from core.shared.paths import DATA_DIR, TOOLS_DIR  # type: ignore
        return DATA_DIR, TOOLS_DIR
    except Exception:
        pass
    import os
    # VT_DATA_ROOT > 指针文件 data_dir.txt > 程序根（src 的上一级）
    app_dir = os.path.dirname(SRC_DIR)
    env = (os.environ.get("VT_DATA_ROOT") or "").strip().strip('"')
    root = env or app_dir
    if not env:
        try:
            pointer = os.path.join(app_dir, "data_dir.txt")
            if os.path.isfile(pointer):
                with open(pointer, encoding="utf-8-sig") as f:
                    v = f.read().strip().strip('"')
                if v:
                    root = v
        except OSError:
            pass
    return os.path.join(root, "data"), os.path.join(app_dir, "tools")


def default_engine_paths() -> EnginePaths:
    """按当前运行上下文构造默认 :class:`EnginePaths`（纯计算，无副作用）。"""
    import os
    data_dir, tools_dir = _resolve_data_dir_and_tools()
    return EnginePaths(
        data_dir=os.path.join(data_dir, "VideoCaptioner"),
        tools_dir=tools_dir,
    )
