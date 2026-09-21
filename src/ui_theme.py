# -*- coding: utf-8 -*-
# @version 1.15.7
"""界面美化：主题感知的全局视觉体系 + 每个导航板块自定义背景图。

两块能力，配置都持久化在 `data/ui_custom.json`（engine.DATA_DIR 下），
全部改动立即生效、重启保持：

1) 全局视觉体系（所有页面统一换新，**主题感知**）：
   · build_app_qss()  → 全局 QSS：输入框/菜单/工具提示/滚动条/进度条，
     深色主题用深色规范（#2B2E33 底、#3A3E45 边），浅色主题用浅灰底浅边；
   · 输入类控件成套补齐  → 数字框的上下箭头、下拉框的箭头、复选框的方框
     都换成与主题同色的小图形（QPainter 现场生成 PNG，见 _input_icon），
     不再露出系统原生的老式三角箭头/方框；
   · dialog_palette() / dialog_qss() → 顶层对话框（颜色选择框等）的兜底
     主题：这类框由 Qt 自己构造，会从父窗口继承 palette，「字幕编辑」页
     是深色控制台风格，浅色主题下就会整块发暗（用户截图反馈）；
   · UICard           → 统一卡片皮肤：圆角 10、1px 描边、hover 提亮，
     深色下 #26292E 实底、浅色下白色实底（card() 与视频库缩略图卡共用）；
   · 主题色可配置     → ACCENT_PRESETS 预设色板，点一下 setThemeColor
     全局生效并持久化（输入框聚焦/滑杆/QSS 同步取当前主题色）；
   · 主题三档持久化   → 深色/浅色/跟随系统记进配置，切换时**立即**重应用
     全局 QSS + 通知已注册控件（on_theme_change / connect_theme）重启保持；
     「跟随系统」档在系统深浅切换时也会自动跟随（qconfig.themeChanged）。

2) 每个板块自定义背景图（v1.13.x 已有，本次增强）：
   六个导航页（视频处理/视频库/字幕处理/字幕编辑/流水线/设置）可各自铺一张
   背景图，另有「全局背景」兜底；新增「背景模糊」开关（预模糊缓存，
   不拖累重绘），遮罩为主题感知的竖向渐变：深色主题压暗（黑色）、
   浅色主题雾白提亮（白色）——两档下前景文字都可读。
   另提供**板块遮罩**（v1.14.x）：与是否设置背景图无关，透明度非 0 时
   给**每个板块（卡片）的底色**统一设置同透明度——卡片变半透明、透出
   背景图/实底，六页卡片观感一致。

实现方式（刻意选最保守的一种）：
  · 对页面 QWidget 做**实例级 paintEvent 覆盖**——先调原 QWidget.paintEvent
    保留既有底色/样式，再按 cover 模式画背景图，最后叠主题遮罩。
  · **未设置背景图时什么都不画**：与改造前逐像素一致，不影响自检基线。
  · 子控件完全不动：卡片（UICard）不透明，天然形成「卡片浮在背景图上」
    的层次；滚动区在页面里本就是 transparent 的（ScrollPage/TabPage）。
  · 不写注册表、不碰其它配置文件；损坏/缺失的配置一律回退默认。

线程约定：全部接口只能在**主线程**调用（QWidget 绘制本就要求如此）。

已知边界：
  · 背景只铺**内容区**（导航条/标题栏保持 Mica 原样）；
  · 「字幕处理」页内嵌引擎界面自带部分不透明容器，背景能透出的范围以
    容器透明度为准；
  · 「字幕编辑」页的视频画面是 mpv 原生子窗口，始终不透明，属于预期；
  · 波形时间轴/字幕表/媒体控制条保持「深色控制台」风格（与剪映等一致），
    不随浅色主题翻转——浅色页面里深色时间轴是专业剪辑软件的常态。
"""

import json
import os

from PyQt5.QtCore import QPointF, QRectF, Qt
from PyQt5.QtGui import (QColor, QLinearGradient, QPainter, QPalette, QPen,
                         QPixmap)
from PyQt5.QtWidgets import (QApplication, QGraphicsBlurEffect, QGraphicsScene,
                             QWidget)

import video_toolbox as engine

#: 配置文件名（落在 engine.DATA_DIR，与 subtitle_style.json 同级）
CONFIG_FILE = "ui_custom.json"

#: 板块定义：(配置键, 显示名)。键与 MainWindow.page_by_key() 一致。
PAGE_DEFS = [
    ("download", "视频处理"),
    ("library", "视频库"),
    ("subtitle", "字幕处理"),
    ("edit", "字幕编辑"),
    ("pipeline", "流水线"),
    ("settings", "设置"),
]

#: 全部合法配置键（含 global 兜底键）
_ALL_KEYS = tuple([k for k, _ in PAGE_DEFS] + ["global"])

#: 默认暗化比例（%）。背景图上叠一层暗色遮罩，0=原图直出，90=几乎全黑。
DEFAULT_DIM = 55
#: 暗化上限（%）——留 10% 保证背景图永远隐约可见，不至于完全失效
DIM_MAX = 90

#: 板块遮罩默认透明度（%）。0=不叠加（保持现状），>0 时**每个板块**内容区
#: 统一叠一层同透明度的遮罩（与是否设置背景图无关），让六页风格一致。
DEFAULT_SECTION_DIM = 0
#: 板块遮罩透明度上限（%）
SECTION_DIM_MAX = 90

#: 背景模糊半径（px，固定档；开关式而非连续可调，避免每次重绘都算模糊）
BLUR_RADIUS = 24

# ---------------------------------------------------------------------- #
# 设计 token（深色 = 原「UI 美化设计」深色规范；浅色 = 同构的浅色规范）
# ---------------------------------------------------------------------- #
#: 默认主题色（设计稿确认的亮绿；旧品牌绿 #2F8D63 保留在预设里可一键切回）
DEFAULT_ACCENT = "#45C877"
#: 主题色预设（设置页「界面」卡片里点选；首项为默认，第二项为旧品牌绿）
ACCENT_PRESETS = ["#45C877", "#2F8D63", "#3B82F6", "#06B6D4",
                  "#8B5CF6", "#EC4899", "#F59E0B", "#EF4444"]

