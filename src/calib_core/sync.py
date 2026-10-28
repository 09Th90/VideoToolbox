# -*- coding: utf-8 -*-
# @version 2.7.0
"""增量同步通道

源：subtitle_calib_merged.py L13651-L14529 @ 97d7d463（2026-10-24 冻结快照）
"""
import datetime as _dt
import uuid as _uuid
import io
import os
import re
import shutil
import sys
import unicodedata
from .data.modes import _MODE_TERM_TABLE
from .inspect import _check_term_hazards
from .learn import LEARNED_KB_DEFAULT, _learn_extended, _load_learned_kb, _save_learned_kb
from .state import (CTX_TABLES, EXCLUDE_CONTEXT, TABLES,
                    _rebuild_context_caches)



# =============================================================
# 8. 增量同步通道（v1.11.0：条目级增量日志架构，2026-09-13）
#
#    目标（任务书 v1.11.0）：把同步对象从"文件快照"翻转为"条目级
#    增量日志"；服务端退化为哑存储，合并下沉到本地脚本，AI 不参与合并。
#
#    数据通道布局：
#      远端哑存储（VT_SYNC_ROOT 或 config.sync_root，默认 data/calib_sync_remote/）
#        baseline.json                      折叠基线（schema/seq/meta + entries）
#        archive/                           旧 baseline 与已折叠 inbox 归档
#        inbox/<client_id>/<ts>.jsonl       增量日志（只新建，绝不改写他人文件）
#      本地状态（VT_SYNC_DIR，默认 data/calib_sync/）
#        config.json       client_id / last_seq / last_baseline_seq /
#                          sync_root / maintainers / disabled_keys
#        applied.json      应用生效的条目（键控，(table,mode,key) -> entry）
#        conflict.json     冲突隔离区（永不自动应用）
#        local_log/<client_id>/<ts>.jsonl   本机导出留档（未上传则下次补传）
#        calib_sync.log    全量日志（上传/拉取/合并/拒绝/冲突，含条目 id）
#
#    增量条目格式（FR-1，JSON Lines 一行一个对象）：
#      {"id": uuid, "author": client_uuid, "ts": ISO8601+时区,
#       "op": "upsert|tombstone",
#       "table": "BILINGUAL_TERMS|CONTEXT_MAP|EXCLUDE_CONTEXT|
#                ENTITIES_VARIANT|LEARNED_CANDIDATE",
#       "mode": "bi|ja|jpe|ko|ak|akko|endo|zho|pgren|wwoc|react",
#       "key": 错形, "value": 正形, "supersedes": 被取代条目id|null,
#       "evidence": {"count":..,"cues":[..],"kb_status":..},
#       "trust": "maintainer|observed"(可选), "rx": 正则(仅 CONTEXT/EXCLUDE)}
#    CONTEXT_MAP / EXCLUDE_CONTEXT 条目必须携带 "rx"（参考行佐证正则，
#    可多值）；"supersedes" 用于修正旧错误（不留痕不算完成）。
#
#    合并语义（确定性、幂等，NFR-1/2）：
#      生效集 = baseline.entries ∪ 增量（全局序按 ts+id 字典序；同 key 取
#      ts 最新且非 tombstone 的一条；tombstone 显式删除；supersedes 使被
#      取代条目失效；同 key 不同 value 且无取代关系 -> 冲突隔离区）。
#      应用前三道门（实体注册冲突 / kb-lint / terms-check），不通过则该批
#      增量整批拒绝并记日志。信任分级：author ∈ maintainers 直接应用；
#      普通用户条目应用但标"待观察"；冲突条目永不自动应用。
#
#    子命令（v1.12.1 起仅剩用户侧两个；管理员命令见独立程序 kb_admin.py）：
#      kb-sync            更新：拉取 + 合并 + 应用（校准入口自动执行；幂等）
#      kb-push [--learned 库] [--file 增量.jsonl]
#                         上传增量（learn 收尾、learned-reject 自动调用）
#
#    回滚（NFR-5）：VT_SYNC_MODE=legacy 停用增量（不拉取、不合并、不应用）；
#    条目级可通过 config.disabled_keys 单独禁用；VT_NO_SYNC=1 强制关闭。
#    增量数据全链路仅 json.load，禁止
#    eval/exec/import（安全约束，违反即返工）。
# =============================================================



def json_load(text):
    """统一 JSON 读取（增量数据全链路仅 json.load，禁止 eval/exec）。"""
    return __import__("json").loads(text)



def json_dumps(obj):
    return __import__("json").dumps(obj, ensure_ascii=False)



_SYNC_TABLES = ("BILINGUAL_TERMS", "CONTEXT_MAP", "EXCLUDE_CONTEXT",
                "ENTITIES_VARIANT", "LEARNED_CANDIDATE")

_SYNC_MODES = ("bi", "ja", "jpe", "ko", "ak", "akko", "endo", "endobi",
               "endoko", "zho", "pgren", "wwoc", "react", "limbus")

