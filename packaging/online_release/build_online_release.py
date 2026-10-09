# -*- coding: utf-8 -*-
# @version 1.18.3
"""把「在线更新包」发布成 GitHub Release 的**平铺资产**（替代 IFW 的在线仓库）。

====================================================================
与 IFW 路线的关系
====================================================================
`installer_src/build_online_installer.py` 走的是 Qt IFW：repogen 把组件打成
`<组件名>/<归档>.7z`，再由 binarycreator 生成在线安装器。那条路有**两个硬约束**：
  1. IFW 取归档的 URL 是 `<基址>/<组件名>/<归档>` —— **多一层目录**；
  2. 仓库要能承载它，只能放 gh-pages（有目录结构），而 gh-pages 走 git，
     **单文件 100 MiB 硬限**（主程序 exe 已 103MB，撞线）。
GitHub Releases 能放 2GB/资产、但**资产是平铺的**，装不下 IFW 的目录结构
（实测嵌套路径 404；带斜杠 tag 冒充目录会撞 git D/F 冲突）。

本脚本改走「平铺 + 自解压」：组件打成 **zip** 平铺上传，由自研的
`vt_online_setup.exe` 自己下载解压。于是：
  · 不再有 100 MiB 限制（单资产上限 2GB）；
  · 不再依赖 gh-pages 的目录结构；
  · 打包侧只剩「zip + manifest + 上传」三件事。

====================================================================
用法
====================================================================
    python packaging/online_release/build_online_release.py --dry-run   # 只打包+出清单
    python packaging/online_release/build_online_release.py             # 打包并上传
    python packaging/online_release/build_online_release.py --tag repo-latest
    python packaging/online_release/build_online_release.py --notes "本次更新…"

⚠ 资产文件名带版本号（`v1.18.0-base.zip`），**同一 tag 下可累积多版**，
  客户端按 manifest 取，不受影响；发布后建议手工清掉过老的版本资产。
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
#: 脚本位于 <仓库根>/packaging/online_release/，仓库根再上两级
ROOT = HERE.parent.parent
DIST = ROOT / "installer_online"

OWNER, REPO = "09Th90", "VideoToolbox"
DEFAULT_TAG = "repo-latest"

#: 组件 -> [(源路径(相对仓库根), zip 内相对路径)]。target 恒为安装目录根。
#: ⚠ 必须与 installer_src/build_online_installer.py 的 COMPONENTS 保持一致；
#:   本脚本启动时会 import 那个模块做一次比对，不一致直接报错（防止两边漂移）。
COMPONENTS = {
    "base": [
        ("dist/视频工具箱.exe", "视频工具箱.exe"),
        ("subtitle_calib_merged.py", "subtitle_calib_merged.py"),
        ("src", "src"),
        ("docs", "docs"),
        ("tools/ai_client.py", "tools/ai_client.py"),
        ("tools/download_open_source_deps.py", "tools/download_open_source_deps.py"),
    ],
}

#: 严禁进发布包的东西（v1.14.1 安全整改，沿用）
FORBIDDEN = ("github_proxy.yaml", "mihomo", "runtime.yaml", "cache.db",
             "config.yaml", "uploader_profile")

#: 超过这个大小就改用「存储」而非「压缩」——主程序 exe 是 PyInstaller onefile，
#: 内部已 zlib 压缩，deflate 再压一次只会白费 CPU（实测收益 0.06%）。
STORE_OVER = 8 * 1024 * 1024


def human(n):
    n = float(n)
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024 or u == "GB":
            return "%.1f %s" % (n, u)
        n /= 1024


def check_components_in_sync():
    """与 IFW 那份组件清单比对，防止两处漂移。"""
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
    # 只比「文件清单」，不比组件键名：IFW 那边是包名 com.videotoolbox.base，
    # 这边为了资产文件名短一些叫 base，属有意差异。
    if sorted(ifw.values()) != sorted(COMPONENTS.values()):
        print("   !! 组件文件清单与 IFW 版不一致，两边必须同步改：")
        print("      IFW:", ifw)
        print("      本脚本:", COMPONENTS)
        sys.exit(2)
    print("   ✓ 组件文件清单与 IFW 版一致（键名差异属有意：%s -> %s）"
          % (", ".join(ifw), ", ".join(COMPONENTS)))


def iter_files(src, dest_rel):
    """枚举一个源条目下的所有文件，产出 (绝对路径, zip 内相对路径)。"""
    src = Path(src)
    if src.is_file():
        yield src, dest_rel.replace("\\", "/")
        return
    for cur, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs if d not in ("__pycache__",)]
        rel = Path(cur).relative_to(src)
        for f in files:
            if f.endswith((".pyc", ".pyo")):
                continue
            p = Path(cur) / f
            z = (Path(dest_rel) / rel / f).as_posix()
            yield p, z


def build_zip(comp, items, out_dir):
    """按组件打一个 zip，返回 (zip 路径, 文件数, sha256, 大小)。"""
    ver = read_version()
    out = Path(out_dir) / ("v%s-%s.zip" % (ver, comp))
    n = 0
    bad = []
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for src_rel, dest_rel in items:
            src = ROOT / src_rel
            if not src.exists():
                print("   !! 源不存在：%s" % src)
                sys.exit(2)
            for ap, zn in iter_files(src, dest_rel):
                low = zn.lower()
                if any(b in low for b in FORBIDDEN):
                    bad.append(zn)
                    continue
                size = ap.stat().st_size
                method = (zipfile.ZIP_STORED if size >= STORE_OVER
                          else zipfile.ZIP_DEFLATED)
                # 固定时间戳，让同内容重复打包得到逐字节相同的 zip
                zi = zipfile.ZipInfo(zn, date_time=(2026, 1, 1, 0, 0, 0))
                zi.compress_type = method
                zi.external_attr = 0o644 << 16
                with open(ap, "rb") as fh:
                    zf.writestr(zi, fh.read())
                n += 1
    if bad:
        print("   !! 有 %d 个禁止入库的文件被跳过（请核对是否误配）：%s"
              % (len(bad), bad[:5]))
    h = hashlib.sha256()
    with open(out, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return out, n, h.hexdigest(), out.stat().st_size


def read_version():
    """从 src/video_toolbox_qt.py 读 VERSION（唯一版本号源头）。"""
    import re
    p = ROOT / "src" / "video_toolbox_qt.py"
    m = re.search(r'VERSION\s*=\s*"([\d.]+)"', p.read_text(encoding="utf-8"))
    if not m:
        sys.exit("读不到 src/video_toolbox_qt.py 里的 VERSION")
    return m.group(1)


# ---------------------------------------------------------------- 上传


def _token():
    t = subprocess.run(["gh", "auth", "token"], capture_output=True,
                       text=True).stdout.strip()
    if not t:
        sys.exit("取不到 gh token（先 gh auth login）")
    return t


def api(method, path, payload=None, raw=None, ctype="application/json",
        host="https://api.github.com", timeout=1800):
    tok = _token()
    data = raw if raw is not None else (
        json.dumps(payload).encode() if payload is not None else None)
    url = path if path.startswith("http") else host + path
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": "Bearer " + tok,
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "VideoToolbox-online-release",
        "Content-Type": ctype,
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            b = r.read().decode("utf-8", "replace")
            return r.status, (json.loads(b) if b.strip() else {})
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
            raw = open(path, "rb").read()
            c, d = api("POST", url, raw=raw, ctype="application/octet-stream")
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


# ---------------------------------------------------------------- 主流程


def main():
    ap = argparse.ArgumentParser(description="发布在线更新包（平铺资产）")
    ap.add_argument("--tag", default=DEFAULT_TAG, help="固定的 Release tag")
    ap.add_argument("--out", default=str(DIST), help="zip 与 manifest 的输出目录")
    ap.add_argument("--notes", default="", help="写进 manifest 的更新说明")
    ap.add_argument("--dry-run", action="store_true", help="只打包+出清单，不上传")
    args = ap.parse_args()

    ver = read_version()
    print("== 打包在线更新包 v%s ==" % ver)
    check_components_in_sync()
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    base_url = (f"https://github.com/{OWNER}/{REPO}/releases/download/"
                f"{urllib.parse.quote(args.tag, safe='')}/")
    assets = []
    for comp, items in COMPONENTS.items():
        print("   组件 %s …" % comp)
        zp, n, sha, size = build_zip(comp, items, out_dir)
        print("      %s  %d 个文件  %s" % (zp.name, n, human(size)))
        assets.append({
            "name": comp, "file": zp.name, "size": size, "sha256": sha,
            "entries": n, "target": "",
            "desc": "主程序、界面源码、文档与第三方组件声明（必装）",
        })

    manifest = {
        "schema": 1, "app": "视频工具箱", "version": ver,
        "released": time.strftime("%Y-%m-%d %H:%M:%S"),
        "base_url": base_url, "assets": assets,
        "notes": args.notes or ("视频工具箱 v%s 在线更新包" % ver),
    }
    mf = out_dir / "manifest.json"
    mf.write_text(json.dumps(manifest, ensure_ascii=False, indent=1),
                  encoding="utf-8")
    print("\n== manifest ==")
    print("   %s" % mf)
    print("   base_url = %s" % base_url)
    for a in assets:
        print("   %-6s %-24s %10s  %s" % (a["name"], a["file"],
                                          human(a["size"]), a["sha256"][:16] + "…"))
    if args.dry_run:
        print("\n（--dry-run：未上传。可直接用本地 manifest 跑引导安装器自测）")
        return 0

    print("\n== 上传到 Release %s ==" % args.tag)
    rel = ensure_release(args.tag, "【在线更新包】视频工具箱（固定 tag，随版本原地更新）",
                         "由 packaging/online_release/build_online_release.py 自动发布。\n"
                         "资产为平铺 zip + manifest.json，供 vt_online_setup.exe 使用。")
    print("   release id = %s" % rel["id"])
    ok = True
    for a in assets:
        zp = out_dir / a["file"]
        # 同名资产要先删再传（GitHub 不允许同名覆盖）
        if drop_asset(rel["id"], a["file"]):
            print("   （删除同名旧资产 %s）" % a["file"])
        ok &= upload_asset(rel["id"], zp, a["file"])
    if drop_asset(rel["id"], "manifest.json"):
        print("   （删除旧的 manifest.json）")
    ok &= upload_asset(rel["id"], mf, "manifest.json")

    if not ok:
        sys.exit("!! 有资产上传失败")
    print("\n✅ 已发布：%s" % base_url)
    print("   manifest：%smanifest.json" % base_url)
    print("   ⚠ GitHub 资产下载会 302 跳转，CDN 生效通常几秒内")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
