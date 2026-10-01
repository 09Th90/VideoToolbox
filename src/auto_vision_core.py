#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# @version 1.16.4
"""视觉自动化引擎（demo）—— 参考 MAA（MaaAssistantArknights）的四段设计
====================================================================
MAA 的本质是一个「游戏 UI 的视觉状态机机器人」，完全站在玩家位置看屏幕、
点按钮，不碰目标进程内存。它把整条链路拆成四段（详见工作区
`日常编程/MAA原理拆解与场景推导.md`）：

  ① 感知（抓帧）  ControlUnit 抽象「从哪拿画面」——模拟器 ADB / Win32 窗口截图；
  ② 认知（识别）  三级火力，从便宜到昂贵：模板匹配 → OCR → 神经网络；
  ③ 决策（状态机）声明式 `tasks.json`：{识别什么, 在哪片 ROI, 做什么动作,
                  成功后去哪个节点, 失败/超时去哪}；`next` 按序尝试、
                  `maxTimes` + `exceededNext` 构成熔断兜底；
  ④ 行动（注入）  ClickSelf = 点本节点识别命中的位置；还有滑动、长按等。

本模块把同一套骨架做成**与具体游戏无关**的最小实现，供「自动化」页调用：

  · `list_windows()` / `capture_window()`       —— 感知：枚举窗口 + 客户区抓帧
  · `match_template()` / `match_color()`        —— 认知：FFT 归一化互相关 / 色块
  · `parse_pipeline()` / `PipelineRunner`       —— 决策：声明式节点 + 熔断转移
  · `click()`                                   —— 行动：SendInput 绝对坐标点击

与 MAA 的差异（有意为之，demo 规模）：
  1. 识别只做**模板匹配 + 色块**，OCR / 神经网络留接口不实现——不引第三方
     模型（本机没装 opencv，也不想为 demo 增依赖）；
  2. 模板匹配用 numpy FFT 算归一化互相关（NCC），对亮度线性变化不敏感，
     与 OpenCV `TM_CCOEFF_NORMED` 同源；
  3. **默认演练（dry-run）**：只识别、只标注，不真的点鼠标；要真点必须在页面上
     显式打开开关。MAA 的边界说明同样适用——自动化别人家的界面属于灰色地带。

线程模型：本模块不碰 Qt，纯函数 + 一个无状态 Runner，主线程直接调用即可
（1920×1080 上跑一次模板匹配实测 30~80ms，不构成卡顿）。
"""

import ctypes
import ctypes.wintypes as wt
import os
import time

import numpy as np
from PIL import Image, ImageGrab

try:  # 抓帧的兜底路径（窗口被遮挡时用 PrintWindow）
    import win32con
    import win32gui
    import win32ui
    _HAS_WIN32 = True
except Exception:  # noqa: BLE001
    _HAS_WIN32 = False


# ---------------------------------------------------------------------- #
# ① 感知：窗口枚举 + 客户区抓帧
# ---------------------------------------------------------------------- #
class WindowInfo:
    """一个可被当作「画面来源」的顶层窗口。"""

    __slots__ = ("hwnd", "title", "rect", "client_rect")

    def __init__(self, hwnd, title, rect, client_rect):
        self.hwnd = hwnd
        self.title = title
        #: 窗口外框在**屏幕物理坐标**下的 (left, top, right, bottom)
        self.rect = rect
        #: 客户区在屏幕物理坐标下的 (left, top, right, bottom)
        self.client_rect = client_rect

    @property
    def size(self):
        l, t, r, b = self.client_rect
        return (max(0, r - l), max(0, b - t))

    def __repr__(self):  # pragma: no cover - 调试用
        return f"<WindowInfo 0x{self.hwnd:X} {self.title!r} {self.size}>"


