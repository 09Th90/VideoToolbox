#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# @version 1.18.3
"""音画合并「手动合并」自检：引擎侧编码探测 + 拖入合成，界面侧子页结构。

覆盖 v1.18.0 新增能力：
  · engine.probe_audio_codec  —— 实测音频编码（决定 copy / 转 AAC）
  · engine.merge_pair(reencode_video=) —— 视频 copy 失败后的重编码回退
  · MergePage 二级分段「自动配对 / 手动合并」、三个拖放槽、页级拖放分派
  · 配对表鼠标选中语义 —— 单选/多选/全选/清空；选中后「开始合成」只合选中，
    未选中仍合全部；重新扫描后旧选中必须失效
  · v1.18.0 自动配对多容器 —— scan_media 收 mp4/mkv/webm…（此前只 glob
    `*.mp4`，同名 webm + m4a 恒配不出对）；并固化「哪些编码能 copy、
    哪些必须重编码」，防止有人再照旧注释以为 vp9/av1 不能进 mp4

不联网。用法：tools/python/python.exe scripts/dev/_selftest_merge_manual.py
"""
import os
import sys
import tempfile

_SRC = os.path.join(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))), "src")
sys.path.insert(0, _SRC)
os.environ["VT_NO_PIPELINE"] = "1"
import video_toolbox as engine  # noqa: E402

os.environ.setdefault(
    "QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault(
    "QT_QPA_PLATFORM_PLUGIN_PATH",
    os.path.join(engine.EMBEDDED_SITE_PACKAGES, "PyQt5", "Qt5", "plugins"))

FAILS = []


def check(name, cond, extra=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}"
          f"{(' -> ' + str(extra)) if extra else ''}")
    if not cond:
        FAILS.append(name)


def _mk_media(tmp, ffmpeg):
    """生成测试素材：h264+aac 的 mp4、wav（pcm）、m4a（aac）。"""
    mp4 = os.path.join(tmp, "clip.mp4")
    engine.run_process([
        ffmpeg, "-y", "-f", "lavfi", "-i", "testsrc=size=160x120:rate=10:duration=2",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
        "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest", mp4,
    ], capture_output=True)
    wav = os.path.join(tmp, "voice.wav")
    engine.run_process([ffmpeg, "-y", "-f", "lavfi", "-i",
                        "sine=frequency=660:duration=2", wav], capture_output=True)
    m4a = os.path.join(tmp, "voice.m4a")
    engine.run_process([ffmpeg, "-y", "-f", "lavfi", "-i",
                        "sine=frequency=880:duration=2", "-c:a", "aac", m4a],
                       capture_output=True)
    return mp4, wav, m4a


def _has_audio(path, ffprobe):
    cmd = [ffprobe, "-v", "error", "-select_streams", "a:0",
           "-show_entries", "stream=codec_name", "-of",
           "default=noprint_wrappers=1:nokey=1", path]
    r = engine.run_process(cmd, capture_output=True)
    return bool(engine.decode_bytes_any(r.stdout).strip())


