# -*- coding: utf-8 -*-
# @version 1.12.2
"""字幕编辑页的纯逻辑层：SRT 读写、时间换算、编辑操作、撤销栈。

与界面完全解耦（本模块**不 import Qt**），便于 `_selftest_*` 直接测试。

设计取舍
--------
1. **时间一律用 int 毫秒**。mpv 的 `time-pos` 是 float（实测出现
   `25.400000000000002` 这种值），一旦反复加减就会累积漂移；内部只存 int，
   仅在展示时格式化。
2. **解码口径与校准链路一致**：复用 `subtitle_calib_merged.py` 的
   `TEXT_ENCODINGS` 策略（BOM 优先 → utf-8 → gb18030 → big5 → shift_jis →
   latin-1），**写出统一 UTF-8**，并**按原样保留 BOM 与 CRLF**。
   该逻辑在此内建一份：编辑器跑在主程序 exe 内，不能假设
   `subtitle_calib_merged.py` 一定存在于磁盘。
3. **撤销用整档快照**。字幕文件通常几百 KB，快照比 diff 简单可靠得多，
   也不会出现"编辑后 diff 无法还原"的经典 bug。
4. 编辑操作**只改内存**，由调用方决定何时落盘（避免误写用户文件）。
"""
import copy
import re
from dataclasses import dataclass, field

# =============================================================
# 0. 统一解码（与 subtitle_calib_merged.py 保持同口径，改动需两边同步）
# =============================================================
TEXT_ENCODINGS = ("utf-8-sig", "utf-8", "gb18030", "big5", "shift_jis", "latin-1")


def decode_any(data, encodings=TEXT_ENCODINGS):
    """把任意字节流解码成文本（永不抛异常）。"""
    if isinstance(data, str):
        return data
    if not data:
        return ""
    if data[:4] in (b"\xff\xfe\x00\x00", b"\x00\x00\xfe\xff"):
        try:
            return data.decode("utf-32")
        except UnicodeDecodeError:
            pass
    elif data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        try:
            return data.decode("utf-16")
        except UnicodeDecodeError:
            pass
    if data[:3] == b"\xef\xbb\xbf":
        try:
            return data.decode("utf-8-sig")
        except UnicodeDecodeError:
            pass
    for enc in encodings:
        try:
            return data.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("utf-8", "replace")


# =============================================================
# 1. 时间换算
# =============================================================
def ms_to_srt(ms):
    """int 毫秒 -> `HH:MM:SS,mmm`（负数按 0 处理）。"""
    ms = max(0, int(ms))
    h, rem = divmod(ms, 3600000)
    m, rem = divmod(rem, 60000)
    s, milli = divmod(rem, 1000)
    return "%02d:%02d:%02d,%03d" % (h, m, s, milli)


def ms_to_clock(ms):
    """int 毫秒 -> `MM:SS.mmm`（打轴时读时间用，省掉小时位更省眼睛）。"""
    ms = max(0, int(ms))
    h, rem = divmod(ms, 3600000)
    m, rem = divmod(rem, 60000)
    s, milli = divmod(rem, 1000)
    if h:
        return "%d:%02d:%02d.%03d" % (h, m, s, milli)
    return "%02d:%02d.%03d" % (m, s, milli)


def clock_to_ms(text):
    """`[HH:]MM:SS[.,]mmm` / `SS[.,]mmm` -> int 毫秒；失败返回 None。

    供"手动输入时间"用，允许只写秒（如 `12.5`）。
    """
    if text is None:
        return None
    t = str(text).strip().replace(",", ".")
    if not t:
        return None
    if ":" not in t:
        try:
            return max(0, int(round(float(t) * 1000)))
        except ValueError:
            return None
    parts = t.split(":")
    if len(parts) > 3:
        return None
    try:
        sec = float(parts[-1])
        minutes = int(parts[-2]) if len(parts) >= 2 else 0
        hours = int(parts[-3]) if len(parts) >= 3 else 0
    except ValueError:
        return None
    return max(0, int(round(((hours * 60 + minutes) * 60 + sec) * 1000)))


_TS = r"(?:(\d+):)?(\d{1,2}):(\d{1,2})[,.](\d{1,3})"
_TIME_LINE_RE = re.compile(r"^\s*" + _TS + r"\s*-->\s*" + _TS + r"\s*(?:X1:.*)?$")


