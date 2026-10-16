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


# ---------- v1.14.1 起：ASR 服务模式全协议适配 ----------

#: 支持的协议（= 配置里 asr_protocol 的取值；auto 为自动识别）
#: ⚠️ `dashscope` 是历史键：它其实就是 chat_audio 那一族（百炼兼容模式），
#:    保留是为了让老配置继续能用，新推断一律产出 `chat_audio`。
ASR_PROTOCOLS = ("auto", "openai", "azure", "chat_audio", "dashscope",
                 "deepgram", "elevenlabs", "gemini",
                 "volcengine", "assemblyai", "dashscope_realtime",
                 "dashscope_native", "dashscope_filetrans")

#: 协议说明（供界面下拉提示与日志引用）
ASR_PROTOCOL_NOTES = {
    "openai": "OpenAI Whisper 兼容（multipart /audio/transcriptions）——"
              "覆盖 OpenAI / 硅基流动 / Groq / Fireworks / DeepInfra / "
              "Mistral Voxtral / 自建 whisper.cpp、faster-whisper 服务等",
    "azure": "Azure OpenAI（deployments 端点 + api-key 头）",
    "chat_audio": "OpenAI 兼容 chat/completions + input_audio（音频以 Data URL "
                  "传入）——阿里云百炼 Qwen-ASR（qwen3-asr-flash）、"
                  "小米 MiMo（mimo-v2.5-asr）等",
    "dashscope": "同 chat_audio（历史键，保留兼容）",
    "deepgram": "Deepgram（POST /v1/listen，Authorization: Token + 原始音频，"
                "带词级时间轴）",
    "elevenlabs": "ElevenLabs Scribe（POST /v1/speech-to-text，xi-api-key，"
                  "带词级时间轴）",
    "gemini": "Google Gemini（generateContent + inline_data，返回纯文本，"
              "时间轴按句兜底）",
    "volcengine": "火山引擎（豆包）录音识别极速版——一次请求即返回，本地文件"
                  "直传；密钥填「APPID:AccessToken」或新版 API Key，"
                  "模型填 Resource ID（默认 volc.bigasr.auc_turbo）",
    "assemblyai": "AssemblyAI（上传 → 提交 → 轮询；Authorization 头**不带** "
                  "Bearer，模型名可逗号分隔多个做回退，带词级时间轴）",
    "dashscope_realtime": "百炼实时（WebSocket）——把本地音频切片推给 "
                          "wss://…/api-ws/v1/inference/，覆盖**只有实时形态**"
                          "的模型（fun-asr-flash-8k-realtime / fun-asr-realtime"
                          " / qwen3-asr-flash-realtime 等），带原生句级时间轴",
    "dashscope_filetrans":
        "百炼 Filetrans 异步文件转写（提交 → 轮询，POST /api/v1/services/"
        "audio/asr/transcription）——模型名带 -filetrans；⚠️ 不收本地音频，"
        "会先把音频传到百炼临时存储再转写（官方标注勿用于生产环境）；"
        "说话人分离仅支持单声道、建议 ≤2 小时",
    "dashscope_native": "百炼原生录音文件识别（POST /api/v1/services/aigc/"
                        "multimodal-generation/generation）——Qwen-Audio-3.0-ASR-"
                        "Flash（qwen-audio-3.0-asr-flash）等**不走兼容模式**的 "
                        "ASR 模型专用；音频以 base64 Data URL 传入，响应含词级"
                        "时间轴（output.sentence.words）",
}

#: 实时（WebSocket 流式）模型的识别特征：这些模型**不能**一次性上传调用
ASR_REALTIME_HINTS = ("realtime", "-rt-", "streaming")

#: 实时模型里属于「录音转写」族的关键词：名字带 realtime 但确实是语音识别
#: 模型（百炼实时协议可用）。livetranslate 这类实时**对话/翻译**模型不在此
#: 族——任何协议都拿它做不了转写，必须提前拦下给改法。
_REALTIME_ASR_FAMILY = ("asr", "paraformer", "sensevoice", "whisper",
                        "stt", "transcri")


def is_realtime_asr_family(model: str) -> bool:
    """是否「实时语音识别」族模型（区别于实时对话/翻译模型）。"""
    m = str(model or "").lower()
    if not any(h in m for h in ASR_REALTIME_HINTS):
        return False
    return any(k in m for k in _REALTIME_ASR_FAMILY)


_TTS_HINTS = ("tts", "speech-synthesis", "voice-synthesis", "cosyvoice",
              "sambert")

#: 百炼**原生**（multimodal-generation）录音文件识别模型特征：qwen-audio 系带
#: asr 的即时模型。实测（2026-09-20）：qwen-audio-3.0-asr-flash 官方文档给的就是
#: 原生端点，拿兼容模式的 chat/completions 打它**恒回 HTTP 400 空体**——同一个
#: 模型、同一份音频，换端点即 200 并返回词级时间轴。filetrans（异步，需公网
#: URL）与 realtime 不在此列。
def is_dashscope_native_asr(model) -> bool:
    m = str(model or "").lower()
    if not m or "filetrans" in m or any(h in m for h in ASR_REALTIME_HINTS):
        return False
    return "qwen-audio" in m and "asr" in m


#: 百炼原生 ASR 的官方 API 路径（与 compatible-mode 不是同一个端点）
ASR_NATIVE_PATH = "/api/v1/services/aigc/multimodal-generation/generation"


def _asr_native_url(base_url):
    """从「接口地址」推导百炼原生 ASR 端点（只换路径，不换域名）。

    · 已填原生端点 → 原样；
    · 填 compatible-mode/v1 或只填域名 → 同域名 + 官方 API 路径；
    · 留空 → 公共百炼 dashscope.aliyuncs.com + 官方 API 路径。
    """
    b = asr_strip_endpoint_tail(str(base_url or "").strip())
    low = b.lower()
    if low.endswith(ASR_NATIVE_PATH.lower()):
        return b
    if not b:
        return "https://dashscope.aliyuncs.com" + ASR_NATIVE_PATH
    if "//" in b:
        scheme, rest = b.split("//", 1)
        return scheme + "//" + rest.split("/", 1)[0] + ASR_NATIVE_PATH
    return "https://" + b.split("/", 1)[0] + ASR_NATIVE_PATH


def asr_model_hard_guard(model: str) -> str:
    """模型与「录音转写」根本不符的硬守卫：**不论协议**都返回提示（可放行空串）。

    覆盖两类（v1.15.5 实测各踩一次）：
      · 实时对话/翻译模型（livetranslate 族）：名字带 realtime 但不是转写；
      · 语音合成（TTS）模型（qwen-audio-3.0-tts-plus 等）：输出音频不收音频。
    两类走任何协议都转写不了（WS 被拒后降级文件上传只回 HTTP 400/500 空
    体），所以无条件拦，并在提示里给出录音文件识别模型与套餐专属端点。
    """
    m = str(model or "").lower()
    if any(h in m for h in ASR_REALTIME_HINTS) and not is_realtime_asr_family(m):
        return ("模型「%s」是实时对话/翻译模型（名字带 realtime 但不是录音转写"
                "模型），语音转写用不了它。请改录音文件识别模型：百炼 "
                "qwen3-asr-flash / qwen-audio-3.0-asr-flash（原生端点）/ "
                "fun-asr-flash、硅基流动 "
                "FunAudioLLM/SenseVoiceSmall、OpenAI whisper-1；订阅套餐还要"
                "端点配套：百炼按量 dashscope.aliyuncs.com/compatible-mode/v1、"
                "Token Plan token-plan.cn-beijing.maas.aliyuncs.com/"
                "compatible-mode/v1" % model)
    if any(k in m for k in _TTS_HINTS):
        return ("模型「%s」是语音合成（TTS）模型——它输出音频、不收音频，做不了"
                "语音转写。请改录音文件识别模型：百炼 qwen3-asr-flash / "
                "qwen-audio-3.0-asr-flash（原生端点）/ fun-asr-flash、硅基流动 "
                "FunAudioLLM/SenseVoiceSmall、OpenAI whisper-1" % model)
    return ""


def _host_path(base: str):
    """拆出 (host, 路径) 小写形式，供各端点守卫判断域名与路径段。"""
    b = str(base or "").strip().rstrip("/").lower()
    if "//" in b:
        b = b.split("//", 1)[1]
    host, _, path = b.partition("/")
    return host, ("/" + path) if path else ""


def _is_anthropic_only_path(base: str) -> bool:
    """火山方舟 Anthropic 协议专用端点：/api/coding、/api/compatible。

    这两个地址不含 "anthropic" 字样却只收 Anthropic 协议——旧守卫只认
    "anthropic" 关键词时拦不住，OpenAI 请求打上去必 404/400。该平台的
    OpenAI 协议端点是 /api/v3（按量）与 /api/coding/v3（Coding Plan）。
    """
    host, path = _host_path(base)
    if "volces.com" not in host and "volcengine" not in host:
        return False
    return path.rstrip("/").endswith(("/api/coding", "/api/compatible"))


#: 「完整端点」的常见尾巴 —— 用户从服务商文档抄地址时容易连路径一起抄进来
ASR_ENDPOINT_TAILS = ("/audio/transcriptions", "/audio/translations",
                      "/chat/completions", "/v2/upload", "/v2/transcript",
                      "/api/v1/services/aigc/multimodal-generation/generation")


def asr_strip_endpoint_tail(base, *tails):
    """削掉"用户把**完整端点**抄进地址栏"的那截尾巴。

    为什么要削：无论 OpenAI SDK 还是我们自己的拼接，都是「base + 固定路径」
    的写法，而服务商文档给的常常是完整 URL —— 例如智谱的
    `https://open.bigmodel.cn/api/paas/v4/audio/transcriptions`。照抄进去就会
    拼成 `.../audio/transcriptions/audio/transcriptions` → 404。
    宁可在这里削一次，也不该让用户对着 404 猜。

    不传 tails 时按 `ASR_ENDPOINT_TAILS` 里的常见端点尾巴削。
    """
    tails = tails or ASR_ENDPOINT_TAILS
    b = str(base or "").strip().rstrip("/")
    changed = True
    while changed and b:
        changed = False
        low = b.lower()
        for tail in tails:
            t = str(tail or "").strip().lower().rstrip("/")
            if t and low.endswith(t):
                b = b[: -len(t)].rstrip("/")
                changed = True
                break
    return b


def _infer_asr_protocol(base_url, model):
    """按地址与模型名推断协议（auto 档的唯一实现）。

    顺序有讲究：先认**域名独有的**服务（小米 MiMo / deepgram / elevenlabs /
    gemini），再认 Azure，最后才是"看着像 OpenAI 兼容"的兜底。

    ⚠️ 「chat/completions + input_audio」这族（百炼 Qwen-ASR、小米 MiMo ASR）
    必须与 `openai` 分开：这类服务**没有** `/audio/transcriptions` 端点，
    按 openai 协议去调只会 404（小米 MiMo 官方明确说明 ASR 走 chat completions）。
    """
    base = str(base_url or "").lower()
    mdl = str(model or "").lower()
    if "openspeech.bytedance.com" in base or "volcengine" in base:
        return "volcengine"
    if "assemblyai.com" in base:
        return "assemblyai"
    if "filetrans" in mdl:
        # 模型名带 -filetrans 是百炼异步文件转写的专有命名（qwen3-asr-flash-
        # filetrans / qwen-audio-3.0-asr-flash-filetrans / fun-asr 系列），
        # 走同步端点会 404/参数错——直接按异步链路认。
        return "dashscope_filetrans"
    if ("aliyuncs.com" in base or "dashscope" in base) and any(
            h in mdl for h in ASR_REALTIME_HINTS):
        # 百炼系域名 + 实时模型：这类模型只有 WebSocket 形态 → 走实时协议。
        # （它们连 compatible-mode 的 chat/completions 都调不了，官方模型表
        #   标注「模式=即时、API=WebSocket」。）
        return "dashscope_realtime"
    if ("aliyuncs.com" in base or "dashscope" in base) \
            and is_dashscope_native_asr(mdl):
        # Qwen-Audio-3.0-ASR-Flash 这类**原生端点**专用的录音文件识别模型：
        # 按 chat_audio 打 compatible-mode 恒回 400 空体（v1.15.6 实测），
        # 换原生端点即通 —— 必须在这里就分出去。
        return "dashscope_native"
    if "deepgram.com" in base:
        return "deepgram"
    if "elevenlabs.io" in base:
        return "elevenlabs"
    if "generativelanguage.googleapis.com" in base:
        return "gemini"
    if ("openai.azure.com" in base or "/openai/deployments/" in base
            or "azure.com" in base):
        return "azure"
    if ("xiaomimimo.com" in base or "mimo-v2" in mdl
            or "compatible-mode" in base or "dashscope" in base
            or ("qwen" in mdl and ("audio" in mdl or "asr" in mdl))
            or "paraformer" in mdl or "fun-asr" in mdl):
        return "chat_audio"
    return "openai"


def asr_protocol_fix(proto, base_url, model):
    """协议纠偏（双向）：把「协议 ↔ 端点 ↔ 模型」明显对不上的组合拉回正轨。

    返回 `(修正后的协议, 给日志的说明)`；无需修正时说明为空串。

    · `openai` + 百炼/小米系端点或模型 → 按推断改走 `chat_audio`
      （这类服务没有 `/audio/transcriptions`，按 openai 打只会 404）。
    · `dashscope_realtime` + 模型**不含实时特征**（v1.15.3 新增的反向守卫）
      → 按推断改走文件识别。用文件识别模型去连实时端点时，服务端只回
      `InvalidParameter url error, please check url!`——用户完全无从下手；
      而「接口协议」显式选过「百炼实时（WebSocket）」后，很容易与后来换成的
      文件识别模型残留成这个组合（实测踩到）。
    """
    p = str(proto or "").strip().lower()
    mdl = str(model or "").lower()
    if p == "openai":
        auto = _infer_asr_protocol(base_url, model)
        if auto and auto != "openai":
            return auto, "协议 openai 与该端点/模型不符，自动改走 %s" % auto
    if p in ("chat_audio", "dashscope", "dashscope_native") \
            and "filetrans" in mdl:
        # 模型名带 -filetrans 却按同步协议在打：走 Filetrans 提交-轮询链路。
        # 这是用户换模型后最常见的残留组合（旧配置留着 chat_audio）。
        return "dashscope_filetrans", (
            "模型「%s」是百炼异步文件转写模型，改走 Filetrans（提交 → 轮询）"
            "链路" % mdl)
    if p in ("chat_audio", "dashscope") and is_dashscope_native_asr(mdl):
        # v1.15.6：Qwen-Audio-3.0-ASR-Flash 这类原生端点专用模型被显式/旧配置
        # 判成 chat_audio 时，compatible-mode 只会回 HTTP 400 空体（重试与降级
        # 都救不回）→ 按推断改走原生端点。
        return "dashscope_native", (
            "模型「%s」走百炼原生端点（multimodal-generation），兼容模式的 "
            "chat/completions 对它恒回 400 空体，协议自动改走 dashscope_native"
            % model)
    if p == "dashscope_realtime" and not any(h in mdl for h in ASR_REALTIME_HINTS):
        auto = _infer_asr_protocol(base_url, model)
        if auto and auto != "dashscope_realtime":
            return auto, ("协议设为「百炼实时（WebSocket）」但模型「%s」不是实时"
                          "模型（名里没有 realtime / -rt- / streaming），"
                          "自动改走 %s" % (model, auto))
    return p, ""


def asr_base_guard(base_url):
    """ASR 地址守卫：地址填成了「文本对话端点」时给出能照着改的提示。

    最常见的错误是把 Anthropic / chat 这类**只收文本**的端点当成 ASR 地址
    （音频走 multipart 或 input_audio，那些端点根本不收），表现就是五花八门
    的 404 / 415 —— 与其让用户对着状态码猜，不如直接说"该填什么"。
    """
    b = str(base_url or "").lower()
    if "anthropic" in b or _is_anthropic_only_path(b):
        return ("ASR 地址填的是 Anthropic 文本对话端点（%s）——它收不了音频。"
                "请改填 OpenAI 兼容端点：公共百炼 "
                "https://dashscope.aliyuncs.com/compatible-mode/v1，Token Plan "
                "https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1，"
                "火山方舟 https://ark.cn-beijing.volces.com/api/v3（Coding Plan "
                "为 /api/coding/v3），或专属实例的 …/compatible-mode/v1" % base_url)
    return ""


def asr_model_guard(model):
    """实时（流式）模型守卫：返回给用户看的提示，可放行时返回空串。

    ⚠️ 只在**非实时协议**下调用：实时模型在「百炼实时（WebSocket）」协议下
    是能正常出字幕的（_asr_dashscope_realtime_submit），不该被拦。
    """
    m = str(model or "").lower()
    if any(h in m for h in ASR_REALTIME_HINTS):
        return ("模型「%s」是实时（WebSocket 流式）语音识别，本协议用不了它。"
                "把「接口协议」改为「百炼实时（WebSocket）」（留自动识别也会"
                "选中），或改用录音文件识别模型：公共百炼 qwen3-asr-flash、"
                "硅基流动 FunAudioLLM/SenseVoiceSmall、OpenAI whisper-1" % model)
    return ""


