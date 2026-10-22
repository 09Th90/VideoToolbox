# -*- coding: utf-8 -*-
# @version 2.5.3
"""全局 AI / LLM 配置与通道（tools/ai_client.py 加载器 + 配置读写/测试）（v2.3.1 拆分工程 · 自 video_toolbox.py 原样搬入）。

本模块是 src/core/shared/ 的组成部分；域间依赖规则见 core/__init__.py。
"""

import json

import os

from core.shared.paths import DATA_DIR, TOOLS_DIR

# ========== 全局 AI（智谱 GLM：字幕/标题语言识别） ==========
# AI 客户端实现在 tools\ai_client.py（仅标准库依赖，原投稿引擎内模块独立化），
# 按路径直接加载；配置在 data\ai_config.json，首次调用自动生成默认配置。
_AI_MOD = None


def ai_mod():
    """按路径加载内嵌 AI 客户端模块（缓存单例）。"""
    global _AI_MOD
    if _AI_MOD is None:
        import importlib.util
        path = os.path.join(TOOLS_DIR, "ai_client.py")
        spec = importlib.util.spec_from_file_location("vt_ai_client", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _AI_MOD = mod
    return _AI_MOD


def ai_detect_language(text):
    """AI 识别文本主要语言代码（zh/en/ja/...）；AI 不可用或失败返回 ''。"""
    try:
        if not ai_mod().is_enabled():
            return ""
        return ai_mod().detect_language(text)
    except Exception:
        return ""

# ========== 全局 AI / LLM 配置（v1.10.8：唯一一套，工具箱与字幕引擎共用） ==========
# 配置实体仍在 data\ai_config.json（由 tools\ai_client.py 读写），这里提供给
# 界面使用的加载 / 保存 / 连通性测试接口；保存后立即把 OpenAI 兼容槽同步给
# 字幕引擎，做到「LLM 配置只在全局设置里出现一次」。
AI_CONFIG_PATH = os.path.join(DATA_DIR, "ai_config.json")


def ai_load_config():
    """读取全局 AI/LLM 配置（缺失字段用出厂默认补齐）。ai_client 不可用时直接读文件。"""
    try:
        return ai_mod().load_config()
    except Exception:
        try:
            with open(AI_CONFIG_PATH, encoding="utf-8-sig") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}


def ai_match_settings(cfg=None):
    """设置自动匹配（2026-10-01 v2）：把一份 AI 配置修正成自洽可用的组合。

    返回 (修正后的配置, 说明列表)。纯本地计算（不发网络请求），是「设置页
    自动匹配按钮」与「校准入口最后自救」共用的唯一实现，规则见
    tools\\ai_client.py 的 match_settings()。ai_client 不可用时原样返回。
    """
    cfg = dict(cfg if cfg is not None else ai_load_config())
    try:
        return ai_mod().match_settings(cfg)
    except Exception as e:  # noqa: BLE001
        return cfg, ["自动匹配不可用：" + str(e)[:200]]


def ai_plan_risk(base_url):
    """订阅套餐端点的合规风险提示（规则见 ai_client.plan_endpoint_risk）。

    只提示、不阻止：套餐端点能不能用、会不会被判违规由服务商定，风险用户自负。
    非套餐端点或 ai_client 不可用时返回空串。
    """
    try:
        return ai_mod().plan_endpoint_risk(base_url)
    except Exception:  # noqa: BLE001
        return ""


def ai_plan_risks(cfg=None):
    """一份配置里**所有**套餐端点的风险提示（全局 AI / 视觉 / ASR 三处）。

    返回形如 ``["【ASR 语音识别】⚠️ 该地址是…"]``：**每条都带出处前缀**，
    同一端点占多个槽时合并标注（``【全局 AI / ASR 语音识别】``），没有套餐
    端点时返回空列表。

    ⚠️ 出处前缀不是装饰：三个槽各有独立地址，保存时是一条 InfoBar 汇总弹出。
    不带前缀时用户会以为它在说眼前卡片里的地址——实测 2026-10-05：全局 AI
    填的是智谱 open.bigmodel.cn，弹窗却在说「百炼 Token Plan」（告警其实来自
    ASR 槽），看起来就像"识别错了"。
    """
    cfg = dict(cfg if cfg is not None else ai_load_config())
    order, labels, tips = [], {}, {}
    for key, label in (("base_url", "全局 AI"),
                       ("vision_base_url", "视觉通道"),
                       ("asr_base_url", "ASR 语音识别")):
        tip = ai_plan_risk(cfg.get(key))
        if not tip:
            continue
        if tip in tips:
            tips[tip] = tips[tip] + " / " + label
        else:
            tips[tip] = label
            order.append(tip)
    return ["【%s】%s" % (tips[t], t) for t in order]


