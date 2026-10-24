# -*- coding: utf-8 -*-
# @version 2.7.0
"""vc 引擎运行期补丁（lazy-cache 宿主缓存接驳 / settings 预备 / 运行时强制 / 历史数据迁移与残留检测）（v2.3.1 拆分工程 · 自 video_toolbox.py 原样搬入）。

v2.3.1 拆分工程；域间依赖规则见 core/__init__.py。
"""

from core.asr.engine_config import apply_asr_to_engine, vc_asr_patch_apply
from core.asr.patches import TS_BING, TS_LLM
from core.shared.ai import ai_load_config
from core.shared.runtime import VC_NAME, _VC_LEGACY_DIRS, vc_data_dir
from core.shared.vcsettings import (_vc_force_local_paths, _vc_read_settings, _vc_write_settings, vc_settings_path)

import os
import shutil

from core.shared.log import _vc_log
from core.shared.paths import DATA_DIR, DATA_ROOT

def vc_lazy_cache_patch():
    """把引擎 5 处 diskcache 实例创建改成惰性建库（幂等）。

    引擎在 `videocaptioner.core.utils.cache` 模块级创建 5 个 diskcache 实例
    （LLM / ASR / TTS / 翻译 / 版本状态），每个都会真实打开 SQLite 建库并做
    维护：本机实测每个约 0.9 秒（慢盘更久），合计 2.5~4.5 秒——而进入「字幕
    处理」页并不需要任何缓存。

    v1.20.0 起改用自研 `engine_cache`（cache 接缝接管）：
      · 惰性策略与实例管理归自研模块，**不再 monkey-patch diskcache 的类**——
        旧做法把 `diskcache.Cache` 整个换成代理类，等于改写第三方库的公开面；
      · diskcache 保留为 Apache-2.0 底层组件（不重写 SQLite 缓存引擎）；
      · diskcache 缺失时降级为进程内字典缓存，而不是让程序起不来。

    必须在任何 videocaptioner 导入之前调用（prepare_runtime_env 最前面）。
    """
    try:
        import sys as _sys
        import diskcache
    except Exception as e:  # noqa: BLE001
        _vc_log(f"缓存补丁跳过（diskcache 不可用，引擎将走内存降级）：{e}")
        return False
    if getattr(diskcache, "_vt_lazy_patched", False):
        return True
    from engine_cache import CACHE_KINDS, LazyCache

    # 让第三方 `from diskcache import Cache` 拿到的仍是真 Cache——
    # 我们只在这里把「模块级实例」换成惰性代理，公开类本身不动。
    real_cache = diskcache.Cache

    def _vt_lazy_cache_factory(directory, *args, **kwargs):
        """引擎构造缓存实例时的唯一入口：返回自研惰性代理。"""
        sub = str(directory).replace("\\", "/").rstrip("/").split("/")[-1]
        kind = next((k for k, v in CACHE_KINDS.items() if v == sub), None)
        if kind is not None:
            # 走 hub：同一 kind 复用同一实例（与引擎「模块级单例」等价）
            return _vt_cache_hub().get(kind)
        return LazyCache(directory, *args, **kwargs)

    diskcache.Cache = _vt_lazy_cache_factory
    diskcache._vt_lazy_patched = True
    diskcache._vt_real_cache = real_cache
    return True


def _vt_cache_hub():
    """进程内单例的缓存工厂（幂等）。

    放在这里而不是模块级，是为了让缓存根目录跟随 `engine_paths` 的取值，
    且能在 `VT_DATA_ROOT` 变更后仍取到正确根。
    """
    hub = getattr(vc_lazy_cache_patch, "_hub", None)
    if hub is None:
        from engine_cache import CacheHub
        hub = CacheHub(os.path.join(vc_data_dir(), "cache"))
        try:
            vc_lazy_cache_patch._hub = hub
        except (AttributeError, TypeError):
            pass
    return hub


