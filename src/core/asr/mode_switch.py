# -*- coding: utf-8 -*-
# @version 3.3.1
"""ASR 模式切换（本地 / 云端）：写配置 → 注入引擎 → 体检真实生效。

2026-11-22 用户需求：转录页那个下拉原先只有「默认（必剪已失效）/ ASR」两项，
点「ASR」只是"按设置页当前模式再应用一次"——既看不出用的是**电脑里的模型**
还是**服务商提供的接口**，也改不了模式（要先去设置页改，再回来重选）。现在
下拉拆成「本地 / 云端」两项，点哪项就真正切到哪套后端：

  1. 把 ``asr_mode``（``local`` / ``service``）写进 ``data/ai_config.json``；
  2. 调 :func:`core.asr.engine_config.apply_asr_to_engine` 落到引擎「转录配置」：
     · local   → ``FasterWhisper ✨``（模型名/目录一并写进 FasterWhisper 槽）
     · service → ``Whisper [API] ✨``（地址/密钥/模型/提示词一并写进 WhisperAPI 槽）
  3. 回一份**体检结果**（本地权重能否真的加载 / 云端接口是否配全），界面据此
     提示——避免"文字上切了、实际还在用旧通道"。

本地模型名留空时自动挑一个工具箱内**完整可加载**的模型（优先 large-v3），
保证「本地」点下去即可用，而不是等用户先去设置页补一格。
"""
from core.asr.engine_config import apply_asr_to_engine
from core.shared.ai import ai_load_config, ai_mod

MODE_LOCAL = "local"
MODE_SERVICE = "service"

__all__ = [
    "MODE_LOCAL",
    "MODE_SERVICE",
    "asr_mode_of",
    "set_asr_mode",
    "asr_mode_status",
]


def _normalize_mode(mode) -> str:
    """任意写法 → ``local`` / ``service``（默认 service，与 asr_config 同口径）。"""
    return MODE_LOCAL if str(mode or "").strip().lower() in (
        "local", "本地", "本机") else MODE_SERVICE


def asr_mode_of(ai_cfg=None) -> str:
    """当前**已保存**的 ASR 模式：``local`` / ``service``。"""
    try:
        ac = ai_mod().asr_config(ai_cfg or ai_load_config())
        return MODE_LOCAL if ac.get("mode") == MODE_LOCAL else MODE_SERVICE
    except Exception:  # noqa: BLE001 - 读不到按云端（历史默认）
        return MODE_SERVICE


def _fill_local_model(cfg: dict) -> bool:
    """本地模式没填模型名/目录时，自动挑一个工具箱内可加载的模型。

    返回是否改动了 cfg（改动即需要落盘，否则引擎那边只会拿到空的 FasterWhisper
    槽，转录时才报"模型缺失"）。故意**只挑完整权重**（config/model/tokenizer/
    词表齐全），半截目录不会被当成可用模型。
    """
    if str(cfg.get("asr_local_model") or "").strip() \
            or str(cfg.get("asr_local_model_dir") or "").strip():
        return False
    try:
        from features.transcribe import asr_local_paths as paths
        avail = paths.list_available_models()
    except Exception:  # noqa: BLE001
        avail = []
    if not avail:
        return False
    cfg["asr_local_model"] = "large-v3" if "large-v3" in avail else avail[0]
    return True


def set_asr_mode(mode, ai_cfg=None):
    """切换并**真正生效**：写 ai_config + 注入引擎转录配置。

    返回 ``(是否成功, 说明)``。说明里带具体落点（本地模型 / 云端端点），
    便于界面直接显示"现在到底用的是什么"。
    """
    mode = _normalize_mode(mode)
    try:
        cfg = dict(ai_cfg or ai_mod().load_config())
    except Exception as e:  # noqa: BLE001
        return False, "读取 AI 配置失败：%s" % e

    changed = False
    if mode == MODE_LOCAL and _fill_local_model(cfg):
        changed = True
    if str(cfg.get("asr_mode") or "").strip().lower() != mode:
        cfg["asr_mode"] = mode
        changed = True
    if changed:
        try:
            ai_mod().save_config(cfg)
        except Exception as e:  # noqa: BLE001
            return False, "写入 ASR 模式失败：%s" % e

    ok, detail = apply_asr_to_engine(cfg)
    try:
        from core.shared.log import _vc_log
        _vc_log("[ASR] 模式 → %s（%s）%s"
                % ("本地" if mode == MODE_LOCAL else "云端",
                   detail, "" if ok else " 注入失败"))
    except Exception:  # noqa: BLE001
        pass
    return ok, detail


def asr_mode_status(mode=None, ai_cfg=None) -> dict:
    """体检当前模式**能不能真的跑**：``{mode, ready, detail, hint}``。

    · detail：现在实际会用到的模型/端点（界面 tooltip 直接显示，一眼看出
      "切的到底是不是我选的那套"）；
    · hint  ：没配好时的可操作指引（缺什么、去哪个设置卡片补）。
    """
    mode = _normalize_mode(mode if mode is not None else asr_mode_of(ai_cfg))
    out = {"mode": mode, "ready": False, "detail": "", "hint": ""}
    try:
        ac = ai_mod().asr_config(ai_cfg or ai_load_config())
    except Exception as e:  # noqa: BLE001
        out["hint"] = "读取 ASR 配置失败：%s" % e
        return out

    if mode == MODE_LOCAL:
        model = str(ac.get("local_model") or "").strip()
        explicit = str(ac.get("local_model_dir") or "").strip()
        name = model or "large-v3"
        out["detail"] = "faster-whisper · %s（本机运行）" % name
        try:
            from features.transcribe import asr_local_paths as paths
            model_dir = paths.resolve_model_dir(name, explicit)
        except Exception as e:  # noqa: BLE001
            first = str(e).splitlines()[0] if str(e) else "模型不可用"
            out["hint"] = (first + "\n请到 设置 → ASR 语音识别 → 本地独立模型 "
                           "填模型名或选一个含完整权重的目录")
            return out
        out["ready"] = True
        out["detail"] = "faster-whisper · %s（%s）" % (name, model_dir)
        return out

    base = str(ac.get("base_url") or "").strip()
    key = str(ac.get("api_key") or "").strip()
    model = str(ac.get("model") or "").strip()
    host = base.split("://", 1)[-1].split("/", 1)[0] if base else ""
    out["detail"] = "云端接口 · %s%s" % (
        model or "(未填模型名)", (" @ " + host) if host else "")
    miss = []
    if not base:
        miss.append("接口地址")
    if not key:
        miss.append("密钥")
    if miss:
        out["hint"] = ("云端接口还没配全（缺 %s）\n"
                       "请到 设置 → ASR 语音识别 填好后点「保存并应用」"
                       "（只填不保存不生效）" % "、".join(miss))
        return out
    out["ready"] = True
    return out