#: 深色设计 token。键集与 TOKENS_LIGHT 完全一致（新增键两表同步加）：
#:   card*          UICard 三态底色 / 描边
#:   input_bg*      输入类控件（QLineEdit/QTextEdit/QSpinBox）底色
#:                  ⚠️ 浅色档是**浅灰**而非纯白：卡片本身就是白的，纯白输入框
#:                  在白卡上只剩一圈极淡的描边，看上去像"没画完的空白条"
#:                  （用户截图反馈）。聚焦时转白 + 主题色描边，形成反馈。
#:   border*        通用描边 / hover 描边（QSS + 滚动条）
#:   text / text_dim / check_text   文字 / 弱文字 / 复选框文字
#:   menu_bg / menu_item_sel        菜单与工具提示底 / 菜单选中项底
#:   page_base      背景图下先铺的实底（RGB 元组）
#:   shade          背景遮罩色（RGB 元组）：深色=黑（压暗），浅色=白（雾化）
#:   log_bg / log_text / log_dim    日志控制台底 / 正文 / 时间戳等弱字
TOKENS_DARK = {
    "card": "#26292E",
    "card_hover": "#2C3037",
    "card_pressed": "#23262B",
    "card_border": "#3A3E45",
    "card_border_hover": "#4A5058",
    "input_bg": "#2B2E33",
    "input_bg_focus": "#2E3237",
    "input_disabled_bg": "#26292E",
    "border": "#3A3E45",
    "border_hover": "#4A5058",
    "text": "#E8EAED",
    "text_dim": "#9BA0A8",
    "check_text": "#C9CDD3",
    "menu_bg": "#26292E",
    "menu_item_sel": "#34383F",
    "page_base": (23, 24, 27),
    "shade": (10, 12, 14),
    "log_bg": "#1B1B1B",
    "log_text": "#D6D6D6",
    "log_dim": "#8A8A8A",
}

#: 浅色设计 token（与深色同构：白卡片浅描边、白输入框、白雾遮罩）。
TOKENS_LIGHT = {
    "card": "#FFFFFF",
    "card_hover": "#F7F9FA",
    "card_pressed": "#EFF2F4",
    "card_border": "#E1E4E8",
    "card_border_hover": "#C7CDD4",
    "input_bg": "#F6F8FA",
    "input_bg_focus": "#FFFFFF",
    "input_disabled_bg": "#F1F3F5",
    "border": "#DEE1E6",
    "border_hover": "#C4CAD2",
    "text": "#1F2226",
    "text_dim": "#697077",
    "check_text": "#3F444B",
    "menu_bg": "#FFFFFF",
    "menu_item_sel": "#EDF0F4",
    "page_base": (244, 245, 247),
    "shade": (255, 255, 255),
    "log_bg": "#F4F6F8",
    "log_text": "#33383E",
    "log_dim": "#82898F",
}

#: 合法主题档
_THEME_MODES = ("dark", "light", "auto")

# 运行期状态
#: 已注册的页面 {key: QWidget}（paintEvent 已被覆盖的页面）
_REG = {}
#: QPixmap 缓存 {path: (mtime, QPixmap)}——避免每次重绘都读盘
_PIX_CACHE = {}
#: 模糊图缓存 {(path, mtime): QPixmap}
_BLUR_CACHE = {}
#: 小图形（箭头/勾）缓存 {(kind, color, size): QSS 用的 url 片段}
_ICON_CACHE = {}
#: 内存中的配置副本（懒加载；写穿到磁盘）
_CFG = None
#: 主题变化回调列表（connect_theme 注册，weakref 保证不拖住控件）
_THEME_HOOKS = []


# ---------------------------------------------------------------------- #
# 配置读写
# ---------------------------------------------------------------------- #
def _config_path():
    """ui_custom.json 的绝对路径（数据根目录下）。"""
    try:
        return os.path.join(engine.DATA_DIR, CONFIG_FILE)
    except Exception:
        return os.path.join("data", CONFIG_FILE)


def _default_cfg():
    """默认配置结构（accent/theme/blur/mica 为 v2 新增键，旧文件缺省即默认）。"""
    return {"version": 2, "dim": DEFAULT_DIM, "blur": False,
            "accent": DEFAULT_ACCENT, "theme": "dark", "mica": True,
            "section_dim": DEFAULT_SECTION_DIM,
            "backgrounds": {k: "" for k in _ALL_KEYS}}


def _load_cfg():
    """读配置；损坏/缺失一律回退默认结构（绝不抛异常拖垮启动）。"""
    global _CFG
    if _CFG is not None:
        return _CFG
    cfg = _default_cfg()
    try:
        # utf-8-sig：兼容记事本/PowerShell 写出的带 BOM 文件
        with open(_config_path(), encoding="utf-8-sig") as f:
            raw = json.load(f)
        if isinstance(raw, dict):
            dim = raw.get("dim", DEFAULT_DIM)
            if isinstance(dim, int) and 0 <= dim <= DIM_MAX:
                cfg["dim"] = dim
            blur = raw.get("blur")
            if isinstance(blur, bool):
                cfg["blur"] = blur
            mica = raw.get("mica")
            if isinstance(mica, bool):
                cfg["mica"] = mica
            sdim = raw.get("section_dim")
            if isinstance(sdim, int) and 0 <= sdim <= SECTION_DIM_MAX:
                cfg["section_dim"] = sdim
            accent = raw.get("accent")
            if isinstance(accent, str) and QColor(accent).isValid():
                cfg["accent"] = accent.strip()
            theme = raw.get("theme")
            if theme in _THEME_MODES:
                cfg["theme"] = theme
            bgs = raw.get("backgrounds")
            if isinstance(bgs, dict):
                for k in _ALL_KEYS:
                    v = bgs.get(k)
                    if isinstance(v, str):
                        cfg["backgrounds"][k] = v.strip()
    except Exception:
        pass
    _CFG = cfg
    return _CFG


