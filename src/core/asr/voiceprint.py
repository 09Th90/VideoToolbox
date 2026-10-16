# -*- coding: utf-8 -*-
# @version 2.3.1
"""转录体验补丁（黑窗抑制）+ 主播声纹筛选（转录完成后处理）（v2.3.1 拆分工程 · 自 video_toolbox.py 原样搬入）。

v2.3.1 拆分工程；域间依赖规则见 core/__init__.py。
"""

import subprocess

import os

from core.shared.log import _vc_log

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




__all__ = [
    "vc_pydub_nowindow_patch",
    "voiceprint_enabled_names",
    "voiceprint_filter_subtitle",
    "TM_DISPLAY_DEFAULT",
    "TM_DISPLAY_ASR",
]
