#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# @version 1.15.3
"""字幕引擎自检（v1.10.2）：验证内嵌字幕引擎可导入、界面可构建、品牌已中性化。

步骤：
  1. 环境检查：当前进程可导入 videocaptioner，Qt 依赖齐全；
  2. 品牌补丁：engine_ui_brand_patch() 生效（预览窗口标题中性化）；
  3. 真实构建：HomeInterface 可创建（即「字幕处理」页内嵌的工作台），
     品牌水印与捐助入口处于隐藏状态；
  4. 合规文件：GPL-3.0 许可全文与组件来源声明随包。

需要图形界面（本机运行）；不联网。运行：python _selftest_vc.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import video_toolbox as engine

os.environ.setdefault(
    "QT_QPA_PLATFORM_PLUGIN_PATH",
    os.path.join(engine.EMBEDDED_SITE_PACKAGES, "PyQt5", "Qt5", "plugins"))

FAILS = []


def check(name, cond, extra=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}{(' -> ' + extra) if extra else ''}")
    if not cond:
        FAILS.append(name)


def main():
    print("=" * 62)
    print("  字幕引擎自检：内嵌环境 / 品牌中性化 / 界面构建")
    print("=" * 62)

    # 与真实启动一致：在导入 videocaptioner 之前完成路径重定向/资源就位
    engine.prepare_runtime_env()

    check("字幕引擎可导入（内嵌可用）", engine.vc_importable())
    check("Qt 依赖齐全（PyQt5 / qfluentwidgets）",
          not engine.vc_missing_deps(), str(engine.vc_missing_deps()))
    ready, main_text, detail = engine.vc_state()
    check("引擎判定环境就绪", ready, main_text)
    if detail:
        print(f"        {detail}")

    check("品牌补丁生效（预览窗口标题中性化）",
          engine.engine_ui_brand_patch())

    check("GPL-3.0 许可全文随包", os.path.isfile(engine.VC_LICENSE_FILE),
          os.path.basename(engine.VC_LICENSE_FILE))
    check("组件来源声明随包", os.path.isfile(engine.VC_SOURCE_FILE),
          os.path.basename(engine.VC_SOURCE_FILE))

    if not ready:
        print("\n环境未就绪，跳过界面构建测试。")
        print("=" * 62)
        return 1

    # —— 资源自包含：纯代码 wheel 不带 resource，必须由我们随包补齐，
    #    否则界面空图、裸调 ffmpeg 找不到，字幕功能就是“空壳”。 ——
    import shutil
    from videocaptioner import config as C
    for asset in ("logo.png", "default_thumbnail.jpg", "audio-thumbnail.png",
                  "default_bg.png", "default_bg_landscape.png",
                  "default_bg_portrait.png", "en.mp3"):
        check("随包资源存在：assets/" + asset, (C.ASSETS_PATH / asset).is_file())
    n_fonts = len(list(C.FONTS_PATH.glob("*.ttf"))) if C.FONTS_PATH.is_dir() else 0
    check("烧录字体随包（≥1 个 ttf）", n_fonts >= 1, "%d 个" % n_fonts)
    n_styles = (len(list(C.SUBTITLE_STYLE_PATH.glob("*.json")))
                if C.SUBTITLE_STYLE_PATH.is_dir() else 0)
    check("默认字幕样式补齐（≥4 套）", n_styles >= 4, "%d 套" % n_styles)
    ff = shutil.which("ffmpeg")
    check("引擎裸调 ffmpeg 命中随包二进制",
          bool(ff) and os.path.dirname(ff).lower() == str(C.BIN_PATH).lower(),
          str(ff))
    check("引擎资源/数据路径不落在系统盘",
          os.path.splitdrive(str(C.RESOURCE_PATH))[0].lower() != "c:" and
          os.path.splitdrive(str(C.WORK_PATH))[0].lower() != "c:",
          str(C.RESOURCE_PATH))

    from PyQt5.QtWidgets import QApplication
    from PyQt5.QtCore import qInstallMessageHandler
    _qt_msgs = []
    qInstallMessageHandler(lambda mode, ctx, msg: _qt_msgs.append(msg))
    app = QApplication.instance() or QApplication(sys.argv)
    try:
        from videocaptioner.ui.view.home_interface import HomeInterface
        home = HomeInterface()
        check("引擎工作台可构建（内嵌界面）", home is not None)
        null_imgs = [m for m in _qt_msgs if "null pixmap" in m.lower()]
        check("内嵌工作台构建无空图片（资源已就位）", not null_imgs,
              "%d 处空图" % len(null_imgs))
        tc = getattr(home, "task_creation_interface", None)
        check("品牌水印控件存在（嵌入层负责隐藏）",
              tc is not None and getattr(tc, "info_label", None) is not None)
        check("捐助入口控件存在（嵌入层负责隐藏）",
              tc is not None and getattr(tc, "donate_button", None) is not None)
        home.deleteLater()
    except Exception as e:  # noqa: BLE001
        check("引擎工作台可构建（内嵌界面）", False, str(e))

    print("\n" + "=" * 62)
    if FAILS:
        print(f"  结果：{len(FAILS)} 项失败")
        for f in FAILS:
            print(f"    - {f}")
        print("=" * 62)
        return 1
    print("  结果：全部通过")
    print("=" * 62)
    return 0


if __name__ == "__main__":
    sys.exit(main())
