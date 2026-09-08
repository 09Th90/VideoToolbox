# -*- coding: utf-8 -*-
"""
模块四：B 站标签输入兼容处理（开发书 3.4 / R4）。

核心问题：标签块（<span class="tag">）逐个生成会把 <input> 挤到不同位置甚至下一行，
缓存坐标会点到标签块上。因此：
  1. 每次输入前都重新 DOM 查询输入框，绝不缓存 Locator/坐标；
  2. 逐字符 type(delay) 触发 React onChange，避免 fill() 瞬间赋值丢状态；
  3. 提交后读取 DOM 中真实存在的标签块做验证，失败自动换提交策略重试；
  4. 兼容 B 站联想下拉：Enter 可能选中高亮联想词而非原文，按 “Esc 关下拉 → Enter”
     与 “逗号提交” 两种兜底策略保证写入的是目标标签。
"""

from __future__ import annotations

import asyncio
import logging

from playwright.async_api import Page

import config
from modules.browser import human_click

logger = logging.getLogger(__name__)

# 标签块文本末尾可能附带关闭符号（× ✕ x），验证时统一剥除
_BLOCK_TAIL_CHARS = " ×✕✖xX\t\n\r"


def sanitize_tags(tags: list[str]) -> list[str]:
    """标签预处理（开发书 3.4.3）：去空白、限长、去重、最多 10 个。"""
    result: list[str] = []
    for raw in tags:
        if not isinstance(raw, str):
            continue
        t = raw.strip()
        if len(t) > 20:  # B 站单标签长度限制
            t = t[:20]
        if t and t not in result:
            result.append(t)
    return result[:10]


async def get_tag_input(page: Page):
    """每次都重新查询标签输入框（开发书 3.4.2 正确做法）。返回 Locator 或 None。"""
    for selector in config.TAG_INPUT_SELECTORS:
        loc = page.locator(selector)
        try:
            if await loc.count() > 0:
                return loc.first
        except Exception:  # noqa: BLE001
            continue
    return None


_GET_BLOCKS_JS = r"""
(selectors) => {
    const out = [];
    for (const sel of selectors) {
        document.querySelectorAll(sel).forEach((el) => {
            const t = (el.innerText || el.textContent || '').trim();
            if (t) out.push(t);
        });
    }
    return out;
}
"""


def _clean_block_text(text: str) -> str:
    return text.strip(_BLOCK_TAIL_CHARS).strip()


async def get_committed_tags(page: Page) -> set[str]:
    """读取当前 DOM 中已经生成的全部标签块文本（已清洗关闭符号）。"""
    try:
        raw_list = await page.evaluate(_GET_BLOCKS_JS, config.TAG_ITEM_SELECTORS)
    except Exception:  # noqa: BLE001
        return set()
    return {_clean_block_text(t) for t in raw_list if t}


# ---------------------------------------------------------------------------
# 分区 chip 定位：在指定栏目（如“推荐标签”“参与话题”）内按文本找可点击 chip。
# 从栏目标签文本出发逐级向上，在其子树内找位于标签下方/同行的叶子元素，
# 避免全页扫描误点其他区域。返回中心坐标与 className（供选中态验证）。
# ---------------------------------------------------------------------------
_SECTION_CHIP_JS = r"""
(args) => {
    const { sectionLabel, chipText, containsMode = false } = args;
    const visible = (el) => {
        if (!el) return false;
        const s = window.getComputedStyle(el);
        if (s.display === 'none' || s.visibility === 'hidden' || parseFloat(s.opacity) === 0) return false;
        const r = el.getBoundingClientRect();
        return r.width > 2 && r.height > 2;
    };
    const match = (t) => containsMode ? t.includes(chipText) : (t === chipText);

    // 1) 定位栏目标签（短文本命中）
    let labelEl = null;
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, null, false);
    let node;
    while ((node = walker.nextNode())) {
        const t = node.textContent.trim();
        if (t && t.length <= 15 && t.includes(sectionLabel)) {
            const el = node.parentElement;
            if (visible(el)) { labelEl = el; break; }
        }
    }
    if (!labelEl) return null;
    const lr = labelEl.getBoundingClientRect();

    // 2) 从标签逐级向上，在其子树中找目标 chip（叶子、面积最小者最精确）
    let cur = labelEl;
    for (let depth = 0; depth < 6 && cur; depth++) {
        let best = null, bestEl = null;
        cur.querySelectorAll('div,span,li,a,p,button').forEach((el) => {
            if (!visible(el)) return;
            const t = (el.innerText || '').trim();
            if (!t || t.includes('\n') || t.length > 24) return;
            if (!match(t)) return;
            // 存在同名子元素说明当前是外层容器，取子元素
            for (const c of el.children) {
                const ct = (c.innerText || '').trim();
                if (ct && match(ct)) return;
            }
            const r = el.getBoundingClientRect();
            if (r.y < lr.y - 6) return;   // 必须位于标签下方或同一行
            if (!best || r.width * r.height < best.w * best.h) {
                best = { w: r.width, h: r.height, text: t };
                bestEl = el;
            }
        });
        if (bestEl) {
            // 先滚动到视口中心再取坐标，保证 CDP 点击落在视口内
            bestEl.scrollIntoView({ block: 'center' });
            const r2 = bestEl.getBoundingClientRect();
            return {
                x: r2.x + r2.width / 2, y: r2.y + r2.height / 2,
                w: r2.width, h: r2.height, text: best.text,
                className: bestEl.className ? bestEl.className.toString() : ''
            };
        }
        cur = cur.parentElement;
    }
    return null;
}
"""


