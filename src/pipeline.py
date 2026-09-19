# -*- coding: utf-8 -*-
# @version 1.15.3
"""视频全流程流水线（引擎侧，v1.14.0 新增）：事件驱动的阶段状态机。

链接任务：填入链接 → 下载(原片+字幕+封面+信息) → 字幕翻译(谷歌) →
          字幕校准(脚本基线) → 二次校准(AI 续跑) → 成品打包
目录任务：下载目录里出现文件 → 下载完成判定 → (可选)智能合并 → 同上

调度原则
--------
* **事件驱动**：只有三类事件会触发评估——目录变更（registry 回调）、阶段完成、
  手动操作（重试 / 打开自动开关 / 点刷新 / 新建链接任务）。定时器只用于
  "发现文件"，绝不用于"推进阶段"。
* **单并发**：全局一个执行线程，队列 FIFO（同一时刻只有一个子进程/线程在跑）。
* **幂等**：状态持久化到 data\\pipeline_state.json（走 engine._atomic_write），
  重启后 DONE 的阶段直接跳过，RUNNING 重置为 READY；产物复用必须输入指纹一致。
* **失败隔离**：某阶段 FAILED 只停住该 job 的后续阶段，其它 job 照常推进。
* **线程铁律**：本模块不 import 任何 QtGui/QtWidgets；阶段执行体运行在后台线程，
  只通过回调/信号把结果交给上层（GUI 侧再投进 app.q）。
"""

import json
import os
import re
import shutil
import subprocess
import hashlib
import threading
import time
import traceback

try:  # QtCore 可选
    from PyQt5.QtCore import QObject, pyqtSignal
    _HAS_QT = True
except Exception:  # noqa: BLE001
    _HAS_QT = False
    QObject = object

    def pyqtSignal(*_a, **_k):  # noqa: N802
        return None

import video_toolbox as engine
from media_registry import KIND_BY_EXT as _KIND_BY_EXT

# ---------- 状态与常量 ----------
WAITING, READY, RUNNING, DONE, FAILED, SKIPPED = (
    "waiting", "ready", "running", "done", "failed", "skipped")

STATE_VERSION = 1
STATE_FILE = os.path.join(engine.DATA_DIR, "pipeline_state.json")
WORK_ROOT = os.path.join(engine.DATA_DIR, "pipeline_work")
#: 下载完成判定：文件"大小 + mtime"稳定超过这么久才算落盘完毕
STABLE_SECS = 2.0
#: 校准脚本（与「字幕校准」页同一个，不另造）
CALIB_SCRIPT = os.path.join(engine.APP_DIR, "subtitle_calib_merged.py")

STAGE_DOWNLOAD, STAGE_MERGE, STAGE_TRANSLATE = "download", "merge", "translate"
STAGE_CALIB1, STAGE_CALIB2, STAGE_PACKAGE = "calib1", "calib2", "package"
STAGE_ORDER = [STAGE_DOWNLOAD, STAGE_MERGE, STAGE_TRANSLATE,
               STAGE_CALIB1, STAGE_CALIB2, STAGE_PACKAGE]
STAGE_LABELS = {STAGE_DOWNLOAD: "下载完成", STAGE_MERGE: "智能合并",
                STAGE_TRANSLATE: "字幕翻译", STAGE_CALIB1: "字幕校准",
                STAGE_CALIB2: "二次校准", STAGE_PACKAGE: "成品打包"}
#: 点击圆点跳转的功能页（MainWindow.page_by_key 的 key）
STAGE_JUMP = {STAGE_DOWNLOAD: "download", STAGE_MERGE: "merge",
              STAGE_TRANSLATE: "subtitle", STAGE_CALIB1: "calib",
              STAGE_CALIB2: "calib", STAGE_PACKAGE: "library"}

#: 两条任务链：链接任务（用户填链接 → 全自动）与目录任务（下载目录里出现的文件）
CHAIN_LINK = [STAGE_DOWNLOAD, STAGE_TRANSLATE, STAGE_CALIB1,
              STAGE_CALIB2, STAGE_PACKAGE]
CHAIN_WATCH = [STAGE_DOWNLOAD, STAGE_MERGE, STAGE_TRANSLATE,
               STAGE_CALIB1, STAGE_CALIB2, STAGE_PACKAGE]

#: config.json 里的键
CFG_AUTO = "pipeline_auto"
CFG_AI = "pipeline_ai_calib"


class SkipStage(Exception):
    """阶段主动跳过（记录 reason，状态置 SKIPPED，不算失败）。"""


def _safe_name(text, fallback="job"):
    s = re.sub(r'[\\/:*?"<>|]+', "_", str(text or "").strip())
    s = s.strip().strip(".") or fallback
    return s[:80]


def _fingerprint(paths):
    """输入文件指纹：文件名 → [大小, mtime]（用于判断旧产物还能不能用）。"""
    out = {}
    for p in paths or ():
        if not p or not isinstance(p, str):      # 无字幕时 sub 为 None
            continue
        try:
            st = os.stat(p)
            out[os.path.basename(p)] = [int(st.st_size), int(st.st_mtime)]
        except (OSError, TypeError, ValueError):
            out[str(p)] = None
    return out


def _reusable(out_path, srcs):
    """产物可复用：产物在 + 输入指纹与产出时一致。

    只判"文件在"会把换了源文件的旧产物当成现成结果（实测：换片重跑仍直接
    DONE），所以必须带输入指纹。
    """
    if not out_path or not os.path.isfile(out_path):
        return False
    meta = out_path + ".src.json"
    if not os.path.isfile(meta):
        return False
    try:
        return json.loads(engine.read_text_any(meta)) == _fingerprint(srcs)
    except Exception:  # noqa: BLE001
        return False


def _mark_reusable(out_path, srcs):
    try:
        engine.write_text_utf8(out_path + ".src.json",
                               json.dumps(_fingerprint(srcs), ensure_ascii=False))
    except OSError:
        pass


def _same_path(a, b):
    try:
        return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))
    except OSError:
        return False


# ============================ 阶段执行体 ============================
def _stage_download_ready(job, registry):
    """下载完成：链接任务有 URL 就绪（执行时真正去下载）；
    目录任务要求视频已落盘（连续两次观察内容未变 + 同目录无 .part）。"""
    if job.kind == "link":
        return bool(job.url)
    return bool(job.video) and registry.is_settled(job.video)


def _stage_download_run(job, ctx):
    if job.kind == "link":
        return _download_link_run(job, ctx)
    v = job.video
    if not v or not os.path.isfile(v):
        raise RuntimeError("视频文件不存在")
    if os.path.getsize(v) <= 0:
        raise RuntimeError("视频文件为空")
    ctx.log(f"[下载完成] {os.path.basename(v)} "
            f"({engine.format_size(os.path.getsize(v))})")
    return v


