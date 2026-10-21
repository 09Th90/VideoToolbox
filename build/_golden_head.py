# -*- coding: utf-8 -*-
# @version 2.4.1
"""GUI 黄金基准比对工具（P3 引擎自研化替换 · 需在**能跑 Qt 的桌面**执行）。

用途：证明「自研 UI（vt_engine_ui）」与「引擎 UI（videocaptioner）」经过**同一套
宿主整形**后，最终可见控件树逐节点一致——即「图形界面不发生变化」。

为什么必须在桌面跑：本替换的开发环境无交互窗口站，``QApplication()`` 会挂起，
无法实例化控件。请在装有本工具的机器上执行本脚本。

比对方式：
  · golden = 引擎类 + 类级补丁(brand/transcribe) + 构造 + 宿主实例整形
  · actual = 自研类 + 构造 + 宿主实例整形（补丁已内建，无需再打）
  两者走**同一份** ``apply_home_surgery`` / ``apply_setting_surgery``，输入一致 ⇒
  输出一致即证明视觉等价。

已知且**预期**的差异（不影响任何可见像素，比对时自动忽略）：
  自研转录设置卡不再构建引擎那三块「永不可达」的配置控件
  （WhisperCpp / WhisperAPI / FasterWhisper SettingWidget）——下拉收敛为
  「默认/ASR」后它们永远不会成为当前页（规格补丁 ③ 的既定语义）。

用法：
  python scripts/dev/vt_ui_golden.py dump   engine_home    out/home_golden.json
  python scripts/dev/vt_ui_golden.py dump   self_home      out/home_self.json
  python scripts/dev/vt_ui_golden.py diff   out/home_golden.json out/home_self.json
  （setting 同理：engine_setting / self_setting）
  python scripts/dev/vt_ui_golden.py all    out/     # 一键跑完 home+setting 并给结论
"""
import json
import os
import re
import sys

# 忽略的「死控件」类名（自研侧按设计不再构建；永不可见）
IGNORE_CLASSES = {
    "WhisperCppSettingWidget",
    "WhisperAPISettingWidget",
    "FasterWhisperSettingWidget",
}


def _norm_ws(s):
    return re.sub(r"\s+", " ", s).strip() if s else ""


def _icon_name(w):
    try:
        ic = w.icon()
    except Exception:
        return None
    if ic is None or ic.isNull():
        return None
    for attr in ("_icon",):
        v = getattr(w, attr, None)
        n = getattr(v, "name", None)
        if callable(n):
            try:
                return n()
            except Exception:
                pass
        elif isinstance(n, str):
            return n
    return "icon"


def _layout_info(lay):
    if lay is None:
        return None
    info = {"type": lay.__class__.__name__}
    try:
        info["spacing"] = round(lay.spacing(), 2)
    except Exception:
        pass
    try:
        m = lay.contentsMargins()
        info["margins"] = [m.left(), m.top(), m.right(), m.bottom()]
    except Exception:
        pass
    return info


def serialize(w, depth=0, max_depth=60):
    if w is None or depth > max_depth:
        return None
    if w.__class__.__name__ in IGNORE_CLASSES:
        return None
    from PyQt5.QtWidgets import QWidget
    node = {"cls": w.__class__.__name__, "obj": w.objectName() or ""}
    try:
        g = w.geometry()
        node["geo"] = [g.x(), g.y(), g.width(), g.height()]
    except Exception:
        pass
    try:
        node["hid"] = bool(w.isHidden())
    except Exception:
        pass
    try:
        ss = w.styleSheet()
        if ss:
            node["ss"] = _norm_ws(ss)
    except Exception:
        pass
    for getter, key in (("text", "txt"), ("placeholderText", "ph"),
                        ("windowTitle", "wt")):
        try:
            fn = getattr(w, getter, None)
            if callable(fn):
                v = fn()
                if isinstance(v, str) and v:
                    node[key] = v
        except Exception:
            pass
    icn = _icon_name(w)
    if icn:
        node["icon"] = icn
    try:
        li = _layout_info(w.layout())
        if li:
            node["lay"] = li
    except Exception:
        pass
    kids = []
    try:
        for c in w.children():
            if isinstance(c, QWidget):
                s = serialize(c, depth + 1, max_depth)
                if s is not None:
                    kids.append(s)
    except Exception:
        pass
    if kids:
        node["kids"] = kids
    return node


