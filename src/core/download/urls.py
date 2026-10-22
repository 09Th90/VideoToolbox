# -*- coding: utf-8 -*-
# @version 2.5.2
"""链接识别与提取（.url/txt/分享文案 → URL；yt-dlp 字幕语言参数）（v2.3.1 拆分工程 · 自 video_toolbox.py 原样搬入）。

core/download 域：yt-dlp 全链 / cookie / NPE / 媒体合并；依赖规则见 core/__init__.py。
"""
import os
import re

from core.shared.ai import ai_mod
from core.shared.textio import read_text_any

DEFAULT_INPUT_DIR = r"D:\剪辑"
DURATION_THRESHOLD = 1.0
URL_RE = re.compile(r'https?://[^\s"<>\)\]]+')
# ========== 功能 1：视频下载 ==========
def extract_url(arg):
    """从 .url 快捷方式 / 文本文件 / 原始字符串中提取第一个 http 链接"""
    if os.path.isfile(arg):
        try:
            text = read_text_any(arg)
        except Exception:
            return None
        m = URL_RE.search(text)
        return m.group(0) if m else None
    m = URL_RE.search(arg)
    return m.group(0) if m else None


# ========== 网页链接识别（「任务创建」输入框用） ==========
# 用户往输入框里贴的东西远不止一个光秃秃的 URL，实际见过这几种：
#   1) https://www.bilibili.com/video/BVxxxx        —— 标准形态
#   2) 「【标题】  https://b23.tv/xxxx  复制本条信息…」—— 分享文案整段
#   3) www.bilibili.com/video/BVxxxx              —— 手打漏了协议头
#   4) 「...」『...』<...> 包裹的链接              —— 带引号/尖括号
#   5) 结尾粘上了中文标点（，。！）或英文标点        —— URL_RE 不吃这些
# 原实现只认 `scheme in (http, https)`，把 2/3/4/5 全判成「不是 URL」，
# 用户看到的就是「请输入音视频文件路径或URL」——链接明明就在框里。
#: 结尾要剥掉的标点（中英文都收）。**只剥结尾**，链接中间的标点不动
#: （YouTube 的 `?v=` 后面可能跟 `&list=` 之类，剥中间会截断）。
_URL_TRAIL_PUNCT = ".,;:!?、，。；：！？…～~'\"’”」』)】》〉>"

#: **绝不可能是顶级域**的末段——它们是本程序支持的媒体/字幕文件扩展名。
#: 光靠「末段纯字母」挡不住 `x.mkv` / `clip.avi`（mkv、avi 全是字母），
#: 补成 `https://x.mkv` 会把一个文件名当网址跳去下载页。
#: 双向约定：本程序 VIDEO_EXTS / AUDIO_EXTS / SUBTITLE_EXTS 里有的，
#: 这里就得有；改那三处时记得同步（否则新增格式会从这个洞漏出去）。
_NOT_A_TLD = {
    # 视频
    "mp4", "mkv", "avi", "mov", "flv", "wmv", "webm", "m4v", "mpg",
    "mpeg", "rmvb", "ts", "m2ts", "mts", "vob", "ogv", "asf", "divx",
    "mxf", "three", "ogm", "rm", "vtt",
    # 音频
    "mp3", "m4a", "wav", "aac", "flac", "ogg", "oga", "opus", "wma",
    "aiff", "aif", "amr", "ape", "mka",
    # 字幕
    "srt", "ass", "ssa", "vtt", "sub", "smi", "sbv", "lrc",
}


def _strip_url_punct(url):
    """剥掉链接结尾的标点/包裹符；剥到不再变化为止（连续多个时也干净）。"""
    out = url
    while out and out[-1] in _URL_TRAIL_PUNCT:
        out = out[:-1]
    return out


def _prepend_scheme_if_bare(host_path):
    """裸域名补协议头。

    只在「像域名」时才补——`C:\\视频\\a.mp4` 里有 `\\`、不会命中；
    `BV1xx411c7mD` 这种纯 ID 也不会命中（要求至少一个点）。
    ⚠ 末段必须 **≥2 个字符**且字母开头：`a.b` / `1.5` 这类版本号、句号
    分句不是网址，补出 `https://a.b` 只会把用户带到一个必然 404 的地址。
    """
    body = host_path.strip()
    if not body or "://" in body:
        return body
    # 反斜杠（Windows 路径）一律不当作裸域名
    if "\\" in body:
        return body
    host = body.split("/", 1)[0].split("?", 1)[0].split("#", 1)[0]
    # 去掉端口再判末段（`192.168.1.1:8080/x` 的末段是 "1:8080"）
    host_no_port = host.rsplit(":", 1)[0] if host.count(":") == 1 else host
    if "." not in host_no_port:
        return body
    # 末段得像个域名段（≥2 字符、纯字母、且**不是媒体文件扩展名**）
    tail = host_no_port.rsplit(".", 1)[-1].lower()
    # ⚠ 三重约束，缺一个就会把本地文件名当网址（实测依次踩到）：
    #   · ≥2 字符      —— `a.b` / `1.5` 这类版本号、句号分句；
    #   · 纯字母      —— `a.mp4` 的 "mp4" 含数字；
    #   · 不在 _NOT_A_TLD —— `x.mkv` / `clip.avi` 全是字母，只能靠黑名单。
    # 为什么宁严勿松：TaskCreationInterface.process() 里 os.path.isfile
    # 已经先判过，能走到这里的都是**不存在的路径**——用户看到的是"我明明
    # 输的是文件，怎么跳到下载页去了"。漏判 punycode 顶级域（xn--p1ai）
    # 用户手动补个 https:// 就行；误判则是一次莫名其妙的跳转。
    if len(tail) < 2 or not tail.isalpha() or tail in _NOT_A_TLD:
        return body
    return "https://" + body


