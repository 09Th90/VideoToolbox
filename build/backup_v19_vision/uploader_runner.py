# -*- coding: utf-8 -*-
"""
视频工具箱内置 B 站自动投稿引擎（完全自包含）。

由 GUI 子进程调用：python uploader_runner.py --task <任务JSON>
登录态存 工具箱\\tools\\uploader_profile（首次扫码），浏览器用内嵌
playwright + 内嵌 chromium（tools\\ms-playwright）；不依赖任何外部投稿程序。
"""

from __future__ import annotations

import sys
# 不在安装目录生成 __pycache__/*.pyc，保持程序文件夹整洁（必须在导入本地模块前设置）
sys.dont_write_bytecode = True

import argparse
import asyncio
import datetime as dt
import logging
from pathlib import Path

from playwright.async_api import Page, TimeoutError as PWTimeoutError

# 嵌入工具箱：以 tools/uploader_src 为包根（sys.path 注入本目录后
# `import config` 与 `from modules.xxx import` 均可解析）
_SRC_DIR = Path(__file__).resolve().parent
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

import config
from modules import ai_client
from modules.browser import BrowserManager, BrowserSession, human_click
from modules.form_engine import fill_all_forms
from modules.uploader import upload_video
from modules.vision_agent import VisionAgent

logger = logging.getLogger("bili-uploader")


# ---------------------------------------------------------------------------
# 日志
# ---------------------------------------------------------------------------
def setup_logging() -> Path:
    log_path = config.LOGS_DIR / f"run_{dt.datetime.now():%Y%m%d_%H%M%S}.log"
    fmt = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
    formatter = logging.Formatter(fmt, datefmt="%H:%M:%S")

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers.clear()

    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setFormatter(formatter)
    root.addHandler(fh)

    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(formatter)
    root.addHandler(sh)
    return log_path


async def save_failure_screenshot(page: Page | None, stage: str) -> Path | None:
    """任意阶段失败时截图留证，便于对照排查选择器/页面状态。"""
    if page is None:
        return None
    try:
        p = config.SCREENSHOT_DIR / f"{dt.datetime.now():%Y%m%d_%H%M%S}_{stage}.png"
        await page.screenshot(path=str(p), full_page=True)
        logger.info("已保存失败截图: %s", p)
        return p
    except Exception as e:  # noqa: BLE001
        logger.warning("截图失败: %s", e)
        return None


# ---------------------------------------------------------------------------
# 登录态确认（R1：复用 Profile；未登录则等待人工扫码，之后长期免登录）
# ---------------------------------------------------------------------------
async def ensure_logged_in(page: Page) -> None:
    async def on_login_page() -> bool:
        url = page.url.lower()
        return any(k in url for k in config.LOGIN_URL_KEYWORDS)

    if not await on_login_page():
        logger.info("登录态有效，直接进入投稿流程")
        return

    logger.warning("=" * 60)
    logger.warning("检测到未登录，请在弹出的浏览器窗口中手动扫码/验证登录。")
    logger.warning("登录成功后程序会自动继续，无需关闭浏览器（最长等待 %.0f 秒）。",
                   config.TIMEOUT["login_wait"])
    logger.warning("=" * 60)

    deadline = asyncio.get_event_loop().time() + config.TIMEOUT["login_wait"]
    while asyncio.get_event_loop().time() < deadline:
        await asyncio.sleep(2)
        if not await on_login_page():
            logger.info("检测到登录成功，等待页面稳定...")
            await asyncio.sleep(2)
            # 登录跳转后重新进入投稿页
            await page.goto(config.UPLOAD_URL,
                            timeout=int(config.TIMEOUT["page_goto"] * 1000),
                            wait_until="domcontentloaded")
            logger.info("已重新进入投稿页")
            return
    raise PWTimeoutError("等待手动登录超时")


# ---------------------------------------------------------------------------
# 封面：自动选择第一张候选封面（开发书运行流程第 7 步）
# ---------------------------------------------------------------------------
async def select_first_cover(page: Page, wait_seconds: float = 60.0) -> bool:
    logger.info("等待候选封面生成...")
    deadline = asyncio.get_event_loop().time() + wait_seconds
    while asyncio.get_event_loop().time() < deadline:
        for sel in config.COVER_ITEM_SELECTORS:
            loc = page.locator(sel)
            try:
                if await loc.count() > 0 and await loc.first.is_visible():
                    await loc.first.scroll_into_view_if_needed()
                    box = await loc.first.bounding_box()
                    if box:
                        await human_click(page,
                                          box["x"] + box["width"] / 2,
                                          box["y"] + box["height"] / 2)
                        logger.info("已选择第一张候选封面（%s）", sel)
                        await asyncio.sleep(0.5)
                        return True
            except Exception:  # noqa: BLE001
                continue
        await asyncio.sleep(2)
    logger.warning("等待候选封面超时，跳过自动选封面（可手动选择后程序会继续）")
    return False


