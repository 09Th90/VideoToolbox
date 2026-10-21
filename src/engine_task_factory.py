# -*- coding: utf-8 -*-
# @version 2.4.1
"""自研任务工厂（P2 尾部 · 档 B：接管 ``videocaptioner.ui.task_factory``）。

以**自研代码**重建 ``TaskFactory`` 的构造算法（输出路径命名、按 LLM 服务选配置、
转录/字幕/合成任务的字段装配），并把原先运行期打在引擎工厂上的后端补丁
``vc_asr_patch_apply`` **内建为显式逻辑**：

  · 本地独立 ASR：``asr_local_override()`` 命中时覆盖 ``faster_whisper_model`` /
    ``faster_whisper_model_dir``（自定义模型名/目录，枚举外也生效）；
  · 显式识别语言（非「自动检测」）：写进 ``transcribe_config.transcribe_language``
    ——与引擎补丁同款：优先 ``engine_entities.LANGUAGES[label]``，异常才退
    ``ai_mod().asr_language_code(label)``。

**兼容面**：产出的任务对象与引擎（已打补丁的）``TaskFactory`` **逐字段一致**——
由 ``scripts/dev/_selftest_engine_task_factory.py`` 离线逐字段比对引擎产物验证
（构造任务是纯数据操作，无需 QApplication）。任务数据类（``TranscribeTask`` 等）
与配置单例 ``cfg`` 仍取自既有引擎（分属档 A 核心 / 档 B 配置层，各有其接管时间
线）；本模块只接管「工厂构造逻辑」这一档 B 线项。

约束：所有 ``videocaptioner`` / ``video_toolbox`` 导入均**惰性**，import 本模块
不触发引擎导入树。
"""
from __future__ import annotations

import datetime
import importlib
from pathlib import Path
from typing import Optional


def _mod(name: str):
    return importlib.import_module(name)


def _entities():
    return _mod("videocaptioner.core.entities")


def _cfg():
    return _mod("videocaptioner.ui.common.config").cfg


def _model_path():
    return _mod("videocaptioner.config").MODEL_PATH


def _engine_helpers():
    """video_toolbox 里的 ASR 覆盖/配置助手（本项目自研）。"""
    m = _mod("video_toolbox")
    return m


