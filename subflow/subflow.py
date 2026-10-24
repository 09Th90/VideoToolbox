# -*- coding: utf-8 -*-
# @version 2.6.0
"""subflow——字幕生产全链路单命令编排（整合方案书 v1.0 阶段 2/3 交付物）。

链路：获取 → finesub 转写精修 → MAW/MAWE 人工校对（人工交接点）→ ffmpeg 烧录交付。
工具之间只通过文件与子进程交互；任务状态落盘 work/<任务名>/task.json，
重复执行同一阶段先检查产物是否已存在，存在即跳过（幂等）。

用法（详见 README.md）：
    python subflow.py add  <URL|本地文件> [--lang ja] [--extra-info "..."] [--name ep01]
    python subflow.py run  [任务名]        # 处理待办任务直到校对就绪
    python subflow.py status              # 各任务阶段与耗时
    python subflow.py review <任务名>      # 启动 MAWE 并等待校对导出
    python subflow.py burn  <任务名> [--style default]
    python subflow.py resume <任务名>      # 从中断阶段继续
    python subflow.py kb-sync             # 知识库主库 → VT 术语表 / MAW 预设
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import webbrowser
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import bridges  # noqa: E402
import kb_export  # noqa: E402
import mosp_bridge  # noqa: E402
from bridges import ToolConfig, ToolError  # noqa: E402

STAGES = ("queued", "download", "transcribe", "review", "burn", "done")
# 各阶段的幂等门槛：该产物存在即视为阶段已完成
_NOW = lambda: datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")


def normalize_name(raw: str) -> str:
    """任务名规范：半角字母数字、连字符与下划线（方案书 4.3 命名契约）。"""
    name = re.sub(r"[^0-9A-Za-z\-_]+", "-", raw.strip()).strip("-")
    if not name:
        raise ToolError("任务名规范化后为空，请用 --name 指定一个含半角字符的名字")
    return name


class Task:
    def __init__(self, cfg: ToolConfig, name: str):
        self.cfg = cfg
        self.name = name
        self.dir = cfg.task_dir(name)
        self.path = self.dir / "task.json"
        self.data: dict = {}

    # ---------- 读写 ----------
    @classmethod
    def load(cls, cfg: ToolConfig, name: str) -> "Task":
        t = cls(cfg, name)
        if not t.path.exists():
            raise ToolError(f"任务不存在: {name}（{t.path}）")
        t.data = json.loads(mosp_bridge.read_text_any(t.path))
        return t

    def save(self) -> None:
        self.data["updated_at"] = _NOW()
        tmp = self.path.with_name(self.path.name + ".tmp")
        mosp_bridge.write_text(tmp, json.dumps(self.data, ensure_ascii=False, indent=2), crlf=True)
        tmp.replace(self.path)

    # ---------- 常用属性 ----------
    @property
    def stage(self) -> str:
        return self.data.get("stage", "queued")

    @property
    def media(self) -> Path | None:
        p = self.data.get("artifacts", {}).get("media")
        return Path(p) if p else None

    def artifact(self, key: str) -> Path | None:
        p = self.data.get("artifacts", {}).get(key)
        return Path(p) if p else None

    def set_artifact(self, key: str, path: Path | None) -> None:
        self.data.setdefault("artifacts", {})
        if path is None:
            self.data["artifacts"].pop(key, None)
        else:
            self.data["artifacts"][key] = str(path)

    def set_stage(self, stage: str) -> None:
        if stage not in STAGES:
            raise ToolError(f"未知阶段: {stage}")
        self.data["stage"] = stage

    def record(self, stage: str, started_monotonic: float, returncode: int = 0) -> None:
        """记录一次阶段执行。started_monotonic 是 time.monotonic() 起点；
        wall 时间戳由 duration 反推（monotonic 值不是墙钟，不能直接进 fromtimestamp）。"""
        duration = max(0.0, time.monotonic() - started_monotonic)
        end_dt = datetime.now(timezone.utc)
        start_dt = end_dt - timedelta(seconds=duration)
        self.data.setdefault("history", []).append(
            {
                "stage": stage,
                "start": start_dt.strftime("%Y-%m-%dT%H:%M:%S+00:00"),
                "end": end_dt.strftime("%Y-%m-%dT%H:%M:%S+00:00"),
                "duration_s": round(duration, 1),
                "returncode": returncode,
            }
        )

    def fail(self, message: str) -> None:
        self.data["error"] = message
        self.save()

    def clear_error(self) -> None:
        self.data["error"] = None

    def log(self) -> Path:
        return self.cfg.logs_dir / f"{self.name}.log"

    # ---------- 阶段实现（全部幂等：产物在即跳过） ----------
    def ensure_media(self, *, force: bool = False) -> Path:
        """download 阶段：URL 交给 yt-dlp 留档到 media/；本地文件直接引用不复制。"""
        source = self.data["source"]
        if self.data.get("source_kind") == "file":
            media = Path(source)
            if not media.exists():
                raise ToolError(f"本地源文件不存在: {media}")
            self.set_artifact("media", media)
            return media
        existing = self.artifact("media")
        if existing and existing.exists() and not force:
            return existing
        started = time.monotonic()
        media = bridges.ytdlp_download(self.cfg, source, self.dir / "media", "input")
        self.set_artifact("media", media)
        self.record("download", started)
        return media

    def ensure_transcribed(self, *, force: bool = False) -> Path:
        """transcribe 阶段：finesub --stage final-srt，产出成品与 raw 双 SRT。"""
        final = self.dir / "finesub" / f"{self.name}.srt"
        if final.exists() and not force:
            self.set_artifact("finesub_srt", final)
            raw = self.dir / "finesub" / f"{self.name}-raw.srt"
            if raw.exists():
                self.set_artifact("raw_srt", raw)
            return final
        media = self.ensure_media()
        started = time.monotonic()
        try:
            bridges.finesub_transcribe(
                self.cfg,
                media,
                final,
                language=self.data.get("language", ""),
                extra_info=self.data.get("extra_info", ""),
                knowledge=self.data.get("knowledge", "update"),
            )
        except ToolError:
            raise
        finally:
            self.record("transcribe", started, returncode=0 if final.exists() else 1)
        self.set_artifact("finesub_srt", final)
        raw = self.dir / "finesub" / f"{self.name}-raw.srt"
        if raw.exists():
            self.set_artifact("raw_srt", raw)
        return final

    def ensure_mosp(self) -> Path:
        """review 前置：把成品 SRT 转成 MAW 工程文件（已存在即复用）。"""
        mosp = self.dir / "review" / f"{self.name}.mosp"
        if not mosp.exists():
            srt = self.artifact("finesub_srt")
            if not srt:
                raise ToolError("缺少 finesub 成品 SRT，请先 run")
            n = mosp_bridge.srt_to_mosp(srt, self.media, mosp, language=self.data.get("language", ""))
            print(f"  已生成 MAW 工程（{n} 条字幕）: {mosp}")
        self.set_artifact("mosp", mosp)
        return mosp


def load_all_tasks(cfg: ToolConfig) -> list[Task]:
    tasks: list[Task] = []
    if not cfg.work_dir.exists():
        return tasks
    for d in sorted(cfg.work_dir.iterdir()):
        if (d / "task.json").exists():
            tasks.append(Task.load(cfg, d.name))
    return tasks


# ---------- 命令实现 ----------
def cmd_add(args, cfg: ToolConfig) -> None:
    cfg.ensure_dirs()
    source = args.source
    kind = "url" if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", source) else "file"
    if kind == "file":
        source = str(Path(source).resolve())
        if not Path(source).exists():
            raise ToolError(f"本地文件不存在: {source}")
        default_name = Path(source).stem
    else:
        default_name = "task-" + time.strftime("%Y%m%d-%H%M%S")
    name = normalize_name(args.name or default_name)
    task = Task(cfg, name)
    if task.path.exists():
        raise ToolError(f"任务已存在: {name}（{task.path}）")
    task.dir.mkdir(parents=True, exist_ok=True)
    task.data = {
        "id": name,
        "name": name,
        "source": source,
        "source_kind": kind,
        "language": args.lang or "",
        "extra_info": args.extra_info or "",
        "knowledge": args.knowledge,
        "stage": "queued",
        "artifacts": {},
        "history": [],
        "error": None,
        "created_at": _NOW(),
        "updated_at": _NOW(),
    }
    task.save()
    print(f"已登记任务 {name}（{kind}）：{source}")
    print(f"下一步: python subflow.py run {name}")


def cmd_run(args, cfg: ToolConfig) -> None:
    cfg.ensure_dirs()
    tasks = [Task.load(cfg, args.name)] if args.name else [t for t in load_all_tasks(cfg) if t.stage != "done"]
    if not tasks:
        print("没有待处理任务。用 add 登记后重试。")
        return
    for task in tasks:
        print(f"[{task.name}] stage={task.stage}")
        if task.data.get("error"):
            print(f"  该任务上次失败（resume 继续）: {task.data['error'][:200]}")
            continue
        try:
            if task.stage in ("queued", "download"):
                task.set_stage("download")
                task.save()
                media = task.ensure_media()
                print(f"  媒体就绪: {media}")
                task.set_stage("transcribe")
                task.save()
            if task.stage == "transcribe":
                srt = task.ensure_transcribed()
                print(f"  精修完成: {srt}")
                task.set_stage("review")
                task.save()
            if task.stage == "review":
                mosp = task.ensure_mosp()
                print(f"  校对就绪。执行: python subflow.py review {task.name}")
                print(f"  （工程文件: {mosp}）")
        except ToolError as exc:
            task.fail(str(exc))
            print(f"  失败，已写入 task.json.error：{str(exc)[:300]}")
            print(f"  排障后执行: python subflow.py resume {task.name}")


def cmd_status(args, cfg: ToolConfig) -> None:
    tasks = load_all_tasks(cfg)
    if not tasks:
        print("尚无任务。")
        return
    print(f"{'任务名':<24} {'阶段':<11} {'错误':<4} 总耗时  最近活动")
    for t in tasks:
        total = sum(h.get("duration_s", 0) for h in t.data.get("history", []))
        last = t.data.get("updated_at", "")[:16].replace("T", " ")
        err = "有" if t.data.get("error") else "-"
        print(f"{t.name:<24} {t.stage:<11} {err:<4} {total:>7.0f}s {last}")


def cmd_review(args, cfg: ToolConfig) -> None:
    cfg.ensure_dirs()
    task = Task.load(cfg, args.name)
    if task.stage == "queued":
        raise ToolError("任务尚未 run，先执行 python subflow.py run " + task.name)
    mosp = task.ensure_mosp()
    port = bridges.maw_open_review(cfg, mosp, task.media, port=args.port)
    url = f"http://127.0.0.1:{port}/"
    print(f"MAW 编辑器已启动: {url}")
    print(f"工程: {mosp}")
    print("校对完成后在编辑器保存（Ctrl+S，写回工程文件），本命令自动检出 SRT。")
    if args.no_wait:
        return
    reviewed = task.dir / "review" / f"{task.name}-reviewed.srt"
    baseline = mosp.stat().st_mtime
    try:
        while True:
            if reviewed.exists():
                task.set_artifact("reviewed_srt", reviewed)
                task.save()
                break
            if mosp.stat().st_mtime > baseline:
                n = mosp_bridge.mosp_to_srt(mosp, reviewed)
                task.set_artifact("reviewed_srt", reviewed)
                task.save()
                print(f"  检测到工程保存，已渲染 {n} 条 → {reviewed}")
                break
            time.sleep(2.0)
    except KeyboardInterrupt:
        print("\n已停止等待；工程保持打开。校对完成后重跑本命令或直接 burn。")
        return
    task.set_stage("burn")
    task.save()
    print("校对完成，阶段推进到 burn。执行: python subflow.py burn " + task.name)


def cmd_burn(args, cfg: ToolConfig) -> None:
    cfg.ensure_dirs()
    task = Task.load(cfg, args.name)
    reviewed = task.artifact("reviewed_srt")
    if not reviewed or not reviewed.exists():
        # 兜底：review 目录里已有导出文件也认（人工直接放入的场景）
        candidate = task.dir / "review" / f"{task.name}-reviewed.srt"
        if candidate.exists():
            reviewed = candidate
            task.set_artifact("reviewed_srt", reviewed)
        else:
            raise ToolError("缺少校对后 SRT。先执行 review（或把导出 SRT 放到 review/ 目录）。")
    media = task.media
    if not media or not media.exists():
        # 兜底：run 流程中媒体落在 media/input.<ext>（task.json 丢失 artifacts 时仍可烧录）
        fallback = sorted(p for p in (task.dir / "media").glob("input.*") if not p.name.endswith(".part"))
        media = fallback[0] if fallback else None
    if not media or not media.exists():
        raise ToolError("缺少媒体文件，无法烧录")
    out_mp4 = task.dir / "final" / f"{task.name}.mp4"
    if not out_mp4.exists() or args.force:
        started = time.monotonic()
        try:
            bridges.ffmpeg_burn(cfg, media, reviewed, out_mp4, style=args.style)
        except ToolError:
            task.record("burn", started, returncode=1)
            raise
        task.record("burn", started)
    final_srt = task.dir / "final" / f"{task.name}.srt"
    mosp_bridge.write_text(final_srt, mosp_bridge.read_text_any(reviewed), crlf=True)
    task.set_artifact("final_mp4", out_mp4)
    task.set_artifact("final_srt", final_srt)
    task.set_stage("done")
    task.clear_error()
    task.save()
    print(f"交付完成:\n  成片 {out_mp4}\n  字幕 {final_srt}")


def cmd_resume(args, cfg: ToolConfig) -> None:
    task = Task.load(cfg, args.name)
    task.clear_error()
    # 幂等状态机天然支持续跑：从当前阶段重入，已完成阶段按产物存在性跳过
    stage = task.stage
    task.data["stage"] = "queued" if stage in ("queued", "download") else stage
    task.save()
    if task.stage in ("review", "burn", "done"):
        task.data["stage"] = stage
        task.save()
        print(f"任务 {task.name} 处于 {stage} 阶段，无需回退。直接执行对应命令（review/burn）。")
        return
    args_run = argparse.Namespace(name=task.name)
    cmd_run(args_run, cfg)


def cmd_open(args, cfg: ToolConfig) -> None:
    """在文件管理器打开任务目录（review 人工交接的辅助命令）。"""
    task = Task.load(cfg, args.name)
    webbrowser.open(str(task.dir))
    print(f"已打开: {task.dir}")


def cmd_kb_sync(args, cfg: ToolConfig) -> None:
    cfg.ensure_dirs()
    stats = kb_export.sync(cfg)
    print("知识库同步完成（单向：主库 → 导出物）：")
    for line in stats.summary:
        print(f"  {line}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="subflow", description="字幕生产全链路编排（方案书阶段 2）")
    parser.add_argument("--root", help="SubFlow 工作站根目录（默认 subflow/workflow，可用 SUBFLOW_ROOT 覆盖）")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("add", help="登记任务（URL 或本地文件）")
    p.add_argument("source", help="视频 URL 或本地媒体路径")
    p.add_argument("--lang", help="语言提示，透传 finesub --language（如 ja/en）")
    p.add_argument("--extra-info", help="背景信息（主播名、节目名、关键专名），透传 finesub")
    p.add_argument("--name", help="任务名（默认取文件名或时间戳）")
    p.add_argument("--knowledge", choices=["update", "collect", "none"], default="update", help="知识库读写模式（默认 update，校对后可回喂）")
    p.set_defaults(func=cmd_add)

    p = sub.add_parser("run", help="处理待办任务：下载留档 → finesub 转写精修 → 校对就绪")
    p.add_argument("name", nargs="?", help="任务名（缺省处理全部待办）")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("status", help="查看各任务阶段与耗时统计")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("review", help="启动 MAW 编辑器并等待校对导出（人工交接点）")
    p.add_argument("name")
    p.add_argument("--port", type=int, help="编辑器服务端口（默认 8250）")
    p.add_argument("--no-wait", action="store_true", help="只启动编辑器不等待")
    p.set_defaults(func=cmd_review)

    p = sub.add_parser("burn", help="校对完成后 ffmpeg 烧录成片")
    p.add_argument("name")
    p.add_argument("--style", default="default", choices=["default", "small", "large"], help="字幕样式预设")
    p.add_argument("--force", action="store_true", help="成片已存在时强制重烧")
    p.set_defaults(func=cmd_burn)

    p = sub.add_parser("resume", help="从中断阶段继续（含失败排障后重入）")
    p.add_argument("name")
    p.set_defaults(func=cmd_resume)

    p = sub.add_parser("open", help="在资源管理器打开任务目录")
    p.add_argument("name")
    p.set_defaults(func=cmd_open)

    p = sub.add_parser("kb-sync", help="知识库主库 → VT 术语表 TSV + MAW 预设（单向）")
    p.set_defaults(func=cmd_kb_sync)

    args = parser.parse_args(argv)
    cfg = ToolConfig.load()
    if args.root:
        cfg.root = Path(args.root)
    try:
        args.func(args, cfg)
    except ToolError as exc:
        print(f"[subflow] 错误: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n[subflow] 已中断。")
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
