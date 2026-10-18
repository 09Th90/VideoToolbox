# -*- coding: utf-8 -*-
# @version 2.3.1
"""核心单体拆分 · 接口契约测试（**先立测试，再动刀**）。

为什么需要（v2.3.1 → 拆分工程）：
    ``src/video_toolbox.py`` 是 9221 行的单体，扛着下载/转录/翻译/校准/流水线
    五大职责（外加共享底座）。拆分的目标架构是 ``src/core/<域>/`` 六个包，
    原文件退化为 **facade**（薄再导出层）——GUI、agent_cli、pipeline 等所有
    调用方的 ``import video_toolbox`` 一根线都不许动。

    本测试就是那根「不许动」的桩：
      1. **公开符号基线**（AST 快照 → ``_golden/core_api.json``）：150 个公开
         函数 + 模块级常量，拆分后必须同名、同签名、同值；
      2. **DOMAIN_MAP**（本文件内置）：每个公开符号的域归属——它同时是拆分
         执行的「施工清单」，并与 AST 实际符号集互相校验（漏映射即 FAIL）；
      3. **行为抽查**：对无副作用纯函数钉死输入/输出，搬家不许变味；
      4. **进度档**（SPLIT_STATUS）：某域标记 ``done`` 后，强制断言
         core 子包可导入、``__all__`` 覆盖该域全部符号、facade 里该符号
         只剩再导出（无函数体）、且 **core 引擎层禁止 import Qt/qfluentwidgets**
         （负向：引擎层混进 GUI 依赖 = 打包时 hiddenimports 静默失效的同款病）。

用法（程序根为 cwd）：
    VT_NO_SYNC=1 tools\\python\\python.exe scripts\\dev\\_selftest_core_api.py
    tools\\python\\python.exe scripts\\dev\\_selftest_core_api.py --rebase   # 刻意变更公开 API 后重打基线

退出码：0 = PASS；1 = FAIL。
"""
import ast
import inspect
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
SRC = os.path.join(ROOT, "src")
CORE = os.path.join(SRC, "core")
GOLDEN = os.path.join(HERE, "_golden", "core_api.json")
MONOLITH = os.path.join(SRC, "video_toolbox.py")

sys.path.insert(0, SRC)