class TaskFactory:
    """任务工厂（自研，API 与引擎 ``TaskFactory`` 同名同义）。"""

    # ---------------- 样式 ----------------
    @staticmethod
    def get_ass_style(style_name: str) -> str:
        load_style = _mod("videocaptioner.core.subtitle.style_manager").load_style
        style = load_style(style_name)
        if style is not None:
            return style.to_ass_string()
        return ""

    @staticmethod
    def get_rounded_style() -> dict:
        cfg = _cfg()
        return {
            "font_name": cfg.rounded_bg_font_name.value,
            "font_size": cfg.rounded_bg_font_size.value,
            "bg_color": cfg.rounded_bg_color.value,
            "text_color": cfg.rounded_bg_text_color.value,
            "corner_radius": cfg.rounded_bg_corner_radius.value,
            "padding_h": cfg.rounded_bg_padding_h.value,
            "padding_v": cfg.rounded_bg_padding_v.value,
            "margin_bottom": cfg.rounded_bg_margin_bottom.value,
            "line_spacing": cfg.rounded_bg_line_spacing.value,
            "letter_spacing": cfg.rounded_bg_letter_spacing.value,
        }

    # ---------------- 转录任务 ----------------
    @staticmethod
    def create_transcribe_task(
        file_path: str,
        need_next_task: bool = False,
        task_id: Optional[str] = None,
    ):
        cfg = _cfg()
        ent = _entities()
        file_name = Path(file_path).stem

        if need_next_task:
            need_word_time_stamp = cfg.need_split.value
            output_path = str(
                Path(cfg.work_dir.value)
                / file_name
                / "subtitle"
                / f"【原始字幕】{file_name}-{cfg.transcribe_model.value.value}-{cfg.transcribe_language.value.value}.srt"
            )
        else:
            need_word_time_stamp = False
            output_path = str(Path(file_path).parent / f"{file_name}.srt")

        config = ent.TranscribeConfig(
            transcribe_model=cfg.transcribe_model.value,
            transcribe_language=ent.LANGUAGES[cfg.transcribe_language.value.value],
            need_word_time_stamp=need_word_time_stamp,
            output_format=cfg.transcribe_output_format.value,
            whisper_model=cfg.whisper_model.value,
            whisper_api_key=cfg.whisper_api_key.value,
            whisper_api_base=cfg.whisper_api_base.value,
            whisper_api_model=cfg.whisper_api_model.value,
            whisper_api_prompt=cfg.whisper_api_prompt.value,
            faster_whisper_program=cfg.faster_whisper_program.value,
            faster_whisper_model=cfg.faster_whisper_model.value,
            faster_whisper_model_dir=str(_model_path()),
            faster_whisper_device=cfg.faster_whisper_device.value,
            faster_whisper_vad_filter=cfg.faster_whisper_vad_filter.value,
            faster_whisper_vad_threshold=cfg.faster_whisper_vad_threshold.value,
            faster_whisper_vad_method=cfg.faster_whisper_vad_method.value,
            faster_whisper_ff_mdx_kim2=cfg.faster_whisper_ff_mdx_kim2.value,
            faster_whisper_one_word=cfg.faster_whisper_one_word.value,
            faster_whisper_prompt=cfg.faster_whisper_prompt.value,
        )

        task = ent.TranscribeTask(
            queued_at=datetime.datetime.now(),
            file_path=file_path,
            output_path=output_path,
            transcribe_config=config,
            need_next_task=need_next_task,
        )
        if task_id:
            task.task_id = task_id

        # —— 内建 vc_asr_patch_apply 的覆盖逻辑（best-effort，任何异常都不破坏任务）——
        TaskFactory._apply_asr_override(task)
        return task

    @staticmethod
    def _apply_asr_override(task) -> None:
        try:
            h = _engine_helpers()
            ov = h.asr_local_override()
            if ov:
                model, model_dir = ov
                tcfg = getattr(task, "transcribe_config", None)
                if tcfg is not None:
                    if model:
                        tcfg.faster_whisper_model = model
                    if model_dir:
                        tcfg.faster_whisper_model_dir = model_dir
            try:
                ac = h.ai_mod().asr_config(h.ai_load_config())
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
                        tcfg.transcribe_language = h.ai_mod().asr_language_code(_label)
        except Exception:  # noqa: BLE001
            pass

    # ---------------- 字幕任务 ----------------
    @staticmethod
    def create_subtitle_task(
        file_path: str,
        video_path: Optional[str] = None,
        need_next_task: bool = False,
        task_id: Optional[str] = None,
    ):
        cfg = _cfg()
        ent = _entities()
        output_name = (
            Path(file_path).stem.replace("【原始字幕】", "").replace("【下载字幕】", "")
        )
        suffix = f"-{cfg.translator_service.value.value}" if cfg.need_translate.value else ""
        if need_next_task:
            output_path = str(Path(file_path).parent / f"【样式字幕】{output_name}{suffix}.ass")
        else:
            output_path = str(Path(file_path).parent / f"【字幕】{output_name}{suffix}.srt")

        current_service = cfg.llm_service.value
        LLM = ent.LLMServiceEnum
        if current_service == LLM.OPENAI:
            base_url, api_key, llm_model = cfg.openai_api_base.value, cfg.openai_api_key.value, cfg.openai_model.value
        elif current_service == LLM.SILICON_CLOUD:
            base_url, api_key, llm_model = cfg.silicon_cloud_api_base.value, cfg.silicon_cloud_api_key.value, cfg.silicon_cloud_model.value
        elif current_service == LLM.DEEPSEEK:
            base_url, api_key, llm_model = cfg.deepseek_api_base.value, cfg.deepseek_api_key.value, cfg.deepseek_model.value
        elif current_service == LLM.OLLAMA:
            base_url, api_key, llm_model = cfg.ollama_api_base.value, cfg.ollama_api_key.value, cfg.ollama_model.value
        elif current_service == LLM.LM_STUDIO:
            base_url, api_key, llm_model = cfg.lm_studio_api_base.value, cfg.lm_studio_api_key.value, cfg.lm_studio_model.value
        elif current_service == LLM.GEMINI:
            base_url, api_key, llm_model = cfg.gemini_api_base.value, cfg.gemini_api_key.value, cfg.gemini_model.value
        elif current_service == LLM.CHATGLM:
            base_url, api_key, llm_model = cfg.chatglm_api_base.value, cfg.chatglm_api_key.value, cfg.chatglm_model.value
        else:
            base_url = api_key = llm_model = ""

        config = ent.SubtitleConfig(
            base_url=base_url,
            api_key=api_key,
            llm_model=llm_model,
            deeplx_endpoint=cfg.deeplx_endpoint.value,
            translator_service=cfg.translator_service.value,
            need_reflect=cfg.need_reflect_translate.value,
            need_translate=cfg.need_translate.value,
            need_optimize=cfg.need_optimize.value,
            thread_num=cfg.thread_num.value,
            batch_size=cfg.batch_size.value,
            subtitle_layout=cfg.subtitle_layout.value,
            subtitle_style=TaskFactory.get_ass_style(cfg.subtitle_style_name.value),
            max_word_count_cjk=cfg.max_word_count_cjk.value,
            max_word_count_english=cfg.max_word_count_english.value,
            need_split=cfg.need_split.value,
            target_language=cfg.target_language.value,
            custom_prompt_text=cfg.custom_prompt_text.value,
        )

        task = ent.SubtitleTask(
            queued_at=datetime.datetime.now(),
            subtitle_path=file_path,
            video_path=video_path,
            output_path=output_path,
            subtitle_config=config,
            need_next_task=need_next_task,
        )
        if task_id:
            task.task_id = task_id
        return task

    # ---------------- 合成任务 ----------------
    @staticmethod
    def create_synthesis_task(
        video_path: str,
        subtitle_path: str,
        need_next_task: bool = False,
        task_id: Optional[str] = None,
    ):
        cfg = _cfg()
        ent = _entities()
        output_path = str(Path(video_path).parent / f"【卡卡】{Path(video_path).stem}.mp4")
        use_style = cfg.use_subtitle_style.value
        config = ent.SynthesisConfig(
            need_video=cfg.need_video.value,
            soft_subtitle=cfg.soft_subtitle.value,
            render_mode=cfg.subtitle_render_mode.value,
            video_quality=cfg.video_quality.value,
            subtitle_layout=cfg.subtitle_layout.value,
            ass_style=TaskFactory.get_ass_style(cfg.subtitle_style_name.value) if use_style else "",
            rounded_style=TaskFactory.get_rounded_style() if use_style else None,
        )
        task = ent.SynthesisTask(
            queued_at=datetime.datetime.now(),
            video_path=video_path,
            subtitle_path=subtitle_path,
            output_path=output_path,
            synthesis_config=config,
            need_next_task=need_next_task,
        )
        if task_id:
            task.task_id = task_id
        return task

    # ---------------- 组合任务（与引擎同签名，保持兼容面） ----------------
    @staticmethod
    def create_transcript_and_subtitle_task(
        file_path: str,
        output_path: Optional[str] = None,
        transcribe_config=None,
        subtitle_config=None,
    ):
        ent = _entities()
        if output_path is None:
            output_path = str(Path(file_path).parent / f"{Path(file_path).stem}_processed.srt")
        return ent.TranscriptAndSubtitleTask(
            queued_at=datetime.datetime.now(),
            file_path=file_path,
            output_path=output_path,
        )

    @staticmethod
    def create_full_process_task(
        file_path: str,
        output_path: Optional[str] = None,
        transcribe_config=None,
        subtitle_config=None,
        synthesis_config=None,
    ):
        ent = _entities()
        if output_path is None:
            output_path = str(
                Path(file_path).parent / f"{Path(file_path).stem}_final{Path(file_path).suffix}"
            )
        return ent.FullProcessTask(
            queued_at=datetime.datetime.now(),
            file_path=file_path,
            output_path=output_path,
        )
