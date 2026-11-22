# -*- coding: utf-8 -*-
# @version 3.2.0
"""功能注册表 / 插件化护栏自检（2026-11-15 功能解耦）。

逐条验证「每个功能独立、互相调用、缺失不影响启动、可扩展」的架构契约：

  1  注册表发现：16 个功能全在位、零发现错误、_template 被跳过
  2  适配器纯净：feature.py / cli.py 模块级禁 Qt（AST 断言）
  3  错误隔离：损坏功能包只记录 reason，不传染、不外抛
  4  缺失降级：功能缺席时 build_parser 仍可用（只少对应子命令）
  5  JSON 信封：后端异常（模拟 ensure_* 缺依赖）落 {"ok":false,"error":…}
  6  服务解析：service() 惰性可调用；未知功能/服务抛 FeatureUnavailable
  7  透传名单：calibrate/stabilize/audit 与注册表一致
  8  CLI 行为面：--version/--help/status --json（含 features 段）/compose --help
  9  compose 核心无 Qt：import subtitle_compose_core 不拉起 PySide6
 10  兼容面：agent_cli 旧符号再导出齐全

用法：tools\\python\\python.exe scripts\\dev\\_selftest_features.py
"""
from __future__ import annotations

import ast
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(ROOT, "src")
PY = os.path.join(ROOT, "tools", "python", "python.exe")
CLI = os.path.join(SRC, "agent_cli.py")
sys.path.insert(0, SRC)

PASS, FAIL = [], []

EXPECTED = {"status", "info", "download", "transcribe", "translate",
            "calibrate", "compose", "split", "automation", "merge",
            "workbench", "pipeline", "library", "subtitle_edit",
            "voiceprint", "harness", "mcp"}


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print("%s %s%s" % ("[OK]" if ok else "[FAIL]", name,
                       (" —— " + detail) if detail else ""))


def run_cli(argv, timeout=300):
    return subprocess.run([PY, CLI] + argv, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout,
                          cwd=ROOT)


