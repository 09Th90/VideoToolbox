#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# @version 1.18.3
"""B 站自动投稿 —— 用内置 MAA 视觉引擎驱动（不碰目标进程内存、不注入脚本）。

定位
====
v1.9 时期投稿走的是 Playwright + CDP + AI 视觉（`history/source-backups/
backup_v19_vision/`），v1.10.1 随投稿板块一起移除。本模块按 v1.17.0 的新
路线重做：**驱动用户自己已登录的浏览器窗口**，全程「抓帧 → 识别 → 声明式
任务 → 鼠标/键盘注入」，也就是 `auto_vision_core` 那套四段设计。

需求对齐历史开发（R1–R5）：
  · R1 登录态复用   —— 不再自建浏览器：直接用用户浏览器里已登录的 B 站会话；
  · R2 视频上传     —— 点「上传视频」→ 系统文件对话框里粘贴路径 + 回车；
  · R3 表单填写     —— 标题 / 简介 / 标签 / 参与话题 / 分区 / 创作声明；
  · R4 分区检测     —— 分区下拉用 AI 视觉枚举（见 `detect_zone_options`）；
  · R5 提交         —— 等「立即投稿」可用 → 点击 → 等成功标志。

本模块**不碰 Qt**，可单独单测；界面在 `auto_vision_page.py`。

素材（模板）从哪来
==================
视觉方案的眼睛是模板图。这里给出 `TEMPLATE_MANIFEST`（13 张必需模板）与
采集向导：在投稿页上把每张图框出来存到 `data/auto_vision/bili/`，管线即按
文件名引用。模板缺失时 `missing_templates()` 会列出来，界面据此提示。
"""

import io
import json
import os
import re
import time

import auto_vision_core as av
from PIL import Image

#: B 站投稿页（用户浏览器里需已登录）
UPLOAD_URL = "https://member.bilibili.com/platform/upload/video/frame"
#: 模板子目录（相对 data/auto_vision）
TEMPLATE_SUBDIR = "bili"
#: 失败截图子目录（相对 data）
SCREENSHOT_SUBDIR = os.path.join("bili_upload", "shots")
#: 投稿物料文件名（与历史开发一致：视频所在目录里的 视频信息.txt）
WULIAO_NAME = "视频信息.txt"

#: 上传等待上限（秒）：大文件上传 + 转码，给足时间
UPLOAD_WAIT_SECONDS = 300


# ---------------------------------------------------------------------- #
# 模板清单：采集向导与管线共用的唯一权威
# ---------------------------------------------------------------------- #
#: 每项 {key, file, label, hint, optional}
TEMPLATE_MANIFEST = [
    {"key": "upload_entry", "file": "01_upload_entry.png",
     "label": "上传视频入口",
     "hint": "投稿页中部的「上传视频」大按钮 / 拖拽区（点它才弹文件对话框）"},
    {"key": "upload_done", "file": "02_upload_done.png",
     "label": "上传完成标志",
     "hint": "上传/转码完成后才出现的元素（如封面候选区、『上传完成』字样）"},
    {"key": "title_input", "file": "03_title_input.png",
     "label": "标题输入框",
     "hint": "「标题」右侧的输入框（截输入框本身，别把标签文字截进去）"},
    {"key": "desc_input", "file": "04_desc_input.png",
     "label": "简介输入框",
     "hint": "「简介」下方的多行输入区"},
    {"key": "tags_input", "file": "05_tags_input.png",
     "label": "标签输入框",
     "hint": "「标签」旁的输入框（输入后回车添加一个标签）"},
    {"key": "topic_input", "file": "06_topic_input.png",
     "label": "参与话题输入框", "optional": True,
     "hint": "「参与话题」的输入框（任务没填话题时可跳过）"},
    {"key": "zone_open", "file": "07_zone_open.png",
     "label": "选择分区按钮",
     "hint": "「分区」那一行的『请选择』/『修改』按钮（点开分区面板）"},
    {"key": "zone_search", "file": "08_zone_search.png",
     "label": "分区搜索框",
     "hint": "分区面板顶部/内部的搜索输入框（用搜索定位分区，比翻列表稳）"},
    {"key": "zone_first", "file": "09_zone_first.png",
     "label": "分区搜索结果第一项",
     "hint": "搜索后第一条结果的样子（点它即选中该分区）"},
    {"key": "cover_first", "file": "10_cover_first.png",
     "label": "第一张候选封面", "optional": True,
     "hint": "封面候选区里第一张自动生成的封面"},
    {"key": "declaration_self", "file": "11_declaration_self.png",
     "label": "创作声明「自制」", "optional": True,
     "hint": "创作声明里的「自制」选项（原创投稿默认选它）"},
    {"key": "submit_button", "file": "12_submit_button.png",
     "label": "「立即投稿」按钮",
     "hint": "页面右下角的「立即投稿」按钮"},
    {"key": "submit_success", "file": "13_submit_success.png",
     "label": "投稿成功标志",
     "hint": "提交后出现的成功提示（如『投稿成功』弹窗 / 跳转投稿管理页的元素）"},
]


