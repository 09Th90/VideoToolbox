# -*- coding: utf-8 -*-
# @version 2.5.0
"""转录体验补丁（黑窗抑制）+ 主播声纹筛选（转录完成后处理）（v2.3.1 拆分工程 · 自 video_toolbox.py 原样搬入）。

v2.3.1 拆分工程；域间依赖规则见 core/__init__.py。
"""

import subprocess

import os
import sys

from core.shared.log import _vc_log

# ---------- v1.14.1：转录体验补丁（黑窗 / 下拉收敛 / 完成回填） ----------

def vc_pydub_nowindow_patch():
    """消掉「开启转录时闪黑色控制台窗口」（幂等，仅 Windows 生效）。

    根因：转录统一走 ChunkedASR，其 _split_audio() 必经 pydub 的
    AudioSegment.from_file()——pydub 内部裸调 ffprobe/ffmpeg 且不带
    CREATE_NO_WINDOW，GUI 进程下每次转录开始都会闪出黑色控制台窗口
    （分块导出 mp3、whisper_cpp 的 CLI 子进程同理）。引擎与 pydub 本体
    都不改，只动 subprocess 的班长方式。

    2026-10-20 性能优化：原实现靠**预先导入** pydub / whisper_cpp 两棵
    模块树做引用交换补丁，其中 whisper_cpp 一溜的引擎 ASR 链实测
    ≈2.6s，全压在启动关键路径上（prepare_runtime_env）。改为**全局
    Popen shim**：补丁之后导入/发起的一切 subprocess.Popen（含
    run/check_output 等内部转发）默认补 CREATE_NO_WINDOW——pydub.utils
    的 `from subprocess import Popen`、whisper_cpp 的属性式调用都天然
    覆盖，启动期不再需要预先导入任何重模块。已导入过的老模块仍按老
    办法补一次引用交换（属性仍指向原 Popen 时才补）。显式传了
    creationflags / startupinfo 的调用方不受影响。
    """
    if os.name != "nt":
        return True
    if getattr(subprocess, "_vt_nowindow", False):
        return True
    try:
        orig = subprocess.Popen
        if not getattr(orig, "_vt_nowindow_wrapped", False):
            # ⚠ 必须是**类**而不是函数：标准库 `asyncio.windows_utils` 里有
            # `class Popen(subprocess.Popen)`，把 Popen 换成函数会让它继承
            # 失败（TypeError: function() argument 'code' must be code, not
            # str），进而 openai/asyncio 导入链整体崩掉（2026-10-20 实测：
            # 引擎预热 import=fail 的根因）。
            class _VTPopen(orig):          # noqa: N801 —— 与 Popen 同名语义
                _vt_nowindow_wrapped = True

                def __init__(self, *args, **kwargs):
                    try:
                        if not kwargs.get("creationflags") \
                                and not kwargs.get("startupinfo"):
                            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
                    except Exception:
                        pass
                    super().__init__(*args, **kwargs)

            subprocess.Popen = _VTPopen
        subprocess._vt_nowindow = True
        subprocess._vt_nowindow_orig = orig
        # 补丁前已导入的模块：引用仍指向原 Popen 的才补交换（未导入的
        # 后续天然吃到全局 shim，无需也不该在此触发重导入）。
        patched = []
        mod = sys.modules.get("pydub.audio_segment")
        if mod is not None and getattr(mod, "subprocess", None) is subprocess:
            mod.subprocess = subprocess
            patched.append("pydub.audio_segment")
        mod = sys.modules.get("pydub.utils")
        if mod is not None and getattr(mod, "Popen", None) is orig:
            mod.Popen = subprocess.Popen
            patched.append("pydub.utils")
        if patched:
            _vc_log("黑窗隐藏补丁已挂（全局 Popen shim；已加载模块补交换）："
                    + ", ".join(patched))
        else:
            _vc_log("黑窗隐藏补丁已挂：全局 Popen shim（后续导入默认无窗）")
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




__all__ = [
    "vc_pydub_nowindow_patch",
    "voiceprint_enabled_names",
    "voiceprint_filter_subtitle",
    "TM_DISPLAY_DEFAULT",
    "TM_DISPLAY_ASR",
]
