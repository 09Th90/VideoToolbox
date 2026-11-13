# -*- coding: utf-8 -*-
# @version 2.9.0
"""谷歌 ``dict-chrome-ex`` 端点的批量请求层（引擎线 / 自研线共用）。

为什么需要这一层
----------------
2026-11-01 实测：3376 条字幕在 GUI 里跑了 **6.5 分钟**（17:50:36→17:56:45）。
根因不是网络慢，而是引擎的 ``GoogleTranslator._translate_chunk`` **一条一次
HTTP GET**，再叠加模块级 ``_gtx_throttle`` 把跨线程相邻请求间隔钳到 ≥0.12s
（进程级串行）——10 个线程实测只有 5.8 行/秒，``thread_num`` 调多大都没用。

而该端点支持**重复 ``q`` 参数批量**，返回数组与请求 **1:1 且保序**
（本机实测 6 轮 10/25/40 条零错位，含日语行 / ``>>`` 前缀 / 换行 / ``100% & ?``）：

    GET https://translate.googleapis.com/translate_a/t
        ?client=dict-chrome-ex&sl=auto&tl=zh-CN&q=句1&q=句2&q=句3
    → [["译文1","en"],["译文2","en"],["译文3","en"]]

每条 ``q`` 仍是**独立翻译**，所以批量不改变译文质量（换行拼接会丢句子边界，
那种做法不要）。实测 100 条/请求仍可用，单请求延迟 0.9~2.4s 由代理 RTT 主导、
与条数几乎无关 → 25 条/批可把 3376 条压到 25~40 秒。

上限为什么按「编码后字节」算
----------------------------
URL 里的非 ASCII 经 percent-encode 是 **9 字节/字**（CJK UTF-8 3 字节 →
``%XX%XX%XX`` 9 字符），不是 3 倍。实测同一端点：URL 9415 字符 200 OK、
28215 字符 HTTP 400、117515 字符 HTTP 413。引擎原来那道「单条 5000 字符」
上限对日/韩文等于放行 45KB URL，**本身就必 400**——这是过去一类查不出原因的
静默 ERROR。所以本模块一律用 :func:`url_bytes` 计预算。

失败必须能看见
--------------
引擎 ``_request_text`` 在非 200 / 形状异常时**静默 ``return None``**，不打状态码，
上层只剩「Cannot extract translation from Google response: #65」这种无信息日志。
本模块自己发请求、自己打日志（状态码 / 条数 / URL 字节 / 响应头 / 耗时），
并顺带绕开那个静默分支。

对齐是本模块唯一不可逆的风险
----------------------------
引擎落盘前的两道门禁只看「译文非空」「有中文」，**译文错位照样全绿**并直接
产出语序打乱的字幕文件。所以这里一切可疑（条数不符、形状异常、组内重复原文
映射出不同译文）一律退回逐条——逐条是已被实测验证过的老路。
"""
from __future__ import annotations

import os
import random
import threading
import time
from urllib.parse import quote

from core.shared.log import _vc_log

__all__ = ["GtxBatchClient", "url_bytes", "group_texts", "batch_enabled"]

#: 单请求条数上限。实测 100 条可用，取 25 是为了压住「一次失败带走多少条」
#: （批量后一次超时/限流的爆炸半径是逐条时代的 25 倍）。
#: ⚠ 这两个上限是引擎缓存键的一部分（键含整块内容哈希），调整即作废旧缓存。
MAX_ITEMS_PER_REQUEST = 25
#: 单请求 URL 编码字节预算。实测 9415 字符可过、28215 被 400 拒，
#: 取已证安全点的约 2/3，并给代理侧可能的 ~8KB 请求行限制留余量。
MAX_REQUEST_URL_BYTES = 6000
#: 单条的编码字节上限（超了才截断并记 warning）。留足一批两条的余量。
MAX_ITEM_URL_BYTES = 4000
#: 批量单次请求超时。逐条时代是 20s；块变大后「停止」按钮要等在飞请求返回，
#: 压到 10s 让中止更跟手。
BATCH_TIMEOUT_SECONDS = 10
#: 429 指数退避的重试次数（与引擎逐条实现同参数）。
RATE_LIMIT_RETRIES = 4
#: 连续多少组触发超限（400/413/414）就整轮降为逐条——说明超限不是偶发。
OVERSIZE_GIVEAWAY_STREAK = 3

