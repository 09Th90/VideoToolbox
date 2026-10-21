# @version 2.5.0
"""端到端编排（自研，替代引擎 TranscriptThread / SubtitleThread 的执行体）。

无 Qt 依赖：全部能力以普通函数 + ``callback(progress, message)`` 暴露，
Qt 线程层（``vt_engine.threads``）只是这层薄封装。两条链路：

* :func:`transcribe_media` —— 视频/音频 → 音频提取 → ASR → 多格式落盘；
* :func:`process_subtitle` —— 读字幕 →（词级化→断句→优化→翻译）→ 保存
  单语/双语/ASS（必要时同步一份 srt/ass 到视频目录，供后续合成）。

可观察行为对齐引擎线程：已下载字幕跳过转录、``All`` 格式展开、
need_next_task 时补一份 srt、翻译前机翻回落、保存前默认
``ONLY_TRANSLATE`` 兜底排布、任务上下文（日志关联）随链路切换。
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Callable, List, Optional

from vt_engine import entities as ent
from vt_engine.asr_core import transcribe as _asr_transcribe
from vt_engine.asr_data import ASRData
from vt_engine.llm_context import (
    clear_task_context,
    set_task_context,
    update_stage,
)
from vt_engine.log import setup_logger
from vt_engine.media import video2audio
from vt_engine.subtitle_llm import optimize_subtitle, split_subtitle
from vt_engine.tasks import TaskFactory
from vt_engine.translate_factory import translate_with_machine_fallback

logger = setup_logger("vt_engine.pipeline")

__all__ = [
    "PipelineError",
    "transcribe_media",
    "process_subtitle",
    "run_full_process",
]

#: 说话人标记（ASR 分离开启时行首出现）——提示词锚定用。
_SPEAKER_RE = None


class PipelineError(RuntimeError):
    """链路执行失败（携带用户可读信息）。"""


def _cb(callback):
    return callback if callback else (lambda p, m: None)


def _formats_to_export(config) -> List[str]:
    """输出格式列表（``All`` 展开为全部单格式；need_next_task 必含 srt）。"""
    fmt = config.output_format
    if fmt == ent.TranscribeOutputFormatEnum.ALL:
        fmts = [f.value.lower() for f in ent.TranscribeOutputFormatEnum
                if f != ent.TranscribeOutputFormatEnum.ALL]
    else:
        fmts = [fmt.value.lower()]
    return list(dict.fromkeys(fmts))


def _find_downloaded_subtitle(file_path: str) -> Optional[str]:
    """need_next_task 时优先用已下载字幕（跳过转录）。"""
    subtitle_dir = Path(file_path).parent / "subtitle"
    if not subtitle_dir.is_dir():
        return None
    found = sorted(subtitle_dir.glob("【下载字幕】*"))
    return str(found[0]) if found else None


def _validate_transcribe_task(task) -> None:
    if not task or not getattr(task, "file_path", None):
        raise PipelineError("文件路径为空")
    if not Path(task.file_path).exists():
        raise PipelineError("视频文件不存在: %s" % task.file_path)
    if not task.transcribe_config:
        raise PipelineError("转录配置为空")
    if not task.output_path:
        raise PipelineError("输出路径为空")


def transcribe_media(task, callback: Optional[Callable] = None) -> str:
    """执行转录任务（视频/音频 → 字幕文件）。返回输出路径。"""
    progress = _cb(callback)
    _validate_transcribe_task(task)
    set_task_context(task_id=task.task_id,
                     file_name=Path(task.file_path).name,
                     stage="transcribe")
    try:
        if task.need_next_task:
            downloaded = _find_downloaded_subtitle(task.file_path)
            if downloaded:
                task.output_path = downloaded
                logger.info("字幕文件已下载，跳过转录: %s", downloaded)
                progress(100, "字幕已下载")
                return downloaded

        config = task.transcribe_config
        audio_index = getattr(task, "selected_audio_track_index", 0) or 0
        tmp_dir = None
        try:
            tmp_dir = tempfile.mkdtemp(prefix="vt_audio_")
            audio_path = os.path.join(tmp_dir, "audio.wav")
            progress(5, "转换音频中")
            logger.info("开始转换音频: %s", task.file_path)
            if not video2audio(task.file_path, audio_path,
                               audio_track_index=audio_index):
                raise PipelineError("音频转换失败")

            progress(20, "语音转录中")
            logger.info("开始语音转录")
            asr_data = _asr_transcribe(audio_path, config,
                                       callback=lambda p, m: progress(
                                           min(20 + int(p * 0.8), 100), m))
        finally:
            if tmp_dir:
                import shutil
                shutil.rmtree(tmp_dir, ignore_errors=True)

        base_path = Path(task.output_path).with_suffix("")
        fmts = _formats_to_export(config)
        if task.need_next_task and "srt" not in fmts:
            fmts.append("srt")
        for fmt in fmts:
            save_path = f"{base_path}.{fmt}"
            if fmt == "vtt":
                # ASRData.save 只认 srt/txt/json/ass，且引擎的 to_vtt 是
                # 未实现桩（NotImplementedError）——ALL 展开含 vtt 走引擎
                # 必然崩；这里走 vt_engine 自研的 WebVTT 导出。
                from vt_engine.asr_data import save_vtt
                save_vtt(asr_data, save_path)
            else:
                asr_data.save(save_path)
            logger.info("%s 字幕文件已保存到: %s", fmt.upper(), save_path)

        progress(100, "转录完成")
        return task.output_path
    finally:
        clear_task_context()


def _speaker_rule_prompt(asr_data: ASRData) -> str:
    """检测到 `[说话人N]` 标记时生成一致性锚定提示（引擎同款规则）。"""
    global _SPEAKER_RE
    if _SPEAKER_RE is None:
        import re
        _SPEAKER_RE = re.compile(r"^\s*[\[［]\s*说话人\s*\d+\s*[\]］]")
    if not any(_SPEAKER_RE.match(str(getattr(s, "text", "") or ""))
               for s in asr_data.segments):
        return ""
    return (
        "IMPORTANT - Speaker diarization: some subtitle lines begin with a "
        "[说话人N] (Speaker N) marker. Rules:\n"
        "1) Keep that marker EXACTLY as-is at the beginning of the "
        "translated line - do NOT translate, remove, reorder or renumber "
        "it.\n"
        "2) The same speaker ID always refers to the same person. Keep the "
        "address terms, tone and gendered pronouns (he/she, 他/她) "
        "consistent across every line of that speaker.\n"
    )


def process_subtitle(task, callback: Optional[Callable] = None,
                     on_data: Optional[Callable] = None) -> str:
    """执行字幕任务（断句/优化/翻译/保存）。返回输出路径。

    ``on_data(asr_data)``：断句/优化/翻译各阶段完成后的数据快照钩子
    （UI 的 ``update_all`` 信号接这里；无 Qt 环境不传即可）。
    """
    progress = _cb(callback)

    def _snap():
        if on_data:
            try:
                on_data(asr_data)
            except Exception:  # noqa: BLE001
                pass
    if not task or not getattr(task, "subtitle_path", None):
        raise PipelineError("字幕文件路径为空")
    if not task.subtitle_config:
        raise PipelineError("字幕配置为空")

    task_file = Path(task.video_path) if task.video_path \
        else Path(task.subtitle_path)
    set_task_context(task_id=task.task_id, file_name=task_file.name,
                     stage="subtitle")
    try:
        config = task.subtitle_config
        logger.info("\n%s", config.print_config())
        asr_data = ASRData.from_subtitle_file(task.subtitle_path)

        # 1. 词级化（非词级且开启断句时）
        if config.need_split and not asr_data.is_word_timestamp():
            asr_data.split_to_word_segments()

        # 2. LLM 重新断句（词级字幕）
        if asr_data.is_word_timestamp():
            update_stage("split")
            progress(5, "字幕断句...")
            asr_data = split_subtitle(
                asr_data,
                max_word_count_cjk=config.max_word_count_cjk,
                max_word_count_english=config.max_word_count_english,
                model=config.llm_model or "",
                thread_num=config.thread_num)
            _snap()

        # 3. 优化（LLM）
        context_info = (
            'The subtitles below are from a file named "%s". Use this '
            'context to improve accuracy if needed.\n' % task_file.name)
        custom_prompt = (context_info + _speaker_rule_prompt(asr_data)
                         + (config.custom_prompt_text or "") + "\n")
        if config.need_optimize:
            update_stage("optimize")
            progress(0, "优化字幕...")
            if not config.llm_model:
                raise PipelineError("LLM 模型未配置")
            asr_data = optimize_subtitle(
                asr_data, model=config.llm_model or "",
                thread_num=config.thread_num, batch_num=config.batch_size,
                custom_prompt=custom_prompt)
            asr_data.remove_punctuation()
            _snap()

        # 4. 翻译
        if config.need_translate:
            update_stage("translate")
            progress(0, "翻译字幕...")
            if not config.target_language:
                raise PipelineError("目标语言未配置")
            user_prompt = (config.custom_prompt_text or "").strip()
            if user_prompt and config.translator_service in (
                    ent.TranslatorServiceEnum.GOOGLE,
                    ent.TranslatorServiceEnum.BING,
                    ent.TranslatorServiceEnum.DEEPLX):
                logger.warning(
                    "翻译服务「%s」是机器翻译，不支持自定义提示词/术语表，"
                    "已填写的内容（%d 字）不会生效",
                    config.translator_service.value, len(user_prompt))
                progress(0, "提示：机器翻译不支持自定义提示词，已填写内容未生效")
            asr_data = translate_with_machine_fallback(
                config, custom_prompt, None, asr_data,
                progress=lambda msg: progress(0, msg))
            asr_data.remove_punctuation()
            _snap()

            # 翻译结果各排布备份（need_next_task 时供后续任务选排布）
            if task.need_next_task and task.video_path:
                for layout in ent.SubtitleLayoutEnum:
                    save_path = str(
                        Path(task.subtitle_path).parent /
                        f"{Path(task.video_path).stem}-{layout.value}.srt")
                    asr_data.save(save_path=save_path,
                                  ass_style=config.subtitle_style or "",
                                  layout=layout)

        # 5. 保存主输出
        asr_data.save(
            save_path=task.output_path or "",
            ass_style=config.subtitle_style or "",
            layout=config.subtitle_layout or ent.SubtitleLayoutEnum.ONLY_TRANSLATE)
        logger.info("字幕保存到 %s", task.output_path)

        # 6. 同步到视频目录（srt + ass）
        if task.need_next_task and task.video_path:
            save_srt = (Path(task.video_path).parent /
                        f"{Path(task.video_path).stem}.srt")
            asr_data.to_srt(save_path=str(save_srt),
                            layout=config.subtitle_layout)
            save_ass = (Path(task.video_path).parent /
                        f"{Path(task.video_path).stem}.ass")
            asr_data.to_ass(save_path=str(save_ass),
                            layout=config.subtitle_layout,
                            style_str=config.subtitle_style)

        progress(100, "优化完成")
        return task.output_path
    finally:
        clear_task_context()


def run_full_process(video_path: str, callback: Optional[Callable] = None,
                     need_translate: Optional[bool] = None) -> dict:
    """全流程：转录 → 字幕。返回 ``{"transcribe": 任务, "subtitle": 任务,
    "srt": 路径}``。"""
    progress = _cb(callback)
    t_task = TaskFactory.create_transcribe_task(video_path,
                                                need_next_task=True)
    transcribe_media(t_task, callback)
    s_task = TaskFactory.create_subtitle_task(
        t_task.output_path, video_path=video_path, need_next_task=True)
    if need_translate is not None and s_task.subtitle_config is not None:
        # 调用方显式指定时覆盖 cfg 默认——参数被接受就必须生效，
        # 否则 need_translate=False 的调用方仍会走翻译链路。
        s_task.subtitle_config.need_translate = bool(need_translate)
    process_subtitle(s_task, callback)
    progress(100, "全流程完成")
    return {"transcribe": t_task, "subtitle": s_task,
            "srt": s_task.output_path}
