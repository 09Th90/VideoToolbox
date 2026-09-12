# -*- coding: utf-8 -*-
"""
屏幕识别代理（AI Vision Agent）——投稿引擎的"眼睛和手"。

定位思路（对应用户需求：不用脚本操作页面，改为模拟鼠标点击 + 滚动 + 屏幕识别）：
1. 视觉：page.screenshot 截取当前视口 → 全局 AI 视觉模型读图，
   返回目标元素的 0-1000 归一化坐标（GLM 视觉定位的规范输出），本模块换算为像素；
2. 操作：一律使用拟人鼠标（human_click，CDP Input.dispatchMouseEvent，isTrusted=true）
   与真实滚轮（page.mouse.wheel）完成点击 / 滚动，全程不注入任何页面 JS；
3. 校验：操作后再截图问 AI"刚才的修改是否生效"，读回确认。

AI 不可用（未启用 / 网络失败 / 解析失败）时抛 VisionError，由调用方决定回退通道。
"""

from __future__ import annotations

import asyncio
import logging

from playwright.async_api import Page

from modules import ai_client
from modules.browser import human_click

logger = logging.getLogger(__name__)


class VisionError(RuntimeError):
    """屏幕识别或视觉操作失败。"""


# ---------------------------------------------------------------------------
# 提示词模板（GLM 视觉定位约定：0-1000 归一化坐标）
# ---------------------------------------------------------------------------
_LOCATE_PROMPT = """你是浏览器自动化助手。这是一张浏览器当前视口的截图。
任务：{target}

若目标在截图内可见，返回严格 JSON（不要输出任何其他文字）：
{{"found": true, "x": <0-1000归一化横坐标,元素中心点>, "y": <0-1000归一化纵坐标,元素中心点>, "label": "你看到的元素文字"}}
若截图内找不到目标，返回：{{"found": false}}
注意：
1. 坐标是相对整张截图宽高的 0-1000 归一化数值，不是像素值；
2. 必须返回目标元素本身（输入框/按钮/选项）的几何中心，
   不要返回其旁边的标签文字、标题或说明文字的位置。"""

_LIST_PROMPT = """你是浏览器自动化助手。这是一张浏览器当前视口的截图。
{instruction}

返回严格 JSON（不要输出任何其他文字）：
{{"options": ["可见选项1", "可见选项2", ...], "end": <true或false>}}
options：把屏幕上{scope}当前可见的全部选项文字原样照抄（保持原文，不要翻译、不要去重、不要补充遗漏的猜测）；
end：该列表是否已经滚动到底（下方没有更多选项了）。"""

_VERIFY_PROMPT = """你是浏览器自动化助手。这是一张浏览器当前视口的截图。
请判断：{question}

返回严格 JSON（不要输出任何其他文字）：
{{"ok": true或false, "detail": "一句话依据"}}"""


