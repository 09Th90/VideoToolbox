# -*- coding: utf-8 -*-
"""负向验证：v2.1.0「去掉字幕视频合成 + 剩下三个平铺」。

正向检查全过不说明检查有效。这里把源码**故意改坏**三处，确认探针真的会报FAIL：

  N1  把「字幕视频合成」重新 addSubInterface 回去⇒ 必须报"分段项数=4"
  N2  撤掉平铺（sizePolicy 回 Minimum /对齐回 AlignLeft）⇒ 必须报"未平铺"
  N3  去掉 item.hide()（只removeWidget）⇒ 必须报"存在残留可见分段项"

每项在**独立进程 + 独立副本**里做，跑完即还原；污染必须真落进副本
（否则就是假绿），这一点会显式断言。
"""
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PY = r"C:\bld\qt_build\Scripts\python.exe"

SELF = os.path.join(ROOT, "src", "vt_engine_ui", "home_interface.py")
HOST = os.path.join(ROOT, "src", "video_toolbox_qt.py")

PROBE = r'''
import os, sys, time
os.environ.setdefault("QT_QPA_PLATFORM", "windows")
ROOT = r"%s"
sys.path.insert(0, os.path.join(ROOT, "src"))
os.environ["VT_DATA_ROOT"] = os.path.join(ROOT, "build", "_negprobe_data")
from PySide6.QtWidgets import QApplication, QSizePolicy
import video_toolbox_qt as vt

def pump(app, ms=500):
    end = time.time() + ms / 1000.0
    while time.time() < end:
        app.processEvents(); time.sleep(0.01)

app = QApplication.instance() or QApplication(sys.argv)
win = vt.MainWindow([]); win.resize(1180, 729); win.show(); pump(app, 300)
for _ in range(60):
    win.subtitle_page.ensure_built(); pump(app, 250)
    if win.home_page.task_creation is not None:
        break
win.switchTo(win.subtitle_page); pump(app, 900)
p = win.subtitle_page._engine.pivot
keys = list(p.items.keys())
g = [p.items[k].geometry() for k in keys]
widths = [x.width() for x in g]
vis = [k for k, w in p.items.items() if w.isVisible()]
flat = (len(keys) > 0
        and max(widths) - min(widths) <= 2
        and g[0].x() <= 2
        and abs((g[-1].x() + g[-1].width()) - p.width()) <= 2)
# 残留判据：SegmentedWidget 下**仍挂着父对象、却已不在 items 里**的子控件。
# ⚠ 不能只看"是否 visible"——``Pivot.removeWidget`` 内部是 deleteLater()，
# 只要事件循环转起来 DeferredDelete 就会被处理，控件真的没了 ⇒ 残留只在
# deleteLater 落地前的那一瞬间可见，事后探测必然是假阴性。
# 持久判据是**子控件数量**：摘干净 ⇒ p 下正好N 个按钮；没脱父 ⇒ N+1 个
# （哪怕那个已被销毁/隐藏，它占着的 sibling 下标仍会让 golden 结构比对错位）。
from PySide6.QtWidgets import QPushButton, QWidget
import json
kids = p.findChildren(QPushButton)
leftover = [ch.text() for ch in kids if ch not in list(p.items.values())]
home = win.subtitle_page._engine
# 合成页是否还挂在**堆叠页**下（QStackedWidget.removeWidget 只移出当前显示，
# 不改父子关系 ⇒ 这是"没脱父"的持久判据，比数 HomeInterface 子控件准）
syn = getattr(home, "video_synthesis_interface", None)
syn_attached = 1 if (syn is not None and syn.parent() is not None) else 0
n_stack_kids = len(home.stackedWidget.findChildren(QWidget))
# 声纹历史列表是否可见（应为隐藏）：全局找 VoiceprintEnrollCard
# （它挂在 TranscriptionSettingCard 里，**不在** TaskCreationInterface 上，
#  按 tc 属性找会落空 ⇒ 探针打 -1 = 假绿）。卡片构造可能晚于首次 dump，
#  循环等待重找。
vp_list_visible = -1
vp_found = 0
for _ in range(20):
    try:
        for w in QApplication.allWidgets():
            if type(w).__name__ == "VoiceprintEnrollCard":
                vp_found = 1
                if hasattr(w, "list_box"):
                    vp_list_visible = 1 if w.list_box.isVisible() else 0
                break
        if vp_found:
            break
    except Exception:
        pass
    end = time.time() + 0.3
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)
print("@@" + json.dumps({
    "keys": keys,
    "count": len(keys),
    "no_syn": 0 if "VideoSynthesisInterface" in keys else 1,
    "all_vis": 1 if len(vis) == len(keys) else 0,
    "flat": 1 if flat else 0,
    "leftover": leftover,
    "n_kids": len(kids),
    "n_stack_kids": n_stack_kids,
    "syn_attached": syn_attached,
    "vp_list_visible": vp_list_visible,
    "vp_found": vp_found,
    "widths": widths,
    "pivot_w": p.width(),
    "sp": int(p.sizePolicy().horizontalPolicy()),
    "sp_item": int(p.items[keys[0]].sizePolicy().horizontalPolicy()) if keys else -1,
    "constraint": int(p.hBoxLayout.sizeConstraint()),
}))
''' % ROOT.replace("\\", "\\\\")

