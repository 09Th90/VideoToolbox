# -*- coding: utf-8 -*-
# @version 3.3.1
"""AI 校准入口（calib_ai_chat / calib_web_proxy / calib_ai_run）+ 同步开关。

v2.3.1 拆分工程 · 自 video_toolbox.py 原样搬入。
依赖：core.shared；calib_web_proxy 对 asr 域 http_proxies_for 的引用按域间
规则走函数内延迟 import（calibrate→asr 运行时耦合，A4 收口时评估）。
"""

from core.shared.paths import APP_DIR
from core.shared.runtime import system_python
from core.shared.ai import ai_plan_risks

import os
import time

from core.shared.ai import ai_load_config, ai_mod
from core.shared.decision import decision_client
from core.shared.config import load_config, save_config


def calib_ai_chat(prompt, system=None, max_tokens=None, on_reasoning=None,
                  member=None):
    """AI 校准的 LLM 回调：走全局 AI 单通道（v1.12.0 起不再选通道）。

    on_reasoning（v1.14.2）：思考链上报回调，透传给 AIClient，把推理模型返回的
    思考过程（reasoning_content）实时交给校准日志显示。

    思考控制（2026-09-20）：读配置 `calib_thinking` / `calib_reasoning_effort`
    （设置页「AI 校准」卡片），随请求体 thinking / reasoning_effort 下发；
    端点不支持时 ai_client 会自动去掉参数重试，不影响可用性。

    member（v1.16.1，Agent 集群）：传入集群成员 dict 时改用该成员自己的
    base_url / api_key / model 建客户端（未填字段回落全局配置）；None = 全局通道。
    """
    ai = ai_load_config()
    thinking = bool(ai.get("calib_thinking", True))
    effort = str(ai.get("calib_reasoning_effort") or "high").strip().lower()
    client = ai_mod().member_client(member, ai) if member else ai_mod().get_client()
    # 过程事件（重试 / 超时 / 端点自愈）接到当前校准的日志上：这些消息以前只走
    # ai_client 的 logger，而全项目没配过 logging ⇒ 完全不可见。表现为「一块
    # 校准卡在重试链里拖到 7 分钟，界面一片空白」（2026-10-05 实测）。
    try:
        client.on_event = _CALIB_EVENT_SINK[0] if _CALIB_EVENT_SINK else None
    except Exception:  # noqa: BLE001
        pass
    # 开发版观测（2026-11-24）：请求/思考链/响应成对事件；telemetry 未启用时
    # no-op。思考流仅在调用方本就传了 on_reasoning 时包装累积（不改变流式行为），
    # 收尾一次性发射，避免逐 chunk 事件泛滥。
    from features.calibrate import telemetry as _tel  # noqa: PLC0415
    _t0 = time.time()
    _reason_parts = []
    _sink = on_reasoning
    if on_reasoning is not None:
        def _sink(txt):
            _reason_parts.append(str(txt))
            on_reasoning(txt)
    _tel.emit("ai", "llm_request", prompt=prompt, system=system,
              max_tokens=int(max_tokens or 8192), thinking=thinking,
              effort=effort if thinking else None,
              member=(member or {}).get("name") if isinstance(member, dict) else None,
              model=(member or {}).get("model") if isinstance(member, dict) else None)
    try:
        reply = client.chat_text(prompt, system=system,
                                 max_tokens=int(max_tokens or 8192),
                                 on_reasoning=_sink,
                                 thinking=thinking,
                                 reasoning_effort=effort if thinking else None)
    except Exception as _e:
        _tel.emit("ai", "llm_error", error=str(_e)[:2000],
                  elapsed_ms=int((time.time() - _t0) * 1000))
        raise
    if _reason_parts:
        _tel.emit("ai", "reasoning", text="".join(_reason_parts))
    _tel.emit("ai", "llm_response", text=reply,
              elapsed_ms=int((time.time() - _t0) * 1000))
    return reply


#: 当前校准运行的「过程事件」上报槽（0/1 元素）：calib_ai_run 起止时设置/清空，
#: calib_ai_chat 每次调用时把 ai_client 的重试/超时事件接到校准日志。
_CALIB_EVENT_SINK: list = []


