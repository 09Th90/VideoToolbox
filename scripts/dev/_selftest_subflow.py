# -*- coding: utf-8 -*-
# @version 2.7.0
"""subflow 自检：SRT/mosp 往返、知识库导出解析、任务状态机与烧录链路。

按项目自检惯例（内置 Python 运行）：
    tools\\python\\python.exe scripts\\dev\\_selftest_subflow.py

全部产物落在临时目录，结束清理；唯一外部依赖是 tools/ffmpeg.exe（烧录实测）。
MAW 编辑器启动环节涉及 GUI 服务与浏览器，不在本脚本范围（验证见 README）。
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "subflow"))

import bridges  # noqa: E402
import kb_export  # noqa: E402
import mosp_bridge  # noqa: E402
import subflow  # noqa: E402
from bridges import ToolConfig, ToolError  # noqa: E402

_CHECKS = 0
_FAILURES: list[str] = []


def check(cond: bool, label: str) -> None:
    global _CHECKS
    _CHECKS += 1
    if cond:
        print(f"  ok  {label}")
    else:
        _FAILURES.append(label)
        print(f"  FAIL {label}")


def make_cfg(tmp: Path) -> ToolConfig:
    cfg = ToolConfig.load()
    cfg.root = tmp / "workflow"
    cfg.ensure_dirs()
    return cfg


# ---------- 1. SRT 解析与 mosp 往返 ----------
def test_mosp_roundtrip(tmp: Path) -> None:
    print("[1] SRT 解析与 .mosp 往返")
    srt_text = (
        "1\n00:00:01,000 --> 00:00:02,500\n大家好\n\n"
        "2\n00:00:03,120 --> 00:00:05,840\n这是第二行字幕\n跨行文本\n\n"
        "3\n00:00:06,000 --> 00:00:07,000\n尾随空格行   \n"
    )
    srt_path = tmp / "in.srt"
    mosp_bridge.write_text(srt_path, srt_text, crlf=True)

    cues = mosp_bridge.parse_srt(mosp_bridge.read_text_any(srt_path))
    check(len(cues) == 3, f"解析 3 条 cue（实际 {len(cues)}）")
    check(cues[0].start_ms == 1000 and cues[0].end_ms == 2500, "毫秒换算正确")
    check(cues[1].normalized_text() == "这是第二行字幕\n跨行文本", "多行文本保留换行")
    check(cues[2].normalized_text() == "尾随空格行", "行尾空白剥除")

    mosp = tmp / "t.mosp"
    n = mosp_bridge.srt_to_mosp(srt_path, Path("D:/media/x.mp4"), mosp, language="ja")
    check(n == 3, f"srt_to_mosp 段数（{n}）")
    project = json.loads(mosp_bridge.read_text_any(mosp))
    check(project["schema"] == mosp_bridge.MOSP_SCHEMA, "schema 标记正确")
    check(project["media"] == "D:/media/x.mp4", "media 路径正斜杠化")
    check(project["segments"][0]["start"] == 1000 and isinstance(project["segments"][0]["start"], int), "整数毫秒")
    check(project["segments"][1]["text"] == "这是第二行字幕\n跨行文本", "text 换行进工程")
    check(project["segments"][0]["items"] == [], "items 空数组（编辑器自动插值）")
    check(not mosp.read_bytes().startswith(b"\xef\xbb\xbf"), "mosp 无 BOM")

    back = tmp / "back.srt"
    m = mosp_bridge.mosp_to_srt(mosp, back)
    check(m == 3, f"mosp_to_srt 段数（{m}）")
    cues2 = mosp_bridge.parse_srt(mosp_bridge.read_text_any(back))
    check(
        [(c.start_ms, c.end_ms, c.normalized_text()) for c in cues]
        == [(c.start_ms, c.end_ms, c.normalized_text()) for c in cues2],
        "SRT → mosp → SRT 语义无损",
    )
    check(back.read_bytes().replace(b"\r\n", b"\n").count(b"\n") > 0 and b"\r\n" in back.read_bytes(), "SRT 落盘 CRLF")

    # disabled 段应被跳过
    project["segments"][1]["disabled"] = True
    mosp_bridge.write_text(mosp, json.dumps(project, ensure_ascii=False, indent=2), crlf=False)
    m2 = mosp_bridge.mosp_to_srt(mosp, back)
    check(m2 == 2, f"disabled 段跳过（{m2}）")

    # 空文本段也应被跳过（MAW 工程可能出现空 cue）
    project["segments"][1]["disabled"] = False
    project["segments"][1]["text"] = ""
    mosp_bridge.write_text(mosp, json.dumps(project, ensure_ascii=False, indent=2), crlf=False)
    check(mosp_bridge.mosp_to_srt(mosp, back) == 2, "空文本段跳过")

    # 换行二次翻译回归：输入已含 CRLF 的文本再写 crlf=True 不得出现 \r\r\n
    crlf_in = tmp / "crlf_in.srt"
    crlf_out = tmp / "crlf_out.srt"
    mosp_bridge.write_text(crlf_in, "1\n00:00:00,000 --> 00:00:00,500\n甲\n\n2\n00:00:01,000 --> 00:00:01,500\n乙\n", crlf=True)
    mosp_bridge.write_text(crlf_out, mosp_bridge.read_text_any(crlf_in), crlf=True)
    check(b"\r\r\n" not in crlf_out.read_bytes(), "write_text 对 CRLF 输入不二次翻译")
    check(crlf_out.read_bytes().count(b"\r\n") == 7, "CRLF 行数正确（无行间空行膨胀）")


# ---------- 2. 知识库导出 ----------
def test_kb_export(cfg: ToolConfig) -> None:
    print("[2] 知识库导出（以 finesub 官方样板为主库）")
    sample = REPO_ROOT / "downloads" / "finesub" / "examples" / "knowledge"
    rendered = cfg.knowledge_root / "rendered"
    if not sample.exists():
        print("  skip 样板缺失（downloads/finesub 不在），跳过")
        return
    for cat in ("common", "streamer", "style"):
        src_dir = sample / cat
        if src_dir.exists():
            shutil.copytree(src_dir, rendered / cat, dirs_exist_ok=True)

    terms, stats = kb_export.collect(cfg)
    by_pair = {(t.src, t.zh): t for t in terms}
    check(("空月の歌", "空月之歌") in by_pair, "条目术语行：源语言→中文定名")
    check(("ナド・クライ", "挪德卡莱") in by_pair, "条目术语行二")
    check(("Lauma", "菈乌玛") in by_pair, "别名列展开（英文别名）")
    check("以挪德卡莱为舞台" in by_pair[("空月の歌", "空月之歌")].note, "含竖线的描述完整保留")
    check(("原神", "原神") not in by_pair, "[本名] 同名去重（源=译名不导出）")
    check(("げんしん", "原神") in by_pair, "[本名] 括号读音展开为别名行")
    check(
        not any("行式" in t.src for t in terms),
        "条目 HTML 注释中的行式示例不混入术语",
    )
    check(("原神", "空月之歌") not in by_pair, "index 别名格的 CJK 项不错误映射为定名")
    streamer_hit = [t for t in terms if "四月一日" in t.src]
    check(bool(streamer_hit), "streamer index 行导出")
    check(all(t.category != "style" for t in terms), "style 目录未混入")

    summary = kb_export.sync(cfg)
    tsv = cfg.glossary_dir / kb_export._EXPORT_TSV
    rows = [l for l in mosp_bridge.read_text_any(tsv).splitlines() if l and not l.startswith("#")]
    check(len(rows) == summary.tsv_rows and summary.tsv_rows > 0, f"TSV 落盘 {summary.tsv_rows} 行")
    first = rows[0].split("\t")
    check(len(first) == 3, "TSV 三列（原文/译名/类别）")
    hot = mosp_bridge.read_text_any(cfg.glossary_dir / kb_export._EXPORT_HOTWORDS)
    check(len([w for w in hot.splitlines() if w]) == summary.hotwords, "MAW 热词落盘")
    check(bool(summary.summary), "同步摘要可读")
    for s in summary.summary:
        print(f"      {s}")


# ---------- 3. 任务状态机（add → 伪造精修 → mosp → burn 实测） ----------
def test_task_state_machine(tmp: Path, cfg: ToolConfig) -> None:
    print("[3] 任务状态机（本地媒体 → 伪造精修产物 → 烧录实测）")
    ffmpeg = cfg.ffmpeg_bin
    if not ffmpeg.exists():
        print(f"  skip tools/ffmpeg.exe 缺失（{ffmpeg}），烧录实测跳过")
        return

    # 生成 3 秒测试媒体
    media = tmp / "sample.mp4"
    bridges.run_logged(
        [str(ffmpeg), "-y", "-f", "lavfi", "-i", "testsrc=duration=3:size=320x240:rate=10",
         "-f", "lavfi", "-i", "sine=duration=3", "-c:v", "libx264", "-c:a", "aac", "-shortest", str(media)],
        timeout_s=120,
    )
    check(media.exists() and media.stat().st_size > 1000, "ffmpeg 生成测试媒体")

    args = argparse.Namespace(source=str(media), lang="ja", extra_info="自检样片", name=None, knowledge="collect")
    subflow.cmd_add(args, cfg)
    task = subflow.Task.load(cfg, "sample")
    check(task.stage == "queued", "add 后 stage=queued")
    check(task.name == "sample", "本地文件任务名取文件主干")

    # transcribe：绕过真实 finesub，直接放成品 SRT 模拟产物就位（幂等门槛是产物存在）
    final = task.dir / "finesub" / "sample.srt"
    mosp_bridge.write_text(final, "1\n00:00:00,200 --> 00:00:01,800\n自检字幕行\n", crlf=True)
    raw = task.dir / "finesub" / "sample-raw.srt"
    mosp_bridge.write_text(raw, "1\n00:00:00,200 --> 00:00:01,800\nraw行\n", crlf=True)
    srt = task.ensure_transcribed()
    check(srt == final and task.artifact("raw_srt") == raw, "ensure_transcribed 幂等复用已有产物")
    task.ensure_media()
    task.set_stage("review")
    task.save()

    mosp = task.ensure_mosp()
    check(mosp.exists() and json.loads(mosp_bridge.read_text_any(mosp))["segments"][0]["text"] == "自检字幕行", "工程文件生成")

    # 校对交接：模拟用户保存 .mosp（改文本 + mtime 前移）→ 渲染回 SRT
    project = json.loads(mosp_bridge.read_text_any(mosp))
    project["segments"][0]["text"] = "校对后的字幕行"
    mosp_bridge.write_text(mosp, json.dumps(project, ensure_ascii=False, indent=2), crlf=False)
    reviewed = task.dir / "review" / "sample-reviewed.srt"
    mosp_bridge.mosp_to_srt(mosp, reviewed)
    task.set_artifact("reviewed_srt", reviewed)

    # burn 真实跑 ffmpeg
    subflow.cmd_burn(argparse.Namespace(name="sample", style="default", force=False), cfg)
    out_mp4 = task.dir / "final" / "sample.mp4"
    check(out_mp4.exists() and out_mp4.stat().st_size > 1000, "烧录成片落盘")
    final_srt = task.dir / "final" / "sample.srt"
    check("校对后的字幕行" in mosp_bridge.read_text_any(final_srt), "定稿 SRT 与成片同目录")
    task = subflow.Task.load(cfg, "sample")
    check(task.stage == "done", "burn 后 stage=done")
    hist = {h["stage"]: h for h in task.data.get("history", [])}
    if "burn" in hist:
        hb = hist["burn"]
        check(
            hb["start"] >= task.data["created_at"] and hb["end"] >= hb["start"] and hb["duration_s"] > 0,
            "record 墙钟时间戳合理（monotonic 未混入时间戳）",
        )

    # resume 对已完成任务不回退
    subflow.cmd_resume(argparse.Namespace(name="sample"), cfg)
    check(subflow.Task.load(cfg, "sample").stage == "done", "resume 不回退已完成任务")

    # status 不抛错
    subflow.cmd_status(argparse.Namespace(), cfg)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--keep", action="store_true", help="保留临时目录（排障用）")
    args = parser.parse_args()
    tmp = Path(tempfile.mkdtemp(prefix="subflow-selftest-"))
    print(f"工作目录: {tmp}")
    try:
        cfg = make_cfg(tmp)
        test_mosp_roundtrip(tmp)
        test_kb_export(cfg)
        test_task_state_machine(tmp, cfg)
    finally:
        if args.keep:
            print(f"保留临时目录: {tmp}")
        else:
            shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n共 {_CHECKS} 项断言，失败 {len(_FAILURES)} 项")
    if _FAILURES:
        for f in _FAILURES:
            print(f"  FAIL {f}")
        return 1
    print("SUBFLOW_SELFTEST_OK")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ToolError as exc:
        print(f"[自检] 工具调用失败: {exc}", file=sys.stderr)
        sys.exit(1)
