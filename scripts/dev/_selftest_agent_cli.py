# -*- coding: utf-8 -*-
# @version 2.5.0
"""第三方 Agent 接入（agent_cli + 技能包）回归自检（2026-10-15）。

背景：用户要求「harness 必须非常清楚工具箱能干什么、直接调用」，且第三方
Agent（Claude Code / WorkBuddy / Trae / Kimi…）要能完全接入、效果与内置
harness 一致。落地物 = 统一 CLI（src/agent_cli.py）+ 技能包（AGENTS.md /
SKILL.md 及各 Agent 约定副本）+ bridge 物化（ensure_agent_assets）。

逐条验证（每条带「确实生效」的正向对照，避免假阳性）：

  1  CLI --version / --help / 各子命令 --help 退出码 0
  2  --json 放子命令前后两个位置都认（Agent 本能写法）
  3  status --json：stdout 是单个 JSON 对象，ok=true，AI 槽已配置
  4  info：样例 SRT 的 cue 数/时间跨度正确
  5  translate：必应端点实跑，产物为双语（含中文），时间轴不动
  6  calibrate：透传退出码 0，--out 产物存在
  7  stabilize：透传退出码 0
  8  技能包：静态文件与 bridge 常量逐字节同源；ensure_agent_assets 幂等；
     DSH_HOME 两落点存在；SKILL.md frontmatter 含 name/description
  9  compose --help 可用（不实跑，避免重编码耗时）

用法：tools\\python\\python.exe scripts\\dev\\_selftest_agent_cli.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(ROOT, "src")
PY = os.path.join(ROOT, "tools", "python", "python.exe")
CLI = os.path.join(SRC, "agent_cli.py")

PASS, FAIL = [], []


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print("%s %s%s" % ("[OK]" if ok else "[FAIL]", name,
                       (" —— " + detail) if detail else ""))


def run_cli(argv, timeout=300):
    return subprocess.run([PY, CLI] + argv, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout,
                          cwd=ROOT)


def main() -> int:
    if not os.path.isfile(PY):
        print("缺少 tools\\python\\python.exe")
        return 2
    tmp = tempfile.mkdtemp(prefix="vt_agentcli_")
    sample = os.path.join(tmp, "probe.en.srt")
    with open(sample, "w", encoding="utf-8", newline="\n") as f:
        f.write("1\n00:00:01,000 --> 00:00:03,000\n"
                "Hello, welcome to the show.\n\n"
                "2\n00:00:03,000 --> 00:00:06,000\n"
                "Today we talk about Arknights Endfield.\n\n"
                "3\n00:00:06,000 --> 00:00:09,000\n"
                "The Industrial Center is under attack.\n")

    # 1 —— version / help
    r = run_cli(["--version"])
    check("CLI --version", r.returncode == 0 and "agent_cli" in r.stdout,
          r.stdout.strip()[:60])
    r = run_cli(["--help"])
    check("CLI --help", r.returncode == 0 and "子命令" in r.stdout)
    for sub in ("status", "info", "download", "transcribe", "translate",
                "calibrate", "stabilize", "compose"):
        r = run_cli([sub, "--help"])
        check("子命令 --help: %s" % sub, r.returncode == 0)

    # 2 —— --json 两个位置
    r1 = run_cli(["--json", "status"])
    r2 = run_cli(["status", "--json"])
    ok = (r1.returncode == 0 and r2.returncode == 0
          and json.loads(r1.stdout).get("ok") is True
          and json.loads(r2.stdout).get("ok") is True)
    check("--json 前后位置都认", ok)

    # 3 —— status 结构
    d = json.loads(r2.stdout)
    check("status --json 单对象+ok", isinstance(d, dict) and d.get("ok") is True
          and d.get("ai", {}).get("configured") is True,
          "model=%s" % d.get("ai", {}).get("model"))

    # 4 —— info
    r = run_cli(["info", sample, "--json"])
    d = json.loads(r.stdout) if r.returncode == 0 else {}
    check("info SRT cue 数", d.get("n_cues") == 3, str(d.get("n_cues")))

    # 5 —— translate（必应实跑）
    zh = os.path.join(tmp, "probe.zh.srt")
    r = run_cli(["translate", sample, "--engine", "bing", "--to", "zh-Hans",
                 "--out", zh, "--json"])
    d = json.loads(r.stdout) if r.returncode == 0 else {}
    body = open(zh, encoding="utf-8").read() if os.path.isfile(zh) else ""
    check("translate 双语产物", d.get("ok") is True
          and any("\u4e00" <= c <= "\u9fff" for c in body)
          and "00:00:01,000 --> 00:00:03,000" in body,
          d.get("error", ""))

    # 6 —— calibrate 透传
    cal = os.path.join(tmp, "probe.calib.srt")
    r = run_cli(["calibrate", sample.replace(".en.srt", ".zh.srt"),
                 "--endobi", "--out", cal, "--report",
                 os.path.join(tmp, "r.tsv")])
    check("calibrate 透传退出码 0 + 产物存在",
          r.returncode == 0 and os.path.isfile(cal),
          (r.stdout or r.stderr)[-120:])

    # 7 —— stabilize 透传
    st = os.path.join(tmp, "probe.stab.srt")
    r = run_cli(["stabilize", zh, "--out", st])
    check("stabilize 透传退出码 0", r.returncode == 0,
          (r.stdout or r.stderr)[-120:])

    # 8 —— 技能包
    sys.path.insert(0, SRC)
    import harness_bridge as hb  # noqa: PLC0415
    import pathlib
    root_p = pathlib.Path(ROOT)
    same = ((root_p / "AGENTS.md").read_text(encoding="utf-8") == hb._AGENTS_MD_TEXT
            and (root_p / "SKILL.md").read_text(encoding="utf-8") == hb._SKILL_MD_TEXT
            and (root_p / ".claude/skills/video-toolbox/SKILL.md")
            .read_text(encoding="utf-8") == hb._SKILL_MD_TEXT
            and (root_p / ".workbuddy/skills/video-toolbox/SKILL.md")
            .read_text(encoding="utf-8") == hb._SKILL_MD_TEXT
            and (root_p / ".agents/skills/video-toolbox/SKILL.md")
            .read_text(encoding="utf-8") == hb._SKILL_MD_TEXT
            and (root_p / ".trae/rules/project_rules.md")
            .read_text(encoding="utf-8") == hb._AGENTS_MD_TEXT)
    check("技能包静态文件与 bridge 常量逐字节同源", same)
    a1 = hb.ensure_agent_assets()
    a2 = hb.ensure_agent_assets()
    check("ensure_agent_assets 幂等", a1.get("ok") and a2.get("written") == 0,
          str(a2))
    home = hb.dsh_home()
    check("DSH_HOME 技能包落点",
          os.path.isfile(os.path.join(home, "AGENTS.md"))
          and os.path.isfile(os.path.join(home, "skills", "video-toolbox",
                                          "SKILL.md")))
    skill_text = (root_p / "SKILL.md").read_text(encoding="utf-8")
    check("SKILL.md frontmatter 合规",
          skill_text.startswith("---\n") and "\nname: video-toolbox\n" in skill_text
          and "\ndescription: " in skill_text)

    # 9 —— compose --help（不实跑）
    r = run_cli(["compose", "--help"])
    check("compose --help", r.returncode == 0 and "burn" in r.stdout)

    # 收尾：清理临时产物
    try:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
    except Exception:  # noqa: BLE001
        pass

    print("\n==== 结果：%d 通过 / %d 失败 ====" % (len(PASS), len(FAIL)))
    if FAIL:
        for f in FAIL:
            print("  FAIL:", f)
        return 1
    print("ALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
