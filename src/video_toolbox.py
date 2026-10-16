#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# @version 2.3.1
"""
视频工具箱 v1.12.0（单文件整合版）
==================================================
v1.15.6：**ASR 新增「百炼原生」协议**（Qwen-Audio-3.0-ASR-Flash 出字幕的
  正路）：实测（2026-09-20）qwen-audio-3.0-asr-flash 的官方接口是
  `POST {域名}/api/v1/services/aigc/multimodal-generation/generation`
  （音频 base64 Data URL + parameters.format/sample_rate，响应在
  output.sentence.text 且 words[] 带毫秒词级时间轴），而程序一直按
  compatible-mode 的 chat/completions 提交 → **恒回 HTTP 400 空体 `{}`**，
  被误判成「模型不可用/实例没部署」。同一模型、同一份音频换端点即 200。
  落地：① `ASR_PROTOCOLS` 增加 `dashscope_native` + 界面下拉项；
  ② `is_dashscope_native_asr()` 识别 qwen-audio*asr*（非 realtime/filetrans），
  `_infer_asr_protocol` 与 `asr_protocol_fix` 命中即改走原生协议；
  ③ `_asr_dashscope_native_submit()` + `_asr_native_output()`（词级时间轴经
  `_asr_words_to_segments` 聚合）；④ chat_audio 拿到空体 400/500 时
  `_asr_retry_native()` 兜一次（Fun-ASR-Flash 等官方同挂原生端点）。
  另：maas 专属实例的 /models **不列 ASR 模型**，测试连接不再按列表一票否决
  （tools/ai_client.py 改主动探测，提示不再误报「实例没有可用 ASR 模型」）。
v1.15.3：ASR 协议纠偏补「反向守卫」——「接口协议」显式选了「百炼实时
  （WebSocket）」但模型**不是**实时模型（名里没有 realtime / -rt- / streaming）
  时，原先会拿文件识别模型直接去连实时端点，服务端只回
  `InvalidParameter url error, please check url!`——用户看不懂，而且 task-failed
  属确定性错误，重试与降级都救不回（实测：专属实例上把协议留成「百炼实时」、
  模型换成 `qwen-audio-3.0-asr-flash-filetrans` 即触发）。现在 `asr_protocol_fix()`
  按 auto 推断把它改走文件识别协议并写日志；真实时模型完全不受影响。
  同时把该服务端报错翻译成可操作提示（点名实时模型的命名特征 + 引导改协议）。
v1.12.2：校准知识收集通道调整（用户拍板）——
  ① 恢复 GitHub 整文件同步通道（_gh_* / sync_calib_to_github / _pull_and_merge）：
  用于收集不同使用者在校准过程中产生的增量内容；条目级三方合并保证
  多用户互不覆盖、收敛到并集；
  ② 所有上传全自动、隐藏在后台：校准 learn 实时写本地学习库，退出程序时
  派生隐藏子进程自动推送 GitHub（界面不提供也不显示任何上传入口）；
  ③ 连接参数统一使用内置 github_proxy.yaml 的 vt-github 段
  （owner/repo/branch/api/token/files）；直连失败回退同文件的代理规则；
  ④ 程序界面仅保留「更新」选项（启动自动 + 手动立即更新）；
  ⑤ v1.12.1 的本地增量镜像通道（kb-sync/kb-push + baseline/inbox）保留为
  可选增强：管理员用独立程序 kb_admin.exe 配了共享更新库时自动叠加启用。
v1.12.1：（已被 v1.12.2 部分取代）工具箱曾只保留「更新 + 上传增量」两动作、
  GitHub 通道全部移交独立程序；现按要求恢复 GitHub 收集通道。
v1.12.0：翻译链路全面修缮（配套 site-packages 里的引擎改动，均由
  src\apply_vc_official.py 归档可复现）：① 谷歌翻译改抓 Chrome 内置翻译同源
  免费接口（translate_a/t?client=dict-chrome-ex）并加全局请求节流（≥0.12s/次，
  约 8 QPS）——官方旧端点 translate.google.com/m 已被 302 到验证码页；
  ② 必应翻译换 translatetext 端点取 token（官方匿名 token 方案已失效）；
  ③ 翻译基类对失败译文（ERROR / 空 / xxx||ERROR）不写缓存，块级失败可重试；
  ④ LLM 翻译并发上限 `_LLM_THREAD_CAP=5`（免费/共享模型速率限制很紧，50 并发
  会 429 刷屏）与限流处理；⑤ 任务取消立即停掉翻译/优化线程池（原先取消后
  仍把剩余批次跑完）；⑥ 「启用 AI」关闭时，翻译兜底与引擎 LLM 注入都不介入。
v1.11.0：① LLM 拆分为**两条各自独立的 API 通道**——接口 A（工具箱自身：
  标题/语言识别与视觉，Anthropic 兼容）与接口 B（字幕引擎优化/翻译/拆分与
  AI 校准，OpenAI 兼容），地址、密钥、模型都能分别填写，接口 B 密钥留空则
  沿用 A（旧配置平滑迁移）；② 新增全局 ASR（语音识别）配置：可接自有 ASR
  服务（OpenAI 兼容 /audio/transcriptions）或本地独立 faster-whisper 模型
  （模型名 + 模型目录自定义），保存即写入引擎「转录配置」——服务模式切到
  Whisper [API]，本地模式切到 FasterWhisper 并由 vc_asr_patch_apply() 覆盖
  模型名/目录；③ 新增 Agent 级 AI 校准入口 calib_ai_run（实现见
  src\\calib_ai_agent.py）；④ 修复启动同步长期静默失败：_pull_and_merge 调用
  的 _read_sync_text / _atomic_write 此前**未定义**（日志反复出现
  「启动同步异常（忽略）: name '_read_sync_text' is not defined」）；
  ⑤ vc_lazy_cache_patch()：引擎在模块级建 5 个 diskcache 库（每个约 0.9s）
  改为惰性代理，进入「字幕处理」页的等待从数秒降到亚秒级。
v1.10.5：校准脚本升级为对象级知识库版本（ENTITIES 对象层 + learn 学习系统）；
  校准界面模式列表与脚本实际支持的全部 12 种模式对齐，移除脚本已删除的
  「长句拆两行（--layout）」开关；新增退出时自动同步校准脚本到 GitHub
  （sync_calib_on_exit，挂接 QApplication.aboutToQuit）：静默后台、不阻塞退出、
  不弹窗，直连失败回退内置 mihomo 代理（仅 api.github.com），日志见
  logs 目录下的 calib_sync.log。
v1.10.4：界面与设置整合——左侧导航宽度按「最长项文字 + 2 个字符」自适应
  （不再固定 322px）；新增导航底部「设置」页，工具设置与字幕引擎设置统一
  入口（原「字幕处理」页右下「引擎设置…」对话框并入）；跨屏拖拽按相对位置
  平滑移动（不再因两屏缩放比不同而瞬移）；DPI 取整策略改为 PassThrough，
  100%/125%/150%/200% 缩放比表现一致；字幕引擎界面后台预热，消除首次进入
  「字幕处理」页的数秒卡顿。
v1.10.2：字幕引擎改为内嵌——不再唤起独立窗口，「字幕处理」页直接呈现引擎
  界面（品牌水印/捐助入口在嵌入层隐藏，engine_ui_brand_patch 中性化用户可见
  文案；许可与来源声明保留在 docs 目录下）；界面布局重做：页面「标题区固定 +
  内容滚动」，窗口尺寸按屏幕自适应，高分屏矢量渲染；随包 wheel 与独立进程
  唤起链路（launch_vc_gui / vc_install_from_wheel）移除。
v1.10.1：① 界面整体重写为 Fluent 风格（FluentWindow +
  左侧导航 + 卡片分组，PySide6 + PySide6-Fluent-Widgets），原 tkinter 界面退役；
  ② 移除「B站投稿」板块及其 Playwright 引擎（tools/uploader_src、tools/ms-playwright
  不再随包分发），AI 客户端独立为 tools/ai_client.py 供字幕语言识别继续使用；
  ③ 修复：直接运行构建产物时找不到 tools/python 的问题（向上逐级查找）。
v1.10.0：字幕链路整体替换为第三方开源字幕引擎（GPL-3.0 组件）——
  语音转录 / 字幕优化 / 翻译 / 配音 / 合成全部交由引擎承担；
  原自带 ASR 实现（src\asr_subtitle_worker.py + tools\asr_model 模型引导）已移除；
  「字幕校准」页仍调用自建术语库脚本 subtitle_calib_merged.py 做终校。
v1.9.0：接入全局 AI（智谱 GLM：glm-4.7-flash 文本 + glm-4.6v-flash 视觉，
  配置 data\ai_config.json）；字幕语言由 AI 识别标题语言自动匹配（下载侧）。
目录结构（v1.7 按功能划分，程序目录顶层只留主程序）：
  视频工具箱.exe | tools/ 运行时 | src/ 源代码 | docs/ 文档
  data/ 用户数据（下载/配置/缓存/登录态/任务/分区缓存）| logs/ 日志
功能 1 - 视频下载：
  拖入链接（.url 快捷方式 / 含链接的 txt / 直接粘贴链接）
  -> 自定义保存位置（回车 = 上次使用的目录，长期记忆）
  -> 自动检测画质：仅 >=720p、同分辨率只保留最大文件、优先 60fps
  -> 下载并合并为 mp4（音频始终最高质量）
  -> 每个视频打包到独立文件夹：视频 + 封面.jpg（1280x720）+ 视频信息.txt

功能 2 - 音视频智能合并（整合自 merge_audio_video v3.2）：
  扫描文件夹，按文件名/时长智能配对 mp4 + m4a/weba + srt/ass，合并为完整视频
  m4a -> 直接封装 | weba -> 转 AAC | SRT -> 软字幕 | ASS -> 烧录/MKV/忽略

首次运行自动在脚本旁 tools\\ 目录下载 yt-dlp 与 ffmpeg（仅一次）
"""

import os
import sys
import json
import glob
import shutil
import base64
import subprocess
import urllib.request
import zipfile
import re
import time
import atexit
import threading
import tempfile
import codecs
from datetime import datetime
from pathlib import Path
# ========== facade：核心域再导出（v2.3.1 拆分工程） ==========
# video_toolbox.py 原为 9221 行单体；现按域拆入 src\core/，本文件只剩：
#   ① 下列显式再导出（调用方 import video_toolbox 一根线不变）；
#   ② 尚未拆走的域代码（asr/translate/calibrate/download 剩余部分 + main）。
# 铁律：新增/删除公开符号必须同步 scripts/dev/_selftest_core_api.py 的
# DOMAIN_MAP 与 facade 清单——漏一个立刻被接口测试抓红。
from core.shared import *  # noqa: F401,F403 —— 常量（APP_DIR/MIHOMO_*/TEXT_ENCODINGS/...）
from core.shared import (  # shared 域公开函数（DOMAIN_MAP「shared」全集，显式列=契约）
    decode_bytes_any, read_text_any, write_text_utf8, decode_process_output,
    configure_stdio_utf8, app_icon_path, system_python, worker_subprocess_env,
    run_process, popen_process, kill_process_tree, sleep_cancellable,
    ensure_builtin_proxy, ytdlp_proxy_args, translate_session_proxies,
    proxy_status, get_proxy_yaml, set_proxy_yaml, vc_importable,
    vc_missing_deps, vc_env_ready, vc_state, vc_data_dir,
    vc_bundled_resource_dir, vc_redirect_paths, vc_settings_path,
    apply_global_llm_to_engine, load_config, save_config,
    get_saved_download_dir, set_saved_download_dir, ai_mod,
    ai_detect_language, ai_load_config, ai_match_settings, ai_plan_risk,
    ai_plan_risks, ai_save_config, ai_last_auto_notes, ai_test_connection,
    ai_test_asr, clean_path, proxy_group_now, proxy_node_delays,
    pick_best_proxy_node, proxy_lock_acquire, proxy_lock_release,
    # 注：data_root_info/set_data_root/prepare_runtime_env/sync_env_into/
    # engine_ui_brand_patch 五个 DOMAIN_MAP-shared 符号的函数体仍在本文件
    # 下方（依赖 asr/calibrate 未拆域），随 A2/A3 再搬；届时从这里补名，
    # _selftest_core_api 的 DOMAIN_MAP 覆盖校验会盯着。
)
from core.download import (  # download 域公开函数（DOMAIN_MAP「download」全集）
    ensure_ytdlp, ensure_ffmpeg, ensure_mpv_dll,
    extract_url, extract_web_url, ytdlp_sub_langs,
    ytdlp_prefer_hls, ytdlp_part_leftovers, ytdlp_error_retryable,
    ytdlp_err_brief, ytdlp_cookie_args,
    cookie_mode, cookie_browser, cookie_file, cookies_file_status,
    browser_cookie_probe, cookie_load_failure_reason,
    browser_user_data_dir, browser_exe_path, browser_app_bound_enabled,
    browser_cookie_diagnose, write_netscape_cookies,
    export_browser_cookies_via_cdp, invalidate_cookie_cache,
    fetch_info_json, parse_qualities, save_info_json,
    sanitize_folder_name, unique_folder,
    npe_engine_mode, npe_available, npe_proxy_url, npe_cookie_file,
    output_template, hls_alt_format, write_info_txt,
    make_cover_1280x720, probe_qualities, download_mode,
    get_duration, probe_audio_codec, calib_media_for_srt,
    scan_media, get_base_name, find_subtitle,
    smart_pair, merge_pair, merge_mode,
    format_size, format_time, open_folder,
)
from core.download import *  # noqa: F401,F403 —— download 域常量（URL_RE/MERGE_VIDEO_EXTS/YTDLP_*/CFG_*/COOKIE_*…）
from core.asr import (  # asr 域公开函数（DOMAIN_MAP「asr」A2a 部分）
    is_realtime_asr_family, is_dashscope_native_asr, asr_model_hard_guard,
    asr_strip_endpoint_tail, asr_protocol_fix, asr_base_guard,
    asr_model_guard, asr_protocol_of, asr_diarize_of, asr_separate_of,
    asr_examples, asr_examples_text, asr_instance_models,
    asr_missing_model_hint, is_domestic_ai_endpoint, http_proxies_for,
    vc_asr_protocol_patch, vc_asr_chunk_patch, asr_non_zh_en_ratio,
)
from core.asr import *  # noqa: F401,F403 —— asr 域常量与私有函数（_asr_*_submit/_infer_asr_protocol 等，* 经 __all__ 全量导出）
from core.shared import (  # 私有名（* 不导出下划线开头，必须显式列）
    _AI_LAST_AUTO_NOTES, _LOG_ERR_WORDS, _LOG_WARN_WORDS, _append_log,
    _vc_log, _mihomo_log, _is_self_exe, _VC_LEGACY_DIRS,
    _BOOTSTRAP_LOCK, _hide_console_kwargs,
)






