# -*- coding: utf-8 -*-
# @version 2.9.0
"""本地 faster-whisper 模型目录解析（纯计算、零第三方依赖）。

背景
----
旧链路把本地转录交给外部 ``faster-whisper-xxl.exe``，模型要么联网下载、
要么落在 HF 缓存（``C:\\Users\\...\\.cache\\huggingface\\hub``）。本轮修复把权重
**物理搬进工具箱**，改成内置 ``faster_whisper.WhisperModel`` 直连，因此必须有
一个稳定的、可在「源码运行 / PyInstaller onefile / 用户改过数据根」三种形态下
都指向同一个 ``tools`` 的解析层。

设计约束
--------
1. **路径口径复刻 ``engine_paths.py`` / ``vt_engine.paths.default_engine_paths``**：
   优先取主程序已有常量（``video_toolbox.TOOLS_DIR`` / ``core.shared.paths``），
   其次走 ``EnginePaths`` 的约定，最后才按 frozen/源码形态自行推导并向上找
   ``tools``。绝不硬编码任何盘符，也绝不按 ``sys._MEIPASS``/``%TEMP%`` 推工具箱
   ——onefile 会把模块解压到 ``%TEMP%\\_MEIxxxx``，那样算出来的是
   ``%TEMP%\\tools\\asr_model``（见 ``speaker_voiceprint.py:115-133`` 的踩坑说明）。
2. **纯计算**：本模块只返回路径字符串与候选列表，不创建目录、不下载、不联网。
3. **显式无效目录必须被忽略而不是报错**：引擎的 ``TaskFactory`` 会把
   ``faster_whisper_model_dir`` 硬编码成 ``data\\videocaptioner\\models``（空目录），
   若把它当真就会「模型找不到」。故只有**真的含完整权重**的目录才算命中。
4. **失败要清晰中文错误**：列出期望目录、必需文件与实际找过的候选路径。
"""

from __future__ import annotations

import os
import sys
from typing import List, Optional, Tuple

__all__ = [
    "FW_REL_DIR",
    "REQUIRED_WEIGHT_FILES",
    "VOCABULARY_NAMES",
    "VOICEPRINT_MODEL_NAME",
    "ModelDirNotFound",
    "resolve_tools_dir",
    "model_root",
    "list_available_models",
    "is_complete_model_dir",
    "candidate_dirs",
    "resolve_model_dir",
]

#: 工具箱内模型根：``{tools}\\asr_model\\faster-whisper``
FW_REL_DIR = os.path.join("asr_model", "faster-whisper")

#: ``WhisperModel(目录)`` 能加载的最少文件集合。
REQUIRED_WEIGHT_FILES = ("config.json", "model.bin", "tokenizer.json")
VOCABULARY_NAMES = ("vocabulary.json", "vocabulary.txt")

#: 声纹模型（同目录，必须原样保留；本模块只读不写）。
VOICEPRINT_MODEL_NAME = "3dspeaker_speech_campplus_sv_zh-cn_16k-common.onnx"

#: HF 缓存仓库名模板（可选回退通道，搬移后通常不再命中）。
_HF_REPO_TMPL = "models--Systran--faster-whisper-%s"


class ModelDirNotFound(FileNotFoundError):
    """模型目录不可用（不存在或缺权重文件）——消息为可操作的中文提示。"""


