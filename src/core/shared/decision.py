# -*- coding: utf-8 -*-
# @version 3.2.5
"""System One / Jev 客户端加载缝（实现位于 tools/decision_client.py）。

WP3 part 1（2026-11-22）：决策通道**独立凭据注入**——
  * decision_api_key 只存 data/credentials.json（credential_store），绝不写进
    ai_config.json；本缝按需读取并**仅内存**覆盖 cfg["api_key"]，任何路径都
    不会把它回写配置文件（本缝从不调用 save_config）；
  * 未配置独立 key 时 R0 影子允许回落全局 api_key，来源标记
    credential_source="global_fallback"（进审计）；**不做**「静默复制全局
    key 到 decision_api_key」——那会绕过凭据来源审计语义，设置页引导显式
    配置（WP6）；
  * R1 起可在配置里 decision_require_own_key=True 强制独立 key（缺失即
    missing_decision_key 不可用），本缝只透传配置，不替用户兜底。
"""
import os
import sys

from core.shared.ai import ai_load_config
from core.shared.paths import TOOLS_DIR

_DECISION_MOD = None
_CRED_MOD = None


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


def credential_mod():
    """按路径加载 tools/credential_store.py（决策独立凭据的唯一权威来源）。"""
    global _CRED_MOD
    if _CRED_MOD is None:
        import importlib
        import importlib.util
        if os.path.isdir(TOOLS_DIR) and TOOLS_DIR not in sys.path:
            sys.path.insert(0, TOOLS_DIR)
        try:
            _CRED_MOD = importlib.import_module("credential_store")
        except Exception:  # noqa: BLE001 - 回退按文件位置加载
            path = os.path.join(TOOLS_DIR, "credential_store.py")
            if not os.path.isfile(path):
                raise FileNotFoundError(
                    f"credential_store.py 缺失（TOOLS_DIR={TOOLS_DIR}）")
            spec = importlib.util.spec_from_file_location(
                "vt_credential_store", path)
            if spec is None or spec.loader is None:
                raise ImportError(f"无法加载 credential_store：{path}")
            _CRED_MOD = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(_CRED_MOD)
    return _CRED_MOD


def decision_client(config=None, **kwargs):
    """构造 Jev 客户端：独立凭据注入 + 凭据来源标记（仅内存，永不回写配置）。

    有独立 decision_api_key → cfg["api_key"] **仅内存**覆盖为独立 key，
    credential_source="decision"；
    没有 → credential_source="global_fallback"（R0 影子允许回落全局
    api_key；R1 可由 decision_require_own_key 强制不可用）。
    """
    cfg = dict(config if config is not None else ai_load_config())
    try:
        own = credential_mod().get("decision_api_key", "")
    except Exception:  # noqa: BLE001 - 凭据层缺失按未配置处理，绝不阻断
        own = ""
    if not own:
        own = str(cfg.get("decision_api_key") or "").strip()
    if own:
        cfg["api_key"] = own                 # 仅内存覆盖；本缝永不回写配置
        cfg["decision_api_key"] = own
        cfg["credential_source"] = "decision"
    else:
        cfg["credential_source"] = "global_fallback"
    return decision_mod().DecisionClient(cfg, **kwargs)


__all__ = ["decision_mod", "credential_mod", "decision_client"]
