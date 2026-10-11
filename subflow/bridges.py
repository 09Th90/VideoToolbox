# -*- coding: utf-8 -*-
"""subflow 对外工具的子进程调用封装（方案书 5.3「调用集中封装在单独模块」）。

覆盖三个外部工具：
- finesub：源码 venv 里的 ``python -m finesub.pipeline``（转写精修主引擎）；
- MAW：源码 PyInstaller 自编译产物 ``MAW.exe``（--server 编辑器服务）；
- yt-dlp / ffmpeg：项目 tools/ 自带的可执行文件（下载留档与烧录）。

所有路径都可用环境变量覆盖：SUBFLOW_ROOT、FINESUB_PYTHON、MAW_EXE、
FFMPEG_BIN、YTDLP_BIN、MAW_PORT。
"""

from __future__ import annotations

import os
import subprocess
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path

# 项目仓库根（subflow/ 的上一级）
REPO_ROOT = Path(__file__).resolve().parent.parent


def _env_path(name: str, default: Path) -> Path:
    value = os.environ.get(name)
    return Path(value) if value else default


@dataclass
class ToolConfig:
    root: Path            # SubFlow 工作站根目录（inbox/work/knowledge/glossary/logs）
    finesub_python: Path  # finesub 源码 venv 的 python.exe
    maw_exe: Path         # 自编译 MAW.exe
    ffmpeg_bin: Path
    ytdlp_bin: Path
    maw_port: int

    @classmethod
    def load(cls) -> "ToolConfig":
        root = _env_path("SUBFLOW_ROOT", REPO_ROOT / "subflow" / "workflow")
        # finesub venv 默认走 C 盘 junction（ASCII 路径）：torch 在 Windows 用 ANSI
        # fopen 加载 jit 模型，中文路径（仓库工作区）下 silero_vad.jit 会 errno 2；
        # junction 指向 downloads/finesub/.venv，创建方法见 subflow/README.md。
        junction_python = Path("C:/finesub-venv/Scripts/python.exe")
        default_python = junction_python if junction_python.exists() else (
            REPO_ROOT / "downloads" / "finesub" / ".venv" / "Scripts" / "python.exe"
        )
        return cls(
            root=root,
            finesub_python=_env_path("FINESUB_PYTHON", default_python),
            maw_exe=_env_path(
                "MAW_EXE", REPO_ROOT / "downloads" / "moys-asr-workflow" / "dist" / "MAW" / "MAW.exe"
            ),
            ffmpeg_bin=_env_path("FFMPEG_BIN", REPO_ROOT / "tools" / "ffmpeg.exe"),
            ytdlp_bin=_env_path("YTDLP_BIN", REPO_ROOT / "tools" / "yt-dlp.exe"),
            maw_port=int(os.environ.get("MAW_PORT", "8250")),
        )

    @property
    def work_dir(self) -> Path:
        return self.root / "work"

    @property
    def knowledge_root(self) -> Path:
        """finesub 知识库主库（单向同步的唯一真源，见 kb_export.py）。"""
        return self.root / "knowledge"

    @property
    def glossary_dir(self) -> Path:
        return self.root / "glossary"

    @property
    def logs_dir(self) -> Path:
        return self.root / "logs"

    def task_dir(self, name: str) -> Path:
        return self.work_dir / name

    def ensure_dirs(self) -> None:
        for d in (self.root, self.work_dir, self.knowledge_root, self.glossary_dir, self.logs_dir):
            d.mkdir(parents=True, exist_ok=True)


class ToolError(RuntimeError):
    """外部工具调用失败（超时/非零退出/产物缺失）。"""


