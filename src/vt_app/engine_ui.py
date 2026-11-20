# -*- coding: utf-8 -*-
# @version 3.1.2
"""引擎 UI 决策与后台预热（原 video_toolbox_qt.py 同名代码，逐字下沉）。

UI 视觉/交互补丁（品牌中性化、下拉收敛、声纹录入/多选/筛选、陈旧状态自愈、独立
转录回填、任务创建收字幕……）均已内建为各页显式逻辑，不再 monkey-patch 引擎。
后端（配置 / 任务工厂 / 线程 / 核心数据模型）仍走既有引擎，属档 A/B（P1~P2）。

安全兜底：自研 UI 不可导入或构造抛异常时，自动回退到引擎 UI，界面永不因替换打不开。
排障/对照：设环境变量 VT_ENGINE_UI=engine 强制走引擎旧路径。
"""
import os
import sys
import threading
import time

import video_toolbox as engine

from vt_app.boot import _perf_note

_ENGINE_UI_DECISION = None

#: 模块级引擎 UI 预热（2026-10-20 第三波）：在 main() 的 prepare 之后、建窗之前
#: 就起线程导入引擎 UI 树——原先由 SubtitlePage.prewarm 在首帧后才起，导入
#: （隔离实测 2.85s，真实环境因与主线程抢 GIL 达 14s）几乎全落在窗口出现之后。
_ENGINE_PREWARM = {"thread": None, "ok": False, "done": False, "t0": 0.0,
                   #: 界面侧模块（vt_engine_ui + 四个子界面）是否已导入完毕。
                   #: 与 done 分开：done 等整条预热（含后端补丁）结束，ui_ready
                   #: 一到就能构建界面——2026-10-21 实测后端补丁里的
                   #: ``videocaptioner.ui.task_factory`` 导入要 4.26s，没必要
                   #: 让首页任务框陪着等。
                   "ui_ready": False}


def _engine_prewarm_done():
    """引擎预热是否已完成（供延迟项判断能否开跑）。"""
    return bool(_ENGINE_PREWARM["done"])