_SYNC_MODE_CTX_TABLE = {"bi": "CONTEXT_MAP", "ja": "JA_CONTEXT",
                        "jpe": "JA_ENDFIELD_CONTEXT", "akko": "AK_KO_CONTEXT",
                        "ko": "KO_CONTEXT", "ak": "AK_CONTEXT",
                        "wwoc": "WWOC_CONTEXT", "limbus": "LIMBUS_CONTEXT"}



def _sync_env_mode():
    return os.environ.get("VT_SYNC_MODE", "delta").strip().lower() or "delta"



def _sync_enabled():
    if os.environ.get("VT_NO_SYNC"):
        return False
    return _sync_env_mode() != "legacy"



def _sync_local_dir():
    return os.environ.get("VT_SYNC_DIR") or os.path.join("data", "calib_sync")



def _sync_remote_dir():
    return os.environ.get("VT_SYNC_ROOT") or ""



def _sync_cfg_path():
    return os.path.join(_sync_local_dir(), "config.json")



def _sync_cfg():
    """读取本机同步配置；不存在则生成 client_id（安装时一次）。"""
    cfg = {"client_id": "", "last_seq": "", "last_baseline_seq": 0,
           "sync_root": "", "maintainers": [], "disabled_keys": []}
    p = _sync_cfg_path()
    if os.path.exists(p):
        try:
            with open(p, encoding="utf-8") as f:
                cfg.update(json_load(f.read()))
        except Exception:
            pass
    if not cfg.get("client_id"):
        cfg["client_id"] = str(_uuid.uuid4())
        _sync_save_cfg(cfg)
    return cfg



def _sync_save_cfg(cfg):
    os.makedirs(_sync_local_dir(), exist_ok=True)
    with open(_sync_cfg_path(), "w", encoding="utf-8") as f:
        f.write(json_dumps(cfg) + "\n")



def _sync_log(msg):
    """追加一行同步日志（best-effort，绝不因日志失败影响主流程）。"""
    try:
        os.makedirs(_sync_local_dir(), exist_ok=True)
        p = os.path.join(_sync_local_dir(), "calib_sync.log")
        with open(p, "a", encoding="utf-8") as f:
            f.write(f"[{_dt.datetime.now():%Y-%m-%d %H:%M:%S}] {msg}\n")
    except OSError:
        pass



def _sync_root(cfg=None):
    cfg = cfg if cfg is not None else _sync_cfg()
    root = _sync_remote_dir() or cfg.get("sync_root") or ""
    if not root:
        root = os.path.join("data", "calib_sync_remote")
    return root



def _sync_ts():
    import datetime as _dt
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="milliseconds")



def _sync_entry(author, table, mode, key, value="", op="upsert",
                supersedes=None, evidence=None, trust=None, rx=None):
    id_src = f"calib|{author}|{table}|{mode}|{key}|{value}"
    if rx is not None:
        id_src += "|" + (rx if isinstance(rx, str) else "|".join(rx))
    e = {"id": str(_uuid.uuid5(_uuid.NAMESPACE_URL, id_src)),
         "author": author, "ts": _sync_ts(), "op": op, "table": table,
         "mode": mode, "key": key, "value": value,
         "supersedes": supersedes or None,
         "evidence": dict(evidence or {})}
    if trust:
        e["trust"] = trust
    if rx is not None:
        e["rx"] = rx
    return e



def _sync_entry_key(e):
    """生效/合并键。CONTEXT_MAP 是多规则共存表：同一 wrong 词在不同 rx
    条件下可映射不同目标，键必须含 rx，否则同词多规则会被误判冲突。"""
    k = (e.get("table"), e.get("mode", ""), e.get("key"))
    if e.get("table") == "CONTEXT_MAP" and e.get("rx") is not None:
        rx = tuple(e["rx"]) if isinstance(e["rx"], list) else e["rx"]
        k = k + (rx,)
    return k



#: v1.16.5：applied.json / conflict.json 的键序列化。
#: 此前直接 `"\x1f".join(k)`——但 CONTEXT_MAP 的键末位 rx 可能是 **tuple**
#: （见 _sync_entry_key），join 对嵌套 tuple 会抛 TypeError，整条同步通道崩。
#: 统一走下面这对称的一对：嵌套元素用 \x1e 二级连接，读回时还原成 tuple。
_SYNC_KEY_SEP = "\x1f"

_SYNC_SUB_SEP = "\x1e"



def _sync_key_str(k):
    """键 tuple → 可存盘字符串（嵌套 tuple/list 用 \\x1e 二级连接）。"""
    parts = []
    for x in k:
        if isinstance(x, (tuple, list)):
            parts.append(_SYNC_SUB_SEP.join(str(i) for i in x))
        else:
            parts.append(str(x))
    return _SYNC_KEY_SEP.join(parts)



