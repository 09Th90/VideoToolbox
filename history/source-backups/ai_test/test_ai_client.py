# -*- coding: utf-8 -*-
"""AI 客户端全链路实测（不触浏览器）：
1. quick_test：文本通道 glm-4.7-flash 连通；
2. chat_vision：视觉通道 glm-4.6v-flash 读真实界面截图并做 0-1000 坐标定位；
3. detect_language：中/英/日标题语言识别；
4. 语言→B站字幕语言 / yt-dlp sub-langs 映射。
"""
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "tools" / "uploader_src"
sys.path.insert(0, str(SRC))
sys.dont_write_bytecode = True

from modules import ai_client  # noqa: E402

ok_all = True

def check(name, cond, extra=""):
    global ok_all
    print(("PASS" if cond else "FAIL"), name, extra)
    if not cond:
        ok_all = False

cfg = ai_client.load_config()
print("config:", {k: (v if k != "api_key" else "***") for k, v in cfg.items()})
check("配置: 模型 glm-4.7-flash", cfg["model"] == "glm-4.7-flash")
check("配置: 视觉模型 glm-4.6v-flash", cfg["vision_model"] == "glm-4.6v-flash")

client = ai_client.get_client()
print("文本端点:", client.url)
print("视觉端点:", client.vision_url)

# 1. 文本通道
ok, msg = ai_client.quick_test()
check("文本通道 quick_test", ok, msg[:120])

# 2. 视觉通道：真实界面截图定位「简介」输入框
shot = Path(__file__).resolve().parents[1] / "upload_tab_v171_full.png"
raw = client.chat_vision(
    "这是软件界面截图。任务：找到「简介（支持换行）」标签下方的多行文本输入框中心点。"
    "返回严格JSON（不要输出其他文字）：{\"found\": true, \"x\": <0-1000归一化横坐标>, "
    "\"y\": <0-1000归一化纵坐标>, \"label\": \"你看到的元素文字\"}；找不到返回 {\"found\": false}",
    [shot], max_tokens=1024)
print("视觉定位原始回复:", raw[:200])
data = ai_client.try_parse_json(raw)
check("视觉通道返回合法 JSON", isinstance(data, dict), str(data)[:120])
if isinstance(data, dict):
    check("视觉定位 found=True", bool(data.get("found")))
    x, y = float(data.get("x", -1)), float(data.get("y", -1))
    # 简介输入框中心大约在 (518, 670)/1000 附近，允许 ±120 误差
    check("视觉定位坐标合理", 380 <= x <= 660 and 550 <= y <= 800, f"x={x} y={y}")

# 3. 语言识别
cases = {
    "【4K】New York City Walking Tour - Manhattan Downtown": "en",
    "鸣潮 2.0 版本全剧情流程实况解说": "zh",
    "【歌ってみた】夜に駆ける  covered by 花譜": "ja",
}
for title, expect in cases.items():
    code = ai_client.detect_language(title)
    check(f"语言识别 {expect}", code == expect, f"得到 {code} | {title[:30]}")

# 4. 映射
check("映射 zh→简体中文", ai_client.bili_subtitle_lang("zh") == "简体中文")
check("映射 en→英语", ai_client.bili_subtitle_lang("en") == "英语")
check("映射 en→sub-langs", "en" in ai_client.ytdlp_sub_langs("en"))
check("映射 zh→sub-langs", "zh-Hans" in ai_client.ytdlp_sub_langs("zh"))

print("\n=== 全部通过 ===" if ok_all else "\n=== 有失败项 ===")
sys.exit(0 if ok_all else 1)