def _save_cfg():
    """写穿配置到磁盘；失败只吞掉（下次修改会再试，不影响界面）。"""
    try:
        with open(_config_path(), "w", encoding="utf-8") as f:
            json.dump(_load_cfg(), f, ensure_ascii=False, indent=2)
    except Exception:
        pass


# ---------------------------------------------------------------------- #
# 背景图（板块级）
# ---------------------------------------------------------------------- #
def get_dim():
    """当前暗化比例（0-90 的整数百分比）。"""
    return int(_load_cfg()["dim"])


def set_dim(value):
    """设置暗化比例（0-90），立即重绘全部已注册页面并持久化。"""
    value = max(0, min(DIM_MAX, int(value)))
    _load_cfg()["dim"] = value
    _save_cfg()
    refresh()


def get_blur():
    """背景模糊开关（bool）。"""
    return bool(_load_cfg()["blur"])


def set_blur(on):
    """开/关背景模糊，立即重绘全部已注册页面并持久化。"""
    _load_cfg()["blur"] = bool(on)
    _save_cfg()
    refresh()


def get_section_dim():
    """板块遮罩透明度（0-90 的整数百分比）。

    与 dim（背景遮罩）不同：板块遮罩**与是否设置背景图无关**，作用在
    每个卡片（UICard）底色的 alpha 上——卡片半透明、透出页面背景，
    是让六页视觉风格一致的统一层。
    """
    return int(_load_cfg()["section_dim"])


def set_section_dim(value):
    """设置板块遮罩透明度（0-90），立即重绘并持久化。

    遮罩画在每个卡片（UICard）底色的 alpha 上，页面浅刷不足以让卡片
    重绘（同切主题的坑：父 update() 不触发子卡片 paintEvent），必须
    deep=True 连子控件一起刷。写入很小，拖动滑条的高频调用可接受。
    """
    value = max(0, min(SECTION_DIM_MAX, int(value)))
    _load_cfg()["section_dim"] = value
    _save_cfg()
    refresh(deep=True)


def section_dim_card_fill(state="card"):
    """所有卡片**统一**的底色：token 三态 + 板块遮罩透明度。

    无论遮罩是否开启，UICard 与 qfluentwidgets 原生卡片都从这里取色，
    保证任何滑条位置下两者完全同色同透明度（用户三轮实测反馈的最终
    形态：归零时原生行卡的"白 170"材质与大卡纯白也不一样，必须统一）。
    sdim=0 → 不透明 token 色（与旧 UICard 基线逐像素一致）；
    sdim>0 → token 色 + 统一 alpha，透出页面背景。
    state ∈ card / card_hover / card_pressed。
    """
    sdim = get_section_dim()
    c = QColor(tokens()[state])
    c.setAlpha(max(0, 255 - int(round(sdim / 100.0 * 255))))
    return c


def get_bg(key):
    """某板块单独设置的背景图路径；未设置返回 ''。"""
    return _load_cfg()["backgrounds"].get(key, "")


def get_effective_bg(key):
    """板块实际生效的背景：优先单独设置，否则用全局背景。"""
    path = get_bg(key)
    return path if path else get_bg("global")


def has_any_bg():
    """是否已有任一板块（或全局）设置了背景图。

    暗化/模糊只影响背景图，一张背景都没有时调它们不会有任何可见变化。
    """
    return any(get_effective_bg(k) for k in _ALL_KEYS)


def set_bg(key, path):
    """设置板块（或 global）背景图；空路径等价于清除。立即生效并持久化。"""
    if key not in _ALL_KEYS:
        return
    _load_cfg()["backgrounds"][key] = (path or "").strip()
    _save_cfg()
    refresh()


def clear_bg(key):
    """清除板块（或 global）背景图。立即生效并持久化。"""
    set_bg(key, "")


# ---------------------------------------------------------------------- #
# 主题色 / 主题档
# ---------------------------------------------------------------------- #
def get_accent():
    """当前主题色（#RRGGBB）。"""
    return _load_cfg()["accent"]


def set_accent(hexcolor):
    """设置主题色：立即 setThemeColor + 重应用全局 QSS + 持久化。"""
    c = QColor(str(hexcolor).strip())
    if not c.isValid():
        return
    hexcolor = c.name().upper()
    _load_cfg()["accent"] = hexcolor
    _save_cfg()
    try:
        from qfluentwidgets import setThemeColor
        setThemeColor(QColor(hexcolor))
    except Exception:
        pass
    try:
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(build_app_qss())
    except Exception:
        pass
    refresh()


def get_theme_mode():
    """主题档（'dark' / 'light' / 'auto'）。"""
    return _load_cfg()["theme"]


def is_dark():
    """当前是否深色外观。

    dark/light 档直接判断；auto 档问 qfluentwidgets（setTheme(AUTO) 后
    它内部已把系统深浅解析进 qconfig.theme），解析不了再探系统、最终回退深色。
    """
    mode = get_theme_mode()
    if mode == "dark":
        return True
    if mode == "light":
        return False
    try:
        from qfluentwidgets import isDarkTheme
        return bool(isDarkTheme())
    except Exception:
        pass
    try:
        from qfluentwidgets import isSystemDarkTheme
        return bool(isSystemDarkTheme())
    except Exception:
        return True


def tokens():
    """当前主题的设计 token（dict；深浅两套键集一致，见 TOKENS_DARK 注释）。"""
    return TOKENS_DARK if is_dark() else TOKENS_LIGHT


def connect_theme(widget, fn):
    """注册控件级主题变化回调：主题档/系统深浅切换时调 `fn(widget)`。

    用 weakref 挂住控件——控件析构后回调自动失效并从列表里清掉，
    不会拖住页面无法回收。回调里通常重新 setStyleSheet + update。
    """
    import weakref
    ref = weakref.ref(widget)

    def _hook():
        w = ref()
        if w is None:
            _drop_hook(_hook)
            return
        try:
            fn(w)
        except RuntimeError:
            # C++ 对象已删（Python 包装还在的窗口期）
            _drop_hook(_hook)
        except Exception:
            pass

    _THEME_HOOKS.append(_hook)


def _drop_hook(hook):
    try:
        _THEME_HOOKS.remove(hook)
    except ValueError:
        pass


