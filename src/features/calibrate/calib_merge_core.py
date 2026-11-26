#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# @version 3.3.1
"""校准知识条目级合并核心（纯函数，零副作用）。

============================================================
v1.10.8 起从 video_toolbox.py 抽出，成为可被 GUI 引擎、退出同步子进程、
CI / 脚本共同复用的「合并接口」。本模块**只做合并**：
  · 不创建任何目录；
  · 不读写环境变量、不联网、不起子进程；
  · 不直接写日志文件（冲突等运行信息走可注入的 `_log` 钩子，
    默认空操作；引擎导入后把它接到 logs/calib_sync.log 的写入器）。
因此它可以在任何环境（含无图形、无文件系统写权限的 CI）直接 import。

合并语义（v1.10.7 确立，v1.10.8 原样保留——多用户对等并集收敛）：
  启动：本地 ←拉取 + 条目级三方合并— GitHub main；
  退出：先把远程新内容并进来，再推送（pull-merge-then-push）。
合并单位从「整个文件」降到「条目」：
  · 纯字符串字面量 dict（各模式术语表等）：按 错形键 合并；
  · 常量二元组列表（CONTEXT_MAP 等上下文佐证规则）：按整元组合并；
  · ENTITIES（Entity(...) 调用列表）：按 canonical 合并；
  · 学习库 JSON：按 "模式|错形" 候选合并。
只做并集、从不删除，任意多用户反复拉推最终收敛到全体条目的并集。
用 ast 而非文本 diff：脚本是合法 Python，AST 能精确定位表与条目且免误伤。
============================================================
"""

import ast as _ast
import hashlib as _hashlib
import json as _json
import re as _re
import threading as _threading
from collections import OrderedDict as _OrderedDict

#: 三方合并中「基线里也没有该键」的哨兵（表示该条目是本地/远程单边新增）
_MERGE_MISSING = object()

#: _ast_module_tables 的解析结果缓存（键 = 源码 sha256）。合并只读 AST 节点、
#: 从不改动，故按内容缓存安全；local==base 常见情形可免重复全文件 parse。
#: 有界 LRU，避免长期运行内存膨胀；parse 本身不持锁（持 GIL 的 C 段在锁外）。
_TABLES_CACHE = _OrderedDict()
_TABLES_CACHE_MAX = 8
_TABLES_LOCK = _threading.Lock()


def _log(msg):
    """运行信息钩子（冲突保留本地等）。默认空操作；引擎可替换为落盘日志。"""
    return None


# ---------------------------------------------------------------------------
# AST 工具
# ---------------------------------------------------------------------------
def _ast_module_tables(src):
    """解析模块级「名称 = Dict/List 字面量」赋值，返回 {名称: value 节点}。
    解析失败返回 None。按源码 sha256 做有界 LRU 缓存（只读节点，安全）。"""
    key = _hashlib.sha256(src.encode("utf-8", "surrogatepass")).hexdigest()
    with _TABLES_LOCK:
        hit = _TABLES_CACHE.get(key)
        if hit is not None:
            _TABLES_CACHE.move_to_end(key)
            return hit
    try:
        tree = _ast.parse(src)
    except SyntaxError:
        return None
    out = {}
    for node in tree.body:
        if (isinstance(node, _ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], _ast.Name)
                and isinstance(node.value, (_ast.Dict, _ast.List))):
            out[node.targets[0].id] = node.value
    with _TABLES_LOCK:
        _TABLES_CACHE[key] = out
        _TABLES_CACHE.move_to_end(key)
        while len(_TABLES_CACHE) > _TABLES_CACHE_MAX:
            _TABLES_CACHE.popitem(last=False)
    return out


def _source_lines(src):
    """把源码切成「带行尾终止符」的行表，**整份只切一次**。

    与 CPython ast._splitlines_no_ff 完全同构（保留 \\r\\n / \\n / \\r），
    供 _source_segment 按节点行号 O(1) 索引——替代 ast.get_source_segment
    逐节点从位置 0 正则扫到节点行的 O(N×文件大小) 开销。"""
    splitter = getattr(_ast, "_splitlines_no_ff", None)
    if splitter is not None:
        return splitter(src)
    return [m[0] for m in _re.finditer(r"(.*?(?:\r\n|\n|\r|$))", src)]