def _stage_merge_ready(job, registry):
    """智能合并：配对逻辑一律走 registry.find_pairs() → engine.smart_pair()。"""
    if not job.video:
        return False
    if os.path.splitext(job.video)[1].lower() != ".mp4":
        return False          # smart_pair 只处理 mp4
    for p in registry.find_pairs():
        if _same_path(p[0], job.video):
            job.pair = p
            return True
    return False


def _stage_merge_run(job, ctx):
    pair = job.pair or (None,)
    mp4, audio, atype, _mtype, _diff, sub, stype = (list(pair) + [None] * 7)[:7]
    if not mp4 or not audio:
        raise RuntimeError("配对信息缺失（文件可能已被移走）")
    ffmpeg, _ffprobe = ctx.ffmpeg()
    work = ctx.work_dir(job)
    out = os.path.join(work, f"{_safe_name(job.name)}_merged.mp4")
    if _reusable(out, [mp4, audio, sub]):
        return out
    ok, final_out = engine.merge_pair(mp4, audio, atype, sub, stype,
                                      out, ffmpeg, ass_mode="ignore")
    if not ok or not final_out or not os.path.isfile(final_out):
        raise RuntimeError("ffmpeg 合并失败")
    _mark_reusable(final_out, [mp4, audio, sub])
    ctx.log(f"[智能合并] {os.path.basename(final_out)} "
            f"（{engine.format_size(os.path.getsize(final_out))}）")
    return final_out


def _stage_translate_ready(job, registry):
    """字幕翻译：有（非中文的）字幕才介入。无字幕时该阶段可跳过。"""
    return bool(_pick_source_srt(job))


def _stage_translate_run(job, ctx):
    src = _pick_source_srt(job)
    if not src:
        raise SkipStage("没有可翻译的字幕（下载阶段未取到字幕）")
    out = os.path.join(ctx.work_dir(job), f"{_safe_name(job.name)}.zh.srt")
    if _reusable(out, [src]):
        return out
    return _translate_srt_file(src, out, ctx)


def _stage_calib1_ready(job, registry):
    """字幕校准（脚本基线）：有 srt 就校准（翻译产物优先，其次原始字幕）。"""
    return bool(_pick_source_srt(job) or job.srt())


def _stage_calib1_run(job, ctx):
    src = _pick_source_srt(job) or job.srt()
    if not src or not os.path.isfile(src):
        raise RuntimeError("找不到待校准的 srt")
    work = ctx.work_dir(job)
    out = os.path.join(work, f"{_safe_name(job.name)}.calib.srt")
    if not os.path.isfile(CALIB_SCRIPT):
        raise SkipStage("校准脚本缺失：" + CALIB_SCRIPT)
    if _reusable(out, [src]):        # 同一份 srt 不重复校准
        return out
    py = engine.system_python()
    if not py or not os.path.isfile(py):
        raise SkipStage("找不到可用的 Python 运行时")
    args = [py, CALIB_SCRIPT, src, "--out", out]
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    ctx.log("[字幕校准] " + " ".join(f'"{a}"' if " " in a else a for a in args))
    proc = engine.popen_process(args, cwd=os.path.dirname(CALIB_SCRIPT),
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, encoding="utf-8", errors="replace",
                                bufsize=1, env=env)
    for line in proc.stdout:
        line = line.rstrip()
        if line:
            ctx.log("  " + line)
    rc = proc.wait()
    if rc != 0 or not os.path.isfile(out):
        raise RuntimeError(f"校准脚本退出码 {rc}")
    _mark_reusable(out, [src])
    # 统一编码写出（读/写全部走 engine 的统一编解码入口）
    try:
        engine.write_text_utf8(out, engine.read_text_any(out))
    except OSError:
        pass
    return out


def _stage_calib2_ready(job, registry):
    """二次校准（AI 续跑）：第一轮校准完成即可；AI 未启用时执行体会主动跳过。"""
    return job.state(STAGE_CALIB1) == DONE


def _stage_calib2_run(job, ctx):
    src = job.stage_out(STAGE_CALIB1)
    if not src or not os.path.isfile(src):
        raise RuntimeError("找不到第一轮校准产物")
    if not ctx.ai_enabled():
        raise SkipStage("AI 校准未启用（全局 AI 未配置或已关闭）")
    out = os.path.join(ctx.work_dir(job), f"{_safe_name(job.name)}.calib2.srt")
    if _reusable(out, [src]):
        return out
    ctx.log(f"[二次校准] AI 在第一轮产物上继续（resume）")
    res = engine.calib_ai_run(src, out=out, log=ctx.log, round_no=2,
                              resume_from=src)
    if not (res and res.get("ok")) and not os.path.isfile(out):
        raise RuntimeError(f"AI 二次校准失败：{str((res or {}).get('error'))[:160]}")
    _mark_reusable(out, [src])
    return out


def _stage_package_ready(job, registry):
    """成品打包：校准链已走到终态 + 成品视频存在。"""
    st1 = job.state(STAGE_CALIB1)
    if st1 not in (DONE, SKIPPED):
        return False
    if job.chain_contains(STAGE_CALIB2) and job.state(STAGE_CALIB2) not in (DONE, SKIPPED):
        return False
    return bool(job.final_video())


def _stage_package_run(job, ctx):
    src_video = job.final_video()
    if not src_video or not os.path.isfile(src_video):
        raise RuntimeError("找不到成品视频")
    dest_dir = os.path.join(ctx.out_root, _safe_name(job.name))
    os.makedirs(dest_dir, exist_ok=True)
    # 只复制，绝不移动/覆盖用户原始文件
    dst_video = os.path.join(dest_dir, _safe_name(job.name) + os.path.splitext(src_video)[1])
    if not os.path.exists(dst_video):
        shutil.copy2(src_video, dst_video)
    srt = job.srt()
    if srt and os.path.isfile(srt):
        dst_srt = os.path.join(dest_dir, _safe_name(job.name) + ".srt")
        if not os.path.exists(dst_srt):
            shutil.copy2(srt, dst_srt)
    for kind in ("cover", "info"):
        for p in (job.files.get(kind) or [])[:1]:
            if os.path.isfile(p):
                dst = os.path.join(dest_dir, os.path.basename(p))
                if not os.path.exists(dst):
                    shutil.copy2(p, dst)
    ctx.log(f"[成品打包] → {dest_dir}")
    return dest_dir


class StageDef:
    """阶段定义：名称 + 输入条件 + 执行体 + 产物路径。"""

    def __init__(self, key, label, ready, run, jump="download", optional=False):
        self.key = key
        self.label = label
        self.ready = ready          # (job, registry) -> bool
        self.run = run              # (job, ctx) -> 产物路径
        self.jump = jump
        #: optional=True：条件不满足时直接置 SKIPPED 并继续看后面的阶段
        #: （如"已有字幕 → 转录阶段无需执行"）；False 则保持 WAITING 等文件齐备
        self.optional = optional

    def output(self, job):
        return job.stages[self.key]["out"]


