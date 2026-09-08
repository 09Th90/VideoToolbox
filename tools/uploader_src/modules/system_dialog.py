# -*- coding: utf-8 -*-
"""
模块：系统级文件对话框处理（开发书 3.2 方案 B，备用通道）。

仅当网站使用非标准上传组件、CDP DOM.setFileInputFiles 无法注入时启用。
通过 PyAutoGUI 操控 Windows 原生“打开”对话框：
    Alt+N 聚焦“文件名(N)”输入框 → 写入完整路径 → 回车确认。

注意：
1. PyAutoGUI 会接管物理键盘鼠标，运行期间不要人工操作电脑（开发书 3.2 注意事项）。
2. pyautogui.typewrite 只能输入 ASCII，遇到中文路径会丢字；
   因此本模块统一走“剪贴板 + Ctrl+V”，对中英文路径都稳定。
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

logger = logging.getLogger(__name__)


def _copy_to_clipboard(text: str) -> None:
    """把文本写入系统剪贴板。优先 pyperclip，回退标准库 tkinter。"""
    try:
        import pyperclip  # type: ignore

        pyperclip.copy(text)
        return
    except ImportError:
        pass

    try:
        import tkinter as tk

        root = tk.Tk()
        root.withdraw()
        root.clipboard_clear()
        root.clipboard_append(text)
        root.update()  # 让剪贴板内容在窗口销毁后仍然保留
        root.destroy()
        return
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(
            "无法写入剪贴板：请安装 pyperclip（pip install pyperclip），"
            f"或确认 tkinter 可用。原始错误: {e}"
        ) from e


def _import_pyautogui():
    try:
        import pyautogui  # type: ignore
    except ImportError as e:
        raise RuntimeError(
            "未安装 pyautogui，无法使用系统对话框方案。请执行: pip install pyautogui"
        ) from e
    # 安全兜底：鼠标甩到屏幕四角可立即中止所有 PyAutoGUI 动作
    pyautogui.FAILSAFE = True
    # 每个动作后的暂停，给对话框留出响应时间
    pyautogui.PAUSE = 0.08
    return pyautogui


def handle_system_dialog(file_path: str | Path,
                         wait_dialog: float = 0.8,
                         typing_interval: float = 0.01) -> None:
    """在系统“打开文件”对话框弹出后，自动填入路径并确认。

    调用时机：先点击页面上传按钮，确认对话框弹出，再调用本函数。

    :param file_path: 要选择的本地文件绝对路径
    :param wait_dialog: 调用前额外等待对话框获得焦点的秒数
    :param typing_interval: 兜底键盘输入的逐键间隔
    """
    pg = _import_pyautogui()
    path = str(Path(file_path).resolve())
    if not Path(path).exists():
        raise FileNotFoundError(f"待上传文件不存在: {path}")

    logger.info("等待系统文件对话框弹出 (%.1fs)...", wait_dialog)
    time.sleep(wait_dialog)

    # Alt+N：聚焦 Windows 文件对话框的“文件名”输入框（开发书 3.2）
    pg.keyDown("alt")
    pg.press("n")
    pg.keyUp("alt")
    time.sleep(0.25)

    # 清空输入框残留内容
    pg.hotkey("ctrl", "a")
    time.sleep(0.05)

    ascii_only = all(ord(ch) < 128 for ch in path)
    if ascii_only:
        # 纯 ASCII 路径可直接逐键输入
        logger.info("通过键盘输入路径: %s", path)
        pg.typewrite(path, interval=typing_interval)
    else:
        # 含中文/非 ASCII 字符：剪贴板粘贴，避免 typewrite 丢字
        logger.info("路径含非 ASCII 字符，改用剪贴板粘贴: %s", path)
        _copy_to_clipboard(path)
        pg.hotkey("ctrl", "v")
    time.sleep(0.25)

    # 回车确认
    pg.press("enter")
    logger.info("已确认系统文件对话框")
    # 等待对话框关闭、页面收到文件
    time.sleep(0.5)


async def click_upload_and_fill_dialog(page, upload_trigger, file_path: str | Path,
                                       wait_dialog: float = 0.8) -> None:
    """组合动作：点击页面上传入口 → 立即用系统对话框自动填路径。

    :param page: Playwright Page
    :param upload_trigger: 触发文件对话框的 Locator（上传按钮/拖拽区）
    :param file_path: 本地文件路径
    """
    import asyncio

    logger.info("点击上传入口，准备走系统对话框方案")
    await upload_trigger.scroll_into_view_if_needed()
    # PyAutoGUI 为同步阻塞调用，放到线程中避免卡住事件循环
    await upload_trigger.click()
    await asyncio.to_thread(handle_system_dialog, file_path, wait_dialog)
