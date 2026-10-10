# -*- coding: utf-8 -*-
# @version 1.19.0
"""主播声纹模板的多用户同步（**独立通道**，与字幕校准知识同步互不干涉）。

为什么单独一套而不并进 `subtitle_calib_merged.py` 的 kb-sync 通道：
  · 数据形态不同——校准知识是「错形→正形」的词条（人可读、可裁决、可固化进
    脚本内置表），声纹模板是**二进制性质的 192 维向量**（约 2.8KB/条），
    没有「固化进代码」这一步，也不该被校准的三道门（实体注册冲突 / kb-lint /
    terms-check 二次命中）检查；
  · 生命周期不同——模板随主播/节目变化重录，删除是常态（tombstone 必须真删
    本地文件），而校准词条只做并集、从不删除；
  · 责任边界不同——校准知识由 kb_admin 管理端折叠基线，声纹没有基线概念
    （纯 inbox 并集即生效集），管理端不需要认识它。

因此本模块自带：条目 schema、确定性合并、落地裁决、待传队列、状态目录与 CLI，
**只复用「哑存储根」这一层传输**（GitHub kb 分支 / 共享目录整树发布时会一并
带走），数据落在该根下独立的 `vp_inbox/` 命名空间——校准通道只枚举
`inbox/`，永远看不到声纹条目，反之亦然。

============================================================
数据布局
============================================================
  <data>/voiceprint/<名>.json          模板本体（speaker_voiceprint 写，本模块落地同步副本）
  <data>/voiceprint/selection.json     启用名单——**本地偏好，刻意不同步**
  <data>/vp_sync/config.json           本机 client_id 与水位线
  <data>/vp_sync/pending.jsonl         待传队列（录入/删除时由产生端追加）
  <data>/vp_sync/local_log/<cid>/*.jsonl   本机上传留档（远端不可用时靠它补传）
  <data>/vp_sync/conflict.json         「本地自录优先」的冲突隔离区
  <data>/vp_sync/vp_sync.log           运行日志
  <远端根>/vp_inbox/<cid>/<ts>-<hex4>.jsonl   各客户端收件箱（只新建、绝不改写他人文件）

远端根：`VT_VP_SYNC_ROOT` > `VT_SYNC_ROOT` > `<data>/calib_sync_remote`
（与校准共用同一个哑存储根，但子目录不同；这样 kb_admin publish/pull 整树
发布时声纹条目自动随行，无需第二套发布通道）。

============================================================
条目 schema（自带，比校准 FR-1 精简：无 table/mode，单一用途）
============================================================
  {"id": uuid5(URL, "vp|<author>|<key>|<value>"),   # 幂等键：同内容必同 id
   "author": "<client_id>", "ts": "<UTC ISO8601 毫秒>",
   "op": "upsert" | "tombstone",
   "key": "<声纹名>", "value": "<模板 JSON 字符串>" | "",
   "supersedes": "<被取代条目 id>" | null,          # 重录链：新条目取代旧条目
   "evidence": {"fp": "<向量指纹16位>", "seconds": .., "source": ..}}

模板 value 的迭代字段（折叠语义引入时新增）：
  embedding   聚合单位向量（消费方只读它，schema 不变）
  weight      该聚合的合成长度 |Σ 片段向量|（缺省 1.0 = 单片段）
  clips       参与聚合的片段数
  mix         叶子列表 [{fp, v, w, n, author}]——每次录入/追加动作产生的
              (聚合向量, 权重, 片段数, 来源)；折叠按 fp 去重，是跨客户端
              收敛的并集语义载体
  sources     贡献者 client_id 前 8 位列表（谁录的，展示用）

合并语义（NFR：同输入必同输出，任意多客户端反复拉推收敛）：
  生效集 = 全部收件箱条目按 (ts, id) 全局序重放；被 supersedes 的条目失效；
  同 key 的全部 alive upsert **按向量加权并集折叠**（fold_leaves：按 fp 去重、
  按 fp 序累积、同人守卫拒绝异人叶子），不再「取最新一条覆盖」——这就是
  「不同用户录同一主播 → 数据迭代更准」的载体：每份上传都是并集的一份子；
  最新为 tombstone 则该 key 删除。id 幂等 ⇒ 重复拉取无害。

落地裁决（本地自有数据优先，与校准的学习库同思路）：
  upsert   本地无此名   -> 落盘为「同步副本」= 远端叶子折叠结果
           折叠指纹一致 -> 幂等跳过
           远端叶子与本地叶子同人（余弦 ≥ 0.55）-> **合并落盘**（未发布的
           本地叶子随合并值回播，其他客户端据此收敛）
           远端叶子与本地叶子不像同一人 -> 不写入该叶子，记 conflict.json 隔离
  tombstone 仅当本地副本指纹与证据一致才删（防「A 删除后 B 已本地重录」被误删；
           合并模板的指纹是折叠结果、与被删单份不同 ⇒ 天然保留他人贡献）。
           ⚠ 代价：删除者自己的片段无法从合并向量里剔除，属已知限制。

用法：
    python src/voiceprint_sync.py sync      # 推待传 + 拉取 + 合并 + 落地（幂等）
    python src/voiceprint_sync.py push      # 只把待传队列发出去
    python src/voiceprint_sync.py status    # 看本机/远端/冲突概况
引擎侧由 video_toolbox.sync_voiceprint_on_startup / _on_exit 自动调用。
全链路只 json.load，禁止 eval/exec；任何失败都静默降级，绝不影响录入与转录。
"""
import hashlib
import json
import math
import os
import sys
import time
import uuid as _uuid