def vc_lazy_openai_patch():
    """openai 惰性化（2026-10-20 启动优化）。

    openai 3.11 有 1500+ 子模块，本机导入实测 ≈4.4s；而引擎 UI 构建链
    （home_interface → core.llm → check_llm / whisper_api）在模块顶层
    ``from openai import OpenAI`` 就把它整包拉进来——只为界面能打开，而
    绝大多数用户根本不用 OpenAI 通道。这里把 ``sys.modules["openai"]``
    换成惰性桩：import 零成本，``OpenAI(...)`` 首次实例化（或任何属性
    访问）时才导入真包。

    安全性：引擎侧全部是 ``from openai import OpenAI`` 与裸 ``import
    openai``（异常类等属性都在运行期访问），**无子模块导入**
    （无 ``import openai.xxx``）⇒ 桩可透明替换。真包首次导入后桩仍留在
    sys.modules，属性访问一律转发给真模块。
    """
    import sys as _sys
    import types as _types
    import importlib as _importlib
    if "openai" in _sys.modules:
        return True
    state = {}

    class _LazyOpenAI(_types.ModuleType):
        def __getattr__(self, name):
            if name.startswith("__") and name.endswith("__"):
                raise AttributeError(name)
            real = state.get("real")
            if real is None:
                _sys.modules.pop("openai", None)
                try:
                    real = _importlib.import_module("openai")
                finally:
                    _sys.modules["openai"] = self
                state["real"] = real
            if name == "OpenAI":
                def _factory(*a, **k):
                    return real.OpenAI(*a, **k)
                return _factory
            if name == "AsyncOpenAI":
                def _afactory(*a, **k):
                    return real.AsyncOpenAI(*a, **k)
                return _afactory
            return getattr(real, name)

    _sys.modules["openai"] = _LazyOpenAI("openai")
    _vc_log("openai 已惰性化（首次使用 OpenAI 通道时才导入真包）")
    return True


def vc_prepare_settings_file():
    """引擎界面导入前规整 settings.json（幂等，在 prepare_runtime_env 调用）。

    1) 工作目录等路径项全部收进软件文件夹（修掉历史 C 盘 Work_Dir）；
    2) 把全局 LLM 配置注入引擎 OpenAI 兼容槽。
    必须在 videocaptioner.ui.common.config（qconfig 读盘）之前完成。
    """
    try:
        os.makedirs(vc_data_dir(), exist_ok=True)
        existed = os.path.isfile(vc_settings_path())
        data = _vc_read_settings()
        changed = _vc_force_local_paths(data)
        ai = ai_load_config()
        llm = data.setdefault("LLM", {})
        if not bool(ai.get("enabled", True)):
            # 「启用 AI」已关闭：清空引擎 LLM 槽（历史注入的密钥一并清掉），
            # 引擎的优化 / LLM 翻译会明确提示需配置 AI，而不是偷偷消耗额度
            for k in ("OpenAI_API_Key", "OpenAI_API_Base", "OpenAI_Model"):
                if llm.get(k):
                    llm[k] = ""
                    changed = True
        else:
            # v1.12.0：全局 AI 单通道（base_url / api_key / model 一套）
            want = {
                "LLMService": "OpenAI 兼容",
                "OpenAI_API_Base": str(ai.get("base_url") or "").strip(),
                "OpenAI_API_Key": str(ai.get("api_key") or "").strip(),
                "OpenAI_Model": str(ai.get("model") or "").strip(),
            }
            for k, v in want.items():
                if v and llm.get(k) != v:
                    llm[k] = v
                    changed = True
        # v1.12.0：微软翻译已改用 Edge 免认证端点、谷歌翻译已改用 gtx 免费网页版
        # 接口（docs/vc_translate_impl/*.py），两者恢复直连可用。
        # v1.12.0 起字幕翻译板块全面去 AI（仅机翻）：历史配置若被 v1.11.0 迁到
        # 「LLM 大模型翻译」，这里迁回「微软翻译」；翻译失败不再回退 LLM，
        # 如实报错（失败率 ≥50% 时引擎会抛 RuntimeError 提示检查网络）。
        tr = data.setdefault("Translate", {})
        cur_ts = str(tr.get("TranslatorServiceEnum") or "").strip()
        if cur_ts == TS_LLM:
            tr["TranslatorServiceEnum"] = TS_BING
            changed = True
            _vc_log("字幕翻译仅支持机器翻译，已把翻译服务由「LLM 大模型翻译」"
                    "迁回「微软翻译」")
        if changed or not existed:
            _vc_write_settings(data)
        # v1.11.0：ASR（转录配置）与接口 B 同样在引擎读盘前注入
        apply_asr_to_engine(ai)
    except Exception:
        pass


