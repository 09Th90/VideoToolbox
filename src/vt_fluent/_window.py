# -*- coding: utf-8 -*-
# @version 2.7.0
"""vt_fluent 窗口与导航（自研，替代 qfluentwidgets.window + navigation）。

行为契约（对齐上游 1.11.3）：
· FluentWindow：无边框窗口 + Windows 11 Mica 背景（DWM 系统背景，非 Mica
  环境自动回落实底）+ 48px 标题栏（图标/标题/最小化/最大化/关闭）+
  左侧导航 + 右侧 StackedWidget；addSubInterface/switchTo/removeInterface/
  setMicaEffectEnabled/titleBar/navigationInterface/stackedWidget；
· NavigationInterface：竖向导航（展开 312 / 紧凑 48，可折叠，滚动承载，
  底部分隔项），addItem/addWidget/addSeparator/setCurrentItem/expand/toggle/
  setExpandWidth/setMinimumExpandWidth/setCollapsible/widget/removeWidget；
· NavigationWidget：40×36（紧凑）/312×36（展开）自绘导航项
  （图标 16×16@11.5,10、文字 @44、选中指示条 3×16 圆角 1.5、
  悬停底 rgba(c,c,c,6/10)、按压 0.7 透明度）。

自研口径：不依赖 PySideSix-Frameless-Window——窗口层在代码层照抄 2.3.0
一直在用的两段上游实现（qframelesswindow 的边缘命中/NCCALCSIZE +
qfluentwidgets 的 Win11 Snap 命中），见 FramelessWindow.nativeEvent。
"""

import ctypes
import sys

from PySide6.QtCore import (QEvent, QMargins, QPoint, QRect, QRectF, QSize,
                            Qt, Signal)
from PySide6.QtGui import (QColor, QCursor, QFont, QIcon, QPainter, QPen,
                           QMouseEvent)
from PySide6.QtWidgets import (QAbstractScrollArea, QApplication, QFrame,
                               QHBoxLayout, QLabel, QScrollArea, QSizePolicy,
                               QStackedWidget, QVBoxLayout, QWidget)

from ._anim import BackgroundAnimationWidget
from ._icon import FluentIcon, drawIcon, toQIcon
from ._theme import (FluentStyleSheet, autoFallbackThemeColor, isDarkTheme, qconfig,
                     setFont)

if sys.platform == "win32":
    from ctypes import wintypes

    class _NCCALCSIZE_PARAMS(ctypes.Structure):
        """照抄 qframelesswindow c_structures.NCCALCSIZE_PARAMS（lppos 不访问）。"""
        _fields_ = [("rgrc", wintypes.RECT * 3), ("lppos", ctypes.c_void_p)]

    _LPNCCALCSIZE_PARAMS = ctypes.POINTER(_NCCALCSIZE_PARAMS)

    # ---- 自动隐藏任务栏 ------------------------------------------------
    #: 让出带宽（物理像素）——照抄上游 qframelesswindow
    #: Taskbar.AUTO_HIDE_THICKNESS（Windows Terminal 同款取值）。
    _AUTO_HIDE_THICKNESS = 2
    _ABM_GETSTATE = 4
    _ABS_AUTOHIDE = 1
    _ABM_GETAUTOHIDEBAREX = 11
    _MONITOR_DEFAULTTONEAREST = 2
    _EDGE_LEFT, _EDGE_TOP, _EDGE_RIGHT, _EDGE_BOTTOM = 0, 1, 2, 3

    class _APPBARDATA(ctypes.Structure):
        """照抄 qframelesswindow win32_utils.APPBARDATA。"""
        _fields_ = [("cbSize", wintypes.DWORD),
                    ("hWnd", wintypes.HWND),
                    ("uCallbackMessage", wintypes.UINT),
                    ("uEdge", wintypes.UINT),
                    ("rc", wintypes.RECT),
                    ("lParam", wintypes.LPARAM)]

    class _MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD),
                    ("rcMonitor", wintypes.RECT),
                    ("rcWork", wintypes.RECT),
                    ("dwFlags", wintypes.DWORD)]

    def _monitor_rects(hwnd):
        """窗口所在显示器的 (rcMonitor, rcWork)，物理像素；失败返回 None。"""
        try:
            u = ctypes.windll.user32
            u.MonitorFromWindow.restype = ctypes.c_void_p
            u.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
            u.GetMonitorInfoW.argtypes = [ctypes.c_void_p,
                                          ctypes.POINTER(_MONITORINFO)]
            hmon = u.MonitorFromWindow(wintypes.HWND(int(hwnd)),
                                       _MONITOR_DEFAULTTONEAREST)
            if not hmon:
                return None
            mi = _MONITORINFO()
            mi.cbSize = ctypes.sizeof(_MONITORINFO)
            if not u.GetMonitorInfoW(hmon, ctypes.byref(mi)):
                return None
            return mi.rcMonitor, mi.rcWork
        except Exception:  # noqa: BLE001
            return None

    def _autohide_taskbar_edge(hwnd):
        """窗口所在显示器上自动隐藏任务栏的边缘；无则 None。

        ABM_GETAUTOHIDEBAREX 按「显示器矩形 + 边缘」查询，多屏下能准确定位
        任务栏所在屏；ABM_GETTASKBARPOS 只报主屏，副屏会误判。
        """
        try:
            shell32 = ctypes.windll.shell32
            shell32.SHAppBarMessage.restype = ctypes.c_size_t
            abd = _APPBARDATA()
            abd.cbSize = ctypes.sizeof(_APPBARDATA)
            # 上游用 == ABS_AUTOHIDE，state=3（自动隐藏 + 置顶）时会漏判
            if not (shell32.SHAppBarMessage(_ABM_GETSTATE, ctypes.byref(abd))
                    & _ABS_AUTOHIDE):
                return None
            rects = _monitor_rects(hwnd)
            if rects is None:
                return None
            rc_monitor = rects[0]
            for edge in (_EDGE_LEFT, _EDGE_TOP, _EDGE_RIGHT, _EDGE_BOTTOM):
                abd = _APPBARDATA()
                abd.cbSize = ctypes.sizeof(_APPBARDATA)
                abd.uEdge = edge
                abd.rc = rc_monitor
                if shell32.SHAppBarMessage(_ABM_GETAUTOHIDEBAREX,
                                           ctypes.byref(abd)):
                    return edge
        except Exception:  # noqa: BLE001
            return None
        return None


def _nav_position():
    """取 B0 定义在包入口的 NavigationItemPosition（延迟导入避免循环）。"""
    from . import NavigationItemPosition
    return NavigationItemPosition


# ---------------------------------------------------------------------- #
# Mica / 无边框窗口
# ---------------------------------------------------------------------- #
class _Margins(ctypes.Structure):
    """DWM 框架扩展边距（照抄 qframelesswindow c_structures.MARGINS）。"""
    _fields_ = [("cxLeftWidth", ctypes.c_int), ("cxRightWidth", ctypes.c_int),
                ("cyTopHeight", ctypes.c_int), ("cyBottomHeight", ctypes.c_int)]


