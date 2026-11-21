#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# @version 3.1.5
"""自更新「被锁文件延迟交换」自检（2026-11-20 用户报障修复）。

报障：主程序进程内自更新时 apply_staging 第一遍 rename
`_internal/base_library.zip` → .vtold 抛 WinError 32（bootloader 以无
FILE_SHARE_DELETE 方式持有该数据文件），整体回滚＝更新永远失败。
修复：被锁文件延迟到主进程退出后由批处理交换（_vt_pending）。

覆盖：
  · 被锁文件跳过 rename/落地，旧版原样保留，其余文件正常落地
  · _vt_pending 暂存 + 清单（mbcs）+ 退出后批处理真的能换成功
  · reconciling：本次落地的 rel 作废旧 pending（防降级）；无关旧 pending 保留
  · schedule_relaunch 模板嵌入 pending 行不炸格式
  · 落地失败整体回滚不受影响（mock move 第二步炸）

不联网。用法：tools/python/python.exe scripts/dev/_selftest_update_pending.py
"""
import os
import shutil
import subprocess
import sys
import tempfile
from unittest import mock

_SRC = os.path.join(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))), "src")
_PKG = os.path.join(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))), "packaging", "online_release")
sys.path.insert(0, _SRC)
sys.path.insert(0, _PKG)
os.environ["VT_NO_PIPELINE"] = "1"

import vt_update_core as core  # noqa: E402

FAILS = []


def check(name, cond, extra=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}"
          f"{(' -> ' + str(extra)) if extra else ''}")
    if not cond:
        FAILS.append(name)


def _write(p, text):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(text)


def _read(p):
    with open(p, encoding="utf-8") as fh:
        return fh.read()


def _mk(staging, install, ver):
    """三个文件：base_library.zip（将被锁）/ foo.dll / code/a.py。"""
    rels = ["_internal/base_library.zip", "_internal/foo.dll", "code/a.py"]
    for rel in rels:
        _write(os.path.join(staging, rel.replace("/", os.sep)), "NEW-" + ver)
        _write(os.path.join(install, rel.replace("/", os.sep)), "OLD-" + ver)
    files = {rel: {"pkg": ("code" if rel.startswith("code/") else "app")}
             for rel in rels}
    return rels, {"schema": 2, "version": ver, "files": files}