#: 关闭本通道（独立开关，与校准的 VT_NO_SYNC / VT_NO_CALIB_SYNC 互不影响）
DISABLE_ENV = "VT_NO_VP_SYNC"
#: 远端根覆盖（默认与校准共用哑存储根，见模块文档）
ROOT_ENV = "VT_VP_SYNC_ROOT"
#: 状态目录覆盖（默认 <data>/vp_sync）
DIR_ENV = "VT_VP_SYNC_DIR"
#: 收件箱子目录名（与校准的 inbox/ 严格分开）
INBOX_SUB = "vp_inbox"
#: 待传队列文件名
PENDING_NAME = "voiceprint_pending.jsonl"

#: 折叠的同人守卫阈值：叶子（各用户上传的声纹聚合）间余弦低于它即判
#: 「不是同一主播」，拒绝写入并记冲突。**与 speaker_voiceprint.DEFAULT_THRESHOLD
#: （0.55）刻意同源**——低于判定边界的两份数据不该被合并成一份模板；
#: 这里不跨模块 import，保持本模块纯标准库、可独立跑。
FOLD_MIN_COS = 0.55
#: 本地模板文件上的同步标记键（入队 value 前剥掉，保证「文件内容 == 条目
#: value」恒成立——自录模板的条目 id 才能由文件内容确定性重建）。
SYNC_MARK_KEYS = ("sync", "sync_id", "sync_author", "sync_ts", "fold_key")


# ---------------------------------------------------------------- 路径解析
def _data_dir():
    """**数据目录**（= 引擎 `DATA_DIR`，即 `<数据根>\\data`）。

    ⚠ 别与 `VT_DATA_ROOT` 混用：那个环境变量存的是**数据根**（引擎
    `DATA_ROOT`，见 video_toolbox.py 的 `DATA_DIR = DATA_ROOT/data`），
    直接拿它当数据目录会把状态写到程序根下。

    取值顺序与 speaker_voiceprint._resolve_dirs 同口径：引擎常量优先
    （它同时处理源码运行 / 打包后 / 用户改过数据目录指针三种情形），
    引擎不可用时才按 VT_DATA_ROOT + `data` 推，最后从 src/ 向上找。"""
    try:
        import video_toolbox as _e
        d = getattr(_e, "DATA_DIR", "")
        if d:
            return d
    except Exception:  # noqa: BLE001  引擎不可用（纯 CLI / 循环 import 早期）
        pass
    r = (os.environ.get("VT_DATA_ROOT") or "").strip().strip('"')
    if r:
        return os.path.join(os.path.abspath(r), "data")
    d = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for _ in range(5):
        if os.path.isdir(os.path.join(d, "data")):
            return os.path.join(d, "data")
        p = os.path.dirname(d)
        if p == d:
            break
        d = p
    return os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "data")


def data_dir():
    return _data_dir()


def template_dir():
    """声纹模板目录（与 speaker_voiceprint.TEMPLATE_DIR 同口径）。"""
    return os.path.join(_data_dir(), "voiceprint")


def state_dir():
    """本通道状态目录（独立于校准的 data/calib_sync）。"""
    return os.environ.get(DIR_ENV) or os.path.join(_data_dir(), "vp_sync")


def remote_root():
    """哑存储根。VT_VP_SYNC_ROOT 可单独指定；缺省与校准共用 VT_SYNC_ROOT，
    再退回 <data>/calib_sync_remote（同一个根，不同子目录）。"""
    r = (os.environ.get(ROOT_ENV) or "").strip().strip('"')
    if r:
        return os.path.abspath(r)
    r = (os.environ.get("VT_SYNC_ROOT") or "").strip().strip('"')
    if r:
        return os.path.abspath(r)
    return os.path.join(_data_dir(), "calib_sync_remote")


def enabled():
    """通道是否启用（独立开关；不读校准的设置项，由引擎侧决定是否调用）。

    只有显式的真值才关停（1/true/yes/on）——`VT_NO_VP_SYNC=0` 视为启用，
    便于自检与脚本里显式打开。"""
    v = (os.environ.get(DISABLE_ENV) or "").strip().lower()
    return v not in ("1", "true", "yes", "on")


# ---------------------------------------------------------------- 基础工具
def _log(msg):
    """追加一行日志（best-effort，绝不因日志失败影响主流程）。"""
    try:
        os.makedirs(state_dir(), exist_ok=True)
        with open(os.path.join(state_dir(), "vp_sync.log"), "a",
                  encoding="utf-8") as f:
            f.write("[%s] %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg))
    except OSError:
        pass


def _dumps(obj):
    return json.dumps(obj, ensure_ascii=False)


def _loads(text):
    return json.loads(text)


def _now_iso():
    import datetime as _dt
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="milliseconds")


def _ts_sortkey(s):
    """ISO8601（带毫秒与时区）可直接字典序比较；异常值排最前。"""
    return s or ""