class _AccentPolicy(ctypes.Structure):
    """Windows 合成强调策略（照抄 qframelesswindow WINDOWCOMPOSITIONATTRIB）。"""
    _fields_ = [("AccentState", ctypes.c_int), ("AccentFlags", ctypes.c_int),
                ("GradientColor", ctypes.c_uint), ("AnimationId", ctypes.c_int)]


class _WinCompAttrData(ctypes.Structure):
    _fields_ = [("Attribute", ctypes.c_int), ("Data", ctypes.c_void_p),
                ("SizeOfData", ctypes.c_size_t)]


#: WCA_ACCENT_POLICY=19；ACCENT_ENABLE_HOSTBACKDROP=5（Mica 宿主背板）
_WCA_ACCENT_POLICY = 19
_ACCENT_ENABLE_HOSTBACKDROP = 5
_ACCENT_DISABLED = 0
#: DWMWA_SYSTEMBACKDROP_TYPE=38 的取值
_DWMSBT_MAINWINDOW = 2
_DWMSBT_NONE = 1
_DWMWA_SYSTEMBACKDROP_TYPE = 38
_DWMWA_USE_IMMERSIVE_DARK_MODE = 20


def _set_window_composition(hwnd, accent_state: int) -> bool:
    """SetWindowCompositionAttribute(WCA_ACCENT_POLICY, accent_state)。

    照抄 qframelesswindow 的做法。该函数未在 user32.h 公开导出，部分系统
    拿不到——取不到就静默跳过（Mica 降级为实底，不影响其它功能）。
    """
    try:
        u = ctypes.windll.user32
        fn = getattr(u, "SetWindowCompositionAttribute", None)
        if fn is None:
            return False
        policy = _AccentPolicy(accent_state, 0, 0, 0)
        data = _WinCompAttrData(_WCA_ACCENT_POLICY,
                                ctypes.cast(ctypes.pointer(policy),
                                            ctypes.c_void_p),
                                ctypes.sizeof(policy))
        fn(ctypes.c_void_p(int(hwnd)), ctypes.byref(data))
        return True
    except Exception:  # noqa: BLE001
        return False


def _set_mica(hwnd, dark: bool) -> bool:
    """Windows 11 Mica 系统背景 —— 代码层照抄 qframelesswindow.setMicaEffect。

    上游三段链路缺一不可（缺任一则背板不显示）：
      ① `DwmExtendFrameIntoClientArea(整窗 MARGINS)` —— 让 DWM 在整窗背后
         绘制系统背板；
      ② `SetWindowCompositionAttribute(WCA_ACCENT_POLICY,
         ACCENT_ENABLE_HOSTBACKDROP)` —— 启用宿主背板；
      ③ `DwmSetWindowAttribute(DWMWA_SYSTEMBACKDROP_TYPE, MAINWINDOW)`。
    另设 `DWMWA_USE_IMMERSIVE_DARK_MODE` 让标题栏跟随深浅。

    ⚠️ 关键：**绝不使用 Qt 的 `WA_TranslucentBackground`**。上游 Windows 平台
    从不设置它（只在 macOS 分支设置）。实测它会引入 `WS_EX_LAYERED` 扩展样式
    = 分层窗口，系统的鼠标命中按**逐像素 alpha** 判定；而 Mica 生效时 Qt 层
    背景是全透明（材质由 DWM 画），于是内容区/导航栏所有点的 alpha=0，鼠标
    **直接穿透到底层窗口**（用户实测「点击会直接穿过程序」）。DWM 背板机制
    不需要分层窗口，去掉后 EXSTYLE 回到 0x100，命中恢复正常。
    """
    if sys.platform != "win32":
        return False
    try:
        dwm = ctypes.windll.dwmapi
        # ① 框架扩展到整窗 —— ⚠️ **四个方向都要扩**。
        #    上游只扩左右 `(0xFFFFFF, 0xFFFFFF, 0, 0)`，上下为 0，于是 DWM
        #    认为**垂直方向没有框架**：系统在垂直方向不认原生缩放，拖上下边缘
        #    只会整体移动。用户实测「底部向上调整无效」「顶部向下只会向下移动」
        #    「只要放大就无法缩小」正是**垂直方向失去缩放**的典型表现。
        #    这里四向均用 -1（DWM 约定的"扩展到整个窗口"）。
        dwm.DwmExtendFrameIntoClientArea(
            ctypes.c_void_p(int(hwnd)),
            ctypes.byref(_Margins(-1, -1, -1, -1)))
        # ② 宿主背板
        _set_window_composition(hwnd, _ACCENT_ENABLE_HOSTBACKDROP)
        # ③ 背板类型 = Mica(MAINWINDOW)
        backdrop = ctypes.c_int(_DWMSBT_MAINWINDOW)
        dwm.DwmSetWindowAttribute(ctypes.c_void_p(int(hwnd)),
                                  _DWMWA_SYSTEMBACKDROP_TYPE,
                                  ctypes.byref(backdrop), ctypes.sizeof(backdrop))
        # 深色标题栏（Win10 1903+ / Win11）
        dark_mode = ctypes.c_int(1 if dark else 0)
        dwm.DwmSetWindowAttribute(ctypes.c_void_p(int(hwnd)),
                                  _DWMWA_USE_IMMERSIVE_DARK_MODE,
                                  ctypes.byref(dark_mode), ctypes.sizeof(dark_mode))
        return True
    except Exception:
        return False


def _remove_backdrop(hwnd) -> bool:
    """关闭系统背板（照抄上游 removeBackgroundEffect + SYSTEMBACKDROP_TYPE）。"""
    if sys.platform != "win32":
        return False
    try:
        dwm = ctypes.windll.dwmapi
        _set_window_composition(hwnd, _ACCENT_DISABLED)
        none = ctypes.c_int(_DWMSBT_NONE)
        dwm.DwmSetWindowAttribute(ctypes.c_void_p(int(hwnd)),
                                  _DWMWA_SYSTEMBACKDROP_TYPE,
                                  ctypes.byref(none), ctypes.sizeof(none))
        return True
    except Exception:
        return False


