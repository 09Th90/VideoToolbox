# -*- coding: utf-8 -*-
# @version 2.4.1
"""自检：engine_task_factory 与引擎（已打补丁）TaskFactory 的**逐字段**兼容性。

P2 尾部 / 档 B 接缝验收脚本。判定口径不是「能 import / 能构造」，而是：在**同一
cfg 状态 + 同一 ASR 覆盖状态**下，自研工厂产出的任务对象与引擎产物**逐字段一致**
（含嵌套的 TranscribeConfig / SubtitleConfig / SynthesisConfig）。构造任务是纯数据
操作，无需 QApplication，故本自检可完全离线运行。

结构
----
正向：遍历 transcribe_model / llm_service / translator_service 全枚举 × need_next_task
      × need_split × need_translate × use_subtitle_style × ASR 覆盖（无 / 本地模型 /
      显式语言）等状态，逐字段比对 create_transcribe_task / create_subtitle_task /
      create_synthesis_task。
负向：故意污染自研工厂的一个字段，确认本检查**确实能抓到**（防「绿屏假象」）。

用法
----
    python scripts/dev/_selftest_engine_task_factory.py

退出码 0 = 通过。用随包 CPython（tools/python）跑，VT_DATA_ROOT 指向临时目录以隔离
真实 settings.json（枚举状态会写 cfg）。
"""
import dataclasses
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
SRC = os.path.join(ROOT, "src")
PYPARSE = os.path.join(ROOT, "tools", "python", "python.exe")
if not os.path.exists(PYPARSE):
    PYPARSE = sys.executable

SKIP_FIELDS = {"queued_at"}  # 时间戳天然不同