def _fire_theme_hooks():
    """依次调用主题回调；单个失败不影响其他控件。"""
    for hook in list(_THEME_HOOKS):
        try:
            hook()
        except Exception:
            pass


def set_theme_mode(mode):
    """设置并持久化主题档；**立即**重应用全局 QSS + 通知控件 + 深度重绘。

    旧实现只 setTheme + 刷新页面背景——导航条/标题栏切了浅色，卡片、
    输入框、背景遮罩还停在深色 token 上，就是「浅色页面里一半深一半浅」
    的根源。现在切档后重生成 QSS（UICard/遮罩走 paintEvent 自然取新色）。
    """
    if mode not in _THEME_MODES:
        return
    _load_cfg()["theme"] = mode
    _save_cfg()
    try:
        from qfluentwidgets import setTheme
        setTheme(qtheme())
    except Exception:
        pass
    try:
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(build_app_qss())
    except Exception:
        pass
    _fire_theme_hooks()
    refresh(deep=True)


def qtheme():
    """配置里的主题档 → qfluentwidgets.Theme 枚举。"""
    from qfluentwidgets import Theme
    return {"dark": Theme.DARK, "light": Theme.LIGHT,
            "auto": Theme.AUTO}.get(get_theme_mode(), Theme.DARK)


def get_mica():
    """云母特效开关（bool）。仅持久化状态；窗口效果由主窗口应用。"""
    return bool(_load_cfg()["mica"])


def set_mica(on):
    """持久化云母特效开关（窗口效果由设置页立即应用到主窗口）。"""
    _load_cfg()["mica"] = bool(on)
    _save_cfg()


def apply_startup_theme(app):
    """main() 里一次性应用：主题档 + 主题色 + 全局 QSS。

    「跟随系统」档：qfluentwidgets 的 setTheme(AUTO) 自身会监听系统深浅，
    这里再挂 qconfig.themeChanged——系统深浅翻转时重应用全局 QSS、通知
    已注册控件并深度重绘（否则只有 fluent 组件跟着变，我们的 QSS/卡片
    停在旧外观上）。信号挂接失败只影响 auto 跟随，不影响启动。
    """
    from qfluentwidgets import setTheme, setThemeColor
    setTheme(qtheme())
    setThemeColor(QColor(get_accent()))
    try:
        from qfluentwidgets import qconfig

        def _on_theme_changed(*_):
            try:
                app.setStyleSheet(build_app_qss())
            except Exception:
                pass
            _fire_theme_hooks()
            refresh(deep=True)

        qconfig.themeChanged.connect(_on_theme_changed)
    except Exception:
        pass
    if os.environ.get("VT_NO_UI_QSS"):
        return
    try:
        app.setStyleSheet(build_app_qss())
    except Exception:
        pass


# ---------------------------------------------------------------------- #
# 小图形资源（QSS 的 image 只吃文件路径，所以现场画一枚 PNG 落盘）
# ---------------------------------------------------------------------- #
def _tint(color, alpha):
    """十六进制色 → `rgba(r, g, b, a)` 字符串（QSS 里做半透明 tint）。"""
    c = QColor(color)
    if not c.isValid():
        c = QColor(DEFAULT_ACCENT)
    return "rgba(%d, %d, %d, %.2f)" % (c.red(), c.green(), c.blue(), alpha)


def _icon_path(kind, color, size=10):
    """生成/复用一枚小图形 PNG，返回 QSS 可用的 `url("...")` 片段。

    `kind`：up（上箭头）/ down（下箭头）/ check（对勾）。
    颜色写进文件名——切主题时颜色变、取到的就是另一个文件，不会出现
    "旧主题的箭头被 QPixmap 缓存住"这种问题。

    没有 QApplication（纯逻辑单测）时返回 "none"：既省去无谓落盘，也避免
    在 app 之前构造 QPixmap 直接 abort（本仓踩过：QPixmap 必须在 app 之后）。
    """
    key = (kind, str(color), int(size))
    if key in _ICON_CACHE:
        return _ICON_CACHE[key]
    if QApplication.instance() is None:
        return "none"
    url = "none"
    try:
        d = os.path.join(engine.DATA_DIR, "ui_assets")
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, "%s_%s_%d.png" % (
            kind, str(color).lstrip("#").lower(), int(size)))
        if not os.path.exists(path):
            pm = QPixmap(int(size), int(size))
            pm.fill(Qt.transparent)
            p = QPainter(pm)
            p.setRenderHint(QPainter.Antialiasing, True)
            pen = QPen(QColor(color), 1.4)
            pen.setCapStyle(Qt.RoundCap)
            pen.setJoinStyle(Qt.RoundJoin)
            p.setPen(pen)
            s = float(size)
            if kind == "up":
                p.drawPolyline(QPointF(s * 0.22, s * 0.64),
                               QPointF(s * 0.50, s * 0.34),
                               QPointF(s * 0.78, s * 0.64))
            elif kind == "down":
                p.drawPolyline(QPointF(s * 0.22, s * 0.36),
                               QPointF(s * 0.50, s * 0.66),
                               QPointF(s * 0.78, s * 0.36))
            else:                       # check
                p.drawPolyline(QPointF(s * 0.22, s * 0.52),
                               QPointF(s * 0.42, s * 0.72),
                               QPointF(s * 0.78, s * 0.26))
            p.end()
            pm.save(path, "PNG")
        url = '"%s"' % path.replace("\\", "/")
    except Exception:
        url = "none"
    _ICON_CACHE[key] = url
    return url