def list_windows(min_size=(80, 60)):
    """枚举可见且有标题的顶层窗口（按标题排序，过滤掉本程序自己）。

    返回 `[WindowInfo, ...]`。非 Windows / 缺 pywin32 时返回空列表。
    """
    if not _HAS_WIN32:
        return []
    me = os.getpid()
    out = []

    def _cb(hwnd, _):
        try:
            if not win32gui.IsWindowVisible(hwnd):
                return True
            title = (win32gui.GetWindowText(hwnd) or "").strip()
            if not title:
                return True
            if win32gui.IsIconic(hwnd):          # 最小化的窗口抓不到画面
                return True
            # 排除本进程自己的窗口（避免"自己抓自己"的递归观感）
            pid = wt.DWORD()
            ctypes.windll.user32.GetWindowThreadProcessId(
                hwnd, ctypes.byref(pid))
            if pid.value == me:
                return True
            l, t, r, b = win32gui.GetWindowRect(hwnd)
            if (r - l) < min_size[0] or (b - t) < min_size[1]:
                return True
            cl, ct, cr, cb = win32gui.GetClientRect(hwnd)
            sx, sy = win32gui.ClientToScreen(hwnd, (cl, ct))
            ex, ey = win32gui.ClientToScreen(hwnd, (cr, cb))
            out.append(WindowInfo(hwnd, title, (l, t, r, b),
                                  (sx, sy, ex, ey)))
        except Exception:  # noqa: BLE001
            pass
        return True

    try:
        win32gui.EnumWindows(_cb, None)
    except Exception:  # noqa: BLE001
        return []
    out.sort(key=lambda w: w.title.lower())
    return out


def window_info(hwnd):
    """由句柄直接构造 WindowInfo（**包含本进程自己的窗口**）。

    `list_windows()` 有意把本程序的窗口滤掉（避免"自己抓自己"），但内置演示
    场景恰恰就是本程序弹出的一个窗口，需要走这条通道。非 Windows 返回 None。
    """
    if not _HAS_WIN32:
        return None
    try:
        title = win32gui.GetWindowText(hwnd) or ""
        l, t, r, b = win32gui.GetWindowRect(hwnd)
        cl, ct, cr, cb = win32gui.GetClientRect(hwnd)
        sx, sy = win32gui.ClientToScreen(hwnd, (cl, ct))
        ex, ey = win32gui.ClientToScreen(hwnd, (cr, cb))
        return WindowInfo(hwnd, title, (l, t, r, b), (sx, sy, ex, ey))
    except Exception:  # noqa: BLE001
        return None


def capture_window(win, use_printwindow=False):
    """抓取窗口**客户区**画面。

    参数
      win              WindowInfo
      use_printwindow  True 时走 PrintWindow（可抓被遮挡的窗口，但对
                       GPU 加速渲染的窗口常得到全黑，故默认走屏幕抓取）

    返回 `(frame, origin, cost_ms)`
      frame   np.ndarray, 形状 (H, W, 3), dtype=uint8, RGB
      origin  (x, y) 客户区左上角在**屏幕物理坐标**下的位置——
              识别出的坐标加上它才是屏幕坐标，点击时要的就是屏幕坐标
    """
    t0 = time.time()
    l, t, r, b = win.client_rect
    w, h = max(1, r - l), max(1, b - t)

    frame = None
    if use_printwindow and _HAS_WIN32:
        try:
            frame = _print_window(win.hwnd, w, h)
        except Exception:  # noqa: BLE001
            frame = None

    if frame is None:
        # all_screens=True：多屏 / 副屏在负坐标时也能抓到
        img = ImageGrab.grab(bbox=(l, t, r, b), all_screens=True)
        frame = np.asarray(img.convert("RGB"), dtype=np.uint8)

    return frame, (l, t), (time.time() - t0) * 1000.0


def _print_window(hwnd, w, h):
    """PrintWindow 抓帧（被遮挡窗口的兜底；GPU 窗口可能全黑）。"""
    hwnd_dc = win32gui.GetWindowDC(hwnd)
    mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
    save_dc = mfc_dc.CreateCompatibleDC()
    bmp = win32ui.CreateBitmap()
    bmp.CreateCompatibleBitmap(mfc_dc, w, h)
    save_dc.SelectObject(bmp)
    # PW_CLIENTONLY(1) | PW_RENDERFULLCONTENT(2)
    ctypes.windll.user32.PrintWindow(hwnd, save_dc.GetSafeHdc(), 3)
    info = bmp.GetInfo()
    buf = bmp.GetBitmapBits(True)
    arr = np.frombuffer(buf, dtype=np.uint8)
    arr = arr.reshape((info["bmHeight"], info["bmWidth"], 4))[:, :, :3][:, :, ::-1]
    win32gui.DeleteObject(bmp.GetHandle())
    save_dc.DeleteDC()
    mfc_dc.DeleteDC()
    win32gui.ReleaseDC(hwnd, hwnd_dc)
    return np.ascontiguousarray(arr, dtype=np.uint8)