STAGES = [
    StageDef(STAGE_DOWNLOAD, STAGE_LABELS[STAGE_DOWNLOAD],
             _stage_download_ready, _stage_download_run, STAGE_JUMP[STAGE_DOWNLOAD]),
    StageDef(STAGE_MERGE, STAGE_LABELS[STAGE_MERGE],
             _stage_merge_ready, _stage_merge_run, STAGE_JUMP[STAGE_MERGE]),
    StageDef(STAGE_TRANSLATE, STAGE_LABELS[STAGE_TRANSLATE],
             _stage_translate_ready, _stage_translate_run, STAGE_JUMP[STAGE_TRANSLATE],
             optional=True),
    StageDef(STAGE_CALIB1, STAGE_LABELS[STAGE_CALIB1],
             _stage_calib1_ready, _stage_calib1_run, STAGE_JUMP[STAGE_CALIB1]),
    StageDef(STAGE_CALIB2, STAGE_LABELS[STAGE_CALIB2],
             _stage_calib2_ready, _stage_calib2_run, STAGE_JUMP[STAGE_CALIB2],
             optional=True),
    StageDef(STAGE_PACKAGE, STAGE_LABELS[STAGE_PACKAGE],
             _stage_package_ready, _stage_package_run, STAGE_JUMP[STAGE_PACKAGE]),
]
STAGE_BY_KEY = {s.key: s for s in STAGES}


# ============================ 数据模型 ============================
class Job:
    """一个视频 = 一个 job。

    kind="watch"：目录感知（下载目录里出现的视频文件）；
    kind="link" ：用户填链接创建，下载阶段把原片/字幕/封面/信息一次拿齐。
    """

    def __init__(self, jid, name, directory, video="", kind="watch"):
        self.id = jid
        self.name = name
        self.dir = directory
        self.video = video
        self.kind = kind if kind in ("watch", "link") else "watch"
        self.url = ""
        self.files = {}          # kind -> [path]
        self.pair = None         # 最近一次 smart_pair 命中（不持久化）
        self.bootstrap = False   # 存量任务（启动前就在目录里，默认不自动点火）
        self.progress = 0.0      # 下载进度 0~100（不持久化）
        self.created = time.time()
        self.chain = list(CHAIN_LINK if self.kind == "link" else CHAIN_WATCH)
        self.stages = {k: {"state": WAITING, "error": "", "reason": "",
                           "out": "", "ts": 0.0} for k in self.chain}

    def chain_contains(self, key):
        return key in self.chain

    # ---------- 产物查询 ----------
    def stage_out(self, key):
        return self.stages.get(key, {}).get("out") or ""

    def merged_video(self):
        p = self.stage_out(STAGE_MERGE)
        return p if p and os.path.isfile(p) else ""

    def final_video(self):
        return self.merged_video() or (self.video if os.path.isfile(self.video or "") else "")

    def source_srt(self):
        """待翻译/待校准的"源字幕"（不含校准产物）。"""
        return _pick_source_srt(self)

    def srt(self):
        """当前有效的最终 srt：二次校准 > 脚本校准 > 翻译 > 原始字幕。"""
        for key in (STAGE_CALIB2, STAGE_CALIB1, STAGE_TRANSLATE):
            p = self.stage_out(key)
            if p and os.path.isfile(p) and p.lower().endswith(".srt"):
                return p
        for p in (self.files.get("subtitle") or []):
            if p.lower().endswith(".srt") and os.path.isfile(p):
                return p
        return ""

    def state(self, key):
        return self.stages.get(key, {}).get("state", WAITING)

    def all_done(self):
        return all(self.state(k) in (DONE, SKIPPED) for k in self.chain)

    def status_text(self):
        if getattr(self, "bootstrap", False) and not any(
                self.state(k) in (RUNNING, DONE, SKIPPED) for k in self.chain):
            return "存量任务（点「执行」开始）"
        for k in self.chain:
            if self.state(k) == RUNNING:
                label = STAGE_LABELS.get(k, k)
                if k == STAGE_DOWNLOAD and self.kind == "link" and self.progress:
                    return f"下载中 {self.progress:.0f}%"
                return f"进行中：{label}"
            if self.state(k) == FAILED:
                return f"失败：{STAGE_LABELS.get(k, k)}"
            if self.state(k) == READY:
                return f"待执行：{STAGE_LABELS.get(k, k)}"
        return "已完成" if self.all_done() else "等待文件"

    def to_dict(self):
        return {"id": self.id, "name": self.name, "dir": self.dir,
                "video": self.video, "kind": self.kind, "url": self.url,
                "chain": list(self.chain),
                "files": {k: list(v) for k, v in self.files.items()},
                "created": self.created, "status": self.status_text(),
                "bootstrap": bool(getattr(self, "bootstrap", False)),
                "stages": {k: dict(v) for k, v in self.stages.items()}}

    @classmethod
    def from_dict(cls, data):
        kind = data.get("kind") or ("link" if data.get("url") else "watch")
        job = cls(data.get("id") or "", data.get("name") or "",
                  data.get("dir") or "", data.get("video") or "", kind=kind)
        job.url = str(data.get("url") or "")
        chain = data.get("chain") or (CHAIN_LINK if kind == "link" else CHAIN_WATCH)
        # 旧版状态迁移：transcribe→translate、calib→calib1（旧 transcribe/calib2 无产物即丢）
        migrated = []
        for k in chain:
            if k == "transcribe":
                continue
            if k == "calib":
                k = STAGE_CALIB1
            if k not in migrated and k in STAGE_ORDER:
                migrated.append(k)
        job.chain = migrated or list(CHAIN_WATCH)
        job.stages = {k: {"state": WAITING, "error": "", "reason": "",
                          "out": "", "ts": 0.0} for k in job.chain}
        job.files = {k: list(v) for k, v in (data.get("files") or {}).items()}
        job.created = float(data.get("created") or time.time())
        for k, st in (data.get("stages") or {}).items():
            if k == "calib":
                k = STAGE_CALIB1
            if k in job.stages:
                job.stages[k].update({
                    "state": st.get("state", WAITING),
                    "error": str(st.get("error") or ""),
                    "reason": str(st.get("reason") or ""),
                    "out": str(st.get("out") or ""),
                    "ts": float(st.get("ts") or 0.0)})
        return job


# ============================ 链接任务的下载执行体 ============================
#: 与下载页 DownloadPage.SUB_LANGS 保持同一份多语言兜底列表
DEFAULT_SUB_LANGS = "en,zh,ja,zh-Hans,zh-Hant,ko,es,fr,de"
_YTDLP_PCT_RE = re.compile(r"\[download\]\s+([\d.]+)%")


def _srt_state(folder, before=None):
    """目录里 .srt 的快照；给了 before 就只返回新增/刚改写的那些（与下载页同款）。"""
    now = {}
    try:
        names = os.listdir(folder)
    except OSError:
        return {} if before is None else []
    for name in names:
        if not name.lower().endswith(".srt"):
            continue
        p = os.path.join(folder, name)
        try:
            st = os.stat(p)
        except OSError:
            continue
        now[p] = (st.st_mtime_ns, st.st_size)
    if before is None:
        return now
    return sorted(p for p, sig in now.items() if before.get(p) != sig)