# =============================




# ---------- 引擎「转录配置」：独立 ASR（自有服务 / 本地模型） ----------
# 引擎的转录模型是枚举项（B 接口 / J 接口 / Whisper [API] ✨ / FasterWhisper ✨），
# 这里把全局 ASR 配置映射过去：service → Whisper [API]（自有 ASR 服务），
# local → FasterWhisper ✨ + 独立模型名/目录。
#: FasterWhisper.Model 是枚举项，枚举外的自定义模型名写不进 settings.json
#: （读盘会被枚举校验拦下），只能靠 vc_asr_patch_apply() 在建任务时覆盖。
FW_MODEL_ENUM = ("tiny", "base", "small", "medium", "large-v1", "large-v2",
                 "large-v3", "large-v3-turbo")
#: 与 videocaptioner.core.entities.TranscribeModelEnum 的值保持一致
TM_WHISPER_API = "Whisper [API] ✨"
TM_FASTER_WHISPER = "FasterWhisper ✨"


def asr_local_override(ai_cfg=None):
    """本地独立 ASR 的覆盖参数：返回 (模型名, 模型目录)；非本地模式返回 None。"""
    try:
        ac = ai_mod().asr_config(ai_cfg or ai_load_config())
    except Exception:  # noqa: BLE001
        return None
    if ac.get("mode") != "local":
        return None
    model = str(ac.get("local_model") or "").strip()
    model_dir = str(ac.get("local_model_dir") or "").strip()
    if not model and not model_dir:
        return None
    return model, model_dir


def apply_asr_to_engine(ai_cfg=None):
    """把全局 ASR 配置写进引擎「转录配置」：转录模型 + WhisperAPI / FasterWhisper。

    service：WhisperAPI 槽写入自有 ASR 服务（地址/密钥/模型/提示词），转录模型切
      到 Whisper [API] ✨；local：转录模型切到 FasterWhisper ✨，模型名（枚举内）
      与模型目录写入 FasterWhisper 槽，枚举外的自定义模型由运行期补丁生效。
    返回 (是否成功, 说明)。
    """
    try:
        ac = ai_mod().asr_config(ai_cfg or ai_load_config())
        data = _vc_read_settings()
        changed = False
        want = TM_FASTER_WHISPER if ac["mode"] == "local" else TM_WHISPER_API
        tr = data.setdefault("Transcribe", {})
        if tr.get("TranscribeModel") != want:
            tr["TranscribeModel"] = want
            changed = True
        if ac["mode"] == "service":
            wa = data.setdefault("WhisperAPI", {})
            for k, v in (("WhisperApiBase", ac["base_url"]),
                         ("WhisperApiKey", ac["api_key"]),
                         ("WhisperApiModel", ac["model"]),
                         ("WhisperApiPrompt", ac["prompt"])):
                if v and wa.get(k) != v:
                    wa[k] = v
                    changed = True
        else:
            fw = data.setdefault("FasterWhisper", {})
            if ac["local_model"] in FW_MODEL_ENUM \
                    and fw.get("Model") != ac["local_model"]:
                fw["Model"] = ac["local_model"]
                changed = True
            if ac["local_model_dir"] \
                    and fw.get("ModelDir") != ac["local_model_dir"]:
                fw["ModelDir"] = ac["local_model_dir"]
                changed = True
        # 识别语言（2026-10-12）：显式语言才写——「自动检测」时刻意不碰
        # TranscribeLanguage，让引擎保留自己的取值（默认也是自动检测），
        # 避免工具箱的默认值把用户在引擎里设过的语言覆盖掉。
        _lang_label = str(ac.get("language_label") or "").strip()
        if _lang_label and _lang_label != "自动检测":
            if tr.get("TranscribeLanguage") != _lang_label:
                tr["TranscribeLanguage"] = _lang_label
                changed = True
        if changed:
            _vc_write_settings(data)
        # 内存态同步（引擎界面/QConfig 已加载时免重启生效）
        try:
            from videocaptioner.ui.common.config import cfg as _cfg
            from engine_entities import (FasterWhisperModelEnum,
                                         TranscribeModelEnum)
            _cfg.set(_cfg.transcribe_model,
                     TranscribeModelEnum.FASTER_WHISPER if ac["mode"] == "local"
                     else TranscribeModelEnum.WHISPER_API)
            if ac["mode"] == "service":
                if ac["base_url"]:
                    _cfg.set(_cfg.whisper_api_base, ac["base_url"])
                if ac["api_key"]:
                    _cfg.set(_cfg.whisper_api_key, ac["api_key"])
                if ac["model"]:
                    _cfg.set(_cfg.whisper_api_model, ac["model"])
                if ac["prompt"]:
                    _cfg.set(_cfg.whisper_api_prompt, ac["prompt"])
            elif ac["local_model"] in FW_MODEL_ENUM:
                for m in FasterWhisperModelEnum:
                    if m.value == ac["local_model"]:
                        _cfg.set(_cfg.faster_whisper_model, m)
                        break
            # 识别语言内存同步（与 settings.json 写入同口径：仅显式语言）
            _lang_label = str(ac.get("language_label") or "").strip()
            if _lang_label and _lang_label != "自动检测":
                from engine_entities import TranscribeLanguageEnum
                _cfg.set(_cfg.transcribe_language,
                         TranscribeLanguageEnum(_lang_label))
        except Exception:
            pass
        detail = (f"转录模型 → {'FasterWhisper（本地独立模型）' if ac['mode'] == 'local' else 'Whisper [API]（自有 ASR 服务）'}"
                  + (f"；识别语言 → {ac.get('language_label')}"
                     if str(ac.get("language_label") or "").strip()
                     and ac.get("language_label") != "自动检测" else ""))
        return True, detail
    except Exception as e:  # noqa: BLE001
        return False, str(e)


def vc_asr_patch_apply():
    """运行期补丁：让「独立 ASR 模型」真正生效（幂等，best-effort）。

    引擎的 TaskFactory.create_transcribe_task 把 faster_whisper_model_dir 硬编码
    成数据根 models 目录、模型名取自枚举项；本地独立模型（自定义模型名/模型目录，
    如自训练/微调的 faster-whisper 模型）必须在这里覆盖进 TranscribeConfig 才会
    被 used。service 模式不干预（引擎自己读 WhisperAPI 配置）。
    另：识别语言（asr_language，2026-10-12）为显式非自动值时，同样在这里写进
    TranscribeConfig.transcribe_language（apply_asr_to_engine 的兜底）。
    """
    try:
        from videocaptioner.ui import task_factory as _tf
    except Exception:  # noqa: BLE001
        return False
    if getattr(_tf, "_vt_asr_patched", False):
        return True
    orig = _tf.TaskFactory.create_transcribe_task

    def _patched(*args, **kwargs):
        task = orig(*args, **kwargs)
        try:
            ov = asr_local_override()
            if ov:
                model, model_dir = ov
                tcfg = getattr(task, "transcribe_config", None)
                if tcfg is not None:
                    if model:
                        tcfg.faster_whisper_model = model
                    if model_dir:
                        tcfg.faster_whisper_model_dir = model_dir
            # 识别语言（2026-10-12）：显式语言时直接写进 TranscribeConfig。
            # apply_asr_to_engine 已同步 settings.json 与内存 cfg，这里是兜底——
            # 任务在内存同步之前创建（或 cfg 尚未加载）时同样生效。
            try:
                ac = ai_mod().asr_config(ai_load_config())
            except Exception:  # noqa: BLE001
                ac = {}
            _label = str(ac.get("language_label") or "").strip()
            if _label and _label != "自动检测":
                tcfg = getattr(task, "transcribe_config", None)
                if tcfg is not None:
                    try:
                        from engine_entities import LANGUAGES
                        tcfg.transcribe_language = LANGUAGES.get(_label, "")
                    except Exception:  # noqa: BLE001
                        tcfg.transcribe_language = \
                            ai_mod().asr_language_code(_label)
        except Exception:
            pass
        return task

    _tf.TaskFactory.create_transcribe_task = staticmethod(_patched)
    _tf._vt_asr_patched = True
    return True


# ---------- v1.14.1：转录体验补丁（黑窗 / 下拉收敛 / 完成回填） ----------

def vc_pydub_nowindow_patch():
    """消掉「开启转录时闪黑色控制台窗口」（幂等，仅 Windows 生效）。

    根因：转录统一走 ChunkedASR，其 _split_audio() 必经 pydub 的
    AudioSegment.from_file()——pydub 内部裸调 ffprobe/ffmpeg 且不带
    CREATE_NO_WINDOW，GUI 进程下每次转录开始都会闪出黑色控制台窗口
    （分块导出 mp3、whisper_cpp 的 CLI 子进程同理）。引擎与 pydub 本体
    都不改：把 pydub / whisper_cpp 模块命名空间里的 subprocess 换成
    「默认补 CREATE_NO_WINDOW」的 shim，只影响这几个调用点。
    """
    if os.name != "nt":
        return True
    if getattr(subprocess, "_vt_nowindow", False):
        return True
    try:
        import types
        orig = subprocess.Popen

        def _popen(*args, **kwargs):
            try:
                if not kwargs.get("creationflags"):
                    kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
            except Exception:
                pass
            return orig(*args, **kwargs)

        shim = types.ModuleType("subprocess_vt_nowindow_shim")
        shim.__dict__.update(subprocess.__dict__)
        shim.Popen = _popen
        patched = []
        try:
            import pydub.audio_segment as _pas
            _pas.subprocess = shim
            patched.append("pydub.audio_segment")
        except Exception:
            pass
        try:
            import pydub.utils as _pu          # from subprocess import Popen
            _pu.Popen = _popen
            patched.append("pydub.utils")
        except Exception:
            pass
        try:
            from videocaptioner.core.asr import whisper_cpp as _wc
            _wc.subprocess = shim
            patched.append("whisper_cpp")
        except Exception:
            pass
        subprocess._vt_nowindow = True
        subprocess._vt_nowindow_orig = orig
        _vc_log("黑窗隐藏补丁已挂：Popen shim → " + ", ".join(patched))
        return True
    except Exception as e:  # noqa: BLE001
        _vc_log(f"黑窗隐藏补丁失败：{e}")
        return False


#: 转录下拉显示名：「默认」= 引擎免费接口（B 接口）；「ASR」= 全局 ASR 配置
TM_DISPLAY_DEFAULT = "默认"
TM_DISPLAY_ASR = "ASR"


# ---------- v1.18.0：转录完成后的「主播声纹筛选」 ----------
def voiceprint_enabled_names():
    """当前启用的声纹名单（空 = 用户没打算筛，别动字幕）。"""
    try:
        import speaker_voiceprint as _sv
        return _sv.load_selection()
    except Exception as e:  # noqa: BLE001
        _vc_log(f"读取声纹启用名单失败：{e}")
        return []


def voiceprint_filter_subtitle(srt_path, media_path, progress=None):
    """把刚转录出的字幕按「已启用声纹」筛成只留主播（**就地覆盖**）。

    返回结果 dict；返回 `None` 表示「本次不筛」——以下情形都算：
      · 一个声纹都没启用（用户没打算筛）
      · 声纹模型还没下载（提示用户去「主播声纹 → 下载模型」）
      · 字幕或媒体文件不存在

    ⚠ 就地覆盖前先把原件备份成 `<名>_未筛选.srt`：筛选是启发式的，万一误杀
    用户还能拿回全文。**任何异常都不吞**——由调用方记日志，绝不留半截产物。
    """
    import shutil
    import speaker_voiceprint as sv

    names = sv.load_selection()
    if not names:
        return None
    if not sv.model_present():
        _vc_log("声纹筛选跳过：模型未下载（界面「主播声纹 → 下载模型」）")
        return None
    if not (srt_path and os.path.isfile(srt_path)
            and media_path and os.path.isfile(media_path)):
        _vc_log(f"声纹筛选跳过：字幕或媒体不存在（{srt_path} / {media_path}）")
        return None

    backup = os.path.splitext(srt_path)[0] + "_未筛选.srt"
    if not os.path.isfile(backup):
        shutil.copyfile(srt_path, backup)
    res = sv.filter_srt(media_path, srt_path, names, out_path=srt_path,
                        progress=progress)
    res["backup"] = backup
    res["report"] = os.path.splitext(srt_path)[0] + ".报告.txt"
    _vc_log("声纹筛选完成（%s）：%d 条 -> 保留 %d / 存疑 %d / 丢弃 %d；"
            "原件备份 %s"
            % ("、".join(names), res["total"], res["kept_total"],
               res["review"], res["drop"], os.path.basename(backup)))
    return res


