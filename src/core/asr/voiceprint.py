# -*- coding: utf-8 -*-
# @version 2.9.0
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
    """已启用的声纹名单（回答**筛谁**）。

    手动「按声纹筛选」按钮用它做前置检查。**自动路径别用它**——名单非空只
    说明用户勾过声音，不代表这次转录要筛，见 `voiceprint_auto_names()`。
    """
    try:
        import speaker_voiceprint as _sv
        return _sv.load_selection()
    except Exception as e:  # noqa: BLE001
        _vc_log(f"读取声纹启用名单失败：{e}")
        return []


def voiceprint_auto_names():
    """转录完成后要不要自动筛——**唯一**的门禁读数。

    名单非空（选了筛谁）**且**转录页「声纹筛选」开关为开（这次确实要筛）才返回
    名单，否则返回 `[]`。纯读数：不查模型、不碰字幕、不写盘，异常一律吞成
    `[]`（= 不筛）。

    以前四个挂载点各自直接读全局名单，等于「某次勾过一下就永久自动筛」：
    2026-11-03 一份 3856 条的日语片被 10-30 残留的陌生声纹筛到只剩 22 条，
    而且筛选是就地覆盖，产物随后又被送进翻译，污染一路扩散。
    """
    try:
        import speaker_voiceprint as _sv
        if not _sv.load_auto_filter():
            return []
        return _sv.load_selection()
    except Exception as e:  # noqa: BLE001
        _vc_log(f"读取声纹自动筛选门禁失败：{e}")
        return []


def voiceprint_auto_filter_enabled():
    """转录页「声纹筛选」开关的状态（**筛不筛**，与「筛谁」的名单是两回事）。"""
    try:
        import speaker_voiceprint as _sv
        return bool(_sv.load_auto_filter())
    except Exception as e:  # noqa: BLE001
        _vc_log(f"读取声纹自动筛选开关失败：{e}")
        return False


def voiceprint_set_auto_filter(enabled):
    """落盘转录页「声纹筛选」开关，返回落盘后的布尔值。"""
    try:
        import speaker_voiceprint as _sv
        return _sv.save_auto_filter(bool(enabled))
    except Exception as e:  # noqa: BLE001
        _vc_log(f"写入声纹自动筛选开关失败：{e}")
        return False


def voiceprint_auto_tooltip():
    """「声纹筛选」开关的 tooltip，按三态说真话。

    自研转录页与引擎补丁**共用这一份文案**：两边挂的是同一个开关，文案各写
    一份迟早会互相打架（也与 `vt_ui_golden` 的控件树等价性同理）。
    """
    try:
        import speaker_voiceprint as _sv
        floor = _sv.DEFAULT_MIN_KEEP_RATIO
    except Exception:  # noqa: BLE001
        floor = 0.05
    on = voiceprint_auto_filter_enabled()
    names = voiceprint_enabled_names()
    if not on:
        return ("声纹筛选（已关闭）\n"
                "转录完成后**不会**动字幕。\n"
                "打开后：转录完成即按齿轮里勾选的声音筛选。")
    if not names:
        return ("声纹筛选（已打开）\n"
                "但还没勾选声音——到右侧齿轮里勾选要保留的声音，"
                "否则转录完不筛。")
    return ("声纹筛选（已打开）\n"
            "本片转录完成后按「%s」筛选（多选 = 并集）。\n"
            "误杀熔断：保留率低于 %.0f%% 时不覆盖成品字幕，只出报告。"
            % ("、".join(names), floor * 100.0))


def voiceprint_result_notice(res):
    """把筛选结果翻成一条界面提示：`(级别, 标题, 正文, 时长ms)`。

    级别取 `success` / `warning` / `error`，调用方据此选 `InfoBar.*`。
    **四处入口共用**（自研转录页、任务创建路径、字幕页手动按钮、引擎补丁），
    文案只在这里改一次——以前四份复制粘贴，熔断态要新增就得同时改四处、
    漏一处就出现「同一个结果两个说法」。
    """
    if isinstance(res, dict) and res.get("error"):
        return ("error", "声纹筛选失败",
                str(res["error"])[:200] + "\n字幕已保留未筛选版本", 9000)
    if res is None:
        return ("warning", "声纹筛选未执行",
                "声纹模型还没下载：到「语音转录 → 主播声纹」点「下载模型」", 8000)
    if res.get("aborted"):
        backup = res.get("backup")
        return ("warning", "疑似误杀：已停止覆盖字幕",
                "模板「%s」只匹配到 %d/%d 条（保留率 %.2f%%，低于熔断线 %.2f%%），"
                "判为声音不匹配。\n成品字幕未改动；筛出的 %d 条已另存「%s」，"
                "明细见「%s」。全文%s"
                % ("、".join(res.get("templates") or []) or "-",
                   res["kept_total"], res["total"],
                   res["keep_ratio"] * 100.0,
                   res["min_keep_ratio"] * 100.0,
                   res["kept_total"],
                   os.path.basename(res.get("kept_path") or "（未写出）"),
                   os.path.basename(res.get("report") or ".报告.txt"),
                   ("仍在「%s」" % os.path.basename(backup)) if backup
                   else "仍在原字幕文件里"),
                15000)
    return ("success", "声纹筛选完成",
            "保留 %d 条（其中存疑 %d）/ 丢弃 %d，保留率 %.1f%%；"
            "原件已备份为「%s」，明细见「%s」"
            % (res["kept_total"], res["review"], res["drop"],
               res.get("keep_ratio", 0.0) * 100.0,
               os.path.basename(res.get("backup") or ""),
               os.path.basename(res.get("report") or ".报告.txt")),
            9000)