def _run_ytdlp(ctx, cmd):
    """跑一条 yt-dlp 命令：逐行透出日志、解析下载进度。返回 (rc, lines)。"""
    try:
        proc = engine.popen_process(cmd, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, bufsize=1)
    except Exception as e:  # noqa: BLE001
        ctx.log(f"[错误] 无法启动下载器: {e}")
        return 1, []
    lines = []
    for raw in proc.stdout:
        line = engine.decode_bytes_any(raw).rstrip()
        if not line:
            continue
        lines.append(line)
        m = _YTDLP_PCT_RE.search(line)
        if m:
            ctx.progress(float(m.group(1)))
        elif "WARNING" not in line and "Deprecated" not in line:
            ctx.log("  " + line)
    return proc.wait(), lines


def _ytdlp_with_retry(ctx, cmd, attempts=3):
    """带风控重试的 yt-dlp（HTTP 412 等，与下载页同一策略）。"""
    wait = 6
    rc, lines = 1, []
    for i in range(attempts):
        rc, lines = _run_ytdlp(ctx, cmd)
        if rc == 0:
            return 0
        joined = "\n".join(lines)
        if "412" not in joined and "Unable to download webpage" not in joined:
            return rc
        if i < attempts - 1:
            ctx.log(f"[重试] 站点风控拦截（HTTP 412），{wait}s 后重试 "
                    f"({i + 2}/{attempts}) ...")
            time.sleep(wait)
            wait *= 2
    return rc


def _download_link_run(job, ctx):
    """链接任务：原片 + 字幕 + 封面 + 信息一次性下载到位。

    与下载页同一套引擎原语（ensure_ytdlp / fetch_info_json / output_template /
    normalize_rolling_srt / write_info_txt / make_cover_1280x720），只是不带
    画质选择 UI —— 固定取检测到的最高画质（≥720p 的第一档）。
    """
    url = job.url
    if not url:
        raise RuntimeError("任务缺少链接")
    ytdlp = engine.ensure_ytdlp()
    ffmpeg, _ = ctx.ffmpeg()
    proxy_args = engine.ytdlp_proxy_args()
    if proxy_args:
        ctx.log(f"[代理] 下载经本地代理 {proxy_args[1]}")
    ctx.progress(1.0)

    # 1) 视频信息（fetch_info_json 自带 4 次/退避重试）
    raw = engine.fetch_info_json(ytdlp, url, log=ctx.log)
    if not raw:
        raise RuntimeError("无法获取视频信息（站点风控或网络异常）")
    try:
        meta = json.loads(raw)
    except ValueError:
        meta = {}
    title = str(meta.get("title") or "").strip() or "video"
    dest_root = ctx.download_root()
    folder = engine.unique_folder(dest_root, engine.sanitize_folder_name(title, "video"))
    os.makedirs(folder, exist_ok=True)
    job.dir = folder
    job.name = title
    ctx.log(f"[下载] {title} → {folder}")
    ctx.progress(3.0)

    info_path = engine.save_info_json(raw)
    try:
        best = []
        try:
            best = engine.parse_qualities(raw) or []
        except Exception:  # noqa: BLE001
            best = []
        fid = best[0]["format_id"] if best else ""
        height = best[0].get("height") if best else 0
        fmt = f"{fid}+ba/b" if fid else "bv*+ba/b"
        opts = ["-f", fmt, "--merge-output-format", "mp4",
                "--ffmpeg-location", os.path.dirname(ffmpeg),
                "--newline", "--no-playlist",
                "--write-thumbnail", "--convert-thumbnails", "jpg",
                *proxy_args,
                "-o", engine.output_template(folder)]
        # 2) 视频本体：先复用检测结果，CDN 过期再退回链接重提
        rc, _ = _run_ytdlp(ctx, [ytdlp, "--load-info-json", info_path, *opts])
        if rc != 0:
            ctx.log("[下载] 复用检测结果失败（多为 CDN 链接过期），改用链接重新提取")
            ctx.progress(0.0)
            rc = _ytdlp_with_retry(ctx, [ytdlp, *opts, url])
        if rc != 0:
            raise RuntimeError(f"视频下载失败（退出码 {rc}）")
        # 3) 字幕：按标题语言优先，空手再用多语言兜底（与下载页同策略）
        _fetch_subs_for_job(job, ctx, ytdlp, url, folder, info_path, title)
        # 4) 信息 txt + 封面
        try:
            engine.write_info_txt(folder, meta, f"{height}p" if height else "")
            ctx.log("[打包] 视频信息.txt 已生成")
        except Exception as e:  # noqa: BLE001
            ctx.log(f"[打包] 视频信息.txt 写入失败: {e}")
        if engine.make_cover_1280x720(ffmpeg, folder):
            ctx.log("[打包] 封面.jpg（1280x720）已生成")
        else:
            ctx.log("[打包] 该视频无可用封面，已跳过封面步骤")
    finally:
        try:
            os.remove(info_path)
        except OSError:
            pass
    # 5) 定位成品视频（目录里最大的 mp4）
    mp4s = []
    try:
        for name in os.listdir(folder):
            if name.lower().endswith(".mp4"):
                p = os.path.join(folder, name)
                try:
                    mp4s.append((os.path.getsize(p), p))
                except OSError:
                    pass
    except OSError:
        pass
    if not mp4s:
        raise RuntimeError("下载完成但没有找到 mp4 文件")
    mp4s.sort(reverse=True)
    job.video = mp4s[0][1]
    ctx.progress(100.0)
    ctx.log(f"[下载完成] {os.path.basename(job.video)} "
            f"（{engine.format_size(mp4s[0][0])}）")
    return folder


