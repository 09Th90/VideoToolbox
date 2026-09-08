# -*- coding: utf-8 -*-
"""
模块一：浏览器启动与反检测配置（开发书 3.1 / R5 / R6）。

职责：
1. 以持久化 Context 方式启动 Chromium，复用已登录 Profile（R1）。
2. 通过启动参数 + init script 抹除自动化指纹（R6）。
3. 固定视口与缩放比例，保证 DOM 坐标与物理像素 1:1。
4. 提供基于 CDP Input.dispatchMouseEvent 的拟人鼠标移动/点击（R5，isTrusted=true）。
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
import signal
import subprocess
import sys
from pathlib import Path
from typing import Any

from playwright.async_api import (
    BrowserContext,
    Page,
    Playwright,
    async_playwright,
)

import config
from config import BROWSER_CONFIG, TIMING

logger = logging.getLogger(__name__)

# Global registry for active browser sessions (for cleanup on exit)
_active_sessions: list["BrowserSession"] = []


def _kill_stale_browser_processes() -> int:
    """杀掉残留的 chrome / msedge 进程，返回杀掉的进程数。

    历史上异常退出后常留下大量 zombie 进程持有 user_data_dir 锁，
    必须先清理才能再次启动 Playwright 持久化上下文。
    """
    killed = 0
    targets = ("chrome.exe", "msedge.exe", "chromium.exe")
    try:
        if sys.platform == "win32":
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            for name in targets:
                try:
                    out = subprocess.check_output(
                        ["tasklist", "/FI", f"IMAGENAME eq {name}",
                         "/FO", "CSV", "/NH"],
                        creationflags=flags,
                    ).decode("utf-8", errors="replace")
                except subprocess.CalledProcessError:
                    continue
                for line in out.splitlines():
                    line = line.strip()
                    if not line or line.startswith("INFO:"):
                        continue
                    parts = line.split('","')
                    if len(parts) < 2:
                        continue
                    try:
                        pid = int(parts[1].strip('"'))
                    except (ValueError, IndexError):
                        continue
                    try:
                        subprocess.run(
                            ["taskkill", "/F", "/PID", str(pid)],
                            creationflags=flags, check=False,
                            capture_output=True,
                        )
                        killed += 1
                    except Exception:  # noqa: BLE001
                        pass
        else:
            for name in ("chrome", "chromium", "msedge"):
                try:
                    out = subprocess.check_output(["pgrep", name]).decode()
                except subprocess.CalledProcessError:
                    continue
                for pid_s in out.split():
                    try:
                        os.kill(int(pid_s), 9)
                        killed += 1
                    except Exception:  # noqa: BLE001
                        pass
    except Exception as e:  # noqa: BLE001
        logger.debug("清理残留浏览器进程时出错（继续）: %s", e)
    if killed:
        logger.info("已清理 %d 个残留的浏览器进程", killed)
        # 给进程一点退出时间
        import time as _time
        _time.sleep(0.5)
    return killed


def _cleanup_stale_browser_locks(user_data_dir: str) -> None:
    """启动前清理：杀掉残留浏览器进程，移除过时的 lockfile / SingletonLock。

    必须在 launch_persistent_context 之前调用，否则
    "Target page, context or browser has been closed" 会反复出现。
    """
    _kill_stale_browser_processes()

    profile = Path(user_data_dir)
    if not profile.exists():
        return
    # Chrome 持久化上下文的锁文件：根目录的 lockfile / SingletonLock / SingletonCookie
    stale_files = ("SingletonLock", "SingletonCookie", "lockfile",
                   "DevToolsActivePort")
    for name in stale_files:
        for p in (profile / name, profile / "Default" / name):
            try:
                if p.exists():
                    p.unlink()
                    logger.info("已删除过时锁文件: %s", p)
            except OSError:
                pass
    # 尝试删除所有 *.lock 文件（SQLite / LevelDB 等）
    try:
        for lock in profile.rglob("*.lock"):
            try:
                lock.unlink()
            except OSError:
                pass
        for lock in profile.rglob("LOCK"):
            try:
                lock.unlink()
            except OSError:
                pass
    except OSError:
        pass


def _register_session(session: "BrowserSession") -> None:
    """Register a session for global cleanup."""
    _active_sessions.append(session)


def _unregister_session(session: "BrowserSession") -> None:
    """Unregister a session after it's been stopped."""
    if session in _active_sessions:
        _active_sessions.remove(session)


