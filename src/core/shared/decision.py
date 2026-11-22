# -*- coding: utf-8 -*-
# @version 3.2.0
"""System One / Jev 客户端加载缝（实现位于 tools/decision_client.py）。"""
import os
import sys

from core.shared.ai import ai_load_config
from core.shared.paths import TOOLS_DIR

_DECISION_MOD = None


def decision_mod():
    global _DECISION_MOD
    if _DECISION_MOD is None:
        import importlib
        import importlib.util
        path = os.path.join(TOOLS_DIR, "decision_client.py")
        mod = None
        # 优先常规 import（TOOLS_DIR 注入 sys.path）：打包后随包目录可直接导入，
        # 不依赖绝对路径动态加载（v3.1.5：修打包后 tools 缺失即裸 FileNotFoundError）。
        if os.path.isdir(TOOLS_DIR):
            if TOOLS_DIR not in sys.path:
                sys.path.insert(0, TOOLS_DIR)
            try:
                mod = importlib.import_module("decision_client")
            except Exception:  # noqa: BLE001 - 回退按文件位置加载
                mod = None
        if mod is None:
            if not os.path.isfile(path):
                raise FileNotFoundError(
                    f"decision_client.py 缺失（TOOLS_DIR={TOOLS_DIR}）："
                    "请确认 tools 目录随包分发或重新安装")
            spec = importlib.util.spec_from_file_location("vt_decision_client", path)
            if spec is None or spec.loader is None:
                raise ImportError(f"无法加载 decision_client：{path}")
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
        _DECISION_MOD = mod
    return _DECISION_MOD


def decision_client(config=None, **kwargs):
    cfg = dict(config if config is not None else ai_load_config())
    return decision_mod().DecisionClient(cfg, **kwargs)


__all__ = ["decision_mod", "decision_client"]
