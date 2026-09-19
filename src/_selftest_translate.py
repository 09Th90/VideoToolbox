# -*- coding: utf-8 -*-
# @version 1.15.2
"""字幕翻译完整性自检（v1.15.1 回归保护）。

背景：机翻端点整批失败时，条目译文是空字符串，``ASRData.to_srt`` 会"静默回落
成原文"，于是产出一个**名字叫「-谷歌翻译.srt」、内容其实是原文**的文件，全程零
报错。本脚本用 mock 掉的网络层验证修复后不会再出现这种"假翻译"。

覆盖四种场景：
  A. 全部成功        → 出双语产物
  B. 部分失败        → 抛 TranslationIncompleteError，且**不落盘**
  C. 端点返回原文    → 抛「译文里没有任何中文」
  D. 目标语言非中文  → 不触发语言校验（不误伤）

用法（在 src 目录）：
    "..\\tools\\python\\python.exe" _selftest_translate.py
说明：必须用 tools\\python 的解释器跑（要能 import videocaptioner 及其依赖）。
"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SP = os.path.join(ROOT, "tools", "python", "Lib", "site-packages")
if os.path.isdir(SP) and SP not in sys.path:
    sys.path.insert(0, SP)

from videocaptioner.core.asr.asr_data import ASRData          # noqa: E402
from videocaptioner.core.entities import (                    # noqa: E402
    SubtitleLayoutEnum,
    TranslatorServiceEnum,
)
from videocaptioner.core.translate import types as ttypes     # noqa: E402
from videocaptioner.core.translate.base import (              # noqa: E402
    TranslationIncompleteError,
)
import videocaptioner.core.translate.google_translator as gtr  # noqa: E402
import videocaptioner.core.translate.bing_translator as btr    # noqa: E402
from videocaptioner.ui.thread.subtitle_thread import (         # noqa: E402
    translate_with_machine_fallback,
)

LINES, FAILS = [], []
TMP = tempfile.mkdtemp(prefix="vt_selftest_translate_")


def check(name, ok, extra=""):
    LINES.append(("PASS" if ok else "FAIL") + " | " + name
                 + ((" | " + str(extra)) if extra else ""))
    if not ok:
        FAILS.append(name)


def _make_srt(tag):
    body = [
        "%d\n00:00:%02d,000 --> 00:00:%02d,000\nSentence %s number %d\n"
        % (i, i * 2, i * 2 + 2, tag, i)
        for i in range(1, 7)
    ]
    p = os.path.join(TMP, "_st_%s.srt" % tag)
    with open(p, "w", encoding="utf-8") as f:
        f.write("\n".join(body))
    return p


def _run(tag, mode, target=ttypes.TargetLanguage.SIMPLIFIED_CHINESE):
    """mode: ok（全成功）| partial（每 3 条失败 1 条）| passthrough（原样返回）"""
    src = _make_srt(tag)
    out = os.path.join(TMP, "_st_%s.out.srt" % tag)
    if os.path.isfile(out):
        os.remove(out)

    asr = ASRData.from_subtitle_file(src)
    seq = [0]

    def fake_request_text(self, text, target_lang, timeout=None):
        seq[0] += 1
        if mode == "passthrough":
            return text
        if mode == "partial" and seq[0] % 3 == 0:
            return None
        return "译文<%s>" % text

    orig = gtr.GoogleTranslator._request_text
    gtr.GoogleTranslator._request_text = fake_request_text
    try:
        tr = gtr.GoogleTranslator(thread_num=2, batch_num=3, target_language=target,
                                  timeout=10, update_callback=None)
        result, err = None, None
        try:
            result = tr.translate_subtitle(asr)
        except Exception as e:  # noqa: BLE001
            err = e
        if result is not None:
            result.save(save_path=out, ass_style="",
                        layout=SubtitleLayoutEnum.TRANSLATE_ON_TOP)
        return err, out, result
    finally:
        gtr.GoogleTranslator._request_text = orig


def _run_fallback():
    """首选机翻（谷歌）整批失败 → 应自动回退微软并产出中文。

    顺带验证回退是"可逆"的：config 上的翻译服务用过即还原。
    """
    import types

    src = _make_srt("fb")
    asr = ASRData.from_subtitle_file(src)
    cfg = types.SimpleNamespace(
        translator_service=TranslatorServiceEnum.GOOGLE,
        thread_num=2,
        batch_size=3,
        target_language=ttypes.TargetLanguage.SIMPLIFIED_CHINESE,
        llm_model="",
        need_reflect=False,
        deeplx_endpoint="",
    )

    def google_always_fail(self, text, target_lang, timeout=None):
        return None                       # 模拟境内直连谷歌：全部失败

    def bing_ok(self, chunk):
        for d in chunk:
            d.translated_text = "微软译:" + d.original_text
        return chunk

    orig_g = gtr.GoogleTranslator._request_text
    orig_b = btr.BingTranslator._translate_chunk
    gtr.GoogleTranslator._request_text = google_always_fail
    btr.BingTranslator._translate_chunk = bing_ok

    msgs = []
    try:
        res = translate_with_machine_fallback(cfg, "", None, asr,
                                              progress=msgs.append)
        han = sum(1 for s in res.segments for ch in s.translated_text
                  if "\u4e00" <= ch <= "\u9fff")
        return han, len(res.segments), cfg.translator_service, msgs, None
    except Exception as e:  # noqa: BLE001
        return 0, len(asr.segments), cfg.translator_service, msgs, e
    finally:
        gtr.GoogleTranslator._request_text = orig_g
        btr.BingTranslator._translate_chunk = orig_b


def _run_fastfail():
    """预检失败时应**立刻**放弃，而不是把每条字幕都慢慢超时一遍。

    返回 (实际发起请求次数, 异常)。
    """
    src = _make_srt("ff")
    asr = ASRData.from_subtitle_file(src)
    calls = [0]

    def always_none(self, text, target_lang, timeout=None):
        calls[0] += 1
        return None

    orig = gtr.GoogleTranslator._request_text
    gtr.GoogleTranslator._request_text = always_none
    try:
        tr = gtr.GoogleTranslator(
            thread_num=2, batch_num=3,
            target_language=ttypes.TargetLanguage.SIMPLIFIED_CHINESE,
            timeout=10, update_callback=None)
        err = None
        try:
            tr.translate_subtitle(asr)
        except Exception as e:  # noqa: BLE001
            err = e
        return calls[0], err
    finally:
        gtr.GoogleTranslator._request_text = orig


def main():
    print("=" * 62)
    print("  字幕翻译完整性自检（v1.15.1：译文缺失必须报错，不得静默输出原文）")
    print("=" * 62)

    err, out, _ = _run("ok", "ok")
    check("A 全成功：不报错", err is None, repr(err)[:90])
    check("A 全成功：产出双语",
          os.path.isfile(out) and "译文<" in open(out, encoding="utf-8-sig").read())

    err, out, _ = _run("part", "partial")
    check("B 部分失败：抛 TranslationIncompleteError",
          isinstance(err, TranslationIncompleteError), type(err).__name__)
    check("B 部分失败：不落盘", not os.path.isfile(out))

    err, out, _ = _run("pass", "passthrough")
    check("C 未真正翻译：抛 TranslationIncompleteError",
          isinstance(err, TranslationIncompleteError), type(err).__name__)
    check("C 未真正翻译：命中中文缺失判定",
          err is not None and "中文" in str(err), str(err)[:100] if err else "")
    check("C 未真正翻译：不落盘", not os.path.isfile(out))

    err, out, _ = _run("en", "passthrough", target=ttypes.TargetLanguage.ENGLISH)
    check("D 目标非中文：不误伤", err is None and os.path.isfile(out), repr(err)[:90])

    # E. 机翻回退：谷歌不通 → 自动改用微软
    han, total, svc_after, msgs, err = _run_fallback()
    check("E 谷歌全失败：自动回退微软并出中文", err is None and han > 0,
          "err=%s han=%d/%d" % (repr(err)[:60], han, total))
    check("E 回退后翻译服务设置已还原",
          svc_after == TranslatorServiceEnum.GOOGLE,
          getattr(svc_after, "value", svc_after))
    check("E 回退动作有提示", any("微软翻译" in m for m in msgs), msgs[:1])

    # F. 预检快速失败：只在预检探 1 次，不把 6 条字幕逐条跑超时
    calls, err = _run_fastfail()
    check("F 预检失败：只探 1 次就放弃", err is not None and calls == 1,
          "calls=%d" % calls)
    check("F 预检失败：给出可操作的提示",
          err is not None and "谷歌翻译端点" in str(err), str(err)[:80] if err else "")

    print("\n".join(LINES))
    print("-" * 62)
    print("PASS=%d FAIL=%d" % (len(LINES) - len(FAILS), len(FAILS)))
    if FAILS:
        print("FAILS: " + "; ".join(FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