async def _cleanup_all_sessions() -> None:
    """Stop all active browser sessions. Called on exit signals."""
    for session in list(_active_sessions):
        try:
            await session.stop()
        except Exception as e:  # noqa: BLE001
            logger.warning("清理浏览器会话时出错: %s", e)


def _install_signal_handlers() -> None:
    """Install signal handlers for graceful shutdown."""
    if sys.platform == "win32":
        # Windows doesn't support SIGTERM/SIGINT in the same way
        # but we can still try to handle Ctrl+C
        try:
            import win32api

            def _win_handler(ctrl_type):
                if ctrl_type in (win32api.CTRL_C_EVENT, win32api.CTRL_BREAK_EVENT,
                                 win32api.CTRL_CLOSE_EVENT, win32api.CTRL_SHUTDOWN_EVENT):
                    # Schedule cleanup on the event loop
                    try:
                        loop = asyncio.get_event_loop()
                        if loop.is_running():
                            loop.create_task(_cleanup_all_sessions())
                        else:
                            asyncio.run(_cleanup_all_sessions())
                    except Exception:
                        pass
                    return True  # Indicate we handled it
                return False

            win32api.SetConsoleCtrlHandler(_win_handler, True)
        except Exception:
            # win32api not available, skip Windows-specific handler
            pass
    else:
        # Unix-like: SIGINT (Ctrl+C), SIGTERM (kill)
        def _signal_handler(signum, frame):
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    loop.create_task(_cleanup_all_sessions())
                else:
                    asyncio.run(_cleanup_all_sessions())
            except Exception:
                pass

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(sig, _signal_handler)
            except Exception:
                pass


# Install handlers on module import
_install_signal_handlers()

# Also register atexit as a last resort
# 重要：atexit 运行时主 event loop 已关闭，不能再 asyncio.run()，
# 否则 Playwright 子进程 transport 报"Event loop is closed"。
# 这里采用同步方式：直接调用 Session._pw.stop() 的同步部分，
# 必要时强杀残留的浏览器/驱动子进程。
import atexit
import subprocess as _sp


def _atexit_cleanup() -> None:
    """同步兜底清理：event loop 已关闭，只能强杀残留进程。"""
    if not _active_sessions:
        return
    try:
        # 先尝试优雅关闭（同步等待一小段时间）
        import threading
        done = threading.Event()

        def _runner():
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    loop.run_until_complete(_cleanup_all_sessions())
                finally:
                    loop.close()
            except Exception:  # noqa: BLE001
                pass
            finally:
                done.set()

        t = threading.Thread(target=_runner, daemon=True)
        t.start()
        done.wait(timeout=3.0)  # 最多等 3 秒

        # 如果还有残留，强制杀掉 chrome / playwright driver 进程
        for proc in _list_browser_processes():
            try:
                proc.kill()
            except Exception:  # noqa: BLE001
                pass
    except Exception:  # noqa: BLE001
        pass


def _list_browser_processes() -> list[Any]:
    """列出残留的浏览器/驱动进程，用于强杀。"""
    procs: list[Any] = []
    try:
        if sys.platform == "win32":
            # 通过 tasklist 查找 chrome / playwright / msedge
            out = _sp.check_output(
                ["tasklist", "/FO", "CSV", "/NH"],
                creationflags=getattr(_sp, "CREATE_NO_WINDOW", 0),
            ).decode("utf-8", errors="replace")
            targets = ("chrome.exe", "msedge.exe", "playwright", "chromium")
            for line in out.splitlines():
                name = line.split('","', 1)[0].lstrip('"').lower()
                if any(t in name for t in targets):
                    try:
                        pid = int(line.split('","', 1)[1].split('","', 1)[0].strip('"'))
                        procs.append(_FakeProc(pid))
                    except Exception:  # noqa: BLE001
                        pass
        else:
            # Unix: 用 pgrep 找 chrome / playwright
            try:
                out = _sp.check_output(["pgrep", "-f", "chrome|playwright|chromium"]).decode()
                for pid_s in out.split():
                    try:
                        procs.append(_FakeProc(int(pid_s)))
                    except Exception:  # noqa: BLE001
                        pass
            except Exception:  # noqa: BLE001
                pass
    except Exception:  # noqa: BLE001
        pass
    return procs


