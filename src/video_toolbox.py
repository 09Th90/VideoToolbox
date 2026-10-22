#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# @version 2.5.2
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
    proxy_lock_status, proxy_ctl_base, proxy_egress_ip, proxy_note_eof,
    # 注：data_root_info/set_data_root/prepare_runtime_env/sync_env_into/
    # engine_ui_brand_patch 五个 DOMAIN_MAP-shared 符号的函数体仍在本文件
    # 下方（依赖 asr/calibrate 未拆域），随 A2/A3 再搬；届时从这里补名，
    # _selftest_core_api 的 DOMAIN_MAP 覆盖校验会盯着。
)
from core.download import (  # download 域公开函数（DOMAIN_MAP「download」全集）
    ensure_ytdlp, ensure_ffmpeg, ensure_mpv_dll,
    extract_url, extract_web_url, ytdlp_sub_langs,
    ytdlp_prefer_hls, ytdlp_part_leftovers, ytdlp_error_retryable,
    ytdlp_err_brief, ytdlp_error_needs_reextract, ytdlp_dl_args,
    ytdlp_concurrent_fragments, ytdlp_cookie_args,
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
from core.asr import (  # asr 域公开函数（DOMAIN_MAP「asr」A2b 部分）
    asr_local_override, apply_asr_to_engine, vc_asr_patch_apply,
    vc_pydub_nowindow_patch, voiceprint_enabled_names,
    voiceprint_filter_subtitle, vc_transcribe_ui_patch, vc_lazy_cache_patch,
    vc_prepare_settings_file, vc_enforce_runtime_cfg, vc_migrate_legacy_data,
    vc_legacy_leftovers,
)
from core.shared import (  # shared 收口四符号（DOMAIN_MAP「shared」A2b 部分）
    prepare_runtime_env, data_root_info, set_data_root, engine_ui_brand_patch,
)
from core.translate import (  # translate 域公开函数（DOMAIN_MAP「translate」全集）
    vc_translate_route_patch, vc_translate_no_llm_patch, ensure_translate_patches,
)
from core.translate import *  # noqa: F401,F403 —— translate 域私有与常量
from core.calibrate import (  # calibrate 域公开函数（DOMAIN_MAP「calibrate」全集）
    calib_ai_chat, calib_web_proxy, calib_ai_run,
    calib_sync_enabled, set_calib_sync_enabled,
    sync_calib_to_github, sync_calib_push_local,
    sync_calib_on_startup, sync_calib_on_exit,
    sync_voiceprint_on_startup, sync_voiceprint_on_exit, sync_env_into,
)
from core.calibrate import *  # noqa: F401,F403 —— calibrate 域私有与常量
from core.pipeline import (  # pipeline 域公开函数（DOMAIN_MAP「pipeline」全集）
    srt_time_to_ms, ms_to_srt_time, normalize_rolling_srt, main,
)
from core.pipeline import *  # noqa: F401,F403 —— pipeline 域私有与常量
from core.shared import (  # 私有名（* 不导出下划线开头，必须显式列）
    _AI_LAST_AUTO_NOTES, _LOG_ERR_WORDS, _LOG_WARN_WORDS, _append_log,
    _vc_log, _mihomo_log, _is_self_exe, _VC_LEGACY_DIRS,
    _BOOTSTRAP_LOCK, _hide_console_kwargs,
    _vc_read_settings, _vc_write_settings, _fallback_config_path,
    _path_on_system_drive,
)


# ========== CLI 入口（v2.3.1：main 搬入 core.pipeline，此处只留守门） ==========
if __name__ == "__main__":
    from core.pipeline import main
    main()