def vc_enforce_runtime_cfg():
    """引擎 QConfig 已加载后的运行期兜底：强制工作目录收敛到软件文件夹。

    防止历史 settings.json 的 C 盘 Work_Dir 在内存里复活、或被界面回写。
    在引擎界面/设置界面构建之后调用（best-effort）。
    """
    try:
        from videocaptioner.ui.common.config import cfg as _cfg
        work_posix = os.path.join(vc_data_dir(), "work-dir").replace(os.sep, "/")
        try:
            cur = str(_cfg.get(_cfg.work_dir) or "")
        except Exception:
            cur = ""
        if cur.replace("\\", "/") != work_posix:
            _cfg.set(_cfg.work_dir, work_posix)
    except Exception:
        pass
    # v1.11.0：转录配置（自有 ASR 服务 / 本地独立模型）与本地模型覆盖补丁
    # 一并在此兜底——引擎界面构建完成后调用，保证内存 QConfig 与磁盘一致。
    try:
        apply_asr_to_engine()
    except Exception:
        pass
    try:
        vc_asr_patch_apply()
    except Exception:
        pass
    # v1.12.0：翻译板块已全面去 AI（仅机翻），「创建失败/无有效产出回退 LLM」
    # 兜底补丁（vc_translate_fallback_patch）整体移除；翻译失败如实报错。


def vc_migrate_legacy_data():
    """把字幕引擎在 C 盘的历史数据迁移到数据根目录（幂等，一次有效）。

    上游在不同版本用过两种布局，都要处理：
      · <legacy>/settings.json、<legacy>/logs/...    —— 直接以 legacy 为数据根
      · <legacy>/VideoCaptioner/settings.json、...   —— 多套了一层同名子目录
    做法：逐个把 legacy 下的「数据项」（settings.json / logs / cache / models /
    resource / work-dir）搬到目标根；若发现 legacy 下还有嵌套的 VideoCaptioner
    子目录，则把它的内容也视作数据项一并搬走，避免出现 VideoCaptioner\\VideoCaptioner。
    目标已存在同名项时不覆盖（保留新位置的数据）。返回迁移的条目数。
    """
    dst_root = vc_data_dir()
    # 2026-10-20 启动优化：legacy 树是**冻结的历史数据**，迁移完成后没必要
    # 每次启动整棵扫描（`_merge_into` 逐文件 stat，冷缓存实测 2.16s）。
    # 用「legacy 目录指纹」做戳，未变化直接返回。
    stamp_path = os.path.join(dst_root, ".vt_legacy_migrated")
    fp_s = None
    try:
        from core.shared.runtime import _VC_LEGACY_DIRS as _LD
        fp = []
        for _d in _LD:
            if os.path.isdir(_d):
                _st = os.stat(_d)
                fp.append((_d, _st.st_mtime_ns, len(os.listdir(_d))))
        fp_s = repr(sorted(fp))
        try:
            with open(stamp_path, encoding="utf-8") as _f:
                if _f.read().strip() == fp_s:
                    return 0          # 已迁移且 legacy 未变：跳过整轮扫描
        except OSError:
            pass
    except Exception:  # noqa: BLE001
        fp_s = None
    # 需要搬运的数据项名（白名单，避免搬进无关文件）
    DATA_ITEMS = ("settings.json", "logs", "cache", "models", "resource",
                  "work-dir", "cli", "llm_requests.jsonl")
    moved = 0

    def _merge(src_dir, depth=0):
        """把 src_dir 下的数据项合并到 dst_root；遇到嵌套同名目录则下钻。"""
        nonlocal moved
        if depth > 2:
            return
        try:
            names = os.listdir(src_dir)
        except OSError:
            return
        nested = []
        for name in names:
            src = os.path.join(src_dir, name)
            # 兼容旧布局：<legacy>/VideoCaptioner/... 下钻一层（稍后处理，
            # 先搬完本层的数据项，避免父目录自己的 settings.json 被漏掉）
            if (name == VC_NAME and os.path.isdir(src)
                    and os.path.abspath(src) != os.path.abspath(dst_root)):
                nested.append(src)
                continue
            if name not in DATA_ITEMS:
                continue
            dst = os.path.join(dst_root, name)
            if os.path.exists(dst):
                # 目录已存在则合并内容（同名文件不覆盖）
                if os.path.isdir(src) and os.path.isdir(dst):
                    moved += _merge_into(src, dst)
                continue
            try:
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.move(src, dst)
                moved += 1
            except OSError:
                pass
        for sub in nested:
            _merge(sub, depth + 1)

    def _merge_into(src_dir, dst_dir):
        """递归合并目录，同名不覆盖；返回搬动的条目数。"""
        n = 0
        try:
            names = os.listdir(src_dir)
        except OSError:
            return 0
        for name in names:
            s = os.path.join(src_dir, name)
            d = os.path.join(dst_dir, name)
            if os.path.isdir(s):
                try:
                    os.makedirs(d, exist_ok=True)
                except OSError:
                    continue
                n += _merge_into(s, d)
            elif not os.path.exists(d):
                try:
                    shutil.move(s, d)
                    n += 1
                except OSError:
                    pass
        return n

    try:
        os.makedirs(dst_root, exist_ok=True)
    except OSError:
        return 0

    for legacy in _VC_LEGACY_DIRS:
        if not legacy or not os.path.isdir(legacy):
            continue
        if os.path.abspath(legacy) == os.path.abspath(dst_root):
            continue
        _merge(legacy)
        _prune_empty(legacy)
    if fp_s is not None:
        try:
            with open(stamp_path, "w", encoding="utf-8") as _f:
                _f.write(fp_s)
        except OSError:
            pass
    return moved


