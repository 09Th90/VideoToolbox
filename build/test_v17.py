# -*- coding: utf-8 -*-
"""v1.7 改造的离线功能验证（不启动浏览器）"""
import os, sys, json, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "tools", "uploader_src"))

import video_toolbox as eng

print("== 1. 路径锚点 ==")
checks = {
    "APP_DIR": eng.APP_DIR == ROOT,
    "TOOLS_DIR": eng.TOOLS_DIR.endswith("tools"),
    "SRC_DIR": eng.SRC_DIR.endswith("src"),
    "DOCS_DIR": eng.DOCS_DIR.endswith("docs"),
    "DATA_DIR": eng.DATA_DIR.endswith("data"),
    "LOGS_DIR": eng.LOGS_DIR.endswith("logs"),
    "CONFIG_PATH in data": eng.CONFIG_PATH.endswith(os.path.join("data", "config.json")),
    "DOWNLOAD in data": eng.DEFAULT_DOWNLOAD_DIR.endswith(os.path.join("data", "downloads")),
    "PROFILE in data": eng.UPLOADER_PROFILE.endswith(os.path.join("data", "uploader_profile")),
    "TASKS in data": eng.UPLOADER_TASKS_DIR.endswith(os.path.join("data", "uploader_tasks")),
    "UPLOG in logs": eng.UPLOADER_LOGS_DIR.endswith(os.path.join("logs", "uploader")),
    "CATALOG in data": eng.CATALOG_DIR.endswith(os.path.join("data", "catalog")),
    "worker in src": eng.asr_worker_script().endswith(os.path.join("src", "asr_subtitle_worker.py")),
}
for k, v in checks.items():
    print(("  OK " if v else "  FAIL ") + k)
assert all(checks.values()), "路径锚点错误"
for d in (eng.DATA_DIR, eng.LOGS_DIR, eng.UPLOADER_PROFILE, eng.CATALOG_DIR):
    assert os.path.isdir(d), d
print("  运行时目录均已创建")

print("== 2. 视频信息.txt 生成 -> 解析 往返 ==")
with tempfile.TemporaryDirectory() as td:
    data = {"title": "测试标题", "description": "第一行简介\n第二行简介",
            "webpage_url": "https://www.bilibili.com/video/BV1xx",
            "uploader": "UP主", "uploader_url": "https://space.bilibili.com/123456",
            "tags": ["标签A", "标签B"], "categories": []}
    eng.write_info_txt(td, data, quality_label="1080P 高清")
    txt = os.path.join(td, "视频信息.txt")
    info = eng.parse_info_txt(txt)
    print("  解析结果:", json.dumps(info, ensure_ascii=False))
    assert info["title"] == "测试标题"
    assert "第二行简介" in info["description"]
    assert info["tags"] == ["标签A", "标签B"]
    assert info["zone"] == "" and info["topics"] == []
    assert info["declaration"] == ""  # “无需标注”归一为空
    # 手工补写分区/话题/声明后再解析
    raw = open(txt, encoding="utf-8-sig").read()
    raw = raw.replace("分区: ", "分区: 游戏") \
             .replace("话题: ", "话题: 话题1,话题2") \
             .replace("创作声明: 无需标注", "创作声明: 含有虚构演绎内容")
    open(txt, "w", encoding="utf-8-sig").write(raw)
    info2 = eng.parse_info_txt(txt)
    assert info2["zone"] == "游戏", info2
    assert info2["topics"] == ["话题1", "话题2"], info2
    assert info2["declaration"] == "含有虚构演绎内容", info2
    assert info2["source_url"] == "https://www.bilibili.com/video/BV1xx", info2
    assert info2["uploader_url"] == "https://space.bilibili.com/123456", info2
    print("  OK 全字段往返一致")

print("== 2.1 简介格式（源地址/来源/原简介） ==")
info3 = {"description": "第一行\n第二行",
         "source_url": "https://www.bilibili.com/video/BV1xx",
         "uploader_url": "https://space.bilibili.com/123456"}
