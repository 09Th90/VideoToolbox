# -*- coding: utf-8 -*-
# @version 3.0.0
"""跨功能共享的媒体类型常量（纯标准库，2026-11-15 功能解耦阶段③）。

原在 video_toolbox_qt.py 模块级，被下载/合并/切片/视频库/拖放分派共用。
下沉到功能层共享模块：各页面 ``from features._media import ...``，
入口再导出旧名保存量调用方零改动。
"""

#: 视频：常见容器 + av1 / h264 / h265 / x264 等裸流与更多封装；
#: 音频：常见音频容器；
#: 字幕：常见字幕文本格式。
#: 这些集合既用于「视频库」扫描，也用于「把文件拖进程序」时的类型分派。
VIDEO_EXTS = {".mp4", ".mkv", ".avi", ".mov", ".flv", ".wmv", ".ts", ".m4v",
              ".webm", ".av1", ".264", ".h264", ".x264", ".265", ".h265",
              ".x265", ".hevc", ".m2ts", ".mts", ".vob", ".ogv", ".3gp",
              ".mpg", ".mpeg", ".divx", ".rm", ".rmvb", ".asf", ".mxf"}
AUDIO_EXTS = {".mp3", ".m4a", ".wav", ".aac", ".flac", ".ogg", ".oga",
              ".opus", ".wma", ".amr", ".ape", ".ac3", ".dts", ".wv",
              ".aiff", ".aif", ".caf"}
SUBTITLE_EXTS = {".srt", ".ass", ".ssa", ".vtt", ".sub", ".smi", ".sbv", ".lrc"}

# 字幕编辑「打开媒体」对话框的完整格式过滤串（与 VIDEO_EXTS + AUDIO_EXTS 对应）
MEDIA_FILE_FILTER = ("媒体文件 (" + " ".join("*" + e for e in
                      sorted(VIDEO_EXTS | AUDIO_EXTS, key=str.lower)) +
                     ");;所有文件 (*.*)")

# 「音画合并 → 手动合并」三个拖放槽的浏览过滤串（分别与三个扩展名集合对应）
VIDEO_FILE_FILTER = ("视频文件 (" + " ".join("*" + e for e in
                      sorted(VIDEO_EXTS, key=str.lower)) + ");;所有文件 (*.*)")
AUDIO_FILE_FILTER = ("音频文件 (" + " ".join("*" + e for e in
                      sorted(AUDIO_EXTS, key=str.lower)) + ");;所有文件 (*.*)")
SUB_FILE_FILTER = ("字幕文件 (" + " ".join("*" + e for e in
                    sorted(SUBTITLE_EXTS, key=str.lower)) + ");;所有文件 (*.*)")