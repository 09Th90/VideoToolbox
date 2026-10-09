# -*- coding: utf-8 -*-
# @version 1.18.2
"""安装目录 vs 仓库：全量字节级一致性核对。

判定：安装目录里「本应随包分发」的文件（iss [Files] 声明的那些），
必须与仓库源文件 sha256 完全一致。不一致即说明打包漏了或装了旧版。

用法：
    python scripts/dev/check_install_sync.py
    python scripts/dev/check_install_sync.py D:/VideoToolbox
"""
from __future__ import annotations

import hashlib
import io
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
#: HERE 已是 scripts/dev ⇒ 再上两层才是仓库根
ROOT = os.path.dirname(os.path.dirname(HERE))
ISS = os.path.join(ROOT, "packaging", "视频工具箱.iss")

#: 安装目录默认值（与 iss 的 DefaultDirName 一致）
DEFAULT_APP = r"D:\VideoToolbox"

SRC_RE = re.compile(r'^\s*Source:\s*"([^"]+)"\s*;\s*DestDir:\s*"\{app\}([^";]*)"')
SKIP_DIR_PARTS = ("tools\\python", "tools\\videocaptioner")


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for blk in iter(lambda: f.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


def collect_pairs():
    """从 iss 解析出 (仓库源文件, 安装后相对路径) 列表（只取单文件条目）。"""
    base = os.path.dirname(os.path.abspath(ISS))
    out = []
    for raw in io.open(ISS, encoding="utf-8", errors="replace"):
        m = SRC_RE.match(raw)
        if not m:
            continue
        src, destdir = m.group(1), m.group(2)
        if "*" in src or any(p in src for p in SKIP_DIR_PARTS):
            continue          # 通配/大目录另算，比对单个文件没意义
        repo = os.path.normpath(os.path.join(base, src.replace("\\", os.sep)))
        if not os.path.isfile(repo):
            continue
        # Inno 的 DestDir 只给**目录**，文件名沿用 Source 的 basename。
        # DestDir 末尾也可能带文件名（如 {app}\src\apply_vc_official.py）：
        # 此时若 basename 与目录名相同，说明它就是文件本身而非目录。
        name = os.path.basename(repo)
        dd = destdir.strip("\\").replace("\\", os.sep)
        if dd.endswith("/" + name) or dd == name:
            rel = dd                       # DestDir 直接就是文件路径
        else:
            rel = (dd + "/" + name) if dd else name
        out.append((repo, rel))
    return out


def _exe_version(exe: str) -> str:
    """从 exe 的 CArchive 里挖出 video_toolbox_qt 模块的 VERSION 常量。

    ⚠⚠ v1.18.2 新增。起因：安装目录曾被**外部**（便携测试目录 / 手工拷贝）
    整体覆盖成旧版 exe + 旧 src\，而 sha256 比对是「谁最后跑谁说了算」——
    只有在旧版覆盖**之后**主动跑本脚本才会发现。而用户在 UI 上看到的现象是
    「文案是旧的」（旧版才有「先执行 python ...」那句），此时该问的是
    「这个 exe 到底是哪一版」，而不是「它和 dist 一样吗」。

    做法：`video_toolbox_qt` 是 exe 的 **CArchive 顶层条目**（不在 PYZ 里，
    记忆里的老铁律），CArchiveReader.extract() 取回的是 **marshalled 字节**，
    要再 marshal.loads() 才是 code 对象；然后扫模块级 co_consts 里形如
    `x.y.z` 的字符串常量。比 sha256 更快，且能直接报出版本号。

    ⚠ 提取失败**不算失败**（返回 ""），交由 sha256 比对兜底——本函数是
    增强项，不能因为它反而让正常安装报红。
    """
    try:
        import marshal as _marshal
        import os as _os
        import re as _re

        from PyInstaller.archive.readers import CArchiveReader
        if not _os.path.isfile(exe):
            return ""
        co = _marshal.loads(CArchiveReader(exe).extract("video_toolbox_qt"))
        for k in getattr(co, "co_consts", ()):
            if isinstance(k, str) and _re.fullmatch(r"\d+\.\d+\.\d+", k):
                return k
        return ""
    except Exception:            # noqa: BLE001
        return ""


def main() -> int:
    app = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_APP
    if not os.path.isdir(app):
        print("安装目录不存在：", app)
        return 2

    pairs = collect_pairs()
    same = diff = missing = 0
    bad = []
    for repo, rel in pairs:
        inst = os.path.join(app, rel)
        if not os.path.isfile(inst):
            missing += 1
            bad.append(("缺失", rel))
            continue
        if sha256(repo) == sha256(inst):
            same += 1
        else:
            diff += 1
            bad.append(("不一致", rel))

    print("安装目录：", app)
    print("比对文件 =", len(pairs), " 一致 =", same,
          " 不一致 =", diff, " 缺失 =", missing)
    for why, rel in bad[:25]:
        print("   [%s] %s" % (why, rel))

    # ---- exe 版本指纹交叉核对（v1.18.2 新增）----
    # sha256 只说「一样/不一样」，看不出「装的到底是哪一版」。
    # 仓库声明的版本 = src\video_toolbox_qt.py 里的 VERSION =。
    repo_ver = ""
    try:
        import ast
        qt = os.path.join(ROOT, "src", "video_toolbox_qt.py")
        for node in ast.walk(ast.parse(io.open(qt, encoding="utf-8").read())):
            if (isinstance(node, ast.Assign)
                    and any(getattr(t, "id", "") == "VERSION" for t in node.targets)
                    and isinstance(node.value, ast.Constant)
                    and isinstance(node.value.value, str)):
                repo_ver = node.value.value
                break
    except Exception:            # noqa: BLE001
        pass

    inst_ver = _exe_version(os.path.join(app, "视频工具箱.exe"))
    print("exe 版本：仓库 = %s  安装版 = %s" % (repo_ver or "?", inst_ver or "未识别"))
    if repo_ver and inst_ver and repo_ver != inst_ver:
        print("   [版本不符] 安装目录的 exe 是 %s，仓库是 %s —— "
              "说明安装目录被旧版覆盖（外部拷贝/便携目录），重装即可"
              % (inst_ver, repo_ver))
        return 1
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