def _engine_prewarm_work():
    """后台导入引擎 UI 树（分步埋点，便于下一轮按真实数据优化）。"""
    t0 = time.perf_counter()
    _ENGINE_PREWARM["t0"] = t0
    # 2026-10-21：先让首帧绘制落定再开跑。预热是纯 Python 的 CPU 密集导入，
    # 与首帧 paint 抢 GIL 会把「窗口可见」从亚秒级拖到秒级（历史实测 9.9s）。
    time.sleep(0.35)
    # 预热期间把 GIL 切换间隔再压细一档（1ms → 0.5ms）：主线程（事件循环、
    # 点击、重绘）能更频繁地拿回 GIL。代价是预热本身略慢，但用户体感优先
    # ——这正是「窗口出来了却点不动」的根源。结束/异常都恢复原值。
    try:
        sys.setswitchinterval(0.0005)
    except Exception:  # noqa: BLE001
        pass
    ok = False
    try:
        # 2026-10-21：`vc_asr_patch_apply()` **从开头移到末尾**。它内部
        # `from videocaptioner.ui import task_factory` 实测 **4.26s**（引擎
        # 后端任务工厂，含 asr_data 链），却与界面构建毫无关系——挡在
        # UI 导入之前，等于让首页任务框白等 4 秒。它只在「创建转录任务」
        # 时才被用到，用户点转录远晚于首帧。
        _home_cls, _setting_cls, is_self, _err = _resolve_engine_ui()
        _perf_note(f"prewarm[resolve] {time.perf_counter() - t0:.2f}s")
        if is_self:
            import vt_engine_ui  # noqa: F401
            _perf_note(f"prewarm[import vt_engine_ui] {time.perf_counter() - t0:.2f}s")
            # ⚠⚠ 2026-10-21（启动调度专项，本轮最大发现）：
            #   ``vt_engine_ui/__init__`` 是**惰性导出**——`import vt_engine_ui`
            #   只加载包壳，四个子界面模块要等主线程构造 HomeInterface 时才
            #   首次导入。实测 `TranscriptionInterface` 首次导入+构造 **7.86s**
            #   （含 openai/httpx 等链），整段压在主线程上：UI 心跳探针实测
            #   **单次占用 3391ms**，正是用户说的「窗口出来了但点不动」。
            #   这里在**后台线程**预先把四个子界面模块全部导入，主线程构建
            #   就退化成纯构造（全热时 HomeInterface 仅 0.20s）。
            from vt_engine_ui import (  # noqa: F401
                home_interface, task_creation_interface,
                transcription_interface, subtitle_interface,
                video_synthesis_interface)
            _perf_note(f"prewarm[import 子界面] {time.perf_counter() - t0:.2f}s")
            from vt_engine_ui import _seams
            _ = _seams.cfg
            _perf_note(f"prewarm[cfg] {time.perf_counter() - t0:.2f}s")
            _ = _seams.entities
            _perf_note(f"prewarm[entities] {time.perf_counter() - t0:.2f}s")
            # ASR 协议分发补丁：同样放在这里（引擎 ASR 链已热）。此前在
            # prepare_runtime_env 里装，冷缓存要 1.55s 压在建窗前。
            try:
                from core.asr.patches import vc_asr_protocol_patch
                vc_asr_protocol_patch()
                _perf_note(f"prewarm[asr protocol] {time.perf_counter() - t0:.2f}s")
            except Exception:  # noqa: BLE001
                pass
            # ⚠ 放行主线程构建的时机：**必须**在 asr protocol 补丁之后。
            #   `_build_engine` 里还会幂等地再调一次 vc_asr_protocol_patch()，
            #   若此刻预热线程正首次导入 core.asr.patches，主线程会卡在
            #   import 锁上——放到这里，主线程拿到的是已装好的补丁（零等待）。
            _ENGINE_PREWARM["ui_ready"] = True
            _perf_note(f"prewarm[ui_ready] {time.perf_counter() - t0:.2f}s")
            # 翻译两补丁在这里装（引擎模块已热，代价≈0）；必须在首个翻译
            # 任务之前——GUI 翻译由用户点击触发，远晚于此。
            try:
                from core.translate.route_patch import ensure_translate_patches
                ensure_translate_patches()
                _perf_note(f"prewarm[translate patches] {time.perf_counter() - t0:.2f}s")
            except Exception:  # noqa: BLE001
                pass
            # 后端 ASR 补丁放在最后（见本段开头注释：它要 4.26s 导入引擎
            # 任务工厂，与界面无关）。此时首页通常已构建完成。
            try:
                engine.vc_asr_patch_apply()
                _perf_note(f"prewarm[asr 后端补丁] {time.perf_counter() - t0:.2f}s")
            except Exception:  # noqa: BLE001
                pass
            ok = True
        else:
            try:
                engine.engine_ui_brand_patch()
            except Exception:  # noqa: BLE001
                pass
            import videocaptioner.ui.view.home_interface  # noqa: F401
            ok = True
    except Exception as _e:  # noqa: BLE001
        ok = False
        # 2026-10-20：失败必须留痕——静默 ok=False 会让调用方退回主线程
        # 同步导入（frozen 下冻结界面 ~10s），而日志里只有一行 import=fail，
        # 根因（哪个 import 抛的）永远查不到。
        try:
            import traceback as _tb
            _perf_note("prewarm 线程异常: "
                       + _tb.format_exc().replace("\n", " | ")[:1500])
        except Exception:
            pass
    # 恢复全局 GIL 切换间隔（见函数开头），再标记完成——顺序不能反：
    # 探针看到 done=True 时主线程可能立刻开始构建界面。
    try:
        sys.setswitchinterval(0.001)
    except Exception:  # noqa: BLE001
        pass
    _ENGINE_PREWARM["ok"] = ok
    _ENGINE_PREWARM["done"] = True
    _perf_note(f"prewarm 线程：import={'ok' if ok else 'fail'} "
               f"{time.perf_counter() - t0:.2f}s")