class _FakeProc:
    """最小进程接口，只提供 kill() 给 atexit 用。"""
    def __init__(self, pid: int) -> None:
        self.pid = pid

    def kill(self) -> None:
        try:
            if sys.platform == "win32":
                _sp.run(
                    ["taskkill", "/F", "/PID", str(self.pid)],
                    creationflags=getattr(_sp, "CREATE_NO_WINDOW", 0),
                    check=False,
                )
            else:
                import os as _os
                _os.kill(self.pid, 9)
        except Exception:  # noqa: BLE001
            pass


atexit.register(_atexit_cleanup)

# ---------------------------------------------------------------------------
# 反自动化指纹注入脚本：在每个文档、每个 frame 的任意页面脚本之前执行
# ---------------------------------------------------------------------------
ANTI_DETECT_SCRIPT = r"""
(function () {
    // 1. 移除 navigator.webdriver 标志
    try {
        Object.defineProperty(Navigator.prototype, 'webdriver', {
            get: () => undefined,
            configurable: true
        });
    } catch (e) {}

    // 2. 补全 window.chrome（无头环境缺失）
    if (!window.chrome) {
        window.chrome = { runtime: {}, app: {}, csi: () => {}, loadTimes: () => {} };
    }

    // 3. 语言 / 插件指纹
    try {
        Object.defineProperty(Navigator.prototype, 'languages', {
            get: () => ['zh-CN', 'zh'],
            configurable: true
        });
    } catch (e) {}
    try {
        Object.defineProperty(Navigator.prototype, 'plugins', {
            get: () => [
                { name: 'Chrome PDF Plugin' },
                { name: 'Chrome PDF Viewer' },
                { name: 'Native Client' }
            ],
            configurable: true
        });
    } catch (e) {}

    // 4. 权限查询伪装（Notification 等不应返回 denied 异常值）
    try {
        const origQuery = window.navigator.permissions
            && window.navigator.permissions.query.bind(window.navigator.permissions);
        if (origQuery) {
            window.navigator.permissions.query = (parameters) => (
                parameters && parameters.name === 'notifications'
                    ? Promise.resolve({ state: Notification.permission })
                    : origQuery(parameters)
            );
        }
    } catch (e) {}

    // 5. 锁定页面缩放：禁止 Ctrl+滚轮 / Ctrl +/-/0（开发书 3.1 关键措施）
    window.addEventListener('wheel', (e) => {
        if (e.ctrlKey) { e.preventDefault(); e.stopImmediatePropagation(); }
    }, { capture: true, passive: false });
    window.addEventListener('keydown', (e) => {
        if (e.ctrlKey && ['=', '-', '_', '+', '0'].includes(e.key)) {
            e.preventDefault();
            e.stopImmediatePropagation();
        }
    }, { capture: true });
})();
"""


