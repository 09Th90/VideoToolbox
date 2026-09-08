# -*- coding: utf-8 -*-
"""视频工具箱内置「B 站自动投稿」引擎的配置（完全自包含版）。

由 tools/uploader_src/config.py 提供，被 modules/* 以 `import config` 方式引用。
所有路径锚定到工具箱 tools 目录（登录态/日志/任务均在工具箱内），
不依赖任何外部投稿程序；浏览器用内嵌 playwright + 内嵌 chromium
（tools\\ms-playwright，缺失时回退本机 Chrome/Edge）。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# 路径常量（全部锚定到工具箱内）
# ---------------------------------------------------------------------------
# TOOLS_DIR：打包后锚定 exe 同目录 tools；源码模式锚定脚本同目录 tools。
if getattr(sys, "frozen", False):
    TOOLS_DIR = Path(sys.executable).resolve().parent / "tools"
else:
    TOOLS_DIR = Path(__file__).resolve().parent.parent

# v1.7 按功能分目录：程序根 = tools 的上级；用户数据归 data，日志归 logs
APP_DIR = TOOLS_DIR.parent
DATA_DIR = APP_DIR / "data"
LOGS_ROOT = APP_DIR / "logs"

SRC_DIR = Path(__file__).resolve().parent            # tools/uploader_src
PROFILE_DIR = DATA_DIR / "uploader_profile"          # B站登录态（首次扫码）
LOGS_DIR = LOGS_ROOT / "uploader"
SCREENSHOT_DIR = LOGS_DIR / "screenshots"
TASKS_DIR = DATA_DIR / "uploader_tasks"
CATALOG_DIR = DATA_DIR / "catalog"                    # 分区/话题检测缓存


def _migrate_legacy_dirs() -> None:
    """把 v1.6 以前落在 tools 下的用户数据迁移到 data/logs（幂等）。"""
    legacy = [
        (TOOLS_DIR / "uploader_profile", PROFILE_DIR),
        (TOOLS_DIR / "uploader_tasks", TASKS_DIR),
        (TOOLS_DIR / "uploader_logs", LOGS_DIR),
    ]
    for old, new in legacy:
        try:
            if old.exists() and not new.exists():
                new.parent.mkdir(parents=True, exist_ok=True)
                old.rename(new)
        except OSError:
            pass


_migrate_legacy_dirs()
for _d in (DATA_DIR, LOGS_ROOT, PROFILE_DIR, LOGS_DIR, SCREENSHOT_DIR,
           TASKS_DIR, CATALOG_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# 浏览器内核查找顺序：工具箱内嵌 tools\\ms-playwright（自包含分发）
# → 用户显式设置的 PLAYWRIGHT_BROWSERS_PATH → 全局 %LOCALAPPDATA%\\ms-playwright
# → 都找不到时由 modules/browser.py 回退本机 Chrome/Edge。
_EMBEDDED_BROWSERS = TOOLS_DIR / "ms-playwright"
if os.environ.get("PLAYWRIGHT_BROWSERS_PATH"):
    pass  # 用户显式指定，最优先
elif _EMBEDDED_BROWSERS.is_dir() and any(
        p.name.startswith("chromium-") for p in _EMBEDDED_BROWSERS.iterdir()):
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(_EMBEDDED_BROWSERS)
else:
    _pw = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "ms-playwright"
    if _pw.is_dir():
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(_pw)

# ---------------------------------------------------------------------------
# 1. 浏览器启动与反检测配置
# ---------------------------------------------------------------------------
BROWSER_CONFIG: dict[str, Any] = {
    "user_data_dir": str(PROFILE_DIR),
    "channel": None,               # None=playwright 自带 chromium；可改 "chrome" 用本机正式版
    "headless": False,
    "viewport": {"width": 1920, "height": 1080},
    "device_scale_factor": 1,
    "locale": "zh-CN",
    "timezone_id": "Asia/Shanghai",
    "args": [
        "--window-size=1920,1080",
        "--force-device-scale-factor=1",
        "--disable-blink-features=AutomationControlled",
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-background-networking",
        "--disable-features=IsolateOrigins,site-per-process",
    ],
}

UPLOAD_URL = "https://member.bilibili.com/platform/upload/video"
LOGIN_URL_KEYWORDS = ("passport.bilibili.com", "login")

# ---------------------------------------------------------------------------
# 2. 投稿内容（由工具箱 GUI 以任务 JSON / apply 方式覆盖）
# ---------------------------------------------------------------------------
UPLOAD_TASK: dict[str, Any] = {
    "video_path": "",
    "title": "",
    "description": "",
    "tags": [],
    "declaration": "",
    "topics": [],
    "zone": "游戏",
    "collection": "",           # 加入合集（空=不加入）
    "subtitle": "",             # 同步上传的原始字幕 .srt（空=不上传）
    "subtitle_lang": "英语",    # 字幕语言
    "auto_select_cover": True,
    "use_recommended": True,
    "submit": False,
}

# ---------------------------------------------------------------------------
# 3. 智能表单字段配置（与原投稿系统一致）
# ---------------------------------------------------------------------------
FIELD_CONFIG: dict[str, dict[str, Any]] = {
    "title": {
        "keywords": ["视频标题", "稿件标题", "标题"],
        "value": UPLOAD_TASK["title"],
        "type": "text",
        "max_length": 80,
        "selector": "input.input-container",
        "placeholder_keywords": ["标题"],
    },
    "description": {
        "keywords": ["视频简介", "稿件简介", "简介", "描述"],
        "value": UPLOAD_TASK["description"],
        "type": "textarea",
        "selector": ".ql-editor, textarea[placeholder*='简介']",
        "placeholder_keywords": ["简介"],
    },
    "declaration": {
        "keywords": ["创作声明"],
        "value": UPLOAD_TASK["declaration"],
        "type": "select",
        "selector": "",
        "optional": True,
    },
    "zone": {
        "keywords": ["分区", "栏目"],
        "value": UPLOAD_TASK["zone"],
        "type": "select",
        "selector": ".category-container, .select-item-cont",
    },
    "collection": {
        "keywords": ["加入合集", "选择合集", "合集", "系列"],
        "value": UPLOAD_TASK["collection"],
        "type": "select",
        "selector": "",
        "optional": True,
    },
    "subtitle": {
        "keywords": ["字幕"],
        "value": UPLOAD_TASK["subtitle"],
        "lang": UPLOAD_TASK["subtitle_lang"],
        "type": "subtitle",
    },
    "tags": {
        "keywords": ["视频标签", "稿件标签", "标签", "话题"],
        "value": UPLOAD_TASK["tags"],
        "type": "tags",
        "selector": ".tag-container input, .input-tag input",
        "placeholder_keywords": ["标签", "回车"],
    },
    "topics": {
        "keywords": ["参与话题"],
        "value": UPLOAD_TASK["topics"],
        "type": "topics",
    },
}

DECLARATION_PRESETS: list[str] = [
    "该视频使用人工智能合成技术",
    "无需标注",
    "含有虚构演绎内容",
    "内容为个人观点，仅供参考",
    "视频内含有危险动作，请勿模仿",
    "请理性适度消费",
]

FIELD_ORDER: list[str] = ["title", "declaration", "zone", "description",
                          "collection", "tags", "topics", "subtitle"]

# ---------------------------------------------------------------------------
# 4. 时序 / 超时参数
# ---------------------------------------------------------------------------
TIMING: dict[str, float] = {
    "type_delay_ms": 30,
    "after_click_delay": 0.15,
    "after_field_filled": 0.25,
    "tag_enter_wait": 0.3,
    "human_jitter_min": 0.15,
    "human_jitter_max": 0.5,
    "dry_run_hold": 30.0,
}

TIMEOUT: dict[str, float] = {
    "page_goto": 60.0,
    "login_wait": 180.0,
    "upload_complete": 1800.0,
    "field_locate": 10.0,
    "submit_enabled": 300.0,
    "submit_success": 60.0,
}

UPLOAD_READY_SELECTORS: list[str] = [
    ".video-jam",
    ".cover-v2",
    ".cover-list .cover-item",
    "input.input-container",
]
UPLOAD_BUSY_KEYWORDS: list[str] = ["上传中", "上传进度", "正在上传"]

SUBMIT_SELECTORS: list[str] = [
    ".submit-add",
    "button.submit-btn",
    "button:has-text('立即投稿')",
]

TAG_ITEM_SELECTORS: list[str] = [".tag-item", ".tag-container .tag", "span.tag"]
TAG_INPUT_SELECTORS: list[str] = [
    ".tag-container input",
    ".input-tag input",
    "input[placeholder*='标签']",
]

COVER_ITEM_SELECTORS: list[str] = [".cover-list .cover-item", ".cover-item"]

# ---------------------------------------------------------------------------
# 5. 字幕同步上传（B 站 CC 字幕区）
# ---------------------------------------------------------------------------
SUBTITLE_INPUT_SELECTORS: list[str] = [
    'input[type="file"][accept*="srt"]',
    'input[type="file"][accept*="ass"]',
    'input[type="file"][accept*="vtt"]',
    'input[type="file"][accept*="subtitle"]',
    'input[type="file"][accept*="caption"]',
]
SUBTITLE_SECTION_KEYWORDS: list[str] = ["字幕"]
SUBTITLE_LANG: str = "英语"

# ---------------------------------------------------------------------------
# 6. 任务 JSON 加载 / 覆盖
# ---------------------------------------------------------------------------
def load_task_file(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    with p.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"任务文件格式错误，根节点应为对象: {p}")
    apply_task_dict(data)
    return UPLOAD_TASK


def apply_task_dict(data: dict[str, Any]) -> dict[str, Any]:
    for key in ("video_path", "title", "description", "tags", "zone",
                "declaration", "topics", "collection", "subtitle",
                "subtitle_lang", "use_recommended",
                "auto_select_cover", "submit"):
        if key in data:
            UPLOAD_TASK[key] = data[key]
    field_value_map = {
        "title": "title", "description": "description", "tags": "tags",
        "zone": "zone", "declaration": "declaration", "topics": "topics",
        "collection": "collection", "subtitle": "subtitle",
    }
    for task_key, field_key in field_value_map.items():
        if task_key in data and field_key in FIELD_CONFIG:
            FIELD_CONFIG[field_key]["value"] = data[task_key]
    if "subtitle_lang" in data:
        FIELD_CONFIG["subtitle"]["lang"] = data["subtitle_lang"]
    return UPLOAD_TASK


def apply_cli_overrides(**overrides: Any) -> dict[str, Any]:
    for key, value in overrides.items():
        if value is None:
            continue
        UPLOAD_TASK[key] = value
        if key in ("title", "description", "tags", "zone", "declaration", "topics") \
                and key in FIELD_CONFIG:
            FIELD_CONFIG[key]["value"] = value
        elif key == "collection" and key in FIELD_CONFIG:
            FIELD_CONFIG[key]["value"] = value
        elif key == "subtitle" and key in FIELD_CONFIG:
            FIELD_CONFIG[key]["value"] = value
        elif key == "subtitle_lang" and "subtitle" in FIELD_CONFIG:
            FIELD_CONFIG["subtitle"]["lang"] = value
    return UPLOAD_TASK