async def find_section_chip(page: Page, section_label: str, chip_text: str,
                            contains: bool = False) -> dict | None:
    """在指定栏目内查找可点击 chip，返回 {x, y, text, className} 或 None。"""
    try:
        return await page.evaluate(_SECTION_CHIP_JS, {
            "sectionLabel": section_label,
            "chipText": chip_text,
            "containsMode": contains,
        })
    except Exception as e:  # noqa: BLE001
        logger.debug("分区 chip 查询异常（%s / %s）: %s", section_label, chip_text, e)
        return None


async def click_recommended_tags(page: Page, tags: list[str],
                                 existing: set[str]) -> list[str]:
    """优先点击B站“推荐标签”区与目标一致的标签（与官方页面交互一致）。

    与逐字键入相比，点击推荐标签更接近真人操作，也能规避联想下拉劫持。
    :return: 未能通过点击完成、需要回退到手动键入的标签列表
    """
    remaining: list[str] = []
    for tag in tags:
        if tag in existing:
            continue
        hit = await find_section_chip(page, "推荐标签", tag)
        if hit is None:
            remaining.append(tag)
            continue
        before = await get_committed_tags(page)
        try:
            await human_click(page, hit["x"], hit["y"])
        except Exception as e:  # noqa: BLE001
            logger.warning("推荐标签「%s」点击异常: %s", tag, e)
            remaining.append(tag)
            continue
        await asyncio.sleep(0.4)
        after = await get_committed_tags(page)
        if tag in after:
            logger.info("推荐标签「%s」点击成功（与B站推荐标签一致）", tag)
            continue
        unexpected = after - before - {tag}
        if unexpected:
            logger.info("推荐标签「%s」点击产生了意外标签 %s，撤销后回退键入",
                        tag, unexpected)
            for _ in range(len(unexpected)):
                await _remove_last_block(page)
        remaining.append(tag)
    return remaining


async def _clear_input(input_el) -> None:
    """清空输入框残留文本。

    关键：输入框为空时**绝不能**按 Backspace——B 站块级输入的默认行为是
    “空输入框按 Backspace 删除前一个已生成标签块”，会误伤上一个标签。
    因此先读取当前值，确认有残留文本才执行全选删除。
    """
    try:
        current = await input_el.input_value()
    except Exception:  # noqa: BLE001
        current = ""
    if current:
        await input_el.press("Control+a")
        await input_el.press("Delete")


