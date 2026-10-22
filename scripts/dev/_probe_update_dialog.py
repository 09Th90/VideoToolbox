# -*- coding: utf-8 -*-
# @version 2.5.4
"""Verify update dialog text/version-direction fixes (no network)."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import vt_update_check as u  # noqa: E402

ok = [0]
bad = [0]


def chk(name, cond, extra=""):
    if cond:
        ok[0] += 1
        print("  PASS  %s" % name)
    else:
        bad[0] += 1
        print("  FAIL  %s   %s" % (name, extra))


def mk(local, remote, full=None, **kw):
    r = u.CheckResult()
    r.ok = True
    r.local_ver = local
    r.remote_ver = remote
    r.full = (local == "未安装") if full is None else full
    if local == "未安装" or u._vnewer(u.SELF_VERSION, local):
        r.baseline_ver = u.SELF_VERSION
    else:
        r.baseline_ver = local
    r.download_bytes = kw.get("dl", 104239406)
    r.packages = kw.get("pkgs", [("base", u._human(104239406))])
    r.changed = kw.get("changed", 0)
    r.orphans = kw.get("orphans", 0)
    r.update = True
    return r


def width_of(line):
    return sum(1.0 if ord(c) > 0x2E7F else 0.5 for c in line)


print("== _v prefix ==")
chk("真实版本号带 v", u._v("1.19.0") == "v1.19.0", u._v("1.19.0"))
chk("未安装不带 v", u._v("未安装") == "未安装", u._v("未安装"))
chk("空值不带 v", u._v("") == "未安装", u._v(""))

print("\n== scenario A: dev run (2.0.0), nothing installed, remote 1.19.0 ==")
r = mk("未安装", "1.19.0")
chk("判降级", r.downgrade() is True)
chk("动作短语=安装较旧版本", r.action_label() == "安装较旧版本", r.action_label())
lines = r.detail_lines()
text = "\n".join(lines)
chk("无 'v未安装' 拼接事故", "v未安装" not in text and "v v" not in text, text)
chk("说明含『未安装（正在运行 v2.0.0）』",
    any("未安装（正在运行 v2.0.0）" in ln for ln in lines), lines[:2])
chk("标出低于当前版本", any("低于当前" in ln for ln in lines), lines[:3])
chk("所有行不超 30 列", all(width_of(ln) <= 30.0 for ln in lines),
    [ln for ln in lines if width_of(ln) > 30.0])
chk("无空 excised 行", all(ln.strip() for ln in lines if ln != ""), lines)
print("   detail_lines ->")
for ln in lines:
    print("     | %s" % ln)

print("\n== scenario B: fresh install, remote newer than running ==")
r = mk("未安装", "2.1.0")
chk("不判降级", r.downgrade() is False)
chk("动作短语=全新安装", r.action_label() == "全新安装", r.action_label())

print("\n== scenario C: normal upgrade (installed 1.18.0, remote 1.19.0) ==")
# 发布版视角：当前运行版本 = 已装版本 = 1.18.0（本仓库是 2.0.0 开发
# 形态，须把 SELF_VERSION 压低才能复现普通用户的升级场景）
_real_self = u.SELF_VERSION
u.SELF_VERSION = "1.18.0"
r = mk("1.18.0", "1.19.0", full=False, changed=12)
chk("不判降级", r.downgrade() is False)
chk("动作短语=发现新版本", r.action_label() == "发现新版本", r.action_label())
lines = r.detail_lines()
chk("首行『当前版本：v1.18.0』", lines[0] == "当前版本：v1.18.0", lines[0])
chk("第二行『最新版本：v1.19.0』", lines[1] == "最新版本：v1.19.0", lines[1])
chk("所有行不超 30 列", all(width_of(ln) <= 30.0 for ln in lines), lines)
u.SELF_VERSION = _real_self

print("\n== scenario D: rollback (installed 2.0.0, remote 1.19.0) ==")
r = mk("2.0.0", "1.19.0", full=False, orphans=3)
chk("判降级", r.downgrade() is True)
chk("动作短语=回滚到旧版本", r.action_label() == "回滚到旧版本", r.action_label())
lines = r.detail_lines()
chk("首行即 v2.0.0", lines[0] == "当前版本：v2.0.0", lines[0])
chk("含残留清理提示", any("3 个旧版本残留" in ln for ln in lines), lines)

print("\n== scenario E: installed 1.18.0, dev run 2.0.0, remote 1.19.0 ==")
r = mk("1.18.0", "1.19.0", full=False)
chk("基准取运行版本（判降级）", r.downgrade() is True)
lines = r.detail_lines()
chk("并列说明运行版本",
    lines[0] == "当前版本：v1.18.0（正在运行 v2.0.0）", lines[0])

print("\n== summary / no-update ==")
r = mk("1.19.0", "1.19.0", full=False)
r.update = False
chk("已是最新文案无 v未安装", "v未安装" not in r.summary(), r.summary())
r2 = u.CheckResult()
r2.ok = True
r2.update = False
r2.local_ver = "未安装"
chk("未装+无更新文案干净", "v未安装" not in r2.summary(), r2.summary())

print("\n== _wrap ==")
long_line = "（本地未检测到已安装版本，将执行全新安装）" * 3
ws = u._wrap(long_line, width=30)
chk("折成多行且每行≤30 列",
    len(ws) > 1 and all(width_of(w) <= 30.0 for w in ws), ws)
chk("折行不丢字符", "".join(ws) == long_line, "".join(ws)[:50])

print("\n== failure paths do not raise ==")
r3 = u.CheckResult()
r3.ok = False
r3.err = "网络错误"
chk("失败态 detail_lines 返回错误文本", r3.detail_lines() == ["网络错误"],
    r3.detail_lines())
chk("失败态 downgrade False", r3.downgrade() is False)

print("\n%d passed, %d failed" % (ok[0], bad[0]))
sys.exit(1 if bad[0] else 0)
