# @version 2.5.2
"""任务工厂（自研，替代 videocaptioner.ui.task_factory.TaskFactory）。

以自研设置层（``vt_engine.config.cfg``）+ 自研数据类
（``vt_engine.entities``）重建任务构造：输出路径命名、按 LLM 服务选
配置、转录/字幕/合成任务字段装配，并把原先运行期补丁
``vc_asr_patch_apply`` 的能力**内建为显式逻辑**：

* 本地独立 ASR：``asr_local_override()`` 命中时覆盖
  ``faster_whisper_model`` / ``faster_whisper_model_dir``（自定义模型名/
  目录，枚举外也生效）；
* 显式识别语言（非「自动检测」）：写进
  ``transcribe_config.transcribe_language``——优先 ``LANGUAGES`` 映射，
  异常才退 ISO 码（与引擎补丁同款）。

与自研 ``engine_task_factory``（已接线版）的差别只在于后端来源：
那边任务数据类仍取自引擎 entities、设置走引擎 cfg；本模块全部取自研
模块——**不 import 任何 videocaptioner 符号**（自检红线）。
"""

from __future__ import annotations

import datetime
import importlib
from pathlib import Path
from typing import Optional

from vt_engine import entities as ent
from vt_engine.config import cfg as _cfg
from vt_engine.log import setup_logger
from vt_engine.paths import default_engine_paths

logger = setup_logger("vt_engine.tasks")

__all__ = ["TaskFactory"]


def _mod(name: str):
    return importlib.import_module(name)


def _model_path():
    return default_engine_paths().model_path


def _ai_mod():
    """项目自有 AI 客户端模块（tools/ai_client.py）。"""
    try:
        return importlib.import_module("ai_client")
    except Exception:
        pass
    try:
        import sys
        tools = str(default_engine_paths().bin_path)
        if tools not in sys.path:
            sys.path.insert(0, tools)
        return importlib.import_module("ai_client")
    except Exception:
        return None


def asr_local_override():
    """本地独立 ASR 覆盖参数：``(模型名, 模型目录)``；非本地模式 None。

    镜像 ``core.asr.engine_config.asr_local_override``（唯一事实来源是
    ``data/ai_config.json`` 的 asr 段）——并行引擎不 import 在维护中的
    core 包，故在此复刻同等判据；自检脚本会对着 core 版交叉验证。
    """
    mod = _ai_mod()
    if mod is None:
        return None
    try:
        ac = mod.asr_config(mod.load_config())
    except Exception:  # noqa: BLE001
        return None
    if ac.get("mode") != "local":
        return None
    model = str(ac.get("local_model") or "").strip()
    model_dir = str(ac.get("local_model_dir") or "").strip()
    if not model and not model_dir:
        return None
    return model, model_dir


def _asr_language_label() -> str:
    """显式识别语言标签（空/「自动检测」表示不强制）。"""
    mod = _ai_mod()
    if mod is None:
        return ""
    try:
        ac = mod.asr_config(mod.load_config())
    except Exception:  # noqa: BLE001
        return ""
    return str(ac.get("language_label") or "").strip()


