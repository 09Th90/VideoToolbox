# -*- coding: utf-8 -*-
# @version 2.3.1
"""媒体扫描 / 智能配对 / 音画合并（mp4+m4a/weba+srt/ass → 成品）（v2.3.1 拆分工程 · 自 video_toolbox.py 原样搬入）。

core/download 域：yt-dlp 全链 / cookie / NPE / 媒体合并；依赖规则见 core/__init__.py。
"""

from core.download.util import format_size, format_time
from core.shared.textio import decode_bytes_any


import glob
from core.download.deps import ensure_ffmpeg
from core.download.urls import DEFAULT_INPUT_DIR, DURATION_THRESHOLD
from core.shared.paths import SCRIPT_DIR, clean_path

import os

from core.shared.paths import FFMPEG_PATH, FFPROBE_PATH
from core.shared.proc import run_process
from core.shared.textio import write_text_utf8
from core.download.util import make_cover_1280x720

# ========== 功能 2：音视频智能合并（整合自 v3.2） ==========
#: 时长探测缓存（路径+大小+mtime 建键）：视频库每次刷新会对每个媒体文件
#: 起一个 ffprobe 进程，实测对刚写完的几 GB 大文件单次可达数秒——同文件
#: 未变时直接复用结果，完成风暴下不再反复 spawn ffprobe。
_DUR_CACHE = {}


def get_duration(filepath, ffprobe_path):
    cmd = [
        ffprobe_path, '-v', 'error',
        '-show_entries', 'format=duration',
        '-of', 'csv=p=0',
        filepath
    ]
    try:
        st = os.stat(filepath)
        key = (os.path.abspath(filepath), st.st_size, st.st_mtime_ns)
    except OSError:
        return 0.0
    hit = _DUR_CACHE.get(key)
    if hit is not None:
        return hit
    try:
        result = run_process(cmd, capture_output=True, check=True)
        dur = float(decode_bytes_any(result.stdout).strip() or 0.0)
    except Exception:
        dur = 0.0
    if len(_DUR_CACHE) > 5000:
        _DUR_CACHE.clear()
    _DUR_CACHE[key] = dur
    return dur


def probe_audio_codec(filepath, ffprobe_path):
    """探测首个音频流的编码名（小写）；失败返回 ''。

    手动合并用它决定音频走「直接 copy」还是「转 AAC」——不能像自动配对那样
    靠扩展名猜（那里只有 m4a / weba 两种）。用户从资源管理器拖进来的是任意
    音频：mp3 / wav / flac / ogg / opus / aac / m4a …，扩展名与容器里的实际
    编码未必一致（例如 .m4a 里可能是 ALAC 无损）。实测编码才是可靠依据。
    """
    cmd = [
        ffprobe_path, '-v', 'error',
        '-select_streams', 'a:0',
        '-show_entries', 'stream=codec_name',
        '-of', 'default=noprint_wrappers=1:nokey=1',
        filepath,
    ]
    try:
        result = run_process(cmd, capture_output=True, check=True)
        return decode_bytes_any(result.stdout).strip().lower()
    except Exception:  # noqa: BLE001
        return ''


#: 自动配对接受的视频容器（v1.18.0 起不再只认 mp4）。
#: ⚠️ 这里只列**能装进 mp4 输出**的容器：合并产物恒定 .mp4，容器能力不对就会
#   在 copy 阶段炸掉。实测（tools\ffmpeg.exe）：
#     mp4/mov/m4v/mkv/ts/avi/flv/wmv —— 接受 -c:v copy + aac；
#     **webm 装不了 h264/aac**（`Could not write header`），但它的典型编码
#     VP9/AV1 **可以**直接进 mp4，所以 webm 输入照样能用（VP8 才会失败并
#     靠 reencode_video=True 重试救回）。
#: 因此「输入容器」不加限制也可以，只要内容编码与 mp4 兼容。
MERGE_VIDEO_EXTS = (".mp4", ".mkv", ".webm", ".mov", ".m4v",
                    ".avi", ".flv", ".ts", ".m4s", ".wmv", ".f4v")

