# -*- coding: utf-8 -*-
# @version 2.5.2
"""程序运行时环境总准备（数据目录迁移 / 引擎重定向 / 全链补丁挂载）（v2.3.1 拆分工程 · 自 video_toolbox.py 原样搬入）。

v2.3.1 拆分工程；域间依赖规则见 core/__init__.py。
"""

import tempfile
from core.shared.paths import _resolve_data_root
from core.shared.textio import configure_stdio_utf8

import os
import shutil

from core.shared.log import _vc_log
from core.shared.paths import (APP_DIR, DATA_DIR, DATA_ROOT,
                                DATA_ROOT_POINTER, LOGS_DIR, TMP_DIR,
                                TOOLS_DIR)
from core.shared.runtime import (VC_NAME, system_python,
                                  vc_bundled_resource_dir,
                                  vc_redirect_paths)
from core.shared.vcsettings import vc_settings_path

def prepare_runtime_env():
    """统一准备运行期环境（幂等，可重复调用）。

    0. diskcache 延迟化补丁（v1.11.0：省掉引擎导入时建 5 个缓存库的数秒）；
    1. 迁移字幕引擎在 C 盘的历史数据到数据根目录；
    2. 重定向字幕引擎的路径常量为数据根目录；
    3. 兜底确保临时目录指向数据根目录（不落系统 Temp）。
    在导入 videocaptioner *之前*调用；GUI 启动与自检都会走这里。

    2026-10-20 启动专项：每步前后留痕 logs/startup.log，供定位 frozen
    环境下哪一步被 _MEI 新文件的 AV 扫描拖慢（开发态全步合计 <0.2s，
    旧 frozen 构建实测 3.05s，劣化全在文件 I/O）。
    """
    import time as _t
    _t0 = _t.perf_counter()

    def _step(name, fn):
        try:
            fn()
        except Exception:
            pass
        _vc_log_step(f"prepare[{name}] {_t.perf_counter() - _t0:.2f}s")

    # 必须最先：任何 videocaptioner 导入之前替换 diskcache.Cache
    def _s0():
        from core.asr.runtime_patches import vc_lazy_cache_patch
        vc_lazy_cache_patch()
    _step("lazy_cache", _s0)
    # openai 惰性桩（2026-10-20）：引擎 UI 构建链顶层 `from openai import
    # OpenAI` 会整包拉入 openai（≈4.4s），而多数用户不走 OpenAI 通道。
    # 必须在任何 videocaptioner 导入之前装。
    def _s1():
        from core.asr.runtime_patches import vc_lazy_openai_patch
        vc_lazy_openai_patch()
    _step("lazy_openai", _s1)
    # ⚠️ 顺序不可调换：路径重定向必须早于任何会导入 videocaptioner 的补丁。
    # v1.14.1 的 pydub 补丁内部 `from videocaptioner.core.asr import whisper_cpp`
    # 会触发引擎 config 导入、把路径常量固化成 AppData 默认值；一旦它先跑，
    # vc_redirect_paths() 的「已导入即跳过」守卫就会放行，导致重定向整体失效
    # ——表现为资源/日志/缓存落回 C 盘、随包 assets 与 ffmpeg 定位全丢
    # （_selftest_vc 11 项失败即由此暴露）。
    _step("redirect_paths", vc_redirect_paths)
    # v1.14.1：转录时 pydub 裸调 ffprobe/ffmpeg 闪黑窗 → 子进程默认隐藏窗口
    def _s3():
        from core.asr.voiceprint import vc_pydub_nowindow_patch
        vc_pydub_nowindow_patch()
    _step("pydub_nowindow", _s3)
    # 翻译两补丁（路由钉死 + 去 AI）**不在这里装**（2026-10-20 启动优化）：
    # 它们要导入 videocaptioner.core.translate 链（冷缓存 ≈2s），而首个翻译
    # 任务最早也要用户点下按钮之后——改由 ensure_translate_patches() 在
    # 引擎预热线程末尾（模块已热，≈0）或 agent_cli 翻译命令开头装。
    # ASR 协议分发补丁**不在这里装**（2026-10-20 启动优化）：它要导入
    # videocaptioner.core.asr 链（冷缓存实测 1.55s），而转录必然晚于引擎
    # 界面就绪——改由预热线程末尾（模块已热）与 agent_cli transcribe 入口装。
    # 标准流统一 UTF-8 容错，避免 GBK 控制台打印生僻字/Emoji 时崩溃
    _step("stdio_utf8", configure_stdio_utf8)
    def _s5():
        from core.asr.runtime_patches import vc_migrate_legacy_data
        vc_migrate_legacy_data()
    _step("migrate_legacy", _s5)
    def _s6():
        # 引擎界面读盘前规整 settings.json：路径收进软件文件夹 + 注入全局 LLM
        from core.asr.runtime_patches import vc_prepare_settings_file
        vc_prepare_settings_file()
    _step("prepare_settings", _s6)
    def _s7():
        os.makedirs(TMP_DIR, exist_ok=True)
        os.environ["TEMP"] = TMP_DIR
        os.environ["TMP"] = TMP_DIR
        tempfile.tempdir = TMP_DIR
    _step("tmp_redirect", _s7)
    _step("cleanup_mei", _cleanup_mei_leftovers)


