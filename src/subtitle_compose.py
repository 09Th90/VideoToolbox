# -*- coding: utf-8 -*-
# @version 1.15.7
"""字幕编辑页的「内嵌字幕」：把当前字幕挂成视频的一条独立轨道，不重新编码。

（原引擎工作台「字幕视频合成」那一段搬到编辑页，并按需求收窄为"只内嵌"。）

为什么搬到编辑页
----------------
引擎工作台原本自带「字幕视频合成」分段，流程是「转录 → 翻译 → 合成」。
但真正要合成的时候，字幕往往**正躺在字幕编辑页里、甚至还没保存**；先去别的
页面导出、再拖回引擎、再选一遍视频，纯属绕路。所以把那一段摘掉，能力并到
这里——视频就是当前打开的那个，字幕就是当前正在编辑的那份（含未保存改动）。

为什么只做内嵌、不做硬烧录
--------------------------
硬烧录（libass 把字幕画进画面）必须逐帧重编码视频。实测踩到两个坑：
1. 又慢又大——长片动辄十几分钟，体积还翻倍；
2. `tools/ffmpeg.exe` 在硬烧录那套参数下**会卡死**：只写出 48 字节的 ftyp
   头就停住，直到超时。已排除的变量：`-t 3` 的小片段正常，纯
   `-c:v libx264 -c:a aac` 全时长也正常，但把日志级别、进度输出、`-vf ass`、
   `-map` 逐项拿掉都照样卡——至今没锁定单一诱因（记录在案，别再试）。
内嵌字幕（`-c:v copy -c:a copy -c:s mov_text`）只把字幕当**独立轨道**塞进
容器，音视频字节级原样搬过去，几秒就完；音视频时间轴与源文件**完全一致**，
字幕按自己的时间轴对上即可——正是这里要的效果。

命令拼装、进度解析、对齐体检都是纯函数（不 import 本项目其它模块），便于
`_selftest_*` 直接单测；只有对话框才碰 Qt。
"""
import os
import re
import subprocess
import sys
import tempfile
import threading

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import (QDialog, QFileDialog, QGridLayout, QHBoxLayout,
                             QLabel, QLineEdit, QVBoxLayout)
from qfluentwidgets import (InfoBar, InfoBarPosition, PrimaryPushButton,
                            ProgressBar, PushButton, RadioButton, isDarkTheme)

import subtitle_editor_core as secore

#: 子进程不弹黑框（打包成 windowed exe 后尤其重要）
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0

# =============================================================
# 0. 纯函数：命令行拼装 / 进度解析 / 对齐体检（可单测）
# =============================================================
#: 容器 -> 字幕编码。mp4 系只吃 mov_text；mkv 用原生 srt，兼容性最好
SOFT_CODECS = {
    ".mp4": "mov_text",
    ".m4v": "mov_text",
    ".mov": "mov_text",
    ".mkv": "srt",
}

OUTPUT_FILTER = ("MP4 视频 (*.mp4);;Matroska 字幕友好 (*.mkv);;所有文件 (*.*)")

VIDEO_FILTER = ("视频文件 (*.mp4 *.mkv *.mov *.avi *.flv *.ts *.webm);;"
                "所有文件 (*.*)")
SUB_FILTER = "字幕文件 (*.srt *.ass);;所有文件 (*.*)"


