#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""界面自检（v1.10.4 Fluent 界面）：验证窗口与各页面可构建、导航宽度自适应、
设置页统一入口、字幕处理环境就绪。

不联网、不下载视频。运行：python _selftest_gui.py
需要图形界面（本机运行）；用内置运行时 tools/python 执行。
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import video_toolbox as engine

os.environ.setdefault(
    "QT_QPA_PLATFORM_PLUGIN_PATH",
    os.path.join(engine.EMBEDDED_SITE_PACKAGES, "PyQt5", "Qt5", "plugins"))

FAILS = []
_LINES = []


def check(name, cond, extra=""):
    line = f"  [{'PASS' if cond else 'FAIL'}] {name}{(' -> ' + extra) if extra else ''}"
    print(line)
    _LINES.append(line)
    if not cond:
        FAILS.append(line)


def _about_to_quit_hooked():
    """检查 GUI 的 main() 是否已把退出同步挂到 aboutToQuit。

    直接读源码而非实例化 QApplication：自检自身就在一个 QApplication 里，
    main() 里的挂接发生在其执行流程中，源码断言最稳。
    """
    try:
        src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "video_toolbox_qt.py"), encoding="utf-8").read()
        return "aboutToQuit.connect(engine.sync_calib_on_exit)" in src
    except OSError:
        return False


def _worker_env_ok():
    """子进程环境是否带着数据根目录与改向后的 TEMP（避免中间产物落系统盘）。"""
    try:
        env = engine.worker_subprocess_env()
    except Exception:
        return False
    return (env.get("VT_DATA_ROOT") == engine.DATA_ROOT
            and os.path.abspath(env.get("TEMP", "")) == os.path.abspath(engine.TMP_DIR))


def _prepare_called_before_vc():
    """GUI 的 main() 是否在 Qt/引擎初始化之前调用了 prepare_runtime_env。

    必须在任何 videocaptioner 导入之前执行，否则其路径常量已在导入时固化，
    重定向就失效了。这里按源码位置判断调用早于 configure_qt_plugins。
    """
    try:
        src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "video_toolbox_qt.py"), encoding="utf-8").read()
        i = src.find("def main()")
        if i < 0:
            return False
        seg = src[i:i + 500]
        a = seg.find("engine.prepare_runtime_env()")
        b = seg.find("configure_qt_plugins()")
        return a != -1 and (b == -1 or a < b)
    except OSError:
        return False


def _migrate_flattens_nested():
    """迁移旧数据时，父层自己的 settings.json 不能被「下钻子目录」漏掉。

    复现旧布局：<legacy>/settings.json + <legacy>/VideoCaptioner/logs/app.log
    期望两者都落到同一个数据根下（不能只搬 logs 而丢掉 settings.json）。
    """
    import shutil
    import tempfile as _tf
    sandbox = _tf.mkdtemp(prefix="vt_mig_nested_", dir=engine.TMP_DIR)
    legacy = os.path.join(sandbox, "legacy")
    dst = os.path.join(sandbox, "dst")
    try:
        os.makedirs(os.path.join(legacy, engine.VC_NAME, "logs"))
        with open(os.path.join(legacy, "settings.json"), "w", encoding="utf-8") as f:
            f.write("{}")
        with open(os.path.join(legacy, engine.VC_NAME, "logs", "app.log"),
                  "w", encoding="utf-8") as f:
            f.write("x")
        os.makedirs(dst)

        orig_dirs, orig_dst = engine._VC_LEGACY_DIRS, engine.vc_data_dir
        engine._VC_LEGACY_DIRS = (legacy,)
        engine.vc_data_dir = lambda: dst
        try:
            engine.vc_migrate_legacy_data()
        finally:
            engine._VC_LEGACY_DIRS, engine.vc_data_dir = orig_dirs, orig_dst

        got_settings = os.path.isfile(os.path.join(dst, "settings.json"))
        got_log = os.path.isfile(os.path.join(dst, "logs", "app.log"))
        return got_settings and got_log and not os.path.isdir(
            os.path.join(dst, engine.VC_NAME))
    except OSError:
        return False
    finally:
        shutil.rmtree(sandbox, ignore_errors=True)


def _leftover_ignores_migrated():
    """数据根已存在对应文件的旧目录，不应被报为「待清理残留」。"""
    import shutil
    import tempfile as _tf
    sandbox = _tf.mkdtemp(prefix="vt_leftover_", dir=engine.TMP_DIR)
    legacy = os.path.join(sandbox, "legacy")
    dst = os.path.join(sandbox, "dst")
    try:
        os.makedirs(os.path.join(legacy, "logs"))
        with open(os.path.join(legacy, "logs", "app.log"), "w", encoding="utf-8") as f:
            f.write("x")
        os.makedirs(os.path.join(dst, "logs"))
        # 数据根已有同名同路径文件 => 属重复遗留，不该提示用户清理
        with open(os.path.join(dst, "logs", "app.log"), "w", encoding="utf-8") as f:
            f.write("x")

        orig_dirs, orig_dst = engine._VC_LEGACY_DIRS, engine.vc_data_dir
        engine._VC_LEGACY_DIRS = (legacy,)
        engine.vc_data_dir = lambda: dst
        try:
            leftovers = engine.vc_legacy_leftovers()
        finally:
            engine._VC_LEGACY_DIRS, engine.vc_data_dir = orig_dirs, orig_dst
        return leftovers == []
    except OSError:
        return False
    finally:
        shutil.rmtree(sandbox, ignore_errors=True)