# ---------------------------------------------------------------------- #
# 全局 QSS
# ---------------------------------------------------------------------- #
def build_app_qss():
    """全局 QSS：按当前主题 token 生成（深色深底浅字，浅色白底深字）。

    只样式化**普通 Qt 控件**；qfluentwidgets 自绘组件（按钮/下拉/开关等）
    跟随 setThemeColor，不在这里硬管。应用级样式表会被控件自身样式表
    覆盖，内嵌字幕引擎界面自带完整样式，不受影响。

    排查开关：`VT_UI_QSS_GROUPS=input,menu,misc,scroll`（逗号分隔）只启用
    指定规则组——用于定位样式表与内嵌引擎界面的相性问题。
    规则组：line / textedit / spin / combo / check / menu / misc / scroll。
    """
    accent = get_accent()
    t = tokens()
    only = os.environ.get("VT_UI_QSS_GROUPS", "").strip()
    allow = ({s.strip() for s in only.split(",") if s.strip()}
             if only else {"line", "textedit", "spin", "combo", "check",
                           "menu", "misc", "scroll"})
    parts = []
    # ⚠️ 注意：不给 QLineEdit/QTextEdit 配 selection-background-color 等选区色
    # 不是因为崩溃——「字幕处理」页退出阶段偶发 native 段错误（rc≈139，
    # 约 1/3 概率）经 13 次有/无 QSS 对照确认是**既有的引擎内嵌界面退出
    # 时序问题**，与样式表无关（VT_NO_UI_QSS=1 也复现）。选区色省略只是
    # 顺带收敛样式面；选区高亮交给 qfluentwidgets 主题默认值。
    if "line" in allow:
        parts.append(f"""
QLineEdit {{
    background: {t['input_bg']}; color: {t['text']};
    border: 1px solid {t['border']}; border-radius: 6px; padding: 3px 8px;
    min-height: 20px;
}}
QLineEdit:focus {{
    background: {t['input_bg_focus']}; border: 1px solid {accent};
}}
QLineEdit:disabled {{
    background: {t['input_disabled_bg']}; color: {t['text_dim']};
}}
""")
    if "textedit" in allow:
        parts.append(f"""
QTextEdit, QPlainTextEdit {{
    background: {t['input_bg']}; color: {t['text']};
    border: 1px solid {t['border']}; border-radius: 6px; padding: 3px 8px;
}}
QTextEdit:focus, QPlainTextEdit:focus {{
    background: {t['input_bg_focus']}; border: 1px solid {accent};
}}
QTextEdit:disabled, QPlainTextEdit:disabled {{
    background: {t['input_disabled_bg']}; color: {t['text_dim']};
}}
""")
    if "spin" in allow:
        up = _icon_path("up", t["text_dim"])
        down = _icon_path("down", t["text_dim"])
        parts.append(f"""
QSpinBox, QDoubleSpinBox {{
    background: {t['input_bg']}; color: {t['text']};
    border: 1px solid {t['border']}; border-radius: 6px;
    padding: 1px 18px 1px 7px; min-height: 20px;
}}
QSpinBox:focus, QDoubleSpinBox:focus {{
    background: {t['input_bg_focus']}; border: 1px solid {accent};
}}
QSpinBox:disabled, QDoubleSpinBox:disabled {{
    background: {t['input_disabled_bg']}; color: {t['text_dim']};
}}
QSpinBox::up-button, QDoubleSpinBox::up-button {{
    subcontrol-origin: border; subcontrol-position: top right;
    width: 16px; height: 11px; border: none; background: transparent;
    border-top-right-radius: 6px; margin: 1px 1px 0 0;
}}
QSpinBox::down-button, QDoubleSpinBox::down-button {{
    subcontrol-origin: border; subcontrol-position: bottom right;
    width: 16px; height: 11px; border: none; background: transparent;
    border-bottom-right-radius: 6px; margin: 0 1px 1px 0;
}}
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {{
    background: {_tint(accent, 0.18)};
}}
QSpinBox::up-button:pressed, QDoubleSpinBox::up-button:pressed,
QSpinBox::down-button:pressed, QDoubleSpinBox::down-button:pressed {{
    background: {_tint(accent, 0.34)};
}}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{
    image: url({up}); width: 10px; height: 10px;
}}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{
    image: url({down}); width: 10px; height: 10px;
}}
""")
    if "combo" in allow:
        caret = _icon_path("down", t["text_dim"])
        parts.append(f"""
QComboBox, QFontComboBox {{
    background: {t['input_bg']}; color: {t['text']};
    border: 1px solid {t['border']}; border-radius: 6px;
    padding: 1px 22px 1px 8px; min-height: 20px;
}}
QComboBox:hover, QFontComboBox:hover {{
    border: 1px solid {t['border_hover']};
}}
QComboBox:focus, QFontComboBox:focus {{
    background: {t['input_bg_focus']}; border: 1px solid {accent};
}}
QComboBox:disabled, QFontComboBox:disabled {{
    background: {t['input_disabled_bg']}; color: {t['text_dim']};
}}
QComboBox::drop-down, QFontComboBox::drop-down {{
    subcontrol-origin: border; subcontrol-position: top right;
    width: 22px; border: none; background: transparent;
    border-top-right-radius: 6px; border-bottom-right-radius: 6px;
}}
QComboBox::drop-down:hover, QFontComboBox::drop-down:hover {{
    background: {_tint(accent, 0.18)};
}}
QComboBox::down-arrow, QFontComboBox::down-arrow {{
    image: url({caret}); width: 10px; height: 10px;
}}
QComboBox QAbstractItemView, QFontComboBox QAbstractItemView {{
    background: {t['menu_bg']}; color: {t['text']};
    border: 1px solid {t['border']}; border-radius: 8px; padding: 4px;
    outline: 0; selection-background-color: {_tint(accent, 0.22)};
    selection-color: {t['text']};
}}
QComboBox QAbstractItemView::item, QFontComboBox QAbstractItemView::item {{
    min-height: 24px; padding: 1px 6px; border-radius: 6px;
}}
""")
    if "check" in allow:
        tick = _icon_path("check", "#FFFFFF")
        parts.append(f"""
QCheckBox, QRadioButton {{ color: {t['check_text']}; spacing: 6px; }}
QCheckBox::indicator {{
    width: 15px; height: 15px; border: 1px solid {t['border_hover']};
    border-radius: 4px; background: {t['input_bg']};
}}
QCheckBox::indicator:hover {{ border: 1px solid {accent}; }}
QCheckBox::indicator:checked {{
    background: {accent}; border: 1px solid {accent}; image: url({tick});
}}
QCheckBox::indicator:disabled {{
    background: {t['input_disabled_bg']}; border: 1px solid {t['border']};
}}
QRadioButton::indicator {{
    width: 15px; height: 15px; border: 1px solid {t['border_hover']};
    border-radius: 8px; background: {t['input_bg']};
}}
QRadioButton::indicator:checked {{
    border: 4px solid {accent}; background: {t['input_bg']};
}}
""")
    if "menu" in allow:
        parts.append(f"""
QMenu {{
    background: {t['menu_bg']}; color: {t['text']};
    border: 1px solid {t['border']}; border-radius: 8px; padding: 4px;
}}
QMenu::item {{ padding: 5px 24px; border-radius: 6px; }}
QMenu::item:selected {{ background: {t['menu_item_sel']}; }}
QMenu::separator {{ height: 1px; background: {t['border']}; margin: 4px 8px; }}
QToolTip {{
    background: {t['menu_bg']}; color: {t['text']};
    border: 1px solid {t['border']}; padding: 3px 8px;
}}
""")
    if "misc" in allow:
        parts.append(f"""
QProgressBar {{
    background: {t['input_bg']}; border: none; border-radius: 4px;
    color: {t['text']}; text-align: center;
}}
QProgressBar::chunk {{ background: {accent}; border-radius: 4px; }}
""")
    if "scroll" in allow:
        parts.append(f"""
QScrollBar:vertical {{ background: transparent; width: 8px; margin: 2px; }}
QScrollBar::handle:vertical {{
    background: {t['border']}; border-radius: 2px; min-height: 32px;
}}
QScrollBar::handle:vertical:hover {{ background: {t['border_hover']}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: transparent;
}}
QScrollBar:horizontal {{ background: transparent; height: 8px; margin: 2px; }}
QScrollBar::handle:horizontal {{
    background: {t['border']}; border-radius: 2px; min-width: 32px;
}}
QScrollBar::handle:horizontal:hover {{ background: {t['border_hover']}; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
    background: transparent;
}}
""")
    return "".join(parts)


