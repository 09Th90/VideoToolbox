# -*- coding: utf-8 -*-
# @version 2.4.1
"""在线引导安装器 · 核心逻辑（无 UI，可单测）。

====================================================================
为什么要自研、而不是继续用 Qt Installer Framework（IFW）
====================================================================
IFW 的在线仓库有**结构性**的目录要求：取归档的 URL 是
`<仓库基址>/<组件名>/<归档名>`，天然比 `Updates.xml` 多一层目录。
而 GitHub Releases 的资产是**平铺**的（没有子目录），实测：

    .../releases/download/<tag>/Updates.xml            → 302 → 200   ✅
    .../releases/download/<tag>/<组件名>/<归档>          → 404        ❌

试过「用带斜杠的 tag 冒充目录」（`.../download/X/comp/asset` 单测能过），
但 `<X>` 与 `<X>/comp` 在 git 里是 **D/F 冲突**（先建子再建父 → HTTP 500），
两者不能共存 —— 而 IFW 恰好同时需要这两层。所以 Releases 装不下 IFW 仓库。

于是改为：**自己下载、自己解压**。资产完全平铺，直接吃满 GitHub Releases 的
**2GB/资产**上限，`gh-pages` 那条 **100 MiB 单文件硬限**就此消失。

====================================================================
发布形态（与 build_online_release.py 约定）
====================================================================
固定 tag 的 Release（默认 `repo-latest`）下挂**平铺**资产：

    manifest.json                  ← 版本 + 资产清单 + 文件级清单（小）
    v1.20.0-app.zip                ← 组件包（大，超限时自动分卷 .001/.002）
    v1.20.0-code.zip
    视频工具箱_在线安装_v1.20.0.exe  ← 更新器自身（updater 条目，不进 assets）

manifest 结构：

    schema 1（旧版，仍兼容）：
        {"schema": 1, "version": "1.18.0", "base_url": "…",
         "assets": [{"name": "base", "file": "v1.18.0-base.zip",
                     "size": …, "sha256": "…", "target": ""}]}

    schema 2（v1.20.0 起，新增三样东西）：
        · files   —— 完整安装的文件级清单 {相对路径: {size, sha256, pkg}}
        · parts   —— 资产超限时的分卷名列表（随 asset 给）
        · updater —— 更新器自身条目 {file, size, sha256}
        · remove  —— 本次应删除的路径列表（可选）

`files` 是**增量更新**的地基：客户端拿它和本地 `vt_installed.json`
（或现场扫描）比对，只下载 sha256 不同的文件所在的包——任何旧版本
都能对齐到最新版，这就是「全版本通用」。没有 files 的旧清单退化为
全量下载（行为与 schema 1 完全一致）。

====================================================================
体积限制的解法（对应设计目标）
====================================================================
· **单文件无上限**：zip64 本身支持到 16EB；发布侧把超 VOLUME_MAX
  （默认 1.5GB，留足 GitHub 2GB 余量）的 zip 按字节切卷，每卷是一个
  普通下载任务，客户端按序拼接还原（zip 可按字节切分后原样拼回）。
· **总量无上限**：增量 diff 决定下载量，版本历史再长也只下差量；
  单次下载的暂存空间按「本次下载量」计，不随版本总数增长。
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vt_dl  # noqa: E402  自研下载引擎（多线程/续传/镜像回退）
import vt_version_index as vindex  # noqa: E402  全版本目录（index.json）

#: 默认 manifest 地址（固定 tag，随版本原地更新）——**最新版别名**
DEFAULT_MANIFEST_URL = ("https://github.com/09Th90/VideoToolbox/releases/"
                        "download/repo-latest/manifest.json")
#: 默认版本索引地址（全版本目录；装任意版本/回滚靠它定位）
DEFAULT_INDEX_URL = ("https://github.com/09Th90/VideoToolbox/releases/"
                     "download/repo-latest/index.json")
#: 默认安装目录（与 视频工具箱.iss 的 DefaultDirName 保持一致）
#: ⚠ **D 盘优先**是硬性产品口径：主程序加运行时近 GB，装 C 盘容易把系统盘
#:   撑满，且重装系统时会被一起抹掉。D 盘不可用时才由 pick_default_dir()
#:   退到其它盘——那是容错，不是默认。
DEFAULT_DIR = r"D:\VideoToolbox"
#: 默认目录下的应用子目录名（拼在盘符后）
DEFAULT_DIR_NAME = "VideoToolbox"
#: D 盘不可用时依次试的盘符（D 已在 DEFAULT_DIR 里，这里只列兜底顺序）
FALLBACK_DRIVES = ("D:", "E:", "F:", "C:")
#: 本更新器自身的版本（用于比对目标版本的 min_updater 要求）
#: ⚠ 必须与 src/video_toolbox_qt.py 的 VERSION 一致：它是**硬门槛**——
#: 发布侧若给 manifest 写了 min_updater="2.0.0"，而随包的更新器仍自称
#: 旧版，装新版本会被直接拒（updater_ok 返回 False）。
#: v2.2.5 起已纳入 scripts/dev/apply_version.py 的 TARGETS，改号自动同步
#: （此前是手工项，正是这类漂移的来源）。
SELF_VERSION = "2.4.1"
#: 安装目录里的本地清单文件名（记录本次安装的文件级 sha256）
INSTALLED_NAME = "vt_installed.json"
#: 下载分块（sha256 等本地 IO 用；网络分块在 vt_dl 里）
CHUNK = 1 << 20
#: 落地时的临时后缀（重命名技巧的中间态）
OLD_SUFFIX = ".vtold"


class UpdateError(RuntimeError):
    """可预期的失败（网络、校验不符、磁盘、权限…），UI 直接显示其文本。"""


#: 取消异常与引擎同名——UI 只需捕这一个类型（vt_dl.Canceled 即它本身）
Canceled = vt_dl.Canceled


# ------------------------------------------------------------------ 工具


def sha256_file(path, progress=None):
    """算文件 sha256；progress 为 (已读, 总数) 回调（可为 None）。"""
    total = os.path.getsize(path)
    h = hashlib.sha256()
    done = 0
    with open(path, "rb") as fh:
        while True:
            b = fh.read(CHUNK)
            if not b:
                break
            h.update(b)
            done += len(b)
            if progress:
                progress(done, total)
    return h.hexdigest()


def human(n):
    """字节数转人类可读。"""
    n = float(n)
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024 or u == "GB":
            return "%.1f %s" % (n, u)
        n /= 1024


def ver_tuple(v):
    """'1.20.0' → (1, 20, 0)；解析失败按 (0,0,0)。

    ⚠ 2026-10-13 审查修复：旧实现 `split(".")[:3]` 有两个坑：
      · "1.20" → (1, 20) 与 (1, 20, 0) 比较时更小 → 同版本被判成降级；
      · "2.1.0-beta.1" → int("0-beta") 炸 → (0,0,0)，预发布恒最低。
    改为委托 vindex.parse_version（支持缺位补 0 与预发布的单一真相源），
    不足三位补 0。调用方（vt_update_check 的升降级判断）随之正确。
    """
    try:
        nums = vindex.parse_version(str(v).strip())[0]
        return nums + (0,) * (3 - len(nums))
    except Exception:  # noqa: BLE001
        return (0, 0, 0)


def _quiet_remove(p):
    try:
        if os.path.isfile(p):
            os.remove(p)
    except OSError:
        pass


# ------------------------------------------------------------------ manifest


def _fetch_url_bytes(url, log=None, what="文件"):
    """按源链取一个小文件（manifest / index）：直连 → gh-proxy 镜像 → 本地代理。

    与 `vt_dl.source_chain` 同口径——这些文件都挂在 github.com 上，国内
    无代理时直连可能整体失败，那意味着「根本发现不了更新」。文件本身只有
    几 KB，不值得动用分块引擎，但源链回退必须有。
    """
    chain = vt_dl.source_chain(url, log=log)
    why = []
    for src in chain:
        try:
            req = urllib.request.Request(src.url, headers={
                "User-Agent": "VideoToolbox-updater",
                "Accept": "application/json"})
            with src.opener.open(req, timeout=60) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001
            why.append("%s：%r" % (src.label, e))
    raise UpdateError("取%s失败（已尝试 %d 个源）：\n  %s\n（%s）"
                      % (what, len(chain), "\n  ".join(why), url))


def load_manifest(src, log=None):
    """读 manifest。`src` 可以是 http(s) URL、本地路径或 file:// URL。

    ⚠ 支持本地路径/`file://` 是为了**离线自测**：不必真的发一版才能验流程。
    schema 1 与 schema 2 都认；schema 2 的字段做存在性校验但不强制
    （files/updater/remove 均可缺省，缺省即退化行为）。
    http(s) 走镜像回退链（见 `_fetch_url_bytes`）。
    """
    if src.startswith("http://") or src.startswith("https://"):
        raw = _fetch_url_bytes(src, log=log, what="更新清单")
    else:
        import urllib.parse
        if src.startswith("file://"):
            # ⚠ 不能简单砍掉 "file://" —— Windows 上是 `file:///C:/...`，
            #   砍完剩 `/C:/...`，多一个前导斜杠就找不到文件。
            #   用 url2pathname 归一（它会把 `/C:/x` 还原成 `C:\x`）。
            p = urllib.request.url2pathname(urllib.parse.urlparse(src).path)
        else:
            p = src
        if not os.path.isfile(p):
            raise UpdateError("更新清单不存在：%s" % p)
        raw = open(p, "rb").read()

    try:
        m = json.loads(raw.decode("utf-8"))
    except Exception as e:  # noqa: BLE001
        raise UpdateError("更新清单不是合法 JSON：%s" % e)
    if not isinstance(m, dict) or m.get("schema") not in (1, 2):
        raise UpdateError("更新清单 schema 不受支持：%r" % m.get("schema"))
    if not m.get("version") or not isinstance(m.get("assets"), list):
        raise UpdateError("更新清单缺 version / assets")
    m.setdefault("base_url", "")
    m.setdefault("files", {})
    m.setdefault("remove", [])
    if not isinstance(m["files"], dict):
        raise UpdateError("更新清单 files 字段必须是对象")
    return m


# ------------------------------------------------------------------ 版本索引（全版本通用）


def load_version_index(url=None, log=None):
    """读全版本目录 index.json。失败转成 UpdateError（UI 口径统一）。"""
    def say(msg):
        if log:
            log(msg)

    src = url or DEFAULT_INDEX_URL
    say("读取版本索引：%s" % src)
    # ⚠ 只有 http(s) 才需要源链回退。本地路径 / file:// 没有"源"可换，
    #   交给 vindex 自己读 —— 离线自测与 `--index <本地文件>` 靠这条。
    #   （_fetch_url_bytes 走 vt_dl.source_chain，喂本地路径会报
    #    "unknown url type: c"，即盘符被当成协议名。）
    fetch = None
    if src.startswith(("http://", "https://")):
        # 注入带镜像回退链的实现——index.json 与 manifest/资产
        # 走同一条容错路径（vt_version_index 本身不依赖 vt_dl）
        fetch = lambda u: _fetch_url_bytes(  # noqa: E731
            u, log=log, what="版本索引")
    try:
        idx = vindex.load_index(src, fetch=fetch)
    except vindex.VIndexError as e:
        raise UpdateError(str(e))
    say("    %d 个版本可用，最新 v%s"
        % (len(vindex.visible_versions(idx)),
           (idx.get("channels") or {}).get("latest") or "?"))
    return idx


def list_versions(idx, allow_hidden=False, limit=0):
    """列出可选版本（降序）。`(版本, 状态, 说明)` 三元组列表。"""
    out = [(e["version"], e.get("state") or "stable", e.get("notes") or "")
           for e in vindex.visible_versions(idx, allow_hidden=allow_hidden)]
    return out[:limit] if limit and limit > 0 else out


def resolve_manifest(want="latest", index_url=None, manifest=None,
                     base_url=None, allow_hidden=False, log=None):
    """按版本诉求取到 manifest dict —— **全版本通用的入口**。

    · `want` 是 latest/newest/空 **且**没给 index_url → 直接读
      `manifest_url`（老行为，一次请求，默认路径完全不变）；
    · 否则 → 读 index.json，按 `want` 选版本，再读该版本自己的
      `manifest-<版本>.json`（升级 / 降级 / 重装同一套代码）。

    `want` 的写法见 `vt_version_index.resolve()`：精确版本号、
    `^1.20` / `~1.20` / `>=1.19` 范围、通道名 stable/latest 都认。

    返回 `(manifest, entry_or_None)`：第二项是命中的版本记录
    （老路径下为 None），调用方可用它显示"正在装 vX 的哪个版本"。
    """
    def say(msg):
        if log:
            log(msg)

    want = (want or "latest").strip()
    plain_latest = want.lower() in ("latest", "newest", "")

    if plain_latest and not index_url:
        m = load_manifest(manifest or DEFAULT_MANIFEST_URL)
        if base_url:
            m["base_url"] = base_url
        return m, None

    idx = load_version_index(index_url, log=log)
    if base_url:
        idx["base_url"] = base_url
    # vindex 的 VIndexError / VersionError 必须归一成 UpdateError：
    # vt_online_setup 的 worker 只捕 core.UpdateError，漏一个类型
    # 界面就永远停在"正在获取更新信息…"、退出码还是 0
    # （--version 9.9.9、索引被全部 yanked、">abc" 都会走到这里）。
    try:
        entry = vindex.resolve(idx, want, allow_hidden=allow_hidden, log=log)
        url = vindex.manifest_url(idx, entry, base_url=base_url)
    except (vindex.VIndexError, vindex.VersionError) as e:
        raise UpdateError(str(e))
    say("已选版本 v%s → %s" % (entry["version"], url))

    # 自身版本不够新时不能硬装：新版清单可能有老安装器不认的字段，
    # 静默漏文件比报错难查得多。
    if not vindex.updater_ok(entry, SELF_VERSION):
        raise UpdateError(
            "安装 v%s 需要 v%s 以上的在线安装器（当前 v%s）。\n"
            "请先更新在线安装器后重试。"
            % (entry["version"], entry.get("min_updater"), SELF_VERSION))

    m = load_manifest(url)
    # ⚠ 显式传入的 base_url 必须**覆盖** manifest 里的值，不能 setdefault：
    #   线上发布的 manifest 里 base_url 写死 GitHub 地址，而本地验证 /
    #   离线场景传的 base_url 指向本地目录（file:///…）。用 setdefault 时
    #   清单已带 base_url 就不会被替换，后续资产下载全打向 GitHub 404 ——
    #   而且 404 发生在下载阶段，看起来像「发布物没上传」，
    #   真正原因却是调用方想本地自测。
    if base_url:
        m["base_url"] = base_url
    else:
        m.setdefault("base_url", idx.get("base_url") or "")
    return m, entry


def plan_orphans(install_dir, manifest, log=None):
    """算「装过、但目标版本不要」的文件 —— 降级 / 跨大版本切换时的残留。

    三重安全判据，缺一不可：

      · 该文件在 `vt_installed.json` 里出现过 —— 证明它**是我们装的**。
        用户数据（`data/`、`logs/`、`downloads/`…）压根不进 installed.json，
        所以天然不会被误伤；
      · 它不在目标 manifest 的 `files` 清单里 —— 目标版本确实不要它；
      · 它当前内容的 sha256 **仍等于** installed.json 记录的值 ——
        没人改过。改过就可能是用户的东西，一律不动。

    没有 installed.json（首次装 / 清单被删）时返回空——宁可留残留，
    也不冒误删用户文件的险。
    """
    def say(msg):
        if log:
            log(msg)

    files = manifest.get("files") or {}
    if not files:
        return []
    inst = read_installed(install_dir)
    if not inst:
        return []
    inst_files = inst.get("files") or {}
    out = []
    for rel, meta in inst_files.items():
        if rel in files:
            continue
        p = os.path.join(install_dir, rel.replace("/", os.sep))
        if not os.path.isfile(p):
            continue
        try:
            if sha256_file(p) != meta.get("sha256"):
                say("    跳过残留清理（内容已被改动，可能不是我们的）：%s" % rel)
                continue
        except OSError:
            continue
        out.append(rel)
    if out:
        say("    目标版本不再包含 %d 个文件，将清理" % len(out))
    return out


def asset_url(manifest, asset):
    """把 manifest.base_url 与资产文件名拼成下载地址。"""
    base = (manifest.get("base_url") or "").rstrip("/")
    if not base:
        raise UpdateError("更新清单里没有 base_url，无法定位资产")
    # 文件名必须 percent-encode：updater 资产名带中文
    # （视频工具箱_在线安装_vX.exe），裸拼进 URL 会让 urllib 在
    # 发请求时抛 UnicodeEncodeError，整个安装以 rc=1 收场
    # （组件其实已全部落地，只有这一步炸，2026-10-15 实测）。
    import urllib.parse
    return base + "/" + urllib.parse.quote(asset["file"])


def asset_parts(manifest, asset):
    """资产的实际分卷列表。无 parts 时就是 [file] 自身。"""
    parts = asset.get("parts")
    if parts and isinstance(parts, list):
        return list(parts)
    return [asset["file"]]


# ------------------------------------------------------------------ 本地清单与增量计划


def installed_path(install_dir):
    return os.path.join(install_dir, INSTALLED_NAME)


def read_installed(install_dir):
    """读本地安装清单；不存在/损坏返回 None。

    ⚠ 2026-10-13 审查修复：`files` 的每个值也必须是 dict——旧实现只查
    顶层，`files: {"a": 1}` 会让后续 `meta.get("sha256")` 抛
    AttributeError，一路逃到调用方兜底（表现为"比对本地文件失败"）。
    值不是 dict 的一律剔除（记不全比炸了好）。
    """
    p = installed_path(install_dir)
    if not os.path.isfile(p):
        return None
    try:
        d = json.loads(open(p, "rb").read().decode("utf-8"))
        if isinstance(d.get("files"), dict):
            d["files"] = {k: v for k, v in d["files"].items()
                          if isinstance(v, dict)}
            return d
    except Exception:  # noqa: BLE001
        pass
    return None


def write_installed(install_dir, manifest):
    """按 manifest 写本地安装清单（更新完成后的新基准）。"""
    files = {}
    for rel, meta in (manifest.get("files") or {}).items():
        files[rel] = {"size": meta.get("size"), "sha256": meta.get("sha256")}
    d = {"version": manifest.get("version"),
         "written": time.strftime("%Y-%m-%d %H:%M:%S"), "files": files}
    p = installed_path(install_dir)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(d, fh, ensure_ascii=False)
    os.replace(tmp, p)
    return p


def local_inventory(install_dir, manifest, log=None):
    """取本地文件真相：{rel: sha256 或 None（缺失/待下）} + 本地版本号。

    以**磁盘**为基准，installed.json 只用来走快路径：

      · installed.json 记录的 sha 与远端清单一致、且文件大小一致、
        且 mtime 不新于写清单的时刻 → 认定未变，**免哈希**
        （104MB 的 exe 每次更新重算要 1 秒+，绝大多数文件根本没人动过）；
      · 其余情况一律现场算 sha（含 installed.json 缺失——这就是
        「任何旧版本都能对齐」的路径）；
      · installed 记录与远端清单本来就不同的文件直接判「待下」，
        不必哈希（反正要重下）。

    mtime 快路径是保守的：只有「安装后没被碰过」才免哈希；
    时钟被故意拨乱只会让更多文件走全哈希，不会放过真变化。
    """
    def say(msg):
        if log:
            log(msg)

    files = manifest.get("files") or {}
    inst = read_installed(install_dir)
    inst_files = (inst or {}).get("files") or {}
    local_ver = (inst or {}).get("version", "")
    written_ts = 0.0
    if inst:
        try:
            written_ts = time.mktime(time.strptime(
                inst.get("written", ""), "%Y-%m-%d %H:%M:%S"))
        except Exception:  # noqa: BLE001
            written_ts = 0.0

    out = {}
    hashed = skipped = 0
    for i, (rel, meta) in enumerate(files.items(), 1):
        p = os.path.join(install_dir, rel.replace("/", os.sep))
        old = inst_files.get(rel) or {}
        if old.get("sha256") and old.get("sha256") != meta.get("sha256"):
            out[rel] = None            # 新旧版本就该不同，直接判待下
            continue
        if not os.path.isfile(p):
            out[rel] = None
            continue
        if (old.get("sha256") == meta.get("sha256")
                and old.get("size") == meta.get("size")
                and os.path.getsize(p) == meta.get("size")
                and os.path.getmtime(p) <= written_ts + 1):
            out[rel] = old["sha256"]   # 安装后未被碰过，免哈希
            skipped += 1
            continue
        try:
            out[rel] = sha256_file(p)
            hashed += 1
        except OSError:
            out[rel] = None
        if log and (i % 500 == 0 or i == len(files)):
            say("    已核对 %d/%d 个本地文件（实算 %d，免算 %d）"
                % (i, len(files), hashed, skipped))
    return out, local_ver


def plan_update(manifest, install_dir, log=None):
    """算增量计划。返回 dict：

        need           需要下载的资产列表（manifest["assets"] 的子集）
        changed        将有内容变化的文件相对路径列表
        download_bytes 本次需下载的字节数
        skip_bytes     被跳过（未变）的字节数
        full           是否退化为全量（schema 1 无 files，或映射失败）
        remove         发布侧声明应删除的路径列表
        orphans        本地装过、目标版本不要的文件（**降级**时才有）
        local_version  识别到的本地版本（无清单时为 ''）

    ⚠ `orphans` 只在降级 / 跨版本切换时非空。升级时目标清单只会比本地
    多（或改），不会"少"，所以它是空表——它的存在就是为了让
    「升 / 降 / 重装」三种方向共用同一套计划逻辑。
    """
    def say(msg):
        if log:
            log(msg)

    assets = manifest["assets"]
    files = manifest.get("files") or {}
    remove = manifest.get("remove") or []

    if not files:
        # schema 1：没有文件级清单，只能全量（也因此算不出孤儿，不敢删）
        total = sum(int(a.get("size") or 0) for a in assets)
        return {"need": assets, "changed": [], "download_bytes": total,
                "skip_bytes": 0, "full": True, "remove": remove,
                "orphans": [], "local_version": ""}

    local, local_ver = local_inventory(install_dir, manifest, log=log)
    say("本地版本 v%s，核对 %d 个文件" % (local_ver or "?", len(local)))

    changed = [rel for rel, meta in files.items()
               if local.get(rel) != meta.get("sha256")]
    pkgs = sorted({files[rel].get("pkg") or "base" for rel in changed})
    by_name = {a.get("name"): a for a in assets}
    missing_pkg = [p for p in pkgs if p not in by_name]
    if missing_pkg:
        # 清单指向的包不在资产里——不敢猜，退化全量更安全
        say("有 %d 个变化包不在资产列表中（%s），本次按全量处理"
            % (len(missing_pkg), ", ".join(missing_pkg[:3])))
        total = sum(int(a.get("size") or 0) for a in assets)
        return {"need": assets, "changed": changed, "download_bytes": total,
                "skip_bytes": 0, "full": True, "remove": remove,
                "orphans": plan_orphans(install_dir, manifest, log=log),
                "local_version": local_ver}

    need = [by_name[p] for p in pkgs]
    need_names = set(pkgs)
    dl = sum(int(a.get("size") or 0) for a in need)
    skip = sum(int(meta.get("size") or 0) for rel, meta in files.items()
               if (meta.get("pkg") or "base") not in need_names)
    orphans = plan_orphans(install_dir, manifest, log=log)
    return {"need": need, "changed": changed, "download_bytes": dl,
            "skip_bytes": skip, "full": False, "remove": remove,
            "orphans": orphans, "local_version": local_ver}


# ------------------------------------------------------------------ 下载（分卷 + 引擎）


def download_asset(manifest, asset, dest, progress=None, log=None, cancel=None,
                   stats=None):
    """下载一个资产（含分卷拼接）到 dest 并校验整体 sha256。

    分卷逻辑：parts 里的每一卷都是一个普通下载任务（各自断点续传），
    全部就位后按序拼接成最终文件——zip 可以按字节切分后原样拼回。
    单卷超过 GitHub 2GB 也不怕：发布侧保证每卷 ≤ VOLUME_MAX。

    progress 契约：(阶段文本, 已完成, 总数)——与 apply_update / UI 一致。
    vt_dl 的引擎回调是 2 arg (done, total)，这里用 _wrap 适配，
    **不要**把 3-arg 回调直接透传给 vt_dl（会 TypeError）。
    """
    def say(msg):
        if log:
            log(msg)

    def _wrap(stage):
        """把 (stage, done, total) 契约适配成 vt_dl 的 (done, total)。"""
        if not progress:
            return None
        return lambda d, t: progress(stage, d, t)

    parts = asset_parts(manifest, asset)
    try:
        if len(parts) == 1 and parts[0] == asset["file"]:
            url = asset_url(manifest, asset)
            say("    下载 %s" % url)
            return vt_dl.download_file(
                url, dest, progress=_wrap("下载 %s" % (asset.get("name")
                                                       or asset["file"])),
                log=log, cancel=cancel,
                expect_sha256=asset.get("sha256"), stats=stats)

        # 分卷：逐卷下载（可续传）→ 拼接 → 校验
        tmp = dest + ".catting"
        got_parts = []
        for i, pname in enumerate(parts, 1):
            url = asset_url(manifest, {"file": pname})
            pp = dest + ".part%03d" % i
            say("    分卷 %d/%d：%s" % (i, len(parts), pname))
            vt_dl.download_file(
                url, pp,
                progress=_wrap("下载分卷 %d/%d" % (i, len(parts))),
                log=log, cancel=cancel, stats=stats)
            got_parts.append(pp)
        with open(tmp, "wb") as out:
            for pp in got_parts:
                with open(pp, "rb") as fh:
                    while True:
                        b = fh.read(CHUNK)
                        if not b:
                            break
                        out.write(b)
        for pp in got_parts:
            _quiet_remove(pp)
        if asset.get("sha256"):
            got = sha256_file(tmp)
            if got != asset["sha256"]:
                _quiet_remove(tmp)
                raise UpdateError(
                    "分卷拼接后 sha256 校验不通过，已中止：\n  期望 %s\n  实际 %s\n（%s）"
                    % (asset["sha256"], got, asset["file"]))
        os.replace(tmp, dest)
        return dest
    except Canceled:
        raise
    except vt_dl.DlError as e:
        raise UpdateError(str(e))


# ------------------------------------------------------------------ 解压与校验


def _safe_members(zf):
    """过滤 zip 成员，挡掉路径穿越（zip slip）与绝对路径。"""
    out = []
    for info in zf.infolist():
        name = info.filename.replace("\\", "/")
        if name.startswith("/") or ".." in name.split("/"):
            raise UpdateError("压缩包里有可疑路径，已拒绝解压：%s" % info.filename)
        if name.startswith("__MACOSX/"):
            continue
        out.append(info)
    return out


def extract_zip(zip_path, target_dir, progress=None):
    """把 zip 解压到 target_dir；返回解压的文件数。"""
    os.makedirs(target_dir, exist_ok=True)
    n = 0
    try:
        with zipfile.ZipFile(zip_path) as zf:
            members = _safe_members(zf)
            total = len(members)
            for i, info in enumerate(members, 1):
                zf.extract(info, target_dir)
                if not info.is_dir():
                    n += 1
                if progress:
                    progress(i, total)
    except zipfile.BadZipFile as e:
        raise UpdateError("组件包已损坏（不是合法 zip）：%s\n%s" % (zip_path, e))
    except UpdateError:
        raise
    except Exception as e:  # noqa: BLE001
        raise UpdateError("解压失败：%s" % e)
    return n


def verify_staging(staging, manifest, pkg_names, log=None):
    """落地前的最后一道闸：逐文件验 sha256。

    整体 zip 的 sha256 只证明「包没下错」；这里证明「包里的每个文件
    确实是清单声称的那个」——防的是打包侧清单写错、zip 被二次篡改等
    整包校验看不出的情况。任何不符直接抛错，绝不落地。
    """
    def say(msg):
        if log:
            log(msg)

    files = manifest.get("files") or {}
    checked = 0
    for rel, meta in files.items():
        if (meta.get("pkg") or "base") not in pkg_names:
            continue
        p = os.path.join(staging, rel.replace("/", os.sep))
        if not os.path.isfile(p):
            raise UpdateError("暂存区缺少清单中的文件：%s" % rel)
        got = sha256_file(p)
        if got != meta.get("sha256"):
            raise UpdateError(
                "暂存区文件校验不通过，已中止：\n  %s\n  期望 %s\n  实际 %s"
                % (rel, meta.get("sha256"), got))
        checked += 1
    say("    暂存区 %d 个文件逐一体校验通过 ✓" % checked)
    return checked


# ------------------------------------------------------------------ 原子落地


def apply_staging(staging, install_dir, manifest, pkg_names, log=None):
    """把暂存区文件原子地落到安装目录。失败整体回滚。

    手法（Windows 语义）：
      · 运行中的 exe 不能覆盖/删除，但**可以重命名**；普通文件同理。
      · 因此落地 = 先把目标改名为 `<目标>.vtold`（元数据操作，瞬时且
        不占额外空间），再把暂存文件 move 到位；成功后再删 .vtold。
      · 任一步失败：已落地的删掉、.vtold 全部改回 → 安装目录保持
        旧版本完整状态，不会半新半旧。
    """
    def say(msg):
        if log:
            log(msg)

    files = manifest.get("files") or {}
    targets = [rel for rel, meta in files.items()
               if (meta.get("pkg") or "base") in pkg_names]
    renamed = []      # [(目标路径, .vtold 路径)]
    landed = []       # 已落地的新文件路径

    def rollback():
        for new in reversed(landed):
            try:
                if os.path.isfile(new):
                    os.remove(new)
                elif os.path.isdir(new):
                    shutil.rmtree(new, ignore_errors=True)
            except OSError:
                pass
        for tgt, old in reversed(renamed):
            try:
                if not os.path.exists(old):
                    continue
                # ⚠ 2026-10-13 审查修复：旧条件 `not os.path.exists(tgt)`
                # 漏掉了「拷到一半失败」的目标——跨卷时 shutil.move 退化为
                # copy2+unlink，磁盘满/占用会让 tgt 留下半截新文件。旧版本
                # 还躺在 .vtold 里，而下一轮更新会直接删掉 .vtold → 旧版
                # 永久丢失。现在：凡 old 还在，先把当前 tgt（不管是落地
                # 的还是拷了一半的）清掉再还原。
                if os.path.exists(tgt):
                    if os.path.isfile(tgt):
                        os.remove(tgt)
                    else:
                        shutil.rmtree(tgt, ignore_errors=True)
                os.replace(old, tgt)
            except OSError:
                pass

    try:
        # 第一遍：全部目标先改名（快，基本不会失败）
        for rel in targets:
            tgt = os.path.join(install_dir, rel.replace("/", os.sep))
            if os.path.exists(tgt):
                old = tgt + OLD_SUFFIX
                if os.path.exists(old):
                    _quiet_remove(old) if os.path.isfile(old) else \
                        shutil.rmtree(old, ignore_errors=True)
                os.replace(tgt, old)
                renamed.append((tgt, old))
        # 第二遍：暂存文件落地
        for rel in targets:
            src = os.path.join(staging, rel.replace("/", os.sep))
            tgt = os.path.join(install_dir, rel.replace("/", os.sep))
            os.makedirs(os.path.dirname(tgt), exist_ok=True)
            shutil.move(src, tgt)
            landed.append(tgt)
    except Exception as e:  # noqa: BLE001
        say("落地失败，正在回滚：%s" % e)
        rollback()
        raise UpdateError("落地失败（已回滚到旧版本）：%s" % e)

    # 成功：清理 .vtold（删不掉无所谓，多是运行中的 exe，下次更新会覆盖）
    for _tgt, old in renamed:
        try:
            if os.path.isfile(old):
                os.remove(old)
            elif os.path.isdir(old):
                shutil.rmtree(old, ignore_errors=True)
        except OSError:
            pass
    say("已落地 %d 个文件" % len(landed))
    return len(landed)


def _safe_rel(rel):
    """把 manifest/orphan 列表里的相对路径规范化成安全形态。

    拒绝空串 / "." / 含 ".." 的路径——`os.path.join(install_dir, "")`
    就是安装目录本身，rmtree 下去整个安装目录（含用户数据）没了。
    manifest 是远程可更新文件，发布侧一个 bug 混进空串就等于帮用户
    「格式化安装目录」。zip slip 有 `_safe_members` 挡着，manifest 自己
    的 remove 列表同理要防。
    """
    rel = (rel or "").strip().replace("\\", "/").lstrip("/")
    parts = [p for p in rel.split("/") if p not in ("", ".")]
    if not rel or not parts or ".." in parts:
        return None
    return "/".join(parts)


def apply_removals(install_dir, remove, log=None):
    """按 manifest.remove 删除文件/目录（删除失败只警告，不阻断）。"""
    n = 0
    for rel in remove or []:
        safe = _safe_rel(rel)
        if safe is None:
            if log:
                log("    [warn] 跳过可疑删除路径：%r" % rel)
            continue
        p = os.path.join(install_dir, safe.replace("/", os.sep))
        try:
            if os.path.isfile(p):
                os.remove(p)
                n += 1
            elif os.path.isdir(p):
                shutil.rmtree(p, ignore_errors=True)
                n += 1
        except OSError as e:
            if log:
                log("    [warn] 删除 %s 失败：%s" % (rel, e))
    return n


# ------------------------------------------------------------------ 安装目录


def _drive_usable(root):
    """盘符是否可用：存在、是目录、且能在其下建子目录（可写）。

    ⚠ 只做「能不能建目录」的探测，不去真的建——os.access 对 NTFS 权限
      的判断不可靠，实测建目录才是唯一可信的判据。建完立刻删掉。
    """
    if not root or not os.path.isdir(root):
        return False
    probe = os.path.join(root, ".vt_probe_%d" % os.getpid())
    try:
        os.makedirs(probe, exist_ok=True)
        os.rmdir(probe)
        return True
    except OSError:
        return False


def pick_default_dir(name=None, drives=FALLBACK_DRIVES):
    """挑默认安装目录：**D 盘优先**，不可用时逐个退让。

    顺序：
      1. `D:\\<name>` 且 D 盘可写 —— 正常情况就是它；
      2. 依次试 E: / F: / C: 上的 `<name>`；
      3. 全都不行 → `%LOCALAPPDATA%\\Programs\\<name>`（一定能建）。

    为什么第 3 步兜到 LOCALAPPDATA 而不是放弃：安装器必须给出一个
    可直接点「开始安装」的路径，给空串会让 UI 卡在「请先选择目录」。
    """
    sub = name or DEFAULT_DIR_NAME
    for drv in drives:
        cand = os.path.join(drv + os.sep, sub)
        if _drive_usable(drv + os.sep):
            return cand
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, "Programs", sub)


def default_install_dir():
    """给 UI 用的默认目录：`DEFAULT_DIR` 不可写时才退让。

    与 `pick_default_dir()` 的差别：那个是「从零挑」，这个是「先认
    既定的 D:\\VideoToolbox，实在不行才换」——已装用户的习惯路径
    优先级最高，不能因为一次权限抖动就换地方。
    """
    root = os.path.splitdrive(DEFAULT_DIR)[0] + os.sep
    if _drive_usable(root):
        return DEFAULT_DIR
    return pick_default_dir()


def detect_install_dir():
    """从注册表找已安装目录（Inno 写的 InstallLocation）；找不到返回 ''。

    ⚠ 只用标准库：优先读 `winreg`，非 Windows 或读不到就返回空。
    ⚠ Inno 的卸载键名 = AppId（本项目是固定 GUID，见 视频工具箱.iss），
      **键名里不可能出现 "videotoolbox"**——必须逐键读 DisplayName 匹配。
      曾经的 bug：只匹配键名，导致自定义安装目录的用户被误判为「未安装」，
      更新会落到 D:\\VideoToolbox（或提示全新安装），装出第二份来。
    """
    if os.name != "nt":
        return ""
    try:
        import winreg
    except ImportError:
        return ""
    roots = (r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
             r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall")

    def _hit(text):
        return ("videotoolbox" in (text or "").lower()
                or "视频工具箱" in (text or ""))

    def _qv(key, name):
        try:
            v, _t = winreg.QueryValueEx(key, name)
            return str(v or "")
        except OSError:
            return ""

    for root in roots:
        for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            try:
                with winreg.OpenKey(hive, root) as k:
                    for i in range(winreg.QueryInfoKey(k)[0]):
                        try:
                            sub = winreg.EnumKey(k, i)
                        except OSError:
                            continue
                        try:
                            with winreg.OpenKey(k, sub) as sk:
                                # 键名命中（非 GUID 命名的安装器）或
                                # DisplayName 命中（Inno GUID 键）都算
                                if not (_hit(sub) or _hit(_qv(sk,
                                        "DisplayName"))):
                                    continue
                                loc = _qv(sk, "InstallLocation")
                                if loc and os.path.isdir(loc):
                                    return loc
                        except OSError:
                            continue
            except OSError:
                continue
    # 兜底一：既定的默认位置（D:\VideoToolbox）确实存在 —— 用它
    if os.path.isdir(DEFAULT_DIR):
        return DEFAULT_DIR
    # 兜底二：装过但注册表没写、或 D 盘换过 —— 退让到可用盘上的同名目录，
    #         存在就说明以前装在那儿
    for cand in pick_default_dir(),:
        if os.path.isdir(cand):
            return cand
    return ""


def app_running(install_dir):
    """安装目录里的主程序是否在跑（判断能否直接覆盖 exe）。"""
    exe = os.path.join(install_dir, "视频工具箱.exe")
    if not os.path.isfile(exe):
        return False
    if os.name != "nt":
        return False
    try:
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq 视频工具箱.exe",
                              "/NH"], capture_output=True, timeout=20)
        return "视频工具箱.exe" in (out.stdout or b"").decode("gbk", "replace")
    except Exception:  # noqa: BLE001
        return False


def free_space_ok(path, need):
    """目标盘剩余空间是否够（留 200MB 余量）。"""
    try:
        probe = path
        while probe and not os.path.isdir(probe):
            probe = os.path.dirname(probe)
        if not probe:
            return True
        return shutil.disk_usage(probe).free > need + 200 * 1048576
    except Exception:  # noqa: BLE001
        return True


# ------------------------------------------------------------------ 快捷方式


def create_shortcuts(install_dir, desktop=True, start_menu=True):
    """建/刷新快捷方式。返回成功创建的条数。

    ⚠ 用 PowerShell 的 WScript.Shell —— 标准库里没有建 .lnk 的能力，
    自己写 COM 要近百行 ctypes。失败只记数不抛，不阻断安装。
    """
    if os.name != "nt":
        return 0
    exe = os.path.join(install_dir, "视频工具箱.exe")
    if not os.path.isfile(exe):
        return 0
    lnks = []
    if desktop:
        lnks.append(os.path.join(os.path.expanduser("~"), "Desktop",
                                 "视频工具箱.lnk"))
    if start_menu:
        lnks.append(os.path.join(os.environ.get("APPDATA", ""),
                                 r"Microsoft\Windows\Start Menu\Programs",
                                 "视频工具箱.lnk"))
    made = 0
    for lnk in lnks:
        if not os.path.isdir(os.path.dirname(lnk)):
            continue
        ps = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut('%s');"
              "$s.TargetPath='%s';$s.WorkingDirectory='%s';$s.Save()"
              % (lnk.replace("'", "''"), exe.replace("'", "''"),
                 install_dir.replace("'", "''")))
        try:
            r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive",
                                "-Command", ps], capture_output=True, timeout=60)
            if r.returncode == 0 and os.path.isfile(lnk):
                made += 1
        except Exception:  # noqa: BLE001
            continue
    return made


# ------------------------------------------------------------------ 更新器自身


def ensure_updater(manifest, install_dir, work_dir, progress=None, log=None,
                   cancel=None):
    """保证安装目录里的在线安装器（updater）是最新版。

    返回 updater 路径；manifest 没给 updater 条目时返回 None。
    已是最新（sha256 一致）则什么都不下。主程序「检查更新」入口与
    setup exe 收尾自检都用它——**老版本的主程序因此永远只会拉起
    最新的 updater**，不会被执行旧逻辑。
    """
    def say(msg):
        if log:
            log(msg)

    up = manifest.get("updater") or {}
    if not up.get("file") or not up.get("sha256"):
        return None
    dest = os.path.join(install_dir, up["file"])
    if os.path.isfile(dest):
        try:
            if sha256_file(dest) == up["sha256"]:
                return dest
        except OSError:
            pass
    say("更新在线安装器：%s（%s）" % (up["file"], human(int(up.get("size") or 0))))
    os.makedirs(work_dir, exist_ok=True)
    tmp = os.path.join(work_dir, up["file"] + ".new")
    # 远端资产名与本地落地名分开：GitHub Release 资产名**不支持中文**
    # （中文名会被平台强制净化成 `_._v2.3.0.exe`，PATCH 改名也拦不住），
    # 而发布侧 manifest 记的 file 是中文本地名。2026-10-15 实测：两者
    # 混用导致 updater 下载 404。新 manifest 带 `asset`（ASCII 资产名），
    # 老 manifest 没有就退回 file。
    url = asset_url(manifest, {"file": up.get("asset") or up["file"]})
    # vt_dl 的 progress 是 2 arg (done, total)；本层契约是 3 arg
    # (阶段, done, total)——必须包一层，否则调用方传 3-arg 回调会
    # TypeError（曾被通用 except 吞掉、把成功的更新误报成失败）。
    dl_prog = (lambda d, t: progress and progress("更新在线安装器", d, t)) \
        if progress else None
    try:
        vt_dl.download_file(url, tmp, progress=dl_prog, log=log, cancel=cancel,
                            expect_sha256=up["sha256"])
    except Canceled:
        raise
    except vt_dl.DlError as e:
        raise UpdateError(str(e))
    # 落地：自己在跑也能被重命名（Windows 语义），旧的留 .vtold 下次清
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    # ⚠ 跨盘陷阱（2026-10-15 实测）：work_dir 在 %TEMP%（通常 C:），安装目录
    #   常在 D: —— os.replace 跨盘一律 OSError 18「无法将文件移到不同的磁盘
    #   驱动器」，首次安装（dest 不存在）也照样炸，整个安装以 rc=1 收场
    #   （组件其实已全部落地，只有 updater 这一步失败，症状极具迷惑性）。
    #   先把文件 copy 到**目标盘**的临时名，再同盘 os.replace——rename 可
    #   覆盖运行中的 exe 这一 Windows 语义原样保留。
    if os.path.splitdrive(os.path.abspath(tmp))[0].lower() != \
            os.path.splitdrive(os.path.abspath(dest))[0].lower():
        tmp2 = dest + ".new"
        shutil.copyfile(tmp, tmp2)
        _quiet_remove(tmp)
        tmp = tmp2
    if os.path.isfile(dest):
        try:
            os.replace(dest, dest + OLD_SUFFIX)
        except OSError as e:
            say("    [warn] 旧安装器改名失败（%s），直接覆盖试试" % e)
    os.replace(tmp, dest)
    say("    在线安装器已更新 ✓")
    return dest


def find_updater_exe(install_dir):
    """在安装目录里找在线安装器 exe（名字带版本号，取最新的一个）。"""
    import glob
    cands = glob.glob(os.path.join(install_dir, "视频工具箱_在线安装_v*.exe"))
    if not cands:
        return ""
    return max(cands, key=os.path.getmtime)


# ------------------------------------------------------------------ 总流程


def apply_update(manifest, install_dir, work_dir, progress=None, log=None,
                 shortcuts=None, cancel=None, stats=None):
    """按 manifest 下载并更新到 install_dir。

    · schema 1（无 files）：老行为——下载全部资产并直接解压进安装目录。
    · schema 2（有 files）：先算增量计划，只下变化的包；解压到暂存区、
      逐文件校验、原子落地，最后写 vt_installed.json。

    progress / log 为回调：(阶段文本, 已完成, 总数) 与 (文本)。
    返回结果 dict（供 UI 汇总）。
    """
    def say(msg):
        if log:
            log(msg)

    if not install_dir:
        raise UpdateError("没有指定安装目录")
    os.makedirs(install_dir, exist_ok=True)
    os.makedirs(work_dir, exist_ok=True)

    plan = plan_update(manifest, install_dir, log=log)
    if not plan["need"] and not plan["remove"] and not plan["orphans"]:
        say("没有需要下载的组件（文件均与清单一致）")
        if manifest.get("files"):
            write_installed(install_dir, manifest)
        return {"version": manifest.get("version"), "files": 0,
                "downloaded": 0, "skipped": plan["skip_bytes"],
                "seconds": 0.0, "full": False, "dir": install_dir}

    need_bytes = plan["download_bytes"]
    # ⚠ 2026-10-13 审查修复：下载/暂存全在 work_dir（TEMP 盘，通常 C:），
    # 只查 install_dir 会让「D: 安装省 C: 盘」的目标被自身破坏——C: 先满，
    # 而落地时 staging→install 的跨卷拷贝正好需要两份空间。异盘时两个盘
    # 都要查（安装侧还要容纳解压暂存，故 ×2）。
    if not free_space_ok(install_dir, need_bytes + need_bytes):
        raise UpdateError("安装盘剩余空间不足（约需 %s）"
                          % human(need_bytes * 2))
    if os.path.splitdrive(os.path.abspath(work_dir))[0].lower() != \
            os.path.splitdrive(os.path.abspath(install_dir))[0].lower():
        if not free_space_ok(work_dir, need_bytes + need_bytes):
            raise UpdateError("下载缓存盘（%s）剩余空间不足（约需 %s）"
                              % (os.path.splitdrive(os.path.abspath(work_dir))[0],
                                 human(need_bytes * 2)))

    t0 = time.time()
    downloaded = 0
    staging_root = os.path.join(work_dir, "staging")
    if os.path.isdir(staging_root):
        shutil.rmtree(staging_root, ignore_errors=True)
    os.makedirs(staging_root, exist_ok=True)
    pkg_names = set()
    #: 落地文件计数。**两条路径都要累加**：schema 1 在循环里解压即落地，
    #: schema 2 在循环后由 apply_staging 统一落地。只算后者会让老清单
    #: （schema 1）一路返回 0，UI 上显示"0 个文件"纯属误导。
    n_files = 0

    for idx, a in enumerate(plan["need"], 1):
        name = a.get("name") or a["file"]
        pkg_names.add(name)
        say("[%d/%d] %s（%s）"
            % (idx, len(plan["need"]), name, human(int(a.get("size") or 0))))
        zip_path = os.path.join(work_dir, a["file"])

        # 本地缓存命中（上次下到一半/整包已下过）则跳过下载
        if os.path.isfile(zip_path) and a.get("sha256"):
            try:
                if sha256_file(zip_path) == a["sha256"]:
                    say("    本地缓存校验一致，跳过下载")
            except OSError:
                _quiet_remove(zip_path)
        if not os.path.isfile(zip_path):
            download_asset(manifest, a, zip_path, progress=progress,
                           log=log, cancel=cancel, stats=stats)
        downloaded += int(a.get("size") or 0)

        if a.get("sha256"):
            got = sha256_file(zip_path)
            if got != a["sha256"]:
                raise UpdateError(
                    "sha256 校验不通过，已中止：\n  期望 %s\n  实际 %s\n（%s）"
                    % (a["sha256"], got, a["file"]))
            say("    sha256 校验一致 ✓")

        if manifest.get("files"):
            # schema 2：解进暂存区（各包文件集互斥，平铺合并），校验后原子落地
            # ⚠ 组件互斥性是硬约束：build_online_release.py 启动时会与 IFW
            #   版清单比对，重叠文件会导致后解的包覆盖前一个，verify 会抓到。
            stg = staging_root
            say("    解压到暂存区 %s" % stg)
            n = extract_zip(zip_path, stg,
                            progress=(lambda i, t, _i=idx: progress and
                                      progress("解压 %s" % name, i, t)))
            say("    解开 %d 个文件" % n)
        else:
            # schema 1：老行为，直接解压进安装目录（解压即落地，故计进 n_files）
            target = os.path.join(install_dir, a.get("target") or "")
            say("    解压到 %s" % target)
            n_files += extract_zip(
                zip_path, target,
                progress=(lambda i, t, _i=idx: progress and progress(
                    "解压 %s" % name, i, t)))

    if manifest.get("files") and plan["need"]:
        verify_staging(staging_root, manifest, pkg_names, log=log)
        n_files += apply_staging(staging_root, install_dir, manifest,
                                 pkg_names, log=log)
        shutil.rmtree(staging_root, ignore_errors=True)
        for zp in (os.path.join(work_dir, a["file"]) for a in plan["need"]):
            _quiet_remove(zp)      # 更新成功后清掉下载缓存，不留 100MB 垃圾

    # 删除清单 = 发布侧声明的 remove + 本次算出的孤儿（降级残留）。
    # 两者都是「相对路径」，都只可能是我们装过的东西（孤儿有三重判据）。
    removes = list(plan.get("remove") or []) + list(plan.get("orphans") or [])
    n_rm = apply_removals(install_dir, removes, log=log)
    if n_rm:
        say("清理了 %d 个旧版残留路径（含孤儿 %d）"
            % (n_rm, len(plan.get("orphans") or [])))

    if manifest.get("files"):
        write_installed(install_dir, manifest)
        say("已写入本地安装清单 %s" % INSTALLED_NAME)

    if shortcuts:
        made = create_shortcuts(install_dir, **shortcuts)
        say("    快捷方式：%d 个" % made)

    return {"version": manifest.get("version"), "files": n_files,
            "downloaded": downloaded, "skipped": plan["skip_bytes"],
            "seconds": round(time.time() - t0, 1),
            "full": plan["full"], "dir": install_dir}
