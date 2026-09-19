#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# @version 1.15.4
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
import json as _json

#: 三方合并中「基线里也没有该键」的哨兵（表示该条目是本地/远程单边新增）
_MERGE_MISSING = object()


def _log(msg):
    """运行信息钩子（冲突保留本地等）。默认空操作；引擎可替换为落盘日志。"""
    return None


# ---------------------------------------------------------------------------
# AST 工具
# ---------------------------------------------------------------------------
def _ast_module_tables(src):
    """解析模块级「名称 = Dict/List 字面量」赋值，返回 {名称: value 节点}。
    解析失败返回 None。"""
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
    return out


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


def _registry_conflicts(src):
    """静态复算脚本 _register_entities 的注册冲突检查（同变体不同目标）。

    合并器绝不制造这种冲突——它会 raise SystemExit 让整个校准脚本起不来。
    返回冲突描述列表（空列表 = 通过）。"""
    try:
        tree = _ast.parse(src)
    except SyntaxError:
        return ["语法解析失败"]
    tables, entities = {}, []
    for node in tree.body:
        if (isinstance(node, _ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], _ast.Name)):
            name = node.targets[0].id
            if isinstance(node.value, _ast.Dict):
                try:
                    tables[name] = _ast.literal_eval(node.value)
                except ValueError:
                    pass
            if name == "ENTITIES" and isinstance(node.value, _ast.List):
                for elt in node.value.elts:
                    if isinstance(elt, _ast.Call):
                        c, modes, variants = _entity_fields(elt)
                        if c is not None:
                            entities.append((c, modes, variants))
    mode_table = tables.get("_MODE_TERM_TABLE") or {}
    bad = []
    for canonical, modes, variants in entities:
        for m in modes:
            tname = mode_table.get(m)
            tbl = tables.get(tname) if tname else None
            if not isinstance(tbl, dict):
                continue
            for v in variants:
                if v in tbl and tbl[v] != canonical:
                    bad.append(f"{v!r}->{tbl[v]!r} 与实体 {canonical!r} 冲突")
    return bad


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
                def _canon_map(node, src):
                    out = {}
                    for e in node.elts:
                        if isinstance(e, _ast.Call):
                            c, _m, _v = _entity_fields(e)
                            if c is not None:
                                out[c] = (e, _ast.get_source_segment(src, e) or "")
                    return out
                lmap_e = _canon_map(lnode, local_src)
                rmap_e = _canon_map(rnode, remote_src)
                bmap_e = _canon_map(B[name], base_src) if isinstance(B.get(name), _ast.List) else {}
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