def _flatten(node, path, out, in_hidden=False):
    """展平控件树。

    ``in_hidden``：祖先是否已隐藏。**隐藏节点及其整棵子树不计入比对**——
    宿主 ``_build_engine`` 有意把「字幕视频合成」页从堆叠页摘掉并 ``hide()``，
    自研侧对应页是**占位实现**（无可见控件），这是设计而非缺陷。把隐藏节点
    也拿来比，会让「故意不显示的页面」永远显示成 21 个节点缺失。
    """
    hidden = in_hidden or bool(node.get("hid"))
    if hidden:
        return
    label = node.get("cls", "?")
    if node.get("obj"):
        label += "#" + node["obj"]
    if node.get("txt"):
        label += '"%s"' % node["txt"]
    cur = path + "/" + label
    summary = {k: node[k] for k in ("geo", "hid", "ss", "ph", "icon", "lay", "wt")
               if k in node}
    summary.pop("hid", None)      # 已按可见性过滤，无需再比
    out.append((cur, summary))
    for i, k in enumerate(node.get("kids", [])):
        _flatten(k, "%s[%d]" % (cur, i), out, hidden)


def diff(a_path, b_path):
    with open(a_path, encoding="utf-8") as f:
        a = json.load(f)
    with open(b_path, encoding="utf-8") as f:
        b = json.load(f)
    fa, fb = [], []
    _flatten(a, "", fa)
    _flatten(b, "", fb)
    da, db = dict(fa), dict(fb)
    ka = [p for p, _ in fa]
    kb = [p for p, _ in fb]
    only_a = [k for k in ka if k not in db]
    only_b = [k for k in kb if k not in da]
    changed = [(k, da[k], db[k]) for k in ka if k in db and da[k] != db[k]]
    print("golden(engine)=%d  actual(self)=%d" % (len(ka), len(kb)))
    print("only-engine=%d  only-self=%d  changed=%d"
          % (len(only_a), len(only_b), len(changed)))
    for k in only_a[:80]:
        print("  -E", k)
    for k in only_b[:80]:
        print("  +S", k)
    for k, va, vb in changed[:120]:
        print("  ~", k)
        print("      E:", json.dumps(va, ensure_ascii=False))
        print("      S:", json.dumps(vb, ensure_ascii=False))
    ok = not (only_a or only_b or changed)
    print("RESULT:", "IDENTICAL ✅" if ok else "DIFFERS ❌")
    return 0 if ok else 1


# ---------------- host surgery (与 video_toolbox_qt._build_engine 同源) ----------------