class BrowserSession:
    """封装 Playwright 生命周期，对外只暴露 context / page。"""

    def __init__(self, browser_config: dict[str, Any] | None = None) -> None:
        self._pw: Playwright | None = None
        self._context: BrowserContext | None = None
        self.browser_config = browser_config or BROWSER_CONFIG

    # ---- 生命周期 --------------------------------------------------------
    async def start(self) -> tuple[Playwright, BrowserContext]:
        """启动持久化浏览器上下文，返回 (playwright, context)。"""
        cfg = self.browser_config

        # 启动前先清理可能残留的旧浏览器进程与锁文件
        # 历史上异常退出后常留下 chrome.exe / msedge.exe 僵尸进程，
        # 这些进程持有 user_data_dir 下的 lockfile，导致新进程无法启动
        _cleanup_stale_browser_locks(cfg["user_data_dir"])

        self._pw = await async_playwright().start()

        launch_kwargs: dict[str, Any] = {
            "user_data_dir": cfg["user_data_dir"],
            "headless": cfg["headless"],
            "args": list(cfg["args"]),
            "viewport": dict(cfg["viewport"]),
            "device_scale_factor": cfg["device_scale_factor"],
            "locale": cfg["locale"],
            "timezone_id": cfg["timezone_id"],
            # 给扩展/系统组件留足初始化时间，降低指纹异常
            "slow_mo": 10,
        }
        # 浏览器通道：显式配置则只用配置值；否则按 自带Chromium→Chrome→Edge 自动回退，
        # 保证打包后的程序在未额外下载浏览器的机器上也能运行
        configured_channel = cfg.get("channel")
        channel_candidates = [configured_channel] if configured_channel \
            else [None, "chrome", "msedge"]

        last_err: Exception | None = None
        for idx, channel in enumerate(channel_candidates):
            kwargs = dict(launch_kwargs)
            if channel:
                kwargs["channel"] = channel
            else:
                kwargs.pop("channel", None)
            try:
                logger.info("启动浏览器（通道: %s，Profile: %s）",
                            channel or "playwright-chromium", cfg["user_data_dir"])
                self._context = await self._pw.chromium.launch_persistent_context(**kwargs)
                logger.info("浏览器通道就绪: %s", channel or "playwright-chromium")
                break
            except Exception as e:  # noqa: BLE001
                last_err = e
                logger.warning("通道 %s 启动失败: %s", channel or "playwright-chromium", e)
                if idx < len(channel_candidates) - 1:
                    logger.info("自动回退到下一通道: %s",
                                channel_candidates[idx + 1] or "playwright-chromium")
        if self._context is None:
            raise RuntimeError(
                "所有浏览器通道均启动失败。请安装 Chrome/Edge，或执行 "
                "`python -m playwright install chromium`。最后错误: %s" % last_err
            )

        # 反检测脚本：对后续所有页面生效
        await self._context.add_init_script(ANTI_DETECT_SCRIPT)

        # 固定默认页面设置
        if self._context.pages:
            page = self._context.pages[0]
        else:
            page = await self._context.new_page()
        await page.set_viewport_size(cfg["viewport"])

        # 对已打开的页面立即注入一次（init script 只对之后的导航生效）
        try:
            await page.evaluate(ANTI_DETECT_SCRIPT)
        except Exception as e:  # noqa: BLE001
            logger.debug("初始页面注入反检测脚本失败（可忽略）: %s", e)

        logger.info("浏览器启动完成，视口固定为 %s，缩放 1:1", cfg["viewport"])
        _register_session(self)
        return self._pw, self._context

    async def stop(self) -> None:
        """关闭浏览器上下文与 Playwright 驱动。"""
        try:
            if self._context is not None:
                await self._context.close()
        except Exception as e:  # noqa: BLE001 - 关闭阶段异常不掩盖主流程结果
            logger.warning("关闭 Context 时出现异常: %s", e)
        finally:
            if self._pw is not None:
                await self._pw.stop()
            self._context = None
            self._pw = None
            logger.info("浏览器已关闭")
        _unregister_session(self)

    @property
    def context(self) -> BrowserContext:
        if self._context is None:
            raise RuntimeError("浏览器尚未启动，请先 await session.start()")
        return self._context

    async def new_page(self) -> Page:
        page = await self.context.new_page()
        await page.set_viewport_size(self.browser_config["viewport"])
        return page


# ---------------------------------------------------------------------------
# 拟人鼠标：底层即 CDP Input.dispatchMouseEvent，事件 isTrusted=true（R5）
# ---------------------------------------------------------------------------
async def _jitter(base: float) -> float:
    return random.uniform(TIMING["human_jitter_min"], TIMING["human_jitter_max"]) \
        if base <= 0 else base


async def human_move(page: Page, target_x: float, target_y: float,
                     steps: int = 12) -> None:
    """以贝塞尔式分段移动逼近目标坐标，模拟真人鼠标轨迹而非瞬移。"""
    mouse = page.mouse
    # Playwright 鼠标位置在首次 move 之前是未定义的，必须先初始化到视口内
    # 若之前没有任何 move，会从当前位置（通常是 0,0）出发；为安全起见先
    # 移动到视口中心，再开始贝塞尔动画
    try:
        vp = page.viewport_size or {"width": 1920, "height": 1080}
        # 显式初始化鼠标到视口中心，避免 CDP 报"mouse position undefined"
        await mouse.move(vp["width"] / 2, vp["height"] / 2)
        # 再随机偏移到目标附近，模拟"手从屏幕中央移到目标区域"
        start_x = target_x - random.randint(30, 100)
        start_y = target_y - random.randint(20, 60)
        await mouse.move(start_x, start_y)
    except Exception as e:  # noqa: BLE001
        logger.debug("鼠标初始化位置时出错（继续）: %s", e)
        start_x, start_y = target_x - random.randint(20, 80), target_y - random.randint(10, 40)

    for i in range(1, steps + 1):
        t = i / steps
        # 二次缓动 + 垂直方向轻微抖动
        ease = t * t * (3 - 2 * t)
        x = start_x + (target_x - start_x) * ease + random.uniform(-1.2, 1.2)
        y = start_y + (target_y - start_y) * ease + random.uniform(-1.2, 1.2)
        await mouse.move(x, y)
        await asyncio.sleep(random.uniform(0.008, 0.028))
    # 最终精确定位到目标
    await mouse.move(target_x, target_y)
    await asyncio.sleep(0.05)