def _sync_key_from_str(s):
    """_sync_key_str 的逆：还原嵌套 tuple（与 _sync_entry_key 输出同构）。"""
    parts = s.split(_SYNC_KEY_SEP)
    if len(parts) >= 4 and _SYNC_SUB_SEP in parts[3]:
        parts[3] = tuple(parts[3].split(_SYNC_SUB_SEP))
    return tuple(parts)



def _sync_validate(e):
    """增量条目 schema 校验（FR-1 字段缺一不可；只读不执行）。"""
    if not isinstance(e, dict):
        return False, "非对象"
    for f in ("id", "author", "ts", "op", "table", "mode", "key", "value",
              "supersedes", "evidence"):
        if f not in e:
            return False, f"缺字段 {f}"
    if not isinstance(e["id"], str) or not e["id"]:
        return False, "id 非法"
    if e["op"] not in ("upsert", "tombstone"):
        return False, f"op 非法: {e['op']!r}"
    if e["table"] not in _SYNC_TABLES:
        return False, f"table 非法: {e['table']!r}"
    if e["mode"] not in _SYNC_MODES:
        return False, f"mode 非法: {e['mode']!r}"
    if not isinstance(e["key"], str) or not e["key"]:
        return False, "key 非法"
    if not isinstance(e["value"], str):
        return False, "value 非法"
    if e["op"] == "upsert" and not e["value"]:
        return False, "upsert 的 value 为空"
    if e["supersedes"] is not None and not isinstance(e["supersedes"], str):
        return False, "supersedes 非法"
    if e["table"] in ("CONTEXT_MAP", "EXCLUDE_CONTEXT") and not e.get("rx"):
        return False, f"{e['table']} 条目缺少 rx 正则"
    if e.get("rx") is not None:
        rx = e["rx"]
        if isinstance(rx, str):
            try:
                re.compile(rx)
            except re.error:
                return False, f"rx 非法正则: {rx!r}"
        elif isinstance(rx, list):
            for r in rx:
                try:
                    re.compile(r)
                except re.error:
                    return False, f"rx 非法正则: {r!r}"
        else:
            return False, "rx 类型非法"
    return True, ""



def _sync_read_jsonl(path, log_prefix="读取"):
    """读取增量文件 -> (条目列表, 畸形行数)。畸形/非 JSON 行只跳过并记日志。"""
    entries, bad = [], 0
    if not os.path.isfile(path):
        return entries, bad
    with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
        for ln, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                e = json_load(line)
            except Exception:
                bad += 1
                _sync_log(f"{log_prefix} {path} 行{ln} 非 JSON，已跳过（安全拦截）")
                continue
            ok, why = _sync_validate(e)
            if not ok:
                bad += 1
                _sync_log(f"{log_prefix} {path} 行{ln} schema 拒绝: {why}")
                continue
            entries.append(e)
    if bad:
        _sync_log(f"{log_prefix} {path} 共 {len(entries)} 条有效 / {bad} 条畸形拒绝")
    return entries, bad



def _sync_write_jsonl(path, entries):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for e in entries:
            f.write(json_dumps(e) + "\n")



def _sync_read_baseline(root):
    """读远端 baseline -> (meta, entries: {key: entry})。缺失返回 ({}, {})。
    seq 存文件顶层，并入 meta 返回（下游统一用 meta.get('seq')）。"""
    p = os.path.join(root, "baseline.json")
    if not os.path.isfile(p):
        return {}, {}
    try:
        with open(p, encoding="utf-8-sig") as f:
            data = json_load(f.read())
    except Exception as e:
        _sync_log(f"baseline 读取失败（{e}），按空基线处理")
        return {}, {}
    entries = {}
    for k, e in (data.get("entries") or {}).items():
        ok, why = _sync_validate(e)
        if not ok:
            _sync_log(f"baseline 条目拒绝: {why}")
            continue
        entries[e["id"]] = e
    meta = dict(data.get("meta") or {})
    if data.get("seq") is not None:
        meta["seq"] = data["seq"]
    return meta, entries



def _sync_write_baseline(root, seq, meta, entries):
    os.makedirs(root, exist_ok=True)
    p = os.path.join(root, "baseline.json")
    data = {"schema": 1, "seq": int(seq),
            "meta": dict(meta or {}), "entries": entries}
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(json_dumps(data) + "\n")
    os.replace(tmp, p)



def _sync_inbox_files(root):
    """列出远端全部增量文件 -> [(client_id, ts, path)]，按 ts 字典序。"""
    out = []
    inbox = os.path.join(root, "inbox")
    if not os.path.isdir(inbox):
        return out
    for cid in sorted(os.listdir(inbox)):
        cdir = os.path.join(inbox, cid)
        if not os.path.isdir(cdir):
            continue
        for fn in sorted(os.listdir(cdir)):
            if fn.endswith(".jsonl"):
                ts = fn[:-6]
                if "-" in ts:
                    ts = ts.rsplit("-", 1)[0]   # 去掉唯一后缀，取毫秒前缀
                out.append((cid, ts, os.path.join(cdir, fn)))
    return out