def _source_segment(lines, node):
    """从预切行表取节点源码段，逐字节复刻 ast.get_source_segment(padded=False)。

    col_offset / end_col_offset 是 UTF-8 **字节**偏移（含中文注释才正确），
    故按 .encode()[...].decode() 切片；行表已含终止符，用 ''.join 拼接。
    位置信息缺失返回 None（与原函数一致，调用方 `or ""` 兜底）。"""
    try:
        if node.end_lineno is None or node.end_col_offset is None:
            return None
        lineno = node.lineno - 1
        end_lineno = node.end_lineno - 1
        col_offset = node.col_offset
        end_col_offset = node.end_col_offset
    except AttributeError:
        return None
    if end_lineno == lineno:
        return lines[lineno].encode()[col_offset:end_col_offset].decode()
    first = lines[lineno].encode()[col_offset:].decode()
    last = lines[end_lineno].encode()[:end_col_offset].decode()
    return "".join([first] + lines[lineno + 1:end_lineno] + [last])


def _dict_entries(dnode):
    """Dict 节点中「字符串键 -> 字符串值」的条目 {key: (键节点, 值节点)}。
    含任何非常量成员的表返回的映射会缺项——调用方以此跳过非纯字面量表。"""
    out = {}
    if not isinstance(dnode, _ast.Dict):
        return out
    for k, v in zip(dnode.keys, dnode.values):
        if (isinstance(k, _ast.Constant) and isinstance(v, _ast.Constant)
                and isinstance(k.value, str) and isinstance(v.value, str)):
            out[k.value] = (k, v)
    return out


def _entity_fields(call):
    """从 Entity(...) 调用节点提取 (canonical, modes, variants)。"""
    canonical = None
    if call.args and isinstance(call.args[0], _ast.Constant):
        canonical = call.args[0].value
    modes, variants = (), ()
    for kw in call.keywords:
        if kw.arg == "canonical" and isinstance(kw.value, _ast.Constant):
            canonical = kw.value.value
        elif kw.arg in ("modes", "variants") and isinstance(kw.value, (_ast.Tuple, _ast.List)):
            try:
                vals = tuple(_ast.literal_eval(kw.value))
            except ValueError:
                continue
            if kw.arg == "modes":
                modes = vals
            else:
                variants = vals
    return canonical, modes, variants


#: 角色名共存短键：这些短键（同一表内）与「辛吉勒姆/洛瑟菈/露希尔」等官方长键
#: 共用前缀/后缀，长键优先替换本身安全（输出等价），但**禁止单边删除或拆表**，
#: 一律降级为 warning 交人工复核（2026-11-24 前缀冲突闸门）。
_NAME_COEXIST_SHORT = frozenset({
    "Sigi", "西吉",          # vs Sigilum/Sigillum/Sigila mech/西吉兰机甲（辛吉勒姆/隧铠机甲）
    "露西拉", "卢西拉",       # vs 露西拉总统/卢西拉总统（洛瑟菈校长）
    "Luciel", "Luciela",     # vs Lucielle/Luciella（露希尔）
})

#: 术语键只收「词形」：含空白或标点的长键多半是整句 ASR 变体，不作为孤儿长键来源。
_PHRASE_CHARS = frozenset(" \t:：/、，,。·'’\"()（）<>《》[]【】-—–~!！?？\n\r")

#: 运行期合并表（engine._resolve_terms 口径）：ak-ja 先 AK_TERMS 再 AK_JA_TERMS 覆盖。
#: 闸门必须按合并视图扫描，否则 AK_JA 单表会把「AK_TERMS 已登记的长键」误判成孤儿。
_UNION_TERM_TABLES = {"AK_JA_TERMS": ("AK_TERMS",)}


def _script_of(ch):
    """字符脚本类：拉丁字母数字 / 汉字 / 谚文 / 假名 / 其他（空串）。"""
    if not ch:
        return ""
    if ch.isascii() and (ch.isalnum() or ch == "_"):
        return "latin"
    o = ord(ch)
    if 0x3400 <= o <= 0x9FFF or 0xF900 <= o <= 0xFAFF:
        return "cjk"
    if 0xAC00 <= o <= 0xD7AF:
        return "hangul"
    if 0x3040 <= o <= 0x30FF:
        return "kana"
    return ""


def _same_script(a, b):
    sa = _script_of(a)
    return bool(sa) and sa == _script_of(b)


def _term_like(key):
    return (len(key) >= 2 and len(key) <= 24
            and not any(c in _PHRASE_CHARS for c in key))


