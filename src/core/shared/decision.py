# -*- coding: utf-8 -*-
# @version 3.1.4
"""System One / Jev 客户端加载缝（实现位于 tools/decision_client.py）。"""
import os

from core.shared.ai import ai_load_config
from core.shared.paths import TOOLS_DIR

_DECISION_MOD = None


def decision_mod():
    global _DECISION_MOD
    if _DECISION_MOD is None:
        import importlib.util
        path = os.path.join(TOOLS_DIR, "decision_client.py")
        spec = importlib.util.spec_from_file_location("vt_decision_client", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _DECISION_MOD = mod
    return _DECISION_MOD


def decision_client(config=None, **kwargs):
    cfg = dict(config if config is not None else ai_load_config())
    return decision_mod().DecisionClient(cfg, **kwargs)


__all__ = ["decision_mod", "decision_client"]
