# -*- coding: utf-8 -*-
# @version 1.17.0
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
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