def _fetch_subs_for_job(job, ctx, ytdlp, url, folder, info_path, title):
    """给链接任务拉字幕（下载页 _fetch_subtitles 的引擎侧等价实现）。"""
    sub_langs = DEFAULT_SUB_LANGS
    code = ""
    try:
        code = engine.ai_detect_language(title) or ""
    except Exception:  # noqa: BLE001
        code = ""
    if code:
        langs = engine.ytdlp_sub_langs(code, "")
        if langs:
            sub_langs = langs
            ctx.log(f"[字幕] 标题语言 {code}，按标题语言拉取字幕（{langs}）")
    proxy_args = engine.ytdlp_proxy_args()
    before = _srt_state(folder)
    opts = ["--skip-download", "--newline", "--no-playlist",
            "--socket-timeout", "15", "--retries", "3",
            "--write-subs", "--write-auto-subs", "--sub-langs", sub_langs,
            "--sub-format", "srt/best", "--convert-subs", "srt",
            *proxy_args,
            "-o", engine.output_template(folder)]
    rc = 1
    if info_path and os.path.isfile(info_path):
        rc, _ = _run_ytdlp(ctx, [ytdlp, "--load-info-json", info_path, *opts])
    if rc != 0:
        rc = _ytdlp_with_retry(ctx, [ytdlp, *opts, url])
    fresh = _srt_state(folder, before)
    if not fresh and sub_langs != DEFAULT_SUB_LANGS:
        ctx.log("[字幕] 首轮没取到字幕，改用多语言列表补拉一次")
        retry_opts = list(opts)
        k = retry_opts.index("--sub-langs")
        retry_opts[k + 1] = DEFAULT_SUB_LANGS
        _ytdlp_with_retry(ctx, [ytdlp, *retry_opts, url])
        fresh = _srt_state(folder, before)
    fixed = 0
    for p in fresh:
        try:
            if engine.normalize_rolling_srt(p):
                fixed += 1
        except Exception:  # noqa: BLE001
            pass
    if fresh:
        extra = f"，其中 {fixed} 份做了去重叠整理" if fixed else ""
        ctx.log(f"[字幕] 已下载 {len(fresh)} 份字幕（.srt）{extra}")
    else:
        ctx.log("[字幕] 未取到字幕 —— 后续翻译/校准阶段将自动跳过，"
                "可在「字幕处理」页手动转录后再补跑")


# ============================ 字幕翻译（谷歌） ============================
_GT_URL = "https://translate.googleapis.com/translate_a/single"
_GT_BATCH_CHARS = 1200     # 单次请求的字符上限（保守，避免 413/限流）
_GT_BATCH_LINES = 40       # 单次请求的行数上限
_GT_RETRIES = 3
_CUE_ID_RE = re.compile(r"^\s*\d+\s*$")
_CUE_TIME_RE = re.compile(
    r"^\s*\d{1,2}:\d{2}:\d{2}[,.]\d{1,3}\s*-->\s*\d{1,2}:\d{2}:\d{2}[,.]\d{1,3}.*$")


def _gt_request(text, target="zh-CN", proxy="", timeout=20):
    """调一次谷歌翻译（gtx 免费端点），返回译文。失败抛异常。"""
    import urllib.parse
    import urllib.request
    params = urllib.parse.urlencode(
        {"client": "gtx", "sl": "auto", "tl": target, "dt": "t", "q": text})
    handlers = []
    if proxy:
        handlers.append(urllib.request.ProxyHandler(
            {"http": proxy, "https": proxy}))
    opener = urllib.request.build_opener(*handlers)
    req = urllib.request.Request(
        f"{_GT_URL}?{params}", headers={"User-Agent": "Mozilla/5.0"})
    with opener.open(req, timeout=timeout) as resp:
        data = json.loads(engine.decode_bytes_any(resp.read()))
    segs = data[0] if isinstance(data, list) and data else []
    return "".join(s[0] for s in segs if isinstance(s, list) and s)


def _google_translate_lines(lines, target="zh-CN", proxy="", log=None):
    """批量翻译文本行，返回等长译文列表；单批彻底失败抛异常（阶段可重试）。"""
    out = [""] * len(lines)
    active = [i for i, t in enumerate(lines) if t.strip()]
    batches, cur, size = [], [], 0
    for i in active:
        if cur and (size + len(lines[i]) + 1 > _GT_BATCH_CHARS
                    or len(cur) >= _GT_BATCH_LINES):
            batches.append(cur)
            cur, size = [], 0
        cur.append(i)
        size += len(lines[i]) + 1
    if cur:
        batches.append(cur)
    for bi, batch in enumerate(batches):
        text = "\n".join(lines[i] for i in batch)
        got = None
        for attempt in range(_GT_RETRIES):
            try:
                got = _gt_request(text, target=target, proxy=proxy)
                break
            except Exception as e:  # noqa: BLE001
                if log:
                    log(f"[翻译] 批次 {bi + 1}/{len(batches)} 失败"
                        f"（{attempt + 1}/{_GT_RETRIES}）：{e}")
                time.sleep(1.5 * (attempt + 1))
        if got is None:
            raise RuntimeError(f"谷歌翻译请求失败（批次 {bi + 1}/{len(batches)}）")
        parts = got.split("\n")
        if len(parts) == len(batch):
            for i, t in zip(batch, parts):
                out[i] = t.strip()
        else:
            # 行数没对齐（谷歌合并/拆句了）：退化为逐行翻译兜底
            if log:
                log(f"[翻译] 批次 {bi + 1} 返回行数不齐"
                    f"（{len(parts)} vs {len(batch)}），逐行重译")
            for i in batch:
                try:
                    out[i] = _gt_request(lines[i], target=target,
                                         proxy=proxy).strip()
                except Exception:  # noqa: BLE001
                    out[i] = lines[i]
    return out


def _parse_srt_cues(text):
    """把 srt 拆成块列表：[ [行, 行, ...], ... ]（按空行分隔，保持原始顺序）。"""
    blocks, cur = [], []
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if line.strip():
            cur.append(line)
        elif cur:
            blocks.append(cur)
            cur = []
    if cur:
        blocks.append(cur)
    return blocks


def _chinese_ratio(text):
    """中文字符占全部字母类字符的比例（无字母时：有汉字=1，否则 0）。"""
    han = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    letters = sum(1 for ch in text if ch.isalpha())
    if not letters:
        return 1.0 if han else 0.0
    return han / float(letters)


def _pick_source_srt(job):
    """挑要翻译的源字幕：优先已有翻译/校准产物，其次目录里的 srt 里
    「中文占比最低」的那份（反应片通常拿到 en/ja 原文 + 可能有官方中文）。"""
    p = job.stage_out(STAGE_TRANSLATE)
    if p and os.path.isfile(p):
        return p
    srts = [p for p in (job.files.get("subtitle") or [])
            if p.lower().endswith(".srt") and os.path.isfile(p)]
    if not srts:
        return ""
    scored = []
    for p in srts:
        try:
            ratio = _chinese_ratio(engine.read_text_any(p))
        except OSError:
            continue
        scored.append((ratio, p))
    if not scored:
        return ""
    scored.sort(key=lambda t: (t[0], os.path.basename(t[1]).lower()))
    return scored[0][1]


