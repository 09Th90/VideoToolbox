#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""离线自检：验证「独立文件夹 + 封面1280x720 + 信息txt + 目录长期记忆」四项功能。

不联网、不下载视频，全部用本地生成的素材验证打包逻辑。
运行：python _selftest_pack.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import video_toolbox as engine

FAILS = []


def check(name, cond, extra=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}{(' -> ' + extra) if extra else ''}")
    if not cond:
        FAILS.append(name)


def test_sanitize_and_unique_folder(base):
    print("\n[1] 文件夹名净化与去重")
    cases = {
        '正常标题': ('普通视频标题', '普通视频标题'),
        '含非法字符 \\/:*?"<>|': ('a/b\\c:d*e?f"g<h>i|j', 'a b c d e f g h i j'),
        '含百分号（会破坏 yt-dlp 模板）': ('100%好用的视频', '100 好用的视频'),
        'Windows 保留名 CON': ('CON', '_CON'),
        '空标题': ('', 'video'),
        '超长标题截断到80': ('长' * 200, '长' * 80),
    }
    for desc, (src, want) in cases.items():
        got = engine.sanitize_folder_name(src, "video")
        check(desc, got == want, f"{got!r}")

    # 去重：已存在且非空的文件夹应让位
    f1 = engine.unique_folder(base, "视频A")
    os.makedirs(f1, exist_ok=True)
    with open(os.path.join(f1, "占位.txt"), "w") as f:
        f.write("x")
    f2 = engine.unique_folder(base, "视频A")
    check("同名非空文件夹自动加序号", f2 != f1 and f2.endswith("(2)"), os.path.basename(f2))

    # 已存在的空文件夹可直接复用
    f3 = engine.unique_folder(base, "空目录测试")
    os.makedirs(f3, exist_ok=True)
    f4 = engine.unique_folder(base, "空目录测试")
    check("同名空文件夹直接复用", f3 == f4)


def test_write_info_txt(base):
    print("\n[2] 视频信息.txt（标题/简介/视频链接/博主链接）")
    data = {
        "title": "测试视频：封面与信息导出",
        "description": "这是简介第一行\n这是简介第二行",
        "webpage_url": "https://www.bilibili.com/video/BV1xx411c7XX",
        "uploader": "某博主",
        "channel": "某频道",
        "uploader_id": "12345678",
    }
    p = engine.write_info_txt(base, data, "1080p")
    check("文件已生成", os.path.isfile(p), os.path.basename(p))

    raw = open(p, "rb").read()
    check("使用 utf-8-sig（记事本不乱码）", raw.startswith(b"\xef\xbb\xbf"))
    text = raw.decode("utf-8-sig")

    check("包含标题", "测试视频：封面与信息导出" in text)
    check("包含简介", "这是简介第二行" in text)
    check("包含视频链接", "BV1xx411c7XX" in text)
    check("包含博主名", "某博主" in text)
    check("包含博主主页链接", "space.bilibili.com" in text, "B站无 uploader_url 时用 uploader_id 推导")
    check("包含画质", "1080p" in text)
    check("包含下载时间", "下载时间" in text)

    # 缺字段时不应崩溃，且要有占位
    p2 = engine.write_info_txt(base, {}, "")
    t2 = open(p2, encoding="utf-8-sig").read()
    check("空数据不崩溃且有占位", "（未知标题）" in t2 and "（无简介）" in t2)


def test_cover_1280x720(base, ffmpeg):
    print("\n[3] 封面.jpg 固定 1280x720")

    def make_img(name, w, h, color="red"):
        out = os.path.join(base, name)
        subprocess.run([ffmpeg, "-y", "-f", "lavfi", "-i",
                        f"color=c={color}:s={w}x{h}", "-frames:v", "1", out],
                       capture_output=True, check=True)
        return out

    def dims(path):
        r = subprocess.run([engine.FFPROBE_PATH, "-v", "error",
                            "-select_streams", "v:0",
                            "-show_entries", "stream=width,height",
                            "-of", "json", path], capture_output=True, text=True)
        s = json.loads(r.stdout)["streams"][0]
        return s["width"], s["height"]

    # 竖图（9:16）：等比缩放 + 黑边补齐，不能拉伸变形
    d = os.path.join(base, "cover_v")
    os.makedirs(d, exist_ok=True)
    make_img(os.path.join(d, "thumb.png"), 720, 1280)
    ok = engine.make_cover_1280x720(ffmpeg, d)
    out = os.path.join(d, "封面.jpg")
    check("竖图转换成功", ok and os.path.isfile(out))
    if os.path.isfile(out):
        check("竖图输出恰为 1280x720", dims(out) == (1280, 720), str(dims(out)))
    left = [n for n in os.listdir(d) if n.lower().endswith((".png", ".jpg", ".webp"))
            and n != "封面.jpg"]
    check("原始封面已清理", not left, str(left))

    # 横图（超宽）
    d2 = os.path.join(base, "cover_h")
    os.makedirs(d2, exist_ok=True)
    make_img(os.path.join(d2, "thumb.webp"), 1920, 480)
    ok2 = engine.make_cover_1280x720(ffmpeg, d2)
    o2 = os.path.join(d2, "封面.jpg")
    check("超宽图转换成功", ok2 and os.path.isfile(o2))
    if os.path.isfile(o2):
        check("超宽图输出恰为 1280x720", dims(o2) == (1280, 720), str(dims(o2)))

    # 多张候选图：应取最大的那张
    d3 = os.path.join(base, "cover_multi")
    os.makedirs(d3, exist_ok=True)
    make_img(os.path.join(d3, "small.jpg"), 160, 90, "blue")
    make_img(os.path.join(d3, "big.jpg"), 1280, 720, "green")
    ok3 = engine.make_cover_1280x720(ffmpeg, d3)
    check("多候选图取最大者并成功", ok3 and os.path.isfile(os.path.join(d3, "封面.jpg")))

    # 无封面：返回 False 且不抛异常
    d4 = os.path.join(base, "cover_none")
    os.makedirs(d4, exist_ok=True)
    check("无封面时安全跳过", engine.make_cover_1280x720(ffmpeg, d4) is False)