def resolve_tools_dir(explicit: Optional[str] = None) -> str:
    """定位 ``tools`` 目录，兼容 frozen / 源码 / 自定义数据根三种形态。

    参数
    ----
    explicit:
        显式注入（自检负向用例用）。给了就直接返回其绝对路径，**不校验存在性**
        ——这样调用方可以故意指向不存在的目录来验证报错路径。

    优先级：``explicit`` > ``VT_TOOLS_DIR`` > 主程序常量 > ``core.shared.paths``
    > ``EnginePaths`` 口径 > frozen/源码推导（向上找 ``tools``）。
    """
    if explicit:
        return os.path.abspath(str(explicit))
    env = (os.environ.get("VT_TOOLS_DIR") or "").strip().strip('"')
    if env:
        return os.path.abspath(env)

    # ① 主程序常量：video_toolbox 的 _resolve_dirs 已处理 frozen 与 data_dir.txt
    try:
        import video_toolbox as _vt  # 惰性：本模块可在无 GUI 环境独立 import
        cand = getattr(_vt, "TOOLS_DIR", "")
        if cand and os.path.isdir(str(cand)):
            return os.path.abspath(str(cand))
    except Exception:  # noqa: BLE001 - 引擎未加载/导入失败都继续回退
        pass

    # ② 拆分工程后的单一事实来源
    try:
        from core.shared.paths import TOOLS_DIR as _tools
        if _tools and os.path.isdir(str(_tools)):
            return os.path.abspath(str(_tools))
    except Exception:  # noqa: BLE001
        pass

    # ③ EnginePaths 口径（vt_engine.paths.default_engine_paths 复用同一实现）
    try:
        from vt_engine.paths import default_engine_paths
        cand = str(default_engine_paths().tools_dir)
        if cand and os.path.isdir(cand):
            return os.path.abspath(cand)
    except Exception:  # noqa: BLE001
        pass

    # ④ 兜底：frozen 锚 exe 目录；源码锚本文件上两级；再向上逐级找 tools
    if getattr(sys, "frozen", False):
        app = os.path.dirname(os.path.abspath(sys.executable))
    else:
        app = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cur = app
    for _ in range(5):
        cand = os.path.join(cur, "tools")
        if os.path.isdir(cand):
            return os.path.abspath(cand)
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    return os.path.abspath(os.path.join(app, "tools"))


def model_root(tools_dir: Optional[str] = None) -> str:
    """返回 ``{tools}\\asr_model\\faster-whisper``（纯计算，不建目录）。"""
    return os.path.join(resolve_tools_dir(tools_dir), FW_REL_DIR)


def _is_nonempty_file(path: str) -> bool:
    try:
        return os.path.isfile(path) and os.path.getsize(path) > 0
    except OSError:
        return False


def is_complete_model_dir(path: str) -> bool:
    """目录里是否含可直接加载的扁平权重。

    ``WhisperModel(str(path), local_files_only=True)`` 要求 config/model/tokenizer
    与词表都在同一层；HF 快照目录天然满足，我们搬移后的目录也按此结构整理。
    """
    if not path or not os.path.isdir(path):
        return False
    for name in REQUIRED_WEIGHT_FILES:
        if not _is_nonempty_file(os.path.join(path, name)):
            return False
    if not any(_is_nonempty_file(os.path.join(path, n))
               for n in VOCABULARY_NAMES):
        return False
    return True


def _expand_explicit(model_name: str, explicit_dir: str) -> List[str]:
    """把「显式模型目录」展开成候选列表（含相对路径按程序根解析）。"""
    raw = str(explicit_dir or "").strip().strip('"')
    if not raw:
        return []
    if os.path.isabs(raw):
        bases = [os.path.abspath(raw)]
    else:
        # settings.json 里允许写相对路径（如 tools/asr_model/faster-whisper）
        root = resolve_tools_dir()
        app = os.path.dirname(root)
        bases = [os.path.abspath(os.path.join(app, raw)),
                 os.path.abspath(os.path.join(root, raw))]
    out: List[str] = []
    for base in bases:
        for cand in (base,
                     os.path.join(base, str(model_name)),
                     os.path.join(base, "faster-whisper", str(model_name))):
            cand = os.path.abspath(cand)
            if cand not in out:
                out.append(cand)
    return out