def extract_web_url(text):
    """从任意文本里提取**一个**网页链接；没有则返回 ``""``。

    与 :func:`extract_url` 的分工：那个只做「http(s):// 正则捞第一个」，
    这个负责「用户到底想表达什么」，覆盖分享文案整段 / 漏协议头 / 带引号
    / 尾部标点。纯函数，不碰 IO，自检可直接断言。

    返回值已归一（剥尾部标点、裸域名补 ``https://``），可直接喂给 yt-dlp。
    """
    if not text:
        return ""
    raw = str(text).strip()
    if not raw:
        return ""

    # ① 整段就是链接（含漏协议头的裸域名）——最常见，优先走这条，
    #    避免整段分享文案被当成 URL 的一部分。
    #    ⚠ 必须**不含空白**：否则「看看这个 www.bilibili.com/... 不错」整段
    #    会被当成一个超长 host，补出 `https://看看这个 www.bilibili.com/...`。
    whole = _strip_url_punct(raw.strip(" \t\"'“”‘’<>《》【】()（）"))
    if whole and not any(c.isspace() for c in whole):
        cand = _prepend_scheme_if_bare(whole)
        if cand.lower().startswith(("http://", "https://")):
            rest = cand.split("://", 1)[1]
            # 光有协议头不够，还得像个网址（含点域名或 localhost）
            host = rest.split("/", 1)[0]
            if host and ("." in host or host.lower().startswith("localhost")):
                return _strip_url_punct(cand)

    # ② 分享文案整段：从里面正则捞一个 http(s):// 开头的
    m = URL_RE.search(raw)
    if m:
        got = _strip_url_punct(m.group(0))
        if got.lower().startswith(("http://", "https://")):
            return got

    # ③ 整段里嵌着裸域名（如「看看这个 www.bilibili.com/video/BVxx 不错」）
    #    三处约束缺一不可，都是实测踩出来的：
    #      · 前瞻 `(?<![\w./\\-])`：排除反斜杠，否则 `C:\v\a.mp4` 里的
    #        `a.mp4` 会被当成裸域名（`\` 不在原字符类里）。
    #      · 域名后必须紧跟分隔符或结束（`(?=[/?#\s]|$)` 等价地要求），
    #        否则 `a.mp4` 会被截成 `a.mp` 当域名——TLD 后若还跟着**任何**
    #        字母数字，就说明我们只啃下了域名的一部分。
    #      · TLD 至少 2 字符且字母开头（由 `_prepend_scheme_if_bare` 保证）。
    m2 = re.search(
        r"(?<![\w./\\-])((?:[\w-]+\.)+[a-zA-Z]{2,})(?![0-9A-Za-z._-])"
        r"([/?#]\S*)?", raw)
    if m2:
        got = _strip_url_punct(m2.group(1) + (m2.group(2) or ""))
        cand = _prepend_scheme_if_bare(got)
        if cand.lower().startswith("https://"):
            return _strip_url_punct(cand)

    return ""


#: yt-dlp 下载分片大小。YouTube 自 2026-09 起对 videoplayback 直链**强制要求
#: Range 请求**，yt-dlp 默认的整体 GET 一律 403 —— 表现为"下载几秒/几十 MB 后
#: 失败"，看着像风控其实是缺 Range。下载页与流水线共用这一个值。
def ytdlp_sub_langs(lang_code, default=""):
    """语言代码 → yt-dlp --sub-langs 参数（下载字幕跟随标题语言用）。"""
    try:
        return ai_mod().ytdlp_sub_langs(lang_code, default)
    except Exception:
        return default


__all__ = [
    "DEFAULT_INPUT_DIR",
    "DURATION_THRESHOLD",
    "URL_RE",
    "extract_url",
    "extract_web_url",
    "ytdlp_sub_langs",
    "_URL_TRAIL_PUNCT",
    "_NOT_A_TLD",
]
