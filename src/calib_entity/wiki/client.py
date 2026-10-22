# @version 2.5.2
"""MediaWiki API 客户端（极简，只用标准库）。

只用三类查询：

    category_members(site, category)   分类成员（分页到底）
    page_wikitext(site, title)         页面源码（取 infobox 里的英文名等）
    search(site, q)                    按关键词搜页面

对 B 站 wiki 与 wiki.gg 通用。带 UA、重试、限速（默认 0.15 s/请求）。
"""
from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from typing import Dict, Iterator, List, Optional

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36 "
      "VideoToolbox-CalibBot/1.0 (+local use)")

DEFAULT_PAUSE = 0.15


class WikiClient:
    def __init__(self, api: str, pause: float = DEFAULT_PAUSE, retries: int = 4):
        self.api = api
        self.pause = pause
        self.retries = retries
        self.last_error = ""
        # B 站 wiki 用 Referer 做反爬：缺 Referer 直接 567（实测 2026-10-19）
        self.referer = api.rsplit("/", 1)[0] + "/"

    # -- 底层 ----------------------------------------------------

    def _get(self, params: Dict[str, object]) -> dict:
        q = {"format": "json", "formatversion": "1"}
        q.update({k: v for k, v in params.items() if v is not None})
        url = self.api + "?" + urllib.parse.urlencode(q, doseq=True)
        last = None
        for attempt in range(self.retries):
            try:
                req = urllib.request.Request(url, headers={
                    "User-Agent": UA,
                    "Referer": self.referer,
                    "Accept": "application/json, text/javascript, */*; q=0.01",
                    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                })
                with urllib.request.urlopen(req, timeout=20) as r:
                    data = r.read()
                time.sleep(self.pause)
                return json.loads(data.decode("utf-8", errors="replace"))
            except Exception as e:                    # noqa: BLE001
                last = e
                # 567 是 B 站 wiki 的限流码，退避更久
                wait = 1.2 * (attempt + 1) if "567" in str(e) else 0.6 * (attempt + 1)
                time.sleep(wait)
        self.last_error = f"{type(last).__name__}: {last}"
        return {}

    # -- 查询 ----------------------------------------------------

    def category_members(self, category: str, limit: int = 500) -> List[str]:
        """分类下全部页面标题（不含子分类）。"""
        out: List[str] = []
        cont: Optional[str] = None
        while True:
            d = self._get({
                "action": "query", "list": "categorymembers",
                "cmtitle": category, "cmlimit": limit,
                "cmnamespace": 0, "cmcontinue": cont,
            })
            if not d:
                break
            for it in (d.get("query", {}).get("categorymembers") or []):
                t = it.get("title")
                if t:
                    out.append(t)
            cont = (d.get("continue") or {}).get("cmcontinue")
            if not cont:
                break
        return out

    def page_wikitext(self, title: str) -> str:
        d = self._get({"action": "parse", "page": title,
                       "prop": "wikitext", "redirects": 1})
        return ((d.get("parse") or {}).get("wikitext") or "")

    def page_wikitexts(self, titles: List[str], batch: int = 20) -> Dict[str, str]:
        """批量取源码（先查缺失，再逐个 parse；parse 不支持批量）。"""
        return {t: self.page_wikitext(t) for t in titles}

    def search(self, q: str, limit: int = 10) -> List[str]:
        d = self._get({"action": "query", "list": "search",
                       "srsearch": q, "srlimit": limit})
        return [x["title"] for x in ((d.get("query") or {}).get("search") or [])
                if x.get("title")]

    def allpages_prefix(self, prefix: str, limit: int = 500, max_pages: int = 20) -> List[str]:
        """按标题前缀取页面（如 `名词注释/`、`世界观/`）。

        比 allpages 全量便宜得多，且能精准命中「地名/术语」命名空间。
        """
        out: List[str] = []
        cont: Optional[str] = None
        for _ in range(max_pages):
            d = self._get({
                "action": "query", "list": "allpages",
                "apprefix": prefix, "aplimit": limit,
                "apnamespace": 0, "apcontinue": cont,
            })
            if not d:
                break
            for it in (d.get("query", {}).get("allpages") or []):
                t = it.get("title")
                if t:
                    out.append(t)
            cont = (d.get("continue") or {}).get("apcontinue")
            if not cont:
                break
        return out
