# -*- coding: utf-8 -*-
# @version 1.15.6
"""流水线离线自检（v1.14.0）：临时目录 + 假文件 + mock 引擎调用。

不联网、不碰真实下载目录、不需要 GUI：
  · 目录：tempfile 自建，假 .mp4/.m4a/.srt 都是几 KB 的占位文件；
  · 引擎：ensure_ffmpeg / get_duration / merge_pair 全部 mock；
  · 校准：跑真实的 subtitle_calib_merged.py（纯本地脚本，离线安全）；
  · 事件循环：只用 QCoreApplication（QtCore，无 GUI）。
用法：python _selftest_pipeline.py   →  结果写入 <本文件同目录>/_selftest_pipeline_result.txt
"""

import ast
import json
import os
import re
import shutil
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.environ.get("VT_PIPE_SRC") or HERE
if not os.path.isfile(os.path.join(SRC, "video_toolbox.py")):
    SRC = os.path.join(os.path.dirname(HERE), "src")
sys.path.insert(0, SRC)

from PyQt5.QtCore import QCoreApplication, QTimer         # noqa: E402

app = QCoreApplication.instance() or QCoreApplication(sys.argv)

import video_toolbox as engine                             # noqa: E402
import media_registry as mreg                              # noqa: E402
import pipeline as pl                                      # noqa: E402

RESULT_PATH = os.path.join(HERE, "_selftest_pipeline_result.txt")
LINES = []
FAILS = []
PIPE_LOG = []


def _pipe_log(msg):
    PIPE_LOG.append(f"[{time.time() % 1000:7.2f}] " + str(msg))
    if len(PIPE_LOG) > 2000:
        del PIPE_LOG[:1000]


def check(name, cond, detail=""):
    ok = bool(cond)
    LINES.append(("PASS" if ok else "FAIL") + " | " + name +
                 ((" | " + str(detail)) if detail else ""))
    if not ok:
        FAILS.append(name)
    return ok


def note(text):
    LINES.append("     · " + str(text))


# ---------------------------- mock 区 ----------------------------
CALLS = {"smart_pair": 0, "merge": 0, "read_text_any": 0, "write_text_utf8": 0,
         "ytdlp": 0}

_smart_pair_orig = engine.smart_pair
_read_orig = engine.read_text_any
_write_orig = engine.write_text_utf8


def _mock_smart_pair(mp4s, m4as, webas, srts, asss, ffprobe_path):
    CALLS["smart_pair"] += 1
    return _smart_pair_orig(mp4s, m4as, webas, srts, asss, ffprobe_path)


def _mock_read(path, *a, **k):
    CALLS["read_text_any"] += 1
    return _read_orig(path, *a, **k)


def _mock_write(path, text, *a, **k):
    CALLS["write_text_utf8"] += 1
    return _write_orig(path, text, *a, **k)


def _fake_merge(mp4, audio, atype, sub, stype, out, ffmpeg, ass_mode="burn"):
    CALLS["merge"] += 1
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "wb") as f:
        f.write(b"\x00" * 2048)          # 假成品（只验证流程，不验证编码）
    return True, out


engine.smart_pair = _mock_smart_pair
engine.read_text_any = _mock_read
engine.write_text_utf8 = _mock_write
engine.merge_pair = _fake_merge
engine.ensure_ffmpeg = lambda: ("ffmpeg_mock", "ffprobe_mock")
engine.get_duration = lambda path, ffprobe: 100.0


# ---------------------------- 工具 ----------------------------
def wait_until(pred, timeout=12.0, interval=0.05):
    end = time.time() + timeout
    while time.time() < end:
        app.processEvents()
        if pred():
            return True
        time.sleep(interval)
    return bool(pred())


