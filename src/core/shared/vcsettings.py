# -*- coding: utf-8 -*-
# @version 2.5.1
"""字幕引擎 settings.json 读写 + 全局 LLM 注入（OpenAI 兼容槽）（v2.3.1 拆分工程 · 自 video_toolbox.py 原样搬入）。

本模块是 src/core/shared/ 的组成部分；域间依赖规则见 core/__init__.py。
"""

import os
from core.shared.textio import read_text_any

import json
import sys

from core.shared.ai import ai_load_config
from core.shared.paths import DATA_DIR
from core.shared.runtime import VC_NAME, vc_data_dir

# ---------- 引擎 settings.json：路径全部收进软件文件夹 + 全局 LLM 注入 ----------
def vc_settings_path():
    """字幕引擎的 settings.json 路径（数据根下，绝不在系统盘）。"""
    return os.path.join(vc_data_dir(), "settings.json")


def _vc_read_settings():
    """读取引擎 settings.json；缺失/损坏返回空 dict（绝不抛异常）。"""
    try:
        data = json.loads(read_text_any(vc_settings_path()))
        if isinstance(data, dict):
            return data
    except (OSError, ValueError):
        pass
    return {}


def _vc_write_settings(data):
    """原子写回引擎 settings.json（缩进与上游 qconfig 落盘风格一致）。"""
    path = vc_settings_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".vt_tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
    os.replace(tmp, path)


def _path_on_system_drive(p):
    """绝对路径是否落在系统盘（默认 C:）的用户目录/AppData/ProgramData。

    用于揪出引擎历史设置里仍指向 C 盘的路径项；非绝对路径（相对/空）一律
    视为安全（上游会按重定向后的常量解析到软件文件夹）。
    """
    if not p or not isinstance(p, str) or not os.path.isabs(p):
        return False
    s = p.replace("/", "\\").lower()
    drive = os.path.splitdrive(s)[0]
    sys_drive = (os.environ.get("SystemDrive") or "C:").lower()
    if not drive or drive != sys_drive:
        return False
    home = os.path.expanduser("~").replace("/", "\\").lower()
    return (bool(home) and s.startswith(home)) or ("\\appdata\\" in s) \
        or ("\\programdata\\" in s) or ("\\users\\" in s)


def _vc_force_local_paths(settings):
    """把 settings 里仍指向系统盘的路径项改到软件文件夹。返回是否有改动。"""
    changed = False
    # 工作目录：无条件收敛到数据根下的 work-dir（上游用正斜杠存储）
    work_posix = os.path.join(vc_data_dir(), "work-dir").replace(os.sep, "/")
    save = settings.setdefault("Save", {})
    if str(save.get("Work_Dir", "")).replace("\\", "/") != work_posix:
        save["Work_Dir"] = work_posix
        changed = True
    # 转录模型目录：空值=用重定向后的 models 目录；若被指到系统盘则清空回默认
    fw = settings.get("FasterWhisper")
    if isinstance(fw, dict) and _path_on_system_drive(fw.get("ModelDir", "")):
        fw["ModelDir"] = ""
        changed = True
    # 字幕样式预览图若残留在系统盘历史目录，清空（样式参数本身保留）
    ss = settings.get("SubtitleStyle")
    if isinstance(ss, dict) and _path_on_system_drive(ss.get("PreviewImage", "")):
        ss["PreviewImage"] = ""
        changed = True
    return changed


def apply_global_llm_to_engine(ai_cfg=None):
    """把全局 AI 配置写入引擎的 OpenAI 兼容槽。

    v1.10.8 起字幕引擎不再保留独立 LLM 设置；v1.12.0 起全局 AI 合并为单通道
    （base_url / api_key / model 一套），工具箱、字幕引擎、AI 校准共用。
    同时若引擎 QConfig 已在本进程加载，把内存里的对应项一并改掉（免重启生效）。
    返回 (是否成功, 说明)。
    """
    try:
        ai = ai_cfg or ai_load_config()
        data = _vc_read_settings()
        llm = data.setdefault("LLM", {})
        if not bool(ai.get("enabled", True)):
            # 「启用 AI」已关闭：清空引擎 LLM 槽（含内存态）。引擎的优化
            # 会明确提示需配置 AI，而不是拿着历史注入的密钥偷偷消耗额度。
            wiped = False
            for k in ("OpenAI_API_Key", "OpenAI_API_Base", "OpenAI_Model"):
                if llm.get(k):
                    llm[k] = ""
                    wiped = True
            if wiped:
                _vc_write_settings(data)
            # 内存态同步仅在引擎配置已加载时做（未加载时导入它白付 ~1s，
            # 而引擎此后首次读盘拿到的就是刚写的 settings.json）。
            if "videocaptioner.ui.common.config" in sys.modules:
                try:
                    from videocaptioner.ui.common.config import cfg as _cfg
                    _cfg.set(_cfg.openai_api_key, "")
                except Exception:
                    pass
            return True, "AI 已关闭，未写入引擎 LLM 槽"
        base = str(ai.get("base_url") or "").strip()
        key = str(ai.get("api_key") or "").strip()
        model = str(ai.get("model") or "").strip()
        llm["LLMService"] = "OpenAI 兼容"
        if base:
            llm["OpenAI_API_Base"] = base
        if key:
            llm["OpenAI_API_Key"] = key
        if model:
            llm["OpenAI_Model"] = model
        _vc_write_settings(data)
        # 内存态同步（引擎界面已构建、QConfig 已导入时）
        # ⚠ 同上：只在已加载时才同步，未加载时导入纯属白付时间。
        if "videocaptioner.ui.common.config" in sys.modules:
            try:
                from videocaptioner.ui.common.config import cfg as _cfg
                from engine_entities import LLMServiceEnum
                if base:
                    _cfg.set(_cfg.openai_api_base, base)
                if key:
                    _cfg.set(_cfg.openai_api_key, key)
                if model:
                    _cfg.set(_cfg.openai_model, model)
                _cfg.set(_cfg.llm_service, LLMServiceEnum.OPENAI)
            except Exception:
                pass
        return True, "ok"
    except Exception as e:  # noqa: BLE001
        return False, str(e)




__all__ = [
    "vc_settings_path",
    "apply_global_llm_to_engine",
]