def _entity_official_keys(entities):
    """实体官方键（canonical/en/ja/ko/variants）与 键->canonical 映射。"""
    official, owner = set(), {}
    for e in entities:
        canon = e[0]
        extras = e[3] if len(e) > 3 else ()
        for k in (canon,) + tuple(extras) + tuple(e[2]):
            if not k:
                continue
            official.add(k)
            owner.setdefault(k, canon)
    return official, owner


def term_registry_conflicts(tables, entities, mode_table=None, project=False):
    """术语表前缀/后缀冲突闸门（2026-11-24）。

    背景：机械替换器按键长降序 str.replace，同表长键优先是安全的；真正的污染
    来自「孤儿短键」——短键在表、对应官方长键不在该表时，短键会把长键切碎
    （西吉兰机甲→西格莉卡兰机甲、Royanes→罗伊族nes）。

    三组检查：
      A 同表长键二次命中（hard）：apply_map(长键) 必须等于该长键自己的目标；
      B 孤儿短键（hard/warn）：短键 s 在表 T、实体官方长键 l 不在 T，且 T 对 l 的
        替换结果不属于 l 的已知正确形（即 l 被切碎）→ hard；若短键本身出现在
        canonical 里（顺序替换必然二次命中，加长键救不了）→ warning 交人工收窄；
      C 角色名共存（warn）：_NAME_COEXIST_SHORT 的短键与长键同表共存，
        只提示人工复核，不拦、不删。

    tables 为 {表名: {错形: 正确形}}；entities 元素为
    (canonical, modes, variants[, 额外官方键])（兼容 Entity 对象）。
    project=True 时先按 mode_table 把 variants 投影进表（与
    state._register_entities 同构）；AK_JA_TERMS 等运行期并表按合并视图扫描。
    返回 {"hard": [...], "warn": [...]}。
    """
    def _norm(e):
        if isinstance(e, (tuple, list)):
            canon = e[0]
            modes = e[1] if len(e) > 1 else ()
            variants = e[2] if len(e) > 2 else ()
            extras = e[3] if len(e) > 3 else ()
        else:
            canon = getattr(e, "canonical", None)
            modes = getattr(e, "modes", ()) or ()
            variants = getattr(e, "variants", ()) or ()
            extras = tuple(k for k in (getattr(e, "en", None), getattr(e, "ja", None),
                                       getattr(e, "ko", None)) if k)
        return (canon, tuple(modes), tuple(variants), tuple(extras))

    ents = [_norm(e) for e in entities]
    ents = [e for e in ents if e[0]]
    tbls = {n: dict(t) for n, t in tables.items() if isinstance(t, dict)}
    # 合并视图：AK_JA_TERMS 等运行期并表的模式按合并后单表扫描。
    # 只把「并表独有键」当短键扫描（基表问题已在基表扫描过，避免重复报告）。
    union_short = {}
    for name, extra in _UNION_TERM_TABLES.items():
        if name in tbls:
            merged = {}
            for src in extra:
                if isinstance(tbls.get(src), dict):
                    merged.update(tbls[src])
            base_keys = set(merged)
            merged.update(tbls[name])
            union_short[name] = set(tbls[name]) - base_keys
            tbls[name] = merged

    if project:
        for canon, modes, variants, _extra in ents:
            for m in modes:
                tname = (mode_table or {}).get(m)
                tbl = tbls.get(tname) if tname else None
                if not isinstance(tbl, dict):
                    continue
                for v in variants:
                    tbl.setdefault(v, canon)

    hard, warn = [], []
    official, owner = _entity_official_keys(ents)

    # 长键池 + 前缀/后缀索引：对每个长键枚举 2..len-1 的前缀/后缀
    pool = set()
    for t in tbls.values():
        pool.update(t)
    pool |= official
    pre_index, suf_index = {}, {}
    for l in pool:
        if not _term_like(l):
            continue
        for i in range(2, len(l)):
            pre_index.setdefault(l[:i], set()).add(l)
            suf_index.setdefault(l[-i:], set()).add(l)

    # 每张表的替换器（懒编译：按键长降序，仅供命中的键算输出）
    sorted_pairs = {}

    def _apply_map(name, text):
        pairs = sorted_pairs.get(name)
        if pairs is None:
            pairs = sorted(tbls[name].items(), key=lambda kv: len(kv[0]), reverse=True)
            sorted_pairs[name] = pairs
        if not pairs or not any(k in text for k, _ in pairs):
            return text
        for k, v in pairs:
            if k in text:
                text = text.replace(k, v)
        return text

    for name, tbl in tbls.items():
        keys = set(tbl)
        short_keys = union_short.get(name, keys)
        for s in tbl:
            if s not in short_keys or not s or len(s) < 2:
                continue
            cands = pre_index.get(s, set()) | suf_index.get(s, set())
            for l in sorted(cands):
                if l == s:
                    continue
                if l.startswith(s):
                    if not _same_script(s[-1], l[len(s)]):
                        continue
                elif l.endswith(s):
                    if not _same_script(s[0], l[-len(s) - 1]):
                        continue
                else:
                    continue
                if l in keys:
                    # A 同表长键输出等价：长键替换结果不得再被其它键二次命中
                    out = _apply_map(name, l)
                    if out != tbl[l]:
                        item = (f"{name}[{s!r}->{tbl[s]!r}] 长键 {l!r} 二次命中"
                                f"（应得 {tbl[l]!r}，实得 {out!r}）")
                        if s in _NAME_COEXIST_SHORT:
                            warn.append("角色名共存，勿删：" + item)
                        elif s in tbl[l]:
                            # 短键落在长键的值里：加长键也救不了，只能人工收窄
                            warn.append("短键过泛（值内含键），需人工收窄：" + item)
                        else:
                            hard.append(item)
                    continue
                # B 孤儿短键：只以「实体官方键」为长键来源（正确形被切碎才是污染；
                #   ASR 整句变体被短键部分修正属预期，不进闸门）
                if l not in official:
                    continue
                # l 的 canonical/已知正确形：各表目标、实体 canonical、或 l 本身
                targets = {t[l] for t in tbls.values() if l in t}
                canon_set = set(targets)
                if l in owner:
                    canon_set.add(owner[l])
                good = canon_set | {l}
                out = _apply_map(name, l)
                if out in good:
                    continue
                canon = next(iter(targets)) if len(targets) == 1 else owner.get(l, l)
                item = (f"{name}[{s!r}->{tbl[s]!r}] 切碎长键 {l!r}"
                        f"（应得 {canon!r}，实得 {out!r}）")
                if any(s in g for g in canon_set):
                    # 短键出现在 canonical 内：补长键也救不了（顺序替换会二次命中），
                    # 只能由人工收窄短键或改 ctx 锚定 —— 列 warning，不硬拦。
                    warn.append("短键过泛，需人工收窄：" + item)
                else:
                    # 包括角色名共存短键：长键缺失时就是实污染，必须先补长键
                    hard.append(item)

        # C 同表共存对（长键已在同一表，长键优先安全）：只 warning
        for s in sorted(keys & _NAME_COEXIST_SHORT):
            for l in sorted(pre_index.get(s, set()) | suf_index.get(s, set())):
                if l in keys and l != s:
                    warn.append(f"{name}[{s!r}/{l!r}] 角色名共存对，禁单边删除/拆表")
    return {"hard": list(dict.fromkeys(hard)),
            "warn": list(dict.fromkeys(warn))}