def embedding_fp(embedding):
    """向量指纹：对 round(6) 后的向量 JSON 取 sha256 前 16 位。

    产生端（speaker_voiceprint）与落地端都用它判「是不是同一个向量」——
    模板文件里的 embedding 本就是 round(6) 落盘的，两处口径天然一致。"""
    return hashlib.sha256(
        _dumps([round(float(x), 6) for x in (embedding or [])]).encode("utf-8")
    ).hexdigest()[:16]


# ---------------------------------------------------------------- 叶子与折叠
# 「同一主播多人贡献 → 数据迭代」的数学载体。每个叶子 = 一次录入/追加动作
# 产生的 (聚合向量 v, 合成长度 w, 片段数 n, 指纹 fp, 来源 author)；
# 折叠 = 按 fp 去重后对 {w·v} 求和归一（向量加法天然交换/结合/幂等，
# 任意客户端以任意顺序折叠同一叶子集必得同一结果）。同人守卫（FOLD_MIN_COS）
# 挡住「同名不同主播」的脏数据：拒绝的叶子进 conflict.json 由人工裁决。


def strip_sync_marks(obj):
    """剥掉同步标记键的模板副本（入队 value / 重建条目 id 用）。"""
    return {k: v for k, v in (obj or {}).items() if k not in SYNC_MARK_KEYS}


def own_entry_id(name, obj):
    """本机模板对应的通道条目 id（uuid5 确定性重建）。

    自录模板文件内容 == 当年入队的 value（save_template 同源写盘、入队前
    剥同步标记），故可用文件内容重建条目 id，作为重录/追加的 supersedes。
    不修这条的话：fold 语义下自录重录的旧条目仍 alive，旧片段会被折进
    新模板——「重录=替换」退化成「重录=追加」。"""
    cid = config()["client_id"]
    src = "vp|%s|%s|%s" % (cid, name, _dumps(strip_sync_marks(obj)))
    return str(_uuid.uuid5(_uuid.NAMESPACE_URL, src))


def _vec_cos(a, b):
    """纯标准库余弦（192 维 × 小数量级，性能无感；本模块刻意不依赖 numpy）。"""
    n = min(len(a), len(b))
    if n == 0:
        return 0.0
    dot = ssa = ssb = 0.0
    for i in range(n):
        x = float(a[i])
        y = float(b[i])
        dot += x * y
        ssa += x * x
        ssb += y * y
    if ssa <= 0.0 or ssb <= 0.0:
        return 0.0
    return dot / math.sqrt(ssa * ssb)


def template_leaves(obj, author=""):
    """模板 dict -> 叶子列表。无 mix 的旧模板合成单叶（向后兼容）。"""
    if not isinstance(obj, dict):
        return []
    mix = obj.get("mix")
    if isinstance(mix, list) and mix:
        out = []
        for m in mix:
            if not isinstance(m, dict) or not isinstance(m.get("v"), list) \
                    or not m["v"]:
                continue
            v = [round(float(x), 6) for x in m["v"]]
            try:
                w = float(m.get("w") or 1.0)
                n = int(m.get("n") or 1)
            except (TypeError, ValueError):
                w, n = 1.0, 1
            out.append({"fp": str(m.get("fp") or embedding_fp(v)), "v": v,
                        "w": w, "n": max(1, n),
                        "author": str(m.get("author") or author or "")})
        if out:
            return out
    emb = obj.get("embedding") or []
    if not emb:
        return []
    v = [round(float(x), 6) for x in emb]
    try:
        w = float(obj.get("weight") or 1.0)
        n = int(obj.get("clips") or 1)
    except (TypeError, ValueError):
        w, n = 1.0, 1
    return [{"fp": embedding_fp(v), "v": v, "w": w, "n": max(1, n),
             "author": str(author or "")}]