#: 音画证据（2026-10-12）：按 SRT 路径猜源媒体的扩展名（视频容器 + 音频兜底）
CALIB_MEDIA_EXTS = MERGE_VIDEO_EXTS + (".m4a", ".mp3", ".wav", ".aac",
                                       ".flac", ".ogg")


def calib_media_for_srt(srt_path):
    """按字幕路径找同目录同名源媒体（视频优先，其次音频）；找不到返回 ""。

    校准页只认 SRT 路径，而音画证据需要源媒体——下载/剪辑流程里视频与
    字幕恒定同目录同名，这是最可靠的猜法。猜不到就返回空串，Agent 按
    离线继续（行为与旧版完全一致）。
    """
    try:
        base = os.path.splitext(os.path.abspath(srt_path))[0]
        d = os.path.dirname(base)
        if not os.path.isdir(d):
            return ""
        for ext in CALIB_MEDIA_EXTS:
            for suffix in (ext, ext.upper()):
                p = base + suffix
                if os.path.isfile(p):
                    return p
    except Exception:  # noqa: BLE001
        pass
    return ""


def scan_media(folder, video_exts=None):
    """扫描视频、音频(m4a优先，其次weba)、字幕(srt/ass)。

    video_exts：参与自动配对的视频扩展名，默认 `MERGE_VIDEO_EXTS`。
      · 传 `None`（默认）⇒ 用 `MERGE_VIDEO_EXTS` 全量；
      · 传 `(".mp4",)` ⇒ 只扫 mp4（旧的「只要 mp4」口径，自检
        `multicontainer_cases()` 用它验证多容器确实是新增行为而非一直如此）；
      · 传**空集合** ⇒ 一个视频都不扫，`videos` 恒为 `[]`。
      ⚠️ 别把空集合当「退回 mp4」用——那会让 `find_pairs()` 配不出对，
      表现为「目录里明明有视频却扫不到」。要限制口径就显式写 `(".mp4",)`。

    ⚠️ 历史坑：这里曾硬编码只 glob `*.mp4`，于是「同名 webm + m4a」这类目录
    配对结果恒为 0，webm 只能走「手动合并」逐个拖。现在多容器统一参与，
    排序仍按文件名（大小写不敏感）以保证配对顺序稳定。
    """
    exts = tuple(MERGE_VIDEO_EXTS if video_exts is None else video_exts)

    def _by_ext(ext):
        out = []
        for suffix in (ext, ext.upper()):
            out += glob.glob(os.path.join(folder, f'*{suffix}'))
        return sorted(out, key=lambda x: os.path.basename(x).lower())

    videos = []
    for ext in exts:
        for p in _by_ext(ext):
            if p not in videos:      # 扩展名重叠时去重（保持首次出现顺序）
                videos.append(p)
    m4as = sorted(glob.glob(os.path.join(folder, '*.m4a')) + glob.glob(os.path.join(folder, '*.M4A')),
                  key=lambda x: os.path.basename(x).lower())
    webas = sorted(glob.glob(os.path.join(folder, '*.weba')) + glob.glob(os.path.join(folder, '*.WEBA')),
                   key=lambda x: os.path.basename(x).lower())
    srts = sorted(glob.glob(os.path.join(folder, '*.srt')) + glob.glob(os.path.join(folder, '*.SRT')),
                  key=lambda x: os.path.basename(x).lower())
    asss = sorted(glob.glob(os.path.join(folder, '*.ass')) + glob.glob(os.path.join(folder, '*.ASS')),
                  key=lambda x: os.path.basename(x).lower())
    return videos, m4as, webas, srts, asss


def get_base_name(filepath):
    return os.path.splitext(os.path.basename(filepath))[0]


