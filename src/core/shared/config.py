# -*- coding: utf-8 -*-
# @version 2.3.1
"""设置持久化（config.json：数据根内，只读时回退程序目录）（v2.3.1 拆分工程 · 自 video_toolbox.py 原样搬入）。

本模块是 src/core/shared/ 的组成部分；域间依赖规则见 core/__init__.py。
"""

from core.shared.paths import DEFAULT_DOWNLOAD_DIR, clean_path

import json
import os

from core.shared.paths import APP_DIR, CONFIG_PATH, DATA_DIR


def _fallback_config_path():
    """配置回退位置。

    v1.10.6 起：配置一律写在数据根目录下（默认程序目录），**不再回退到
    %LOCALAPPDATA%（C 盘）**。仅当数据根目录也写不进去时，才退到程序目录，
    保证"配置永不落系统盘"这一约束优先于可用性。
    """
    cand = os.path.join(DATA_DIR, "config.json")
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        return cand
    except OSError:
        return os.path.join(APP_DIR, "data", "config.json")


# ========== 设置持久化 ==========
def load_config():
    for path in (CONFIG_PATH, _fallback_config_path()):
        try:
            with open(path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            if isinstance(cfg, dict) and cfg:
                return cfg
        except Exception:
            continue
    return {}


def save_config(cfg):
    """写入配置；脚本目录只读时自动改写到用户本地目录，保证「长期固定」不失效"""
    candidates = [CONFIG_PATH]
    fb = _fallback_config_path()
    if os.path.abspath(fb) != os.path.abspath(CONFIG_PATH):
        candidates.append(fb)
    for path in candidates:
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
            return True
        except Exception:
            continue
    return False


def get_saved_download_dir():
    """上次使用的下载目录。

    即使该目录当前不存在（如外接硬盘未插入）也照样返回，
    以免用户的长期设置被静默丢掉；下载时会按需创建。
    """
    d = str(load_config().get("download_dir", "")).strip()
    return d if d else DEFAULT_DOWNLOAD_DIR


def set_saved_download_dir(path):
    """记住下载目录，下次启动自动填入（长期固定）"""
    path = clean_path(str(path or ""))
    if not path:
        return
    try:
        path = os.path.abspath(path)
    except Exception:
        pass
    cfg = load_config()
    cfg["download_dir"] = path
    save_config(cfg)


__all__ = [
    "load_config",
    "save_config",
    "get_saved_download_dir",
    "set_saved_download_dir",
]
