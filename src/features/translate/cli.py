# -*- coding: utf-8 -*-
# @version 3.1.2
"""translate 子命令（原 agent_cli.cmd_translate，行为不变）。"""
from __future__ import annotations

import os

from features._cli import _agent_out_dir, _emit, _fail, _say, common


def cmd_translate(args) -> int:
    # 翻译两补丁（路由钉死 + 去 AI）：CLI 路径不经 GUI 预热，这里显式装一次
    # （幂等；2026-10-20 起不再在 prepare_runtime_env 里装）。
    try:
        from core.translate.route_patch import ensure_translate_patches
        ensure_translate_patches()
    except Exception:  # noqa: BLE001
        pass
    from engine_asr_data import ASRData      # noqa: PLC0415
    from features.translate.engine_translate import make_translator  # noqa: PLC0415
    src = os.path.abspath(args.file)
    if not os.path.isfile(src):
        return _fail(args, "文件不存在：%s" % src)
    try:
        data = ASRData.from_subtitle_file(src)
    except Exception as e:  # noqa: BLE001
        return _fail(args, "字幕解析失败：%s" % e)
    segs = list(getattr(data, "segments", []) or [])
    if not segs:
        return _fail(args, "字幕没有任何 cue")

    target = _lang_label(args.to)
    if target is None:
        return _fail(args, "无法识别的目标语言：%r" % args.to)
    try:
        translator = make_translator(args.engine, thread_num=args.threads,
                                     batch_num=args.batch,
                                     target_language=target)
    except KeyError as e:
        return _fail(args, str(e))
    ok, why = translator.probe()
    if not ok:
        return _fail(args, "翻译端点不可用（%s）：%s" % (args.engine, why))

    out_dir = os.path.abspath(args.out) if args.out else _agent_out_dir()
    out_path = out_dir if out_dir.lower().endswith((".srt", ".ass", ".txt")) else \
        os.path.join(out_dir, os.path.splitext(os.path.basename(src))[0]
                     + ".zh.srt")
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)

    # 引擎 chunk 协议是 SubtitleProcessData(original_text/translated_text)，
    # 而 ASRData 段的原文字段叫 text——包一层适配，译后回写 seg.translated_text，
    # save() 按 ORIGINAL_ON_TOP（原文在上、译文在下）出双语字幕。
    from videocaptioner.core.entities import SubtitleProcessData  # noqa: PLC0415
    items = [SubtitleProcessData(index=i, original_text=(s.text or ""))
             for i, s in enumerate(segs)]

    from concurrent.futures import ThreadPoolExecutor, as_completed  # noqa: PLC0415
    chunks = [items[i:i + args.batch] for i in range(0, len(items), args.batch)]
    _say(args, "[信息] %d 条 cue → %d 块（%s → %s，%d 线程）"
         % (len(segs), len(chunks), args.engine, target, args.threads))
    failed = 0
    with ThreadPoolExecutor(max_workers=args.threads) as pool:
        futs = {pool.submit(translator.translate, c): c for c in chunks}
        for i, fut in enumerate(as_completed(futs), 1):
            try:
                fut.result()
            except Exception:  # noqa: BLE001
                failed += 1
            _say(args, "[%d/%d] 块完成" % (i, len(chunks)))
    n_bad = 0
    for seg, item in zip(segs, items):
        zh = (item.translated_text or "").strip()
        if not zh or zh == "ERROR":
            n_bad += 1
            continue                      # 失败条目不写译文（保留纯原文）
        seg.translated_text = zh
    data.save(out_path)
    return _emit(args, {"ok": n_bad == 0, "source": src,
                        "output": out_path, "target": target,
                        "engine": args.engine,
                        "n_cues": len(segs),
                        "n_failed_chunks": failed,
                        "n_failed_lines": n_bad})


def _lang_label(v: str):
    """目标语言三套口径都收：引擎标签（中文/英语…）、翻译器标签（简体中文…）、
    ISO 码（zh-Hans/zh/en/ja…）。无法识别返回 None（由调用方报错）。"""
    from engine_entities import LANGUAGES  # noqa: PLC0415
    v = (v or "").strip()
    if not v:
        return "简体中文"
    if v in LANGUAGES or v in LANGUAGES.values():
        return v
    try:
        import features.translate.engine_translate as et  # noqa: PLC0415
        probes = getattr(et, "TRANSLATOR_PROBES", {}) or {}
    except Exception:  # noqa: BLE001
        probes = {}
    for cls in probes.values():
        lm = getattr(cls, "lang_map", {}) or {}
        if v in lm or v in lm.values():
            return v
    #: ISO 简码 → 翻译器标签（端点代码由翻译器自己的 lang_map 解析）
    iso = {"zh": "简体中文", "zh-cn": "简体中文", "zh-hans": "简体中文",
           "zh-tw": "繁体中文", "zh-hant": "繁体中文", "zt": "繁体中文",
           "en": "英语", "ja": "日本語", "jp": "日本語", "ko": "韩语", "kr": "韩语",
           "yue": "粤语", "fr": "法语", "de": "德语", "es": "西班牙语",
           "ru": "俄语", "pt": "葡萄牙语", "tr": "土耳其语"}
    return iso.get(v.lower())


def setup_translate(sub) -> None:
    s = sub.add_parser("translate", parents=[common],
                       help="翻译字幕（bing/google/deeplx 免认证端点）")
    s.add_argument("file", help="输入字幕（.srt/.ass/.vtt）")
    s.add_argument("--to", default="zh-Hans", help="目标语言（zh-Hans/简体中文/en…）")
    s.add_argument("--engine", default="bing",
                   choices=["bing", "google", "deeplx", "微软翻译", "谷歌翻译", "DeepLx 翻译"],
                   help="翻译服务（默认 bing）")
    s.add_argument("--threads", type=int, default=4, help="并发线程数（默认 4）")
    s.add_argument("--batch", type=int, default=20, help="每块 cue 数（默认 20）")
    s.add_argument("--out", default="", help="输出字幕或目录（默认 data\\agent_out\\<时间戳>\\<名>.zh.srt）")
    s.set_defaults(fn=cmd_translate)