def template_dir(data_dir):
    """模板目录：`<data>/auto_vision/bili`。"""
    return os.path.join(data_dir, "auto_vision", TEMPLATE_SUBDIR)


def screenshot_dir(data_dir):
    """失败截图目录：`<data>/bili_upload/shots`。"""
    return os.path.join(data_dir, SCREENSHOT_SUBDIR)


def missing_templates(data_dir, include_optional=False):
    """返回尚未采集的模板项（列表）。`include_optional` 为 False 时忽略可选模板。"""
    tdir = template_dir(data_dir)
    out = []
    for item in TEMPLATE_MANIFEST:
        if item.get("optional") and not include_optional:
            continue
        if not os.path.isfile(os.path.join(tdir, item["file"])):
            out.append(item)
    return out


def template_ready(data_dir):
    """必需模板是否齐备。"""
    return not missing_templates(data_dir)


# ---------------------------------------------------------------------- #
# 投稿物料解析（视频信息.txt）
# ---------------------------------------------------------------------- #
#: 字段别名：中英文/常见写法都认
_FIELD_ALIASES = {
    "title": ("标题", "title", "名字", "稿件标题"),
    "tags": ("标签", "tag", "tags", "关键词"),
    "zone": ("分区", "zone", "版块", "分类"),
    "desc": ("简介", "描述", "desc", "description", "说明", "原简介"),
    "topic": ("话题", "topic", "参与话题", "活动"),
}

#: 旧版 视频信息.txt 里「简介:」之后还有 链接/博主/标签 等结构行；
#: 收集多行简介时遇到这些行要停，别把它们吃进简介正文
_STRUCT_BREAK_KEYS = ("视频链接", "博主", "博主主页", "下载画质", "下载时间",
                      "创作声明")


def _split_list(value):
    """把 `a / b、c，d,e` 这类串拆成列表。"""
    parts = re.split(r"[/、,，;；|]+", str(value or ""))
    return [p.strip() for p in parts if p.strip()]


def _field_of(key):
    """字段名 → 归一字段（title/tags/zone/desc/topic）；不认识返回空串。"""
    k = str(key or "").strip().lower()
    for field, aliases in _FIELD_ALIASES.items():
        if k in [a.lower() for a in aliases]:
            return field
    return ""


def split_tags(value):
    """把界面上的标签输入串拆成列表（额外把空白也当分隔符）。"""
    return _split_list(re.sub(r"\s+", "/", str(value or "")))


def _collect_desc_body(lines, i):
    """收集「原简介」行之后的多行正文（新样版 2026-10-06：字段行下一行直接
    跟内容）。遇到下一个已知字段行、旧版结构行或追加段落的 `──` 分隔线
    （校准产物「中文标题推荐」等，不属于简介）就停。返回 (desc, 新下标)。"""
    buf = []
    while i < len(lines):
        probe = lines[i].strip().lstrip("#").strip()
        if probe.startswith("──"):
            break
        pm = re.match(r"^([^:：]{1,8})\s*[:：]\s*(.+)$", probe)
        if pm and (_field_of(pm.group(1)) in ("title", "tags", "zone", "topic")
                   or pm.group(1) in _STRUCT_BREAK_KEYS):
            break
        buf.append(lines[i].rstrip())
        i += 1
    return "\n".join(buf).strip(), i