def term_conflicts_from_pkg(pkg):
    """对运行时包（calib_core）扫描术语前后缀冲突。

    包内 TABLES 已由 state._register_entities 投影过，故不再二次投影。
    返回 {"hard": [...], "warn": [...]}。
    """
    tables = {}
    for name, tbl in getattr(pkg, "TABLES", {}).items():
        if (isinstance(tbl, dict) and tbl
                and all(isinstance(k, str) and isinstance(v, str)
                        for k, v in tbl.items())):
            tables[name] = tbl
    return term_registry_conflicts(tables, getattr(pkg, "ENTITIES", ()))


def _entity_extra_keys(call):
    """Entity(...) 的 en/ja/ko 常量键（AST 路径用）。"""
    out = []
    for kw in call.keywords:
        if kw.arg in ("en", "ja", "ko") and isinstance(kw.value, _ast.Constant):
            if isinstance(kw.value.value, str) and kw.value.value:
                out.append(kw.value.value)
    return tuple(out)


def _registry_conflicts(src, structured=False):
    """静态复算脚本 _register_entities 的注册冲突 + 术语前后缀冲突。

    合并器绝不制造注册冲突——它会 raise SystemExit 让整个校准脚本起不来。
    返回冲突描述列表（空列表 = 通过）；structured=True 时返回
    {"hard": [...], "warn": [...]}，硬拦项非空即不可用。

    2026-11-10：从「只比对静态表」升级为复算运行期投影（先注册实体的 variants
    也会写入表），修实体间同变体不同目标漏检——合并器曾因此写出起不来的脚本。
    2026-11-24：增补术语表前缀/后缀冲突闸门（同表输出等价 + 孤儿短键）。
    """
    try:
        tree = _ast.parse(src)
    except SyntaxError:
        bad = ["语法解析失败"]
        return {"hard": bad, "warn": []} if structured else bad
    tables, entities, mode_table = {}, [], {}
    reg_names = []
    for node in tree.body:
        if (isinstance(node, _ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], _ast.Name)):
            name = node.targets[0].id
            if isinstance(node.value, _ast.Dict):
                if name == "TABLES":
                    # TABLES 的值是 Name 节点（非字面量），只取字符串键名作注册表
                    reg_names = [k.value for k in node.value.keys
                                 if isinstance(k, _ast.Constant)
                                 and isinstance(k.value, str)]
                    continue
                try:
                    tables[name] = _ast.literal_eval(node.value)
                except ValueError:
                    pass
            if name == "ENTITIES" and isinstance(node.value, _ast.List):
                for elt in node.value.elts:
                    if isinstance(elt, _ast.Call):
                        c, modes, variants = _entity_fields(elt)
                        if c is not None:
                            entities.append((c, modes, variants,
                                             _entity_extra_keys(elt)))
    mode_table = tables.get("_MODE_TERM_TABLE") or {}
    # 与 state._register_entities（state.py:241-272）同构：先复制静态表，
    # 再按 ENTITIES 顺序把 variants 投影进去，先查后 setdefault。
    projected = {}

    def _projected(tname):
        if tname not in projected:
            base = tables.get(tname)
            projected[tname] = dict(base) if isinstance(base, dict) else None
        return projected[tname]

    bad = []
    for canonical, modes, variants, _extra in entities:
        for m in modes:
            tname = mode_table.get(m)
            tbl = _projected(tname) if tname else None
            if not isinstance(tbl, dict):
                continue
            for v in variants:
                if v in tbl and tbl[v] != canonical:
                    bad.append(f"{v!r}->{tbl[v]!r} 与实体 {canonical!r} 冲突")
                else:
                    tbl.setdefault(v, canonical)

    # 术语表范围：TABLES 注册表里的纯 str->str 表（运行期口径）
    term_tables = {}
    for tname in reg_names:
        tbl = _projected(tname)
        if (isinstance(tbl, dict) and tbl
                and all(isinstance(k, str) and isinstance(v, str)
                        for k, v in tbl.items())):
            term_tables[tname] = tbl
    term = term_registry_conflicts(term_tables, entities)
    hard = bad + term["hard"]
    if structured:
        return {"hard": hard, "warn": term["warn"]}
    return hard