# ---------------------------------------------------------------------------
# 提交：等待按钮可用 → CDP 真实鼠标点击（R5）
# ---------------------------------------------------------------------------
_SUBMIT_STATE_JS = r"""
(selectors) => {
    for (const sel of selectors) {
        const el = document.querySelector(sel);
        if (!el) continue;
        const s = window.getComputedStyle(el);
        const r = el.getBoundingClientRect();
        if (s.display === 'none' || s.visibility === 'hidden' || r.width === 0) continue;
        const disabled = !!(el.disabled)
            || el.classList.contains('disabled')
            || el.getAttribute('aria-disabled') === 'true'
            || /(^|\s)disabled(\s|$)/.test(el.className || '');
        return {
            found: true, disabled,
            x: r.x + r.width / 2, y: r.y + r.height / 2,
            text: (el.innerText || '').trim()
        };
    }
    return { found: false };
}
"""

_SUCCESS_KEYWORDS = ("投稿成功", "稿件投递成功", "已投稿", "投稿管理", "等待审核")


async def click_submit(page: Page) -> None:
    timeout = config.TIMEOUT["submit_enabled"]
    deadline = asyncio.get_event_loop().time() + timeout
    logger.info("等待“立即投稿”按钮变为可点击（最长 %.0f 秒）...", timeout)

    state = None
    while asyncio.get_event_loop().time() < deadline:
        state = await page.evaluate(_SUBMIT_STATE_JS, config.SUBMIT_SELECTORS)
        if state.get("found") and not state.get("disabled"):
            break
        await asyncio.sleep(2)
    else:
        raise PWTimeoutError("“立即投稿”按钮在超时时间内始终不可用，"
                             "请检查必填项（标题/创作声明/分区/标签等）是否完整")

    logger.info("按钮可点击（文本: %s），滚动至可见后用 CDP 鼠标事件提交",
                state.get("text"))
    for sel in config.SUBMIT_SELECTORS:
        loc = page.locator(sel).first
        try:
            if await loc.count() > 0:
                await loc.scroll_into_view_if_needed()
                break
        except Exception:  # noqa: BLE001
            continue

    await asyncio.sleep(0.5)
    # 重新取一次最新坐标（防止滚动/布局变化）
    state = await page.evaluate(_SUBMIT_STATE_JS, config.SUBMIT_SELECTORS)
    await human_click(page, state["x"], state["y"])
    logger.info("已点击“立即投稿”")


async def wait_submit_success(page: Page) -> bool:
    timeout = config.TIMEOUT["submit_success"]
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        body_text = ""
        try:
            body_text = (await page.locator("body").inner_text(timeout=3000))[:4000]
        except Exception:  # noqa: BLE001
            pass
        if any(k in body_text for k in _SUCCESS_KEYWORDS):
            logger.info("检测到投稿成功提示")
            return True
        if "platform/upload-manager" in page.url or "/platform/home" in page.url:
            logger.info("页面已跳转至投稿管理/首页，视为投稿成功")
            return True
        await asyncio.sleep(2)
    logger.warning("未在超时时间内检测到明确成功提示，请人工确认投稿结果")
    return False


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
# 阶段标识 → 展示文案（GUI 进度条 / 状态栏用；CLI 下仅写日志）
STAGE_LABELS: dict[str, str] = {
    "boot": "启动浏览器",
    "goto": "打开B站投稿页",
    "login": "登录确认",
    "upload": "上传视频",
    "detect": "现场检测分区",
    "cover": "选择封面",
    "form": "填写表单",
    "submit": "提交投稿",
    "success": "等待投稿结果",
    "done": "完成",
}


async def goto_upload_page(page: Page) -> None:
    """导航到B站投稿页（复用会话时每次任务开始前都会重新进入）。"""
    await page.goto(config.UPLOAD_URL,
                    timeout=int(config.TIMEOUT["page_goto"] * 1000),
                    wait_until="domcontentloaded")
    await page.wait_for_timeout(2500)