def _translate_srt_file(src, out, ctx):
    """把 src 翻译成中文并写成**双语** srt（原文在上、译文在下），时间轴不动。"""
    text = engine.read_text_any(src)
    nl = "\r\n" if "\r\n" in text else "\n"
    blocks = _parse_srt_cues(text)
    # 收集所有正文行（前两行的序号/时间轴不翻译；正文行可能含内嵌时间样式行）
    body_idx, body_lines = [], []
    for bi, block in enumerate(blocks):
        for li, line in enumerate(block):
            if li < 2 and (_CUE_TIME_RE.match(line) or _CUE_ID_RE.match(line)):
                continue
            body_idx.append((bi, li))
            body_lines.append(line)
    if not body_lines:
        raise SkipStage("字幕没有可翻译的正文")
    if _chinese_ratio("\n".join(body_lines)) > 0.3:
        raise SkipStage("字幕已是中文，无需翻译")
    ctx.log(f"[翻译] 谷歌翻译 {len(body_lines)} 行 "
            f"（源：{os.path.basename(src)}，目标：zh-CN）")
    translated = _google_translate_lines(
        body_lines, target="zh-CN", proxy=ctx.proxy(), log=ctx.log)
    for (bi, li), zh in zip(body_idx, translated):
        zh = zh or blocks[bi][li]
        blocks[bi][li] = blocks[bi][li] + "\n" + zh        # 双语：原文+译文
    rebuilt = []
    for block in blocks:
        rebuilt.extend(block)
        rebuilt.append("")                                  # 块间空行
    out_text = nl.join(rebuilt).rstrip() + nl
    engine.write_text_utf8(out, out_text)
    _mark_reusable(out, [src])
    ctx.log(f"[翻译] 已生成双语字幕 {os.path.basename(out)}")
    return out


class Ctx:
    """阶段执行上下文（执行体唯一能拿到的"外部世界"，不含任何控件）。"""

    def __init__(self, pipeline, job):
        self.pipeline = pipeline
        self.job = job
        self.registry = pipeline.registry
        self.engine = engine
        self.log = pipeline._log
        self.out_root = pipeline.out_root

    def work_dir(self, job):
        d = os.path.join(WORK_ROOT, _safe_name(job.id or job.name))
        os.makedirs(d, exist_ok=True)
        return d

    def ffmpeg(self):
        return engine.ensure_ffmpeg()

    def download_root(self):
        """链接任务的落盘根目录（与下载页同一个「上次使用的下载目录」）。"""
        return engine.get_saved_download_dir()

    def proxy(self):
        """谷歌翻译用的 HTTP 代理：与 yt-dlp 同源（内置 mihomo），拿不到就直连。"""
        try:
            args = engine.ytdlp_proxy_args()
        except Exception:  # noqa: BLE001
            args = []
        return args[1] if len(args) >= 2 else ""

    def progress(self, pct):
        """下载进度（0~100）：写回 job 并节流刷新 UI。"""
        self.pipeline._set_progress(self.job, pct)

    def ai_enabled(self):
        if not self.pipeline.ai_calib:
            return False
        try:
            return bool(engine.ai_mod().is_enabled())
        except Exception:  # noqa: BLE001
            return False


class _Emitter(QObject):
    if _HAS_QT:
        state_changed = pyqtSignal(object)   # dict（见 Pipeline._emit）

    def __init__(self):
        if _HAS_QT:
            super().__init__()
        self._listeners = []
        if not _HAS_QT:
            self.state_changed = None

    def add_listener(self, cb):
        if callable(cb) and cb not in self._listeners:
            self._listeners.append(cb)
        return cb

    def _emit(self, payload):
        # ⚠️ 关闭后不得再碰 Qt 信号：窗口销毁 / QApplication 退出之后 emit 会
        #    打到已删除的 C++ 对象上，表现为收尾阶段的崩溃。listener 同理。
        if self._closed:
            return
        try:
            listeners = list(self._listeners)
        except Exception:  # noqa: BLE001
            listeners = []
        for cb in listeners:
            try:
                cb(payload)
            except Exception:  # noqa: BLE001
                pass
        if _HAS_QT and self.state_changed is not None:
            try:
                self.state_changed.emit(payload)
            except Exception:  # noqa: BLE001
                pass