# ---------------------------------------------------------------------------
# 域归属施工清单（150 个公开符号 → 六域）
# 六域 = 用户指定五域（download/asr/translate/calibrate/pipeline）+ shared 底座。
# shared 收「被多域共用的基础设施」：文本编解码、进程/代理/cookie 之外的运行时、
# vc 引擎嵌入胶水、AI 通道（calib_ai_agent/auto_vision 共用）、配置存取。
# 改这个映射 = 改施工图，必须同步改拆分实现，否则覆盖性自检会红。
# ---------------------------------------------------------------------------
DOMAIN_MAP = {
    "shared": [
        "decode_bytes_any", "read_text_any", "write_text_utf8",
        "decode_process_output", "configure_stdio_utf8",
        "app_icon_path", "system_python", "worker_subprocess_env",
        "run_process", "popen_process", "kill_process_tree", "sleep_cancellable",
        "ensure_builtin_proxy", "ytdlp_proxy_args", "translate_session_proxies",
        "proxy_status", "get_proxy_yaml", "set_proxy_yaml",
        "vc_importable", "vc_missing_deps", "vc_env_ready", "vc_state",
        "vc_data_dir", "vc_bundled_resource_dir", "vc_redirect_paths",
        "vc_settings_path", "apply_global_llm_to_engine",
        "data_root_info", "set_data_root", "prepare_runtime_env",
        "load_config", "save_config", "get_saved_download_dir",
        "set_saved_download_dir", "engine_ui_brand_patch",
        "ai_mod", "ai_detect_language", "ai_load_config", "ai_match_settings",
        "ai_plan_risk", "ai_plan_risks", "ai_save_config", "ai_last_auto_notes",
        "ai_test_connection", "ai_test_asr",
        # clean_path：A1 拆 download 时发现它被 shared/config 的
        # set_saved_download_dir/set_proxy_yaml 依赖（下载域→shared 依赖倒置），
        # 随 shared/paths 先行托管；DOMAIN_MAP 随之改登记（施工图追认现实）。
        "clean_path",
        # proxy_group_now/proxy_node_delays/pick_best_proxy_node/proxy_lock_*
        # 五符号：DOMAIN_MAP 初版登记在 download，但 A1 切 shared/proxy_c 段时
        # 已随代理节点锁定家族搬入 shared（yt-dlp/翻译共用）。此处追认移域。
        "proxy_group_now", "proxy_node_delays", "pick_best_proxy_node",
        "proxy_lock_acquire", "proxy_lock_release",
        # 2026-10-17 通用化（换设备/换系统仍可用）新增：控制口发现与诊断族。
        # proxy_note_eof 把「EOF 是链接作废、正在重新提取」说给用户听；
        # proxy_lock_status/ctl_base/egress_ip 供 GUI 与 CLI 一次说清现状。
        "proxy_lock_status", "proxy_ctl_base", "proxy_egress_ip",
        "proxy_note_eof",
    ],
    "download": [
        "ensure_ytdlp", "ensure_ffmpeg", "ensure_mpv_dll",
        "format_size", "format_time", "open_folder",
        "extract_url", "extract_web_url", "ytdlp_sub_langs",
        "ytdlp_prefer_hls", "ytdlp_part_leftovers", "ytdlp_error_retryable",
        "ytdlp_err_brief",
        # 2026-10-17：EOF/TLS 断连属「链接作废、必须重新提取」，与上面的
        # retryable（值不值得原地再试）分工不同——单独判定。
        "ytdlp_error_needs_reextract",
        # 2026-10-17 监控后新增：分片并发可调（VT_YTDLP_FRAGMENTS 覆盖）。
        # ytdlp_dl_args 取代码里 YTDLP_DL_COMMON_ARGS 常量的位置——常量改为
        # 函数是为了让环境变量改动即时生效，不必重启进程。
        "ytdlp_concurrent_fragments", "ytdlp_dl_args",
        "ytdlp_cookie_args",
        "cookie_mode", "cookie_browser", "cookie_file", "cookies_file_status",
        "browser_cookie_probe", "cookie_load_failure_reason",
        "browser_user_data_dir", "browser_exe_path", "browser_app_bound_enabled",
        "browser_cookie_diagnose", "write_netscape_cookies",
        "export_browser_cookies_via_cdp", "invalidate_cookie_cache",
        "fetch_info_json", "parse_qualities", "save_info_json",
        "sanitize_folder_name", "unique_folder",
        "npe_engine_mode", "npe_available", "npe_proxy_url",
        # proxy_group_now/proxy_node_delays/pick_best_proxy_node/
        # proxy_lock_acquire/proxy_lock_release 已移 shared（A1 追认）。
        "npe_cookie_file",
        "output_template", "hls_alt_format", "write_info_txt",
        "make_cover_1280x720", "probe_qualities", "download_mode",
        "get_duration", "probe_audio_codec", "calib_media_for_srt",
        "scan_media", "get_base_name", "find_subtitle",
        "smart_pair", "merge_pair", "merge_mode",
    ],
    "asr": [
        "asr_local_override", "apply_asr_to_engine", "vc_asr_patch_apply",
        "vc_pydub_nowindow_patch", "voiceprint_enabled_names",
        "voiceprint_filter_subtitle", "vc_transcribe_ui_patch",
        "is_realtime_asr_family", "is_dashscope_native_asr",
        "asr_model_hard_guard", "asr_strip_endpoint_tail", "asr_protocol_fix",
        "asr_base_guard", "asr_model_guard", "asr_protocol_of",
        "asr_diarize_of", "asr_separate_of", "asr_examples",
        "asr_examples_text", "asr_instance_models", "asr_missing_model_hint",
        "is_domestic_ai_endpoint", "http_proxies_for",
        "vc_asr_protocol_patch", "vc_asr_chunk_patch", "asr_non_zh_en_ratio",
        "vc_lazy_cache_patch", "vc_prepare_settings_file",
        "vc_enforce_runtime_cfg", "vc_migrate_legacy_data", "vc_legacy_leftovers",
    ],
    "translate": [
        "vc_translate_route_patch",
    ],
    "calibrate": [
        "calib_ai_chat", "calib_web_proxy", "calib_ai_run",
        "calib_sync_enabled", "set_calib_sync_enabled",
        "sync_calib_to_github", "sync_calib_push_local",
        "sync_calib_on_startup", "sync_calib_on_exit",
        "sync_voiceprint_on_startup", "sync_voiceprint_on_exit",
        # sync_env_into：A3-2 追认自 shared 移入（与同步家族物理同段，
        # 出身子进程同步环境注入）。施工图追认现实，同 clean_path 先例。
        "sync_env_into",
    ],
    "pipeline": [
        "main", "srt_time_to_ms", "ms_to_srt_time", "normalize_rolling_srt",
    ],
}