async def detect_and_match_zone(page: Page, agent: "VisionAgent | None",
                                task: dict) -> None:
    """现场检测分区列表并自动匹配任务分区（v1.9.1：先上传再检测）。

    上传视频进入投稿区后，用 AI 屏幕识别现场枚举分区下拉的全部选项，
    再把任务里的分区名匹配到精确的现场名称后回填任务——投稿不再依赖
    预先点「检测分区」按钮产生的缓存列表（检测按钮仍可单独使用）。

    匹配失败时的行为：正式投稿 → 抛错终止（避免填完表单卡在提交按钮）；
    预览模式 → 记录警告继续（表单填完后可在浏览器中人工选择分区）。
    """
    from modules import catalog

    zone_name = str(task.get("zone") or "").strip()
    formal = bool(task.get("submit", True))

    if agent is None:
        logger.info("AI 屏幕识别未启用，跳过现场分区检测（分区按任务名直接选择）")
        if not zone_name and formal:
            raise RuntimeError("任务未指定分区名，无法完成投稿（AI 未启用时也"
                               "无法现场检测分区，请填写分区名或启用 AI）")
        return

    stage_label = "现场检测分区列表（上传完成后自动进行）"
    logger.info("%s", stage_label)
    try:
        areas = await catalog.detect_live_areas(page, agent)
    except Exception as e:  # noqa: BLE001
        if formal:
            raise RuntimeError(f"现场检测分区列表失败: {e}") from e
        logger.warning("现场检测分区列表失败（预览模式继续，请人工选择分区）: %s", e)
        return

    names = [a.get("name") for a in areas if a.get("name")]
    logger.info("现场检测到分区 %d 个: %s", len(names), names)

    if not zone_name:
        if formal:
            raise RuntimeError(
                f"任务未指定分区名，无法完成投稿；现场检测到: {names}")
        logger.warning("任务未指定分区（预览模式继续，请在浏览器中手动选择分区）")
        return

    matched = catalog.match_zone_name(zone_name, names)
    if matched:
        if matched != zone_name:
            logger.info("任务分区「%s」已匹配现场分区「%s」", zone_name, matched)
        else:
            logger.info("任务分区「%s」与现场分区完全一致", matched)
        task["zone"] = matched
        config.FIELD_CONFIG["zone"]["value"] = matched
        return

    msg = (f"现场分区列表中未找到「{zone_name}」；检测到 {len(names)} 个分区: "
           f"{names}。请修改分区名后重试（可点「检测/刷新分区列表」核对）")
    if formal:
        raise RuntimeError(msg)
    logger.warning("%s（预览模式继续，请在浏览器中手动选择分区）", msg)


