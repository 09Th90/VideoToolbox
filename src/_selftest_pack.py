#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# @version 1.17.0
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


def test_launcher_encoding():
    print("\n[0] 启动器 视频工具箱.bat 编码安全（cmd 按 OEM 代码页解析）")
    bat = os.path.join(engine.SRC_DIR, "视频工具箱.bat")
    check("启动器存在", os.path.isfile(bat), bat)
    if not os.path.isfile(bat):
        return
    raw = open(bat, "rb").read()
    # cmd 在 chcp 65001 生效前按 GBK 解析 .bat 字节；任何非 ASCII（如 UTF-8 中文
    # 注释）都可能错读后吞掉后续 set 行，导致选错解释器而无法启动。必须纯 ASCII。
    non_ascii = [i for i, b in enumerate(raw) if b > 127]
    check("启动器为纯 ASCII（无中文/UTF-8 字节）", not non_ascii,
          "非 ASCII 字节数=%d" % len(non_ascii))
    text = raw.decode("ascii", errors="replace")
    check("优先使用内嵌 tools\\python", "tools\\python\\python.exe" in text)
    code_lines = [ln.strip() for ln in text.splitlines()
                  if ln.strip() and not ln.strip().lower().startswith("rem")]
    check("拖入参数逐个安全加引号（命令行不裸用 %*）",
          any(':collect' in ln for ln in code_lines) and
          any('"%~1"' in ln for ln in code_lines) and
          not any("%*" in ln for ln in code_lines))


