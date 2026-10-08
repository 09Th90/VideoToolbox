#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# @version 1.17.0
"""视觉自动化引擎 —— 参考 MAA（MaaAssistantArknights）的四段设计
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

本模块把同一套骨架做成**与具体应用无关**的最小实现，供 B 站自动投稿
（`bili_upload.py`）使用：

  · `list_windows()` / `capture_window()`       —— 感知：枚举窗口 + 客户区抓帧
  · `match_template()` / `match_color()`        —— 认知：FFT 归一化互相关 / 色块
  · `parse_pipeline()` / `PipelineRunner`       —— 决策：声明式节点 + 熔断转移
  · `click()`                                   —— 行动：SendInput 绝对坐标点击

与 MAA 的差异（有意为之，最小实现）：
  1. 识别只做**模板匹配 + 色块**，OCR / 神经网络留接口不实现——不引第三方
     模型（本机没装 opencv，也不想为此增加依赖）；
  2. 模板匹配用 numpy FFT 算归一化互相关（NCC），对亮度线性变化不敏感，
     与 OpenCV `TM_CCOEFF_NORMED` 同源；
  3. **默认演练（dry-run）**：只识别、只标注，不真的点鼠标；要真点必须在页面上
     显式打开开关。MAA 的边界说明同样适用——自动化别人家的界面属于灰色地带。

v1.17.0 扩展（为「B 站自动投稿」补动作，见 `bili_upload.py`）：
  原 demo 只有 `ClickSelf/Click/Log/None` 四个动作，够点按钮、不够填表单。投稿
  这类「长尾 RPA」还差三样，这里按 MAA 的动作命名补齐：

  · `TypeText`  往当前焦点输入框打字（`text` 支持 `{{变量}}`；默认走剪贴板粘贴，
                对中文/IME 更稳，`method:"type"` 可切逐字符 SendInput Unicode）；
  · `Key`       按键/组合键（`keys:"ctrl+a"`、`"enter"`、`"tab"`…）；
  · `Scroll`    滚轮（`scroll:[dx,dy]`，用于下拉浮层翻页）；
  · `Wait`      纯等待（`wait` 毫秒，用于等转码/等渲染）；
  · `Activate`  把目标窗口提到前台（真点前必须先激活，否则点的是别的窗口）。

  同时补两处工程必需：① 管线字符串统一支持 `{{变量}}` 替换（`PipelineRunner`
  的 `vars` 参数），任务字段（视频路径/标题/标签…）由此注入声明式管线；
  ② `maxTimes` 变成**真重试**——未命中时重新抓帧再试，配合 `preDelay` 即可表达
  「等某个元素出现」；重试耗尽才走 `exceededNext`。

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

    `list_windows()` 有意把本程序的窗口滤掉（避免"自己抓自己"），需要按句柄
    取本进程或未出现在枚举结果里的窗口时，走这条通道。非 Windows 返回 None。
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
#: 支持的识别算法（OcrDetect 留位不实现，见模块头说明）。
#: `None` / `JustReturn` = **不做识别、恒命中**——给「只执行动作」的节点用
#: （Wait / Activate / TypeText / Key），语义对齐 MAA 的 `JustReturn`。
ALGORITHMS = ("TemplateMatch", "ColorMatch", "OcrDetect", "None", "JustReturn")
#: 支持的动作（v1.17.0 补 TypeText/Key/Scroll/Wait/Activate，见模块头说明）
ACTIONS = ("ClickSelf", "Click", "TypeText", "Key", "Scroll", "Wait",
           "Activate", "Log", "None")


class Node:
    """任务管线里的一个节点。

    字段命名尽量与 MAA `tasks.json` 对齐（`next` / `exceededNext` /
    `maxTimes` / `preDelay` / `postDelay` / `roi` / `template` /
    `threshold`），便于对照阅读。
    """

    __slots__ = ("name", "algorithm", "template", "roi", "threshold", "color",
                 "color_tolerance", "action", "click", "text", "keys", "scroll",
                 "wait", "method", "window", "next", "exceeded_next",
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
        # ---- v1.17.0：输入 / 等待 / 激活动作的参数（见模块头说明）----
        self.text = data.get("text")            # TypeText：要输入的文字（支持 {{变量}}）
        self.keys = data.get("keys")            # Key：键名或组合，如 "ctrl+a" / ["ctrl","a"]
        self.scroll = data.get("scroll")        # Scroll：[dx, dy] 或单个 dy
        self.wait = int(data.get("wait", 0) or 0)   # Wait：等待毫秒
        self.method = str(data.get("method", "paste") or "paste")  # 输入方式
        self.window = str(data.get("window", "") or "")            # Activate：窗口标题关键字
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


#: 一次 run 内两次识别尝试之间的最小间隔（毫秒）。配合 preDelay 即可表达
#: 「等某个元素出现」：preDelay=800 + maxTimes=15 ≈ 最多等 12 秒。
_RETRY_INTERVAL_MS = 200


def substitute(value, vars):
    """把字符串里的 `{{name}}` 递归替换成 `vars[name]`（未定义的原样保留）。

    作用于 str / list / dict——管线 JSON 里任何字段（template / text /
    keys / click / note …）都能写变量。任务字段（视频路径 / 标题 / 标签）
    由此注入声明式管线，无需为每个任务改 JSON。
    """
    if isinstance(value, str):
        if "{{" not in value:
            return value
        out = value
        for k, v in (vars or {}).items():
            out = out.replace("{{" + str(k) + "}}", str(v))
        return out
    if isinstance(value, list):
        return [substitute(v, vars) for v in value]
    if isinstance(value, dict):
        return {k: substitute(v, vars) for k, v in value.items()}
    return value


class PipelineRunner:
    """声明式状态机的执行器（无状态，可反复调用）。

    与 MAA 一致的语义：
      · 进节点先 `preDelay`，再按 `maxTimes` 重试识别（每次重试重新抓帧）；
      · 命中 → 执行 action → `postDelay` → 转移到 `next[0]`（`next` 为空 =
        任务成功结束）；
      · 重试耗尽仍不命中 → 转移到 `exceededNext[0]`（为空 = 任务失败结束）——
        这就是 MAA 的熔断兜底，防死循环。
    """

    def __init__(self, frame_provider, template_dir="", on_log=None, vars=None,
                 on_stage=None):
        #: frame_provider(win) -> (frame, origin) 由调用方提供（页面持有窗口）
        self.frame_provider = frame_provider
        self.template_dir = template_dir
        self.on_log = on_log or (lambda *_a, **_k: None)
        #: 阶段回调 on_stage(node_name)：每开始执行一个节点前调用一次，
        #: 供界面显示「当前阶段」；抛异常只忽略，不影响管线本身。
        self.on_stage = on_stage
        #: 变量表：管线里的 `{{name}}` 用它替换（run(vars=...) 可再覆盖）
        self.vars = dict(vars or {})

    def _v(self, value):
        """按当前变量表展开一个字段值。"""
        return substitute(value, self.vars)

    # -- 内部：识别单个节点 ------------------------------------------- #
    def recognize(self, node, frame):
        """按节点配置识别，返回按得分降序的 `[Match, ...]`。

        `threshold` 对两种算法语义一致（都是 0~1 的得分门限）：
        模板匹配比的是 NCC 得分，色块比的是连通块内的像素密度。
        `algorithm` 为 `None`/`JustReturn` 时不做识别、恒命中（整帧框）。
        """
        if node.algorithm in ("None", "JustReturn"):
            if frame is None:
                return []
            h, w = frame.shape[:2]
            return [Match(0, 0, int(w), int(h), 1.0)]
        if node.algorithm == "ColorMatch":
            if not node.color:
                return []
            hits = match_color(frame, node.color, node.roi,
                               node.color_tolerance)
            return [m for m in hits if m.score >= node.threshold]
        if node.algorithm == "OcrDetect":
            self.on_log(f"  · {node.name}: OcrDetect 为占位实现，本 demo 未接 OCR")
            return []
        path = str(self._v(node.template))
        if path and not os.path.isabs(path) and self.template_dir:
            path = os.path.join(self.template_dir, path)
        tpl = load_template(path) if path else None
        if tpl is None:
            self.on_log(f"  · {node.name}: 模板缺失或不可读（{node.template}）")
            return []
        return match_template(frame, tpl, node.roi, node.threshold)

    # -- 内部：执行动作 ----------------------------------------------- #
    def _do_action(self, node, best, frame, origin, win, dry_run):
        """执行节点的 action，返回给日志用的一句话。"""
        act = node.action
        if act == "Log":
            return "仅记录"
        if act == "None":
            return ""

        if act in ("ClickSelf", "Click"):
            if act == "ClickSelf":
                cx, cy = best.center
                sx, sy = origin[0] + cx, origin[1] + cy
            else:
                if not (node.click and len(node.click) >= 2):
                    return "Click 动作缺少 click:[x,y]"
                spec = self._v(node.click)
                sx = origin[0] + int(spec[0])
                sy = origin[1] + int(spec[1])
            if dry_run:
                return f"演练：本应点击屏幕 ({sx},{sy})"
            return (f"已点击屏幕 ({sx},{sy})" if click(sx, sy)
                    else f"点击失败 ({sx},{sy})")

        if act == "TypeText":
            text = str(self._v(node.text) or "")
            if not text:
                return "TypeText 缺少 text"
            if dry_run:
                return f"演练：本应输入「{text}」"
            ok = (type_text(text) if node.method == "type"
                  else paste_text(text))
            return f"已输入「{text}」" if ok else f"输入失败「{text}」"

        if act == "Key":
            keys = self._v(node.keys)
            if not keys:
                return "Key 缺少 keys"
            if dry_run:
                return f"演练：本应按键 {keys}"
            ok = press_key(keys)
            return f"已按键 {keys}" if ok else f"按键失败 {keys}"

        if act == "Scroll":
            dx, dy = _scroll_delta(self._v(node.scroll))
            if win is not None:
                px, py = _window_center(win)
            else:
                h, w = (frame.shape[:2] if frame is not None else (0, 0))
                px, py = origin[0] + w // 2, origin[1] + h // 2
            if dry_run:
                return f"演练：本应在 ({px},{py}) 滚动 ({dx},{dy})"
            ok = scroll(dx, dy, px, py)
            return (f"已在 ({px},{py}) 滚动 ({dx},{dy})" if ok
                    else "滚动失败")

        if act == "Wait":
            ms = int(node.wait or 0)
            if dry_run:
                return f"演练：本应等待 {ms}ms"
            time.sleep(ms / 1000.0)
            return f"已等待 {ms}ms"

        if act == "Activate":
            if win is None:
                return "Activate 需要目标窗口（win 为空）"
            if dry_run:
                return f"演练：本应激活窗口「{win.title[:30]}」"
            ok = activate_window(win.hwnd)
            return (f"已激活窗口「{win.title[:30]}」" if ok
                    else "激活窗口失败")

        return f"未知动作 {act}"

    # -- 对外：单步 / 整条 --------------------------- #
    def step(self, node, frame, dry_run=True, origin=(0, 0), win=None):
        """执行一个节点（识别 + 动作），返回 StepResult（单次识别，不重试）。"""
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
        acted = self._do_action(node, best, frame, origin, win, dry_run)
        if acted:
            self.on_log(f"    → {acted}")
        if node.post_delay:
            time.sleep(node.post_delay / 1000.0)
        return StepResult(node, True, best, acted, "", note, cost)

    def run(self, pipeline, entry=None, win=None, dry_run=True,
            max_steps=40, vars=None):
        """跑完整条管线，返回 `[StepResult, ...]`（含未命中的步骤）。

        识别所需的画面**每个节点重新抓一次**（MAA 也是每步重新截图），
        未命中时按 `maxTimes` 重新抓帧重试；同一次 run 内复用同一个窗口句柄。
        `vars` 会合并进变量表（供管线里的 `{{name}}` 展开）。
        """
        nodes, errors = parse_pipeline(pipeline)
        for e in errors:
            self.on_log(f"⚠ {e}")
        if not nodes:
            return []
        if vars:
            self.vars.update(vars)
        cur = entry or next(iter(nodes))
        trace = []
        for i in range(int(max_steps)):
            node = nodes.get(cur)
            if node is None:
                self.on_log(f"节点「{cur}」不存在，结束")
                break
            self.on_log(f"[{i + 1}] 执行节点「{node.name}」"
                        f"{'（' + node.note + '）' if node.note else ''}")
            if self.on_stage is not None:
                try:
                    self.on_stage(node.name)
                except Exception:  # noqa: BLE001
                    pass
            res = None
            tries = max(1, node.max_times)
            for attempt in range(tries):
                frame, origin, _ = self.frame_provider(win)
                if frame is None:
                    self.on_log("抓帧失败，结束")
                    break
                res = self.step(node, frame, dry_run=dry_run,
                                origin=origin, win=win)
                if res.hit:
                    break
                if attempt + 1 < tries:
                    self.on_log(f"  ↻ 重试 {attempt + 2}/{tries}（重新抓帧）")
                    time.sleep(_RETRY_INTERVAL_MS / 1000.0)
            if res is None:
                break
            trace.append(res)

            if res.hit:
                if not node.next:
                    self.on_log(f"节点「{node.name}」无 next → 任务成功结束")
                    res.moved_to = ""
                    break
                nxt = self._v(node.next[0])
            else:
                if not node.exceeded_next:
                    self.on_log(f"节点「{node.name}」重试耗尽且无 exceededNext "
                                f"→ 任务失败结束")
                    break
                nxt = self._v(node.exceeded_next[0])
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
# ④ 行动：鼠标 / 键盘注入（Windows SendInput，绝对坐标）
# ---------------------------------------------------------------------- #
class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wt.LONG), ("dy", wt.LONG), ("mouseData", wt.DWORD),
                ("dwFlags", wt.DWORD), ("time", wt.DWORD),
                ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wt.WORD), ("wScan", wt.WORD), ("dwFlags", wt.DWORD),
                ("time", wt.DWORD),
                ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]


class _HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wt.DWORD), ("wParamL", wt.WORD), ("wParamH", wt.WORD)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", _MOUSEINPUT), ("ki", _KEYBDINPUT),
                ("hi", _HARDWAREINPUT)]


class _INPUT(ctypes.Structure):
    """SendInput 的 INPUT 结构。

    ⚠ 必须用 **union**（鼠标/键盘/硬件三种输入共用一个结构）。若给键盘另建
    一个只有 type+KEYBDINPUT 的小结构，`cbSize` 就对不上（x64 上 INPUT 是
    40 字节），SendInput 会整批拒绝（返回 0），表现为「键盘注入毫无反应」。
    """
    _fields_ = [("type", wt.DWORD), ("u", _INPUTUNION)]


_INPUT_MOUSE = 0
_INPUT_KEYBOARD = 1

_MOUSEEVENTF_MOVE = 0x0001
_MOUSEEVENTF_LEFTDOWN = 0x0002
_MOUSEEVENTF_LEFTUP = 0x0004
_MOUSEEVENTF_WHEEL = 0x0800
_MOUSEEVENTF_ABSOLUTE = 0x8000
_MOUSEEVENTF_VIRTUALDESK = 0x4000
_WHEEL_DELTA = 120

_KEYEVENTF_KEYUP = 0x0002
_KEYEVENTF_UNICODE = 0x0004


def _screen_to_abs(x, y):
    """屏幕物理坐标 → SendInput 绝对坐标（0~65535，归一化到虚拟桌面）。"""
    user32 = ctypes.windll.user32
    vx = user32.GetSystemMetrics(76)      # SM_XVIRTUALSCREEN
    vy = user32.GetSystemMetrics(77)      # SM_YVIRTUALSCREEN
    vw = max(1, user32.GetSystemMetrics(78))
    vh = max(1, user32.GetSystemMetrics(79))
    return (int(round((x - vx) * 65535.0 / vw)),
            int(round((y - vy) * 65535.0 / vh)))


def _send_mouse(*events):
    """把一串 `_MOUSEINPUT` 交给 SendInput，返回是否全部成功。"""
    try:
        seq = (_INPUT * len(events))()
        for i, mi in enumerate(events):
            seq[i].type = _INPUT_MOUSE
            seq[i].u.mi = mi
        sent = ctypes.windll.user32.SendInput(
            len(events), ctypes.byref(seq), ctypes.sizeof(_INPUT))
        return sent == len(events)
    except Exception:  # noqa: BLE001
        return False


def move_to(x, y):
    """只移动鼠标（不点击），屏幕物理坐标。"""
    nx, ny = _screen_to_abs(x, y)
    return _send_mouse(_MOUSEINPUT(
        nx, ny, 0, _MOUSEEVENTF_MOVE | _MOUSEEVENTF_ABSOLUTE
        | _MOUSEEVENTF_VIRTUALDESK, 0, None))


def click(x, y):
    """把鼠标移到 (x, y) 并左键单击（屏幕物理坐标）。

    用 SendInput + `MOUSEEVENTF_VIRTUALDESK` 归一化到**虚拟桌面**，多屏 /
    负坐标副屏下也对。失败返回 False。
    """
    nx, ny = _screen_to_abs(x, y)
    return _send_mouse(
        _MOUSEINPUT(nx, ny, 0, _MOUSEEVENTF_MOVE | _MOUSEEVENTF_ABSOLUTE
                    | _MOUSEEVENTF_VIRTUALDESK, 0, None),
        _MOUSEINPUT(0, 0, 0, _MOUSEEVENTF_LEFTDOWN, 0, None),
        _MOUSEINPUT(0, 0, 0, _MOUSEEVENTF_LEFTUP, 0, None))


def scroll(dx=0, dy=-3, x=None, y=None):
    """滚轮滚动：一个「格」= 120，dy>0 向上、dy<0 向下。

    若给了 (x, y) 先把鼠标移过去——滚轮作用在**光标所在窗口**，位置不对
    就会滚到别的窗口。返回是否成功。
    """
    if x is not None and y is not None:
        move_to(x, y)
    events = []
    if dx:
        events.append(_MOUSEINPUT(0, 0, int(dx) * _WHEEL_DELTA,
                                  _MOUSEEVENTF_WHEEL, 0, None))
    if dy:
        events.append(_MOUSEINPUT(0, 0, int(dy) * _WHEEL_DELTA,
                                  _MOUSEEVENTF_WHEEL, 0, None))
    if not events:
        return True
    return _send_mouse(*events)


def _scroll_delta(spec):
    """解析 `scroll` 字段：[dx, dy] / 单值 dy / None → (dx, dy)。"""
    if spec is None:
        return (0, -3)
    if isinstance(spec, (int, float)):
        return (0, int(spec))
    try:
        seq = [int(v) for v in spec]
    except (TypeError, ValueError):
        return (0, -3)
    if len(seq) >= 2:
        return (seq[0], seq[1])
    if seq:
        return (0, seq[0])
    return (0, -3)


def _window_center(win):
    """窗口客户区中心（屏幕物理坐标）。"""
    l, t, r, b = win.client_rect
    return (int((l + r) / 2), int((t + b) / 2))


# ---- 键盘 --------------------------------------------------------------- #
_VK_NAMES = {
    "enter": 0x0D, "return": 0x0D, "tab": 0x09, "esc": 0x1B, "escape": 0x1B,
    "space": 0x20, "backspace": 0x08, "delete": 0x2E, "del": 0x2E,
    "insert": 0x2D, "home": 0x24, "end": 0x23, "pageup": 0x21,
    "pagedown": 0x22, "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
    "ctrl": 0x11, "control": 0x11, "alt": 0x12, "shift": 0x10, "win": 0x5B,
}
_VK_NAMES.update({f"f{i}": 0x6F + i for i in range(1, 13)})
_VK_NAMES.update({chr(c): c - 32 for c in range(ord("a"), ord("z") + 1)})
_VK_NAMES.update({str(d): 0x30 + d for d in range(10)})

#: 组合键里的修饰键（按固定顺序先按下、最后松开）
_MODIFIER_KEYS = ("ctrl", "control", "alt", "shift", "win")


def _vk_of(name):
    """键名 → 虚拟键码；认不出来返回 None。"""
    key = str(name).strip().lower()
    if key in _VK_NAMES:
        return _VK_NAMES[key]
    if len(key) == 1:
        return ord(key.upper())
    return None


def _send_keys(vk_events):
    """vk_events: [(vk, up_bool), ...] → SendInput，返回是否全部成功。"""
    try:
        seq = (_INPUT * len(vk_events))()
        for i, (vk, up) in enumerate(vk_events):
            seq[i].type = _INPUT_KEYBOARD
            seq[i].u.ki = _KEYBDINPUT(int(vk), 0,
                                      _KEYEVENTF_KEYUP if up else 0, 0, None)
        sent = ctypes.windll.user32.SendInput(
            len(vk_events), ctypes.byref(seq), ctypes.sizeof(_INPUT))
        return sent == len(vk_events)
    except Exception:  # noqa: BLE001
        return False


def press_key(spec):
    """按键或组合键。

    spec 可为字符串 `"ctrl+a"` / `"enter"`，也可为列表 `["ctrl","a"]`。
    修饰键先按下、主键随后按下、松开顺序相反。
    """
    if isinstance(spec, str):
        parts = [p for p in spec.replace("+", " ").split() if p]
    elif isinstance(spec, (list, tuple)):
        parts = [str(p) for p in spec]
    else:
        return False
    vks = [_vk_of(p) for p in parts]
    if not vks or any(v is None for v in vks):
        return False
    mods = [v for p, v in zip(parts, vks) if p.lower() in _MODIFIER_KEYS]
    main = [v for p, v in zip(parts, vks) if p.lower() not in _MODIFIER_KEYS]
    events = [(v, False) for v in mods]
    events += [(v, False) for v in main]
    events += [(v, True) for v in reversed(main)]
    events += [(v, True) for v in reversed(mods)]
    return _send_keys(events)


def type_text(text):
    """逐字符注入文本（SendInput `KEYEVENTF_UNICODE`）。

    直接把码点送进焦点控件，**不经过输入法**——中文也会原样落到输入框，
    不会被候选框截胡。代理对（emoji 等）拆成两个 UTF-16 码元各发一次。
    """
    text = str(text or "")
    if not text:
        return True
    seq = []
    for ch in text:
        raw = ch.encode("utf-16-le")
        for i in range(0, len(raw), 2):
            unit = int.from_bytes(raw[i:i + 2], "little")
            seq.append((unit, False))
            seq.append((unit, True))
    try:
        arr = (_INPUT * len(seq))()
        for i, (scan, up) in enumerate(seq):
            arr[i].type = _INPUT_KEYBOARD
            arr[i].u.ki = _KEYBDINPUT(
                0, scan, _KEYEVENTF_UNICODE
                | (_KEYEVENTF_KEYUP if up else 0), 0, None)
        sent = ctypes.windll.user32.SendInput(
            len(seq), ctypes.byref(arr), ctypes.sizeof(_INPUT))
        return sent == len(seq)
    except Exception:  # noqa: BLE001
        return False


# ---- 剪贴板（粘贴式输入，中文/长文本更稳）-------------------------------- #
def set_clipboard_text(text):
    """写系统剪贴板文本。优先 win32clipboard，退回 ctypes。返回是否成功。"""
    text = str(text or "")
    if _HAS_WIN32:
        try:
            import win32clipboard
            win32clipboard.OpenClipboard()
            try:
                win32clipboard.EmptyClipboard()
                win32clipboard.SetClipboardData(
                    win32clipboard.CF_UNICODETEXT, text)
            finally:
                win32clipboard.CloseClipboard()
            return True
        except Exception:  # noqa: BLE001
            pass
    try:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        kernel32.GlobalAlloc.restype = ctypes.c_void_p
        kernel32.GlobalLock.restype = ctypes.c_void_p
        if not user32.OpenClipboard(None):
            return False
        try:
            user32.EmptyClipboard()
            buf = (text + "\0").encode("utf-16-le")
            handle = kernel32.GlobalAlloc(0x0002, len(buf))  # GMEM_MOVEABLE
            if not handle:
                return False
            ptr = kernel32.GlobalLock(handle)
            ctypes.memmove(ptr, buf, len(buf))
            kernel32.GlobalUnlock(handle)
            user32.SetClipboardData(13, handle)      # CF_UNICODETEXT
        finally:
            user32.CloseClipboard()
        return True
    except Exception:  # noqa: BLE001
        return False


def get_clipboard_text():
    """读系统剪贴板文本（拿不到返回 None）。"""
    if _HAS_WIN32:
        try:
            import win32clipboard
            win32clipboard.OpenClipboard()
            try:
                if win32clipboard.IsClipboardFormatAvailable(
                        win32clipboard.CF_UNICODETEXT):
                    return win32clipboard.GetClipboardData(
                        win32clipboard.CF_UNICODETEXT)
            finally:
                win32clipboard.CloseClipboard()
            return None
        except Exception:  # noqa: BLE001
            pass
    try:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        kernel32.GlobalLock.restype = ctypes.c_void_p
        if not user32.OpenClipboard(None):
            return None
        try:
            handle = user32.GetClipboardData(13)
            if not handle:
                return None
            ptr = kernel32.GlobalLock(handle)
            if not ptr:
                return None
            try:
                return ctypes.wstring_at(ptr)
            finally:
                kernel32.GlobalUnlock(handle)
        finally:
            user32.CloseClipboard()
    except Exception:  # noqa: BLE001
        return None


def paste_text(text, restore=True, settle=0.35):
    """剪贴板粘贴：写剪贴板 → Ctrl+V →（可选）恢复原剪贴板。

    中文标题、长简介、含特殊符号时比逐字符注入更稳（不受输入法影响）。

    ⚠ `settle` 不能省：Ctrl+V 只是把 WM_PASTE 投给**目标进程**，目标要等自己
    的消息循环跑到才去读剪贴板。若立刻恢复旧剪贴板，目标读到的就是旧内容
    （实测：粘出的是上一次的剪贴板）。0.35s 对浏览器这类独立进程足够；
    对同一进程内的控件（消息循环被本函数阻塞）则天然做不到，请改用
    `type_text`。
    """
    old = get_clipboard_text() if restore else None
    if not set_clipboard_text(text):
        return False
    time.sleep(0.05)
    ok = press_key("ctrl+v")
    time.sleep(max(0.0, float(settle)))
    if restore and old is not None:
        set_clipboard_text(old)
    return ok


# ---- 窗口激活 ----------------------------------------------------------- #
def activate_window(hwnd):
    """把窗口提到前台（必要时先还原最小化）。返回是否成功。

    `SetForegroundWindow` 在「调用进程不在前台」时会被系统拒绝，故补一条
    `AttachThreadInput` 借前台线程输入队列的经典兜底。
    """
    if not _HAS_WIN32:
        return False
    try:
        user32 = ctypes.windll.user32
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        if user32.SetForegroundWindow(hwnd):
            return True
        try:
            fg = user32.GetForegroundWindow()
            t1 = user32.GetWindowThreadProcessId(fg, None)
            t2 = user32.GetWindowThreadProcessId(hwnd, None)
            if t1 and t2 and t1 != t2:
                user32.AttachThreadInput(t1, t2, True)
                user32.BringWindowToTop(hwnd)
                ok = bool(user32.SetForegroundWindow(hwnd))
                user32.AttachThreadInput(t1, t2, False)
                return ok
        except Exception:  # noqa: BLE001
            pass
        return bool(user32.SetForegroundWindow(hwnd))
    except Exception:  # noqa: BLE001
        return False


# ---- 整屏抓帧 / 存图（失败留证）----------------------------------------- #
def grab_screen():
    """抓整块虚拟桌面（RGB ndarray）。失败返回 None。

    用于「与具体窗口无关」的留证截图——出错时目标窗口可能已跳转/关闭。
    """
    try:
        img = ImageGrab.grab(all_screens=True)
        return np.asarray(img.convert("RGB"), dtype=np.uint8)
    except Exception:  # noqa: BLE001
        return None


def save_frame(frame, path):
    """把帧存成 PNG（失败截图用）。返回路径，失败返回 None。"""
    if frame is None:
        return None
    try:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        Image.fromarray(frame).save(path)
        return path
    except Exception:  # noqa: BLE001
        return None