def put(path, size=2048, text=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = (text or ("x" * size)).encode("utf-8")
    with open(path, "wb") as f:
        f.write(data)
    return path


SRT = ("1\n00:00:00,000 --> 00:00:02,000\n鸣潮 漂泊者 登场\n\n"
       "2\n00:00:02,000 --> 00:00:04,000\n对决 开始\n\n"
       "3\n00:00:04,000 --> 00:00:06,000\n谢谢观看\n\n")
SRT_EN = ("1\n00:00:00,000 --> 00:00:02,000\nHello world\n\n"
          "2\n00:00:02,000 --> 00:00:04,000\nWuthering Waves\n\n"
          "3\n00:00:04,000 --> 00:00:06,000\nThank you for watching\n\n")
INFO_JSON = {"title": "测试视频", "uploader": "tester",
             "formats": [
                 {"format_id": "137", "height": 1080, "vcodec": "avc1.640028",
                  "filesize": 10_000_000},
                 {"format_id": "140", "height": 0, "vcodec": "none",
                  "filesize": 5_000_000}]}


def make_pipeline(root, auto=True, poll=0.3, name="dl"):
    d = os.path.join(root, name)
    os.makedirs(d, exist_ok=True)
    reg = mreg.MediaRegistry(dirs=[d], poll_interval=poll, use_watcher=False,
                             settle_seconds=SETTLE)
    pipe = pl.Pipeline(reg, out_root=os.path.join(root, "成品"),
                       auto=auto, ai_calib=False,
                       state_path=os.path.join(root, "pipeline_state.json"),
                       log=_pipe_log, ignite_existing=True)
    reg.add_listener(pipe.on_files_changed)
    reg.start()
    return d, reg, pipe


# ---------------------------- 用例 ----------------------------
#: 自检里把"落盘稳定"阈值收紧（默认 2.0s），保证用例跑得快；
#: 机制本身（连续两次观察 + 稳定时长 + 无 .part）照常生效
SETTLE = 0.3
#: 中间产物目录隔离到系统临时目录，避免与历史残留互相污染（否则旧产物会被复用）
pl.WORK_ROOT = os.path.join(tempfile.gettempdir(), "vt_pipeline_work_selftest")
shutil.rmtree(pl.WORK_ROOT, ignore_errors=True)


def case_missing_audio_then_ready(root):
    """缺 m4a → 不点火；补放 m4a → 轮询兜底 5 秒内自动点火。"""
    d, reg, pipe = make_pipeline(root, name="dl_wait")
    vdir = os.path.join(d, "视频A")
    put(os.path.join(vdir, "视频A.mp4"))
    reg.poll_once()                                   # 首轮索引
    pipe.manual_evaluate()
    ok = wait_until(lambda: any(j["name"] == "视频A" for j in pipe.job_list()), 8)
    check("目录变更 → 生成 job", ok)
    # 只有 mp4：等 download 完成，merge 必须仍是 waiting（不点火）
    ok = wait_until(lambda: state_of(pipe, "视频A", "download") == pl.DONE, 10)
    check("DOWNLOAD 阶段已完成", ok,
          "download=" + state_of(pipe, "视频A", "download"))
    check("缺 m4a 时 MERGE 不点火",
          state_of(pipe, "视频A", "merge") == pl.WAITING,
          "merge=" + state_of(pipe, "视频A", "merge"))

    # 补放 m4a：靠 registry 的轮询兜底（不手动 poll）自动点火
    before = CALLS["merge"]
    put(os.path.join(vdir, "视频A.m4a"))
    t0 = time.time()
    trace = []
    fired = False
    while time.time() - t0 < 6.0:
        app.processEvents()
        if CALLS["merge"] > before:
            fired = True
            break
        if len(trace) < 30:
            trace.append(f"{time.time() - t0:.1f}s:{state_of(pipe, '视频A', 'merge')}"
                         f"/m{CALLS['merge']}/sp{CALLS['smart_pair']}")
        time.sleep(0.2)
    note("补放后轨迹 " + " ".join(trace))
    check("补放 m4a 后轮询兜底自动点火（≤5s）", fired and time.time() - t0 <= 5.0,
          f"用时 {time.time() - t0:.2f}s")
    ok = wait_until(lambda: state_of(pipe, "视频A", "merge") == pl.DONE, 8)
    check("MERGE 自动跑完", ok, "merge=" + state_of(pipe, "视频A", "merge"))
    check("配对复用 engine.smart_pair", CALLS["smart_pair"] >= 1,
          f"调用 {CALLS['smart_pair']} 次")
    reg.stop()


def state_of(pipe, name, stage):
    for j in pipe.job_list():
        if j["name"] == name:
            return (j.get("stages") or {}).get(stage, {}).get("state")
    return ""


def case_full_chain(root):
    """自带中文 srt：MERGE → TRANSLATE(跳过：已是中文) → 校准 → PACKAGE 全自动。"""
    d, reg, pipe = make_pipeline(root, name="dl_full")
    vdir = os.path.join(d, "视频B")
    put(os.path.join(vdir, "视频B.mp4"))
    put(os.path.join(vdir, "视频B.m4a"))
    put(os.path.join(vdir, "视频B.srt"), text=SRT)
    put(os.path.join(vdir, "封面.jpg"))
    reg.poll_once()
    pipe.manual_evaluate()
    ok = wait_until(lambda: state_of(pipe, "视频B", "package") == pl.DONE, 25)
    st = next((j["stages"] for j in pipe.job_list() if j["name"] == "视频B"), {})
    check("全链自动接续到 PACKAGE 完成", ok,
          " / ".join(f"{k}={st.get(k, {}).get('state')}" for k in pl.STAGE_ORDER))
    check("已是中文字幕 → TRANSLATE 标记 SKIPPED",
          st.get("translate", {}).get("state") == pl.SKIPPED,
          st.get("translate", {}).get("reason", ""))
    if os.path.isfile(engine.APP_DIR and os.path.join(engine.APP_DIR, "subtitle_calib_merged.py")):
        check("CALIB1 完成（真实校准脚本）",
              st.get("calib1", {}).get("state") == pl.DONE,
              st.get("calib1", {}).get("error", ""))
    else:
        note("校准脚本缺失，CALIB1 断言降级为 SKIPPED")
    # 打包只复制、不移动：原始文件必须还在
    check("PACKAGE 不移动原始文件",
          os.path.isfile(os.path.join(vdir, "视频B.mp4"))
          and os.path.isfile(os.path.join(vdir, "视频B.srt")))
    out_dir = os.path.join(root, "成品", "视频B")
    check("PACKAGE 产物落到独立文件夹",
          os.path.isdir(out_dir)
          and any(f.endswith(".mp4") for f in os.listdir(out_dir)),
          out_dir if os.path.isdir(out_dir) else "(未生成)")
    check("文本读写走 read_text_any / write_text_utf8",
          CALLS["read_text_any"] >= 1 and CALLS["write_text_utf8"] >= 1,
          f"read={CALLS['read_text_any']} write={CALLS['write_text_utf8']}")
    reg.stop()
    return pipe


def find_job(pipe, name):
    return next((j for j in pipe.job_list() if j["name"] == name), None)


def case_failure_isolation(root, pipe_full):
    """注入某阶段异常 → 该阶段 FAILED，其它 job 不受影响。"""
    d, reg, pipe = make_pipeline(root, name="dl_fail")
    vdir_ok = os.path.join(d, "视频C")
    put(os.path.join(vdir_ok, "视频C.mp4"))
    put(os.path.join(vdir_ok, "视频C.m4a"))
    vdir_bad = os.path.join(d, "视频D")
    put(os.path.join(vdir_bad, "视频D.mp4"))
    put(os.path.join(vdir_bad, "视频D.m4a"))
    reg.poll_once()
    note("索引文件：" + ", ".join(sorted(os.path.basename(p)
                                        for p in reg.index))[:200])

    orig_run = pl.STAGE_BY_KEY[pl.STAGE_MERGE].run

    def boom(job, ctx):
        if job.name == "视频D":
            raise RuntimeError("注入的合并失败")
        return orig_run(job, ctx)

    pl.STAGE_BY_KEY[pl.STAGE_MERGE].run = boom
    try:
        pipe.manual_evaluate()
        ok = wait_until(lambda: state_of(pipe, "视频D", "merge") == pl.FAILED, 12)
        check("注入异常 → 阶段 FAILED", ok,
              "merge=" + state_of(pipe, "视频D", "merge"))
        check("失败不阻塞其它 job",
              state_of(pipe, "视频C", "merge") == pl.DONE,
              "视频C merge=" + state_of(pipe, "视频C", "merge"))
        check("失败阶段后续不再自动推进",
              state_of(pipe, "视频D", "translate") == pl.WAITING,
              state_of(pipe, "视频D", "translate"))
        jd = find_job(pipe, "视频D")
        check("失败信息已记录",
              bool(jd and jd["stages"]["merge"]["error"]),
              (jd or {}).get("stages", {}).get("merge", {}).get("error", "(无 job)"))
        # 重试：清掉 FAILED 后应重新点火
        pl.STAGE_BY_KEY[pl.STAGE_MERGE].run = orig_run
        if jd:
            pipe.retry(jd["id"])
        check("重试后重新点火并成功",
              wait_until(lambda: state_of(pipe, "视频D", "merge") == pl.DONE, 12),
              "merge=" + state_of(pipe, "视频D", "merge"))
    finally:
        pl.STAGE_BY_KEY[pl.STAGE_MERGE].run = orig_run
        reg.stop()


def case_bootstrap_no_ignite(root):
    """默认 ignite_existing=False：启动前就在目录里的存量任务不自动点火，
    用户点「执行」后才开始跑（避免一启动就把几十个历史视频全部重跑）。"""
    d = os.path.join(root, "dl_boot")
    vdir = os.path.join(d, "视频G")
    put(os.path.join(vdir, "视频G.mp4"))
    put(os.path.join(vdir, "视频G.m4a"))
    reg = mreg.MediaRegistry(dirs=[d], poll_interval=0.3, use_watcher=False,
                             settle_seconds=SETTLE)
    pipe = pl.Pipeline(reg, out_root=os.path.join(root, "成品"), auto=True,
                       ai_calib=False, state_path=os.path.join(root, "st_boot.json"),
                       log=_pipe_log)          # ignite_existing 默认 False
    reg.add_listener(pipe.on_files_changed)
    reg.start()
    reg.poll_once()
    pipe.manual_evaluate()
    wait_until(lambda: False, 1.5)
    check("存量任务不自动点火",
          state_of(pipe, "视频G", "merge") == pl.WAITING,
          "merge=" + state_of(pipe, "视频G", "merge"))
    job = find_job(pipe, "视频G")
    check("存量任务状态有提示",
          bool(job) and "存量" in (job.get("status") or ""),
          (job or {}).get("status", ""))
    if job:
        pipe.retry(job["id"])
    check("点「执行」后存量任务开始跑",
          wait_until(lambda: state_of(pipe, "视频G", "merge") == pl.DONE, 12),
          "merge=" + state_of(pipe, "视频G", "merge"))
    reg.stop()


def case_translate_unit(root):
    """翻译函数单测：双语输出、时间轴不动、中文字幕自动跳过、行数对齐兜底。"""
    import types

    def fake_gt(text, target="zh-CN", proxy="", timeout=20):
        n = text.count("\n") + 1
        return "\n".join(f"译{i}" for i in range(n))      # 始终按行数返回

    orig = pl._gt_request
    pl._gt_request = fake_gt
    ctx = types.SimpleNamespace(log=lambda m: None, proxy=lambda: "")
    try:
        src = os.path.join(root, "t_en.srt")
        put(src, text=SRT_EN)
        out = os.path.join(root, "t_zh.srt")
        pl._translate_srt_file(src, out, ctx)
        text = engine.read_text_any(out)
        check("翻译产物时间轴不变", text.count("-->") == 3
              and "00:00:00,000 --> 00:00:02,000" in text)
        check("翻译产物为双语（原文+译文）",
              "Hello world" in text and "译" in text)
        zh = os.path.join(root, "t_cn.srt")
        put(zh, text=SRT)
        try:
            pl._translate_srt_file(zh, os.path.join(root, "x.srt"), ctx)
            check("中文字幕 → 主动跳过", False, "未抛 SkipStage")
        except pl.SkipStage as e:
            check("中文字幕 → 主动跳过", "中文" in str(e), str(e))
    finally:
        pl._gt_request = orig


def case_link_full(root):
    """链接任务全链：add_link → 下载(原片/字幕/封面/信息) → 谷歌翻译 →
    校准一 → 二次校准（AI 关=SKIPPED；AI 开=DONE，mock）→ 打包。"""
    import types

    link_dir = os.path.join(root, "dl_link")
    os.makedirs(link_dir, exist_ok=True)
    # ---- mock 引擎侧下载依赖（不联网、不碰真实下载目录） ----
    saved = {name: getattr(engine, name) for name in
             ("get_saved_download_dir", "ensure_ytdlp", "fetch_info_json",
              "ytdlp_proxy_args", "ai_detect_language", "ytdlp_sub_langs",
              "write_info_txt", "make_cover_1280x720", "ai_mod", "calib_ai_run")}
    saved_run_ytdlp = pl._run_ytdlp
    engine.get_saved_download_dir = lambda: link_dir
    engine.ensure_ytdlp = lambda: "ytdlp_mock.exe"
    engine.fetch_info_json = lambda ytdlp, url, **k: json.dumps(INFO_JSON)
    engine.ytdlp_proxy_args = lambda: []
    engine.ai_detect_language = lambda t: "en"
    engine.ytdlp_sub_langs = lambda c, d="": "en"

    def fake_info_txt(folder, data, quality_label=""):
        put(os.path.join(folder, "视频信息.txt"), text="info")

    def fake_cover(ffmpeg, folder, timeout=60):
        put(os.path.join(folder, "封面.jpg"))
        return True

    engine.write_info_txt = fake_info_txt
    engine.make_cover_1280x720 = fake_cover

    def fake_run_ytdlp(ctx, cmd):
        CALLS["ytdlp"] += 1
        i = list(cmd).index("-o")
        folder = os.path.dirname(str(cmd[i + 1]).replace("%%", "%"))
        if "--write-subs" in cmd:
            put(os.path.join(folder, "video.en.srt"), text=SRT_EN)
        else:
            put(os.path.join(folder, "video.mp4"))
            put(os.path.join(folder, "video.jpg"))
        return 0, []

    pl._run_ytdlp = fake_run_ytdlp

    def fake_gt(text, target="zh-CN", proxy="", timeout=20):
        n = text.count("\n") + 1
        return "\n".join(f"译{i}" for i in range(n))

    saved_gt = pl._gt_request
    pl._gt_request = fake_gt

    def fake_calib_ai_run(src, out=None, **k):
        put(out, text=SRT)
        return {"ok": True, "out": out, "round": 2}

    engine.calib_ai_run = fake_calib_ai_run
    saved_set_cfg = pl.Pipeline.__dict__.get("_set_cfg")

    reg = mreg.MediaRegistry(dirs=[link_dir], poll_interval=0.3,
                             use_watcher=False, settle_seconds=SETTLE)
    pipe = pl.Pipeline(reg, out_root=os.path.join(root, "成品"), auto=True,
                       ai_calib=False, state_path=os.path.join(root, "st_link.json"),
                       log=_pipe_log, ignite_existing=True)
    reg.add_listener(pipe.on_files_changed)
    reg.start()

    def job_state(url_suffix, stage):
        for j in pipe.job_list():
            if j.get("kind") == "link" and str(j.get("url", "")).endswith(url_suffix):
                return (j.get("stages") or {}).get(stage, {}).get("state")
        return ""

    try:
        jid, msg = pipe.add_link("https://www.youtube.com/watch?v=abc")
        check("add_link 创建任务", bool(jid), msg)
        jid2, _ = pipe.add_link("https://www.youtube.com/watch?v=abc")
        check("重复链接不重复建任务", jid2 == jid)
        ok = wait_until(lambda: job_state("v=abc", "package") == pl.DONE, 40)
        check("链接任务全链跑到 PACKAGE", ok,
              " / ".join(f"{k}={job_state('v=abc', k)}"
                         for k in pl.CHAIN_LINK))
        jl = [j for j in pipe.job_list()
              if j.get("kind") == "link" and j.get("url", "").endswith("v=abc")]
        check("下载产物已归档到 job（视频/字幕/封面/信息）",
              bool(jl) and os.path.isfile(jl[0].get("video") or "")
              and jl[0].get("files", {}).get("subtitle")
              and jl[0].get("files", {}).get("cover")
              and jl[0].get("files", {}).get("info"),
              str((jl or [{}])[0].get("files", {}))[:160])
        check("任务名来自视频标题", bool(jl) and jl[0].get("name") == "测试视频",
              (jl or [{}])[0].get("name", ""))
        check("下载目录不落在真实下载目录",
              bool(jl) and (jl[0].get("dir") or "").startswith(link_dir),
              (jl or [{}])[0].get("dir", ""))
        check("AI 关闭 → 二次校准 SKIPPED",
              job_state("v=abc", "calib2") == pl.SKIPPED,
              job_state("v=abc", "calib2"))
        check("英文字幕 → 翻译自动完成（双语）",
              job_state("v=abc", "translate") == pl.DONE,
              job_state("v=abc", "translate"))
        # 链接任务目录不应再生成重复的 watch job
        n_jobs = sum(1 for j in pipe.job_list() if j.get("kind") == "watch"
                     and (j.get("dir") or "").startswith(link_dir))
        check("链接任务不产生重复 watch job", n_jobs == 0, f"{n_jobs} 个")

        # ---- AI 开启的第二个链接任务 → 二次校准 DONE ----
        class _FakeAI:
            @staticmethod
            def is_enabled():
                return True

        engine.ai_mod = lambda: _FakeAI()
        pl.Pipeline._set_cfg = staticmethod(lambda k, v: True)
        pipe.ai_calib = True
        jid3, _ = pipe.add_link("https://example.com/watch?v=v2")
        ok = wait_until(lambda: job_state("v=v2", "calib2") == pl.DONE, 40)
        check("AI 开启 → 二次校准自动完成", ok,
              "calib2=" + job_state("v=v2", "calib2"))
        check("二次校准后打包完成（成品引用最终 srt）",
              wait_until(lambda: job_state("v=v2", "package") == pl.DONE, 40),
              "package=" + job_state("v=v2", "package"))
    finally:
        for name, fn in saved.items():
            setattr(engine, name, fn)
        pl._run_ytdlp = saved_run_ytdlp
        pl._gt_request = saved_gt
        if saved_set_cfg is not None:
            pl.Pipeline._set_cfg = saved_set_cfg
        reg.stop()


def case_persistence(root):
    """state 文件删除后重建；DONE 重启跳过；RUNNING 重启重置为 READY。"""
    d, reg, pipe = make_pipeline(root, name="dl_state")
    vdir = os.path.join(d, "视频E")
    put(os.path.join(vdir, "视频E.mp4"))
    put(os.path.join(vdir, "视频E.m4a"))
    reg.poll_once()
    pipe.manual_evaluate()
    wait_until(lambda: state_of(pipe, "视频E", "merge") == pl.DONE, 12)
    sp = pipe.state_path
    check("状态文件已写出", os.path.isfile(sp), sp)
    # 1) 删除 → 重建
    os.remove(sp)
    check("删除后重建（save 即重建）", (pipe._save(), os.path.isfile(sp))[1])
    # 2) 重启：DONE 阶段跳过（merge 不再被调用）
    before = CALLS["merge"]
    pid = next(j["id"] for j in pipe.job_list() if j["name"] == "视频E")
    reg2 = mreg.MediaRegistry(dirs=[d], poll_interval=0.5, use_watcher=False)
    reg2.settle_seconds = SETTLE
    pipe2 = pl.Pipeline(reg2, out_root=os.path.join(root, "成品"),
                        auto=True, ai_calib=False, state_path=sp)
    check("重启后 DONE 阶段保留",
          pipe2.get_job(pid).state(pl.STAGE_MERGE) == pl.DONE)
    wait_until(lambda: False, 0.3)
    pipe2.evaluate()
    wait_until(lambda: CALLS["merge"] == before, 4)
    check("重启后 DONE 阶段不再重跑（幂等）", CALLS["merge"] == before,
          f"merge 调用 {CALLS['merge'] - before} 次")
    # 3) RUNNING → READY（用链上的翻译阶段验证）
    pipe2.get_job(pid).stages[pl.STAGE_TRANSLATE]["state"] = pl.RUNNING
    pipe2._save()
    reg3 = mreg.MediaRegistry(dirs=[d], poll_interval=0.5, use_watcher=False)
    reg3.settle_seconds = SETTLE
    pipe3 = pl.Pipeline(reg3, out_root=os.path.join(root, "成品"),
                        auto=True, ai_calib=False, state_path=sp)
    check("进行中的阶段重启后重置为 READY",
          pipe3.get_job(pid).state(pl.STAGE_TRANSLATE) == pl.READY,
          pipe3.get_job(pid).state(pl.STAGE_TRANSLATE))
    # 4) 状态文件损坏 → 不崩、重建
    with open(sp, "w", encoding="utf-8") as f:
        f.write("{坏掉的 json")
    reg4 = mreg.MediaRegistry(dirs=[d], poll_interval=0.5, use_watcher=False)
    pipe4 = pl.Pipeline(reg4, out_root=os.path.join(root, "成品"),
                        auto=True, ai_calib=False, state_path=sp)
    check("状态文件损坏可容错启动", isinstance(pipe4.jobs, dict))
    reg.stop()


def case_auto_off(root):
    """关闭自动流水线：registry 照常索引，但无阶段自动点火。"""
    d, reg, pipe = make_pipeline(root, auto=False, name="dl_off")
    pipe.set_auto(False)
    vdir = os.path.join(d, "视频F")
    put(os.path.join(vdir, "视频F.mp4"))
    put(os.path.join(vdir, "视频F.m4a"))
    reg.poll_once()
    pipe.manual_evaluate()
    wait_until(lambda: False, 1.5)
    job = next((j for j in pipe.job_list() if j["name"] == "视频F"), None)
    check("关闭开关后仍建立索引与 job", job is not None and reg.index,
          f"索引 {len(reg.index)} 个文件")
    states = set((job or {}).get("stages", {}).get(k, {}).get("state")
                 for k in ((job or {}).get("chain") or pl.STAGE_ORDER))
    check("关闭开关后无阶段自动点火",
          states and pl.RUNNING not in states and pl.DONE not in states,
          "状态集=" + str(states))
    check("关闭开关后队列为空", not pipe._queue)
    # 打开开关 → 立即补点火
    pipe.set_auto(True)
    check("打开开关后补点火",
          wait_until(lambda: state_of(pipe, "视频F", "merge") == pl.DONE, 12),
          "merge=" + state_of(pipe, "视频F", "merge"))
    reg.stop()


def case_code_review():
    """代码审查：后台代码不得 import Qt 控件类；不得私自 open() 写文本。"""
    for fname in ("media_registry.py", "pipeline.py"):
        path = os.path.join(SRC, fname) if os.path.isfile(os.path.join(SRC, fname)) \
            else os.path.join(HERE, fname)
        if not os.path.isfile(path):
            check(f"{fname} 存在", False, path)
            continue
        src = open(path, encoding="utf-8").read()
        tree = ast.parse(src)
        bad = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    if a.name.split(".")[0] in ("qfluentwidgets",) or \
                       ".QtWidgets" in a.name or ".QtGui" in a.name:
                        bad.append(a.name)
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                if mod.split(".")[0] == "qfluentwidgets" or \
                   mod.endswith("QtWidgets") or mod.endswith("QtGui"):
                    bad.append(mod)
        check(f"{fname} 未 import Qt 控件模块", not bad, ",".join(bad))
        # 禁止私自 open() 写文本（urllib opener.open() 等方法调用不算）
        check(f"{fname} 未直接 open() 读写文本",
              re.search(r"(?<![.\w])open\(", src) is None)
        check(f"{fname} 使用统一编解码入口",
              "read_text_any" in src or "write_text_utf8" in src or "engine." in src)


def case_cli_import(root):
    """纯 CLI（无 QApplication）下可 import 且核心调度可跑。"""
    code = (
        "import sys, os, time\n"
        f"sys.path.insert(0, {SRC!r})\n"
        f"sys.path.insert(0, {HERE!r})\n"
        "import video_toolbox as engine\n"
        "import media_registry as mreg, pipeline as pl\n"
        "engine.ensure_ffmpeg = lambda: ('ff','ff')\n"
        "engine.get_duration = lambda p, f: 100.0\n"
        "engine.merge_pair = lambda mp4, a, at, s, st, out, ff, ass_mode='burn': "
        "(open(os.path.join(os.path.dirname(out), os.path.basename(out)), 'wb').write(b'0'*64), (True, out))[1]\n"
        f"d = {os.path.join(root, 'dl_cli')!r}\n"
        "os.makedirs(os.path.join(d, 'V'), exist_ok=True)\n"
        "open(os.path.join(d, 'V', 'V.mp4'), 'wb').write(b'0'*64)\n"
        "open(os.path.join(d, 'V', 'V.m4a'), 'wb').write(b'0'*64)\n"
        "r = mreg.MediaRegistry(dirs=[d], poll_interval=0.2, use_watcher=False,"
        " settle_seconds=0.3)\n"
        "p = pl.Pipeline(r, out_root=os.path.join(d, '..', 'cli_out'), auto=True,"
        " ai_calib=False, state_path=os.path.join(d, 'st.json'),"
        " ignite_existing=True)\n"
        "r.refresh(); time.sleep(0.4); r.refresh()\n"
        "p.evaluate()\n"
        "end = time.time() + 10\n"
        "ok = False\n"
        "while time.time() < end:\n"
        "    j = [x for x in p.job_list() if x['name'] == 'V']\n"
        "    if j and j[0]['stages']['merge']['state'] == 'done':\n"
        "        ok = True; break\n"
        "    time.sleep(0.1)\n"
        "print('CLI_OK' if ok else 'CLI_FAIL')\n"
    )
    py = engine.system_python() or sys.executable
    import subprocess
    try:
        out = subprocess.run([py, "-c", code], capture_output=True, text=True,
                             timeout=90, cwd=SRC)
        check("纯 CLI（无 QApplication）可 import 并跑通调度",
              "CLI_OK" in (out.stdout or ""),
              (out.stdout or "")[-200:] or (out.stderr or "")[-200:])
    except Exception as e:  # noqa: BLE001
        check("纯 CLI（无 QApplication）可 import 并跑通调度", False,
              f"{type(e).__name__}: {e}")


def main():
    root = tempfile.mkdtemp(prefix="vt_pipeline_selftest_")
    import traceback
    for fn in (lambda: case_missing_audio_then_ready(root),
               lambda: case_full_chain(root),
               lambda: case_failure_isolation(root, None),
               lambda: case_bootstrap_no_ignite(root),
               lambda: case_translate_unit(root),
               lambda: case_link_full(root),
               lambda: case_persistence(root),
               lambda: case_auto_off(root),
               case_code_review,
               lambda: case_cli_import(root)):
        try:
            fn()
        except Exception:  # noqa: BLE001 - 单个用例炸了也要出报告
            check(f"{getattr(fn, '__name__', 'case')} 未异常退出", False,
                  traceback.format_exc(limit=3))
    try:
        shutil.rmtree(root, ignore_errors=True)
    except OSError:
        pass
    LINES.append("")
    LINES.append(f"总计 {len(LINES) - 1} 项，失败 {len(FAILS)} 项")
    if FAILS:
        LINES.append("失败项：" + "；".join(FAILS))
    if PIPE_LOG:
        LINES.append("")
        LINES.append("---- 流水线日志（末尾 40 条）----")
        LINES.extend(PIPE_LOG[-40:])
        LINES.append("---- 视频A 相关日志 ----")
        LINES.extend([x for x in PIPE_LOG if "视频A" in x][:40])
    with open(RESULT_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(LINES) + "\n")
    print("\n".join(LINES))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