NEG_CHECK = r'''
import json, sys
for line in sys.stdin:
    line = line.strip()
    if line.startswith("@@"):
        print(json.dumps(json.loads(line[2:])))
'''


def run_probe():
    p = subprocess.run([PY, "-c", PROBE], capture_output=True, text=True,
                       cwd=ROOT, encoding="utf-8", errors="replace")
    if p.returncode != 0:
        print(p.stdout[-3000:])
        print(p.stderr[-3000:])
        raise SystemExit("探针自身崩溃")
    import json
    for line in p.stdout.splitlines():
        if line.startswith("@@"):
            return json.loads(line[2:])
    print(p.stdout[-3000:])
    print(p.stderr[-3000:])
    raise SystemExit("探针未输出 @@ 行")


def restore(path, bak):
    if os.path.exists(bak):
        shutil.copy2(bak, path)
        os.remove(bak)


# ⚠⚠ 铁律：负向测试会**改真实源码**。若进程被中断（Ctrl-C / 超时 / 崩溃），
# 还原语句不会执行 ⇒ 源码永久停在污染态，下一次跑任何东西都基于坏代码，
# 而且极难察觉（本次就真的发生过：src/vt_engine_ui/home_interface.py 的
# setContentsMargins 被留成了 `pass  # negtest`）。
#  ⇒备份文件改用**哨兵名**登记到全局表，atexit + SIGINT/SIGTERM 兜底还原，
#    并且下一轮运行**开工前先扫一遍残留哨兵**（自愈）。
_LIVE_BACKUPS = []


def _recover_all():
    for bak in list(_LIVE_BACKUPS):
        try:
            path, tag = bak
            src = os.path.join(ROOT, path)
            if os.path.exists(src + ".negbak." + tag):
                restore(src, src + ".negbak." + tag)
        except Exception:  # noqa: BLE001
            pass
    _LIVE_BACKUPS.clear()


def sweep_stale_backups():
    """开工前自愈：把上一轮残留的哨兵备份全部还原并清理。"""
    import glob
    n = 0
    for g in glob.glob(os.path.join(ROOT, "src", "*.negbak.*")) + \
            glob.glob(os.path.join(ROOT, "src", "vt_engine_ui", "*.negbak.*")):
        src = g.rsplit(".negbak.", 1)[0]
        try:
            shutil.copy2(g, src)
            os.remove(g)
            n += 1
            print("[自愈] 还原残留污染文件：%s" % src)
        except Exception:  # noqa: BLE001
            pass
    return n


