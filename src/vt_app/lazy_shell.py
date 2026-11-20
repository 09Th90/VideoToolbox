# -*- coding: utf-8 -*-
# @version 3.1.4
"""惰性页外壳（原 video_toolbox_qt.py 同名代码，逐字下沉）。"""
from PySide6.QtWidgets import QVBoxLayout, QWidget

#: SpinBox 兼容补丁的一次性安装状态（见 _install_spinbox_fix_once）
_SPINBOX_FIX_STATE = {"done": False}


def _install_spinbox_fix_once():
    """SpinBox 兼容补丁的一次性安装（幂等）。

    探测函数本身会建一个真 SpinBox 跑一轮布局（≈0.6s，含一次性 QStyle
    初始化），因此**不能留在启动关键路径上**。调用时机：
      ① 惰性页外壳 ensure() 构造真身前（首帧后，样式已初始化，≈10ms）；
      ② 引擎工作台 _build_now 前；
      ③ main() 首帧后的 singleShot(0)（兜底：任何遗漏的构造路径）。
    """
    if _SPINBOX_FIX_STATE["done"]:
        return
    _SPINBOX_FIX_STATE["done"] = True
    try:
        import qt_compat
        qt_compat.install_spinbox_fix()
    except Exception:
        pass


class _LazyPageShell(QWidget):
    """惰性页外壳（2026-10-20 启动 <5s 专项）。

    导航项与堆叠索引在 MainWindow 构造时就用**外壳**占好（导航顺序、
    switchTo、page_by_key、事件过滤器全部不变），真身推迟到「首次被
    显示」或「首次被取用属性」时才构造——启动关键路径上只付一个空
    QWidget 的代价。实测三个重页（视频处理 1.2s / 设置 0.3s /
    字幕编辑 0.2s，真实平台）构造期从首帧前挪到首帧后。

    属性转发（``__getattr__``）：``window.download_page.url_edit`` 之类
    既有调用点零改动——首次取用即触发构造并转发到真身。外壳自身属性
    （real/_win/_builder）在实例字典里，不会进入转发路径。
    """

    def __init__(self, win, builder, name, objname):
        super().__init__()
        self._win = win
        self._builder = builder
        self._shell_name = name
        # objectName 必须与真身一致：qfluentwidgets 拿它当 routeKey，
        # 导航/截图/自检都按名字找页
        self.setObjectName(objname)
        self.real = None
        #: 真身建好后才执行的回调（见 defer）。2026-10-21 加：流水线在启动时
        #: 只是「把 pipe 接上」，不该为此把整页建出来（实测 3.82s）。
        self._pending = []
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)

    def defer(self, fn):
        """登记「真身建好后执行」的回调；真身已存在则立即执行。

        与直接取属性（``shell.attach(...)``）的区别：后者经 ``__getattr__``
        会**立刻构造整页**，把按需加载变成启动期开销。
        """
        if self.real is not None:
            try:
                fn(self.real)
            except Exception:  # noqa: BLE001
                pass
            return
        self._pending.append(fn)

    def ensure(self):
        """构造真身（幂等）并挂进外壳；返回真身。

        v3.1.4：builder 抛异常时不再让外壳保持空布局——空壳会被
        ui_theme 的实例级 paintEvent 画上背景图，用户看到的就是「整页
        只剩背景」（设置页曾因缺 tools/decision_client.py 如此）。现在
        落盘 traceback + 挂占位控件明示失败，对齐自动化页的占位模式。
        """
        if self.real is None:
            _install_spinbox_fix_once()   # 补丁必须先于任何 SpinBox 存在
            try:
                self.real = self._builder()
            except Exception as e:  # noqa: BLE001
                self._pending = []      # 占位控件接不了真身回调，弃掉防噪
                try:
                    import sys
                    from vt_app.boot import _crash_log_write
                    _crash_log_write("页面构建", *sys.exc_info()[:3])
                except Exception:  # noqa: BLE001
                    pass
                self.real = self._build_placeholder(e)
            self.layout().addWidget(self.real)
            try:
                # 事件过滤器补挂真身（外壳在建窗时已挂过一份）
                self._win.installEventFilter(self.real)
            except Exception:  # noqa: BLE001
                pass
            pending, self._pending = self._pending, []
            for fn in pending:
                try:
                    fn(self.real)
                except Exception:  # noqa: BLE001
                    pass
        return self.real

    def _build_placeholder(self, exc):
        """构建失败占位页：明示错误与日志位置，绝不静默空白。"""
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QLabel
        box = QWidget(self)
        box.setObjectName(self.objectName() + "_BuildFailed")
        lay = QVBoxLayout(box)
        lay.setContentsMargins(32, 32, 32, 32)
        lbl = QLabel(
            "「%s」页构建失败：%s\n\n"
            "详细堆栈见 logs\\crash.log（「页面构建」段）。\n"
            "多为随包组件缺失或配置损坏：补齐依赖或重装/在线更新后重启程序。"
            % (self._shell_name, exc), box)
        lbl.setWordWrap(True)
        lbl.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        lay.addWidget(lbl)
        lay.addStretch(1)
        return box

    def showEvent(self, event):
        super().showEvent(event)
        self.ensure()

    def __getattr__(self, name):
        # ⚠ 仅当外壳自身（含 Qt 基类）没有该属性时才走到这里。
        #   以 dunder 开头的名字直接抛 AttributeError——PySide6 内部
        #   探测（__deepcopy__/__getstate__ 等）不该触发整页构造。
        if name.startswith("__") and name.endswith("__"):
            raise AttributeError(name)
        real = self.ensure()
        return getattr(real, name)


def _lazy_real(page):
    """取惰性外壳的真身；**没建过就返回 None**（绝不触发构造）。

    与直接 ``shell.attach(...)`` 的区别：后者经 ``__getattr__`` 会立刻把整页
    建出来。后台消息（流水线日志/状态）到达时只该更新**已存在**的界面，
    不该为了投递一条日志而付出建页的代价。
    """
    if isinstance(page, _LazyPageShell):
        return page.real
    return page