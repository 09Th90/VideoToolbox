# -*- coding: utf-8 -*-
"""
模块三：智能表单填写引擎（开发书 3.3 / R3；v1.9 全量屏幕识别化）。

设计原则（v1.9，对应用户要求：不使用脚本操作页面，改为模拟鼠标点击/滚动
+ 屏幕识别完成）：
1. 简介（description）与分区（zone）只走「AI 屏幕识别」通道：截屏 → 全局 AI
   视觉定位 → 拟人鼠标点击/滚轮滚动 → 键盘逐字输入 → 再截图让 AI 读回校验；
   全程不注入任何页面脚本（不再调用 page.evaluate 定位这两类字段），
   AI 未启用时直接报错并提示检查 data\\ai_config.json，不再回退 DOM 通道。
2. 标题等其余字段保留 DOM 定位（快且稳定），失败且有 AI 代理时回退视觉通道。
3. 每次填写前重新定位，不缓存元素引用。
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from playwright.async_api import Page

import config
from modules.browser import human_click
from modules.tag_handler import fill_bilibili_tags, find_section_chip

logger = logging.getLogger(__name__)

# 各文本字段给 AI 的屏幕识别描述（v1.8）
_VISION_TARGETS: dict[str, str] = {
    "description": (
        "B站投稿表单中「简介」标签下方的多行简介输入框（placeholder 提示类似"
        "“填写更全面的相关信息，让更多人看到你的视频吧！”），是可输入多行文字的"
        "大输入区域；不是上方的单行「标题」输入框，也不是「标签」输入框"),
    "title": (
        "B站投稿表单中「标题」标签处的单行标题输入框（placeholder 提示类似"
        "“请输入稿件标题”或“填写标题”）"),
}

# 分区下拉触发器 / 浮层的 AI 屏幕识别描述（catalog 检测与投稿填写共用）
ZONE_TRIGGER_DESC = (
    "B站投稿表单里的「分区」下拉选择框触发器：通常显示为“请选择”或一个已选分区名，"
    "位于页面“基本信息”区域「分区」一行，右侧带下拉箭头。"
    "不要点“创作声明”“加入合集”“定时发布”等其他下拉或按钮。")
ZONE_PANEL_DESC = (
    "刚被点开的「分区」下拉选项浮层：一块列出多个分区名称（如 动画、游戏、音乐、"
    "知识、科技、娱乐…）的可滚动列表面板，通常出现在分区触发器正下方。")

# ---------------------------------------------------------------------------
# JS：可见性判定（页面内复用）
# ---------------------------------------------------------------------------
_VISIBLE_HELPER = r"""
const agentVisible = (el) => {
    if (!el) return false;
    const s = window.getComputedStyle(el);
    if (s.display === 'none' || s.visibility === 'hidden' || parseFloat(s.opacity) === 0) return false;
    const r = el.getBoundingClientRect();
    return r.width > 2 && r.height > 2;
};
"""

# ---------------------------------------------------------------------------
# JS：文本扫描器（开发书 3.3.1）+ 四级关联输入框定位（3.3.3）
# 入参 args = {anchor, labelKeywords, placeholderKeywords, preferSelector}
# 找到后给元素打 data-agent-anchor 锚点并返回定位信息；找不到返回 null
# ---------------------------------------------------------------------------
_LOCATE_JS = _VISIBLE_HELPER + r"""
(args) => {
    const { anchor, labelKeywords = [], placeholderKeywords = [], preferSelector = '' } = args;

    // 清掉上一轮同锚点标记，保证每次都是全新查询
    document.querySelectorAll('[data-agent-anchor]').forEach((n) => {
        if (n.getAttribute('data-agent-anchor') === anchor) n.removeAttribute('data-agent-anchor');
    });

    const mark = (el, strategy) => {
        el.setAttribute('data-agent-anchor', anchor);
        const r = el.getBoundingClientRect();
        return {
            strategy, tag: el.tagName, inputType: el.type || '',
            contentEditable: !!el.isContentEditable,
            x: r.x, y: r.y, w: r.width, h: r.height
        };
    };

    const editableSel = 'input:not([type=hidden]):not([type=file]):not([type=submit]):not([type=button]), '
                      + 'textarea, [contenteditable="true"], [contenteditable=""]';

    // 策略 0：配置中的精确 CSS 选择器（非坐标硬编码，仅作优先通道）
    if (preferSelector) {
        for (const sel of preferSelector.split(',')) {
            const el = document.querySelector(sel.trim());
            if (el && (agentVisible(el) || el.tagName === 'INPUT')) return mark(el, 'config-selector');
        }
    }

    // 扫描可见短文本节点，按关键词命中并打分
    const labelNodes = [];
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, null, false);
    let node;
    while ((node = walker.nextNode())) {
        const text = node.textContent.trim();
        if (!text || text.length > 15) continue;          // 长度过滤，降低噪声
        let bestKw = null;
        for (const kw of labelKeywords) {
            if (text.includes(kw)) { bestKw = kw; break; }
        }
        if (!bestKw) continue;
        const el = node.parentElement;
        if (!agentVisible(el)) continue;
        const r = el.getBoundingClientRect();
        let score;
        if (text === bestKw) score = 100 - text.length;           // 精确相等最优
        else if (text.startsWith(bestKw)) score = 60 - text.length;
        else score = 30 - text.length;
        labelNodes.push({ el, score, x: r.x, y: r.y });
    }
    labelNodes.sort((a, b) => b.score - a.score);

    // 策略 1：<label for="id"> 显式关联
    for (const item of labelNodes) {
        const lab = item.el.closest('label');
        if (lab && lab.htmlFor) {
            const target = document.getElementById(lab.htmlFor);
            if (target) return mark(target, 'label-for');
        }
    }

    // 策略 2：父容器递归（标签向上最多 4 层内查找输入控件）
    for (const item of labelNodes) {
        let cur = item.el;
        for (let depth = 0; depth < 4 && cur; depth++) {
            const cand = cur.querySelector(editableSel);
            if (cand && agentVisible(cand)) return mark(cand, 'ancestor-' + depth);
            cur = cur.parentElement;
        }
    }

    // 策略 3：placeholder 关键词匹配
    if (placeholderKeywords.length) {
        for (const el of document.querySelectorAll('input, textarea')) {
            const ph = el.getAttribute('placeholder') || '';
            if (ph && placeholderKeywords.some((k) => ph.includes(k)) && agentVisible(el)) {
                return mark(el, 'placeholder');
            }
        }
    }

    // 策略 4（兜底）：标签下方最近邻的可见输入框
    let best = null, bestDist = Infinity;
    for (const item of labelNodes) {
        document.querySelectorAll(editableSel).forEach((t) => {
            if (!agentVisible(t)) return;
            const r = t.getBoundingClientRect();
            const dy = r.y - item.y;
            if (dy < -10) return;                  // 必须位于标签下方（10px 容差）
            const dist = dy + Math.abs(r.x - item.x) * 0.3;
            if (dist < bestDist) { bestDist = dist; best = t; }
        });
        if (best) break;
    }
    if (best) return mark(best, 'nearest');

    return null;
}
"""

# 读回锚点元素当前值（input/textarea 取 value，富文本取 innerText）
_READ_VALUE_JS = r"""
(anchor) => {
    const el = document.querySelector('[data-agent-anchor="' + anchor + '"]');
    if (!el) return null;
    return el.isContentEditable ? (el.innerText || '') : (el.value || '');
}
"""

# 扫描浮层中可点击的文本项（自定义下拉用），返回中心坐标列表
_SCAN_CLICKABLE_JS = _VISIBLE_HELPER + r"""
(args) => {
    const { want, containsMode = false, maxLen = 10 } = args;
    const hits = [];
    const seen = new Set();
    document.querySelectorAll('div,span,li,a,p,button,dd,dt').forEach((el) => {
        if (!agentVisible(el)) return;
        const t = (el.innerText || '').trim();
        if (!t || t.length > maxLen) return;
        // 聚合容器文本常含换行，真实选项不会有
        if (t.includes('\n')) return;
        const ok = containsMode ? t.includes(want) : (t === want);
        if (!ok) return;
        // 叶子要求：存在文本同样匹配的子元素时说明点到了外层容器，跳过
        for (const c of el.children) {
            const ct = (c.innerText || '').trim();
            if (containsMode ? ct.includes(want) : ct === want) return;
        }
        const r = el.getBoundingClientRect();
        // 去重键用中心点：父子容器的左上角可能重合，中心点不会
        const key = Math.round(r.x + r.width / 2) + ',' + Math.round(r.y + r.height / 2);
        if (seen.has(key)) return;
        seen.add(key);
        hits.push({ x: r.x + r.width / 2, y: r.y + r.height / 2,
                    w: r.width, h: r.height, text: t });
    });
    return hits;
}
"""

# 按字段标签就近定位“自定义下拉触发器”（创作声明等无 input 的下拉组件用）：
# 标签下方找文本含“请选择”的占位元素，或 className 语义像下拉的元素。
_DROPDOWN_TRIGGER_JS = _VISIBLE_HELPER + r"""
(args) => {
    const { labelKeywords = [] } = args;

    // 1) 定位字段标签（可见短文本命中，取最靠前的一个）
    const labels = [];
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, null, false);
    let node;
    while ((node = walker.nextNode())) {
        const text = node.textContent.trim();
        if (!text || text.length > 15) continue;
        if (!labelKeywords.some((k) => text.includes(k))) continue;
        const el = node.parentElement;
        if (!agentVisible(el)) continue;
        const r = el.getBoundingClientRect();
        labels.push({ x: r.x, y: r.y });
    }
    if (!labels.length) return null;
    labels.sort((a, b) => a.y - b.y);
    const label = labels[0];

    // 2) 标签下方/同行找下拉触发器候选
    const cands = [];
    document.querySelectorAll('div,span').forEach((el) => {
        if (!agentVisible(el)) return;
        const t = (el.innerText || '').trim();
        if (!t || t.includes('\n') || t.length > 40) return;
        const cn = (el.className && el.className.toString()) || '';
        const placeholderHit = t.includes('请选择');
        const classHit = /(select|dropdown|cascader|picker|category|cate)/i.test(cn);
        if (!placeholderHit && !classHit) return;
        // 存在同样命中的子元素时，当前是外层容器，取子元素
        for (const c of el.children) {
            const ct = (c.innerText || '').trim();
            if (ct && ct.length <= 40 && ct.includes('请选择')) return;
        }
        const r = el.getBoundingClientRect();
        if (r.y < label.y - 6) return;            // 必须位于标签下方或同一行
        if (r.width < 40 || r.height < 18) return;
        cands.push({ x: r.x + r.width / 2, y: r.y + r.height / 2,
                     w: r.width, h: r.height, text: t });
    });
    if (!cands.length) return null;
    // 距标签垂直距离最近者优先
    cands.sort((a, b) => Math.abs(a.y - label.y) - Math.abs(b.y - label.y));
    const target = cands[0];
    // 滚动到视口中心后重取坐标，保证 CDP 点击落在视口内
    const el = document.elementFromPoint(target.x, target.y);
    if (el) {
        el.scrollIntoView({ block: 'center' });
        const r2 = el.getBoundingClientRect();
        return { x: r2.x + r2.width / 2, y: r2.y + r2.height / 2,
                 w: r2.width, h: r2.height, text: target.text };
    }
    return target;
}
"""


# 读取浮层中全部短文本项（用于遍历一级分类/自动选第一项），附带 className 供语义加权
_LIST_OPTIONS_JS = _VISIBLE_HELPER + r"""
(args) => {
    const maxLen = (args && args.maxLen) || 6;
    const out = [];
    const seen = new Set();
    document.querySelectorAll('div,span,li,a,p').forEach((el) => {
        if (!agentVisible(el)) return;
        const t = (el.innerText || '').trim();
        if (!t || t.length > maxLen) return;
        if (t.includes('\n')) return;   // 聚合容器文本含换行，不是可点选项
        let childSame = false;
        for (const c of el.children) {
            const ct = (c.innerText || '').trim();
            if (ct === t) { childSame = true; break; }
        }
        if (childSame) return;
        const r = el.getBoundingClientRect();
        // 去重键用中心点，避免父子容器左上角重合造成误去重
        const key = Math.round(r.x + r.width / 2) + ',' + Math.round(r.y + r.height / 2);
        if (seen.has(key)) return;
        seen.add(key);
        out.push({ x: r.x + r.width / 2, y: r.y + r.height / 2,
                   text: t, className: el.className || '' });
    });
    return out;
}
"""


# ---------------------------------------------------------------------------
# 文本 / 多行文本填写
# ---------------------------------------------------------------------------
async def _anchor_locator(page: Page, anchor: str):
    """每轮重新取锚点元素的最新 Locator（不缓存）。"""
    return page.locator(f'[data-agent-anchor="{anchor}"]').first


async def _fill_text_by_dom(page: Page, field_key: str, field: dict,
                            value: str) -> dict:
    """DOM 定位通道（旧主通道）：文本扫描定位 → 点击聚焦 → 键盘输入 → 读回校验。"""
    # 每轮重新扫描定位
    located = await page.evaluate(_LOCATE_JS, {
        "anchor": field_key,
        "labelKeywords": field.get("keywords", []),
        "placeholderKeywords": field.get("placeholder_keywords", []),
        "preferSelector": field.get("selector", ""),
    })
    if not located:
        raise RuntimeError(f"字段「{field_key}」未能通过任何策略定位到输入框")

    logger.info("字段「%s」定位成功，策略: %s（%s%s）",
                field_key, located["strategy"], located["tag"],
                "/contenteditable" if located["contentEditable"] else "")

    loc = await _anchor_locator(page, field_key)
    await loc.wait_for(state="visible",
                       timeout=int(config.TIMEOUT["field_locate"] * 1000))
    await loc.scroll_into_view_if_needed()
    # CDP 可信点击聚焦
    await loc.click()
    await asyncio.sleep(config.TIMING["after_click_delay"])

    # 全选清空残留（富文本内 Ctrl+A 仅选中编辑器内部内容）
    await page.keyboard.press("Control+a")
    await page.keyboard.press("Delete")
    await asyncio.sleep(0.08)

    # 逐字符输入：派发完整 keydown/keypress/input/keyup 序列，保证 React/Vue 状态同步
    await page.keyboard.type(value, delay=config.TIMING["type_delay_ms"])
    await asyncio.sleep(0.2)

    # 读回验证
    actual = await page.evaluate(_READ_VALUE_JS, field_key)
    ok = actual is not None and value.replace("\n", "").strip() in actual.replace("\n", "")
    if not ok:
        logger.warning("字段「%s」读回校验不一致，期望包含 %r，实际 %r",
                       field_key, value[:30], (actual or "")[:30])
    else:
        logger.info("字段「%s」填写完成并通过读回校验", field_key)

    await asyncio.sleep(config.TIMING["after_field_filled"])
    return {"ok": bool(ok), "strategy": located["strategy"], "actual": actual}


async def _fill_text_by_vision(page: Page, agent, field_key: str,
                               value: str) -> dict:
    """AI 屏幕识别通道（v1.8 主通道）：截屏定位 → 拟人点击 → 键盘输入 → AI 读回。

    不注入任何页面脚本；定位与校验都来自截图 + 全局 AI 视觉模型。
    """
    target = _VISION_TARGETS.get(
        field_key, f"投稿表单中「{field_key}」对应的输入框")

    # 简介（description）是 B 站富文本（contenteditable），定位 + 点击
    # 必须精确到输入区中心；同时先确保它滚到视口里
    box = await agent.locate_or_fail(target, scroll_if_missing=True)
    try:
        await page.mouse.move(box["x"], box["y"])
        await page.mouse.wheel(0, -300)
        await asyncio.sleep(0.2)
    except Exception:  # noqa: BLE001
        pass
    # 重新定位（页面可能因滚动改变位置）
    box = await agent.locate_or_fail(target, scroll_if_missing=False)
    await agent.click_point(box["x"], box["y"])
    await asyncio.sleep(config.TIMING["after_click_delay"])

    # 对 contenteditable：先点 1 次聚焦，再 click 三次选中全部内容（B 站编辑器
    # 接受这种习惯，行为与人工"三连击全选"一致），最后 Delete 清空
    if field_key == "description":
        try:
            # 双击或三击可全选（更接近真人行为）
            await page.mouse.dblclick(box["x"], box["y"])
            await asyncio.sleep(0.1)
        except Exception:  # noqa: BLE001
            pass
        await page.keyboard.press("Control+a")
    else:
        await page.keyboard.press("Control+a")
    await asyncio.sleep(0.05)
    await page.keyboard.press("Delete")
    await asyncio.sleep(0.1)

    # 逐字符输入：对 React 受控组件 + contenteditable 都更稳定
    # 多行内容：先 type 整段，type 会把 \n 转为 Enter（B 站编辑器支持）
    await page.keyboard.type(value, delay=config.TIMING["type_delay_ms"])
    await asyncio.sleep(0.3)

    head = value.strip().replace("\n", " ")[:60]
    label = "简介" if field_key == "description" else "标题"
    question = (
        f"页面「{label}」输入框内当前显示的文字是否以“{head}”开头"
        "（允许输入框只显示部分内容，允许换行、空格差异）；"
        "若输入框为空或内容明显不同，则不算")
    ok = False
    for attempt in (1, 2):
        try:
            res = await agent.verify(question)
        except Exception as e:  # noqa: BLE001
            logger.warning("字段「%s」AI 读回校验调用失败: %s", field_key, e)
            break
        ok = bool(res.get("ok"))
        logger.info("字段「%s」AI 读回校验（第 %d 次）: %s（%s）",
                    field_key, attempt, ok, res.get("detail"))
        if ok:
            break
        # 校验未通过：重新点击、清空、再输入一遍
        try:
            box = await agent.locate_or_fail(target, scroll_if_missing=True)
        except Exception:  # noqa: BLE001
            break
        await agent.click_point(box["x"], box["y"])
        await asyncio.sleep(config.TIMING["after_click_delay"])
        if field_key == "description":
            try:
                await page.mouse.dblclick(box["x"], box["y"])
                await asyncio.sleep(0.1)
            except Exception:  # noqa: BLE001
                pass
        await page.keyboard.press("Control+a")
        await asyncio.sleep(0.05)
        await page.keyboard.press("Delete")
        await asyncio.sleep(0.1)
        await page.keyboard.type(value, delay=config.TIMING["type_delay_ms"])
        await asyncio.sleep(0.3)

    await asyncio.sleep(config.TIMING["after_field_filled"])
    if not ok:
        logger.warning("字段「%s」AI 视觉填写后未能通过读回确认（请人工核对）", field_key)
    else:
        logger.info("字段「%s」AI 视觉通道填写完成", field_key)
    return {"ok": ok, "strategy": "ai-vision"}


async def fill_text_field(page: Page, field_key: str, field: dict,
                          agent=None) -> dict:
    """填写 text / textarea（含 contenteditable 富文本编辑器）。

    通道选择（v1.9.1）：
    - 全部字段优先走 DOM 通道（按 config 中配置的 selector 定位 + 键盘输入）；
    - DOM 失败且有 AI 代理时回退视觉通道；
    - 简介（description）DOM 通道需要先点开编辑区再输入。
    """
    value = str(field["value"])
    max_len = field.get("max_length")
    if max_len:
        value = value[:max_len]

    if field_key == "description" and not value.strip():
        return {"ok": True, "skipped": "简介为空"}

    # 通道 1：DOM 定位 + 键盘输入（对 B 站表单最稳定）
    try:
        return await _fill_text_by_dom(page, field_key, field, value)
    except Exception as e:  # noqa: BLE001
        if agent is not None and value.strip():
            logger.warning("字段「%s」DOM 通道失败，回退 AI 视觉填写: %s", field_key, e)
            return await _fill_text_by_vision(page, agent, field_key, value)
        raise


# ---------------------------------------------------------------------------
# 自定义下拉（分区）填写
# ---------------------------------------------------------------------------
async def _click_option_by_text(page: Page, text: str, *,
                                contains: bool = False) -> bool:
    """在当前页面浮层中按文本点击最“叶子”的匹配项。"""
    hits = await page.evaluate(_SCAN_CLICKABLE_JS,
                               {"want": text, "containsMode": contains})
    if not hits:
        return False
    hits.sort(key=lambda h: h["w"] * h["h"])  # 面积最小 = 最具体的叶子节点
    target = hits[0]
    await human_click(page, target["x"], target["y"])
    logger.info("下拉项「%s」已点击（匹配文本: %s）", target["text"], text)
    return True


async def _vision_click_option(page: Page, agent, text: str, *,
                               contains: bool = False) -> bool:
    """AI 屏幕识别兜底：截屏让 AI 在下拉浮层中找到目标选项后拟人点击。"""
    mode = "文字包含" if contains else "文字完全等于"
    try:
        pos = await agent.locate_or_fail(
            f"当前屏幕上已展开的下拉浮层中，{mode}“{text}”的那一个选项"
            "（只匹配浮层里的选项本身，不要匹配输入框里已填的内容或其他文字）",
            scroll_if_missing=False)
    except Exception as e:  # noqa: BLE001
        logger.warning("AI 视觉未找到下拉选项「%s」: %s", text, e)
        return False
    await human_click(page, pos["x"], pos["y"])
    await asyncio.sleep(0.35)
    logger.info("下拉项「%s」已通过 AI 视觉定位点击（%s）", text, pos.get("label") or "")
    return True


# ---------------------------------------------------------------------------
# 分区选择：纯屏幕识别通道（v1.9）——不注入任何页面脚本
# ---------------------------------------------------------------------------
async def _vision_open_zone_dropdown(page: Page, agent) -> dict:
    """屏幕识别定位「分区」触发器 → 拟人点击展开 → 识别确认浮层已打开。"""
    pos = await agent.locate_or_fail(ZONE_TRIGGER_DESC, scroll_if_missing=True)
    await agent.click_point(pos["x"], pos["y"])
    await asyncio.sleep(0.8)
    try:
        res = await agent.verify(
            "屏幕上是否已展开「分区」下拉选项列表（能看到多个分区名称，如 动画/游戏/音乐 等）？")
        if not res.get("ok"):
            # 可能误点或未展开：再点击一次触发器
            logger.info("分区浮层未确认展开（%s），重试点击触发器", res.get("detail"))
            pos = await agent.locate_or_fail(ZONE_TRIGGER_DESC,
                                             scroll_if_missing=False)
            await agent.click_point(pos["x"], pos["y"])
            await asyncio.sleep(0.8)
    except Exception as e:  # noqa: BLE001
        logger.warning("分区浮层展开确认失败（继续按已展开处理）: %s", e)
    logger.info("AI 视觉已点击分区下拉触发器（%s）@ (%.0f, %.0f)",
                pos.get("label") or "未命名", pos["x"], pos["y"])
    return pos


async def _vision_click_zone_option(page: Page, agent, text: str,
                                    anchor: tuple[float, float], *,
                                    max_scrolls: int = 6) -> bool:
    """在已展开的分区浮层中找目标选项并点击；找不到就悬停浮层滚轮下翻再找。"""
    for attempt in range(max_scrolls + 1):
        for contains in (False, True):
            mode = "文字包含" if contains else "文字完全等于"
            try:
                pos = await agent.locate(
                    f"当前屏幕上已展开的分区下拉浮层中，{mode}“{text}”的那一个分区选项"
                    "（只匹配浮层里的选项本身，不要匹配触发器输入框里已填的内容）",
                    scroll_if_missing=False)
            except Exception as e:  # noqa: BLE001
                logger.warning("分区选项「%s」屏幕识别失败: %s", text, e)
                return False
            if pos is not None:
                await human_click(page, pos["x"], pos["y"])
                await asyncio.sleep(0.4)
                logger.info("分区选项「%s」已点击（识别为: %s）",
                            text, pos.get("label") or "")
                return True
        # 本屏没有：把鼠标悬到浮层中部滚动一屏再识别
        await agent.scroll_at(anchor[0], anchor[1], agent.scroll_step)
    return False


async def _fill_zone_by_vision(page: Page, agent, value) -> dict:
    """纯屏幕识别选择分区：定位触发器 → 点击展开 → 逐级识别选项 → 点击 → 读回校验。"""
    steps = value if isinstance(value, (list, tuple)) else [value]
    steps = [str(s).strip() for s in steps if str(s).strip()]
    if not steps:
        return {"ok": False, "reason": "分区为空"}

    trigger = await _vision_open_zone_dropdown(page, agent)
    # 浮层滚动锚点：优先识别浮层面板位置，否则用触发器下方（浮层通常向下展开）
    try:
        panel = await agent.locate(ZONE_PANEL_DESC, scroll_if_missing=False)
    except Exception:  # noqa: BLE001
        panel = None
    if panel:
        anchor = (panel["x"], min(panel["y"] + 120, 1000))
    else:
        anchor = (trigger["x"], min(trigger["y"] + 200, 1000))

    for step in steps:
        if not await _vision_click_zone_option(page, agent, step, anchor):
            raise RuntimeError(
                f"分区下拉中屏幕识别未找到选项「{step}」（已滚动查找多屏）")
        await asyncio.sleep(0.3)

    # 读回校验：触发器上应显示所选分区
    ok = True
    try:
        res = await agent.verify(
            f"投稿表单「分区」一栏当前是否已选中“{steps[-1]}”"
            "（触发器/输入框上显示该分区名即可）？")
        ok = bool(res.get("ok"))
        logger.info("分区选择读回校验: %s（%s）", ok, res.get("detail"))
    except Exception as e:  # noqa: BLE001
        logger.warning("分区选择读回校验失败（不影响已完成的点击）: %s", e)
    logger.info("分区选择完成（AI 屏幕识别通道）: %s", " / ".join(steps))
    return {"ok": ok, "selected": steps, "strategy": "ai-vision"}



async def _open_dropdown(page: Page, field_key: str, field: dict) -> dict:
    """点击下拉触发器并返回其视口中心坐标（供后续就近选择选项）。

    定位通道（依次尝试）：
      1. 配置 selector（分区等已知结构的优先通道）；
      2. 字段标签下方找“请选择”占位/下拉语义元素（创作声明等无 input 组件）；
      3. _LOCATE_JS 输入框式扫描兜底。
    """
    # 通道 1：配置 selector
    if field.get("selector"):
        for sel in field["selector"].split(","):
            loc = page.locator(sel.strip()).first
            try:
                if await loc.count() > 0:
                    await loc.scroll_into_view_if_needed()
                    box = await loc.bounding_box()
                    if box:
                        cx, cy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
                        await human_click(page, cx, cy)
                        await asyncio.sleep(0.45)  # 等待浮层动画与列表渲染
                        return {"x": cx, "y": cy, "w": box["width"], "h": box["height"]}
            except Exception:  # noqa: BLE001
                continue

    # 通道 2：字段标签就近找“请选择”类触发器（无 input 的自定义下拉）
    hit = await page.evaluate(_DROPDOWN_TRIGGER_JS,
                              {"labelKeywords": field.get("keywords", [])})
    if hit:
        await human_click(page, hit["x"], hit["y"])
        await asyncio.sleep(0.45)
        return hit

    # 通道 3：复用定位扫描（select 容器内一般没有 input，主要靠祖先容器命中）
    located = await page.evaluate(_LOCATE_JS, {
        "anchor": field_key,
        "labelKeywords": field.get("keywords", []),
        "placeholderKeywords": [],
        "preferSelector": "",
    })
    if not located:
        raise RuntimeError(f"字段「{field_key}」找不到下拉触发器")
    trigger = await _anchor_locator(page, field_key)
    await trigger.scroll_into_view_if_needed()
    box = await trigger.bounding_box()
    if not box:
        raise RuntimeError(f"字段「{field_key}」下拉触发器无有效坐标")
    cx, cy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    await human_click(page, cx, cy)
    await asyncio.sleep(0.45)
    return {"x": cx, "y": cy, "w": box["width"], "h": box["height"]}


async def _click_first_option(page: Page, trigger: dict) -> str | None:
    """在已打开的下拉浮层中选择第一个非占位选项（创作声明“自动”模式）。

    优先取触发器正下方的选项（浮层通常向下展开），找不到再取全局最近项。
    :return: 选中的选项文本；无可选项返回 None
    """
    options = await page.evaluate(_LIST_OPTIONS_JS, {"maxLen": 40})
    noise = ("请选择", "取消", "确定", "关闭", "收起", "展开", "标题", "简介",
             "标签", "分区", "话题", "封面", "投稿", "上传", "搜索", "推荐", "活动")
    cands = [o for o in options if not any(n in o["text"] for n in noise)]
    if not cands:
        return None
    tx, ty = trigger["x"], trigger["y"]
    below = [o for o in cands if o["y"] > ty + 5]
    pool = below if below else cands
    pool.sort(key=lambda o: (o["y"] - ty) ** 2 + (o["x"] - tx) ** 2)
    target = pool[0]
    await human_click(page, target["x"], target["y"])
    await asyncio.sleep(0.3)
    return target["text"]


async def _search_in_first_level(page: Page, target: str) -> bool:
    """单值分区兜底：逐个点开一级分类，在其二级列表中寻找目标。

    全页扫描时会混入表单其他短文本，因此：
    1. 噪声词按“包含”过滤；
    2. className 含 cate/item/option/menu 等语义的候选优先点击；
    3. 设置 20 次安全上限，避免失控点击。
    """
    options = await page.evaluate(_LIST_OPTIONS_JS, {"maxLen": 6})
    noise_contains = ("请选择", "取消", "确定", "关闭", "上传", "投稿",
                      "标题", "简介", "标签", "搜索", "封面",
                      "话题", "声明", "推荐", "活动")
    semantic = ("cate", "item", "option", "select", "list", "dropdown",
                "menu", "tree", "tab", "cell")

    candidates = []
    seen_text = set()
    for opt in options:
        text = opt["text"]
        if text == target or text in seen_text:
            continue
        if any(n in text for n in noise_contains):
            continue
        seen_text.add(text)
        cn = (opt.get("className") or "").lower()
        semantic_hit = any(k in cn for k in semantic)
        candidates.append((0 if semantic_hit else 1, len(text), opt))

    candidates.sort(key=lambda c: (c[0], c[1]))
    for _, _, opt in candidates[:20]:
        await human_click(page, opt["x"], opt["y"])
        await asyncio.sleep(0.25)
        if await _click_option_by_text(page, target):
            return True
    return False


async def fill_select_field(page: Page, field_key: str, field: dict,
                            agent=None) -> dict:
    """填写自定义下拉（分区 / 创作声明等，B 站均为弹层式自定义组件）。

    值为空（创作声明“自动”模式）时：打开下拉后自动选择第一个非占位选项，
    与人工在B站原始页面上的操作保持一致。
    分区（zone）为纯 AI 屏幕识别通道（v1.9，用户指定：不注入脚本）；
    其余下拉选项点击为 DOM 扫描，失败且有 AI 代理时回退屏幕识别定位点击。
    """
    value = field["value"]

    # 分区：仅走 AI 屏幕识别（模拟鼠标点击 + 滚轮滚动，不注入页面脚本）
    if field_key == "zone":
        if agent is None:
            raise RuntimeError(
                "分区选择使用 AI 屏幕识别通道，但 AI 未启用或初始化失败。"
                "请检查 data\\ai_config.json（enabled=true、api_key 有效）后重试")
        return await _fill_zone_by_vision(page, agent, value)

    # “自动”模式：值为空 → 选第一项
    if value is None or (isinstance(value, str) and not value.strip()):
        try:
            trigger = await _open_dropdown(page, field_key, field)
        except RuntimeError as e:
            if field.get("optional"):
                logger.warning("字段「%s」未找到下拉（页面可能无此项），已跳过: %s",
                               field_key, e)
                return {"ok": False, "skipped": str(e)}
            raise
        text = await _click_first_option(page, trigger)
        if text is None:
            raise RuntimeError(f"字段「{field_key}」下拉打开后未找到可选项")
        logger.info("字段「%s」已自动选择第一项: %s", field_key, text)
        return {"ok": True, "selected": text}

    steps = value if isinstance(value, (list, tuple)) else [value]
    if not steps:
        return {"ok": False, "reason": "字段值为空"}

    await _open_dropdown(page, field_key, field)

    for idx, step in enumerate(steps):
        clicked = await _click_option_by_text(page, str(step))
        if not clicked and agent is not None:
            clicked = await _vision_click_option(page, agent, str(step))
        if not clicked:
            if idx == len(steps) - 1:
                # 最后一级找不到：若是单值两级分区，遍历一级分类兜底
                if len(steps) == 1 and await _search_in_first_level(page, str(step)):
                    clicked = True
                else:
                    # 宽松包含匹配再试一次（DOM + AI 视觉各一次）
                    clicked = await _click_option_by_text(
                        page, str(step), contains=True)
                    if not clicked and agent is not None:
                        clicked = await _vision_click_option(
                            page, agent, str(step), contains=True)
        if not clicked:
            raise RuntimeError(f"下拉中找不到选项「{step}」")
        await asyncio.sleep(0.3)

    logger.info("下拉选择完成: %s", " / ".join(str(s) for s in steps))
    return {"ok": True, "selected": list(steps)}


# ---------------------------------------------------------------------------
# 参与话题：点击B站“参与话题”区中同名的话题标签（与官方页面交互一致）
# ---------------------------------------------------------------------------
_SELECTED_CLASS_HINTS = ("active", "selected", "checked", "chosen", "on")


def _looks_selected(class_name: str) -> bool:
    cn = (class_name or "").lower()
    return any(k in cn for k in _SELECTED_CLASS_HINTS)


async def _fill_topics_by_vision(page: Page, agent, topics: list[str]) -> dict:
    """AI 屏幕识别参与话题：定位「参与话题」区 → 现场枚举可选话题 → 逐个匹配点击。"""
    clicked: list[str] = []
    missed: list[str] = []
    # 先让话题区进入视口
    try:
        await agent.locate("投稿页中的「参与话题」栏目标题或话题标签区域",
                           scroll_if_missing=True)
    except Exception as e:  # noqa: BLE001
        logger.warning("屏幕识别未定位到「参与话题」区域: %s", e)
    # 现场检测一轮当前可选话题（记录日志，便于对照任务里未命中的话题）
    try:
        data = await agent.read_options(
            "截图是B站投稿页的「参与话题」栏目。请列出该区域内当前可见的全部话题标签文字。"
            "照抄原文（可保留#号），不要包含栏目标题“参与话题”本身，也不要包含按钮或说明文字。")
        live: list[str] = []
        for t in data["options"]:
            t = str(t).strip().strip("#").strip()
            if t and "参与话题" not in t and len(t) <= 24 and t not in live:
                live.append(t)
        if live:
            logger.info("现场检测到「参与话题」可选话题 %d 个: %s", len(live), live)
    except Exception as e:  # noqa: BLE001
        logger.warning("现场枚举话题失败（不影响逐个匹配点击）: %s", e)
    for topic in topics:
        try:
            pos = await agent.locate(
                f"「参与话题」区域内文字为“{topic}”的话题标签按钮（chip），"
                "只匹配该区域内的标签本身",
                scroll_if_missing=False)
        except Exception as e:  # noqa: BLE001
            logger.warning("话题「%s」屏幕识别失败: %s", topic, e)
            pos = None
        if pos is None:
            logger.warning("话题「%s」未在“参与话题”区识别到，跳过"
                           "（可在浏览器中手动参与）", topic)
            missed.append(topic)
            continue
        await agent.click_point(pos["x"], pos["y"])
        await asyncio.sleep(0.35)
        clicked.append(topic)
        logger.info("话题「%s」已通过屏幕识别点击参与", topic)
    return {"ok": not missed, "clicked": clicked, "missed": missed}


async def fill_topics_field(page: Page, field_key: str, field: dict,
                            agent=None) -> dict:
    """逐个点击“参与话题”栏目中与目标同名的话题 chip。

    提供 AI 代理时走屏幕识别通道（v1.9）；否则保留 DOM 文本扫描通道。
    """
    topics = [str(t).strip() for t in (field["value"] or []) if str(t).strip()]
    if not topics:
        return {"ok": True, "clicked": [], "missed": []}
    if agent is not None:
        return await _fill_topics_by_vision(page, agent, topics)

    clicked: list[str] = []
    missed: list[str] = []
    for topic in topics:
        hit = await find_section_chip(page, "参与话题", topic)
        if hit is None:
            hit = await find_section_chip(page, "参与话题", topic, contains=True)
        if hit is None:
            logger.warning("话题「%s」未在“参与话题”区找到，跳过（可在浏览器中手动参与）",
                           topic)
            missed.append(topic)
            continue
        await human_click(page, hit["x"], hit["y"])
        await asyncio.sleep(0.35)
        # 重新读取 chip 状态：选中的话题通常会带上 active/selected 类名
        state = await find_section_chip(page, "参与话题", topic)
        if state and _looks_selected(state.get("className", "")):
            logger.info("话题「%s」已参与", topic)
        else:
            logger.info("话题「%s」已点击（未能自动确认选中态，请在浏览器中核对）", topic)
        clicked.append(topic)

    return {"ok": not missed, "clicked": clicked, "missed": missed}


# ---------------------------------------------------------------------------
# 字幕同步上传（B 站 CC 字幕区）
# ---------------------------------------------------------------------------
async def _find_subtitle_input(page: Page):
    """定位字幕 file input：优先 accept 含 srt/ass/vtt 的输入框；
    兜底为所有 file input 中非视频上传的那个。返回 Locator 或 None。"""
    for selector in config.SUBTITLE_INPUT_SELECTORS:
        loc = page.locator(selector)
        try:
            if await loc.count() > 0:
                logger.info("命中字幕输入框: %s", selector)
                return loc.first
        except Exception:  # noqa: BLE001
            continue
    inputs = page.locator('input[type="file"]')
    try:
        n = await inputs.count()
    except Exception:  # noqa: BLE001
        return None
    for i in range(n):
        el = inputs.nth(i)
        try:
            accept = (await el.get_attribute("accept") or "").lower()
        except Exception:  # noqa: BLE001
            accept = ""
        if "video" in accept:
            continue
        logger.info("兜底命中字幕输入框（第 %d 个 file input，accept=%s）", i, accept)
        return el
    return None


async def _click_section_tab(page: Page, label: str) -> bool:
    """点击页面中可见的“字幕”等栏目入口（左侧菜单/页签）。"""
    hits = await page.evaluate(_SCAN_CLICKABLE_JS,
                               {"want": label, "containsMode": False, "maxLen": 8})
    if not hits:
        return False
    hits.sort(key=lambda h: h["w"] * h["h"])  # 面积最小 = 最具体的叶子节点
    await human_click(page, hits[0]["x"], hits[0]["y"])
    logger.info("已点击栏目入口「%s」", label)
    return True


async def _select_subtitle_language(page: Page, lang: str) -> bool:
    """在字幕区选择语言（英语）：先尝试语言下拉，再直接点击可见语言项。"""
    # 通道 1：字幕语言下拉（“字幕语言/语言”标签附近，打开后点击目标语言）
    try:
        trigger = await _open_dropdown(page, "subtitle_lang", {
            "keywords": ["字幕语言", "字幕语言:", "语言"],
            "selector": "",
            "optional": True,
        })
        if trigger and await _click_option_by_text(page, lang, contains=True):
            logger.info("字幕语言已通过下拉选择: %s", lang)
            return True
    except Exception as e:  # noqa: BLE001
        logger.debug("字幕语言下拉通道失败: %s", e)
    # 通道 2：直接扫描可点击的语言文本（部分页面为语言 chip 平铺）
    hits = await page.evaluate(_SCAN_CLICKABLE_JS,
                               {"want": lang, "containsMode": True, "maxLen": 12})
    if hits:
        hits.sort(key=lambda h: h["w"] * h["h"])
        await human_click(page, hits[0]["x"], hits[0]["y"])
        logger.info("字幕语言已直接点击: %s", lang)
        return True
    return False


async def _wait_subtitle_done(page: Page, timeout: float = 45.0) -> None:
    """等待字幕上传完成（“字幕上传中/解析中”文本消失），超时仅告警不阻断。"""
    busy_kw = ("字幕上传中", "正在上传字幕", "字幕解析中", "字幕解析")
    await asyncio.sleep(2.0)
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        try:
            body = (await page.locator("body").inner_text(timeout=3000))[:3000]
        except Exception:  # noqa: BLE001
            body = ""
        if any(k in body for k in busy_kw):
            await asyncio.sleep(2.0)
            continue
        await asyncio.sleep(1.0)
        try:
            body2 = (await page.locator("body").inner_text(timeout=3000))[:3000]
        except Exception:  # noqa: BLE001
            body2 = body
        if not any(k in body2 for k in busy_kw):
            logger.info("字幕上传完成")
            return
    logger.warning("等待字幕上传完成超时，请人工核对字幕区状态")


async def fill_subtitle_field(page: Page, field_key: str, field: dict) -> dict:
    """上传原始字幕（.srt）并选择字幕语言（B 站 CC 字幕区）。

    未配置字幕文件时直接跳过（不影响其他字段）。流程：
    定位字幕入口（必要时先点开“字幕”栏目）→ 先选语言 → 注入字幕文件 → 等待完成。
    """
    path = str(field.get("value") or "").strip()
    if not path:
        return {"ok": True, "skipped": "未指定字幕文件"}
    if not Path(path).exists():
        raise RuntimeError(f"字幕文件不存在: {path}")
    lang = str(field.get("lang") or config.SUBTITLE_LANG or "英语").strip()
    logger.info("开始上传字幕: %s（语言: %s）", Path(path).name, lang)

    # 1. 定位字幕 file input（未直接命中时先点开“字幕”栏目）
    input_el = await _find_subtitle_input(page)
    if input_el is None:
        logger.info("未直接找到字幕输入框，尝试点击“字幕”栏目入口")
        for label in config.SUBTITLE_SECTION_KEYWORDS:
            if await _click_section_tab(page, label):
                await asyncio.sleep(0.8)
                input_el = await _find_subtitle_input(page)
                if input_el is not None:
                    break
    if input_el is None:
        raise RuntimeError("未找到字幕上传入口（input[type=file] accept 含 srt/ass）")

    # 2. 先选语言（B 站为上传前选择字幕语言）
    if not await _select_subtitle_language(page, lang):
        logger.warning("未能自动选择字幕语言「%s」，请在浏览器中手动确认", lang)

    # 3. 注入字幕文件（CDP 层绑定，与视频上传同一通道）
    await input_el.set_input_files(str(Path(path).resolve()))
    logger.info("字幕文件已注入: %s", Path(path).name)

    # 4. 等待上传完成
    await _wait_subtitle_done(page)
    return {"ok": True, "file": Path(path).name, "lang": lang}


# ---------------------------------------------------------------------------
# 引擎总入口
# ---------------------------------------------------------------------------
async def fill_all_forms(page: Page, agent=None) -> dict[str, dict]:
    """按 config.FIELD_ORDER 逐字段填写；单字段失败不影响其他字段。

    :param agent: modules.vision_agent.VisionAgent（AI 屏幕识别代理，可为 None）
    """
    results: dict[str, dict] = {}
    for field_key in config.FIELD_ORDER:
        field = config.FIELD_CONFIG[field_key]
        ftype = field.get("type")
        logger.info("==== 处理字段 [%s] 类型=%s ===", field_key, ftype)
        try:
            # 每字段开始前都重新查询，杜绝动态渲染导致的引用失效
            if ftype == "tags":
                results[field_key] = await fill_bilibili_tags(page, list(field["value"]))
            elif ftype == "select":
                # 加入合集：未指定时跳过（不做任何点击），避免误选“不加入合集”
                if field_key == "collection" and not str(field["value"] or "").strip():
                    results[field_key] = {"ok": True, "skipped": "未指定合集"}
                    continue
                results[field_key] = await fill_select_field(page, field_key, field,
                                                             agent=agent)
            elif ftype == "topics":
                results[field_key] = await fill_topics_field(page, field_key, field,
                                                             agent=agent)
            elif ftype == "subtitle":
                results[field_key] = await fill_subtitle_field(page, field_key, field)
            else:
                results[field_key] = await fill_text_field(page, field_key, field,
                                                           agent=agent)
        except Exception as e:  # noqa: BLE001 - 单字段失败隔离
            logger.exception("字段「%s」填写失败: %s", field_key, e)
            results[field_key] = {"ok": False, "error": str(e)}
    return results
