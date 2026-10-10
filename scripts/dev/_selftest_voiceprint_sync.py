#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# @version 1.19.0
"""声纹模板多用户同步自检（离线：临时目录模拟两个客户端 + 一个共享哑存储根）。

覆盖 `src/voiceprint_sync.py`（独立通道）与产生端 `src/speaker_voiceprint.py`
的挂接：
  · 条目 schema 校验、id 幂等（同作者同名同内容必同 id）
  · 确定性合并 `merge()`：取代链 / 同名 alive 条目**全保留**（折叠输入）/
    tombstone / 删除后复活 / 重复拉取幂等
  · `fold_leaves` 加权并集折叠：单叶透传（保指纹）、双叶加权归一、fp 去重、
    顺序无关、同人守卫、trusted（本地在野叶优先）
  · **多用户数据迭代**：A/B 各录同一主播 -> 双方 push -> C sync 落地为
    两叶折叠（方向 = 加权均值、clips 累加、sources 记双方）
  · 端到端两客户端：A 录入 -> push -> B sync 落地（带 sync 标记）-> B 再 sync 幂等
  · 重录传播（supersedes 链不产生冲突；自录副本重建本机条目 id）
  · 删除传播（tombstone + 向量指纹保护；合并模板指纹不同天然不被误删）
  · 「本地自录优先」：B 自录同名异人**不被覆盖**，条目进 conflict.json 隔离
  · `selection.json` 是本地偏好不进通道；`vp_inbox/` 与校准 `inbox/` 命名空间隔离
  · 产生端：save_template / delete_template 自动排队列；VT_NO_VP_SYNC 可单独关停
  · 待传队列冲刷：成功即清；远端不可用时保留待下次补传

⚠ 本自检**不碰真实数据目录**：全程把 `voiceprint_sync._data_dir` 与
`VT_VP_SYNC_ROOT` 指到临时目录，speaker_voiceprint.TEMPLATE_DIR 一并重定向。

运行：tools/python/python.exe scripts/dev/_selftest_voiceprint_sync.py
结果同时打印到 stdout 并写入 C:\\bld\\_vp_sync_test\\result.txt。
"""
import json
import math
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "src"))
os.environ.setdefault("VT_NO_PIPELINE", "1")
os.environ.setdefault("VT_NO_SYNC", "1")
# 声纹通道要**显式打开**（本自检就是测它）；真实数据目录靠下面的重定向隔离
os.environ.pop("VT_NO_VP_SYNC", None)

import voiceprint_sync as V          # noqa: E402
import speaker_voiceprint as SV      # noqa: E402

OUT = r"C:\bld\_vp_sync_test"
LINES, FAILS = [], []


def say(m):
    LINES.append(str(m))
    print(m)


def check(name, cond, extra=""):
    line = "  [%s] %s%s" % ("PASS" if cond else "FAIL", name,
                            (" -> " + str(extra)) if extra != "" else "")
    say(line)
    if not cond:
        FAILS.append(name)


def mk_template(name, seed=1.0, seconds=12.5):
    """造一个假模板（192 维，round(6) 与真实落盘口径一致）。

    ⚠ 用**按 seed 播种的 RNG** 生成。早先用 `((seed*1000+i*37) % 997)` 这类
    线性式踩过两个坑：① seed 相差 7 的整数倍时逐元素同余（两个"不同"seed
    同向量）；② 修掉①后不同 seed 之间仍是**循环移位**关系——seed 2.0 与 9.0
    实测余弦 0.999，「本地自录 vs 远端异人」的冲突分支永远测不到（折叠守卫
    把两个"异人"当同人合并了）。RNG 保证：不同 seed 必不同向量，且两两
    余弦 ≈ 0（|cos| < 0.3，192 维随机向量的自然水平）。"""
    import random as _random
    rng = _random.Random("vp-tpl|%s" % seed)
    emb = [round(rng.uniform(-0.5, 0.5), 6) for _i in range(192)]
    return {"name": str(name), "dim": 192,
            "created": "2026-10-09 20:00:00", "embedding": emb,
            "source": "demo.mp4", "start": 0.0, "dur": seconds,
            "seconds": seconds}


