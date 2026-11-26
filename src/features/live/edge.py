# -*- coding: utf-8 -*-
# @version 3.3.1
"""Edge 翻译：POST JSON 数组，无需令牌，直连可用，批量 1:1 保序。

方向自动判定：原文含汉字 → 译英文；否则 → 译简体中文。与本地引擎
``--ask`` 的两行方向语义一致，保证云端/本地降级时字幕方向不跳变。
翻译失败一律返回空串（上层标 degraded），绝不抛断整条字幕链路。
"""
from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request

from .cue import script

ENDPOINT = "https://edge.microsoft.com/translate/translatetext"
ZH_CODE = "zh-Hans"
EN_CODE = "en"


class EdgeTranslator:
    name = "edge"

    def __init__(self, cfg):
        t = cfg.section("translate")
        self.enabled = bool(t.get("enabled", True))
        self.endpoint = t.get("endpoint", ENDPOINT) or ENDPOINT
        self.timeout = float(t.get("timeout_s", 8))
        self.retries = max(0, int(t.get("retries", 1)))
        self.zh_code = t.get("zh_code", ZH_CODE)
        self.en_code = t.get("en_code", EN_CODE)
        self.fallback_lang = t.get("target_lang", ZH_CODE) or ZH_CODE
        self.calls = 0
        self.errors = 0
        self.last_error = ""
        self._local = threading.local()

    def _opener(self):
        op = getattr(self._local, "op", None)
        if op is None:
            op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            self._local.op = op
        return op

    def target_for(self, text: str) -> str:
        s = script(text)
        if s == "zh":
            return self.en_code
        if s == "en":
            return self.zh_code
        return self.fallback_lang

    def translate_batch(self, texts: list[str]) -> list[str]:
        """批量翻译，返回与入参等长、同序的结果；失败位为空串。

        端点偶发返回空体（实测 8 次中 1 次，多在首次请求），故对网络/解析类
        失败重试；条数不匹配属语义错误，不重试以免译文错位。
        """
        out = [""] * len(texts)
        idx = [i for i, t in enumerate(texts) if t and t.strip()]
        if not self.enabled or not idx:
            return out
        payload = [texts[i].strip() for i in idx]
        to = self.target_for(payload[0])
        url = f"{self.endpoint}?to={to}&api-version=3.0"
        data = None
        for attempt in range(self.retries + 1):
            req = urllib.request.Request(
                url, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                method="POST", headers={"Content-Type": "application/json",
                                        "Accept": "application/json"})
            self.calls += 1
            try:
                with self._opener().open(req, timeout=self.timeout) as r:
                    raw = r.read().decode("utf-8", "replace")
                data = json.loads(raw)
                break
            except Exception as e:  # noqa: BLE001
                self.last_error = repr(e)[:160]
                if attempt < self.retries:
                    time.sleep(0.3)
                    continue
                self.errors += 1
                return out
        if not isinstance(data, list) or len(data) != len(payload):
            self.errors += 1
            self.last_error = ("条数不匹配: %s/%s"
                               % (len(data) if isinstance(data, list) else "?",
                                  len(payload)))
            return out
        for i, item in zip(idx, data):
            try:
                out[i] = item["translations"][0]["text"]
            except (KeyError, IndexError, TypeError):
                self.errors += 1
                self.last_error = "响应缺 translations[0].text"
                return out
        self.last_error = ""
        return out

    def translate(self, text: str) -> str:
        if not text or not text.strip():
            return ""
        return self.translate_batch([text])[0]

    def stats(self) -> dict:
        return {"name": self.name, "enabled": self.enabled, "calls": self.calls,
                "errors": self.errors, "last_error": self.last_error}