def _calib_event_sink(log):
    """把 ai_client 的过程事件转成校准日志的一行（level 默认 err=红字）。"""
    def _cb(msg, level="err"):
        try:
            log("  · " + str(msg), level)
        except TypeError:
            log("  · " + str(msg))
    return _cb


def calib_web_proxy():
    """校准 Agent 联网查证的出网代理（返回 calib_web_agent 认的 proxy 快照）。

    走内置 mihomo（`ytdlp_proxy_args` 已带缓存与 204 硬校验）；拿不到代理时
    返回 None=跟随系统代理，绝不强制直连（国内直连 Bing 常无结果）。
    """
    try:
        from core.shared.proxy import ytdlp_proxy_args
        args = ytdlp_proxy_args()
        if args and len(args) >= 2 and args[1]:
            u = args[1]
            return {"http": u, "https": u}
    except Exception:  # noqa: BLE001
        pass
    return None


def calib_ai_run(src, out=None, report=None, mode_flag="", fix_en=False,
                 log=None, round_no=1, cancel=None, workdir=None,
                 style=None, resume_from=None, prev_changes=None, title=None,
                 media_path=None, task_instruction=None):
    """跑一轮 Agent 级 AI 校准，返回结果 dict（见 calib_ai_agent.calibrate）。

    style：None=读配置 `calib_style` 三档——`""`/`term`/`auto` 自动（默认：机翻腔
           hot==0 双语片自动改派整句重写，否则术语级）/ `term-locked` 锁定术语级
           （只替换名词，绝不改派）/ `rewrite` 整句重写（针对机翻腔、跨 cue 断句的片源）。
    resume_from：起点文件。长片源「再次校准」应传上一轮产物：这样会**跳过脚本基线**
           直接在上轮成果上继续；否则从原始源重跑会把上轮已采纳的改动丢掉。
    prev_changes：上轮采纳明细 [(num, old, new), ...]，注入提示词禁止回退。
    concurrency：逐块 LLM 调用并发路数，None=读配置 `calib_concurrency`（默认 1＝串行）。

    web（2026-09-20 校准 Agent 联网）：`calib_web_enabled` 开启时挂联网查证工具
    （web_search/web_fetch），出网走内置代理；失败降级为「查不到不改」，不打断主流程。

    think_rounds（v1.16.1）：读配置 `calib_think_rounds`——每块「思考→联网查证→
    再思考」的往返轮数上限，0 = 关闭（不限，内部 32 轮安全上限）。
    cluster（v1.16.1）：读配置 `calib_cluster_enabled` / `calib_cluster_members` /
    `calib_cluster_rounds`，开启后走多智能体协作（提议 Agent + 评审 Agent）。

    title（v1.16.1）：原始视频标题，传给片源档案作**改写新标题的参考基准**；
    None = 由 Agent 自动探测（字幕同目录 `视频信息.txt` 的「标题:」→ 视频文件名）。

    media_path（2026-10-12 音画证据）：源视频/音频路径。`calib_media_enabled`
    开启且路径可用时，装配 calib_media_agent 的音画证据工具（裁音频重转写 /
    抽帧视觉描述），Agent 可对疑似误听与丢弃候选请求证据；无路径或工具装配
    失败按离线继续，行为与旧版完全一致。
    """
    import features.calibrate.calib_ai_agent as _agent
    ai = ai_load_config()
    # 设置自动匹配（2026-10-01 v2）：端点↔模型、预算↔模型能力一次算清，
    # 走 ai_client.match_settings() 这一份权威实现（设置页「自动匹配」按钮、
    # 保存落盘、校准入口三处共用同一套规则，不再各写一遍）。
    # 说明统一走校准日志亮给用户（logger 在打包运行时不落界面）。
    # 客户端发送前还会再钳一次 max_tokens，两层兜底。
    _auto_notes = []
    try:
        ai, _auto_notes = ai_mod().match_settings(ai)
    except Exception:  # noqa: BLE001
        pass
    if _auto_notes and log:
        for _n in _auto_notes:
            try:
                log("· 设置自动匹配：" + _n, "info")
            except TypeError:
                log("· 设置自动匹配：" + _n)
    # 订阅套餐端点：**允许接入，只做提示**（2026-10-05 产品口径）。校准是典型的
    # 批量非交互调用，正好落在多数套餐条款的禁止范围内，故每轮校准都在日志里
    # 点名一次，风险由用户自负。只写日志，不拦、不改地址与模型。
    for _r in ai_plan_risks(ai):
        if not log:
            break
        try:
            log("· " + _r, "err")
        except TypeError:
            log("· " + _r)
    # 2026-11-24 自动路由接线：calibrate 的 style=None 哨兵＝「未锁定，允许按片源
    # 特征自动改派 rewrite」（见 calib_ai_agent.calibrate）。配置三档（设置页下拉）：
    #   "" / "auto" / 旧值 "term" → 未锁定 → 传 None（hot==0 双语片自动切 rewrite）；
    #   "term-locked" → 显式锁定 term（calib_ai_agent 内归一为 term，绝不改派）；
    #   "rewrite"       → 显式锁定 rewrite。调用方显式传入 style 时优先尊重。
    if style is None:
        _cfg_style = str(ai.get("calib_style") or "").strip().lower()
        style = None if _cfg_style in ("", "term", "auto") else _cfg_style
    # 片源模式 -> 作品名：联网查证据此做「站内优先检索」
    # （PRTS / BWIKI / 终末地 Wiki / 库街区 / 森空岛，见 calib_web_agent.WORK_SITES）。
    # 识别不出时为空，Agent 会退回通用 Bing 检索。
    _MODE_WORK = {
        "bi": "鸣潮", "wuwa-ja": "鸣潮", "wuwa-ko": "鸣潮", "wwoc": "鸣潮", "react": "鸣潮",
        "endo-ja": "终末地", "endo": "终末地", "endo-bi": "终末地", "endo-ko": "终末地",
        "ak": "明日方舟", "ak-ko": "明日方舟", "ak-ja": "明日方舟",
        "pgr": "战双", "pgr-en": "战双", "pgr-ja": "战双",
        "limbus": "边狱巴士",
    }
    web = None
    if bool(ai.get("calib_web_enabled", False)):
        try:
            import features.calibrate.calib_web_agent as _web
            _work = _MODE_WORK.get(_agent.MODE_KEY.get(mode_flag, "bi"), "")
            web = _web.make_tools(proxy=calib_web_proxy, log=log, work=_work)
            if _work and log:
                try:
                    log(f"  · 联网查证预置作品：{_work}", "dim")
                except TypeError:
                    log(f"  · 联网查证预置作品：{_work}")
        except Exception as e:  # noqa: BLE001
            web = None
            if log:
                try:
                    log(f"  · 联网查证工具初始化失败（按离线继续）：{e}", "err")
                except TypeError:
                    log(f"  · 联网查证工具初始化失败（按离线继续）：{e}")

    # 音画证据（2026-10-12）：calib_media_enabled 开启且传入源媒体路径时装配。
    # 只支持 OpenAI 兼容 ASR 端点（重转写）；视觉走全局视觉通道。任何一步
    # 缺失都按「无音画证据」继续，不打断校准主流程。
    media = None
    if bool(ai.get("calib_media_enabled", False)) and media_path:
        try:
            import features.calibrate.calib_media_agent as _media
            _asr = ai_mod().asr_config(ai)
            _asr["protocol"] = ai_mod().resolve_asr_protocol(_asr)
            _ff = ""
            try:
                from core.download.deps import ensure_ffmpeg
                _ff, _fp = ensure_ffmpeg()
            except Exception:  # noqa: BLE001
                _ff = ""
            _vision = None
            try:
                _vision = ai_mod().get_client().chat_vision
            except Exception:  # noqa: BLE001
                _vision = None
            media = _media.make_tools(media_path, asr=_asr, vision=_vision,
                                      ffmpeg=_ff or None, log=log)
            if log:
                try:
                    log("  · 音画证据已装配（音频重转写 + 抽帧视觉；"
                        + ("视觉通道就绪" if _vision else "视觉通道不可用")
                        + "）", "dim")
                except TypeError:
                    pass
        except Exception as e:  # noqa: BLE001
            media = None
            if log:
                try:
                    log(f"  · 音画证据工具初始化失败（按离线继续）：{e}", "err")
                except TypeError:
                    log(f"  · 音画证据工具初始化失败（按离线继续）：{e}")

    def _member_chat(member):
        """按集群成员产出 chat 回调（成员走自己的端点/密钥/模型）。"""
        def _call(prompt, system=None, max_tokens=None, on_reasoning=None):
            return calib_ai_chat(prompt, system=system, max_tokens=max_tokens,
                                 on_reasoning=on_reasoning, member=member)
        return _call

    cluster = None
    if bool(ai.get("calib_cluster_enabled", False)):
        cluster = {"enabled": True,
                   "members": ai_mod().cluster_members(ai),
                   "rounds": max(1, int(ai.get("calib_cluster_rounds") or 1))}

    _CALIB_EVENT_SINK[:] = [_calib_event_sink(log)] if log else []
    # 开发版观测（2026-11-24）：AI 校准会话包裹 + 配置快照；未启用时 no-op。
    from features.calibrate import telemetry as _tel  # noqa: PLC0415
    _tel.start_session("ai-calibrate", input=src, out=out, mode=mode_flag,
                       round=round_no, style=style, resume_from=resume_from)
    _tel.emit("workflow", "stage", stage="ai_config",
              model=ai.get("model"), base_url=ai.get("base_url"),
              web=bool(web), media=bool(media), cluster=bool(cluster),
              think_rounds=int(ai.get("calib_think_rounds") or 0),
              concurrency=int(ai.get("calib_concurrency") or 1))
    _t0 = time.time()
    try:
        result = _agent.calibrate(
            src, out=out, report=report, mode_flag=mode_flag, fix_en=fix_en,
            script=os.path.join(APP_DIR, "subtitle_calib_merged.py"),
            python=system_python(), log=log, chat=calib_ai_chat,
            chat_for_member=_member_chat, cluster=cluster,
            think_rounds=int(ai.get("calib_think_rounds") or 0),
            orig_title=title, decision_client=decision_client(ai),
            chunk_cues=int(ai.get("calib_chunk_cues") or 400),
            max_chars=int(ai.get("calib_max_chars") or 60000),
            max_tokens=int(ai.get("calib_max_tokens") or 65536),
            context_tokens=int(ai.get("calib_context_tokens") or 1000000),
            concurrency=int(ai.get("calib_concurrency") or 1),
            round_no=round_no, cancel=cancel, workdir=workdir,
            style=style, resume_from=resume_from, prev_changes=prev_changes,
            sentence_aware=bool(ai.get("calib_sentence_aware", True)),
            strict_width=bool(ai.get("calib_strict_width", False)),
            web=web, media=media, preflight=True,
            task_instruction=task_instruction)
        _tel.end_session(ok=result.get("ok"), error=result.get("error") or None,
                         script_changes=result.get("script_changes"),
                         ai_changes=result.get("ai_changes"),
                         rejected=result.get("rejected"),
                         elapsed_ms=int((time.time() - _t0) * 1000))
        return result
    except Exception as _e:
        _tel.end_session(ok=False, error=str(_e)[:2000])
        raise
    finally:
        # 事件槽用完即清：否则跑完的校准日志回调会挂在全局客户端上，
        # 之后别的调用（视觉识别、接口测试）出的重试消息会写进一份已经结束的日志。
        _CALIB_EVENT_SINK.clear()
        try:
            ai_mod().get_client().on_event = None
        except Exception:  # noqa: BLE001
            pass


# ========== 校准知识多用户同步开关（持久化在 config.json） ==========
def calib_sync_enabled():
    """是否启用校准知识自动同步（默认启用；VT_NO_CALIB_SYNC 仍可强制关闭）。"""
    if os.environ.get("VT_NO_CALIB_SYNC"):
        return False
    return bool(load_config().get("calib_sync_enabled", True))


def set_calib_sync_enabled(flag):
    cfg = load_config()
    cfg["calib_sync_enabled"] = bool(flag)
    save_config(cfg)
# =============================

__all__ = [
    "calib_ai_chat",
    "calib_web_proxy",
    "calib_ai_run",
    "calib_sync_enabled",
    "set_calib_sync_enabled",
    "_calib_event_sink",
    # 原地改写的接线列表（[:] / clear()，对象身份不变）：engine 别名经
    # 两级 import * 依赖它，pack 门禁断言已接线（解耦时漏导出致回归）。
    "_CALIB_EVENT_SINK",
]