def apply_home_surgery(h, app):
    """复现宿主对内嵌工作台的实例级整形（两条路径共用，保证输入一致）。"""
    from PyQt5.QtWidgets import QWidget as _QW, QStackedWidget, QVBoxLayout
    sub_if = getattr(h, "subtitle_optimization_interface", None)
    if sub_if is not None:
        opt = getattr(sub_if, "optimize_button", None)
        cb = getattr(sub_if, "command_bar", None)
        if opt is not None and cb is not None:
            cb.removeAction(opt)
            try:
                _QW.removeAction(cb, opt)
            except Exception:
                pass
        lay = getattr(sub_if, "main_layout", None)
        tbl = getattr(sub_if, "subtitle_table", None)
        if lay is not None:
            lay.setSpacing(10)
            if tbl is not None:
                lay.setStretch(lay.indexOf(tbl), 1)
    h.setStyleSheet("HomeInterface{background:transparent;}")
    try:
        h.pivot.setItemText("SubtitleInterface", "字幕翻译")
    except Exception:
        pass
    try:
        syn = getattr(h, "video_synthesis_interface", None)
        if syn is not None:
            try:
                h.subtitle_optimization_interface.finished.disconnect(h.switch_to_video_synthesis)
            except Exception:
                pass
            h.switch_to_video_synthesis = lambda *a, **k: None
            h.pivot.removeWidget("VideoSynthesisInterface")
            h.stackedWidget.removeWidget(syn)
            syn.hide()
    except Exception:
        pass
    tc = getattr(h, "task_creation_interface", None)
    if tc is not None:
        for attr in ("info_label", "donate_button"):
            w = getattr(tc, attr, None)
            if w is not None:
                w.hide()
        try:
            tc.finished.disconnect(h.switch_to_transcription)
        except Exception:
            pass
        tc.finished.connect(lambda fp: None)
    # 并入「字幕校准」占位页（宿主用真实 CalibPage；此处用同 objectName 的占位，
    # 两条路径一致，不影响结构比对）
    try:
        calib = _QW()
        calib.setObjectName("CalibrationInterface")
        h.stackedWidget.addWidget(calib)
        keys = list(h.pivot.items.keys())
        idx = (keys.index("SubtitleInterface") + 1) if "SubtitleInterface" in keys else -1
        h.pivot.insertItem(idx, "CalibrationInterface", "字幕校准",
                           onClick=lambda: h.stackedWidget.setCurrentWidget(calib))
    except Exception:
        pass
    h.resize(1200, 800)
    h.show()
    app.processEvents()
    return h


def apply_setting_surgery(s, app):
    """复现宿主 _ensure_engine_setting 的整形（隐藏分组/卡片、合并翻译组、拍平视口）。"""
    from PyQt5.QtCore import Qt
    from PyQt5.QtWidgets import QFrame, QSizePolicy
    try:
        s.settingLabel.hide()
    except Exception:
        pass
    for gname in ("llmGroup", "saveGroup", "personalGroup", "aboutGroup"):
        g = getattr(s, gname, None)
        if g is not None:
            g.setHidden(True)
    promo = getattr(s, "openaiOfficialApiCard", None)
    if promo is not None:
        orig = promo.setVisible
        promo.setVisible = lambda _v=True: orig(False)
        orig(False)
    for cname in ("subtitleCorrectCard", "needReflectTranslateCard"):
        c = getattr(s, cname, None)
        if c is not None:
            c.hide()
    tn = getattr(s, "threadNumCard", None)
    if tn is not None:
        try:
            tn.setContent("请求并行处理的数量，免费机翻端点已内置全局限速保护，设置过大不会更快")
        except Exception:
            pass
    trg = getattr(s, "transcribeGroup", None)
    if trg is not None:
        trg.setHidden(True)
    # 合并 translate_serviceGroup -> translateGroup（「字幕翻译」）
    try:
        src_g = getattr(s, "translate_serviceGroup", None)
        dst_g = getattr(s, "translateGroup", None)
        if src_g is not None and dst_g is not None:
            order = ["translatorServiceCard", "subtitleTranslateCard",
                     "targetLanguageCard", "threadNumCard", "deeplxEndpointCard"]
            dst_lay = dst_g.cardLayout
            dst_ws = getattr(dst_lay, "_ExpandLayout__widgets", None)
            src_lay = src_g.cardLayout
            src_ws = getattr(src_lay, "_ExpandLayout__widgets", None)
            for _idx, _name in enumerate(order):
                _card = getattr(s, _name, None)
                if _card is None:
                    continue
                if src_ws is not None and _card in src_ws:
                    src_ws.remove(_card)
                    _card.removeEventFilter(src_lay)
                _card.setParent(dst_g)
                if dst_ws is None:
                    dst_g.addSettingCard(_card)
                    continue
                if _card in dst_ws:
                    dst_ws.remove(_card)
                dst_ws.insert(min(_idx, len(dst_ws)), _card)
                _card.installEventFilter(dst_lay)
            dst_g.titleLabel.setText("字幕翻译")
            dst_g.titleLabel.adjustSize()
            dst_g.adjustSize()
            src_g.setHidden(True)
            src_g.adjustSize()
    except Exception:
        pass
    try:
        s.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        s.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        s.setFrameShape(QFrame.NoFrame)
        s.setViewportMargins(0, 0, 0, 0)
        s.expandLayout.setContentsMargins(0, 0, 0, 0)
        s.expandLayout.setSpacing(20)
        s.setMinimumWidth(0)
        sp = s.sizePolicy()
        sp.setHorizontalPolicy(QSizePolicy.Expanding)
        s.setSizePolicy(sp)
    except Exception:
        pass
    s.resize(900, 800)
    s.show()
    app.processEvents()
    return s