def _ts_to_ms(m):
    """把 _TS 的 4 个捕获组换算成毫秒。"""
    h = int(m.group(1) or 0)
    mi = int(m.group(2))
    s = int(m.group(3))
    frac = m.group(4)
    milli = int(frac.ljust(3, "0")[:3])
    return ((h * 60 + mi) * 60 + s) * 1000 + milli


# =============================================================
# 2. 数据模型
# =============================================================
@dataclass
class Cue:
    """一条字幕。`start`/`end` 为 int 毫秒，`text` 内部用 LF 换行。"""

    start: int
    end: int
    text: str = ""

    @property
    def duration(self):
        return max(0, self.end - self.start)

    def clone(self):
        return Cue(self.start, self.end, self.text)

    def overlaps(self, other):
        return self.start < other.end and other.start < self.end


@dataclass
class SubtitleDoc:
    """一份字幕文档 + 写出所需的原始风格信息。"""

    cues: list = field(default_factory=list)
    newline: str = "\r\n"        # 原样保留（项目一贯要求）
    has_bom: bool = False
    src_encoding: str = "utf-8"  # 仅用于界面提示，写出统一 UTF-8
    path: str = ""

    # ---------- 读 ----------
    def load_bytes(self, data, path=""):
        """从字节流解析。返回 (成功解析条数, 跳过的可疑行数)。"""
        text = decode_any(data)
        self.has_bom = data[:3] == b"\xef\xbb\xbf" or data[:2] in (b"\xff\xfe", b"\xfe\xff")
        self.newline = "\r\n" if "\r\n" in text else "\n"
        self.src_encoding = _sniff_encoding(data)
        self.path = path
        return self.parse(text)

    def load_file(self, path):
        with open(path, "rb") as fh:
            return self.load_bytes(fh.read(), path)

    def parse(self, text):
        """宽松解析 SRT/类 SRT 文本。

        容错点：序号可缺/可错、时间分隔符 `,` 或 `.`、小时位可省、
        多余空行、文本行数不定（含空行也并入上一条，直到遇到下一条时间行）。
        """
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        lines = text.split("\n")
        self.cues = []
        skipped = 0
        i = 0
        n = len(lines)
        while i < n:
            line = lines[i]
            m = _TIME_LINE_RE.match(line)
            if not m:
                if line.strip():
                    skipped += 1
                i += 1
                continue
            start = _ts_to_ms(m)
            end = _ts_to_ms(_second_ts(m))
            i += 1
            body = []
            while i < n:
                nxt = lines[i]
                if _TIME_LINE_RE.match(nxt):
                    break
                # 纯数字行若其后紧跟时间行，视作下一条的序号，不当正文
                if (nxt.strip().isdigit() and i + 1 < n
                        and _TIME_LINE_RE.match(lines[i + 1])):
                    break
                body.append(nxt)
                i += 1
            while body and not body[-1].strip():
                body.pop()
            self.cues.append(Cue(start, max(start, end), "\n".join(body)))
        return len(self.cues), skipped

    # ---------- 写 ----------
    def dump(self):
        """写出标准 SRT 文本（UTF-8；BOM 与换行按原样）。"""
        blocks = []
        for idx, c in enumerate(self.cues, 1):
            blocks.append("%d\n%s --> %s\n%s" % (
                idx, ms_to_srt(c.start), ms_to_srt(c.end), c.text or ""))
        body = "\n\n".join(blocks)
        if body:
            body += "\n"
        return body

    def to_bytes(self):
        """写出字节流：保留原 BOM 与否。"""
        text = self.dump().replace("\n", self.newline)
        data = text.encode("utf-8")
        if self.has_bom:
            data = b"\xef\xbb\xbf" + data
        return data

    def save_file(self, path):
        with open(path, "wb") as fh:
            fh.write(self.to_bytes())
        self.path = path

    # ---------- 查询 ----------
    def index_at(self, ms):
        """返回覆盖该时刻的 cue 下标；没有则返回 -1。"""
        for i, c in enumerate(self.cues):
            if c.start <= ms < c.end:
                return i
        return -1

    def nearest_index(self, ms):
        """返回时间上最近的 cue 下标（打轴"切句"用，永不返回 -1，除非空）。"""
        if not self.cues:
            return -1
        best, best_d = 0, None
        for i, c in enumerate(self.cues):
            d = 0 if c.start <= ms <= c.end else min(abs(c.start - ms), abs(c.end - ms))
            if best_d is None or d < best_d:
                best, best_d = i, d
        return best

    def overlaps_count(self):
        return sum(1 for a, b in zip(self.cues, self.cues[1:]) if a.end > b.start)

    def total_chars(self):
        return sum(len(c.text) for c in self.cues)

    def snapshot(self):
        return copy.deepcopy(self.cues)

    def restore(self, snap):
        self.cues = copy.deepcopy(snap)