def test_config_persistence(base):
    print("\n[4] 保存位置长期固定")
    target = os.path.join(base, "我的下载目录")
    os.makedirs(target, exist_ok=True)

    engine.set_saved_download_dir(target)
    got = engine.get_saved_download_dir()
    check("写入后能读回同一路径", os.path.abspath(got) == os.path.abspath(target), got)

    # 模拟重启：清空可能的内存缓存后重新读配置文件
    cfg_files = [p for p in (engine.CONFIG_PATH, engine._fallback_config_path())
                 if os.path.isfile(p)]
    check("配置已落盘为真实文件", bool(cfg_files), str(cfg_files))

    # 目录当前不存在（如外接盘未插入）时，记忆不应被丢弃
    engine.set_saved_download_dir(os.path.join(base, "尚未创建的盘符目录"))
    got2 = engine.get_saved_download_dir()
    check("目录暂不存在时仍保留记忆", got2.endswith("尚未创建的盘符目录"), got2)

    # 带引号/空格的输入应被净化
    engine.set_saved_download_dir(f'  "{target}"  ')
    got3 = engine.get_saved_download_dir()
    check("自动去除首尾空格与引号", os.path.abspath(got3) == os.path.abspath(target), got3)


def test_output_template(base):
    print("\n[5] 输出模板百分号转义（防止下载到错误路径）")
    tpl = engine.output_template(base, "%(title)s.%(ext)s")
    check("模板占位符保持不变", tpl.endswith("%(title)s.%(ext)s"), tpl[-24:])

    tricky = os.path.join(base, "%(id)s素材")
    t2 = engine.output_template(tricky)
    # 注意：%%(id)s 字面上包含 %(id)s 子串，因此只断言出现了转义后的 %%(
    check("目录名中的 % 被转义为 %%", "%%(id)s素材" in t2, t2)

    plain = os.path.join(base, "普通目录")
    check("无百分号目录保持原样", engine.output_template(plain)
          == os.path.join(plain, "%(title)s.%(ext)s"))

    # 用 yt-dlp 真实解析模板，确认转义后目录名不会被当作变量替换。
    # 这里刻意用纯 ASCII 目录名：Windows 控制台会按本地代码页输出，
    # 中文会被写成乱码，导致断言比对失真（实际转换是正确的）。
    ytdlp = engine.ensure_ytdlp()
    info = os.path.join(base, "info.json")
    src = os.path.join(base, "src.mp4")
    with open(info, "w", encoding="utf-8") as f:
        json.dump({
            "id": "t1", "title": "myvideo", "ext": "mp4", "_type": "video",
            "extractor": "generic", "duration": 1,
            "webpage_url": "https://example.com/v",
            "formats": [
                {"format_id": "v1", "ext": "mp4", "vcodec": "avc1", "acodec": "none",
                 "height": 720, "width": 1280, "protocol": "file", "url": src},
                {"format_id": "a1", "ext": "m4a", "vcodec": "none", "acodec": "mp4a",
                 "protocol": "file", "url": src},
            ],
            "requested_formats": [],
        }, f)
    tricky_ascii = os.path.join(base, "%(id)s_clips")
    t3 = engine.output_template(tricky_ascii)
    r = subprocess.run([ytdlp, "--load-info-json", info, "--simulate",
                        "-o", t3, "--print", "filename"],
                       capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    got = (r.stdout or "").strip()
    dirname = os.path.basename(os.path.dirname(got)) if got else ""
    check("yt-dlp 解析后目录名保持字面量（未被替换成 t1_clips）",
          r.returncode == 0 and dirname == "%(id)s_clips",
          dirname or f"rc={r.returncode}")


def main():
    print("=" * 62)
    print("  视频工具箱 v1.3 打包功能离线自检")
    print("=" * 62)

    ffmpeg, ffprobe = engine.ensure_ffmpeg()
    engine.FFPROBE_PATH = ffprobe
    print(f"[工具] ffmpeg: {ffmpeg}")

    base = tempfile.mkdtemp(prefix="vt_selftest_")
    backup_cfg = None
    if os.path.isfile(engine.CONFIG_PATH):
        backup_cfg = engine.CONFIG_PATH + ".selftest_bak"
        shutil.copy2(engine.CONFIG_PATH, backup_cfg)

    try:
        test_sanitize_and_unique_folder(base)
        test_write_info_txt(base)
        test_cover_1280x720(base, ffmpeg)
        test_config_persistence(base)
        test_output_template(base)
    finally:
        shutil.rmtree(base, ignore_errors=True)
        if backup_cfg:
            shutil.move(backup_cfg, engine.CONFIG_PATH)
        elif os.path.isfile(engine.CONFIG_PATH):
            os.remove(engine.CONFIG_PATH)

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