def asr_protocol_of(ai_cfg=None):
    """解析 ASR 服务模式当前应使用的接口协议。

    显式协议直接用；auto 按 base_url 与模型名推断（与 tools\\ai_client.py
    resolve_asr_protocol 同一套规则，这里独立实现避免依赖 ai_mod 失败）。
    """
    try:
        ac = ai_mod().asr_config(ai_cfg or ai_load_config())
        p = str(ac.get("protocol") or "auto").strip().lower()
        if p in ("dashscope", "chat_audio"):
            return "chat_audio"      # 历史键归一到 chat_audio（两者同一实现）
        if p in ASR_PROTOCOLS and p != "auto":
            return p
        return _infer_asr_protocol(ac.get("base_url"), ac.get("model"))
    except Exception:  # noqa: BLE001
        pass
    # v1.14.2：ai_client 读取失败不再盲返 openai（实时模型经 OpenAI SDK 必断、
    # qwen-audio 族在 maas 无 /audio/transcriptions）——退一步直读磁盘配置推断。
    try:
        raw = ai_cfg if ai_cfg else ai_load_config()
    except Exception:  # noqa: BLE001
        raw = {}
    raw = raw or {}
    p = str(raw.get("asr_protocol") or "auto").strip().lower()
    if p in ("dashscope", "chat_audio"):
        return "chat_audio"
    if p in ASR_PROTOCOLS and p != "auto":
        return p
    return _infer_asr_protocol(str(raw.get("asr_base_url") or ""),
                               str(raw.get("asr_model") or ""))


def _asr_diarize_flag(val):
    """把配置里的开关值（bool / 1 / "true" / "yes" / "on"）归一成布尔。"""
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return bool(val)
    return str(val or "").strip().lower() in ("1", "true", "yes", "on")


def asr_diarize_of(ai_cfg=None):
    """是否开启说话人分离（diarization）——与 asr_protocol_of 同一套读法。

    只有部分服务端原生支持（火山极速版 / AssemblyAI / Deepgram /
    ElevenLabs / 百炼 3.1 原生端点 / 百炼 Filetrans）；不支持的端点拿到
    True 也只是不产生 speaker 字段，字幕形态不变。
    """
    try:
        ac = ai_mod().asr_config(ai_cfg or ai_load_config())
        return _asr_diarize_flag(ac.get("diarize"))
    except Exception:  # noqa: BLE001
        pass
    try:
        raw = ai_cfg if ai_cfg else ai_load_config()
    except Exception:  # noqa: BLE001
        raw = {}
    return _asr_diarize_flag((raw or {}).get("asr_diarize"))


def _asr_diarize_on(asr_obj):
    """取本次转录是否要说话人分离。

    _submit 会把全局开关写进 asr_obj.diarize（分块重试、实时降级时沿用同一
    个值），没写就回落到读配置。
    """
    v = getattr(asr_obj, "diarize", None)
    if v is None:
        return asr_diarize_of()
    return _asr_diarize_flag(v)


def asr_separate_of(ai_cfg=None):
    """是否开启语音分离（separation）——与 asr_diarize_of 同一套读法。

    语音分离比说话人分离（diarization）更硬核：diarization 只回答"谁在
    什么时候说话"，separation 要在**两人同时说话**时把重叠的混合信号拆成
    各自独立的单人轨（音乐 reaction 里"把歌声从人声里剔除"也归这一路）。

    ⚠️ 当前版本**只保留开关与接口**，未内置声源分离模型（Demucs /
    MossFormer 等体积与算力开销较大）。开启后转录会在日志里记录待分离
    音频路径；后续接入时只需替换 `_asr_separate_audio` 的实现。
    """
    try:
        ac = ai_mod().asr_config(ai_cfg or ai_load_config())
        return _asr_diarize_flag(ac.get("separate"))
    except Exception:  # noqa: BLE001
        pass
    try:
        raw = ai_cfg if ai_cfg else ai_load_config()
    except Exception:  # noqa: BLE001
        raw = {}
    return _asr_diarize_flag((raw or {}).get("asr_separate"))


def _asr_separate_on(asr_obj):
    """取本次转录是否要语音分离（与 _asr_diarize_on 同构，供分块重试沿用）。"""
    v = getattr(asr_obj, "separate", None)
    if v is None:
        return asr_separate_of()
    return _asr_diarize_flag(v)


def _asr_separate_audio(audio_path, asr_obj=None):
    """语音分离的**接口占位**：把音频里的重叠人声拆成单人轨。

    约定（后续接入声源分离模型时按此实现即可，调用方无需改动）：
      · 入参：`audio_path` 原始音频；`asr_obj` 当前转录对象（可读配置）；
      · 返回：`[(标签, 音频路径), ...]` 列表——每个元素是一条**单人轨**，
        标签形如 `说话人1`（与 diarization 的编号口径一致），路径为分离后
        落盘的音频；无重叠 / 未启用时返回 `[(None, audio_path)]`（原轨）。
      · 音乐 reaction 场景：把"歌声"当作独立的一路返回（标签 `歌声`），
        调用方按标签决定是否剔除——这正是"把歌声给剔除出去"的落点。

    当前实现是**直通**（不分离，原样返回单轨），只做日志记录，便于确认
    开关已经贯通到引擎。真正的分离模型接入点见 docs/程序说明书(开发版).md。
    """
    try:
        _vc_log("[ASR] 语音分离已开启（接口占位，未内置分离模型），待处理音频：%s"
                % (audio_path,))
    except Exception:  # noqa: BLE001
        pass
    return [(None, audio_path)]