class FramelessWindow(QWidget):
    """无边框窗口基类（原生命中测试缩放 + 标题栏拖动）。

    窗口层实现照抄 2.3.0 实际使用的上游链路（代码层照抄，不 import 上游）：
      · qframelesswindow `WindowsFramelessWindowBase`：flags 保留式设置 +
        `addWindowAnimation` 补样式位 + nativeEvent（WM_NCHITTEST 边缘命中 /
        WM_NCCALCSIZE 客户区=整窗、最大化缩边）；
      · qfluentwidgets `frameless_window.FramelessWindow`：nativeEvent 的
        HTMAXBUTTON（Win11 Snap 布局面板）与 NCLBUTTONDOWN 按钮转发。
    """

    #: 边缘命中带宽（物理像素）——照抄上游 WindowsFramelessWindowBase.BORDER_WIDTH
    BORDER_WIDTH = 5

    def __init__(self, parent=None):
        super().__init__(parent)
        # ⚠️ 照抄上游 qframelesswindow（2.3.0 一直在用的可用实现）：
        #    **保留**原有 windowFlags，只「或」上 FramelessWindowHint。
        #    绝不能写成 setWindowFlags(FramelessWindowHint | Window)——那会把
        #    顶层窗口默认携带的 WindowSystemMenuHint / WindowMinimizeButtonHint
        #    / WindowMaximizeButtonHint / WindowCloseButtonHint（0xf000）一并
        #    丢掉：实测 flags 从上游的 0x800f801 掉成 0x801，系统于是不认本
        #    窗口有最大化按钮——Snap 布局面板不弹、拖到屏幕边缘也不贴靠。
        stay_on_top = (Qt.WindowStaysOnTopHint
                       if self.windowFlags() & Qt.WindowStaysOnTopHint else 0)
        self.setWindowFlags(self.windowFlags()
                            | Qt.FramelessWindowHint | stay_on_top)
        # ⚠️ **不设** Qt.WA_TranslucentBackground（照抄上游 Windows 分支）：
        #    该属性会引入 WS_EX_LAYERED 扩展样式（分层窗口），系统鼠标命中
        #    改按逐像素 alpha 判定；Mica 生效时 Qt 层背景全透明（材质由 DWM
        #    画），于是整窗 alpha=0、鼠标点击**直接穿透到底层窗口**（用户实测
        #    「无法被选中，点击会直接穿过程序」）。DWM 背板不需要分层窗口。
        #    上游 qframelesswindow 只在 macOS 分支设该属性，Windows 不设。
        self.titleBar = None
        self._isResizeEnabled = True
        self._apply_native_resize_style()

    def setTitleBar(self, titleBar):
        self.titleBar = titleBar
        titleBar.raise_()

    def showEvent(self, e):
        super().showEvent(e)
        self._apply_native_resize_style()

    def _apply_native_resize_style(self):
        """补回系统「可缩放」样式位 —— Windows 贴靠/定位（Snap）的前提。

        Qt 的 `FramelessWindowHint` 会把窗口样式剥掉一大截：实测
        `GetWindowLong(GWL_STYLE)` 里 WS_THICKFRAME / WS_MAXIMIZEBOX /
        WS_CAPTION / WS_SYSMENU **全部缺失**。于是系统不把本窗口当成可缩放
        窗口——拖到屏幕边缘不贴靠、选了 Snap 布局也不生效（用户实测
        "程序不能激活 win 的定位"）。这里只补**样式位**，外观照旧无边框
        （由 nativeEvent 里的 WM_NCCALCSIZE 保持），与上游 qframelesswindow
        的 `addWindowAnimation` 同款做法。
        """
        if sys.platform != "win32" or getattr(self, "_vt_style_fixed", False):
            return
        try:
            import ctypes
            u = ctypes.windll.user32
            gwl_style = -16
            ws_minimizebox, ws_maximizebox = 0x00020000, 0x00010000
            ws_caption, ws_thickframe = 0x00C00000, 0x00040000
            #: ⚠️ 照抄上游 `WindowsWindowEffect.addWindowAnimation`：**只加位**。
            #: 实测上游窗口同样带 WS_POPUP（GWL_STYLE 0x96cf0008）却一直正常
            #: 工作，所以 POPUP 并非症结——上一轮「清 WS_POPUP」是错的方向，
            #: 已按上游原样退回。代码走位组合与上游逐位一致。
            swp_framechanged, swp_nomove, swp_nosize = 0x0020, 0x0002, 0x0001
            hwnd = int(self.winId())
            style = u.GetWindowLongW(hwnd, gwl_style)
            u.SetWindowLongW(
                hwnd, gwl_style,
                style | ws_minimizebox | ws_maximizebox
                | ws_caption | ws_thickframe)
            # 改完样式必须走一次 FRAMECHANGED，系统才会按新样式重算边框
            u.SetWindowPos(hwnd, 0, 0, 0, 0, 0,
                           swp_framechanged | swp_nomove | swp_nosize)
            self._vt_style_fixed = True
        except Exception:  # noqa: BLE001
            pass

    def _isHoverMaxBtn(self):
        """照抄 qfluentwidgets.FramelessWindow._isHoverMaxBtn。"""
        if self.titleBar is None:
            return False
        maxBtn = getattr(self.titleBar, "maxBtn", None)
        if maxBtn is None:
            return False
        pos = QCursor.pos() - self.geometry().topLeft() - self.titleBar.pos()
        return self.titleBar.childAt(pos) is maxBtn

    @staticmethod
    def _resizeBorderThickness(hwnd, horizontal=True):
        """照抄 qframelesswindow win32_utils.getResizeBorderThickness。"""
        try:
            build = sys.getwindowsversion().build
        except Exception:  # noqa: BLE001
            build = 0
        result = ctypes.c_int(0)
        if build >= 22000:
            # Win11：问 DWM 可见边框厚度（DWMWA_VISIBLE_FRAME_BORDER_THICKNESS）
            ctypes.windll.dwmapi.DwmGetWindowAttribute(
                int(hwnd), 34, ctypes.byref(result), ctypes.sizeof(result))
        else:
            # SM_CXSIZEFRAME=32 / SM_CYSIZEFRAME=33 / SM_CXPADDEDBORDER=92
            u = ctypes.windll.user32
            result.value = (u.GetSystemMetrics(32 if horizontal else 33)
                            + u.GetSystemMetrics(92))
        return result.value

    def nativeEvent(self, eventType, message):
        """窗口消息处理 —— 代码层照抄 2.3.0 实际使用的上游两段实现。

        段① 照抄 qfluentwidgets/components/widgets/frameless_window.py：
            WM_NCHITTEST 悬停最大化按钮 → 返回 HTMAXBUTTON（Win11 悬停弹
            「Snap 布局」面板的必要条件，自绘按钮系统认不出来）；点击时
            把 WM_NCLBUTTONDOWN 合成鼠标事件转发给自绘按钮。
        段② 照抄 qframelesswindow/windows/__init__.py nativeEvent：
            WM_NCHITTEST 边缘 8 向命中 → 系统原生缩放循环；WM_NCCALCSIZE
            客户区=整窗（无边框外观）+ 最大化时四边缩进缩放边框厚度。
        自动隐藏任务栏的让位补偿照抄上游（Taskbar.isAutoHide），见下方
        WM_NCCALCSIZE 分支——最大化铺满全屏时保留任务栏唤出热区。

        ⚠ 说明：真实鼠标的 WM_NCHITTEST 由系统直接调窗口过程，**主窗口**
        这层能收到（点落在 mpv 嵌入提升出的原生子窗口上时收不到——那是
        宿主 _ResizeHitFilter 的职责，见 video_toolbox_qt.py v1.13.6）。
        """
        if sys.platform != "win32":
            return super().nativeEvent(eventType, message)
        try:
            import win32api
            import win32con
            import win32gui
            msg = wintypes.MSG.from_address(int(message))
            if not msg.hWnd:
                return super().nativeEvent(eventType, message)

            # ---- 段①：Win11 Snap（照抄 qfluentwidgets） -------------------
            if msg.message == win32con.WM_NCHITTEST and self._isResizeEnabled:
                if self._isHoverMaxBtn():
                    self.titleBar.maxBtn.isHover = True
                    self.titleBar.maxBtn.update()
                    return True, win32con.HTMAXBUTTON
            elif msg.message in (0x2A2, win32con.WM_MOUSELEAVE):
                # 0x2A2=WM_NCMOUSELEAVE：离开标题栏时复位按钮 hover 态
                maxBtn = getattr(self.titleBar, "maxBtn", None)
                if maxBtn is not None:
                    maxBtn.isHover = False
                    maxBtn.update()
            elif (msg.message in (win32con.WM_NCLBUTTONDOWN,
                                  win32con.WM_NCLBUTTONDBLCLK)
                  and self._isHoverMaxBtn()):
                e = QMouseEvent(QEvent.MouseButtonPress, QPoint(),
                                Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
                QApplication.sendEvent(self.titleBar.maxBtn, e)
                return True, 0
            elif (msg.message in (win32con.WM_NCLBUTTONUP,
                                  win32con.WM_NCRBUTTONUP)
                  and self._isHoverMaxBtn()):
                e = QMouseEvent(QEvent.MouseButtonRelease, QPoint(),
                                Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
                QApplication.sendEvent(self.titleBar.maxBtn, e)

            # ---- 段②：边缘缩放 + 客户区布局（照抄 qframelesswindow） -------
            if msg.message == win32con.WM_NCHITTEST and self._isResizeEnabled:
                xPos, yPos = win32gui.ScreenToClient(
                    msg.hWnd, win32api.GetCursorPos())
                clientRect = win32gui.GetClientRect(msg.hWnd)

                w = clientRect[2] - clientRect[0]
                h = clientRect[3] - clientRect[1]

                # 最大化/全屏时边宽归零（上游 fix #98），否则会误判边缘
                bw = 0 if self.isMaximized() or self.isFullScreen() \
                    else self.BORDER_WIDTH
                lx = xPos < bw  # left
                rx = xPos > w - bw  # right
                ty = yPos < bw  # top
                by = yPos > h - bw  # bottom
                if lx and ty:
                    return True, win32con.HTTOPLEFT
                elif rx and by:
                    return True, win32con.HTBOTTOMRIGHT
                elif rx and ty:
                    return True, win32con.HTTOPRIGHT
                elif lx and by:
                    return True, win32con.HTBOTTOMLEFT
                elif ty:
                    return True, win32con.HTTOP
                elif by:
                    return True, win32con.HTBOTTOM
                elif lx:
                    return True, win32con.HTLEFT
                elif rx:
                    return True, win32con.HTRIGHT
            elif msg.message == win32con.WM_NCCALCSIZE:
                if msg.wParam:
                    rect = ctypes.cast(
                        msg.lParam, _LPNCCALCSIZE_PARAMS).contents.rgrc[0]
                else:
                    rect = ctypes.cast(
                        msg.lParam, wintypes.LPRECT).contents

                hwnd = int(msg.hWnd)
                # IsZoomed 取系统实时状态：首次最大化的 NCCALCSIZE 消息链里
                # Qt 的 isMaximized() 可能尚未更新，会漏掉本轮调整。
                is_max = bool(ctypes.windll.user32.IsZoomed(
                    wintypes.HWND(hwnd)))
                is_full = self.isFullScreen()

                # 最大化时把客户区四边缩进系统缩放边框厚度，避免内容
                # 被屏幕边缘裁掉（照抄上游；此处相当于上游
                # win_utils.isMaximized/isFullScreen 的 Qt 等价判断）
                if is_max and not is_full:
                    ty = self._resizeBorderThickness(hwnd, False)
                    rect.top += ty
                    rect.bottom -= ty

                    tx = self._resizeBorderThickness(hwnd, True)
                    rect.left += tx
                    rect.right -= tx

                    # WS_THICKFRAME 会让系统给的最大化矩形向屏外扩出边框
                    # 宽度，只缩 DWM 边框厚度不足以回到屏内；以显示器工作区
                    # 钳制，普通任务栏（非自动隐藏）时也不会遮挡任务栏。
                    rects = _monitor_rects(hwnd)
                    if rects is not None:
                        work = rects[1]
                        rect.left = max(rect.left, work.left)
                        rect.top = max(rect.top, work.top)
                        rect.right = min(rect.right, work.right)
                        rect.bottom = min(rect.bottom, work.bottom)

                # 自动隐藏任务栏时工作区=整屏，客户区铺满会让 Shell 把窗口
                # 当全屏应用并压制任务栏唤出。在任务栏所在边缘让出 2 物理
                # 像素恢复唤出热区（上游同款做法，修正其 LEFT/TOP 分支笔误）。
                if is_max or is_full:
                    edge = _autohide_taskbar_edge(hwnd)
                    if edge == _EDGE_LEFT:
                        rect.left += _AUTO_HIDE_THICKNESS
                    elif edge == _EDGE_TOP:
                        rect.top += _AUTO_HIDE_THICKNESS
                    elif edge == _EDGE_RIGHT:
                        rect.right -= _AUTO_HIDE_THICKNESS
                    elif edge == _EDGE_BOTTOM:
                        rect.bottom -= _AUTO_HIDE_THICKNESS

                result = 0 if not msg.wParam else win32con.WVR_REDRAW
                return True, result
        except Exception:  # noqa: BLE001
            pass
        return super().nativeEvent(eventType, message)


# ---------------------------------------------------------------------- #
# 导航部件
# ---------------------------------------------------------------------- #
class NavigationWidget(QWidget):
    """导航项基类（对齐上游 NavigationWidget 的尺寸/态语义）。"""

    clicked = Signal(bool)
    selectedChanged = Signal(bool)
    EXPAND_WIDTH = 312

    def __init__(self, isSelectable: bool, parent=None):
        super().__init__(parent)
        self.isCompacted = True
        self.isSelected = False
        self.isPressed = False
        self.isEnter = False
        self.isAboutSelected = False
        self.isSelectable = isSelectable
        self.treeParent = None
        self.nodeDepth = 0
        self.lightTextColor = QColor(0, 0, 0)
        self.darkTextColor = QColor(255, 255, 255)
        self.lightIndicatorColor = QColor()
        self.darkIndicatorColor = QColor()
        self.setFixedSize(40, 36)

    def enterEvent(self, e):
        self.isEnter = True
        self.update()

    def leaveEvent(self, e):
        self.isEnter = False
        self.isPressed = False
        self.update()

    def mousePressEvent(self, e):
        super().mousePressEvent(e)
        self.isPressed = True
        self.update()

    def mouseReleaseEvent(self, e):
        super().mouseReleaseEvent(e)
        self.isPressed = False
        self.update()
        self.clicked.emit(True)

    def click(self):
        self.clicked.emit(True)

    def setCompacted(self, isCompacted: bool):
        if isCompacted == self.isCompacted:
            return
        self.isCompacted = isCompacted
        if isCompacted:
            self.setFixedSize(40, 36)
        else:
            self.setFixedSize(self.EXPAND_WIDTH, 36)
        self.update()

    def setSelected(self, isSelected: bool):
        if not self.isSelectable:
            return
        self.isSelected = isSelected
        self.isAboutSelected = False
        self.update()
        self.selectedChanged.emit(isSelected)

    def textColor(self):
        return self.darkTextColor if isDarkTheme() else self.lightTextColor

    def setTextColor(self, light, dark):
        self.lightTextColor = QColor(light)
        self.darkTextColor = QColor(dark)
        self.update()

    def setAboutSelected(self, selected: bool):
        self.isAboutSelected = selected
        self.update()

    def _margins(self):
        return QMargins(0, 0, 0, 0)

    def indicatorRect(self):
        m = self._margins()
        return QRectF(m.left(), 10, 3, 16)

    def setIndicatorColor(self, light, dark):
        self.lightIndicatorColor = QColor(light)
        self.darkIndicatorColor = QColor(dark)
        self.update()


class NavigationPushButton(NavigationWidget):
    """导航按钮项（图标 + 文字，对齐上游 NavigationPushButton）。"""

    def __init__(self, icon, text: str, isSelectable: bool, parent=None):
        super().__init__(isSelectable=isSelectable, parent=parent)
        self._icon = icon
        self._text = text
        setFont(self)

    def text(self):
        return self._text

    def setText(self, text: str):
        self._text = text
        self.update()

    def icon(self):
        return toQIcon(self._icon)

    def setIcon(self, icon):
        self._icon = icon
        self.update()

    def _canDrawIndicator(self):
        return self.isSelected

    def paintEvent(self, e):
        painter = QPainter(self)
        painter.setRenderHints(QPainter.Antialiasing |
                               QPainter.TextAntialiasing |
                               QPainter.SmoothPixmapTransform)
        painter.setPen(Qt.NoPen)

        if self.isPressed:
            painter.setOpacity(0.7)
        if not self.isEnabled():
            painter.setOpacity(0.4)

        c = 255 if isDarkTheme() else 0
        m = self._margins()
        pl, pr = m.left(), m.right()
        globalRect = QRect(self.mapToGlobal(QPoint()), self.size())

        if self._canDrawIndicator():
            painter.setBrush(QColor(c, c, c, 6 if self.isEnter else 10))
            painter.drawRoundedRect(self.rect(), 5, 5)
            painter.setBrush(autoFallbackThemeColor(self.lightIndicatorColor,
                                                    self.darkIndicatorColor))
            painter.drawRoundedRect(self.indicatorRect(), 1.5, 1.5)
        elif ((self.isEnter and globalRect.contains(QCursor.pos()))
              or self.isAboutSelected) and self.isEnabled():
            painter.setBrush(QColor(c, c, c, 6 if self.isAboutSelected else 10))
            painter.drawRoundedRect(self.rect(), 5, 5)

        drawIcon(self._icon, painter, QRectF(11.5 + pl, 10, 16, 16))

        if self.isCompacted:
            return

        painter.setFont(self.font())
        painter.setPen(self.textColor())
        left = 44 + pl if not self.icon().isNull() else pl + 16
        painter.drawText(QRectF(left, 0, self.width() - 13 - left - pr,
                                self.height()),
                         Qt.AlignVCenter, self.text())


class NavigationToolButton(NavigationPushButton):
    """导航工具按钮（仅图标，固定紧凑）。"""

    def __init__(self, icon, parent=None):
        super().__init__(icon, "", False, parent)

    def setCompacted(self, isCompacted: bool):
        self.setFixedSize(40, 36)


class NavigationSeparator(NavigationWidget):
    """导航分隔线（对齐上游 NavigationSeparator）。"""

    def __init__(self, parent=None):
        super().__init__(False, parent=parent)
        self.setCompacted(True)

    def setCompacted(self, isCompacted: bool):
        if isCompacted:
            self.setFixedSize(48, 3)
        else:
            self.setFixedSize(self.EXPAND_WIDTH + 10, 3)
        self.update()

    def paintEvent(self, e):
        painter = QPainter(self)
        c = 255 if isDarkTheme() else 0
        pen = QPen(QColor(c, c, c, 15))
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.drawLine(0, 1, self.width(), 1)


class NavigationInterface(QWidget):
    """竖向导航接口（对齐上游 NavigationInterface 的使用面）。

    Constructors
    ------------
    * NavigationInterface(`parent`=None, `showMenuButton`=True,
                          `showReturnButton`=False, `collapsible`=True)
    """

    displayModeChanged = Signal(object)

    def __init__(self, parent=None, showMenuButton=True, showReturnButton=False,
                 collapsible=True):
        super().__init__(parent)
        #: 应用侧按 `navigationInterface.panel.font()` 取导航字体，
        #: 这里让 panel 指向自身（QWidget 自带 font()）。
        self.panel = self
        self.items = {}
        self.routeKeyToWidget = {}
        self._currentRouteKey = None
        self._isCollapsible = collapsible
        self._isExpanded = False
        self._expandWidth = NavigationWidget.EXPAND_WIDTH
        self._minimumExpandWidth = 1008

        self.topLayout = QVBoxLayout()
        self.bottomLayout = QVBoxLayout()
        self.vBoxLayout = QVBoxLayout(self)

        self.scrollArea = QScrollArea(self)
        self.scrollWidget = QWidget()
        self.scrollLayout = QVBoxLayout(self.scrollWidget)

        self._initInterface()

    def _initInterface(self):
        self.setAttribute(Qt.WA_StyledBackground)
        self.setFixedWidth(48)

        self.scrollArea.setWidget(self.scrollWidget)
        self.scrollArea.setWidgetResizable(True)
        self.scrollArea.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scrollArea.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scrollArea.setFrameShape(QFrame.NoFrame)
        # ⚠ 导航栏必须随主题：QScrollArea 的 viewport 默认 autoFillBackground=True，
        # 按 QPalette.Base 自填充（浅色主题即 #efefef 浅灰白），深色主题下会留
        # 一整块浅底——导航栏与标题栏左侧都发白（用户实测）。这里关掉自动填充
        # 并把 viewport 背景置透明，让导航栏透出窗口底（Mica / 主题底色）。
        # 选择器限定为 QScrollArea，避免级联到导航项子控件。
        self.scrollArea.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }")
        self.scrollArea.viewport().setAutoFillBackground(False)
        # ⚠ 真正的发白源头：Qt 的 QScrollArea.setWidget() 会把**内容控件**的
        # autoFillBackground 由 False 改成 True（实测确认），于是 scrollWidget
        # 按 palette Window(#efefef) 自填充整块导航栏。必须在 setWidget 之后
        # 显式关掉，导航栏才透出窗口底。
        self.scrollWidget.setAutoFillBackground(False)

        self.scrollLayout.setContentsMargins(4, 8, 4, 8)
        self.scrollLayout.setSpacing(4)
        self.scrollLayout.setAlignment(Qt.AlignTop)
        self.scrollLayout.addLayout(self.topLayout)
        self.scrollLayout.addStretch(1)
        self.scrollLayout.addLayout(self.bottomLayout)

        #: 顶部返回键（应用把它改挂「定位到首页」；上游同位置同名）
        self.returnButton = NavigationToolButton(FluentIcon.RETURN, self)
        self.returnButton.setToolTip(self.tr("返回"))
        self.returnButton.move(4, 4)
        self.returnButton.show()

        # ⚠ 顶部必须让出标题栏高度（48）：FluentWindow 的标题栏从 x=46 起且
        # **半透明**，展开态导航项（宽 312）会伸进标题栏区域，被半透明标题栏
        # 透出、与标题 logo 挤在一起（用户实测"顶部样式错误"）。上游同款结构
        # 顶部还排了 return/menu 两个工具按钮，这里预留标题栏高度即可对齐。
        self.vBoxLayout.setContentsMargins(0, 48, 0, 0)
        self.vBoxLayout.setSpacing(0)
        self.vBoxLayout.addWidget(self.scrollArea)

    # ---- 项增删 -------------------------------------------------------- #
    def addItem(self, routeKey: str, icon, text: str, onClick=None,
                selectable=True, position=None, tooltip=None,
                isMinimalExpand=False):
        pos = _nav_position().TOP if position is None else position
        widget = NavigationPushButton(icon, text, selectable, self)
        widget.setToolTip(tooltip or text)
        self.addWidget(routeKey, widget, onClick, pos)
        return widget

    def addWidget(self, routeKey: str, widget, onClick=None, position=None):
        pos = _nav_position().TOP if position is None else position
        if routeKey in self.routeKeyToWidget:
            return

        widget.setParent(self.scrollWidget)
        widget.setCompacted(not self._isExpanded)

        if onClick:
            widget.clicked.connect(onClick)

        if pos == _nav_position().BOTTOM:
            self.bottomLayout.addWidget(widget)
        else:
            self.topLayout.addWidget(widget)

        self.routeKeyToWidget[routeKey] = widget
        self.items[routeKey] = widget
        widget.clicked.connect(lambda: self._onWidgetClicked(routeKey))

    def addSeparator(self, position=None):
        pos = _nav_position().TOP if position is None else position
        sep = NavigationSeparator(self)
        sep.setCompacted(not self._isExpanded)
        if pos == _nav_position().BOTTOM:
            self.bottomLayout.addWidget(sep)
        else:
            self.topLayout.addWidget(sep)

    def removeWidget(self, routeKey: str):
        if routeKey not in self.routeKeyToWidget:
            return
        w = self.routeKeyToWidget.pop(routeKey)
        self.items.pop(routeKey, None)
        self.topLayout.removeWidget(w)
        self.bottomLayout.removeWidget(w)
        w.deleteLater()

    def widget(self, routeKey: str):
        return self.routeKeyToWidget.get(routeKey)

    # ---- 选中 ---------------------------------------------------------- #
    def _onWidgetClicked(self, routeKey: str):
        self.setCurrentItem(routeKey)

    def setCurrentItem(self, routeKey: str):
        if routeKey not in self.routeKeyToWidget:
            return
        if self._currentRouteKey == routeKey:
            return
        old = self.routeKeyToWidget.get(self._currentRouteKey)
        if old is not None:
            old.setSelected(False)
        self._currentRouteKey = routeKey
        self.routeKeyToWidget[routeKey].setSelected(True)

    def currentItem(self):
        return self.routeKeyToWidget.get(self._currentRouteKey)

    def currentRouteKey(self):
        return self._currentRouteKey

    # ---- 展开/收起 ----------------------------------------------------- #
    def setCollapsible(self, collapsible: bool):
        self._isCollapsible = collapsible
        if not collapsible:
            # 上游语义：不可折叠 = 常驻展开（默认窄条只有图标）
            self._setExpanded(True)

    def isCollapsible(self):
        return self._isCollapsible

    def expand(self, useAni=True):
        self._setExpanded(True)

    def collapse(self, useAni=True):
        self._setExpanded(False)

    def toggle(self):
        self._setExpanded(not self._isExpanded)

    def isExpanded(self):
        return self._isExpanded

    def _setExpanded(self, expanded: bool):
        if self._isExpanded == expanded:
            return
        self._isExpanded = expanded
        for w in self.routeKeyToWidget.values():
            if expanded:
                w.EXPAND_WIDTH = max(self._expandWidth - 8, 40)
            w.setCompacted(not expanded)
            if expanded and not w.isCompacted:
                w.setFixedSize(w.EXPAND_WIDTH, 36)
        for sep in self.findChildren(NavigationSeparator):
            sep.setCompacted(not expanded)
        self.setFixedWidth(self._expandWidth if expanded else 48)

    def setExpandWidth(self, width: int):
        self._expandWidth = int(width)
        if not self._isExpanded:
            return
        self.setFixedWidth(self._expandWidth)
        for w in self.routeKeyToWidget.values():
            w.EXPAND_WIDTH = max(self._expandWidth - 8, 40)
            # setCompacted 在已是展开态时提前返回，这里直接落尺寸
            if not w.isCompacted:
                w.setFixedSize(w.EXPAND_WIDTH, 36)
            w.update()

    def setMinimumExpandWidth(self, width: int):
        self._minimumExpandWidth = width

    def setMenuButtonVisible(self, isVisible: bool):
        pass

    def setReturnButtonVisible(self, isVisible: bool):
        pass

    def setAcrylicEnabled(self, isEnabled: bool):
        pass

    def isAcrylicEnabled(self):
        return False


class StackedWidget(QFrame):
    """页面栈（对齐上游 window.StackedWidget：popOut 参数 + currentChanged 转发）。

    上游用 PopUpAniStackedWidget 做滑动动画；此处为**纯切换**（静态截图与
    布局完全一致），动画属后续 nicety，接口签名保持兼容。
    """

    currentChanged = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.hBoxLayout = QHBoxLayout(self)
        self.view = QStackedWidget(self)

        self.hBoxLayout.setContentsMargins(0, 0, 0, 0)
        self.hBoxLayout.addWidget(self.view)

        self.view.currentChanged.connect(self.currentChanged)
        self.setAttribute(Qt.WA_StyledBackground)

    def addWidget(self, widget):
        self.view.addWidget(widget)

    def removeWidget(self, widget):
        self.view.removeWidget(widget)

    def widget(self, index):
        return self.view.widget(index)

    def count(self):
        return self.view.count()

    def indexOf(self, widget):
        return self.view.indexOf(widget)

    def setCurrentWidget(self, widget, popOut=True):
        if isinstance(widget, QAbstractScrollArea):
            widget.verticalScrollBar().setValue(0)
        self.view.setCurrentWidget(widget)

    def setCurrentIndex(self, index, popOut=True):
        self.view.setCurrentIndex(index)

    def currentIndex(self):
        return self.view.currentIndex()

    def currentWidget(self):
        return self.view.currentWidget()

    def setAnimationEnabled(self, isEnabled: bool):
        pass

    def isAnimationEnabled(self):
        return False


class FluentTitleBarButton(QWidget):
    """标题栏按钮（最小化/最大化/关闭，46×32）。"""

    def __init__(self, icon, parent=None):
        super().__init__(parent)
        self._icon = icon
        self.isHover = False
        self.isPressed = False
        self.isCloseButton = False
        self.setFixedSize(46, 32)
        self.setCursor(Qt.ArrowCursor)

    def setIcon(self, icon):
        self._icon = icon
        self.update()

    def icon(self):
        return toQIcon(self._icon)

    def enterEvent(self, e):
        self.isHover = True
        self.update()

    def leaveEvent(self, e):
        self.isHover = False
        self.isPressed = False
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.isPressed = True
            self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self.isPressed:
            self.isPressed = False
            self.update()
            self.clicked.emit()

    clicked = Signal()

    def paintEvent(self, e):
        painter = QPainter(self)
        painter.setRenderHints(QPainter.Antialiasing |
                               QPainter.SmoothPixmapTransform)
        c = 255 if isDarkTheme() else 0
        bg = Qt.transparent
        if self.isPressed:
            bg = QColor(c, c, c, 26) if not self.isCloseButton else QColor(192, 43, 28)
        elif self.isHover:
            bg = QColor(c, c, c, 14) if not self.isCloseButton else QColor(196, 43, 28)
        painter.setPen(Qt.NoPen)
        painter.setBrush(bg)
        painter.drawRect(self.rect())

        rect = QRectF(self.width() / 2 - 5, self.height() / 2 - 5, 10, 10)
        if self.isCloseButton and (self.isHover or self.isPressed):
            FluentIcon.CLOSE.render(painter, rect, fill="#FFFFFF")
        else:
            drawIcon(self._icon, painter, rect)


class FluentTitleBar(QWidget):
    """标题栏（48px：图标 + 标题 + 窗口按钮，可拖动/双击最大化）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.window = parent
        self._dragPos = None
        self.setFixedHeight(48)
        self.setAttribute(Qt.WA_StyledBackground, False)

        self.iconWidget = QLabel(self)
        self.titleLabel = QLabel(self)
        self.minBtn = FluentTitleBarButton(FluentIcon.MINIMIZE, self)
        self.maxBtn = FluentTitleBarButton(FluentIcon.FULL_SCREEN, self)
        self.closeBtn = FluentTitleBarButton(FluentIcon.CLOSE, self)
        self.closeBtn.isCloseButton = True

        self.hBoxLayout = QHBoxLayout(self)
        self._initWidget()

    def _initWidget(self):
        self.hBoxLayout.setContentsMargins(12, 0, 0, 0)
        self.hBoxLayout.setSpacing(0)
        self.hBoxLayout.addWidget(self.iconWidget, 0, Qt.AlignVCenter)
        self.hBoxLayout.addSpacing(10)
        self.hBoxLayout.addWidget(self.titleLabel, 0, Qt.AlignVCenter)
        self.hBoxLayout.addStretch(1)
        self.hBoxLayout.addWidget(self.minBtn, 0, Qt.AlignVCenter)
        self.hBoxLayout.addWidget(self.maxBtn, 0, Qt.AlignVCenter)
        self.hBoxLayout.addWidget(self.closeBtn, 0, Qt.AlignVCenter)

        self.iconWidget.setFixedSize(18, 18)
        self.titleLabel.setStyleSheet("background: transparent;")
        setFont(self.titleLabel, 13)

        self.minBtn.clicked.connect(self.window.showMinimized)
        self.maxBtn.clicked.connect(self._toggleMaximized)
        self.closeBtn.clicked.connect(self.window.close)

    def _toggleMaximized(self):
        if self.window.isMaximized():
            self.window.showNormal()
        else:
            self.window.showMaximized()

    def setTitle(self, title: str):
        self.titleLabel.setText(title)

    def setIcon(self, icon):
        if icon is None:
            self.iconWidget.clear()
            return
        self.iconWidget.setPixmap(toQIcon(icon).pixmap(18, 18))

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._dragPos = e.globalPosition().toPoint() - self.window.frameGeometry().topLeft()

    def _startSystemMove(self):
        """照抄上游 qframelesswindow `win32_utils.MoveResize.startSystemMove`。

        `ReleaseCapture()` + `SendMessage(WM_SYSCOMMAND, SC_MOVE | HTCAPTION)`
        —— 把窗口拖动的控制权交给**系统移动循环**。这是 Win11 贴靠
        （拖到屏幕边缘自动吸附 / 半屏 / Win+方向键布局）生效的前提：系统只在
        它自己的移动循环里做边缘吸附探测。原先用 `self.window.move()` 纯 Qt
        自绘拖动，不进系统循环，所以「贴边未反馈」（用户实测）。
        SendMessage 会阻塞到拖动结束（系统模态循环），与上游行为一致。
        """
        import win32api
        import win32con
        import win32gui
        win32gui.ReleaseCapture()
        win32api.SendMessage(int(self.window.winId()), win32con.WM_SYSCOMMAND,
                             win32con.SC_MOVE | win32con.HTCAPTION, 0)

    def mouseMoveEvent(self, e):
        if sys.platform == "win32":
            try:
                self._startSystemMove()
                return
            except Exception:  # noqa: BLE001
                pass
        # 非 Windows 平台（或系统调用失败）维持 Qt 自绘拖动
        if self._dragPos is None or self.window.isMaximized():
            return
        self.window.move(e.globalPosition().toPoint() - self._dragPos)

    def mouseReleaseEvent(self, e):
        self._dragPos = None

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._toggleMaximized()

    def paintEvent(self, e):
        """标题栏**不叠任何底色** —— 照抄上游 fluent_window.qss：

            FluentTitleBar, SplitTitleBar { background-color: transparent; }

        原实现叠了 rgba(255,255,255,8)（深色）/ rgba(0,0,0,4)（浅色），
        使标题栏比左侧「导航栏顶部 48px 出让区」（透明、直接透出窗口底）
        亮一档，顶部一整条出现**左深右浅的色带** —— 用户实测「顶部样式不统一」。
        这里不画即透明，整条统一透出 FluentWindow 的底色。
        """
        pass


class FluentWindow(BackgroundAnimationWidget, FramelessWindow):
    """Fluent 主窗口（无边框 + Mica + 标题栏 + 左侧导航 + 页面栈）。

    Constructors
    ------------
    * FluentWindow(`parent`: QWidget = None)
    """

    def __init__(self, parent=None):
        self._isMicaEnabled = False
        self._lightBackgroundColor = QColor(240, 244, 249)
        self._darkBackgroundColor = QColor(32, 32, 32)
        super().__init__(parent=parent)

        self.titleBar = FluentTitleBar(self)
        self.setTitleBar(self.titleBar)

        self.hBoxLayout = QHBoxLayout(self)
        self.widgetLayout = QHBoxLayout()
        self.stackedWidget = StackedWidget(self)
        self.navigationInterface = NavigationInterface(self, showReturnButton=True)

        self.hBoxLayout.setSpacing(0)
        self.hBoxLayout.setContentsMargins(0, 0, 0, 0)
        self.hBoxLayout.addWidget(self.navigationInterface)
        self.hBoxLayout.addLayout(self.widgetLayout)
        self.hBoxLayout.setStretchFactor(self.widgetLayout, 1)

        self.widgetLayout.setContentsMargins(0, 48, 0, 0)
        self.widgetLayout.setSpacing(0)
        self.widgetLayout.addWidget(self.stackedWidget)

        FluentStyleSheet.FLUENT_WINDOW.apply(self.stackedWidget)
        self.stackedWidget.setObjectName("stackedWidget")

        self.titleBar.raise_()
        self.setMicaEffectEnabled(True)
        qconfig.themeChangedFinished.connect(self._onThemeChangedFinished)

    # ---- 背景 / Mica --------------------------------------------------- #
    def _normalBackgroundColor(self):
        """窗口底色 —— 恒为**实色**，绝不返回全透明。

        ⚠️ 实测（深色主题逐点像素采样）：本机 DWM Mica 背板给出的是**浅色**
        （#f3f3f3），而窗口在去掉 WA_TranslucentBackground 后是非分层窗口，
        `paintEvent` 画全透明等于 Qt 不画底色 → 导航栏 / 底部 / 标题栏整片
        露出浅色背板，即用户实测的「深色主题左边和底部依旧是白色」。
        故不再走「透明让背板透出」，恒返回主题实色：深色 #202020、浅色
        #f0f4f9 —— 任何未被子控件覆盖的区域都保证是主题色。
        Mica 仍照常设置（被实色盖住）；将来若背板能正确输出深色可再恢复
        透明分支。
        """
        return (self._darkBackgroundColor if isDarkTheme()
                else self._lightBackgroundColor)

    def setCustomBackgroundColor(self, light, dark):
        self._lightBackgroundColor = QColor(light)
        self._darkBackgroundColor = QColor(dark)
        self._updateBackgroundColor()

    def _onThemeChangedFinished(self):
        if self.isMicaEffectEnabled():
            _set_mica(int(self.winId()), isDarkTheme())

    def setMicaEffectEnabled(self, isEnabled: bool):
        if sys.platform != "win32":
            return
        try:
            build = sys.getwindowsversion().build
        except Exception:
            build = 0
        if build < 22000:
            # 非 Win11：退化为实底（与上游一致）
            self._isMicaEnabled = False
            return
        self._isMicaEnabled = isEnabled
        if isEnabled:
            _set_mica(int(self.winId()), isDarkTheme())
        else:
            _remove_backdrop(int(self.winId()))
        self.setBackgroundColor(self._normalBackgroundColor())

    def isMicaEffectEnabled(self):
        return self._isMicaEnabled

    def paintEvent(self, e):
        super().paintEvent(e)
        painter = QPainter(self)
        painter.setPen(Qt.NoPen)
        painter.setBrush(self.backgroundColor)
        painter.drawRect(self.rect())

    def showEvent(self, e):
        super().showEvent(e)
        if self.isMicaEffectEnabled():
            _set_mica(int(self.winId()), isDarkTheme())

    # ---- 页面管理 ------------------------------------------------------ #
    def addSubInterface(self, interface: QWidget, icon, text: str,
                        position=None, parent=None, isTransparent=False):
        from . import NavigationItemPosition
        pos = NavigationItemPosition.TOP if position is None else position

        if not interface.objectName():
            raise ValueError("The object name of `interface` can't be empty string.")

        interface.setProperty("isStackedTransparent", isTransparent)
        self.stackedWidget.addWidget(interface)

        routeKey = interface.objectName()
        item = self.navigationInterface.addItem(
            routeKey=routeKey, icon=icon, text=text,
            onClick=lambda: self.switchTo(interface),
            position=pos, tooltip=text)

        if self.stackedWidget.count() == 1:
            self.stackedWidget.currentChanged.connect(
                self._onCurrentInterfaceChanged)
            self.navigationInterface.setCurrentItem(routeKey)

        self._updateStackedBackground()
        return item

    def removeInterface(self, interface: QWidget, isDelete=False):
        self.navigationInterface.removeWidget(interface.objectName())
        self.stackedWidget.removeWidget(interface)
        interface.hide()
        if isDelete:
            interface.deleteLater()

    def switchTo(self, interface: QWidget):
        self.stackedWidget.setCurrentWidget(interface)

    def _onCurrentInterfaceChanged(self, index: int):
        widget = self.stackedWidget.widget(index)
        if widget is not None:
            self.navigationInterface.setCurrentItem(widget.objectName())
        self._updateStackedBackground()

    def _updateStackedBackground(self):
        widget = self.stackedWidget.currentWidget()
        if widget is None:
            return
        isTransparent = bool(widget.property("isStackedTransparent"))
        if bool(self.stackedWidget.property("isTransparent")) == isTransparent:
            return
        self.stackedWidget.setProperty("isTransparent", isTransparent)
        self.stackedWidget.setStyle(QApplication.style())

    # ---- 布局 ---------------------------------------------------------- #
    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.titleBar.move(46, 0)
        self.titleBar.resize(self.width() - 46, self.titleBar.height())
        self.titleBar.raise_()
        # ⚠️ 这里**不能**写 `navigationInterface.setFixedHeight(self.height())`
        # （上游原样如此，本项目删除）：导航栏就在本窗口的 hBoxLayout 里，
        # 垂直策略 Preferred 会随窗口自动拉伸铺满，这行纯属冗余；而
        # setFixedHeight 会把导航栏的**最小高度**钉成当前窗口高度——窗口
        # 布局的最小高度从此等于「上一次的窗口高度」，于是：
        #   ① 用户拖小窗口 → 布局最小高度还是旧值 → 若此刻发生布局激活，
        #      SetDefaultConstraint 按旧高度把窗口**撑回**，缩小被吞；
        #   ② 放大后再也缩不回去（最小高度被撑到放大后的值）；
        #   ③ 拖上边缘向下 = 缩小高度，被钉住后系统退化为「只移动窗口」。
        # 实测触发条件（2026-10-18）：停在「语音转录」分段时，页内多个
        # word-wrap 标签随宽度重排 → LayoutRequest 上传到窗口布局 → 激活
        # → 高度弹回缩小前的值（1180x664 缩到 880x620，秒回 880x664；
        # 放大到 950 后再缩，钉在 950）。换到「字幕翻译」等只拉伸、不重排
        # 的页面则完全正常——与用户实测「换一个页面，缩放功能就正常」
        # 逐字吻合。导航栏该多高由布局说了算，不该由这行代码替窗口记尺寸。

    def setWindowTitle(self, title: str):
        super().setWindowTitle(title)
        self.titleBar.setTitle(title)

    def setWindowIcon(self, icon):
        super().setWindowIcon(icon)
        self.titleBar.setIcon(icon)