def _same_bytes(a, b):
    """两个文件是否逐字节相同（分块比，不整份读进内存）。"""
    try:
        if os.path.getsize(a) != os.path.getsize(b):
            return False
        with open(a, "rb") as fa, open(b, "rb") as fb:
            while True:
                x, y = fa.read(1 << 16), fb.read(1 << 16)
                if x != y:
                    return False
                if not x:
                    return True
    except OSError:
        return False


def voiceprint_filter_subtitle(srt_path, media_path, progress=None, *,
                               names=None, min_keep_ratio=None):
    """把字幕按声纹筛成只留主播（**就地覆盖**）。

    `names` 省略时读已启用名单（手动按钮的行为）；转录完成的自动路径**显式**
    传 `voiceprint_auto_names()` 的结果——顺带消掉「转录跑到一半用户改勾选」
    的竞态。`min_keep_ratio` 省略时用 `speaker_voiceprint` 的出厂熔断线。

    返回结果 dict；返回 `None` 表示「本次不筛」——以下情形都算：
      · 名单为空（用户没打算筛）
      · 声纹模型还没下载（提示用户去「主播声纹 → 下载模型」）
      · 字幕或媒体文件不存在

    ⚠ 备份铁律：**只要准备覆盖成品，就必须先有 `<名>_未筛选.srt` 全文**——
    筛选是启发式的，万一误杀用户还能拿回全文。反过来，熔断（保留率过低，
    判为模板不匹配）时成品一个字节都没动，此时本次自建的等价备份会被收掉，
    不在片源目录里堆垃圾；但**上次运行留下的备份绝不删除**，那可能是全文的
    唯一副本。**任何异常都不吞**——由调用方记日志，绝不留半截产物。
    """
    import shutil
    import speaker_voiceprint as sv

    if names is None:
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
    backup_created = not os.path.isfile(backup)
    if backup_created:
        shutil.copyfile(srt_path, backup)

    kw = {"in_place_backup": backup}
    if min_keep_ratio is not None:
        kw["min_keep_ratio"] = min_keep_ratio
    res = sv.filter_srt(media_path, srt_path, names, out_path=srt_path,
                        progress=progress, **kw)

    if res.get("aborted") and backup_created and _same_bytes(backup, srt_path):
        try:
            os.remove(backup)
            res["backup"] = None
        except OSError:
            res["backup"] = backup
    else:
        res["backup"] = backup
    res["report"] = os.path.splitext(srt_path)[0] + ".报告.txt"

    if res.get("aborted"):
        _vc_log("声纹筛选**熔断未覆盖**（%s）：保留 %d/%d = %.2f%% 低于熔断线 "
                "%.2f%%，成品字幕保持原样；候选 %s"
                % ("、".join(names), res["kept_total"], res["total"],
                   res["keep_ratio"] * 100.0,
                   res["min_keep_ratio"] * 100.0,
                   os.path.basename(res.get("kept_path") or "（未写出）")))
    else:
        _vc_log("声纹筛选完成（%s）：%d 条 -> 保留 %d / 存疑 %d / 丢弃 %d；"
                "原件备份 %s"
                % ("、".join(names), res["total"], res["kept_total"],
                   res["review"], res["drop"],
                   os.path.basename(res["backup"] or "")))
    return res




__all__ = [
    "vc_pydub_nowindow_patch",
    "voiceprint_enabled_names",
    "voiceprint_auto_names",
    "voiceprint_auto_filter_enabled",
    "voiceprint_set_auto_filter",
    "voiceprint_auto_tooltip",
    "voiceprint_result_notice",
    "voiceprint_filter_subtitle",
    "TM_DISPLAY_DEFAULT",
    "TM_DISPLAY_ASR",
]