def asr_examples(cfg=None):
    """生成当前 ASR 配置对应的**非流式**调用示例（curl + Python）。

    为什么要有它：设置页「测试 ASR 配置」失败时，或者要在别的程序 / 脚本里
    集成同一套服务时，用户需要一条**自己能跑通**的命令，用来区分"是我程序
    的问题"还是"密钥 / 账号 / 模型的问题"。示例里的请求与引擎 `_asr_*_submit`
    一一对应（同一端点、同样的头与 body 形态），跑通它即等于验证了本程序。

    密钥一律用环境变量占位，不把明文写进可复制文本。
    返回 dict(protocol, title, curl, python, env, notes)。
    """
    try:
        ac = ai_mod().asr_config(cfg or ai_load_config())
    except Exception:  # noqa: BLE001
        ac = {"mode": "service", "base_url": "", "model": "", "api_key": ""}
    mode = str(ac.get("mode") or "service")
    base = str(ac.get("base_url") or "").strip().rstrip("/")
    model = str(ac.get("model") or "").strip()
    proto = "local" if mode == "local" else asr_protocol_of(cfg)
    notes = ["非流式：一次请求（或上传→提交→轮询）返回完整结果，"
             "不是 WebSocket 实时流；实时模型（*realtime*）用不了这种调用。",
             "示例与程序内实现一一对应：跑通它 = 这套密钥/地址/模型可用。"]

    if proto == "local":
        _lang = str(ac.get("language") or "").strip()
        return {
            "protocol": "local", "title": "本地 faster-whisper（不联网）",
            "env": {},
            "curl": "（本地模式不涉及 HTTP，没有 curl 示例）",
            "python": "\n".join([
                "from faster_whisper import WhisperModel",
                "",
                "model = WhisperModel(%r, device=\"auto\")   # 或模型目录" % (model or "large-v3"),
                "segments, info = model.transcribe(\"audio.mp3\", %s)"
                % (("language=%r" % _lang) if _lang else "language=None  # 自动检测"),
                "print(\"\".join(s.text for s in segments))",
            ]),
            "notes": notes + ["本地模型在本程序的「设置 → ASR 语音识别 → 本地独立模型」里配。"]
                    + (["识别语言已固定为 %s（%r）。" % (ac.get("language_label"), _lang)]
                       if _lang else []),
        }

    # ⚠️ 只给变量名与说明，**不把密钥明文写进可复制文本**（方便安全地
    #    贴文档 / 发同事；也让示例本身不因换密钥而失效）
    env = {"ASR_API_KEY": "设置页「ASR 密钥」里填的那个"}
    title = {
        "openai": "OpenAI Whisper 兼容", "azure": "Azure OpenAI",
        "chat_audio": "Chat 音频转写（百炼 Qwen-ASR / 小米 MiMo 等）",
        "dashscope": "Chat 音频转写（百炼 Qwen-ASR / 小米 MiMo 等）",
        "deepgram": "Deepgram",
        "elevenlabs": "ElevenLabs Scribe", "gemini": "Google Gemini",
        "volcengine": "火山引擎（豆包）录音识别极速版",
        "assemblyai": "AssemblyAI",
        "dashscope_native": "百炼原生端点（Qwen-Audio-3.0-ASR-Flash 等 ASR 专用模型）",
        "dashscope_filetrans": "百炼 Filetrans 异步文件转写（提交 → 轮询）",
    }.get(proto, proto)

    if proto == "openai":
        sd_base = asr_strip_endpoint_tail(base or "https://api.openai.com/v1",
                                          "/audio/transcriptions",
                                          "/audio/translations")
        url = sd_base + "/audio/transcriptions"
        mdl = model or "whisper-1"
        _lang = str(ac.get("language") or "").strip()
        curl = "\n".join([
            'curl -X POST "%s" \\' % url,
            '  -H "Authorization: Bearer $ASR_API_KEY" \\',
            '  -F "file=@audio.mp3" \\',
            '  -F "model=%s" \\' % mdl,
        ] + (['  -F "language=%s" \\' % _lang] if _lang else [])
        + [
            '  -F "response_format=verbose_json" \\',
            '  -F "timestamp_granularities[]=word"',
        ])
        py = "\n".join([
            "import os",
            "from openai import OpenAI",
            "",
            "client = OpenAI(base_url=%r, api_key=os.environ[\"ASR_API_KEY\"])" % sd_base,
            "with open(\"audio.mp3\", \"rb\") as f:",
            "    r = client.audio.transcriptions.create(",
            "        model=%r, file=f, response_format=\"verbose_json\",  # 非流式" % mdl,
        ] + (["        language=%r," % _lang] if _lang else [])
        + [
            "        timestamp_granularities=[\"word\"])",
            "print(r.text)",
        ])
        notes = notes + (["识别语言已固定为 %s（请求带 language=%r）。"
                          % (ac.get("language_label"), _lang)] if _lang else [])
    elif proto == "azure":
        res = base or "https://<你的资源名>.openai.azure.com"
        dep = model or "<部署名>"
        if "/openai/deployments/" in res:
            url = res if res.lower().endswith("/audio/transcriptions") else \
                res + "/audio/transcriptions"
        else:
            url = "%s/openai/deployments/%s/audio/transcriptions" % (res, dep)
        if "api-version=" not in url:
            url += "?api-version=2024-10-21"
        curl = "\n".join([
            'curl -X POST "%s" \\' % url,
            '  -H "api-key: $ASR_API_KEY" \\',
            '  -F "file=@audio.mp3" \\',
            '  -F "response_format=verbose_json"',
        ])
        py = "\n".join([
            "import os",
            "from openai import AzureOpenAI",
            "",
            "client = AzureOpenAI(azure_endpoint=%r, api_key=os.environ[\"ASR_API_KEY\"],"
            % res,
            "                       api_version=\"2024-10-21\")",
            "with open(\"audio.mp3\", \"rb\") as f:",
            "    r = client.audio.transcriptions.create(",
            "        model=%r, file=f, response_format=\"verbose_json\")   # 非流式" % dep,
            "print(r.text)",
        ])
    elif proto in ("chat_audio", "dashscope"):
        url = (base or "https://dashscope.aliyuncs.com/compatible-mode/v1") \
            + "/chat/completions"
        mdl = model or "qwen3-asr-flash"
        # body 用 python 现造：base64 的引号嵌套交给 shell 太脆，
        # 而且 base64 -w0 在 macOS 上不支持（GNU 专有参数）
        _body = ("python -c \"import base64,json;b=base64.b64encode("
                 "open('audio.mp3','rb').read()).decode();"
                 "print(json.dumps({'model':'%s','messages':[{'role':'user',"
                 "'content':[{'type':'input_audio','input_audio':{'data':"
                 "'data:audio/mp3;base64,'+b}}]}],'stream':False}))\"" % mdl)
        curl = "\n".join([
            "BODY=$(%s)" % _body,
            'curl -X POST "%s" \\' % url,
            '  -H "Authorization: Bearer $ASR_API_KEY" \\',
            '  -H "Content-Type: application/json" \\',
            '  -d "$BODY"',
        ])
        py = "\n".join([
            "import base64, os",
            "from openai import OpenAI",
            "",
            "client = OpenAI(base_url=%r, api_key=os.environ[\"ASR_API_KEY\"])"
            % (base or "https://dashscope.aliyuncs.com/compatible-mode/v1"),
            "b64 = base64.b64encode(open(\"audio.mp3\", \"rb\").read()).decode()",
            "r = client.chat.completions.create(          # 非流式",
            "    model=%r," % mdl,
            "    messages=[{\"role\": \"user\", \"content\": [",
            "        {\"type\": \"input_audio\",",
            "         \"input_audio\": {\"data\": \"data:audio/mp3;base64,\" + b64}}]}],",
            "    stream=False)",
            "print(r.choices[0].message.content)",
        ])
        notes.append("音频走 input_audio 的 **Data URL**（自带 MIME）；"
                     "`stream=false` 才是非流式。")
        if "xiaomimimo" in base.lower() or "mimo" in mdl.lower():
            notes.append("小米 MiMo：ASR 也走 chat/completions（**没有** "
                         "/audio/transcriptions 端点，别填成 OpenAI Whisper 那样），"
                         "仅支持 mp3 / wav，返回纯文本（时间轴由本程序按句兜底）。")
    elif proto == "dashscope_native":
        # 百炼原生端点（Qwen-Audio-3.0-ASR-Flash / Fun-ASR-Flash 这类模型）：
        # 不是 chat/completions，走 /api/v1/services/aigc/multimodal-generation/generation
        url = _asr_native_url(base or "https://dashscope.aliyuncs.com/compatible-mode/v1")
        mdl = model or "qwen-audio-3.0-asr-flash"
        _body = ("python -c \"import base64,json;b=base64.b64encode("
                 "open('audio.wav','rb').read()).decode();"
                 "print(json.dumps({'model':'%s','input':{'messages':[{'role':"
                 "'user','content':[{'type':'input_audio','input_audio':{'data':"
                 "'data:audio/wav;base64,'+b}}]}]},'parameters':"
                 "{'format':'wav','sample_rate':16000}}))\"" % mdl)
        curl = "\n".join([
            "BODY=$(%s)" % _body,
            'curl -X POST "%s" \\' % url,
            '  -H "Authorization: Bearer $ASR_API_KEY" \\',
            '  -H "Content-Type: application/json" \\',
            '  -d "$BODY"',
        ])
        py = "\n".join([
            "import base64, os",
            "import requests      # 原生端点不认 OpenAI SDK，直接用裸 HTTP",
            "",
            "b64 = base64.b64encode(open(\"audio.wav\", \"rb\").read()).decode()",
            "r = requests.post(                       # 非流式",
            "    %r," % url,
            "    headers={\"Authorization\": \"Bearer \" + os.environ[\"ASR_API_KEY\"],",
            "             \"Content-Type\": \"application/json\"},",
            "    json={\"model\": %r," % mdl,
            "          \"input\": {\"messages\": [{\"role\": \"user\", \"content\": [",
            "              {\"type\": \"input_audio\",",
            "               \"input_audio\": {\"data\": \"data:audio/wav;base64,\" + b64}}]}]},",
            "          \"parameters\": {\"format\": \"wav\", \"sample_rate\": 16000}})",
            "d = r.json()",
            "# 返回没有 choices：文本在 output.text，句内字级时间戳在 output.sentence.words",
            "print(d[\"output\"].get(\"text\") or d[\"output\"][\"sentence\"][\"text\"])",
        ])
        notes.append("百炼**原生端点**（不是 chat/completions）：Qwen-Audio-3.0-ASR-Flash "
                     "这类文件转写模型只认 multimodal-generation；用 chat 协议调它会收到 "
                     "HTTP 400 空响应（模型本身没问题）。")
        notes.append("响应没有 choices 字段：识别文本在 `output.text`（整段）/"
                     "`output.sentence.text`（句级），`output.sentence.words[]` 带字级 "
                     "begin_time/end_time（毫秒）+ 独立标点。")
    elif proto == "deepgram":
        b = base or "https://api.deepgram.com"
        url = b if b.lower().endswith("/listen") else \
            (b + "/listen" if b.lower().endswith("/v1") else b + "/v1/listen")
        mdl = model or "nova-3"
        curl = "\n".join([
            'curl -X POST "%s?model=%s&smart_format=true&language=zh-CN" \\'
            % (url, mdl),
            '  -H "Authorization: Token $ASR_API_KEY" \\',
            '  -H "Content-Type: audio/mp3" \\',
            '  --data-binary @audio.mp3',
        ])
        py = "\n".join([
            "import os",
            "import requests      # 官方 SDK（deepgram-sdk）各版本写法差异较大，",
            "                     # 这里给等价的裸 HTTP 版本，最稳",
            "r = requests.post(",
            "    %r," % (url + "?model=%s&smart_format=true&language=zh-CN" % mdl),
            "    headers={\"Authorization\": \"Token \" + os.environ[\"ASR_API_KEY\"],",
            "             \"Content-Type\": \"audio/mp3\"},",
            "    data=open(\"audio.mp3\", \"rb\").read(),   # 原始字节，不是 multipart",
            "    timeout=600)",
            "j = r.json()[\"results\"][\"channels\"][0][\"alternatives\"][0]",
            "print(j[\"transcript\"])",
            "for w in j.get(\"words\", []):        # 词级时间轴（秒）",
            "    print(w[\"start\"], w[\"end\"], w[\"word\"])",
        ])
        notes.append("鉴权头是 `Authorization: Token <key>`（不是 Bearer）；"
                     "音频以原始字节放在 body 里。")
    elif proto == "elevenlabs":
        b = base or "https://api.elevenlabs.io"
        url = b if b.lower().endswith("/speech-to-text") else b + "/v1/speech-to-text"
        mdl = model or "scribe_v1"
        curl = "\n".join([
            'curl -X POST "%s" \\' % url,
            '  -H "xi-api-key: $ASR_API_KEY" \\',
            '  -F "model_id=%s" \\' % mdl,
            '  -F "timestamps_granularity=word" \\',
            '  -F "file=@audio.mp3"',
        ])
        py = "\n".join([
            "import os",
            "from elevenlabs.client import ElevenLabs",
            "",
            "client = ElevenLabs(api_key=os.environ[\"ASR_API_KEY\"])",
            "with open(\"audio.mp3\", \"rb\") as f:",
            "    r = client.speech_to_text.convert(        # 非流式",
            "        model_id=%r, file=f, timestamps_granularity=\"word\")" % mdl,
            "print(r.text)",
        ])
    elif proto == "gemini":
        b = base or "https://generativelanguage.googleapis.com"
        mdl = model or "gemini-2.5-flash"
        url = "%s/v1beta/models/%s:generateContent" % (b, mdl)
        _body = ("python -c \"import base64,json;b=base64.b64encode("
                 "open('audio.mp3','rb').read()).decode();"
                 "print(json.dumps({'contents':[{'parts':[{'inline_data':"
                 "{'mime_type':'audio/mp3','data':b}},{'text':"
                 "'请把这段音频逐字转写为文本，只输出转写内容。'}]}]}))\"")
        curl = "\n".join([
            "BODY=$(%s)" % _body,
            'curl -X POST "%s" \\' % url,
            '  -H "x-goog-api-key: $ASR_API_KEY" \\',
            '  -H "Content-Type: application/json" \\',
            '  -d "$BODY"',
        ])
        py = "\n".join([
            "import base64, os",
            "from google import genai            # pip install google-genai",
            "",
            "client = genai.Client(api_key=os.environ[\"ASR_API_KEY\"])",
            "b64 = base64.b64encode(open(\"audio.mp3\", \"rb\").read()).decode()",
            "r = client.models.generate_content(        # 非流式",
            "    model=%r," % mdl,
            "    contents=[{\"inline_data\": {\"mime_type\": \"audio/mp3\", \"data\": b64}},",
            "              \"请把这段音频逐字转写为文本，只输出转写内容。\"])",
            "print(r.text)",
        ])
        notes.append("Gemini 返回纯文本、没有时间轴；本程序按句切分后再按句长占比"
                     "给出近似时间轴。")
    elif proto == "volcengine":
        url = (base or "https://openspeech.bytedance.com") + \
            ("" if base.endswith("/recognize/flash")
             else "/api/v3/auc/bigmodel/recognize/flash")
        res_id = model or VOLC_DEFAULT_RESOURCE
        env = {"VOLC_APP_ID": "控制台的 APP ID",
               "VOLC_ACCESS_KEY": "控制台的 Access Token"}
        _body = ("python -c \"import base64,json,os;b=base64.b64encode("
                 "open('audio.mp3','rb').read()).decode();"
                 "print(json.dumps({'user':{'uid':os.environ['VOLC_APP_ID']},"
                 "'audio':{'data':b},'request':{'model_name':'bigmodel',"
                 "'enable_punc':True,'show_utterances':True}}))\"")
        curl = "\n".join([
            "BODY=$(%s)" % _body,
            'curl -X POST "%s" \\' % url,
            '  -H "X-Api-App-Key: $VOLC_APP_ID" \\',
            '  -H "X-Api-Access-Key: $VOLC_ACCESS_KEY" \\',
            '  -H "X-Api-Resource-Id: %s" \\' % res_id,
            '  -H "X-Api-Request-Id: $(uuidgen)" \\',
            '  -H "X-Api-Sequence: -1" \\',
            '  -H "Content-Type: application/json" \\',
            '  -d "$BODY"',
        ])
        py = "\n".join([
            "import base64, json, os, uuid",
            "import requests        # 火山没有官方同步 Python SDK，这是等价实现",
            "",
            "r = requests.post(",
            "    %r," % url,
            "    headers={\"X-Api-App-Key\": os.environ[\"VOLC_APP_ID\"],",
            "             \"X-Api-Access-Key\": os.environ[\"VOLC_ACCESS_KEY\"],",
            "             \"X-Api-Resource-Id\": \"%s\"," % res_id,
            "             \"X-Api-Request-Id\": str(uuid.uuid4()),",
            "             \"X-Api-Sequence\": \"-1\",",
            "             \"Content-Type\": \"application/json\"},",
            "    data=json.dumps({\"user\": {\"uid\": os.environ[\"VOLC_APP_ID\"]},",
            "                     \"audio\": {\"data\": base64.b64encode(",
            "                         open(\"audio.mp3\", \"rb\").read()).decode()},",
            "                     \"request\": {\"model_name\": \"bigmodel\",",
            "                                 \"show_utterances\": True}}),",
            "    timeout=600)",
            "print(r.headers.get(\"X-Api-Status-Code\"))     # 20000000 = 成功（在响应头！）",
            "print(r.json()[\"result\"][\"text\"])",
        ])
        notes.append("状态码在**响应头** `X-Api-Status-Code`（`20000000` 为成功）；"
                     "新版控制台只有一个 API Key 时，把前两个头换成 "
                     "`X-Api-Key: $ASR_API_KEY`。")
    elif proto == "dashscope_filetrans":
        root = _asr_dashscope_root(base)
        mdl = model or "qwen3-asr-flash-filetrans"
        if "filetrans" not in mdl.lower():
            mdl = mdl + "-filetrans"
        curl = "\n".join([
            "# 1) 取上传凭证（Filetrans 不收本地文件，音频须先传到临时存储）",
            'POL=$(curl -s "%s%s?action=getPolicy&model=%s" \\'
            % (root, ASR_UPLOAD_POLICY_PATH, mdl),
            '  -H "Authorization: Bearer $ASR_API_KEY")',
            "# 2) 按凭证把音频传到百炼临时存储（OSS 表单上传，file 字段放最后）",
            'curl -s -X POST "$(echo $POL | jq -r .data.upload_host)" \\',
            '  -F "key=$(echo $POL | jq -r .data.upload_dir)/audio.mp3" \\',
            '  -F "policy=$(echo $POL | jq -r .data.policy)" \\',
            '  -F "Signature=$(echo $POL | jq -r .data.signature)" \\',
            '  -F "OSSAccessKeyId=$(echo $POL | jq -r .data.oss_access_key_id)" \\',
            '  -F "x-oss-object-acl=private" -F "x-oss-forbid-overwrite=true" \\',
            '  -F "file=@audio.mp3"',
            "# 3) 提交任务（oss:// 链接 + 两个必需头）",
            'ID=$(curl -s -X POST "%s%s" \\' % (root, ASR_FILETRANS_PATH),
            '  -H "Authorization: Bearer $ASR_API_KEY" \\',
            '  -H "Content-Type: application/json" \\',
            '  -H "X-DashScope-Async: enable" \\',
            '  -H "X-DashScope-OssResourceResolve: enable" \\',
            "  -d '{\"model\": \"%s\", \"input\": {\"file_urls\": "
            "[\"oss://<UPLOAD_DIR>/audio.mp3\"]}, \"parameters\": "
            "{\"diarization_enabled\": true}}' | jq -r .output.task_id)" % mdl,
            "# 4) 轮询任务；结果 JSON 地址在 output.results[0].transcription_url",
            'curl -s "%s/api/v1/tasks/$ID" -H "Authorization: Bearer $ASR_API_KEY"'
            % root,
        ])
        py = "\n".join([
            "import os, time, requests",
            "",
            "key = os.environ['ASR_API_KEY']",
            "root = %r" % root,
            "model = %r" % mdl,
            "",
            "# 程序内部就是这四步：凭证 → 传临时存储 → 提交 → 轮询下载",
            "pol = requests.get(root + '/api/v1/uploads',",
            "                   params={'action': 'getPolicy', 'model': model},",
            "                   headers={'Authorization': 'Bearer ' + key}",
            "                   ).json()['data']",
            "key_name = pol['upload_dir'] + '/audio.mp3'",
            "requests.post(pol['upload_host'],",
            "              data={'key': key_name, 'policy': pol['policy'],",
            "                    'Signature': pol['signature'],",
            "                    'OSSAccessKeyId': pol['oss_access_key_id'],",
            "                    'x-oss-object-acl': pol['x_oss_object_acl'],",
            "                    'x-oss-forbid-overwrite': pol['x_oss_forbid_overwrite'],",
            "                    'success_action_status': '200'},",
            "              files={'file': ('audio.mp3', open('audio.mp3', 'rb'))})",
            "",
            "task = requests.post(root + '/api/v1/services/audio/asr/transcription',",
            "                     headers={'Authorization': 'Bearer ' + key,",
            "                              'X-DashScope-Async': 'enable',",
            "                              'X-DashScope-OssResourceResolve': 'enable'},",
            "                     json={'model': model,",
            "                           'input': {'file_urls': ['oss://' + key_name]},",
            "                           'parameters': {'diarization_enabled': True}}",
            "                     ).json()['output']['task_id']",
            "",
            "while True:",
            "    out = requests.get(root + '/api/v1/tasks/' + task,",
            "                       headers={'Authorization': 'Bearer ' + key}",
            "                       ).json()['output']",
            "    if out['task_status'] in ('SUCCEEDED', 'FAILED'):",
            "        break",
            "    time.sleep(5)",
            "",
            "url = out['results'][0]['transcription_url']     # 结果要再下载一次",
            "sent = requests.get(url).json()['transcripts'][0]['sentences']",
            "for s in sent:                                   # 开分离后每句带 speaker_id",
            "    print(s.get('speaker_id'), s['text'])",
        ])
        notes.append(
            "⚠️ 官方限制：临时 URL 有效期 48 小时、凭证接口限流 100 QPS，文档"
            "标注「请勿用于生产环境」；说话人分离仅支持单声道、建议 ≤ 2 小时。"
            "qwen3 系模型的 input 字段是 file_url（单对象），qwen-audio / "
            "fun-asr 是 file_urls（数组），程序会按模型自动选。")
    else:   # assemblyai
        b = base or "https://api.assemblyai.com"
        models = [x.strip() for x in (model or "").split(",") if x.strip()] \
            or list(ASSEMBLYAI_DEFAULT_MODELS)
        models_json = "[\"" + "\", \"".join(models) + "\"]"
        curl = "\n".join([
            "# 1) 上传本地文件（raw bytes，不是 multipart）",
            'UP=$(curl -s -X POST "%s/v2/upload" \\' % b,
            '  -H "authorization: $ASR_API_KEY" --data-binary @audio.mp3 | jq -r .upload_url)',
            "# 2) 提交转写任务",
            'ID=$(curl -s -X POST "%s/v2/transcript" \\' % b,
            '  -H "authorization: $ASR_API_KEY" -H "content-type: application/json" \\',
            "  -d '{\"audio_url\": \"'$UP'\", \"speech_models\": %s}' | jq -r .id)"
            % models_json,
            "# 3) 轮询到完成（非流式：结果一次性取回）",
            'while :; do',
            '  S=$(curl -s "%s/v2/transcript/$ID" -H "authorization: $ASR_API_KEY"' % b,
            "        | jq -r .status)",
            '  [ "$S" = "completed" ] && break; [ "$S" = "error" ] && break; sleep 3',
            'done',
            'curl -s "%s/v2/transcript/$ID" -H "authorization: $ASR_API_KEY" | jq -r .text' % b,
        ])
        py = "\n".join([
            "import os",
            "import assemblyai as aai           # pip install assemblyai",
            "",
            "aai.settings.api_key = os.environ[\"ASR_API_KEY\"]",
            "cfg = aai.TranscriptionConfig(speech_models=%r, language_detection=True)"
            % models,
            "t = aai.Transcriber().transcribe(\"audio.mp3\", config=cfg)   # 阻塞到完成",
            "print(t.text)",
            "for w in (t.words or []):          # 词级时间轴（毫秒）",
            "    print(w.start, w.end, w.text)",
        ])
        notes.append("鉴权头是 `authorization: <key>`（**不带 Bearer**）；"
                     "`speech_models` 必填（官方无默认值）；词级时间轴单位是**毫秒**。"
                     "curl 示例用到 jq（Windows 上直接看 Python 版即可）。")

    return {"protocol": proto, "title": title, "curl": curl, "python": py,
            "env": env, "notes": notes}


def asr_examples_text(cfg=None):
    """把 asr_examples() 拼成一份可直接给人看 / 另存的纯文本。"""
    ex = asr_examples(cfg)
    out = ["# %s（协议：%s）" % (ex["title"], ex["protocol"]), ""]
    if ex.get("env"):
        out.append("# 先设置环境变量：")
        for k, note in ex["env"].items():
            out.append("#   export %s='%s'" % (k, note))
        out.append("")
    out += ["# ---- curl（非流式）----", ex["curl"], "",
            "# ---- Python（非流式）----", ex["python"], "", "# 说明"]
    out += ["#  · " + n for n in ex.get("notes", [])]
    return "\n".join(out)


def _asr_audio_format(data: bytes) -> str:
    """按魔数识别音频容器（DashScope input_audio 需要显式 format）。"""
    head = bytes(data[:16]) if data else b""
    if head.startswith(b"RIFF") and head[8:12] == b"WAVE":
        return "wav"
    if head.startswith(b"ID3") or (len(head) > 2 and head[0] == 0xFF
                                   and (head[1] & 0xE0) == 0xE0):
        return "mp3"
    if head.startswith(b"OggS"):
        return "ogg"
    if head.startswith(b"fLaC"):
        return "flac"
    return "mp3"


def _asr_text_to_segments(text, duration_sec):
    """把无时间戳的纯文本识别结果按句切分并按时长占比分配时间轴。

    返回与引擎 WhisperAPI._make_segments 兼容的
    [{"text":…, "start":秒, "end":秒}, …]；文本为空返回空表。
    """
    import re
    text = str(text or "").strip()
    if not text:
        return []
    # 先按句末标点/换行切句，再把超长句按逗号级标点二次切
    pieces = [p for p in re.split(r"(?<=[。！？!?；;…])\s*|\n+", text) if p.strip()]
    refined = []
    for p in pieces:
        p = p.strip()
        if len(p) > 42:
            parts = [q for q in re.split(r"(?<=[，,、])", p) if q.strip()]
        else:
            parts = [p]
        refined.extend(parts)
    if not refined:
        refined = [text]
    weights = [max(len(s), 1) for s in refined]
    total = float(sum(weights))
    dur_ms = max(int(float(duration_sec or 0) * 1000), 1000)
    segs, t = [], 0
    for s, w in zip(refined, weights):
        d = int(dur_ms * w / total)
        segs.append({"text": s, "start": round(t / 1000.0, 3),
                     "end": round((t + d) / 1000.0, 3)})
        t += d
    if segs:
        segs[-1]["end"] = round(dur_ms / 1000.0, 3)
    return segs


def _asr_is_cjk(ch):
    return bool(ch) and ord(ch) > 0x2E7F


def _asr_join_words(tokens):
    """拼词成句：中文之间不加空格，拉丁词之间加。"""
    out = ""
    for t in tokens:
        if out and not _asr_is_cjk(out[-1]) and not _asr_is_cjk(t[:1]):
            out += " "
        out += t
    return out


def _asr_is_sentence_end(tok):
    """词尾是否句末（词级 ASR 的 punctuated_word 会带标点）。

    英文句点一律算句末 —— **不需要**给小数开特例：词级结果不会把 `3.5`
    切成 `3.` + `5`（`3.5` 的末位是 `5`，本来就落不进句点分支）。
    """
    if not tok:
        return False
    return tok[-1] in "。！？!?；;…."