def read_json(path):
    with open(path, encoding="utf-8-sig") as f:
        return json.load(f)


def entry_value(name, seed):
    return json.dumps(mk_template(name, seed), ensure_ascii=False)


def mk_unit(name, deg, seconds=10.0):
    """单位向量模板（角度制，cos(deg) 即两模板余弦）——折叠数学用例专用。

    与 mk_template 的伪随机向量不同：这里 embedding 是单位向量、且两模板
    夹角可控，fold 的加权归一结果可以精确断言。"""
    import math as _m
    emb = [round(_m.cos(_m.radians(deg)), 6), round(_m.sin(_m.radians(deg)), 6)]
    emb += [0.0] * 190
    return {"name": str(name), "dim": 192, "created": "2026-10-09 20:00:00",
            "embedding": emb, "seconds": seconds, "weight": 1.0, "clips": 1,
            "mix": [{"fp": V.embedding_fp(emb), "v": emb, "w": 1.0, "n": 1,
                     "author": ""}]}


def unit_leaf(deg, author=""):
    import math as _m
    v = [round(_m.cos(_m.radians(deg)), 6), round(_m.sin(_m.radians(deg)), 6)]
    v += [0.0] * 190
    return {"fp": V.embedding_fp(v), "v": v, "w": 1.0, "n": 1,
            "author": author}


class Client:
    """模拟一个客户端：独立数据根（模板目录 + 通道状态），共享同一个远端根。

    激活时把 `voiceprint_sync._data_dir` 与 `VT_VP_SYNC_ROOT` 指到本客户端，
    并清掉模块里的 client_id 缓存——两个客户端因此各有身份、互不串味。"""

    def __init__(self, base, remote, tag):
        self.base = base
        self.remote = remote
        self.tag = tag
        self.data = os.path.join(base, tag, "data")
        self.vp = os.path.join(self.data, "voiceprint")
        os.makedirs(self.vp, exist_ok=True)

    def __enter__(self):
        self._undo = (V._data_dir, os.environ.get("VT_VP_SYNC_ROOT"),
                      SV.TEMPLATE_DIR, dict(V._CFG_CACHE))
        V._data_dir = lambda: self.data
        os.environ["VT_VP_SYNC_ROOT"] = self.remote
        SV.TEMPLATE_DIR = self.vp
        V._CFG_CACHE.clear()
        return self

    def __exit__(self, *exc):
        fn, root, tpl, cache = self._undo
        V._data_dir = fn
        if root is None:
            os.environ.pop("VT_VP_SYNC_ROOT", None)
        else:
            os.environ["VT_VP_SYNC_ROOT"] = root
        SV.TEMPLATE_DIR = tpl
        V._CFG_CACHE.clear()
        V._CFG_CACHE.update(cache)
        return False

    @property
    def client_id(self):
        return V.config()["client_id"]

    def pending(self):
        p = V._pending_path()
        if not os.path.isfile(p):
            return []
        with open(p, encoding="utf-8") as f:
            return [json.loads(x) for x in f if x.strip()]

    def files(self):
        d = self.vp
        return sorted(f for f in os.listdir(d) if f.endswith(".json")) \
            if os.path.isdir(d) else []