# ---------------------------------------------------------------------------
# 校准脚本（.py）条目级三方合并
# ---------------------------------------------------------------------------
def merge_calib_script(local_src, remote_src, base_src=""):
    """校准脚本条目级三方合并。返回 (merged, added, conflicts)。

    三方 = 本地 / 远程 / 基线快照（上次同步后的内容，即公共祖先）：
      · 远程新增条目 -> 并入本地（保留远程原文行，含行尾注释）；
      · 基线有而本地已删 -> 本地有意删除，不复活；
      · 本地未动、远程修改 -> 采用远程；
      · 两边都改且不同 -> 冲突，保留本地并记录（退出推送交由人工裁决）；
      · 本地新增/修改 -> 保留本地（推送时带给别人）。
    合并结果必须同时通过 语法编译 与 实体注册冲突 两道门，任一不过整体
    放弃、返回本地原文——宁可少并一次，绝不产出起不来的脚本。
    """
    crlf = "\r\n" in local_src
    norm = lambda s: (s or "").replace("\r\n", "\n")
    local_src, remote_src, base_src = norm(local_src), norm(remote_src), norm(base_src)
    if not remote_src.strip() or not local_src.strip():
        return (local_src.replace("\n", "\r\n") if crlf else local_src), 0, []
    L, R = _ast_module_tables(local_src), _ast_module_tables(remote_src)
    B = _ast_module_tables(base_src) or {}
    if L is None or R is None:
        return (local_src.replace("\n", "\r\n") if crlf else local_src), 0, \
            ["远程或本地脚本解析失败，放弃合并"]

    lines = local_src.split("\n")
    rlines = remote_src.split("\n")
    # ENTITIES 指纹用「带终止符」的预切行表（整份各切一次），与上面按 \n 切、
    # 用于行区间替换的 lines/rlines 互不相干。
    lseg_lines = _source_lines(local_src)
    rseg_lines = _source_lines(remote_src)
    bseg_lines = _source_lines(base_src)
    edits = []          # (start0, end0_exclusive, 替换行列表)；start==end 表示插入
    added, conflicts = 0, []

    for name, rnode in R.items():
        lnode = L.get(name)
        if lnode is None or type(lnode) is not type(rnode):
            continue

        if isinstance(rnode, _ast.Dict):
            # 只合并纯「字符串->字符串」表；结构复杂的表（INFO/映射表）不动
            le, re_ = _dict_entries(lnode), _dict_entries(rnode)
            be = _dict_entries(B.get(name)) if name in B else {}
            if len(le) != len(lnode.keys) or len(re_) != len(rnode.keys):
                continue
            pos = lnode.end_lineno - 1          # 收尾 } 独占一行才可插入
            if lines[pos].strip() != "}":
                continue
            new_rows = []
            for key, (rk, rv) in re_.items():
                rval = rv.value
                if key not in le:
                    if key in be:
                        continue                 # 本地删除，尊重本地
                    row = rlines[rk.lineno - 1:rv.end_lineno]
                    new_rows.extend(row)
                    added += 1
                    continue
                lk, lv = le[key]
                if lv.value == rval:
                    continue                     # 两边一致
                bval = be[key][1].value if key in be else _MERGE_MISSING
                if bval is _MERGE_MISSING:
                    continue                     # 本地新增，保留
                if lv.value == bval:
                    # 本地未动、远程修改 -> 采用远程整行
                    edits.append((lk.lineno - 1, lv.end_lineno,
                                  rlines[rk.lineno - 1:rv.end_lineno]))
                else:
                    conflicts.append(f"{name}[{key!r}] 两边不同：保留本地 {lv.value!r}")
            if new_rows:
                edits.append((pos, pos, new_rows))

        elif isinstance(rnode, _ast.List):
            pos = lnode.end_lineno - 1
            if lines[pos].strip() != "]":
                continue
            if name == "ENTITIES":
                # Entity 调用列表：按 canonical 合并
                def _canon_map(node, seg_lines):
                    out = {}
                    for e in node.elts:
                        if isinstance(e, _ast.Call):
                            c, _m, _v = _entity_fields(e)
                            if c is not None:
                                out[c] = (e, _source_segment(seg_lines, e) or "")
                    return out
                lmap_e = _canon_map(lnode, lseg_lines)
                rmap_e = _canon_map(rnode, rseg_lines)
                bmap_e = _canon_map(B[name], bseg_lines) if isinstance(B.get(name), _ast.List) else {}
                new_rows = []
                for canon, (enode, rseg) in rmap_e.items():
                    if canon not in lmap_e:
                        if canon in bmap_e:
                            continue             # 本地删除，尊重本地
                        new_rows.extend(rlines[enode.lineno - 1:enode.end_lineno])
                        added += 1
                        continue
                    lnode_e, lseg = lmap_e[canon]
                    bnode_e = bmap_e.get(canon)
                    if (bnode_e is not None and lseg == bmap_e[canon][1]
                            and rseg != bmap_e[canon][1]):
                        # 本地未动、远程更新 -> 整段替换
                        edits.append((lnode_e.lineno - 1, lnode_e.end_lineno,
                                      rlines[enode.lineno - 1:enode.end_lineno]))
                if new_rows:
                    edits.append((pos, pos, new_rows))
            else:
                # 常量列表（CONTEXT_MAP 等元组规则）：按整元素并集
                def _elts(node):
                    out = []
                    for e in node.elts:
                        try:
                            out.append((_ast.literal_eval(e), e))
                        except ValueError:
                            return None
                    return out
                lels, rels = _elts(lnode), _elts(rnode)
                bels = _elts(B[name]) if isinstance(B.get(name), _ast.List) else []
                if lels is None or rels is None or bels is None:
                    continue
                lvals = {v for v, _ in lels}
                bvals = {v for v, _ in bels}
                new_rows = []
                for val, enode in rels:
                    if val in lvals or val in bvals:
                        continue
                    new_rows.extend(rlines[enode.lineno - 1:enode.end_lineno])
                    lvals.add(val)
                    added += 1
                if new_rows:
                    edits.append((pos, pos, new_rows))

    if not edits:
        merged = local_src
    else:
        for s0, e0, repl in sorted(edits, key=lambda t: (t[0], t[1]), reverse=True):
            lines[s0:e0] = repl
        merged = "\n".join(lines)
        try:
            compile(merged, "merged_calib", "exec")
        except SyntaxError as e:
            return (local_src.replace("\n", "\r\n") if crlf else local_src), 0, \
                [f"合并结果语法不过（{e.msg}，行 {e.lineno}），已放弃并入"]
        reg = _registry_conflicts(merged)
        if reg:
            return (local_src.replace("\n", "\r\n") if crlf else local_src), 0, \
                ["合并会触发实体注册冲突：" + "；".join(reg[:3]) + "，已放弃并入"]
    if conflicts:
        _log(f"脚本合并冲突 {len(conflicts)} 条（保留本地）：{conflicts[0]}")
    merged = merged.replace("\n", "\r\n") if crlf else merged
    return merged, added, conflicts


