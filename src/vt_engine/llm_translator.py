# @version 2.5.0
"""LLM 字幕翻译器（自研，替代 videocaptioner.core.translate.llm_translator）。

行为契约（对着引擎 llm_translator 的可观察行为逐条固化）：

* 输入为 ``{序号: 原文}`` JSON，输出**同键** JSON——严格一一对应，
  不合并不拆分；
* **Agent loop**：响应键集与输入不一致时，把错误反馈给模型要求修正，
  最多 ``MAX_STEPS=3`` 轮，仍不符就用最后一次结果（由上层断言兜底）；
* **反思模式**：每条值须为 dict 且含 ``native_translation`` 字段
  （定稿译文），取该字段作为译文；
* 缓存键多带一截模型名：``类名:哈希:语言:模型``（换模型必须重翻）；
* 失败抛异常由 ``_safe_translate_chunk`` 记账，绝不静默写原文。

提示词为自研模板（输入/输出结构与归档资源
``docs/vc_prompts_official/`` 的观察一致），不复制第三方提示词文件。
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple

from vt_engine.cache import generate_cache_key
from vt_engine.entities import SubtitleProcessData
from vt_engine.llm_client import LLMError, ai_enabled, chat
from vt_engine.log import setup_logger
from vt_engine.translate_base import BaseTranslator

logger = setup_logger("vt_engine.llm_translate")

__all__ = ["LLMTranslator", "parse_llm_json"]

#: Agent loop 最大轮次（引擎同款）。
MAX_STEPS = 3

_STANDARD_TEMPLATE = """你是一位经验丰富的字幕翻译专家，精通{target_language}的翻译，\
擅长将视频字幕译成流畅易懂的{target_language}。

要求：
- 译文要符合{target_language}的表达习惯，通俗易懂，连贯流畅。
- 专有名词或术语可适当保留或音译。
- 严格保持字幕编号的一一对应，不要合并或拆分字幕。
{extra}

输入是 JSON 字典（键为字幕编号，值为原文）。请输出同样键集的 JSON 字典，\
值为{target_language}译文。只输出 JSON，不要任何解释。"""

_REFLECT_TEMPLATE = """你是一位经验丰富的字幕翻译专家，精通{target_language}的翻译。

翻译流程（对每一条独立执行四轮）：
1. 直译：逐字逐句忠实原文，不遗漏信息。
2. 意译：在保证原意的前提下用通俗流畅的{target_language}意译。
3. 改进建议：审视直译与意译，结合术语与注意事项给出具体建议。
4. 定稿：择优整合，产出简洁畅达的最终译文。
{extra}

