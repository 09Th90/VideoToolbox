# -*- coding: utf-8 -*-
# @version 2.2.5
"""视频工具箱 · 版本索引（「全版本通用」的地基）。

====================================================================
为什么需要它
====================================================================
`manifest.json` 是**单版本**的：它只描述某一个版本有哪些包、每个文件
是什么 sha256。在线安装形态下它是**原地覆盖**的——固定 tag `repo-latest`
上永远只有一份 `manifest.json`，每次发版被覆盖。于是：

  · 只能装「当前最新」，装不了历史版本；
  · 旧资产会被 `cleanup_old_assets --keep N` 清掉，即便记得版本号也下不到；
  · 回滚（1.20.1 → 1.19.0）没有可依据的清单。

「全版本通用」要求三件事，单份 manifest 一件都兜不住：

  1. 任意已发布版本都能被**列出来**；
  2. 任意版本都能被**精确定位**到它自己的清单与资产；
  3. 任意方向的切换（升级 / 降级 / 重装）都走**同一套**增量逻辑。

`index.json` 就是为此存在：一个**全版本目录**，每条记录指向该版本自己
的 manifest 文件（不再互相覆盖），并记录版本状态与兼容下限。

====================================================================
发布形态（与 build_online_release.py 约定）
====================================================================
    index.json                ← 全版本目录（小，每次发版就地更新）
    manifest.json             ← 最新版别名（= 最新那份 manifest-<v>.json 的副本）
    manifest-1.20.0.json      ← 每版本留档，**永不覆盖**
    manifest-1.19.0.json
    v1.20.0-app.zip[.001…]    ← 资产按版本命名，互不覆盖

index.json 结构：:

    {
      "schema": 1,
      "app": "视频工具箱",
      "updated": "2026-10-12 17:00:00",
      "base_url": "https://…/releases/download/repo-latest/",
      "channels": {"latest": "1.20.0", "stable": "1.19.0"},
      "versions": [
        {"version": "1.20.0",
         "manifest": "manifest-1.20.0.json",
         "released": "2026-10-12 16:00:00",
         "notes": "…",
         "state": "stable",           # stable|prerelease|yanked|archived
         "total_size": 105000000,
         "pkgs": ["app", "code", "docs", "tools"],
         "min_updater": "1.20.0"}     # 装它所需的更新器最低版本
      ]
    }

====================================================================
版本选择器
====================================================================
`resolve()` 接受这些写法（空串等价于 "latest"）：

    latest / newest / ""      → channels.latest（找不到则取最高版本）
    stable                    → channels.stable
    1.20.0                    → 精确匹配
    >=1.19.0  >1.19  <1.21    → 比较运算（缺位补 0）
    ^1.20.0                   → >=1.20.0 且 <2.0.0（同主版本）
    ~1.20.0                   → >=1.20.0 且 <1.21.0（同次版本）
    1.20                      → 视为 ~1.20（该次版本下最高的那个）

范围选择器取**满足条件的最高版本**——这是安装器该有的语义：用户说
"给我 1.20 系的"，就是想要 1.20 系里最新的那个。

====================================================================
与「体积限制」的关系
====================================================================
本模块不下载任何东西，只做**定位**。但它让「整体无体积上限」真正成立：
每个版本的资产都留在 Release 上（index 记录它们），版本历史可以任意长，
而每次安装 / 切换仍只下**差量**——下载量不随版本总数增长。

====================================================================
离线自测
====================================================================
`load_index()` 同时接受 http(s) URL、本地路径与 `file://` URL，
与 `vt_update_core.load_manifest()` 口径一致——这样整套流程（列版本、
选版本、取清单、下资产）都能在**无网络**环境下用本地目录跑通。
"""

import json
import os
import re
import urllib.parse
import urllib.request

#: index.json 的 schema 版本号
INDEX_SCHEMA = 1
#: 远端索引文件名（位于 base_url 下）
INDEX_NAME = "index.json"
#: 每版本清单的命名模板（版本号里的点保留，便于人肉辨认）
MANIFEST_TEMPLATE = "manifest-%s.json"

#: 默认可见的版本状态：这两个才能被自动选中
STATE_VISIBLE = ("stable", "prerelease")
#: 需要显式 --allow-hidden 才会出现的状态
#:   yanked   发版后发现严重问题，撤回但不删资产（保留可追溯）
#:   archived 太老，资产可能已离线
STATE_HIDDEN = ("yanked", "archived")
ALL_STATES = STATE_VISIBLE + STATE_HIDDEN


class VIndexError(RuntimeError):
    """索引本身的问题（取不到、schema 不对、缺字段…）。UI 直接显示其文本。"""