def main():
    say("=" * 62)
    say("  声纹模板多用户同步自检（voiceprint_sync，独立通道）")
    say("=" * 62)

    tmp = tempfile.mkdtemp(prefix="vt_vpsync_")
    remote = os.path.join(tmp, "store")          # 共享哑存储根
    os.makedirs(remote, exist_ok=True)

    try:
        # ---------------- 1) 条目 schema / id 幂等 ----------------
        say("\n== 1) 条目 schema 与 id 幂等 ==")
        e1 = V.make_entry("cidA", "主播", "upsert", entry_value("主播", 1.0),
                          None, {"fp": V.embedding_fp(mk_template("主播", 1.0)["embedding"])})
        ok, why = V.entry_valid(e1)
        check("合法 upsert 通过校验", ok, why)
        for f in ("id", "author", "ts", "op", "key", "value", "supersedes",
                  "evidence"):
            check("条目含必填字段 %s" % f, f in e1)
        e1b = V.make_entry("cidA", "主播", "upsert", entry_value("主播", 1.0))
        check("同作者同名同内容 -> 同 id（幂等键）", e1["id"] == e1b["id"],
              (e1["id"], e1b["id"]))
        e1c = V.make_entry("cidB", "主播", "upsert", entry_value("主播", 1.0))
        check("不同作者 -> 不同 id", e1["id"] != e1c["id"])
        e1d = V.make_entry("cidA", "主播", "upsert", entry_value("主播", 2.0))
        check("同作者同名字不同向量 -> 不同 id", e1["id"] != e1d["id"])
        bad = dict(e1, value="{不是 JSON")
        check("value 非 JSON 被拒", V.entry_valid(bad)[0] is False,
              V.entry_valid(bad)[1])
        bad2 = dict(e1, value=json.dumps({"name": "x"}))
        check("缺 embedding 被拒", V.entry_valid(bad2)[0] is False,
              V.entry_valid(bad2)[1])
        bad3 = dict(e1, op="upsert", value="")
        check("upsert 空 value 被拒", V.entry_valid(bad3)[0] is False)
        tomb = V.make_entry("cidA", "主播", "tombstone", "", None, {"fp": "x"})
        check("tombstone（空 value）合法", V.entry_valid(tomb)[0],
              V.entry_valid(tomb)[1])
        bad4 = dict(e1, op="upsert2")
        check("op 非法被拒", V.entry_valid(bad4)[0] is False)
        check("指纹稳定（同向量同指纹）",
              V.embedding_fp([0.1, 0.2]) == V.embedding_fp([0.1, 0.2]))
        check("指纹区分不同向量",
              V.embedding_fp([0.1, 0.2]) != V.embedding_fp([0.1, 0.3]))
        check("假模板生成器：不同 seed 必产生不同向量（防测试数据自身同余）",
              len({V.embedding_fp(mk_template("x", s)["embedding"])
                   for s in (1.0, 2.0, 3.0, 9.0)}) == 4,
              sorted({V.embedding_fp(mk_template("x", s)["embedding"])
                      for s in (1.0, 2.0, 3.0, 9.0)}))
        check("假模板生成器：不同 seed 两两余弦 ≈ 0（折叠守卫分支可测）",
              max(abs(V._vec_cos(mk_template("x", a)["embedding"],
                                 mk_template("x", b)["embedding"]))
                  for a in (1.0, 2.0, 3.0, 9.0) for b in (1.0, 2.0, 3.0, 9.0)
                  if a != b) < 0.3)
        check("文件名净化与 speaker_voiceprint 同规则",
              V.safe_name('a/b:c*?"<>|') == "abc"
              and V.safe_name("selection") == "selection_声纹"
              and V.safe_name("  ") == "主播",
              V.safe_name('a/b:c*?"<>|'))

        # ---------------- 2) 确定性合并 ----------------
        say("\n== 2) merge()：取代链 / alive 全保留 / tombstone / 幂等 ==")
        a, d, rep = V.merge([e1])
        check("单条 upsert -> 生效 1", list(a) == ["主播"] and not d, rep)
        check("生效值为条目**列表**（折叠输入，单条时长度 1）",
              isinstance(a.get("主播"), list) and len(a["主播"]) == 1
              and a["主播"][0]["id"] == e1["id"])
        old = V.make_entry("cidA", "主播", "upsert", entry_value("主播", 1.0))
        old["ts"] = "2026-10-01T00:00:00.000+00:00"
        new = V.make_entry("cidA", "主播", "upsert", entry_value("主播", 2.0),
                           supersedes=old["id"])
        new["ts"] = "2026-10-02T00:00:00.000+00:00"
        a, d, rep = V.merge([old, new])
        check("重录带 supersedes -> 只有新条目生效",
              len(a.get("主播", [])) == 1 and a["主播"][0]["id"] == new["id"]
              and rep["superseded"] == 1, rep)
        x1 = V.make_entry("cidA", "主播", "upsert", entry_value("主播", 1.0))
        x1["ts"] = "2026-10-01T00:00:00.000+00:00"
        x2 = V.make_entry("cidB", "主播", "upsert", entry_value("主播", 3.0))
        x2["ts"] = "2026-10-03T00:00:00.000+00:00"
        a, d, rep = V.merge([x2, x1])            # 故意乱序传入
        check("同名无取代关系 -> alive **全部保留**（按 ts 排序，供折叠）",
              [e["id"] for e in a["主播"]] == [x1["id"], x2["id"]],
              [e["ts"] for e in a["主播"]])
        t1 = V.make_entry("cidA", "主播", "tombstone", "", None, {"fp": "f"})
        t1["ts"] = "2026-10-04T00:00:00.000+00:00"
        a, d, rep = V.merge([x1, x2, t1])
        check("最新为 tombstone -> 进删除集、不进生效集",
              "主播" not in a and d.get("主播", {}).get("id") == t1["id"], rep)
        x3 = V.make_entry("cidB", "主播", "upsert", entry_value("主播", 4.0))
        x3["ts"] = "2026-10-05T00:00:00.000+00:00"
        a, d, rep = V.merge([x1, x2, t1, x3])
        check("删除后再录入（ts 更新）-> 复活",
              len(a.get("主播", [])) == 1 and a["主播"][0]["id"] == x3["id"]
              and not d, rep)
        a2, d2, rep2 = V.merge([x1, x2, t1, x3] * 3)
        check("重复拉取同一批条目 -> 结果完全一致（幂等）",
              a2 == a and d2 == d and rep2 == rep, rep2)
        a3, d3, rep3 = V.merge([])
        check("空输入 -> 空生效集", not a3 and not d3, rep3)

        # ---------------- 2b) fold_leaves 折叠数学 ----------------
        say("\n== 2b) fold_leaves：加权并集 / 去重 / 守卫 / trusted ==")
        la, lb = unit_leaf(0.0, "authA"), unit_leaf(10.0, "authB")
        obj, rej = V.fold_leaves([la, lb])
        import math as _math
        exp_w = 2.0 * _math.cos(_math.radians(5.0))   # |u0 + u10| = 2cos(5°)
        check("双叶折叠：方向 = 加权均值方向（5°）",
              abs(obj["embedding"][0] - _math.cos(_math.radians(5))) < 1e-5
              and abs(obj["embedding"][1] - _math.sin(_math.radians(5))) < 1e-5,
              obj["embedding"][:2])
        check("双叶折叠：weight = |Σ w·v|", abs(obj["weight"] - exp_w) < 1e-4,
              obj["weight"])
        check("双叶折叠：clips 累加 / mix 双叶 / sources 合并",
              obj["clips"] == 2 and len(obj["mix"]) == 2
              and obj["sources"] == ["authA", "authB"], obj)
        check("同人叶子不被拒绝", rej == [], rej)
        o2, _ = V.fold_leaves([lb, la])          # 乱序同集
        check("折叠与输入顺序无关（交换律）",
              o2["embedding"] == obj["embedding"]
              and o2["weight"] == obj["weight"])
        o3, _ = V.fold_leaves([la, la, lb])      # 重复叶子
        check("同 fp 去重（重复上传不双计）",
              o3["embedding"] == obj["embedding"] and len(o3["mix"]) == 2)
        single = V.fold_leaves([lb])[0]
        check("单叶透传：embedding 逐字节不变（保指纹，兼容旧同步副本）",
              single["embedding"] == lb["v"] and single["clips"] == 1
              and len(single["mix"]) == 1)
        far_a, far_b = unit_leaf(0.0), unit_leaf(90.0)
        obj_f, rej_f = V.fold_leaves([far_a, far_b])
        check("异人守卫（0° vs 90°）：恰一叶被拒",
              len(obj_f["mix"]) == 1 and len(rej_f) == 1, (obj_f, rej_f))
        check("守卫确定性：fp 较小者优先入场",
              obj_f["mix"][0]["fp"] == min(far_a["fp"], far_b["fp"]),
              obj_f["mix"][0]["fp"])
        obj_t, rej_t = V.fold_leaves([far_a, far_b], trusted={far_b["fp"]})
        check("trusted（本地在野叶）优先入场且不过守卫",
              obj_t["mix"][0]["fp"] == far_b["fp"] and len(rej_t) == 1
              and rej_t[0]["fp"] == far_a["fp"], obj_t["mix"])
        legacy = {"name": "旧", "embedding": far_a["v"]}
        lv = V.template_leaves(legacy, author="cidX")
        check("无 mix 旧模板合成单叶（weight/clips 缺省 1）",
              len(lv) == 1 and lv[0]["w"] == 1.0 and lv[0]["n"] == 1
              and lv[0]["fp"] == far_a["fp"] and lv[0]["author"] == "cidX", lv)
        check("旧模板叶子 cos 可用", abs(V._vec_cos(lv[0]["v"], far_a["v"]) - 1.0)
              < 1e-9)

        # ---------------- 3) 端到端：A 录入 -> B 落地 ----------------
        say("\n== 3) 端到端：A 录入并推送，B 拉取落地 ==")
        with Client(tmp, remote, "A") as A:
            SV.save_template("主播", mk_template("主播", 1.0)["embedding"],
                             source="demo.mp4", seconds=12.5)
            check("A 本地模板已落盘", "主播.json" in A.files(), A.files())
            check("A 自录模板**不带** sync 标记",
                  not read_json(os.path.join(A.vp, "主播.json")).get("sync"))
            q = A.pending()
            check("录入排入待传队列 1 条", len(q) == 1, len(q))
            check("待传条目 schema 合法", V.entry_valid(q[0])[0],
                  V.entry_valid(q[0])[1] if q else "-")
            check("待传条目 key = 声纹名", q and q[0]["key"] == "主播")
            n = V.push(quiet=True)
            check("push 返回上传条数 1", n == 1, n)
            check("push 后待传队列已清", A.pending() == [], A.pending())
            inbox = os.path.join(remote, V.INBOX_SUB, A.client_id)
            check("远端 vp_inbox 出现本机收件箱文件",
                  os.path.isdir(inbox) and len(os.listdir(inbox)) == 1,
                  os.listdir(inbox) if os.path.isdir(inbox) else "-")
            check("校准 inbox/ 未被声纹通道写入",
                  not os.path.isdir(os.path.join(remote, "inbox")))

        with Client(tmp, remote, "B") as B:
            check("B 同步前没有模板", B.files() == [], B.files())
            ok = V.sync(quiet=True)
            check("B sync 成功", ok is True)
            check("B 落地了 A 的模板", "主播.json" in B.files(), B.files())
            got = read_json(os.path.join(B.vp, "主播.json"))
            check("B 的副本带 sync 标记", got.get("sync") is True)
            check("B 的副本记录来源条目 id", bool(got.get("sync_id")))
            check("B 的副本记录来源作者（前 8 位）",
                  len(str(got.get("sync_author"))) == 8, got.get("sync_author"))
            check("B 的向量与 A 一致",
                  V.embedding_fp(got["embedding"])
                  == V.embedding_fp(mk_template("主播", 1.0)["embedding"]))
            m1 = os.path.getmtime(os.path.join(B.vp, "主播.json"))
            V.sync(quiet=True)
            m2 = os.path.getmtime(os.path.join(B.vp, "主播.json"))
            check("重复 sync 幂等（同向量不重写文件）", m1 == m2)
            st = V.status()
            check("status 报告 1 个模板且为同步副本",
                  st["templates"] == 1 and st["synced"] == 1, st)
            check("status 不含冲突", st["conflicts"] == 0, st)

        # ---------------- 4) 重录传播（supersedes 链）----------------
        say("\n== 4) A 重录同名模板 -> B 收敛到新向量（不算冲突）==")
        with Client(tmp, remote, "A") as A:
            p = os.path.join(A.vp, "主播.json")
            prev_obj = read_json(p)
            # A 的本地副本是自录（无 sync_id）：supersedes 应能由文件内容
            # **确定性重建**出本机旧条目 id（fold 语义下缺 supersedes 会让
            # 旧片段折进新模板——「重录=替换」退化成「重录=追加」）
            SV.save_template("主播", mk_template("主播", 2.0)["embedding"],
                             source="demo2.mp4", seconds=20.0)
            q = A.pending()
            check("重录排入 1 条待传", len(q) == 1, len(q))
            check("重录条目 supersedes = 本机旧条目 id（由文件内容重建）",
                  q and q[0]["supersedes"] == V.own_entry_id("主播", prev_obj),
                  q[0]["supersedes"] if q else "-")
            check("自录重录的条目 id 可确定性重建（同内容必同 id）",
                  V.own_entry_id("主播", prev_obj)
                  == V.own_entry_id("主播", json.loads(json.dumps(prev_obj))))
            V.push(quiet=True)
        with Client(tmp, remote, "B") as B:
            V.sync(quiet=True)
            got = read_json(os.path.join(B.vp, "主播.json"))
            check("B 的副本已更新为重录后的向量",
                  V.embedding_fp(got["embedding"])
                  == V.embedding_fp(mk_template("主播", 2.0)["embedding"]))
            check("B 侧无冲突隔离", V.status()["conflicts"] == 0,
                  V.status()["conflicts"])

        # ---------------- 5) 本地自录优先（冲突隔离）----------------
        say("\n== 5) B 自录同名不同向量 -> 不被覆盖，进 conflict.json ==")
        with Client(tmp, remote, "B") as B:
            SV.save_template("主播", mk_template("主播", 9.0)["embedding"])
            mine = V.embedding_fp(read_json(
                os.path.join(B.vp, "主播.json"))["embedding"])
            B.pending()                          # 清不掉也无妨，下面只看落地
            os.remove(V._pending_path())         # 本组不测推送
            V.sync(quiet=True)
            got = read_json(os.path.join(B.vp, "主播.json"))
            check("B 的自录模板未被远端覆盖",
                  V.embedding_fp(got["embedding"]) == mine)
            check("B 的自录模板仍无 sync 标记", not got.get("sync"))
            cp = os.path.join(V.state_dir(), "conflict.json")
            check("冲突已写隔离区", os.path.isfile(cp), cp)
            conf = read_json(cp) if os.path.isfile(cp) else {}
            check("隔离区记录了该声纹名",
                  "主播" in (conf.get("conflicts") or {}), list(conf.get("conflicts") or {}))
            check("status 报告 1 条冲突", V.status()["conflicts"] == 1,
                  V.status()["conflicts"])

        # ---------------- 5b) 多用户录同一主播 -> 折叠迭代 ----------------
        say("\n== 5b) 多用户录同一主播 -> 数据迭代（向量加权并集折叠）==")
        u5 = math.cos(math.radians(5))
        u5s = math.sin(math.radians(5))
        exp_fold = V.fold_leaves([unit_leaf(0.0, "A"), unit_leaf(10.0, "B")])[0]
        with Client(tmp, remote, "A") as A:
            aid = A.client_id[:8]
            SV.save_template("双录", mk_unit("双录", 0.0)["embedding"],
                             seconds=10.0)
            V.push(quiet=True)
        with Client(tmp, remote, "B") as B:
            bid = B.client_id[:8]
            SV.save_template("双录", mk_unit("双录", 10.0)["embedding"],
                             seconds=10.0)
            V.push(quiet=True)
        with Client(tmp, remote, "D") as D:
            V.sync(quiet=True)
            got = read_json(os.path.join(D.vp, "双录.json"))
            check("D 落地的是两叶折叠结果（mix 双叶）",
                  len(got.get("mix") or []) == 2, len(got.get("mix") or []))
            check("折叠向量方向 = 加权均值（0°与10° -> 5°）",
                  abs(got["embedding"][0] - u5) < 1e-4
                  and abs(got["embedding"][1] - u5s) < 1e-4, got["embedding"][:2])
            check("clips 累加 = 2", got.get("clips") == 2, got.get("clips"))
            check("sources 记录双方贡献者",
                  set(got.get("sources") or []) == {aid, bid}, got.get("sources"))
            check("D 的副本带 sync 标记", got.get("sync") is True)
            check("D 未产生冲突（同人守卫通过）",
                  V.status()["conflicts"] == 0, V.status()["conflicts"])
            m1 = os.path.getmtime(os.path.join(D.vp, "双录.json"))
            V.sync(quiet=True)
            m2 = os.path.getmtime(os.path.join(D.vp, "双录.json"))
            check("再次 sync 幂等（折叠结果不变不重写）", m1 == m2)
        with Client(tmp, remote, "A") as A:
            V.sync(quiet=True)
            got_a = read_json(os.path.join(A.vp, "双录.json"))
            check("A sync 后也收敛到同一折叠结果",
                  V.embedding_fp(got_a["embedding"])
                  == V.embedding_fp(exp_fold["embedding"]),
                  got_a["embedding"][:2])
            check("A 的叶子已在远端：收敛后不产生多余回播",
                  V.pending_count() == 0, V.pending_count())
        with Client(tmp, remote, "B") as B:
            V.sync(quiet=True)
            got_b = read_json(os.path.join(B.vp, "双录.json"))
            check("B sync 后也收敛到同一折叠结果",
                  V.embedding_fp(got_b["embedding"])
                  == V.embedding_fp(exp_fold["embedding"]))

        # ---------------- 6) 删除传播 + 指纹保护 ----------------
        say("\n== 6) 删除传播（tombstone）与指纹保护 ==")
        with Client(tmp, remote, "C") as C:
            V.sync(quiet=True)                   # C 先拿到 A 的模板（同步副本）
            check("C 落地了同步副本", "主播.json" in C.files(), C.files())
            check("C 的副本带 sync 标记",
                  read_json(os.path.join(C.vp, "主播.json")).get("sync") is True)
            # 启用名单里放上它，验证删除会同步摘除
            with open(os.path.join(C.vp, "selection.json"), "w",
                      encoding="utf-8") as f:
                f.write(json.dumps({"enabled": ["主播"], "updated": ""},
                                   ensure_ascii=False))
        with Client(tmp, remote, "A") as A:
            check("A 删除返回 True", SV.delete_template("主播") is True)
            q = A.pending()
            check("删除排入 tombstone 1 条",
                  len(q) == 1 and q[0]["op"] == "tombstone", q)
            check("tombstone 带被删副本的向量指纹",
                  bool((q[0].get("evidence") or {}).get("fp")) if q else False)
            V.push(quiet=True)
        with Client(tmp, remote, "C") as C:
            V.sync(quiet=True)
            check("C 的同步副本已被删除", "主播.json" not in C.files(), C.files())
            sel = read_json(os.path.join(C.vp, "selection.json"))
            check("启用名单同步摘除该名字", sel.get("enabled") == [], sel)
        # 指纹保护：B 本地是自录（向量与 tombstone 证据不同），不该被删
        with Client(tmp, remote, "B") as B:
            before = B.files()
            V.sync(quiet=True)
            check("指纹不匹配的本地自录副本不被 tombstone 误删",
                  "主播.json" in B.files() and B.files() == before,
                  (before, B.files()))

        # ---------------- 7) selection 不进通道 / 命名空间隔离 ----------------
        say("\n== 7) 本地偏好不同步 + 与校准通道命名空间隔离 ==")
        with Client(tmp, remote, "A") as A:
            # 启用名单是本地偏好：先写一份，确认它不会进通道
            with open(os.path.join(A.vp, "selection.json"), "w",
                      encoding="utf-8") as f:
                f.write(json.dumps({"enabled": ["嘉宾"], "updated": ""},
                                   ensure_ascii=False))
            SV.save_template("嘉宾", mk_template("嘉宾", 5.0)["embedding"])
            q = A.pending()
            check("只有模板进队列（selection 不进通道）",
                  q and all(x["key"] != "selection" for x in q),
                  [x["key"] for x in q])
            V.push(quiet=True)
        keys = []
        for _cid, _fn, path in V._inbox_files(remote):
            with open(path, encoding="utf-8") as f:
                keys += [json.loads(x)["key"] for x in f if x.strip()]
        check("远端 vp_inbox 里没有 selection 条目",
              "selection" not in keys, sorted(set(keys)))
        check("声纹收件箱在独立子目录 vp_inbox/",
              V.INBOX_SUB == "vp_inbox"
              and os.path.isdir(os.path.join(remote, "vp_inbox")))
        check("声纹通道不读校准的 inbox/",
              not os.path.isdir(os.path.join(remote, "inbox")))

        # ---------------- 8) 产生端开关与队列韧性 ----------------
        say("\n== 8) 产生端：VT_NO_VP_SYNC 关停 / 远端不可用保留队列 ==")
        with Client(tmp, remote, "A") as A:
            if os.path.isfile(V._pending_path()):
                os.remove(V._pending_path())
            os.environ[V.DISABLE_ENV] = "1"
            try:
                check("关停后 enabled() = False", V.enabled() is False)
                SV.save_template("临时", mk_template("临时", 7.0)["embedding"])
                check("关停时录入**不**排队列", A.pending() == [], A.pending())
                check("关停时录入仍正常落盘", "临时.json" in A.files(), A.files())
            finally:
                os.environ.pop(V.DISABLE_ENV, None)
            check("恢复后 enabled() = True", V.enabled() is True)
            os.environ[V.DISABLE_ENV] = "0"
            check("VT_NO_VP_SYNC=0 视为启用（只有真值才关停）",
                  V.enabled() is True)
            os.environ.pop(V.DISABLE_ENV, None)
            SV.delete_template("临时")
            check("删除也排队列（tombstone）",
                  len(A.pending()) == 1 and A.pending()[0]["op"] == "tombstone",
                  A.pending())
            # 远端不可用：把远端根指到「一个文件的下面」（makedirs 必抛 OSError），
            # 而不是"不存在的路径"——后者会被 _push_entries 的 makedirs 直接建出来，
            # 于是推送照样成功、测不到"保留队列等下次"这条分支。
            blocker = os.path.join(tmp, "blocker.dat")
            with open(blocker, "w", encoding="utf-8") as f:
                f.write("x")
            os.environ["VT_VP_SYNC_ROOT"] = os.path.join(blocker, "store")
            try:
                V.push(quiet=True)
                check("远端不可用时队列保留（下次补传）",
                      len(A.pending()) == 1, A.pending())
                check("远端不可用时已本机留档",
                      os.path.isdir(os.path.join(V.state_dir(), "local_log")),
                      os.listdir(os.path.join(V.state_dir(), "local_log"))
                      if os.path.isdir(os.path.join(V.state_dir(), "local_log")) else "-")
            finally:
                os.environ["VT_VP_SYNC_ROOT"] = remote
            n = V.push(quiet=True)
            check("远端恢复后补传成功", n == 1, n)
            check("补传后队列已清", A.pending() == [], A.pending())

        # ---------------- 9) CLI 入口 ----------------
        say("\n== 9) CLI 入口（status / sync / push 不抛异常）==")
        with Client(tmp, remote, "B") as B:
            for argv in (["status"], ["sync"], ["push"], ["坏命令"]):
                try:
                    rc = V._main(argv)
                    check("CLI %s 正常返回（rc=%s）" % (argv[0], rc),
                          isinstance(rc, int))
                except Exception as e:  # noqa: BLE001
                    check("CLI %s 正常返回" % argv[0], False, repr(e)[:120])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    say("\n" + "=" * 62)
    if FAILS:
        say("  结果：%d 项失败" % len(FAILS))
        for x in FAILS:
            say("   · " + x)
    else:
        say("  结果：全部通过")
    say("=" * 62)
    try:
        os.makedirs(OUT, exist_ok=True)
        with open(os.path.join(OUT, "result.txt"), "w", encoding="utf-8") as f:
            f.write("\n".join(LINES) + "\n")
    except OSError:
        pass
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