def _second_ts(m):
    """从时间行匹配里取出"结束时间"的 4 个组，拼成与 _ts_to_ms 同构的对象。"""
    return _FakeMatch(m.group(5), m.group(6), m.group(7), m.group(8))


class _FakeMatch:
    __slots__ = ("_g",)

    def __init__(self, a, b, c, d):
        self._g = (a, b, c, d)

    def group(self, i):
        return self._g[i - 1]


def _sniff_encoding(data):
    """猜出原编码名，仅用于界面显示（不参与写出）。"""
    if data[:3] == b"\xef\xbb\xbf":
        return "utf-8-sig"
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return "utf-16"
    for enc in ("utf-8", "gb18030", "big5", "shift_jis"):
        try:
            data.decode(enc)
            return enc
        except UnicodeDecodeError:
            continue
    return "latin-1"


# =============================================================
# 3. 编辑操作（原地修改 SubtitleDoc.cues）
# =============================================================
MIN_DURATION_MS = 40      # 一帧（25fps）；低于此值的 cue 视为无效


def shift_cues(cues, indices, delta_ms, keep_order=True):
    """把指定 cue 整体平移 delta_ms（负值提前）。返回实际平移量。"""
    if not indices:
        return 0
    sel = [cues[i] for i in indices if 0 <= i < len(cues)]
    if not sel:
        return 0
    # 不允许把任何一条推成负数起点：必要时整体削减位移
    lo = min(c.start for c in sel)
    if lo + delta_ms < 0:
        delta_ms = -lo
    if delta_ms == 0:
        return 0
    for c in sel:
        c.start += delta_ms
        c.end += delta_ms
    if keep_order:
        sort_cues(cues)
    return delta_ms


def shift_all(cues, delta_ms):
    """整轨平移，等价于全部选中。"""
    return shift_cues(cues, list(range(len(cues))), delta_ms, keep_order=False)


def set_boundary(cues, index, which, ms):
    """设置第 index 条的起点或终点（`which` 取 'start'/'end'）。"""
    if not (0 <= index < len(cues)):
        return False
    c = cues[index]
    ms = max(0, int(ms))
    if which == "start":
        if ms >= c.end:
            ms = max(0, c.end - MIN_DURATION_MS)
        c.start = ms
    else:
        if ms <= c.start:
            ms = c.start + MIN_DURATION_MS
        c.end = ms
    return True


def split_cue(cues, index, at_ms, min_dur=MIN_DURATION_MS):
    """在 at_ms 处把一条切成两条；不满足最小长度则返回 False。"""
    if not (0 <= index < len(cues)):
        return False
    c = cues[index]
    at_ms = int(at_ms)
    if at_ms - c.start < min_dur or c.end - at_ms < min_dur:
        return False
    tail = Cue(at_ms, c.end, c.text)
    c.end = at_ms
    cues.insert(index + 1, tail)
    return True


def merge_cues(cues, indices, sep=" "):
    """合并若干条为一条（取并集范围，文本用 sep 连接）；返回新下标。"""
    idxs = sorted(set(i for i in indices if 0 <= i < len(cues)))
    if len(idxs) < 2:
        return idxs[0] if idxs else -1
    group = [cues[i] for i in idxs]
    start = min(c.start for c in group)
    end = max(c.end for c in group)
    text = sep.join(c.text.strip() for c in group if c.text.strip())
    for i in reversed(idxs):
        del cues[i]
    cues.insert(idxs[0], Cue(start, end, text))
    return idxs[0]