def _asr_words_to_segments(words, max_gap=0.9, max_chars=42):
    """词级时间轴 → 句级 segments（Deepgram / ElevenLabs / 火山 / 百炼原生用）。

    断句四条件：句末标点、停顿超过 max_gap 秒、当前句超长、**说话人切换**。
    最后一条为说话人分离（diarization）专用——不在切换处断开的话，同一条
    字幕里会混进两个人的发言，标签只能落在其中一个头上，看的人更乱。

    words 里带 `speaker` 时，产出段会多一个 `speaker` 字段（原样保留服务端
    的原始标识，统一编号交给 _asr_apply_speaker_labels 做）。不带 speaker
    时行为与 v1.15.7 之前完全一致（自检基线依赖这一点）。
    """
    segs = []
    cur, start, end, cur_spk = [], None, None, None

    def _flush():
        if not cur:
            return
        seg = {"text": _asr_join_words(cur),
               "start": round(start or 0, 3),
               "end": round(end if end is not None else (start or 0), 3)}
        if cur_spk is not None:
            seg["speaker"] = cur_spk
        segs.append(seg)

    for w in words or []:
        tok = str(w.get("word") or w.get("text") or "").strip()
        if not tok:
            continue
        try:
            s = float(w.get("start") or 0)
            e = float(w.get("end") or s)
        except (TypeError, ValueError):
            continue
        spk = w.get("speaker")
        spk = None if spk is None else str(spk)
        # 说话人切换 → 立即断句（先于停顿/长度判断，避免把新人的话并进旧句）
        if cur and spk is not None and cur_spk is not None and spk != cur_spk:
            _flush()
            cur, start, cur_spk = [], None, None
        if cur and (s - (end if end is not None else s) > max_gap
                    or sum(len(x) for x in cur) >= max_chars):
            _flush()
            cur, start, cur_spk = [], None, None
        if start is None:
            start = s
        cur.append(tok)
        end = e
        if cur_spk is None:
            cur_spk = spk
        if _asr_is_sentence_end(tok):
            _flush()
            cur, start, cur_spk = [], None, None
    _flush()
    return segs


#: 说话人标签形态：段文本前置，形如「[说话人1] 台词」
ASR_SPEAKER_PREFIX = "[说话人%d] "


def _asr_apply_speaker_labels(resp):
    """把段上的 speaker 落成文本前缀「[说话人1] …」。

    为什么拼进文本而不是给 ASRDataSeg 加字段：下游 ASRDataSeg 只有
    text/start_time/end_time 三个字段，翻译、AI 校准、字幕编辑页、SRT 导出
    全都只认 text。加字段要把这几处一起改；拼前缀则整条链路零改动。

    服务端返回的标识形态各异（火山是数字串、AssemblyAI 是 A/B/C、ElevenLabs
    是 spk_0），这里按**首次出现顺序**统一重编成 1、2、3……保证同一个结果
    内编号连续且与出场顺序一致。

    ⚠️ 有 speaker 时会同时摘掉 `words`：词级模式下 whisper_api._make_segments
    是一个词一条字幕，前缀会重复糊在每一个词上；说话人分离本就按话轮成段，
    强制走句级。
    """
    if not isinstance(resp, dict):
        return resp
    segs = resp.get("segments")
    if not isinstance(segs, list) or not segs:
        return resp
    order = {}
    hit = False
    for seg in segs:
        if not isinstance(seg, dict):
            continue
        raw = seg.get("speaker")
        if raw is None:
            continue
        key = str(raw)
        if key not in order:
            order[key] = len(order) + 1
        seg["text"] = (ASR_SPEAKER_PREFIX % order[key]) + str(seg.get("text") or "")
        hit = True
    if hit:
        resp.pop("words", None)
    return resp


def _asr_words_response(text, words):
    """统一成 {text, segments, words}：引擎两条消费路径（句级 / 词级）都能吃。"""
    clean = []
    for w in words or []:
        tok = str(w.get("word") or w.get("text") or "").strip()
        if not tok:
            continue
        try:
            s = float(w.get("start") or 0)
            e = float(w.get("end") or s)
        except (TypeError, ValueError):
            continue
        item = {"word": tok, "start": s, "end": e}
        spk = w.get("speaker")
        if spk is not None:
            item["speaker"] = str(spk)
        clean.append(item)
    out = {"text": str(text or ""), "segments": _asr_words_to_segments(clean)}
    if clean:
        out["words"] = clean
    return out


def _asr_plan_endpoint_hint(asr_obj):
    """订阅套餐端点配套提示（转录失败时追加，非套餐端点返回空串）。

    百炼 Token Plan / Coding Plan、智谱与火山 Coding Plan 均为专属端点且
    密钥不跨方案通用；套餐密钥打错端点时服务端常常只回空体 400/500，用户
    无从下手，故在此点名各方案端点。
    """
    b = str(getattr(asr_obj, "base_url", "") or "").lower()
    if not any(k in b for k in ("token-plan", "coding.", "/api/coding",
                                "maas.aliyuncs")):
        return ""
    return ("；端点与密钥须同属一个计费方案（百炼按量 "
            "dashscope.aliyuncs.com/compatible-mode/v1、Token Plan "
            "token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1、"
            "火山方舟 /api/v3（Coding Plan 为 /api/coding/v3）、智谱 "
            "/api/paas/v4（Coding Plan 为 /api/coding/paas/v4）——套餐密钥"
            "打错端点只会得到空体错误；Qwen-Audio-3.0-ASR-Flash 另有专用原生"
            "端点 /api/v1/services/aigc/multimodal-generation/generation，"
            "程序会按模型自动改走）")


#: 实例模型清单缓存：base_url -> (取回时间, [模型名…])
_ASR_MODELS_CACHE = {}


def asr_instance_models(base_url, api_key, ttl=600):
    """查 `GET {base}/models` 拿该实例**当前可用**的模型名列表（带缓存）。

    为什么需要它：百炼专属实例的模型清单**会变**。实测（2026-09-30）用户实例
    上 `qwen-audio-3.0-asr-flash` 消失后，原生端点与 chat/completions **都回
    400 空体 `{}`**——光看响应完全看不出原因，只能靠模型清单定位。拿不到
    返回 []（绝不干扰原错误路径）。
    """
    base = asr_strip_endpoint_tail(str(base_url or "").strip()).rstrip("/")
    if not base:
        return []
    hit = _ASR_MODELS_CACHE.get(base)
    if hit and (time.time() - hit[0]) < ttl:
        return hit[1]
    models = []
    try:
        import requests
        url = base + "/models"
        r = requests.get(url,
                         headers={"Authorization": "Bearer " + str(api_key or "")},
                         proxies=http_proxies_for(url), timeout=20)
        if r.status_code == 200:
            data = (r.json() or {}).get("data") or []
            models = [str(m.get("id")) for m in data if m.get("id")]
    except Exception:  # noqa: BLE001
        models = []
    _ASR_MODELS_CACHE[base] = (time.time(), models)
    return models


def asr_missing_model_hint(asr_obj):
    """模型不在该实例里时的**可操作**提示；判断不了返回空串。

    这是「转录失败」最常见的真实原因：用户配置没动，但服务端实例的模型清单
    变了。原文案只猜"模型与端点不配套"，会把人往改协议的方向带（而协议其实
    已经是对的），所以这里直接查清单点名，并给出该换什么。
    """
    model = str(getattr(asr_obj, "model", "") or "").strip()
    if not model:
        return ""
    models = asr_instance_models(getattr(asr_obj, "base_url", ""),
                                 getattr(asr_obj, "api_key", ""))
    if not models or model in models:
        return ""
    # 「可转写」的音频模型：TTS / 实时对话族虽然名字带 audio，却做不了录音
    # 转写（前者输出音频、后者是流式对话），算进来会把误诊说成"还有能用的"。
    audio_like = [m for m in models
                  if any(h in m.lower() for h in
                         ("asr", "audio", "whisper", "paraformer", "sensevoice"))
                  and not any(k in m.lower() for k in _TTS_HINTS)
                  and not any(k in m.lower() for k in ASR_REALTIME_HINTS)]
    # 误诊拦截（2026-10-05 实测）：清单里**一个音频类模型都没有**、而配置的
    # 又是原生端点的 ASR 模型（qwen-audio-*-asr-*）时，多半是这份清单压根不
    # 列 ASR 模型，而不是模型下架。实证：百炼 Token Plan 共享端点
    # token-plan.cn-beijing.maas.aliyuncs.com 的 `GET /models` 只回 16 个
    # 文本/图像/TTS/实时模型，不含 qwen-audio-3.0-asr-flash；但用同一个 Key
    # POST 原生端点，该模型能正常受理（回 400 空体 = 只是这段没语音），而
    # qwen3-asr-flash 才真回 404 Model not exist。此时报"模型已下架"会把用户
    # 引去改一份本来正确的配置，直接不提示。
    if not audio_like and is_dashscope_native_asr(model):
        return ""
    tip = ("；⚠️ `GET /models` 返回的实例清单里**找不到**模型「%s」"
           "（服务端模型清单会变，配置没动也可能失效）。" % model)
    if audio_like:
        tip += "其中音频相关的是：%s。" % "、".join(audio_like[:6])
    else:
        tip += ("而且**一个音频/识别类模型都没有**（现有：%s）。"
                % "、".join(models[:8]))
    # 免责：专属实例的 /models 有时不列 ASR 模型（历史踩过），所以清单只能
    # 当线索、不能当判决——否则会把"其实还能用"的用户劝去换配置。
    tip += ("（注意：专属实例的 /models 有时**不列** ASR 模型，清单只能作线索；"
            "若连一个音频类模型都没有，多半是该实例的 ASR 模型已下架——可改用"
            "公共百炼 dashscope.aliyuncs.com/compatible-mode/v1 + qwen3-asr-flash，"
            "或在「转录模型来源」里改用本地模型）")
    return tip


def _asr_err_hint(resp):
    """把 HTTP 错误响应转成"能照着修"的提示（密钥 / 模型名 / 其它）。"""
    text = ""
    try:
        text = (resp.text or "")[:300]
    except Exception:  # noqa: BLE001
        pass
    low = text.lower()
    if resp.status_code in (401, 403):
        return ("HTTP %d（密钥被拒：确认密钥属于这个服务/实例，并且在设置页按过"
                "「保存并应用」）: %s" % (resp.status_code, text))
    if "too large" in low or "file size" in low:
        # v1.14.2：百炼多模态端点对单次请求内嵌音频有体积上限，整段直传
        # （尤其降级 qwen3-asr-flash 时）会撞 This Multimodal file size is
        # too large——提示必须给"切短/压缩"出路，且不能被下面的实时误判分支吞掉。
        return ("HTTP %d（音频体积超过该端点单次上限：程序会自动把超限音频压成"
                "低码率 MP3 再传，仍超限说明音频太长——请把音频切短分段后分别转录，"
                "或改用支持大文件的服务端点）: %s" % (resp.status_code, text))
    if "too long" in low:
        return ("HTTP %d（音频时长超过该端点单次上限：程序会自动对半切分重试，"
                "仍失败则请把音频切短分段，或换支持长音频的模型）: %s"
                % (resp.status_code, text))
    if ("invalidparameter" in low or "invalid parameter" in low
            or "model not" in low or "unsupported" in low):
        return ("HTTP %d（参数或模型名不被该端点支持——注意实时（realtime）"
                "模型不能一次性上传调用）: %s" % (resp.status_code, text))
    if resp.status_code in (400, 500) and (
            not text.strip() or text.strip() == "{}"
            or ("internalerror" in low and "unknown" in low)):
        return ("HTTP %d（端点返回空体/未知错误：① 模型与端点不配套——"
                "Qwen-Audio-3.0-ASR-Flash（qwen-audio-3.0-asr-flash）这类百炼"
                "原生 ASR 模型走的是 multimodal-generation 端点，拿兼容模式的 "
                "chat/completions 打恒回空体 400，请把「接口协议」选为"
                "「百炼原生（ASR 专用端点）」或留自动识别；② 名字带 *realtime* "
                "的实时对话/翻译模型（如 livetranslate）、*tts* 语音合成模型"
                "都做不了录音转写，请改 qwen3-asr-flash、"
                "FunAudioLLM/SenseVoiceSmall、whisper-1 等；"
                "maas 专属实例请到百炼控制台确认实例已部署该模型"
                "（其 /models 列表不显示 ASR 模型，以控制台为准）；"
                "并确认地址与模型属同一计费套餐）: %s"
                % (resp.status_code, text))
    return "HTTP %d: %s" % (resp.status_code, text)


def _asr_normalize_resp(resp, asr_obj):
    """把各协议响应归一成引擎 _make_segments 可解析的 dict。

    已含 segments/words（带原生时间轴）→ 原样返回；纯文本/仅 text →
    按句切分 + 时长占比生成近似时间轴（无时间戳协议的兜底）。
    """
    if isinstance(resp, dict) and ("segments" in resp or "words" in resp):
        return _asr_apply_speaker_labels(resp)
    if isinstance(resp, dict):
        text = str(resp.get("text") or "")
    else:
        text = str(resp or "")
    return {"text": text,
            "segments": _asr_text_to_segments(text, getattr(asr_obj,
                                                            "audio_duration",
                                                            0))}


def _asr_azure_submit(asr_obj):
    """Azure OpenAI 语音转文字：POST …/deployments/<部署>/audio/transcriptions。

    地址允许填资源根或填到 deployments/<部署名>（自动补齐路径与 api-version），
    鉴权用 api-key 头（与 LLM 的 Azure 适配同一套约定）。
    """
    import requests
    base = (asr_obj.base_url or "").strip().rstrip("/")
    model = (asr_obj.model or "").strip()
    if "/openai/deployments/" not in base.lower():
        base = f"{base}/openai/deployments/{model}" if model else \
            f"{base}/openai/deployments"
    low = base.lower()
    if not low.endswith("/audio/transcriptions"):
        base = base + "/audio/transcriptions"
    if "api-version=" not in base:
        base = f"{base}{'&' if '?' in base else '?'}api-version=2024-10-21"
    fmt = _asr_audio_format(asr_obj.file_binary or b"")
    form = {"response_format": "verbose_json"}
    if asr_obj.language:
        form["language"] = asr_obj.language
    if asr_obj.prompt:
        form["prompt"] = asr_obj.prompt
    r = requests.post(
        base, headers={"api-key": asr_obj.api_key}, data=form,
        files={"file": (f"audio.{fmt}", asr_obj.file_binary or b"",
                        f"audio/{fmt}")},
        proxies=http_proxies_for(base), timeout=300)
    if r.status_code != 200:
        raise RuntimeError(f"Azure ASR HTTP {r.status_code}: {r.text[:200]}")
    try:
        return r.json()
    except ValueError:
        return {"text": r.text}


#: 多模态请求（chat_audio 的 Data URL / gemini 的 inline_data）内嵌音频的
#: 原始字节上限：base64 会再放大约 4/3，6.5MB 原始 ≈ 8.7MB 编码后，贴着百炼
#: compatible-mode 多模态请求体上限留余量。超限先压缩，再不行由服务端报体积错。
ASR_INLINE_AUDIO_MAX_RAW = 6_500_000

#: "audio is too long" 自动对半切分的最大递归层数（2^3=8 段封顶，防无限拆）
ASR_SPLIT_MAX_DEPTH = 3


def _asr_shrink_audio_blob(blob, max_raw_bytes):
    """超过内嵌上限的音频 → ffmpeg 压成低码率单声道 MP3（v1.14.2）。

    chat_audio / gemini 这类"音频进 JSON"的协议，原始文件直接 base64 会撑爆
    请求体上限（百炼报 Multimodal file size is too large）。语音识别对码率不
    敏感，32k/16k 单声道 MP3 足够。任何一步失败（无 ffmpeg/解码失败/越压越大）
    都**原样返回**，让服务端回它自己的错误码——绝不把用户音频弄丢或弄坏。
    """
    blob = blob or b""
    if len(blob) <= max_raw_bytes:
        return blob
    try:
        ffmpeg, _ffprobe = ensure_ffmpeg()
    except Exception:  # noqa: BLE001
        ffmpeg = ""
    if not ffmpeg:
        return blob
    import subprocess as _sp
    import tempfile as _tf
    src = dst = ""
    try:
        with _tf.NamedTemporaryFile(suffix="." + _asr_audio_format(blob),
                                    delete=False) as tf:
            tf.write(blob)
            src = tf.name
        dst = src + ".shrink.mp3"
        for br in ("48k", "32k", "16k"):
            try:
                os.unlink(dst)
            except OSError:
                pass
            _sp.run([ffmpeg, "-y", "-i", src, "-vn", "-ac", "1",
                     "-b:a", br, dst],
                    capture_output=True, check=True, timeout=300,
                    creationflags=getattr(_sp, "CREATE_NO_WINDOW", 0)
                    if os.name == "nt" else 0)
            data = open(dst, "rb").read()
            if data and len(data) <= max_raw_bytes:
                return data
        return blob          # 压到底仍超限/全部失败：原样交给服务端判
    except Exception:  # noqa: BLE001 非音频坏数据或 ffmpeg 报错
        return blob
    finally:
        for p in (src, dst):
            if p:
                try:
                    os.unlink(p)
                except OSError:
                    pass