def fold_leaves(leaves, min_cos=FOLD_MIN_COS, trusted=frozenset()):
    """加权并集折叠（确定性：fp 去重 -> fp 字典序累积 -> 同人守卫）。

    `trusted` 里的 fp 跳过守卫（调用方已校验过的本地历史叶子，如追加录入
    时旧 mix 里的叶子——新旧之间可能因同人抖动落在阈值两侧，不该因此翻旧账）。

    返回 (obj, rejected)：
      obj      {"embedding", "weight", "clips", "mix", "sources"}；
               **单叶时原样透传**（不重归一化，保证 embedding 指纹与旧版
               逐字节一致，已同步副本的幂等判断不受影响）；无存活叶 -> None。
      rejected 被守卫拒绝的叶子列表。
    """
    uniq = {}
    authors = {}
    for l in leaves or []:
        fp = l.get("fp")
        if not fp or not l.get("v"):
            continue
        uniq.setdefault(fp, l)
        authors.setdefault(fp, set())
        if l.get("author"):
            authors[fp].add(str(l["author"]))
    # 接纳顺序：**trusted（本地在野叶子）一律先入场**（跳过守卫），
    # 其余按 fp 字典序、逐个对已在场叶子过同人守卫。trusted 优先让
    # 「本地自录不被异人远端冲掉」是确定的（不受 fp 排序摇奖影响），
    # 同时合成本身是向量加法、与入场顺序无关——只影响「谁被拒」。
    ordered = sorted(uniq)
    ordered = [x for x in ordered if x in trusted] + \
              [x for x in ordered if x not in trusted]
    acc, rej = [], []
    for fp in ordered:
        l = uniq[fp]
        if fp in trusted or all(
                _vec_cos(l["v"], a["v"]) >= min_cos for a in acc):
            acc.append(l)
        else:
            rej.append(l)
    if not acc:
        return None, rej
    if len(acc) == 1:
        l = acc[0]
        obj = {"embedding": list(l["v"]),
               "weight": round(float(l["w"]), 6),
               "clips": int(l["n"]),
               "mix": [{"fp": l["fp"], "v": list(l["v"]),
                        "w": round(float(l["w"]), 6), "n": int(l["n"]),
                        "author": l.get("author") or ""}],
               "sources": sorted(authors.get(l["fp"], set()))}
        return obj, rej
    dim = len(acc[0]["v"])
    s = [0.0] * dim
    for l in acc:
        w = float(l["w"])
        v = l["v"]
        for i in range(dim):
            s[i] += w * float(v[i])
    r = math.sqrt(sum(x * x for x in s))
    if r <= 0.0:
        return None, rej
    emb = [round(x / r, 6) for x in s]
    cross = [round(_vec_cos(a["v"], b["v"]), 6)
             for i, a in enumerate(acc) for b in acc[:i]]
    obj = {"embedding": emb,
           "weight": round(r, 6),
           "clips": sum(int(l["n"]) for l in acc),
           "mix": [{"fp": l["fp"], "v": list(l["v"]),
                    "w": round(float(l["w"]), 6), "n": int(l["n"]),
                    "author": l.get("author") or ""} for l in acc],
           "sources": sorted({a for fp in (l["fp"] for l in acc)
                              for a in authors.get(fp, set())})}
    if cross:
        obj["consistency"] = min(cross)
    return obj, rej


def fold_key_of(leaves):
    """折叠输入的指纹（排序后叶子 fp 的 sha1 前 16 位），幂等跳过用。"""
    return hashlib.sha1("|".join(sorted({l.get("fp") or ""
                                         for l in leaves})).encode("utf-8")
                        ).hexdigest()[:16]


def safe_name(name):
    """模板文件名净化，与 speaker_voiceprint.template_path 同规则
    （去 \\\\ / : * ? " < > |、空名回退「主播」、selection 保留名加后缀）。"""
    safe = "".join(c for c in str(name) if c not in '\\/:*?"<>|').strip() or "主播"
    if safe.lower() == "selection":
        safe += "_声纹"
    return safe


def template_path(name):
    return os.path.join(template_dir(), safe_name(name) + ".json")


# ---------------------------------------------------------------- 本机配置
_CFG_CACHE = {}


def _cfg_path():
    return os.path.join(state_dir(), "config.json")


def config():
    """读本机配置；不存在则生成 client_id（首次一次，之后稳定）。"""
    if _CFG_CACHE:
        return _CFG_CACHE
    cfg = {"client_id": "", "last_pull_ts": "", "last_push_ts": ""}
    p = _cfg_path()
    if os.path.isfile(p):
        try:
            with open(p, encoding="utf-8-sig") as f:
                cfg.update(_loads(f.read()))
        except (OSError, ValueError):
            pass
    if not cfg.get("client_id"):
        cfg["client_id"] = str(_uuid.uuid4())
        _save_cfg(cfg)
    _CFG_CACHE.clear()
    _CFG_CACHE.update(cfg)
    return cfg


def _save_cfg(cfg):
    try:
        os.makedirs(state_dir(), exist_ok=True)
        with open(_cfg_path(), "w", encoding="utf-8") as f:
            f.write(_dumps(cfg) + "\n")
    except OSError as e:
        _log("写配置失败：%s" % e)


# ---------------------------------------------------------------- 条目
def make_entry(author, name, op="upsert", value="", supersedes=None,
               evidence=None):
    """构造条目。id = uuid5(URL, "vp|作者|名|值")——同内容必同 id（幂等键）。"""
    id_src = "vp|%s|%s|%s" % (author, name, value)
    return {"id": str(_uuid.uuid5(_uuid.NAMESPACE_URL, id_src)),
            "author": author, "ts": _now_iso(), "op": op,
            "key": str(name), "value": value,
            "supersedes": supersedes or None,
            "evidence": dict(evidence or {})}


def entry_valid(e):
    """条目 schema 校验（只读不执行）。返回 (ok, 原因)。"""
    if not isinstance(e, dict):
        return False, "非对象"
    for f in ("id", "author", "ts", "op", "key", "value", "supersedes",
              "evidence"):
        if f not in e:
            return False, "缺字段 %s" % f
    if not isinstance(e["id"], str) or not e["id"]:
        return False, "id 非法"
    if e["op"] not in ("upsert", "tombstone"):
        return False, "op 非法: %r" % (e["op"],)
    if not isinstance(e["key"], str) or not e["key"]:
        return False, "key 非法"
    if not isinstance(e["value"], str):
        return False, "value 非法"
    if e["op"] == "upsert":
        if not e["value"]:
            return False, "upsert 的 value 为空"
        try:
            obj = _loads(e["value"])
        except ValueError:
            return False, "value 非合法 JSON"
        if (not isinstance(obj, dict) or not obj.get("name")
                or not isinstance(obj.get("embedding"), list)
                or not obj["embedding"]):
            return False, "value 结构非法（缺 name/embedding）"
        mix = obj.get("mix")
        if mix is not None:
            if not isinstance(mix, list) or not mix:
                return False, "mix 非法（应为非空列表）"
            for m in mix:
                if (not isinstance(m, dict)
                        or not isinstance(m.get("v"), list) or not m["v"]):
                    return False, "mix 叶子缺 v"
    if e["supersedes"] is not None and not isinstance(e["supersedes"], str):
        return False, "supersedes 非法"
    return True, ""


