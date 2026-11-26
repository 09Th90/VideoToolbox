# -*- coding: utf-8 -*-
# @version 3.3.1
"""发布素材生成（2026-11-25）：从字幕产出 B 站投稿素材。

产出 10 段时间轴（00:00:00 起点、每段>=5s、每节标题<=16 字、尽可能均匀、按剧情）
+ 10 个 tag（与标题不重复）+ 中文标题（【游戏名】钩子【主播名】，<=80 字）。
素材目录写 投稿信息.txt，格式对齐 automation/bili_auto_submit.load_material。
LLM 走全局 AI 单通道；代码侧强制约束兜底。纯标准库 + 引擎接缝，不 import Qt。
"""
from __future__ import annotations

import json
import os
import re

CHAPTER_COUNT = 10
TAG_COUNT = 10
MIN_SEG_SECONDS = 5.0
MAX_CHAPTER_TITLE = 16
MAX_TITLE = 80

_HMS_RE = re.compile(r"(\d+):(\d+):(\d+)[,.](\d+)")


def _safe_join(base, name):
    """在 base 目录内拼接文件名：realpath 规范化 + commonpath 限制在 base 内，
    文件名取 basename 杜绝目录分量，防路径穿越。"""
    base = os.path.realpath(base)
    target = os.path.realpath(os.path.join(base, os.path.basename(name)))
    if os.path.commonpath([base, target]) != base:
        raise ValueError("输出路径越界")
    return target