def find_subtitle(video_base, srts, asss):
    """按基础文件名查找字幕"""
    for s in srts:
        if get_base_name(s) == video_base:
            return s, 'srt'
    for a in asss:
        if get_base_name(a) == video_base:
            return a, 'ass'
    return None, None


def smart_pair(mp4s, m4as, webas, srts, asss, ffprobe_path):
    """智能配对 视频 + 音频(m4a优先，其次weba)，并关联字幕。

    ⚠️ 第一个形参名叫 `mp4s` 是历史包袱，实际收的是**任意容器**的视频列表
    （scan_media 默认按 MERGE_VIDEO_EXTS 收）。**所有调用点都用位置传参**，
    所以只改名不动顺序；真要语义化得连调用点一起改，另说。
    内部逻辑本来就不依赖"必须是 mp4"，只是拿文件名 + 时长做匹配。
    """
    mp4_dur = {f: get_duration(f, ffprobe_path) for f in mp4s}
    m4a_dur = {f: get_duration(f, ffprobe_path) for f in m4as}
    weba_dur = {f: get_duration(f, ffprobe_path) for f in webas}

    mp4_by_name = {get_base_name(f): f for f in mp4s}
    m4a_by_name = {get_base_name(f): f for f in m4as}
    weba_by_name = {get_base_name(f): f for f in webas}

    pairs = []
    used_mp4 = set()
    used_audio = set()

    # 阶段1：同名匹配（优先 m4a，其次 weba）
    for name, mp4_path in mp4_by_name.items():
        audio_path = None
        audio_type = None
        if name in m4a_by_name:
            audio_path = m4a_by_name[name]
            audio_type = 'm4a'
        elif name in weba_by_name:
            audio_path = weba_by_name[name]
            audio_type = 'weba'

        if audio_path:
            dur_map = m4a_dur if audio_type == 'm4a' else weba_dur
            diff = abs(mp4_dur[mp4_path] - dur_map[audio_path])
            match_type = "perfect" if diff <= DURATION_THRESHOLD else "name_only"
            sub_path, sub_type = find_subtitle(name, srts, asss)
            pairs.append((mp4_path, audio_path, audio_type, match_type, diff, sub_path, sub_type))
            used_mp4.add(mp4_path)
            used_audio.add(audio_path)

    # 阶段2：未配对的按时长匹配（优先 m4a，其次 weba）
    remaining_mp4 = [f for f in mp4s if f not in used_mp4]
    remaining_m4a = [f for f in m4as if f not in used_audio]
    remaining_weba = [f for f in webas if f not in used_audio]

    for mp4_path in remaining_mp4:
        best_audio = None
        best_type = None
        best_diff = float('inf')

        for m4a_path in remaining_m4a:
            diff = abs(mp4_dur[mp4_path] - m4a_dur[m4a_path])
            if diff < best_diff:
                best_diff = diff
                best_audio = m4a_path
                best_type = 'm4a'

        for weba_path in remaining_weba:
            diff = abs(mp4_dur[mp4_path] - weba_dur[weba_path])
            if diff < best_diff:
                best_diff = diff
                best_audio = weba_path
                best_type = 'weba'

        if best_audio and best_diff <= DURATION_THRESHOLD:
            name = get_base_name(mp4_path)
            sub_path, sub_type = find_subtitle(name, srts, asss)
            pairs.append((mp4_path, best_audio, best_type, "duration", best_diff, sub_path, sub_type))
            used_mp4.add(mp4_path)
            used_audio.add(best_audio)
            if best_type == 'm4a':
                remaining_m4a.remove(best_audio)
            else:
                remaining_weba.remove(best_audio)

    order = {"perfect": 0, "duration": 1, "name_only": 2}
    pairs.sort(key=lambda x: order.get(x[3], 99))

    return pairs, remaining_mp4, remaining_m4a, remaining_weba


