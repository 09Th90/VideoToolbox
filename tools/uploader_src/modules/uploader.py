# -*- coding: utf-8 -*-
"""
模块二：视频文件上传（开发书 3.2 / R2）。

主通道（方案 A）：Playwright set_input_files → 底层 CDP DOM.setFileInputFiles，
直接在内核 DOM 层绑定文件，不经过操作系统文件选择器，页面收到的 change 事件与真实选择一致。

备用通道（方案 B）：页面组件拦截了原生 input 时，点击上传入口，
交给 system_dialog.handle_system_dialog 用键盘自动确认系统对话框。

上传后轮询页面，等待上传/转码就绪再进入表单填写阶段。
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from playwright.async_api import Page, TimeoutError as PWTimeoutError

import config
from modules import system_dialog

logger = logging.getLogger(__name__)

# B 站允许的常见视频容器格式
VIDEO_SUFFIXES = {".mp4", ".flv", ".avi", ".wmv", ".mov", ".mkv", ".webm",
                  ".mpeg", ".mpg", ".m4v", ".ts", ".3gp"}

# 视频 file input 的候选选择器（按优先级）
VIDEO_INPUT_SELECTORS = [
    'input[type="file"][accept*="video"]',
    'input[type="file"][accept*="video/*"]',
    'input[type="file"]',
]

# 读取上传进度文本的候选选择器（仅用于日志，找不到不影响流程）
PROGRESS_TEXT_SELECTORS = [".upload-progress", ".progress-text", ".text-progress",
                           "[class*='progress']"]

# 页面出现这些短文本视为上传明确失败（立即报错，不再空等到超时）
UPLOAD_FAIL_KEYWORDS = ["上传失败", "上传出错", "上传错误", "转码失败",
                        "视频转码失败", "重新上传", "上传异常"]

# 进度文本长时间无变化判定为“卡死”（秒）；超过即报错并截图留证
UPLOAD_STALL_SECONDS = 300.0


def validate_video_file(file_path: str | Path) -> Path:
    """上传前的本地文件校验，尽早暴露配置错误。"""
    p = Path(file_path).expanduser()
    if not p.exists():
        raise FileNotFoundError(f"视频文件不存在: {p}")
    if not p.is_file():
        raise IsADirectoryError(f"给定路径不是文件: {p}")
    if p.suffix.lower() not in VIDEO_SUFFIXES:
        logger.warning("文件后缀 %s 不在常见视频格式列表内，仍尝试上传", p.suffix)
    size_mb = p.stat().st_size / 1024 / 1024
    logger.info("待上传文件: %s（%.2f MB）", p, size_mb)
    return p.resolve()


async def _find_video_input(page: Page):
    """按候选选择器依次查找视频 file input，返回 Locator 或 None。"""
    for selector in VIDEO_INPUT_SELECTORS:
        loc = page.locator(selector)
        try:
            count = await loc.count()
        except Exception:  # noqa: BLE001
            continue
        if count > 0:
            logger.info("命中视频文件输入框: %s（共 %d 个，取第一个）", selector, count)
            return loc.first
    return None


async def inject_file_by_cdp(page: Page, file_path: Path) -> bool:
    """方案 A：CDP DOM.setFileInputFiles 直接注入。成功返回 True。"""
    file_input = await _find_video_input(page)
    if file_input is None:
        logger.warning("页面未找到任何 input[type=file]，方案 A 不可用")
        return False

    try:
        # set_input_files 不要求元素可见，隐藏 input 同样可注入
        await file_input.set_input_files(str(file_path))
        logger.info("CDP 已注入文件（DOM.setFileInputFiles）: %s", file_path.name)
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning("CDP 文件注入失败: %s", e)
        return False


async def inject_file_by_system_dialog(page: Page, file_path: Path) -> bool:
    """方案 B：点击上传入口 + PyAutoGUI 自动确认系统对话框。"""
    # 常见的上传触发区候选
    trigger_selectors = [
        ".upload-btn",
        ".uploader-web",
        "[class*='upload-trigger']",
        ".bcc-upload",
        "text=上传文件",
    ]
    trigger = None
    for sel in trigger_selectors:
        loc = page.locator(sel).first
        try:
            if await loc.is_visible():
                trigger = loc
                logger.info("命中上传入口: %s", sel)
                break
        except Exception:  # noqa: BLE001
            continue

    if trigger is None:
        # 最后兜底：直接点 file input 的关联区域（部分页面点击隐藏 input 也会弹框）
        file_input = await _find_video_input(page)
        if file_input is None:
            logger.error("方案 B 失败：找不到任何可点击的上传入口")
            return False
        trigger = file_input

    try:
        await system_dialog.click_upload_and_fill_dialog(page, trigger, file_path)
        return True
    except Exception as e:  # noqa: BLE001
        logger.error("系统对话框方案失败: %s", e)
        return False


# ---------------------------------------------------------------------------
# 上传 / 转码就绪等待
# ---------------------------------------------------------------------------
_READY_JS = r"""
(args) => {
    const selectors = args[0];
    const busyKeywords = args[1] || [];
    const failKeywords = args[2] || [];
    const isVisible = (el) => {
        if (!el) return false;
        const s = window.getComputedStyle(el);
        if (s.display === 'none' || s.visibility === 'hidden' || s.opacity === '0') return false;
        const r = el.getBoundingClientRect();
        return r.width > 0 && r.height > 0;
    };
    let readyHit = null;
    for (const sel of selectors) {
        const el = document.querySelector(sel);
        if (el && isVisible(el)) { readyHit = sel; break; }
    }
    // 扫描“上传中”类忙碌文本与“上传失败”类失败文本
    let busy = false;
    let failHit = null;
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, null, false);
    let node;
    while ((node = walker.nextNode())) {
        const t = node.textContent.trim();
        if (!t || t.length > 12) continue;
        const p = node.parentElement;
        if (!p || !isVisible(p)) continue;
        if (!busy && busyKeywords.some(k => t.includes(k))) busy = true;
        if (!failHit && failKeywords.some(k => t.includes(k))) failHit = t;
        if (busy && failHit) break;
    }
    return { readyHit, busy, failHit };
}
"""

_PROGRESS_JS = r"""
(selectors) => {
    for (const sel of selectors) {
        const els = document.querySelectorAll(sel);
        for (const el of els) {
            const t = (el.innerText || '').trim();
            if (t && t.length <= 30 && /\d/.test(t)) return t;
        }
    }
    return '';
}
"""


async def _read_progress(page: Page) -> str:
    try:
        return await page.evaluate(_PROGRESS_JS, config.PROGRESS_TEXT_SELECTORS) or ""
    except Exception:  # noqa: BLE001
        return ""


async def wait_until_upload_ready(page: Page, timeout: float | None = None) -> None:
    """轮询等待：出现“就绪标志”且页面不再显示“上传中”。

    报错检测（v1.9.2）：
    1. 页面出现“上传失败/转码失败/重新上传”等文本 → 立即抛错（不空等超时）；
    2. 进度文本超过 UPLOAD_STALL_SECONDS 秒无变化 → 判定卡死抛错；
    3. 总超时 → 抛错并附最后一次进度，便于定位。

    :param timeout: 总超时秒数，默认取 config.TIMEOUT['upload_complete']
    """
    timeout = timeout if timeout is not None else config.TIMEOUT["upload_complete"]
    deadline = asyncio.get_event_loop().time() + timeout
    poll_interval = 2.0
    last_progress = ""
    last_change = asyncio.get_event_loop().time()
    stall_limit = min(UPLOAD_STALL_SECONDS, max(timeout / 4, 60.0))

    logger.info("等待视频上传与初始化完成（超时 %.0f 秒，卡死判定 %.0f 秒无进度）...",
                timeout, stall_limit)
    while asyncio.get_event_loop().time() < deadline:
        try:
            state = await page.evaluate(_READY_JS,
                                        [config.UPLOAD_READY_SELECTORS,
                                         config.UPLOAD_BUSY_KEYWORDS,
                                         UPLOAD_FAIL_KEYWORDS])
        except Exception as e:  # noqa: BLE001
            logger.debug("就绪轮询 evaluate 异常（页面可能正在跳转）: %s", e)
            await asyncio.sleep(poll_interval)
            continue

        # 1. 明确失败信号：立即报错，不再空等
        if state.get("failHit"):
            raise RuntimeError(
                f"页面显示上传失败（检测到文本“{state['failHit']}”）。"
                "请检查网络后重试；若为视频转码失败，请确认视频编码受 B 站支持")

        progress = await _read_progress(page)
        now = asyncio.get_event_loop().time()
        if progress and progress != last_progress:
            logger.info("上传进度: %s", progress)
            last_progress = progress
            last_change = now
        elif state.get("readyHit") or state.get("busy"):
            # 就绪/忙碌状态本身也是活性信号，防止进度文本缺失时误判卡死
            last_change = now

        if state.get("readyHit") and not state.get("busy"):
            # 稳定判定：连续两次轮询都就绪，避免进度条消失瞬间的抖动
            await asyncio.sleep(1.0)
            state2 = await page.evaluate(_READY_JS,
                                         [config.UPLOAD_READY_SELECTORS,
                                          config.UPLOAD_BUSY_KEYWORDS,
                                          UPLOAD_FAIL_KEYWORDS])
            if state2.get("failHit"):
                raise RuntimeError(
                    f"页面显示上传失败（检测到文本“{state2['failHit']}”）")
            if state2.get("readyHit") and not state2.get("busy"):
                logger.info("上传/初始化完成（就绪标志: %s）", state.get("readyHit"))
                # 再给 React 表单一点渲染时间
                await asyncio.sleep(1.0)
                return

        # 2. 卡死检测：进度与状态长时间无变化
        if now - last_change > stall_limit:
            raise RuntimeError(
                f"上传疑似卡死：{stall_limit:.0f} 秒内进度无任何变化"
                f"（最后进度: {last_progress or '未读到'}）。"
                "请检查网络/带宽或账号状态后重试；大文件请先确认上传确实在推进")

        await asyncio.sleep(poll_interval)

    raise PWTimeoutError(
        f"等待上传完成超时（{timeout:.0f}s，最后进度: {last_progress or '未读到'}）。"
        "请检查网络/带宽，或在 config.TIMEOUT 中调大 "
        "'upload_complete'；大文件上传时间 ≈ 文件大小/带宽 + 转码缓冲。"
    )


async def upload_video(page: Page, file_path: str | Path,
                       timeout: float | None = None) -> None:
    """完整上传流程：校验 → 方案 A 注入（失败回退方案 B）→ 等待就绪。"""
    p = validate_video_file(file_path)

    ok = await inject_file_by_cdp(page, p)
    if not ok:
        logger.info("主通道不可用，回退系统对话框方案（方案 B）")
        ok = await inject_file_by_system_dialog(page, p)
    if not ok:
        raise RuntimeError("两种文件上传通道均失败：CDP 注入与系统对话框都未能投递文件")

    await wait_until_upload_ready(page, timeout)
