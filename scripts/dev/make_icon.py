# -*- coding: utf-8 -*-
# @version 2.5.3
"""把源 PNG 图标转成多尺寸 ``.ico``（含 256px PNG 压缩帧）。

为什么需要脚本而不是手工转一次：图标是要**长期维护**的资产，每次改图都得
重新生成 7 档尺寸；手工做的代价是"改忘了某一档"，而 Windows 会按不同场合
挑不同尺寸（任务栏 16/24、Alt-Tab 32、资源管理器列表 48、桌面 64/128、
资源管理器大图标 256）——缺哪档就在哪档糊。

多尺寸 vs 单尺寸的实测差别：单尺寸 256 的 ico 在任务栏会被 Windows 缩到
16px，边缘的像素画细节（这里那圈硬描边）直接糊成锯齿；每档都按**最近邻**
从 1024 源缩放，描边保持锐利。

用法：
    python scripts/dev/make_icon.py                       # 用默认源/输出
    python scripts/dev/make_icon.py 源.png 输出.ico
"""
import os
import sys

#: 目标尺寸。256 单独处理（PNG 压缩帧，见下）。
SIZES = [16, 24, 32, 48, 64, 128, 256]
#: 256 用 PNG 压缩帧：BMP 帧未压缩时要 256×256×4 = 256KB，
#: 而 PNG 只要几 KB；Vista 以后的资源管理器都支持这种帧。
PNG_FRAME_SIZES = {256}

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
DEFAULT_SRC = os.path.join(ROOT, "assets", "app_icon.png")
DEFAULT_OUT = os.path.join(ROOT, "assets", "app_icon.ico")


def build_ico(src, out, sizes=None):
    """生成 ``out``（多尺寸 ico）；返回写入的尺寸列表。

    **自己拼 ICO 容器**，不用 Pillow 的 ``save(format="ICO")``——后者有个
    静默失效：``PIL.IcoImagePlugin._save`` 里有
    ``if size[0] > width or size[1] > height: continue``，而 width/height
    取的是**传入的第一张图**的尺寸。你若把缩好的 16px 当首图传进去，所有
    >16 的档会被这一行悄悄跳过，**不报任何错**，产出一个只有一帧的 ico
    （Pillow 12.3.0 实测：save(sizes=[7 档]) 实得 1 档）。它对"未提供的档"
    还会 fallback 用 LANCZOS 缩放，对像素画是灾难（硬描边糊成渐变）。

    ICO 容器本身就 40 行：6 字节头 + 每帧 16 字节目录项 + 帧数据。
    帧数据直接放 PNG（Vista+ 支持；本项目目标平台 Win10+ 无兼容问题，
    256px 用 BMP 帧要 256KB，PNG 只要几 KB）。
    """
    import struct
    from io import BytesIO

    from PIL import Image

    sizes = list(sizes or SIZES)
    im = Image.open(src)
    # 源图可能是 RGB（无 alpha），转成 RGBA 才能保留圆角外的透明区
    if im.mode != "RGBA":
        im = im.convert("RGBA")

    frames = []
    for s in sizes:
        # ⚠ 必须 **NEAREST**（最近邻）：本图标是像素画（pixel art），双线性/
        #   Lanczos 会把硬描边糊成渐变，看着"脏"。
        buf = BytesIO()
        im.resize((s, s), Image.NEAREST).save(buf, format="PNG", optimize=True)
        frames.append((s, buf.getvalue()))

    n = len(frames)
    header = struct.pack("<HHH", 0, 1, n)          # 0=icon, 1=多图, n=帧数
    # 目录项：宽/高为 256 时该字节写 0（ICO 规范的特例，不是写 256）
    entries = b""
    offset = 6 + 16 * n
    for s, data in frames:
        dim = 0 if s >= 256 else s
        entries += struct.pack(
            "<BBBBHHII", dim, dim, 0, 0, 1, 32, len(data), offset)
        offset += len(data)

    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "wb") as f:
        f.write(header + entries + b"".join(d for _, d in frames))
    return sizes


def verify_ico(path, expect=None):
    """回读校验：确认每个尺寸**真的**写进去了。

    为什么要回读——``save(..., sizes=...)`` 在某些 Pillow 版本上会静默只写
    第一档（尤其当传入的 sizes 与图片自身尺寸不一致时）。肉眼打不开 ico 看
    帧数，只能靠回读。"""
    from PIL import Image

    expect = list(expect or SIZES)
    with Image.open(path) as im:
        got = sorted(im.info.get("sizes", []))
        # im.size 是"最大帧"的尺寸
        ok = got == sorted((s, s) for s in expect)
        return ok, got, im.size


def verify_ico_qt(path, expect=None):
    """用 **Qt** 独立校验 ico（Windows 上 QImageReader 走原生 ICO 解析）。

    为什么不能只用 Pillow 自证：自己写的容器，让自己读回来，逻辑错误会
    一致地错两遍——"看起来对"但 Windows 未必认。Qt 是第三方实现，且在
    Windows 上底层就是 GDI 的 ``LoadImage``/ICO 解析，与资源管理器同一套。
    返回 ``(ok, frames, note)``；Qt 不可用时 note 说明已跳过。
    """
    expect = sorted((s, s) for s in (expect or SIZES))
    try:
        from PySide6.QtGui import QImageReader
    except Exception as e:  # noqa: BLE001
        return None, [], "Qt 不可用，跳过独立校验：%s" % e
    try:
        rd = QImageReader(path)
        if bytes(rd.format() or b"").lower() != b"ico":
            return False, [], "Qt 认不出这是 ico（format=%r）" % rd.format()
        frames = []
        for i in range(rd.imageCount()):
            if not rd.jumpToImage(i):
                return False, frames, "第 %d 帧跳不过去" % i
            im = rd.read()
            if im.isNull():
                return False, frames, "第 %d 帧解不出图像" % i
            frames.append((im.width(), im.height()))
        if sorted(frames) != expect:
            return False, frames, "期望 %s，实得 %s" % (expect, sorted(frames))
        return True, frames, "Qt 校验通过（%d 帧，与原生 ICO 解析一致）" % len(frames)
    except Exception as e:  # noqa: BLE001
        return False, [], "Qt 校验异常：%s" % e


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SRC
    out = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_OUT
    if not os.path.isfile(src):
        print("源图不存在：%s" % src)
        return 1
    sizes = build_ico(src, out)
    ok, got, biggest = verify_ico(out, sizes)
    print("生成 %s" % out)
    print("  Pillow 读回：%s" % ", ".join("%dx%d" % g for g in got))
    print("  最大帧：%dx%d   体积：%.1f KB"
          % (biggest[0], biggest[1], os.path.getsize(out) / 1024.0))
    if not ok:
        print("  ✗ Pillow 回读不通过：期望 %s，实得 %s"
              % (sorted((s, s) for s in sizes), got))
        return 1
    print("  ✓ Pillow 回读通过（%d 档）" % len(got))

    qok, _qframes, note = verify_ico_qt(out, sizes)
    print("  %s" % note)
    if qok is False:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())