def ai_save_config(cfg):
    """保存全局 AI/LLM 配置：落盘 ai_config.json + 重置客户端单例 + 同步给字幕引擎。

    只保留默认 schema 内的键（避免界面写入杂字段）。返回清洗后的配置 dict。
    v1.11.0 起含两条通道（A 工具箱 / B 引擎）与 ASR、AI 校准参数；保存后统一
    把接口 B 注入字幕引擎、把 ASR 注入引擎转录配置。
    v1.16.5（2026-10-01）：保存前先过一次「设置自动匹配」——端点是火山 Token
    Plan 而模型不在套餐内时自动换成套餐模型、输入/输出预算按模型能力夹回。
    这样「设置里写错的组合」在落盘那一刻就被纠正，校准不会再撞
    404 UnsupportedModel → 换端点 → 401 这条死路。修正说明不混进配置，
    单独经 `ai_last_auto_notes()` 回传界面（保存后取用）。
    """
    mod = ai_mod()
    clean = dict(getattr(mod, "DEFAULT_CONFIG", {}))
    for k in list(clean.keys()):
        if k in cfg and cfg[k] is not None:
            clean[k] = cfg[k]
    # —— 设置自动匹配：把错配的「端点 ↔ 模型 / 预算」纠正后再落盘 ——
    auto_notes = []
    try:
        clean, auto_notes = mod.match_settings(clean)
    except Exception:  # noqa: BLE001
        auto_notes = []          # 匹配失败不该挡住保存，按原值落盘
    mod.save_config(clean)
    try:
        mod.reset_clients()     # 强制下次调用重建客户端（两条通道一起丢）
    except Exception:
        pass
    try:
        from core.shared.vcsettings import apply_global_llm_to_engine
        apply_global_llm_to_engine(clean)
    except Exception:
        pass
    try:
        # TODO(A2)：asr 域拆入 core/asr 后改为 from core.asr import ...
        from video_toolbox import apply_asr_to_engine
        apply_asr_to_engine(clean)
    except Exception:
        pass
    # AI 托管（harness）实时同步：设置页一保存就把 provider 路由/凭据重写进
    # DSH_HOME——headless 下次运行拿新值，已在跑的交互控制台经 HMR 热加载。
    # （v2.3.0：旧实现只在跑任务时才同步，用户切换账号后控制台仍在调用旧 API）
    try:
        import harness_bridge as _hb
        _hb.sync_provider_config()
    except Exception:
        pass
    _AI_LAST_AUTO_NOTES.clear()
    _AI_LAST_AUTO_NOTES.extend(auto_notes)
    return clean


#: 最近一次「设置自动匹配」的说明（界面保存后取用，亮给用户看）
_AI_LAST_AUTO_NOTES = []


def ai_last_auto_notes():
    """取最近一次保存时「设置自动匹配」做了哪些修正（列表，可能为空）。"""
    return list(_AI_LAST_AUTO_NOTES)


def ai_test_connection(cfg=None, channel="a"):
    """连通性自检：返回 (是否成功, 说明)。用传入配置或已保存配置。

    v1.12.0 起单通道（channel 参数保留兼容，忽略）。
    v1.16.5：测试前先跑「设置自动匹配」并把修正结果跟原文一起回传，避免
    用户拿一份错配的配置反复测、反复看到同一句英文报错。
    """
    mod = ai_mod()
    _notes = []
    if cfg is not None:
        cfg, _notes = ai_match_settings(cfg)
    probe = ai_save_config(cfg) if cfg is not None else None
    if probe is not None:
        _notes = ai_last_auto_notes() or _notes
    try:
        client = mod.AIClient(probe) if probe is not None else mod.get_client()
        reply = client.chat_text("收到请只回复两个字：正常", max_tokens=512)
        tip = ("；设置自动匹配：" + "；".join(_notes)) if _notes else ""
        return True, (reply or "(空回复)") + \
            f"（全局 AI，模型 {client.model}{tip}）"
    except Exception as e:  # noqa: BLE001
        if _notes:
            return False, str(e) + "\n（已尝试设置自动匹配：" + \
                "；".join(_notes) + "）"
        return False, str(e)


def ai_test_asr(cfg=None):
    """ASR（语音识别）配置自检：返回 (是否成功, 说明)。"""
    try:
        return ai_mod().asr_test_connection(cfg if cfg is not None else ai_load_config())
    except Exception as e:  # noqa: BLE001
        return False, str(e)




__all__ = [
    "AI_CONFIG_PATH",
    "ai_mod",
    "ai_detect_language",
    "ai_load_config",
    "ai_match_settings",
    "ai_save_config",
    "ai_plan_risk",
    "ai_plan_risks",
    "ai_last_auto_notes",
    "ai_test_connection",
    "ai_test_asr",
]