def run_logged(
    cmd: list[str],
    *,
    log_path: Path | None = None,
    timeout_s: float | None = None,
    env_extra: dict[str, str] | None = None,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess:
    """运行子进程，stdout+stderr 追加落盘日志并返回 CompletedProcess。

    超时或退出码非零抛 ToolError；日志尾部（截 4000 字符）附在错误消息里便于排障。
    Windows 下用新进程组 + taskkill /T，保证超时能杀掉工具拉起的子进程树。
    """
    if log_path is not None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    if env_extra:
        env.update(env_extra)
    creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    started = time.monotonic()
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            cwd=str(cwd) if cwd else None,
            env=env,
            creationflags=creationflags,
        )
    except FileNotFoundError as exc:
        raise ToolError(f"找不到可执行文件: {cmd[0]}（{exc}）") from exc

    timed_out = False
    try:
        stdout, _ = proc.communicate(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        timed_out = True
        subprocess.run(
            ["taskkill", "/T", "/F", "/PID", str(proc.pid)],
            capture_output=True,
            creationflags=creationflags,
        )
        stdout, _ = proc.communicate()

    tail = (stdout or b"").decode("utf-8", errors="replace")
    if log_path is not None:
        with open(log_path, "a", encoding="utf-8", newline="") as f:
            f.write(f"\n===== {time.strftime('%Y-%m-%d %H:%M:%S')} {' '.join(cmd)} =====\n")
            f.write(tail)
    duration = time.monotonic() - started
    head = f"{Path(cmd[0]).name} 退出码 {proc.returncode}（{duration:.0f}s）"
    if timed_out:
        raise ToolError(f"{head}：超时（>{timeout_s:.0f}s），已终止进程树。\n{tail[-4000:]}")
    if proc.returncode != 0:
        raise ToolError(f"{head}：调用失败。\n{tail[-4000:]}")
    return proc


def finesub_transcribe(
    cfg: ToolConfig,
    media: Path,
    out_srt: Path,
    *,
    language: str = "",
    extra_info: str = "",
    knowledge: str = "update",
    timeout_s: float = 12 * 3600,
) -> None:
    """finesub 全流水线：媒体 → 成品 SRT（+ 同名 -raw.srt 留档）。

    知识库通过 FINESUB_KNOWLEDGE_ROOT 钉到 SubFlow 主库，实现三工具单源同步；
    成功判定按仓库约定：退出码 0 且 -o 指定的成品 SRT 落盘。
    CWD 钉到工作站根：finesub 的 out/、批量状态等相对路径产物不会散落调用方目录。
    """
    if not cfg.finesub_python.exists():
        raise ToolError(
            f"finesub 源码解释器不存在: {cfg.finesub_python}\n"
            "请先按 subflow/README.md「环境准备」从源码构建（downloads/finesub 内 uv venv 安装）。"
        )
    cmd = [
        str(cfg.finesub_python),
        "-m",
        "finesub.pipeline",
        str(media),
        "-o",
        str(out_srt),
        "--stage",
        "final-srt",
        "--knowledge",
        knowledge,
        "--log-level",
        "normal",
    ]
    if language:
        cmd += ["--language", language]
    if extra_info:
        cmd += ["--extra-info", extra_info]
    run_logged(
        cmd,
        log_path=cfg.logs_dir / "finesub.log",
        timeout_s=timeout_s,
        cwd=cfg.root,
        env_extra={"FINESUB_KNOWLEDGE_ROOT": str(cfg.knowledge_root), "FINESUB_NO_UPDATE_CHECK": "1"},
    )
    if not out_srt.exists():
        raise ToolError(f"finesub 退出码 0 但成品 SRT 缺失: {out_srt}")


def ytdlp_download(cfg: ToolConfig, url: str, dest_dir: Path, name: str = "input", *, timeout_s: float = 3600) -> Path:
    """yt-dlp 下载媒体到 dest_dir/name.<ext>，返回实际产物路径（截断片段处理交给后续）。"""
    if not cfg.ytdlp_bin.exists():
        raise ToolError(f"yt-dlp 不存在: {cfg.ytdlp_bin}")
    dest_dir.mkdir(parents=True, exist_ok=True)
    run_logged(
        [
            str(cfg.ytdlp_bin),
            "-o",
            str(dest_dir / f"{name}.%(ext)s"),
            "--no-playlist",
            "--no-overwrites",
            "--ffmpeg-location",
            str(cfg.ffmpeg_bin),
            url,
        ],
        log_path=cfg.logs_dir / "ytdlp.log",
        timeout_s=timeout_s,
    )
    produced = [p for p in dest_dir.glob(f"{name}.*") if not p.name.endswith(".part")]
    if not produced:
        raise ToolError(f"yt-dlp 退出码 0 但未找到产物: {dest_dir / (name + '.*')}")
    return max(produced, key=lambda p: p.stat().st_size)


def maw_stop_server(cfg: ToolConfig, port: int | None = None) -> None:
    """幂等停止 MAW 编辑器服务（无服务时退出码 1，视为已停止）。"""
    port = cfg.maw_port if port is None else port
    if not cfg.maw_exe.exists():
        raise ToolError(
            f"MAW.exe 不存在: {cfg.maw_exe}\n"
            "请先按 subflow/README.md「环境准备」从源码编译（downloads/moys-asr-workflow 内 PyInstaller 打包）。"
        )
    subprocess.run(
        [str(cfg.maw_exe), "--stop-server", str(port)],
        capture_output=True,
        timeout=60,
    )


def maw_server_ready(port: int, wait_s: float = 60.0) -> bool:
    """轮询 MAW 编辑器 HTTP 服务是否就绪。"""
    deadline = time.monotonic() + wait_s
    url = f"http://127.0.0.1:{port}/"
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2):
                return True
        except Exception:
            time.sleep(0.5)
    return False


