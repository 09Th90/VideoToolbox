# @version 2.5.4
"""任务上下文（自研，替代 videocaptioner.core.llm.context 的公开面）。

``generate_task_id`` 的格式是 8 位 hex（``uuid4().hex[:8]``）——任务 ID
会进 LLM 请求日志与任务链传递，改动只会影响日志可读性，无持久化契约；
但保持同格式便于两套实现并行期日志对照。任务上下文用模块级变量 +
锁（ThreadPoolExecutor 不自动复制 contextvars，与引擎同因）。
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass
from typing import Optional

__all__ = [
    "TaskContext",
    "generate_task_id",
    "set_task_context",
    "get_task_context",
    "update_stage",
    "clear_task_context",
]


@dataclass
class TaskContext:
    """任务上下文。"""

    task_id: str      # 任务唯一标识，如 "a1b2c3d4"
    file_name: str    # 处理的文件名，如 "video.mp4"
    stage: str        # 当前阶段: transcribe / split / optimize / translate / synthesis


_lock = threading.Lock()
_current_context: Optional[TaskContext] = None


def generate_task_id() -> str:
    """生成 8 位任务 ID（与引擎同格式）。"""
    return uuid.uuid4().hex[:8]


def set_task_context(task_id: str, file_name: str, stage: str) -> None:
    """设置当前任务上下文。"""
    global _current_context
    with _lock:
        _current_context = TaskContext(task_id=task_id, file_name=file_name,
                                       stage=stage)


def get_task_context() -> Optional[TaskContext]:
    """获取当前任务上下文。"""
    with _lock:
        return _current_context


def update_stage(stage: str) -> None:
    """更新当前阶段。"""
    global _current_context
    with _lock:
        if _current_context:
            _current_context = TaskContext(
                task_id=_current_context.task_id,
                file_name=_current_context.file_name,
                stage=stage,
            )


def clear_task_context() -> None:
    """清除任务上下文。"""
    global _current_context
    with _lock:
        _current_context = None