def parse_wuliao(text):
    """解析投稿物料文本，返回 `{title, tags, zone, desc, topic}`。

    兼容历史 `视频信息.txt` 的写法：`标题：xxx`、`标签：a / b / c`、
    `分区：游戏`、`话题：...`；标签/话题支持 `/`、`、`、`，`、`,` 分隔。
    v1.17.1 新样版：`原简介`（不带冒号）独立成行，正文从下一行起到文件尾
    （或下一个已知结构行 / 追加段分隔线）都算简介原文 —— 多行、原样保留；
    带冒号的 `原简介：` 旧写法同样支持。
    未出现的字段返回空串 / 空列表。
    """
    out = {"title": "", "tags": [], "zone": "", "desc": "", "topic": ""}
    lines = str(text or "").splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip().lstrip("#").strip()
        i += 1
        if not line:
            continue
        m = re.match(r"^([^:：]{1,8})\s*[:：]\s*(.*)$", line)
        if not m:
            if line == "原简介":                 # 新样版：无冒号独立成行
                out["desc"], i = _collect_desc_body(lines, i)
            continue
        key, val = m.group(1).strip(), m.group(2).strip()
        field = _field_of(key)
        if not field:
            continue
        # 去掉可能包着的引号/书名号
        val = val.strip().strip("「」《》\"'“”‘’")
        if field == "desc" and not val:
            out["desc"], i = _collect_desc_body(lines, i)
            continue
        if field == "tags":
            out[field] = _split_list(val)
        else:
            out[field] = val
    return out


def load_wuliao(path):
    """读取物料文件（UTF-8 / 带 BOM 均可），返回解析结果。"""
    try:
        with open(path, encoding="utf-8-sig") as f:
            return parse_wuliao(f.read())
    except OSError:
        return {"title": "", "tags": [], "zone": "", "desc": "", "topic": ""}


def find_wuliao(video_path):
    """在视频所在目录（及上一级）找 `视频信息.txt`，返回路径或 None。"""
    if not video_path:
        return None
    d = os.path.dirname(os.path.abspath(video_path))
    for _ in range(2):
        cand = os.path.join(d, WULIAO_NAME)
        if os.path.isfile(cand):
            return cand
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return None


# ---------------------------------------------------------------------- #
# 任务 / 变量
# ---------------------------------------------------------------------- #
def default_task():
    """投稿任务默认字段。"""
    return {
        "video": "",
        "title": "",
        "desc": "",
        "tags": [],
        "zone": "",
        "topic": "",
        "declaration": "self",   # self=自制 / repost=转载（仅 self 有模板）
        "submit": True,          # False = 只填不提交（演练）
    }


def default_vars(task):
    """任务 → 管线变量表（`{{name}}` 用它展开）。"""
    t = {**default_task(), **(task or {})}
    tags = t.get("tags")
    if isinstance(tags, (list, tuple)):
        tags = [str(x).strip() for x in tags if str(x).strip()]
    else:
        tags = _split_list(tags)
    return {
        "video": str(t.get("video") or ""),
        "title": str(t.get("title") or ""),
        "desc": str(t.get("desc") or ""),
        "tags": tags,
        "zone": str(t.get("zone") or ""),
        "topic": str(t.get("topic") or ""),
    }


# ---------------------------------------------------------------------- #
# 声明式投稿管线（仿 MAA tasks.json）
# ---------------------------------------------------------------------- #
def _node(algorithm="None", action="None", **kw):
    d = {"algorithm": algorithm, "action": action}
    d.update(kw)
    return d