# ---------------------------------------------------------------------------
# 学习库（.json）候选级合并
# ---------------------------------------------------------------------------
def merge_learned_kb(local_text, remote_text):
    """学习库（subtitle_learned_kb.json）候选级合并。返回 (合并文本, 新增数, 冲突数)。

    键为 "模式|错形"，语义与脚本 learn 状态机对齐：
      · 单边独有 -> 直接并入；
      · 同键：count/uncorrected 取较大值，cues/samples 取并集（沿用脚本 20/10
        封顶），ref_tokens/unc_ref_tokens 计数求和，first/last 取更早/更晚；
      · 同键不同目标 -> 置 conflict（脚本会停止自动应用，留人工裁决），alts 并入；
      · status 就高：rejected（人工否决）不被对方的 candidate/confirmed 抵消。
    任一侧解析失败返回本地原文，绝不产出坏库。
    """
    empty = _json.dumps({"version": 1, "candidates": {}}, ensure_ascii=False)
    try:
        L = _json.loads(local_text) if local_text.strip() else {"candidates": {}}
        R = _json.loads(remote_text) if remote_text.strip() else {"candidates": {}}
        lc, rc = dict(L["candidates"]), R["candidates"]
    except (ValueError, KeyError, TypeError):
        return (local_text if local_text.strip() else empty), 0, 0
    added = conflicts = 0
    for k, r in rc.items():
        l = lc.get(k)
        if l is None:
            lc[k] = r
            added += 1
            continue
        if l == r:
            continue
        m = dict(l)
        rejected = (l.get("status") == "rejected" or r.get("status") == "rejected")
        if rejected:
            m["status"] = "rejected"
        elif r.get("right") != l.get("right"):
            m["conflict"] = True
            alts = dict(m.get("alts") or {})
            alts[r.get("right", "")] = alts.get(r.get("right", ""), 0) + max(r.get("count", 1), 1)
            m["alts"] = alts
            conflicts += 1
        m["count"] = max(l.get("count", 0), r.get("count", 0))
        m["uncorrected"] = max(l.get("uncorrected", 0), r.get("uncorrected", 0))
        m["cues"] = list(dict.fromkeys(
            list(l.get("cues") or []) + list(r.get("cues") or [])))[:20]
        ls = l.get("samples") or []
        m["samples"] = (ls + [s for s in (r.get("samples") or []) if s not in ls])[:10]
        for f in ("ref_tokens", "unc_ref_tokens"):
            d = dict(l.get(f) or {})
            for t, n in (r.get(f) or {}).items():
                d[t] = d.get(t, 0) + n
            m[f] = d
        firsts = [x for x in (l.get("first"), r.get("first")) if x]
        lasts = [x for x in (l.get("last"), r.get("last")) if x]
        if firsts:
            m["first"] = min(firsts)
        if lasts:
            m["last"] = max(lasts)
        if l.get("demoted") or r.get("demoted"):
            m["demoted"] = True
        lc[k] = m
    return _json.dumps({"version": 1, "candidates": lc},
                       ensure_ascii=False, indent=1), added, conflicts