# ---------------------------------------------------------------------- #
# 顶层对话框（颜色选择框等）兜底主题
# ---------------------------------------------------------------------- #
def dialog_palette():
    """按当前主题造一份 QPalette，给 Qt 自建的顶层对话框兜底。

    为什么需要：`QColorDialog.getColor(...)` 这类框由 Qt 自己构造，外观完全
    取 palette，而 palette 是**从父窗口继承**的。「字幕编辑」页是深色控制台
    风格（波形/字幕表不随浅色翻转），浅色主题下弹出的颜色框就整块发暗，
    与白色属性面板并排像两个软件（用户截图反馈）。
    """
    t = tokens()
    accent = get_accent()
    pal = QPalette()
    pal.setColor(QPalette.Window, QColor(t["card"]))
    pal.setColor(QPalette.WindowText, QColor(t["text"]))
    pal.setColor(QPalette.Base, QColor(t["input_bg"]))
    pal.setColor(QPalette.AlternateBase, QColor(t["log_bg"]))
    pal.setColor(QPalette.Text, QColor(t["text"]))
    pal.setColor(QPalette.Button, QColor(t["input_bg"]))
    pal.setColor(QPalette.ButtonText, QColor(t["text"]))
    pal.setColor(QPalette.Highlight, QColor(accent))
    pal.setColor(QPalette.HighlightedText, QColor("#FFFFFF"))
    pal.setColor(QPalette.ToolTipBase, QColor(t["menu_bg"]))
    pal.setColor(QPalette.ToolTipText, QColor(t["text"]))
    pal.setColor(QPalette.Disabled, QPalette.Text, QColor(t["text_dim"]))
    pal.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(t["text_dim"]))
    return pal


def dialog_qss():
    """顶层对话框的样式表：与页面同 token（配色、圆角、主按钮）。

    ⚠️ 这里**不重复**写 QLineEdit / QSpinBox：全局 QSS 已经把它们（含上下
    箭头、下拉箭头）管起来了；对话框样式表里再写一遍会把全局那套子控件规则
    挡掉，箭头会退回系统原生的老式三角。
    """
    t = tokens()
    accent = get_accent()
    return f"""
/* ⚠️ 底色必须由 QSS 钉死：主窗口（Mica FluentWindow）的 palette.Window 是黑的，
   顶层对话框在建窗时会把那套 palette 继承过去——只靠 setPalette 会被打回来
   （见 subtitle_editor.ThemedColorDialog 的注释）。 */
QDialog, QColorDialog {{ background-color: {t['card']}; color: {t['text']}; }}
QDialog QLabel {{ color: {t['text']}; background: transparent; }}
QDialog QPushButton {{
    background: {t['input_bg']}; color: {t['text']};
    border: 1px solid {t['border']}; border-radius: 6px;
    padding: 3px 14px; min-width: 60px; min-height: 20px;
}}
QDialog QPushButton:hover {{
    background: {t['card_hover']}; border: 1px solid {t['border_hover']};
}}
QScrollArea, QAbstractScrollArea {{ background: {t['card']}; border: none; }}
"""


def primary_button_qss():
    """主题色主按钮皮肤（实底白字）：给「确定」这类主操作打标。

    ⚠️ 必须**直接设在按钮自己身上**：这些按钮是对话框的子控件，而对话框又挂在
    属性面板下——面板自己的样式表里有一条不带前缀的 `QPushButton` 规则，实测
    它会把对话框样式表里的 `:default` 覆盖掉（OK 按钮仍是灰底）。
    """
    accent = get_accent()
    return f"""
QPushButton {{
    background: {accent}; color: #FFFFFF;
    border: 1px solid {accent}; border-radius: 6px;
    padding: 3px 14px; min-width: 60px;
}}
QPushButton:hover {{ background: {_tint(accent, 0.86)}; }}
QPushButton:pressed {{ background: {_tint(accent, 0.72)}; }}
"""