def multicontainer_cases():
    """v1.18.0：自动配对支持多容器（此前 scan_media 只 glob `*.mp4`）。

    同时固化"哪些编码能 copy 进 mp4、哪些必须重编码"——旧注释写着
    「vp9/av1 装不进 mp4」，实测是错的（真正失败的是 vp8）。这类结论
    依赖具体 ffmpeg 构建，必须由自检守着，改环境后能立刻看到差异。
    """
    ffmpeg, ffprobe = engine.ensure_ffmpeg()
    with tempfile.TemporaryDirectory(dir=engine.DATA_DIR + os.sep + "tmp") as tmp:
        # 三种容器的同名三连：webm(VP9) / mp4(H.264) / mkv(VP9)
        specs = (("EP01", "libvpx-vp9", ".webm"),
                 ("EP02", "libx264", ".mp4"),
                 ("EP03", "libvpx-vp9", ".mkv"))
        for name, venc, ext in specs:
            vp = os.path.join(tmp, name + ext)
            ap = os.path.join(tmp, name + ".m4a")
            engine.run_process([
                ffmpeg, "-y", "-f", "lavfi", "-i",
                "testsrc=size=160x120:rate=10:duration=2",
                "-c:v", venc, "-preset", "ultrafast", "-b:v", "200k",
                "-an", vp], capture_output=True)
            engine.run_process([
                ffmpeg, "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
                "-c:a", "aac", ap], capture_output=True)
            with open(os.path.join(tmp, name + ".srt"), "w", encoding="utf-8") as fh:
                fh.write("1\n00:00:00,000 --> 00:00:01,000\nhi\n")

        check("测试素材就位（3 容器 × 各自 m4a/srt）",
              all(os.path.exists(os.path.join(tmp, n + x))
                  for n, _, x in specs))

        videos, m4as, webas, srts, asss = engine.scan_media(tmp)
        got_exts = {os.path.splitext(v)[1].lower() for v in videos}
        check("scan_media 认到三种视频容器",
              got_exts == {".webm", ".mp4", ".mkv"}, got_exts)
        check("MERGE_VIDEO_EXTS 含 webm / mkv",
              {".webm", ".mkv"} <= set(engine.MERGE_VIDEO_EXTS),
              engine.MERGE_VIDEO_EXTS)

        # 显式传入旧口径仍能只扫 mp4（流水线按后缀筛任务的场景依赖这点）
        only_mp4 = engine.scan_media(tmp, video_exts=(".mp4",))[0]
        check("video_exts=(.mp4,) 时退回旧口径（只扫 mp4）",
              len(only_mp4) == 1 and only_mp4[0].endswith("EP02.mp4"),
              [os.path.basename(v) for v in only_mp4])

        pairs, rem_v, rem_a, rem_w = engine.smart_pair(
            videos, m4as, webas, srts, asss, ffprobe)
        check("三种容器全部配出对（此前 webm 恒配不出）", len(pairs) == 3, len(pairs))
        by_video = {os.path.basename(p[0]): p for p in pairs}
        check("EP01.webm 配上了同名 m4a",
              "EP01.webm" in by_video and by_video["EP01.webm"][1].endswith("EP01.m4a"),
              sorted(by_video))
        check("配对项都关联到同名 srt",
              all(p[5] and os.path.basename(p[5]).startswith(
                  os.path.splitext(os.path.basename(p[0]))[0]) for p in pairs),
              [(os.path.basename(p[0]), p[5]) for p in pairs])

        # —— 端到端真合并：webm(VP9) 输入 → mp4 产物 ——
        out = os.path.join(tmp, "out")
        os.makedirs(out, exist_ok=True)
        ok, f1 = engine.merge_pair(os.path.join(tmp, "EP01.webm"),
                                   os.path.join(tmp, "EP01.m4a"), "m4a",
                                   None, None, os.path.join(out, "EP01.mp4"),
                                   ffmpeg)
        check("webm(VP9) 无字幕合成成功且直接 copy（无需重编码）",
              ok and os.path.exists(f1), f1)
        if ok and os.path.exists(f1):
            vc = engine.decode_bytes_any(engine.run_process(
                [ffprobe, "-v", "error", "-select_streams", "v:0",
                 "-show_entries", "stream=codec_name", "-of",
                 "default=noprint_wrappers=1:nokey=1", f1],
                capture_output=True).stdout).strip()
            dec = engine.run_process(
                [ffmpeg, "-v", "error", "-i", f1, "-f", "null", "-"],
                capture_output=True).returncode
            check("产物视频流仍是 vp9（无损 copy，不是转码）", vc == "vp9", vc)
            check("产物能被完整解码", dec == 0, dec)

        # —— 固化"只有 vp8 需要重编码"这个实测结论 ——
        vp8 = os.path.join(tmp, "V8.webm")
        engine.run_process([
            ffmpeg, "-y", "-f", "lavfi", "-i",
            "testsrc=size=160x120:rate=10:duration=2",
            "-c:v", "libvpx", "-b:v", "150k", "-an", vp8], capture_output=True)
        o8 = os.path.join(out, "V8.mp4")
        ok8, _ = engine.merge_pair(vp8, os.path.join(tmp, "EP02.m4a"), "m4a",
                                   None, None, o8, ffmpeg)
        check("vp8 首次 copy 确实失败（重试机制有存在意义）", not ok8, ok8)
        ok8b, f8 = engine.merge_pair(vp8, os.path.join(tmp, "EP02.m4a"), "m4a",
                                     None, None, o8, ffmpeg, reencode_video=True)
        vc8 = engine.decode_bytes_any(engine.run_process(
            [ffprobe, "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=codec_name", "-of",
             "default=noprint_wrappers=1:nokey=1", f8],
            capture_output=True).stdout).strip() if ok8b else ""
        check("vp8 靠 reencode_video=True 救回 h264", ok8b and vc8 == "h264",
              (ok8b, vc8))