def build_command(ffmpeg, video, subtitle, output):
    """拼出「内嵌字幕」的 ffmpeg 参数表（list，不经过 shell）。

    返回 `(argv, 错误信息)`；错误信息非空时应直接提示用户，不要启动进程。
    音视频一律 `copy`、只多一条字幕轨——所以这个操作**不重新编码**。
    """
    for label, p in (("视频", video), ("字幕", subtitle)):
        if not p or not os.path.isfile(p):
            return None, "%s文件不存在：%s" % (label, p or "(空)")
    if not output:
        return None, "没有指定输出文件"

    ext = os.path.splitext(output)[1].lower()
    codec = SOFT_CODECS.get(ext)
    if codec is None:
        return None, "只支持 .mp4 / .mkv 输出（当前 %s）" % (ext or "无扩展名")

    out_dir = os.path.dirname(os.path.abspath(output))
    if out_dir and not os.path.isdir(out_dir):
        return None, "输出目录不存在：%s" % out_dir

    # `-y` 是无条件覆盖，别让用户一不小心把原片写没了
    if os.path.abspath(output) == os.path.abspath(video):
        return None, "输出文件不能就是原视频本身，换个文件名"

    return [
        ffmpeg, "-y", "-hide_banner",
        # GUI 调 ffmpeg 的常规护身符：免得它去读一个永远不产出数据的 stdin 句柄
        "-nostdin",
        "-i", video,
        # 进度走 stdout；`-progress` 的字段名骗人，解析见 parse_progress
        "-progress", "pipe:1", "-nostats",
        "-i", subtitle,
        "-map", "0:v:0", "-map", "0:a?", "-map", "1:0",
        "-c:v", "copy", "-c:a", "copy", "-c:s", codec,
        "-metadata:s:s:0", "language=chi",
        output,
    ], ""


_KEY_RE = re.compile(r"^([A-Za-z_]+)=(.*)$")


def parse_progress(line, total_ms):
    """解析一行 `-progress` 输出；返回 0-100 的整数，或 None（不是进度行）。

    注意：`out_time_ms` 的**单位其实是微秒**——ffmpeg 这个字段名是历史遗留的
    坑，按毫秒算会得到 1000 倍的速度。上限压到 99，100 只由 `progress=end`
    给出。内嵌只用 copy，通常几秒结束，进度可能直接跳到 100，属正常。
    """
    m = _KEY_RE.match((line or "").strip())
    if not m:
        return None
    key, val = m.group(1), m.group(2).strip()
    if key == "progress":
        return 100 if val == "end" else None
    if key in ("out_time_ms", "out_time_us"):
        if not total_ms:
            return None
        try:
            us = int(float(val))
        except (TypeError, ValueError):
            return None
        if us < 0:
            us = 0
        return min(99, int(us / 1000.0 * 100.0 / float(total_ms)))
    return None


def default_output(video):
    """默认输出名：`<视频名>_内嵌字幕.mp4`。"""
    stem = os.path.splitext(video or "output")[0]
    return stem + "_内嵌字幕.mp4"


def check_alignment(cues, video_ms):
    """字幕时间轴 vs 视频时长的体检；返回一句提示，没问题则返回空串。

    内嵌字幕靠时间轴挂载，超出视频时长的那部分播放时根本不会出现。提前说
    一声，免得用户以为字幕没生效。
    """
    if not cues or not video_ms:
        return ""
    last_end = max((int(c.end) for c in cues), default=0)
    if last_end <= int(video_ms) + 1000:
        return ""
    return ("字幕末条结束于 %s，而视频只有 %s，超出部分播放时不会显示"
            % (secore.ms_to_clock(last_end),
               secore.ms_to_clock(int(video_ms))))