# ---------------- builders ----------------

#: 进程内唯一的 QApplication 强引用。
#:
#: ⚠ PyQt5 同一进程**只能有一个** QApplication：第二次构造会销毁前一个实例，
#: 挂在它上面的 widget 随即变成已删除的 C++ 对象
#: （报 "wrapped C/C++ object of type HomeInterface has been deleted"）。
#: `_mk_app()` 若每次新建，_all() 里连着 dump 四个界面时必然踩到 ⇒ 用模块级
#: 变量把实例钉住，保证既不重复创建也不被 GC。
_APP = None

#: dump 期间存活的 widget 强引用（见 _dump 的说明）。
_KEEP = []

#: 构造下一轮界面前需清掉的**类级 widget 缓存**。
#:
#: 引擎 / 自研 UI 的界面类会把若干子控件挂成**类属性**（首次构造时赋值，
#: 之后所有实例共享）。上一轮的实例一旦被 PyQt 回收，这些类属性就指向已
#: 删除的 C++ 对象；下一轮 `apply_setting_surgery` 里
#: `getattr(s, "llmGroup").setHidden(True)` 便抛
#: "wrapped C/C++ object of type SettingCardGroup has been deleted"。
#:
#: 判定口径：**值是 QWidget 子类实例**才算缓存（类上原本声明的同名属性是
#: 字符串，如 llmGroup='llmGroup'，那是取实例属性的键名，不是缓存）。
_CACHED_WIDGET_ATTRS = (
    "llmGroup", "saveGroup", "personalGroup", "aboutGroup",
    "transcribeGroup", "subtitleGroup", "videoGroup", "audioGroup",
    "threadNumCard", "subtitleCorrectCard", "needReflectTranslateCard",
    "openaiOfficialApiCard",
)


def _clear_class_widget_cache(cls):
    """清掉界面类上的 widget 实例缓存，使下一轮能干净构造。"""
    from PyQt5.QtWidgets import QWidget
    cleared = []
    for attr in _CACHED_WIDGET_ATTRS:
        try:
            val = cls.__dict__.get(attr)
        except Exception:
            continue
        if isinstance(val, QWidget):
            try:
                delattr(cls, attr)
                cleared.append(attr)
            except Exception:
                pass
    if cleared:
        print("[cleanup] %s 类级缓存已清: %s"
              % (cls.__name__, ", ".join(cleared)))
    return cleared


def _mk_app():
    global _APP
    from PyQt5.QtWidgets import QApplication
    inst = QApplication.instance()
    if inst is None:
        inst = QApplication(sys.argv[:1])
    _APP = inst          # 强引用，防被回收
    return inst


def _prepare_backend():
    sys.path.insert(0, os.path.join(os.getcwd(), "src"))
    import video_toolbox as engine
    engine.prepare_runtime_env()
    return engine


def build_engine_home():
    engine = _prepare_backend()
    app = _mk_app()
    engine.engine_ui_brand_patch()
    try:
        engine.vc_transcribe_ui_patch()
    except Exception:
        pass
    from videocaptioner.ui.view.home_interface import HomeInterface
    return apply_home_surgery(HomeInterface(), app)


def build_self_home():
    _prepare_backend()
    app = _mk_app()
    import vt_engine_ui
    if not vt_engine_ui.self_ui_available():
        raise RuntimeError("self UI unavailable: %s" % vt_engine_ui.self_ui_error())
    return apply_home_surgery(vt_engine_ui.HomeInterface(), app)