def engine_cases():
    ffmpeg, ffprobe = engine.ensure_ffmpeg()
    with tempfile.TemporaryDirectory() as tmp:
        mp4, wav, m4a = _mk_media(tmp, ffmpeg)

        check("probe_audio_codec 认得出 AAC",
              engine.probe_audio_codec(m4a, ffprobe) == "aac",
              engine.probe_audio_codec(m4a, ffprobe))
        check("probe_audio_codec 认得出 WAV(PCM)",
              engine.probe_audio_codec(wav, ffprobe).startswith("pcm"),
              engine.probe_audio_codec(wav, ffprobe))
        check("probe_audio_codec 对不存在的文件返回空串",
              engine.probe_audio_codec(os.path.join(tmp, "nope.aac"), ffprobe) == "")

        # 手动合并主路径：AAC → copy；PCM(wav) → 转 AAC（audio_type='weba'）
        out1 = os.path.join(tmp, "aac_copy.mp4")
        ok1, f1 = engine.merge_pair(mp4, m4a, "m4a", None, None, out1, ffmpeg)
        check("手动合并：AAC 音频直封成功且有音轨",
              ok1 and os.path.exists(f1) and _has_audio(f1, ffprobe))

        out2 = os.path.join(tmp, "wav_transcode.mp4")
        ok2, f2 = engine.merge_pair(mp4, wav, "weba", None, None, out2, ffmpeg)
        check("手动合并：非 AAC 音频转码成功且有音轨",
              ok2 and os.path.exists(f2) and _has_audio(f2, ffprobe))

        # 重编码回退：reencode_video=True 时视频必须走 libx264
        out3 = os.path.join(tmp, "reencode.mp4")
        ok3, f3 = engine.merge_pair(mp4, m4a, "m4a", None, None, out3, ffmpeg,
                                    reencode_video=True)
        cmd = [ffprobe, "-v", "error", "-select_streams", "v:0",
               "-show_entries", "stream=codec_name", "-of",
               "default=noprint_wrappers=1:nokey=1", f3]
        vcodec = engine.decode_bytes_any(
            engine.run_process(cmd, capture_output=True).stdout).strip()
        check("merge_pair(reencode_video=True) 输出 h264",
              ok3 and vcodec == "h264", vcodec)

        # SRT 软字幕路径仍走 video_codec 变量（不能因重构而漏改）
        srt = os.path.join(tmp, "clip.srt")
        with open(srt, "w", encoding="utf-8") as fh:
            fh.write("1\n00:00:00,000 --> 00:00:01,000\nhi\n")
        out4 = os.path.join(tmp, "with_srt.mp4")
        ok4, f4 = engine.merge_pair(mp4, m4a, "m4a", srt, "srt", out4, ffmpeg)
        check("SRT 软字幕路径仍可用", ok4 and os.path.exists(f4))