#: 拆分进度档。某域施工完成并自检全绿后改 "done"——随后本测试对该域启用
#: 严格断言（core 子包可导入 / __all__ 覆盖 / facade 只剩再导出）。
SPLIT_STATUS = {d: "pending" for d in DOMAIN_MAP}
SPLIT_STATUS["download"] = "done"  # v2.3.1 A1：56 符号 + 15 常量全量搬入
SPLIT_STATUS["asr"] = "done"       # v2.3.1 A2：31 符号全量搬入（A2a+A2b）
SPLIT_STATUS["translate"] = "done"  # v2.3.1 A3-1：1 符号（route_patch，含 10-17 双重保险增强）
SPLIT_STATUS["calibrate"] = "done"   # v2.3.1 A3-2：16 符号 + sync_env_into 追认移域（shared→calibrate）
SPLIT_STATUS["pipeline"] = "done"    # v2.3.1 A3-3：4 符号（rolling 3 + main 编排层）
SPLIT_STATUS["shared"] = "done"     # v2.3.1 A3-4：55 符号（含用户 10-17/18 新增 7 个）全量在册

#: 常量基线只快照这些类型（dict/set 等运行期缓存会变，不钉）
_CONST_TYPES = (str, int, float, bool, tuple, list, frozenset)

#: 行为抽查：函数名 -> (args, kwargs, 期望值)。期望值于 v2.3.1 未拆分代码实测。
BEHAVIOR_CASES = [
    ("format_size", (0,), {}, "0.00 B"),
    ("format_size", (1536,), {}, "1.50 KB"),
    ("format_time", (3725.5,), {}, "1:02:05.500"),
    ("format_time", (45,), {}, "00:45.000"),
    ("srt_time_to_ms", ("00:01:02,500",), {}, 62500),
    ("ms_to_srt_time", (62500,), {}, "00:01:02,500"),
    ("sanitize_folder_name", ("a/b:c*d?",), {}, "a b c d"),
    ("get_base_name", ("/a/b/c.srt",), {}, "c"),
    ("extract_web_url",
     ("看这个 https://www.bilibili.com/video/BV1xx 好了",), {},
     "https://www.bilibili.com/video/BV1xx"),
]

#: core 引擎层禁止出现的 GUI 依赖（负向桩：引擎层混入 Qt = hiddenimports 静默失效病）
_GUI_FORBIDDEN = ("qfluentwidgets", "PySide6", "PyQt5", "PyQt6")


def _public_symbols():
    """AST 提取 facade 的公开**函数**符号（排序去重）。

    v2.3.1 起 video_toolbox.py 是 facade：未拆域的函数体仍在本文件
    （FunctionDef），已拆域的公开函数来自 ``from core.<域> import ...``
    的**显式**再导出（ImportFrom）。两种来源都算公开 API——常量另走
    constants 基线（经 ``from core.shared import *`` 进来，AST 不可见）。
    """
    with open(MONOLITH, encoding="utf-8") as f:
        tree = ast.parse(f.read(), MONOLITH)
    names = set()
    for n in tree.body:
        if isinstance(n, (ast.FunctionDef, ast.ClassDef)) \
                and not n.name.startswith("_"):
            names.add(n.name)
        elif isinstance(n, ast.ImportFrom) and n.module \
                and n.module.startswith("core."):
            for a in n.names:
                if a.name != "*" and not a.name.startswith("_"):
                    names.add(a.name)
    return sorted(names)


def _module_constants():
    """模块级大写常量 {名: repr}。

    v2.3.1 A 区自查升级：拆分后 facade 无顶层赋值——原逻辑（只扫 facade
    AST）导致 core 全树 164 个常量里 95 个不在基线内（CONFIG_PATH/
    MIHOMO_API/URL_RE/_PROXY_LOCK 等关键路径常量裸奔）。现改为
    **facade AST + core/**/*.py 顶层大写赋值名并集**（值仍运行时
    getattr 求真，见 _collect_live）。
    """
    out = {}
    with open(MONOLITH, encoding="utf-8") as f:
        tree = ast.parse(f.read(), MONOLITH)
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id.isupper():
                    try:
                        val = _literal(node.value)
                    except Exception:
                        continue
                    if isinstance(val, _CONST_TYPES):
                        out[t.id] = repr(val)
    # core 全树顶层常量名（路径/缓存/锁/URL 等拆分后落在子模块的）
    for dirpath, _dirs, files in os.walk(CORE):
        if "__pycache__" in dirpath:
            continue
        for fname in files:
            if not fname.endswith(".py"):
                continue
            try:
                sub = ast.parse(open(os.path.join(dirpath, fname),
                                     encoding="utf-8").read())
            except (OSError, SyntaxError):
                continue
            for node in sub.body:
                if isinstance(node, ast.Assign):
                    for t in node.targets:
                        if isinstance(t, ast.Name) and t.id.isupper()                                 and not t.id.startswith("__"):
                            out.setdefault(t.id, "")
    return out