def _migrate_idempotent():
    """迁移函数必须幂等：第二次调用不应再搬动任何条目。"""
    import shutil
    import tempfile as _tf
    sandbox = _tf.mkdtemp(prefix="vt_mig_idem_", dir=engine.TMP_DIR)
    legacy = os.path.join(sandbox, "legacy")
    dst = os.path.join(sandbox, "dst")
    try:
        os.makedirs(legacy)
        os.makedirs(dst)
        with open(os.path.join(legacy, "settings.json"), "w", encoding="utf-8") as f:
            f.write("{}")

        orig_dirs, orig_dst = engine._VC_LEGACY_DIRS, engine.vc_data_dir
        engine._VC_LEGACY_DIRS = (legacy,)
        engine.vc_data_dir = lambda: dst
        try:
            first = engine.vc_migrate_legacy_data()
            second = engine.vc_migrate_legacy_data()
        finally:
            engine._VC_LEGACY_DIRS, engine.vc_data_dir = orig_dirs, orig_dst
        # 首次至少搬 1 项；第二次必须为 0（源已空）
        return first >= 1 and second == 0
    except OSError:
        return False
    finally:
        shutil.rmtree(sandbox, ignore_errors=True)


def _engine_src():
    """引擎模块源码文本（用于源码级结构断言）。"""
    try:
        return open(os.path.abspath(engine.__file__), encoding="utf-8").read()
    except (OSError, AttributeError):
        return ""


def _qt_main_uses(fn_src_frag):
    """video_toolbox_qt.py 的 main() 段里是否调用了给定入口。"""
    try:
        src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "video_toolbox_qt.py"), encoding="utf-8").read()
        i = src.find("def main()")
        return i >= 0 and fn_src_frag in src[i:i + 800]
    except OSError:
        return False


def _qt_main_uses_src():
    """video_toolbox_qt.py 全文（用于「界面无某入口」的源码级断言）。"""
    try:
        return open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                 "video_toolbox_qt.py"), encoding="utf-8").read()
    except OSError:
        return ""


def _merge_script_cases():
    """脚本条目级三方合并：新增并入/远程更新采纳/冲突保留本地/幂等/注册守门。"""
    hdr = '_MODE_TERM_TABLE = {"bi": "A_TERMS"}\n'
    local = (hdr + 'A_TERMS = {\n    "旧错": "旧正",\n    "本地新": "本地正",\n}\n'
             'ENTITIES = [\n    Entity("角色甲", modes=("bi",), variants=("甲错",)),\n]\n')
    base = (hdr + 'A_TERMS = {\n    "旧错": "旧正",\n}\n'
            'ENTITIES = [\n    Entity("角色甲", modes=("bi",), variants=("甲错",)),\n]\n')
    remote = (hdr + 'A_TERMS = {\n    "旧错": "旧正改",\n    "远新": "远正",\n}\n'
              'ENTITIES = [\n    Entity("角色甲", modes=("bi",), variants=("甲错",)),\n'
              '    Entity("角色乙", modes=("bi",), variants=("乙错",)),\n]\n')
    merged, added, _ = engine.merge_calib_script(local, remote, base)
    ok1 = (added == 2 and '"远新"' in merged and 'Entity("角色乙"' in merged
           and '"本地新"' in merged and '"旧错": "旧正改"' in merged)
    local2 = local.replace('"旧错": "旧正"', '"旧错": "本地改"')
    merged2, _a2, conf2 = engine.merge_calib_script(local2, remote, base)
    ok2 = '"旧错": "本地改"' in merged2 and conf2
    merged3, a3, _ = engine.merge_calib_script(merged, remote, merged)
    ok3 = merged3 == merged and a3 == 0
    remote_bad = (hdr + 'A_TERMS = {\n    "甲错": "别人家的正形",\n}\n'
                  'ENTITIES = [\n    Entity("角色甲", modes=("bi",), variants=("甲错",)),\n]\n')
    merged4, a4, conf4 = engine.merge_calib_script(local, remote_bad, base)
    ok4 = merged4 == local and a4 == 0 and conf4
    return ok1 and ok2 and ok3 and ok4


def _merge_kb_cases():
    """学习库合并：新增并入/人工否决就高/同键不同目标置冲突/count 取大。"""
    import json as _json

    def cand(w, r, st, cnt):
        return {"wrong": w, "right": r, "mode": "bi", "count": cnt,
                "uncorrected": 0, "status": st, "cues": [1], "samples": [],
                "ref_tokens": {}, "unc_ref_tokens": {},
                "first": "2026-09-01", "last": "2026-09-02", "alts": {}}
    loc = {"version": 1, "candidates": {
        "bi|错一": cand("错一", "正一", "confirmed", 3),
        "bi|错二": cand("错二", "正二", "candidate", 1)}}
    rem = {"version": 1, "candidates": {
        "bi|错一": cand("错一", "正一改", "confirmed", 2),
        "bi|错二": cand("错二", "正二", "rejected", 5),
        "bi|错三": cand("错三", "正三", "candidate", 1)}}
    text, added, conflicts = engine.merge_learned_kb(
        _json.dumps(loc), _json.dumps(rem))
    c = _json.loads(text)["candidates"]
    return ("bi|错三" in c and added == 1
            and c["bi|错二"]["status"] == "rejected"
            and c["bi|错一"].get("conflict") is True and conflicts == 1
            and c["bi|错一"]["count"] == 3)


def _qt_src():
    """界面源码文本（用于源码级结构断言）。"""
    try:
        return open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                 "video_toolbox_qt.py"), encoding="utf-8").read()
    except OSError:
        return ""