def _read_jsonl(path, tag="读取"):
    """读增量文件 -> (条目列表, 畸形行数)。畸形/非法行只跳过并记日志。"""
    out, bad = [], 0
    if not os.path.isfile(path):
        return out, bad
    try:
        with open(path, encoding="utf-8-sig", errors="replace") as f:
            lines = f.readlines()
    except OSError as e:
        _log("%s失败 %s：%s" % (tag, path, e))
        return out, bad
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            e = _loads(line)
        except ValueError:
            bad += 1
            continue
        ok, why = entry_valid(e)
        if ok:
            out.append(e)
        else:
            bad += 1
            _log("%s丢弃非法条目（%s）：%r" % (tag, why, str(e.get("key"))[:40]))
    return out, bad


# ---------------------------------------------------------------- 待传队列
def _pending_path():
    return os.path.join(state_dir(), PENDING_NAME)


def _queue(entry):
    """追加到待传队列。写失败绝不影响调用方（录入/删除主流程优先）。"""
    try:
        os.makedirs(state_dir(), exist_ok=True)
        with open(_pending_path(), "a", encoding="utf-8") as f:
            f.write(_dumps(entry) + "\n")
        return True
    except OSError as e:
        _log("待传队列写入失败：%s" % e)
        return False


def queue_upsert(name, template_obj, prev_sync_id=None):
    """录入/重录/追加一个模板后排入待传队列（产生端：speaker_voiceprint.save_template）。

    `prev_sync_id` 是被覆盖的旧副本的通道条目 id——重录/追加即「取代」，带上它
    可让其它客户端把旧条目判为 superseded，避免旧片段被折进新模板。
    value 统一**剥掉同步标记**：文件内容 == 条目 value 恒成立，
    `own_entry_id()` 才能从文件内容确定性重建条目 id。"""
    if not enabled():
        return False
    obj = strip_sync_marks(template_obj)
    emb = obj.get("embedding") or []
    e = make_entry(config()["client_id"], name, "upsert",
                   _dumps(obj), prev_sync_id,
                   {"fp": embedding_fp(emb),
                    "seconds": obj.get("seconds"),
                    "source": obj.get("source")})
    return _queue(e)


def queue_tombstone(name, prev_sync_id=None, fp=None):
    """删除一个模板后排入待传队列（产生端：speaker_voiceprint.delete_template）。

    `fp` 是被删副本的向量指纹：落地端只在指纹匹配时才删，防误删别人后来
    本地重录的同名模板。"""
    if not enabled():
        return False
    e = make_entry(config()["client_id"], name, "tombstone", "",
                   prev_sync_id, {"fp": fp or ""})
    return _queue(e)


def pending_count():
    es, _bad = _read_jsonl(_pending_path(), "待传")
    return len(es)


# ---------------------------------------------------------------- 推送
def _inbox_files(root):
    """枚举远端 vp_inbox 下全部增量文件 -> [(client_id, ts, path)]（按 ts 排序）。"""
    base = os.path.join(root, INBOX_SUB)
    out = []
    if not os.path.isdir(base):
        return out
    for cid in sorted(os.listdir(base)):
        d = os.path.join(base, cid)
        if not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            if fn.endswith(".jsonl"):
                out.append((cid, fn, os.path.join(d, fn)))
    out.sort(key=lambda t: t[1])
    return out


def _push_entries(entries):
    """写本机留档 + 拷进远端收件箱（只新建文件，绝不改写他人文件）。
    远端不可用时只留档，下次 sync 开头补传。返回是否已进远端。"""
    if not entries:
        return False
    cfg = config()
    # 文件名 = 完整 UTC 时间戳（去掉冒号）+ 4 位随机 hex：按文件名字典序即时间序，
    # 且同一秒内多次推送也不会撞名（撞名会被下面的 isfile 幂等判断静默跳过 = 丢数据）
    fn = "%s-%s.jsonl" % (_now_iso().replace(":", ""), _uuid.uuid4().hex[:4])
    body = "".join(_dumps(e) + "\n" for e in entries)
    archived = False
    try:
        d = os.path.join(state_dir(), "local_log", cfg["client_id"])
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, fn), "w", encoding="utf-8") as f:
            f.write(body)
        archived = True
    except OSError as e:
        _log("本机留档失败：%s" % e)
    root = remote_root()
    dst = os.path.join(root, INBOX_SUB, cfg["client_id"], fn)
    if os.path.isfile(dst):
        return True
    try:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(dst, "w", encoding="utf-8") as f:
            f.write(body)
    except OSError as e:
        _log("上传失败（%s），仅本机留档，下次补传" % e)
        return archived and False
    cfg["last_push_ts"] = _now_iso()
    _save_cfg(cfg)
    _log("上传 %d 条 -> %s/%s/%s" % (len(entries), INBOX_SUB,
                                     cfg["client_id"][:8], fn))
    return True