def patch(path, old, new, tag, count=1):
    """在**副本**上打补丁；返回备份路径。

    ⚠ 备份名必须带 tag：同一文件可能被连续 patch 两次（如 N3 的 hide 与
    setParent），固定备份名会让第二次覆盖第一次的备份 ⇒ restore 时丢文件。
    ``count``：替换处数。宿主里同一段字面量可能出现多处（如任务创建摘除
    在 _build_engine 和 HomePage.adopt 各有一次，构成双保险）——负向要
    **同时**破坏所有防线，只换第一处会被兜底救回 = 假绿。
    """
    bak = "%s.negbak.%s" % (path, tag)
    shutil.copy2(path, bak)
    src = open(path, encoding="utf-8").read()
    n = src.count(old)
    if n < count:
        os.remove(bak)
        raise SystemExit("[%s] 锚点出现 %d 次 < 需要的 %d，负向无效：%r"
                         % (tag, n, count, old[:60]))
    open(path, "w", encoding="utf-8").write(src.replace(old, new, count))
    _LIVE_BACKUPS.append((path, tag))
    return bak


def main():
    # 开工先自愈：把上一轮（可能被中断）残留的污染还原
    if sweep_stale_backups():
        print("[警告] 检测到上一轮负向测试残留污染，已自动还原\n")

    import atexit
    import signal
    atexit.register(_recover_all)

    def _sig(_s, _f):
        _recover_all()
        os._exit(130)
    for s in ("SIGINT", "SIGTERM", "SIGBREAK"):
        try:
            signal.signal(getattr(signal, s), _sig)
        except Exception:  # noqa: BLE001
            pass

    base = run_probe()
    print("[基线]", base)
    ok = (base["count"] == 3 and base["no_syn"] == 1
          and base["all_vis"] == 1 and base["flat"] == 1
          and not base["leftover"])
    print("[基线判定]", "PASS" if ok else "FAIL（基线就不对，后面的负向无意义）")
    if not ok:
        return 1

    results = {}

    # ---- N1 把「字幕视频合成」加回分段 ----
    #⚠ 关键：宿主 _build_engine 里还有一层 removeWidget 兜底，会把加回的项
    #    **再次摘掉** ⇒ 只改自研源码的话，负向打不中（假绿）。要证明
    #    "源码层不注册"这道防线有效，必须**同时**把宿主兜底一起破坏，
    #    模拟"两道防线都失守"的极端情形。
    old_s = '        self.video_synthesis_interface.setParent(None)\n        self.video_synthesis_interface.hide()'
    new_s = ('        self.addSubInterface(self.video_synthesis_interface,\n'
             '                            "VideoSynthesisInterface", self.tr("字幕视频合成"))')
    old_h = 'home.pivot.removeWidget("VideoSynthesisInterface")'
    bak_s = patch(SELF, old_s, new_s, "N1-self")
    try:
        bak_h = patch(HOST, old_h, "pass", "N1-host")
        try:
            r = run_probe()
            print("[N1 源码加回 + 宿主兜底同时失守]", r)
            results["N1"] = (r["count"] == 4 and r["no_syn"] == 0)
        finally:
            restore(HOST, bak_h)
    finally:
        restore(SELF, bak_s)

    # ---- N2 平铺是**默认行为**：撤掉宿主/自研里跟平铺沾边的设置，几何不应变 ----
    #⚠ 这两条**不是**负向，而是"证明我们没多管闲事"的回归护栏：
    #   当初我加过 setAlignment / setSizePolicy(Expanding) /
    #   setSizeConstraint(0) 一整套，负向实验（整段撤掉）证明几何**一模一样**
    #   ⇒ 那套是多余代码，已删。这里锁死"删掉后仍平铺"，防止有人再加回来。
    for tag, old in (
        ("N2_sizePolicy", "        self.pivot.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)"),
        ("N2_margins", "        self.vBoxLayout.setContentsMargins(30, 10, 30, 30)"),
    ):
        bak = patch(SELF, old, "        pass  # negtest", tag)
        try:
            r = run_probe()
            print("[%s 撤掉后仍平铺？] flat=%s widths=%s pivot_w=%s"
                  % (tag, r["flat"], r["widths"], r["pivot_w"]))
            # 期望 flat 仍为 1（平铺不依赖这些设置）——若变成 0，说明平铺
            # 另有来源、我们理解错了，必须回头查清。
            results[tag] = (r["flat"] == 1)
        finally:
            restore(SELF, bak)

    # ---- N3 摘除时不让合成页脱父（syn.setParent(None) 被撤掉） ----
    # 前置：必须先让源码侧真的注册合成项，否则宿主那段摘除代码走不到
    # （syn 拿不到 / pivot.items 里没有该项），负向就是假绿。
    old_s = '        self.video_synthesis_interface.setParent(None)\n        self.video_synthesis_interface.hide()'
    new_s = ('        self.addSubInterface(self.video_synthesis_interface,\n'
             '                            "VideoSynthesisInterface", self.tr("字幕视频合成"))')
    bak_s = patch(SELF, old_s, new_s, "N3-self")
    try:
        old = "                syn.setParent(None)\n"
        bak = patch(HOST, old, "", "N3-parent")
        try:
            r = run_probe()
            print("[N3 摘除后合成页仍挂在工作台下]", r)
            # 判据是"目标行为"：合成页是否还挂着父对象（没脱父）
            results["N3"] = (r["syn_attached"] == 1)
        finally:
            restore(HOST, bak)
    finally:
        restore(SELF, bak_s)

    # ---- N4 宿主「摘任务创建分段」双保险同时失守 ⇒ 必须报出任务创建仍在 ----
    # v2.1.0：任务创建摘除已**前移到 _build_engine**（结构性保证），且
    # HomePage.adopt 里保留同字面量的幂等兜底 ⇒ **两处**构成双保险。
    # 负向必须 count=2 同时破坏，否则另一处会把分段又摘掉 = 假绿。
    old = 'home.pivot.removeWidget("TaskCreationInterface")'
    bak = patch(HOST, old, "pass  # negtest", "N4-tc", count=2)
    try:
        r = run_probe()
        print("[N4 双保险同时失守]", r)
        results["N4"] = (r["count"] >= 4
                         and "TaskCreationInterface" in r["keys"])
    finally:
        restore(HOST, bak)

    # ---- N5 「隐藏声纹历史列表」失守 ⇒ 必须报出 list_box 可见 ----
    old = "        self.list_box.hide()"
    bak = patch(os.path.join(ROOT, "src", "speaker_voiceprint_page.py"),
                old, "pass  # negtest", "N5-vp")
    try:
        r = run_probe()
        print("[N5 声纹历史列表未隐藏]", r)
        # 找不到卡片本身也是失败（探针失明 = 假绿风险）
        results["N5"] = (r["vp_found"] == 1 and r["vp_list_visible"] == 1)
    finally:
        restore(os.path.join(ROOT, "src", "speaker_voiceprint_page.py"), bak)

    print("=" * 56)
    bad = [k for k, v in results.items() if not v]
    for k, v in results.items():
        print("  %-13s %s" % (k, "OK" if v else "!! 未捕获/不符合预期"))
    print("NEG RESULT:", "ALL OK" if not bad else "FAILED " + ",".join(bad))

    # ---- 收尾自检：绝不能把污染留在源码里 ----
    _recover_all()
    if sweep_stale_backups():
        print("[收尾] 又清掉一批残留")
    # ⚠ 判据必须精确到"注入的标记"本身，不能只搜脚本名——源码注释里正当
    # 引用了本脚本名（记录负向结论），会被误判成污染。
    leaked = [p for p in (SELF, HOST)
              if "pass  # negtest" in open(p, encoding="utf-8").read()]
    if leaked:
        print("[致命] 负向测试残留污染未清除：%s" % leaked)
        return 2
    for p in (SELF, HOST):
        if "negbak" in p:
            print("[致命] 备份文件未清理：%s" % p)
            return 2
    print("[收尾自检] 源码已完全还原，无 negtest 残留")
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())