def test_codec_compat(base):
    print("\n[*] 文本编码兼容（UTF-8 / GBK / ASCII 同时支持）")
    d = engine.decode_bytes_any
    # ASCII 是 UTF-8 子集
    check("ASCII 正常解码", d(b"hello 123") == "hello 123")
    cn = "中文字幕：你好，世界！🎉"
    cn_gbk = "中文字幕：你好，世界！繁體與简体"  # GBK 可编码（不含 emoji）
    # UTF-8 无 BOM / 带 BOM
    check("UTF-8 无 BOM", d(cn.encode("utf-8")) == cn)
    check("UTF-8 带 BOM", d(b"\xef\xbb\xbf" + cn.encode("utf-8")) == cn)
    # GBK（GB18030 超集）老式中文 Windows / 字幕工具导出
    gbk = cn_gbk.encode("gbk")
    check("GBK 正确解码回中文", d(gbk) == cn_gbk, d(gbk)[:12])
    # UTF-16 LE 带 BOM（记事本“Unicode”保存）
    check("UTF-16 LE BOM", d((b"\xff\xfe" + cn.encode("utf-16-le"))) == cn)
    # str 原样、None 安全
    check("str 原样返回", d(cn) is cn or d(cn) == cn)
    check("None 返回空串", d(None) == "")
    # 损坏/随机字节绝不抛异常
    import random
    random.seed(1)
    bad = bytes(random.randrange(256) for _ in range(200))
    raised = False
    try:
        d(bad)
    except UnicodeDecodeError:
        raised = True
    check("任意坏字节不抛 UnicodeDecodeError", not raised)

    # read_text_any：分别以 UTF-8 / GBK 落盘都能正确读回
    p_u = os.path.join(base, "u.srt")
    p_g = os.path.join(base, "g.srt")
    open(p_u, "wb").write(("1\n00:00:01,000 --> 00:00:02,000\n" + cn_gbk + "\n\n").encode("utf-8"))
    open(p_g, "wb").write(("1\n00:00:01,000 --> 00:00:02,000\n" + cn_gbk + "\n\n").encode("gbk"))
    check("read_text_any 读 UTF-8 文件", cn_gbk in engine.read_text_any(p_u))
    check("read_text_any 读 GBK 文件", cn_gbk in engine.read_text_any(p_g))
    # write_text_utf8 BOM 选项
    p_b = os.path.join(base, "b.txt")
    engine.write_text_utf8(p_b, cn_gbk, bom=True)
    check("write_text_utf8(bom=True) 带 BOM", open(p_b, "rb").read().startswith(b"\xef\xbb\xbf"))

    # 校准统一脚本自带同款 _decode_any，能读 GBK 字幕（端到端关键路径）
    try:
        import importlib.util
        merged = os.path.join(engine.APP_DIR, "subtitle_calib_merged.py")
        spec = importlib.util.spec_from_file_location("subtitle_calib_merged", merged)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        check("校准脚本 _decode_any 可读 GBK 字幕",
              mod._decode_any(cn_gbk.encode("gbk")) == cn_gbk)
        # 回归（2026-09-28）：英文 ASR 断词 + 谷翻硬译残留
        #   实测："Water ing lace just released shin the reson ator showcase,"
        #         -> 中文"浇水蕾丝刚刚在共鸣者展示柜上发布"（全错）
        d = tempfile.mkdtemp(prefix="vt_calib_split_")
        src = os.path.join(d, "s.srt")
        dst = os.path.join(d, "o.srt")
        srt = ("1\n00:00:01,000 --> 00:00:03,000\n"
               "浇水蕾丝刚刚在共鸣者展示柜上发布\n"
               "Water ing lace just released shin the reson ator showcase,\n\n"
               "2\n00:00:04,000 --> 00:00:06,000\n"
               "谐振器刚刚发布\nreson ator just released\n\n"
               "3\n00:00:07,000 --> 00:00:09,000\n"
               "我喜欢给花浇水，这是正常的浇水方式\n"
               "I like watering flowers, this is a normal watering method\n")
        open(src, "wb").write(srt.encode("utf-8"))
        mod.process(src, dst, mode="bi")
        got = open(dst, encoding="utf-8-sig").read()
        check("校准：ASR 断词硬译 '浇水蕾丝'->'鸣潮'",
              "鸣潮" in got and "浇水蕾丝" not in got,
              got.splitlines()[2] if len(got.splitlines()) > 2 else got)
        check("校准：'共鸣者展示柜'->'共鸣者展示'（resonator showcase）",
              "展示柜" not in got)
        check("校准：断词锚定 'reson ator'->谐振器->共鸣者",
              "共鸣者刚刚发布" in got)
        check("校准：正常句 '浇水方式' 无英文佐证时不误伤",
              "正常的浇水方式" in got)
        check("scan-split 识别 'reson ator' 断词",
              any(j.lower() == "resonator"
                  for _l, _r, j, _a in mod._scan_split_line("reson ator just released")))
        check("_ref_for_match 规整 'Water ing lace'->'Wuthering Waves'",
              mod._ref_for_match("Water ing lace just released").startswith("Wuthering Waves"))
    except Exception as e:  # noqa: BLE001
        check("校准脚本 _decode_any 可读 GBK 字幕", False, str(e))