def delete_cues(cues, indices):
    """删除若干条；返回删除条数。"""
    idxs = sorted(set(i for i in indices if 0 <= i < len(cues)), reverse=True)
    for i in idxs:
        del cues[i]
    return len(idxs)


def insert_cue(cues, at_ms, duration_ms=1500, text=""):
    """在 at_ms 插入一条空白字幕；返回新下标。"""
    at_ms = max(0, int(at_ms))
    cue = Cue(at_ms, at_ms + max(MIN_DURATION_MS, int(duration_ms)), text)
    pos = len(cues)
    for i, c in enumerate(cues):
        if c.start > at_ms:
            pos = i
            break
    cues.insert(pos, cue)
    return pos


def sort_cues(cues):
    """按起点稳定排序（保持内容行顺序，避免"看似没动却全乱"）。"""
    cues.sort(key=lambda c: (c.start, c.end))


def fix_overlaps(cues, gap_ms=1):
    """消除相邻重叠：把前一条的终点截到后一条起点之前。返回修正条数。"""
    fixed = 0
    for a, b in zip(cues, cues[1:]):
        if a.end > b.start:
            new_end = max(a.start + MIN_DURATION_MS, b.start - gap_ms)
            if new_end < a.end:
                a.end = new_end
                fixed += 1
    return fixed


def clamp_zero_length(cues, min_dur=MIN_DURATION_MS):
    """把零长/倒挂的 cue 拉直成最短时长。返回修正条数。"""
    fixed = 0
    for c in cues:
        if c.end - c.start < min_dur:
            c.end = c.start + min_dur
            fixed += 1
    return fixed


def renumber(cues):
    """重排为「从 0 开始、彼此不重叠、首尾相接的空隙保留」的连续编号。

    这里只做排序（序号在写出时按顺序生成），保留函数是为了让界面上的
    「重编号」动作有明确语义：抵消用户手工排序造成的乱序。
    """
    sort_cues(cues)
    return len(cues)


def stats(cues):
    """汇总统计，供界面状态栏显示。"""
    if not cues:
        return {"count": 0, "chars": 0, "duration": 0, "overlaps": 0, "zero": 0}
    return {
        "count": len(cues),
        "chars": sum(len(c.text) for c in cues),
        "duration": max(c.end for c in cues) - min(c.start for c in cues),
        "overlaps": sum(1 for a, b in zip(cues, cues[1:]) if a.end > b.start),
        "zero": sum(1 for c in cues if c.end - c.start < MIN_DURATION_MS),
    }


# =============================================================
# 4. 撤销栈（整档快照）
# =============================================================
class UndoStack:
    """基于整档快照的撤销/重做。

    每次"原子编辑"前 push 一份当前 cues；undo 时把栈顶换回当前并推入 redo。
    深度默认 100：一份 3000 条字幕的快照约几百 KB，100 层完全可接受。
    """

    def __init__(self, depth=100):
        self.depth = depth
        self._undo = []
        self._redo = []
        self.label = ""

    def push(self, cues, label="", snapshot=None):
        """压入一份撤销快照。

        `snapshot` 为 None 时取 `cues` 当前状态的深拷贝；传入 snapshot 用于
        「改动已经发生、但快照必须是改动之前」的场景（典型是时间轴拖拽：
        控件边拖边改 cue，只能在拖拽开始前先把快照存下来）。
        """
        self._undo.append((copy.deepcopy(cues) if snapshot is None else snapshot, label))
        if len(self._undo) > self.depth:
            self._undo.pop(0)
        self._redo.clear()
        self.label = label

    def can_undo(self):
        return bool(self._undo)

    def can_redo(self):
        return bool(self._redo)

    def undo(self, cues):
        """返回 (新 cues, 动作名)；无可撤销则返回 (None, "")。"""
        if not self._undo:
            return None, ""
        snap, label = self._undo.pop()
        self._redo.append((copy.deepcopy(cues), label))
        return snap, label

    def redo(self, cues):
        if not self._redo:
            return None, ""
        snap, label = self._redo.pop()
        self._undo.append((copy.deepcopy(cues), label))
        return snap, label

    def clear(self):
        self._undo.clear()
        self._redo.clear()