def _sel_cases(mp, app):
    """配对表选中语义：单选 / 多选 / 全选 / 清空 + 「开始合成」取哪些行。"""
    from PyQt5.QtCore import Qt, QItemSelectionModel, QVariant
    from PyQt5.QtWidgets import QTableWidgetItem

    def _fake_pairs(n):
        """n 组假配对；match_type 交替覆盖 perfect / name_only 两条过滤分支。"""
        out = []
        for i in range(n):
            mt = "perfect" if i % 2 == 0 else "name_only"
            out.append((f"v{i}.mp4", f"v{i}.m4a", "m4a", mt, 0.05, None, None))
        return out

    def _feed(n=4):
        """绕过扫描线程，直接把 n 组假配对灌进表格（走 on_scan_done 的填表逻辑）。"""
        pairs = _fake_pairs(n)
        mp.on_scan_done(pairs, ([], [], []),
                        (n, n, 0, 0, 0), None)
        return pairs

    def _names():
        """当前选中状态下「开始合成」会取到的 pair 文件名列表。

        走的是页面上的纯函数 merge_targets()，不 patch 线程/弹窗——
        monkeypatch threading.Thread 在这里反而更脆（起线程成功与否
        依赖时序，断言会偶发）。合成逻辑本身由 merge_targets 单点负责。
        """
        return [os.path.basename(p[0]) for p in mp.merge_targets()]

    check("配对表允许多选（ExtendedSelection）",
          mp.table.selectionMode() == mp.table.ExtendedSelection,
          mp.table.selectionMode())
    check("配对表按整行选中", mp.table.selectionBehavior()
          == mp.table.SelectRows, mp.table.selectionBehavior())

    pairs = _feed(4)
    check("灌入 4 组配对", mp.table.rowCount() == 4 and len(mp.pairs) == 4,
          mp.table.rowCount())
    check("初始未选中 → 提示为合成全部",
          "未选中" in mp.sel_info.text(), mp.sel_info.text())

    # —— 单选 ——
    mp.table.selectRow(1)
    check("单击行 = 单选该行", mp.selected_rows() == [1], mp.selected_rows())
    check("选中后提示切到「只合成选中项」",
          "只合成选中项" in mp.sel_info.text(), mp.sel_info.text())
    check("单选后「开始合成」只取这 1 组", _names() == ["v1.mp4"], _names())

    # —— 多选（Ctrl：逐行加选）——
    sm = mp.table.selectionModel()
    sm.select(mp.table.model().index(3, 0),
              QItemSelectionModel.Select | QItemSelectionModel.Rows)
    check("Ctrl 加选成多选", mp.selected_rows() == [1, 3], mp.selected_rows())
    check("多选后「开始合成」只取这 2 组",
          _names() == ["v1.mp4", "v3.mp4"], _names())

    # —— 显式选中时不再按 match_type 二次过滤 ——
    # 选中的第 1 行是 name_only：用户点了就是要合，不该被静默跳过
    mp.table.clearSelection()
    mp.table.selectRow(1)
    check("选中「仅同名」行也照合（显式选择优先于匹配类型）",
          _names() == ["v1.mp4"], _names())

    # —— 全选 ——
    mp.sel_all_btn.click()
    check("「全选」选中全部行", mp.selected_rows() == [0, 1, 2, 3],
          mp.selected_rows())
    check("全选后合成范围 = 全部 4 组（含仅同名）",
          len(_names()) == 4, _names())

    # —— 清空 → 回到「未选中 = 按匹配类型合全部」——
    mp.sel_clear_btn.click()
    check("「清除选择」回到未选中", mp.selected_rows() == [],
          mp.selected_rows())
    # 未选中 + force 关闭：只合 perfect（v0/v2），name_only（v1/v3）被过滤
    check("未选中时按匹配类型筛（name_only 被过滤）",
          _names() == ["v0.mp4", "v2.mp4"], _names())
    mp.force_switch.setChecked(True)
    check("未选中 + 强制合成 → 全部 4 组", len(_names()) == 4, _names())
    mp.force_switch.setChecked(False)

    # —— start_merge 真的按选中起线程，且只把选中的交给 worker ——
    import threading as _th
    import video_toolbox_qt as vtq
    seen = {}
    orig_thread, orig_warn = _th.Thread, vtq.InfoBar.warning

    class _FakeThread:
        def __init__(self, target=None, args=(), **kw):
            seen["args"] = args

        def start(self):
            pass

    mp.table.clearSelection()
    mp.table.selectRow(2)
    _th.Thread = _FakeThread
    vtq.InfoBar.warning = staticmethod(lambda *a, **k: None)
    try:
        mp.start_merge()
    finally:
        _th.Thread = orig_thread
        vtq.InfoBar.warning = orig_warn
        mp.set_busy(False)
    check("start_merge 只把选中项交给 worker",
          [os.path.basename(p[0]) for p in (seen.get("args") or [[]])[0]]
          == ["v2.mp4"],
          [os.path.basename(p[0]) for p in (seen.get("args") or [[]])[0]])

    # —— 选中底色真的写进了 BackgroundRole，且取消后清干净 ——
    # delegate.paint 里 `if index.data(Qt.BackgroundRole)` 一旦为真，
    # 就跳过自己的隔行/hover 底色 → 残留会让取消选中的行变成一块空白。
    mp.table.clearSelection()
    mp.table.selectRow(2)
    picked = mp.table.item(2, 0).data(Qt.BackgroundRole)
    check("选中行铺了主题色底", picked is not None and bool(picked), picked)
    mp.table.clearSelection()
    gone = mp.table.item(2, 0).data(Qt.BackgroundRole)
    check("取消选中后 BackgroundRole 清成 invalid（隔行/hover 恢复）",
          not bool(gone), repr(gone))

    # —— 真实鼠标点击（用户实际的操作路径，与 selectRow 走的不是同一条路）——
    # TableBase.mousePressEvent 对左键是放行给 QTableView 的，鼠标点击选择
    # 与 selectRow 走的是两套入口，必须各自验一遍，别只测后者。
    from PyQt5.QtTest import QTest
    from PyQt5.QtCore import Qt as _Qt

    def _click_row(r, mod=_Qt.NoModifier, clear=True):
        if clear:
            mp.table.clearSelection()
        vp = mp.table.viewport()
        rect = mp.table.visualItemRect(mp.table.item(r, 0))
        QTest.mouseClick(vp, _Qt.LeftButton, mod, rect.center())

    _feed(4)
    mp.table.resize(760, 240)
    mp.table.show()
    app.processEvents()
    _click_row(2)
    check("鼠标单击行 = 单选该行", mp.selected_rows() == [2], mp.selected_rows())
    check("鼠标单击后合成范围就是那一行",
          [os.path.basename(p[0]) for p in mp.merge_targets()] == ["v2.mp4"],
          [os.path.basename(p[0]) for p in mp.merge_targets()])
    # Ctrl+单击追加（不清空已有选中，模拟连续 Ctrl 累加）
    _click_row(0, _Qt.ControlModifier, clear=False)
    _click_row(1, _Qt.ControlModifier, clear=False)
    check("Ctrl 多次单击可累积多选",
          mp.selected_rows() == [0, 1, 2], mp.selected_rows())
    check("鼠标多选后合成范围 = 这 3 行",
          [os.path.basename(p[0]) for p in mp.merge_targets()]
          == ["v0.mp4", "v1.mp4", "v2.mp4"],
          [os.path.basename(p[0]) for p in mp.merge_targets()])
    # Ctrl 再次单击已选中的行 = 取消该行（Qt 的 ToggleCell 语义）
    _click_row(1, _Qt.ControlModifier, clear=False)
    check("Ctrl 再次单击可取消该行",
          mp.selected_rows() == [0, 2], mp.selected_rows())
    # 点表格空白处 → 清空选中 → 回到"全部"
    mp.table.clearSelection()
    check("取消选中后回到全部语义",
          mp.selected_rows() == [] and "未选中" in mp.sel_info.text(),
          mp.sel_info.text())

    # —— 忙碌期间锁住选择入口 ——
    mp.table.selectRow(0)
    mp.set_busy(True)
    check("忙碌时配对表与选择按钮被锁",
          (not mp.table.isEnabled()) and (not mp.sel_all_btn.isEnabled())
          and (not mp.sel_clear_btn.isEnabled()))
    mp.set_busy(False)
    check("空闲后恢复可选", mp.table.isEnabled())

    # —— 重新扫描必须清掉旧选中（否则旧行号指向新数据）——
    pairs = _feed(4)
    mp.table.selectRow(3)
    _feed(2)                      # 重新扫描，行数变 2
    check("重新扫描后旧选中已清空", mp.selected_rows() == [],
          mp.selected_rows())
    check("重新扫描后行号与 pairs 对齐",
          mp.table.rowCount() == len(mp.pairs) == 2,
          (mp.table.rowCount(), len(mp.pairs)))
    # 行内容与 pairs 顺序一致（选中→合成靠的就是这个映射）
    same = all(mp.table.item(r, 0).text()
               == os.path.basename(mp.pairs[r][0])
               for r in range(mp.table.rowCount()))
    check("表格行序与 pairs 一致（选中行号能直接映射回 pair）", same)

    mp.table.clearSelection()
    assert pairs is not None and QVariant is not None and QTableWidgetItem is not None