# ---------------------------------------------------------------------- #
# ② 认知：模板匹配（FFT 归一化互相关）+ 色块匹配
# ---------------------------------------------------------------------- #
class Match:
    """一次识别的命中结果（坐标一律是**客户区相对坐标**）。"""

    __slots__ = ("x", "y", "w", "h", "score")

    def __init__(self, x, y, w, h, score):
        self.x, self.y, self.w, self.h, self.score = x, y, w, h, score

    @property
    def center(self):
        return (self.x + self.w // 2, self.y + self.h // 2)

    def as_roi(self):
        return [int(self.x), int(self.y), int(self.w), int(self.h)]

    def __repr__(self):  # pragma: no cover - 调试用
        return (f"<Match ({self.x},{self.y},{self.w}x{self.h}) "
                f"score={self.score:.3f}>")


def crop_roi(frame, roi):
    """按 [x, y, w, h] 裁 ROI；roi 为空 / 全 0 / 越界时自动收敛到帧内。"""
    H, W = frame.shape[:2]
    if not roi or len(roi) < 4:
        return frame, (0, 0)
    x, y, w, h = [int(v) for v in roi[:4]]
    if w <= 0 or h <= 0:                       # w/h 为 0 = 全帧（与 MAA 同）
        return frame, (0, 0)
    x = max(0, min(x, W - 1))
    y = max(0, min(y, H - 1))
    x2 = max(x + 1, min(x + w, W))
    y2 = max(y + 1, min(y + h, H))
    return frame[y:y2, x:x2], (x, y)


def _corr_valid(img, tpl):
    """互相关（valid 区域）：等价于 conv(img, flip(tpl))。"""
    H, W = img.shape
    h, w = tpl.shape
    F = np.fft.rfft2(img, s=(H, W))
    T = np.fft.rfft2(tpl[::-1, ::-1], s=(H, W))
    out = np.fft.irfft2(F * T, s=(H, W))
    return out[h - 1:H, w - 1:W]


def _window_sum(a, h, w):
    """所有 h×w 窗口的元素和，形状 (H-h+1, W-w+1)（积分图实现）。"""
    c = np.cumsum(np.cumsum(a, axis=0, dtype=np.float64), axis=1)
    c = np.pad(c, ((1, 0), (1, 0)))
    return c[h:, w:] - c[:-h, w:] - c[h:, :-w] + c[:-h, :-w]


def _ncc_map(img, tpl):
    """单通道归一化互相关得分图（-1 ~ 1）。

    ⚠ 平坦区域必须显式作废：窗口内像素方差趋近 0 时，分子分母都是浮点残渣，
    相除会给出 20+ 的荒谬得分（实测纯色底图上误命中、得分 24.388）。这里要求
    窗口方差至少达到模板方差的 1%，否则该位置直接判 0 分。
    """
    H, W = img.shape
    h, w = tpl.shape
    if h > H or w > W:
        return None
    n = float(h * w)
    s_t = float(tpl.sum())
    s_t2 = float((tpl ** 2).sum())
    var_t = s_t2 - s_t * s_t / n
    if var_t <= 1e-9:                 # 纯色模板：NCC 无定义，交给色块算法
        return None
    s_i = _window_sum(img, h, w)
    s_i2 = _window_sum(img ** 2, h, w)
    var_i = s_i2 - s_i * s_i / n
    ok = var_i > max(1.0, var_t * 0.01)
    num = _corr_valid(img, tpl) - s_t * s_i / n
    den = np.sqrt(np.maximum(var_i, 1e-9) * var_t)
    score = np.where(ok, num / den, 0.0)
    return np.clip(score, -1.0, 1.0)


def match_template(frame, template, roi=None, threshold=0.8, max_results=8):
    """模板匹配：返回按得分降序的 `[Match, ...]`（含非极大值抑制）。

    彩色图对 R/G/B 三通道分别算 NCC 再取均值（与 OpenCV 模板匹配的逐通道
    行为一致）；灰度图直接算。`threshold` 为 0~1 的得分门限。
    """
    if frame is None or template is None:
        return []
    sub, (ox, oy) = crop_roi(frame, roi)
    if template.ndim == 2:
        tpl_ch = [template.astype(np.float32)]
        sub_ch = [sub.astype(np.float32)]
    else:
        tpl_ch = [template[:, :, c].astype(np.float32) for c in range(3)]
        sub_ch = [sub[:, :, c].astype(np.float32) for c in range(3)]

    maps = []
    for t, s in zip(tpl_ch, sub_ch):
        m = _ncc_map(s, t)
        if m is None:
            return []
        maps.append(m)
    score = np.mean(maps, axis=0)

    h, w = template.shape[:2]
    # 非极大值抑制：按得分降序贪心取点，抑制与已取点重叠过半的候选
    flat = score.ravel()
    order = np.argsort(flat)[::-1]
    W = score.shape[1]
    taken = []
    for idx in order[:4000]:
        v = float(flat[idx])
        if v < threshold:
            break
        y, x = divmod(int(idx), W)
        if any(abs(x - t[0]) < w * 0.5 and abs(y - t[1]) < h * 0.5
               for t in taken):
            continue
        taken.append((x, y, v))
        if len(taken) >= max_results:
            break
    return [Match(x + ox, y + oy, w, h, v) for x, y, v in taken]


def _largest_blob_bbox(mask, block=6):
    """在二值掩码里找**最大连通块**的包围盒。

    不能直接对所有命中像素取 min/max：背景噪点零散命中时，包围盒会一路撑到
    全屏（实测得分 0.007、框住整帧，等于没判据）。这里先在 block×block 的
    粗网格上做 4 邻域连通，再回原图收紧到该连通块内命中的像素。
    """
    H, W = mask.shape
    bh, bw = (H + block - 1) // block, (W + block - 1) // block
    pad_h, pad_w = bh * block - H, bw * block - W
    if pad_h or pad_w:
        mask = np.pad(mask, ((0, pad_h), (0, pad_w)))
    counts = mask.reshape(bh, block, bw, block).sum(axis=(1, 3))
    if counts.max() <= 0:
        return None
    start = np.unravel_index(int(counts.argmax()), counts.shape)
    seen = np.zeros_like(counts, dtype=bool)
    stack = [start]
    seen[start] = True
    comp = []
    while stack:
        cy, cx = stack.pop()
        comp.append((cy, cx))
        for ny, nx in ((cy - 1, cx), (cy + 1, cx), (cy, cx - 1), (cy, cx + 1)):
            if 0 <= ny < bh and 0 <= nx < bw and not seen[ny, nx] \
                    and counts[ny, nx] > 0:
                seen[ny, nx] = True
                stack.append((ny, nx))
    ys = [c[0] for c in comp]
    xs = [c[1] for c in comp]
    y0, y1 = min(ys) * block, (max(ys) + 1) * block
    x0, x1 = min(xs) * block, (max(xs) + 1) * block
    sub = mask[y0:y1, x0:x1]
    if not sub.any():
        return None
    # 粗网格会把边界扩出去最多 block 像素，还会把贴着实心块的零星噪点包进来。
    # 用行/列投影把边框收紧到"命中数显著"的那一段（实心块的内部行列计数远高于
    # 噪点行列），否则一个 140x60 的按钮会被量成 147x87、密度被拉低。
    rows = sub.sum(axis=1)
    cols = sub.sum(axis=0)
    r_thr = max(2.0, rows.max() * 0.25)
    c_thr = max(2.0, cols.max() * 0.25)
    ry = np.nonzero(rows >= r_thr)[0]
    rx = np.nonzero(cols >= c_thr)[0]
    if ry.size == 0 or rx.size == 0:
        return None
    ry0, ry1 = y0 + int(ry[0]), y0 + int(ry[-1])
    rx0, rx1 = x0 + int(rx[0]), x0 + int(rx[-1])
    density = float(mask[ry0:ry1 + 1, rx0:rx1 + 1].mean())
    return (rx0, ry0, rx1, ry1, density)


def match_color(frame, rgb, roi=None, tolerance=24, min_pixels=40):
    """色块匹配：找出与目标颜色接近的**最大连通块**，返回 `[Match, ...]`。

    比模板匹配便宜得多，适合"血条 / 进度条 / 纯色按钮亮起"这类判据。
    得分用连通块包围盒内的**像素密度**（0~1），语义与模板匹配的得分对齐。
    """
    if frame is None:
        return []
    sub, (ox, oy) = crop_roi(frame, roi)
    target = np.array(rgb[:3], dtype=np.int16)
    diff = np.abs(sub.astype(np.int16) - target).max(axis=2)
    mask = diff <= int(tolerance)
    if int(mask.sum()) < int(min_pixels):
        return []
    blob = _largest_blob_bbox(mask)
    if blob is None:
        return []
    x0, y0, x1, y1, density = blob
    return [Match(x0 + ox, y0 + oy, x1 - x0 + 1, y1 - y0 + 1, density)]


def load_template(path):
    """读模板图（PNG/JPG），统一成 RGB uint8 ndarray；失败返回 None。"""
    try:
        with Image.open(path) as img:
            return np.asarray(img.convert("RGB"), dtype=np.uint8)
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------------- #
# ③ 决策：声明式任务管线（仿 MAA tasks.json）
# ---------------------------------------------------------------------- #
#: 支持的识别算法（OcrDetect 留位不实现，见模块头说明）
ALGORITHMS = ("TemplateMatch", "ColorMatch", "OcrDetect")
#: 支持的动作
ACTIONS = ("ClickSelf", "Click", "Log", "None")


class Node:
    """任务管线里的一个节点。

    字段命名尽量与 MAA `tasks.json` 对齐（`next` / `exceededNext` /
    `maxTimes` / `preDelay` / `postDelay` / `roi` / `template` /
    `threshold`），便于对照阅读。
    """

    __slots__ = ("name", "algorithm", "template", "roi", "threshold", "color",
                 "color_tolerance", "action", "click", "next", "exceeded_next",
                 "max_times", "pre_delay", "post_delay", "note")

    def __init__(self, name, data):
        self.name = name
        self.algorithm = str(data.get("algorithm", "TemplateMatch"))
        self.template = str(data.get("template", "") or "")
        self.roi = data.get("roi") or None
        self.threshold = float(data.get("threshold", 0.8))
        self.color = data.get("color") or None
        self.color_tolerance = int(data.get("colorTolerance", 24))
        self.action = str(data.get("action", "None"))
        self.click = data.get("click") or None
        self.next = list(data.get("next") or [])
        self.exceeded_next = list(data.get("exceededNext") or [])
        self.max_times = max(1, int(data.get("maxTimes", 3)))
        self.pre_delay = int(data.get("preDelay", 0))
        self.post_delay = int(data.get("postDelay", 0))
        self.note = str(data.get("note", "") or "")


def parse_pipeline(data):
    """把 JSON（dict）解析成 `(nodes, errors)`。

    `nodes` 是 `OrderedDict[name] -> Node`；`errors` 是给页面显示的校验信息。
    """
    nodes = {}
    errors = []
    if not isinstance(data, dict) or not data:
        return nodes, ["任务为空：需要 {节点名: {algorithm, ...}, ...}"]
    for name, raw in data.items():
        if name.startswith("_"):          # 下划线开头当注释用
            continue
        if not isinstance(raw, dict):
            errors.append(f"节点「{name}」不是对象，已跳过")
            continue
        node = Node(name, raw)
        if node.algorithm not in ALGORITHMS:
            errors.append(f"节点「{name}」算法 {node.algorithm} 不支持")
        if node.action not in ACTIONS:
            errors.append(f"节点「{name}」动作 {node.action} 不支持")
        for nxt in list(node.next) + list(node.exceeded_next):
            if nxt not in data and not str(nxt).startswith("END"):
                errors.append(f"节点「{name}」指向了不存在的节点「{nxt}」")
        nodes[name] = node
    if not nodes:
        errors.append("没有可用节点")
    return nodes, errors


class StepResult:
    """一次节点识别的结果，供页面画框与写日志。"""

    __slots__ = ("node", "hit", "match", "action", "moved_to", "note", "cost_ms")

    def __init__(self, node, hit, match=None, action="", moved_to="",
                 note="", cost_ms=0.0):
        self.node = node
        self.hit = hit
        self.match = match
        self.action = action
        self.moved_to = moved_to
        self.note = note
        self.cost_ms = cost_ms


class PipelineRunner:
    """声明式状态机的执行器（无状态，可反复调用）。

    与 MAA 一致的语义：
      · 进节点先 `preDelay`，再按 `maxTimes` 重试识别；
      · 命中 → 执行 action → `postDelay` → 转移到 `next[0]`（`next` 为空 =
        任务成功结束）；
      · 始终未命中 → 转移到 `exceededNext[0]`（为空 = 任务失败结束）——
        这就是 MAA 的熔断兜底，防死循环。
    """

    def __init__(self, frame_provider, template_dir="", on_log=None):
        #: frame_provider(win) -> (frame, origin) 由调用方提供（页面持有窗口）
        self.frame_provider = frame_provider
        self.template_dir = template_dir
        self.on_log = on_log or (lambda *_a, **_k: None)

    # -- 内部：识别单个节点 ------------------------------------------- #
    def recognize(self, node, frame):
        """按节点配置识别，返回按得分降序的 `[Match, ...]`。

        `threshold` 对两种算法语义一致（都是 0~1 的得分门限）：
        模板匹配比的是 NCC 得分，色块比的是连通块内的像素密度。
        """
        if node.algorithm == "ColorMatch":
            if not node.color:
                return []
            hits = match_color(frame, node.color, node.roi,
                               node.color_tolerance)
            return [m for m in hits if m.score >= node.threshold]
        if node.algorithm == "OcrDetect":
            self.on_log(f"  · {node.name}: OcrDetect 为占位实现，本 demo 未接 OCR")
            return []
        path = node.template
        if path and not os.path.isabs(path) and self.template_dir:
            path = os.path.join(self.template_dir, path)
        tpl = load_template(path) if path else None
        if tpl is None:
            self.on_log(f"  · {node.name}: 模板缺失或不可读（{node.template}）")
            return []
        return match_template(frame, tpl, node.roi, node.threshold)

    # -- 对外：单步 / 整条 --------------------------- #
    def step(self, node, frame, dry_run=True, origin=(0, 0)):
        """执行一个节点（识别 + 动作），返回 StepResult。"""
        if node.pre_delay:
            time.sleep(node.pre_delay / 1000.0)
        t0 = time.time()
        matches = self.recognize(node, frame)
        cost = (time.time() - t0) * 1000.0
        if not matches:
            self.on_log(f"  ✗ {node.name}: 未命中（{node.algorithm}，"
                        f"{cost:.0f}ms）")
            return StepResult(node, False, None, "", "", "未命中", cost)

        best = matches[0]
        note = f"命中 {len(matches)} 处，最高 {best.score:.3f}"
        self.on_log(f"  ✓ {node.name}: {note} @ {best.as_roi()}")
        acted = ""
        if node.action == "ClickSelf":
            cx, cy = best.center
            sx, sy = origin[0] + cx, origin[1] + cy
            if dry_run:
                acted = f"演练：本应点击屏幕 ({sx},{sy})"
            else:
                click(sx, sy)
                acted = f"已点击屏幕 ({sx},{sy})"
        elif node.action == "Click":
            if node.click and len(node.click) >= 2:
                sx = origin[0] + int(node.click[0])
                sy = origin[1] + int(node.click[1])
                if dry_run:
                    acted = f"演练：本应点击屏幕 ({sx},{sy})"
                else:
                    click(sx, sy)
                    acted = f"已点击屏幕 ({sx},{sy})"
            else:
                acted = "Click 动作缺少 click:[x,y]"
        elif node.action == "Log":
            acted = "仅记录"
        if acted:
            self.on_log(f"    → {acted}")
        if node.post_delay:
            time.sleep(node.post_delay / 1000.0)
        return StepResult(node, True, best, acted, "", note, cost)

    def run(self, pipeline, entry=None, win=None, dry_run=True,
            max_steps=40):
        """跑完整条管线，返回 `[StepResult, ...]`（含未命中的步骤）。

        识别所需的画面**每个节点重新抓一次**（MAA 也是每步重新截图），
        但同一次 run 内复用同一个窗口句柄。
        """
        nodes, errors = parse_pipeline(pipeline)
        for e in errors:
            self.on_log(f"⚠ {e}")
        if not nodes:
            return []
        cur = entry or next(iter(nodes))
        trace = []
        for i in range(int(max_steps)):
            node = nodes.get(cur)
            if node is None:
                self.on_log(f"节点「{cur}」不存在，结束")
                break
            frame, origin, _ = self.frame_provider(win)
            if frame is None:
                self.on_log("抓帧失败，结束")
                break
            self.on_log(f"[{i + 1}] 执行节点「{node.name}」"
                        f"{'（' + node.note + '）' if node.note else ''}")
            res = self.step(node, frame, dry_run=dry_run, origin=origin)
            trace.append(res)

            if res.hit:
                if not node.next:
                    self.on_log(f"节点「{node.name}」无 next → 任务成功结束")
                    res.moved_to = ""
                    break
                nxt = node.next[0]
            else:
                if not node.exceeded_next:
                    self.on_log(f"节点「{node.name}」重试耗尽且无 exceededNext "
                                f"→ 任务失败结束")
                    break
                nxt = node.exceeded_next[0]
            if str(nxt).upper().startswith("END"):
                self.on_log(f"转移到 {nxt} → 结束")
                res.moved_to = nxt
                break
            res.moved_to = nxt
            self.on_log(f"    ⇢ 转移到「{nxt}」")
            cur = nxt
        else:
            self.on_log("达到步数上限，强制结束（防死循环）")
        return trace


# ---------------------------------------------------------------------- #
# ④ 行动：鼠标注入（Windows SendInput，绝对坐标）
# ---------------------------------------------------------------------- #
class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wt.LONG), ("dy", wt.LONG), ("mouseData", wt.DWORD),
                ("dwFlags", wt.DWORD), ("time", wt.DWORD),
                ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]