def _vc_log_step(msg):
    """prepare_runtime_env 的分步留痕（best-effort，写 logs/startup.log）。"""
    try:
        from core.shared.log import _append_log
        _append_log("startup.log", msg, dedup=False)
    except Exception:
        pass


# PyInstaller onefile 每次启动把打包内容解到 %TEMP%\_MEIxxxxxx，正常退出由
# 运行时自己删。但程序被强杀 / 崩溃 / 子进程继承句柄未释放时残留会永久留下，
# 且因为本程序把 TEMP 重定向到了 data/tmp（见上），残留集中砸在 data/tmp：
# 实测 29 个 _MEI 目录占 754MB。这里启动时做一次保守清理。
_MEI_KEEP_DAYS = 7


def _cleanup_mei_leftovers(tmp_dir=None, keep_days=_MEI_KEEP_DAYS):
    """删除 tmp_dir 下过期（mtime 早于 keep_days 天）的 PyInstaller `_MEI*` 残留目录。

    保守原则：
      - 当前进程正在用的 `sys._MEIPASS` 恒不删（路径比对 + 目录名双重判定）；
      - 判定依据是目录 **mtime**（_MEIPASS 解包会写入文件，mtime≈启动时刻）；
        mtime 读取失败一律按"不过期"处理，宁可留不误删；
      - 只删除以 `_MEI` 开头的目录，不碰任何文件与其它目录；
      - 单个目录删除失败静默跳过，不影响其它目录与调用方。
    返回 (删除数量, 释放字节数)，供自测断言。
    """
    import sys
    import time

    root = tmp_dir or TMP_DIR
    if not root or not os.path.isdir(root):
        return 0, 0
    # 当前进程的 _MEIPASS 必须排除：onefile 主进程正在用它
    protected = set()
    mei = getattr(sys, "_MEIPASS", None)
    if mei:
        try:
            protected.add(os.path.normcase(os.path.abspath(mei)))
        except OSError:
            pass
        protected.add(os.path.normcase(os.path.basename(mei)))

    deadline = time.time() - max(0, int(keep_days)) * 86400
    removed = freed = 0
    try:
        entries = list(os.scandir(root))
    except OSError:
        return 0, 0
    for ent in entries:
        try:
            if not ent.name.startswith("_MEI") or not ent.is_dir():
                continue
            if os.path.normcase(os.path.abspath(ent.path)) in protected:
                continue
            if os.path.normcase(ent.name) in protected:
                continue
            try:
                mtime = ent.stat().st_mtime
            except OSError:
                continue          # 拿不到时间就不动
            if mtime > deadline:
                continue          # 未过期（含当前进程刚解出的那份）
            size = _dir_size(ent.path)
            shutil.rmtree(ent.path, ignore_errors=True)
            if not os.path.isdir(ent.path):
                removed += 1
                freed += size
        except Exception:
            continue
    if removed:
        try:
            _vc_log("清理 PyInstaller 临时残留: %d 个目录 / %.1f MB"
                    % (removed, freed / 1048576.0))
        except Exception:
            pass
    return removed, freed


