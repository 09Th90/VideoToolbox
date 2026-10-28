# -*- coding: utf-8 -*-
# @version 2.8.0
"""vt_fluent 图标渲染 parity 探针（B0 门：图标与 qfluentwidgets 渲染对照）。

同一进程内对 59 个使用面图标 × 明暗两档 × 多尺寸，比对两侧渲染像素：
  1. 枚举成员面      —— FluentIcon 成员名/值逐一相同（含别名对）
  2. 渲染像素        —— QIcon.pixmap() → QImage 逐像素相等（同源 SVG，
                         上游走 Qt 内置引擎、vt_fluent 走 fill 替换 + QSvgRenderer）
  3. 主题跟随        —— 切主题后图标换色（浅色黑 / 深色白）

用法（程序根为 cwd）：
    VT_NO_SYNC=1 tools\\python\\python.exe scripts\\dev\\_selftest_vt_fluent_icon.py
退出码：0 = PASS；1 = FAIL。
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "data", "tmp"))

fails = []

#: 合成画布底色（中性灰，明暗笔画都能显出边缘差异）
_BG = (128, 128, 128, 255)


def _canvas(size):
    """造中性灰底画布（Format_ARGB32 直通 alpha）。"""
    from PySide6.QtGui import QColor, QImage
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(QColor(*_BG))
    return img


def _draw(canvas, pixmap):
    """把图标 pixmap 画到画布中心（QPainter 正确处理两种 alpha 编码）。"""
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QPainter
    p = QPainter(canvas)
    p.drawPixmap(QPoint(0, 0), pixmap)
    p.end()


def main():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])

    import qfluentwidgets as qfw
    import vt_fluent as vt
    from qfluentwidgets.common.icon import FluentIcon as QFluentIcon
    from vt_fluent._icon import FluentIcon as VFluentIcon

    # ---- 1. 枚举成员面 --------------------------------------------------- #
    q_members = [(n, m.value) for n, m in QFluentIcon.__members__.items()]
    v_members = [(n, m.value) for n, m in VFluentIcon.__members__.items()]
    if q_members != v_members:
        q_only = [n for n, _ in q_members if n not in dict(v_members)]
        v_only = [n for n, _ in v_members if n not in dict(q_members)]
        fails.append(f"成员面不一致: 上游独有={q_only} vt_fluent独有={v_only}")
    print(f"[MEMBERS] 上游 {len(q_members)} / vt_fluent {len(v_members)} 成员")

    # ---- 2/3. 渲染像素 --------------------------------------------------- #
    from qfluentwidgets.common.config import Theme as QTheme
    from qfluentwidgets import setTheme as q_setTheme
    from vt_fluent import setTheme as v_setTheme
    from vt_fluent._icons_data import ART

    sizes = (16, 20, 24, 32)
    total = matched = 0
    for theme_name, q_t, v_t in (("LIGHT", QTheme.LIGHT, vt.Theme.LIGHT),
                                 ("DARK", QTheme.DARK, vt.Theme.DARK)):
        q_setTheme(q_t)
        v_setTheme(v_t)
        for name in sorted(ART):
            q_icon = QFluentIcon[name].icon()
            v_icon = VFluentIcon[name].icon()
            for size in sizes:
                total += 1
                # ⚠ 判定基准是**合成后的视觉结果**：上游 pixmap 是
                # Format_ARGB32_Premultiplied、vt_fluent 是 Format_ARGB32
                # （与 qfluentwidgets 自绘 SvgIconEngine 一致）——白笔画边缘
                # 像素两种 alpha 编码的 RGB 表示不同，直接比 QImage 会假报
                # 差异。把两个图标分别画到同一底色的画布上再比像素 = 真值。
                qc = _canvas(size)
                vc = _canvas(size)
                _draw(qc, q_icon.pixmap(size, size))
                _draw(vc, v_icon.pixmap(size, size))
                diff = sum(1 for y in range(size) for x in range(size)
                           if qc.pixel(x, y) != vc.pixel(x, y))
                if diff == 0:
                    matched += 1
                else:
                    fails.append(
                        f"合成差异 {name}/{theme_name}/{size}px: {diff}/{size * size} 像素不同")
    print(f"[PIXELS] {matched}/{total} 合成渲染逐像素相等"
          f"（{len(ART)} 图标 × 明暗 × {sizes} 尺寸）")

    # 主题跟随：浅色下应有深色笔画，深色下应有白色笔画
    v_setTheme(vt.Theme.LIGHT)
    img = VFluentIcon["SYNC"].icon().pixmap(16, 16).toImage()
    dark_px = sum(1 for y in range(16) for x in range(16)
                  if img.pixel(x, y) and (img.pixel(x, y) & 0xFFFFFF) < 0x404040)
    v_setTheme(vt.Theme.DARK)
    img = VFluentIcon["SYNC"].icon().pixmap(16, 16).toImage()
    light_px = sum(1 for y in range(16) for x in range(16)
                   if img.pixel(x, y) and (img.pixel(x, y) & 0xFFFFFF) > 0xC0C0C0)
    if dark_px == 0 or light_px == 0:
        fails.append(f"主题跟随异常: 浅色深笔画 {dark_px} / 深色白笔画 {light_px}")
    else:
        print(f"[THEME] 主题跟随正常（浅色深笔画 {dark_px}px / 深色白笔画 {light_px}px）")

    print("=" * 56)
    if fails:
        print(f"VT-FLUENT-ICON PARITY RESULT: FAIL ({len(fails)} 项)")
        for x in fails[:20]:
            print("  -", x)
        return 1
    print("VT-FLUENT-ICON PARITY RESULT: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