def main():
    print("== 自更新被锁文件延迟交换自检 ==")
    tmp = tempfile.mkdtemp(prefix="vt_pend_")
    install = os.path.join(tmp, "install")
    staging = os.path.join(tmp, "staging")
    work = os.path.join(tmp, "work")
    os.makedirs(work)
    rels, man = _mk(staging, install, "v1")
    locked = os.path.join(install, "_internal", "base_library.zip")

    # ---- 1. 被锁文件延迟，其余落地 ----
    fh = open(locked, "rb")          # 无 FILE_SHARE_DELETE：rename 必 32
    n = core.apply_staging(staging, install, man, {"app", "code"})
    check("落地计数不含被锁文件", n == 2, n)
    check("被锁文件旧版原样", _read(locked) == "OLD-v1")
    check("其余文件新版落地",
          _read(os.path.join(install, "_internal", "foo.dll")) == "NEW-v1"
          and _read(os.path.join(install, "code", "a.py")) == "NEW-v1")
    check("pending 清单命中被锁 rel",
          core.read_pending(install) == ["_internal/base_library.zip"],
          core.read_pending(install))
    pend_copy = os.path.join(install, core.PENDING_DIR,
                             "_internal", "base_library.zip")
    check("pending 暂存为新版", _read(pend_copy) == "NEW-v1")

    # ---- 2. 退出后批处理真的换成功 ----
    script = core.write_pending_batch(install, work, "vt_probe_absent.exe",
                                      restart=False)
    check("生成等待批处理", bool(script) and os.path.isfile(script))
    fh.close()                        # 模拟主进程退出释放锁
    r = subprocess.run(["cmd", "/c", script], capture_output=True, timeout=60)
    check("批处理退出码 0", r.returncode == 0, r.returncode)
    check("被锁文件换为新版", _read(locked) == "NEW-v1", _read(locked))
    check("pending 清单与暂存清掉",
          core.read_pending(install) == []
          and not os.path.exists(pend_copy))
    check("不留 .vtold 残骸", not os.path.exists(locked + ".vtold"))

    # ---- 3. reconciling：落地的 rel 作废旧 pending ----
    staging2 = os.path.join(tmp, "staging2")
    rels2, man2 = _mk(staging2, install, "v2")
    fh2 = open(locked, "rb")
    core.apply_staging(staging2, install, man2, {"app", "code"})
    check("二轮仍延迟且暂存覆盖为 v2", _read(pend_copy) == "NEW-v2")
    fh2.close()
    staging3 = os.path.join(tmp, "staging3")
    rels3, man3 = _mk(staging3, install, "v3")
    core.apply_staging(staging3, install, man3, {"app", "code"})
    check("三轮无锁落地后旧 pending 作废（防降级）",
          core.read_pending(install) == []
          and _read(locked) == "NEW-v3", _read(locked))

    # ---- 4. 无关旧 pending 保留 ----
    keep_rel = "docs/遗留.txt"
    _write(os.path.join(install, core.PENDING_DIR,
                        keep_rel.replace("/", os.sep)), "KEEP")
    lst = os.path.join(install, core.PENDING_DIR, core.PENDING_NAME)
    with open(lst, "w", encoding="mbcs", newline="\r\n") as f:
        f.write(keep_rel + "\n")
    staging4 = os.path.join(tmp, "staging4")
    _write(os.path.join(staging4, "code", "a.py"), "NEW-v4")
    _write(os.path.join(staging4, "_internal", "base_library.zip"), "NEW-v4")
    man4 = {"schema": 2, "version": "v4",
            "files": {"code/a.py": {"pkg": "code"},
                      "_internal/base_library.zip": {"pkg": "app"}}}
    fh4 = open(locked, "rb")         # 再锁住，逼出 deferred → reconciling 真跑
    core.apply_staging(staging4, install, man4, {"code", "app"})
    fh4.close()
    check("无关旧 pending 保留 + 新被锁 rel 入清单",
          sorted(core.read_pending(install)) == sorted(
              [keep_rel, "_internal/base_library.zip"]),
          core.read_pending(install))

    # ---- 5. schedule_relaunch 模板嵌入 pending 行 ----
    import vt_update_check as vuc
    lines = core.pending_batch_lines(install)
    body = vuc._REPLACE_SCRIPT % {
        "target": "T.exe", "new": "N.exe", "old": "O.exe", "backup": "O.exe",
        "image": "T.exe", "done": "D.txt", "pending": "\n".join(lines),
        "sys32": r"C:\Windows\system32"}
    check("模板嵌入 pending 行不炸格式", "VT_PEND" in body and ":wait" in body)

    # ---- 6. 回滚回归（mock move 第二步炸）----
    install6 = os.path.join(tmp, "install6")
    staging6 = os.path.join(tmp, "staging6")
    _write(os.path.join(install6, "code", "a.py"), "OLD\n")
    _write(os.path.join(install6, "code", "b.py"), "OLD2\n")
    _write(os.path.join(staging6, "code", "a.py"), "NEW\n")
    _write(os.path.join(staging6, "code", "b.py"), "NEW2\n")
    man6 = {"schema": 2, "version": "v6",
            "files": {"code/a.py": {"pkg": "code"},
                      "code/b.py": {"pkg": "code"}}}
    real_move = shutil.move
    calls = {"n": 0}

    def flaky(s, d):
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("磁盘被故意弄坏")
        return real_move(s, d)

    with mock.patch.object(shutil, "move", flaky):
        try:
            core.apply_staging(staging6, install6, man6, {"code"})
            check("落地失败抛 UpdateError", False)
        except core.UpdateError:
            check("落地失败抛 UpdateError", True)
    check("回滚后旧文件原样", _read(os.path.join(install6, "code", "a.py"))
          == "OLD\n" and _read(os.path.join(install6, "code", "b.py"))
          == "OLD2\n")

    shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n结果：FAIL {len(FAILS)}")
    if FAILS:
        print("失败项：", FAILS)
        sys.exit(1)
    print("OK")


if __name__ == "__main__":
    main()