class VersionError(ValueError):
    """版本号或选择器无法解析。"""


# ------------------------------------------------------------------ 版本号


#: 宽松 semver：允许 `v` 前缀、允许只写到主/次版本、允许预发布后缀。
#: 例：1.20.0 / v1.20 / 1.20.0-beta.1 / 2.0
#: ⚠ 第 4 个数值段与 `+` 后元数据都会落在预发布组（`[-.+]` 触发）：
#:   因此 "1.2.3.4" 是"1.2.3 的预发布"（< 1.2.3）、"1.2.3+build" 同。
#:   这是刻意取舍——四段号本就非 semver 标准，宁可降级为预发布也不算相等。
_VER_RE = re.compile(
    r"^v?(\d+)(?:\.(\d+))?(?:\.(\d+))?(?:[-.+]([0-9A-Za-z][0-9A-Za-z.\-]*))?$")


def parse_version(text):
    """把版本字符串解析成 `((主,次,修), 预发布元组)`。

    缺位补 0：`"1.20"` → `((1, 20, 0), ())`。
    预发布串按 `.`/`-` 切段；纯数字段按数值排，其余按字符串排
    （`beta.2` < `beta.10`，符合直觉）。

    解析不了抛 `VersionError`——**不静默降级为 (0,0,0)**：版本号错了
    就该当场炸，而不是被当成"最低版本"混进排序结果里。
    """
    s = (text or "").strip()
    m = _VER_RE.match(s)
    if not m:
        raise VersionError("无法解析版本号：%r" % text)
    nums = tuple(int(m.group(i) or 0) for i in (1, 2, 3))
    pre_src = m.group(4) or ""
    pre = ()
    if pre_src:
        parts = []
        for seg in re.split(r"[.\-]", pre_src):
            parts.append((0, int(seg), "") if seg.isdigit() else (1, 0, seg))
        pre = tuple(parts)
    return nums, pre


def cmp_version(a, b):
    """比较两个版本字符串，返回 -1 / 0 / 1。

    预发布**低于**同号的正式版：`1.20.0-beta.1 < 1.20.0`。
    """
    na, pa = parse_version(a)
    nb, pb = parse_version(b)
    if na != nb:
        return -1 if na < nb else 1
    # 有预发布的更小；都有则逐段比
    if not pa and not pb:
        return 0
    if not pa:
        return 1
    if not pb:
        return -1
    for x, y in zip(pa, pb):
        if x != y:
            return -1 if x < y else 1
    return -1 if len(pa) < len(pb) else (1 if len(pa) > len(pb) else 0)


def vkey(text):
    """排序键，供 `sorted(..., key=vkey)` 用。

    ⚠ 调用方一律 `reverse=True`（新的在前），所以**键越大越靠前**：
    正式版的第二个分量必须**大于**预发布，否则同号预发布会排到正式版
    前面（2026-10-13 审查实测：旧代码 0=正式/1=预发布 + reverse=True
    让 2.0.0-beta.1 排在 2.0.0 前，stable 通道被预发布污染）。
    解析失败 → (0,0,0) 且视同预发布，排到最后。
    """
    try:
        nums, pre = parse_version(text)
    except VersionError:
        return ((0, 0, 0), 0, ())
    # 第二个分量：1=正式版，0=预发布 —— 配合 reverse=True 保证正式版在前
    return (nums, 1 if not pre else 0, pre)


def version_eq(a, b):
    return cmp_version(a, b) == 0


# ------------------------------------------------------------------ 选择器


#: 前缀运算符 + 版本体。^ / ~ 各自展开成一对边界（见 match_selector）。
_SEL_RE = re.compile(r"^\s*(>=|<=|==|!=|>|<|\^|~|=)?\s*(\S*)\s*$")


def _next_major(v):
    nums, _ = parse_version(v)
    return "%d.0.0" % (nums[0] + 1)


def _next_minor(v):
    nums, _ = parse_version(v)
    return "%d.%d.0" % (nums[0], nums[1] + 1)


