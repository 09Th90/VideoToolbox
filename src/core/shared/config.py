# -*- coding: utf-8 -*-
# @version 2.4.1
"""设置持久化（config.json：数据根内，只读时回退程序目录）（v2.3.1 拆分工程 · 自 video_toolbox.py 原样搬入）。

本模块是 src/core/shared/ 的组成部分；域间依赖规则见 core/__init__.py。
"""

from core.shared.paths import DEFAULT_DOWNLOAD_DIR, clean_path

import json
import os
import shutil

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
    # 顺序：正式文件 → 上一份可用副本（.bak）→ 回退路径。
    # .bak 由 _atomic_write_json 维护，只在原文件可解析时才更新，
    # 因此它是「最后一次写入成功」的可靠快照；正式文件被外部截断/损坏时
    # 靠它把用户设置找回来，而不是返回空 dict 让全部设置消失。
    fb = _fallback_config_path()
    paths = [CONFIG_PATH, CONFIG_PATH + ".bak"]
    if os.path.abspath(fb) != os.path.abspath(CONFIG_PATH):
        paths += [fb, fb + ".bak"]
    for path in paths:
        try:
            with open(path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            if isinstance(cfg, dict) and cfg:
                return cfg
        except Exception:
            continue
    return {}


def save_config(cfg):
    """写入配置（原子写 + 保留上一份可用副本）。

    直接 ``open(path, "w")`` 覆写有两个致命问题：
      1. 写入过程不是原子的——进程被强杀 / 断电 / 磁盘满时，磁盘上会留下
         **截断的 JSON**。``load_config`` 遇到解析失败会 continue 到回退路径，
         而两条路径指向同一个文件，最终返回 ``{}``：**用户全部设置一次性丢失**
         （实测 302 个键 → 0）。
      2. 没有任何可回滚的副本。
    因此改为「写同目录临时文件 → flush+fsync → os.replace 原子替换」，
    替换前把旧文件复制成 ``config.json.bak``（替换成功后才覆盖，损坏的那份
    永远不会成为新的 .bak）。
    """
    candidates = [CONFIG_PATH]
    fb = _fallback_config_path()
    if os.path.abspath(fb) != os.path.abspath(CONFIG_PATH):
        candidates.append(fb)
    for path in candidates:
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            _atomic_write_json(path, cfg)
            return True
        except Exception:
            continue
    return False


def _atomic_write_json(path, cfg):
    """原子写 JSON：临时文件 → fsync → os.replace；旧文件先备份成 .bak。"""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
        f.flush()
        try:
            os.fsync(f.fileno())     # 断电也不留半截
        except (OSError, AttributeError):
            pass
    # 旧文件备份：只在旧文件**可解析**时才覆盖 .bak，保证 .bak 永远是好的
    try:
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as old:
                _ok = isinstance(json.load(old), dict)
            if _ok:
                shutil.copyfile(path, path + ".bak")
    except Exception:  # noqa: BLE001
        pass
    os.replace(tmp, path)            # Windows/POSIX 均保证原子性


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