# --------------------------------------------------------------------------
# 在子进程内执行的比对逻辑（避免污染父进程，且正/负向各自独立进程）
# --------------------------------------------------------------------------
def _inprocess(mode: str) -> int:
    sys.path.insert(0, SRC)
    import video_toolbox as vt
    vt.prepare_runtime_env()
    vt.vc_asr_patch_apply()          # 确保引擎工厂已打补丁（比对基准）
    from videocaptioner.ui.common.config import cfg
    from videocaptioner.ui.task_factory import TaskFactory as Eng
    from videocaptioner.core import entities as ent
    import engine_task_factory as etf
    Self = etf.TaskFactory

    if mode == "negative":
        # 污染自研工厂：让 create_subtitle_task 的 thread_num 多 1（staticmethod
        # 经类访问即普通函数，直接取用，无 __func__）
        _orig = Self.create_subtitle_task

        def _bad(*a, **k):
            t = _orig(*a, **k)
            try:
                t.subtitle_config.thread_num = t.subtitle_config.thread_num + 1
            except Exception:
                t.output_path = t.output_path + ".CORRUPT"
            return t
        Self.create_subtitle_task = staticmethod(_bad)

    diffs = []

    def cmp(tag, a, b):
        fa, fb = _flatten(a), _flatten(b)
        if fa != fb:
            keys = sorted(set(fa) | set(fb))
            for k in keys:
                if fa.get(k, "<缺>") != fb.get(k, "<缺>"):
                    diffs.append("%s :: %s  engine=%r self=%r"
                                 % (tag, k, fa.get(k, "<缺>"), fb.get(k, "<缺>")))

    def _flatten(obj, prefix=""):
        out = {}
        if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
            for f in dataclasses.fields(obj):
                if f.name in SKIP_FIELDS:
                    continue
                out.update(_flatten(getattr(obj, f.name), prefix + f.name + "."))
        elif isinstance(obj, dict):
            for k, v in obj.items():
                out.update(_flatten(v, prefix + str(k) + "."))
        else:
            out[prefix.rstrip(".")] = _norm(obj)
        return out

    def _norm(v):
        # 枚举/路径统一成可比较的稳定表示
        return getattr(v, "value", v) if hasattr(v, "value") and not isinstance(v, (str, int, float, bool)) else v

    FILE = os.path.join(tempfile.gettempdir(), "vt_tf_sample.mkv")
    SUB = os.path.join(tempfile.gettempdir(), "vt_tf_sample.srt")

    # ---- ASR 覆盖状态：通过替换 video_toolbox 的助手函数模拟（两工厂同源调用）----
    # ⚠ 必须**同时**替换 core.asr.engine_config 里的同名全局名（2026-10-19 假红教训）：
    #   · 引擎侧补丁 vc_asr_patch_apply 的闭包在 engine_config 模块作用域求值
    #     `asr_local_override` / `ai_mod` / `ai_load_config`，绑定的是**该模块的全局名**；
    #   · 自研 engine_task_factory 走 `_engine_helpers()` → video_toolbox 模块属性。
    #   只替换 vt.* 时引擎侧仍读真实配置 ⇒ 两侧输入不同 ⇒ 大量伪差异
    #   （实测差异全是 faster_whisper_model / transcribe_language，即覆盖逻辑本身）。
    import core.asr.engine_config as _ec

    _dual = (vt, _ec)   # 需要同步打桩的模块

    def set_asr(mode_kind, label=""):
        if mode_kind == "none":
            for m in _dual:
                m.asr_local_override = lambda ai_cfg=None: None
            vt.ai_load_config = lambda: {}
            _ec.ai_load_config = lambda: {}
        elif mode_kind == "local":
            for m in _dual:
                m.asr_local_override = lambda ai_cfg=None: ("my-custom-model", "/my/model/dir")
            vt.ai_load_config = lambda: {}
            _ec.ai_load_config = lambda: {}
        elif mode_kind == "lang":
            for m in _dual:
                m.asr_local_override = lambda ai_cfg=None: None
            # 让 ai_mod().asr_config(...) 返回带 language_label 的 dict
            class _AI:
                def asr_config(self, c):
                    return {"mode": "service", "language_label": label}
                def asr_language_code(self, l):
                    return "zh"
            vt.ai_mod = lambda: _AI()
            _ec.ai_mod = lambda: _AI()
            vt.ai_load_config = lambda: {}
            _ec.ai_load_config = lambda: {}

    _saved = [(m, m.ai_mod, m.ai_load_config, m.asr_local_override) for m in _dual]

    # 自证：桩是否真的打到两侧（防止再次出现「只改 vt」的静默假红）
    def _stub_effective():
        return (vt.asr_local_override is not _saved[0][3]
                and _ec.asr_local_override is not _saved[1][3])

    try:
        # ================= create_transcribe_task =================
        for tm in list(ent.TranscribeModelEnum):
            cfg.set(cfg.transcribe_model, tm)
            for nnt in (False, True):
                for split in (False, True):
                    cfg.set(cfg.need_split, split)
                    for asr in ("none", "local", "lang"):
                        set_asr(asr, label="日本語" if asr == "lang" else "")
                        if not _stub_effective():
                            diffs.append("桩未生效[t=%s]：vt/engine_config 覆盖不同步" % asr)
                        tag = "transcribe[%s,nnt=%s,split=%s,asr=%s]" % (tm.name, nnt, split, asr)
                        cmp(tag,
                            Eng.create_transcribe_task(FILE, need_next_task=nnt, task_id="T1"),
                            Self.create_transcribe_task(FILE, need_next_task=nnt, task_id="T1"))
        cfg.set(cfg.need_split, False)

        # ================= create_subtitle_task =================
        for llm in list(ent.LLMServiceEnum):
            cfg.set(cfg.llm_service, llm)
            for tr in list(ent.TranslatorServiceEnum):
                cfg.set(cfg.translator_service, tr)
                for nt in (False, True):
                    cfg.set(cfg.need_translate, nt)
                    for nnt in (False, True):
                        tag = "subtitle[llm=%s,tr=%s,nt=%s,nnt=%s]" % (llm.name, tr.name, nt, nnt)
                        cmp(tag,
                            Eng.create_subtitle_task(SUB, FILE, need_next_task=nnt, task_id="S1"),
                            Self.create_subtitle_task(SUB, FILE, need_next_task=nnt, task_id="S1"))
        cfg.set(cfg.need_translate, False)

        # ================= create_synthesis_task =================
        for style in (False, True):
            cfg.set(cfg.use_subtitle_style, style)
            for nv in (False, True):
                cfg.set(cfg.need_video, nv)
                tag = "synthesis[style=%s,nv=%s]" % (style, nv)
                cmp(tag,
                    Eng.create_synthesis_task(FILE, SUB, need_next_task=False, task_id="Y1"),
                    Self.create_synthesis_task(FILE, SUB, need_next_task=False, task_id="Y1"))
    finally:
        for m, _am, _al, _ov in _saved:
            m.ai_mod = _am
            m.ai_load_config = _al
            m.asr_local_override = _ov

    if mode == "negative":
        # 负向：必须**抓到**至少一处差异，否则说明比对形同虚设
        if diffs:
            print("NEGATIVE OK: 污染被检出（%d 处），示例：%s" % (len(diffs), diffs[0]))
            return 0
        print("NEGATIVE FAIL: 污染未被检出——比对无效（假绿）")
        return 3

    if diffs:
        print("POSITIVE FAIL: %d 处字段不一致" % len(diffs))
        for d in diffs[:60]:
            print("  DIFF", d)
        return 1
    print("POSITIVE OK: 全部状态逐字段一致")
    return 0


def _run(mode: str) -> int:
    tmp = tempfile.mkdtemp(prefix="vt_tf_selftest_")
    env = dict(os.environ)
    env["PYTHONPATH"] = SRC + os.pathsep + env.get("PYTHONPATH", "")
    env["VT_DATA_ROOT"] = tmp
    env["VT_SELFTEST"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"   # 子进程 stdout 用 utf-8，避免 Windows GBK
    code = (
        "import sys; sys.path.insert(0, r'%s');"
        "import importlib.util as u;"
        "spec=u.spec_from_file_location('st', r'%s');"
        "m=u.module_from_spec(spec); spec.loader.exec_module(m);"
        "sys.exit(m._inprocess('%s'))"
    ) % (SRC, os.path.abspath(__file__), mode)
    p = subprocess.run([PYPARSE, "-c", code], env=env, capture_output=True,
                       encoding="utf-8", errors="replace")
    if p.stdout:
        sys.stdout.write(p.stdout)
    if p.stderr:
        sys.stderr.write(p.stderr)
    return p.returncode


def main():
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    print("=== engine_task_factory 自检（逐字段 vs 引擎已打补丁工厂）===")
    rc_pos = _run("positive")
    rc_neg = _run("negative")
    ok = (rc_pos == 0 and rc_neg == 0)
    print("=" * 50)
    print("RESULT:", "PASS" if ok else "FAIL", "(positive=%d negative=%d)" % (rc_pos, rc_neg))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