def _read_text(path):
    raw = open(path, "rb").read()
    for bom, enc in ((b"\xef\xbb\xbf", "utf-8-sig"), (b"\xff\xfe", "utf-16"),
                     (b"\xfe\xff", "utf-16")):
        if raw.startswith(bom):
            return raw.decode(enc, errors="replace")
    for enc in ("utf-8", "gb18030", "big5", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _hms_to_sec(h, m, s, ms):
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0


def parse_srt_timed(path):
    lines = _read_text(path).replace("\r\n", "\n").replace("\r", "\n").split("\n")
    cues, i, n = [], 0, len(lines)
    while i < n:
        s = lines[i].strip()
        if s.isdigit() and (i == 0 or lines[i - 1].strip() == ""):
            j = i + 1
            if j < n and "-->" in lines[j]:
                m = _HMS_RE.findall(lines[j])
                kk = j + 1
                while kk < n and lines[kk].strip() != "":
                    kk += 1
                texts = lines[j + 1:kk]
                if texts and len(m) >= 2:
                    start = _hms_to_sec(*m[0])
                    end = _hms_to_sec(*m[1])
                    zh, en = [], []
                    for t in texts:
                        if re.search(r"[一-鿿]", t):
                            zh.append(t)
                        else:
                            en.append(t)
                    cues.append({"num": s, "start": start, "end": end,
                                 "zh": " ".join(zh), "en": " ".join(en)})
                    i = kk
                    continue
        i += 1
    return cues


def hms(seconds):
    seconds = max(0, int(round(seconds)))
    return "%02d:%02d:%02d" % (seconds // 3600, (seconds % 3600) // 60, seconds % 60)


def video_duration(video, cues):
    if video and os.path.isfile(video):
        try:
            from features.split.video_split import probe_media
            from core.download.deps import ensure_ffmpeg
            _ff, fp = ensure_ffmpeg()
            info = probe_media(fp, video)
            d = float(info.get("duration") or 0)
            if d > 0:
                return d
        except Exception:
            pass
    return max((c["end"] for c in cues), default=0.0)


def _title_from_info(folder):
    if not folder or not os.path.isdir(folder):
        return ""
    for fn in sorted(os.listdir(folder)):
        if fn.endswith("信息.txt"):
            try:
                for ln in _read_text(os.path.join(folder, fn)).splitlines():
                    mm = re.match(r"\s*标题\s*[:：]\s*(.+)", ln)
                    if mm and mm.group(1).strip():
                        return mm.group(1).strip()
            except OSError:
                pass
    return ""


def _clean_title_en(srt, title_en, video=None):
    if title_en:
        return title_en.strip()
    dirs = [os.path.split(os.path.realpath(srt))[0]]
    if video:
        dirs.append(os.path.split(os.path.realpath(video))[0])
    for d in dirs:
        t = _title_from_info(d)
        if t:
            return t
    name = os.path.splitext(os.path.basename(srt))[0]
    name = re.sub(r"^【字幕】", "", name)
    name = re.sub(r"[.\-](?:en|ja|ko|zh|calib\w*|微软翻译|谷歌翻译).*$", "", name)
    return name.strip()


def _config_default(key):
    try:
        from core.shared.ai import ai_load_config
        return str(ai_load_config().get(key) or "").strip()
    except Exception:
        return ""


def _sample(cues, max_n=160, max_chars=14000):
    if len(cues) <= max_n:
        picked = cues
    else:
        step = len(cues) / float(max_n)
        picked = [cues[min(int(i * step), len(cues) - 1)] for i in range(max_n)]
    out, used = [], 0
    for c in picked:
        ln = f'{hms(c["start"])}\t{c["zh"]}\t{c["en"]}'
        if used + len(ln) > max_chars:
            break
        out.append(ln)
        used += len(ln)
    return "\n".join(out)


_SYSTEM = ("你是 B 站二游区资深运营，擅长高点击率标题与章节策划。只输出一个严格 JSON 对象，"
           "不要解释、不要代码围栏。")


def _prompt(sample, title_en, game, streamer, duration):
    return f"""根据以下反应片字幕（每行：时间戳<TAB>中文<TAB>英文参考）策划 B 站投稿素材。

英文原始标题：{title_en}
游戏名：{game or '（从字幕推断）'}
主播名：{streamer or '（从字幕推断）'}
视频时长：{hms(duration)}

【字幕采样】
{sample}

输出严格 JSON，四个字段：
1. title：中文标题，格式严格为「【游戏名】<高点击钩子>【主播名】」。钩子基于主播对游戏/角色的
   评价总结（抓住最有梗/最反差的一句），参考英文原标题，<={MAX_TITLE} 字，正文不得出现
   「XX主播」「该主播」这类说法（主播名只放在结尾【】里）。游戏名/主播名用上面给定的值。
2. tags：正好 {TAG_COUNT} 个简体中文标签，每个 2-8 字，与标题用词不重复，覆盖游戏名/角色/
   体裁/主题，按重要度排序。
3. chapters：正好 {CHAPTER_COUNT} 段章节，按剧情/话题转折裁切、尽可能均匀。每段
   {{"start": 起始秒数(整数), "title": "章节标题(<={MAX_CHAPTER_TITLE}字)"}}。第一段 start 必须 0，
   起始秒数递增，最后一段接近视频结尾。
4. desc：一句话简介（<=60 字）。

JSON 形如：{{"title":"…","tags":["…"],"chapters":[{{"start":0,"title":"…"}}],"desc":"…"}}"""


def _parse_json(raw):
    if not raw:
        return {}
    s = raw.strip()
    if "```" in s:
        for seg in s.split("```"):
            seg = seg.strip()
            if seg.startswith("json"):
                seg = seg[4:].strip()
            if seg.startswith("{"):
                s = seg
                break
    a, b = s.find("{"), s.rfind("}")
    if a < 0 or b <= a:
        return {}
    try:
        v = json.loads(s[a:b + 1])
        return v if isinstance(v, dict) else {}
    except ValueError:
        return {}


def _enforce(obj, duration, game, streamer):
    title = str(obj.get("title") or "").strip()
    g = game or "游戏"
    s = streamer or ""
    body = re.sub(r"【[^】]*】", "", title).strip() or title or "精彩反应合集"
    title = f"【{g}】{body}" + (f"【{s}】" if s else "")
    if len(title) > MAX_TITLE:
        keep = MAX_TITLE - len(f"【{g}】") - (len(f"【{s}】") if s else 0)
        body = body[:max(1, keep)]
        title = f"【{g}】{body}" + (f"【{s}】" if s else "")
    tags, seen = [], set()
    for t in (obj.get("tags") or []):
        t = str(t).strip().strip("#")
        if not t or t in seen or t in title:
            continue
        seen.add(t)
        tags.append(t)
    tags = tags[:TAG_COUNT]
    # 不足 10 个用通用体裁词补足（去标题词/去重），保证 tag 数量达标
    _fill = ["游戏测评", "动作游戏", "Reaction", "二游", "手游情报", "游戏音乐",
             "二次元", "游戏杂谈", "游戏推荐", "库洛游戏", "鹰角网络", "米哈游"]
    for t in _fill:
        if len(tags) >= TAG_COUNT:
            break
        if t not in seen and t not in title:
            seen.add(t)
            tags.append(t)
    raw_ch = obj.get("chapters") or []
    starts, titles = [], []
    for c in raw_ch:
        if isinstance(c, dict):
            try:
                st = float(c.get("start", 0))
            except (TypeError, ValueError):
                st = 0.0
            starts.append(max(0.0, st))
            titles.append(str(c.get("title") or "").strip()[:MAX_CHAPTER_TITLE])
    need_rebuild = (len(starts) != CHAPTER_COUNT or not starts or starts[0] > 1.0)
    if not need_rebuild:
        for k in range(1, len(starts)):
            if starts[k] - starts[k - 1] < MIN_SEG_SECONDS:
                need_rebuild = True
                break
    if need_rebuild:
        step = duration / CHAPTER_COUNT if duration > 0 else MIN_SEG_SECONDS
        starts = [round(k * step, 1) for k in range(CHAPTER_COUNT)]
    starts[0] = 0.0
    for k in range(1, len(starts)):
        if starts[k] <= starts[k - 1] + MIN_SEG_SECONDS:
            starts[k] = starts[k - 1] + MIN_SEG_SECONDS
    chapters = []
    for k in range(CHAPTER_COUNT):
        t = titles[k] if k < len(titles) and titles[k] else f"第{k + 1}段"
        chapters.append({"start": starts[k], "title": t[:MAX_CHAPTER_TITLE]})
    desc = str(obj.get("desc") or "").strip()[:60]
    return {"title": title, "tags": tags, "chapters": chapters, "desc": desc}


def write_material(folder, mat, game):
    base = os.path.realpath(folder)
    os.makedirs(base, exist_ok=True)
    lines = [f"中文标题：{mat['title']}",
             "标签：" + "，".join(mat["tags"]),
             f"分区：{game or '游戏'}",
             f"简介：{mat['desc']}", ""]
    for c in mat["chapters"]:
        lines.append(f'{hms(c["start"])} {c["title"]}')
    info = "\n".join(lines) + "\n"
    with open(_safe_join(base, "投稿信息.txt"), "w", encoding="utf-8", newline="") as f:
        f.write(info)
    md = ["# 发布素材\n", f"## 标题\n{mat['title']}\n",
          f"## 标签（{len(mat['tags'])}）\n" + " / ".join(mat["tags"]) + "\n",
          f"## 时间轴（{len(mat['chapters'])} 段）"]
    for c in mat["chapters"]:
        md.append(f'- {hms(c["start"])} {c["title"]}')
    md.append(f"\n## 简介\n{mat['desc']}\n")
    with open(_safe_join(base, "发布素材.md"), "w", encoding="utf-8", newline="") as f:
        f.write("\n".join(md))
    return info


def generate_material(srt, video=None, game=None, streamer=None, title_en=None,
                      out=None, log=None, chat=None):
    log = log or (lambda m: None)
    srt = os.path.realpath(srt)
    if not os.path.isfile(srt):
        return {"ok": False, "error": f"字幕不存在：{srt}"}
    cues = parse_srt_timed(srt)
    if not cues:
        return {"ok": False, "error": "字幕为空，无内容可生成素材"}
    game = (game or _config_default("publish_default_game")).strip()
    streamer = (streamer or _config_default("publish_default_streamer")).strip()
    title_en = _clean_title_en(srt, title_en, video)
    duration = video_duration(video, cues)
    if chat is None:
        from core.calibrate.ai import calib_ai_chat
        chat = calib_ai_chat
    prompt = _prompt(_sample(cues), title_en, game, streamer, duration)
    log(f"[发布素材] 时长 {hms(duration)}，{len(cues)} cue，游戏={game or '?'} 主播={streamer or '?'}")
    try:
        raw = chat(prompt, system=_SYSTEM, max_tokens=8192)
    except Exception as e:
        return {"ok": False, "error": f"AI 调用失败：{e}"}
    obj = _parse_json(raw)
    if not obj:
        return {"ok": False, "error": "AI 未返回合法 JSON"}
    mat = _enforce(obj, duration, game, streamer)
    base_name = os.path.splitext(os.path.basename(srt))[0]
    srt_dir = os.path.split(srt)[0]
    folder = os.path.realpath(out) if out else os.path.join(srt_dir, base_name + "_素材")
    write_material(folder, mat, game)
    log(f"[发布素材] 已写入 {os.path.realpath(folder)}（标题/10tag/10段）")
    return {"ok": True, "folder": os.path.realpath(folder), **mat}