def build_pipeline(task=None, upload_wait_seconds=None):
    """构造投稿管线（dict）。任务字段以 `{{变量}}` 注入，便于界面直接展示。

    节点名与阶段文案见 `STAGES`。标签/话题按个数动态展开成「输入 → 回车」
    节点，保证每个标签都被 B 站标签框单独接纳。
    """
    t = {**default_task(), **(task or {})}
    v = default_vars(t)
    wait_s = int(upload_wait_seconds or UPLOAD_WAIT_SECONDS)
    tries_upload = max(5, wait_s)

    p = {
        "_说明": ("B 站自动投稿管线：Activate → 上传 → 填表 → 分区 → 封面 → "
                  "声明 → 提交。模板来自 data/auto_vision/bili/。"),
        "Activate": _node("None", "Activate",
                          note="把浏览器窗口提到前台（真点前必须先激活）",
                          next=["CheckPage"], maxTimes=1),
        "CheckPage": _node("TemplateMatch", "Log",
                           template="01_upload_entry.png", threshold=0.75,
                           note="确认当前就在投稿页（能看到「上传视频」入口）",
                           next=["UploadEntry"], exceededNext=["FailNoPage"],
                           maxTimes=2),
        "UploadEntry": _node("TemplateMatch", "ClickSelf",
                             template="01_upload_entry.png", threshold=0.75,
                             note="点「上传视频」→ 弹出系统文件对话框",
                             next=["WaitDialog"], postDelay=900, maxTimes=2),
        "WaitDialog": _node("None", "Wait", wait=1200,
                            note="等文件对话框出现（它自己会成为前台窗口）",
                            next=["ClearPath"], maxTimes=1),
        "ClearPath": _node("None", "Key", keys="ctrl+a",
                           note="清空文件名输入框",
                           next=["TypePath"], maxTimes=1),
        "TypePath": _node("None", "TypeText", text="{{video}}", method="paste",
                          note="粘贴视频文件完整路径",
                          next=["ConfirmPath"], maxTimes=1),
        "ConfirmPath": _node("None", "Key", keys="enter",
                             note="回车确认 → 开始上传",
                             next=["WaitUploaded"], maxTimes=1),
        "WaitUploaded": _node("TemplateMatch", "Log",
                              template="02_upload_done.png", threshold=0.75,
                              preDelay=1000, maxTimes=tries_upload,
                              note="等上传/转码完成（大文件较慢）",
                              next=["FillTitle"], exceededNext=["FailUpload"]),
        "FillTitle": _node("TemplateMatch", "ClickSelf",
                           template="03_title_input.png", threshold=0.75,
                           note="点标题输入框",
                           next=["ClearTitle"], postDelay=250, maxTimes=3),
        "ClearTitle": _node("None", "Key", keys="ctrl+a",
                            note="清空标题框（可能是自动填的稿件名）",
                            next=["TypeTitle"], maxTimes=1),
        "TypeTitle": _node("None", "TypeText", text="{{title}}", method="paste",
                           note="输入标题",
                           next=["FillDesc"], maxTimes=1),
        "FillDesc": _node("TemplateMatch", "ClickSelf",
                          template="04_desc_input.png", threshold=0.75,
                          note="点简介输入区",
                          next=["TypeDesc"], postDelay=250,
                          exceededNext=["FillTags"], maxTimes=2),
        "TypeDesc": _node("None", "TypeText", text="{{desc}}", method="paste",
                          note="输入简介",
                          next=["FillTags"], maxTimes=1),
        "FillTags": _node("TemplateMatch", "ClickSelf",
                          template="05_tags_input.png", threshold=0.75,
                          note="点标签输入框",
                          next=["__TAGS__"], postDelay=250, maxTimes=3),
    }

    # —— 标签：每个标签「输入 → 回车」一对节点 ——
    tag_chain = []
    tags = v["tags"] or []
    for i, tag in enumerate(tags):
        tname = f"Tag{i + 1}"
        ename = f"Tag{i + 1}Enter"
        p[tname] = _node("None", "TypeText", text=str(tag), method="paste",
                         note=f"输入标签「{tag}」",
                         next=[ename], maxTimes=1)
        p[ename] = _node("None", "Key", keys="enter",
                         note=f"回车添加标签「{tag}」",
                         next=["__AFTER_TAGS__"], maxTimes=1)
        tag_chain.append(tname)

    after_tags = ["FillTopic"] if v["topic"] else ["PickZone"]
    if tags:
        p["FillTags"]["next"] = [tag_chain[0]]
        for i, tname in enumerate(tag_chain):
            ename = f"Tag{i + 1}Enter"
            p[ename]["next"] = ([tag_chain[i + 1]] if i + 1 < len(tag_chain)
                                else after_tags)
    else:
        p["FillTags"]["next"] = after_tags

    # —— 参与话题（可选）——
    p["FillTopic"] = _node("TemplateMatch", "ClickSelf",
                           template="06_topic_input.png", threshold=0.75,
                           note="点参与话题输入框",
                           next=["TypeTopic"], postDelay=250,
                           exceededNext=["PickZone"], maxTimes=2)
    p["TypeTopic"] = _node("None", "TypeText", text="{{topic}}",
                           method="paste", note="输入话题",
                           next=["ConfirmTopic"], maxTimes=1)
    p["ConfirmTopic"] = _node("None", "Key", keys="enter",
                              note="回车确认话题",
                              next=["PickZone"], maxTimes=1)

    # —— 分区：点开 → 搜索 → 点第一条结果 ——
    p["PickZone"] = _node("TemplateMatch", "ClickSelf",
                          template="07_zone_open.png", threshold=0.75,
                          note="点开分区选择面板",
                          next=["ZoneSearch"], postDelay=500,
                          exceededNext=["SkipZone"], maxTimes=2)
    p["ZoneSearch"] = _node("TemplateMatch", "ClickSelf",
                            template="08_zone_search.png", threshold=0.75,
                            note="点分区搜索框",
                            next=["TypeZone"], postDelay=200,
                            exceededNext=["FailZone"], maxTimes=3)
    p["TypeZone"] = _node("None", "TypeText", text="{{zone}}",
                          method="paste", note="输入分区名",
                          next=["WaitZoneResult"], maxTimes=1)
    p["WaitZoneResult"] = _node("TemplateMatch", "Log",
                                template="09_zone_first.png", threshold=0.72,
                                preDelay=500, maxTimes=8,
                                note="等搜索结果出现",
                                next=["ClickZone"], exceededNext=["FailZone"])
    p["ClickZone"] = _node("TemplateMatch", "ClickSelf",
                           template="09_zone_first.png", threshold=0.72,
                           note="点搜索结果第一条",
                           next=["PickCover"], postDelay=400, maxTimes=2)
    p["SkipZone"] = _node("None", "Log",
                          note="⚠ 没找到分区按钮：沿用页面默认分区，继续",
                          next=["PickCover"], maxTimes=1)

    # —— 封面（可选）——
    p["PickCover"] = _node("TemplateMatch", "ClickSelf",
                           template="10_cover_first.png", threshold=0.72,
                           note="选第一张候选封面",
                           next=["Declare"], postDelay=300,
                           exceededNext=["Declare"], maxTimes=3)

    # —— 创作声明（可选）——
    p["Declare"] = _node("TemplateMatch", "ClickSelf",
                         template="11_declaration_self.png", threshold=0.75,
                         note="创作声明选「自制」",
                         next=["Submit"], postDelay=250,
                         exceededNext=["Submit"], maxTimes=2)

    # —— 提交 / 等结果 ——
    p["Submit"] = _node("TemplateMatch", "ClickSelf",
                        template="12_submit_button.png", threshold=0.75,
                        note="点「立即投稿」",
                        next=["WaitSuccess"], postDelay=800, maxTimes=3)
    p["WaitSuccess"] = _node("TemplateMatch", "Log",
                             template="13_submit_success.png", threshold=0.72,
                             preDelay=1000, maxTimes=20,
                             note="等投稿成功标志",
                             next=["Done"], exceededNext=["FailSubmit"])

    # —— 终点 ——
    p["Done"] = _node("None", "Log", note="✅ 投稿流程完成", next=[], maxTimes=1)
    p["FailNoPage"] = _node("None", "Log",
                            note="❌ 没找到上传入口：请确认浏览器已打开投稿页且已登录",
                            next=[], maxTimes=1)
    p["FailUpload"] = _node("None", "Log",
                            note="❌ 等待上传完成超时：检查网络/文件大小，或调大等待上限",
                            next=[], maxTimes=1)
    p["FailZone"] = _node("None", "Log",
                          note="❌ 分区搜索无结果：核对分区名，或手动在页面选择",
                          next=[], maxTimes=1)
    p["FailSubmit"] = _node("None", "Log",
                            note="❌ 未检测到投稿成功：请人工到浏览器确认",
                            next=[], maxTimes=1)

    # 只填不提交：把 Submit 换成停手节点
    if not t.get("submit", True):
        p["Submit"] = _node("None", "Log",
                            note="（演练/预览）表单已填完，未点击「立即投稿」",
                            next=["Done"], maxTimes=1)
        p["WaitSuccess"] = _node("None", "Log", note="跳过提交结果等待",
                                 next=[], maxTimes=1)
    return p