def main() -> int:
    import features
    from features import (FeatureRegistry, FeatureSpec, FeatureUnavailable,
                          GuiSpec, registry)

    # 1 —— 发现
    reg = registry()
    specs = reg.specs()
    errs = reg.errors()
    check("注册表发现 17 功能", set(specs) == EXPECTED and not errs,
          "缺=%s 多=%s 错=%s" % (sorted(EXPECTED - set(specs)),
                                sorted(set(specs) - EXPECTED), errs))
    check("_template 被跳过", "_template" not in specs)
    check("probe 绝不抛异常", all(isinstance(reg.probe(f), tuple)
                                 for f in list(specs) + ["不存在的功能"]))

    # 2 —— 适配器模块级禁 Qt（AST）
    # 扫描面＝适配器与包基建（feature.py/cli.py/__init__.py/_registry/_cli/_media）；
    # GUI 模块（page.py、subtitle_compose.py 等对话框）合法用 Qt，不受此约束
    # （2026-11-15：subtitle_compose 迁入 features/compose/ 后，旧「只排除
    # page.py」黑名单误伤 GUI 对话框模块，改为按适配器白名单扫描）。
    qt_roots = {"PySide6", "PyQt5", "PyQt6", "qfluentwidgets", "vt_fluent"}
    adapter_names = {"feature.py", "cli.py", "__init__.py",
                     "_registry.py", "_cli.py", "_media.py"}
    bad = []
    for dirpath, _dirs, files in os.walk(os.path.join(SRC, "features")):
        for fn in files:
            if fn not in adapter_names:
                continue
            p = os.path.join(dirpath, fn)
            try:
                tree = ast.parse(open(p, encoding="utf-8").read())
            except SyntaxError as e:
                bad.append("%s: 语法错 %s" % (p, e))
                continue
            for node in tree.body:      # 只看模块级
                mods = []
                if isinstance(node, ast.Import):
                    mods = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    mods = [node.module]
                for m in mods:
                    if m.split(".")[0] in qt_roots:
                        bad.append("%s:%d import %s" % (p, node.lineno, m))
    check("适配器模块级无 Qt", not bad, "; ".join(bad[:5]))

    # 3/4 —— 错误隔离 + 缺失降级（临时功能包，不碰 src）
    tmp = tempfile.mkdtemp(prefix="vt_ftest_", dir=os.path.join(ROOT, "data", "tmp"))
    pkg_name = "vt_ftest_%d" % os.getpid()
    pkg_dir = os.path.join(tmp, pkg_name)
    os.makedirs(os.path.join(pkg_dir, "good"))
    os.makedirs(os.path.join(pkg_dir, "bad"))
    open(os.path.join(pkg_dir, "__init__.py"), "w").close()
    open(os.path.join(pkg_dir, "good", "__init__.py"), "w").close()
    with open(os.path.join(pkg_dir, "good", "feature.py"), "w", encoding="utf-8") as f:
        f.write("from features._registry import CliCommand, FeatureSpec\n"
                "FEATURE = FeatureSpec(id='good', title='好功能',\n"
                "    cli=(CliCommand(name='goodcmd', help='h',\n"
                "        setup='%s.good.cli:setup_good'),))\n" % pkg_name)
    with open(os.path.join(pkg_dir, "good", "cli.py"), "w", encoding="utf-8") as f:
        f.write("def setup_good(sub):\n"
                "    s = sub.add_parser('goodcmd')\n"
                "    s.set_defaults(fn=lambda args: 0)\n")
    open(os.path.join(pkg_dir, "bad", "__init__.py"), "w").close()
    with open(os.path.join(pkg_dir, "bad", "feature.py"), "w", encoding="utf-8") as f:
        f.write("raise RuntimeError('模拟损坏的功能包')\n")
    sys.path.insert(0, tmp)
    try:
        treg = FeatureRegistry(pkg_name).discover()
        check("损坏包被隔离", "good" in treg.specs() and "bad" in treg.errors()
              and "模拟损坏" in treg.errors()["bad"], str(treg.errors()))
        # 缺失降级：把全局注册表换成只含 good 的临时表，build_parser 仍可用
        import agent_cli
        saved = features._default
        features._default = treg
        try:
            p = agent_cli.build_parser()
            check("功能缺席不破坏 CLI 装配",
                  "goodcmd" in p._subparsers._group_actions[0].choices
                  and "status" not in p._subparsers._group_actions[0].choices)
        finally:
            features._default = saved
    finally:
        sys.path.remove(tmp)
        for m in [m for m in sys.modules if m.startswith(pkg_name)]:
            del sys.modules[m]
        shutil.rmtree(tmp, ignore_errors=True)

    # 5 —— JSON 信封：模拟后端异常（ensure_* 缺依赖同款路径）
    # 2026-11-20 三层独立：compose 编排下沉 _api，_engine 补丁点随迁
    import agent_cli
    import features._api.commands.compose as compose_cmd
    saved_engine = compose_cmd._engine

    def _boom():
        raise RuntimeError("模拟依赖缺失（ffmpeg 未就位）")

    compose_cmd._engine = _boom
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            rc = agent_cli.main(["compose", "a.mp4", "b.srt", "--json"])
    finally:
        compose_cmd._engine = saved_engine
    try:
        d = json.loads(buf.getvalue())
    except ValueError:
        d = {}
    check("后端异常落 JSON 信封", rc == 1 and d.get("ok") is False
          and "模拟依赖缺失" in d.get("error", ""), buf.getvalue()[:120])

    # 6 —— 服务解析
    check("service 惰性可调用", callable(reg.service("split", "plan_split"))
          and callable(reg.service("calibrate", "main_argv")))
    try:
        reg.service("split", "不存在的服务")
        ok = False
    except FeatureUnavailable:
        ok = True
    try:
        reg.service("不存在的功能", "x")
        ok2 = False
    except FeatureUnavailable:
        ok2 = True
    check("未知功能/服务抛 FeatureUnavailable", ok and ok2)
    check("GuiSpec 契约可构造",
          GuiSpec(nav="x", builder="m:f").position == "top")

    # 7 —— 透传名单
    check("透传名单同源", reg.passthrough_names() == ["calibrate", "stabilize", "audit"],
          str(reg.passthrough_names()))

    # 8 —— CLI 行为面（子进程）
    r = run_cli(["--version"])
    check("CLI --version", r.returncode == 0 and "agent_cli" in r.stdout)
    r = run_cli(["--help"])
    check("CLI --help", r.returncode == 0 and "子命令" in r.stdout)
    r = run_cli(["status", "--json"])
    try:
        d = json.loads(r.stdout)
    except ValueError:
        d = {}
    feats = d.get("features")
    check("status --json + features 段",
          r.returncode == 0 and d.get("ok") is True
          and isinstance(feats, list)
          and {f["id"] for f in feats} == EXPECTED
          and all(isinstance(f["available"], bool) for f in feats),
          str(d.get("error", ""))[:100])
    r = run_cli(["compose", "--help"])
    check("compose --help", r.returncode == 0 and "burn" in r.stdout)

    # 9 —— compose 核心无 Qt
    r = subprocess.run(
        [PY, "-c", "import sys; sys.path.insert(0, r'%s'); "
         "import features.compose.subtitle_compose_core; "
         "assert not any(m.startswith('PySide6') for m in sys.modules), 'Qt 泄漏'; "
         "print('PURE')" % SRC],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=120, cwd=ROOT)
    check("compose 核心无 Qt", r.returncode == 0 and "PURE" in r.stdout,
          (r.stderr or "")[-120:])

    # 10 —— 兼容面
    missing = [n for n in agent_cli.__all__ if not hasattr(agent_cli, n)]
    check("agent_cli 兼容再导出齐全", not missing, str(missing))

    print("\n==== 结果：%d 通过 / %d 失败 ====" % (len(PASS), len(FAIL)))
    if FAIL:
        for f in FAIL:
            print("  FAIL:", f)
        return 1
    print("ALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())