class TaskFactory:
    """任务工厂（API 与引擎 TaskFactory 同名同义）。"""

    # ---------------- 样式 ----------------
    @staticmethod
    def get_ass_style(style_name: str) -> str:
        from vt_engine.style_manager import load_style
        style = load_style(style_name)
        if style is not None:
            return style.to_ass_string()
        return ""

    @staticmethod
    def get_rounded_style() -> dict:
        return {
            "font_name": _cfg.rounded_bg_font_name.value,
            "font_size": _cfg.rounded_bg_font_size.value,
            "bg_color": _cfg.rounded_bg_color.value,
            "text_color": _cfg.rounded_bg_text_color.value,
            "corner_radius": _cfg.rounded_bg_corner_radius.value,
            "padding_h": _cfg.rounded_bg_padding_h.value,
            "padding_v": _cfg.rounded_bg_padding_v.value,
            "margin_bottom": _cfg.rounded_bg_margin_bottom.value,
            "line_spacing": _cfg.rounded_bg_line_spacing.value,
            "letter_spacing": _cfg.rounded_bg_letter_spacing.value,
        }

    # ---------------- 转录任务 ----------------
    @staticmethod
    def create_transcribe_task(file_path: str,
                               need_next_task: bool = False,
                               task_id: Optional[str] = None):
        cfg = _cfg
        file_name = Path(file_path).stem

        if need_next_task:
            need_word_time_stamp = cfg.need_split.value
            output_path = str(
                Path(cfg.work_dir.value) / file_name / "subtitle" /
                f"【原始字幕】{file_name}-{cfg.transcribe_model.value.value}-"
                f"{cfg.transcribe_language.value.value}.srt")
        else:
            need_word_time_stamp = False
            output_path = str(Path(file_path).parent / f"{file_name}.srt")

        config = ent.TranscribeConfig(
            transcribe_model=cfg.transcribe_model.value,
            transcribe_language=ent.LANGUAGES[
                cfg.transcribe_language.value.value],
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
        TaskFactory._apply_asr_override(task)
        return task

    @staticmethod
    def _apply_asr_override(task) -> None:
        """内建 vc_asr_patch_apply：本地模型覆盖 + 显式识别语言。"""
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
            label = _asr_language_label()
            if label and label != "自动检测":
                tcfg = getattr(task, "transcribe_config", None)
                if tcfg is not None:
                    try:
                        tcfg.transcribe_language = \
                            ent.LANGUAGES.get(label, "")
                    except Exception:  # noqa: BLE001
                        tcfg.transcribe_language = ""
        except Exception:  # noqa: BLE001
            logger.exception("ASR 覆盖应用失败（不影响任务构造）")

    # ---------------- 字幕任务 ----------------
    @staticmethod
    def create_subtitle_task(file_path: str,
                             video_path: Optional[str] = None,
                             need_next_task: bool = False,
                             task_id: Optional[str] = None):
        cfg = _cfg
        output_name = (
            Path(file_path).stem.replace("【原始字幕】", "")
            .replace("【下载字幕】", ""))
        suffix = f"-{cfg.translator_service.value.value}" \
            if cfg.need_translate.value else ""
        if need_next_task:
            output_path = str(Path(file_path).parent /
                              f"【样式字幕】{output_name}{suffix}.ass")
        else:
            output_path = str(Path(file_path).parent /
                              f"【字幕】{output_name}{suffix}.srt")

        current_service = cfg.llm_service.value
        LLM = ent.LLMServiceEnum
        if current_service == LLM.OPENAI:
            base_url, api_key, llm_model = (cfg.openai_api_base.value,
                                            cfg.openai_api_key.value,
                                            cfg.openai_model.value)
        elif current_service == LLM.SILICON_CLOUD:
            base_url, api_key, llm_model = (cfg.silicon_cloud_api_base.value,
                                            cfg.silicon_cloud_api_key.value,
                                            cfg.silicon_cloud_model.value)
        elif current_service == LLM.DEEPSEEK:
            base_url, api_key, llm_model = (cfg.deepseek_api_base.value,
                                            cfg.deepseek_api_key.value,
                                            cfg.deepseek_model.value)
        elif current_service == LLM.OLLAMA:
            base_url, api_key, llm_model = (cfg.ollama_api_base.value,
                                            cfg.ollama_api_key.value,
                                            cfg.ollama_model.value)
        elif current_service == LLM.LM_STUDIO:
            base_url, api_key, llm_model = (cfg.lm_studio_api_base.value,
                                            cfg.lm_studio_api_key.value,
                                            cfg.lm_studio_model.value)
        elif current_service == LLM.GEMINI:
            base_url, api_key, llm_model = (cfg.gemini_api_base.value,
                                            cfg.gemini_api_key.value,
                                            cfg.gemini_model.value)
        elif current_service == LLM.CHATGLM:
            base_url, api_key, llm_model = (cfg.chatglm_api_base.value,
                                            cfg.chatglm_api_key.value,
                                            cfg.chatglm_model.value)
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
            subtitle_style=TaskFactory.get_ass_style(
                cfg.subtitle_style_name.value),
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
    def create_synthesis_task(video_path: str, subtitle_path: str,
                              need_next_task: bool = False,
                              task_id: Optional[str] = None):
        cfg = _cfg
        output_path = str(Path(video_path).parent /
                          f"【卡卡】{Path(video_path).stem}.mp4")
        use_style = cfg.use_subtitle_style.value
        config = ent.SynthesisConfig(
            need_video=cfg.need_video.value,
            soft_subtitle=cfg.soft_subtitle.value,
            render_mode=cfg.subtitle_render_mode.value,
            video_quality=cfg.video_quality.value,
            subtitle_layout=cfg.subtitle_layout.value,
            ass_style=TaskFactory.get_ass_style(
                cfg.subtitle_style_name.value) if use_style else "",
            rounded_style=TaskFactory.get_rounded_style() if use_style
            else None,
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

    # ---------------- 组合任务 ----------------
    @staticmethod
    def create_transcript_and_subtitle_task(
            file_path: str, output_path: Optional[str] = None,
            transcribe_config=None, subtitle_config=None):
        if output_path is None:
            output_path = str(Path(file_path).parent /
                              f"{Path(file_path).stem}_processed.srt")
        # 调用方传入的 config 必须透传进任务实体——接受参数却丢弃会让
        # 「自定义配置执行」静默回落全局 cfg（2026-10-19 自查修复）。
        return ent.TranscriptAndSubtitleTask(
            queued_at=datetime.datetime.now(),
            file_path=file_path,
            output_path=output_path,
            transcribe_config=transcribe_config,
            subtitle_config=subtitle_config,
        )

    @staticmethod
    def create_full_process_task(
            file_path: str, output_path: Optional[str] = None,
            transcribe_config=None, subtitle_config=None,
            synthesis_config=None):
        if output_path is None:
            output_path = str(
                Path(file_path).parent / f"{Path(file_path).stem}_final"
                f"{Path(file_path).suffix}")
        # 同 create_transcript_and_subtitle_task：config 透传，不丢弃。
        return ent.FullProcessTask(
            queued_at=datetime.datetime.now(),
            file_path=file_path,
            output_path=output_path,
            transcribe_config=transcribe_config,
            subtitle_config=subtitle_config,
            synthesis_config=synthesis_config,
        )