def _dir_size(path):
    """递归统计目录字节数（失败静默，仅用于日志展示）。"""
    total = 0
    for base, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(base, name))
            except OSError:
                pass
    return total


def data_root_info():
    """返回 (当前数据根目录, 是否为默认位置, 来源说明)，供界面展示。"""
    root = _resolve_data_root()
    if os.environ.get("VT_DATA_ROOT"):
        src = "环境变量 VT_DATA_ROOT"
    elif os.path.isfile(DATA_ROOT_POINTER):
        src = "用户自定义（data_dir.txt）"
    else:
        src = "默认（程序目录）"
    return root, os.path.abspath(root) == os.path.abspath(APP_DIR), src


def set_data_root(new_root, migrate=True):
    """切换数据根目录（写指针文件），返回 (是否成功, 说明文案)。

    只改指针文件，不立刻搬数据；migrate=True 时把当前 data/logs/tmp 下的内容
    尽量搬到新位置（同名不覆盖）。切换需重启程序后完全生效（路径常量在导入
    时已固化）。
    """
    try:
        new_root = os.path.abspath(str(new_root).strip().strip('"'))
    except OSError as e:
        return False, "路径无效：%s" % e
    if not new_root:
        return False, "路径为空"
    try:
        os.makedirs(new_root, exist_ok=True)
        # 探针：确认真的可写（避免只读盘/权限问题）
        probe = os.path.join(new_root, ".vt_write_test")
        with open(probe, "w", encoding="utf-8") as f:
            f.write("ok")
        os.remove(probe)
    except OSError as e:
        return False, "该位置不可写：%s" % e

    if os.path.abspath(new_root) == os.path.abspath(APP_DIR):
        # 切回默认：删掉指针文件
        try:
            if os.path.isfile(DATA_ROOT_POINTER):
                os.remove(DATA_ROOT_POINTER)
        except OSError as e:
            return False, "无法移除指针文件：%s" % e
        return True, "已切回默认位置（程序目录），重启后生效"

    try:
        with open(DATA_ROOT_POINTER, "w", encoding="utf-8") as f:
            f.write(new_root)
    except OSError as e:
        return False, "无法写入指针文件：%s" % e

    if migrate:
        moved, failed = _move_data_to(new_root)
        return True, "已切换，并迁移 %d 项数据%s，重启后生效" % (
            moved, ("（%d 项被占用未迁移）" % failed) if failed else "")

    return True, "已切换，重启后生效"


def _move_data_to(new_root):
    """把当前数据根下的 data/logs/tmp 内容搬到新根（同名不覆盖）。"""
    moved = failed = 0
    for sub in ("data", "logs"):
        src_dir = os.path.join(DATA_ROOT, sub)
        dst_dir = os.path.join(new_root, sub)
        if not os.path.isdir(src_dir):
            continue
        try:
            os.makedirs(dst_dir, exist_ok=True)
        except OSError:
            failed += 1
            continue
        for name in os.listdir(src_dir):
            s = os.path.join(src_dir, name)
            d = os.path.join(dst_dir, name)
            if os.path.exists(d):
                continue
            try:
                shutil.move(s, d)
                moved += 1
            except OSError:
                failed += 1
    return moved, failed




__all__ = [
    "prepare_runtime_env",
    "data_root_info",
    "set_data_root",
    "_cleanup_mei_leftovers",
]