def gui_cases():
    from PyQt5.QtWidgets import QApplication
    from PyQt5.QtCore import QMimeData, QUrl, QPoint, Qt
    from PyQt5.QtGui import QDropEvent
    import video_toolbox_qt as vtq

    app = QApplication.instance() or QApplication(sys.argv)
    win = vtq.MainWindow([])
    check("主窗口可构造", win is not None)
    if win is None:
        return
    mp = win.merge_page
    check("音画合并页含二级分段「自动配对 / 手动合并」",
          list(mp.mode_seg.items) == ["auto", "manual"],
          list(mp.mode_seg.items))
    check("自动配对子页仍在（配对表 5 列）", mp.table.columnCount() == 5)
    check("手动合并子页三个拖放槽就位",
          all(hasattr(mp, a) for a in ("mv_video", "mv_audio", "mv_sub")))
    check("手动合并子页含独立的输出框与合成按钮",
          mp.mv_out_edit is not None and mp.mv_button is not None)

    print("-- 配对表选中语义 --")
    _sel_cases(mp, app)
    print("-- 拖放与端到端 --")

    # 页级拖放分派：分类正确
    v, a, s = mp._classify(["x/y.mp4", "x/y.m4a", "x/y.srt", "x/z.flac"])
    check("拖入分类：视频/音频/字幕各取第一个",
          v.endswith("y.mp4") and a.endswith("y.m4a") and s.endswith("y.srt"),
          (v, a, s))

    # 字幕归一：merge_pair 只认 srt / ass（ssa 同族）
    rs = mp._resolve_sub
    check("字幕归一：srt 保留", rs("a.srt", "burn") == ("a.srt", "srt"))
    check("字幕归一：ssa 视作 ass", rs("a.ssa", "burn") == ("a.ssa", "ass"))
    check("字幕归一：ass + 忽略 → 摘掉",
          rs("a.ass", "ignore") == (None, None))
    check("字幕归一：vtt 不支持 → 摘掉", rs("a.vtt", "burn") == (None, None))
    check("字幕归一：未选字幕 → 空", rs("", "burn") == (None, None))

    # 只有停在手动合并子页才接管拖放
    win.download_page.seg.setCurrentItem("merge")
    win.download_page.stack.setCurrentIndex(1)
    mp._switch_mode(0)
    check("自动配对自己不接管拖放", mp._drop_active() is False)
    mp._switch_mode(1)
    check("手动合并子页接管拖放", mp._drop_active() is True)
    win.download_page.seg.setCurrentItem("download")
    win.download_page.stack.setCurrentIndex(0)
    check("切回视频下载后不接管拖放", mp._drop_active() is False)

    # 真丢一个事件：槽位与页面都要能收
    win.download_page.seg.setCurrentItem("merge")
    win.download_page.stack.setCurrentIndex(1)
    mp._switch_mode(1)
    with tempfile.TemporaryDirectory() as tmp:
        vp = os.path.join(tmp, "a.mp4")
        ap = os.path.join(tmp, "a.m4a")
        sp = os.path.join(tmp, "a.srt")
        for p in (vp, ap, sp):
            open(p, "wb").close()
        md = QMimeData()
        md.setUrls([QUrl.fromLocalFile(vp), QUrl.fromLocalFile(ap),
                    QUrl.fromLocalFile(sp)])
        ev = QDropEvent(QPoint(5, 5), Qt.CopyAction, md, Qt.LeftButton,
                        Qt.NoModifier)
        mp.dropEvent(ev)
        check("拖入 mp4+m4a+srt：三个槽位自动归位",
              os.path.normpath(mp.mv_video.path()) == os.path.normpath(vp)
              and os.path.normpath(mp.mv_audio.path()) == os.path.normpath(ap)
              and os.path.normpath(mp.mv_sub.path()) == os.path.normpath(sp),
              (mp.mv_video.path(), mp.mv_audio.path(), mp.mv_sub.path()))

        # 槽位自身也要能收（只收匹配后缀）
        mp.mv_video.set_path("")
        check("槽位 matches 按后缀判定",
              mp.mv_video.matches(vp) and not mp.mv_video.matches(ap))

        # 主窗口兜底：拖到窗口边缘（事件冒泡到全局分派）也要就地归位，不跳字幕编辑
        win.switchTo(win.download_page)
        mp.mv_video.set_path("")
        mp.mv_audio.set_path("")
        mp.mv_sub.set_path("")
        win._handle_dropped_files([vp, ap])
        check("边缘拖放兜底：归位到手动合并槽且不跳「字幕编辑」",
              os.path.normpath(mp.mv_video.path()) == os.path.normpath(vp)
              and os.path.normpath(mp.mv_audio.path()) == os.path.normpath(ap)
              and win.stackedWidget.currentWidget() is not win.subtitle_edit_page,
              (mp.mv_video.path(), mp.mv_audio.path()))

        # —— 端到端：走完整 GUI 线程链（start_manual_merge → 队列 → 完成回调） ——
        import time
        ffmpeg, _ffprobe = engine.ensure_ffmpeg()
        real_mp4, real_wav, _ = _mk_media(tmp, ffmpeg)
        mp.mv_video.set_path(real_mp4)
        mp.mv_audio.set_path(real_wav)
        mp.mv_sub.set_path("")
        mp.mv_out_edit.setText(tmp)
        mp.mv_ass_combo.setCurrentIndex(0)
        orig_open = engine.open_folder
        engine.open_folder = lambda *a, **k: None      # 别真弹资源管理器
        try:
            mp.start_manual_merge()
            deadline = time.time() + 90
            while time.time() < deadline and mp.mv_busy:
                app.processEvents()
                win._pump()
                time.sleep(0.05)
        finally:
            engine.open_folder = orig_open
        outs = [f for f in os.listdir(tmp) if f.endswith("_merged.mp4")]
        check("端到端：GUI 手动合并产出文件且进度到 100",
              bool(outs) and mp.mv_progress.value() == 100, outs)

    win.close()


def main():
    print("== 引擎：音频编码探测 / 手动合成 ==")
    engine_cases()
    print("== 引擎：自动配对多容器（webm/mkv/mp4）==")
    multicontainer_cases()
    print("== 界面：手动合并子页与拖放 ==")
    gui_cases()
    print()
    if FAILS:
        print(f"FAILED ({len(FAILS)}): " + "; ".join(FAILS))
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