def _sync_flush_local_log(cfg, root):
    """把本机留档中未上传的增量补传（幂等：远端已有同名文件跳过）。"""
    base = os.path.join(_sync_local_dir(), "local_log", cfg["client_id"])
    if not os.path.isdir(base):
        return 0
    sent = 0
    for fn in sorted(os.listdir(base)):
        if not fn.endswith(".jsonl"):
            continue
        dst = os.path.join(root, "inbox", cfg["client_id"], fn)
        if os.path.exists(dst):
            continue
        try:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with open(os.path.join(base, fn), "rb") as f:
                data = f.read()
            with open(dst, "wb") as f:
                f.write(data)
            sent += 1
            _sync_log(f"补传 {fn} -> inbox/{cfg['client_id']}/")
        except OSError as e:
            _sync_log(f"补传失败（{e}），静默跳过（离线/只读远端）")
            return sent
    if sent:
        _sync_log(f"补传完成：{sent} 个本地留档")
    return sent



def _sync_push_entries(entries, cfg=None):
    """本地留档 + 上传远端 inbox（FR-2：只新建文件，绝不改写他人文件）。
    无远端/断网：静默跳过，本地功能完整可用，记日志。"""
    cfg = cfg if cfg is not None else _sync_cfg()
    if not entries:
        return False
    if not _sync_enabled():
        _sync_log(f"跳过上传（{len(entries)} 条）：同步未启用/legacy 模式")
        return False
    fn = _sync_ts().replace(":", "").replace("+00:00", "") \
        + f"-{_uuid.uuid4().hex[:4]}.jsonl"
    local = os.path.join(_sync_local_dir(), "local_log", cfg["client_id"], fn)
    _sync_write_jsonl(local, entries)
    try:
        local_show = os.path.relpath(local)
    except ValueError:
        local_show = local          # 跨盘符（临时目录在 C:，cwd 在 I:）
    _sync_log(f"本地留档 {len(entries)} 条 -> {local_show}："
              + ";".join(e["id"] for e in entries[:5]))
    root = _sync_root(cfg)
    if not os.path.isdir(root):
        _sync_log("远端不可用，上传静默跳过（留档保留，下次补传）")
        return False
    dst = os.path.join(root, "inbox", cfg["client_id"], fn)
    if os.path.exists(dst):
        return True
    try:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(dst, "w", encoding="utf-8") as f:
            for e in entries:
                f.write(json_dumps(e) + "\n")
        _sync_log(f"上传 {len(entries)} 条 -> inbox/{cfg['client_id']}/{fn}"
                  + "；".join(e["id"] for e in entries[:5]))
        return True
    except OSError as e:
        _sync_log(f"上传失败（{e}），静默跳过（断网/只读远端）")
        return False



def _sync_merge(baseline_entries, pending):
    """确定性合并（NFR-1/2 纯函数，同输入必同输出）。

    baseline_entries: {id: entry}；pending: 增量条目列表（已按 ts+id 排序）。
    返回 (applied: {key: entry}, conflicts: {key: [entry...]}, report)。
    幂等键 = 条目 id；同 key 多条全部保留参与裁决：不同 value 且无取代
    关系 -> 冲突隔离（不应用）；单值 -> 取 ts+id 最新；最新为 tombstone
    则整键删除（人工否决优先，不可被覆盖）；supersedes 使被取代条目失效。
    """
    by_id = dict(baseline_entries)
    for e in sorted(pending, key=lambda x: (x["ts"], x["id"])):
        old = by_id.get(e["id"])
        if old is not None and (old["ts"], old["id"]) > (e["ts"], e["id"]):
            continue                      # 旧副本，跳过（幂等）
        by_id[e["id"]] = e
    superseded = {e.get("supersedes") for e in by_id.values()
                  if e.get("supersedes")}
    groups = {}
    for eid, e in by_id.items():
        if eid in superseded:
            continue                      # 被取代：历史可查但不生效
        groups.setdefault(_sync_entry_key(e), []).append(e)
    # 冲突判定仅适用于单值语义表：同 key 不同 value -> 冲突隔离。
    # CONTEXT_MAP/EXCLUDE_CONTEXT 为多规则共存表（同词不同 rx 各存一条），
    # 同键多条取最新，由 _sync_apply 天然聚合。
    single_valued = ("BILINGUAL_TERMS", "ENTITIES_VARIANT", "LEARNED_CANDIDATE")
    applied, conflicts = {}, {}
    for key, es in groups.items():
        es.sort(key=lambda x: (x["ts"], x["id"]))
        if es[-1]["op"] == "tombstone":
            continue                      # 最新裁决为否决：整键删除，不应用
        if key[0] in single_valued:
            vals = {}
            for e in es:
                vals.setdefault(e["value"], e)
            if len(vals) > 1:
                conflicts[key] = es       # 同 key 不同值：冲突隔离，永不自动应用
                continue
        applied[key] = es[-1]
    report = {"total": len(by_id), "applied": len(applied),
              "conflicts": len(conflicts),
              "tombstones": sum(1 for e in by_id.values()
                                if e["op"] == "tombstone" and e["id"] not in superseded),
              "superseded": len(superseded)}
    return applied, conflicts, report