def vc_transcribe_ui_patch():
    """工作台转录下拉收敛为「默认 / ASR」+ 独立转录完成回填「字幕翻译」。

    v1.14.1 用户需求，全部运行期补丁（引擎 site-packages 保持原版）：
      ① 命令栏转录模型菜单只建「默认 / ASR」两项——J 接口 / FasterWhisper /
         WhisperCpp / Whisper [API] 不再出现；
      ② 选「ASR」时实时调 apply_asr_to_engine()（以全局设置「ASR 语音识别」
         卡片为准，按 asr_mode 落到 Whisper [API] / FasterWhisper）；
         选「默认」时落回 B 接口；历史残留取值一并收敛；
      ③ 引擎转录页自带的 Whisper API / FasterWhisper 配置块随下拉收敛
         不再可达（重复入口，从根上消除「与全局设置不一致」的两张页面），
         空位留一行提示；
      ④ 在转录页单独转录（拖入媒体，need_next_task=False）完成后，引擎原
         逻辑不做任何事——这里把生成的字幕装载进「字幕翻译」并自动切换
         过去（不自动开跑优化/翻译，等用户按「开始」）。
    幂等；必须在 HomeInterface 导入之后、实例构造之前调用。
    """
    try:
        from videocaptioner.ui.view import transcription_interface as ti
        from videocaptioner.ui.components import transcription_setting_card as tsc
        from engine_entities import TranscribeModelEnum
        from videocaptioner.ui.common.config import cfg as _cfg
        from qfluentwidgets import (Action, BodyLabel, FluentIcon, InfoBar,
                                    InfoBarPosition, PushButton, RoundMenu)
        from PySide6.QtWidgets import QVBoxLayout as _QVBox
    except Exception as e:  # noqa: BLE001
        _vc_log(f"转录 UI 补丁导入失败：{e}")
        return False
    if getattr(ti, "_vt_transcribe_ui_patched", False):
        return True

    def _asr_not_ready():
        """全局 ASR 是否还没配好（用于给出设置指引提示）。"""
        try:
            ac = ai_mod().asr_config(ai_load_config())
            if ac.get("mode") == "local":
                return not (ac.get("local_model") or ac.get("local_model_dir"))
            return not (ac.get("base_url") and ac.get("api_key"))
        except Exception:  # noqa: BLE001
            return False

    def _asr_missing_hint():
        """**已保存的**配置里缺什么 —— 说清楚，用户才知道该改哪一格。

        ⚠️ 读的是磁盘配置（不是界面输入框）：实测最常踩的坑是"设置页填好了
        但没点「保存并应用」"，这时磁盘上还是旧值/空值，转录页就说未配置。
        """
        try:
            ac = ai_mod().asr_config(ai_load_config())
            if ac.get("mode") == "local":
                if not (ac.get("local_model") or ac.get("local_model_dir")):
                    return "本地模式还没填模型名或目录"
                return ""
            miss = []
            if not ac.get("base_url"):
                miss.append("接口地址")
            if not ac.get("api_key"):
                miss.append("密钥")
            return ("已保存的配置里缺：" + "、".join(miss)) if miss else ""
        except Exception:  # noqa: BLE001
            return ""

    # ① 命令栏菜单：只留「默认 / ASR」
    orig_setup_bar = ti.TranscriptionInterface._setup_command_bar

    def _setup_command_bar(self):
        orig_setup_bar(self)
        try:
            menu = RoundMenu(parent=self)
            menu.addActions([
                Action(FluentIcon.GLOBE, TM_DISPLAY_DEFAULT),
                Action(FluentIcon.MICROPHONE, TM_DISPLAY_ASR),
            ])
            self.model_menu = menu          # _setup_signals 遍历的是这个菜单
            self.model_button.setMenu(menu)
        except Exception:  # noqa: BLE001
            pass

    ti.TranscriptionInterface._setup_command_bar = _setup_command_bar

    # ② 模型切换：显示名 ↔ 引擎枚举映射
    def _on_model_changed(self, model_name: str):
        # 防重入：cfg 信号 → 本槽 → cfg 信号 的环路在此截断
        if getattr(self, "_vt_model_busy", False):
            return
        try:
            asr_values = (TranscribeModelEnum.WHISPER_API.value,
                          TranscribeModelEnum.FASTER_WHISPER.value)
            if model_name == TM_DISPLAY_ASR:
                # 用户点了「ASR」：以全局「ASR 语音识别」设置为准实时同步
                self._vt_model_busy = True
                try:
                    self.model_button.setText(TM_DISPLAY_ASR)
                    self.transcription_setting_card.on_model_changed(
                        TM_DISPLAY_ASR)
                    ok, detail = apply_asr_to_engine()
                    if not ok:
                        _vc_log(f"ASR 应用失败：{detail}")
                    if _asr_not_ready():
                        InfoBar.warning(
                            "ASR 未配置",
                            ("%s；" % _asr_missing_hint() if _asr_missing_hint()
                             else "")
                            + "请到 设置 → ASR 语音识别 填好后点「保存并应用」"
                              "（只填不保存不生效）",
                            duration=8000, parent=self.window())
                finally:
                    self._vt_model_busy = False
                return
            if model_name == TM_DISPLAY_DEFAULT:
                # 用户点了「默认」：落回 B 接口
                self._vt_model_busy = True
                try:
                    self.model_button.setText(TM_DISPLAY_DEFAULT)
                    self.transcription_setting_card.on_model_changed(
                        TM_DISPLAY_DEFAULT)
                    _cfg.set(_cfg.transcribe_model, TranscribeModelEnum.BIJIAN)
                finally:
                    self._vt_model_busy = False
                return
            # 其余为启动恢复/signalBus 广播（传引擎枚举值）：只做显示映射，
            # 不回写配置，避免构造期触发配置环路
            if model_name in asr_values:
                self.model_button.setText(TM_DISPLAY_ASR)
                self.transcription_setting_card.on_model_changed(TM_DISPLAY_ASR)
            else:
                # 「B 接口」及被移除的历史取值（J 接口/WhisperCpp）→ 显示「默认」
                self.model_button.setText(TM_DISPLAY_DEFAULT)
                self.transcription_setting_card.on_model_changed(
                    TM_DISPLAY_DEFAULT)
                if model_name != TranscribeModelEnum.BIJIAN.value:
                    self._vt_model_busy = True
                    try:
                        _cfg.set(_cfg.transcribe_model,
                                 TranscribeModelEnum.BIJIAN)
                    finally:
                        self._vt_model_busy = False
        except Exception as e:  # noqa: BLE001
            self._vt_model_busy = False
            _vc_log(f"转录模型切换异常：{e}")

    ti.TranscriptionInterface.on_transcription_model_changed = _on_model_changed

    # ③ 独立转录完成 → 回填「字幕翻译」
    orig_finished = ti.TranscriptionInterface._on_transcript_finished

    def _home_of(widget):
        """沿 parent 链向上找 HomeInterface（判定标准：持有字幕翻译子界面）。

        ⚠️ 不能用 `self.parent()`：HomeInterface 构造时把各子界面
        `stackedWidget.addWidget(...)`，Qt 会顺手把父级改成那个
        QStackedWidget，于是 parent() 返回的是容器而不是 HomeInterface，
        `getattr(home, "subtitle_optimization_interface", None)` 恒为 None，
        整段回填被静默跳过（v1.14.1「转录完不自动跳字幕翻译」的根因）。
        这里逐级向上找，并以属性为准而非类名，宿主层级怎么改都不会再失联。
        """
        w = widget
        while w is not None:
            if getattr(w, "subtitle_optimization_interface", None) is not None:
                return w
            w = w.parent()
        # 兜底：宿主窗口里扫一遍（parent 链被重挂接打断时仍能找到）
        try:
            from PySide6.QtWidgets import QApplication, QWidget as _QWidget
            for tl in QApplication.topLevelWidgets():
                if getattr(tl, "subtitle_optimization_interface", None) is not None:
                    return tl
                for ch in tl.findChildren(_QWidget):
                    if getattr(ch, "subtitle_optimization_interface",
                               None) is not None:
                        return ch
        except Exception:  # noqa: BLE001
            pass
        return None

    def _produced_subtitle(path):
        """定位转录产物：引擎按 output_format 落盘（base_path + 实际后缀），
        task.output_path 的后缀未必等于真实文件名，这里按同基名补齐。"""
        if not path:
            return None
        try:
            if os.path.isfile(path):
                return path
            base = os.path.splitext(path)[0]
            for ext in (".srt", ".ass", ".vtt"):
                cand = base + ext
                if os.path.isfile(cand):
                    return cand
            # 输出格式设成「全部」等自定义后缀时，同目录同基名的字幕文件
            d, stem = os.path.split(base)
            if os.path.isdir(d):
                for name in sorted(os.listdir(d)):
                    low = name.lower()
                    if (name.startswith(stem + ".")
                            and low.endswith((".srt", ".ass", ".vtt"))):
                        return os.path.join(d, name)
        except Exception:  # noqa: BLE001
            pass
        return None

    def _start_voiceprint_filter(iface, out, media, then):
        """后台跑声纹筛选，完成后回调 `then()`；返回是否已接管流程。

        ⚠ 用 QThread 而非同步调用：实测 18 分钟素材「解码 + 提 275 段声纹 +
        聚类打分」约 27 秒，同步跑会把界面冻住（用户会以为卡死）。
        ⚠ worker 必须挂在 iface 上防 GC——局部变量出作用域就被回收，线程会被
        连带销毁，表现为"进度条一闪、什么都没发生"。
        """
        try:
            # ⚠ `Signal` 必须在这里导入：本补丁函数只 import 了
            #   QVBoxLayout / BodyLabel 等，没带 Signal。漏了会抛
            #   `name 'Signal' is not defined`，而它被外层 try 吞进
            #   logs\vc_fallback.log —— 界面上表现就是"什么都没发生"
            #   （v1.18.0 实测踩过：转录完既不筛也不提示）。
            from PySide6.QtCore import QThread as _QThread
            from PySide6.QtCore import Signal as _Signal
        except Exception:  # noqa: BLE001
            return False

        parent = _home_of(iface) or iface.window()
        try:
            bar = InfoBar.info(
                "正在按声纹筛选", "只保留主播台词，请稍候（长片约需半分钟）…",
                duration=-1, position=InfoBarPosition.BOTTOM, parent=parent)
        except Exception:  # noqa: BLE001
            bar = None

        class _VpWorker(_QThread):
            done = _Signal(object)

            def run(self):
                try:
                    r = voiceprint_filter_subtitle(out, media)
                except Exception as e:  # noqa: BLE001
                    _vc_log(f"声纹筛选失败：{e}")
                    r = {"error": str(e)}
                self.done.emit(r)

        def _finish(res):
            try:
                if bar is not None:
                    bar.close()
            except Exception:  # noqa: BLE001
                pass
            try:
                if isinstance(res, dict) and res.get("error"):
                    InfoBar.error("声纹筛选失败",
                                  str(res["error"])[:200] + "\n字幕已保留未筛选版本",
                                  duration=9000,
                                  position=InfoBarPosition.BOTTOM, parent=parent)
                elif res is None:
                    InfoBar.warning(
                        "声纹筛选未执行",
                        "声纹模型还没下载：到「语音转录 → 主播声纹」点「下载模型」",
                        duration=8000,
                        position=InfoBarPosition.BOTTOM, parent=parent)
                else:
                    InfoBar.success(
                        "声纹筛选完成",
                        "保留 %d 条（其中存疑 %d）/ 丢弃 %d；原件已备份为「%s」"
                        % (res["kept_total"], res["review"], res["drop"],
                           os.path.basename(res.get("backup") or "")),
                        duration=9000,
                        position=InfoBarPosition.BOTTOM, parent=parent)
            except Exception:  # noqa: BLE001
                pass
            try:
                then()
            except Exception as e:  # noqa: BLE001
                _vc_log(f"声纹筛选后回填异常：{e}")

        w = _VpWorker()
        w.done.connect(_finish)
        iface._vt_vp_worker = w          # 防 GC
        w.start()
        return True

    def _vt_filter_current_subtitle(iface):
        """对「字幕翻译」页**当前加载的字幕**套用声纹筛选，完了刷新表格。

        为什么需要这个手动入口：自动筛选只在「转录完成」时触发，而用户完全可能
        （a）走的是别的路径、（b）直接打开一份旧字幕、（c）想换个阈值再筛一次
        ——总不能每次都重转录（费时又费 ASR 额度）。有了它，任何来源的字幕都能筛。
        """
        path = getattr(iface, "subtitle_path", None)
        media = getattr(getattr(iface, "task", None), "video_path", None)
        if not path or not os.path.isfile(path):
            InfoBar.warning("没有可筛选的字幕", "请先加载字幕文件",
                            duration=5000, position=InfoBarPosition.BOTTOM,
                            parent=iface)
            return
        if not media or not os.path.isfile(media):
            InfoBar.warning(
                "缺少配套视频",
                "声纹筛选要从原视频/音频里取声音，当前字幕没有关联的媒体文件",
                duration=7000, position=InfoBarPosition.BOTTOM, parent=iface)
            return
        if not voiceprint_enabled_names():
            InfoBar.warning(
                "没有启用声纹",
                "到「语音转录 → 主播声纹」勾选要保留的声音（可多选）",
                duration=7000, position=InfoBarPosition.BOTTOM, parent=iface)
            return
        # 先把表格里的编辑写回文件——与引擎 `start_subtitle_optimization` 同款，
        # 否则筛选会连带丢掉用户在表格里做的合并 / 删除 / 编辑。
        try:
            from engine_asr_data import ASRData
            if getattr(getattr(iface, "model", None), "_data", None):
                ASRData.from_json(iface.model._data).to_srt(save_path=path)
        except Exception as e:  # noqa: BLE001
            _vc_log(f"筛选前回写表格失败（忽略，继续筛）：{e}")

        def _after():
            try:
                iface.load_subtitle_file(path)      # 刷新表格为筛选后的内容
            except Exception as e:  # noqa: BLE001
                _vc_log(f"筛选后刷新表格失败：{e}")

        if not _start_voiceprint_filter(iface, path, media, _after):
            _after()

    def _on_transcript_finished(self, task):
        # ⚠️⚠️ 入口先复位「处理中」标记（v1.15.7 修复）。
        # 引擎原生 _on_transcript_finished 的第一件事就是 is_processing=False，
        # 而下面的成功分支会 return、不再回调 orig_finished ⇒ 该标记永久停在
        # True：字幕明明已落盘、卡片按钮已是「转录完成」，但拖拽换视频被拦
        # 「正在处理中，请等待当前任务完成」，start_button 也被禁用（update_info
        # 见 is_processing=True 就 setEnabled(False)）⇒ 既中止不了也换不了视频。
        # 此处无条件复位（orig_finished 里那次复位是幂等的，重复无害）。
        self.is_processing = False
        try:
            if task is not None and not getattr(task, "need_next_task", False):
                out = _produced_subtitle(getattr(task, "output_path", None))
                media = getattr(task, "file_path", None)

                def _handoff():
                    """把产物字幕装载到「字幕翻译」并切过去（原 ③ 的跳转）。"""
                    home = _home_of(self) if out else None
                    sub = (getattr(home, "subtitle_optimization_interface", None)
                           if home is not None else None)
                    if sub is None:
                        if out:
                            _vc_log("独立转录完成，但未定位到工作台首页，"
                                    "回退引擎原逻辑")
                        return False
                    from videocaptioner.ui.task_factory import TaskFactory
                    st = TaskFactory.create_subtitle_task(
                        out, media, need_next_task=False,
                        task_id=getattr(home, "_current_task_id", None))
                    sub.set_task(st)
                    # 切到「字幕翻译」并让分段控件同步高亮（原生跳转同款两连）
                    home.stackedWidget.setCurrentWidget(sub)
                    home.pivot.setCurrentItem("SubtitleInterface")
                    _vc_log(f"独立转录完成 → 已装载「字幕翻译」：{out}")
                    InfoBar.success(
                        "转录完成",
                        "生成的字幕已装载到「字幕翻译」，可直接开始优化 / 翻译",
                        duration=5000,
                        position=InfoBarPosition.BOTTOM,
                        parent=home)
                    return True

                # ⑥ 主播声纹（v1.18.0）：启用了声纹就先筛，**筛完再回填字幕翻译**
                #    ——顺序不能反：字幕翻译要拿筛过的字幕，否则翻译出来还是多人。
                #    ⚠ 必须走后台线程：18 分钟的片子解码+提声纹要二三十秒，同步跑
                #    会把主线程（也就是整个界面）冻住。
                if out and voiceprint_enabled_names():
                    if _start_voiceprint_filter(self, out, media, _handoff):
                        return
                if _handoff():
                    return
        except Exception as e:  # noqa: BLE001
            _vc_log(f"转录完成回填异常：{e}")
        orig_finished(self, task)

    ti.TranscriptionInterface._on_transcript_finished = _on_transcript_finished

    # ③-B 陈旧「处理中」自愈（v1.15.7 兜底）——根因已在 ③ 修掉，这里防历史
    #      残留与其它路径把标记卡死（例如线程异常退出、任务创建页派发后中断）。
    #      判据：标记为 True 但转录线程不存在 / 已不在运行 ⇒ 判为陈旧，清标记
    #      并复位卡片按钮，然后照常放行拖拽与「打开文件」。
    def _vt_heal_stale(self):
        """陈旧「处理中」自愈；返回是否真的发生了自愈。"""
        if not getattr(self, "is_processing", False):
            return False
        card = getattr(self, "video_info_card", None)
        th = (getattr(card, "transcript_thread", None)
              if card is not None else None)
        if th is not None:
            try:
                if th.isRunning():
                    return False        # 真在跑：保持拦截，不误放行
            except Exception:  # noqa: BLE001
                return False
        self.is_processing = False
        try:
            if card is not None:
                card.reset_ui()         # 文案→「开始转录」并解除禁用
        except Exception:  # noqa: BLE001
            pass
        _vc_log("转录页陈旧「处理中」状态已自愈（无运行中的转录线程）")
        return True

    ti.TranscriptionInterface._vt_heal_stale = _vt_heal_stale

    def _heal_guard(orig):
        """在两个用户入口前先跑一次自愈，其后完全保持原行为。"""
        def _wrapped(self, *args, **kwargs):
            try:
                self._vt_heal_stale()
            except Exception:  # noqa: BLE001
                pass
            return orig(self, *args, **kwargs)
        return _wrapped

    ti.TranscriptionInterface.dropEvent = _heal_guard(
        ti.TranscriptionInterface.dropEvent)
    ti.TranscriptionInterface._on_file_select = _heal_guard(
        ti.TranscriptionInterface._on_file_select)

    # ④ 转录设置卡片空位提示（默认/ASR 都不再展示引擎内置 ASR 配置块）
    #    + ⑥ 主播声纹录入卡（v1.18.0）：本页 `empty_widget` 是默认显示的空白
    #    区，正好用来放声纹录入——不新增页面，用户也不用另找入口。
    orig_card_init = tsc.TranscriptionSettingCard.__init__

    def _card_init(self, parent=None):
        orig_card_init(self, parent)
        try:
            lay = _QVBox(self.empty_widget)
            lay.setContentsMargins(24, 4, 24, 4)
            tip = BodyLabel(
                "默认：内置免费语音识别；ASR：使用设置页「ASR 语音识别」的模型"
                "（自有服务 / 本地模型），统一在全局设置中维护",
                self.empty_widget)
            tip.setStyleSheet("color: #8a8a8a;")
            tip.setWordWrap(True)   # 窄窗口下不换行会被裁掉右半句
            lay.addWidget(tip)
            try:
                from speaker_voiceprint_page import VoiceprintEnrollCard
                self.vt_voiceprint_card = VoiceprintEnrollCard(self.empty_widget)
                lay.addWidget(self.vt_voiceprint_card)
            except Exception as e:  # noqa: BLE001
                _vc_log(f"声纹录入卡挂载失败：{e}")
            lay.addStretch(1)
        except Exception:  # noqa: BLE001
            pass

    tsc.TranscriptionSettingCard.__init__ = _card_init

    # ⑦ 转录设置弹窗加「主播声纹（可多选）」（v1.18.0）
    #    勾选即写入 data/voiceprint/selection.json；多选 = 并集语义。
    try:
        from videocaptioner.ui.components.TranscriptionSettingDialog import (
            TranscriptionSettingDialog as _VTSettingDialog)
        from speaker_voiceprint_page import VoiceprintPicker

        _orig_dlg_init = _VTSettingDialog.__init__

        def _dlg_init(self, parent=None):
            _orig_dlg_init(self, parent)
            try:
                self.vt_voiceprint_picker = VoiceprintPicker(self)
                self.viewLayout.addWidget(self.vt_voiceprint_picker)
            except Exception as e:  # noqa: BLE001
                _vc_log(f"声纹多选器挂载失败：{e}")

        _VTSettingDialog.__init__ = _dlg_init
    except Exception as e:  # noqa: BLE001
        _vc_log(f"转录设置弹窗声纹补丁未挂：{e}")

    # ⑧ 任务创建路径的声纹筛选（v1.18.0）
    #    ⚠⚠ 引擎的 `TranscriptionInterface._on_transcript_finished` **只在
    #    `need_next_task=True` 时**才 `self.finished.emit(...)`；而补丁 ③ 挂的是
    #    `not need_next_task`（「独立转录」）那一支 ⇒ **走「任务创建」的用户筛选
    #    完全不生效**（2026-10-09 实测踩过：转录产物 275 条原样没筛，用户看到
    #    "还是混杂"）。这里把另一条路也挂上——它的落点是
    #    `HomeInterface.switch_to_subtitle_optimization(file_path, video_path)`。
    try:
        from videocaptioner.ui.view.home_interface import (
            HomeInterface as _VT_HOME)
        _orig_switch_sub = _VT_HOME.switch_to_subtitle_optimization

        def _switch_sub(self, file_path, video_path):
            if voiceprint_enabled_names() and _start_voiceprint_filter(
                    self, file_path, video_path,
                    lambda: _orig_switch_sub(self, file_path, video_path)):
                return
            return _orig_switch_sub(self, file_path, video_path)

        _VT_HOME.switch_to_subtitle_optimization = _switch_sub
    except Exception as e:  # noqa: BLE001
        _vc_log(f"任务创建路径的声纹筛选补丁未挂：{e}")

    # ⑨ 「字幕翻译」页加「按声纹筛选」按钮（v1.18.0）
    #    自动筛选只在「转录完成」时触发；用户完全可能直接打开一份旧字幕、或想
    #    换个阈值再筛一次——总不能每次重转录。给个手动入口，任何来源都能筛。
    try:
        from videocaptioner.ui.view.subtitle_interface import (
            SubtitleInterface as _VT_SubIface)
        _orig_sub_init = _VT_SubIface.__init__

        def _sub_init(self, parent=None):
            _orig_sub_init(self, parent)
            try:
                btn = PushButton("按声纹筛选", self)
                btn.setToolTip("按已启用的主播声纹过滤当前字幕"
                               "（原件自动备份为 *_未筛选.srt）")
                btn.clicked.connect(lambda: _vt_filter_current_subtitle(self))
                self.command_bar.addWidget(btn)
                self._vt_vp_button = btn
            except Exception as e:  # noqa: BLE001
                _vc_log(f"字幕翻译页声纹按钮挂载失败：{e}")

        _VT_SubIface.__init__ = _sub_init
    except Exception as e:  # noqa: BLE001
        _vc_log(f"字幕翻译页声纹补丁未挂：{e}")

    # ⑤ ASR 服务模式多协议适配（auto / openai / azure / dashscope）
    try:
        vc_asr_protocol_patch()
    except Exception:  # noqa: BLE001
        pass

    ti._vt_transcribe_ui_patched = True
    _vc_log("转录 UI 补丁已挂：下拉=默认/ASR，独立转录完成回填「字幕翻译」")
    return True