输入是 JSON 字典（键为字幕编号，值为原文）。输出同样键集的 JSON 字典；\
每条值必须是 dict，且**必须包含 native_translation 字段**（第四轮定稿译文）。\
只输出 JSON，不要任何解释。"""


def parse_llm_json(text: str) -> Any:
    """容忍性 JSON 解析（markdown 围栏 / 前后杂文本 / 尾逗号）。

    按序尝试：直接解析 → 剥 ```json 围栏 → 截取首个 ``{`` 到末个 ``}``
    → 失败抛 ``ValueError``。零第三方依赖（引擎用 json_repair，此处
    以有限容忍换无依赖）。
    """
    if not text:
        raise ValueError("空响应")
    s = text.strip()
    try:
        return json.loads(s)
    except ValueError:
        pass
    fence = re.search(r"```(?:json)?\s*(.*?)```", s, re.S)
    if fence:
        try:
            return json.loads(fence.group(1).strip())
        except ValueError:
            pass
    start, end = s.find("{"), s.rfind("}")
    if 0 <= start < end:
        candidate = s[start:end + 1]
        try:
            return json.loads(candidate)
        except ValueError:
            # 容忍尾逗号
            cleaned = re.sub(r",\s*([}\]])", r"\1", candidate)
            try:
                return json.loads(cleaned)
            except ValueError:
                pass
    raise ValueError("响应不是可解析的 JSON: %s" % s[:120])


class LLMTranslator(BaseTranslator):
    """OpenAI 兼容 LLM 翻译器（走项目自有 AI 单通道）。"""

    MAX_STEPS = MAX_STEPS

    def __init__(self, thread_num: int, batch_num: int, target_language,
                 model: str = "", custom_prompt: str = "",
                 is_reflect: bool = False, update_callback=None):
        super().__init__(thread_num=thread_num, batch_num=batch_num,
                         target_language=target_language,
                         update_callback=update_callback)
        self.model = model or ""
        self.custom_prompt = custom_prompt or ""
        self.is_reflect = bool(is_reflect)

    # ---------- 预检：AI 没配好就别开翻 ----------
    def _preflight(self) -> None:
        if not ai_enabled():
            raise LLMError(
                "AI 未配置或已关闭：LLM 翻译需要在「设置」中配置 API "
                "地址/密钥/模型，或改用机翻服务")

    # ---------- 提示词 ----------
    def _system_prompt(self) -> str:
        tpl = _REFLECT_TEMPLATE if self.is_reflect else _STANDARD_TEMPLATE
        extra = ""
        if self.custom_prompt.strip():
            extra = "\n术语/额外要求：\n%s" % self.custom_prompt.strip()
        return tpl.format(
            target_language=getattr(self.target_language, "value",
                                    str(self.target_language)),
            extra=extra)

    # ---------- 缓存键（多带模型名） ----------
    def _get_cache_key(self, chunk) -> str:
        name = getattr(self.target_language, "value",
                       str(self.target_language))
        return "%s:%s:%s:%s" % (type(self).__name__,
                                generate_cache_key(chunk), name, self.model)

    # ---------- 翻译一个块 ----------
    def _translate_chunk(self, subtitle_chunk: List[SubtitleProcessData]):
        logger.debug("[+]正在翻译字幕: %s - %s",
                     subtitle_chunk[0].index, subtitle_chunk[-1].index)
        subtitle_dict = {str(d.index): d.original_text
                         for d in subtitle_chunk}
        result_dict = self._agent_loop(subtitle_dict)

        for data in subtitle_chunk:
            key = str(data.index)
            if key not in result_dict:
                data.translated_text = "ERROR"
                continue
            v = result_dict[key]
            if self.is_reflect:
                if isinstance(v, dict):
                    text = v.get("native_translation")
                    if text is None:
                        # 定稿字段缺失时按引擎的可观察行为退回整体值
                        text = json.dumps(v, ensure_ascii=False)
                else:
                    text = v
            else:
                text = v if isinstance(v, str) else json.dumps(
                    v, ensure_ascii=False)
            data.translated_text = str(text or "").strip() or "ERROR"
        return subtitle_chunk

    # ---------- Agent loop ----------
    def _agent_loop(self, subtitle_dict: Dict[str, str]) -> Dict[str, Any]:
        messages: List[Dict[str, str]] = [
            {"role": "system", "content": self._system_prompt()},
            {"role": "user",
             "content": json.dumps(subtitle_dict, ensure_ascii=False)},
        ]
        last_response_dict = None
        for _ in range(self.MAX_STEPS):
            response = self._call_llm(messages)
            try:
                response_dict = parse_llm_json(response)
            except ValueError as e:
                logger.warning("LLM 响应解析失败（%s），按错误反馈重试", e)
                response_dict = None
            last_response_dict = response_dict
            is_valid, error_message = self._validate_llm_response(
                response_dict, subtitle_dict)
            if is_valid:
                return response_dict
            # 反馈循环：把错误告诉模型，要求只输出含全部键的有效 JSON。
            # ⚠ 单通道 chat() 只取「首个 system + 末位 user」，多轮消息
            # 历史会被压扁——反馈消息必须自带原始输入与上一轮坏响应，
            # 否则模型看不到待修的数据，修正循环永远无法成功（键集对不
            # 上时三轮全废，2026-10-19 自查修复）。
            bad = (json.dumps(response_dict, ensure_ascii=False)
                   if response_dict is not None else "(unparsable response)")
            messages.append({"role": "assistant", "content": bad})
            messages.append({
                "role": "user",
                "content": "Error: %s\n\nPrevious (invalid) response:\n%s\n"
                           "Original input:\n%s\n\nFix the errors above and "
                           "output ONLY a valid JSON dictionary with ALL %d "
                           "keys" % (error_message, bad,
                                     json.dumps(subtitle_dict,
                                                ensure_ascii=False),
                                     len(subtitle_dict))})
        return last_response_dict if last_response_dict is not None else {}

    def _call_llm(self, messages: List[Dict[str, str]]) -> str:
        """把多消息对话压成本项目单通道调用（system + 末位 user）。"""
        system = ""
        user = ""
        for m in messages:
            if m.get("role") == "system" and not system:
                system = m.get("content", "")
            elif m.get("role") == "user":
                user = m.get("content", "")
        return chat(user, system=system, model=self.model,
                    use_cache=False)

    def _validate_llm_response(self, response_dict: Any,
                               subtitle_dict: Dict[str, str]
                               ) -> Tuple[bool, str]:
        """校验键集（反思模式还校验 native_translation 嵌套结构）。"""
        if not isinstance(response_dict, dict):
            return (False,
                    "Output must be a dict, got %s. Use format: "
                    "{'0': 'text', '1': 'text'}"
                    % type(response_dict).__name__)
        expected = set(subtitle_dict.keys())
        actual = set(response_dict.keys())
        if expected != actual:
            def _sort(keys):
                return sorted(keys, key=lambda x: int(x) if x.isdigit()
                              else x)
            parts = []
            missing = expected - actual
            extra = actual - expected
            if missing:
                parts.append("Missing keys %s - you must translate these "
                             "items" % _sort(missing))
            if extra:
                parts.append("Extra keys %s - these keys are not in input, "
                             "remove them" % _sort(extra))
            return (False, "; ".join(parts))
        if self.is_reflect:
            for key, value in response_dict.items():
                if not isinstance(value, dict):
                    return (False,
                            "Key '%s': value must be a dict with "
                            "'native_translation' field. Got %s."
                            % (key, type(value).__name__))
                if "native_translation" not in value:
                    return (False,
                            "Key '%s': missing 'native_translation' field. "
                            "Found keys: %s. Must include "
                            "'native_translation'."
                            % (key, list(value.keys())))
        return True, ""