def _sync_gates(applied):
    """三道门（FR-3：不通过则该批增量整批拒绝并记日志）。

    门1 实体注册冲突：同 (table, mode, key) 与本地生效知识（内置表 +
    已应用）映射不同目标；
    门2 kb-lint：变体与既有 ENTITIES canonical 冲突（同 mode 下
    key->value 与已有 Entity 冲突）或目标即键自身；
    门3 terms-check：并入后相关表出现【新增】二次命中隐患。
    返回 (ok, 原因列表)。
    """
    bad = []
    # 门1：与内置表/已应用冲突
    cur = _sync_current_terms()
    for key, e in applied.items():
        table, mode, k, v = key[0], key[1], e["key"], e["value"]
        if table == "ENTITIES_VARIANT":
            tname = _MODE_TERM_TABLE.get(mode)
            tbl = TABLES.get(tname) or {}
            if tbl.get(k) and tbl[k] != v:
                bad.append(f"门1 {k!r}->{v!r} 与内置表 {tname}[{k}]={tbl[k]!r} 冲突")
            if cur.get(key) and cur[key] != v:
                bad.append(f"门1 {k!r}->{v!r} 与已应用 {cur[key]!r} 冲突")
        elif table == "BILINGUAL_TERMS":
            tbl = TABLES.get("BILINGUAL_TERMS") or {}
            if tbl.get(k) and tbl[k] != v:
                bad.append(f"门1 {k!r}->{v!r} 与内置 BILINGUAL_TERMS 冲突")
    # 门2：目标合法性
    for key, e in applied.items():
        k, v = e["key"], e["value"]
        if v == k:
            bad.append(f"门2 恒等键 {k!r}->{v!r}")
        if "\n" in v or "\r" in v:
            bad.append(f"门2 目标含换行: {k!r}")
    # 门3：terms-check 新增隐患（并入前 vs 并入后）
    base_haz = _sync_hazard_keys()
    for key, e in applied.items():
        table, mode, k, v = key[0], key[1], e["key"], e["value"]
        tname = None
        if table in ("ENTITIES_VARIANT", "BILINGUAL_TERMS"):
            tname = (_MODE_TERM_TABLE.get(mode) if table == "ENTITIES_VARIANT"
                     else "BILINGUAL_TERMS")
        elif table in _SYNC_MODE_CTX_TABLE.values():
            continue
        if not tname:
            continue
        tbl = dict(TABLES.get(tname) or {})
        tbl[k] = v
        newhaz = [h for h in _check_term_hazards(tbl)
                  if h not in base_haz.get(tname, ())]
        for h in newhaz:
            bad.append(f"门3 {tname} 新增二次命中隐患: {h[0]!r} 命中 {h[1]!r} 结果 {h[2]!r}")
    if bad:
        _sync_log("三道门拒绝该批增量：" + "；".join(bad[:8]))
        return False, bad
    return True, []



def _sync_current_terms():
    """当前已应用的生效值：{key: value}（applied.json 视图）。"""
    out = {}
    p = os.path.join(_sync_local_dir(), "applied.json")
    if os.path.isfile(p):
        try:
            with open(p, encoding="utf-8-sig") as f:
                data = json_load(f.read())
            for k, e in (data.get("entries") or {}).items():
                out[_sync_key_from_str(k)] = e["value"]
        except Exception:
            pass
    return out



def _sync_hazard_keys():
    """当前各术语表的二次命中隐患（用于对比新增）。"""
    out = {}
    for n, t in TABLES.items():
        if n.endswith("TERMS") and isinstance(t, dict) and t:
            out[n] = tuple(_check_term_hazards(t))
    return out



