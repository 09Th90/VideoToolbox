# @version 2.5.3
r"""自检：公益转录限流查询经 LazyCache 代理转发 diskcache 私有 ``_sql``。

真实缺陷（用户截图，2026-10-14）：点「语音转录」走 Bcut/剪映公益接口时弹
「转录失败 Failed to query rate limit: _sql」，按钮同时回弹成绿色「转录失败」。

根因链
------
1. 宿主 ``video_toolbox.vc_lazy_cache_patch()`` 把引擎模块级 5 个 diskcache
   实例换成自研 :class:`engine_cache.LazyCache` 代理（惰性建库，省 2.5~4.5s）；
2. 引擎 ``BaseASR._check_rate_limit``（``bcut.py`` / ``jianying.py`` 调用）用
   diskcache **私有** ``_sql`` 查限流记录：
   ``SELECT key FROM Cache WHERE tag = ? AND store_time >= ?``；
3. ``LazyCache.__getattr__`` 对 ``_`` 前缀一律 ``AttributeError``（本为挡
   copy/pickle 协议探测）⇒ 查询直接失败，``str(e)`` 就是裸属性名 ``_sql``。

修复：``engine_cache._FORWARDED_PRIVATE`` 显式放行**仅** ``_sql`` 一个具名属性。

判定口径
--------
正向（完整宿主接线，VT_DATA_ROOT 隔离到临时目录）：
  · 引擎**真实的** ``BaseASR._check_rate_limit`` 跑通（用户报错的原点）；
  · 刚落账的限流记录能通过同一 ``_sql`` 查询查到（写+读都走通代理）；
  · 第二次调用放行、超大音频仍被时长阈值挡下（限流语义没被中和）；
  · 自研 ``engine_asr.BaseASR._check_rate_limit``（同名孪生分支）同样跑通；
  · 其他私有名（``__deepcopy__``）仍被挡——修复没开任意私有属性的口子。
负向（把 ``_FORWARDED_PRIVATE`` 污染成空集合）：
  同一引擎调用必须以 ``RuntimeError("Failed to query rate limit: _sql")``
  失败——即用户看到的原始报错逐字重现，证明检查有牙。

用法
----
    python scripts/dev/_selftest_rate_limit_sql.py

退出码 0 = 通过。
"""

import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
SRC = os.path.join(ROOT, "src")

PYPARSE = os.path.join(ROOT, "tools", "python", "python.exe")
if not os.path.exists(PYPARSE):
    PYPARSE = sys.executable

#: 子进程公共前置：隔离数据根 + 挂 src + 打宿主补丁（与生产启动顺序一致）
#: ⚠ 路径只经 PYTHONPATH 注入，**不要**在子进程里再 insert(0, SRC)——
#: 负向运行时 PYTHONPATH 首位是污染副本目录，任何 insert 都会把真源码
#: 挤回前面，污染被绕过 ⇒ 负向「形同虚设」还显示通过。
_CHILD_HEAD = r'''
import os, sys, time
os.environ["VT_DATA_ROOT"] = os.environ["VT_RL_ROOT"]

fails = []
def chk(name, cond, detail=""):
    print(("OK   " if cond else "FAIL ") + name + ("" if cond else "  << " + str(detail)))
    if not cond:
        fails.append(name)

import video_toolbox as vt
chk("vc_lazy_cache_patch 生效", vt.vc_lazy_cache_patch() is True)

from videocaptioner.core.utils.cache import get_asr_cache
from videocaptioner.core.asr.base import BaseASR

class _Dummy(BaseASR):
    def _run(self, callback=None, **kw):
        return {}
    def _make_segments(self, resp):
        return []

cache = get_asr_cache()
chk("引擎 asr 缓存是 LazyCache 代理", type(cache).__name__ == "LazyCache",
    type(cache).__name__)

d = object.__new__(_Dummy)
d._cache = cache
d.audio_duration = 65.0
'''

#: 正向子进程：修复后必须全部成立
_CHILD_POS = _CHILD_HEAD + r'''
# ── 用户报错的原点：修复前这一行抛 RuntimeError("Failed to query rate limit: _sql") ──
try:
    d._check_rate_limit()
    chk("引擎 _check_rate_limit 跑通（不再报 _sql）", True)
except Exception as e:
    chk("引擎 _check_rate_limit 跑通（不再报 _sql）", False, repr(e))

# ── 刚落账的记录必须能通过同一 _sql 查询查到（写+读都走通代理）──
try:
    tag = "rate_limit:%s" % type(d).__name__
    time_limit = time.time() - _Dummy.RATE_LIMIT_TIME_WINDOW
    rows = cache._sql(
        "SELECT key FROM Cache WHERE tag = ? AND store_time >= ?",
        (tag, time_limit)).fetchall()
    chk("限流记录可查（1 条）", len(rows) == 1, str(rows))
except Exception as e:
    chk("限流记录可查（1 条）", False, repr(e))

# ── 第二次调用放行（调用计数语义正常）──
try:
    d._check_rate_limit()
    chk("第二次调用放行", True)
except Exception as e:
    chk("第二次调用放行", False, repr(e))

# ── 限流语义没被中和：超大音频必须被时长阈值挡下 ──
d.audio_duration = 400 * 60
try:
    d._check_rate_limit()
    chk("超时长仍被限流挡下", False, "未抛异常")
except RuntimeError as e:
    chk("超时长仍被限流挡下", "duration limit exceeded" in str(e), str(e))
except Exception as e:
    chk("超时长仍被限流挡下", False, repr(e))

# ── 自研 engine_asr 的同名孪生分支同样跑通（双实现 parity）──
try:
    import engine_asr
    from engine_asr import BaseASR as MyBase, set_cache_hub
    from engine_cache import CacheHub

    class _Dummy2(MyBase):
        def _run(self, callback=None, **kw):
            return {}
        def _make_segments(self, resp):
            return []

    set_cache_hub(CacheHub(os.path.join(
        os.environ["VT_RL_ROOT"], "asr_hub")))
    d2 = object.__new__(_Dummy2)
    d2._cache = engine_asr._cache_hub().get("asr")
    d2.audio_duration = 30.0
    d2._check_rate_limit()
    chk("自研 engine_asr._check_rate_limit 跑通", True)
except Exception as e:
    chk("自研 engine_asr._check_rate_limit 跑通", False, repr(e))

# ── 修复没开口子：其他私有名仍被 __getattr__ 挡掉 ──
try:
    getattr(cache, "__deepcopy__")
    chk("其他私有名仍被挡（__deepcopy__）", False, "未抛 AttributeError")
except AttributeError as e:
    chk("其他私有名仍被挡（__deepcopy__）", str(e) == "__deepcopy__", str(e))

print("FAIL:", len(fails), fails if fails else "限流查询经代理全部成立")
sys.exit(1 if fails else 0)
'''