async def _type_and_commit(page: Page, tag: str, strategy: str) -> None:
    """按指定策略提交单个标签。strategy: escape_enter / enter / comma。"""
    # 关键：每次重新定位，天然处理跨行位移
    input_el = await get_tag_input(page)
    if input_el is None:
        raise RuntimeError("找不到标签输入框")

    await input_el.scroll_into_view_if_needed()
    await input_el.click()
    await asyncio.sleep(config.TIMING["after_click_delay"])
    await _clear_input(input_el)

    # 逐字符输入，delay 模拟真人打字并保证 React 状态同步
    await input_el.type(tag, delay=config.TIMING["type_delay_ms"])
    await asyncio.sleep(0.2)

    if strategy == "escape_enter":
        # 先关掉联想下拉浮层，再提交原文
        await input_el.press("Escape")
        await asyncio.sleep(0.12)
        await input_el.press("Enter")
    elif strategy == "comma":
        # B 站支持英文逗号生成标签块，可绕过联想高亮
        await input_el.type(",", delay=20)
    else:  # enter
        await input_el.press("Enter")

    await asyncio.sleep(config.TIMING["tag_enter_wait"])


async def _remove_last_block(page: Page) -> None:
    """输入框为空时按 Backspace 可删除前一个标签块（用于撤销被联想词替换的块）。"""
    input_el = await get_tag_input(page)
    if input_el is None:
        return
    await input_el.click()
    await asyncio.sleep(0.05)
    await input_el.press("Backspace")
    await asyncio.sleep(0.2)


async def fill_one_tag(page: Page, tag: str) -> bool:
    """填写并验证单个标签，成功返回 True。"""
    strategies = ["escape_enter", "enter", "comma"]
    for attempt, strategy in enumerate(strategies, start=1):
        before = await get_committed_tags(page)
        try:
            await _type_and_commit(page, tag, strategy)
        except Exception as e:  # noqa: BLE001
            logger.warning("标签「%s」第 %d 次提交异常: %s", tag, attempt, e)
            continue

        after = await get_committed_tags(page)

        if tag in after:
            logger.info("标签「%s」提交成功（策略: %s）", tag, strategy)
            return True

        # 出现了不在预期内的新块（多半是被联想词劫持），撤销后换策略
        unexpected = after - before - {tag}
        if unexpected:
            logger.info("标签「%s」被联想词替换为 %s，撤销后重试", tag, unexpected)
            for _ in range(len(unexpected)):
                await _remove_last_block(page)

    logger.error("标签「%s」多次提交后仍未在 DOM 中验证到，已跳过", tag)
    return False


async def fill_bilibili_tags(page: Page, tags: list[str]) -> dict[str, list[str]]:
    """按开发书 3.4.2 流程填写全部标签。

    优先点击B站“推荐标签”中与目标一致的标签（use_recommended=True 时），
    未命中的再逐字键入；最终以 DOM 中真实存在的标签块核对结果。

    :return: {"success": [...], "failed": [...]}
    """
    clean_tags = sanitize_tags(tags)
    if not clean_tags:
        logger.warning("标签列表预处理后为空，跳过标签填写")
        return {"success": [], "failed": []}

    logger.info("开始填写 %d 个标签: %s", len(clean_tags), clean_tags)

    # 若页面上已有同名标签块则跳过，避免重复
    existing = await get_committed_tags(page)

    # 先走“推荐标签”点击通道（与B站官方页面交互一致）
    if config.UPLOAD_TASK.get("use_recommended", True):
        clean_tags = await click_recommended_tags(page, clean_tags, existing)
        existing = await get_committed_tags(page)
        if not clean_tags:
            logger.info("全部标签已通过“推荐标签”点击完成")

    success: list[str] = []
    failed: list[str] = []

    for tag in clean_tags:
        if tag in existing:
            logger.info("标签「%s」已存在，跳过", tag)
            success.append(tag)
            continue
        ok = await fill_one_tag(page, tag)
        committed_now = await get_committed_tags(page)
        # 累计守卫：此前已成功的标签不能在本次操作后丢失（如被 Backspace 误删）
        lost = [t for t in success if t not in committed_now]
        if lost:
            logger.error("检测到已提交标签丢失: %s（本次标签 %s 判定失败）", lost, tag)
            ok = False
        if ok:
            success.append(tag)
        else:
            failed.append(tag)
        existing = committed_now
        await asyncio.sleep(config.TIMING["after_field_filled"])

    # 以 DOM 真实状态做最终核对（含通过推荐标签点击完成的标签）
    final = await get_committed_tags(page)
    all_target = sanitize_tags(tags)
    success = [t for t in all_target if t in final]
    failed = [t for t in all_target if t not in final]

    logger.info("标签填写完成：成功 %d，失败 %d", len(success), len(failed))
    return {"success": success, "failed": failed}