def _sync_apply(applied):
    """应用生效集：写 applied.json + 注入扁平表（键控，只 json）。"""
    p = os.path.join(_sync_local_dir(), "applied.json")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    keyed = {_sync_key_str(k): v for k, v in applied.items()}
    with open(p, "w", encoding="utf-8") as f:
        f.write(json_dumps({"schema": 1, "entries": keyed}) + "\n")
    n_terms = n_ctx = n_kb = 0
    _kb_pending.clear()
    for key, e in applied.items():
        table, mode, k, v = key[0], key[1], e["key"], e["value"]
        if table == "ENTITIES_VARIANT":
            tname = _MODE_TERM_TABLE.get(mode)
            if tname and isinstance(TABLES.get(tname), dict):
                if TABLES[tname].get(k) != v:
                    TABLES[tname][k] = v
                    n_terms += 1
        elif table == "BILINGUAL_TERMS":
            if isinstance(TABLES.get("BILINGUAL_TERMS"), dict) \
                    and TABLES["BILINGUAL_TERMS"].get(k) != v:
                TABLES["BILINGUAL_TERMS"][k] = v
                n_terms += 1
        elif table == "CONTEXT_MAP":
            cname = _SYNC_MODE_CTX_TABLE.get(mode) or "CONTEXT_MAP"
            lst = CTX_TABLES.get(cname)
            if isinstance(lst, list):
                rxs = e["rx"] if isinstance(e.get("rx"), list) else [e.get("rx")]
                for rx in rxs:
                    row = (rx, k, v)
                    if row not in lst:
                        lst.append(row)
                        n_ctx += 1
        elif table == "EXCLUDE_CONTEXT":
            exc = EXCLUDE_CONTEXT
            if isinstance(exc, dict):
                rxs = e["rx"] if isinstance(e.get("rx"), list) else [e.get("rx")]
                old = exc.get(k)
                if old:
                    right, rr = old
                    exc[k] = (right, tuple(rr) + tuple(r for r in rxs if r not in rr))
                else:
                    exc[k] = (v, tuple(rxs))
                n_ctx += 1
        elif table == "LEARNED_CANDIDATE":
            _kb_pending.append((mode, k, v, e))
    if _kb_pending:
        n_kb = _sync_apply_learned_batch(_kb_pending)
    if n_terms or n_ctx:
        _rebuild_context_caches()
    _sync_log(f"应用 {len(applied)} 条（terms {n_terms} / ctx {n_ctx} / 学习库 {n_kb}）")
    return n_terms + n_ctx + n_kb



#: 本批待写入学习库的候选（``_sync_apply`` 收集，循环结束后**一次**落盘）。
_kb_pending = []



def _learned_kb_backup(kb_path, keep=5):
    """学习库落盘前备份（``<name>.bak_YYYYmmdd_HHMMSS``，只留最近 keep 份）。

    为什么要备份（2026-10-19）：同步通道 ``_sync_apply_learned_batch`` 会
    把远端条目**写进用户真实的学习库**，而它由 ``main_argv`` 里那次
    ``_sync_maybe_auto()`` 触发——也就是「用户只是跑了一次校准」就会改
    全局学习库。实测当日一次校准就让 300+ 条候选的 first/last 变成今天。
    没有备份时，一次误同步就是不可逆的数据改写。
    """
    if not (kb_path and os.path.isfile(kb_path)):
        return ""
    import datetime as _dt
    import glob as _glob
    import shutil as _shutil
    stamp = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    dst = f"{kb_path}.bak_{stamp}"
    if os.path.exists(dst):
        return dst
    try:
        _shutil.copy2(kb_path, dst)
    except OSError:
        return ""
    # 只留最近 keep 份：按文件名里的时间戳排序（同秒并列时保留靠后的）
    olds = sorted(_glob.glob(f"{kb_path}.bak_*"))
    for p in olds[:-keep] if len(olds) > keep else []:
        try:
            os.remove(p)
        except OSError:
            pass
    return dst



def _sync_apply_learned_batch(pending):
    """一批 LEARNED_CANDIDATE 增量**一次性**写入学习库，返回实际变更条数。

    与逐条写入的区别（都改了，逐条是原来那版）：
      1. **只落盘一次**：原来 ``_sync_apply`` 循环里每条都 ``_load`` + ``_save``
         整个 JSON（数百条约等于反复重写 100KB 文件）；
      2. **未变更条目不重建**：原来命中同一条目时也整体重建 dict，
         ``first/last`` 被刷成今天——这在数据上是「改写了历史」，用户完全
         看不出来（实测一次校准把 312 条 first/last 全刷成当日）；
      3. **写盘前备份**（见 :func:`_learned_kb_backup`）；
      4. **日志可追溯**：把本批真正写进去的键记一行（原来只有条数）。
    """
    if not pending:
        return 0
    kb_path = (os.environ.get("VT_SYNC_KB") or "").strip() or LEARNED_KB_DEFAULT
    kb = _load_learned_kb(kb_path)
    import datetime as _dt
    today = _dt.date.today().isoformat()
    changed = []
    skipped = 0
    for mode, wrong, right, e in pending:
        ev = (e or {}).get("evidence") or {}
        k = f"{mode}|{wrong}"
        old = kb["candidates"].get(k)
        if old is not None and (
                old.get("status") == "rejected"
                or (old.get("right") and old["right"] != right)):
            skipped += 1            # 本地已有裁决/冲突：不覆盖
            continue
        new_count = int(ev.get("count") or 1)
        new_cues = list(ev.get("cues") or [])[:20]
        if old is not None:
            # 值没变就不动（保留 first/last 与累计证据）
            if old.get("right") == right and old.get("status") == "confirmed" \
                    and int(old.get("count") or 0) >= new_count:
                continue
            merged_cues = list(dict.fromkeys(list(old.get("cues") or []) + new_cues))
            old.update({
                "right": right,
                "count": max(int(old.get("count") or 0), new_count),
                "cues": merged_cues[:20],
                "status": "confirmed",
                "last": today,
                "sync": True,
            })
            changed.append(k)
            continue
        kb["candidates"][k] = {
            "wrong": wrong, "right": right, "mode": mode,
            "count": new_count, "uncorrected": 0,
            "status": "confirmed", "cues": new_cues,
            "samples": [], "ref_tokens": {}, "unc_ref_tokens": {},
            "first": today, "last": today, "alts": {},
            "sync": True,
        }
        changed.append(k)
    if changed:
        bak = _learned_kb_backup(kb_path)
        _save_learned_kb(kb, kb_path)
        head = "、".join(changed[:5]) + ("…" if len(changed) > 5 else "")
        _sync_log(
            f"学习库写入 {len(changed)} 条（{head}）"
            + (f"；备份 {os.path.basename(bak)}" if bak else "")
            + (f"；跳过 {skipped} 条（本地已裁决/目标冲突）" if skipped else ""))
    return len(changed)