def vc_lazy_cache_patch():
    """把引擎 5 处 diskcache 实例创建改成惰性建库（幂等）。

    引擎在 `videocaptioner.core.utils.cache` 模块级创建 5 个 diskcache 实例
    （LLM / ASR / TTS / 翻译 / 版本状态），每个都会真实打开 SQLite 建库并做
    维护：本机实测每个约 0.9 秒（慢盘更久），合计 2.5~4.5 秒——而进入「字幕
    处理」页并不需要任何缓存。

    v1.20.0 起改用自研 `engine_cache`（cache 接缝接管）：
      · 惰性策略与实例管理归自研模块，**不再 monkey-patch diskcache 的类**——
        旧做法把 `diskcache.Cache` 整个换成代理类，等于改写第三方库的公开面；
      · diskcache 保留为 Apache-2.0 底层组件（不重写 SQLite 缓存引擎）；
      · diskcache 缺失时降级为进程内字典缓存，而不是让程序起不来。

    必须在任何 videocaptioner 导入之前调用（prepare_runtime_env 最前面）。
    """
    try:
        import sys as _sys
        import diskcache
    except Exception as e:  # noqa: BLE001
        _vc_log(f"缓存补丁跳过（diskcache 不可用，引擎将走内存降级）：{e}")
        return False
    if getattr(diskcache, "_vt_lazy_patched", False):
        return True
    from engine_cache import CACHE_KINDS, LazyCache

    # 让第三方 `from diskcache import Cache` 拿到的仍是真 Cache——
    # 我们只在这里把「模块级实例」换成惰性代理，公开类本身不动。
    real_cache = diskcache.Cache

    def _vt_lazy_cache_factory(directory, *args, **kwargs):
        """引擎构造缓存实例时的唯一入口：返回自研惰性代理。"""
        sub = str(directory).replace("\\", "/").rstrip("/").split("/")[-1]
        kind = next((k for k, v in CACHE_KINDS.items() if v == sub), None)
        if kind is not None:
            # 走 hub：同一 kind 复用同一实例（与引擎「模块级单例」等价）
            return _vt_cache_hub().get(kind)
        return LazyCache(directory, *args, **kwargs)

    diskcache.Cache = _vt_lazy_cache_factory
    diskcache._vt_lazy_patched = True
    diskcache._vt_real_cache = real_cache
    return True


def _vt_cache_hub():
    """进程内单例的缓存工厂（幂等）。

    放在这里而不是模块级，是为了让缓存根目录跟随 `engine_paths` 的取值，
    且能在 `VT_DATA_ROOT` 变更后仍取到正确根。
    """
    hub = getattr(vc_lazy_cache_patch, "_hub", None)
    if hub is None:
        from engine_cache import CacheHub
        hub = CacheHub(os.path.join(vc_data_dir(), "cache"))
        try:
            vc_lazy_cache_patch._hub = hub
        except (AttributeError, TypeError):
            pass
    return hub


def vc_prepare_settings_file():
    """引擎界面导入前规整 settings.json（幂等，在 prepare_runtime_env 调用）。

    1) 工作目录等路径项全部收进软件文件夹（修掉历史 C 盘 Work_Dir）；
    2) 把全局 LLM 配置注入引擎 OpenAI 兼容槽。
    必须在 videocaptioner.ui.common.config（qconfig 读盘）之前完成。
    """
    try:
        os.makedirs(vc_data_dir(), exist_ok=True)
        existed = os.path.isfile(vc_settings_path())
        data = _vc_read_settings()
        changed = _vc_force_local_paths(data)
        ai = ai_load_config()
        llm = data.setdefault("LLM", {})
        if not bool(ai.get("enabled", True)):
            # 「启用 AI」已关闭：清空引擎 LLM 槽（历史注入的密钥一并清掉），
            # 引擎的优化 / LLM 翻译会明确提示需配置 AI，而不是偷偷消耗额度
            for k in ("OpenAI_API_Key", "OpenAI_API_Base", "OpenAI_Model"):
                if llm.get(k):
                    llm[k] = ""
                    changed = True
        else:
            # v1.12.0：全局 AI 单通道（base_url / api_key / model 一套）
            want = {
                "LLMService": "OpenAI 兼容",
                "OpenAI_API_Base": str(ai.get("base_url") or "").strip(),
                "OpenAI_API_Key": str(ai.get("api_key") or "").strip(),
                "OpenAI_Model": str(ai.get("model") or "").strip(),
            }
            for k, v in want.items():
                if v and llm.get(k) != v:
                    llm[k] = v
                    changed = True
        # v1.12.0：微软翻译已改用 Edge 免认证端点、谷歌翻译已改用 gtx 免费网页版
        # 接口（docs/vc_translate_impl/*.py），两者恢复直连可用。
        # v1.12.0 起字幕翻译板块全面去 AI（仅机翻）：历史配置若被 v1.11.0 迁到
        # 「LLM 大模型翻译」，这里迁回「微软翻译」；翻译失败不再回退 LLM，
        # 如实报错（失败率 ≥50% 时引擎会抛 RuntimeError 提示检查网络）。
        tr = data.setdefault("Translate", {})
        cur_ts = str(tr.get("TranslatorServiceEnum") or "").strip()
        if cur_ts == TS_LLM:
            tr["TranslatorServiceEnum"] = TS_BING
            changed = True
            _vc_log("字幕翻译仅支持机器翻译，已把翻译服务由「LLM 大模型翻译」"
                    "迁回「微软翻译」")
        if changed or not existed:
            _vc_write_settings(data)
        # v1.11.0：ASR（转录配置）与接口 B 同样在引擎读盘前注入
        apply_asr_to_engine(ai)
    except Exception:
        pass


def vc_enforce_runtime_cfg():
    """引擎 QConfig 已加载后的运行期兜底：强制工作目录收敛到软件文件夹。

    防止历史 settings.json 的 C 盘 Work_Dir 在内存里复活、或被界面回写。
    在引擎界面/设置界面构建之后调用（best-effort）。
    """
    try:
        from videocaptioner.ui.common.config import cfg as _cfg
        work_posix = os.path.join(vc_data_dir(), "work-dir").replace(os.sep, "/")
        try:
            cur = str(_cfg.get(_cfg.work_dir) or "")
        except Exception:
            cur = ""
        if cur.replace("\\", "/") != work_posix:
            _cfg.set(_cfg.work_dir, work_posix)
    except Exception:
        pass
    # v1.11.0：转录配置（自有 ASR 服务 / 本地独立模型）与本地模型覆盖补丁
    # 一并在此兜底——引擎界面构建完成后调用，保证内存 QConfig 与磁盘一致。
    try:
        apply_asr_to_engine()
    except Exception:
        pass
    try:
        vc_asr_patch_apply()
    except Exception:
        pass
    # v1.12.0：翻译板块已全面去 AI（仅机翻），「创建失败/无有效产出回退 LLM」
    # 兜底补丁（vc_translate_fallback_patch）整体移除；翻译失败如实报错。