#: 本模块自己的全局节流（引擎线会传入引擎的 ``_gtx_throttle`` 复用同一把钟）。
_LOCK = threading.Lock()
_NEXT = [0.0]
_MIN_INTERVAL = 0.12


def _throttle() -> None:
    """全局节流：相邻两次谷歌请求间隔不小于 0.12s。"""
    while True:
        with _LOCK:
            now = time.monotonic()
            wait = _NEXT[0] - now
            if wait <= 0:
                _NEXT[0] = now + _MIN_INTERVAL
                return
        time.sleep(min(wait, 1.0))


def batch_enabled() -> bool:
    """批量总开关：``VT_GTX_BATCH=0`` 整体退回逐条（线上出问题不必重新打包）。"""
    return (os.environ.get("VT_GTX_BATCH") or "1").strip() != "0"


def url_bytes(text) -> int:
    """该文本作为 query 参数值时的**编码后字节数**（percent-encode 实算）。"""
    return len(quote(str(text or ""), safe=""))


def clip_to_url_bytes(text, budget=None):
    """把单条裁到编码字节预算内；返回 ``(文本, 是否被裁)``。

    只在真超限时截断，且**调用方必须记 warning**——静默截断会让译文丢掉后半段，
    用户只看到「这句怎么翻了一半」，日志里没有任何线索。
    """
    budget = budget or MAX_ITEM_URL_BYTES
    s = str(text or "")
    if url_bytes(s) <= budget:
        return s, False
    lo, hi = 0, len(s)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if url_bytes(s[:mid]) <= budget:
            lo = mid
        else:
            hi = mid - 1
    return s[:lo], True


def group_texts(texts, max_items=None, budget=None):
    """按「条数 ∧ 编码字节」双上限把下标分组（返回 ``list[list[int]]``）。

    确定性：同一输入永远得到同一分组——分组是缓存键的一部分，
    非确定性会让缓存永远不命中。
    """
    max_items = max_items or MAX_ITEMS_PER_REQUEST
    budget = budget or MAX_REQUEST_URL_BYTES
    groups: list = []
    cur: list = []
    cur_bytes = 0
    for i, t in enumerate(texts):
        n = url_bytes(t) + len("&q=")
        if cur and (len(cur) >= max_items or cur_bytes + n > budget):
            groups.append(cur)
            cur, cur_bytes = [], 0
        cur.append(i)
        cur_bytes += n
    if cur:
        groups.append(cur)
    return groups