def _literal(node):
    """安全求值字面量节点（非字面量抛 ValueError）。"""
    try:
        return ast.literal_eval(node)
    except Exception as e:
        raise ValueError(str(e))


def _collect_live():
    """import facade 后收集 {符号: 签名str} 与 {常量: repr}。

    常量比对对象 = golden 常量名 ∪ 当前 AST 常量名，逐个 ``getattr(vt, ...)``
    ——拆分后常量搬进 core 子模块，必须仍挂在 facade 上（再导出）；只扫当前
    AST 会把「搬走即 MISSING」误报成漂移（v2.3.1 实测踩坑）。
    """
    import video_toolbox as vt
    sigs = {}
    for name in _public_symbols():
        obj = getattr(vt, name, None)
        if obj is None:
            sigs[name] = "<MISSING>"
            continue
        try:
            sigs[name] = str(inspect.signature(obj))
        except (TypeError, ValueError):
            sigs[name] = "<NO-SIG>"
    names = set(_module_constants())
    if os.path.isfile(GOLDEN):
        names |= set(_load_golden().get("constants", {}))
    consts = {}
    import _thread as _th
    for name in sorted(names):
        got = getattr(vt, name, None)
        if got is None:
            consts[name] = "<MISSING>"
            continue
        if isinstance(got, _th.LockType):
            continue  # 锁对象 repr 含内存地址，逐进程不稳，不纳入基线
        if isinstance(got, (set, frozenset)):
            try:
                consts[name] = "SORTED-SET " + repr(sorted(got))
            except TypeError:
                consts[name] = "UNORDERED-SET"
            continue
        consts[name] = repr(got)
    return sigs, consts


def _load_golden():
    with open(GOLDEN, encoding="utf-8") as f:
        return json.load(f)


def _save_golden(data):
    os.makedirs(os.path.dirname(GOLDEN), exist_ok=True)
    with open(GOLDEN, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1, sort_keys=True)


def check_domain_map_coverage(fails):
    """DOMAIN_MAP 并集必须与 AST 公开符号集一致（施工图不漏不多）。"""
    mapped = sorted(s for v in DOMAIN_MAP.values() for s in v)
    actual = _public_symbols()
    if mapped != actual:
        only_map = sorted(set(mapped) - set(actual))
        only_ast = sorted(set(actual) - set(mapped))
        dup = sorted(s for s in set(mapped) if mapped.count(s) > 1)
        if only_map:
            fails.append(f"DOMAIN_MAP 多出 AST 没有的符号: {only_map}")
        if only_ast:
            fails.append(f"DOMAIN_MAP 漏映射的符号: {only_ast}")
        if dup:
            fails.append(f"DOMAIN_MAP 重复映射的符号: {dup}")
    return len(mapped)


def check_baseline(fails):
    """公开符号/签名/常量与黄金基线一致。"""
    if not os.path.isfile(GOLDEN):
        return 0
    golden = _load_golden()
    live_sigs, live_consts = _collect_live()
    gs, gc = golden.get("signatures", {}), golden.get("constants", {})
    for name, want in sorted(gs.items()):
        got = live_sigs.get(name, "<MISSING>")
        if got != want:
            fails.append(f"签名漂移: {name} 基线 {want} -> 现 {got}")
    for name, want in sorted(gc.items()):
        got = live_consts.get(name, "<MISSING>")
        if got != want:
            fails.append(f"常量漂移: {name} 基线 {want} -> 现 {got}")
    return len(gs)


def check_behavior(fails):
    """纯函数行为抽查（输入/输出钉死）。"""
    import video_toolbox as vt
    for name, args, kwargs, want in BEHAVIOR_CASES:
        fn = getattr(vt, name, None)
        if fn is None:
            fails.append(f"行为抽查缺函数: {name}")
            continue
        try:
            got = fn(*args, **kwargs)
        except Exception as e:
            fails.append(f"行为抽查 {name} 抛异常: {e!r}")
            continue
        if got != want:
            fails.append(f"行为漂移: {name}{args} -> {got!r}（期望 {want!r}）")