def merge_pair(mp4_path, audio_path, audio_type, sub_path, sub_type, output_path, ffmpeg_path, ass_mode='burn',
               reencode_video=False):
    """
    合并一对音视频+字幕
    audio_type: 'm4a' 或 'weba'
    ass_mode: 'burn'=硬字幕, 'mkv'=封装MKV, 'ignore'=忽略
    reencode_video: 视频流是否强制重编码 H.264（默认 copy）。

    reencode_video 的由来（实测纠正，别再照旧注释传）：
      早先以为「vp9 / av1 装不进 mp4」，实测**错**——用当前 tools\ffmpeg.exe，
      VP9 与 AV1 都能 `-c:v copy` 直接封进 mp4 且解码校验通过。
      真正会失败的是 **VP8**（`tag for codec vp8 in stream #0, codec not
      currently supported in container`）。所以 copy 失败后的重试仍然要留着，
      但它救的是 VP8 这类，而不是 vp9/av1。
      另注：输入容器是 **webm 也不行**——webm 容器本身装不了 h264/aac
      （连不带 `-movflags` 都 `Could not write header`），产物恒为 mp4。
    """
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    audio_codec = ['-c:a', 'copy'] if audio_type == 'm4a' else ['-c:a', 'aac', '-b:a', '192k']
    video_codec = (['-c:v', 'libx264', '-crf', '18', '-preset', 'fast']
                   if reencode_video else ['-c:v', 'copy'])

    # 无字幕
    if not sub_path:
        cmd = [
            ffmpeg_path, '-y',
            '-fflags', '+genpts',
            '-i', mp4_path,
            '-i', audio_path,
            *video_codec,
            *audio_codec,
            '-map', '0:v:0',
            '-map', '1:a:0',
            '-movflags', '+faststart',
            '-avoid_negative_ts', 'make_zero',
            '-shortest',
            output_path
        ]
    # SRT 软字幕
    elif sub_type == 'srt':
        cmd = [
            ffmpeg_path, '-y',
            '-fflags', '+genpts',
            '-i', mp4_path,
            '-i', audio_path,
            '-i', sub_path,
            *video_codec,
            *audio_codec,
            '-c:s', 'mov_text',
            '-map', '0:v:0',
            '-map', '1:a:0',
            '-map', '2:s:0',
            '-metadata:s:s:0', 'language=chi',
            '-movflags', '+faststart',
            '-avoid_negative_ts', 'make_zero',
            '-shortest',
            output_path
        ]
    # ASS 硬字幕烧录（视频必须重编码）
    elif sub_type == 'ass' and ass_mode == 'burn':
        sub_path_clean = os.path.abspath(sub_path).replace('\\', '/').replace("'", "\\'")
        vf = f"subtitles='{sub_path_clean}'"
        cmd = [
            ffmpeg_path, '-y',
            '-i', mp4_path,
            '-i', audio_path,
            '-vf', vf,
            '-c:v', 'libx264',
            '-crf', '18',
            '-preset', 'fast',
            *audio_codec,
            '-movflags', '+faststart',
            '-shortest',
            output_path
        ]
    # ASS 封装 MKV
    elif sub_type == 'ass' and ass_mode == 'mkv':
        output_path = os.path.splitext(output_path)[0] + '.mkv'
        cmd = [
            ffmpeg_path, '-y',
            '-fflags', '+genpts',
            '-i', mp4_path,
            '-i', audio_path,
            '-i', sub_path,
            *video_codec,
            *audio_codec,
            '-map', '0:v:0',
            '-map', '1:a:0',
            '-map', '2:s:0',
            '-metadata:s:s:0', 'language=chi',
            '-shortest',
            output_path
        ]
    else:
        return False, output_path

    result = run_process(cmd, capture_output=True)
    success = result.returncode == 0
    if not success:
        print(f"     [错误] {decode_bytes_any(result.stderr)[-200:]}")
    return success, output_path


