# -*- coding: utf-8 -*-
# @version 3.1.2
"""无边框窗口边缘拖拽热区（原 video_toolbox_qt.py 同名代码，逐字下沉）。"""
from PySide6.QtCore import QAbstractNativeEventFilter

#: 无边框窗口的**边缘拖拽热区**（逻辑像素）。
#: 库默认用的是 BORDER_WIDTH 物理像素（5px），在 125%/150% 缩放下只剩 3~4 个
#: 逻辑像素，鼠标几乎点不中——用户反馈的「无法用鼠标调整窗口大小」即此。
#: 这里按设备像素比换算出一个宽容热区，四边/四角都能拖。
RESIZE_MARGIN = 8


class _ResizeHitFilter(QAbstractNativeEventFilter):
    """**应用级** WM_NCHITTEST 过滤器 —— 让「边框拖拽缩放」真正生效。

    为什么不能只在 `MainWindow.nativeEvent` 里做（v1.13.6 的关键修正）：
    mpv 通过 `wid` 嵌进 `video_host` 时会调用 `winId()`，Qt 随之把导航条 /
    标题栏 / 页面这些 widget 一并**提升成原生子窗口**。实测载入视频后多出
    二十多个 `Qt5152QWindowIcon` 子窗口，它们从窗口最边缘铺开，正好盖住
    `RESIZE_MARGIN` 那 8 逻辑像素的边框带。于是鼠标点在边框上时，
    WM_NCHITTEST 是发给**子窗口**的 —— `MainWindow.nativeEvent` 根本收不到，
    子窗口回 HTCLIENT，系统就不发起缩放。

    实测（`_workspace/probes/_diag_hittest3.py`，同一台机器同一份代码）：
        · 未载入视频：边框带上的点归属主窗口自己 -> 回 HTLEFT，能拖；
        · 载入视频后：归属某个原生子窗口      -> 子窗口回 HTCLIENT，拖不动；
        · 卸载视频后：那些子窗口还在（原生窗口一旦创建就不会撤销）
                      -> 依然拖不动。
    这正是用户反馈的「放入视频后无法调整窗口大小，视频没了也一样」。

    所以这里在应用级接住**所有** WM_NCHITTEST（含子窗口的消息），只按屏幕
    坐标判断该点是否落在主窗口的边框带上：
      · 只处理属于本窗口的消息（`GetAncestor(..., GA_ROOT)` 比对句柄），
        其它窗口与对话框原样放行；
      · 不在边缘时返回 False，交给 Qt 照常处理（按钮、拖拽、双击标题栏等
        都不受影响）。
    """

    def __init__(self, window):
        super().__init__()
        self._window = window

    def nativeEventFilter(self, eventType, message):
        try:
            # ⚠ eventType 在不同绑定/版本下可能是 str、bytes 或 QByteArray：
            #   原写法只与 bytes 比较，实测在 PySide6 下判定为不匹配 →
            #   整个 filter 立即 return，边缘热区失效，只剩 FramelessWindow
            #   nativeEvent 里的 BORDER_WIDTH（5 **物理**像素，@dpr2 仅 2.5
            #   逻辑像素）——鼠标几乎点不中，表现为用户反馈的
            #   「界面上下只能扩大、不能缩小」。这里做兼容归一化。
            et = eventType
            if isinstance(et, (bytes, bytearray)):
                et = et.decode("ascii", "ignore")
            elif hasattr(et, "data"):
                et = bytes(et.data()).decode("ascii", "ignore")
            elif not isinstance(et, str):
                et = str(et)
            if et not in ("windows_generic_MSG", "windows_dispatcher_MSG"):
                return False, 0
            win = self._window
            if win is None or not win.isVisible():
                return False, 0
            if not getattr(win, "_isResizeEnabled", True):
                return False, 0
            if win.isMaximized() or win.isFullScreen():
                return False, 0

            import ctypes
            from ctypes.wintypes import MSG
            import win32con
            import win32gui

            msg = MSG.from_address(int(message))
            if msg.message != win32con.WM_NCHITTEST:
                return False, 0
            hwnd = int(win.winId())
            if win32gui.GetAncestor(msg.hWnd, win32con.GA_ROOT) != hwnd:
                return False, 0
            rect = win32gui.GetWindowRect(hwnd)
            w, h = rect[2] - rect[0], rect[3] - rect[1]
            dpr = float(win.devicePixelRatioF() or 1.0)
            bw = max(5, int(round(RESIZE_MARGIN * dpr)))
            # 窗口本身就比热区大不了多少时不做命中，免得整窗都成了"边缘"
            if w <= bw * 4 or h <= bw * 4:
                return False, 0
            # lParam 是**屏幕物理坐标**（低 16 位 x、高 16 位 y）。
            # 这里不用 GetCursorPos()：它给的是"此刻"的鼠标位置，与消息
            # 携带的坐标在系统连发命中测试时并不一致。
            sx = ctypes.c_short(msg.lParam & 0xFFFF).value
            sy = ctypes.c_short((msg.lParam >> 16) & 0xFFFF).value
            # Win11「Snap 布局」：最大化按钮那一点必须回 HTMAXBUTTON，系统才会
            # 在悬停时弹出「选择布局」面板。按钮是自绘的（FluentTitleBarButton），
            # 系统本来认不出来，只能靠这一层告诉它。⚠ 与边缘同理：消息发给
            # 子窗口时回 HTTRANSPARENT，让系统继续往下找到主窗口再定夺。
            mb = getattr(getattr(win, "titleBar", None), "maxBtn", None)
            if mb is not None and mb.isVisible():
                tl = mb.mapToGlobal(mb.rect().topLeft())
                br = mb.mapToGlobal(mb.rect().bottomRight())
                tlx, tly = int(tl.x() * dpr), int(tl.y() * dpr)
                brx, bry = int(br.x() * dpr), int(br.y() * dpr)
                if tlx <= sx <= brx and tly <= sy <= bry:
                    if msg.hWnd != hwnd:
                        return True, win32con.HTTRANSPARENT
                    return True, win32con.HTMAXBUTTON
            left = sx < rect[0] + bw
            right = sx > rect[2] - bw
            top = sy < rect[1] + bw
            bottom = sy > rect[3] - bw
            hit = None
            if left and top:
                hit = win32con.HTTOPLEFT
            elif right and bottom:
                hit = win32con.HTBOTTOMRIGHT
            elif right and top:
                hit = win32con.HTTOPRIGHT
            elif left and bottom:
                hit = win32con.HTBOTTOMLEFT
            elif left:
                hit = win32con.HTLEFT
            elif right:
                hit = win32con.HTRIGHT
            elif top:
                hit = win32con.HTTOP
            elif bottom:
                hit = win32con.HTBOTTOM
            if hit is None:
                return False, 0
            # ⚠️ 关键中的关键：这条消息可能是发给**子窗口**的（载入视频后 Qt 把
            #    导航条 / 标题栏 / 页面提升成了原生子窗口）。把 NCHITTEST 改成
            #    HTLEFT 只能骗到**光标**（变成双向箭头），真正按下时
            #    WM_NCLBUTTONDOWN 还是落到那个子窗口上，系统不会进入缩放循环 ——
            #    用户看到的就是「光标对了，但拖不动，大小不变」。
            #    回 HTTRANSPARENT 才是正解：告诉系统"这个点当作透明"，系统会
            #    继续在**同一线程**里往下找窗口，最终由主窗口接手，于是
            #    NCLBUTTONDOWN / SIZING / SIZE 全都走主窗口，缩放才真能进行。
            if msg.hWnd != hwnd:
                return True, win32con.HTTRANSPARENT
            return True, hit
        except Exception:  # noqa: BLE001
            # 任何意外都退回 Qt 的默认处理，绝不因为命中测试把程序搞崩
            return False, 0