class GtxBatchClient:
    """一个翻译器实例对应一个客户端（统计按次翻译汇总）。

    ``session`` / ``endpoint`` / ``headers`` / ``target_lang`` 由调用方给：
    引擎线传它自己的 session（路由已被 ``route_patch`` 钉死为走本地代理），
    自研线同理——本模块不碰代理决策，避免两条线各定一套路由。
    """

    def __init__(self, session, endpoint, headers, target_lang,
                 timeout=None, throttle=None, max_items=None, label=""):
        self.session = session
        self.endpoint = endpoint
        self.headers = headers
        self.target_lang = target_lang
        self.timeout = min(int(timeout or 20), BATCH_TIMEOUT_SECONDS)
        self.throttle = throttle or _throttle
        self.max_items = max_items or MAX_ITEMS_PER_REQUEST
        self.label = label
        self._oversize_streak = 0
        self.stats = {
            "batch_req": 0,      # 批量请求次数
            "single_req": 0,     # 逐条回退请求次数
            "hit": 0,            # 拿到译文的条数
            "items": 0,          # 总条数
            "blank": 0,          # 空原文（不发请求）
            "rate_limited": 0,   # 429 重试次数
            "oversize": 0,       # 400/413/414 次数
            "shape_bad": 0,      # 条数/形状异常次数
            "misalign": 0,       # 对齐不变量失败次数
            "fallback_items": 0,  # 走逐条回退的条数
            "clipped": 0,        # 被截断的条数
            "elapsed": 0.0,
        }
        self._errors = []

    # ---------------- 请求 ----------------
    def _params(self, texts):
        p = [("client", "dict-chrome-ex"), ("sl", "auto"),
             ("tl", self.target_lang)]
        p.extend(("q", t) for t in texts)
        return p

    def _note_error(self, text):
        if len(self._errors) < 5:
            self._errors.append(text)

    def _request(self, texts):
        """发一次请求（含 429 退避）。返回 ``(状态码, 解析结果或 None)``。

        解析结果只在「是数组、每项是数组且 ``[0]`` 是非空字符串」时给出，
        长度是否与请求一致交给调用方判——条数不符是**错位信号**，不是解析失败。
        """
        status = 0
        for attempt in range(RATE_LIMIT_RETRIES):
            self.throttle()
            t0 = time.time()
            try:
                r = self.session.get(self.endpoint, params=self._params(texts),
                                     headers=self.headers, timeout=self.timeout)
            except Exception as e:  # noqa: BLE001
                self.stats["elapsed"] += time.time() - t0
                self._note_error("%s: %s" % (type(e).__name__, str(e)[:80]))
                return -1, None
            self.stats["elapsed"] += time.time() - t0
            status = r.status_code
            if status == 429:
                self.stats["rate_limited"] += 1
                wait = 2.0 * (2 ** attempt) + random.uniform(0, 1.0)
                _vc_log("谷歌 429 限流，%.1fs 后第 %d/%d 次重试（本批 %d 条）"
                        % (wait, attempt + 1, RATE_LIMIT_RETRIES, len(texts)))
                time.sleep(wait)
                continue
            if status != 200:
                body = ""
                try:
                    body = (r.text or "")[:100].replace("\n", " ")
                except Exception:  # noqa: BLE001
                    pass
                self._note_error("HTTP %s 本批%d条 URL≈%d字节 %s"
                                 % (status, len(texts),
                                    sum(url_bytes(t) for t in texts), body))
                return status, None
            try:
                data = r.json()
            except Exception as e:  # noqa: BLE001
                self.stats["shape_bad"] += 1
                self._note_error("HTTP 200 但 JSON 解析失败：%s" % str(e)[:60])
                return status, None
            return status, data
        return status, None

    @staticmethod
    def _parse(data, want):
        """把响应解析成 ``want`` 长度的结果；任何形状不符返回 None（触发逐条）。"""
        if not isinstance(data, list) or len(data) != want:
            return None
        out = []
        for item in data:
            if not isinstance(item, list) or not item \
                    or not isinstance(item[0], str):
                return None
            text = item[0].strip()
            out.append(text or None)
        return out

    # ---------------- 降级阶梯 ----------------
    def _request_per_item(self, texts):
        """逐条回退（= 批量之前的老路），返回与 texts 等长的结果。"""
        out = []
        for t in texts:
            self.stats["single_req"] += 1
            _status, data = self._request([t])
            parsed = self._parse(data, 1)
            out.append(parsed[0] if parsed else None)
        return out

    def _request_group(self, texts):
        """一组一次请求，失败按判定顺序逐级降级。

        429 是唯一**不**逐条回退的分支：限流时逐条狂打只会越打越死，
        整组交给上层补翻轮（自带 1s/2s 等待）更划算。
        """
        n = len(texts)
        if n == 1:
            self.stats["single_req"] += 1
            _status, data = self._request(texts)
            parsed = self._parse(data, 1)
            return parsed if parsed else [None]

        self.stats["batch_req"] += 1
        status, data = self._request(texts)

        if status == 429:
            self.max_items = max(1, self.max_items // 2)  # 自适应减半
            _vc_log("谷歌持续 429，本组 %d 条整组失败（后续单请求条数上限减半为 %d）"
                    % (n, self.max_items))
            return [None] * n
        if status in (400, 413, 414):
            self.stats["oversize"] += 1
            self._oversize_streak += 1
            if self._oversize_streak >= OVERSIZE_GIVEAWAY_STREAK:
                _vc_log("谷歌连续 %d 组超限（400/413/414），本轮整体降为逐条"
                        % self._oversize_streak)
                self.max_items = 1
            half = n // 2
            left = self._request_group(texts[:half])
            right = self._request_group(texts[half:])
            return left + right
        self._oversize_streak = 0
        if status == 200:
            parsed = self._parse(data, n)
            if parsed is None:
                self.stats["shape_bad"] += 1
            elif not self._aligned(texts, parsed):
                self.stats["misalign"] += 1
                _vc_log("谷歌批量响应疑似错位（组内重复原文映射出不同译文，%d 条）"
                        "，本组退回逐条" % n)
            else:
                return parsed

        # 网络异常 / 其它非 200 / 形状或对齐可疑 → 逐条重来
        out = self._request_per_item(texts)
        self.stats["fallback_items"] += n
        return out

    @staticmethod
    def _aligned(texts, results):
        """对齐不变量：组内相同原文必须映射出相同译文。

        端点若把两条重复字幕合并或漏一条，位置就会整体平移——这是批量方案
        唯一不可逆的失败模式，宁可退回逐条也不能写进文件。
        """
        seen = {}
        for t, r in zip(texts, results):
            if r is None:
                continue
            if seen.get(t, r) != r:
                return False
            seen[t] = r
        return True

    # ---------------- 对外 ----------------
    def group(self, texts):
        """按当前上限把文本下标分组（引擎线用它切 chunk，保证请求粒度一致）。

        ``max_items`` 会被 429 分支自适应减半，所以分组必须走这里而不是模块函数，
        否则减半只在下一次翻译才生效。
        """
        return group_texts(texts, max_items=self.max_items)

    def translate_texts(self, texts):
        """翻译一批文本，返回与输入等长的 ``[str|None]``（None=没拿到译文）。"""
        t0 = time.time()
        n = len(texts)
        self.stats["items"] += n
        out: list = [None] * n
        if n == 0:
            return out
        if not batch_enabled():
            for i, t in enumerate(texts):
                if not t.strip():
                    out[i] = ""
                    self.stats["blank"] += 1
                    continue
                out[i] = self._request_per_item([t])[0]
            self.stats["elapsed"] += time.time() - t0
            return out

        # 空/纯空白原文摘出批量：空 q 会改变响应条数（→ 错位信号），
        # 且空译文会被引擎判为无效、让上层补翻轮白跑。行为与逐条时代一致。
        pending = []
        for i, t in enumerate(texts):
            if not str(t or "").strip():
                out[i] = ""
                self.stats["blank"] += 1
            else:
                pending.append(i)

        # group 给的是 pending 内部的相对下标，必须映射回 texts 的下标
        pending_texts = [texts[i] for i in pending]
        for rel_group in self.group(pending_texts):
            idxs = [pending[k] for k in rel_group]
            got = self._request_group([texts[i] for i in idxs])
            for j, i in enumerate(idxs):
                out[i] = got[j] if j < len(got) else None
        self.stats["hit"] += sum(1 for i in range(n) if out[i])
        self.stats["elapsed"] += time.time() - t0
        return out

    def translate_chunk(self, chunk):
        """翻译一个 chunk（就地写 ``translated_text`` 并返回同一对象）。

        与两条线的 chunk 契约一致：读 ``original_text``、写 ``translated_text``，
        失败写 ``"ERROR"`` 标记（绝不保留原文冒充译文）。
        """
        texts = []
        for d in chunk:
            text, clipped = clip_to_url_bytes(
                getattr(d, "original_text", "") or "")
            if clipped:
                self.stats["clipped"] += 1
                _vc_log("谷歌字幕条目 #%s 原文超过单请求编码上限 %d 字节，已截断"
                        "（译文可能不完整）——如经常出现请调小 ASR 单句时长"
                        % (getattr(d, "index", "?"), MAX_ITEM_URL_BYTES))
            texts.append(text)
        results = self.translate_texts(texts)
        for d, r in zip(chunk, results):
            if r:
                d.translated_text = r
            else:
                d.translated_text = "ERROR"
                _vc_log("谷歌该条未拿到译文 #%s（本批 %d 条，状态见下方汇总）"
                        % (getattr(d, "index", "?"), len(texts)))
        return chunk

    def summary(self, total_ok, total):
        """一行汇总（走 ``_vc_log``：引擎 logger 只桥 WARNING，级别会吞）。"""
        s = self.stats
        qps = (s["items"] / s["elapsed"]) if s["elapsed"] > 0 else 0
        text = ("谷歌批量翻译汇总%s：请求 批量%d/逐条%d，条数 %d/%d 有效，"
                "回退逐条 %d，空原文 %d，截断 %d，429重试 %d，超限 %d，形状异常 %d，"
                "错位 %d，网络耗时 %.1fs，实测 %.1f 条/秒"
                % (("（%s）" % self.label) if self.label else "",
                   s["batch_req"], s["single_req"], total_ok, total,
                   s["fallback_items"], s["blank"], s["clipped"],
                   s["rate_limited"], s["oversize"], s["shape_bad"],
                   s["misalign"], s["elapsed"], qps))
        if self._errors:
            text += "｜失败样本：" + "；".join(self._errors)
        _vc_log(text)
        return text
