# -*- coding: utf-8 -*-
# @version 1.14.0
"""字幕编辑页的媒体后端：libmpv 播放器封装 + ffmpeg 波形峰值提取。

与界面分离，便于单独调试（本模块只依赖 PyQt5 的信号机制，不建任何窗口）。

三条来之不易的约束（详见 tools/download_open_source_deps.py 的注释）：
  1. `import mpv` **之前**必须先把 tools/mpv 加进 PATH，否则 python-mpv
     找不到 libmpv-2.dll；
  2. 退出时必须 `terminate()`，否则打包后 onefile 的 `_MEI***` 临时目录删不掉；
  3. mpv 的 time-pos 是 float（实测 `25.400000000000002`），对外只暴露
     **int 毫秒**，避免调用方拿浮点做加减累积漂移。
"""
import hashlib
import json
import os
import subprocess
import sys
import tempfile

from PyQt5.QtCore import QObject, QTimer, pyqtSignal

# =============================================================
# 0. libmpv 延迟加载（失败不炸主程序，只在编辑页给出可读提示）
# =============================================================
_MPV_MODULE = None
_MPV_ERROR = ""


def load_mpv(mpv_dir):
    """导入 python-mpv。返回 (module, error)；失败时 module 为 None。

    必须做两件事，缺一不可：

      ① `mpv_dir` 加进 **PATH**：python-mpv 是先 `ctypes.util.find_library
         ('libmpv-2.dll')` 去 **PATH** 里找 dll（不是找自己所在目录），
         找不到才退化成「定位 mpv.py 同目录」。
      ② `mpv_dir` 插进 **sys.path**：文件级兜底。当绑定没随 exe 打包时，
         `import mpv` 会命中 `tools/mpv/mpv.py`，而它 `__file__` 同目录
         正好躺着 libmpv-2.dll，python-mpv 的第二重查找也能成立。

    v1.13.0 修的就是这里：此前只做了 ①，且 python-mpv 绑定既没装进运行时
    也没写进 spec 的 hiddenimports，于是打包后点「打开视频」直接
    `ModuleNotFoundError: No module named 'mpv'`。
    """
    global _MPV_MODULE, _MPV_ERROR
    if _MPV_MODULE is not None:
        return _MPV_MODULE, ""
    dll = os.path.join(mpv_dir, "libmpv-2.dll")
    if not os.path.isfile(dll):
        _MPV_ERROR = ("未找到 libmpv-2.dll（%s）。\n"
                      "请先运行：python tools\\download_open_source_deps.py --only mpv" % dll)
        return None, _MPV_ERROR
    # ① PATH —— 给 ctypes.util.find_library 用
    cur = os.environ.get("PATH", "")
    if os.path.normcase(mpv_dir) not in os.path.normcase(cur):
        os.environ["PATH"] = mpv_dir + os.pathsep + cur
    # ② sys.path —— 给 import 用（tools/mpv/mpv.py 文件级兜底）
    if mpv_dir not in sys.path:
        sys.path.insert(0, mpv_dir)
    try:
        import mpv as _mod
    except Exception as e:  # noqa: BLE001
        _MPV_ERROR = ("导入 python-mpv 失败：%s\n"
                      "（已把 %s 同时加进 PATH 与 sys.path；"
                      "若提示 No module named 'mpv'，说明绑定既没打进程序，"
                      "tools\\mpv\\ 下也缺 mpv.py）" % (e, mpv_dir))
        return None, _MPV_ERROR
    _MPV_MODULE = _mod
    _MPV_ERROR = ""
    return _MPV_MODULE, ""


# =============================================================
# 1. ffprobe / 波形峰值提取
# =============================================================
PEAKS_PER_SEC = 200          # 5ms 一个峰值点：一屏一秒约 200px 时够用
WAVE_CACHE_DIRNAME = "waveforms"