def _no_undefined_names():
    """src 下所有 .py 是否有「引用了但模块里从没定义」的全局名。

    v1.12.0 教训：这类名字（如 duration=INFOBAR_DURATION_SUCCESS）在 PyQt5 槽里
    会变成未捕获异常 → 进程直接 abort → 用户看到「点一下按钮程序就没了」，
    而 py_compile 查不出来。用 check_names 的静态扫描兜住，返回 (ok, 详情)。
    """
    try:
        import check_names
    except Exception:
        return False, "check_names 不可用"
    here = os.path.dirname(os.path.abspath(__file__))
    bad = []
    for f in sorted(os.listdir(here)):
        if not f.endswith(".py") or f.startswith("__"):
            continue
        try:
            with open(os.path.join(here, f), encoding="utf-8") as fh:
                probs = check_names.scan_source(fh.read(), f)
        except OSError:
            continue
        if probs:
            bad.append(f)
    return (not bad), "、".join(bad)


def _crash_guard_ok():
    """未捕获异常兜底是否定义并在 main() 里、QApplication 之前装上。"""
    src = _qt_src()
    call = src.find("install_crash_guard()")
    app = src.find("app = QApplication(sys.argv)")
    return ("def install_crash_guard()" in src
            and "sys.excepthook = _hook" in src
            and "threading.excepthook = _thread_hook" in src
            and 0 <= call < app)


def _merge_core_module_ok():
    """合并算法抽到 calib_merge_core 纯函数模块，引擎以别名复用同一实现。"""
    try:
        import calib_merge_core as core
    except Exception:
        return False
    return (core.merge_calib_script is engine.merge_calib_script
            and core.merge_learned_kb is engine.merge_learned_kb
            and callable(core._registry_conflicts)
            # 纯函数模块不允许偷偷建目录/联网
            and "import requests" not in dir(core))


def _path_normalize_ok():
    """引擎 settings.json 里的 C 盘工作目录会被强制改回软件文件夹。"""
    import json as _json
    data = engine._vc_read_settings()
    saved = _json.dumps(data, ensure_ascii=False)
    data.setdefault("Save", {})["Work_Dir"] = "C:/Users/Someone/VideoCaptioner"
    engine._vc_write_settings(data)
    try:
        engine.vc_prepare_settings_file()
        wd = engine._vc_read_settings().get("Save", {}).get("Work_Dir", "")
        wd = wd.replace("\\", "/").lower()
        root = engine.vc_data_dir().replace("\\", "/").lower()
        ok = wd.startswith(root) and "c:/users" not in wd
        ok = ok and engine._path_on_system_drive("C:/Users/x/VideoCaptioner")
        ok = ok and not engine._path_on_system_drive(
            os.path.join(engine.vc_data_dir(), "work-dir"))
        return ok
    finally:
        engine._vc_write_settings(_json.loads(saved))
        engine.vc_prepare_settings_file()


def _global_llm_engine_ok():
    """全局 AI 配置写入引擎 OpenAI 兼容槽（引擎不再单独配 LLM；单通道）。"""
    probe = dict(engine.ai_load_config())
    probe.update(api_key="test-key-xyz", base_url="https://example.com/v1",
                 model="test-model")
    ok, _msg = engine.apply_global_llm_to_engine(probe)
    s = engine._vc_read_settings().get("LLM", {})
    good = (ok and s.get("OpenAI_API_Key") == "test-key-xyz"
            and s.get("OpenAI_API_Base") == "https://example.com/v1"
            and s.get("OpenAI_Model") == "test-model"
            and s.get("LLMService") == "OpenAI 兼容")
    engine.apply_global_llm_to_engine(engine.ai_load_config())  # 还原真实配置
    return good


def _ai_client_data_dir_ok():
    """ai_client 按 VT_DATA_ROOT 定位 data 目录（不再按错误层级猜目录）。"""
    import importlib.util
    import tempfile
    path = os.path.join(engine.TOOLS_DIR, "ai_client.py")
    spec = importlib.util.spec_from_file_location("vt_ai_client_probe", path)
    mod = importlib.util.module_from_spec(spec)
    old = os.environ.get("VT_DATA_ROOT")
    tmp = tempfile.mkdtemp(prefix="vt_aicfg_")
    os.environ["VT_DATA_ROOT"] = tmp
    try:
        spec.loader.exec_module(mod)
        return os.path.abspath(str(mod.DATA_DIR)) == os.path.abspath(
            os.path.join(tmp, "data"))
    finally:
        if old is None:
            os.environ.pop("VT_DATA_ROOT", None)
        else:
            os.environ["VT_DATA_ROOT"] = old


def _unified_settings_source_ok():
    """源码层面：唯一全局设置页——无分段/独立对话框，隐藏引擎重复分组，
    且内嵌引擎区已消除双层滚动视口（内层无滚条/无边距、高度跟随内容）。"""
    s = _qt_src()
    no_seg = "SegmentedWidget(" not in s and "class EngineSettingsDialog" not in s
    hides = all(g in s for g in ('"llmGroup"', '"saveGroup"',
                                 '"personalGroup"', '"aboutGroup"'))
    global_llm = "ai_save_config" in s and "全局 AI" in s
    # 不再用整个 SettingInterface 当内层滚动视口
    flat = ("_InnerScrollToContent" in s
            and "setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)" in s
            and "setting.expandLayout.setContentsMargins(0, 0, 0, 0)" in s
            and "setFixedHeight" in s)
    return no_seg and hides and global_llm and flat