def _flush_local_log():
    """把「只留档未上传成功」的历史文件补传到远端（幂等：同名即跳过）。"""
    d = os.path.join(state_dir(), "local_log", config()["client_id"])
    if not os.path.isdir(d):
        return 0
    root = remote_root()
    n = 0
    for fn in sorted(os.listdir(d)):
        if not fn.endswith(".jsonl"):
            continue
        dst = os.path.join(root, INBOX_SUB, config()["client_id"], fn)
        if os.path.isfile(dst):
            continue
        try:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with open(os.path.join(d, fn), encoding="utf-8") as f:
                body = f.read()
            with open(dst, "w", encoding="utf-8") as f:
                f.write(body)
            n += 1
        except OSError:
            break                       # 远端不可用，留到下次
    return n


def _flush_pending():
    """待传队列 -> 通道。全部非法时丢弃队列（否则会永远卡在那里）。"""
    p = _pending_path()
    if not os.path.isfile(p):
        return 0
    es, _bad = _read_jsonl(p, "待传")
    if not es:
        try:
            os.remove(p)
        except OSError:
            pass
        return 0
    if _push_entries(es):
        try:
            os.remove(p)
        except OSError:
            pass
        return len(es)
    return 0


def push(quiet=False):
    """只推送：待传队列 + 历史留档补传。"""
    if not enabled():
        if not quiet:
            print("声纹同步未启用（%s），跳过" % DISABLE_ENV)
        return 0
    n = _flush_pending()
    m = _flush_local_log()
    if not quiet:
        print("声纹 push：上传 %d 条%s" % (n, "（另补传留档 %d 个文件）" % m if m else ""))
    return n


# ---------------------------------------------------------------- 合并
def merge(entries):
    """确定性合并（纯函数，同输入必同输出）。

    返回 (applied: {name: [entry...]}, deleted: {name: entry}, report)。
      · 被 supersedes 指向的条目失效（重录/追加链）；
      · 同 name 的 alive upsert **全部保留**（按 (ts, id) 排序）——落地端
        对它们做向量加权并集折叠（fold_leaves），不再取最新一条覆盖；
      · 最新为 tombstone -> 进 deleted（落地端据此删本地副本）。
    声纹没有「基线」概念：生效集就是全部收件箱条目的并集重放结果。"""
    by_id = {}
    for e in sorted(entries, key=lambda x: (_ts_sortkey(x.get("ts")), x.get("id", ""))):
        old = by_id.get(e["id"])
        if old is not None and (_ts_sortkey(old["ts"]), old["id"]) > \
                (_ts_sortkey(e["ts"]), e["id"]):
            continue                    # 旧副本，跳过（幂等）
        by_id[e["id"]] = e
    superseded = {e.get("supersedes") for e in by_id.values() if e.get("supersedes")}
    groups = {}
    for eid, e in by_id.items():
        if eid in superseded:
            continue
        groups.setdefault(e["key"], []).append(e)
    applied, deleted = {}, {}
    for name, es in groups.items():
        es.sort(key=lambda x: (_ts_sortkey(x.get("ts")), x.get("id", "")))
        if es[-1]["op"] == "tombstone":
            deleted[name] = es[-1]
            continue
        # tombstone 之前的 upsert 一并作废：删除语义是「抹掉该名字的历史」，
        # 只有 tombstone 之后的录入才算数（否则折叠会把删除前的旧片段复活）。
        cut = None
        for i in range(len(es) - 1, -1, -1):
            if es[i]["op"] == "tombstone":
                cut = (_ts_sortkey(es[i]["ts"]), es[i]["id"])
                break
        alive = [e for e in es if e["op"] == "upsert"
                 and (cut is None
                      or (_ts_sortkey(e["ts"]), e["id"]) > cut)]
        if alive:
            applied[name] = alive
    report = {"total": len(by_id), "applied": len(applied),
              "deleted": len(deleted), "superseded": len(superseded)}
    return applied, deleted, report


# ---------------------------------------------------------------- 落地
def _read_template(path):
    try:
        with open(path, encoding="utf-8-sig") as f:
            return _loads(f.read())
    except (OSError, ValueError):
        return None