def match_selector(ver, selector):
    """判断版本 `ver` 是否满足选择器 `selector`。

    支持的写法见模块 docstring。比较一律走 `cmp_version`，
    所以 `1.20` 与 `1.20.0` 等价。
    """
    sel = (selector or "").strip()
    if not sel:
        return True                      # 空选择器 = 不设限
    m = _SEL_RE.match(sel)
    if not m:
        raise VersionError("无法解析版本选择器：%r" % selector)
    op, body = m.group(1) or "", m.group(2) or ""
    if not body:
        raise VersionError("版本选择器缺版本号：%r" % selector)

    if op in ("^", "~"):
        lo = body
        nums, _pre = parse_version(body)
        # 段数以 _VER_RE 实际写到的数值位计——不能用十进制段计数：
        # "v1".isdigit() 为 False，v 前缀那段会被漏掉（v1.20 曾被误判成 1 段）
        m = _VER_RE.match(body.strip())
        has_minor = bool(m and m.group(2))
        if op == "^":
            # ^0.x 递进次版本（npm semver：^0.2 → <0.3.0），其余递进主版本
            hi = _next_minor(body) if nums[0] == 0 else _next_major(body)
        else:
            # ~ 只写到主版本时递进主版本（~1 ≡ >=1.0.0 <2.0.0，与裸写 "1" 一致）；
            # 写了次版本才递进修版本（~1.20 → <1.21.0）
            hi = _next_major(body) if not has_minor else _next_minor(body)
        return cmp_version(ver, lo) >= 0 and cmp_version(ver, hi) < 0
    if op in ("=", "=="):
        return cmp_version(ver, body) == 0
    if op == "!=":
        return cmp_version(ver, body) != 0
    if op == ">=":
        return cmp_version(ver, body) >= 0
    if op == "<=":
        return cmp_version(ver, body) <= 0
    if op == ">":
        return cmp_version(ver, body) > 0
    if op == "<":
        return cmp_version(ver, body) < 0
    # 无运算符：位数不足视为「该层里最高的」——上界按**写到的段数**递进：
    #   1      → ^1     （[1, 2.0)，整个 1.x）
    #   1.20   → ~1.20  （[1.20, 1.21)，整个 1.20.x）
    #   1.20.0 → 精确匹配
    # ⚠ 曾经一律按 ~ 处理，一位写法 "1" 被误判成只匹配 1.0.x。
    nums, _pre = parse_version(body)
    m = _VER_RE.match(body.strip())
    segs = sum(1 for i in (1, 2, 3) if m and m.group(i))
    if segs >= 3:
        return cmp_version(ver, body) == 0
    hi = (_next_minor("%d.%d" % (nums[0], nums[1])) if segs >= 2
          else _next_major("%d" % nums[0]))
    return cmp_version(ver, body) >= 0 and cmp_version(ver, hi) < 0


# ------------------------------------------------------------------ 索引读写


def _read_bytes(src):
    """按 src 的形态读原始字节：http(s) 走网络，其余当本地路径。"""
    if src.startswith("http://") or src.startswith("https://"):
        req = urllib.request.Request(src, headers={
            "User-Agent": "VideoToolbox-updater",
            "Accept": "application/json",
        })
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001
            raise VIndexError("取版本索引失败：%s\n（%s）" % (e, src))
    if src.startswith("file://"):
        # ⚠ 不能简单砍掉 "file://" —— Windows 上是 `file:///C:/...`，
        #   砍完剩 `/C:/...`，多一个前导斜杠就找不到文件。
        p = urllib.request.url2pathname(urllib.parse.urlparse(src).path)
    else:
        p = src
    if not os.path.isfile(p):
        raise VIndexError("版本索引不存在：%s" % p)
    try:
        return open(p, "rb").read()
    except OSError as e:
        raise VIndexError("读版本索引失败：%s（%s）" % (e, p))


def normalize_entry(e, where="versions[]"):
    """补齐一条版本记录的缺省字段，并校验版本号合法。原地修改并返回。

    ⚠ 加载**与**构造都走这里（load_index 与 upsert_version 共用）：
    早期只在 load 时补 manifest，导致发布侧刚构造完、还没落盘的索引
    缺这个字段，save→load 才自洽——自测时表现为 KeyError。
    """
    if not isinstance(e, dict) or not e.get("version"):
        raise VIndexError("%s 缺 version 字段" % where)
    try:
        parse_version(e["version"])
    except VersionError as ex:
        raise VIndexError("%s 版本号非法：%s" % (where, ex))
    if not e.get("manifest"):
        # 没写 manifest 就按模板推——早期版本可能只写了 version
        e["manifest"] = MANIFEST_TEMPLATE % e["version"]
    e.setdefault("state", "stable")
    if e["state"] not in ALL_STATES:
        # 拼错 state（如 "Stable"）会让版本既不可见也不可说，只能手改
        # index.json——入口就拦下，与 state 白名单同一处生效
        raise VIndexError("%s state 非法：%r（可用：%s）"
                          % (where, e["state"], "、".join(ALL_STATES)))
    e.setdefault("notes", "")
    e.setdefault("released", "")
    e.setdefault("pkgs", [])
    e.setdefault("total_size", 0)
    return e