def _api_compat_ok():
    """API 地址归一化多厂商兼容：智谱/OpenAI/DeepSeek/百炼/Gemini/Ollama/
    Azure（deployment + api-version）与 Anthropic 旧地址友好报错。"""
    try:
        cases = [
            ("https://open.bigmodel.cn/api/paas/v4",
             "https://open.bigmodel.cn/api/paas/v4/chat/completions"),
            ("https://api.openai.com",
             "https://api.openai.com/v1/chat/completions"),
            ("https://api.deepseek.com",
             "https://api.deepseek.com/v1/chat/completions"),
            ("https://dashscope.aliyuncs.com/compatible-mode/v1",
             "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"),
            ("https://generativelanguage.googleapis.com/v1beta/openai/",
             "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"),
            ("http://localhost:11434/v1",
             "http://localhost:11434/v1/chat/completions"),
            ("https://x.example.com/v1/chat/completions",
             "https://x.example.com/v1/chat/completions"),
        ]
        for raw, expect in cases:
            if engine.ai_mod()._chat_url(raw) != expect:
                return False
        az = engine.ai_mod()._azure_chat_url(
            "https://res.openai.azure.com/openai/deployments/gpt-4o")
        if az != ("https://res.openai.azure.com/openai/deployments/gpt-4o"
                  "/chat/completions?api-version=2024-10-21"):
            return False
        try:
            engine.ai_mod().AIClient(
                {"base_url": "https://open.bigmodel.cn/api/anthropic",
                 "api_key": "k", "model": "m"})
            return False          # Anthropic 旧地址应被拦截并给指引
        except engine.ai_mod().AIClientError:
            return True
    except Exception:  # noqa: BLE001
        return False


def _sync_conn_yaml_ok():
    """v1.12.2 连接统一入口：内置 github_proxy.yaml 的 vt-github 段可解析且
    字段齐备，_sync_conn() 返回值与 yaml 内容一致（改仓库只动 yaml）。"""
    try:
        import yaml
        with open(engine.GITHUB_PROXY_YAML, encoding="utf-8-sig") as f:
            data = yaml.safe_load(f) or {}
        vg = data.get("vt-github") or {}
        cfg = engine._sync_conn(refresh=True)
        need = ("owner", "repo", "branch", "api", "files")
        return (all(str(vg.get(k) or "").strip() for k in need[:-1])
                and isinstance(vg.get("files"), list) and vg["files"]
                and cfg["owner"] == str(vg["owner"]).strip()
                and cfg["repo"] == str(vg["repo"]).strip()
                and cfg["branch"] == str(vg["branch"]).strip()
                and cfg["files"] == [str(p).strip() for p in vg["files"]])
    except Exception:  # noqa: BLE001
        return False


def _sync_env_injection_ok():
    """v1.12.1 增量通道环境注入：sync_env_into 为子进程补齐 VT_SYNC_* 路径。

    旧的 _read_sync_text/_atomic_write 文件级同步辅助随 GitHub 整文件通道
    一起移除；现在引擎只负责把更新库/状态目录/学习库路径注入子进程环境，
    合并与应用都发生在知识脚本（kb-sync / kb-push）内部。
    """
    fn = getattr(engine, "sync_env_into", None)
    if not callable(fn):
        return False
    env = fn({})
    return (env.get("VT_SYNC_ROOT") == engine.SYNC_REMOTE_DIR
            and env.get("VT_SYNC_DIR") == engine.SYNC_LOCAL_DIR
            and env.get("VT_SYNC_KB") == engine.CALIB_KB_PATH
            and env.get("VT_DATA_ROOT") == engine.DATA_ROOT)


def _asr_inject_ok(mode):
    """ASR 全局配置 → 引擎「转录配置」注入正确（service / local 两种模式）。"""
    import json as _json
    saved = _json.dumps(engine._vc_read_settings(), ensure_ascii=False)
    try:
        probe = dict(engine.ai_load_config())
        if mode == "service":
            probe.update(asr_mode="service",
                         asr_base_url="https://asr.example.com/v1",
                         asr_api_key="k-123", asr_model="sensevoice-small")
        else:
            probe.update(asr_mode="local", asr_local_model="large-v3-turbo",
                         asr_local_model_dir=os.path.join(engine.TMP_DIR, "asr_model"))
        ok, _msg = engine.apply_asr_to_engine(probe)
        s = engine._vc_read_settings()
        tr = s.get("Transcribe", {}).get("TranscribeModel", "")
        if mode == "service":
            wa = s.get("WhisperAPI", {})
            return (ok and tr == engine.TM_WHISPER_API
                    and wa.get("WhisperApiBase") == "https://asr.example.com/v1"
                    and wa.get("WhisperApiKey") == "k-123"
                    and wa.get("WhisperApiModel") == "sensevoice-small")
        fw = s.get("FasterWhisper", {})
        return (ok and tr == engine.TM_FASTER_WHISPER
                and fw.get("Model") == "large-v3-turbo"
                and str(fw.get("ModelDir", "")).endswith("asr_model"))
    finally:
        engine._vc_write_settings(_json.loads(saved))
        # 内存 QConfig 也还原成真实配置（否则会影响后续断言与运行态）
        engine.vc_prepare_settings_file()


def _translate_default_ok():
    """v1.12.0 翻译板块去 AI：历史「LLM 大模型翻译」配置在读盘前迁回微软翻译。"""
    import json as _json
    saved = _json.dumps(engine._vc_read_settings(), ensure_ascii=False)
    try:
        data = engine._vc_read_settings()
        data.setdefault("Translate", {})["TranslatorServiceEnum"] = engine.TS_LLM
        engine._vc_write_settings(data)
        engine.vc_prepare_settings_file()
        got = str(engine._vc_read_settings().get("Translate", {}).get(
            "TranslatorServiceEnum") or "")
        return got == engine.TS_BING
    finally:
        engine._vc_write_settings(_json.loads(saved))
        engine.vc_prepare_settings_file()