def vc_migrate_legacy_data():
    """把字幕引擎在 C 盘的历史数据迁移到数据根目录（幂等，一次有效）。

    上游在不同版本用过两种布局，都要处理：
      · <legacy>/settings.json、<legacy>/logs/...    —— 直接以 legacy 为数据根
      · <legacy>/VideoCaptioner/settings.json、...   —— 多套了一层同名子目录
    做法：逐个把 legacy 下的「数据项」（settings.json / logs / cache / models /
    resource / work-dir）搬到目标根；若发现 legacy 下还有嵌套的 VideoCaptioner
    子目录，则把它的内容也视作数据项一并搬走，避免出现 VideoCaptioner\\VideoCaptioner。
    目标已存在同名项时不覆盖（保留新位置的数据）。返回迁移的条目数。
    """
    dst_root = vc_data_dir()
    # 需要搬运的数据项名（白名单，避免搬进无关文件）
    DATA_ITEMS = ("settings.json", "logs", "cache", "models", "resource",
                  "work-dir", "cli", "llm_requests.jsonl")
    moved = 0

    def _merge(src_dir, depth=0):
        """把 src_dir 下的数据项合并到 dst_root；遇到嵌套同名目录则下钻。"""
        nonlocal moved
        if depth > 2:
            return
        try:
            names = os.listdir(src_dir)
        except OSError:
            return
        nested = []
        for name in names:
            src = os.path.join(src_dir, name)
            # 兼容旧布局：<legacy>/VideoCaptioner/... 下钻一层（稍后处理，
            # 先搬完本层的数据项，避免父目录自己的 settings.json 被漏掉）
            if (name == VC_NAME and os.path.isdir(src)
                    and os.path.abspath(src) != os.path.abspath(dst_root)):
                nested.append(src)
                continue
            if name not in DATA_ITEMS:
                continue
            dst = os.path.join(dst_root, name)
            if os.path.exists(dst):
                # 目录已存在则合并内容（同名文件不覆盖）
                if os.path.isdir(src) and os.path.isdir(dst):
                    moved += _merge_into(src, dst)
                continue
            try:
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.move(src, dst)
                moved += 1
            except OSError:
                pass
        for sub in nested:
            _merge(sub, depth + 1)

    def _merge_into(src_dir, dst_dir):
        """递归合并目录，同名不覆盖；返回搬动的条目数。"""
        n = 0
        try:
            names = os.listdir(src_dir)
        except OSError:
            return 0
        for name in names:
            s = os.path.join(src_dir, name)
            d = os.path.join(dst_dir, name)
            if os.path.isdir(s):
                try:
                    os.makedirs(d, exist_ok=True)
                except OSError:
                    continue
                n += _merge_into(s, d)
            elif not os.path.exists(d):
                try:
                    shutil.move(s, d)
                    n += 1
                except OSError:
                    pass
        return n

    try:
        os.makedirs(dst_root, exist_ok=True)
    except OSError:
        return 0

    for legacy in _VC_LEGACY_DIRS:
        if not legacy or not os.path.isdir(legacy):
            continue
        if os.path.abspath(legacy) == os.path.abspath(dst_root):
            continue
        _merge(legacy)
        _prune_empty(legacy)
    return moved


def _prune_empty(root):
    """自底向上删除 root 下的空目录（不含 root 自身）。best-effort。"""
    for cur, dirs, files in os.walk(root, topdown=False):
        if os.path.abspath(cur) == os.path.abspath(root):
            continue
        if files:
            continue
        try:
            os.rmdir(cur)
        except OSError:
            pass


def _dir_has_content(d):
    """目录下是否存在任何文件（含被占用/无权访问的，保守判为有内容）。"""
    try:
        for _cur, _dirs, files in os.walk(d):
            if files:
                return True
    except OSError:
        return True
    return False


def vc_legacy_leftovers():
    """列出仍在 C 盘、且真的含有效数据的历史字幕引擎目录。

    判据是「有文件，且该文件在数据根下还不存在」——迁移后遗留的重复文件
    （数据根已有同名同路径的副本）不算残留，避免误导用户去清理一个已经
    迁空的路径。仅剩空目录树的一律不提示。
    """
    out = []
    dst_root = vc_data_dir()

    def _has_unique_file(d):
        """d 下是否存在数据根里没有对应文件的文件。"""
        try:
            walker = os.walk(d)
        except OSError:
            return False
        for cur, _dirs, files in walker:
            if not files:
                continue
            rel_dir = os.path.relpath(cur, d)
            # <legacy>/ 与 <legacy>/VideoCaptioner/ 两种布局都映射到数据根
            base = os.path.basename(cur)
            for f in files:
                cands = []
                if rel_dir in (".", ""):
                    cands.append(os.path.join(dst_root, f))
                else:
                    cands.append(os.path.join(dst_root, rel_dir, f))
                    # 多套一层同名目录的情况（.../VideoCaptioner/cache/x.db）
                    if base != VC_NAME and VC_NAME in rel_dir.split(os.sep):
                        tail = rel_dir.split(VC_NAME, 1)[1].lstrip(os.sep)
                        cands.append(os.path.join(dst_root, tail, f))
                if not any(os.path.exists(c) for c in cands):
                    return True
        return False

    for d in _VC_LEGACY_DIRS:
        if d and os.path.isdir(d) and _dir_has_content(d) and _has_unique_file(d):
            out.append(d)
    return out


def prepare_runtime_env():
    """统一准备运行期环境（幂等，可重复调用）。

    0. diskcache 延迟化补丁（v1.11.0：省掉引擎导入时建 5 个缓存库的数秒）；
    1. 迁移字幕引擎在 C 盘的历史数据到数据根目录；
    2. 重定向字幕引擎的路径常量为数据根目录；
    3. 兜底确保临时目录指向数据根目录（不落系统 Temp）。
    在导入 videocaptioner *之前* 调用；GUI 启动与自检都会走这里。
    """
    # 必须最先：任何 videocaptioner 导入之前替换 diskcache.Cache
    try:
        vc_lazy_cache_patch()
    except Exception:
        pass
    # ⚠️ 顺序不可调换：路径重定向必须早于任何会导入 videocaptioner 的补丁。
    # v1.14.1 的 pydub 补丁内部 `from videocaptioner.core.asr import whisper_cpp`
    # 会触发引擎 config 导入、把路径常量固化成 AppData 默认值；一旦它先跑，
    # vc_redirect_paths() 的「已导入即跳过」守卫就会放行，导致重定向整体失效
    # ——表现为资源/日志/缓存落回 C 盘、随包 assets 与 ffmpeg 定位全丢
    # （_selftest_vc 11 项失败即由此暴露）。
    try:
        vc_redirect_paths()
    except Exception:
        pass
    # v1.14.1：转录时 pydub 裸调 ffprobe/ffmpeg 闪黑窗 → 子进程默认隐藏窗口
    try:
        vc_pydub_nowindow_patch()
    except Exception:
        pass
    # v1.16.2：翻译请求路由钉死（微软直连 / 谷歌走本地代理）。引擎翻译器默认
    # 跟随系统代理，mihomo 一挂连直连就能用的微软翻译也会被带崩 → 全段失败。
    try:
        vc_translate_route_patch()
    except Exception:
        pass
    # v1.16.2：ASR 协议分发补丁也在这里挂一次。此前它只挂在 GUI 的
    # 「转录 UI 补丁」里（video_toolbox_qt.py 启动时调），一旦那条路径提前
    # 失败（引擎 UI 模块导入异常等），协议分发就整体不生效 —— 表现为
    # qwen-audio-3.0-asr-flash 被按 openai 协议打，直接 404 Api not found。
    try:
        vc_asr_protocol_patch()
    except Exception:
        pass
    # 标准流统一 UTF-8 容错，避免 GBK 控制台打印生僻字/Emoji 时崩溃
    try:
        configure_stdio_utf8()
    except Exception:
        pass
    try:
        vc_migrate_legacy_data()
    except Exception:
        pass
    try:
        # 引擎界面读盘前规整 settings.json：路径收进软件文件夹 + 注入全局 LLM
        vc_prepare_settings_file()
    except Exception:
        pass
    try:
        os.makedirs(TMP_DIR, exist_ok=True)
        os.environ["TEMP"] = TMP_DIR
        os.environ["TMP"] = TMP_DIR
        tempfile.tempdir = TMP_DIR
    except OSError:
        pass


def data_root_info():
    """返回 (当前数据根目录, 是否为默认位置, 来源说明)，供界面展示。"""
    root = _resolve_data_root()
    if os.environ.get("VT_DATA_ROOT"):
        src = "环境变量 VT_DATA_ROOT"
    elif os.path.isfile(DATA_ROOT_POINTER):
        src = "用户自定义（data_dir.txt）"
    else:
        src = "默认（程序目录）"
    return root, os.path.abspath(root) == os.path.abspath(APP_DIR), src


def set_data_root(new_root, migrate=True):
    """切换数据根目录（写指针文件），返回 (是否成功, 说明文案)。

    只改指针文件，不立刻搬数据；migrate=True 时把当前 data/logs/tmp 下的内容
    尽量搬到新位置（同名不覆盖）。切换需重启程序后完全生效（路径常量在导入
    时已固化）。
    """
    try:
        new_root = os.path.abspath(str(new_root).strip().strip('"'))
    except OSError as e:
        return False, "路径无效：%s" % e
    if not new_root:
        return False, "路径为空"
    try:
        os.makedirs(new_root, exist_ok=True)
        # 探针：确认真的可写（避免只读盘/权限问题）
        probe = os.path.join(new_root, ".vt_write_test")
        with open(probe, "w", encoding="utf-8") as f:
            f.write("ok")
        os.remove(probe)
    except OSError as e:
        return False, "该位置不可写：%s" % e

    if os.path.abspath(new_root) == os.path.abspath(APP_DIR):
        # 切回默认：删掉指针文件
        try:
            if os.path.isfile(DATA_ROOT_POINTER):
                os.remove(DATA_ROOT_POINTER)
        except OSError as e:
            return False, "无法移除指针文件：%s" % e
        return True, "已切回默认位置（程序目录），重启后生效"

    try:
        with open(DATA_ROOT_POINTER, "w", encoding="utf-8") as f:
            f.write(new_root)
    except OSError as e:
        return False, "无法写入指针文件：%s" % e

    if migrate:
        moved, failed = _move_data_to(new_root)
        return True, "已切换，并迁移 %d 项数据%s，重启后生效" % (
            moved, ("（%d 项被占用未迁移）" % failed) if failed else "")

    return True, "已切换，重启后生效"


def _move_data_to(new_root):
    """把当前数据根下的 data/logs/tmp 内容搬到新根（同名不覆盖）。"""
    moved = failed = 0
    for sub in ("data", "logs"):
        src_dir = os.path.join(DATA_ROOT, sub)
        dst_dir = os.path.join(new_root, sub)
        if not os.path.isdir(src_dir):
            continue
        try:
            os.makedirs(dst_dir, exist_ok=True)
        except OSError:
            failed += 1
            continue
        for name in os.listdir(src_dir):
            s = os.path.join(src_dir, name)
            d = os.path.join(dst_dir, name)
            if os.path.exists(d):
                continue
            try:
                shutil.move(s, d)
                moved += 1
            except OSError:
                failed += 1
    return moved, failed


def engine_ui_brand_patch():
    """对内嵌引擎的用户可见文案与布局做中性化补丁（幂等，仅改运行时行为）。

    · 视频预览弹窗标题/图标跟随宿主，去除上游品牌；
    · 任务创建页隐藏品牌 logo、收紧独立窗口时代的大留白。
    各部分独立容错：某一模块导入失败（如缺 vlc）不影响其余补丁生效。
    第三方组件的许可全文与来源声明见 docs 目录下两个声明文件（必须保留）。
    """
    # 视频预览弹窗补丁为 best-effort：缺可选依赖 vlc 时跳过，不算失败
    try:
        from videocaptioner.ui.components.MyVideoWidget import MyVideoWidget
    except Exception:
        MyVideoWidget = None
    if MyVideoWidget is not None:
        _patch_video_widget(MyVideoWidget)
    # 任务创建页补丁是内嵌界面真正依赖的（隐藏 logo/水印、收紧留白）
    try:
        from videocaptioner.ui.view.task_creation_interface import (
            TaskCreationInterface)
    except Exception:
        return False
    _patch_task_creation(TaskCreationInterface)
    return True


def _patch_video_widget(MyVideoWidget):
    """视频预览弹窗：标题与图标跟随宿主。"""
    if getattr(MyVideoWidget, "_vt_patched", False):
        return

    orig_init = MyVideoWidget.__init__

    def _init(self, parent=None):
        orig_init(self, parent)
        # 视频预览弹出窗口：标题与图标跟随宿主，去除上游品牌
        self.setWindowTitle("视频预览")
        try:
            from PySide6.QtWidgets import QApplication
            icon = QApplication.windowIcon()
            if not icon.isNull():
                self.setWindowIcon(icon)
        except Exception:
            pass

    MyVideoWidget.__init__ = _init
    MyVideoWidget._vt_patched = True


def _patch_task_creation(TaskCreationInterface):
    """任务创建页：隐藏品牌 logo、收紧独立窗口时代的大留白。"""
    if getattr(TaskCreationInterface, "_vt_layout_patched", False):
        return

    orig_setup = TaskCreationInterface.setup_ui

    def _setup(self):
        orig_setup(self)
        logo = getattr(self, "logo_label", None)
        if logo is not None:
            logo.hide()
        lay = getattr(self, "main_layout", None)
        if lay is not None:
            for i in reversed(range(lay.count())):
                item = lay.itemAt(i)
                spacer = item.spacerItem() if item is not None else None
                if spacer is not None and spacer.sizeHint().height() >= 100:
                    lay.removeItem(item)
            lay.setSpacing(18)
            lay.insertSpacing(0, 24)

    TaskCreationInterface.setup_ui = _setup
    TaskCreationInterface._vt_layout_patched = True
# =============================




