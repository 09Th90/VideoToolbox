# -*- coding: utf-8 -*-
# @version 2.8.0
"""Measure update-dialog label geometry: every detail line must fit the
informativeText label's width (the old bug clipped lines mid-glyph)."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "src"))
os.environ["QT_QPA_PLATFORM"] = "offscreen"
_p = os.path.abspath(os.path.join(ROOT, "tools", "python", "Lib",
                                  "site-packages", "PySide6", "plugins"))
os.environ.setdefault("QT_QPA_PLATFORM_PLUGIN_PATH", _p)

import vt_update_check as u  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox, QLabel  # noqa: E402
from qfluentwidgets import PushButton  # noqa: E402

app = QApplication(sys.argv)

ok = [0]
bad = [0]


def chk(name, cond, extra=""):
    if cond:
        ok[0] += 1
        print("  PASS  %s" % name)
    else:
        bad[0] += 1
        print("  FAIL  %s   %s" % (name, extra))


def text_px(fm, text):
    """PySide6 6.x 移除了 QFontMetrics.width，改用 horizontalAdvance。"""
    if hasattr(fm, "horizontalAdvance"):
        return fm.horizontalAdvance(text)
    return fm.width(text)


def mk(local, remote, full=None, dl=104239406, changed=0, orphans=0):
    r = u.CheckResult()
    r.ok = True
    r.local_ver = local
    r.record_ver = local if local != "未安装" else ""
    r.remote_ver = remote
    r.full = (local == "未安装") if full is None else full
    r.baseline_ver = u.SELF_VERSION
    r.download_bytes = dl
    r.packages = [("base", u._human(dl))]
    r.changed = changed
    r.orphans = orphans
    r.update = True
    r.install_dir = os.getcwd()
    return r


def measure(name, r):
    dlg = QMessageBox()
    label = r.action_label()
    dlg.setWindowTitle(label)
    dlg.setText("%s %s" % (label, r.remote_ver))
    lines = list(r.detail_lines())
    ok_in_proc, why = u.update_available_in_process()
    if not ok_in_proc:
        lines.extend(u.wrap_lines([
            "",
            "注意：%s。" % why,
            "本次只会把新版本安装到：%s"
            % (r.install_dir or "默认安装目录"),
        ]))
    dlg.setInformativeText("\n".join(lines))
    dlg.setMinimumWidth(520)
    yes = PushButton("立即更新", dlg)
    no = PushButton("以后再说", dlg)
    dlg.addButton(yes, QMessageBox.AcceptRole)
    dlg.addButton(no, QMessageBox.RejectRole)
    dlg.adjustSize()
    app.processEvents()
    labels = [w for w in dlg.findChildren(QLabel) if w.text()]
    info = None
    for w in labels:
        if "当前版本" in w.text() or "已是最新" in w.text() or w.text() == r.err:
            info = w
            break
    if info is None and labels:
        info = labels[-1]
    fm = info.fontMetrics()
    lw = info.width()
    print("\n-- %s （%s，标签宽 %dpx，共 %d 行）--"
          % (name, label, lw, len(lines)))
    worst = 0
    for ln in lines:
        px = text_px(fm, ln) if ln else 0
        worst = max(worst, px)
        flag = "" if px <= lw else "  <== 超宽被裁"
        print("   %4dpx / %dpx  %s%s" % (px, lw, ln, flag))
    chk("%s：所有行都在标签宽度内（不截断）" % name, worst <= lw,
        "最宽 %dpx > %dpx" % (worst, lw))
    # 高度：标签要容纳全部行（双倍行距余量）
    need_h = fm.height() * len(lines) + 8
    chk("%s：标签高度容纳全部行" % name, info.height() >= need_h,
        "标签高 %d < 需要 %d" % (info.height(), need_h))


print("== 模拟安装版：本地未安装、远端 1.19.0（低于运行版本）==")
measure("screenshot-case", mk("未安装", "1.19.0"))
print("\n== 普通升级（SELF 压到 1.18.0 复现发布版用户）==")
_real = u.SELF_VERSION
u.SELF_VERSION = "1.18.0"
measure("normal-upgrade", mk("1.18.0", "1.19.0", full=False, changed=12))
u.SELF_VERSION = _real
print("\n== 全新安装（远端比运行版本新）==")
measure("fresh-newer", mk("未安装", "99.0.0"))
print("\n== 回滚（已装 2.0.0 → 远端 1.19.0）==")
measure("rollback", mk("2.0.0", "1.19.0", full=False, orphans=3))

print("\n%d passed, %d failed" % (ok[0], bad[0]))
sys.exit(1 if bad[0] else 0)
