# -*- coding: utf-8 -*-
"""
模块：B 站投稿「分区 / 话题 / 合集」自动检测（v1.9.2 脚本为主通道）。

能力：
1. fetch_areas：抓取投稿页分区下拉的全部选项。
   必须先上传视频（B 站上传视频后才进入可填写的投稿区，用户实测）。
   主通道（v1.9.2，对应用户要求：使用脚本）：DOM 脚本定位「分区」下拉 →
   点击展开 → 页面内枚举选项 → 滚轮翻页补全 → 去重合并；
   AI 屏幕识别（逐屏截图读选项）保留为兜底通道，AI 未启用不影响脚本通道。
2. fetch_topics_for_zone：上传视频并选中分区后，枚举「参与话题」区
   当前可选的全部话题 chip（话题随分区变化，必须选中分区后读取）。
   同样 DOM 脚本为主、AI 屏幕识别兜底。
3. fetch_collections：检测当前登录账号的全部合集（系列），
   主通道为创作中心 seasons 接口，兜底为上传视频后枚举「合集」下拉。

结果统一为可 JSON 序列化结构，并由 uploader_runner 落盘到 data\\catalog 缓存，
GUI 读取缓存填充分区下拉 / 合集下拉 / 话题多选列表，投稿时仍由 form_engine
按名称点击，因此本模块只负责“检测/枚举”，不改变既有投稿填写链路。
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import config
from modules.browser import BrowserSession, human_click
from modules.form_engine import (
    ZONE_PANEL_DESC,
    ZONE_TRIGGER_DESC,
    _LIST_OPTIONS_JS,
    _VISIBLE_HELPER,
    _open_dropdown,
)

logger = logging.getLogger(__name__)

# 分区下拉浮层噪声词（排除“请选择/确定/搜索”等按钮与占位）
_AREA_NOISE = ("请选择", "取消", "确定", "关闭", "上传", "投稿", "标题", "简介",
               "标签", "搜索", "封面", "话题", "声明", "推荐", "活动", "分区",
               "一键分发", "定时发布")

_ZONE_LIST_INSTRUCTION = (
    "截图是B站投稿页已展开的「分区」下拉浮层。请列出浮层中当前可见的全部分区选项文字。"
    "只照抄分区名本身（如“动画”“游戏”“纪录片”），不要包含“请选择”“取消”“确定”"
    "“搜索”“共 X 个分区”等按钮或提示文字。")

_TOPICS_SECTION_DESC = "投稿页中的「参与话题」栏目标题或其下方的话题标签区域"

_TOPICS_LIST_INSTRUCTION = (
    "截图是B站投稿页的「参与话题」栏目。请列出该区域内当前可见的全部话题标签文字。"
    "照抄原文（可保留#号），不要包含栏目标题“参与话题”本身，也不要包含按钮或说明文字。")


# ---------------------------------------------------------------------------
# 分区名匹配：把任务里的分区名匹配到现场检测到的精确分区名（v1.9.1 投稿现场检测用）
# ---------------------------------------------------------------------------
def _norm_zone(s: str) -> str:
    """归一化分区名：NFKC 全角转半角 + 忽略大小写 + 去掉全部空白。"""
    import unicodedata
    return "".join(unicodedata.normalize("NFKC", str(s or "")).split()).casefold()


def match_zone_name(target: str, names: list) -> "str | None":
    """在现场检测到的分区名列表中匹配 target。

    依次尝试：归一化后完全相等 → 双向包含（“游戏”匹配“游戏/电子竞技”类名称
    或反之，实际B站分区均为短名，双向包含已覆盖输入不全的场景）。
    匹配成功返回列表中的原始精确名称（后续按它点击/校验），失败返回 None。
    """
    t = _norm_zone(target)
    if not t:
        return None
    normed = [(_norm_zone(n), n) for n in names if str(n or "").strip()]
    for norm_n, raw in normed:          # 1. 完全相等
        if norm_n == t:
            return raw
    for norm_n, raw in normed:          # 2. 双向包含，取最短命中（最具体）
        if (t in norm_n or norm_n in t):
            return raw
    return None


# ---------------------------------------------------------------------------
# 分区检测：DOM 脚本通道（v1.9.2 主通道）——打开下拉 → 页面内枚举 → 滚轮翻页
# ---------------------------------------------------------------------------
async def _fetch_areas_by_ui(page) -> list[dict]:
    """DOM 脚本枚举分区：打开「分区」下拉 → _LIST_OPTIONS_JS 逐屏枚举
    → 鼠标悬停浮层滚轮下翻补全 → 滤噪声去重 → Esc 收起。"""
    import asyncio

    field = config.FIELD_CONFIG["zone"]
    await _open_dropdown(page, "zone", field)
    await asyncio.sleep(0.5)   # 等浮层动画与列表渲染

    names: list[str] = []
    seen: set[str] = set()
    stale_rounds = 0
    for round_no in range(12):          # 12 屏硬上限，防失控
        opts = await page.evaluate(_LIST_OPTIONS_JS, {"maxLen": 8})
        fresh = 0
        for opt in opts:
            t = opt["text"].strip()
            if not t or t in seen or len(t) > 8:
                continue
            if any(n in t for n in _AREA_NOISE):
                continue
            seen.add(t)
            names.append(t)
            fresh += 1
        logger.info("分区浮层第 %d 屏枚举到 %d 个新选项（累计 %d）",
                    round_no + 1, fresh, len(names))
        if fresh == 0:
            stale_rounds += 1
            if stale_rounds >= 2:       # 连续两屏无新选项视为见底
                break
        else:
            stale_rounds = 0
        if not opts:
            break
        # 滚轮下翻浮层：鼠标悬停到浮层中部（取可见选项的平均横坐标/最低纵坐标）
        cx = sum(o["x"] for o in opts) / len(opts)
        cy = max(o["y"] for o in opts) - 20
        try:
            await page.mouse.move(cx, cy)
            await page.mouse.wheel(0, 400)
        except Exception as e:  # noqa: BLE001
            logger.debug("分区浮层滚动失败（按已枚举完成处理）: %s", e)
            break
        await asyncio.sleep(0.5)

    # 收起浮层（Esc 键，与人工操作一致）
    await page.keyboard.press("Escape")
    await asyncio.sleep(0.3)

    if not names:
        raise RuntimeError("DOM 脚本通道未从分区下拉枚举到任何选项")
    logger.info("DOM 脚本通道共枚举分区 %d 个: %s", len(names), names)
    return [{"name": n, "tid": None} for n in names]


# ---------------------------------------------------------------------------
# 分区检测：AI 屏幕识别兜底通道（DOM 失败时回退）
# ---------------------------------------------------------------------------
async def _fetch_areas_by_vision(page, agent) -> list[dict]:
    """AI 视觉通道：定位下拉 → 拟人点击展开 → 滚动逐屏识别 → 合并去重。

    :param agent: modules.vision_agent.VisionAgent
    """
    import asyncio

    # 1. 屏幕识别定位「分区」下拉触发器并点击展开（必要时随页面滚动查找）
    trigger = await agent.locate_or_fail(ZONE_TRIGGER_DESC,
                                         scroll_if_missing=True)
    await human_click(page, trigger["x"], trigger["y"])
    logger.info("AI 视觉已点击分区下拉触发器（%s）@ (%.0f, %.0f)",
                trigger.get("label") or "未命名", trigger["x"], trigger["y"])
    await asyncio.sleep(1.0)   # 等浮层动画与列表渲染

    # 2. 定位浮层面板作为滚动锚点；找不到就用触发器位置（浮层一般向下展开）
    try:
        panel = await agent.locate(ZONE_PANEL_DESC)
    except Exception:  # noqa: BLE001
        panel = None
    anchor_x, anchor_y = (panel or trigger)["x"], (panel or trigger)["y"]
    if panel:
        anchor_y = min(panel["y"] + 120, 1060)   # 在面板中部滚动，避开标题行

    # 3. 逐屏滚动 + 截图识别：AI 读出每屏可见选项，去重合并，直到见底
    names: list[str] = []
    seen: set[str] = set()
    stale_rounds = 0
    for round_no in range(40):          # 40 屏硬上限，防失控
        data = await agent.read_options(_ZONE_LIST_INSTRUCTION)
        fresh = 0
        for t in data["options"]:
            t = t.strip().strip("#").strip()
            if not t or t in seen:
                continue
            if any(n in t for n in _AREA_NOISE):
                continue
            if len(t) > 20:             # 分区名都很短，超长多为误读噪声
                continue
            seen.add(t)
            names.append(t)
            fresh += 1
        logger.info("分区浮层第 %d 屏识别到 %d 个新选项（累计 %d，end=%s）",
                    round_no + 1, fresh, len(names), data["end"])
        if data["end"]:
            break
        if fresh == 0:
            stale_rounds += 1
            if stale_rounds >= 2:       # 连续两屏无新选项视为见底
                break
        else:
            stale_rounds = 0
        await agent.scroll_at(anchor_x, anchor_y, agent.scroll_step)

    # 4. 收起浮层（Esc 键，与人工操作一致）
    await page.keyboard.press("Escape")
    await asyncio.sleep(0.3)

    if not names:
        raise RuntimeError("AI 视觉通道未从分区下拉识别到任何选项")
    logger.info("AI 视觉通道共识别分区 %d 个: %s", len(names), names)
    return [{"name": n, "tid": None} for n in names]


async def _enum_topics_by_vision(page, agent) -> list[str]:
    """屏幕识别枚举「参与话题」区当前可见话题 chip（页面滚动一轮后合并）。"""
    import asyncio

    try:
        await agent.locate(_TOPICS_SECTION_DESC, scroll_if_missing=True)
    except Exception as e:  # noqa: BLE001
        logger.warning("屏幕识别未定位到「参与话题」区域: %s", e)

    topics: list[str] = []
    seen: set[str] = set()
    for round_no in range(2):       # 当前屏 + 向下滚动一屏，覆盖话题区高度
        data = await agent.read_options(_TOPICS_LIST_INSTRUCTION)
        for t in data["options"]:
            t = t.strip().strip("#").strip()
            if not t or t in seen or len(t) > 24:
                continue
            if "参与话题" in t:
                continue
            seen.add(t)
            topics.append(t)
        if data["end"] or round_no == 1:
            break
        w, h = await agent.viewport_size()
        await agent.scroll_at(w / 2, h / 2, agent.scroll_step)
        await asyncio.sleep(0.3)
    logger.info("屏幕识别枚举到话题 %d 个: %s", len(topics), topics[:10])
    return topics


# ---------------------------------------------------------------------------
# 话题枚举：DOM 脚本通道（v1.9.2 主通道）
# ---------------------------------------------------------------------------
_ENUM_TOPICS_JS = _VISIBLE_HELPER + r"""
() => {
    // 1. 定位「参与话题」栏目标题（可见短文本）
    let labelEl = null;
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, null, false);
    let node;
    while ((node = walker.nextNode())) {
        const t = node.textContent.trim();
        if (t && t.includes('参与话题') && t.length <= 10) {
            const el = node.parentElement;
            if (agentVisible(el)) { labelEl = el; break; }
        }
    }
    if (!labelEl) return null;
    labelEl.scrollIntoView({ block: 'center' });

    // 2. 向上找容器：第一个包含 >=2 个短文本叶子（话题 chip）的祖先
    const leafTexts = (root) => {
        const out = [];
        root.querySelectorAll('div,span,a,p,button').forEach((el) => {
            if (!agentVisible(el)) return;
            const t = (el.innerText || '').trim();
            if (!t || t.length > 24 || t.includes('\n')) return;
            let childSame = false;
            for (const c of el.children) {
                if ((c.innerText || '').trim() === t) { childSame = true; break; }
            }
            if (!childSame) out.push(t);
        });
        return out;
    };
    let cur = labelEl;
    for (let depth = 0; depth < 6 && cur; depth++) {
        const chips = leafTexts(cur).filter((t) => !t.includes('参与话题'));
        if (chips.length >= 2) return chips;
        cur = cur.parentElement;
    }
    return [];
}
"""


async def _enum_topics_by_ui(page) -> list[str]:
    """DOM 脚本枚举「参与话题」区当前可见话题 chip。"""
    import asyncio

    result = await page.evaluate(_ENUM_TOPICS_JS)
    if result is None:
        raise RuntimeError("页面上未找到「参与话题」栏目")
    await asyncio.sleep(0.3)
    # scrollIntoView 后栏目位置变化，重新枚举一次拿到稳定结果
    result = await page.evaluate(_ENUM_TOPICS_JS)
    topics: list[str] = []
    seen: set[str] = set()
    for t in (result or []):
        t = str(t).strip().strip("#").strip()
        if not t or t in seen or len(t) > 24 or "参与话题" in t:
            continue
        seen.add(t)
        topics.append(t)
    logger.info("DOM 脚本枚举到话题 %d 个: %s", len(topics), topics[:10])
    return topics


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# 接口通道：合集列表（当前账号）
# ---------------------------------------------------------------------------
# 当前账号合集（系列）列表接口：创作中心 seasons，需登录 Cookie
COLLECTION_API_CANDIDATES = [
    "https://member.bilibili.com/x2/creative/web/seasons?pn=1&ps=50",
]

# 合集下拉噪声词（排除“创建合集/不加入合集”等操作项）
_COLLECTION_NOISE = ("请选择", "创建合集", "新建合集", "创建系列", "不加入合集",
                     "不加入", "取消", "确定", "关闭", "搜索", "合集", "系列")

async def _fetch_collections_by_api(page) -> list[str] | None:
    """通过创作中心 seasons 接口获取当前账号全部合集标题。"""
    for url in COLLECTION_API_CANDIDATES:
        try:
            resp = await page.evaluate(
                """async (u) => {
                    const r = await fetch(u, {credentials: 'include'});
                    return await r.text();
                }""", url)
            payload = json.loads(resp)
            if payload.get("code") not in (0, None):
                logger.info("合集接口 %s 返回 code=%s msg=%s",
                            url, payload.get("code"), payload.get("message"))
                continue
            data = payload.get("data") or {}
            seasons = data.get("seasons") or []
            names, seen = [], set()
            for item in seasons:
                if not isinstance(item, dict):
                    continue
                season = item.get("season") or {}
                title = str(season.get("title") or "").strip()
                if title and title not in seen:
                    seen.add(title)
                    names.append(title)
            if names:
                logger.info("合集接口命中 %s，共 %d 个合集", url, len(names))
                return names
        except Exception as e:  # noqa: BLE001
            logger.info("合集接口 %s 失败: %s", url, e)
    return None


# ---------------------------------------------------------------------------
# UI 通道：合集下拉
# ---------------------------------------------------------------------------
async def _fetch_collections_by_ui(page, video_path: str) -> list[str]:
    """UI 兜底：上传视频后打开「合集」下拉，枚举现有合集标题。"""
    import asyncio
    field = config.FIELD_CONFIG["collection"]
    try:
        await _open_dropdown(page, "collection", field)
    except RuntimeError as e:
        logger.warning("合集下拉打开失败（UI 兜底跳过）: %s", e)
        return []
    await asyncio.sleep(0.5)

    opts = await page.evaluate(_LIST_OPTIONS_JS, {"maxLen": 12})
    names, seen = [], set()
    for opt in opts:
        t = opt["text"]
        if any(n in t for n in _COLLECTION_NOISE) or t in seen:
            continue
        seen.add(t)
        names.append(t)
    await page.keyboard.press("Escape")
    logger.info("UI 通道枚举到合集 %d 个: %s", len(names), names[:10])
    return names


# ---------------------------------------------------------------------------
# 对外主流程
# ---------------------------------------------------------------------------
async def detect_live_areas(page, agent) -> list[dict]:
    """现场枚举当前投稿页分区下拉的全部选项（v1.9.2 投稿现场检测用）。

    页面需已处于「上传完视频、进入投稿区」的状态（由调用方保证）。
    DOM 脚本通道为主：打开分区浮层 → 页面内枚举 → 滚轮翻页 → 读完收起（Esc），
    不改变表单状态；脚本失败且有 AI 代理时回退屏幕识别逐屏读出。
    """
    try:
        return await _fetch_areas_by_ui(page)
    except Exception as e:  # noqa: BLE001
        if agent is not None:
            logger.warning("分区 DOM 枚举失败，回退 AI 屏幕识别: %s", e)
            return await _fetch_areas_by_vision(page, agent)
        raise


async def fetch_areas(*, video_path: str | None = None, session=None, page=None,
                      close_after=True, agent=None) -> list[dict]:
    """抓取投稿页分区下拉的全部选项。

    必须先上传视频：B 站上传视频后才进入可填写的投稿区（用户实测），
    因此本流程与话题检测一致，会上传视频但不会投稿。
    主通道为 DOM 脚本枚举（v1.9.2 起，用户要求使用脚本）；
    脚本失败且有 AI 代理时回退屏幕识别（定位下拉 → 点击展开 → 滚轮滚动 →
    逐屏识别选项）。

    :param agent: modules.vision_agent.VisionAgent（AI 屏幕识别兜底，可为 None）
    """
    own = session is None
    if own:
        session = BrowserSession()
        _, context = await session.start()
        page = context.pages[0] if context.pages else await context.new_page()

    from uploader_runner import ensure_logged_in, goto_upload_page
    from modules.uploader import upload_video
    try:
        if not video_path:
            raise RuntimeError(
                "分区检测必须先指定视频文件（--video）：B 站上传视频后才进入投稿区")
        if not Path(video_path).exists():
            raise FileNotFoundError(f"视频文件不存在: {video_path}")
        await goto_upload_page(page)
        await ensure_logged_in(page)
        logger.info("分区检测：先上传视频 %s", video_path)
        await upload_video(page, video_path)

        areas: list[dict] = []
        dom_err: Exception | None = None
        try:
            logger.info("分区检测通道：DOM 脚本枚举")
            areas = await _fetch_areas_by_ui(page)
        except Exception as e:  # noqa: BLE001
            dom_err = e
            logger.warning("分区 DOM 枚举失败: %s", e)
        if not areas and agent is not None:
            logger.info("回退 AI 屏幕识别通道枚举分区")
            try:
                areas = await _fetch_areas_by_vision(page, agent)
            except Exception as e:  # noqa: BLE001
                logger.warning("分区 AI 屏幕识别也失败: %s", e)
        if not areas:
            raise RuntimeError(
                f"分区列表获取失败：DOM 脚本与 AI 屏幕识别均未取到分区"
                f"（DOM 错误: {dom_err}）；请确认已登录、视频上传完成后重试")
        return areas
    finally:
        if own and close_after:
            await session.stop()


async def fetch_collections(*, video_path: str | None = None, session=None, page=None,
                            close_after=True) -> list[str]:
    """检测当前登录账号的全部合集（系列）标题。

    主通道为创作中心 seasons 接口（页面内 fetch 自动带登录 Cookie）；
    接口失败且提供视频时，回退为上传视频后枚举「合集」下拉。
    """
    own = session is None
    if own:
        session = BrowserSession()
        _, context = await session.start()
        page = context.pages[0] if context.pages else await context.new_page()

    from uploader_runner import ensure_logged_in, goto_upload_page
    try:
        await goto_upload_page(page)
        await ensure_logged_in(page)
        names = await _fetch_collections_by_api(page)
        if not names and video_path and Path(video_path).exists():
            from modules.uploader import upload_video
            logger.info("合集接口未取到，回退 UI 通道（需先上传视频）")
            await upload_video(page, video_path)
            names = await _fetch_collections_by_ui(page, video_path)
        if not names:
            raise RuntimeError("合集列表获取失败：接口与 UI 通道均未取到，"
                               "请确认已登录后重试")
        return names
    finally:
        if own and close_after:
            await session.stop()


async def fetch_topics_for_zone(zone_steps: list[str], video_path: str, *,
                                session=None, page=None,
                                close_after=True, agent=None) -> list[str]:
    """上传视频并选中分区后，枚举「参与话题」区当前可选话题。

    v1.9.2：DOM 脚本枚举为主通道，失败且有 AI 代理时回退屏幕识别。
    """
    import asyncio
    if not zone_steps:
        raise ValueError("必须指定分区（一级/二级）")
    own = session is None
    if own:
        session = BrowserSession()
        _, context = await session.start()
        page = context.pages[0] if context.pages else await context.new_page()

    from uploader_runner import ensure_logged_in, goto_upload_page
    from modules.uploader import upload_video
    from modules.form_engine import fill_select_field
    try:
        await goto_upload_page(page)
        await ensure_logged_in(page)
        logger.info("话题检测：上传视频 %s", video_path)
        await upload_video(page, video_path)

        field = config.FIELD_CONFIG["zone"]
        field["value"] = list(zone_steps)
        await fill_select_field(page, "zone", field, agent=agent)
        await asyncio.sleep(1.0)   # 等待话题区按分区刷新

        topics: list[str] = []
        try:
            topics = await _enum_topics_by_ui(page)
        except Exception as e:  # noqa: BLE001
            logger.warning("话题 DOM 枚举失败: %s", e)
        if not topics and agent is not None:
            logger.info("回退 AI 屏幕识别枚举话题")
            topics = await _enum_topics_by_vision(page, agent)
        if not topics and agent is None:
            raise RuntimeError(
                "话题枚举失败：DOM 脚本未取到话题且 AI 未启用"
                "（可检查 data\\ai_config.json 后重试，或确认该分区确无可选话题）")
        logger.info("分区 %s 下检测到话题 %d 个: %s",
                    "/".join(zone_steps), len(topics), topics[:10])
        return topics
    finally:
        if own and close_after:
            await session.stop()


def cache_path(kind: str, zone_steps: list[str] | None = None):
    """缓存文件路径：areas.json / collections.json / topics_<一级>.json"""
    config.CATALOG_DIR.mkdir(parents=True, exist_ok=True)
    if kind in ("areas", "collections"):
        return config.CATALOG_DIR / f"{kind}.json"
    name = "_".join(zone_steps or ["x"])
    for ch in '\\/:*?"<>|':
        name = name.replace(ch, "_")
    return config.CATALOG_DIR / f"topics_{name}.json"


def save_cache(kind: str, payload: dict, zone_steps=None) -> str:
    p = cache_path(kind, zone_steps)
    payload = dict(payload)
    payload["cached_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(p)