def _asr_split_audio_blob(blob):
    """按中点切成（前半, 后半）两段 wav；切不了返回 None（v1.14.2）。

    服务端回 "The audio is too long" 时的自动补救：单请求超长 ⇒ 对半切开分别
    提交、文本顺序拼回（时间轴由本程序按段占比近似，见 _asr_normalize_resp）。
    """
    if not blob:
        return None
    try:
        ffmpeg, ffprobe = ensure_ffmpeg()
    except Exception:  # noqa: BLE001
        return None
    if not ffmpeg or not ffprobe:
        return None
    import json as _json
    import subprocess as _sp
    import tempfile as _tf
    src = o1 = o2 = ""
    try:
        with _tf.NamedTemporaryFile(suffix="." + _asr_audio_format(blob),
                                    delete=False) as tf:
            tf.write(blob)
            src = tf.name
        pr = _sp.run([ffprobe, "-v", "error", "-show_entries",
                      "format=duration", "-of", "json", src],
                     capture_output=True, text=True, timeout=60,
                     creationflags=getattr(_sp, "CREATE_NO_WINDOW", 0)
                     if os.name == "nt" else 0)
        dur = float((_json.loads(pr.stdout or "{}")
                     .get("format") or {}).get("duration") or 0)
        if dur < 2:
            return None                       # 太短不值得切
        half = dur / 2.0
        o1, o2 = src + ".a.wav", src + ".b.wav"
        _sp.run([ffmpeg, "-y", "-i", src, "-t", "%.3f" % half,
                 "-vn", "-ac", "1", o1],
                capture_output=True, check=True, timeout=300,
                creationflags=getattr(_sp, "CREATE_NO_WINDOW", 0)
                if os.name == "nt" else 0)
        _sp.run([ffmpeg, "-y", "-i", src, "-ss", "%.3f" % half,
                 "-vn", "-ac", "1", o2],
                capture_output=True, check=True, timeout=300,
                creationflags=getattr(_sp, "CREATE_NO_WINDOW", 0)
                if os.name == "nt" else 0)
        a = open(o1, "rb").read()
        b = open(o2, "rb").read()
        return (a, b) if a and b else None
    except Exception:  # noqa: BLE001
        return None
    finally:
        for p in (src, o1, o2):
            if p:
                try:
                    os.unlink(p)
                except OSError:
                    pass


def _asr_chat_audio_submit(asr_obj, depth=0):
    """Chat 音频转写（OpenAI 兼容 chat/completions + input_audio）：

    POST {base}/chat/completions，音频以 input_audio 进多模态 messages。
    这一族目前包括：**阿里云百炼** Qwen-ASR（qwen3-asr-flash / qwen-audio-asr，
    含 maas 专属实例）、**小米 MiMo**（mimo-v2.5-asr）。

    ⚠️ `data` 必须是 **Data URL**（`data:audio/mp3;base64,…`）：两家官方示例
    都是这个形态，它自带 MIME、不必再给 format；只发裸 base64 会被判成无效
    音频。⚠️ 这些服务**没有** `/audio/transcriptions` 端点，别按 openai 协议调。
    ⚠️ 音频格式支持有限（百炼/MiMo 都主打 mp3、wav），其它容器请先转码。
    """
    import base64
    import requests
    base = (asr_obj.base_url or "").strip().rstrip("/")
    if not base.lower().endswith("/chat/completions"):
        base = base + "/chat/completions"
    # v1.14.2：整段直传是「Multimodal file size is too large」的头号来源
    # （尤其实时模型断连后自动降级 qwen3-asr-flash 走的就是这条路）——
    # 超过内嵌上限先压成低码率 MP3 再进 Data URL。
    blob = _asr_shrink_audio_blob(asr_obj.file_binary or b"",
                                  ASR_INLINE_AUDIO_MAX_RAW)
    fmt = _asr_audio_format(blob)
    b64 = base64.b64encode(blob).decode("ascii")
    content = [{"type": "input_audio",
                "input_audio": {"data": "data:audio/%s;base64,%s" % (fmt, b64)}}]
    if asr_obj.prompt:
        content.append({"type": "text", "text": asr_obj.prompt})
    body = {"model": asr_obj.model,
            "messages": [{"role": "user", "content": content}],
            "stream": False}
    lang = str(getattr(asr_obj, "language", "") or "").strip()
    if lang and lang not in ("auto", "zh"):
        body["asr_options"] = {"language": lang}
    r = requests.post(
        base, json=body,
        headers={"Authorization": "Bearer " + asr_obj.api_key,
                 "Content-Type": "application/json"},
        proxies=http_proxies_for(base), timeout=600)
    if r.status_code != 200:
        low = (r.text or "").lower()
        if ("too long" in low or "duration" in low) \
                and depth < ASR_SPLIT_MAX_DEPTH:
            halves = _asr_split_audio_blob(blob)
            if halves:
                import types as _types
                parts = []
                for hb in halves:
                    sub = _types.SimpleNamespace(
                        base_url=asr_obj.base_url, model=asr_obj.model,
                        api_key=asr_obj.api_key,
                        language=getattr(asr_obj, "language", ""),
                        prompt=getattr(asr_obj, "prompt", ""),
                        diarize=getattr(asr_obj, "diarize", None),
                        file_binary=hb)
                    parts.append(_asr_chat_audio_submit(sub, depth + 1))
                return "".join(parts)
        if "too long" in low or "duration" in low:
            raise RuntimeError(
                "ASR 服务：音频时长超限且自动切分重试已到底（不再继续切短），"
                "请把音频切短分段后分别转录，或换支持长音频的模型。"
                "原始错误：" + _asr_err_hint(r))
        raise RuntimeError("ASR 服务 " + _asr_err_hint(r)
                           + _asr_plan_endpoint_hint(asr_obj))
    try:
        data = r.json()
        cont = data["choices"][0]["message"].get("content")
        if isinstance(cont, list):        # 多模态响应可能是 [{text:…}]
            cont = "".join(str(x.get("text") or "") for x in cont
                           if isinstance(x, dict))
        return str(cont or "")
    except (ValueError, KeyError, IndexError, TypeError) as e:
        raise RuntimeError(f"ASR 响应格式无法解析：{e}; body={r.text[:200]}")


#: 历史名（可能出现在旧配置 / 日志 / 自检里）：两个名字指同一实现
_asr_dashscope_submit = _asr_chat_audio_submit


def _asr_native_output(resp):
    """百炼原生 ASR 响应 → {"text", "segments"}（词级时间轴优先）。

    原生端点**没有 choices**：文本在 `output.sentence.text` / `output.text`
    （专属实例还会在顶层再复制一份 `sentence`/`text`）；`output.sentence.words[]`
    带毫秒级 begin_time/end_time 与独立 punctuation → 原生词级时间轴，
    聚合交给 _asr_words_to_segments（与 Deepgram/ElevenLabs 同一条路）。
    """
    try:
        data = resp.json()
    except (ValueError, AttributeError):
        data = {}
    if not isinstance(data, dict):
        return {"text": "", "segments": []}
    out = data.get("output") if isinstance(data.get("output"), dict) else {}
    # 开启说话人分离后官方改走 output.sentences[]（每个句子带 speaker_id），
    # 与不分离时的 output.sentence（单个对象）不是同一个字段——先认数组形态。
    sents = out.get("sentences")
    if not isinstance(sents, list):
        sents = data.get("sentences") \
            if isinstance(data.get("sentences"), list) else None
    if sents:
        words, texts = [], []
        for s in sents:
            if not isinstance(s, dict):
                continue
            t = str(s.get("text") or "")
            if t:
                texts.append(t)
            spk = s.get("speaker_id")
            for w in (s.get("words") or []):
                if not isinstance(w, dict):
                    continue
                tok = (str(w.get("text") or "")
                       + str(w.get("punctuation") or "")).strip()
                if not tok:
                    continue
                try:
                    b = float(w.get("begin_time")) / 1000.0
                    e = float(w.get("end_time")) / 1000.0
                except (TypeError, ValueError):
                    continue
                item = {"word": tok, "start": b, "end": e}
                if spk is not None:
                    item["speaker"] = str(spk)
                words.append(item)
        full = "".join(texts)
        if words:
            return {"text": full, "segments": _asr_words_to_segments(words)}
        return {"text": full, "segments": []}
    sent = out.get("sentence") if isinstance(out.get("sentence"), dict) else {}
    if not sent and isinstance(data.get("sentence"), dict):
        sent = data["sentence"]
    text = str(sent.get("text") or out.get("text") or data.get("text") or "")
    words = []
    for w in (sent.get("words") or []):
        if not isinstance(w, dict):
            continue
        tok = (str(w.get("text") or "") + str(w.get("punctuation") or "")).strip()
        if not tok:
            continue
        try:
            b = float(w.get("begin_time")) / 1000.0
            e = float(w.get("end_time")) / 1000.0
        except (TypeError, ValueError):
            continue
        words.append({"word": tok, "start": b, "end": e})
    if words:
        return {"text": text, "segments": _asr_words_to_segments(words)}
    return {"text": text, "segments": []}


def _asr_dashscope_native_submit(asr_obj, depth=0):
    """百炼原生录音文件识别（POST /api/v1/services/aigc/multimodal-generation/
    generation）——Qwen-Audio-3.0-ASR-Flash / Fun-ASR-Flash 等专用。

    与 chat_audio 的差别（v1.15.6 实测）：同一个模型、同一份音频，打
    compatible-mode 的 chat/completions 恒回 HTTP 400 空体 `{}`；换成本端点
    即 200 并返回词级时间轴。音频同样用 base64 Data URL（官方示例形态之一），
    另需 `parameters.format`（wav/mp3…），wav 再带 sample_rate。
    """
    import base64
    import requests
    url = _asr_native_url(getattr(asr_obj, "base_url", ""))
    blob = _asr_shrink_audio_blob(getattr(asr_obj, "file_binary", b"") or b"",
                                  ASR_INLINE_AUDIO_MAX_RAW)
    fmt = _asr_audio_format(blob)
    rate = _asr_wav_sample_rate(blob) or 16000
    content = [{"type": "input_audio",
                "input_audio": {"data": "data:audio/%s;base64,%s"
                                        % (fmt, base64.b64encode(blob).decode("ascii"))}}]
    params = {"format": fmt}
    if fmt == "wav":
        params["sample_rate"] = str(rate)
    if _asr_diarize_on(asr_obj):
        # 说话人分离：**仅 qwen-audio-3.1-asr-flash 支持**（官方文档标注）。
        # 3.0 / fun-asr-flash 上带这个参数会被拒或忽略——所以脚本只在用户
        # 主动开了开关时才下传，不开就与 v1.15.7 完全一致。
        params["speaker_diarization_enabled"] = True
    body = {"model": asr_obj.model,
            "input": {"messages": [{"role": "user", "content": content}]},
            "parameters": params}
    r = requests.post(url, json=body,
                      headers={"Authorization": "Bearer " + asr_obj.api_key,
                               "Content-Type": "application/json"},
                      proxies=http_proxies_for(url), timeout=600)
    if r.status_code != 200:
        low = (r.text or "").lower()
        # ① 静音分块：400 空体 + 音频无声 → 这段本来就没内容，返回空即可。
        #    不做这一步，直播回放里夹的静音段会让**整条转录**判失败
        #    （短视频恰好没静音段所以能过 —— 用户实测就是这个形态）。
        if r.status_code == 400 and (r.text or "").strip() in ("", "{}"):
            # ② 内容类失败：400 空体 = 「这段没有可识别语音」。实测同参数下
            #    600s 处 20s 片段回 200 + 279 字符，而 60s 处的 30s/280s 片段
            #    恒回 400 —— 后者是游戏音乐/音效段（音量正常但无语音）。
            #    直播回放里这类片段极多，一律当致命错误就会**整条转录必挂**
            #    （用户实测：短视频过、5 小时回放过不去，就是这个形态）。
            #    密钥/权限问题回 401/403 而不是 400 空体，故此处可安全跳过。
            _vc_log("原生 ASR：该分块无可识别语音（400 空体），按无内容跳过")
            return ""
        if ("too long" in low or "duration" in low) \
                and depth < ASR_SPLIT_MAX_DEPTH:
            halves = _asr_split_audio_blob(blob)
            if halves:
                import types as _types
                parts = []
                for hb in halves:
                    sub = _types.SimpleNamespace(
                        base_url=getattr(asr_obj, "base_url", ""),
                        model=asr_obj.model, api_key=asr_obj.api_key,
                        language=getattr(asr_obj, "language", ""),
                        prompt="", diarize=getattr(asr_obj, "diarize", None),
                        file_binary=hb)
                    parts.append(_asr_native_text(
                        _asr_dashscope_native_submit(sub, depth + 1)))
                return "".join(parts)
        raise RuntimeError("百炼原生 ASR " + _asr_err_hint(r)
                           + _asr_plan_endpoint_hint(asr_obj)
                           + asr_missing_model_hint(asr_obj))
    return _asr_native_output(r)


#: 百炼 Filetrans（异步文件转写）提交端点路径
ASR_FILETRANS_PATH = "/api/v1/services/audio/asr/transcription"

#: 百炼临时存储上传凭证端点（action=getPolicy）
ASR_UPLOAD_POLICY_PATH = "/api/v1/uploads"

#: Filetrans 任务轮询上限：5 秒一次 × 240 次 = 20 分钟（与 AssemblyAI 一致）
ASR_FILETRANS_POLL_MAX = 240


def _asr_dashscope_root(base_url):
    """从「接口地址」推百炼站点根（只留 scheme://host，去掉全部路径）。

    Filetrans 的上传凭证、任务提交、任务查询三个端点都在站点根下，与
    compatible-mode / multimodal-generation 不是同一层路径，所以这里要
    把用户填的 `…/compatible-mode/v1` 之类全部削掉，只留域名。
    """
    b = asr_strip_endpoint_tail(str(base_url or "").strip())
    if not b:
        return "https://dashscope.aliyuncs.com"
    if "//" in b:
        scheme, rest = b.split("//", 1)
        return scheme + "//" + rest.split("/", 1)[0]
    return "https://" + b.split("/", 1)[0]


def _asr_dashscope_upload_oss(root, model, blob, fmt, api_key):
    """把本地音频传到百炼临时存储，返回 `oss://…` 链接（官方称临时 URL）。

    Filetrans 不收本地文件也不收 Base64——只吃公网 URL，RESTful 下额外接受
    `oss://`。桌面端的音频在本地，所以只能先走这一步。
    ⚠️ 官方限制：临时 URL 有效期 48 小时、凭证接口限流 100 QPS，文档明确
    「请勿用于生产环境」。
    """
    import time
    import requests
    pol = requests.get(root + ASR_UPLOAD_POLICY_PATH,
                       params={"action": "getPolicy", "model": model},
                       headers={"Authorization": "Bearer " + api_key},
                       proxies=http_proxies_for(root), timeout=120)
    if pol.status_code != 200:
        raise RuntimeError("百炼上传凭证获取失败 " + _asr_err_hint(pol))
    try:
        d = (pol.json() or {}).get("data") or {}
    except ValueError as e:
        raise RuntimeError(f"上传凭证响应异常：{e}; body={pol.text[:200]}")
    host = str(d.get("upload_host") or "").strip()
    udir = str(d.get("upload_dir") or "").strip()
    if not host or not udir:
        raise RuntimeError("上传凭证缺少 upload_host / upload_dir：%s"
                           % pol.text[:200])
    fname = "vt_audio_%d.%s" % (int(time.time()), fmt)
    key = udir.rstrip("/") + "/" + fname
    form = {"OSSAccessKeyId": str(d.get("oss_access_key_id") or ""),
            "policy": str(d.get("policy") or ""),
            "Signature": str(d.get("signature") or ""),
            "key": key,
            "x-oss-object-acl": str(d.get("x_oss_object_acl") or "private"),
            "x-oss-forbid-overwrite": str(d.get("x_oss_forbid_overwrite") or "true"),
            "success_action_status": "200"}
    # file 字段必须是表单最后一项（OSS 要求）
    up = requests.post(host, data=form,
                       files={"file": (fname, blob, "audio/%s" % fmt)},
                       proxies=http_proxies_for(host), timeout=600)
    if up.status_code not in (200, 204):
        raise RuntimeError("音频上传到百炼临时存储失败 HTTP %d：%s"
                           % (up.status_code, up.text[:200]))
    return "oss://" + key


def _asr_filetrans_result_url(output):
    """取 Filetrans 结果 JSON 的下载地址。

    不同模型族字段不一样（踩过一次就得记下来）：
      · qwen-audio-3.x-asr-flash-filetrans / fun-asr → `output.results[].transcription_url`
      · qwen3-asr-flash-filetrans                    → `output.result.transcription_url`
    """
    res = output.get("results")
    if isinstance(res, list) and res:
        return str((res[0] or {}).get("transcription_url") or "")
    one = output.get("result")
    if isinstance(one, dict):
        return str(one.get("transcription_url") or "")
    return ""


