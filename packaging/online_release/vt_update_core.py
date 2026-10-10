# -*- coding: utf-8 -*-
# @version 1.19.0
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

于是改为：**自己下载、自己解压**。好处是资产可以完全平铺，从而
吃满 GitHub Releases 的 **2GB/资产**上限，`gh-pages` 那条 **100 MiB 单文件**
硬限就此消失（那是本模块存在的直接原因）。

====================================================================
发布形态（与 build_online_release.py 约定）
====================================================================
固定 tag 的 Release（默认 `repo-latest`）下挂**平铺**资产：

    manifest.json                  ← 版本 + 资产清单（小，几百字节）
    v1.18.0-base.zip               ← 组件包（大，可到 2GB）

manifest 结构（schema=1）：
    {
      "schema": 1, "app": "视频工具箱", "version": "1.18.0",
      "released": "2026-10-08 23:00:00",
      "base_url": "https://github.com/.../releases/download/repo-latest/",
      "assets": [
        {"name": "base", "file": "v1.18.0-base.zip",
         "size": 103013033, "sha256": "…", "entries": 10,
         "target": "", "desc": "主程序、界面源码、文档"}
      ],
      "notes": "…"
    }

`target` 是相对安装目录的解压根（空串 = 安装目录本身）。
`base_url` 与资产同源，客户端只需把它和 `file` 拼起来。

⚠ 本模块**不 import 任何第三方库**（只用标准库），这样：
    · 引导安装器可以打成很小的单文件 exe；
    · 纯逻辑能被 `_selftest_online_setup.py` 直接单测，不需要网络。
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import zipfile

#: 默认 manifest 地址（固定 tag，随版本原地更新）
DEFAULT_MANIFEST_URL = ("https://github.com/09Th90/VideoToolbox/releases/"
                        "download/repo-latest/manifest.json")
#: 默认安装目录（与 视频工具箱.iss 的 DefaultDirName 保持一致）
DEFAULT_DIR = r"D:\VideoToolbox"
#: 下载分块
CHUNK = 1 << 20


class UpdateError(RuntimeError):
    """可预期的失败（网络、校验不符、磁盘、权限…），UI 直接显示其文本。"""


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


# ------------------------------------------------------------------ manifest


def load_manifest(src):
    """读 manifest。`src` 可以是 http(s) URL、本地路径或 file:// URL。

    ⚠ 支持本地路径/`file://` 是为了**离线自测**：不必真的发一版才能验流程。
    """
    import urllib.parse
    import urllib.request
    if src.startswith("http://") or src.startswith("https://"):
        req = urllib.request.Request(src, headers={
            "User-Agent": "VideoToolbox-updater",
            "Accept": "application/json",
        })
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                raw = r.read()
        except Exception as e:  # noqa: BLE001
            raise UpdateError("取更新清单失败：%s\n（%s）" % (e, src))
    else:
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
    if not isinstance(m, dict) or m.get("schema") != 1:
        raise UpdateError("更新清单 schema 不受支持：%r" % m.get("schema"))
    if not m.get("version") or not isinstance(m.get("assets"), list):
        raise UpdateError("更新清单缺 version / assets")
    m.setdefault("base_url", "")
    return m


def asset_url(manifest, asset):
    """把 manifest.base_url 与资产文件名拼成下载地址。"""
    base = (manifest.get("base_url") or "").rstrip("/")
    if not base:
        raise UpdateError("更新清单里没有 base_url，无法定位资产")
    return base + "/" + asset["file"]


# ------------------------------------------------------------------ 下载


def download(url, dest, progress=None, expect_size=None):
    """下载到 dest（先写 .part 再改名，中断不会留半成品）。

    progress 为 (已下, 总数或 -1) 回调；总数取自 Content-Length，
    取不到就传 -1（GitHub 的资产下载会给，但不强依赖）。
    """
    import urllib.request
    os.makedirs(os.path.dirname(os.path.abspath(dest)), exist_ok=True)
    tmp = dest + ".part"
    req = urllib.request.Request(url, headers={
        "User-Agent": "VideoToolbox-updater",
        "Accept": "application/octet-stream",
    })
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            total = int(r.headers.get("Content-Length") or 0)
            if expect_size and total and total != expect_size:
                # GitHub 资产下载经 302 跳转，Content-Length 是最终对象的长度，
                # 与 manifest 记录一致；不一致多半是清单过期，提前报错更省时间。
                raise UpdateError(
                    "远端文件大小与清单不符：清单 %d / 实际 %d" % (expect_size, total))
            if not total:
                total = -1
            done = 0
            with open(tmp, "wb") as fh:
                while True:
                    b = r.read(CHUNK)
                    if not b:
                        break
                    fh.write(b)
                    done += len(b)
                    if progress:
                        progress(done, total)
    except UpdateError:
        _quiet_remove(tmp)
        raise
    except Exception as e:  # noqa: BLE001
        _quiet_remove(tmp)
        raise UpdateError("下载失败：%s\n（%s）" % (e, url))
    os.replace(tmp, dest)
    return dest