#: 负向子进程：污染后必须逐字重现用户报错（退出码 3 = 复现成功）
_CHILD_NEG = _CHILD_HEAD + r'''
try:
    d._check_rate_limit()
    print("NEG-UNEXPECTED: 污染后竟然跑通了")
    sys.exit(4)
except RuntimeError as e:
    if str(e) == "Failed to query rate limit: _sql":
        print("NEG-OK:", e)
        sys.exit(3)
    print("NEG-WRONG-ERROR:", repr(e))
    sys.exit(4)
except Exception as e:
    print("NEG-WRONG-TYPE:", repr(e))
    sys.exit(4)
'''


def _run(code, extra_path=None, root=None):
    env = dict(os.environ)
    paths = [p for p in (extra_path, SRC) if p]
    # 保留原 PYTHONPATH（本机有 WorkBuddy cli shim，直接覆盖会莫名失败）
    if os.environ.get("PYTHONPATH"):
        paths.append(os.environ["PYTHONPATH"])
    env["PYTHONPATH"] = os.pathsep.join(paths)
    env["VT_RL_ROOT"] = root or tempfile.mkdtemp(prefix="vt_rl_")
    env["VT_SRC"] = SRC
    p = subprocess.run([PYPARSE, "-c", code], env=env,
                       capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


def positive():
    root = tempfile.mkdtemp(prefix="vt_rl_pos_")
    try:
        rc, out = _run(_CHILD_POS, root=root)
        print(out.rstrip())
        return rc == 0
    finally:
        shutil.rmtree(root, ignore_errors=True)


def negative():
    """把 _FORWARDED_PRIVATE 污染成空集合 ⇒ 用户报错必须逐字重现。"""
    tmp = tempfile.mkdtemp(prefix="vt_rl_neg_")
    root = tempfile.mkdtemp(prefix="vt_rl_negroot_")
    try:
        src_file = os.path.join(SRC, "engine_cache.py")
        with open(src_file, encoding="utf-8") as f:
            txt = f.read()
        anchor = "_FORWARDED_PRIVATE = frozenset({\"_sql\"})"
        if anchor not in txt:
            print("负向：未找到注入点（engine_cache._FORWARDED_PRIVATE），"
                  "跳过——不代表检查有效")
            return False
        polluted = txt.replace(anchor, "_FORWARDED_PRIVATE = frozenset()", 1)
        if polluted == txt:
            print("负向：污染未生效，跳过")
            return False
        dst = os.path.join(tmp, "engine_cache.py")
        with open(dst, "w", encoding="utf-8") as f:
            f.write(polluted)
        # 验证污染真落进副本（防「锚点选错 → 形同虚设」）
        with open(dst, encoding="utf-8") as f:
            if "_FORWARDED_PRIVATE = frozenset()" not in f.read():
                print("FAIL 负向：污染未落入真实代码行")
                return False
        rc, out = _run(_CHILD_NEG, extra_path=tmp, root=root)
        print(out.rstrip())
        if rc == 3:
            print("OK   负向：去掉 _sql 放行后，用户报错逐字重现")
            return True
        print("FAIL 负向：污染后未复现「Failed to query rate limit: _sql」"
              "（rc=%d）——正向检查可能形同虚设" % rc)
        return False
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        shutil.rmtree(root, ignore_errors=True)


def main():
    print("=" * 62)
    print("限流查询 _sql 代理转发自检（engine_cache ↔ 引擎 BaseASR）")
    print("=" * 62)
    print("\n[1/2] 正向：宿主接线下引擎限流查询跑通")
    ok1 = positive()
    print("\n[2/2] 负向：污染 _FORWARDED_PRIVATE 后报错必须重现")
    ok2 = negative()
    print("\n" + "=" * 62)
    print("结论：", "PASS" if (ok1 and ok2) else "FAIL")
    return 0 if (ok1 and ok2) else 1


if __name__ == "__main__":
    sys.exit(main())