def _sync_apply_learned_candidate(mode, wrong, right, e):
    """单条入口（保留兼容）：转调批量版。"""
    return _sync_apply_learned_batch([(mode, wrong, right, e)])



def _sync_write_conflicts(conflicts):
    p = os.path.join(_sync_local_dir(), "conflict.json")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    data = {"schema": 1,
            "conflicts": {_sync_key_str(k): v for k, v in conflicts.items()}}
    with open(p, "w", encoding="utf-8") as f:
        f.write(json_dumps(data) + "\n")
    for k, es in conflicts.items():
        _sync_log(f"冲突隔离 {k}: " + ";".join(
            f"{e['id']}({e['author']}@{e['ts'][:19]})={e['value']!r}" for e in es))



def _cmd_kb_sync(quiet=False):
    """kb-sync：拉取 + 合并 + 三道门 + 信任分级应用（FR-3）。幂等。"""
    if not _sync_enabled():
        if not quiet:
            print("同步未启用（VT_SYNC_MODE=legacy 或 VT_NO_SYNC），跳过 kb-sync")
        return False
    cfg = _sync_cfg()
    root = _sync_root(cfg)
    if not os.path.isdir(root):
        if not quiet:
            print("远端不可用（离线），同步静默跳过")
        _sync_log("kb-sync 跳过：远端不可用")
        return False
    _sync_flush_local_log(cfg, root)
    meta, base_entries = _sync_read_baseline(root)
    files = _sync_inbox_files(root)
    # 全量重放（不按水位线过滤）：生效集 = baseline ∪ 全部增量，确定性合并，
    # id 幂等保证重复拉取结果一致（NFR-1/2）；水位线仅作状态展示/日志。
    pending = []
    for cid, ts, path in files:
        es, _bad = _sync_read_jsonl(path, "拉取")
        pending.extend(es)
    pending.sort(key=lambda x: (x["ts"], x["id"]))
    applied, conflicts, report = _sync_merge(base_entries, pending)
    # 三道门只针对"本次增量引入"的条目：baseline 是管理员已折叠的权威，直通
    new_keys = {_sync_entry_key(e) for e in pending}
    new_applied = {k: v for k, v in applied.items() if k in new_keys}
    ok, reasons = _sync_gates(new_applied)
    if not ok:
        print(f"三道门拒绝该批增量（{len(pending)} 条），水位线不推进：{reasons[0]}")
        return False
    # NFR-5 条目级禁用：disabled_keys 中的键不应用
    dis = {tuple(x) for x in (cfg.get("disabled_keys") or [])}
    if dis:
        applied = {k: v for k, v in applied.items() if k not in dis}
    # 信任分级标注（维护者直接应用；普通用户标待观察——均应用，仅日志区分）
    maint = set(cfg.get("maintainers") or [])
    for e in applied.values():
        if e.get("author") in maint or e.get("trust") == "maintainer":
            e["trust"] = "maintainer"
        else:
            e["trust"] = "observed"
    n_applied = _sync_apply(applied)
    if conflicts:
        _sync_write_conflicts(conflicts)
    cfg["last_seq"] = files[-1][1] if files else cfg.get("last_seq", "")
    cfg["last_baseline_seq"] = int(meta.get("seq") or 0)
    _sync_save_cfg(cfg)
    _sync_log(f"kb-sync 完成：baseline seq={meta.get('seq')} 增量 {len(pending)} 条 "
              f"（{len(files)} 文件），应用 {len(applied)}，"
              f"冲突 {report['conflicts']}，tombstone {report['tombstones']}，"
              f"superseded {report['superseded']}")
    if not quiet:
        print(f"kb-sync：应用 {n_applied} 条 / 冲突隔离 {len(conflicts)} 条 / "
              f"水位线 {cfg['last_seq'] or '（无）'}")
        if conflicts:
            print("  冲突条目已进隔离区（conflict.json），永不自动应用")
    return True