class Pipeline(_Emitter):
    """流水线调度器（引擎侧）。"""

    def __init__(self, registry, out_root=None, auto=None, ai_calib=None,
                 state_path=None, log=None, ignite_existing=False):
        _Emitter.__init__(self)
        self.registry = registry
        #: 启动前就躺在目录里的"存量任务"是否也自动点火。默认 False：程序一启动
        #: 就把几十个历史视频全部重跑一遍（合并/校准/复制）代价太大，也未必是用户
        #: 想要的；存量任务停在 WAITING，由用户在流水线页点「执行」或打开开关。
        self.ignite_existing = bool(ignite_existing)
        self.out_root = out_root or os.path.join(engine.get_saved_download_dir(), "成品")
        self.state_path = state_path or STATE_FILE
        self.ai_calib = self._cfg(CFG_AI, True) if ai_calib is None else bool(ai_calib)
        self.auto = self._cfg(CFG_AUTO, True) if auto is None else bool(auto)
        self.jobs = {}
        self._closed = False
        self._log_cb = log
        self._lock = threading.RLock()
        self._queue = []           # FIFO: [(job_id, stage_key)]
        self._running = None       # (job_id, stage_key)
        self._worker = None
        self._eval_thread = None
        self._eval_pending = False
        self._first_sync_done = False   # 首轮同步（存量任务标记）只做一次
        self._last_progress_emit = 0.0
        self._load()

    # ---------- 配置 ----------
    @staticmethod
    def _cfg(key, default):
        try:
            v = engine.load_config().get(key)
        except Exception:  # noqa: BLE001
            v = None
        return default if v is None else bool(v)

    @staticmethod
    def _set_cfg(key, value):
        try:
            cfg = engine.load_config()
            cfg[key] = bool(value)
            engine.save_config(cfg)
            return True
        except Exception:  # noqa: BLE001
            return False

    def set_auto(self, flag):
        """自动流水线开关（持久化到 data\\config.json）。关闭后仍索引、不点火。"""
        flag = bool(flag)
        with self._lock:
            self.auto = flag
        self._set_cfg(CFG_AUTO, flag)
        self._emit({"type": "auto", "auto": flag})
        if flag:
            self._schedule_evaluate()      # 打开瞬间补一次评估（补点火）
        return flag

    def set_ai_calib(self, flag):
        with self._lock:
            self.ai_calib = bool(flag)
        self._set_cfg(CFG_AI, flag)
        return flag

    # ---------- 任务创建 ----------
    def add_link(self, url):
        """新建链接任务（用户在流水线页填链接）。返回 (job_id, 提示文案)。"""
        url = str(url or "").strip()
        if not url.lower().startswith(("http://", "https://")):
            return None, "请填入有效的 http(s) 链接"
        with self._lock:
            for job in self.jobs.values():
                if (job.kind == "link" and job.url == url
                        and job.state(STAGE_DOWNLOAD) in (WAITING, READY, RUNNING)):
                    return job.id, "该链接的任务已在队列中"
        jid = "link_" + hashlib.md5(url.encode("utf-8")).hexdigest()[:10]
        with self._lock:
            job = self.jobs.get(jid)
            if job is not None:
                # 同链接的历史任务已结束：清掉各阶段状态，按新一轮跑
                job.stages = {k: {"state": WAITING, "error": "", "reason": "",
                                  "out": "", "ts": 0.0} for k in job.chain}
                job.bootstrap = False
            else:
                job = Job(jid, "链接任务（获取标题中…）", "", "", kind="link")
                job.url = url
                self.jobs[jid] = job
        self._save()
        self._emit_jobs()
        self._log(f"[流水线] 新任务：{url}")
        self._schedule_evaluate()
        return jid, "已加入流水线，将自动完成 下载 → 翻译 → 校准 → 打包"

    def _set_progress(self, job, pct):
        """下载进度：写回 job 并节流刷新（≥1s 才推一次，避免刷屏）。"""
        try:
            job.progress = max(0.0, min(100.0, float(pct)))
        except (TypeError, ValueError):
            return
        now = time.time()
        if now - self._last_progress_emit >= 1.0:
            self._last_progress_emit = now
            self._emit_jobs()

    # ---------- 日志 ----------
    def _log(self, msg):
        text = str(msg)
        if self._log_cb is not None:
            try:
                self._log_cb(text)
            except Exception:  # noqa: BLE001
                pass
        self._emit({"type": "log", "text": text})

    def close(self):
        """停机（窗口关闭 / 程序退出时调用）：停止发信号与起新评估。

        已在跑的阶段线程是 daemon，不阻塞退出；这里只做"不再对外发声"和
        "不再点火"，避免收尾阶段往已销毁的 Qt 对象上 emit。
        """
        self._closed = True
        with self._lock:
            self._queue = []
            self._eval_pending = False
            self._listeners = []
        try:
            if self.registry is not None:
                self.registry.stop()
        except Exception:  # noqa: BLE001
            pass

    # ---------- 事件入口 ----------
    def on_files_changed(self, paths=None):
        """目录变更事件（registry 回调/信号接进来）——唯一的外部驱动源。"""
        if self._closed:
            return
        self._schedule_evaluate()

    def on_stage_finished(self):
        """阶段完成也是事件：驱动同一 job 的下一阶段（顺序链）。"""
        self._schedule_evaluate()

    def manual_evaluate(self):
        """手动刷新（UI 按钮 / 自检）。"""
        self._schedule_evaluate()

    def _schedule_evaluate(self):
        """登记一次"待评估"：已有一个评估线程在跑就合并，否则起一个。

        注意 pending 先置 True 再判断线程是否活着——否则"首次调度/线程刚结束"
        这两种情况下线程会进来发现没有待办、直接退出，评估永远不执行。
        """
        if self._closed:
            return
        with self._lock:
            self._eval_pending = True
            alive = self._eval_thread is not None and self._eval_thread.is_alive()
            if alive:
                return
            self._eval_thread = threading.Thread(target=self._evaluate_loop,
                                                 daemon=True,
                                                 name="pipeline-eval")
        self._eval_thread.start()

    def _evaluate_loop(self):
        try:
            while True:
                with self._lock:
                    if not self._eval_pending:
                        self._eval_thread = None
                        return
                    self._eval_pending = False
                self.evaluate()
        except Exception:  # noqa: BLE001
            self._log("[流水线] 评估线程异常：\n" + traceback.format_exc())
        finally:
            with self._lock:
                if self._eval_thread is threading.current_thread():
                    self._eval_thread = None

    # ---------- 核心：评估 + 点火 ----------
    def evaluate(self):
        """重新索引 → 同步 job → 找到每个 job 下一个可执行阶段 → 入队。"""
        if self._closed:
            return
        try:
            self.registry.refresh()
        except Exception:  # noqa: BLE001
            pass
        self._sync_jobs()
        fired = []
        with self._lock:
            for job in self.jobs.values():
                key = self._next_actionable(job)
                if not key:
                    continue
                if job.stages[key]["state"] == WAITING:
                    job.stages[key]["state"] = READY
                    job.stages[key]["ts"] = time.time()
                item = (job.id, key)
                if self._running == item or item in self._queue:
                    continue
                # 存量任务（本次启动前就在目录里的）默认不自动点火
                if getattr(job, "bootstrap", False) and not self.ignite_existing:
                    continue
                if self.auto:
                    self._queue.append(item)
                    fired.append(item)
        if fired:
            for jid, key in fired:
                job = self.jobs.get(jid)
                if job:
                    self._log(f"[流水线] {job.name}：{STAGE_LABELS[key]} 已就绪")
        self._save()
        self._emit_jobs()
        if self.auto:
            self._pump()

    def _next_actionable(self, job):
        """按该 job 的阶段链返回下一个该做的阶段 key；FAILED 即停（等重试）。"""
        for key in job.chain:
            sd = STAGE_BY_KEY.get(key)
            if sd is None:
                continue
            st = job.stages[key]
            state = st["state"]
            if state in (DONE, SKIPPED):
                continue
            if state == RUNNING:
                return None
            if state == FAILED:
                return None
            if state == READY:
                return sd.key
            try:
                ready = sd.ready(job, self.registry)
            except Exception:  # noqa: BLE001 - 条件判定异常不点火，也不算失败
                self._log(f"[流水线] {job.name}：{sd.label} 条件判定异常 "
                          f"（{traceback.format_exc(limit=1).strip()}）")
                return None
            if ready:
                return sd.key
            if sd.optional:
                # 该阶段对这条片子不适用（如已是中文字幕 → 不必翻译）：跳过并继续
                st["state"] = SKIPPED
                st["reason"] = "无需执行（输入条件不满足）"
                st["ts"] = time.time()
                continue
            return None     # 顺序推进：前一阶段没就绪就不看后面
        return None

    def _pump(self):
        """单并发泵：队列里取一个阶段在后台线程执行。"""
        with self._lock:
            if self._worker is not None and self._worker.is_alive():
                return
            while self._queue:
                jid, key = self._queue.pop(0)
                job = self.jobs.get(jid)
                if job is None:
                    continue
                st = job.stages[key]
                if st["state"] in (DONE, SKIPPED, RUNNING):
                    continue
                st["state"] = RUNNING
                st["error"] = ""
                st["ts"] = time.time()
                self._running = (jid, key)
                self._worker = threading.Thread(target=self._run_stage,
                                                args=(jid, key), daemon=True,
                                                name=f"stage-{key}")
                self._worker.start()
                self._save()
                self._emit_jobs()
                return

    def _run_stage(self, jid, key):
        sd = STAGE_BY_KEY[key]
        job = self.jobs.get(jid)
        if job is None:
            return
        ctx = Ctx(self, job)
        self._log(f"[开始] {job.name} → {sd.label}")
        try:
            out = sd.run(job, ctx)
            with self._lock:
                st = job.stages[key]
                st["state"] = DONE
                st["out"] = out or ""
                st["error"] = ""
                st["ts"] = time.time()
            self._log(f"[完成] {job.name} → {sd.label}")
        except SkipStage as e:
            with self._lock:
                st = job.stages[key]
                st["state"] = SKIPPED
                st["reason"] = str(e)
                st["ts"] = time.time()
            self._log(f"[跳过] {job.name} → {sd.label}：{e}")
        except Exception as e:  # noqa: BLE001
            with self._lock:
                st = job.stages[key]
                st["state"] = FAILED
                st["error"] = f"{type(e).__name__}: {e}"
                st["ts"] = time.time()
            self._log(f"[失败] {job.name} → {sd.label}：{st['error']}")
        finally:
            with self._lock:
                self._running = None
            self._save()
            self._emit_jobs()
            self.on_stage_finished()     # 完成 = 新事件 → 驱动下一阶段

    # ---------- job 同步 ----------
    def _job_id(self, path):
        with self._lock:
            roots = list(self.registry.dirs) or [engine.get_saved_download_dir()]
        ap = os.path.abspath(path)
        for root in roots:
            try:
                rel = os.path.relpath(ap, os.path.abspath(root))
            except ValueError:
                continue
            if not rel.startswith(".."):
                return os.path.splitext(rel.replace("\\", "/"))[0]
        return _safe_name(os.path.splitext(os.path.basename(ap))[0])

    def _sync_jobs(self):
        """按「视频文件」聚合目录 job；链接任务的文件在其下载目录里单独归集。"""
        index = self.registry.snapshot()
        vids = [e["path"] for e in index.values() if e["kind"] == "video"]
        vids.sort()
        seen = set()
        with self._lock:
            link_dirs = {os.path.normcase(j.dir) for j in self.jobs.values()
                         if j.kind == "link" and j.dir}
            for v in vids:
                directory = os.path.dirname(v)
                # 链接任务的下载目录不再重复建 watch job（同一部片子）
                if os.path.normcase(directory) in link_dirs:
                    continue
                jid = self._job_id(v)
                if jid in seen:
                    continue
                seen.add(jid)
                name = os.path.splitext(os.path.basename(v))[0]
                directory = os.path.dirname(v)
                job = self.jobs.get(jid)
                if job is None:
                    job = Job(jid, name, directory, v)
                    # 首轮同步发现的就是"存量任务"（本次启动前已存在）
                    job.bootstrap = not self._first_sync_done
                    self.jobs[jid] = job
                job.video = v
                job.dir = directory
                job.name = name
                stem = os.path.splitext(os.path.basename(v))[0].lower()
                files = {}
                for e in index.values():
                    if os.path.dirname(e["path"]) != directory:
                        continue
                    same = os.path.splitext(os.path.basename(e["path"]))[0].lower() == stem
                    if same or e["kind"] in ("subtitle", "cover", "info"):
                        files.setdefault(e["kind"], []).append(e["path"])
                for k in files:
                    files[k].sort()
                job.files = files
            # 链接任务：下载完成后其目录里的字幕/封面/信息由这里归集到 job
            for jid, job in list(self.jobs.items()):
                if job.kind != "link" or not job.dir:
                    continue
                stem = None
                if job.video:
                    stem = os.path.splitext(os.path.basename(job.video))[0].lower()
                files = {}
                try:
                    names = os.listdir(job.dir)
                except OSError:
                    names = []
                for name in names:
                    p = os.path.join(job.dir, name)
                    ext = os.path.splitext(name)[1].lower()
                    kind = _KIND_BY_EXT.get(ext)
                    if kind is None:
                        continue
                    try:
                        if not os.path.isfile(p):
                            continue
                    except OSError:
                        continue
                    same = stem is not None and os.path.splitext(name)[0].lower() == stem
                    if same or kind in ("subtitle", "cover", "info"):
                        files.setdefault(kind, []).append(p)
                if files:
                    job.files = {k: sorted(v) for k, v in files.items()}
                if not job.video:
                    continue
                if os.path.isfile(job.video):
                    seen.add(jid)
                else:
                    job.video = ""
            # 视频被移走 → 保留 job（状态持久化需要），但清掉 video 引用
            for jid, job in self.jobs.items():
                if jid in seen:
                    continue
                if os.path.isfile(job.video or ""):
                    seen.add(jid)
                else:
                    job.video = ""
            self._first_sync_done = True

    # ---------- 对外查询 ----------
    def job_list(self):
        with self._lock:
            jobs = sorted(self.jobs.values(),
                          key=lambda j: (-j.created, j.name))
        return [j.to_dict() for j in jobs]

    def get_job(self, jid):
        with self._lock:
            return self.jobs.get(jid)

    def retry(self, jid, stage=None):
        """重试失败的阶段；也用于手动启动"存量任务"（不传则重试所有停滞阶段）。"""
        with self._lock:
            job = self.jobs.get(jid)
            if job is None:
                return False
            job.bootstrap = False           # 手动点过就不再当存量任务
            keys = [stage] if stage else list(job.chain)
            n = 0
            for k in keys:
                st = job.stages.get(k)
                if st and st["state"] in (FAILED, SKIPPED):
                    st["state"] = WAITING
                    st["error"] = ""
                    st["reason"] = ""
                    st["ts"] = time.time()
                    n += 1
            if not n and not stage:
                n = 1                        # 存量任务：无失败项也要重新评估一次
        if n:
            self._save()
            self._emit_jobs()
            self._schedule_evaluate()
        return bool(n)

    def remove_job(self, jid):
        with self._lock:
            self.jobs.pop(jid, None)
            self._queue = [it for it in self._queue if it[0] != jid]
        self._save()
        self._emit_jobs()

    def _emit_jobs(self):
        self._emit({"type": "jobs", "jobs": self.job_list(),
                    "auto": self.auto, "running": self._running})

    # ---------- 持久化（幂等） ----------
    def _save(self):
        with self._lock:
            data = {"version": STATE_VERSION, "saved": time.time(),
                    "auto": self.auto, "ai_calib": self.ai_calib,
                    "out_root": self.out_root,
                    "jobs": {jid: j.to_dict() for jid, j in self.jobs.items()}}
        try:
            engine._atomic_write(self.state_path,
                                 json.dumps(data, ensure_ascii=False, indent=2))
        except Exception:  # noqa: BLE001
            pass

    def _load(self):
        path = self.state_path
        if not os.path.isfile(path):
            return
        try:
            data = json.loads(engine.read_text_any(path))
        except Exception:  # noqa: BLE001 - 状态文件损坏：重建，绝不让程序起不来
            self._backup_broken(path)
            return
        if not isinstance(data, dict):
            return
        self.out_root = data.get("out_root") or self.out_root
        for jid, jd in (data.get("jobs") or {}).items():
            if not isinstance(jd, dict):
                continue
            job = Job.from_dict(jd)
            for k, st in job.stages.items():
                # 重启恢复：DONE 跳过；RUNNING/READY 重置为 READY 等待重新点火
                if st["state"] == RUNNING:
                    st["state"] = READY
                elif st["state"] == READY:
                    st["state"] = WAITING
                # DONE 阶段的产物若已被删掉 → 回退到 WAITING 重做
                if st["state"] == DONE and st["out"] and not os.path.exists(st["out"]):
                    if k != STAGE_DOWNLOAD:
                        st["state"] = WAITING
            self.jobs[job.id or jid] = job

    @staticmethod
    def _backup_broken(path):
        try:
            os.replace(path, path + ".broken")
        except OSError:
            pass