def merge_mode(input_dir=None):
    print("\n" + "=" * 60)
    print("  音视频智能合并（mp4/mkv/webm/mov… + m4a/weba + srt/ass）")
    print("=" * 60)
    ffmpeg_path, ffprobe_path = ensure_ffmpeg()
    print(f"[OK] ffmpeg 就绪\n")

    if input_dir is None:
        input_dir = DEFAULT_INPUT_DIR if os.path.isdir(DEFAULT_INPUT_DIR) else SCRIPT_DIR

    print(f"默认输入文件夹: {input_dir}")
    new_in = clean_path(input("按回车确认，或输入新路径: "))
    if new_in and os.path.isdir(new_in):
        input_dir = new_in

    default_out = os.path.join(input_dir, "合成结果")
    print(f"\n默认输出文件夹: {default_out}")
    new_out = clean_path(input("按回车确认，或输入新路径: "))
    output_dir = new_out or default_out
    os.makedirs(output_dir, exist_ok=True)

    print(f"\n[信息] 正在扫描: {input_dir}")
    mp4s, m4as, webas, srts, asss = scan_media(input_dir)

    if not mp4s:
        print(f"[错误] 未找到视频文件（支持: {' '.join(MERGE_VIDEO_EXTS)}）")
        return
    if not m4as and not webas:
        print("[错误] 未找到 m4a 或 weba 音频文件")
        return

    print(f"[OK] 找到 {len(mp4s)} 个视频, {len(m4as)} 个 m4a, {len(webas)} 个 weba, {len(srts)} 个 srt, {len(asss)} 个 ass")

    print("\n[信息] 正在分析配对...")
    pairs, rem_mp4, rem_m4a, rem_weba = smart_pair(mp4s, m4as, webas, srts, asss, ffprobe_path)

    has_ass = any(p[6] == 'ass' for p in pairs)

    ass_mode = 'burn'
    if has_ass:
        print("\n" + "-" * 60)
        print("检测到 ASS 字幕文件，请选择处理方式：")
        print("  1. 烧录为硬字幕（保留特效样式，视频会重新编码，较慢）")
        print("  2. 封装为 MKV（不重新编码，播放器需支持 ASS 显示）")
        print("  3. 忽略 ASS 字幕")
        choice = input("请选择 [1/2/3，默认1]: ").strip() or "1"
        if choice == '2':
            ass_mode = 'mkv'
        elif choice == '3':
            ass_mode = 'ignore'

    print("\n" + "=" * 60)
    print("  配对结果")
    print("=" * 60)

    perfect = [p for p in pairs if p[3] == "perfect"]
    duration_match = [p for p in pairs if p[3] == "duration"]
    name_only = [p for p in pairs if p[3] == "name_only"]

    def show_pair(p):
        mp4, audio, audio_type, mt, diff, sub, st = p
        vd = get_duration(mp4, ffprobe_path)
        ad = get_duration(audio, ffprobe_path)
        audio_label = "[m4a→copy]" if audio_type == 'm4a' else "[weba→AAC转码]"
        sub_info = ""
        if st == 'srt':
            sub_info = f" | 字幕: {os.path.basename(sub)} [SRT软字幕]"
        elif st == 'ass':
            if ass_mode == 'burn':
                sub_info = f" | 字幕: {os.path.basename(sub)} [ASS硬字幕]"
            elif ass_mode == 'mkv':
                sub_info = f" | 字幕: {os.path.basename(sub)} [ASS→MKV]"
            else:
                sub_info = " | 字幕: 已忽略"
        print(f"  视频: {os.path.basename(mp4)} ({format_time(vd)})")
        print(f"  音频: {os.path.basename(audio)} ({format_time(ad)}) {audio_label}")
        print(f"  时长差: {diff:.3f}s{sub_info}")
        print()

    if perfect:
        print(f"\n[完美匹配] 同名 + 时长一致 ({len(perfect)} 对):")
        for p in perfect:
            show_pair(p)
    if duration_match:
        print(f"\n[时长匹配] 不同名但时长一致 ({len(duration_match)} 对):")
        for p in duration_match:
            show_pair(p)
    if name_only:
        print(f"\n[同名不匹配] 文件名相同但时长差异大 ({len(name_only)} 对):")
        for p in name_only:
            show_pair(p)

    if rem_mp4:
        print(f"\n[未匹配视频] ({len(rem_mp4)} 个):")
        for f in rem_mp4:
            print(f"  {os.path.basename(f)} ({format_time(get_duration(f, ffprobe_path))})")
    if rem_m4a:
        print(f"\n[未匹配音频-m4a] ({len(rem_m4a)} 个):")
        for f in rem_m4a:
            print(f"  {os.path.basename(f)}")
    if rem_weba:
        print(f"\n[未匹配音频-weba] ({len(rem_weba)} 个):")
        for f in rem_weba:
            print(f"  {os.path.basename(f)}")

    to_merge = perfect + duration_match
    if name_only:
        print("\n" + "-" * 60)
        print("发现同名但时长不匹配的配对，是否强制合成？")
        choice = input("强制合成这些配对? [y/N]: ").strip().lower()
        if choice == 'y':
            to_merge.extend(name_only)

    if not to_merge:
        print("\n[提示] 没有可合成的配对")
        return

    if ass_mode == 'ignore':
        for i, p in enumerate(to_merge):
            mp4, audio, at, mt, diff, sub, st = p
            if st == 'ass':
                to_merge[i] = (mp4, audio, at, mt, diff, None, None)

    print(f"\n[信息] 准备合成 {len(to_merge)} 个视频...")
    print("-" * 60)

    success_count = 0
    fail_count = 0

    for idx, (mp4_path, audio_path, audio_type, match_type, diff, sub_path, sub_type) in enumerate(to_merge, 1):
        base = get_base_name(mp4_path)
        output_name = f"{base}_merged.mp4"
        output_path = os.path.join(output_dir, output_name)

        counter = 1
        orig = output_path
        while os.path.exists(output_path):
            name, ext = os.path.splitext(orig)
            output_path = f"{name}_{counter}{ext}"
            counter += 1

        tag = "[完美]" if match_type == "perfect" else "[时长]" if match_type == "duration" else "[强制]"
        audio_tag = "[m4a]" if audio_type == 'm4a' else "[weba→AAC]"
        sub_tag = ""
        if sub_type == 'srt':
            sub_tag = " [SRT]"
        elif sub_type == 'ass':
            sub_tag = " [ASS硬]" if ass_mode == 'burn' else " [ASS→MKV]" if ass_mode == 'mkv' else ""

        print(f"\n{tag}{audio_tag}{sub_tag} [{idx}/{len(to_merge)}] {base}")
        print(f"     视频: {os.path.basename(mp4_path)}")
        print(f"     音频: {os.path.basename(audio_path)}")
        if sub_path:
            print(f"     字幕: {os.path.basename(sub_path)}")

        ok, final_output = merge_pair(mp4_path, audio_path, audio_type, sub_path, sub_type,
                                      output_path, ffmpeg_path, ass_mode)
        if ok and os.path.exists(final_output):
            out_size = os.path.getsize(final_output)
            print(f"     [OK] 成功 ({format_size(out_size)})")
            success_count += 1
        else:
            print(f"     [X] 失败")
            fail_count += 1

    print("\n" + "=" * 60)
    print("  合成完成")
    print("=" * 60)
    print(f"  成功: {success_count}")
    print(f"  失败: {fail_count}")
    print(f"  输出目录: {output_dir}")
    print("=" * 60)
# =============================




__all__ = [
    "MERGE_VIDEO_EXTS",
    "CALIB_MEDIA_EXTS",
    "get_duration",
    "probe_audio_codec",
    "calib_media_for_srt",
    "scan_media",
    "get_base_name",
    "find_subtitle",
    "smart_pair",
    "merge_pair",
    "merge_mode",
    "_DUR_CACHE",
]
