# -*- coding: utf-8 -*-
# @version 2.5.2
"""vt_fluent 图标数据再生成工具（dev 期，不进随包）。

两件事：
  1. 从**已安装**的 qfluentwidgets Qt 资源提取：使用面 59 个图标的 SVG +
     FluentStyleSheet 全枚举的 light/dark QSS（后者落 data/tmp/qss_ref/，
     仅作 B1/B2/B3 施工的逐值对照基准，gitignore 不随包）；
  2. 生成 src/vt_fluent/_icons_data.py（ART + MEMBERS，内嵌进包）。

何时跑：src/ 新增了 FluentIcon 使用面外的成员（渲染报「无内嵌艺术字」错），
或需要刷新参考 QSS 基准时。前置：tools/python 里装着 qfluentwidgets。

用法（程序根为 cwd）：
    tools\\python\\python.exe scripts\\dev\\_gen_vt_fluent_icons.py
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "tools", "python", "Lib", "site-packages"))


def _current_version():
    """从主界面源码读当前 VERSION，作为生成文件里的 @version 标记。

    ⚠ 旧实现把这行写死成 "2.3.1"：每次发布改号后若重跑本脚本，生成的
    `_icons_data.py` 会被写回旧版本号，`stamp_versions.py` 再跑一遍才补回来，
    中间窗口期里清单与实际不一致（2026-10-19 发布 v2.4.0 时发现）。
    """
    p = os.path.join(ROOT, "src", "video_toolbox_qt.py")
    try:
        with open(p, encoding="utf-8") as f:
            m = re.search(r'VERSION\s*=\s*"([\d.]+)"', f.read())
        if m:
            return m.group(1)
    except OSError:
        pass
    return "0.0.0"

from PySide6.QtCore import QFile

REF_DIR = os.path.join(ROOT, "data", "tmp", "qss_ref")
OUT = os.path.join(ROOT, "src", "vt_fluent", "_icons_data.py")

#: 使用面涉及的 FluentIcon（src/ 实际用到的 FIF.* 与 FluentIcon.* 并集）
USED = sorted({
    "SYNC", "FOLDER", "SAVE", "ROBOT", "DOCUMENT", "LINK", "LANGUAGE", "FONT",
    "DELETE", "UPDATE", "SEARCH", "DOWNLOAD", "CANCEL", "VIDEO", "SETTING",
    "PLAY", "EDIT", "TILES", "SPEED_HIGH", "SEND", "PLAY_SOLID", "MEDIA",
    "HISTORY", "FOLDER_ADD", "FINGERPRINT", "CUT", "CONNECT", "CLOSE",
    "CERTIFICATE", "ALIGNMENT", "HOME", "ZOOM", "SAVE_AS", "RIGHT_ARROW",
    "PAUSE_BOLD", "PASTE", "PALETTE", "PAGE_RIGHT", "PAGE_LEFT", "MOVIE",
    "MENU", "LEFT_ARROW", "LAYOUT", "IOT", "INFO", "HELP", "GLOBE",
    "FEEDBACK", "DEVELOPER_TOOLS", "CONSTRACT", "CODE", "CARE_RIGHT_SOLID",
    "CARE_LEFT_SOLID", "CAMERA", "BRUSH", "BROOM", "ADD", "ACCEPT",
    "MICROPHONE", "ARROW_DOWN",
    # B2/B3 控件族自绘引用（自查补：缺一个就画空白）
    "CHEVRON_RIGHT", "FULL_SCREEN", "MINIMIZE", "MORE", "RETURN", "VIEW",
    # v2.4.1「AI 托管」页部署引导卡的「复制命令」按钮（harness_page.py）。
    # ⚠ 漏登记的症状：按钮 paintEvent 每次重绘抛 RuntimeError，错误气泡刷屏。
    "COPY",
})

#: FluentIcon 使用面之外的、控件族自绘需要的图标。
#: (资源路径前缀, [(成员名, 颜色后缀)])——suffix 为 black/light/dark；
#: info_bar 是**语义彩色双变体**（light/dark 各一套，不做 fill 替换）。
EXTRA_ICON_SRCS = [
    ("images/check_box/", [("Accept", "black"), ("PartialAccept", "black")]),
    ("images/spin_box/", [("Up", "black"), ("Down", "black")]),
    ("images/info_bar/", [("Info", "light"), ("Info", "dark"),
                          ("Success", "light"), ("Success", "dark"),
                          ("Warning", "light"), ("Warning", "dark"),
                          ("Error", "light"), ("Error", "dark")]),
]


def read_qrc(path):
    f = QFile(path)
    if not f.open(QFile.ReadOnly):
        return None
    data = bytes(f.readAll())
    f.close()
    return data


def normalize_svg(text):
    """SVG 压成单行（属性间空白塌缩；59 图均单 path 单 fill，安全）。"""
    text = re.sub(r">\s+<", "><", text)
    return re.sub(r"\s+", " ", text).strip()


def main():
    import qfluentwidgets._rc  # noqa: F401  注册 Qt 资源
    from qfluentwidgets.common.icon import FluentIcon
    from qfluentwidgets.common.style_sheet import FluentStyleSheet
    from qfluentwidgets.common.config import Theme

    # ---- 1. 提取参考资产 ------------------------------------------------ #
    os.makedirs(os.path.join(REF_DIR, "icons"), exist_ok=True)
    for name in USED:
        data = read_qrc(FluentIcon[name].path(Theme.LIGHT))  # LIGHT=黑变体
        if data is None:
            print("[MISS icon]", name)
            continue
        with open(os.path.join(REF_DIR, "icons", name + ".svg"), "wb") as f:
            f.write(data)
    # 额外图标（B1 控件族自绘用）：check_box / spin_box
    extra = {}
    for prefix, names in EXTRA_ICON_SRCS:
        for name, suffix in names:
            src = ":/qfluentwidgets/%s%s_%s.svg" % (prefix, name, suffix)
            data = read_qrc(src)
            if data is None:
                print("[MISS extra icon]", prefix, name, suffix)
                continue
            key = (prefix.strip("/").replace("/", "_") + "_" + name
                   + ("" if suffix == "black" else "_" + suffix))
            extra[key] = normalize_svg(data.decode("utf-8"))
            with open(os.path.join(REF_DIR, "icons", key + ".svg"), "wb") as f:
                f.write(data)
    nq = 0
    for theme_dir, theme in (("dark", Theme.DARK), ("light", Theme.LIGHT)):
        d = os.path.join(REF_DIR, "qss", theme_dir)
        os.makedirs(d, exist_ok=True)
        for member in FluentStyleSheet:
            data = read_qrc(member.path(theme))
            if data is None:
                print("[MISS qss]", theme_dir, member.name)
                continue
            with open(os.path.join(d, member.value + ".qss"), "wb") as f:
                f.write(data)
            nq += 1
    print(f"ref: {len(USED)} icons + {nq} qss → data/tmp/qss_ref/（gitignore）")

    # ---- 2. 生成 _icons_data.py ----------------------------------------- #
    art = {}
    for name in USED:
        p = os.path.join(REF_DIR, "icons", name + ".svg")
        if not os.path.exists(p):
            continue
        with open(p, encoding="utf-8") as f:
            art[name] = normalize_svg(f.read())
    members = [(n, m.value) for n, m in FluentIcon.__members__.items()]

    lines = [
        "# -*- coding: utf-8 -*-",
        "# @version " + _current_version(),
        '"""vt_fluent 图标数据（自动生成区，勿手改）。',
        "",
        "· ART：使用面涉及的 FluentIcon SVG（黑变体单份，fill 运行期按主题替换）。",
        "  再生成：tools/python/python.exe scripts/dev/_gen_vt_fluent_icons.py",
        "  （前置：tools/python 装着 qfluentwidgets；参考资产落 data/tmp/qss_ref/）。",
        "· MEMBERS：FluentIcon 枚举全成员 (名, 值)——API 兼容面，含别名对",
        '  （LIBRARY 与 BOOK_SHELF 同为 "BookShelf"，枚举按定义序自动成别名）。',
        "  未在 ART 中的成员可导入但渲染时报缺失错（指引跑再生成脚本）。",
        "· EXTRA_ART：非 FluentIcon 的自绘图标（check_box/spin_box，B1 控件族用）。",
        '"""',
        "",
        "#: {成员名: 单行 SVG}。viewBox 16x16，单 path，fill=#000000/#000。",
        "ART = {",
    ]
    for name in sorted(art):
        lines.append("    %r: %r," % (name, art[name]))
    lines += ["}", "", "#: FluentIcon 枚举成员表（与 qfluentwidgets 1.11.3 逐名同值）。",
              "MEMBERS = ["]
    for name, value in members:
        lines.append("    (%r, %r)," % (name, value))
    lines += ["]", "", "#: 非 FluentIcon 自绘图标（键 = 资源路径扁平化）。",
              "EXTRA_ART = {"]
    for key in sorted(extra):
        lines.append("    %r: %r," % (key, extra[key]))
    lines += ["}", ""]

    with open(OUT, "w", encoding="utf-8", newline="\r\n") as f:
        f.write("\n".join(lines))
    print(f"written: {OUT}（art {len(art)} / members {len(members)}）")
    bad = [n for n, s in art.items() if any(ord(c) > 127 for c in s)]
    if bad:
        print("WARN non-ascii icons:", bad)


if __name__ == "__main__":
    main()