def _core_files():
    if not os.path.isdir(CORE):
        return []
    out = []
    for dirpath, _dirs, files in os.walk(CORE):
        if "__pycache__" in dirpath:
            continue
        out += [os.path.join(dirpath, f) for f in files if f.endswith(".py")]
    return sorted(out)


def check_core_gui_free(fails):
    """负向桩：core 引擎层**模块顶层**禁止 import Qt/qfluentwidgets。

    只查顶层（tree.body 直挂的 Import/ImportFrom）：函数体内的延迟 import
    是既有模式（vc_importable 用 importlib 字符串导入 videocaptioner、
    engine_ui_brand_patch 延迟 import vt_engine_ui——后者已有 spec
    collect_submodules 兜底），误伤它们会逼出「为过测试把延迟 import 提前到
    模块顶层」的反向灾难。真正的病是「顶层 import GUI 但 spec 没 hiddenimports」
    → 打包后静默 ImportError，顶层检查正好钉这个。
    """
    n = 0
    for path in _core_files():
        n += 1
        try:
            with open(path, encoding="utf-8") as f:
                tree = ast.parse(f.read(), path)
        except (SyntaxError, OSError) as e:
            fails.append(f"core 文件解析失败: {os.path.basename(path)}: {e}")
            continue
        for node in tree.body:  # 只查顶层，函数体内延迟 import 放行
            mods = []
            if isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                mods = [node.module]
            for m in mods:
                top = m.split(".")[0]
                if top in _GUI_FORBIDDEN:
                    fails.append(
                        f"core 引擎层禁 GUI 依赖: {os.path.basename(path)} -> {m}")
    return n


def check_domain_progress(fails):
    """进度档：done 域 -> core 子包可导入、__all__ 覆盖、facade 无函数体。"""
    import importlib
    done = 0
    with open(MONOLITH, encoding="utf-8") as f:
        facade_tree = ast.parse(f.read(), MONOLITH)
    facade_defs = {n.name for n in facade_tree.body
                   if isinstance(n, (ast.FunctionDef, ast.ClassDef))}
    for domain, status in SPLIT_STATUS.items():
        if status != "done":
            continue
        done += 1
        want = set(DOMAIN_MAP[domain])
        try:
            mod = importlib.import_module(f"core.{domain}")
        except Exception as e:
            fails.append(f"core.{domain} 导入失败: {e!r}")
            continue
        exported = set(getattr(mod, "__all__", []) or [])
        missing = sorted(want - exported)
        if missing:
            fails.append(f"core.{domain}.__all__ 缺符号: {missing}")
        leaked = sorted(want & facade_defs)
        if leaked:
            fails.append(f"facade 仍留着 {domain} 域函数体（应只剩再导出）: {leaked}")
    return done


def main():
    rebase = "--rebase" in sys.argv
    fails = []
    mapped = check_domain_map_coverage(fails)
    live_sigs, live_consts = _collect_live()
    if rebase or not os.path.isfile(GOLDEN):
        _save_golden({
            "note": "video_toolbox facade 公开 API 基线（v2.3.1 拆分前）",
            "symbols": _public_symbols(),
            "signatures": live_sigs,
            "constants": live_consts,
        })
        print(f"[BASELINE] 已生成 {os.path.relpath(GOLDEN, ROOT)}"
              f"（{len(live_sigs)} 符号 + {len(live_consts)} 常量）")
    else:
        n = check_baseline(fails)
        print(f"[BASELINE] 公开符号/签名/常量比对完成（{n} 符号）")
    check_behavior(fails)
    print(f"[BEHAVIOR] 行为抽查 {len(BEHAVIOR_CASES)} 项")
    nfiles = check_core_gui_free(fails)
    print(f"[NEG-CORE] core 引擎层禁 GUI 扫描（{nfiles} 文件）")
    ndone = check_domain_progress(fails)
    print(f"[PROGRESS] 域完成 {ndone}/{len(SPLIT_STATUS)}"
          f"（pending: {[d for d, s in SPLIT_STATUS.items() if s != 'done']}）")
    print("=" * 56)
    if fails:
        print(f"CORE-API RESULT: FAIL ({len(fails)} 项)")
        for x in fails:
            print("  -", x)
        return 1
    print(f"CORE-API RESULT: PASS（DOMAIN_MAP {mapped} 符号全覆盖）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