#: 节点 → 阶段文案（界面进度展示用）
STAGES = {
    "Activate": "激活浏览器窗口",
    "CheckPage": "确认投稿页",
    "UploadEntry": "打开文件选择",
    "WaitDialog": "等待文件对话框",
    "TypePath": "填写视频路径",
    "WaitUploaded": "等待上传/转码",
    "FillTitle": "填写标题",
    "FillDesc": "填写简介",
    "FillTags": "填写标签",
    "FillTopic": "填写话题",
    "PickZone": "选择分区",
    "PickCover": "选择封面",
    "Declare": "创作声明",
    "Submit": "提交投稿",
    "WaitSuccess": "等待投稿结果",
    "Done": "完成",
}

#: 失败终点节点名
FAIL_NODES = ("FailNoPage", "FailUpload", "FailZone", "FailSubmit")


def pipeline_text(task=None):
    """给界面展示的管线 JSON 文本。"""
    return json.dumps(build_pipeline(task), ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------- #
# 分区 / 话题检测（AI 视觉枚举，对应历史 R4）
# ---------------------------------------------------------------------- #
ZONE_INSTRUCTION = (
    "这是 B 站投稿页。请列出当前画面上「分区」选择面板里可见的全部分区名称。"
    "只照抄分区名本身（如「游戏」「动画」「知识」），不要包含「请选择」「确定」"
    "「取消」「搜索」等按钮或说明文字。")
TOPIC_INSTRUCTION = (
    "这是 B 站投稿页。请列出「参与话题」区域当前可见的全部话题标签文字。"
    "照抄原文（可保留 # 号），不要包含「参与话题」这个栏目标题本身，也不要包含"
    "按钮或说明文字。")

_LIST_PROMPT = """你是浏览器自动化助手。这是一张窗口截图。
{instruction}

只返回严格 JSON（不要任何其他文字）：
{{"options": ["选项1", "选项2", ...], "end": true或false}}
options：把画面里{scope}当前可见的全部选项原样照抄（保持原文，不要翻译、
不要补充你猜测的项）；end：列表是否已经滚到底（下方没有更多了）。"""


def _ai_module():
    """取工具箱的 AI 客户端模块（按路径加载，见 video_toolbox.ai_mod）。"""
    try:
        import video_toolbox as engine
        return engine.ai_mod()
    except Exception:  # noqa: BLE001
        return None


def ai_available():
    """AI 视觉通道是否可用（分区/话题检测依赖它）。"""
    mod = _ai_module()
    try:
        return bool(mod and mod.is_enabled())
    except Exception:  # noqa: BLE001
        return False


def vision_list_options(win, instruction, *, scope="该列表中",
                        max_tokens=3000):
    """抓 `win` 当前帧 → 交给视觉模型列出可见选项。

    返回 `{"options": [...], "end": bool}`；AI 不可用/解析失败时抛 RuntimeError
    （调用方决定是否降级）。
    """
    mod = _ai_module()
    if not ai_available():
        raise RuntimeError("AI 视觉通道未启用：请到「设置 → 全局 AI」填写密钥")
    frame, _origin, _cost = av.capture_window(win)
    if frame is None:
        raise RuntimeError("抓帧失败")
    buf = io.BytesIO()
    Image.fromarray(frame).save(buf, format="PNG")
    raw = mod.get_client().chat_vision(
        _LIST_PROMPT.format(instruction=instruction, scope=scope),
        [buf.getvalue()], max_tokens=max_tokens)
    data = mod.try_parse_json(raw)
    if not isinstance(data, dict):
        raise RuntimeError(f"视觉返回不是合法 JSON: {str(raw)[:120]}")
    opts = data.get("options")
    if not isinstance(opts, list):
        opts = []
    return {"options": [str(o).strip() for o in opts if str(o).strip()],
            "end": bool(data.get("end"))}


def detect_zone_options(win):
    """检测分区面板里的分区名列表（请先在页面上把分区面板点开）。"""
    return vision_list_options(win, ZONE_INSTRUCTION, scope="分区面板里")


def detect_topic_options(win):
    """检测「参与话题」区域可见的话题列表。"""
    return vision_list_options(win, TOPIC_INSTRUCTION, scope="话题区域里")


def match_zone_name(target, names):
    """把目标分区名匹配到现场列表里的精确名（NFKC + 去空白 + 双向包含）。

    对齐历史 `catalog.match_zone_name`：B 站分区都是短名，双向包含已够用。
    """
    import unicodedata

    def _norm(s):
        return "".join(
            unicodedata.normalize("NFKC", str(s or "")).split()).casefold()

    t = _norm(target)
    if not t:
        return None
    for n in names or []:
        if _norm(n) == t:
            return n
    for n in names or []:
        nn = _norm(n)
        if nn and (t in nn or nn in t):
            return n
    return None


# ---------------------------------------------------------------------- #
# 编排：跑一次完整投稿
# ---------------------------------------------------------------------- #
def frame_provider(win):
    """给 PipelineRunner 用的抓帧回调（每步重新抓一帧）。"""
    try:
        return av.capture_window(win)
    except Exception:  # noqa: BLE001
        return (None, (0, 0), 0.0)


def run_submission(*, task, win, dry_run=True, data_dir,
                   on_log=None, on_stage=None, template_dir_override=None,
                   screenshot_on_fail=True):
    """跑一次完整投稿流程。

    :param task: 投稿任务（见 `default_task`）
    :param win: 目标 `av.WindowInfo`（用户浏览器窗口）
    :param dry_run: True 只识别不真点（演练）；False 真点真打字
    :param data_dir: 工具箱数据目录（定位模板与失败截图）
    :param on_log: 日志回调 on_log(str)
    :param on_stage: 阶段回调 on_stage(node_name, label)
    :param template_dir_override: 覆盖模板目录（默认 data/auto_vision/bili）
    :returns: dict(ok, reached, failed_at, steps, screenshot, missing)
    """
    log = on_log or (lambda *_a: None)
    tdir = template_dir_override or template_dir(data_dir)

    missing = missing_templates(data_dir)
    if missing:
        log("⚠ 缺少模板：" + "、".join(m["label"] for m in missing))
        log("  → 请先在「采集模板」里把这几张截出来，否则对应步骤会走熔断分支")

    def _on_stage(node_name):
        """节点 → 阶段文案（界面进度展示）；异常只忽略，不打断投稿。"""
        if on_stage is None:
            return
        try:
            on_stage(node_name, STAGES.get(node_name, node_name))
        except Exception:  # noqa: BLE001
            pass

    pipeline = build_pipeline(task)
    vars_ = default_vars(task)
    runner = av.PipelineRunner(frame_provider, tdir, on_log=log, vars=vars_,
                               on_stage=_on_stage)

    log(f"投稿任务：视频={vars_['video'] or '(未填)'}｜标题={vars_['title'] or '(未填)'}"
        f"｜标签={len(vars_['tags'])} 个｜分区={vars_['zone'] or '(未填)'}"
        f"｜话题={vars_['topic'] or '(无)'}｜提交={task.get('submit', True)}")

    trace = runner.run(pipeline, win=win, dry_run=dry_run)

    reached = [r.node.name for r in trace if r.hit]
    failed_at = next((r.node.name for r in trace
                      if r.node.name in FAIL_NODES and r.hit), None)
    ok = ("Done" in reached) and failed_at is None

    shot = None
    if not ok and screenshot_on_fail:
        frame = av.grab_screen()
        if frame is not None:
            sdir = screenshot_dir(data_dir)
            name = time.strftime("%Y%m%d_%H%M%S") + \
                f"_{failed_at or 'incomplete'}.png"
            shot = av.save_frame(frame, os.path.join(sdir, name))
            if shot:
                log(f"已保存失败截图：{shot}")

    return {"ok": ok, "reached": reached, "failed_at": failed_at,
            "steps": trace, "screenshot": shot, "missing": missing}
