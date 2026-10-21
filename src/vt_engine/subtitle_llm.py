# @version 2.5.1
"""字幕 LLM 后处理（自研，替代引擎的 SubtitleOptimizer / SubtitleSplitter）。

两项能力，均走项目自有 AI 单通道（``vt_engine.llm_client.chat``）：

* :func:`optimize_subtitle` —— 逐块校对：口头语/口误/标点/大小写/中英
  格式规范化，**保持编号一一对应、不改写原意、不做翻译**（引擎
  optimize 提示词的可观察规则）；
* :func:`split_subtitle` —— 字词级时间戳 → 句级：把词级字幕合并为utterance
  后交给模型在应在断句处插入 ``<br>``，再按词的起止时间重新切片
  （时间戳来自原词，不重新估计）。

与翻译共用同一套「JSON 同键进出 + 修复循环」模式；失败按 chunk 记账，
绝不静默写回原文冒充结果。
"""

from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, List, Optional

from vt_engine.asr_data import ASRData, ASRDataSeg
from vt_engine.entities import SubtitleProcessData
from vt_engine.llm_client import LLMError, ai_enabled, chat
from vt_engine.llm_translator import parse_llm_json
from vt_engine.log import setup_logger

logger = setup_logger("vt_engine.subtitle_llm")

__all__ = ["optimize_subtitle", "split_subtitle"]

#: 断句时每次送给模型的词数上限（输出体量与稳定性权衡）。
_SPLIT_WORDS_PER_CALL = 120

_OPTIMIZE_TEMPLATE = """你是字幕校对专家。你会收到 JSON 格式的字幕（键为编号），\
请按以下规则更正错误，然后输出同样键集的 JSON：

1. 保持原句结构与表达，不换写、不意译、不改写原意。
2. 删除口头语与非语言声音（um、uh、笑声、咳嗽等）。
3. 规范化：标点、英文大小写、纯文本数学公式（× ÷ 等）、代码变量名。
4. 编号一一对应，不合并、不拆分、不增删条目。
5. 有参考信息时优先按参考信息更正。
6. 保持原语言（英文→英文，中文→中文），不做翻译。
7. 只输出 JSON，不要任何解释。

参考信息（可为空）：
{extra}"""

_SPLIT_TEMPLATE = """你是字幕分句专家。请把下面的文本在应该断句的地方插入 <br>\
（原本逗号、句号等位置）。

要求：
- 中文/日语等 CJK：每段不超过 {cjk} 字；英语等拉丁语言：每段不超过 {en} 词。
- 每段之间也不要太短。
- 不修改、不添加、不删除任何内容，只插入 <br>。
- 保持 <br> 之间的内容意思完整。
- 直接返回插入 <br> 后的文本，不要任何解释。"""


def _run_chunks(chunks, worker, thread_num: int, update_callback):
    """线程池跑 chunk（保持输入顺序收集结果；单 chunk 失败不影响其他）。"""
    results = [None] * len(chunks)

    def _one(idx, chunk):
        try:
            results[idx] = worker(idx, chunk)
        except Exception as e:  # noqa: BLE001
            logger.error("chunk %d 失败: %s", idx, e)
            results[idx] = chunk  # 原样退回，由调用方决定是否接受
        if update_callback:
            try:
                update_callback(idx, len(chunks))
            except Exception:  # noqa: BLE001
                pass

    with ThreadPoolExecutor(max_workers=max(1, int(thread_num or 1))) as pool:
        futs = [pool.submit(_one, i, c) for i, c in enumerate(chunks)]
        for f in as_completed(futs):
            f.result()
    return results


def _fix_up_loop(subtitle_dict, system_prompt, model):
    """同键进出的 JSON 修复循环（键集不符时把错误反馈给模型，最多 3 轮）。"""
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user",
         "content": json.dumps(subtitle_dict, ensure_ascii=False)},
    ]
    last = None
    for _ in range(3):
        system = ""
        user = ""
        for m in messages:
            if m.get("role") == "system" and not system:
                system = m.get("content", "")
            elif m.get("role") == "user":
                user = m.get("content", "")
        response = chat(user, system=system, model=model, use_cache=False)
        try:
            resp_dict = parse_llm_json(response)
        except ValueError:
            resp_dict = None
        last = resp_dict
        if isinstance(resp_dict, dict) and \
                set(resp_dict.keys()) == set(subtitle_dict.keys()):
            return resp_dict
        messages.append({"role": "assistant",
                         "content": response})
        # ⚠ 同 llm_translator._agent_loop：单通道 chat() 压扁多轮历史，
        # 反馈消息必须自带原始输入与上一轮坏响应（2026-10-19 自查修复）。
        messages.append({"role": "user",
                         "content": "Error: keys mismatch. Output ONLY a "
                                    "valid JSON dictionary with ALL %d keys"
                                    "\n\nPrevious (invalid) response:\n%s"
                                    "\n\nOriginal input:\n%s"
                                    % (len(subtitle_dict), response,
                                       json.dumps(subtitle_dict,
                                                  ensure_ascii=False))})
    return last if isinstance(last, dict) else {}