class _INPUT(ctypes.Structure):
    _fields_ = [("type", wt.DWORD), ("mi", _MOUSEINPUT)]


def click(x, y):
    """把鼠标移到 (x, y) 并左键单击（屏幕物理坐标）。

    用 SendInput + `MOUSEEVENTF_VIRTUALDESK` 归一化到**虚拟桌面**，多屏 /
    负坐标副屏下也对。失败返回 False。
    """
    try:
        user32 = ctypes.windll.user32
        vx = user32.GetSystemMetrics(76)      # SM_XVIRTUALSCREEN
        vy = user32.GetSystemMetrics(77)      # SM_YVIRTUALSCREEN
        vw = max(1, user32.GetSystemMetrics(78))
        vh = max(1, user32.GetSystemMetrics(79))
        nx = int(round((x - vx) * 65535.0 / vw))
        ny = int(round((y - vy) * 65535.0 / vh))
        flags_move = 0x0001 | 0x8000 | 0x4000  # MOVE | ABSOLUTE | VIRTUALDESK
        seq = (_INPUT * 3)()
        seq[0].type = 0                       # INPUT_MOUSE
        seq[0].mi = _MOUSEINPUT(nx, ny, 0, flags_move, 0, None)
        seq[1].type = 0
        seq[1].mi = _MOUSEINPUT(0, 0, 0, 0x0002, 0, None)   # LEFTDOWN
        seq[2].type = 0
        seq[2].mi = _MOUSEINPUT(0, 0, 0, 0x0004, 0, None)   # LEFTUP
        sent = user32.SendInput(3, ctypes.byref(seq), ctypes.sizeof(_INPUT))
        return sent == 3
    except Exception:  # noqa: BLE001
        return False