def _asr_dashscope_filetrans_submit(asr_obj):
    """百炼 Filetrans 异步文件转写（POST /api/v1/services/audio/asr/transcription）。

    为什么单独一条协议：同步端点（multimodal-generation）有音频体积/时长上限，
    长音频要靠这条**提交-轮询**的异步链路；它也是 3.0 / fun-asr 上唯一能开
    说话人分离的通道（原生同步端点的 speaker_diarization_enabled 只认 3.1）。

    ⚠️ 与同步端点的根本差别：**不收本地音频**。官方明确 file_urls 只支持公网
    HTTP/HTTPS（RESTful 下额外支持 `oss://` 临时 URL），不支持 Base64、不支持
    二进制流、不支持本地路径。因此桌面端必须先把音频传到百炼临时存储
    （_asr_dashscope_upload_oss），再拿 `oss://` 链接提交，并在请求头带
    `X-DashScope-OssResourceResolve: enable` 让服务端解析。

    ⚠️ 说话人分离的两条硬限制（官方）：**仅单声道音频**；建议时长 ≤ 2 小时。
    """
    import time
    import requests
    root = _asr_dashscope_root(getattr(asr_obj, "base_url", ""))
    key = str(asr_obj.api_key or "")
    model = (asr_obj.model or "").strip()
    low_m = model.lower()
    # 用户常常直接填 qwen3-asr-flash（同步模型名）却选了 Filetrans：补后缀
    if model and "filetrans" not in low_m and low_m.startswith("qwen"):
        model = model + "-filetrans"
        low_m = model.lower()
    blob = getattr(asr_obj, "file_binary", b"") or b""
    fmt = _asr_audio_format(blob)
    oss_url = _asr_dashscope_upload_oss(root, model, blob, fmt, key)

    params = {"channel_id": [0]}
    if _asr_diarize_on(asr_obj):
        params["diarization_enabled"] = True
    lang = str(getattr(asr_obj, "language", "") or "").strip()
    if lang and lang not in ("auto", "zh"):
        params["language_hints"] = [lang]
    url = root + ASR_FILETRANS_PATH
    headers = {"Authorization": "Bearer " + key,
               "Content-Type": "application/json",
               "X-DashScope-Async": "enable",
               "X-DashScope-OssResourceResolve": "enable"}
    # qwen3 系用 input.file_url（单对象），qwen-audio / fun-asr 用 file_urls（数组）
    if low_m.startswith("qwen3-"):
        payload = {"model": model, "input": {"file_url": oss_url},
                   "parameters": params}
        alt = {"model": model, "input": {"file_urls": [oss_url]},
               "parameters": params}
    else:
        payload = {"model": model, "input": {"file_urls": [oss_url]},
                   "parameters": params}
        alt = {"model": model, "input": {"file_url": oss_url},
               "parameters": params}
    sub = requests.post(url, json=payload, headers=headers,
                        proxies=http_proxies_for(url), timeout=120)
    if sub.status_code >= 400:
        # 两个模型族的 input 字段不通用，被拒时换另一种形态再试一次
        sub = requests.post(url, json=alt, headers=headers,
                            proxies=http_proxies_for(url), timeout=120)
    if sub.status_code != 200:
        raise RuntimeError("百炼 Filetrans 提交失败 " + _asr_err_hint(sub)
                           + _asr_plan_endpoint_hint(asr_obj))
    try:
        tid = ((sub.json() or {}).get("output") or {}).get("task_id")
    except (ValueError, AttributeError, TypeError) as e:
        raise RuntimeError(f"提交响应异常：{e}; body={sub.text[:200]}")
    if not tid:
        raise RuntimeError("提交未返回 task_id：%s" % sub.text[:200])

    turl = root + "/api/v1/tasks/" + str(tid)
    out = None
    for _ in range(ASR_FILETRANS_POLL_MAX):
        time.sleep(5)
        got = requests.get(turl, headers={"Authorization": "Bearer " + key},
                           proxies=http_proxies_for(turl), timeout=60)
        if got.status_code != 200:
            raise RuntimeError("百炼 Filetrans 查询失败 " + _asr_err_hint(got))
        data = (got.json() or {}).get("output") or {}
        state = str(data.get("task_status") or "").upper()
        if state == "SUCCEEDED":
            out = data
            break
        if state in ("FAILED", "CANCELED", "CANCELLED"):
            raise RuntimeError(
                "百炼 Filetrans 任务失败：%s"
                % str(data.get("code") or data.get("message") or "")[:200])
    if out is None:
        raise RuntimeError("百炼 Filetrans 任务超时（轮询 20 分钟仍未完成）")

    trs = out.get("transcripts")
    js_url = _asr_filetrans_result_url(out)
    if not trs and js_url:
        jr = requests.get(js_url, proxies=http_proxies_for(js_url), timeout=300)
        if jr.status_code != 200:
            raise RuntimeError("下载转写结果失败 HTTP %d：%s"
                               % (jr.status_code, jr.text[:200]))
        try:
            trs = (jr.json() or {}).get("transcripts") or []
        except ValueError as e:
            raise RuntimeError(f"转写结果 JSON 解析失败：{e}; body={jr.text[:200]}")
    if not trs:
        raise RuntimeError("百炼 Filetrans 结果为空（无 transcripts）")

    segs, words, texts = [], [], []
    for tr in (trs or []):
        if not isinstance(tr, dict):
            continue
        for s in (tr.get("sentences") or []):
            if not isinstance(s, dict):
                continue
            t = str(s.get("text") or "").strip()
            spk = s.get("speaker_id")
            spk = None if spk is None else str(spk)
            ws = []
            for w in (s.get("words") or []):
                if not isinstance(w, dict):
                    continue
                tok = (str(w.get("text") or "")
                       + str(w.get("punctuation") or "")).strip()
                if not tok:
                    continue
                try:
                    wb = float(w.get("begin_time")) / 1000.0
                    we = float(w.get("end_time")) / 1000.0
                except (TypeError, ValueError):
                    continue
                item = {"word": tok, "start": wb, "end": we}
                if spk is not None:
                    item["speaker"] = spk
                ws.append(item)
            if ws:
                words.extend(ws)
            elif t:
                try:
                    b = float(s.get("begin_time") or 0) / 1000.0
                    e = float(s.get("end_time") or 0) / 1000.0
                except (TypeError, ValueError):
                    b = e = 0.0
                seg = {"text": t, "start": round(b, 3), "end": round(e, 3)}
                if spk is not None:
                    seg["speaker"] = spk
                segs.append(seg)
            if t:
                texts.append(t)
    full = "".join(texts)
    if words and not segs:
        return {"text": full, "segments": _asr_words_to_segments(words)}
    if segs:
        return {"text": full, "segments": segs}
    return full


def _asr_native_text(resp):
    """_asr_native_output 的结果取纯文本（切分重试时拼接用）。"""
    if isinstance(resp, dict):
        return str(resp.get("text") or "")
    return str(resp or "")


def _asr_retry_native(asr_obj, reason=""):
    """chat_audio 拿到空体 400/500 时改走百炼原生端点（同模型同音频）。

    Fun-ASR-Flash 等官方也挂在原生端点上，但老配置/某些网关按 chat_audio
    也能用 —— 所以不做静态推断，只在 chat_audio 明确失败（空体）时兜一次，
    且**每个任务只兜一次**（`_vt_native_retried` 标记），避免来回打。
    """
    if getattr(asr_obj, "_vt_native_retried", False):
        raise RuntimeError("ASR 服务 " + str(reason or "接口不可用"))
    if not _asr_is_dashscope_base(getattr(asr_obj, "base_url", "")):
        raise RuntimeError("ASR 服务 " + str(reason or "接口不可用"))
    try:
        asr_obj._vt_native_retried = True
    except Exception:  # noqa: BLE001
        pass
    _vc_log("chat_audio 空体失败（%s）→ 改走百炼原生 multimodal-generation"
            % str(reason)[:80])
    return _asr_dashscope_native_submit(asr_obj)


def _asr_is_dashscope_base(base_url):
    """是否百炼系地址（公共 dashscope 或 *.maas.aliyuncs.com 专属实例）。"""
    b = str(base_url or "").lower()
    return "dashscope" in b or "aliyuncs.com" in b


#: 只可能在境内可达的国内 AI/ASR 端点后缀（v1.15.6 代理劫持修复用）。
DOMESTIC_AI_ENDPOINT_SUFFIXES = (
    "aliyuncs.com",         # 百炼：dashscope / *.maas.aliyuncs.com 专属实例
    "aliyun.com",
    "volces.com",           # 火山方舟
    "volcengine.com",
    "volcengineapi.com",
    "bytedance.com",        # openspeech.bytedance.com
    "bigmodel.cn",          # 智谱
    "xfyun.cn",             # 讯飞
    "baidubce.com",
    "tencentcloudapi.com",
)


def is_domestic_ai_endpoint(url):
    """端点是否属于「只在境内可达」的国内 AI/ASR 服务。"""
    try:
        from urllib.parse import urlsplit
        host = (urlsplit(str(url or "")).hostname or "").lower()
    except Exception:  # noqa: BLE001
        return False
    return any(host == s or host.endswith("." + s)
               for s in DOMESTIC_AI_ENDPOINT_SUFFIXES)


def http_proxies_for(url):
    """requests 的 ``proxies`` 取值：国内端点强制直连，其余返回 None（跟随系统）。

    requests 默认 ``trust_env=True``，在 Windows 下会**读注册表**
    ``HKCU\\...\\Internet Settings``，于是 Clash / FlClash 一类客户端的系统
    代理被套给**所有**请求。实测 ``token-plan.cn-beijing.maas.aliyuncs.com``
    被送进 FlClash 的 ``127.0.0.1:7890``；该订阅规则兜底是 ``MATCH,SELECT``，
    域名后缀不是 ``.cn`` 又没命中 GEOIP 直连 ⇒ 走海外节点，而该端点是阿里云
    北京 NLB 专有入口，海外节点转发失败即被对端断连，抛 ``ProxyError:
    ... RemoteDisconnected('Remote end closed connection without response')``；
    同一份音频直连则完全正常（返 401 而非 ProxyError）。

    故：国内端点显式直连，国外端点保持跟随系统代理（它们反而需要代理才能
    访问）。

    ⚠️ ``all`` 键**必须一起覆盖**（requests 2.34.2 实测）：环境里存在
    ``ALL_PROXY`` 时 ``getproxies()`` 会给出 ``all`` 键，只写 http/https 的
    话 ``merge_environment_settings`` 里的 ``setdefault('all', …)`` 仍会把
    代理塞回来（merged 变成 ``{'all': …}``），照旧走代理；写成三项全 None
    后 merged 才是空 dict，请求真正直连。
    """
    if is_domestic_ai_endpoint(url):
        return {"http": None, "https": None, "all": None}
    return None


def _asr_empty_body_err(exc):
    """异常是否属「HTTP 400/500 空体」——原生专用模型被兼容模式打回的形态。

    _asr_err_hint 会把空体错误写成「HTTP 400（端点返回空体/未知错误：…）」，
    未包装的诊断文本则是 `HTTP 400: {}`，两种都认。
    """
    s = str(exc or "")
    return ("空体" in s) or ("HTTP 400: {}" in s) or ("HTTP 500: {}" in s)


def _asr_wav_sample_rate(blob):
    """从 wav 头读采样率；非 wav / 读不到返回 0（调用方兜 16000）。"""
    try:
        if blob[:4] == b"RIFF" and blob[8:12] == b"WAVE":
            return int.from_bytes(blob[24:28], "little")
    except Exception:  # noqa: BLE001
        pass
    return 0


def _asr_deepgram_submit(asr_obj):
    """Deepgram 预录音频识别：POST {base}/v1/listen，原始音频字节 + Token 头。

    地址允许填 https://api.deepgram.com 或填到 /v1（自动补 /listen）。
    响应带词级时间轴（results.channels[0].alternatives[0].words），
    这里聚合成句级 segments 交给引擎。
    """
    import requests
    b = (asr_obj.base_url or "").strip().rstrip("/") or "https://api.deepgram.com"
    low = b.lower()
    if low.endswith("/listen"):
        url = b
    elif low.endswith("/v1"):
        url = b + "/listen"
    else:
        url = b + "/v1/listen"
    fmt = _asr_audio_format(asr_obj.file_binary or b"")
    params = {"model": (asr_obj.model or "nova-3"),
              "smart_format": "true", "punctuate": "true"}
    lang = str(getattr(asr_obj, "language", "") or "").strip()
    if lang and lang not in ("auto", "zh"):
        params["language"] = lang
    elif lang == "zh":
        params["language"] = "zh-CN"
    r = requests.post(
        url, params=params, data=asr_obj.file_binary or b"",
        headers={"Authorization": "Token " + asr_obj.api_key,
                 "Content-Type": "audio/%s" % fmt},
        proxies=http_proxies_for(url), timeout=600)
    if r.status_code != 200:
        raise RuntimeError("ASR 服务 " + _asr_err_hint(r))
    try:
        alt = r.json()["results"]["channels"][0]["alternatives"][0]
    except (ValueError, KeyError, IndexError, TypeError) as e:
        raise RuntimeError(f"ASR 响应格式无法解析：{e}; body={r.text[:200]}")
    return _asr_words_response(
        alt.get("transcript") or "",
        [{"word": w.get("punctuated_word") or w.get("word"),
          "start": w.get("start"), "end": w.get("end")}
         for w in (alt.get("words") or [])])


def _asr_elevenlabs_submit(asr_obj):
    """ElevenLabs Scribe：POST {base}/v1/speech-to-text（multipart + xi-api-key）。

    响应 {text, words:[{text,start,end}], language_code} —— 同样聚合成句级。
    """
    import requests
    b = (asr_obj.base_url or "").strip().rstrip("/") or "https://api.elevenlabs.io"
    url = b if b.lower().endswith("/speech-to-text") else b + "/v1/speech-to-text"
    fmt = _asr_audio_format(asr_obj.file_binary or b"")
    form = {"model_id": (asr_obj.model or "scribe_v1"),
            "timestamps_granularity": "word"}
    lang = str(getattr(asr_obj, "language", "") or "").strip()
    if lang and lang not in ("auto", "zh"):
        form["language_code"] = lang
    r = requests.post(
        url, data=form,
        files={"file": ("audio.%s" % fmt, asr_obj.file_binary or b"",
                        "audio/%s" % fmt)},
        headers={"xi-api-key": asr_obj.api_key},
        proxies=http_proxies_for(url), timeout=600)
    if r.status_code != 200:
        raise RuntimeError("ASR 服务 " + _asr_err_hint(r))
    try:
        data = r.json()
    except ValueError as e:
        raise RuntimeError(f"ASR 响应格式无法解析：{e}; body={r.text[:200]}")
    return _asr_words_response(
        data.get("text") or "",
        [{"word": w.get("text") or w.get("word"),
          "start": w.get("start"), "end": w.get("end")}
         for w in (data.get("words") or [])])


def _asr_gemini_submit(asr_obj):
    """Google Gemini 多模态音频理解：POST models/<model>:generateContent。

    返回纯文本（无时间轴），由 _asr_normalize_resp 按句切分兜底；提示词优先
    用用户填的「识别提示词」，没填就给一句"逐字转写"的指令。
    """
    import base64
    import requests
    b = (asr_obj.base_url or "").strip().rstrip("/") \
        or "https://generativelanguage.googleapis.com"
    model = (asr_obj.model or "gemini-2.5-flash").strip()
    url = "%s/v1beta/models/%s:generateContent" % (b, model)
    # v1.14.2：与 chat_audio 同理，inline_data 的体积上限先压缩再编码
    blob = _asr_shrink_audio_blob(asr_obj.file_binary or b"",
                                  ASR_INLINE_AUDIO_MAX_RAW)
    fmt = _asr_audio_format(blob)
    b64 = base64.b64encode(blob).decode("ascii")
    instruction = (getattr(asr_obj, "prompt", "") or "").strip() \
        or "请把这段音频逐字转写为文本，只输出转写内容，不要加解释或标注。"
    body = {"contents": [{"parts": [
        {"inline_data": {"mime_type": "audio/%s" % fmt, "data": b64}},
        {"text": instruction}]}]}
    r = requests.post(url, json=body,
                      headers={"x-goog-api-key": asr_obj.api_key,
                               "Content-Type": "application/json"},
                      proxies=http_proxies_for(url), timeout=600)
    if r.status_code != 200:
        raise RuntimeError("ASR 服务 " + _asr_err_hint(r))
    try:
        parts = r.json()["candidates"][0]["content"]["parts"]
        return "".join(str(p.get("text") or "") for p in parts)
    except (ValueError, KeyError, IndexError, TypeError) as e:
        raise RuntimeError(f"ASR 响应格式无法解析：{e}; body={r.text[:200]}")


#: 火山（豆包）录音识别极速版默认资源 ID
VOLC_DEFAULT_RESOURCE = "volc.bigasr.auc_turbo"

#: AssemblyAI 默认模型（官方的 speech_models 必填，没有默认值）
ASSEMBLYAI_DEFAULT_MODELS = ("universal-3-pro", "universal-2")