def _setting_parent():
    """造一个**被强引用持有**的父 QWidget。

    ⚠ 引擎 ``SettingInterface.__init__`` 会把若干 ``SettingCardGroup`` 挂成
    **子控件**。若父对象只是 ``SettingInterface(QWidget())`` 里的临时量，
    构造一返回它就没引用了 ⇒ 立即被 PyQt 回收 ⇒ 子控件连带析构，
    随后 ``apply_setting_surgery`` 里的 ``llmGroup.setHidden(True)`` 抛
    "wrapped C/C++ object of type SettingCardGroup has been deleted"。

    实测：把父对象存进模块级 ``_KEEP`` 后同一操作正常。父对象无 parent，
    只能靠 Python 侧强引用维持存活（``_KEEP`` 持有到进程退出）。
    """
    from PyQt5.QtWidgets import QWidget
    parent = QWidget()
    _KEEP.append(parent)
    return parent


def build_engine_setting():
    engine = _prepare_backend()
    app = _mk_app()
    engine.engine_ui_brand_patch()
    from videocaptioner.ui.view.setting_interface import SettingInterface
    _clear_class_widget_cache(SettingInterface)
    return apply_setting_surgery(SettingInterface(_setting_parent()), app)


def build_self_setting():
    _prepare_backend()
    app = _mk_app()
    import vt_engine_ui
    _clear_class_widget_cache(vt_engine_ui.SettingInterface)
    return apply_setting_surgery(
        vt_engine_ui.SettingInterface(_setting_parent()), app)


BUILDERS = {
    "engine_home": build_engine_home,
    "self_home": build_self_home,
    "engine_setting": build_engine_setting,
    "self_setting": build_self_setting,
}


def _dump(builder, out):
    w = BUILDERS[builder]()
    # widget 必须**在整个 dump 期间保持强引用**：局部变量一旦被回收，
    # 底层 C++ 对象可能随之析构，后续 serialize/grab 会拿到已删除对象。
    #
    # ⚠ 也不能在这里 close()/deleteLater()：engine 的 SettingInterface 里
    # `apply_setting_surgery` 会二次遍历上一轮遗留的 SettingCardGroup，
    # 中途销毁会让那些子控件变成已删除的 C++ 对象
    # （报 "wrapped C/C++ object of type SettingCardGroup has been deleted"）。
    # 一律留到进程退出由 Python 回收（_KEEP 持有强引用）。
    _KEEP.append(w)
    _mk_app().processEvents()          # 走完事件循环，让布局稳定下来
    tree = serialize(w)
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(tree, f, ensure_ascii=False, indent=1)
    try:
        png = out.rsplit(".", 1)[0] + ".png"
        w.grab().save(png)
        print("screenshot:", png)
    except Exception as e:
        print("grab failed:", e)
    print("dumped", out)
    return tree


def _all(outdir):
    os.makedirs(outdir, exist_ok=True)
    rc = 0
    for name in ("home", "setting"):
        g = os.path.join(outdir, "%s_golden.json" % name)
        a = os.path.join(outdir, "%s_self.json" % name)
        print("==== %s: dump engine ====" % name)
        _dump("engine_%s" % name, g)
        print("==== %s: dump self ====" % name)
        _dump("self_%s" % name, a)
        print("==== %s: diff ====" % name)
        rc |= diff(g, a)
    print("=" * 50)
    print("OVERALL:", "IDENTICAL ✅" if rc == 0 else "DIFFERS ❌ (见上)")
    return rc


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    cmd = sys.argv[1]
    if cmd == "dump":
        _dump(sys.argv[2], sys.argv[3])
        return 0
    if cmd == "diff":
        return diff(sys.argv[2], sys.argv[3])
    if cmd == "all":
        return _all(sys.argv[2] if len(sys.argv) > 2 else "scripts/dev/_golden")
    print("unknown cmd", cmd)
    return 2


if __name__ == "__main__":
    sys.exit(main())