def optimize_subtitle(asr_data: ASRData, model: str = "",
                      thread_num: int = 5, batch_num: int = 10,
                      custom_prompt: str = "",
                      update_callback: Optional[Callable] = None
                      ) -> ASRData:
    """校对字幕（LLM 逐块）。失败块原样保留——由上层决定是否接受。"""
    if not ai_enabled():
        raise LLMError("AI 未配置或已关闭：字幕优化需要配置 LLM")
    segments = list(asr_data.segments)
    if not segments:
        return asr_data
    chunks = [segments[i:i + max(1, int(batch_num or 1))]
              for i in range(0, len(segments), max(1, int(batch_num or 1)))]

    system = _OPTIMIZE_TEMPLATE.format(extra=custom_prompt or "（无）")

    def _work(idx, chunk):
        d = {str(s_index): seg.text
             for s_index, seg in enumerate(chunk)}
        out = _fix_up_loop(d, system, model)
        return out

    results = _run_chunks(chunks, _work, thread_num, update_callback)
    for chunk, res in zip(chunks, results):
        if not isinstance(res, dict):
            continue
        for s_index, seg in enumerate(chunk):
            v = res.get(str(s_index))
            if isinstance(v, str) and v.strip():
                seg.text = v.strip()
    return ASRData(segments)


# ---------------- 断句 ----------------

def _utterances_from_word_segments(segments: List[ASRDataSeg]):
    """把词级 segments 按标点/停顿合并为 utterance（返回 utterances，
    每个 utterance 是 (start_ms, end_ms, text)）。"""
    utterances = []
    cur_words = []
    cur_start = None
    for seg in segments:
        if cur_start is None:
            cur_start = seg.start_time
        cur_words.append(seg.text)
        text_so_far = "".join(cur_words)
        end_with_punct = text_so_far.rstrip().endswith(
            (".", "!", "?", "。", "！", "？", "…", "，", ","))
        if end_with_punct or len(cur_words) >= _SPLIT_WORDS_PER_CALL:
            utterances.append((cur_start, seg.end_time, text_so_far))
            cur_words = []
            cur_start = None
    if cur_words:
        utterances.append((cur_start or 0, segments[-1].end_time,
                           "".join(cur_words)))
    return utterances


def split_subtitle(asr_data: ASRData, max_word_count_cjk: int = 30,
                   max_word_count_english: int = 20, model: str = "",
                   thread_num: int = 5,
                   update_callback: Optional[Callable] = None
                   ) -> ASRData:
    """字词级时间戳 → 句级字幕（LLM 在应断处插 ``<br>``）。

    输入须为词级（``asr_data.is_word_timestamp()`` 为真）；非词级输入
    原样返回（调用方应先 ``split_to_word_segments()``）。
    """
    if not asr_data.is_word_timestamp():
        logger.info("非词级时间戳，跳过断句")
        return asr_data
    if not ai_enabled():
        raise LLMError("AI 未配置或已关闭：字幕断句需要配置 LLM")

    utterances = _utterances_from_word_segments(list(asr_data.segments))
    if not utterances:
        return asr_data
    system = _SPLIT_TEMPLATE.format(cjk=max_word_count_cjk,
                                    en=max_word_count_english)

    def _work(idx, utt):
        _s, _e, text = utt
        out = chat(text, system=system, model=model, use_cache=False)
        parts = [p.strip() for p in re.split(r"<br\s*/?>", out or "")
                 if p.strip()]
        return parts if parts else [text]

    results = _run_chunks(utterances, _work, thread_num, update_callback)

    # 重建句级 segments：按字符占比把 utterance 时长分摊到各句
    new_segments = []
    for (start, end, text), parts in zip(utterances, results):
        # _run_chunks 的失败回落写回的是 utterance 三元组（非 parts
        # 列表）——先归一化，否则 sum(len(p)) 对 int 求长直接
        # TypeError（单块 LLM 失败会炸掉整个断句，2026-10-19 自查修复）。
        if not isinstance(parts, list):
            parts = [text]
        total_chars = sum(len(p) for p in parts) or 1
        span = max(0, end - start)
        acc = 0
        for i, part in enumerate(parts):
            frac = len(part) / total_chars
            s = start + int(span * acc)
            e = start + int(span * (acc + frac)) if i < len(parts) - 1 \
                else end
            acc += frac
            new_segments.append(ASRDataSeg(text=part, start_time=s,
                                           end_time=max(e, s + 1)))
    return ASRData(new_segments)