def _asr_volcengine_submit(asr_obj):
    """火山引擎（豆包）录音文件识别**极速版**：一次请求即返回，无需轮询。

    鉴权两种形态都吃（零配置改动）：
      · 新版控制台：`api_key` 填 API Key → 走 `X-Api-Key`；
      · 旧版控制台：`api_key` 填 `APPID:AccessToken`（冒号分隔）→ 走
        `X-Api-App-Key` + `X-Api-Access-Key`。
    `model` 填 Resource ID（默认 `volc.bigasr.auc_turbo`）。
    ⚠️ 状态码在**响应头** `X-Api-Status-Code`（`20000000` = OK），不在 body；
    `show_utterances=true` 才有时间轴（毫秒 → 秒）。
    """
    import base64
    import json
    import uuid
    import requests
    base = (asr_obj.base_url or "").strip().rstrip("/") \
        or "https://openspeech.bytedance.com"
    url = base if base.endswith("/recognize/flash") else \
        base + "/api/v3/auc/bigmodel/recognize/flash"
    key = str(asr_obj.api_key or "")
    headers = {"Content-Type": "application/json",
               "X-Api-Resource-Id": (asr_obj.model or VOLC_DEFAULT_RESOURCE),
               "X-Api-Request-Id": str(uuid.uuid4()),
               "X-Api-Sequence": "-1"}
    uid = ""
    if ":" in key:
        uid, _, acc = key.partition(":")
        headers["X-Api-App-Key"] = uid.strip()
        headers["X-Api-Access-Key"] = acc.strip()
    else:
        headers["X-Api-Key"] = key
    body = {"user": {"uid": uid or key},
            "audio": {"data": base64.b64encode(
                asr_obj.file_binary or b"").decode("ascii")},
            "request": {"model_name": "bigmodel", "enable_itn": True,
                        "enable_punc": True, "show_utterances": True}}
    lang = str(getattr(asr_obj, "language", "") or "").strip()
    if lang and lang not in ("auto", "zh"):
        body["request"]["language"] = lang
    if _asr_diarize_on(asr_obj):
        # 说话人分离（说话人日志）：官方标注 10 人以内效果较好。
        body["request"]["enable_speaker_info"] = True
    r = requests.post(url, data=json.dumps(body, ensure_ascii=False),
                      headers=headers, proxies=http_proxies_for(url),
                      timeout=600)
    code = r.headers.get("X-Api-Status-Code", "")
    if r.status_code != 200 or (code and code != "20000000"):
        raise RuntimeError("ASR 服务 " + _asr_err_hint(r)
                           + "（X-Api-Status-Code=%s %s）"
                           % (code or r.status_code,
                              r.headers.get("X-Api-Message", "")))
    try:
        res = (r.json() or {}).get("result") or {}
    except ValueError as e:
        raise RuntimeError(f"ASR 响应格式无法解析：{e}; body={r.text[:200]}")
    utts = res.get("utterances") or []
    ms = 1000.0
    if any(u.get("words") for u in utts):
        words = []
        for u in utts:
            spk = _asr_volc_speaker(u)
            for w in u.get("words") or []:
                item = {
                    "word": w.get("text"),
                    "start": float(w.get("start_time") or 0) / ms,
                    "end": float(w.get("end_time") or 0) / ms}
                if spk:
                    item["speaker"] = spk
                words.append(item)
        return _asr_words_response(res.get("text") or "", words)
    if utts:
        segs = []
        for u in utts:
            if not (u.get("text") or "").strip():
                continue
            seg = {"text": (u.get("text") or "").strip(),
                   "start": round(float(u.get("start_time") or 0) / ms, 3),
                   "end": round(float(u.get("end_time") or 0) / ms, 3)}
            spk = _asr_volc_speaker(u)
            if spk:
                seg["speaker"] = spk
            segs.append(seg)
        return {"text": res.get("text") or "", "segments": segs}
    return res.get("text") or ""


def _asr_volc_speaker(utt):
    """取火山分句上的说话人标识（找不到返回空串）。

    字段位置官方示例里没写死（旧版 v1 在 `utterances[].additions.speaker`，
    v3 bigmodel 的响应示例只给了 `result.additions`），所以这里把两种位置
    都试一遍——猜错字段的后果是**静默没有标签**（不报错但没效果），比报错
    更难发现，宁可多兼容几条路径。
    """
    if not isinstance(utt, dict):
        return ""
    add = utt.get("additions") if isinstance(utt.get("additions"), dict) else {}
    for v in (utt.get("speaker"), add.get("speaker"),
              add.get("speaker_id"), utt.get("speaker_id")):
        if v not in (None, ""):
            return str(v)
    return ""


def _asr_assemblyai_submit(asr_obj):
    """AssemblyAI：上传本地文件 → 提交任务 → 轮询结果（三步，异步）。

    ⚠️ 三个易错点：鉴权头是 `Authorization: <key>`（**没有 Bearer 前缀**）；
    `speech_models` 必填（不填直接报错，官方没有默认值）；词级时间轴单位是
    **毫秒**（别当秒用）。`model` 支持逗号分隔多个模型做回退。
    """
    import time
    import requests
    base = asr_strip_endpoint_tail(asr_obj.base_url, "/v2/upload",
                                   "/v2/transcript") \
        or "https://api.assemblyai.com"
    headers = {"authorization": str(asr_obj.api_key or "").strip()}
    # 1) 上传：必须是 raw bytes（不发 multipart，否则下游 Transcoding failed）
    up = requests.post(base + "/v2/upload", data=asr_obj.file_binary or b"",
                       headers=headers, proxies=http_proxies_for(base),
                       timeout=600)
    if up.status_code != 200:
        raise RuntimeError("ASR 服务 上传失败 " + _asr_err_hint(up))
    try:
        audio_url = up.json()["upload_url"]
    except (ValueError, KeyError, TypeError) as e:
        raise RuntimeError(f"上传响应异常：{e}; body={up.text[:200]}")
    # 2) 提交
    models = [m.strip() for m in str(asr_obj.model or "").split(",")
              if m.strip()] or list(ASSEMBLYAI_DEFAULT_MODELS)
    payload = {"audio_url": audio_url, "speech_models": models}
    lang = str(getattr(asr_obj, "language", "") or "").strip()
    if lang and lang not in ("auto", "zh"):
        payload["language_code"] = lang
    else:
        payload["language_detection"] = True
    if getattr(asr_obj, "prompt", ""):
        payload["prompt"] = asr_obj.prompt
    sub = requests.post(base + "/v2/transcript", json=payload, headers=headers,
                        proxies=http_proxies_for(base), timeout=120)
    if sub.status_code != 200:
        raise RuntimeError("ASR 服务 " + _asr_err_hint(sub))
    try:
        tid = (sub.json() or {}).get("id")
    except ValueError as e:
        raise RuntimeError(f"提交响应异常：{e}; body={sub.text[:200]}")
    if not tid:
        raise RuntimeError("提交未返回 transcript id：%s" % sub.text[:200])
    # 3) 轮询（官方建议 3 秒一次；20 分钟上限，避免任务卡死时无限等）
    url = base + "/v2/transcript/" + str(tid)
    for _ in range(400):
        time.sleep(3)
        got = requests.get(url, headers=headers,
                           proxies=http_proxies_for(url), timeout=60)
        if got.status_code != 200:
            raise RuntimeError("ASR 服务 查询失败 " + _asr_err_hint(got))
        data = got.json() or {}
        state = data.get("status")
        if state == "completed":
            words = [{"word": w.get("text"),
                      "start": float(w.get("start") or 0) / 1000.0,
                      "end": float(w.get("end") or 0) / 1000.0}
                     for w in (data.get("words") or [])]
            if words:
                return _asr_words_response(data.get("text") or "", words)
            return data.get("text") or ""
        if state == "error":
            raise RuntimeError("ASR 任务失败：" + str(data.get("error"))[:200])
    raise RuntimeError("ASR 任务超时（轮询 20 分钟仍未完成）")


def _asr_ws_url(base_url):
    """从「接口地址」推导百炼实时 ASR 的 WebSocket 端点。

    · 留空 / dashscope 公共 → wss://dashscope.aliyuncs.com/api-ws/v1/inference/
    · 专属实例（https://xxx.cn-beijing.maas.aliyuncs.com/…）→ 同域名换 wss，
      API 路径与公共端点一致（/api-ws/v1/inference/）
    · 用户直接填 wss://… → 尊重原样，只在缺路径时补 /api-ws/v1/inference/
    """
    b = str(base_url or "").strip().rstrip("/")
    if not b:
        return "wss://dashscope.aliyuncs.com/api-ws/v1/inference/"
    if b.lower().startswith(("wss://", "ws://")):
        low = b.lower()
        if low.endswith("/inference/"):
            return b
        if low.endswith("/inference"):
            return b + "/"
        return b + "/api-ws/v1/inference/"
    if b.lower().startswith("https://"):
        host = b[8:]
    elif b.lower().startswith("http://"):
        host = b[7:]
    else:
        host = b
    host = host.strip("/")
    if "/" in host:                       # 只取域名，路径一律换成 API 路径
        host = host.split("/", 1)[0]
    return "wss://%s/api-ws/v1/inference/" % host


#: 实时 ASR 的音频帧大小。官方示例按 100ms/3200 字节（16k/16bit）模拟实时，
#: 但批量转录要的是"尽快灌完"——64KB 一帧不 sleep，一小时音频几十秒发完；
#: 服务端按到达顺序处理，不需要对齐真实时间。
ASR_WS_FRAME_BYTES = 65536

#: 实时 ASR 推流倍速（相对 16bit 单声道 PCM 的实时字节率）。
#: ⚠️ 全速灌发实测会被服务端掐断连接（Connection to remote host was lost）：
#: 实时识别服务端按流式消费音频，输入速率远超实时会撑爆内部缓冲。默认
#: 20 倍速折中（6 分钟音频约 19 秒灌完）；VT_ASR_WS_SPEED 可调，最小 1 倍。
def _asr_ws_speed() -> float:
    """VT_ASR_WS_SPEED 归一：环境变量非数字时不炸 import（v1.16.5 修复）。

    此前写成模块级 `max(float(os.environ.get(...) or 20), 1.0)`——环境变量
    被设成非数字（如 "fast"）时 import 期抛 ValueError，整个引擎加载失败。
    """
    try:
        return max(float(os.environ.get("VT_ASR_WS_SPEED") or 20), 1.0)
    except (TypeError, ValueError):
        return 20.0


ASR_WS_SPEED = _asr_ws_speed()


def _asr_collect_sentence(msg, segments, texts):
    """把 result-generated 里的句子收进 segments（毫秒 → 秒）。

    实时流里同一句会先来"中间态"（end_time 为空、文本逐渐变长），说完才有
    带 begin/end 的最终事件 —— 只收**有终点的**，天然去重。
    """
    out = (msg.get("payload") or {}).get("output") or {}
    sent = out.get("sentence") or {}
    text = str(sent.get("text") or "").strip()
    if not text:
        return
    texts.append(text)
    b, e = sent.get("begin_time"), sent.get("end_time")
    if b is None or e is None:
        return                            # 句子还没说完，等最终事件
    try:
        b, e = float(b) / 1000.0, float(e) / 1000.0
    except (TypeError, ValueError):
        return
    if e > b:
        segments.append({"text": text, "start": round(b, 3),
                         "end": round(e, 3)})