# ---------------------------------------------------------------------- #
# 统一卡片皮肤
# ---------------------------------------------------------------------- #
def _make_uiclass():
    """构造 UICard：CardWidget 子类（工厂函数，避免模块顶层散落子类细节）。

    默认 CardWidget 只画上下两段弧线高光、圆角 5、底色是半透明白叠深底
    （纯深底上还行，铺了背景图后显得发灰）。按设计稿换成：不透明实底
    + 全周 1px 描边 + hover 提亮、按压压暗，圆角 10。三态底色与描边
    **每次绘制时按当前主题 token 取**——深色下 #26292E 系，浅色下白色系，
    切主题即换肤，不用重建卡片。
    """
    from qfluentwidgets import CardWidget

    class UICard(CardWidget):
        """统一卡片皮肤（所有页面的 card() 与视频库缩略图卡共用）。"""

        def __init__(self, parent=None):
            super().__init__(parent)
            self.setBorderRadius(10)

        def _normalBackgroundColor(self):
            return QColor(tokens()["card"])

        def _hoverBackgroundColor(self):
            return QColor(tokens()["card_hover"])

        def _pressedBackgroundColor(self):
            return QColor(tokens()["card_pressed"])

        def _fill_color(self):
            """三态底色：与原生卡片共用 section_dim_card_fill（同源统一）。"""
            state = ("card_pressed" if self.isPressed else
                     "card_hover" if self.isHover else "card")
            return section_dim_card_fill(state)

        def paintEvent(self, e):
            # ⚠️ 不用父类缓存的 self.backgroundColor：CardWidget 只在鼠标
            # enter/leave/press/release 时重算它，切主题后 update() 重绘
            # 拿到的还是旧主题的缓存色（实测切深色后卡片停在白色）。
            # 三态色在这里按当前主题现取，重绘即换肤。
            t = tokens()
            fill = self._fill_color()
            painter = QPainter(self)
            painter.setRenderHints(QPainter.Antialiasing)
            painter.setBrush(fill)
            painter.setPen(QColor(t["card_border_hover"]) if self.isHover
                           else QColor(t["card_border"]))
            painter.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1),
                                    self.borderRadius, self.borderRadius)

    return UICard


UICard = _make_uiclass()


# ---------------------------------------------------------------------- #
# 绘制
# ---------------------------------------------------------------------- #
def _pixmap_for(path):
    """按路径取 QPixmap（带 mtime 缓存）；文件失效返回 None。"""
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        _PIX_CACHE.pop(path, None)
        return None
    hit = _PIX_CACHE.get(path)
    if hit is not None and hit[0] == mtime:
        return hit[1]
    pm = QPixmap(path)
    if pm.isNull():
        _PIX_CACHE.pop(path, None)
        return None
    _PIX_CACHE[path] = (mtime, pm)
    return pm


def _blurred_pixmap(path, pm):
    """预模糊（QGraphicsBlurEffect 渲染一次、按 (路径, mtime) 缓存）。"""
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return pm
    hit = _BLUR_CACHE.get((path, mtime))
    if hit is not None:
        return hit
    try:
        out = QPixmap(pm.size())
        out.fill(Qt.transparent)
        scene = QGraphicsScene()
        item = scene.addPixmap(pm)
        eff = QGraphicsBlurEffect()
        eff.setBlurRadius(BLUR_RADIUS)
        eff.setBlurHints(QGraphicsBlurEffect.QualityHint)
        item.setGraphicsEffect(eff)
        p = QPainter(out)
        scene.render(p)
        p.end()
    except Exception:
        return pm
    _BLUR_CACHE[(path, mtime)] = out
    return out


def _draw_cover(painter, w, h, pm):
    """cover 模式铺图：等比放大到完全盖住区域，居中裁边。"""
    iw, ih = pm.width(), pm.height()
    if iw <= 0 or ih <= 0:
        return
    scale = max(w / float(iw), h / float(ih))
    dw, dh = iw * scale, ih * scale
    painter.drawPixmap(QRectF((w - dw) / 2.0, (h - dh) / 2.0, dw, dh),
                       pm, QRectF(0, 0, iw, ih))


def _paint_background(page, key):
    """在页面自身上画背景实底 + 背景图。

    · **板块遮罩**（v1.14.x）：画在**每个卡片（UICard）自身的底色 alpha**
      上（见 UICard.paintEvent），不在页面这一层画——页面层只负责在有
      背景图或开了板块遮罩时铺一层 page_base 实底，保证半透明卡片透出
      的是统一底色而不是 Mica/桌面。sdim=0 且无背景图时逐像素保持现状
      （不改变自检基线）。
    · **背景图**：仅当该板块（或全局）设置了生效背景图时铺图；背景遮罩是
      主题感知的竖向渐变：深色主题用黑色压暗（顶部最重，保标题），浅色主题
      用白色雾化提亮——同一张背景图在两档主题下都能衬住前景文字。
    """
    path = get_effective_bg(key)
    pm = _pixmap_for(path) if path else None
    sdim = get_section_dim()
    # 无背景图且未开板块遮罩：什么都不画，逐像素保持现状（不影响自检基线）
    if pm is None and sdim <= 0:
        return
    w, h = page.width(), page.height()
    if w <= 0 or h <= 0:
        return
    t = tokens()
    p = QPainter(page)
    try:
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        # 统一实底：背景图若是带透明的 PNG、或开了板块遮罩（半透明卡片
        # 透出的底色要统一），先铺一层 page_base，避免透出 Mica/桌面
        p.fillRect(0, 0, w, h, QColor(*t["page_base"]))
        if pm is not None:
            if get_blur():
                pm = _blurred_pixmap(path, pm)
            _draw_cover(p, w, h, pm)
            alpha = int(round(get_dim() / 100.0 * 255))
            if alpha > 0:
                # 竖向渐变遮罩：顶部最重（标题区文字可读性）、中段收敛、
                # 底部略回收一点让画面主体露出来
                sr, sg, sb = t["shade"]
                grad = QLinearGradient(0, 0, 0, h)
                grad.setColorAt(0.0, QColor(sr, sg, sb, min(255, alpha + 50)))
                grad.setColorAt(0.35, QColor(sr, sg, sb, alpha))
                grad.setColorAt(1.0, QColor(sr, sg, sb, max(0, alpha - 15)))
                p.fillRect(0, 0, w, h, grad)
    finally:
        p.end()