desc = eng.build_posting_description(info3)
print("  生成简介:\n" + desc)
assert desc == "源地址：\nhttps://www.bilibili.com/video/BV1xx\n来源：https://space.bilibili.com/123456\n原简介：\n第一行\n第二行", repr(desc)
assert eng.build_posting_description({"description": "仅有简介"}) == "仅有简介"
print("  OK 简介格式正确")

print("== 2.2 原始字幕自动查找 ==")
with tempfile.TemporaryDirectory() as td:
    open(os.path.join(td, "demo.mp4"), "wb").write(b"x")
    open(os.path.join(td, "demo.en.srt"), "w", encoding="utf-8").write("1\n00:00:00,000 --> 00:00:01,000\nhi\n")
    open(os.path.join(td, "demo.zh-Hans.srt"), "w", encoding="utf-8").write("1\n00:00:00,000 --> 00:00:01,000\n你好\n")
    found = eng.find_subtitle_for_video(os.path.join(td, "demo.mp4"))
    assert os.path.basename(found) == "demo.en.srt", found
    # 精确同名优先于 .en
    open(os.path.join(td, "demo.srt"), "w", encoding="utf-8").write("x")
    found2 = eng.find_subtitle_for_video(os.path.join(td, "demo.mp4"))
    assert os.path.basename(found2) == "demo.srt", found2
    assert eng.find_subtitle_for_video(os.path.join(td, "none.mp4")) == ""
print("  OK 字幕查找优先级正确")

print("== 3. sidecar 识别 标签 vs 话题 ==")
from modules import sidecar
with tempfile.TemporaryDirectory() as td:
    p = os.path.join(td, "视频信息.txt")
    open(p, "w", encoding="utf-8").write(
        "标题: T\n标签: a,b\n话题: h1,h2\n分区: 游戏/电子竞技\n创作声明: 无需标注\n简介: d\n")
    parsed = sidecar.parse_sidecar_file(p)
    print("  sidecar:", json.dumps(parsed, ensure_ascii=False))
    assert parsed["tags"] == ["a", "b"]
    assert parsed["topics"] == ["h1", "h2"]
    assert parsed["zone"] == ["游戏", "电子竞技"]
    assert "declaration" not in parsed  # 无需标注不进任务
    print("  OK 标签/话题已正确区分")

print("== 4. 分区接口数据归一化（单级） ==")
from modules import catalog
# B 站当前为单级分区：扁平列表原样归一
api_data = [{"tid": 17, "name": "游戏"}, {"tid": 1, "name": "动画"},
            {"tid": 3, "name": "音乐"}]
areas = catalog._normalize_areas(api_data)
assert areas[0]["name"] == "游戏" and areas[0]["tid"] == 17
assert [a["name"] for a in areas] == ["游戏", "动画", "音乐"]
# 兼容仍返回两级树的接口形态：自动拍平为叶子
api_nested = [{"tid": 17, "name": "游戏", "children": [
    {"tid": 171, "name": "电子竞技"}, {"tid": 172, "name": "手机游戏"}]},
    {"tid": 1, "name": "动画", "children": [{"tid": 27, "name": "综合"}]}]
areas2 = catalog._normalize_areas({"list": api_nested})
assert [a["name"] for a in areas2] == ["电子竞技", "手机游戏", "综合"], areas2
print("  OK 单级归一（扁平 / 两级树拍平）均正确")

print("== 4.1 合集缓存路径 ==")
assert str(catalog.cache_path("collections")).endswith(
    os.path.join("data", "catalog", "collections.json"))
print("  OK collections.json 路径正确")

print("== 5. uploader config 锚点 ==")
import config as upcfg
assert str(upcfg.PROFILE_DIR) == eng.UPLOADER_PROFILE, (upcfg.PROFILE_DIR, eng.UPLOADER_PROFILE)
assert str(upcfg.TASKS_DIR) == eng.UPLOADER_TASKS_DIR
assert str(upcfg.LOGS_DIR).replace("/", "\\").endswith(os.path.join("logs", "uploader"))
assert str(upcfg.CATALOG_DIR).replace("/", "\\").endswith(os.path.join("data", "catalog"))
print("  OK 投稿引擎与主程序路径一致")

print("\nALL_V17_TESTS_PASSED")