def _cmd_kb_push(learned=None, file=None):
    """kb-push：把学习库 confirmed 候选或指定增量文件导出并上传（FR-2）。
    候选导出用扩展形态（_learn_extended），保证增量是完整词元而非最小片段。

    v1.12.1「只上传当前增量」：候选条目 id 是
    (作者,表,模式,键,值) 的确定性哈希，本机用 pushed_ids.json 台账记录
    已成功上传的 id，重复导出时跳过——退出/手动触发的整库导出因此只补传
    「没传过的」条目；远端不可用时不记账，下次再传。"""
    cfg = _sync_cfg()
    entries = []
    ledger_path = os.path.join(_sync_local_dir(), "pushed_ids.json")
    try:
        with open(ledger_path, encoding="utf-8") as f:
            ledger = set(json_load(f.read()) or [])
    except (OSError, ValueError):
        ledger = set()
    n_skipped = 0
    if learned:
        kb = _load_learned_kb(learned)
        for c in kb.get("candidates", {}).values():
            if c.get("status") == "confirmed" and not c.get("conflict"):
                w, r = _learn_extended(c)
                e = _sync_entry(
                    cfg["client_id"], "LEARNED_CANDIDATE", c.get("mode", "bi"),
                    w, r,
                    evidence={"count": c.get("count", 1),
                              "cues": list(c.get("cues") or [])[:20],
                              "kb_status": c.get("status", "confirmed")})
                if e["id"] in ledger:
                    n_skipped += 1
                    continue
                entries.append(e)
    if file:
        es, bad = _sync_read_jsonl(file, "kb-push")
        entries.extend(es)
    if not entries:
        print(f"没有需要上传的增量"
              + (f"（{n_skipped} 条此前已上传，跳过）" if n_skipped else "（学习库无新 confirmed 候选）"))
        return False
    ok = _sync_push_entries(entries, cfg)
    if ok:
        ledger.update(e["id"] for e in entries)
        try:
            os.makedirs(_sync_local_dir(), exist_ok=True)
            with open(ledger_path, "w", encoding="utf-8") as f:
                f.write(json_dumps(sorted(ledger)) + "\n")
        except OSError:
            pass
    print(f"kb-push：上传 {len(entries)} 条"
          + (f"（另 {n_skipped} 条已上传过，跳过）" if n_skipped else "")
          + ("（留档 + 上传）" if ok else "（远端不可用，仅本机留档，下次补传）"))
    return ok



def _sync_export_learn_entries(kb, kb_before, mode):
    """learn 收尾（FR-2）：本次新增/变更的 confirmed 候选导出为增量并上传。
    导出扩展形态（_learn_extended），保证增量是完整词元而非最小片段。"""
    cfg = _sync_cfg()
    before = (kb_before or {}).get("candidates", {})
    entries = []
    for k, c in kb.get("candidates", {}).items():
        if c.get("mode") != mode or c.get("status") != "confirmed" \
                or c.get("conflict"):
            continue
        old = before.get(k)
        if old and old.get("status") == "confirmed" \
                and old.get("right") == c.get("right"):
            continue                    # 非本次新增/变更
        w, r = _learn_extended(c)
        entries.append(_sync_entry(
            cfg["client_id"], "LEARNED_CANDIDATE", mode, w, r,
            evidence={"count": c.get("count", 1),
                      "cues": list(c.get("cues") or [])[:20],
                      "kb_status": c.get("status", "confirmed")}))
    if entries:
        _sync_push_entries(entries, cfg)
        _sync_log(f"learn 收尾导出 {len(entries)} 条 confirmed 增量")
    return len(entries)



def _sync_export_reject_tombstone(word, modes):
    """learned-reject（FR-2）：人工否决 = tombstone 增量，通知其它客户端。"""
    cfg = _sync_cfg()
    entries = [_sync_entry(cfg["client_id"], "LEARNED_CANDIDATE", m, word, "",
                           op="tombstone",
                           evidence={"kb_status": "rejected"})
               for m in modes]
    if entries:
        _sync_push_entries(entries, cfg)
    return len(entries)



def _sync_maybe_auto():
    """校准入口自动同步（v1.11.0）：delta 模式且远端可用时拉取+应用。
    任何失败都静默降级，绝不影响校准主流程（离线/legacy 同 v1.10.7）。"""
    if not _sync_enabled():
        return False
    try:
        return _cmd_kb_sync(quiet=True)
    except Exception as e:  # noqa: BLE001
        _sync_log(f"自动同步异常已静默降级：{e}")
        return False



def _sync_inject_all():
    """把 applied.json 中生效条目注入本地表（校准运行时兜底；kb-sync 已注入）。"""
    ap = os.path.join(_sync_local_dir(), "applied.json")
    if not os.path.isfile(ap):
        return 0
    try:
        with open(ap, encoding="utf-8-sig") as f:
            data = json_load(f.read())
    except Exception:
        return 0
    applied = {}
    for k, v in (data.get("entries") or {}).items():
        applied[_sync_key_from_str(k)] = v
    return _sync_apply(applied)