async def human_click(page: Page, x: float, y: float, *,
                      move_steps: int = 12) -> None:
    """在指定视口坐标执行"移动 → 按下 → 微停顿 → 抬起"的真实点击序列。"""
    # 先把鼠标悬停到目标上 50-150ms，模拟真人"看到目标再点"的过程
    await human_move(page, x, y, steps=move_steps)
    await asyncio.sleep(random.uniform(0.05, 0.15))

    # 使用 page.mouse.click 而不是 down/up 组合：click 内部会自动派发
    # mousemove → mousedown → mouseup → click 完整事件链，兼容 B 站 React 组件
    try:
        await page.mouse.click(x, y, delay=random.randint(40, 110))
    except Exception as e:  # noqa: BLE001
        # 极少数 CDP 状态下 click 会失败，回退到 down/up
        logger.debug("page.mouse.click 失败，回退 down/up: %s", e)
        await page.mouse.down()
        await asyncio.sleep(random.uniform(0.04, 0.11))
        await page.mouse.up()
    logger.debug("拟人点击完成 @ (%.0f, %.0f)", x, y)


async def click_locator(page: Page, locator, *,
                        timeout: float = 10.0) -> None:
    """对 Locator 计算当前坐标后用 CDP 真实鼠标点击（自动处理动态位移）。"""
    await locator.wait_for(state="visible", timeout=int(timeout * 1000))
    await locator.scroll_into_view_if_needed()
    box = await locator.bounding_box()
    if not box:
        raise RuntimeError("无法获取元素坐标（元素可能已脱离布局）")
    await human_click(
        page,
        box["x"] + box["width"] / 2,
        box["y"] + box["height"] / 2,
    )


# ---------------------------------------------------------------------------
# 常驻浏览器会话管理器（v1.9.1）：
#   GUI 进程内单例，检测 / 投稿共用同一个浏览器窗口与登录态，
#   避免每次检测都重启浏览器（用户反馈：原设计错误）。
# ---------------------------------------------------------------------------
class BrowserManager:
    """常驻 BrowserSession 管理器。

    - 首次调用 ensure() 时启动浏览器（清理旧锁后启动 Playwright 持久化上下文）；
    - 之后所有检测 / 投稿复用同一个 session 和 page；
    - GUI 关闭时由 atexit 负责 stop。
    """

    _instance: "BrowserManager | None" = None
    _lock = asyncio.Lock()

    def __init__(self) -> None:
        self.session: BrowserSession | None = None
        self._page: Page | None = None
        self._lock2 = asyncio.Lock()  # 保护 start/stop

    @classmethod
    def instance(cls) -> "BrowserManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    async def ensure(self) -> tuple[BrowserSession, Page]:
        """确保浏览器已启动并返回一个可用 page（每次都返回同一个）。"""
        async with self._lock2:
            if self.session is not None and self._page is not None:
                # 检查 page 是否还活着
                try:
                    if not self._page.is_closed():
                        return self.session, self._page
                except Exception:  # noqa: BLE001
                    pass
                # page 死了，重启
                try:
                    await self.session.stop()
                except Exception:  # noqa: BLE001
                    pass
                self.session = None
                self._page = None

            self.session = BrowserSession()
            _, context = await self.session.start()
            self._page = (context.pages[0] if context.pages
                          else await context.new_page())
            logger.info("常驻浏览器会话已启动，复用 page: %s", self._page.url)
            return self.session, self._page

    async def stop(self) -> None:
        async with self._lock2:
            if self.session is not None:
                try:
                    await self.session.stop()
                except Exception as e:  # noqa: BLE001
                    logger.warning("关闭常驻浏览器失败: %s", e)
                self.session = None
                self._page = None

    @property
    def page(self) -> Page | None:
        return self._page