# =============================================================
# 1. 对话框
# =============================================================
class ComposeDialog(QDialog):
    """「内嵌字幕」对话框。模态；跑合成时禁用输入，可取消。

    ⚠️ 信号名不能叫 `done` / `progress` 之类与 Qt 基类重名的东西：
    `QDialog` 自带 `done(int)`（accept/reject 内部都走它），一旦在子类里用
    `done = pyqtSignal(...)` 盖掉同名成员，sip 的元对象就和 C++ 侧错位，
    表现为**关闭对话框时进程直接崩掉**（Windows 上 exit code 0xC0000409，
    Python 层看不到任何 traceback）。这个坑踩过一次，别再改回去。
    """

    progress_changed = pyqtSignal(int)     # 0-100
    compose_done = pyqtSignal(bool, str)   # (成功?, 末尾日志/错误)

    def __init__(self, page, parent=None):
        super().__init__(parent or page.window())
        self.page = page
        self._proc = None
        self._thread = None
        self._sub_tmp = ""
        self._last_auto = ""       # 上一轮自动写的输出名，用来判断用户有没有手改
        self.setWindowTitle("内嵌字幕")
        self.setModal(True)
        self.setMinimumWidth(680)
        if isDarkTheme():
            self.setStyleSheet("QDialog{background:#202020;}")
        else:
            self.setStyleSheet("QDialog{background:#f7f7f7;}")
        self._build()
        self.progress_changed.connect(self._on_progress)
        self.compose_done.connect(self._on_done)

    # ---------- 构建 ----------
    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(10)

        head = QLabel("把字幕内嵌进视频", self)
        f = head.font()
        f.setBold(True)
        f.setPointSize(f.pointSize() + 2)
        head.setFont(f)
        lay.addWidget(head)

        tip = QLabel("视频与音频原样复制，不重新编码；只多出一条字幕轨道，"
                     "时间轴与源文件完全一致。", self)
        tip.setWordWrap(True)
        tip.setStyleSheet("color:#8a8a8a;")
        lay.addWidget(tip)

        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)

        # 视频
        grid.addWidget(QLabel("视频", self), 0, 0)
        self.ed_video = QLineEdit(self)
        self.ed_video.setText(self.page.video_path or "")
        self.btn_video = PushButton("浏览", self)
        grid.addWidget(self.ed_video, 0, 1)
        grid.addWidget(self.btn_video, 0, 2)

        # 字幕来源
        self.rb_current = RadioButton("用编辑页当前字幕（含未保存改动）", self)
        self.rb_file = RadioButton("用指定字幕文件", self)
        self.rb_current.setChecked(True)
        grid.addWidget(self.rb_current, 1, 1)

        self.ed_sub = QLineEdit(self)
        self.ed_sub.setEnabled(False)
        self.btn_sub = PushButton("浏览", self)
        self.btn_sub.setEnabled(False)
        grid.addWidget(self.ed_sub, 2, 1)
        grid.addWidget(self.btn_sub, 2, 2)
        grid.addWidget(self.rb_file, 2, 0)

        # 输出
        grid.addWidget(QLabel("输出", self), 3, 0)
        self.ed_out = QLineEdit(self)
        self.btn_out = PushButton("浏览", self)
        grid.addWidget(self.ed_out, 3, 1)
        grid.addWidget(self.btn_out, 3, 2)

        grid.setColumnStretch(1, 1)
        lay.addLayout(grid)

        # 对齐体检：字幕比视频长时提前说一声
        self.lbl_align = QLabel("", self)
        self.lbl_align.setWordWrap(True)
        self.lbl_align.setStyleSheet("color:#c07a1a;")
        self.lbl_align.setVisible(False)
        lay.addWidget(self.lbl_align)

        self.bar = ProgressBar(self)
        self.bar.setValue(0)
        lay.addWidget(self.bar)

        self.lbl_state = QLabel("就绪。只搬轨道、不重编码，通常几秒完成。", self)
        self.lbl_state.setWordWrap(True)
        self.lbl_state.setStyleSheet("color:#8a8a8a;")
        lay.addWidget(self.lbl_state)

        brow = QHBoxLayout()
        brow.addStretch(1)
        self.btn_open = PushButton("打开输出目录", self)
        self.btn_cancel = PushButton("取消", self)
        self.btn_go = PrimaryPushButton("开始内嵌", self)
        for b in (self.btn_open, self.btn_cancel, self.btn_go):
            brow.addWidget(b)
        lay.addLayout(brow)

        # ---------- 信号 ----------
        self.btn_video.clicked.connect(
            lambda: self._pick(self.ed_video, "选择视频", VIDEO_FILTER))
        self.btn_sub.clicked.connect(
            lambda: self._pick(self.ed_sub, "选择字幕", SUB_FILTER))
        self.btn_out.clicked.connect(self._pick_output)
        self.rb_current.toggled.connect(self._on_source_toggled)
        self.btn_open.clicked.connect(self._open_out_dir)
        self.btn_cancel.clicked.connect(self._on_cancel)
        self.btn_go.clicked.connect(self._start)
        self.ed_video.textChanged.connect(self._refresh_output)

        self._refresh_output()
        self._refresh_align()

    # ---------- 小交互 ----------
    def _pick(self, edit, title, filt):
        start = os.path.dirname(edit.text().strip()) if edit.text().strip() else ""
        path, _ = QFileDialog.getOpenFileName(self, title, start, filt)
        if path:
            edit.setText(path)

    def _pick_output(self):
        start = self.ed_out.text().strip() or ""
        path, _ = QFileDialog.getSaveFileName(self, "选择输出文件", start,
                                              OUTPUT_FILTER)
        if path:
            self.ed_out.setText(path)

    def _on_source_toggled(self, use_current):
        self.ed_sub.setEnabled(not use_current)
        self.btn_sub.setEnabled(not use_current)

    def _refresh_output(self):
        """跟随视频自动改输出名——但用户手动改过就不再覆盖。

        判断"改过"的办法是记住自己上一轮写的默认名：当前值跟它不一致，
        说明是用户敲的，得尊重。
        """
        video = self.ed_video.text().strip()
        old = self.ed_out.text().strip()
        if not old or old == self._last_auto:
            new = default_output(video)
            self._last_auto = new
            self.ed_out.setText(new)

    def _refresh_align(self):
        """字幕末条是否超出视频时长——提前提示，别让用户白等。"""
        msg = ""
        if self.rb_current.isChecked():
            try:
                cues = self.page.doc.cues
                total = int(self.page.player.duration_ms
                            or self.page.timeline.duration_ms or 0)
                msg = check_alignment(cues, total)
            except Exception:  # noqa: BLE001
                msg = ""
        self.lbl_align.setText(msg)
        self.lbl_align.setVisible(bool(msg))

    def _open_out_dir(self):
        d = os.path.dirname(os.path.abspath(self.ed_out.text().strip() or "."))
        try:
            if sys.platform == "win32":
                os.startfile(d)          # noqa: S606
            else:
                subprocess.Popen(["xdg-open", d])
        except Exception:  # noqa: BLE001
            pass

    # ---------- 合成 ----------
    def _prepare_subtitle(self):
        """按当前选择准备一份 ffmpeg 能直接读的字幕文件，返回路径。

        「用编辑页当前字幕」这一路会落到 `data/tmp` 下的临时文件：
        内存里的 cues 可能还没保存，不能拿磁盘上的旧文件凑数。
        """
        if not self.rb_current.isChecked():
            return self.ed_sub.text().strip()
        doc = self.page.doc
        if not doc.cues:
            return ""
        # tempfile 的根目录已被 engine 指到 `<程序目录>\data\tmp`，
        # 和播放器预览字幕同一个地方，不污染系统临时目录
        tmp_dir = os.path.join(tempfile.gettempdir(), "vt_compose")
        os.makedirs(tmp_dir, exist_ok=True)
        path = os.path.join(tmp_dir, "embed.srt")
        # 按时间轴排好再写，SRT 序号才跟时间轴一致
        cues = sorted(doc.cues, key=lambda c: (int(c.start), int(c.end)))
        text = secore.SubtitleDoc(cues=list(cues)).dump()
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        self._sub_tmp = path
        return path

    def _start(self):
        if self._thread is not None:
            return
        video = self.ed_video.text().strip()
        output = self.ed_out.text().strip()
        try:
            sub = self._prepare_subtitle()
        except OSError as e:
            self._say("准备字幕失败：%s" % e, True)
            return
        if not sub:
            self._say("没有可内嵌的字幕（编辑页是空的，也没指定字幕文件）", True)
            return

        try:
            ffmpeg, _probe = self.page._media_tools()
        except RuntimeError as e:
            self._say(str(e), True)
            return

        argv, err = build_command(ffmpeg, video, sub, output)
        if err:
            self._say(err, True)
            return

        total_ms = int((self.page.player.duration_ms
                        or self.page.timeline.duration_ms or 0))
        self._lock_ui(True)
        self.bar.setValue(0)
        self.lbl_state.setText("正在内嵌字幕…（只搬轨道，不重编码）")

        def work():
            self._run_ffmpeg(argv, total_ms)

        self._thread = threading.Thread(target=work, name="vt-compose",
                                        daemon=True)
        self._thread.start()

    def _run_ffmpeg(self, argv, total_ms):
        tail = []
        try:
            proc = subprocess.Popen(
                argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace",
                bufsize=1, creationflags=_NO_WINDOW)
        except OSError as e:
            self.compose_done.emit(False, "无法启动 ffmpeg：%s" % e)
            return
        self._proc = proc
        try:
            for raw in proc.stdout:
                line = raw.rstrip("\r\n")
                pct = parse_progress(line, total_ms)
                if pct is not None:
                    self.progress_changed.emit(pct)
                elif line.strip():
                    tail.append(line.strip())
                    if len(tail) > 30:
                        tail.pop(0)
            rc = proc.wait()
        except Exception as e:  # noqa: BLE001
            rc = -1
            tail.append("读取 ffmpeg 输出失败：%s" % e)
        finally:
            try:
                proc.stdout.close()
            except Exception:  # noqa: BLE001
                pass
            self._proc = None
        self.compose_done.emit(rc == 0, "\n".join(tail[-6:]))

    def _on_progress(self, pct):
        self.bar.setValue(max(0, min(100, int(pct))))

    def _on_done(self, ok, tail):
        self._thread = None
        self._lock_ui(False)
        self.bar.setValue(100 if ok else self.bar.value())
        out = self.ed_out.text().strip()
        if ok:
            self.lbl_state.setText("完成：" + out)
            self._info("ok", "字幕已内嵌", out, 6000)
        else:
            self.lbl_state.setText("失败。" + (tail or ""))
            self._info("err", "内嵌失败", (tail or "ffmpeg 退出异常")[-400:], 9000)

    def _on_cancel(self):
        if self._thread is not None:
            # 合成中：「取消」变成「中止」
            if self._proc is not None:
                try:
                    self._proc.kill()
                except Exception:  # noqa: BLE001
                    pass
            self.lbl_state.setText("已中止。")
            return
        self.reject()

    def _lock_ui(self, busy):
        for w in (self.ed_video, self.ed_out, self.btn_video, self.btn_out,
                  self.rb_current, self.rb_file):
            w.setEnabled(not busy)
        if busy:
            self.btn_sub.setEnabled(False)
            self.ed_sub.setEnabled(False)
        else:
            self._on_source_toggled(self.rb_current.isChecked())
        self.btn_go.setEnabled(not busy)
        self.btn_cancel.setText("中止" if busy else "取消")
        self.btn_open.setEnabled(not busy)

    def _say(self, text, bad=False):
        self.lbl_state.setText(text)
        if bad:
            self._info("err", "无法开始内嵌", text, 6000)

    def _info(self, kind, title, text, duration=4000):
        try:
            fn = {"ok": InfoBar.success, "err": InfoBar.error}.get(kind,
                                                                   InfoBar.info)
            fn(title, text, duration=duration, position=InfoBarPosition.TOP,
               parent=self)
        except Exception:  # noqa: BLE001
            pass

    def closeEvent(self, ev):
        if self._proc is not None:
            try:
                self._proc.kill()
            except Exception:  # noqa: BLE001
                pass
        super().closeEvent(ev)