def install_page_background(page, key):
    """给页面挂背景绘制能力（实例级 paintEvent 覆盖，可重复调用）。

    原理：PyQt5 的虚方法派发会先查实例字典，`page.paintEvent = fn` 即可
    覆盖而不必派生子类——对已构造完成的页面零侵入。原 QWidget.paintEvent
    仍会先执行，保留既有底色行为。
    """
    if page is None or key not in _ALL_KEYS:
        return
    _REG[key] = page

    def _paint_event(ev, _page=page, _key=key):
        try:
            QWidget.paintEvent(_page, ev)
        except Exception:
            pass
        try:
            _paint_background(_page, _key)
        except Exception:
            pass

    page.paintEvent = _paint_event


def install_for_window(window):
    """一次性给六个导航页挂上背景能力（MainWindow 构造尾部调用一次）。"""
    pairs = [
        ("download", getattr(window, "download_page", None)),
        ("library", getattr(window, "library_page", None)),
        ("subtitle", getattr(window, "subtitle_page", None)),
        ("edit", getattr(window, "subtitle_edit_page", None)),
        ("pipeline", getattr(window, "pipeline_page", None)),
        ("settings", getattr(window, "settings_page", None)),
    ]
    for key, page in pairs:
        install_page_background(page, key)
    refresh()


def refresh(deep=False):
    """配置变化后重绘全部已注册页面（主线程调用）。

    deep=True（主题切换时）：连子控件一起 update——父控件 update() 只重绘
    自身，UICard 的三态色又是绘制时按 token 现取的，不深度刷的话切主题后
    卡片要等 hover 才换色。背景/遮罩类变化只动页面自身，浅刷就够。
    """
    for page in list(_REG.values()):
        try:
            page.update()
        except Exception:
            pass
        if deep:
            for child in page.findChildren(QWidget):
                try:
                    child.update()
                except Exception:
                    pass


# ---------------------------------------------------------------------- #
# qfluentwidgets 原生卡片跟随板块遮罩（引擎面板 SettingCard 系等）
# ---------------------------------------------------------------------- #
def install_card_alpha_patch():
    """让 qfluentwidgets 原生卡片也跟随板块遮罩（模块导入时执行一次）。

    引擎面板（字幕翻译/字幕合成等 tab）的行卡用的是 qfluentwidgets 1.x
    原生组件，不走 UICard，板块遮罩对它们原本无效（用户实测反馈"调整
    没有生效"）。两类绘制路径分别处理：

    · SettingCard(QFrame) 及全部子卡（SwitchSettingCard/RangeSettingCard…）：
      paintEvent 里**硬编码** QColor(255,255,255,170/13)——类级替换
      paintEvent，底色改走 section_dim_card_fill()（同源统一）；
    · CardWidget 系（SimpleCardWidget 及 videocaptioner SimpleSettingCard）：
      底色经 BackgroundAnimationWidget 动画取 _normalBackgroundColor()/
      _hoverBackgroundColor()/_pressedBackgroundColor()——在**定义处**
      类级 wrap，动画目标色 alpha 缩放（子类未覆写 normal 的自动继承）。

    ⚠️ 基线对齐（用户二轮反馈"样式还是不统一"）：原生卡片材质基线
    （浅色白 170）与 UICard（纯白 token）起点不同，即便同比例缩放，
    遮罩开启后透明度也对不上（sdim=30 时 UICard α=179 vs 原生 α=119）。
    所以遮罩开启时**直接同源取色**——section_dim_card_fill() 给出与
    UICard 完全一致的 token 底色 + 统一 alpha + token 描边；遮罩为 0
    时仍走原材质（自检基线不变）。

    ⚠️ 只 patch qfluentwidgets 定义处类，不 import videocaptioner（其导入
    有副作用，须走 vc_lazy_cache_patch 的时序约束）。
    """
    # 1) SettingCard（qfluentwidgets 1.x：QFrame + 硬编码底色）
    try:
        from qfluentwidgets.components.settings.setting_card import (
            SettingCard as _QFWSettingCard)
        from qfluentwidgets.common.style_sheet import isDarkTheme as _is_dark

        if not getattr(_QFWSettingCard.paintEvent, "_vt_alpha_patched", False):
            def _setting_card_paint(self, e, _dark=_is_dark):
                # ⚠️ 不再保留"原材质"分支（用户三轮实测：归零时原生卡白170
                # 与 UICard 纯白也不一样）——任何遮罩值都与 UICard 同源：
                # token 底色 + 统一 alpha + token 描边
                painter = QPainter(self)
                painter.setRenderHints(QPainter.Antialiasing)
                painter.setBrush(section_dim_card_fill("card"))
                painter.setPen(QColor(tokens()["card_border"]))
                painter.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1),
                                        6, 6)
            _setting_card_paint._vt_alpha_patched = True
            _QFWSettingCard.paintEvent = _setting_card_paint
    except Exception:
        pass

    # 2) CardWidget 系（动画取色）：沿**每个覆写处** wrap——SimpleCardWidget
    #    覆写了三态取色（MRO 不再经过 CardWidget 的版本），漏掉就无效。
    #    三态分别对齐 UICard 对应 token（card / card_hover / card_pressed）。
    try:
        from qfluentwidgets.components.widgets.card_widget import (
            CardWidget as _QFWCardWidget, SimpleCardWidget as _QFWSimpleCard,
            ElevatedCardWidget as _QFWElevatedCard)
        for _cls in (_QFWCardWidget, _QFWSimpleCard, _QFWElevatedCard):
            for _name, _state in (
                    ("_normalBackgroundColor", "card"),
                    ("_hoverBackgroundColor", "card_hover"),
                    ("_pressedBackgroundColor", "card_pressed")):
                _orig = _cls.__dict__.get(_name)
                if _orig is None or getattr(_orig, "_vt_alpha_patched", False):
                    continue

                def _make_nbc(_orig, _state):
                    def _nbc(self, _state=_state):
                        return section_dim_card_fill(_state)
                    _nbc._vt_alpha_patched = True
                    return _nbc

                setattr(_cls, _name, _make_nbc(_orig, _state))
    except Exception:
        pass


install_card_alpha_patch()
