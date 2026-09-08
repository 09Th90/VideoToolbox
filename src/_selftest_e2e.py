#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""端到端自检：模拟一次完整下载，验证任务文件夹的最终产出结构。

直接调用 GUI 的 DownloadTab._pack_task（负责信息导出 + 封面转换的串联逻辑），
输入用本地 ffmpeg 生成的素材替代真实下载结果，因此不联网、不下载视频。

运行：python _selftest_e2e.py
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
MSGS = []


def check(name, cond, extra=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}{(' -> ' + extra) if extra else ''}")
    if not cond:
        FAILS.append(name)


def main():
    print("=" * 62)
    print("  端到端自检：模拟完整下载后的文件夹产出结构")
    print("=" * 62)

    ffmpeg, ffprobe = engine.ensure_ffmpeg()
    engine.FFPROBE_PATH = ffprobe

    base = tempfile.mkdtemp(prefix="vt_e2e_")
    backup = None
    if os.path.isfile(engine.CONFIG_PATH):
        backup = engine.CONFIG_PATH + ".e2e_bak"
        shutil.copy2(engine.CONFIG_PATH, backup)

    try:
        # ---- 1. 模拟用户选定的保存位置，并记住 ----
        dest = os.path.join(base, "我的视频下载")
        os.makedirs(dest, exist_ok=True)
        engine.set_saved_download_dir(dest)

        # ---- 2. 模拟「检测画质」拿到的视频元数据 ----
        meta = {
            "id": "BV1test",
            "title": "【教程】如何把封面转成 1280x720 % 特殊字符测试",
            "description": "本期简介第一行。\n第二行内容。\n#标签1 #标签2",
            "webpage_url": "https://www.bilibili.com/video/BV1test",
            "uploader": "测试博主",
            "channel": "测试频道",
            "uploader_id": "9876543",
        }

        # ---- 3. 用标题生成独立文件夹（走真实净化 + 去重逻辑）----
        folder = engine.unique_folder(dest, engine.sanitize_folder_name(meta["title"], "video"))
        os.makedirs(folder, exist_ok=True)
        print(f"\n[模拟] 保存位置: {dest}")
        print(f"[模拟] 独立文件夹: {os.path.basename(folder)}")
        check("独立文件夹建在保存位置下", os.path.dirname(folder) == dest)
        check("文件夹名已去除非法字符",
              not any(c in os.path.basename(folder) for c in '\\/:*?"<>|%'))

        # ---- 4. 模拟 yt-dlp 的下载产物：视频 + 原始封面 ----
        video = os.path.join(folder, os.path.basename(folder) + ".mp4")
        subprocess.run([ffmpeg, "-y", "-f", "lavfi", "-i", "color=c=teal:s=1280x720:d=2",
                        "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
                        "-shortest", "-c:v", "libx264", "-preset", "ultrafast",
                        "-c:a", "aac", video], capture_output=True, check=True)
        # 竖版原始封面（模拟站点给的 9:16 图）
        raw_thumb = os.path.join(folder, "【教程】如何把封面转成 1280x720.webp")
        subprocess.run([ffmpeg, "-y", "-f", "lavfi", "-i", "color=c=orange:s=720x1280",
                        "-frames:v", "1", raw_thumb], capture_output=True, check=True)
        # 字幕（模拟勾选了下载字幕）
        with open(os.path.join(folder, os.path.basename(folder) + ".srt"),
                  "w", encoding="utf-8") as f:
            f.write("1\n00:00:00,000 --> 00:00:02,000\n测试字幕\n")

        # ---- 5. 调用 GUI 真实使用的打包方法 ----
        import video_toolbox_gui as gui

        class FakeQueue:
            def put(self, msg):
                MSGS.append(msg)

        class FakeApp:
            q = FakeQueue()

        tab = gui.DownloadTab.__new__(gui.DownloadTab)   # 不构建界面，只取方法
        tab.app = FakeApp()
        tab._pack_task("T1", ffmpeg, folder, meta, "1080p")

        # ---- 6. 验证最终产出结构 ----
        print("\n[产出] 文件夹内容：")
        names = sorted(os.listdir(folder))
        for n in names:
            p = os.path.join(folder, n)
            print(f"    {n}  ({engine.format_size(os.path.getsize(p))})")

        print("\n[验证] 四项需求")
        check("① 视频本体存在", os.path.isfile(video))
        check("① 字幕随视频同文件夹",
              any(n.lower().endswith(".srt") for n in names))

        cover = os.path.join(folder, "封面.jpg")
        check("② 封面.jpg 已生成", os.path.isfile(cover))
        if os.path.isfile(cover):
            r = subprocess.run([ffprobe, "-v", "error", "-select_streams", "v:0",
                                "-show_entries", "stream=width,height", "-of", "json", cover],
                               capture_output=True, text=True)
            s = json.loads(r.stdout)["streams"][0]
            check("② 封面尺寸恰为 1280x720",
                  (s["width"], s["height"]) == (1280, 720),
                  f"{s['width']}x{s['height']}")
        check("② 竖版原始封面已被清理（只留 封面.jpg）",
              not os.path.isfile(raw_thumb),
              str([n for n in names if n.lower().endswith((".webp", ".png"))]))

        info = os.path.join(folder, "视频信息.txt")
        check("③ 视频信息.txt 已生成", os.path.isfile(info))
        if os.path.isfile(info):
            raw = open(info, "rb").read()
            check("③ 记事本可直接读（utf-8-sig）", raw.startswith(b"\xef\xbb\xbf"))
            text = raw.decode("utf-8-sig")
            check("③ 含标题", "如何把封面转成 1280x720" in text)
            check("③ 含简介", "本期简介第一行" in text and "#标签1" in text)
            check("③ 含视频链接", "bilibili.com/video/BV1test" in text)
            check("③ 含博主名", "测试博主" in text)
            check("③ 含博主主页链接", "space.bilibili.com/9876543" in text)
            check("③ 含画质与下载时间", "1080p" in text and "下载时间" in text)

        check("④ 所有内容都在同一个独立文件夹内",
              os.path.isfile(video) and os.path.isfile(cover) and os.path.isfile(info))

        # ---- 7. 打包日志应从队列透出（GUI 日志区依赖它）----
        logs = [m[2] for m in MSGS if m[0] == "dl_log"]
        check("打包步骤有日志回传界面", any("封面.jpg" in x for x in logs)
              and any("视频信息.txt" in x for x in logs),
              f"{len(logs)} 条")

        # ---- 8. 重复下载同名视频：不应覆盖已有内容 ----
        folder2 = engine.unique_folder(dest, engine.sanitize_folder_name(meta["title"], "video"))
        check("同名视频二次下载自动改名，不覆盖",
              folder2 != folder and folder2.endswith("(2)"),
              os.path.basename(folder2))

        # ---- 9. 目录记忆持久化 ----
        check("⑤ 保存位置已写入配置（长期固定）",
              os.path.abspath(engine.get_saved_download_dir()) == os.path.abspath(dest))
    finally:
        shutil.rmtree(base, ignore_errors=True)
        if backup:
            shutil.move(backup, engine.CONFIG_PATH)
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