def _hf_snapshot_candidates(model_name: str) -> List[str]:
    """可选回退：原 HF 缓存里的快照目录（搬移后正常不再命中，且不联网）。"""
    out: List[str] = []
    try:
        hf_home = (os.environ.get("HF_HOME") or "").strip()
        hub = (os.path.join(hf_home, "hub") if hf_home else
               os.path.join(os.path.expanduser("~"), ".cache",
                            "huggingface", "hub"))
        repo = os.path.join(hub, _HF_REPO_TMPL % str(model_name))
        snap_root = os.path.join(repo, "snapshots")
        if os.path.isdir(snap_root):
            for name in sorted(os.listdir(snap_root)):
                cand = os.path.join(snap_root, name)
                if os.path.isdir(cand):
                    out.append(os.path.abspath(cand))
    except OSError:
        pass
    return out


def candidate_dirs(model_name: str, explicit_dir: str = "",
                   tools_dir: Optional[str] = None) -> List[str]:
    """按优先级返回全部候选目录（供解析、日志与自检使用）。

    顺序即优先级：模型名本身是目录 > 显式目录 > 工具箱内模型 > HF 快照。
    """
    name = str(model_name or "").strip()
    out: List[str] = []

    def add(cand: str) -> None:
        cand = os.path.abspath(str(cand))
        if cand and cand not in out:
            out.append(cand)

    # ① 自定义模型名本身就是一个目录（自训练/微调模型）
    if name and os.path.isabs(name) and os.path.isdir(name):
        add(name)
    # ② 显式配置（可能指向数据根 models 空目录，故只作候选）
    for cand in _expand_explicit(name, explicit_dir):
        add(cand)
    # ③ 工具箱内随包模型
    if name:
        add(os.path.join(model_root(tools_dir), name))
    # ④ 可选：原 HF 缓存快照
    if name:
        for cand in _hf_snapshot_candidates(name):
            add(cand)
    return out


def list_available_models(tools_dir: Optional[str] = None) -> List[str]:
    """列出工具箱内**完整可加载**的模型名（排序，供设置页/自检提示）。"""
    root = model_root(tools_dir)
    try:
        names = os.listdir(root)
    except OSError:
        return []
    return sorted(n for n in names
                  if not n.startswith("_")
                  and is_complete_model_dir(os.path.join(root, n)))


def resolve_model_dir(model_name: str, explicit_dir: str = "",
                      tools_dir: Optional[str] = None) -> str:
    """按优先级解析模型目录，返回可直接传给 ``WhisperModel`` 的绝对路径。

    优先级：显式 ``explicit_dir``（须含完整权重）> 工具箱内
    ``tools\\asr_model\\faster-whisper\\<model>`` >（可选）原 HF 缓存快照。
    显式目录无效时**忽略并回退**（引擎会把 ``faster_whisper_model_dir`` 写死成
    空的数据根 models 目录，不能让它顶掉工具箱里的真权重）。

    找不到时抛 :class:`ModelDirNotFound`，消息含中文可操作指引。
    """
    name = str(model_name or "").strip() or "large-v3"
    candidates = candidate_dirs(name, explicit_dir, tools_dir)
    for cand in candidates:
        if is_complete_model_dir(cand):
            return cand

    root = model_root(tools_dir)
    expected = os.path.join(root, name)
    lines = [
        "未找到可用的本地 faster-whisper 模型「%s」。" % name,
        "请把模型文件放到：%s" % expected,
        "该目录需含：%s 以及 %s 之一（config.json / model.bin / tokenizer.json / vocabulary.json 或 vocabulary.txt）。"
        % (", ".join(REQUIRED_WEIGHT_FILES), " / ".join(VOCABULARY_NAMES)),
        "也可以在「设置 → ASR 语音识别 → 本地独立模型」里填一个含完整权重的目录；"
        "留空即自动定位工具箱内模型。",
        "本次查找过的候选路径：",
    ]
    lines.extend("  - %s%s" % (p, "（存在但缺权重文件）"
                             if os.path.isdir(p) else "（不存在）")
                 for p in candidates)
    raise ModelDirNotFound("\n".join(lines))