def _asr_ws_prepare_audio(blob, model):
    """8k 专版模型 → ffmpeg 重采样为 8kHz 单声道 wav；其它模型原样返回。

    引擎提取音频固定 16kHz（video2audio `-ar 16000`），而
    fun-asr-flash-8k-realtime 等 8k 电话音专版模型**只收 8kHz**——16k 音频
    直接发过去服务端会异常断连（Connection to remote host was lost）。
    ffmpeg 不可用或转码失败时按原样返回，让服务端回具体错误码。
    """
    if "8k" not in str(model or "").lower():
        return blob, 16000
    if blob[:4] == b"RIFF" and blob[8:12] == b"WAVE":
        try:
            if int.from_bytes(blob[24:28], "little") == 8000:
                return blob, 8000              # 已是 8k wav，免转
        except Exception:  # noqa: BLE001
            pass
    try:
        ffmpeg, _ = ensure_ffmpeg()
    except Exception:  # noqa: BLE001
        ffmpeg = ""
    if not ffmpeg or not blob:
        return blob, 16000
    import subprocess as _sp
    import tempfile as _tf
    src = dst = ""
    try:
        with _tf.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
            tf.write(blob)
            src = tf.name
        dst = src + ".8k.wav"
        _sp.run([ffmpeg, "-y", "-i", src, "-vn", "-ac", "1", "-ar", "8000", dst],
                capture_output=True, check=True,
                creationflags=getattr(_sp, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0)
        with open(dst, "rb") as f:
            out = f.read()
        return (out or blob, 8000) if out else (blob, 16000)
    except Exception:  # noqa: BLE001
        return blob, 16000
    finally:
        for p in (src, dst):
            if p:
                try:
                    os.unlink(p)
                except OSError:
                    pass


def _asr_dashscope_realtime_submit(asr_obj):
    """DashScope 实时语音识别（WebSocket，协议见官方「实时语音识别 API」）。

    覆盖**只有实时形态**的模型：fun-asr-flash-8k-realtime / fun-asr-realtime /
    qwen3-asr-flash-realtime（官方模型表标注「模式=即时、API=WebSocket」，
    compatible-mode 的 chat/completions 与 /audio/transcriptions 都调不了它们）。

    交互时序：run-task → task-started → 二进制音频帧 → finish-task →
    result-generated… → task-finished。要点：
      · 握手鉴权 `Authorization: Bearer <key>`，密钥无效直接握手失败；
      · result-generated 的 `payload.output.sentence` 带 begin/end（毫秒），
        即实时模型也有**原生时间轴**，聚合成句级 segments；
      · 60 秒无消息服务端会断连 —— 推帧循环不会空闲，finish 后服务端继续
        推结果，不受影响；
      · 推帧按 ASR_WS_SPEED 倍速限速（全速灌发会被服务端断连）；
      · 8k 专版模型自动把 16k 音频重采样为 8kHz（_asr_ws_prepare_audio）；
      · 断连/超时自动重试 1 次；task-failed（参数/模型错误）不重试。
    """
    import json as _json
    import time as _time
    import uuid as _uuid

    try:
        import websocket                     # websocket-client
    except ImportError as e:
        raise RuntimeError("实时协议缺少依赖 websocket-client，"
                           "请先安装：pip install websocket-client") from e

    url = _asr_ws_url(getattr(asr_obj, "base_url", ""))
    key = str(getattr(asr_obj, "api_key", "") or "").strip()
    lang = str(getattr(asr_obj, "language", "") or "").strip()
    blob, sample_rate = _asr_ws_prepare_audio(
        asr_obj.file_binary or b"", getattr(asr_obj, "model", ""))
    fmt = _asr_audio_format(blob)
    params = {"sample_rate": sample_rate, "format": fmt}
    if lang and lang not in ("auto", "zh"):
        params["language"] = lang

    # 推帧节奏：按 16bit 单声道 PCM 字节率折算每帧"音频时长"，倍速发送
    frame_gap = ASR_WS_FRAME_BYTES / (2.0 * max(sample_rate, 1)) / ASR_WS_SPEED

    class _Transient(Exception):
        """瞬态错误（断连/超时）——值得整段重发一次。"""

    def _ws_send(ws, payload):
        """ws.send 统一包装：服务端掐断后继续 send 会抛
        WebSocketConnectionClosedException（"socket is already closed"，既不是
        _Transient 也不是 RuntimeError）——不包的话既不会自动重试、也进不了
        _submit 的降级分支，用户只会看到裸异常。统一转 _Transient，让
        「重试一次 → 仍失败 → 降级 qwen3-asr-flash 文件识别」的链路生效。
        """
        try:
            ws.send(payload)
        except Exception as e:  # noqa: BLE001
            raise _Transient("实时 ASR 连接中断（发送）：%s" % e)

    def _recv_until(ws, want, deadline, segments, texts):
        """收事件直到 want；途中的 result-generated 顺路收集。"""
        while _time.monotonic() < deadline:
            try:
                raw = ws.recv()
            except Exception as e:  # noqa: BLE001
                raise _Transient("实时 ASR 连接中断：%s" % e)
            if not raw or isinstance(raw, bytes):
                continue
            try:
                msg = _json.loads(raw)
            except ValueError:
                continue
            header = msg.get("header") or {}
            event = str(header.get("event") or "")
            if event == "result-generated":
                _asr_collect_sentence(msg, segments, texts)
            elif event == "task-failed":
                # 参数/模型/密钥类错误，重试也不会好 → 直接抛；顺带把服务端那句
                # `InvalidParameter url error, please check url!` 翻译成可操作的
                # 引导——它几乎总是「模型与实时协议不匹配」造成的。
                code = str(header.get("error_code") or "")
                emsg = str(header.get("error_message") or "")
                hint = ""
                if "url" in emsg.lower() or "invalidparameter" in code.lower():
                    hint = ("。该模型很可能不是实时（WebSocket）模型——实时模型名"
                            "通常含 realtime（如 fun-asr-flash-realtime /"
                            " qwen3-asr-flash-realtime）；若用的是文件识别模型，"
                            "请把「接口协议」改为「自动识别」")
                raise RuntimeError("实时 ASR 任务失败：%s %s%s"
                                   % (code, emsg, hint))
            elif event == want:
                return
        raise _Transient("实时 ASR 等待 %s 超时" % want)

    def _run_once():
        try:
            ws = websocket.create_connection(
                url, timeout=60,
                header={"Authorization": "Bearer " + key,
                        "user-agent": "VideoToolbox-ASR"})
        except Exception as e:  # noqa: BLE001
            msg = str(e)
            # v1.15.3：握手 401/403 是**确定性**的密钥/权限问题——重试与降级
            # 都无意义（降级到文件识别同样用这把密钥，只会再失败一次，用户
            # 反而看到两条互相矛盾的错误）。直接把结论摆出来并给出改法。
            if "401" in msg or "403" in msg:
                raise RuntimeError(
                    "实时 ASR 握手被拒（401/403）：密钥无效、或该密钥不属于这个"
                    "实例。请到「设置 → 字幕引擎」核对 ASR 密钥——**别把接口网址"
                    "粘进密钥栏**（实测踩到过），改完点「保存并应用」。端点：%s"
                    % url)
            raise _Transient("实时 ASR 连接失败（%s）：%s" % (url, msg))
        segments, texts = [], []
        task_id = _uuid.uuid4().hex[:32]     # 每次尝试新 task_id（服务端要求唯一）
        try:
            deadline = _time.monotonic() + 30 * 60      # 整体上限 30 分钟
            _ws_send(ws, _json.dumps({
                "header": {"action": "run-task", "task_id": task_id,
                           "streaming": "duplex"},
                "payload": {"task_group": "audio", "task": "asr",
                            "function": "recognition", "model": asr_obj.model,
                            "parameters": params, "input": {}}}))
            _recv_until(ws, "task-started", deadline, segments, texts)
            for i, off in enumerate(range(0, len(blob), ASR_WS_FRAME_BYTES)):
                if i and frame_gap > 0:
                    _time.sleep(frame_gap)              # 限速：防服务端断连
                _ws_send(ws, blob[off:off + ASR_WS_FRAME_BYTES])   # 二进制帧=原始音频
            _ws_send(ws, _json.dumps({"header": {"action": "finish-task",
                                                 "task_id": task_id,
                                                 "streaming": "duplex"},
                                      "payload": {"input": {}}}))
            _recv_until(ws, "task-finished", deadline, segments, texts)
        finally:
            try:
                ws.close()
            except Exception:  # noqa: BLE001
                pass
        return segments, texts

    segments = texts = None
    for attempt in (1, 2):
        try:
            segments, texts = _run_once()
            break
        except _Transient as e:
            if attempt == 1:
                _time.sleep(2)                          # 稍候重发整段
            else:
                hint = ""
                if "8k" in str(getattr(asr_obj, "model", "") or "").lower():
                    hint = ("；模型是 8k 电话音专版，已自动重采样为 8kHz 仍中断，"
                            "多为网络/服务端问题，可改用 16k 模型"
                            " fun-asr-flash-realtime")
                raise RuntimeError("%s（自动重试 1 次仍失败）%s" % (e, hint))
    if segments:
        return {"text": "".join(texts), "segments": segments}
    text = "".join(texts or [])
    if text:
        return text                     # 没拿到时间轴 → 按句兜底
    raise RuntimeError("实时 ASR 未返回任何识别结果")


#: 实时 WebSocket 会话级降级记忆：服务端掐断实时连接一经确认（官方 dashscope
#: SDK 也复现），本进程后续转录直接走文件识别，不再重复浪费重试时间。
_ASR_WS_DEGRADED = False


def _asr_fallback_chat_audio(asr_obj, reason=""):
    """实时 ASR 不可用 → 同端点换 qwen3-asr-flash 文件识别（chat_audio）。

    实测（2026-09-17）：maas 专属实例与公共百炼的 qwen3-asr-flash 文件识别
    均可用；⚠️ 专属实例的 asr 任务不支持 audio+text 混合输入——带 text
    提示词会 HTTP 400（"does not support this input"），必须裸音频。
    """
    if reason:
        _vc_log("实时 ASR 不可用（%s）→ 自动降级 qwen3-asr-flash 文件识别"
                % str(reason)[:80])
    asr_obj.model = "qwen3-asr-flash"
    asr_obj.prompt = ""
    return _asr_chat_audio_submit(asr_obj)


def vc_asr_protocol_patch():
    """ASR 服务模式全协议适配（幂等运行期补丁，引擎 WhisperAPI 不改本体）。

    在引擎 WhisperAPI._submit 前加协议分发：
      · openai     → 原实现（multipart /audio/transcriptions，verbose_json）；
      · azure      → deployments 端点 + api-key 头；
      · chat_audio → chat/completions + input_audio（百炼 Qwen-ASR、小米 MiMo）；
      · deepgram   → /v1/listen，Token 头 + 原始音频（原生词级时间轴）；
      · elevenlabs → /v1/speech-to-text，xi-api-key（原生词级时间轴）；
      · gemini     → generateContent + inline_data（纯文本，按句兜底）；
      · volcengine → 豆包录音识别极速版（一次请求返回，本地文件直传）；
      · assemblyai → /v2/upload + /v2/transcript + 轮询（词级时间轴）。
    各协议响应统一经 _asr_normalize_resp 归一：原生时间轴原样保留，
    纯文本响应（Azure json / Qwen-Audio / Gemini 等）按句切分 + 时长占比
    生成近似时间轴。缓存键追加协议名，防止换协议后吃到旧结果。
    ⚠️ 实时（WebSocket 流式）模型由 asr_model_guard 提前拦下并给出改法。
    """
    try:
        from videocaptioner.core.asr.whisper_api import WhisperAPI
    except Exception as e:  # noqa: BLE001
        _vc_log(f"ASR 协议补丁导入失败：{e}")
        return False
    if getattr(WhisperAPI, "_vt_proto_patched", False):
        return True
    orig_submit = WhisperAPI._submit
    orig_key = WhisperAPI._get_key

    def _submit(self):
        global _ASR_WS_DEGRADED
        # 说话人分离开关：进 _submit 就取一次挂到实例上，分块重试 / 实时降级
        # 都沿用同一个值，避免同一段音频前后半截口径不一致。
        if getattr(self, "diarize", None) is None:
            self.diarize = asr_diarize_of()
        # 语音分离（separation）：同口径取一次挂到实例上。当前是**接口占位**
        # ——真正接入声源分离模型时，这里改成"先分离出单人轨、再逐轨提交
        # 识别"，音乐 reaction 的"剔除歌声"也在这一层按轨道标签筛掉。
        if getattr(self, "separate", None) is None:
            self.separate = asr_separate_of()
            if self.separate:
                try:
                    _src = getattr(self, "audio_input", "")
                    _asr_separate_audio(_src if isinstance(_src, str) else "", self)
                except Exception as e:  # noqa: BLE001
                    _vc_log("语音分离接口调用失败：%s" % (e,))
        proto = asr_protocol_of()
        # 协议纠偏统一收在 asr_protocol_fix（v1.14.2 起，v1.15.3 补反向守卫）：
        # ① 显式/旧配置判成 openai，但端点与模型特征指向别族时按推断改走——
        #    百炼 maas + 实时模型拿 OpenAI SDK 打必被服务端断连；qwen-audio/
        #    paraformer 族在 maas 上根本没有 /audio/transcriptions；
        # ② 协议选了「百炼实时」但模型不是实时模型时改走文件识别——否则服务端
        #    只回 `InvalidParameter url error, please check url!`，既看不懂、
        #    重试和降级也都救不回来（task-failed 属确定性错误）。
        proto, _fix_note = asr_protocol_fix(proto, getattr(self, "base_url", ""),
                                            getattr(self, "model", ""))
        if _fix_note:
            _vc_log("ASR " + _fix_note)
        # v1.15.5：实时对话/翻译模型（livetranslate 族）任何协议都转写不了，
        # 无条件拦——否则 WS 被拒后降级文件上传只拿到空体 400/500，无从下手。
        guard = asr_model_hard_guard(getattr(self, "model", ""))
        if proto != "dashscope_realtime":
            # 实时模型只有走实时协议才有救：其它协议下提前拦，别等服务端 404。
            # 走实时协议时**不能**拦（那正是让实时模型出字幕的路）。
            if not guard:
                guard = asr_base_guard(getattr(self, "base_url", ""))
            if not guard:
                guard = asr_model_guard(getattr(self, "model", ""))
            # 非 openai 协议不走引擎原实现，它那段"简体中文提示词预设"要自己补
            if (getattr(self, "language", "") == "zh"
                    and not getattr(self, "prompt", "")):
                self.prompt = "你好，我们需要使用简体中文，以下是普通话的句子"
        if guard:
            raise RuntimeError(guard)
        if proto == "dashscope_realtime" and not _ASR_WS_DEGRADED:
            try:
                resp = _asr_dashscope_realtime_submit(self)
            except RuntimeError as e:
                # 实时 WebSocket 被服务端中途掐断（握手/task-started 正常、音频
                # 发送中或完成后无 Close 码断连；官方 dashscope SDK 同样无法
                # 使用——2026-09-17 实测，与客户端实现/网络路径无关）。
                _e = str(e)
                if "连接" not in _e and "超时" not in _e:
                    raise              # task-failed 等确定性错误，降级无意义
                _ASR_WS_DEGRADED = True
                resp = _asr_fallback_chat_audio(self, _e)
        elif proto == "dashscope_realtime":
            # 本进程已确认实时通道被服务端掐断 → 直接走文件识别，不再试 WS
            resp = _asr_fallback_chat_audio(self)
        elif proto == "azure":
            resp = _asr_azure_submit(self)
        elif proto in ("chat_audio", "dashscope"):
            try:
                resp = _asr_chat_audio_submit(self)
            except RuntimeError as e:
                # v1.15.6：百炼原生专用模型（Qwen-Audio-3.0-ASR-Flash /
                # Fun-ASR-Flash）被兼容模式打回空体 400/500 —— 同一模型、同一
                # 音频换原生端点即通，这里兜一次（每个任务只兜一次）。
                if not _asr_empty_body_err(e):
                    raise
                resp = _asr_retry_native(self, e)
        elif proto == "dashscope_native":
            resp = _asr_dashscope_native_submit(self)
        elif proto == "dashscope_filetrans":
            resp = _asr_dashscope_filetrans_submit(self)
        elif proto == "deepgram":
            resp = _asr_deepgram_submit(self)
        elif proto == "elevenlabs":
            resp = _asr_elevenlabs_submit(self)
        elif proto == "gemini":
            resp = _asr_gemini_submit(self)
        elif proto == "volcengine":
            resp = _asr_volcengine_submit(self)
        elif proto == "assemblyai":
            resp = _asr_assemblyai_submit(self)
        else:
            # openai 协议走引擎原实现（OpenAI SDK）。SDK 会在 base_url 后面再
            # 拼一次 /audio/transcriptions，所以先把"完整端点"的尾巴削掉并
            # 重建 client —— 内存里改 base_url 不会影响已经建好的 client。
            clean = asr_strip_endpoint_tail(self.base_url, "/audio/transcriptions",
                                            "/audio/translations")
            if clean and clean != self.base_url:
                self.base_url = clean
                _vc_log(f"ASR 地址含完整端点，已规范化为 {clean}")
                try:
                    from openai import OpenAI
                    self.client = OpenAI(base_url=clean, api_key=self.api_key)
                except Exception as e:  # noqa: BLE001
                    _vc_log(f"规范化后重建 ASR 客户端失败：{e}")
            resp = orig_submit(self)
        return _asr_normalize_resp(resp, self)

    def _get_key(self):
        try:
            return f"{orig_key(self)}-{asr_protocol_of()}"
        except Exception:  # noqa: BLE001
            return orig_key(self)

    WhisperAPI._submit = _submit
    WhisperAPI._get_key = _get_key
    WhisperAPI._vt_proto_patched = True
    _vc_log("ASR 协议补丁已挂：openai/azure/chat_audio/deepgram/elevenlabs/"
            "gemini/volcengine/assemblyai（纯文本响应按句兜底；实时模型提前拦截）")
    try:
        vc_asr_chunk_patch()
    except Exception as e:  # noqa: BLE001
        _vc_log(f"分块补丁挂载失败：{e}")
    return True


#: chat_audio 族（百炼 compatible-mode）单请求音频时长上限约 3 分钟，
#: 引擎默认按 600s 切块必超 → 该协议下把块长压到 170s（留转发/编码余量）。
ASR_CHAT_AUDIO_CHUNK_MS = 170_000

#: 百炼原生端点（multimodal-generation）单请求音频上限约 5 分钟 → 压到 280s。
ASR_NATIVE_CHUNK_MS = 280_000


def vc_asr_chunk_patch():
    """chat_audio 协议下把引擎的 ASR 音频分块长度压到 3 分钟内（幂等补丁）。

    引擎的 ChunkedASR 默认 chunk_length_ms=600s，对 OpenAI/Deepgram 这类
    长音频服务没问题；但百炼 compatible-mode 多模态单次请求上限约 3 分钟，
    600s 的块必被服务端拒（The audio is too long）。这里包住
    transcribe._create_whisper_api_asr：构造完成后按当前协议把块长改到 170s，
    让「切块→逐块提交」在提交前就合规，而不是等 400 再对半救火。
    """
    try:
        import importlib as _il
        # ⚠️ asr 包属性 transcribe 是**函数**（遮蔽同名子模块），普通
        # import ... as _tr 拿到的是函数；必须 importlib 按模块名取真模块。
        _tr = _il.import_module("videocaptioner.core.asr.transcribe")
    except Exception as e:  # noqa: BLE001
        _vc_log(f"分块补丁导入 transcribe 失败：{e}")
        return False
    if getattr(_tr, "_vt_chunk_patched", False):
        return True
    orig = getattr(_tr, "_create_whisper_api_asr", None)
    if orig is None:
        return False

    def _create(*a, **k):
        inst = orig(*a, **k)
        try:
            _p = asr_protocol_of()
            if _p in ("chat_audio", "dashscope"):
                inst.chunk_length_ms = ASR_CHAT_AUDIO_CHUNK_MS
            elif _p == "dashscope_native":
                # 原生端点官方上限约 5 分钟（Qwen-Audio-3.0-ASR-Flash），
                # 压到 280s 留转码/转发余量。
                inst.chunk_length_ms = ASR_NATIVE_CHUNK_MS
        except Exception as e:  # noqa: BLE001
            _vc_log(f"分块长度调整失败：{e}")
        return inst

    _tr._create_whisper_api_asr = _create
    _tr._vt_chunk_patched = True
    _vc_log("ASR 分块补丁已挂：chat_audio 协议块长压到 170s（默认 600s 超上限）")
    return True


def asr_non_zh_en_ratio(text):
    """文本中「非中/英」字符占比（0~1）；无有效字符返回 0。

    判据：跳过空白与标点符号；ASCII（字母数字）与**汉字**算"中/英"，其余
    书写系统（假名/谚文/西里尔/泰文…）算"非中英"。日文句子里的汉字计入中英，
    假名为主时占比仍过半 → 用于「默认接口语言提示」判断片源是不是中文/英文，
    非中英占比高时不再注入简体中文提示词。
    """
    import unicodedata
    total = other = 0
    for ch in str(text or ""):
        if ch.isspace():
            continue
        if unicodedata.category(ch)[0] in ("P", "S"):
            continue
        o = ord(ch)
        total += 1
        if o < 128:
            continue                                  # ASCII 字母数字
        if (0x4E00 <= o <= 0x9FFF or 0x3400 <= o <= 0x4DBF
                or 0xF900 <= o <= 0xFAFF
                or 0x3007 == o or 0x00AA == o or 0x00BA == o):
            continue                                  # 汉字（日文汉字同源）
        other += 1
    return (other / total) if total else 0.0


#: 引擎翻译服务枚举值（videocaptioner.core.entities.TranslatorServiceEnum）。
#: v1.12.0 起字幕翻译板块仅支持机翻（微软 / 谷歌 / DeepLx），LLM 翻译入口
#: 已全部移除；TS_LLM 仅用于把历史配置迁回机翻。
TS_LLM = "LLM 大模型翻译"
TS_BING = "微软翻译"

#: 免费翻译端点预检结果缓存（进程内，避免每条字幕重复探测）
_TS_PROBE_CACHE = {}


def _ts_probe_ok(kind):
    """免费翻译端点连通性探测（3 秒超时，结果进程内缓存）——诊断/备用。

    v1.12.0 实测：微软 ``edge.microsoft.com/translate/translatetext``（免认证）
    直连 200；谷歌 ``translate.googleapis.com/translate_a/single?client=gtx``
    需走系统代理（requests 默认信任），代理未开则超时。本函数**不用于短路**，
    只保留给诊断与后续"可用性提示"复用。
    """
    if kind in _TS_PROBE_CACHE:
        return _TS_PROBE_CACHE[kind]
    ok = True
    if kind == "google":
        try:
            import requests
            r = requests.get(
                "https://translate.googleapis.com/translate_a/single",
                params={"client": "gtx", "sl": "auto", "tl": "zh-CN",
                        "dt": "t", "q": "ok"},
                headers={"User-Agent": "Mozilla/5.0"}, timeout=3)
            ok = r.status_code == 200
        except Exception:  # noqa: BLE001
            ok = False
    _TS_PROBE_CACHE[kind] = ok
    return ok


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