def _unselect(name):
    """从 selection.json 摘除名字（与 speaker_voiceprint.delete_template 同行为）。"""
    sp = os.path.join(template_dir(), "selection.json")
    sel = _read_template(sp)
    if not isinstance(sel, dict):
        return
    names = [str(x) for x in (sel.get("enabled") or [])]
    if str(name) not in names:
        return
    sel["enabled"] = [n for n in names if n != str(name)]
    sel["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
    try:
        with open(sp, "w", encoding="utf-8") as f:
            f.write(_dumps(sel) + "\n")
    except OSError:
        pass


def _conflicts_path():
    return os.path.join(state_dir(), "conflict.json")


def _write_conflicts(conflicts):
    """冲突隔离区（本地自录 vs 远端同名不同向量）。只记录、不自动裁决。

    冲突消解后（远端条目被取代 / 被删除 / 本地改名）要**清空**隔离区，
    否则 status 与界面会永远报一笔已经不存在的老账。"""
    p = _conflicts_path()
    if not conflicts:
        if os.path.isfile(p):
            try:
                os.remove(p)
                _log("冲突已全部消解，清空隔离区")
            except OSError:
                pass
        return
    try:
        os.makedirs(state_dir(), exist_ok=True)
        data = {"schema": 1,
                "conflicts": {k: v for k, v in conflicts.items()}}
        with open(p, "w", encoding="utf-8") as f:
            f.write(_dumps(data) + "\n")
        for k, e in conflicts.items():
            _log("冲突隔离 %r：本地自录优先，远端 %s(%s) 未覆盖"
                 % (k, str(e.get("author"))[:8], str(e.get("ts"))[:19]))
    except OSError as ex:
        _log("写冲突隔离区失败：%s" % ex)


def apply_entry(e):
    """把单条 tombstone 落到本地模板目录（upsert 走 apply_upserts 的折叠路径）。

    返回 1=有动作，0=无动作。"""
    name = e["key"]
    p = template_path(name)
    try:
        if e["op"] != "tombstone":
            return 0
        if not os.path.isfile(p):
            return 0
        cur = _read_template(p)
        if cur is None:
            return 0
        want = (e.get("evidence") or {}).get("fp")
        if want and embedding_fp(cur.get("embedding") or []) != want:
            return 0                # 本地已被重录/折叠（指纹不同），不删
        os.remove(p)
        _unselect(name)
        _log("同步删除声纹 %r（指纹匹配）" % name)
        return 1
    except OSError as ex:
        _log("落地失败 %r：%s" % (name, ex))
        return 0


def apply_upserts(name, entries):
    """把同名的全部 alive upsert 折叠落地。

    返回 (动作数, 冲突 entry 或 None)：
      动作 0 = 幂等跳过（折叠结果与本地一致）；1 = 写入/更新。
      远端叶子被同人守卫拒绝 -> 返回最新被拒 entry 供记冲突（本地自录优先）。
    """
    p = template_path(name)
    remote_leaves = []
    seconds = 0.0
    for e in entries:
        try:
            obj = _loads(e["value"])
        except ValueError:
            continue
        remote_leaves += template_leaves(
            obj, author=str(e.get("author"))[:8])
        try:
            seconds += float((e.get("evidence") or {}).get("seconds") or 0.0)
        except (TypeError, ValueError):
            pass
    if not remote_leaves:
        return 0, None
    cur = _read_template(p) if os.path.isfile(p) else None
    cur_leaves = template_leaves(cur) if cur else []
    remote_fps = {l["fp"] for l in remote_leaves}
    # 「本地在野叶子」= 本地文件里、远端 alive 集里**没有**、且属于本机贡献的
    # 叶子：本机自录文件（无 sync 标记）的全部叶子，或 mix 里 author == 本机
    # 的叶子。同步副本的叶子不算——它们的条目若已不在远端（被重录取代），
    # 就该随之作废，否则「重录=替换」永远传不动。
    cid8 = str(config()["client_id"])[:8]
    self_file = bool(cur) and not cur.get("sync")
    unpublished = [l for l in cur_leaves
                   if l["fp"] not in remote_fps
                   and (self_file or l.get("author") == cid8)]
    # 本地在野叶子 = 在位者（trusted）：先入场、不过守卫——「本地自录优先」
    # 是确定的；steady state（全部推完拉完）下 unpublished 为空，全体客户端
    # 对同一叶子集按 fp 序折叠，结果必然一致（收敛 NFR）。
    obj, rejected = fold_leaves(remote_leaves + unpublished,
                                trusted={l["fp"] for l in unpublished})
    rej_remote = [l for l in rejected if l["fp"] in remote_fps]
    conflict_entry = entries[-1] if rej_remote else None
    if obj is None:
        return 0, conflict_entry
    # 远端叶子**全部**被守卫拒绝且本地向量未变：文件保持原样（本地自录优先），
    # 只记冲突——不写 sync 标记，避免把「隔离中的本地模板」伪装成同步副本。
    accepted_fps = {m["fp"] for m in obj["mix"]} if obj.get("mix") else set()
    if cur is not None and rej_remote \
            and not (remote_fps & accepted_fps) \
            and embedding_fp(cur.get("embedding") or []) == \
            embedding_fp(obj["embedding"]):
        return 0, conflict_entry
    fkey = fold_key_of(remote_leaves + unpublished)
    if cur is not None \
            and embedding_fp(cur.get("embedding") or []) == \
            embedding_fp(obj["embedding"]) \
            and (cur.get("fold_key") or "") == fkey \
            and int(cur.get("clips") or 0) == int(obj["clips"]):
        return 0, conflict_entry        # 幂等：折叠结果未变
    try:
        first = {}
        try:
            first = _loads(entries[0]["value"])
        except (ValueError, IndexError):
            pass
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        out = {"name": str(name), "dim": int(first.get("dim") or 192),
               "created": (cur or first).get("created") or now,
               "updated": now,
               "seconds": round(seconds, 2) or (cur or first).get("seconds"),
               "embedding": obj["embedding"], "weight": obj["weight"],
               "clips": obj["clips"], "mix": obj["mix"],
               "sources": obj.get("sources") or []}
        for k in ("consistency", "source", "start", "dur"):
            v = (cur or first).get(k)
            if v is None:
                v = first.get(k)
            if v is not None:
                out[k] = v
        os.makedirs(template_dir(), exist_ok=True)
        file_obj = dict(out)
        file_obj["sync"] = True
        file_obj["sync_id"] = entries[-1]["id"]
        file_obj["sync_author"] = str(entries[-1].get("author"))[:8]
        file_obj["sync_ts"] = entries[-1].get("ts", "")
        file_obj["fold_key"] = fkey
        with open(p, "w", encoding="utf-8") as f:
            f.write(_dumps(file_obj) + "\n")
        if unpublished:
            # 本地有未发布的叶子：随合并值回播，其他客户端据此收敛
            # （同内容条目 id 相同，重复入队会被收件箱幂等去重）。
            queue_upsert(name, out, prev_sync_id=(cur or {}).get("sync_id"))
        _log("落地声纹 %r：折叠 %d 叶（远端 %d / 本地未发布 %d），"
             "拒绝 %d 叶%s" % (name, len(obj["mix"]), len(remote_leaves),
                              len(unpublished), len(rejected),
                              "，记冲突" if rej_remote else ""))
        return 1, conflict_entry
    except OSError as ex:
        _log("落地失败 %r：%s" % (name, ex))
        return 0, None


def apply_all(applied, deleted):
    """落地生效集 + 删除集。返回 (写入数, 删除数, 冲突 dict)。"""
    n_write = n_del = 0
    conflicts = {}
    for name in sorted(applied):
        n, conflict = apply_upserts(name, applied[name])
        n_write += n
        if conflict is not None:
            conflicts[name] = conflict
    for name in sorted(deleted):
        if apply_entry(deleted[name]) == 1:
            n_del += 1
    return n_write, n_del, conflicts


# ---------------------------------------------------------------- 主流程
def sync(quiet=False):
    """推待传 + 补传留档 + 拉取 + 合并 + 落地。幂等；任何失败静默降级。"""
    if not enabled():
        if not quiet:
            print("声纹同步未启用（%s），跳过" % DISABLE_ENV)
        return False
    cfg = config()
    _flush_pending()
    _flush_local_log()
    root = remote_root()
    if not os.path.isdir(os.path.join(root, INBOX_SUB)):
        if not quiet:
            print("声纹同步：远端不可用（%s\\%s 不存在），静默跳过"
                  % (root, INBOX_SUB))
        _log("sync 跳过：远端不可用 %s" % root)
        return False
    entries = []
    files = _inbox_files(root)
    for _cid, _fn, path in files:
        es, _bad = _read_jsonl(path, "拉取")
        entries.extend(es)
    applied, deleted, report = merge(entries)
    n_write, n_del, conflicts = apply_all(applied, deleted)
    _write_conflicts(conflicts)
    cfg["last_pull_ts"] = _now_iso()
    _save_cfg(cfg)
    _log("sync 完成：收件箱 %d 文件 / %d 条，生效 %d，删除 %d，"
         "写入 %d，冲突 %d，superseded %d"
         % (len(files), report["total"], report["applied"], report["deleted"],
            n_write, len(conflicts), report["superseded"]))
    if not quiet:
        print("声纹 sync：写入 %d / 删除 %d / 冲突隔离 %d（收件箱 %d 条）"
              % (n_write, n_del, len(conflicts), report["total"]))
        if conflicts:
            print("  本地自录的同名声纹已保留，远端条目进 %s" % _conflicts_path())
    return True


def status():
    """概况（供 CLI / 界面显示）。"""
    d = template_dir()
    names = []
    if os.path.isdir(d):
        names = [os.path.splitext(f)[0] for f in os.listdir(d)
                 if f.endswith(".json") and f != "selection.json"]
    synced = 0
    for n in names:
        t = _read_template(os.path.join(d, n + ".json"))
        if isinstance(t, dict) and t.get("sync"):
            synced += 1
    files = _inbox_files(remote_root())
    conf = _read_template(_conflicts_path()) or {}
    cfg = config()
    return {"templates": len(names), "synced": synced,
            "local_only": len(names) - synced,
            "pending": pending_count(),
            "remote_files": len(files),
            "remote_root": remote_root(),
            "client_id": cfg.get("client_id", ""),
            "last_pull_ts": cfg.get("last_pull_ts", ""),
            "last_push_ts": cfg.get("last_push_ts", ""),
            "conflicts": len(conf.get("conflicts") or {})}


def _main(argv):
    cmd = (argv[0] if argv else "status").strip().lower()
    if cmd == "sync":
        return 0 if sync(quiet=False) else 0
    if cmd == "push":
        push(quiet=False)
        return 0
    if cmd == "status":
        s = status()
        print("== 声纹同步状态 ==")
        print("  模板总数   : %d（同步副本 %d / 本地自录 %d）"
              % (s["templates"], s["synced"], s["local_only"]))
        print("  待传队列   : %d 条" % s["pending"])
        print("  远端收件箱 : %d 个文件（%s\\%s）"
              % (s["remote_files"], s["remote_root"], INBOX_SUB))
        print("  冲突隔离   : %d 条" % s["conflicts"])
        print("  本机 id    : %s" % s["client_id"])
        print("  最近拉取   : %s" % (s["last_pull_ts"] or "（无）"))
        print("  最近推送   : %s" % (s["last_push_ts"] or "（无）"))
        return 0
    print(__doc__.split("用法：")[-1].strip())
    return 2


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    raise SystemExit(_main(sys.argv[1:]))