def maw_open_review(cfg: ToolConfig, project_mosp: Path, media: Path | None, *, port: int | None = None) -> int:
    """后台启动 MAW 编辑器服务并直接打开指定工程，返回实际端口。

    MAW 只支持命令行指定工程（无 URL 查询参数），故按
    ``MAW.exe --server <工程> --media <媒体>`` 启动；启动前幂等清理同端口旧服务。
    """
    port = cfg.maw_port if port is None else port
    maw_stop_server(cfg, port)
    cmd = [str(cfg.maw_exe), "--server", str(port), str(project_mosp)]
    if media is not None:
        cmd += ["--media", str(media)]
    subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        cwd=str(cfg.maw_exe.parent),
    )
    if not maw_server_ready(port):
        raise ToolError(
            f"MAW 编辑器服务未在 60s 内就绪（http://127.0.0.1:{port}/）。"
            "可手动执行 MAW.exe --server 后在浏览器拖入工程。"
        )
    return port


def ffmpeg_burn(
    cfg: ToolConfig,
    media: Path,
    srt: Path,
    out_mp4: Path,
    *,
    style: str = "default",
    timeout_s: float = 4 * 3600,
) -> None:
    """ffmpeg 烧录字幕成片：H.264 重编码 + 音轨直拷，输出 mp4。"""
    if not cfg.ffmpeg_bin.exists():
        raise ToolError(f"ffmpeg 不存在: {cfg.ffmpeg_bin}")
    styles = {
        "default": "FontName=Microsoft YaHei,FontSize=22,Outline=1,Shadow=0,MarginV=30",
        "small": "FontName=Microsoft YaHei,FontSize=18,Outline=1,Shadow=0,MarginV=24",
        "large": "FontName=Microsoft YaHei,FontSize=28,Outline=2,Shadow=0,MarginV=36",
    }
    force_style = styles.get(style, styles["default"])
    # subtitles filter 的路径转义：盘符冒号与 filter 分隔符，统一走正斜杠
    srt_arg = str(srt.resolve()).replace("\\", "/").replace(":", "\\:")
    vf = f"subtitles='{srt_arg}':force_style='{force_style}'"
    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    run_logged(
        [
            str(cfg.ffmpeg_bin),
            "-y",
            "-i",
            str(media),
            "-vf",
            vf,
            "-c:v",
            "libx264",
            "-crf",
            "20",
            "-preset",
            "medium",
            "-c:a",
            "copy",
            str(out_mp4),
        ],
        log_path=cfg.logs_dir / "ffmpeg.log",
        timeout_s=timeout_s,
    )
    if not out_mp4.exists():
        raise ToolError(f"ffmpeg 退出码 0 但成片缺失: {out_mp4}")
