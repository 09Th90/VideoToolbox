# -*- coding: utf-8 -*-
# @version 3.3.1
"""术语校准适配层：直连项目一 ``calib_core`` 真源。

旧项目二动态 import ``subtitle_calib_merged.py`` 生成物，2026-11-22 子键化
重构后该生成物一度落后真源，``_check_registry_consistency()`` 抛 ``SystemExit``
（``except Exception`` 接不住）导致字幕线程直接断。本适配层改为：

* 直接 ``import calib_core``，不再依赖任何生成物/绝对路径；
* 旧模式键（``akja`` / ``endobi`` / ``pgren`` / ``ja`` / ``ko``）先经
  ``normalize_mode`` 归一，避免查表为空而静默不校准；
* 表按模式编译一次并缓存；``bi`` 模式额外合并 ``WORD_MAP``（对齐上游主流程）；
* 任何失败都降级为直通，绝不阻断字幕产出。
"""
from __future__ import annotations

import threading

#: UI 展示用；值必须是 ``calib_core._MODE_TERM_TABLE`` 的键或可归一旧键。
MODE_LABELS: tuple[tuple[str, str], ...] = (
    ("bi", "中英双语"),
    ("ak", "明日方舟"),
    ("ak-ja", "明日方舟（日）"),
    ("ak-ko", "明日方舟（韩）"),
    ("endo", "终末地"),
    ("endo-bi", "终末地双语"),
    ("endo-ja", "终末地（日）"),
    ("endo-ko", "终末地（韩）"),
    ("wwoc", "综合手游OST"),
    ("wuwa-ja", "鸣潮（日）"),
    ("wuwa-ko", "鸣潮（韩）"),
    ("pgr-en", "战双（英）"),
    ("pgr-ja", "战双（日）"),
    ("ff14", "FF14"),
    ("ffrs", "FFRS"),
    ("pkm", "宝可梦"),
    ("react", "React"),
    ("zho", "纯中文"),
)


class Calibrator:
    def __init__(self, mode: str = "", enabled: bool = True,
                 extra_terms: dict | None = None):
        self.mode = mode or ""
        self.enabled = bool(enabled)
        self._extra = dict(extra_terms or {})
        self._core = None
        self._compiled: dict[str, tuple] = {}
        self._word_pairs: list[tuple[str, str]] | None = None
        self._lock = threading.RLock()
        self.error = ""
        self.available = False
        self.last_mode = ""

    # ------------------------------------------------------------------ load
    def _load(self) -> bool:
        if self._core is not None:
            return self.available
        try:
            import calib_core as core  # noqa: PLC0415 —— 惰性，避免页面构建即加载 33 张表
            required = ("TABLES", "_MODE_TERM_TABLE", "_compile_map",
                        "_replace_report", "_is_chinese_line")
            missing = [n for n in required if not hasattr(core, n)]
            if missing:
                raise RuntimeError("missing symbols: " + ", ".join(missing))
            self._core = core
            self.available = True
            self.error = ""
        except Exception as e:  # noqa: BLE001
            self.error = f"calib_core load failed: {e!r}"
            self.available = False
        return self.available

    @staticmethod
    def _normalize(mode: str) -> str:
        try:
            from calib_core.data.modes import normalize_mode  # noqa: PLC0415
            return normalize_mode(mode)
        except Exception:  # noqa: BLE001
            return (mode or "").strip().lower()

    def set_mode(self, mode: str) -> None:
        with self._lock:
            self.mode = mode or ""
            self.last_mode = ""          # 让 WORD_MAP 分支按新模式重算

    # ------------------------------------------------------------------ replace
    def calibrate(self, text: str) -> str:
        """仅对中文行做名词级替换；返回原文或校准后的文本。"""
        if not text or not self.enabled or not self.mode:
            return text
        with self._lock:
            if not self._load():
                return text
            core = self._core
            assert core is not None
            mode = self._normalize(self.mode)
            table = core._MODE_TERM_TABLE.get(mode)
            if not table:
                self.last_mode = ""
                return text
            if table not in self._compiled:
                mapping = dict(core.TABLES.get(table, {}))
                mapping.update(self._extra)       # 用户补充词，所有模式生效
                self._compiled[table] = core._compile_map(mapping)
            if self.last_mode != mode:
                pairs = list(self._extra.items())
                if mode == "bi" and hasattr(core, "WORD_MAP"):
                    pairs += list(core.WORD_MAP.items())
                self._word_pairs = sorted(pairs, key=lambda kv: len(kv[0]),
                                          reverse=True)
                self.last_mode = mode
            pairs_extra, charset_extra = self._compiled[table]
            try:
                if not core._is_chinese_line(text):
                    return text
                out = (core._replace_report(text, pairs_extra, charset_extra, {})
                       if pairs_extra else text)
                if self._word_pairs:
                    out = self._absorb_replace(out, self._word_pairs)
                return out
            except Exception as e:  # noqa: BLE001
                self.error = f"calib replace failed: {e!r}"
                return text

    @staticmethod
    def _absorb_replace(text: str, pairs: list[tuple[str, str]]) -> str:
        """长键优先替换，并吸收替换值后缀与原文后续的重叠。

        上游 WORD_MAP 的键不含语境后缀（「暴跌」→「下落攻击」），朴素 replace
        会把「暴跌攻击」变成「下落攻击攻击」；命中键后若紧跟的文本恰为替换值
        的后缀，则一并吸收。
        """
        charset = frozenset("".join(k for k, _ in pairs))
        if charset.isdisjoint(text):
            return text
        for k, v in pairs:
            start = 0
            while True:
                i = text.find(k, start)
                if i < 0:
                    break
                j = i + len(k)
                absorb = 0
                for n in range(min(len(v), len(text) - j), 0, -1):
                    if v.endswith(text[j:j + n]):
                        absorb = n
                        break
                text = text[:i] + v + text[j + absorb:]
                start = i + len(v)
        return text

    def stats(self) -> dict:
        return {"enabled": self.enabled, "mode": self.mode,
                "normalized": self.last_mode,
                "available": self.available,
                "tables_compiled": len(self._compiled),
                "error": self.error}