def parse_index(raw):
    """从原始字节解析并校验 index.json。

    与 `load_index()` 分开是为了**发布侧**：它已经把远端 index.json
    的字节拿到手了，不该为了解析再发一次请求。
    """
    try:
        idx = json.loads(raw.decode("utf-8"))
    except Exception as e:  # noqa: BLE001
        raise VIndexError("版本索引不是合法 JSON：%s" % e)
    if not isinstance(idx, dict):
        raise VIndexError("版本索引顶层必须是对象")
    if idx.get("schema") != INDEX_SCHEMA:
        raise VIndexError("版本索引 schema 不受支持：%r（本程序认 %d）"
                          % (idx.get("schema"), INDEX_SCHEMA))
    vers = idx.get("versions")
    if not isinstance(vers, list) or not vers:
        raise VIndexError("版本索引里没有 versions 列表")
    for i, e in enumerate(vers):
        normalize_entry(e, "versions[%d]" % i)
    idx.setdefault("base_url", "")
    idx.setdefault("channels", {})
    # 版本列表按版本号降序：调用方拿到的就是"新的在前"
    idx["versions"] = sorted(vers, key=lambda e: vkey(e["version"]),
                             reverse=True)
    return idx


def load_index(src, fetch=None):
    """读并校验 index.json。src 可为 http(s) URL、本地路径或 file:// URL。

    返回的 dict 保证含：schema / versions(list) / channels(dict) /
    base_url(str)，且 versions 已按版本号**降序**排好、每条记录字段齐整。
    **不做**网络请求之外的任何 IO，也不下载任何资产。

    `fetch` 可注入自定义取字节函数（调用方传入带镜像回退链的实现，
    让 index.json 与 manifest / 资产走同一条容错路径）；默认走
    内置的 `_read_bytes`（裸 urllib，发布侧与离线自测够用）。
    """
    return parse_index((fetch or _read_bytes)(src))