def _machine_translate_only_ok():
    """v1.12.0 翻译板块去 AI：LLM 回退兜底已整体移除，翻译失败不再转 AI。

    验证三点：engine 上已无回退函数；工厂未被补丁改写（无 _vt 标志）；
    基类 translate_subtitle 为引擎原生实现（源码不含兜底痕迹）。
    """
    try:
        if (hasattr(engine, "vc_translate_fallback_patch")
                or hasattr(engine, "_translate_llm_fallback")):
            return False
        from videocaptioner.core.translate import base as _tb
        from videocaptioner.core.translate import factory as _tf
        if getattr(_tf, "_vt_translate_patched", False):
            return False
        import inspect
        if "_vt" in inspect.getsource(_tb.BaseTranslator.translate_subtitle):
            return False
        return True
    except Exception:  # noqa: BLE001
        return False


def _dump_report():
    """把结果另写一份纯 ASCII 报告，便于在无 stdout 的环境下核对。"""
    try:
        import re
        ascii_lines = []
        for ln in _LINES:
            ascii_lines.append(ln.encode("ascii", "replace").decode("ascii"))
        body = ("PASS=%d FAIL=%d\n" % (len(_LINES) - len(FAILS), len(FAILS))
                + "\n".join(ascii_lines) + "\n--- FAILS ---\n"
                + "\n".join(f.encode("ascii", "replace").decode("ascii")
                            for f in FAILS))
        with open(os.path.join(engine.DATA_DIR, "GUI_SELFTEST_REPORT.txt"),
                  "w", encoding="ascii", errors="replace") as f:
            f.write(re.sub(r"\s+$", "", body))
    except Exception:
        pass