async def run(*, session: BrowserSession | None = None,
              page: Page | None = None,
              use_browser_manager: bool = False,
              on_stage=None) -> int:
    """执行一次完整投稿流程。

    :param session: 复用的浏览器会话（GUI 常驻模式传入；None 则自建并随流程关闭）
    :param page: 复用会话中的页面（与 session 同时传入）
    :param use_browser_manager: True 时从 BrowserManager 单例获取常驻会话（GUI 主进程内）
    :param on_stage: 阶段回调 on_stage(key, text)，用于 GUI 进度展示
    """
    def stage(key: str) -> None:
        if on_stage is not None:
            try:
                on_stage(key, STAGE_LABELS.get(key, key))
            except Exception:  # noqa: BLE001 - 回调异常不影响主流程
                pass

    task = config.UPLOAD_TASK
    logger.info("本次投稿任务: 视频=%s | 标题=%s | 标签=%s | 分区=%s | "
                "创作声明=%s | 话题=%s | 最终提交=%s",
                task["video_path"], task["title"], task["tags"],
                task["zone"], task.get("declaration") or "(自动)",
                task.get("topics") or "(无)", task["submit"])

    if not Path(task["video_path"]).exists():
        logger.error("视频文件不存在: %s（请用 --video 或任务 JSON 指定正确路径）",
                     task["video_path"])
        return 2

    own_session = session is None
    if own_session and not use_browser_manager:
        session = BrowserSession()
    elif page is None:
        raise ValueError("复用浏览器会话时必须同时提供 page")

    stage_name = "init"
    try:
        if own_session and not use_browser_manager:
            stage("boot")
            _, context = await session.start()
            page = context.pages[0] if context.pages else await context.new_page()
        elif use_browser_manager:
            stage("boot")
            session, page = await BrowserManager.instance().ensure()

        # AI 屏幕识别代理（简介填写 / 分区选择等用；未启用或初始化失败时为 None，
        # 相关字段自动回退旧 DOM 通道，不影响投稿流程）
        agent: VisionAgent | None = None
        if ai_client.is_enabled():
            try:
                agent = VisionAgent(page)
                logger.info("AI 屏幕识别已启用（视觉模型: %s，接口: %s；文本模型: %s）",
                            agent.client.vision_model, agent.client.vision_url,
                            agent.client.model)
            except Exception as e:  # noqa: BLE001
                logger.warning("AI 屏幕识别初始化失败，本次运行回退 DOM 通道: %s", e)
        else:
            logger.info("AI 屏幕识别未启用（--no-ai 或 data\\ai_config.json enabled=false），"
                        "全部字段走 DOM 通道")

        # 3. 导航投稿页（复用会话时也会重新进入，保证表单是干净状态）
        stage_name = "goto"
        stage("goto")
        logger.info("打开投稿页: %s", config.UPLOAD_URL)
        await goto_upload_page(page)

        # 登录态确认
        stage_name = "login"
        stage("login")
        await ensure_logged_in(page)

        # 4. 上传视频并等待就绪
        stage_name = "upload"
        stage("upload")
        await upload_video(page, task["video_path"])

        # 7. 选择封面
        if task.get("auto_select_cover", True):
            stage_name = "cover"
            stage("cover")
            await select_first_cover(page)

        # 5.5 现场检测分区并自动匹配（v1.9.1：先上传视频进入投稿区，再检测）
        stage_name = "detect"
        stage("detect")
        await detect_and_match_zone(page, agent, task)

        # 5/6. 智能表单填写（标题/创作声明/分区/标签/话题/简介，对齐B站页面字段；
        #      简介与分区选择优先走 AI 屏幕识别 + 模拟鼠标/键盘）
        stage_name = "form"
        stage("form")
        results = await fill_all_forms(page, agent=agent)
        for name, res in results.items():
            if isinstance(res, dict) and res.get("ok") is False and "error" in res:
                logger.error("字段 %s 填写失败: %s", name, res["error"])

        # 提交前最后停顿，模拟人工检查
        await asyncio.sleep(1.5)

        # 8. 提交
        if task.get("submit", True):
            stage_name = "submit"
            stage("submit")
            await click_submit(page)
            stage_name = "success"
            stage("success")
            await wait_submit_success(page)
        else:
            logger.info("submit=False（预览模式）：表单已填完，未点击“立即投稿”。"
                        "可在浏览器中人工确认后手动提交。")
            # 复用会话（GUI 常驻浏览器）时页面保持原样即可，不做倒计时；
            # CLI 自建会话时保留浏览器一段时间供人工检查
            if own_session:
                hold = config.TIMING.get("dry_run_hold", 30.0)
                if hold > 0:
                    await asyncio.sleep(hold)

        stage("done")
        logger.info("全流程执行结束")
        return 0

    except Exception as e:  # noqa: BLE001
        logger.exception("流程在阶段 [%s] 失败: %s", stage_name, e)
        await save_failure_screenshot(page, stage_name)
        return 1
    finally:
        # 仅关闭本流程自建的会话；GUI 复用的常驻会话（own_session=False 或
        # use_browser_manager=True）保持打开
        if own_session and not use_browser_manager:
            await session.stop()


# ---------------------------------------------------------------------------
# 命令行参数
# ---------------------------------------------------------------------------
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="视频工具箱内置 B 站投稿引擎")
    parser.add_argument("--task", type=str,
                        help="投稿任务 JSON（工具箱生成）")
    # —— 分区/话题/合集检测模式：不投稿，只检测并把结果写入 --out JSON ——
    parser.add_argument("--catalog", choices=["areas", "topics", "collections"],
                        help="检测模式：areas=单级分区列表；topics=指定分区下的话题列表；"
                             "collections=当前账号合集列表")
    parser.add_argument("--out", type=str, help="检测结果 JSON 输出路径")
    parser.add_argument("--video", type=str,
                        help="视频文件绝对路径（areas/topics 必填，collections 可选）")
    parser.add_argument("--zone", type=str, help="两级分区，用 / 分隔，如 游戏/电子竞技")
    parser.add_argument("--title", type=str, help="稿件标题")
    parser.add_argument("--description", type=str, help="稿件简介")
    parser.add_argument("--tags", type=str, help="标签，英文逗号分隔，如 '标签1,标签2'")
    parser.add_argument("--no-cover", action="store_true", help="不自动选择候选封面")
    parser.add_argument("--no-submit", action="store_true",
                        help="只填写不提交（等价 dry-run，便于调试）")
    parser.add_argument("--headless", action="store_true", help="无头模式（调试稳定后使用）")
    parser.add_argument("--no-ai", action="store_true",
                        help="禁用 AI 屏幕识别（本次运行全部走 DOM 通道）")
    return parser.parse_args()