def test_ai_settings_automatch():
    """v1.16.5：设置自动匹配——把「错配的设置」在落盘/发请求前纠正掉。

    来源：用户实测反馈。旧版把「火山 Token Plan 地址 + 非套餐模型」这个纯
    设置错误，处理成「换按量端点重试 → 401 鉴权失败」的长篇英文报错，逐块
    校准时还会放大成整轮 401 风暴。现在的策略是先就地换模型（端点和 Key 都
    不动），只有确实换了 Key 类型才动端点。
    """
    print("\n[6] 设置自动匹配（火山方舟 Token Plan 端点 ↔ 模型）")
    try:
        m = engine.ai_mod()
    except Exception as e:  # noqa: BLE001
        check("ai_client 可加载", False, str(e))
        return
    PLAN = "https://ark.cn-beijing.volces.com/api/plan/v3"
    PAYG = "https://ark.cn-beijing.volces.com/api/v3"

    # ① 端点判据：plan / paygo / coding 三者互斥
    check("plan 端点判据（/api/plan/v3）",
          m._is_volces_plan_url(PLAN + "/chat/completions") is True
          and m._is_volces_paygo_url(PLAN + "/chat/completions") is False)
    check("paygo 端点判据（/api/v3）",
          m._is_volces_paygo_url(PAYG + "/chat/completions") is True
          and m._is_volces_plan_url(PAYG + "/chat/completions") is False)
    check("coding 端点不算 plan 也不算 paygo（Anthropic 专用，另有守卫）",
          m._is_volces_plan_url("https://ark.cn-beijing.volces.com/api/coding/v3")
          is False
          and m._is_volces_paygo_url("https://ark.cn-beijing.volces.com/api/coding/v3")
          is False)

    # ② 核心：套餐端点 + 非套餐模型 → 换成套餐模型（用户 23:30 的设置错误）
    out, notes = m.match_settings({
        "base_url": PLAN, "model": "deepseek-flash",
        "vision_model": "doubao-seed-1.6-flash",
        "calib_max_tokens": 1048576, "calib_context_tokens": 1048576})
    check("套餐端点 + 按量模型 → 自动换套餐模型",
          out["model"] in m.VOLCES_PLAN_MODELS, out["model"])
    check("视觉槽同步匹配（否则屏幕识别仍会 404）",
          out["vision_model"] in m.VOLCES_PLAN_MODELS, out["vision_model"])
    check("预算按模型能力夹回（1M 输出 → 上限）",
          out["calib_max_tokens"] <= m.model_caps(out["model"])["out"]
          and out["calib_context_tokens"] <= m.model_caps(out["model"])["ctx"],
          f"out={out['calib_max_tokens']} ctx={out['calib_context_tokens']}")
    check("每项纠正都给出人话说明", len(notes) >= 3, " / ".join(notes)[:150])

    # ③ 已自洽的配置必须原样返回（避免每次保存都"修正"一遍产生噪音）
    out2, notes2 = m.match_settings({
        "base_url": PLAN, "model": "deepseek-v4-flash",
        "vision_model": "deepseek-v4-flash",
        "calib_max_tokens": 65536, "calib_context_tokens": 1048576})
    check("自洽配置零改动（模型未变）", out2["model"] == "deepseek-v4-flash")
    check("自洽配置零说明（不误报修正）", notes2 == [], str(notes2))

    # ④ 纯函数：不得就地修改传入的 dict
    src = {"base_url": PLAN, "model": "deepseek-flash"}
    m.match_settings(src)
    check("match_settings 不就地改动传入配置", src["model"] == "deepseek-flash")

    # ⑤ 视觉槽留空跟随文本模型；输出预算过小抬到可工作阈值
    out3, _n3 = m.match_settings({
        "base_url": PLAN, "model": "deepseek-v4-flash", "vision_model": "",
        "calib_max_tokens": 512})
    check("视觉模型留空 → 跟随文本模型",
          out3["vision_model"] == "deepseek-v4-flash", out3["vision_model"])
    check("输出预算过小（512）→ 抬到 8192",
          out3["calib_max_tokens"] == 8192, str(out3["calib_max_tokens"]))

    # ⑥ 引擎层：保存时自动匹配 + 说明可回传界面
    check("引擎暴露 ai_match_settings / ai_last_auto_notes",
          callable(getattr(engine, "ai_match_settings", None))
          and callable(getattr(engine, "ai_last_auto_notes", None)))

    # ⑦ 客户端构造即匹配：错配模型不会被打出去（端到端最贴近用户现象的一步）
    try:
        c = m.AIClient({"base_url": PLAN, "api_key": "dummy",
                        "model": "deepseek-flash",
                        "vision_model": "doubao-seed-1.6-flash"})
        check("客户端构造即把模型匹配成套餐模型（不发出错配请求）",
              c.model in m.VOLCES_PLAN_MODELS and bool(c.auto_notes),
              f"model={c.model} notes={len(c.auto_notes)}")
        check("客户端默认未标记为「套餐专用 Key」（避免误跳过换端点重试）",
              c.plan_key_only is False)
    except Exception as e:  # noqa: BLE001
        check("客户端构造即匹配", False, str(e))


    # ⑧ 厂商 ↔ 模型名（跨平台抄错模型名 / 抄到已停用旧名，比端点类型错更常见）
    check("DeepSeek 官方 + 已停用的 deepseek-chat → deepseek-flash",
          m.match_provider_model("https://api.deepseek.com",
                                 "deepseek-chat")[0] == "deepseek-flash")
    check("DeepSeek 官方 + 已停用的 deepseek-reasoner → deepseek-v4-pro",
          m.match_provider_model("https://api.deepseek.com",
                                 "deepseek-reasoner")[0] == "deepseek-v4-pro")
    check("DeepSeek 官方 + 火山套餐名 deepseek-v4.1-flash → deepseek-flash",
          m.match_provider_model("https://api.deepseek.com",
                                 "deepseek-v4.1-flash")[0] == "deepseek-flash")
    check("DeepSeek 官方现役模型原样保留（含官方兼容的旧名）",
          m.match_provider_model("https://api.deepseek.com",
                                 "deepseek-flash")[0] == "deepseek-flash"
          and m.match_provider_model("https://api.deepseek.com",
                                     "deepseek-v4-pro")[0] == "deepseek-v4-pro"
          and m.match_provider_model("https://api.deepseek.com",
                                     "deepseek-v4-flash")[0]
          == "deepseek-v4-flash")
    check("智谱端点 + deepseek-chat → glm-4.7-flash",
          m.match_provider_model("https://open.bigmodel.cn/api/paas/v4",
                                 "deepseek-chat")[0] == "glm-4.7-flash")
    check("火山按量 + doubao 模型 原样保留（不做无谓改动）",
          m.match_provider_model("https://ark.cn-beijing.volces.com/api/v3",
                                 "doubao-seed-1.6-flash")[0]
          == "doubao-seed-1.6-flash")
    check("未识别厂商（自建中转）不做校验，原样放行",
          m.match_provider_model("https://my-proxy.internal/v1",
                                 "anything-goes")[0] == "anything-goes")
    check("厂商判据 provider_of 命中/未命中正确",
          m.provider_of("https://api.deepseek.com") == "api.deepseek.com"
          and m.provider_of("https://my-proxy.internal") == "")
    # ⑨ 端到端：用户实测的失效配置（DeepSeek 官方 + 已停用的 deepseek-chat，
    #    预算还被旧能力表夹到 8192/65536）被修好
    _fx, _fn = engine.ai_match_settings({
        "base_url": "https://api.deepseek.com", "model": "deepseek-chat",
        "vision_model": "deepseek-chat",
        "calib_max_tokens": 65536, "calib_context_tokens": 1000000})
    check("端到端：DeepSeek 官方停用旧名被换成现役模型并给出说明",
          _fx["model"] == "deepseek-flash"
          and _fx["vision_model"] == "deepseek-flash"
          and len(_fn) >= 2, " / ".join(_fn)[:160])
    check("端到端：DeepSeek 官方能力值按官方文档（1M / 384K）不再误夹预算",
          _fx["calib_max_tokens"] == 65536
          and _fx["calib_context_tokens"] == 1000000,
          "out=%s ctx=%s" % (_fx["calib_max_tokens"],
                             _fx["calib_context_tokens"]))
    # ⑩ 视觉能力：deepseek-v4-pro 不支持图片输入 → 视觉槽换 deepseek-flash
    _vx, _vn = engine.ai_match_settings({
        "base_url": "https://api.deepseek.com", "model": "deepseek-v4-pro",
        "vision_model": ""})
    check("DeepSeek v4-pro 视觉槽自动换成支持视觉的 deepseek-flash",
          _vx["vision_model"] == "deepseek-flash", _vx["vision_model"])
    check("厂商级能力覆盖表生效（同名 deepseek-flash 官方 1M/384K）",
          (m.model_caps("deepseek-flash", "https://api.deepseek.com") or {}).get("ctx")
          == 1048576
          and (m.model_caps("deepseek-flash",
                            "https://ark.cn-beijing.volces.com/api/v3")
               or {}).get("ctx") == 131072)

    # ⑪ 订阅套餐端点合规风险提示（2026-10-05 产品口径：允许接入、只做提示）
    _plan_hits = [
        "https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
        "https://token-plan.cn-beijing.maas.aliyuncs.com/apps/anthropic",
        "https://coding.dashscope.aliyuncs.com/v1",
        "https://ark.cn-beijing.volces.com/api/plan/v3",
        "https://ark.cn-beijing.volces.com/api/coding/v3",
        "https://open.bigmodel.cn/api/coding/paas/v4",
    ]
    _miss = [
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "https://ark.cn-beijing.volces.com/api/v3",
        "https://api.siliconflow.cn/v1",
        # ⚠ 专属实例不能当套餐端点，否则会把自建部署的用户吓一跳
        "https://llm-ukmkj60gxr2wms1f.cn-beijing.maas.aliyuncs.com/"
        "compatible-mode/v1",
        "",
    ]
    check("套餐端点识别齐全（百炼 Token/Coding Plan、火山 Agent/Coding、智谱 Coding）",
          all(m.plan_endpoint_risk(u) for u in _plan_hits),
          " / ".join(u for u in _plan_hits if not m.plan_endpoint_risk(u))[:120])
    check("按量端点与专属实例不误报",
          all(not m.plan_endpoint_risk(u) for u in _miss),
          " / ".join(u for u in _miss if m.plan_endpoint_risk(u))[:120])
    check("提示含「风险自负」与稳妥替代端点",
          "风险由你自行承担" in m.plan_endpoint_risk(_plan_hits[0])
          and "dashscope.aliyuncs.com" in m.plan_endpoint_risk(_plan_hits[0]))
    check("只提示、不改变地址与模型（提示函数是纯查询）",
          m.plan_endpoint_risk(_plan_hits[0]) != ""
          and m.match_settings({"base_url": _plan_hits[0],
                                "model": "deepseek-v4.1-flash"})[0]["base_url"]
          == _plan_hits[0])
    check("引擎暴露 ai_plan_risk / ai_plan_risks（三处端点去重）",
          callable(getattr(engine, "ai_plan_risk", None))
          and callable(getattr(engine, "ai_plan_risks", None)))
    _risks = engine.ai_plan_risks({
        "base_url": "https://token-plan.cn-beijing.maas.aliyuncs.com/"
                    "compatible-mode/v1",
        "vision_base_url": "",
        "asr_base_url": "https://token-plan.cn-beijing.maas.aliyuncs.com/"
                        "compatible-mode/v1"})
    check("同一套餐端点只提示一次（去重）", len(_risks) == 1, str(_risks)[:120])
    # ⚠ 出处前缀：三个槽各有地址，汇总成一条 InfoBar 时必须说清是哪一处，
    #   否则"全局 AI 填智谱、弹窗说百炼"看起来就像识别错了（2026-10-05 实测）
    _rr = engine.ai_plan_risks({
        "base_url": "https://open.bigmodel.cn/api/paas/v4/chat/completions",
        "asr_base_url": "https://token-plan.cn-beijing.maas.aliyuncs.com/"
                        "compatible-mode/v1"})
    check("风险提示标明出处（智谱地址 + 百炼 ASR 时只报 ASR 那条）",
          len(_rr) == 1 and _rr[0].startswith("【ASR 语音识别】"), str(_rr)[:90])
    _rr2 = engine.ai_plan_risks({
        "base_url": "https://token-plan.cn-beijing.maas.aliyuncs.com/"
                    "compatible-mode/v1",
        "asr_base_url": "https://token-plan.cn-beijing.maas.aliyuncs.com/"
                        "compatible-mode/v1"})
    check("同一端点占两个槽时合并标注（不重复弹两遍）",
          len(_rr2) == 1 and _rr2[0].startswith("【全局 AI / ASR 语音识别】"),
          str(_rr2)[:90])
    check("非套餐配置零提示", engine.ai_plan_risks({
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "asr_base_url": "https://api.siliconflow.cn/v1"}) == [])

    # ⑫ 校准等待期可观测性（2026-10-05：一块因超时重试拖到 7 分 39 秒，
    #    而重试消息走的是一个从没配过 handler 的 logger ⇒ 界面全程空白）
    # ⚠ 用 m.logger 而不是 getLogger("ai_client")：ai_client 可能以包名导入
    #   （logger 名带前缀），按名字取会拿到另一个空 logger，误判成"没挂上"。
    check("ai_client 挂了文件日志 handler（重试/超时留痕）",
          any(type(h).__name__ == "RotatingFileHandler" for h in m.logger.handlers),
          "%s: %s" % (m.logger.name,
                      [type(h).__name__ for h in m.logger.handlers]))
    _c1 = m.AIClient({"base_url": "https://api.deepseek.com", "api_key": "x"})
    _tos = [_c1._timeout_for({"max_tokens": n}) for n in (512, 8192, 65536, 393216)]
    check("大块请求超时按输出预算放宽（≤8192 维持 90s；65536→300s 封顶）",
          _tos[0] == 90 and _tos[1] == 90 and _tos[2] == 300 and _tos[3] == 300,
          str(_tos))
    check("超时/网络错误不再被误判成「max_tokens 超限」（防减半重试风暴）",
          m._is_max_tokens_over("等待响应超时（90 秒内没收到任何数据）") is False
          and m._is_max_tokens_over("网络错误: <urlopen error timed out>") is False
          and m._is_max_tokens_over("HTTP 400: max_tokens is too large") is True)
    _ev = []
    _c2 = m.AIClient({"base_url": "https://10.255.255.1/v1", "api_key": "x",
                      "timeout": 0.5, "retries": 1})
    _c2.on_event = lambda msg, level="info": _ev.append((level, msg))
    try:
        _c2.chat_openai("hi", max_tokens=64)
    except Exception:  # noqa: BLE001
        pass
    check("重试事件经 on_event 上报（校准日志能看见「正在重试」）",
          len(_ev) == 1 and _ev[0][0] == "err" and "重试" in _ev[0][1],
          str(_ev)[:140])
    check("引擎把重试事件接到校准日志（_CALIB_EVENT_SINK 已接线）",
          callable(getattr(engine, "_calib_event_sink", None))
          and isinstance(getattr(engine, "_CALIB_EVENT_SINK", None), list)
          and callable(getattr(engine, "calib_ai_chat", None)))


def main():
    print("=" * 62)
    print("  视频工具箱 v1.3 打包功能离线自检")
    print("=" * 62)

    test_launcher_encoding()
    ffmpeg, ffprobe = engine.ensure_ffmpeg()
    engine.FFPROBE_PATH = ffprobe
    print(f"[工具] ffmpeg: {ffmpeg}")

    base = tempfile.mkdtemp(prefix="vt_selftest_")
    backup_cfg = None
    if os.path.isfile(engine.CONFIG_PATH):
        backup_cfg = engine.CONFIG_PATH + ".selftest_bak"
        shutil.copy2(engine.CONFIG_PATH, backup_cfg)

    try:
        test_codec_compat(base)
        test_sanitize_and_unique_folder(base)
        test_write_info_txt(base)
        test_cover_1280x720(base, ffmpeg)
        test_config_persistence(base)
        test_output_template(base)
        test_ai_settings_automatch()
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