# ---------------------------------------------------------------------- #
# 内置演示管线：不依赖任何外部素材，直接跑「找到图标 → 点它」
# ---------------------------------------------------------------------- #
#: 页面「内置演示场景」用的任务（模板由页面从自绘图标现渲染，见 auto_vision_page）
DEMO_PIPELINE = {
    "_说明": "仿 MAA tasks.json 的最小管线：感知 → 识别 → 点击 → 复核 → 结束",
    "FindTarget": {
        "algorithm": "TemplateMatch",
        "template": "__demo_target__.png",
        "roi": [0, 0, 0, 0],
        "threshold": 0.75,
        "action": "ClickSelf",
        "next": ["Verify"],
        "exceededNext": ["NotFound"],
        "maxTimes": 2,
        "postDelay": 120,
        "note": "全屏范围找目标图标并点它",
    },
    "Verify": {
        "algorithm": "ColorMatch",
        "color": [245, 196, 84],
        "colorTolerance": 40,
        "roi": [0, 0, 0, 0],
        "threshold": 0.35,
        "action": "Log",
        "next": [],
        "maxTimes": 2,
        "note": "复核：图标主色块还在 → 任务成功结束",
    },
    "NotFound": {
        "algorithm": "ColorMatch",
        "color": [30, 34, 40],
        "colorTolerance": 12,
        "roi": [0, 0, 0, 0],
        "threshold": 0.5,
        "action": "Log",
        "next": [],
        "maxTimes": 1,
        "note": "熔断兜底：没找到目标时走这里，确认仍在场景后结束",
    },
}


def demo_pipeline_text():
    """给页面预填的 JSON 文本（保留注释键，便于用户照着改）。"""
    import json as _json
    return _json.dumps(DEMO_PIPELINE, ensure_ascii=False, indent=2)