def save_index(idx, path):
    """写 index.json（发布侧与自测共用）。返回路径。"""
    p = str(path)
    d = os.path.dirname(os.path.abspath(p))
    if d:
        os.makedirs(d, exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(idx, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, p)
    return p


def new_index(app="视频工具箱", base_url=""):
    """造一个空索引（发布侧首次发版 / 自测用）。"""
    return {"schema": INDEX_SCHEMA, "app": app,
            "updated": "", "base_url": base_url,
            "channels": {}, "versions": []}


def upsert_version(idx, entry):
    """把一条版本记录并入索引（同版本覆盖，其余保留）。返回 idx。

    同时维护 `channels.latest`：只有当并入的版本**高于**现有 latest
    时才顶替——降级发版（回滚发布）不该把 latest 拽回去，除非显式改。
    """
    ver = entry.get("version") or ""
    # 归一化（补 manifest 等缺省字段）+ 校验版本号：提前炸，别让脏数据进索引
    normalize_entry(entry, "version %r" % ver)
    vers = [e for e in idx.get("versions", [])
            if not _same_version(e.get("version"), ver)]
    vers.append(dict(entry))
    vers.sort(key=lambda e: vkey(e["version"]), reverse=True)
    idx["versions"] = vers

    ch = idx.setdefault("channels", {})
    cur = ch.get("latest") or ""
    if not cur or cmp_version(ver, cur) > 0:
        ch["latest"] = ver
    # stable = latest 之下最高的 stable 态版本
    stables = [e["version"] for e in vers
               if e.get("state") == "stable"]
    if stables:
        ch["stable"] = stables[0]
    return idx


# ------------------------------------------------------------------ 版本选择


def visible_versions(idx, allow_hidden=False):
    """按版本号降序返回**可见**的版本记录列表。"""
    keep = ALL_STATES if allow_hidden else STATE_VISIBLE
    return [e for e in idx.get("versions", []) if e.get("state") in keep]


def _ver_key(e):
    return e.get("version") or ""


def _same_version(a, b):
    """版本号相等（吃 v 前缀/缺位：v1.20.0 == 1.20 == 1.20.0）。

    字符串精确比较会把 "v1.20.0" 与 "1.20.0" 当成两个版本，
    upsert 不去重、find_version 找不到——一律走 cmp_version。
    """
    try:
        return cmp_version(a, b) == 0
    except VersionError:
        return (a or "") == (b or "")


def find_version(idx, version):
    """按精确版本号找记录；找不到返回 None（不抛）。"""
    for e in idx.get("versions", []):
        if _same_version(e.get("version"), version):
            return e
    return None


def resolve(idx, want="latest", allow_hidden=False, log=None):
    """把用户写的版本诉求解析成一条版本记录。

    `want` 的写法见模块 docstring。范围类选择器取满足条件里**最高**的
    那个版本。找不到抛 `VIndexError`（带可用版本列表，便于用户改口）。
    """
    def say(msg):
        if log:
            log(msg)

    vers = visible_versions(idx, allow_hidden=allow_hidden)
    if not vers:
        raise VIndexError("索引里没有可用版本（可能被全部标记为撤回）")
    want = (want or "latest").strip()

    low = want.lower()
    if low in ("latest", "newest", ""):
        picked = idx.get("channels", {}).get("latest") or ""
        e = find_version(idx, picked) if picked else None
        if e is None or (not allow_hidden and e.get("state") in STATE_HIDDEN):
            # latest 指向的版本不可见 → 退化为「可见里最高的」
            e = vers[0]
        say("通道 latest → v%s" % e["version"])
        return e
    if low == "stable":
        picked = idx.get("channels", {}).get("stable") or ""
        e = find_version(idx, picked) if picked else None
        if e is None or (not allow_hidden and e.get("state") in STATE_HIDDEN):
            # stable 指向的版本被撤回/归档 → 退到可见里最高的 stable
            stables = [x for x in vers if x.get("state") == "stable"]
            if not stables:
                raise VIndexError("索引里没有 stable 版本")
            e = stables[0]
        say("通道 stable → v%s" % e["version"])
        return e

    # VersionError（选择器非法，如 ">abc"）也要归一成 VIndexError：
    # VIndexError 的定位是"UI 直接显示其文本"，VersionError 漏出去
    # 会逃过调用方的 except VIndexError，变成未处理异常
    try:
        hits = [e for e in vers if match_selector(e["version"], want)]
    except VersionError as ex:
        raise VIndexError("版本选择器 %r 无法解析：%s" % (want, ex))
    if not hits:
        raise VIndexError(
            "没有版本满足 %r。可用版本：%s"
            % (want, "、".join(e["version"] for e in vers[:12])
               + ("…" if len(vers) > 12 else "")))
    # visible_versions 已按降序排好，取第一个即"满足条件里最高的"
    e = hits[0]
    if len(hits) > 1:
        say("选择器 %r 命中 %d 个版本，取最高的 v%s"
            % (want, len(hits), e["version"]))
    return e


def manifest_url(idx, entry, base_url=None):
    """取某版本 manifest 的完整 URL。

    base_url 优先用显式传入的（覆盖用），否则用索引里记的；
    两者都没有就抛错——宁可失败也不猜地址。
    """
    base = (base_url or idx.get("base_url") or "").rstrip("/")
    if not base:
        raise VIndexError("没有 base_url，无法定位 v%s 的清单"
                          % entry.get("version"))
    name = entry.get("manifest") or (MANIFEST_TEMPLATE % entry["version"])
    return base + "/" + name


def index_url(base_url):
    """由 base_url 拼出 index.json 的地址。"""
    b = (base_url or "").rstrip("/")
    if not b:
        raise VIndexError("没有 base_url，无法定位版本索引")
    return b + "/" + INDEX_NAME


# ------------------------------------------------------------------ 兼容性


def updater_ok(entry, self_version):
    """当前更新器版本是否满足目标版本的 `min_updater` 要求。

    不满足意味着：新版用了老安装器不认的清单字段（比如将来 schema 3），
    硬装会静默漏文件。此处的正确处置是**先自我更新再重跑**，
    `vt_update_core.ensure_updater()` 就是干这个的。
    """
    need = (entry or {}).get("min_updater") or ""
    if not need:
        return True
    try:
        return cmp_version(self_version or "0.0.0", need) >= 0
    except VersionError:
        # 自身版本号都解析不出来 —— 保守判不满足
        return False


def summarize(idx, limit=12, allow_hidden=False):
    """把索引渲染成多行文本（控制台 / 日志用）。"""
    lines = ["%s 可用版本（索引更新于 %s）："
             % (idx.get("app") or "应用", idx.get("updated") or "?")]
    for e in visible_versions(idx, allow_hidden=allow_hidden)[:limit]:
        mark = "·"
        st = e.get("state")
        if st == "stable":
            mark = "*"
        elif st == "prerelease":
            mark = "+"
        elif st in STATE_HIDDEN:
            mark = "!"
        lines.append("  %s v%-10s %-12s %s"
                     % (mark, e.get("version"), st or "",
                        (e.get("notes") or "")[:46]))
    lines.append("  （* 正式版  + 预发布  ! 撤回/归档）")
    return "\n".join(lines)
