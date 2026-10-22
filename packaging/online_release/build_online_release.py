# -*- coding: utf-8 -*-
# @version 2.5.3
"""把「在线更新包」发布成 GitHub Release 的**平铺资产**（替代 IFW 的在线仓库）。

====================================================================
与 IFW 路线的关系
====================================================================
`installer_src/build_online_installer.py` 走的是 Qt IFW：repogen 把组件打成
`<组件名>/<归档>.7z`，再由 binarycreator 生成在线安装器。那条路有**两个硬约束**：
  1. IFW 取归档的 URL 是 `<基址>/<组件名>/<归档>` —— **多一层目录**；
  2. 仓库要能承载它，只能放 gh-pages（有目录结构），而 gh-pages 走 git，
     **单文件 100 MiB 硬限**（主程序 exe 已 103MB，撞线，余量不足 2MiB）。
GitHub Releases 能放 2GB/资产、但**资产是平铺的**，装不下 IFW 的目录结构
（实测嵌套路径 404；带斜杠 tag 冒充目录会撞 git D/F 冲突）。

本脚本改走「平铺 + 自解压」：组件打成 **zip** 平铺上传，由自研的
`vt_online_setup.exe` 自己下载解压。于是：
  · 不再有 100 MiB 限制（单资产上限 2GB，超了自动分卷）；
  · 不再依赖 gh-pages 的目录结构；
  · 打包侧只剩「zip + manifest + 上传」三件事。

====================================================================
v1.20.0：manifest schema 2（增量更新的地基）
====================================================================
旧版（schema 1）只有一个 base 包：客户端每次更新都要重下全部 104MB。
本版起 manifest 带**文件级清单**（files）与**分卷**（parts）：

  · files —— {安装相对路径: {size, sha256, pkg}}，客户端拿它和本地
    磁盘比对，只下载 sha256 不同的文件所在的包。日常迭代（只改源码）
    用户只需下 ~2MB 的 code 包，104MB 的 app 包（exe）不变则不碰。
  · parts —— 单个 zip 超过 --volume-max（默认 1.5GB）时按字节切卷，
    每卷是一个普通资产；客户端按序拼接还原（zip 可字节切分后原样拼回）。
    GitHub 单资产 2GB 的上限就此也不再是上限。
  · updater —— 在线安装器自身的条目。主程序「检查更新」靠它保证
    拉起的永远是最新逻辑（老安装器不认 schema 2 也不怕）。
  · remove —— 本次应删除的路径（发版时用 --remove 指定）。

====================================================================
用法
====================================================================
    python packaging/online_release/build_online_release.py --dry-run   # 只打包+出清单
    python packaging/online_release/build_online_release.py             # 打包并上传
    python packaging/online_release/build_online_release.py --tag repo-latest
    python packaging/online_release/build_online_release.py --notes "本次更新…"
    python packaging/online_release/build_online_release.py --keep 3     # 旧资产保留策略

⚠ 先打在线安装 exe（vt_online_setup.spec → installer_online\视频工具箱_在线安装_vX.exe），
  本脚本会把它作为 updater 资产一并上传；找不到只警告不中断。
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import vt_version_index as vindex  # noqa: E402  全版本目录（index.json）

HERE = Path(__file__).resolve().parent
#: 脚本位于 <仓库根>/packaging/online_release/，仓库根再上两级
ROOT = HERE.parent.parent
DIST = ROOT / "installer_online"

OWNER, REPO = "09Th90", "VideoToolbox"
DEFAULT_TAG = "repo-latest"

#: 发布包划分。**按变更频率分层，而不是按目录分类**——同一层内的文件
#: 必须"同生共死"，否则会把不变的文件拖进变更层，白白多下。
#:
#:   app   主程序 exe（PyInstaller onefile，内嵌全部依赖）   每次迭代必变 ~104MB
#:   code  自研源码 + 校准脚本                               每次迭代必变 ~2MB
#:   docs  文档（含 GPL-3.0 合规声明）                        偶尔变
#:   tools 工具脚本                                          偶尔变
#:
#: ⚠ 各包文件集必须**互斥**：重叠会让后解的包覆盖前一个，
#:   verify_staging 的逐文件校验会抓到，但发布前就该避免。
#: ⚠ 并集必须与 installer_src/build_online_installer.py 的 COMPONENTS
#:   一致——脚本启动时会比对，防止两条发布路线文件清单漂移。
PACKAGES = {
    "app": [
        ("dist/视频工具箱.exe", "视频工具箱.exe"),
    ],
    "code": [
        ("src", "src"),
        ("subtitle_calib_merged.py", "subtitle_calib_merged.py"),
    ],
    "docs": [
        ("docs", "docs"),
    ],
    "tools": [
        ("tools/ai_client.py", "tools/ai_client.py"),
        ("tools/credential_store.py", "tools/credential_store.py"),
        ("tools/download_open_source_deps.py", "tools/download_open_source_deps.py"),
    ],
}

#: 严禁进发布包的东西（v1.14.1 安全整改，沿用）
FORBIDDEN = ("github_proxy.yaml", "mihomo", "runtime.yaml", "cache.db",
             "config.yaml", "uploader_profile")

#: 超过这个大小就改用「存储」而非「压缩」——主程序 exe 是 PyInstaller onefile，
#: 内部已 zlib 压缩，deflate 再压一次只会白费 CPU（实测收益 0.06%）。
STORE_OVER = 8 * 1024 * 1024

#: 单卷上限（字节）。GitHub 单资产硬限 2GB，留 25% 余量给 CDN/重试抖动；
#: 超了自动按字节切卷，客户端拼接还原。
DEFAULT_VOLUME_MAX = int(1.5 * 1024 * 1024 * 1024)

#: 固定 zip 内时间戳——同内容重复打包得到逐字节相同的 zip，
#: 这样「内容没变」在 sha256 层面可判，客户端缓存命中率最高。
ZIP_DATE_TIME = (2026, 1, 1, 0, 0, 0)


def human(n):
    n = float(n)
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024 or u == "GB":
            return "%.1f %s" % (n, u)
        n /= 1024


def check_packages_in_sync():
    """与 IFW 那份组件清单比对**文件并集**，防止两处漂移。

    只比文件清单、不比包名：IFW 那边是一个大组件 com.videotoolbox.base，
    这边为了增量拆成四个包，属有意差异；但两边分发的文件必须完全一致。
    """
    old = ROOT / "packaging" / "installer_src" / "build_online_installer.py"
    if not old.is_file():
        print("   [warn] 找不到 IFW 版组件清单，跳过一致性比对：%s" % old)
        return
    sys.path.insert(0, str(old.parent))
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("_ifw_build", old)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        ifw = {k: [tuple(x) for x in v] for k, v in mod.COMPONENTS.items()}
    except Exception as e:  # noqa: BLE001
        print("   [warn] 载入 IFW 组件清单失败（%s），跳过比对" % e)
        return
    ifw_all = sorted(tuple(x) for v in ifw.values() for x in v)
    mine_all = sorted(tuple(x) for v in PACKAGES.values() for x in v)
    if ifw_all != mine_all:
        print("   !! 发布文件清单与 IFW 版不一致，两边必须同步改：")
        only_ifw = [x for x in ifw_all if x not in mine_all]
        only_mine = [x for x in mine_all if x not in ifw_all]
        if only_ifw:
            print("      仅 IFW 有：%s" % only_ifw)
        if only_mine:
            print("      仅本脚本有：%s" % only_mine)
        sys.exit(2)
    print("   ✓ 发布文件清单与 IFW 版一致（共 %d 项；包名拆分属有意）"
          % len(ifw_all))


def iter_files(src, dest_rel):
    """枚举一个源条目下的所有文件，产出 (绝对路径, zip 内相对路径)。"""
    src = Path(src)
    if src.is_file():
        yield src, dest_rel.replace("\\", "/")
        return
    for cur, dirs, files in os.walk(src):
        dirs[:] = sorted(d for d in dirs if d not in ("__pycache__",))
        rel = Path(cur).relative_to(src)
        for f in sorted(files):
            if f.endswith((".pyc", ".pyo")):
                continue
            p = Path(cur) / f
            z = (Path(dest_rel) / rel / f).as_posix()
            yield p, z


def build_package(pkg, items, out_dir, volume_max):
    """打一个发布包，返回 manifest 用的资产 dict（含分卷与文件清单）。

    单包超 volume_max 时按字节切卷（zip 可字节切分后原样拼回），
    每卷 ≤ 1.5GB，远低于 GitHub 单资产 2GB 硬限——单文件大小从此
    不再是发布约束。
    """
    ver = read_version()
    stem = "v%s-%s" % (ver, pkg)
    out = Path(out_dir) / (stem + ".zip")
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    files = {}          # zip 内相对路径 -> {size, sha256}
    n = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for src_rel, dest_rel in items:
            src = ROOT / src_rel
            if not src.exists():
                print("   !! 源不存在：%s" % src)
                sys.exit(2)
            for ap, zn in iter_files(src, dest_rel):
                low = zn.lower()
                if any(b in low for b in FORBIDDEN):
                    # 命中即退出（与"源不存在"同级）：被跳过的文件既不进 zip
                    # 也不进 files 清单，客户端按清单逐个校验发现不了
                    # "从未存在的文件"——宁可发不出，也不能发个缺文件的版本
                    print("   !! 禁止入库的文件：%s（命中 FORBIDDEN：%s）"
                          % (zn, [b for b in FORBIDDEN if b in low]))
                    sys.exit(2)
                size = ap.stat().st_size
                method = (zipfile.ZIP_STORED if size >= STORE_OVER
                          else zipfile.ZIP_DEFLATED)
                zi = zipfile.ZipInfo(zn, date_time=ZIP_DATE_TIME)
                zi.compress_type = method
                zi.external_attr = 0o644 << 16
                h = hashlib.sha256()
                with open(ap, "rb") as fh:
                    data = fh.read()
                h.update(data)
                zf.writestr(zi, data)
                files[zn] = {"size": size, "sha256": h.hexdigest(), "pkg": pkg}
                n += 1
    asset = {"name": pkg, "file": out.name, "size": out.stat().st_size,
             "sha256": _sha256_path(out), "entries": n, "target": "",
             "desc": _PKG_DESC.get(pkg, "")}
    if out.stat().st_size > volume_max:
        # 分卷：按字节切，客户端按序拼接（zip 格式对字节切分透明）
        vol = volume_max
        parts = []
        idx = 0
        with open(out, "rb") as fh:
            while True:
                b = fh.read(vol)
                if not b:
                    break
                idx += 1
                pname = "%s.zip.%03d" % (stem, idx)
                (Path(out_dir) / pname).write_bytes(b)
                parts.append(pname)
        os.remove(out)
        asset["parts"] = parts
        asset["file"] = parts[0].replace(".001", "")
        print("      %s 超 %s，已切 %d 卷（%s）"
              % (out.name, human(volume_max), len(parts),
                 " / ".join(parts)))
    return asset, files


_PKG_DESC = {
    "app": "主程序（PyInstaller onefile，内嵌全部运行时依赖）",
    "code": "自研源码与字幕校准脚本（日常迭代主要变这一层）",
    "docs": "文档与第三方组件许可声明",
    "tools": "工具脚本（AI 客户端、开源依赖下载器）",
}


def _sha256_path(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def read_version():
    """从 src/video_toolbox_qt.py 读 VERSION（唯一版本号源头）。

    2026-10-13：原正则会读不出预发布号（如 2.1.0-beta.1 匹配失败直接
    sys.exit），而 vt_version_index 与 --state 都支持预发布——
    两条能力在发布脚本里断链。改为取任意非引号串，再用
    vindex.parse_version 校验（单一真相源）。
    """
    import re
    p = ROOT / "src" / "video_toolbox_qt.py"
    m = re.search(r'VERSION\s*=\s*"([^"]+)"', p.read_text(encoding="utf-8"))
    if not m:
        sys.exit("读不到 src/video_toolbox_qt.py 里的 VERSION")
    ver = m.group(1).strip()
    try:
        vindex.parse_version(ver)
    except vindex.VersionError as ex:
        sys.exit("VERSION 不是合法版本号：%s" % ex)
    return ver


def find_updater():
    """找在线安装器 exe（installer_online\视频工具箱_在线安装_v<版本>.exe）。"""
    ver = read_version()
    p = DIST / ("视频工具箱_在线安装_v%s.exe" % ver)
    return p if p.is_file() else None


# ---------------------------------------------------------------- 版本索引


def fetch_remote_index(base_url, log=print, force_first=False, tries=3):
    """取远端已有的 index.json。

    ⚠ 只有 **404** 才算真·首次发版（造空索引）。网络错 / 5xx / 坏 JSON
    一律指数退避重试，仍失败则**拒绝发布**——旧实现把这些失败都按
    "首次发版"处理，空索引会在上传时整体覆盖远端，把全版本目录抹掉
    （资产还在 Release 上，但索引没了就没人找得到，换机器不可恢复）。
    `--force-first` 供确认过后果的手工场景显式放行。
    """
    if not base_url:
        return vindex.new_index()
    url = base_url.rstrip("/") + "/" + vindex.INDEX_NAME
    last = None
    for attempt in range(1, tries + 1):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "VideoToolbox-online-release"})
            with urllib.request.urlopen(req, timeout=60) as r:
                raw = r.read()
            break
        except urllib.error.HTTPError as e:
            if e.code == 404:
                log("   [info] 远端无版本索引，按首次发版处理")
                return vindex.new_index()
            last = "HTTP %s" % e.code
        except Exception as e:  # noqa: BLE001
            last = repr(e)[:200]
        if attempt < tries:
            log("   [warn] 取远端索引失败（%s），%d/%d 重试中…"
                % (last, attempt, tries))
            time.sleep(min(2 ** attempt * 2, 15))
    else:
        if force_first:
            log("   [warn] 取远端索引持续失败（%s），--force-first 放行："
                "按首次发版处理（历史版本目录将丢失！）" % last)
            return vindex.new_index()
        sys.exit("取远端版本索引失败（%s）。\n"
                 "    拒绝发布：此时若按首次发版处理，上传的空索引会把远端\n"
                 "    全版本目录整体抹掉（资产还在但不可发现、不可回滚）。\n"
                 "    请修好网络/代理后重试；确要认真空索引发版，显式加 --force-first。"
                 % last)
    try:
        idx = vindex.parse_index(raw)
    except Exception as e:  # noqa: BLE001
        if force_first:
            log("   [warn] 远端索引解析失败（%s），--force-first 放行" % e)
            return vindex.new_index()
        sys.exit("远端版本索引解析失败（%s）。拒绝发布（同上）。" % e)
    log("   远端索引已有 %d 个版本：%s"
        % (len(idx.get("versions", [])),
           "、".join(e["version"] for e in idx.get("versions", [])[:6])
           or "（空）"))
    return idx


def merge_remote_versions(local_idx, remote_idx, log=print):
    """把远端索引里的版本记录并入本地索引（**合并而非覆盖**）。

    ⚠ 这是"别把远端历史弄丢"的关键：本地索引只在本机累积，换机器
    / 清理过 out 目录后就是空的。若直接拿本地空索引覆盖远端，
    历史版本会从目录里消失——虽然资产还在 Release 上，但没人再找得到。
    """
    n = 0
    for e in (remote_idx or {}).get("versions", []):
        if not vindex.find_version(local_idx, e.get("version")):
            try:
                vindex.upsert_version(local_idx, dict(e))
                n += 1
            except Exception as ex:  # noqa: BLE001
                log("   [warn] 跳过远端版本 %r：%s" % (e.get("version"), ex))
    if n:
        log("   已从远端索引并入 %d 个历史版本" % n)
    return local_idx


def prune_index(idx, keep, log=print):
    """把索引裁到最近 keep 个版本（按版本号降序）。

    ⚠ 只动**目录条目**，不动 Release 上的资产——资产清理在
    `cleanup_old_assets()` 里按裁剪后的索引决定，两者必须同参调用，
    否则会出现"目录里有、资产已删"的死链。
    裁剪后同步清理 channels：latest/stable 指向被裁版本时清除，
    让 resolve 的兜底（可见里最高）顶上来，别留悬空指针。
    """
    vers = sorted(idx.get("versions", []),
                  key=lambda e: vindex.vkey(e["version"]), reverse=True)
    if len(vers) <= keep:
        return idx
    drop = vers[keep:]
    idx["versions"] = vers[:keep]
    for e in drop:
        log("   索引移除旧版本 v%s" % e["version"])
    ch = idx.get("channels") or {}
    for k, v in list(ch.items()):
        if not v or vindex.find_version(idx, v) is None:
            log("   通道 %s 指向被裁/不存在的版本 %r，已清除" % (k, v))
            ch.pop(k, None)
    return idx


# ---------------------------------------------------------------- 上传


def _token():
    # 每次 api() 都 spawn 一次 gh auth token 太浪费（一次清理几十个子进程），
    # 进程内缓存——token 有效期远长于一次发布。
    global _TOKEN_CACHE
    if _TOKEN_CACHE:
        return _TOKEN_CACHE
    t = subprocess.run(["gh", "auth", "token"], capture_output=True,
                       text=True).stdout.strip()
    if not t:
        sys.exit("取不到 gh token（先 gh auth login）")
    _TOKEN_CACHE = t
    return t


_TOKEN_CACHE = ""


def api(method, path, payload=None, raw=None, ctype="application/json",
        host="https://api.github.com", timeout=1800, extra_headers=None):
    tok = _token()
    data = raw if raw is not None else (
        json.dumps(payload).encode() if payload is not None else None)
    url = path if path.startswith("http") else host + path
    headers = {
        "Authorization": "Bearer " + tok,
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "VideoToolbox-online-release",
        "Content-Type": ctype,
    }
    if extra_headers:
        headers.update(extra_headers)
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            b = r.read().decode("utf-8", "replace")
            # 502/网关页可能返回 HTML——json.loads 炸 traceback 不如给可读错误
            try:
                return r.status, (json.loads(b) if b.strip() else {})
            except ValueError:
                return r.status, b[:400]
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")[:400]


def find_release(tag):
    c, d = api("GET", f"/repos/{OWNER}/{REPO}/releases/tags/"
               + urllib.parse.quote(tag, safe=""))
    return d if c == 200 else None


def ensure_release(tag, name, body):
    d = find_release(tag)
    if d:
        return d
    c, d = api("POST", f"/repos/{OWNER}/{REPO}/releases", {
        "tag_name": tag, "name": name, "body": body, "prerelease": True})
    if c not in (200, 201):
        sys.exit("建 release 失败 HTTP %s：%s" % (c, d))
    return d


def drop_asset(rel_id, name):
    c, d = api("GET", f"/repos/{OWNER}/{REPO}/releases/{rel_id}/assets")
    if c != 200:
        return False
    for a in d:
        if a["name"] == name:
            api("DELETE", f"/repos/{OWNER}/{REPO}/releases/assets/{a['id']}")
            return True
    return False


def upload_asset(rel_id, path, name, tries=4):
    """上传资产。带重试 + curl 备用通道。

    ⚠ 本机对 uploads.github.com 的**大文件**上传会偶发 TLS 中断
      （`EOF occurred in violation of protocol (_ssl.c:2427)`）——
      几字节的探测上传从不失败，99MB 的实测会断。故这里：
        1) urllib 重试若干次（指数退避）；
        2) 仍失败则回退 curl（`--data-binary @file`，与项目其它脚本同思路）。
    """
    size = os.path.getsize(path)
    print("   上传 %-34s %10s ..." % (name, human(size)), end="", flush=True)
    url = (f"https://uploads.github.com/repos/{OWNER}/{REPO}"
           f"/releases/{rel_id}/assets?name={urllib.parse.quote(name)}")

    for attempt in range(1, tries + 1):
        t0 = time.time()
        try:
            # 流式发送：1.5GB 卷整读进内存 + 重试叠加有 MemoryError 风险。
            # http.client 对文件对象会边读边发，但需自带 Content-Length。
            with open(path, "rb") as fh:
                c, d = api("POST", url, raw=fh, ctype="application/octet-stream",
                           extra_headers={"Content-Length": str(size)})
        except Exception as e:  # noqa: BLE001  —— 网络层异常（非 HTTP 状态码）
            c, d = 0, repr(e)[:200]
        dt = time.time() - t0
        if c in (200, 201):
            print(" OK  %.1fs (%.1f MB/s)" % (dt, size / 1048576 / max(dt, .01)))
            return True
        if c == 422 and "already_exists" in str(d):
            print(" 已存在")
            return True
        print("\n      第 %d/%d 次失败（HTTP %s）：%s" % (attempt, tries, c, d))
        if attempt < tries:
            time.sleep(min(2 ** attempt * 3, 20))

    print("      改用 curl 通道 ...", end="", flush=True)
    tok = _token()
    t0 = time.time()
    r = subprocess.run(
        ["curl", "-sS", "-X", "POST",
         "-H", "Authorization: Bearer " + tok,
         "-H", "Accept: application/vnd.github+json",
         "-H", "X-GitHub-Api-Version: 2022-11-28",
         "-H", "User-Agent: VideoToolbox-online-release",
         "-H", "Content-Type: application/octet-stream",
         "--data-binary", "@" + os.path.abspath(path),
         url], capture_output=True)
    dt = time.time() - t0
    body = (r.stdout or b"").decode("utf-8", "replace")
    if r.returncode == 0 and ('"state"' in body or '"id"' in body):
        print(" OK  %.1fs (%.1f MB/s)  [curl]"
              % (dt, size / 1048576 / max(dt, .01)))
        return True
    print(" 失败 rc=%d：%s" % (r.returncode, (body or r.stderr.decode(
        "utf-8", "replace"))[:300]))
    return False


def _asset_version(name):
    """从资产名解析版本号（含预发布）；解析不出返回 None。

    形如 v主.次.修(预发布)?- —— 预发布段必须一起吃掉，否则
    "v2.1.0-beta.1-app.zip" 会被当成 2.1.0 正式版分组，与 keep_set
    里的 "2.1.0-beta.1" 永远对不上（白名单静默失配）。
    """
    import re
    m = re.match(r"v(\d+)\.(\d+)\.(\d+(?:[-.+][0-9A-Za-z.\-]+)?)-", name)
    if not m:
        return None
    ver = m.group(1)
    try:
        vindex.parse_version(ver)
    except vindex.VersionError:
        return None
    return ver


def _keep_key(v):
    """白名单命中键：版本号元组级（吃 v 前缀/缺位/预发布差异）。"""
    try:
        return ("v", vindex.parse_version(v))
    except vindex.VersionError:
        return ("s", v)


def cleanup_old_assets(rel_id, keep, keep_versions=None):
    """清理旧版资产：只保留最近 keep 个版本的文件（按资产名里的版本号判代）。

    manifest.json / index.json 与在线安装器永远保留。版本号按
    版本序排序，解析不出版本号的资产不动（宁可留垃圾也不误删）。

    ⚠⚠ `keep_versions` 是**硬白名单**：索引里还列着的版本，其资产永不删。
    没有这层保护，「全版本通用」就是假的——目录里写着 v1.18.0 可装、
    资产却早被清掉，用户点了装才 404。宁可多占空间也不能留死链。
    白名单比较走 `_keep_key`（版本号元组）而非字符串精确匹配，
    防止索引存 "v1.19.0"/短写法时静默失配。
    """
    keep_keys = {_keep_key(v) for v in (keep_versions or ())}
    c, d = api("GET", f"/repos/{OWNER}/{REPO}/releases/{rel_id}/assets")
    if c != 200:
        print("   [warn] 取资产列表失败，跳过清理")
        return
    vers = {}
    for a in d:
        v = _asset_version(a["name"])
        if v:
            vers.setdefault(v, []).append(a)
    if len(vers) <= keep:
        return
    for v in sorted(vers, key=vindex.vkey, reverse=True)[keep:]:
        if _keep_key(v) in keep_keys:
            print("   保留 v%s（索引仍在引用）" % v)
            continue
        for a in vers[v]:
            print("   清理旧资产 v%s：%s" % (v, a["name"]))
            api("DELETE", f"/repos/{OWNER}/{REPO}/releases/assets/{a['id']}")


# ---------------------------------------------------------------- 主流程


def _positive_int(text):
    v = int(text)
    if v < 1:
        raise argparse.ArgumentTypeError("必须 ≥ 1（收到 %r）" % text)
    return v


def main():
    ap = argparse.ArgumentParser(description="发布在线更新包（平铺资产）")
    ap.add_argument("--tag", default=DEFAULT_TAG, help="固定的 Release tag")
    ap.add_argument("--out", default=str(DIST), help="zip 与 manifest 的输出目录")
    ap.add_argument("--notes", default="", help="写进 manifest 的更新说明")
    ap.add_argument("--remove", default="",
                    help="本次应删除的安装相对路径（逗号分隔；升级时要清理的旧文件）")
    ap.add_argument("--volume-max", type=_positive_int, default=DEFAULT_VOLUME_MAX,
                    help="单卷字节上限，超过自动分卷（默认 1.5GB；≤0 曾让 read(0) "
                         "返回空、parts[0] 直接 IndexError）")
    ap.add_argument("--keep", type=_positive_int, default=3,
                    help="Release 上保留最近几个版本的资产（默认 3；"
                         "仍在索引里的版本不受此限，见 --index-keep）")
    ap.add_argument("--state", default="stable", choices=list(vindex.ALL_STATES),
                    help="本次版本在索引里的状态（默认 stable；"
                         "发版后发现严重问题用 yanked 撤回：目录里除名但资产保留）")
    ap.add_argument("--min-updater", default="",
                    help="安装本版本所需的在线安装器最低版本（留空=不限制）")
    ap.add_argument("--index-keep", type=_positive_int, default=10,
                    help="版本索引里保留最近几个版本（默认 10；裁空后所有"
                         "客户端都会报「没有 versions 列表」）")
    ap.add_argument("--force-first", action="store_true",
                    help="取远端索引持续失败/解析失败时仍按首次发版放行"
                         "（默认拒绝发布，防止空索引覆盖抹掉历史目录）")
    ap.add_argument("--dry-run", action="store_true", help="只打包+出清单，不上传")
    args = ap.parse_args()

    ver = read_version()
    print("== 打包在线更新包 v%s（schema 2）==" % ver)
    check_packages_in_sync()
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    base_url = (f"https://github.com/{OWNER}/{REPO}/releases/download/"
                f"{urllib.parse.quote(args.tag, safe='')}/")
    assets = []
    files_all = {}
    for pkg, items in PACKAGES.items():
        print("   包 %s …" % pkg)
        asset, files = build_package(pkg, items, out_dir, args.volume_max)
        print("      %s  %d 个文件  %s%s"
              % (asset["file"], asset["entries"], human(asset["size"]),
                 "（%d 卷）" % len(asset.get("parts", []))
                 if asset.get("parts") else ""))
        assets.append(asset)
        files_all.update(files)

    updater = None
    up = find_updater()
    if up:
        # GitHub Release 资产名**不支持中文**：中文名会被平台强制净化成
        # `_._v2.3.0.exe`（2026-10-15 实测，PATCH 改名同样被拦），与
        # manifest 记录对不上导致 updater 下载 404。远端一律用 ASCII
        # 资产名 `asset`，`file` 保留中文本地名（安装目录里的落地名）。
        updater = {"file": up.name,
                   "asset": "vt_online_setup_v%s.exe" % ver,
                   "size": up.stat().st_size,
                   "sha256": _sha256_path(up)}
        # file:// 自测的 updater 下载按 manifest 的 asset（ASCII）名找文件：
        # 本地暂存区放一份同名副本，与远端资产布局一致（sha256 相同）。
        # 缺了它，--dry-run 后的离线自检会在 ensure_updater 一步找不到文件
        # ——组件全部落地、只炸最后一步，rc=1 的症状极具迷惑性。
        shutil.copy2(up, out_dir / updater["asset"])
        print("   更新器 %s → %s  %s"
              % (up.name, updater["asset"], human(up.stat().st_size)))
    else:
        print("   [warn] 找不到在线安装器 exe（%s），manifest 将不含 updater 条目"
              % (DIST / ("视频工具箱_在线安装_v%s.exe" % ver)))

    manifest = {
        "schema": 2, "app": "视频工具箱", "version": ver,
        "released": time.strftime("%Y-%m-%d %H:%M:%S"),
        "base_url": base_url, "assets": assets,
        "files": files_all,
        "remove": [s.strip().replace("\\", "/") for s in args.remove.split(",")
                   if s.strip()],
        "notes": args.notes or ("视频工具箱 v%s 在线更新包" % ver),
    }
    if updater:
        manifest["updater"] = updater

    # 两份内容**逐字节相同**：
    #   manifest-<版本>.json  每版本留档，永不覆盖 —— 装任意版本 / 回滚靠它
    #   manifest.json         最新版别名，老客户端（只认这个名字）仍能工作
    text = json.dumps(manifest, ensure_ascii=False, indent=1)
    mf_ver = out_dir / (vindex.MANIFEST_TEMPLATE % ver)
    mf_ver.write_text(text, encoding="utf-8")
    mf = out_dir / "manifest.json"
    mf.write_text(text, encoding="utf-8")
    print("   清单留档 %s；别名 manifest.json" % mf_ver.name)

    # ------------------------------------------------------ 版本索引
    # ⚠ 先取远端已有索引并**合并**：本机索引只在本机累积，换机器或清过
    #   out 目录就是空的，直接覆盖会把历史版本从目录里抹掉。
    #   取不到（非 404）默认拒绝发布，--force-first 显式放行。
    remote = fetch_remote_index(base_url, force_first=args.force_first)
    idx = merge_remote_versions(vindex.new_index("视频工具箱", base_url),
                                remote)
    vindex.upsert_version(idx, {
        "version": ver,
        "manifest": mf_ver.name,
        "released": manifest["released"],
        "notes": manifest["notes"],
        "state": args.state,
        "pkgs": [a["name"] for a in assets],
        "total_size": sum(int(a.get("size") or 0) for a in assets),
        "min_updater": args.min_updater or "",
    })
    prune_index(idx, args.index_keep)
    idx["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
    idx_path = out_dir / vindex.INDEX_NAME
    vindex.save_index(idx, idx_path)
    print("   版本索引 %d 个版本：%s"
          % (len(idx["versions"]),
             "、".join(e["version"] for e in idx["versions"][:6])
             + ("…" if len(idx["versions"]) > 6 else "")))

    print("\n== manifest ==")
    print("   %s" % mf_ver)
    print("   base_url = %s" % base_url)
    for a in assets:
        print("   %-6s %-26s %10s  %s%s"
              % (a["name"], a["file"], human(a["size"]), a["sha256"][:16] + "…",
                 "  parts=%d" % len(a["parts"]) if a.get("parts") else ""))
    print("   files 清单：%d 个文件" % len(files_all))
    if args.dry_run:
        print("\n（--dry-run：未上传。可直接用本地文件跑引导安装器自测：）")
        # ⚠ base-url 必须是**绝对**路径：相对路径拼出的 file:///build/...
        #   会让 url2pathname 解出一个不存在的盘符根，照着跑必定失败。
        print("   vt_online_setup.exe --manifest %s --base-url file:///%s "
              "--dir <临时目录>" % (mf_ver, out_dir.resolve().as_posix()))
        print("   选版本用 --index %s --version <版本号>"
              % (idx_path,))
        return 0

    print("\n== 上传到 Release %s ==" % args.tag)
    rel = ensure_release(args.tag, "【在线更新包】视频工具箱（固定 tag，随版本原地更新）",
                         "由 packaging/online_release/build_online_release.py 自动发布。\n"
                         "资产为平铺 zip + manifest.json，供 vt_online_setup.exe 使用。")
    print("   release id = %s" % rel["id"])
    ok = True
    for a in assets:
        for fname in (a.get("parts") or [a["file"]]):
            zp = out_dir / fname
            # 同名资产要先删再传（GitHub 不允许同名覆盖）
            if drop_asset(rel["id"], fname):
                print("   （删除同名旧资产 %s）" % fname)
            ok &= upload_asset(rel["id"], zp, fname)
    if updater:
        if drop_asset(rel["id"], updater["asset"]):
            print("   （删除同名旧资产 %s）" % updater["asset"])
        ok &= upload_asset(rel["id"], up, updater["asset"])
    # 每版本清单留档（装任意版本 / 回滚的定位依据）
    if drop_asset(rel["id"], mf_ver.name):
        print("   （删除同名旧资产 %s）" % mf_ver.name)
    ok &= upload_asset(rel["id"], mf_ver, mf_ver.name)
    # 最新版别名（老客户端只认这个名字）
    if drop_asset(rel["id"], "manifest.json"):
        print("   （删除旧的 manifest.json）")
    ok &= upload_asset(rel["id"], mf, "manifest.json")
    # 全版本目录
    if drop_asset(rel["id"], vindex.INDEX_NAME):
        print("   （删除旧的 %s）" % vindex.INDEX_NAME)
    ok &= upload_asset(rel["id"], idx_path, vindex.INDEX_NAME)

    if not ok:
        sys.exit("!! 有资产上传失败")
    # ⚠ 索引里还列着的版本，其资产**不许删**（否则目录里写着能装、点了 404）
    cleanup_old_assets(rel["id"], args.keep,
                       [e["version"] for e in idx.get("versions", [])])
    print("\n✅ 已发布：%s" % base_url)
    print("   manifest：%smanifest.json" % base_url)
    print("   ⚠ GitHub 资产下载会 302 跳转，CDN 生效通常几秒内")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