def _start_engine_prewarm():
    """启动（幂等）模块级引擎预热线程。"""
    if _ENGINE_PREWARM["thread"] is not None:
        return _ENGINE_PREWARM["thread"]
    t = threading.Thread(target=_engine_prewarm_work, daemon=True,
                         name="vc-prewarm")
    _ENGINE_PREWARM["thread"] = t
    t.start()
    # ⚠ 2026-10-21 实测**不要**调 _lower_thread_priority：
    #   降到 BELOW_NORMAL 后，机器上有其它进程（校准同步线程、用户自己的
    #   应用）抢 CPU 时，预热线程被 OS 严重饿死——实测导入从 1.97s 劣化到
    #   **8.05s**，首页占位文案要挂 8 秒。GIL 争用本来就已由 main() 的
    #   setswitchinterval(0.001) 压到 1ms 粒度，不需要再动线程优先级。
    #   （函数保留作应急开关，需要时可手动调用。）
    return t


def _engine_prewarm_probe():
    """启动调度器的「界面可构建」探针任务。

    返回 False = 还要等，调度器 64ms 后再问；返回 True = 可以构建了。
    比原先的 200ms 自轮询好在两点：① 不再每轮写一行 startup.log（实测
    1.97s 内写 9–10 行真实文件 IO）；② 完成瞬间就能被调度器感知，引擎界面
    的构建不会被固定 200ms 栅格拖后。

    ⚠ 判据是 ``ui_ready``（界面模块导入完毕）而不是 ``done``（整条预热结束）：
      后端 ASR 补丁要额外 4.26s，界面没必要陪等（2026-10-21）。
      线程已结束也算就绪（失败时不能让首页永远停在占位文案上）。
    """
    if _ENGINE_PREWARM["ui_ready"]:
        return True
    t = _ENGINE_PREWARM["thread"]
    return not (t is not None and t.is_alive())


def _lower_thread_priority(t, level=-1):
    """把后台预热线程降到 BELOW_NORMAL（Windows）。

    为什么做：预热线程是 CPU 密集的纯 Python 导入，会持续抢 GIL。GIL 本身是
    协作式释放（切换间隔已由 main() 的 ``setswitchinterval(0.001)`` 压到 1ms），
    降线程优先级**不会**缩短主线程单次等待，但能减少「后台线程长期占核、
    主线程被 OS 调度挤出」的概率——作用在那 2s 导入窗口，属中等偏小改善。

    ``level=-1`` 即 THREAD_PRIORITY_BELOW_NORMAL；失败全程静默（非 Windows、
    线程已退出、无权限都只是「没优化」，绝不影响启动）。
    """
    if os.name != "nt" or t is None or t.ident is None:
        return False
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
        # THREAD_SET_INFORMATION = 0x0020
        h = k32.OpenThread(0x0020, False, int(t.ident))
        if not h:
            return False
        try:
            return bool(k32.SetThreadPriority(h, int(level)))
        finally:
            k32.CloseHandle(h)
    except Exception:  # noqa: BLE001
        return False


def _resolve_engine_ui():
    """返回 (home_cls, setting_cls, is_self, err)；结果缓存，仅解析一次。"""
    global _ENGINE_UI_DECISION
    if _ENGINE_UI_DECISION is not None:
        return _ENGINE_UI_DECISION
    mode = (os.environ.get("VT_ENGINE_UI", "self") or "self").strip().lower()
    home_cls = setting_cls = None
    is_self = False
    err = None
    if mode != "engine":
        try:
            import vt_engine_ui
            if vt_engine_ui.self_ui_available():
                home_cls = vt_engine_ui.HomeInterface
                setting_cls = vt_engine_ui.SettingInterface
                is_self = True
            else:
                err = vt_engine_ui.self_ui_error()
        except Exception as e:  # noqa: BLE001
            err = f"{type(e).__name__}: {e}"
    if not is_self:
        try:
            from videocaptioner.ui.view.home_interface import HomeInterface as _EH
            from videocaptioner.ui.view.setting_interface import SettingInterface as _ES
            home_cls, setting_cls = _EH, _ES
        except Exception as e:  # noqa: BLE001
            err = (err + " | " if err else "") + f"engine fallback failed: {e}"
    _ENGINE_UI_DECISION = (home_cls, setting_cls, is_self, err)
    return _ENGINE_UI_DECISION