def _prune_empty(root):
    """自底向上删除 root 下的空目录（不含 root 自身）。best-effort。"""
    for cur, dirs, files in os.walk(root, topdown=False):
        if os.path.abspath(cur) == os.path.abspath(root):
            continue
        if files:
            continue
        try:
            os.rmdir(cur)
        except OSError:
            pass


def _dir_has_content(d):
    """目录下是否存在任何文件（含被占用/无权访问的，保守判为有内容）。"""
    try:
        for _cur, _dirs, files in os.walk(d):
            if files:
                return True
    except OSError:
        return True
    return False


def vc_legacy_leftovers():
    """列出仍在 C 盘、且真的含有效数据的历史字幕引擎目录。

    判据是「有文件，且该文件在数据根下还不存在」——迁移后遗留的重复文件
    （数据根已有同名同路径的副本）不算残留，避免误导用户去清理一个已经
    迁空的路径。仅剩空目录树的一律不提示。
    """
    out = []
    dst_root = vc_data_dir()

    def _has_unique_file(d):
        """d 下是否存在数据根里没有对应文件的文件。"""
        try:
            walker = os.walk(d)
        except OSError:
            return False
        for cur, _dirs, files in walker:
            if not files:
                continue
            rel_dir = os.path.relpath(cur, d)
            # <legacy>/ 与 <legacy>/VideoCaptioner/ 两种布局都映射到数据根
            base = os.path.basename(cur)
            for f in files:
                cands = []
                if rel_dir in (".", ""):
                    cands.append(os.path.join(dst_root, f))
                else:
                    cands.append(os.path.join(dst_root, rel_dir, f))
                    # 多套一层同名目录的情况（.../VideoCaptioner/cache/x.db）
                    if base != VC_NAME and VC_NAME in rel_dir.split(os.sep):
                        tail = rel_dir.split(VC_NAME, 1)[1].lstrip(os.sep)
                        cands.append(os.path.join(dst_root, tail, f))
                if not any(os.path.exists(c) for c in cands):
                    return True
        return False

    for d in _VC_LEGACY_DIRS:
        if d and os.path.isdir(d) and _dir_has_content(d) and _has_unique_file(d):
            out.append(d)
    return out




__all__ = [
    "vc_lazy_cache_patch",
    "vc_prepare_settings_file",
    "vc_enforce_runtime_cfg",
    "vc_migrate_legacy_data",
    "vc_legacy_leftovers",
]