def probe_duration(ffprobe, path):
    """用 ffprobe 取媒体时长（秒，float）；失败返回 0.0。"""
    try:
        r = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, timeout=30)
        return float(r.stdout.decode("utf-8", "replace").strip() or 0.0)
    except Exception:  # noqa: BLE001
        return 0.0


def extract_peaks(ffmpeg, path, peaks_per_sec=PEAKS_PER_SEC, on_progress=None,
                  should_stop=None):
    """把音频解码成峰值序列（0-255 的 bytearray），全程流式，不吃内存。

    做法：让 ffmpeg 输出 16kHz 单声道 s16le 到管道，按 `16000/peaks_per_sec`
    个采样一组取「绝对值最大」，归一化到 0-255。1 小时音频约 720KB。

    on_progress(0-100) 用于界面进度；should_stop() 返回 True 时提前退出。
    返回 (peaks: bytearray, duration_sec: float)。
    """
    src_rate = 16000
    group = max(1, src_rate // max(1, peaks_per_sec))
    # -vn 丢弃视频；-f s16le 裸 PCM；输出到 stdout
    cmd = [ffmpeg, "-v", "error", "-i", path, "-vn",
           "-ac", "1", "-ar", str(src_rate), "-f", "s16le", "-"]
    duration = probe_duration(_ffprobe_of(ffmpeg), path)
    peaks = bytearray()
    total_bytes = 0
    carry = b""
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    try:
        while True:
            if should_stop and should_stop():
                proc.kill()
                break
            chunk = proc.stdout.read(1 << 18)      # 256KB
            if not chunk:
                break
            total_bytes += len(chunk)
            buf = carry + chunk
            n = len(buf) // (group * 2)
            usable = n * group * 2
            carry = buf[usable:]
            if n:
                samples = _unpack_s16(buf[:usable])
                for i in range(0, len(samples), group):
                    seg = samples[i:i + group]
                    peak = max(max(seg), -min(seg))
                    peaks.append(min(255, peak * 255 // 32768))
            if on_progress and duration > 0:
                sec = total_bytes / (src_rate * 2)
                on_progress(min(99, int(sec * 100 / duration)))
    finally:
        try:
            proc.stdout.close()
        except Exception:  # noqa: BLE001
            pass
        proc.wait(timeout=10)
    if on_progress:
        on_progress(100)
    return peaks, duration


def _ffprobe_of(ffmpeg):
    """由 ffmpeg 路径推 ffprobe 路径（同目录同名规则）。"""
    d, n = os.path.split(ffmpeg)
    return os.path.join(d, n.replace("ffmpeg", "ffprobe"))


def _unpack_s16(buf):
    """把 s16le 字节解成 int 列表（用 stdlib array，比 struct 循环快得多）。"""
    import array
    a = array.array("h")
    a.frombytes(buf)
    if sys.byteorder == "big":
        a.byteswap()
    return a


class WaveformCache:
    """波形峰值磁盘缓存。

    键 = 媒体文件绝对路径 + 大小 + mtime + 分辨率，任一变化即失效；
    落到 `<data_root>/waveforms/<md5>.bin`（裸峰值）+ 同名 `.json`（元信息）。
    """

    def __init__(self, data_root, ffmpeg, ffprobe=None, peaks_per_sec=PEAKS_PER_SEC):
        self.dir = os.path.join(data_root, WAVE_CACHE_DIRNAME)
        self.ffmpeg = ffmpeg
        self.ffprobe = ffprobe or _ffprobe_of(ffmpeg)
        self.peaks_per_sec = peaks_per_sec

    def _key(self, media_path):
        try:
            st = os.stat(media_path)
            sig = "%s|%d|%d|%d" % (os.path.abspath(media_path), st.st_size,
                                  int(st.st_mtime), self.peaks_per_sec)
        except OSError:
            sig = "%s|missing" % os.path.abspath(media_path)
        return hashlib.md5(sig.encode("utf-8", "replace")).hexdigest()

    def paths(self, media_path):
        k = self._key(media_path)
        return (os.path.join(self.dir, k + ".bin"),
                os.path.join(self.dir, k + ".json"))

    def load(self, media_path):
        """命中则返回 (peaks, duration)，否则 (None, 0.0)。"""
        b, j = self.paths(media_path)
        if not (os.path.isfile(b) and os.path.isfile(j)):
            return None, 0.0
        try:
            with open(j, encoding="utf-8") as fh:
                meta = json.load(fh)
            with open(b, "rb") as fh:
                peaks = bytearray(fh.read())
            return peaks, float(meta.get("duration", 0.0))
        except Exception:  # noqa: BLE001
            return None, 0.0

    def save(self, media_path, peaks, duration):
        b, j = self.paths(media_path)
        os.makedirs(self.dir, exist_ok=True)
        tmp_b, tmp_j = b + ".part", j + ".part"
        with open(tmp_b, "wb") as fh:
            fh.write(bytes(peaks))
        with open(tmp_j, "w", encoding="utf-8") as fh:
            json.dump({"duration": duration, "pps": self.peaks_per_sec,
                       "count": len(peaks),
                       "src": os.path.abspath(media_path)}, fh,
                      ensure_ascii=False)
        os.replace(tmp_b, b)
        os.replace(tmp_j, j)

    def get_or_build(self, media_path, on_progress=None, should_stop=None):
        """先查缓存，未命中则提取并落盘。返回 (peaks, duration)。"""
        peaks, duration = self.load(media_path)
        if peaks is not None:
            if on_progress:
                on_progress(100)
            return peaks, duration
        peaks, duration = extract_peaks(self.ffmpeg, media_path,
                                        self.peaks_per_sec, on_progress, should_stop)
        if peaks:
            try:
                self.save(media_path, peaks, duration)
            except Exception:  # noqa: BLE001
                pass          # 缓存失败不影响使用
        return peaks, duration


# =============================================================
# 2. libmpv 播放器封装
# =============================================================
class MpvPlayer(QObject):
    """把 libmpv 包成 Qt 友好的播放器。

    · 用 QTimer 轮询 time-pos（而不是 mpv 的 observe 回调）——回调在 mpv
      自己的线程里触发，跨线程直接碰 Qt 控件是事故高发区；轮询 40ms 的
      额外开销可以忽略，且行为完全可预期。
    · 对外一律 **int 毫秒**。
    """

    position_changed = pyqtSignal(int)     # 当前播放位置（ms）
    duration_changed = pyqtSignal(int)     # 媒体总长（ms）
    playing_changed = pyqtSignal(bool)
    loaded = pyqtSignal(bool, str)         # (成功?, 错误信息)

    def __init__(self, mpv_dir, parent=None):
        super().__init__(parent)
        self.mpv_dir = mpv_dir
        self.player = None
        self._duration_ms = 0
        self._last_pos = -1
        self._error = ""
        # 预览字幕（编辑页把当前 cues 生成一份 ASS 交给 mpv 自己渲染）
        self._sub_path = ""
        self._sub_added = ""
        self._timer = QTimer(self)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self._poll)

    # ---------- 生命周期 ----------
    def attach(self, widget):
        """绑定渲染窗口（必须在窗口真正创建后才能拿到有效句柄）。"""
        mod, err = load_mpv(self.mpv_dir)
        if mod is None:
            self._error = err
            self.loaded.emit(False, err)
            return False
        try:
            hwnd = int(widget.winId())
            self.player = mod.MPV(
                wid=str(hwnd),
                osc=False,                      # 控制条自己画
                input_default_bindings=False,   # 不抢键盘，快捷键由页面统一管
                input_vo_keyboard=False,
                hr_seek="yes",                  # 打轴靠它：精确 seek
                keep_open="yes",
                # --- 字幕轨一律关掉（v1.13.2）---
                # sub-auto=no：**关掉自动加载同名外挂字幕**。否则目录里那个
                #   .srt 会被 mpv 自己加载一遍，和我们画的预览叠成两层。
                # sid=no：连**内嵌字幕轨**也关掉——预览字幕改由
                #   `subtitle_overlay.SubtitleStage`（Qt 顶层透明窗口）自绘，
                #   因为只有 Qt 控件才点得中、拖得动、改得了字；mpv 再画一层
                #   就是重影。mpv 从此只负责画面。
                sub_auto="no",
                sid="no",
                log_handler=None,
            )
        except Exception as e:  # noqa: BLE001
            self._error = "创建 MPV 实例失败：%s" % e
            self.player = None
            self.loaded.emit(False, self._error)
            return False
        return True

    def terminate(self):
        """释放 libmpv。**必须调用**，否则 onefile 的 _MEI*** 删不掉。"""
        self._timer.stop()
        self._sub_added = ""
        if self.player is not None:
            try:
                self.player.terminate()
            except Exception:  # noqa: BLE001
                pass
            self.player = None

    @property
    def available(self):
        return self.player is not None

    @property
    def error(self):
        return self._error

    # ---------- 媒体 ----------
    def load(self, path, autoplay=False):
        if self.player is None:
            self.loaded.emit(False, self._error or "播放器未就绪")
            return
        try:
            self.player.pause = True
            self.player.loadfile(path)
            self._duration_ms = 0
            self._last_pos = -1
            # loadfile 会清掉全部字幕轨，记账也要跟着清，否则下次
            # set_subtitles 会误判成"已挂载"而只发 sub-reload（画面空着）
            self._sub_added = ""
            self._autoplay = bool(autoplay)
            self._timer.start()
        except Exception as e:  # noqa: BLE001
            self.loaded.emit(False, "加载媒体失败：%s" % e)

    def close_media(self):
        if self.player is None:
            return
        try:
            self.player.command("stop")
        except Exception:  # noqa: BLE001
            pass
        self._timer.stop()
        self._duration_ms = 0
        self._last_pos = -1

    # ---------- 传输控制 ----------
    def play(self):
        if self.player is not None:
            self.player.pause = False

    def pause(self):
        if self.player is not None:
            self.player.pause = True

    def toggle_play(self):
        if self.player is None or not self.duration_ms:
            return
        self.pause() if self.is_playing() else self.play()

    def is_playing(self):
        if self.player is None:
            return False
        try:
            return not bool(self.player.pause)
        except Exception:  # noqa: BLE001
            return False

    def set_speed(self, speed):
        if self.player is not None:
            try:
                self.player.speed = float(speed)
            except Exception:  # noqa: BLE001
                pass

    def seek_ms(self, ms, exact=True):
        """定位到指定毫秒。`exact=True` 走 hr-seek（帧对齐，打轴必需）。"""
        if self.player is None:
            return
        ms = max(0, int(ms))
        try:
            self.player.command("seek", ms / 1000.0,
                                "absolute+exact" if exact else "absolute")
        except Exception:  # noqa: BLE001
            pass
        self._emit_position(ms, force=True)

    def nudge_ms(self, delta_ms):
        """相对当前位置微调（左右方向键、Shift 平移都用它）。"""
        self.seek_ms(self.position_ms + int(delta_ms))

    def step_frame(self, n=1):
        """逐帧步进（n 正数前进、负数后退）。打轴最核心的操作。"""
        if self.player is None:
            return
        cmd = "frame-step" if n > 0 else "frame-back-step"
        for _ in range(abs(int(n))):
            try:
                self.player.command(cmd)
            except Exception:  # noqa: BLE001
                break

    # ---------- 预览字幕（画面上那一层） ----------
    def _preview_path(self):
        """预览 ASS 的落地路径。放系统临时目录，绝不动用户文件。"""
        if not self._sub_path:
            self._sub_path = os.path.join(
                tempfile.gettempdir(), "vt_sub_preview", "preview.ass")
        return self._sub_path

    def set_subtitles(self, ass_text):
        """把一份 ASS 文本挂到播放器上，由 libass **直接渲染在画面上**。

        为什么走文件而不是 `data://`：`sub-add` 只认路径/URL，内存协议在
        这条命令上不成立；而落到临时目录的文件只有几十 KB，也不碰用户的
        .srt，代价可以忽略。

        首次 `sub-add`，之后只覆盖文件内容 + `sub-reload`——反复 add 会
        堆出一串字幕轨（还会各自渲染），reload 没有这个副作用。
        返回 True 表示已生效，False 表示播放器未就绪或写入失败。
        """
        if self.player is None:
            return False
        path = self._preview_path()
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            tmp = path + ".part"
            with open(tmp, "w", encoding="utf-8") as fh:
                fh.write(ass_text or "")
            os.replace(tmp, path)
        except OSError:
            return False
        try:
            if self._sub_added == path:
                self.player.command("sub-reload")
            else:
                if self._sub_added:
                    self.clear_subtitles()
                self.player.command("sub-add", path, "select")
                self._sub_added = path
        except Exception:  # noqa: BLE001
            return False
        return True

    def clear_subtitles(self):
        """摘掉预览字幕轨（`loadfile` 之后字幕轨会被清空，这里同步记账）。"""
        if self.player is None:
            self._sub_added = ""
            return
        if self._sub_added:
            try:
                self.player.command("sub-remove")
            except Exception:  # noqa: BLE001
                pass
            self._sub_added = ""

    # ---------- 状态 ----------
    @property
    def duration_ms(self):
        return self._duration_ms

    @property
    def position_ms(self):
        if self.player is None:
            return 0
        try:
            tp = self.player.time_pos
            return max(0, int(round(float(tp) * 1000))) if tp is not None else 0
        except Exception:  # noqa: BLE001
            return 0

    @property
    def fps(self):
        """容器帧率（拿不到就给常见的 25）。"""
        if self.player is None:
            return 25.0
        try:
            v = self.player.container_fps
            return float(v) if v else 25.0
        except Exception:  # noqa: BLE001
            return 25.0

    def video_aspect(self):
        """画面宽高比（宽 / 高，含像素比修正）；没有视频时返回 0.0。

        用途是给画面字幕层算**真实显示区域**：竖屏视频放进横向窗口时只占
        中间一竖条，四周是黑边。字幕的坐标基准必须跟画面走，否则选框会和
        真实字幕错位。
        """
        if self.player is None:
            return 0.0
        try:
            vp = self.player.video_params
            if vp:
                a = vp.get("aspect")
                if a:
                    return float(a)
                vw, vh = vp.get("w") or 0, vp.get("h") or 0
                if vw and vh:
                    return float(vw) / float(vh)
        except Exception:  # noqa: BLE001
            pass
        try:
            d = self.player.osd_dimensions
            if d and d.get("w") and d.get("h"):
                return float(d["w"]) / float(d["h"])
        except Exception:  # noqa: BLE001
            pass
        return 0.0

    def _emit_position(self, ms, force=False):
        ms = max(0, int(ms))
        if force or ms != self._last_pos:
            self._last_pos = ms
            self.position_changed.emit(ms)

    def _poll(self):
        if self.player is None:
            return
        dur = 0
        try:
            d = self.player.duration
            dur = int(round(float(d) * 1000)) if d else 0
        except Exception:  # noqa: BLE001
            dur = 0
        if dur and dur != self._duration_ms:
            self._duration_ms = dur
            self.duration_changed.emit(dur)
            if getattr(self, "_autoplay", False):
                self._autoplay = False
                self.play()
        if dur and self._duration_ms:
            self._emit_position(self.position_ms)
            self.playing_changed.emit(self.is_playing())