class VisionAgent:
    """单个页面的屏幕识别代理。方法均为 async。"""

    def __init__(self, page: Page, client: ai_client.AIClient | None = None,
                 scroll_step: int = 400) -> None:
        self.page = page
        self.client = client or ai_client.get_client()
        self.scroll_step = scroll_step

    # ---- 基础 -------------------------------------------------------------
    async def screenshot_png(self) -> bytes:
        """截取当前视口（不注入脚本；device_scale_factor=1，像素=CSS 坐标）。"""
        try:
            return await self.page.screenshot(type="png")
        except Exception as e:  # noqa: BLE001
            raise VisionError(f"截屏失败: {e}") from e

    async def viewport_size(self) -> tuple[int, int]:
        vp = self.page.viewport_size or {"width": 1920, "height": 1080}
        return int(vp["width"]), int(vp["height"])

    # ---- 视觉问答原语 ------------------------------------------------------
    async def locate(self, target: str, *, scroll_if_missing: bool = False,
                     max_scrolls: int = 5) -> dict | None:
        """让 AI 在截图中定位目标元素，返回像素坐标 {'x','y','label'}。

        找不到且允许滚动时：向下滚动页面后再找（识别随滚动完成）。
        :raises VisionError: AI 调用/解析失败
        """
        scrolls = 0
        while True:
            png = await self.screenshot_png()
            w, h = await self.viewport_size()
            raw = self.client.chat_vision(
                _LOCATE_PROMPT.format(target=target),
                [png], max_tokens=1024)
            data = ai_client.try_parse_json(raw)
            if not isinstance(data, dict):
                raise VisionError(f"定位结果不是合法 JSON: {raw[:120]}")
            if data.get("found"):
                try:
                    nx = float(data.get("x"))
                    ny = float(data.get("y"))
                except (TypeError, ValueError):
                    raise VisionError(f"定位坐标非法: {data}")
                return {
                    "x": max(0, min(w - 1, nx / 1000.0 * w)),
                    "y": max(0, min(h - 1, ny / 1000.0 * h)),
                    "label": str(data.get("label") or ""),
                }
            if not scroll_if_missing or scrolls >= max_scrolls:
                logger.info("屏幕识别未找到目标（已滚动 %d 次）: %s", scrolls, target[:50])
                return None
            # 目标可能在视口下方：模拟滚轮向下翻页后重试
            await self.page.mouse.move(w / 2, h / 2)
            await self.page.mouse.wheel(0, self.scroll_step)
            scrolls += 1
            await asyncio.sleep(0.5)

    async def locate_or_fail(self, target: str, **kw) -> dict:
        pos = await self.locate(target, **kw)
        if pos is None:
            raise VisionError(f"屏幕识别未能找到: {target}")
        return pos

    async def read_options(self, instruction: str, *,
                           max_tokens: int = 3000) -> dict:
        """读取屏幕上一份列表当前可见的选项，返回 {'options': [...], 'end': bool}。"""
        png = await self.screenshot_png()
        raw = self.client.chat_vision(
            _LIST_PROMPT.format(instruction=instruction,
                                scope="目标列表中"), [png],
            max_tokens=max_tokens)
        data = ai_client.try_parse_json(raw)
        if not isinstance(data, dict):
            raise VisionError(f"列表识别结果不是合法 JSON: {raw[:120]}")
        opts = data.get("options")
        if not isinstance(opts, list):
            opts = []
        return {"options": [str(o).strip() for o in opts if str(o).strip()],
                "end": bool(data.get("end"))}

    async def verify(self, question: str) -> dict:
        """自由问句校验屏幕状态，返回 {'ok': bool, 'detail': str}。"""
        png = await self.screenshot_png()
        raw = self.client.chat_vision(_VERIFY_PROMPT.format(question=question),
                                      [png], max_tokens=1024)
        data = ai_client.try_parse_json(raw)
        if not isinstance(data, dict):
            raise VisionError(f"校验结果不是合法 JSON: {raw[:120]}")
        return {"ok": bool(data.get("ok")), "detail": str(data.get("detail") or "")}

    # ---- 鼠标 / 滚轮操作 ---------------------------------------------------
    async def click_point(self, x: float, y: float) -> None:
        """在视口坐标执行拟人点击（CDP 真实鼠标事件）。"""
        await human_click(self.page, x, y)

    async def click_element(self, target: str, *, scroll_if_missing: bool = True,
                            settle: float = 0.6) -> dict:
        """屏幕识别定位 → 拟人点击，返回命中的坐标信息。"""
        pos = await self.locate_or_fail(target, scroll_if_missing=scroll_if_missing)
        await self.click_point(pos["x"], pos["y"])
        await asyncio.sleep(settle)
        logger.info("AI 视觉点击「%s」@ (%.0f, %.0f)", pos.get("label") or target[:30],
                    pos["x"], pos["y"])
        return pos

    async def scroll_at(self, x: float, y: float, dy: int) -> None:
        """把鼠标移到 (x, y) 上滚动滚轮（dy>0 向下），模拟真人滚动列表。"""
        await self.page.mouse.move(x, y)
        await asyncio.sleep(0.15)
        await self.page.mouse.wheel(0, dy)
        await asyncio.sleep(0.45)