# ========== AI 校准（Agent 级）入口 ==========
# 界面开启「AI 校准」后点「开始校准」，等价于向 Agent 下达：基于脚本
# subtitle_calib_merged 校准字幕，不改变时间轴与格式，仅调整文字内容，
# 一次读不完就自行拆分，最后合并。实现见 src\calib_ai_agent.py。




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
    return client.chat_text(prompt, system=system,
                            max_tokens=int(max_tokens or 8192),
                            on_reasoning=on_reasoning,
                            thinking=thinking,
                            reasoning_effort=effort if thinking else None)


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
                 media_path=None):
    """跑一轮 Agent 级 AI 校准，返回结果 dict（见 calib_ai_agent.calibrate）。

    style：None=读配置 `calib_style`——`term` 术语级（只替换名词，默认）/
           `rewrite` 整句重写（针对机翻腔、跨 cue 断句的片源，长双语片常用）。
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
    import calib_ai_agent as _agent
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
    style = style or str(ai.get("calib_style") or "term")
    web = None
    if bool(ai.get("calib_web_enabled", False)):
        try:
            import calib_web_agent as _web
            web = _web.make_tools(proxy=calib_web_proxy, log=log)
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
            import calib_media_agent as _media
            _asr = ai_mod().asr_config(ai)
            _asr["protocol"] = ai_mod().resolve_asr_protocol(_asr)
            _ff = ""
            try:
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
    try:
        return _agent.calibrate(
            src, out=out, report=report, mode_flag=mode_flag, fix_en=fix_en,
            script=os.path.join(APP_DIR, "subtitle_calib_merged.py"),
            python=system_python(), log=log, chat=calib_ai_chat,
            chat_for_member=_member_chat, cluster=cluster,
            think_rounds=int(ai.get("calib_think_rounds") or 0),
            orig_title=title,
            chunk_cues=int(ai.get("calib_chunk_cues") or 400),
            max_chars=int(ai.get("calib_max_chars") or 60000),
            max_tokens=int(ai.get("calib_max_tokens") or 65536),
            context_tokens=int(ai.get("calib_context_tokens") or 1000000),
            concurrency=int(ai.get("calib_concurrency") or 1),
            round_no=round_no, cancel=cancel, workdir=workdir,
            style=style, resume_from=resume_from, prev_changes=prev_changes,
            sentence_aware=bool(ai.get("calib_sentence_aware", True)),
            strict_width=bool(ai.get("calib_strict_width", False)),
            web=web, media=media, preflight=True)
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



def _patch_translator_route(mod, cls_name):
    """给某个翻译器类的 `__init__` 包一层：构造完 session 后钉死路由。"""
    cls = getattr(mod, cls_name, None)
    if cls is None or getattr(cls, "_vt_route_patched", False):
        return False
    orig_init = cls.__init__

    def _init(self, *a, **kw):
        orig_init(self, *a, **kw)
        try:
            session = getattr(self, "session", None)
            if session is not None:
                session.trust_env = False          # 关键：不读环境/系统代理
                session.proxies = translate_session_proxies(
                    getattr(self, "endpoint", ""))
        except Exception as e:  # noqa: BLE001
            _vc_log(f"翻译会话路由设置失败（{cls_name}）：{e}")

    cls.__init__ = _init
    cls._vt_route_patched = True
    return True


def vc_translate_route_patch():
    """把「翻译请求路由」钉死（幂等运行期补丁，理由见 `translate_session_proxies`）。"""
    try:
        import videocaptioner.core.translate.bing_translator as _bt
        import videocaptioner.core.translate.google_translator as _gt
    except Exception as e:  # noqa: BLE001
        _vc_log(f"翻译路由补丁导入失败：{e}")
        return False
    done = []
    if _patch_translator_route(_bt, "BingTranslator"):
        done.append("微软")
    if _patch_translator_route(_gt, "GoogleTranslator"):
        done.append("谷歌")
    if done:
        _vc_log("翻译路由补丁已挂：%s 请求显式路由（微软直连 / 谷歌走本地代理，"
                "不再跟随系统代理）" % "+".join(done))
    return True


# ========== 校准知识同步（v1.12.2：GitHub 整文件通道收集 + 可选本地增量镜像） ==========
# 架构：
#   · 更新（界面唯一入口，启动自动 + 手动）：从内置 github_proxy.yaml 指向的
#     GitHub 仓库拉取全体使用者沉淀，条目级三方合并进本地；若管理员另配了
#     共享更新库（VT_SYNC_ROOT 下有 baseline.json），叠加本地增量镜像 kb-sync；
#   · 上传：全自动、隐藏在后台——learn 实时写本地学习库，退出程序时派生
#     隐藏子进程把「校准脚本 + 学习库」推回 GitHub（先拉后推，互不覆盖），
#     镜像启用时同时 kb-push 进收件箱；界面上不存在任何上传按钮；
#   · 折叠基线、清理更新库等管理动作全部在独立程序 kb_admin.exe。
# 连接参数统一在 github_proxy.yaml 的 vt-github 段（owner/repo/branch/api/
#   token/files），改仓库只动 yaml。
# 策略：静默、不阻塞、不弹窗，结果写 logs/calib_sync.log；失败一律降级为
#   "本地功能照常可用"，绝不因同步失败影响校准。
SYNC_LOG = os.path.join(LOGS_DIR, "calib_sync.log")
#: 用户侧同步脚本与更新库路径（打包后随包分发在程序根目录）
CALIB_SCRIPT = os.path.join(APP_DIR, "subtitle_calib_merged.py")
CALIB_KB_PATH = os.path.join(APP_DIR, "subtitle_learned_kb.json")
#: 更新库根目录（管理员维护、可指向网络盘）与本机同步状态目录
SYNC_REMOTE_DIR = os.path.join(DATA_DIR, "calib_sync_remote")
SYNC_LOCAL_DIR = os.path.join(DATA_DIR, "calib_sync")


def _sync_log(msg):
    """追加一行同步日志（best-effort，绝不因日志失败影响主流程）。

    统一走 `_append_log`：轮转 + 去重 + 级别标记（v1.16.2）。GitHub 直连
    超时这类每次启动都会重放的告警，去重后只留首次。
    """
    _append_log("calib_sync.log", msg)


def sync_env_into(env):
    """给校准/同步子进程补齐增量通道路径变量（外部显式设置优先，setdefault 语义）。

    引擎导入时对 os.environ 调用一次：此后所有子进程（校准 worker、AI 校准、
    同步子进程）自动继承，保证 learn 自动上传、退出补传、启动更新指向同一库。
    """
    env.setdefault("VT_DATA_ROOT", DATA_ROOT)
    env.setdefault("VT_SYNC_ROOT", SYNC_REMOTE_DIR)
    env.setdefault("VT_SYNC_DIR", SYNC_LOCAL_DIR)
    env.setdefault("VT_SYNC_KB", CALIB_KB_PATH)
    return env


for _d in (SYNC_REMOTE_DIR, SYNC_LOCAL_DIR):
    try:
        os.makedirs(_d, exist_ok=True)
    except OSError:
        pass
sync_env_into(os.environ)


def _calib_py():
    """跑增量通道子命令的 Python：工具箱内嵌运行时优先，其次系统 python。

    拿不到可用解释器时返回 ""（调用方据此跳过），**绝不回退到 exe 自身**——
    打包后 sys.executable 就是本程序，拿它 Popen 会拉起一个新实例。
    """
    py = system_python()
    if not py or _is_self_exe(py) or not os.path.isfile(py):
        return ""
    return py


# ---------- GitHub 整文件通道（v1.12.2 恢复：收集各使用者校准增量） ----------
# 连接参数统一来自内置 github_proxy.yaml 的 vt-github 段（owner/repo/branch/
# api/token/files）；改仓库或加同步文件只动 yaml、不动代码。上传全部自动、
# 隐藏在后台完成（退出时自动推送）；界面只保留「更新」。
# 全程静默、直连失败回退内置 mihomo 代理、任何异常只写 logs/calib_sync.log，
# 绝不影响校准主流程。
GITHUB_PROXY_YAML = os.path.join(APP_DIR, "github_proxy.yaml")
#: yaml 缺失/解析失败时的兜底默认（与内置 yaml 的 vt-github 段一致）
_SYNC_CONN_DEFAULTS = {
    "owner": "09Th90", "repo": "VideoToolbox", "branch": "main",
    "api": "https://api.github.com", "token": "",
    "files": ["subtitle_calib_merged.py", "subtitle_learned_kb.json"],
}
#: 兼容旧引用（自检/文档仍以此名访问）；实际目标文件以 yaml files 段为准
SYNC_REL_PATH = _SYNC_CONN_DEFAULTS["files"][0]
SYNC_KB_REL_PATH = _SYNC_CONN_DEFAULTS["files"][1]
#: 上次同步成功内容快照 = 条目级三方合并的「公共祖先」（放数据根，不入库不分发）
CALIB_BASE_SNAPSHOT = os.path.join(DATA_DIR, "calib_sync_base.py")
CALIB_KB_BASE_SNAPSHOT = os.path.join(DATA_DIR, "calib_sync_kb_base.json")

_SYNC_CONN_CACHE = None


def _sync_conn(refresh=False):
    """读内置 github_proxy.yaml 的 vt-github 段（模块级缓存；缺字段用默认补齐）。"""
    global _SYNC_CONN_CACHE
    if _SYNC_CONN_CACHE is not None and not refresh:
        return _SYNC_CONN_CACHE
    cfg = {k: (list(v) if isinstance(v, list) else v)
           for k, v in _SYNC_CONN_DEFAULTS.items()}
    try:
        import yaml
        with open(GITHUB_PROXY_YAML, encoding="utf-8-sig") as f:
            data = yaml.safe_load(f) or {}
        vg = data.get("vt-github") or {}
        for key in ("owner", "repo", "branch", "api", "token"):
            val = str(vg.get(key) or "").strip()
            if val:
                cfg[key] = val
        files = vg.get("files")
        if isinstance(files, list) and files:
            cfg["files"] = [str(p).strip() for p in files if str(p).strip()]
    except Exception as e:  # noqa: BLE001  解析失败退回默认，不阻断同步
        _sync_log(f"读取 github_proxy.yaml 失败，改用内置默认连接：{e}")
    if not refresh:
        _SYNC_CONN_CACHE = cfg
    return cfg


def _gh_token(cfg=None):
    """取 GitHub token：内置 yaml 显式配置 > 环境变量 > gh keyring；取不到返回空串。"""
    cfg = cfg or _sync_conn()
    tok = (cfg.get("token") or "").strip()
    if tok:
        return tok
    tok = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if tok:
        return tok.strip()
    for exe in ("gh", os.path.join(TOOLS_DIR, "gh.exe")):
        try:
            p = run_process([exe, "auth", "token"], capture_output=True,
                            text=True, timeout=15)
            if p.returncode == 0 and p.stdout.strip():
                return p.stdout.strip()
        except (OSError, subprocess.SubprocessError):
            continue
    return ""


def _gh_request(method, path, token, payload=None, proxy="", timeout=30):
    """访问 GitHub API（用 curl，避开 requests 的代理问题）。返回 (ok, 数据或错误)。"""
    url = f"{_sync_conn()['api']}/{path}"
    cmd = ["curl", "-sS", "--max-time", str(timeout), "-X", method]
    if proxy:
        cmd += ["-x", proxy]
    if token:  # 公开库匿名读时不带认证头
        cmd += ["-H", f"Authorization: Bearer {token}"]
    cmd += ["-H", "Accept: application/vnd.github+json",
            "-H", "X-GitHub-Api-Version: 2022-11-28",
            "-H", "User-Agent: VideoToolbox-sync",
            "-w", "\n%{http_code}"]
    stdin = b""
    if payload is not None:
        cmd += ["-H", "Content-Type: application/json", "--data-binary", "@-"]
        stdin = json.dumps(payload).encode("utf-8")
    cmd.append(url)
    try:
        p = run_process(cmd, input=stdin, capture_output=True,
                        timeout=timeout + 10)
    except (OSError, subprocess.SubprocessError) as e:
        return False, f"curl 调用失败: {e}"
    if p.returncode != 0:
        return False, f"curl 退出码 {p.returncode}: {decode_bytes_any(p.stderr)[:150]}"
    body, _, code = decode_bytes_any(p.stdout).rpartition("\n")
    try:
        code = int(code.strip() or 0)
    except ValueError:
        code = 0
    if code >= 400:
        return False, f"HTTP {code}: {body[:200]}"
    try:
        return True, (json.loads(body) if body.strip() else {})
    except ValueError:
        return True, {}


def _gh_request_any(method, path, token, payload=None):
    """先直连，失败再走内置代理（仅 GitHub 流量）。认证/参数类错误不重试代理。"""
    ok, data = _gh_request(method, path, token, payload)
    if ok:
        return True, data
    msg = str(data)
    if any(code in msg for code in ("HTTP 401", "HTTP 403", "HTTP 404", "HTTP 422")):
        return False, data
    _sync_log(f"直连 {method} {path} 失败（{msg[:80]}），改用内置代理")
    proxy = ensure_builtin_proxy()
    if not proxy:
        return False, f"{data}；内置代理不可用"
    return _gh_request(method, path, token, payload, proxy=proxy)


def _gh_fetch_file(token, rel_path, cfg):
    """拉仓库单文件最新内容。返回 (ok, 文本或错误, blob_sha)；公开库可匿名读。"""
    path = (f"repos/{cfg['owner']}/{cfg['repo']}/contents/{rel_path}"
            f"?ref={cfg['branch']}")
    ok, data = _gh_request_any("GET", path, token)
    if not ok:
        return False, str(data), ""
    try:
        content = data.get("content")
        if not content and data.get("git_url"):
            blob_path = str(data["git_url"]).replace(cfg["api"] + "/", "")
            ok2, blob = _gh_request_any("GET", blob_path, token)
            if not ok2:
                return False, str(blob), ""
            data, content = blob, blob.get("content")
        text = decode_bytes_any(base64.b64decode(content or ""))
        return True, text, data.get("sha", "")
    except (ValueError, KeyError, TypeError, OSError) as e:
        return False, f"解码失败: {e}", ""


def _read_sync_text(path):
    """读同步目标文件（兼容 UTF-8/GBK/无 BOM）；不存在返回空串。"""
    try:
        return read_text_any(path)
    except OSError:
        return ""


def _atomic_write(path, text):
    """原子写回同步文件：先写同目录临时文件再 os.replace，避免半截文件。"""
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    tmp = path + ".vt_tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    os.replace(tmp, path)


def _pull_and_merge(token, rel_path, base_path, cfg):
    """拉远程单文件与本地做条目级三方合并，结果回写本地与基线。返回本地是否有更新。

    files 段第一个同步文件视为「校准脚本」（走 merge_calib_script），其余视为
    「学习库」（走 merge_learned_kb）。任何失败只记日志，绝不阻断启动/退出。"""
    is_script = (rel_path == cfg["files"][0])
    local_path = os.path.join(APP_DIR, rel_path)
    local_text = _read_sync_text(local_path)
    base_text = _read_sync_text(base_path)
    ok, remote_text, _sha = _gh_fetch_file(token, rel_path, cfg)
    if not ok:
        _sync_log(f"拉取[{rel_path}]跳过合并：{str(remote_text)[:100]}")
        return False
    if not local_text.strip():
        _atomic_write(local_path, remote_text)
        _atomic_write(base_path, remote_text)
        _sync_log(f"拉取[{rel_path}]：本地缺失，已采用远程版（{len(remote_text)} 字符）")
        return True
    if remote_text == local_text:
        if base_text != local_text:
            _atomic_write(base_path, local_text)
        return False
    if is_script:
        merged, added, conflicts = merge_calib_script(local_text, remote_text, base_text)
    else:
        merged, added, conflicts = merge_learned_kb(local_text, remote_text)
    if merged == local_text:
        if conflicts:
            _sync_log(f"合并[{rel_path}]：无可并入"
                      f"（{'; '.join(str(c) for c in conflicts)[:200]}）")
        return False
    _atomic_write(local_path, merged)
    _atomic_write(base_path, merged)
    n_conf = len(conflicts) if isinstance(conflicts, list) else conflicts
    _sync_log(f"合并[{rel_path}]：并入 {added} 条，冲突 {n_conf} 条（保留本地）")
    return True


def sync_calib_to_github(cfg=None):
    """把本地校准脚本与学习库推到 GitHub（推送前先拉远程合并；静默，返回 (ok, 说明)）。"""
    cfg = cfg or _sync_conn()
    token = _gh_token(cfg)
    if not token:
        _sync_log("跳过上传：未取得 GitHub token（需 gh auth login 或设 GH_TOKEN）")
        return False, "未取得 GitHub token"
    # 先拉远程把他人增量并进来再推，多用户互不覆盖、最终收敛到并集
    for idx, rel in enumerate(cfg["files"]):
        base_path = (CALIB_BASE_SNAPSHOT if idx == 0 else CALIB_KB_BASE_SNAPSHOT)
        _pull_and_merge(token, rel, base_path, cfg)
    # 声纹模板增量：与校准文件同走一条 GitHub 通道，但目录隔离——只有这里会搬运
    # vp_inbox/，校准的 files 段永远看不到它（反之亦然）。同一份 rtree 既用于
    # 拉他人增量、也用于判断本机哪些增量还没上去，省一次递归树请求。
    rtree, n_vp_pull = {}, 0
    try:
        rtree = _gh_remote_tree(cfg, token) or {}
        n_vp_pull = _gh_pull_vp_inbox(cfg, token, rtree)
    except Exception as e:  # noqa: BLE001  声纹失败不影响校准知识上传
        _sync_log(f"声纹收件箱拉取异常（忽略）: {e}")
    entries = []  # (rel, bytes, text)
    for rel in cfg["files"]:
        try:
            with open(os.path.join(APP_DIR, rel), "rb") as f:
                b = f.read()
            entries.append((rel, b, decode_bytes_any(b)))
        except (OSError, UnicodeDecodeError) as e:
            if rel == cfg["files"][0]:
                _sync_log(f"跳过上传：读取失败 {e}")
                return False, f"读取失败: {e}"
            _sync_log(f"上传[{rel}]跳过：{e}")
    base = f"repos/{cfg['owner']}/{cfg['repo']}"
    ok, head = _gh_request_any("GET", f"{base}/git/ref/heads/{cfg['branch']}", token)
    if not ok:
        _sync_log(f"失败：读取分支 head {head}")
        return False, f"读取分支失败: {head}"
    head_sha = head["object"]["sha"]
    ok, commit = _gh_request_any("GET", f"{base}/git/commits/{head_sha}", token)
    if not ok:
        return False, f"读取 commit 失败: {commit}"
    base_tree = commit["tree"]["sha"]
    tree_entries = []
    for rel, b, _text in entries:
        ok, blob = _gh_request_any("POST", f"{base}/git/blobs", token, {
            "content": base64.b64encode(b).decode("ascii"), "encoding": "base64"})
        if not ok:
            return False, f"创建 blob 失败: {blob}"
        tree_entries.append({"path": rel, "mode": "100644",
                             "type": "blob", "sha": blob["sha"]})
    # 声纹增量：远端没有的本机文件才上传（文件名含 cid+时间戳+随机 hex，撞名即同一次推送）
    vp_entries, n_vp_push = [], 0
    try:
        vp_entries, n_vp_push = _gh_push_vp_inbox(cfg, token, rtree)
    except Exception as e:  # noqa: BLE001  声纹失败不影响校准知识上传
        _sync_log(f"声纹增量上传异常（忽略）: {e}")
    tree_entries.extend(vp_entries)
    if not tree_entries:
        _sync_log("跳过上传：无内容可提交")
        return True, "无变更"
    ok, tree = _gh_request_any("POST", f"{base}/git/trees", token, {
        "base_tree": base_tree, "tree": tree_entries})
    if not ok:
        return False, f"创建 tree 失败: {tree}"
    ok, new_commit = _gh_request_any("POST", f"{base}/git/commits", token, {
        "message": (f"chore(calib): 同步校准知识{'与声纹模板' if n_vp_push else ''} "
                    f"（{datetime.now():%Y-%m-%d %H:%M:%S}，来自视频工具箱）"),
        "tree": tree["sha"], "parents": [head_sha]})
    if not ok:
        return False, f"创建 commit 失败: {new_commit}"
    ok, res = _gh_request_any("PATCH", f"{base}/git/refs/heads/{cfg['branch']}",
                              token, {"sha": new_commit["sha"], "force": False})
    if not ok:
        return False, f"更新分支失败: {res}"
    _sync_log(f"成功：已上传 {len(entries)} 个文件"
              f"（另声纹模板 +{n_vp_push} / 拉取 {n_vp_pull}）-> "
              f"{cfg['owner']}/{cfg['repo']}@{cfg['branch']} "
              f"commit {new_commit['sha'][:12]}")
    # 推送成功：基线快照对齐本次内容（下次三方合并的公共祖先）
    for idx, (rel, _b, text) in enumerate(entries):
        try:
            _atomic_write(CALIB_BASE_SNAPSHOT if idx == 0
                          else CALIB_KB_BASE_SNAPSHOT, text)
        except OSError as e:
            _sync_log(f"基线快照写入失败[{rel}]（忽略）: {e}")
    return True, f"已上传 commit {new_commit['sha'][:12]}"


# ---------- 本地增量镜像（可选：管理员配了共享盘更新库才启用） ----------
def _local_delta_enabled():
    """VT_SYNC_ROOT 下存在 baseline.json 才启用 kb-sync/kb-push 增量镜像。"""
    try:
        root = os.environ.get("VT_SYNC_ROOT") or SYNC_REMOTE_DIR
        return os.path.isfile(os.path.join(root, "baseline.json"))
    except OSError:
        return False


def sync_calib_push_local():
    """退出子进程内部调用：把学习库新增增量写进本地更新库收件箱（若启用镜像）。"""
    try:
        if not _local_delta_enabled():
            return
        py = _calib_py()
        if not py or not os.path.isfile(CALIB_SCRIPT):
            return
        env = sync_env_into(os.environ.copy())
        env.setdefault("PYTHONIOENCODING", "utf-8")
        run_process([py, CALIB_SCRIPT, "kb-push", "--learned", CALIB_KB_PATH],
                    capture_output=True, text=True, encoding="utf-8",
                    errors="replace", timeout=120, cwd=APP_DIR, env=env)
    except Exception as e:  # noqa: BLE001
        _sync_log(f"本地增量上传异常（忽略）: {e}")


def _exit_sync_child_script():
    """退出子进程入口源码：本地增量补传（若启用镜像）+ GitHub 整文件上传。"""
    src_dir = os.path.join(APP_DIR, "src")
    # ⚠ 顺序要紧：先把待传声纹冲进本地 vp_inbox（纯本地、秒级），再跑 GitHub
    #   上传——否则本次录入的模板要等下一次退出才进得了仓库。
    return ("import sys; sys.path.insert(0, r'%s');"
            "import video_toolbox as e;"
            "e.sync_voiceprint_on_exit();"
            "e.sync_calib_push_local();"
            "e.sync_calib_to_github()" % src_dir)


def sync_calib_on_startup(force=False):
    """更新：从 GitHub 拉全体使用者沉淀并条目级合并进本地；可选叠加本地增量镜像。

    幂等、静默、best-effort；任何失败只写日志，本地校准功能照常可用。
    force 为兼容设置页「立即更新」参数，可忽略。"""
    try:
        if os.environ.get("VT_NO_CALIB_SYNC") or not calib_sync_enabled():
            return False, "同步已禁用"
        updated, notes = False, []
        # 1) GitHub 整文件通道（默认收集渠道；公开库可匿名读）
        cfg = _sync_conn()
        token = _gh_token(cfg)
        for idx, rel in enumerate(cfg["files"]):
            base_path = (CALIB_BASE_SNAPSHOT if idx == 0 else CALIB_KB_BASE_SNAPSHOT)
            if _pull_and_merge(token, rel, base_path, cfg):
                updated = True
                notes.append(rel)
        # 2) 本地增量镜像（管理员配置了共享盘更新库时）
        py = _calib_py()
        if py and os.path.isfile(CALIB_SCRIPT) and _local_delta_enabled():
            env = sync_env_into(os.environ.copy())
            env.setdefault("PYTHONIOENCODING", "utf-8")
            try:
                p = run_process([py, CALIB_SCRIPT, "kb-sync"],
                                capture_output=True, text=True, encoding="utf-8",
                                errors="replace", timeout=180, cwd=APP_DIR, env=env)
                if p.returncode == 0:
                    updated = True
                    notes.append("本地增量")
                else:
                    _sync_log(f"本地增量更新失败（降级）：rc={p.returncode}")
            except Exception as e:  # noqa: BLE001
                _sync_log(f"本地增量更新异常（忽略）: {e}")
        if updated:
            _sync_log("更新完成：" + "、".join(notes))
            return True, "校准知识已更新（" + "、".join(notes) + "）"
        return False, "无可用更新或已是最新"
    except Exception as e:  # noqa: BLE001
        _sync_log(f"更新异常（忽略）: {e}")
        return False, str(e)


def sync_calib_on_exit():
    """退出时自动上传：派生隐藏子进程完成「本地增量补传 + GitHub 整文件上传」。

    用子进程而非线程：主进程退出后线程会被强杀，子进程能自行跑完。
    上传对用户完全无感——不阻塞退出、不弹窗、不出现在任何界面。"""
    try:
        if os.environ.get("VT_NO_CALIB_SYNC") or not calib_sync_enabled():
            return
        py = _calib_py()
        if not py:
            _sync_log("退出上传跳过：无可用 Python 运行时")
            return
        env = sync_env_into(os.environ.copy())
        env.setdefault("PYTHONIOENCODING", "utf-8")
        popen_process([py, "-c", _exit_sync_child_script()],
                      stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                      stderr=subprocess.DEVNULL, cwd=APP_DIR, env=env,
                      close_fds=True)
        _sync_log("已派生退出上传子进程（GitHub 整文件 + 本地增量）")
    except Exception as e:  # noqa: BLE001
        _sync_log(f"派生退出上传子进程失败（忽略）: {e}")


# ---------- 声纹模板同步（独立通道；与上面的校准知识同步互不干涉） ----------
# 数据形态、生命周期与责任边界都不同（192 维向量 / 重录与删除是常态 / 无基线
# 概念），故自成一套：schema、确定性合并、落地裁决、待传队列、状态目录与 CLI
# 全在 src\voiceprint_sync.py，只共用哑存储根的 vp_inbox\ 子目录作传输
# （校准通道只枚举 inbox\，两边永远看不到对方的条目）。
# 用户侧开关沿用同一个「校准同步」设置项（避免设置页多一个语义重叠的开关），
# 另有独立环境变量 VT_NO_VP_SYNC 可单独关停声纹通道。
VP_SYNC_LOG = os.path.join(LOGS_DIR, "vp_sync.log")
#: 声纹增量在仓库里的子目录（与 voiceprint_sync.INBOX_SUB 同名，挂在哑存储根下）
VP_INBOX_SUB = "vp_inbox"
#: 单次同步最多搬运的声纹增量文件数（防目录异常膨胀把启动/退出拖成网络风暴）
VP_INBOX_MAX_FILES = 200


def _vp_inbox_local_files():
    """本机哑存储根下的声纹增量 -> [(仓库相对路径, 绝对路径)]（按路径排序，确定性）。"""
    base = os.path.join(SYNC_REMOTE_DIR, VP_INBOX_SUB)
    out = []
    if not os.path.isdir(base):
        return out
    for cid in sorted(os.listdir(base)):
        d = os.path.join(base, cid)
        if not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            p = os.path.join(d, fn)
            if fn.endswith(".jsonl") and os.path.isfile(p):
                out.append(("%s/%s/%s" % (VP_INBOX_SUB, cid, fn), p))
    return out


def _gh_remote_tree(cfg, token):
    """拉远端分支整树 -> {path: blob_sha}（只收 blob）；失败返回 None。

    ⚠ `?recursive=1` 是必须的：不带它只能拿到第一层目录，vp_inbox/<cid>/ 下的
    文件一个都看不到，声纹就永远同步不到。"""
    base = "repos/%s/%s" % (cfg["owner"], cfg["repo"])
    ok, ref = _gh_request_any("GET", "%s/git/ref/heads/%s" % (base, cfg["branch"]),
                              token)
    if not ok:
        return None
    ok, commit = _gh_request_any(
        "GET", "%s/git/commits/%s" % (base, (ref or {}).get("object", {}).get("sha", "")),
        token)
    if not ok:
        return None
    ok, tree = _gh_request_any(
        "GET", "%s/git/trees/%s?recursive=1"
        % (base, (commit or {}).get("tree", {}).get("sha", "")), token)
    if not ok:
        return None
    return {t.get("path"): (t.get("sha") or "")
            for t in ((tree or {}).get("tree") or [])
            if t.get("type") == "blob" and t.get("path")}


def _gh_pull_vp_inbox(cfg, token, tree=None):
    """把远端收件箱里本机没有的声纹增量拉进哑存储根。返回拉取文件数。

    「只新建、绝不改写」与 voiceprint_sync 的收件箱语义一致：文件名带
    client_id + UTC 时间戳 + 随机 hex，同名必然是同一次推送、内容相同。
    写盘用临时文件 + os.replace，避免拉到一半被中断留下半截文件。
    任何失败只记日志——没有声纹增量不影响校准知识同步。"""
    if tree is None:
        tree = _gh_remote_tree(cfg, token)
    if not tree:
        return 0
    want = [(p, s) for p, s in sorted(tree.items())
            if p.startswith(VP_INBOX_SUB + "/") and p.endswith(".jsonl")]
    if not want:
        return 0
    base = "repos/%s/%s" % (cfg["owner"], cfg["repo"])
    n = 0
    for rel, sha in want[:VP_INBOX_MAX_FILES]:
        dst = os.path.join(SYNC_REMOTE_DIR, rel.replace("/", os.sep))
        if os.path.isfile(dst) or not sha:
            continue
        ok, blob = _gh_request_any("GET", "%s/git/blobs/%s" % (base, sha), token)
        if not ok:
            continue
        try:
            raw = base64.b64decode((blob or {}).get("content") or "")
        except (ValueError, TypeError):
            continue
        if not raw.strip():
            continue
        try:
            # ⚠ 必须按**字节**落盘：文本模式下 Windows 会把远端文件里已有的
            #   \r\n 再转成 \r\r\n（实测往返内容不一致的根因）。原样写才能
            #   保证多客户端间逐字节一致。
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            tmp = dst + ".vt_tmp"
            with open(tmp, "wb") as f:
                f.write(raw)
            os.replace(tmp, dst)
            n += 1
        except OSError:
            continue
    if n:
        _sync_log("声纹收件箱：拉取 %d 个增量文件" % n)
    return n


def _gh_push_vp_inbox(cfg, token, tree):
    """把本机新增的声纹增量做成 tree 条目。返回 (条目列表, 上传数)。

    远端已有的跳过——文件名含 client_id + 时间戳 + 随机 hex，撞名即同一次
    推送，内容必然相同；这样每次退出只为真正的新增量付 API 调用。"""
    if not tree:
        return [], 0
    base = "repos/%s/%s" % (cfg["owner"], cfg["repo"])
    out, n = [], 0
    for rel, abs_p in _vp_inbox_local_files():
        if rel in tree:
            continue
        if len(out) >= VP_INBOX_MAX_FILES:
            break
        try:
            with open(abs_p, "rb") as f:
                b = f.read()
        except OSError:
            continue
        if not b.strip():
            continue
        ok, blob = _gh_request_any("POST", "%s/git/blobs" % base, token, {
            "content": base64.b64encode(b).decode("ascii"), "encoding": "base64"})
        if not ok:
            _sync_log("声纹增量上传跳过[%s]：%s" % (rel, str(blob)[:80]))
            continue
        out.append({"path": rel, "mode": "100644", "type": "blob",
                    "sha": blob["sha"]})
        n += 1
    return out, n


def _vp_sync_log(msg):
    try:
        os.makedirs(LOGS_DIR, exist_ok=True)
        with open(VP_SYNC_LOG, "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")
    except OSError:
        pass


def sync_voiceprint_on_startup(force=False):
    """启动：把其他客户端录入的主播声纹模板拉下来落地（幂等、静默、best-effort）。

    与 `sync_calib_on_startup` 各自独立：不共用子进程、不共用日志、失败互不影响。
    返回 (是否更新, 说明) 以兼容设置页「立即更新」的回调口径。"""
    try:
        if os.environ.get("VT_NO_CALIB_SYNC") or not calib_sync_enabled():
            return False, "同步已禁用"
        # 先把远端收件箱搬进本地哑存储根，再让 voiceprint_sync 合并落地。
        # ⚠ vp_inbox/ 不在 cfg["files"] 里，校准通道不会替我们搬——少了这一步，
        #   声纹就只在本机打转（v1.19.0 的「声纹库没共享」就是漏了它）。
        try:
            _cfg = _sync_conn()
            _gh_pull_vp_inbox(_cfg, _gh_token(_cfg))
        except Exception as _e:  # noqa: BLE001
            _vp_sync_log(f"声纹收件箱拉取异常（忽略）: {_e}")
        import voiceprint_sync as _vps
        if not _vps.enabled():
            return False, "声纹同步已单独禁用（VT_NO_VP_SYNC）"
        # ⚠⚠ 在「拉取收件箱」之后、「合并落地」之前，把**待传队列冲刷一遍**
        #   （2026-10-13 补）：
        #   退出推送只挂在 QApplication.aboutToQuit 上，进程被强杀 / 崩溃 /
        #   taskkill 时它根本不触发——实测安装版 08:43、08:50 录入的两个声纹
        #   就因此一直卡在 data/vp_sync/voiceprint_pending.jsonl（vp_sync.log
        #   停在 07:33，其后只有校准的退出上传记录，没有任何「退出推送」行；
        #   同一时刻残留的孤儿 mihomo.exe 亦印证是异常终止）。
        #   启动时补一次，队列即自愈：强杀只影响「本次到上次启动之间」的增量，
        #   且下一次启动必补上。push 只写本地哑存储根，不联网、不阻塞启动。
        try:
            _n_pushed = _vps.push(quiet=True)
            if _n_pushed:
                _vp_sync_log(f"启动补推 %d 条声纹增量（上次未正常退出遗留）"
                             % _n_pushed)
        except Exception as _e:  # noqa: BLE001
            _vp_sync_log(f"启动补推异常（忽略）: {_e}")
        ok = _vps.sync(quiet=True)
        s = _vps.status()
        _vp_sync_log(f"启动同步{'完成' if ok else '跳过（无远端/未启用）'}："
                     f"模板 {s['templates']}（同步副本 {s['synced']}）、"
                     f"待传 {s['pending']}、冲突 {s['conflicts']}")
        return ok, ("声纹模板已同步" if ok else "无声纹更新")
    except Exception as e:  # noqa: BLE001
        _vp_sync_log(f"启动同步异常（忽略）: {e}")
        return False, str(e)


def sync_voiceprint_on_exit():
    """退出：把本机录入/重录/删除产生的声纹增量推进通道。

    直接在本进程做（纯标准库、只有本地文件写，通常几条），**不派生子进程**——
    与校准退出上传（要跑 GitHub 网络请求，故用子进程）不同。失败只写日志，
    绝不阻塞退出。"""
    try:
        if os.environ.get("VT_NO_CALIB_SYNC") or not calib_sync_enabled():
            return
        import voiceprint_sync as _vps
        if not _vps.enabled():
            return
        n = _vps.push(quiet=True)
        if n:
            _vp_sync_log(f"退出推送 {n} 条声纹增量")
    except Exception as e:  # noqa: BLE001
        _vp_sync_log(f"退出推送异常（忽略）: {e}")


# ---------- 条目级三方合并（v1.10.8：纯函数核心抽到 calib_merge_core） ----------
# 多用户知识收敛的合并算法是纯函数、零副作用，统一放在 calib_merge_core，
# 便于 GUI 引擎、退出同步子进程与脚本/CI 复用；这里只做导入并保留向后兼容
# 别名（自检与外部仍以 engine.merge_* 调用），并把合并期日志接到同步日志。
#
# 同步语义保持 v1.10.7 的对等并集模型（用户最终拍板，不采用 contrib/CI
# 中心化方案）：启动自动拉取 GitHub main 最新校准知识并把其他用户沉淀的
# 新条目并入本地；退出时先把远程新内容并进来再推送，多用户互不覆盖，
# 所有人的脚本最终收敛到全体条目的并集。
from calib_merge_core import (
    _MERGE_MISSING,
    _ast_module_tables,
    _dict_entries,
    _entity_fields,
    _registry_conflicts,
    merge_calib_script,
    merge_learned_kb,
)
import calib_merge_core as _calib_core
_calib_core._log = _sync_log  # 合并期冲突日志写入 logs/calib_sync.log


# ========== 下载字幕的「滚动式重叠」整理（v1.13.7） ==========
# 平台（YouTube 等）给出的自动字幕是**滚动**结构：同一条的结束时间会一直延伸
# 到"下一条的结束"，于是整份字幕大面积互相压住（实测某 3566 条的字幕里有
# 3028 条与下一条重叠，占比 84.9%）。后果是播放时同一时刻两条并行、切轴抖动，
# 后续翻译与打轴也跟着错乱。
#
# 整理方式只有一件事：把每条压到"下一条的起始"。文本、起始时间、序号、空行、
# 换行风格（CRLF/LF）、BOM 全部原样保留 —— 实测这样处理后的结果与用户手工整理
# 出来的"正确字幕"逐条一致（3566/3566）。
_SRT_TL_RE = re.compile(
    r"^(?P<pre>[ \t]*)(?P<t1>\d{1,2}:\d{2}:\d{2}[,.]\d{1,3})"
    r"(?P<sep>[ \t]*-->[ \t]*)"
    r"(?P<t2>\d{1,2}:\d{2}:\d{2}[,.]\d{1,3})(?P<post>.*)$")
_SRT_TS_RE = re.compile(r"(\d{1,2}):(\d{2}):(\d{2})([,.])(\d{1,3})")

#: 判定"滚动式字幕"的门槛：重叠占比 + 重叠条数 + 最少条数。
#: 保守取值，避免误伤"双人对话/双语对齐"这类**有意**重叠的普通字幕。
_ROLLING_RATIO = 0.15
_ROLLING_MIN_OVERLAP = 4
_ROLLING_MIN_CUES = 8


def srt_time_to_ms(text):
    """`00:01:02,345` / `00:01:02.345` → 毫秒；解析不了返回 None。"""
    m = _SRT_TS_RE.search(str(text or ""))
    if not m:
        return None
    h, mi, s, _dot, frac = m.groups()
    return (int(h) * 3600 + int(mi) * 60 + int(s)) * 1000 + int(frac.ljust(3, "0"))


def ms_to_srt_time(ms, sep=",", frac=3):
    """毫秒 → `00:01:02,345`；`frac` 保留原文件的小数位数。"""
    ms = max(0, int(ms))
    h, rem = divmod(ms, 3600000)
    mi, rem = divmod(rem, 60000)
    s, f = divmod(rem, 1000)
    digits = ("%03d" % f)[:frac].ljust(frac, "0")
    return "%02d:%02d:%02d%s%s" % (h, mi, s, sep, digits)


def normalize_rolling_srt(path, dry_run=False, stats=None):
    """把「滚动式」字幕整理成不重叠的常规 SRT（原地改写）；命中则返回 True。

    只改**结束时间**。判定门槛见 `_ROLLING_*`：只有大范围重叠才动手，
    条数太少或只是零散重叠的文件原样不动（那多半是有意的重叠）。

    `dry_run=True` 时只判断、不落盘（返回"本来会改"），供体检工具用；
    `stats` 传 dict 会填进 cues / overlaps / ratio / fixed 便于报告。
    任何异常都吞掉并返回 False —— 整理失败绝不能影响"下载已成功"这个事实。
    """
    try:
        with open(path, "rb") as f:
            raw = f.read()
    except OSError:
        return False
    if not raw:
        return False
    bom = raw.startswith(codecs.BOM_UTF8)
    text = decode_bytes_any(raw)
    if "\r\n" in text:
        nl, text = "\r\n", text.replace("\r\n", "\n")
    elif "\r" in text:
        nl, text = "\r", text.replace("\r", "\n")
    else:
        nl = "\n"

    lines = text.split("\n")
    cues = []      # (行号, 起始 ms, 结束 ms, 结束列起, 结束列止, 分隔符, 小数位)
    for i, line in enumerate(lines):
        m = _SRT_TL_RE.match(line)
        if not m or m.group("pre"):
            # 行首要空格的（缩进）一律不认：真时间轴行都从第 0 列开始，
            # 这样也不会误伤正好长成时间轴的**正文**
            continue
        start_ms = srt_time_to_ms(m.group("t1"))
        end_ms = srt_time_to_ms(m.group("t2"))
        if start_ms is None or end_ms is None:
            continue
        sep = "," if "," in m.group("t2") else "."
        frac = len(m.group("t2").split(sep)[-1])
        cues.append((i, start_ms, end_ms,
                     m.start("t2"), m.end("t2"), sep, frac))

    n = len(cues)
    if stats is not None:
        stats["cues"] = n
    if n < _ROLLING_MIN_CUES:
        if stats is not None:
            stats.update(overlaps=0, ratio=0.0, fixed=0)
        return False
    overlaps = sum(1 for k in range(n - 1) if cues[k][2] > cues[k + 1][1])
    if stats is not None:
        stats.update(overlaps=overlaps, ratio=overlaps / float(n - 1))
    if overlaps < _ROLLING_MIN_OVERLAP:
        if stats is not None:
            stats["fixed"] = 0
        return False
    if overlaps / float(n - 1) < _ROLLING_RATIO:
        if stats is not None:
            stats["fixed"] = 0
        return False

    edits = []     # (行号, 起列, 止列, 新文本)
    for k in range(n - 1):
        line_no, start_ms, end_ms, c0, c1, sep, frac = cues[k]
        next_start = cues[k + 1][1]
        if next_start <= start_ms or end_ms <= next_start:
            continue          # 起始倒挂 / 本来就不重叠：不动
        edits.append((line_no, c0, c1, ms_to_srt_time(next_start, sep, frac)))
    if stats is not None:
        stats["fixed"] = len(edits)
    if not edits:
        return False
    if dry_run:
        return True

    for line_no, c0, c1, new in reversed(edits):
        lines[line_no] = lines[line_no][:c0] + new + lines[line_no][c1:]
    out = nl.join(lines)
    data = out.encode("utf-8")
    if bom:
        data = codecs.BOM_UTF8 + data

    tmp = path + ".vtnew"
    try:
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass
        return False
    return True


# ========== 主入口 ==========
def main():
    print("=" * 60)
    print("  视频工具箱 v1.6.0")
    print("  [1] 视频下载（链接 -> 选画质 -> mp4，每视频独立文件夹）")
    print("  [2] 音视频智能合并（mp4 + m4a/weba + srt/ass）")
    print("=" * 60)

    arg = clean_path(sys.argv[1]) if len(sys.argv) >= 2 else ""

    try:
        if arg:
            if os.path.isdir(arg):
                # 拖入文件夹 -> 合并模式
                merge_mode(arg)
            else:
                # 拖入链接/文件 -> 下载模式
                url = extract_url(arg)
                if url:
                    download_mode(url)
                else:
                    print("[错误] 无法识别拖入的内容（不是链接也不是文件夹）")
        else:
            choice = input("选择功能 [1/2，回车 = 1]: ").strip() or "1"
            if choice == "2":
                merge_mode()
            else:
                download_mode()
    except KeyboardInterrupt:
        print("\n[取消] 用户中断")

    input("\n按回车键退出...")


if __name__ == "__main__":
    main()
