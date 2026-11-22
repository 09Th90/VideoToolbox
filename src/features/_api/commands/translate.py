# -*- coding: utf-8 -*-
# @version 3.2.0
"""translate 命令编排（原 features/translate/cli.py cmd_translate，行为不变）。"""
from __future__ import annotations

import os

from features._api.errors import fail
from features._api.runtime import _agent_out_dir


def run(params: dict, log) -> dict:
    # 翻译两补丁（路由钉死 + 去 AI）：CLI 路径不经 GUI 预热，这里显式装一次
    # （幂等；2026-10-20 起不再在 prepare_runtime_env 里装）。
    try:
        from core.translate.route_patch import ensure_translate_patches
        ensure_translate_patches()
    except Exception:  # noqa: BLE001
        pass
    from engine_asr_data import ASRData      # noqa: PLC0415
    from features.translate.engine_translate import make_translator  # noqa: PLC0415
    src = os.path.abspath(params.get("file", ""))
    if not os.path.isfile(src):
        return fail("文件不存在：%s" % src)
    try:
        data = ASRData.from_subtitle_file(src)
    except Exception as e:  # noqa: BLE001
        return fail("字幕解析失败：%s" % e)
    segs = list(getattr(data, "segments", []) or [])
    if not segs:
        return fail("字幕没有任何 cue")

    target = _lang_label(params.get("to", "zh-Hans"))
    if target is None:
        return fail("无法识别的目标语言：%r" % params.get("to"))
    engine_name = params.get("engine", "bing")
    threads = int(params.get("threads", 4))
    batch = int(params.get("batch", 20))
    try:
        translator = make_translator(engine_name, thread_num=threads,
                                     batch_num=batch, target_language=target)
    except KeyError as e:
        return fail(str(e))
    ok, why = translator.probe()
    if not ok:
        return fail("翻译端点不可用（%s）：%s" % (engine_name, why))

    out_dir = os.path.abspath(params["out"]) if params.get("out") else _agent_out_dir()
    out_path = out_dir if out_dir.lower().endswith((".srt", ".ass", ".txt")) else \
        os.path.join(out_dir, os.path.splitext(os.path.basename(src))[0] + ".zh.srt")
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)

    # 引擎 chunk 协议是 SubtitleProcessData(original_text/translated_text)，
    # 而 ASRData 段的原文字段叫 text——包一层适配，译后回写 seg.translated_text，
    # save() 按 ORIGINAL_ON_TOP（原文在上、译文在下）出双语字幕。
    from videocaptioner.core.entities import SubtitleProcessData  # noqa: PLC0415
    items = [SubtitleProcessData(index=i, original_text=(s.text or ""))
             for i, s in enumerate(segs)]

    from concurrent.futures import ThreadPoolExecutor, as_completed  # noqa: PLC0415
    chunks = [items[i:i + batch] for i in range(0, len(items), batch)]
    log("[信息] %d 条 cue → %d 块（%s → %s，%d 线程）"
        % (len(segs), len(chunks), engine_name, target, threads))
    failed = 0
    with ThreadPoolExecutor(max_workers=threads) as pool:
        futs = {pool.submit(translator.translate, c): c for c in chunks}
        for i, fut in enumerate(as_completed(futs), 1):
            try:
                fut.result()
            except Exception:  # noqa: BLE001
                failed += 1
            log("[%d/%d] 块完成" % (i, len(chunks)))
    n_bad = 0
    for seg, item in zip(segs, items):
        zh = (item.translated_text or "").strip()
        if not zh or zh == "ERROR":
            n_bad += 1
            continue                      # 失败条目不写译文（保留纯原文）
        seg.translated_text = zh
    data.save(out_path)
    return {"ok": n_bad == 0, "source": src,
            "output": out_path, "target": target,
            "engine": engine_name,
            "n_cues": len(segs),
            "n_failed_chunks": failed,
            "n_failed_lines": n_bad}


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