def _quiet_remove(p):
    try:
        if os.path.isfile(p):
            os.remove(p)
    except OSError:
        pass


# ------------------------------------------------------------------ 解压


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


# ------------------------------------------------------------------ 安装目录


def detect_install_dir():
    """从注册表找已安装目录（Inno 写的 InstallLocation）；找不到返回 ''。

    ⚠ 只用标准库：优先读 `winreg`，非 Windows 或读不到就返回空。
    """
    if os.name != "nt":
        return ""
    try:
        import winreg
    except ImportError:
        return ""
    roots = (r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
             r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall")
    for root in roots:
        for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            try:
                with winreg.OpenKey(hive, root) as k:
                    for i in range(winreg.QueryInfoKey(k)[0]):
                        try:
                            sub = winreg.EnumKey(k, i)
                            if "videotoolbox" not in sub.lower() and \
                               "视频工具箱" not in sub:
                                continue
                            with winreg.OpenKey(k, sub) as sk:
                                loc, _ = winreg.QueryValueEx(sk, "InstallLocation")
                            if loc and os.path.isdir(loc):
                                return loc
                        except OSError:
                            continue
            except OSError:
                continue
    # 兜底：常见默认位置存在就用它
    if os.path.isdir(DEFAULT_DIR):
        return DEFAULT_DIR
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


# ------------------------------------------------------------------ 总流程


def apply_update(manifest, install_dir, work_dir, progress=None,
                 log=None, shortcuts=None):
    """按 manifest 下载并解压所有资产到 install_dir。

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

    total_bytes = sum(int(a.get("size") or 0) for a in manifest["assets"])
    if not free_space_ok(install_dir, total_bytes + total_bytes):
        raise UpdateError("目标盘剩余空间不足（约需 %s）" % human(total_bytes * 2))

    t0 = time.time()
    done_files = 0
    for idx, a in enumerate(manifest["assets"], 1):
        name = a.get("name") or a["file"]
        url = asset_url(manifest, a)
        zip_path = os.path.join(work_dir, a["file"])
        say("[%d/%d] %s（%s）" % (idx, len(manifest["assets"]), name,
                                  human(int(a.get("size") or 0))))

        if os.path.isfile(zip_path) and a.get("sha256"):
            if sha256_file(zip_path) == a["sha256"]:
                say("    本地缓存校验一致，跳过下载")
            else:
                _quiet_remove(zip_path)
        if not os.path.isfile(zip_path):
            say("    下载 %s" % url)
            download(url, zip_path,
                     progress=(lambda d, t, _i=idx: progress and progress(
                         "下载 %s" % name, d, t)),
                     expect_size=int(a.get("size") or 0) or None)

        if a.get("sha256"):
            got = sha256_file(zip_path)
            if got != a["sha256"]:
                raise UpdateError(
                    "sha256 校验不通过，已中止：\n  期望 %s\n  实际 %s\n（%s）"
                    % (a["sha256"], got, a["file"]))
            say("    sha256 校验一致 ✓")

        target = os.path.join(install_dir, a.get("target") or "")
        say("    解压到 %s" % target)
        n = extract_zip(zip_path, target,
                        progress=(lambda i, t, _i=idx: progress and progress(
                            "解压 %s" % name, i, t)))
        done_files += n
        say("    解开 %d 个文件" % n)

    if shortcuts:
        made = create_shortcuts(install_dir, **shortcuts)
        say("    快捷方式：%d 个" % made)

    return {"version": manifest.get("version"), "files": done_files,
            "seconds": round(time.time() - t0, 1), "dir": install_dir}
