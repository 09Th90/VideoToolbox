# -*- coding: utf-8 -*-
# @version 1.19.0
r"""自检：exe 内的 onnxruntime 能否在**模拟 _MEIPASS 布局**下真正 import。

======================================================================
为什么需要这个自检（v1.18.2 新增，踩坑记录）
======================================================================
安装版点「录入声纹」报：
    ImportError: DLL load failed while importing onnxruntime_pybind11_state:
    动态链接库(DLL)初始化例程失败。

**难在它「查不出来」**：
  · `onnxruntime` 在 PYZ 里（模块清单齐全）——列清单看不出问题；
  · 三个 onnxruntime 文件（.dll / _providers_shared.dll / .pyd）都在，
    而且与打包环境里那份**字节完全一致**——比哈希也看不出问题；
  · 在**打包环境 / src\ 方式**下 import 一切正常——所以「src 方式自检」
    永远测不到这个 bug。
只有把 exe 解成 `_MEIPASS` 布局、并且**把 `PyQt5\\Qt5\\bin` 也加进
DLL 搜索路径**（这才是真实运行时的加载顺序），才会复现。

根因：exe 里同时存在两套同名 MSVC runtime，且 `PyQt5\\Qt5\\bin` 优先级更高：
    PyQt5\\Qt5\\bin\\MSVCP140.dll = 14.26（Qt 自带，2020 年）
    MSVCP140.dll（根目录）       = 14.50（onnxruntime 编译时依赖的）
onnxruntime.dll 链的是 14.50 的导出表，拿到 14.26 的实现 ⇒ DllMain 就失败。

用法：
    python scripts/dev/_selftest_exe_dll.py                 # 测 dist/ 那份
    python scripts/dev/_selftest_exe_dll.py D:/VideoToolbox/视频工具箱.exe
"""
from __future__ import annotations

import os
import re
import struct
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))

DEFAULT_EXE = os.path.join(ROOT, "dist", "视频工具箱.exe")

PROBE = '''\
import os, sys
me = sys.argv[1]
sys.path.insert(0, me)
os.add_dll_directory(me)
q = os.path.join(me, "PyQt5", "Qt5", "bin")
if os.path.isdir(q):
    os.add_dll_directory(q)
try:
    import onnxruntime as ort
    print("OK", ort.__version__)
except Exception as e:
    print("FAIL", type(e).__name__, str(e)[:200])
'''

#: 要从 exe 里解出来的三类文件 → _MEIPASS 里的目标子目录
_PATTERNS = [
    (r"^onnxruntime\\", "onnxruntime"),
    (r"^(msvcp140|msvcp140_1|vcruntime140|vcruntime140_1)\.dll$", ""),
    (r"^PyQt5\\Qt5\\bin\\(MSVCP140|MSVCP140_1|VCRUNTIME140)", "PyQt5/Qt5/bin"),
]


def file_version(blob: bytes) -> str:
    """从 PE 字节里读 VS_FIXEDFILEINFO 的文件版本号（避免引入 pefile 依赖）。"""
    k = blob.find(b"\xbd\x04\xef\xfe")          # VS_FFI_SIGNATURE
    if k < 0:
        return "?"
    ms, ls = struct.unpack("<II", blob[k + 8:k + 16])
    return "%d.%d.%d.%d" % ((ms >> 16) & 0xFFFF, ms & 0xFFFF,
                            (ls >> 16) & 0xFFFF, ls & 0xFFFF)


def build_mei(exe: str, mei: str) -> int:
    """把 exe 里的相关文件解成 _MEIPASS 布局，返回解出的文件数。"""
    from PyInstaller.archive.readers import CArchiveReader
    a = CArchiveReader(exe)
    n = 0
    for name in a.toc:
        for pat, sub in _PATTERNS:
            if re.match(pat, name, re.I):
                dst = (os.path.join(mei, sub, os.path.basename(name)) if sub
                       else os.path.join(mei, os.path.basename(name)))
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                with open(dst, "wb") as f:
                    f.write(a.extract(name))
                n += 1
                break
    return n


def check_msvc_conflict(exe: str) -> int:
    """比对 Qt5\\bin 与 _MEIPASS 根目录下同名 MSVC DLL 的版本。

    Qt5\\bin 优先级更高，若它更旧就会顶掉新版 ⇒ onnxruntime 加载失败。
    """
    from PyInstaller.archive.readers import CArchiveReader
    a = CArchiveReader(exe)
    root, qtbin = {}, {}
    for name in a.toc:
        bn = os.path.basename(name).lower()
        if not re.match(r"^(msvcp140|msvcp140_1|vcruntime140|vcruntime140_1)\.dll$", bn):
            continue
        v = file_version(a.extract(name))
        d = os.path.dirname(name).replace("\\", "/").lower()
        if d.startswith("pyqt5/qt5/bin"):
            qtbin[bn] = v
        elif not d.strip("/"):
            root[bn] = v
    print("  MSVC runtime 版本：")
    for bn in sorted(set(root) | set(qtbin)):
        r, q = root.get(bn, "—"), qtbin.get(bn, "—")
        print("    %-20s 根目录=%-16s Qt5\\bin=%s" % (bn, r, q))

    bad = []
    for bn, qv in qtbin.items():
        rv = root.get(bn)
        if rv and qv != rv:
            bad.append("%s：Qt5\\bin(%s) 比根目录(%s)旧 ⇒ 会被优先加载顶掉新版"
                       % (bn, qv, rv))
    for msg in bad:
        print("  [FAIL] " + msg)
    return len(bad)


def main() -> int:
    exe = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_EXE
    if not os.path.isfile(exe):
        print("exe 不存在：", exe)
        return 2

    print("exe：", exe)
    print()
    print("[1] MSVC runtime 冲突检查（静态）")
    conflicts = check_msvc_conflict(exe)

    print()
    print("[2] 模拟 _MEIPASS 布局实跑 import（动态，唯一权威判据）")
    mei = tempfile.mkdtemp(prefix="_selftest_dll_")
    try:
        n = build_mei(exe, mei)
        print("    解出 %d 个文件" % n)
        probe = os.path.join(mei, "_probe.py")
        with open(probe, "w", encoding="utf-8") as f:
            f.write(PROBE)
        import subprocess
        r = subprocess.run([sys.executable, probe, mei],
                           capture_output=True, text=True)
        out = (r.stdout or "").strip() or (r.stderr or "").strip()[:300]
        print("    " + out)
        ok = out.startswith("OK")
        if not ok:
            print("    [FAIL] exe 内 onnxruntime 无法加载 —— "
                  "检查 Qt5\\bin 的旧 MSVC runtime")
    finally:
        import shutil
        shutil.rmtree(mei, ignore_errors=True)

    print()
    if conflicts or not ok:
        print("结论：FAIL（%d 处版本冲突%s）"
              % (conflicts, "" if ok else " + 动态加载失败"))
        return 1
    print("结论：PASS（MSVC 无冲突 + exe 内 onnxruntime 可加载）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())