def main():
    print("=" * 62)
    print("  界面自检：Fluent 窗口 + 六个页面 + 导航宽度 + 设置入口")
    print("=" * 62)

    from PyQt5.QtCore import QTimer
    from PyQt5.QtGui import QFontMetrics
    from PyQt5.QtWidgets import QApplication
    import video_toolbox_qt as gui

    app = QApplication.instance() or QApplication(sys.argv)
    gui.setTheme(gui.Theme.DARK)
    win = gui.MainWindow([])

    pages = [win.download_page, win.library_page, win.merge_page,
             win.subtitle_page, win.calib_page, win.settings_page]
    check("六个页面全部构建", all(p is not None for p in pages))
    check("堆叠页数量为 6（新增设置页）",
          win.stackedWidget.count() == 6, f"count={win.stackedWidget.count()}")
    check("左侧导航已创建", win.navigationInterface.width() > 0,
          f"width={win.navigationInterface.width()}")

    # ---- 导航宽度：最长项文字 + 2 个字符 ----
    # v1.11.0 统一口径：按「导航面板实际字体」量最长项文字 + 2 个中文字宽
    panel_font = win.navigationInterface.panel.font()
    fm = QFontMetrics(panel_font)
    longest = max(fm.horizontalAdvance(t) for t in win.NAV_TEXTS)
    expect = gui.nav_width_for(win.NAV_TEXTS, panel_font)
    actual = win.navigationInterface.panel.expandWidth
    check("导航展开宽度按最长项自适应（统一口径：导航面板字体）",
          abs(actual - expect) <= 2, f"actual={actual} expect={expect}")
    check("导航宽度不随重复重算漂移（多次收敛到同一值）",
          (win.refresh_nav_width(), win.refresh_nav_width(),
           win.navigationInterface.panel.expandWidth)[-1] == actual,
          f"{actual}")
    check("nav_width_for 默认按应用字体度量（不再硬编码雅黑）",
          gui.nav_width_for(win.NAV_TEXTS) == gui.nav_width_for(
              win.NAV_TEXTS, gui.QApplication.font()),
          f"{gui.nav_width_for(win.NAV_TEXTS)} vs "
          f"{gui.nav_width_for(win.NAV_TEXTS, gui.QApplication.font())}")
    check("导航宽度含 2 个中文字余量",
          actual - gui.NAV_BUTTON_W - gui.NAV_ICON_TEXT_GAP
          - gui.NAV_SIDE_PADDING * 2 >= longest + fm.horizontalAdvance("字字"),
          f"longest={longest}")
    check("导航宽度远小于旧固定值 322", actual < 322, f"actual={actual}")

    # ---- 设置页：v1.10.8 唯一全局设置（不分段、无独立引擎对话框）----
    sp = win.settings_page
    check("设置页挂载在导航底部",
          "SettingsPage" in win.navigationInterface.panel.items)
    check("设置页不再有工具/引擎分段控件", not hasattr(sp, "seg"))
    check("设置页不再保留工具分段容器", not hasattr(sp, "tool_seg"))
    check("设置页不再保留引擎分段容器", not hasattr(sp, "engine_seg"))
    check("保留定位到引擎参数区的入口", callable(getattr(sp, "scroll_to_engine", None)))
    for attr in ("ai_enabled", "ai_key", "ai_base", "ai_model", "ai_vision"):
        check(f"全局 AI 卡片含控件 {attr}", hasattr(sp, attr))
    check("全局 AI 密钥框为密码输入",
          sp.ai_key.__class__.__name__ == "PasswordLineEdit")
    check("设置页含校准同步开关", hasattr(sp, "sync_switch"))
    check("设置页含字幕引擎参数区容器", hasattr(sp, "engine_holder"))
    _ewd = sp.engine_dir_edit.text().replace("\\", "/").lower()
    check("引擎工作目录只读且落在数据根下",
          sp.engine_dir_edit.isReadOnly()
          and _ewd.startswith(engine.DATA_DIR.replace("\\", "/").lower()),
          _ewd)
    # 持久化验证需暂时摘除 VT_NO_CALIB_SYNC（自检常用它禁网，但它会让 getter
    # 恒为 False，无法反映配置），验证完恢复原环境变量并保持启用
    _kill = os.environ.pop("VT_NO_CALIB_SYNC", None)
    try:
        engine.set_calib_sync_enabled(True)
        sp.sync_switch.setChecked(True)
        sp.sync_switch.setChecked(False)
        check("同步开关切换后持久化", engine.calib_sync_enabled() is False)
        sp.sync_switch.setChecked(True)
        check("同步开关再次打开后持久化", engine.calib_sync_enabled() is True)
    finally:
        engine.set_calib_sync_enabled(True)
        if _kill is not None:
            os.environ["VT_NO_CALIB_SYNC"] = _kill

    check("下载页含任务表/画质列表/日志",
          win.download_page.task_table.columnCount() == 6
          and win.download_page.qlist.count() == 0
          and bool(win.download_page.log.text))
    check("合并页含配对表", win.merge_page.table.columnCount() == 5)
    check("视频库默认目录已填回", bool(win.library_page.dir_edit.text()),
          win.library_page.dir_edit.text())

    sub = win.subtitle_page
    from PyQt5.QtGui import QShowEvent
    sub.showEvent(QShowEvent())   # 首次显示触发引擎界面内嵌
    check("字幕引擎界面已内嵌（非独立窗口）",
          sub._engine is not None and sub.host_lay.count() == 1,
          type(sub._engine).__name__ if sub._engine else "未创建")
    tc = getattr(sub._engine, "task_creation_interface", None) if sub._engine else None
    check("品牌水印与捐助入口已隐藏",
          tc is not None and tc.info_label.isHidden()
          and tc.donate_button.isHidden())
    # ---- v1.12.0：工作台优化（校准合并 / 底部收起 / 比例调整）----
    sub_if = getattr(sub._engine, "subtitle_optimization_interface", None)
    check("工作台「字幕校正」按钮已隐藏（校准并入字幕校准板块）",
          sub_if is not None
          and sub_if.optimize_button not in sub_if.command_bar.actions()
          and all(b.action() is not sub_if.optimize_button
                  for b in sub_if.command_bar.commandButtons))
    check("引擎就绪后底部状态行已收起（设置/许可走导航栏）",
          sub.foot.isHidden())
    check("字幕表格吃满剩余空间（stretch=1）",
          sub_if is not None
          and sub_if.main_layout.stretch(
              sub_if.main_layout.indexOf(sub_if.subtitle_table)) == 1)
    # ---- v1.12.0：用户自定义代理 yaml ----
    check("设置页含网络代理卡片（接入自己的 Clash/mihomo yaml）",
          hasattr(sp, "proxy_edit") and hasattr(sp, "proxy_hint"))
    try:
        saved_py = engine.get_proxy_yaml()
        engine.set_proxy_yaml("")
        empty_ok = engine.get_proxy_yaml() == ""
        port_gh = engine._proxy_yaml_port(os.path.join(engine.APP_DIR,
                                                       "github_proxy.yaml"))
        engine.set_proxy_yaml(saved_py)
        cfg_builtin = os.path.join(engine.TOOLS_DIR, "mihomo", "config.yaml")
        port_builtin = (engine._proxy_yaml_port(cfg_builtin)
                        if os.path.isfile(cfg_builtin) else 7897)
        proxy_ok = (empty_ok and port_gh == 7890
                    and port_builtin == engine.MIHOMO_PORT)
    except Exception:  # noqa: BLE001
        proxy_ok = False
    check("代理 yaml 端口解析与持久化（自定义 7890 / 内置 7897）", proxy_ok)
    # ---- v1.12.0 修复：改代理 yaml 曾因未定义常量闪退（NameError → PyQt5 abort）----
    try:
        saved_py2 = engine.get_proxy_yaml()
        proxy_target = os.path.join(engine.APP_DIR, "github_proxy.yaml")
        browse_ok = (sp._apply_proxy_yaml(proxy_target) is True
                     and os.path.abspath(engine.get_proxy_yaml())
                     == os.path.abspath(proxy_target))
        sp._reset_proxy_yaml()
        reset_ok = engine.get_proxy_yaml() == ""
        if saved_py2:
            engine.set_proxy_yaml(saved_py2)
    except Exception:  # noqa: BLE001
        browse_ok = reset_ok = False
    check("点「选择 yaml…」不再闪退（_apply_proxy_yaml 保存成功）", browse_ok)
    check("点「恢复内置」不再闪退且清空配置", reset_ok)
    names_ok, names_bad = _no_undefined_names()
    check("src 无「引用但未定义」的全局名（闪退头号成因）", names_ok, names_bad)
    check("未捕获异常兜底装在 QApplication 之前（不再直接 abort）",
          _crash_guard_ok())
    try:
        import videocaptioner  # noqa: F401
        vc_ok = True
    except Exception:
        vc_ok = False
    check("字幕引擎随 exe 内嵌（可导入）", vc_ok)
    check("第三方组件许可与来源声明随包",
          os.path.isfile(engine.VC_LICENSE_FILE)
          and os.path.isfile(engine.VC_SOURCE_FILE))

    check("投稿板块代码已移除（引擎无 UPLOADER_*）",
          not any(a.startswith("UPLOADER_") for a in dir(engine)))
    check("AI 字幕语言识别仍可用（tools/ai_client.py 就位）",
          os.path.isfile(os.path.join(engine.TOOLS_DIR, "ai_client.py")))
    check("配置目录长期记忆生效", os.path.isdir(engine.DEFAULT_DOWNLOAD_DIR))

    # ---- 校准知识同步（v1.12.2：GitHub 整文件通道恢复为收集渠道；连接参数
    #      统一来自内置 github_proxy.yaml 的 vt-github 段；上传全自动、界面
    #      只有「更新」；本地增量镜像 kb-sync/kb-push 为可选增强）----
    check("引擎暴露启动 / 退出同步入口",
          callable(getattr(engine, "sync_calib_on_startup", None))
          and callable(getattr(engine, "sync_calib_on_exit", None)))
    check("GitHub 收集通道已恢复（推送 + 拉取合并函数在位）",
          callable(getattr(engine, "sync_calib_to_github", None))
          and callable(getattr(engine, "_pull_and_merge", None))
          and callable(getattr(engine, "_gh_fetch_file", None)))
    check("连接参数统一读内置 github_proxy.yaml（vt-github 段完整）",
          _sync_conn_yaml_ok())
    check("同步远端与本机状态目录已定义（可选增量镜像）",
          bool(getattr(engine, "SYNC_REMOTE_DIR", ""))
          and bool(getattr(engine, "SYNC_LOCAL_DIR", "")))
    check("代理回退仅用内置 mihomo（127.0.0.1:7897）",
          engine.MIHOMO_PROXY == "http://127.0.0.1:7897")
    check("校准脚本就位（程序根目录 subtitle_calib_merged.py）",
          os.path.isfile(os.path.join(engine.APP_DIR, "subtitle_calib_merged.py")))
    check("同步日志落在 logs/ 下", engine.SYNC_LOG.endswith("calib_sync.log"))
    check("退出已挂接 aboutToQuit → 后台自动上传",
          _about_to_quit_hooked())

    # ---- v1.10.5：校准模式列表与脚本实际支持的开关一致 ----
    calib_modes = {flag for _, flag in win.calib_page.MODES if flag}
    expect_modes = {"--ja", "--jpe", "--ko", "--ak", "--akko", "--endo",
                    "--zho", "--pgr", "--pgren", "--wwoc", "--react"}
    check("校准模式覆盖脚本全部模式开关",
          expect_modes <= calib_modes,
          f"缺 {sorted(expect_modes - calib_modes)}")
    check("已移除脚本不再支持的 --layout 选项",
          not hasattr(win.calib_page, "layout_switch"))

    # ---- v1.10.6：运行期文件不落系统盘（数据目录可配置）----
    check("引擎暴露数据根目录 API（data_root_info）",
          callable(getattr(engine, "data_root_info", None)))
    check("引擎暴露数据目录切换 API（set_data_root）",
          callable(getattr(engine, "set_data_root", None)))
    check("引擎暴露运行环境准备 API（prepare_runtime_env）",
          callable(getattr(engine, "prepare_runtime_env", None)))
    _root, _is_default, _src = engine.data_root_info()
    check("默认数据根目录就是程序目录", _is_default, _src)
    check("数据目录全部落在数据根之下",
          all(os.path.abspath(p).startswith(os.path.abspath(_root))
              for p in (engine.DATA_DIR, engine.LOGS_DIR, engine.TMP_DIR,
                        engine.THUMB_CACHE_DIR, engine.vc_data_dir())))
    check("配置不回落系统盘（AppData）",
          "AppData" not in engine._fallback_config_path()
          and "Local" not in engine._fallback_config_path())
    check("临时目录已改向数据根（不落系统 Temp）",
          os.path.abspath(os.environ.get("TEMP", "")) == os.path.abspath(engine.TMP_DIR)
          and os.path.abspath(tempfile.gettempdir()) == os.path.abspath(engine.TMP_DIR),
          os.environ.get("TEMP", ""))
    check("字幕引擎路径可重定向（vc_redirect_paths）",
          callable(getattr(engine, "vc_redirect_paths", None)))
    check("字幕引擎数据目录不在系统盘",
          "AppData" not in engine.vc_data_dir())
    check("设置页含数据目录输入与提示",
          hasattr(win.settings_page, "data_edit")
          and hasattr(win.settings_page, "data_hint"))
    check("数据目录默认值与引擎一致",
          win.settings_page.data_edit.text() == _root,
          win.settings_page.data_edit.text())
    check("子进程环境传递 VT_DATA_ROOT 与 TEMP",
          _worker_env_ok())
    check("main() 在初始化前先准备运行环境（重定向早于引擎导入）",
          _prepare_called_before_vc())
    check("迁移不会漏掉嵌套布局父层的 settings.json", _migrate_flattens_nested())
    check("残留检测不把已迁空的路径报为待清理", _leftover_ignores_migrated())
    check("重复迁移是幂等的（第二次不搬任何东西）", _migrate_idempotent())

    # ---- v1.10.7：多用户校准知识收敛（启动拉取 + 条目级合并）----
    check("引擎暴露启动同步入口（sync_calib_on_startup）",
          callable(getattr(engine, "sync_calib_on_startup", None)))
    check("学习库纳入同步范围（上传增量的来源）",
          os.path.basename(getattr(engine, "CALIB_KB_PATH", ""))
          == "subtitle_learned_kb.json")
    check("GitHub 通道收集增量 + 本地增量镜像两条通道并存",
          "def sync_calib_to_github" in _engine_src()
          and "def _pull_and_merge" in _engine_src()
          and "kb-sync" in _engine_src() and "kb-push" in _engine_src())
    check("上传全自动、界面只有更新（无手动上传按钮 / 无 push_now 入口）",
          "sync_calib_push_now" not in _qt_main_uses_src()
          and "_push_now" not in _qt_main_uses_src())
    check("GUI 启动即后台拉取最新校准知识",
          _qt_main_uses("sync_calib_on_startup"))
    check("条目级三方合并：并入/采纳/冲突保留/幂等/注册守门", _merge_script_cases())
    check("学习库合并：新增/否决就高/冲突标记/count 取大", _merge_kb_cases())

    # ---- v1.10.8：合并核心抽离 / 唯一全局设置 / 路径归一化 / 全局 LLM ----
    check("合并核心抽到 calib_merge_core 且引擎复用同一实现", _merge_core_module_ok())
    check("引擎 C 盘工作目录被强制改回软件文件夹", _path_normalize_ok())
    check("全局 LLM 配置同步写入字幕引擎 OpenAI 兼容槽", _global_llm_engine_ok())
    check("ai_client 按 VT_DATA_ROOT 定位数据目录", _ai_client_data_dir_ok())
    check("唯一全局设置：无分段/独立对话框且隐藏引擎重复分组",
          _unified_settings_source_ok())
    check("校准同步暴露持久开关 API",
          callable(getattr(engine, "calib_sync_enabled", None))
          and callable(getattr(engine, "set_calib_sync_enabled", None)))

    # ---- v1.12.0：设置板块去重整合（校准合并 / 翻译分组合一 / 转录去重）----
    try:
        esp = sp._ensure_engine_setting()
    except Exception:
        esp = None
    check("设置整合：字幕校正/反思翻译卡已隐藏（校准并入字幕校准板块）",
          esp is not None and esp.subtitleCorrectCard.isHidden()
          and esp.needReflectTranslateCard.isHidden())
    check("设置整合：翻译分组合一为「字幕翻译」（服务/开关/语言/线程）",
          esp is not None
          and esp.translateGroup.titleLabel.text() == "字幕翻译"
          and esp.translate_serviceGroup.isHidden()
          and esp.transcribeGroup.isHidden()
          and esp.translatorServiceCard.parentWidget() is esp.translateGroup)

    # ---- v1.11.0：独立 ASR / AI 校准 Agent（v1.12.0：双通道合并为单通道）----
    for attr in ("asr_mode_combo", "asr_base", "asr_key",
                 "asr_model", "asr_local_model", "asr_local_dir",
                 "calib_cues", "calib_tokens"):
        check(f"设置页含 v1.11 控件 {attr}", hasattr(sp, attr))
    check("全局 AI 已合并为单通道（无 A/B 独立密钥与校准通道选择）",
          not hasattr(sp, "ai_llm_key") and not hasattr(sp, "calib_channel_combo")
          and "llm_base_url" not in engine.ai_mod().DEFAULT_CONFIG)
    check("单通道连通性测试可用（ai_test_connection 忽略 channel）",
          "channel" in __import__("inspect").signature(
              engine.ai_test_connection).parameters)
    check("API 地址归一化兼容多厂商（智谱/OpenAI/DeepSeek/百炼/Gemini/"
          "Ollama/Azure）", _api_compat_ok())
    check("ASR 服务/本地区块可切换",
          hasattr(sp, "asr_service_widget") and hasattr(sp, "asr_local_widget")
          and callable(getattr(sp, "_sync_asr_visible", None)))
    check("校准页含 AI 校准开关与「再次校准」",
          hasattr(win.calib_page, "ai_switch")
          and hasattr(win.calib_page, "again_btn")
          and callable(getattr(win.calib_page, "start_again", None)))
    try:
        import calib_ai_agent as _agent
        agent_ok = (_agent.SCRIPT_NAME == "subtitle_calib_merged.py"
                    and callable(_agent.calibrate)
                    and callable(_agent.rebuild_srt))
    except Exception:  # noqa: BLE001
        agent_ok = False
    check("AI 校准 Agent 模块可导入（calib_ai_agent）", agent_ok)
    check("引擎暴露 AI 校准入口（calib_ai_run）",
          callable(getattr(engine, "calib_ai_run", None)))
    check("引擎暴露 ASR 注入与本地模型补丁",
          callable(getattr(engine, "apply_asr_to_engine", None))
          and callable(getattr(engine, "vc_asr_patch_apply", None)))
    check("引擎在导入前给 diskcache 装延迟补丁（消除建库数秒）",
          callable(getattr(engine, "vc_lazy_cache_patch", None))
          and "vc_lazy_cache_patch()" in _engine_src())
    check("增量通道环境注入齐备（sync_env_into 补齐 VT_SYNC_*）",
          _sync_env_injection_ok())
    check("ASR 注入引擎转录配置（自有服务 → Whisper [API]）",
          _asr_inject_ok("service"))
    check("ASR 注入引擎转录配置（本地独立模型 → FasterWhisper）",
          _asr_inject_ok("local"))
    check("翻译服务历史 LLM 配置迁回微软翻译（翻译板块仅机翻）",
          _translate_default_ok())
    check("翻译板块已全面去 AI（LLM 回退兜底整体移除，失败如实报错）",
          _machine_translate_only_ok())
    check("预热只导入 home_interface（设置界面按需懒加载）",
          "videocaptioner.ui.view.setting_interface" not in
          _qt_src()[_qt_src().find("def prewarm"):_qt_src().find("def _wait_prewarm")])

    def done():
        app.quit()

    QTimer.singleShot(400, done)
    win.show()
    app.exec_()
    win.close()

    _dump_report()
    print("\n" + "=" * 62)
    if FAILS:
        print(f"  结果：{len(FAILS)} 项失败")
        for f in FAILS:
            print("    - " + f.strip().replace("[FAIL] ", "", 1))
        print("=" * 62)
        return 1
    print("  结果：全部通过")
    print("=" * 62)
    return 0


if __name__ == "__main__":
    sys.exit(main())