def apply_args(args: argparse.Namespace) -> None:
    if args.task:
        task = config.load_task_file(args.task)
        logger.info("已加载任务文件: %s（标题=%s）", args.task, task.get("title"))

    overrides: dict = {}
    if args.video:
        overrides["video_path"] = args.video
    if args.title:
        overrides["title"] = args.title
    if args.description:
        overrides["description"] = args.description
    if args.tags is not None:
        overrides["tags"] = [t.strip() for t in args.tags.split(",") if t.strip()]
    if args.zone:
        overrides["zone"] = [z.strip() for z in args.zone.split("/")] \
            if "/" in args.zone else args.zone
    if args.no_cover:
        overrides["auto_select_cover"] = False
    if args.no_submit:
        overrides["submit"] = False
    if args.headless:
        config.BROWSER_CONFIG["headless"] = True
    config.apply_cli_overrides(**overrides)


async def run_catalog(kind: str, out_path: str | None,
                      zone: str | None, video: str | None) -> int:
    """分区/话题/合集检测模式：抓取后写 JSON（--out）并向 stdout 打印 CATALOG_JSON 行。"""
    import json
    from modules import catalog

    if kind == "areas":
        if not video or not Path(video).exists():
            raise SystemExit(
                "areas 检测必须用 --video 指定已存在的视频文件"
                "（B 站上传视频后才进入投稿区，需先上传再取分区）")

        async def _detect(session, page):
            agent = _make_agent(page)
            return await catalog.fetch_areas(video_path=video, session=session,
                                             page=page, close_after=False,
                                             agent=agent)
        areas = await _with_own_session(_detect)
        payload = {"kind": "areas", "areas": areas}
    elif kind == "collections":
        video_arg = video if (video and Path(video).exists()) else None

        async def _detect(session, page):
            return await catalog.fetch_collections(video_path=video_arg,
                                                   session=session, page=page,
                                                   close_after=False)
        collections = await _with_own_session(_detect)
        payload = {"kind": "collections", "collections": collections}
    else:
        if not zone:
            raise SystemExit("topics 检测必须用 --zone 指定分区")
        if not video or not Path(video).exists():
            raise SystemExit("topics 检测必须用 --video 指定已存在的视频文件")
        steps = [z.strip() for z in zone.split("/") if z.strip()]

        async def _detect(session, page):
            agent = _make_agent(page)
            return await catalog.fetch_topics_for_zone(
                steps, video, session=session, page=page,
                close_after=False, agent=agent)
        topics = await _with_own_session(_detect)
        payload = {"kind": "topics", "zone": steps, "topics": topics}

    saved = catalog.save_cache(kind, payload, payload.get("zone"))
    if out_path:
        Path(out_path).write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                                  encoding="utf-8")
        saved = out_path
    print("CATALOG_JSON=" + json.dumps(payload, ensure_ascii=False))
    print("CATALOG_SAVED=" + str(saved))
    return 0


def _make_agent(page: Page) -> VisionAgent | None:
    """检测模式的 AI 屏幕识别代理（未启用时返回 None，走兜底通道）。"""
    if not ai_client.is_enabled():
        return None
    try:
        agent = VisionAgent(page)
        logger.info("AI 屏幕识别已启用（视觉模型: %s）", agent.client.vision_model)
        return agent
    except Exception as e:  # noqa: BLE001
        logger.warning("AI 屏幕识别初始化失败，本次检测走 DOM 兜底通道: %s", e)
        return None


async def _with_own_session(detect) -> object:
    """自建浏览器会话执行一次检测函数 detect(session, page)，结束后关闭。"""
    session = BrowserSession()
    _, context = await session.start()
    page = context.pages[0] if context.pages else await context.new_page()
    try:
        return await detect(session, page)
    finally:
        await session.stop()


def main() -> None:
    log_path = setup_logging()
    args = parse_args()
    if args.no_ai:
        ai_client.set_enabled(False)
    # 分区/话题检测模式（无需任务 JSON）
    if args.catalog:
        if args.headless:
            config.BROWSER_CONFIG["headless"] = True
        logger.info("检测模式: %s，日志: %s", args.catalog, log_path)
        rc = asyncio.run(run_catalog(args.catalog, args.out, args.zone, args.video))
        sys.exit(rc)
    if not args.task:
        logger.error("未指定 --task 任务文件，也未指定 --catalog 检测模式")
        sys.exit(2)
    apply_args(args)
    logger.info("日志文件: %s", log_path)
    exit_code = asyncio.run(run())
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
