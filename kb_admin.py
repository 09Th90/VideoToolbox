#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# @version 1.12.2
"""视频工具箱 · 校准知识更新库 —— 管理员工具（完全独立程序）

定位：工具箱本体只做两件事——「更新」（kb-sync 拉基线+增量并本地合并）与
「上传增量」（kb-push 把学习库新增写进更新库收件箱）。更新库的服务器侧
管理全部在本程序：

  init            由脚本内置知识生成首版权威基线 baseline.json（seq=1）
  status          盘点更新库：基线/各客户端增量/全局生效/冲突/可回收预览
  compact         折叠全部增量进新基线（淘汰 superseded/tombstone/promoted，
                  冲突隔离不折叠），旧基线与 inbox 只移不删归档到 archive/
  prune           回收超龄且已无贡献的 inbox 文件（leave-one-out 无损判定，
                  默认 dry-run；执行也只 move 到 archive/pruned_*，不物删）
  archive-prune   清理过旧的 archive/seq_* 归档（默认移到 _cold，
                  物理删除需 --delete --force 双开关）
  publish         把本地更新库发布到 GitHub 仓库专用分支（Git Data API，
                  经 gh CLI 取 token；供各机器 pull 的镜像源）
  pull            从 GitHub 分支拉回本地镜像（网络盘不通时的分发通道）
  maintainers     查看/增删基线 meta 中的维护者名单
  serve           把更新库目录起成局域网 HTTP 只读镜像（免搭服务器）
  schedule        打印定期 compact+prune+publish 的 Windows 计划任务命令
  selftest        隔离环境端到端断言（init→上传→compact→prune→publish 干跑）

独立性：不 import 工具箱任何模块；schema 校验、确定性合并、条目 id 规则
与 subtitle_calib_merged.py 第 8 节保持一致（复刻而非依赖）。知识库内容
通过 AST 静态读取（不执行脚本），避免执行第三方代码。

更新库布局（与客户端约定一致）：
  <root>/baseline.json                 {"schema":1,"seq":N,"meta":{...},"entries":{key:entry}}
  <root>/inbox/<client_id>/<ts>.jsonl  各客户端增量，一行一个条目
  <root>/archive/...                   本程序的归档区（只移不删）

典型节奏：pull → status →（必要时 compact / prune）→ publish。

用法（两种）：
  · 双击 kb_admin.exe / 不带参数运行 → 进入**交互菜单**，按序号选功能（执行完回到菜单）；
  · 命令行 → kb_admin.exe <命令> [选项]，例如
      kb_admin.exe status
      kb_admin.exe cycle --collect --publish
      kb_admin.exe maintainers add <名字>
    完整参数见 kb_admin.exe --help。
"""

import argparse
import base64
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import traceback
import uuid
import datetime as _dt

# ---------------------------------------------------------------------------
# 常量（与客户端 subtitle_calib_merged.py 第 8 节一致）
# ---------------------------------------------------------------------------
#: PyInstaller 打包（--onefile）后 __file__ 位于临时解包目录，程序目录要用 exe 路径
if getattr(sys, "frozen", False):
    APP_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_ROOT = os.path.join(APP_DIR, "data", "calib_sync_remote")
DEFAULT_SCRIPT = os.path.join(APP_DIR, "subtitle_calib_merged.py")
#: 连接参数唯一入口：内置 github_proxy.yaml（与工具箱同一份；exe 放程序目录旁）
GITHUB_PROXY_YAML = os.environ.get("VT_GITHUB_YAML") or \
    os.path.join(APP_DIR, "github_proxy.yaml")

#: 兜底默认（与内置 yaml 的 vt-github 段一致）
_CONN_DEFAULTS = {
    "owner": "09Th90", "repo": "VideoToolbox",
    "api": "https://api.github.com", "token": "",
    # 更新库专用分支（不与 gh-pages 安装器、main 收集分支混用）
    "kb_branch": "kb-repo",
    "collect_branch": "main",
    # 收集分支上工具箱后台上传的文件（pull --collect 拉回进收件区）
    "collect_files": ["subtitle_calib_merged.py", "subtitle_learned_kb.json"],
}
GH_OWNER, GH_REPO, GH_API = ("", "", "")   # 运行时由 _gh_conn() 填充
GH_BRANCH = "kb-repo"


def _gh_conn(refresh=False):
    """读内置 github_proxy.yaml 的 vt-github 段（缓存；缺字段用默认补齐）。"""
    global _GH_CONN_CACHE, GH_OWNER, GH_REPO, GH_API, GH_BRANCH
    if _GH_CONN_CACHE and not refresh:
        return _GH_CONN_CACHE
    cfg = {k: (list(v) if isinstance(v, list) else v)
           for k, v in _CONN_DEFAULTS.items()}
    try:
        import yaml
        with open(GITHUB_PROXY_YAML, encoding="utf-8-sig") as f:
            data = yaml.safe_load(f) or {}
        vg = data.get("vt-github") or {}
        for key in ("owner", "repo", "api", "token", "kb_branch",
                    "collect_branch"):
            val = str(vg.get(key) or "").strip()
            if val:
                cfg[key] = val
        files = vg.get("files")
        if isinstance(files, list) and files:
            cfg["collect_files"] = [str(p).strip()
                                    for p in files if str(p).strip()]
    except Exception as e:  # noqa: BLE001  yaml 缺失/解析失败 → 内置默认
        print(f"提示：读取 {GITHUB_PROXY_YAML} 失败（{e}），改用内置默认连接")
    _GH_CONN_CACHE = cfg
    GH_OWNER, GH_REPO, GH_API = cfg["owner"], cfg["repo"], cfg["api"]
    GH_BRANCH = cfg["kb_branch"]
    return cfg


_GH_CONN_CACHE = None
_gh_conn()   # 模块加载即解析连接参数

_SYNC_TABLES = ("BILINGUAL_TERMS", "CONTEXT_MAP", "EXCLUDE_CONTEXT",
                "ENTITIES_VARIANT", "LEARNED_CANDIDATE")
_SINGLE_VALUE = ("BILINGUAL_TERMS", "ENTITIES_VARIANT", "LEARNED_CANDIDATE")
_FNAME_TS = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{6}(?:\.\d{1,6})?)(?:-[0-9a-f]{4})?$")


def _now():
    return _dt.datetime.now(_dt.timezone.utc)


# ---------------------------------------------------------------------------
# 库读写
# ---------------------------------------------------------------------------
def entry_valid(e):
    """条目 schema 校验（与客户端同口径的宽松版，只读不执行）。"""
    if not isinstance(e, dict):
        return False
    for fld in ("id", "author", "ts", "op", "table", "mode", "key", "value"):
        if fld not in e:
            return False
    return (e["op"] in ("upsert", "tombstone")
            and e["table"] in _SYNC_TABLES
            and isinstance(e["key"], str) and e["key"] != ""
            and isinstance(e["value"], str))


def _load_json(path, default=None):
    if not os.path.isfile(path):
        return default
    try:
        with open(path, encoding="utf-8-sig") as f:
            return json.load(f)
    except (ValueError, OSError):
        return default


def read_jsonl(path):
    """-> (条目列表, 畸形行数)。畸形行跳过并计数。"""
    out, bad = [], 0
    try:
        with open(path, encoding="utf-8-sig", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                except ValueError:
                    bad += 1
                    continue
                if entry_valid(e):
                    out.append(e)
                else:
                    bad += 1
    except OSError:
        pass
    return out, bad


def write_jsonl(path, entries):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")


def write_json_atomic(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")
    os.replace(tmp, path)


def file_ts(path, entries):
    """文件时间：文件名时间戳 > 条目最大 ts > mtime。"""
    stem = os.path.splitext(os.path.basename(path))[0]
    m = _FNAME_TS.match(stem)
    if m:
        s = m.group(1)
        try:
            return _dt.datetime.strptime(
                s, "%Y-%m-%dT%H%M%S.%f" if "." in s else "%Y-%m-%dT%H%M%S"
            ).replace(tzinfo=_dt.timezone.utc)
        except ValueError:
            pass
    best = None
    for e in entries:
        try:
            t = _dt.datetime.fromisoformat(str(e["ts"]).replace("Z", "+00:00"))
            if t.tzinfo is None:
                t = t.replace(tzinfo=_dt.timezone.utc)
            best = t if best is None or t > best else best
        except ValueError:
            continue
    return best or _dt.datetime.fromtimestamp(os.path.getmtime(path),
                                              tz=_dt.timezone.utc)


def load_library(root):
    """-> (meta, baseline_entries, files, bad)。files 按时间升序。"""
    data = _load_json(os.path.join(root, "baseline.json"), {}) or {}
    meta = dict(data.get("meta") or {})
    if data.get("seq") is not None:
        meta["seq"] = data["seq"]
    base = [e for e in (data.get("entries") or {}).values() if entry_valid(e)]
    files, bad = [], 0
    inbox = os.path.join(root, "inbox")
    if os.path.isdir(inbox):
        for cid in sorted(os.listdir(inbox)):
            cdir = os.path.join(inbox, cid)
            if not os.path.isdir(cdir):
                continue
            for fn in sorted(os.listdir(cdir)):
                if not fn.endswith(".jsonl"):
                    continue
                p = os.path.join(cdir, fn)
                es, b = read_jsonl(p)
                bad += b
                files.append({"cid": cid, "path": p, "name": fn,
                              "ts": file_ts(p, es), "entries": es})
    files.sort(key=lambda x: x["ts"])
    return meta, base, files, bad


# ---------------------------------------------------------------------------
# 确定性合并（与客户端 _sync_merge 同口径，独立复刻）
# ---------------------------------------------------------------------------
def entry_key(e):
    k = (e["table"], e.get("mode", ""), e["key"])
    if e["table"] == "CONTEXT_MAP" and e.get("rx") is not None:
        rx = e["rx"] if isinstance(e["rx"], str) else tuple(e["rx"])
        k = k + (rx,)
    return k


def det_merge(entries):
    by_id = {}
    for e in sorted(entries, key=lambda x: (x["ts"], x["id"])):
        old = by_id.get(e["id"])
        if old is not None and (old["ts"], old["id"]) > (e["ts"], e["id"]):
            continue
        by_id[e["id"]] = e
    superseded = {e.get("supersedes") for e in by_id.values() if e.get("supersedes")}
    groups = {}
    for eid, e in by_id.items():
        if eid in superseded:
            continue
        groups.setdefault(entry_key(e), []).append(e)
    applied, conflicts = {}, {}
    for key, es in groups.items():
        es.sort(key=lambda x: (x["ts"], x["id"]))
        if es[-1]["op"] == "tombstone":
            continue
        if key[0] in _SINGLE_VALUE:
            vals = {}
            for e in es:
                vals.setdefault(e["value"], e)
            if len(vals) > 1:
                conflicts[key] = es
                continue
        applied[key] = es[-1]
    return applied, conflicts


def signature(entries):
    """生效集指纹（prune 的 leave-one-out 判定基准）。"""
    applied, conflicts = det_merge(entries)
    a = tuple(sorted((k, v["id"], v["value"]) for k, v in applied.items()))
    c = tuple(sorted((k, tuple(sorted(e["id"] for e in es)))
                     for k, es in conflicts.items()))
    return (a, c)


# ---------------------------------------------------------------------------
# 知识库内置表：AST 静态读取（不执行脚本）
# ---------------------------------------------------------------------------
import ast as _ast


def builtin_tables(script_path):
    """解析脚本模块级 `NAME = 字面量` 赋值 -> {name: value}。"""
    with open(script_path, encoding="utf-8", errors="replace") as f:
        src = f.read()
    out = {}
    for node in _ast.parse(src).body:
        if (isinstance(node, _ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], _ast.Name)):
            try:
                out[node.targets[0].id] = _ast.literal_eval(node.value)
            except (ValueError, TypeError):
                continue
    return out


def make_entry(author, table, mode, key, value, op="upsert", sup=None,
               evidence=None, rx=None, ts=None):
    id_src = f"calib|{author}|{table}|{mode}|{key}|{value}"
    if rx is not None:
        id_src += "|" + (rx if isinstance(rx, str) else "|".join(rx))
    e = {"id": str(uuid.uuid5(uuid.NAMESPACE_URL, id_src)),
         "author": author, "ts": ts or _now().isoformat(timespec="milliseconds"),
         "op": op, "table": table, "mode": mode, "key": key, "value": value,
         "supersedes": sup, "evidence": dict(evidence or {})}
    if rx is not None:
        e["rx"] = rx
    return e


# ---------------------------------------------------------------------------
# 子命令
# ---------------------------------------------------------------------------
def cmd_init(args):
    root, script = args.root, args.script
    if not os.path.isfile(script):
        print(f"找不到知识脚本：{script}")
        return 1
    if os.path.isfile(os.path.join(root, "baseline.json")) and not args.force:
        print("baseline.json 已存在（重建请加 --force；重建后请 publish 分发）")
        return 1
    g = builtin_tables(script)
    mode_term = g.get("_MODE_TERM_TABLE") or {}
    mode_ctx = g.get("_MODE_CTX_TABLE") or {}
    ts = _now().isoformat(timespec="seconds")
    entries = {}

    def add(e):
        e["ts"] = ts
        entries[e["id"]] = e

    for mode, tname in mode_term.items():
        for k, v in (g.get(tname) or {}).items():
            if isinstance(k, str) and isinstance(v, str):
                e = make_entry("system", "ENTITIES_VARIANT", mode, k, v)
                add(e)
    for mode, cname in mode_ctx.items():
        for row in (g.get(cname) or []):
            try:
                rx, wrong, right = row
            except (TypeError, ValueError):
                continue
            if wrong and right:
                add(make_entry("system", "CONTEXT_MAP", mode, wrong, right, rx=rx))
    for wrong, val in (g.get("EXCLUDE_CONTEXT") or {}).items():
        try:
            right, rxs = val
        except (TypeError, ValueError):
            continue
        add(make_entry("system", "EXCLUDE_CONTEXT", "bi", wrong, right,
                       rx=list(rxs)))
    meta = {"maintainers": ["system"], "source": os.path.basename(script),
            "created": ts}
    write_json_atomic(os.path.join(root, "baseline.json"),
                      {"schema": 1, "seq": 1, "meta": meta, "entries": entries})
    print(f"baseline 首版已生成：{os.path.join(root, 'baseline.json')} "
          f"（seq=1，{len(entries)} 条）")
    return 0


def cmd_status(args):
    root = args.root
    if not os.path.isdir(root):
        print(f"更新库不存在：{root}")
        return 1
    meta, base, files, bad = load_library(root)
    all_entries = base + [e for f in files for e in f["entries"]]
    applied, conflicts = det_merge(all_entries)
    print(f"更新库   : {root}")
    print(f"基线     : seq={meta.get('seq','—')} 条目={len(base)} "
          f"维护者={meta.get('maintainers') or ['system']} "
          f"created={meta.get('created','—')} "
          f"compacted_from={meta.get('compacted_from','—')}")
    print(f"增量     : {len(files)} 文件 / {len(all_entries)-len(base)} 条"
          + (f"（畸形拒绝 {bad}）" if bad else ""))
    if files:
        print(f"时间跨度 : {files[0]['ts']:%Y-%m-%d %H:%M} → "
              f"{files[-1]['ts']:%Y-%m-%d %H:%M} (UTC)")
        by_cid = {}
        for f in files:
            by_cid[f["cid"]] = by_cid.get(f["cid"], 0) + 1
        for cid, n in sorted(by_cid.items()):
            print(f"  · {cid[:8]}…  {n} 文件")
    print(f"全局生效 : {len(applied)} 键 / 冲突隔离 {len(conflicts)} 组")
    safe = over_age_safe(root, args.days, files, base)
    print(f"可回收   : {len(safe)} 个文件（> {args.days} 天且 leave-one-out "
          f"已无贡献；prune --apply 执行）")
    if conflicts:
        print("冲突样例 :")
        for k in list(conflicts)[:5]:
            print("   " + " | ".join(str(x) for x in k))
    return 0


def over_age_safe(root, days, files, base, apply_=False):
    cutoff = _now() - _dt.timedelta(days=days)
    all_entries = base + [e for f in files for e in f["entries"]]
    full_sig = signature(all_entries)
    hits = []
    for f in files:
        if f["ts"] >= cutoff:
            continue
        rest = base + [e for g in files if g is not f for e in g["entries"]]
        if signature(rest) == full_sig:
            hits.append(f)
    if not apply_:
        return hits
    if not hits:
        return []
    stamp = _now().strftime("%Y%m%d_%H%M%S")
    dest_base = os.path.join(root, "archive", f"pruned_{stamp}")
    moved = []
    for f in hits:
        dst = os.path.join(dest_base, "inbox", f["cid"], f["name"])
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.move(f["path"], dst)
        moved.append((f["cid"], f["name"], f["ts"]))
    write_json_atomic(os.path.join(dest_base, "prune_report.json"),
                      {"pruned_at": _now().isoformat(timespec="seconds"),
                       "days_threshold": days,
                       "moved": [{"cid": c, "file": n, "ts": t.isoformat()}
                                 for c, n, t in moved]})
    return moved


def cmd_prune(args):
    root = args.root
    meta, base, files, _bad = load_library(root)
    if not files:
        print("inbox 为空，无需回收。")
        return 0
    hits = over_age_safe(root, args.days, files, base)
    if not args.apply:
        print(f"[dry-run] 阈值 {args.days} 天，可安全回收 {len(hits)} 个文件"
              f"（--apply 执行；仅 move 到 archive/pruned_*/，不物理删除）")
        for f in hits:
            print(f"   {f['cid'][:8]}…/{f['name']}  {f['ts']:%Y-%m-%d} "
                  f"{len(f['entries'])} 条")
        return 0
    moved = over_age_safe(root, args.days, files, base, apply_=True)
    print(f"prune 完成：回收 {len(moved)} 个文件 -> archive/pruned_*（只移不删）")
    for c, n, t in moved:
        print(f"   {c[:8]}…/{n}  ({t:%Y-%m-%d})")
    return 0


def cmd_compact(args):
    root = args.root
    meta, base, files, _bad = load_library(root)
    if not meta:
        print("无 baseline.json（先 init）。")
        return 1
    pending = [e for f in files for e in f["entries"]]
    pending.sort(key=lambda x: (x["ts"], x["id"]))
    applied, conflicts = det_merge(base + pending)
    g = builtin_tables(args.script) if os.path.isfile(args.script) else {}
    mode_term = g.get("_MODE_TERM_TABLE") or {}
    pruned = {"superseded": 0, "tombstone": 0, "promoted": 0, "conflict": len(conflicts)}
    ids = {e["id"] for e in base + pending}
    sup = {e.get("supersedes") for e in base + pending if e.get("supersedes")}
    pruned["superseded"] = len(sup & ids)
    pruned["tombstone"] = sum(1 for e in base + pending
                              if e["op"] == "tombstone" and e["id"] not in sup)
    out_entries = {}
    for key, e in applied.items():
        table, mode, k, v = key[0], key[1], e["key"], e["value"]
        tname = (mode_term.get(mode) if table == "ENTITIES_VARIANT"
                 else ("BILINGUAL_TERMS" if table == "BILINGUAL_TERMS" else None))
        if tname and isinstance(g.get(tname), dict) and g[tname].get(k) == v:
            pruned["promoted"] += 1
            continue          # 已固化进脚本内置表，通道不再保留
        out_entries["\x1f".join(map(str, key))] = e
    new_seq = int(meta.get("seq") or 0) + 1
    arch = os.path.join(root, "archive", f"seq_{new_seq}")
    os.makedirs(arch, exist_ok=True)
    old_bp = os.path.join(root, "baseline.json")
    if os.path.isfile(old_bp):
        shutil.copy2(old_bp, os.path.join(arch, f"baseline_v{meta.get('seq')}.json"))
    for f in files:
        d = os.path.join(arch, "inbox", f["cid"])
        os.makedirs(d, exist_ok=True)
        try:
            shutil.move(f["path"], os.path.join(d, f["name"]))
        except OSError:
            continue
    new_meta = dict(meta)
    new_meta["compacted_from"] = int(meta.get("seq") or 0)
    new_meta["pruned"] = pruned
    new_meta["maintainers"] = new_meta.get("maintainers") or ["system"]
    write_json_atomic(old_bp, {"schema": 1, "seq": new_seq,
                               "meta": new_meta, "entries": out_entries})
    print(f"kb-compact：seq {meta.get('seq')} -> {new_seq}，"
          f"增量 {len(pending)} 条 -> 生效 {len(out_entries)} 条，"
          f"冲突 {len(conflicts)} 组（隔离不折叠）")
    print(f"清理报告：{pruned}")
    print(f"归档：{arch}（只移不删，可回溯）")
    print("下一步：publish 分发给各客户端。")
    return 0


def cmd_archive_prune(args):
    arch = os.path.join(args.root, "archive")
    if not os.path.isdir(arch):
        print("无 archive 目录。")
        return 0
    cutoff = _now() - _dt.timedelta(days=args.days)
    done = []
    for name in sorted(os.listdir(arch)):
        p = os.path.join(arch, name)
        if not os.path.isdir(p) or not name.startswith("seq_"):
            continue
        mtime = _dt.datetime.fromtimestamp(os.path.getmtime(p),
                                           tz=_dt.timezone.utc)
        if mtime >= cutoff:
            continue
        if args.delete and args.force:
            shutil.rmtree(p)
        else:
            shutil.move(p, os.path.join(arch, "_cold", name))
        done.append(name)
    tag = "物理删除" if (args.delete and args.force) else "移入 _cold"
    print(f"archive-prune：阈值 {args.days} 天，{tag} {len(done)} 个归档"
          + ("" if done else "（无超龄归档）"))
    if args.delete and not args.force:
        print("！--delete 需配合 --force 才会物理删除，本次仅移到 _cold")
    return 0


def cmd_maintainers(args):
    bp = os.path.join(args.root, "baseline.json")
    data = _load_json(bp)
    if data is None:
        print(f"无基线文件：{bp}")
        return 1
    meta = data.setdefault("meta", {})
    maint = list(meta.get("maintainers") or ["system"])
    if args.op == "list":
        print("维护者：", maint)
        return 0
    if args.op == "add" and args.value not in maint:
        maint.append(args.value)
    elif args.op == "remove":
        if args.value not in maint:
            print("不在名单。")
            return 1
        maint.remove(args.value)
    meta["maintainers"] = maint
    write_json_atomic(bp, data)
    print("维护者已更新：", maint)
    return 0


# ---------------------------------------------------------------------------
# GitHub 收发（管理员工具独占；工具箱本体零 GitHub 代码）
# ---------------------------------------------------------------------------
def _gh_token():
    cfg = _gh_conn()
    tok = (cfg.get("token") or "").strip()   # 内置 yaml 显式配置优先
    if tok:
        return tok
    tok = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if tok:
        return tok.strip()
    for exe in ("gh", os.path.join(APP_DIR, "tools", "gh.exe")):
        try:
            p = subprocess.run([exe, "auth", "token"], capture_output=True,
                               text=True, timeout=20)
            if p.returncode == 0 and p.stdout.strip():
                return p.stdout.strip()
        except (OSError, subprocess.SubprocessError):
            continue
    return ""


def _api(token, method, path, payload=None):
    url = path if path.startswith("http") else f"{GH_API}{path}"
    cmd = ["curl", "-sS", "--noproxy", "*", "--max-time", "180", "-X", method]
    if token:          # 公开仓库匿名读：不带认证头
        cmd += ["-H", f"Authorization: Bearer {token}"]
    cmd += ["-H", "Accept: application/vnd.github+json",
            "-H", "User-Agent: VideoToolbox-kb-admin",
            "-w", "\n%{http_code}"]
    stdin = b""
    if payload is not None:
        cmd += ["-H", "Content-Type: application/json", "--data-binary", "@-"]
        stdin = json.dumps(payload).encode()
    cmd.append(url)
    p = subprocess.run(cmd, input=stdin, capture_output=True, timeout=200)
    body, _, code = p.stdout.decode(errors="replace").rpartition("\n")
    try:
        code = int(code.strip() or 0)
    except ValueError:
        code = 0
    if code >= 400:
        raise RuntimeError(f"{method} {url} → HTTP {code}: {body[:200]}")
    return json.loads(body) if body.strip() else {}


def _fetch_repo_file(token, rel, branch):
    """GitHub contents API 拉单文件（>1MB 回退 blobs 接口）。返回 bytes 或 None。"""
    cfg = _gh_conn()
    path = (f"/repos/{cfg['owner']}/{cfg['repo']}/contents/{rel}"
            f"?ref={branch}")
    try:
        data = _api(token, "GET", path)
        content = data.get("content")
        if not content and data.get("git_url"):
            blob_path = str(data["git_url"]).replace(cfg["api"] + "/", "")
            data = _api(token, "GET", blob_path)
            content = data.get("content")
        return base64.b64decode(content or "")
    except (RuntimeError, ValueError, KeyError) as e:
        print(f"拉取 {branch}:{rel} 失败：{e}")
        return None


def _known_entry_ids(root):
    """基线 + 全部 inbox 已有条目 id 集（collect 幂等去重用）。"""
    ids = set()
    base = _load_json(os.path.join(root, "baseline.json"), {}) or {}
    ents = base.get("entries", [])
    if isinstance(ents, dict):
        ents = list(ents.values())
    for e in ents:
        if isinstance(e, dict):
            ids.add(e.get("id"))
    inbox = os.path.join(root, "inbox")
    if os.path.isdir(inbox):
        for cid in os.listdir(inbox):
            cdir = os.path.join(inbox, cid)
            if not os.path.isdir(cdir):
                continue
            for fn in os.listdir(cdir):
                if fn.endswith(".jsonl"):
                    es, _bad = read_jsonl(os.path.join(cdir, fn))
                    for e in es:
                        ids.add(e.get("id"))
    return ids


def learned_kb_to_entries(kb_bytes, author):
    """学习库 JSON -> 增量条目（与客户端 kb-push 同口径：confirmed、非冲突）。"""
    try:
        kb = json.loads(kb_bytes.decode("utf-8-sig"))
    except (ValueError, UnicodeDecodeError) as e:
        print(f"学习库解析失败：{e}")
        return []
    out = []
    for c in (kb.get("candidates") or {}).values():
        if c.get("status") != "confirmed" or c.get("conflict"):
            continue
        wrong, right = c.get("wrong", ""), c.get("right", "")
        if not (wrong and right and wrong != right):
            continue
        out.append(make_entry(
            author, "LEARNED_CANDIDATE", c.get("mode") or "bi",
            wrong, right,
            evidence={"count": c.get("count", 1),
                      "cues": list(c.get("cues") or [])[:20],
                      "kb_status": "confirmed",
                      "source": "github-collect"}))
    return out


def cmd_collect(args):
    """收集分支（工具箱退出后台上传处）-> 更新库收件箱。

    拉 vt-github collect_files（默认：学习库 JSON + 校准脚本）：学习库的
    confirmed 候选转成条目写入 inbox/collect/（按条目 id 幂等去重，重复跑
    不产生重复）；校准脚本存根目录 collect/ 供管理员对照（内置表增长在
    compact 时经 --script 折叠进基线）。"""
    cfg = _gh_conn()
    token = _gh_token()
    branch = getattr(args, "branch", None) or cfg["collect_branch"]
    root = args.root
    n_new = 0
    kb_rel = next((f for f in cfg["collect_files"]
                   if f.endswith(".json")), None)
    author = getattr(args, "author", None) or "collect"
    if kb_rel:
        data = _fetch_repo_file(token, kb_rel, branch)
        if data is not None:
            known = _known_entry_ids(root)
            fresh = {}
            for e in learned_kb_to_entries(data, author):
                if e["id"] not in known:
                    fresh[e["id"]] = e
            if fresh:
                cdir = os.path.join(root, "inbox", author)
                os.makedirs(cdir, exist_ok=True)
                fn = os.path.join(cdir, f"{_now():%Y-%m-%dT%H%M%S}-collect.jsonl")
                write_jsonl(fn, list(fresh.values()))
                n_new = len(fresh)
            print(f"学习库收编：{kb_rel}@{branch} → 新条目 {n_new}"
                  f"（其余此前已收编）")
        else:
            print(f"学习库收编跳过：未取得 {kb_rel}@{branch}")
    for rel in cfg["collect_files"]:
        if rel.endswith(".json"):
            continue
        data = _fetch_repo_file(token, rel, branch)
        if data is None:
            continue
        dst_dir = os.path.join(root, "collect")
        os.makedirs(dst_dir, exist_ok=True)
        dst = os.path.join(dst_dir, os.path.basename(rel))
        old = open(dst, "rb").read() if os.path.isfile(dst) else b""
        if old != data:
            with open(dst, "wb") as f:
                f.write(data)
            print(f"收集快照更新：{rel}@{branch} -> {dst}")
        else:
            print(f"收集快照无变化：{rel}")
    return 0


def cmd_publish(args):
    """本地更新库 -> GitHub 分支（整仓镜像：新增/更新/删除与本地对齐）。"""
    root = args.root
    args.branch = getattr(args, "branch", None) or _gh_conn()["kb_branch"]
    token = _gh_token()
    if not token:
        print("未取得 GitHub token（gh auth login 或设 GH_TOKEN）")
        return 1
    base = f"/repos/{GH_OWNER}/{GH_REPO}"
    paths = [("baseline.json", os.path.join(root, "baseline.json"))]
    inbox = os.path.join(root, "inbox")
    if os.path.isdir(inbox):
        for cid in sorted(os.listdir(inbox)):
            cdir = os.path.join(inbox, cid)
            if os.path.isdir(cdir):
                for fn in sorted(os.listdir(cdir)):
                    if fn.endswith(".jsonl"):
                        paths.append((f"inbox/{cid}/{fn}", os.path.join(cdir, fn)))
    # 远端现状：分支存在则以其 head 为 parent 并镜像删除，否则从 main 新建
    branch_exists = True
    try:
        ref = _api(token, "GET", f"{base}/git/ref/heads/{args.branch}")
        parent = ref["object"]["sha"]
        commit = _api(token, "GET", f"{base}/git/commits/{parent}")
        tree = _api(token, "GET",
                    f"{base}/git/trees/{commit['tree']['sha']}?recursive=1")
        remote_paths = {t["path"] for t in tree.get("tree", [])
                        if t["type"] == "blob"}
    except RuntimeError:
        ref = _api(token, "GET", f"{base}/git/ref/heads/main")
        parent = ref["object"]["sha"]
        remote_paths = set()
        branch_exists = False
    tree_entries, n_up = [], 0
    local_paths = {rel for rel, _ in paths}
    for rel, fp in paths:
        if not os.path.isfile(fp):
            continue
        data = open(fp, "rb").read()
        blob = _api(token, "POST", f"{base}/git/blobs",
                    {"content": base64.b64encode(data).decode("ascii"),
                     "encoding": "base64"})
        tree_entries.append({"path": rel, "mode": "100644",
                             "type": "blob", "sha": blob["sha"]})
        n_up += 1
    for rel in remote_paths - local_paths:
        tree_entries.append({"path": rel, "mode": "100644",
                             "type": "blob", "sha": None})   # 删除
    new_tree = _api(token, "POST", f"{base}/git/trees", {"tree": tree_entries})
    seq = (_load_json(os.path.join(root, "baseline.json"), {}) or {}).get("seq")
    msg = f"kb: 更新库发布 seq={seq} {_now():%Y-%m-%d %H:%M} UTC"
    commit = _api(token, "POST", f"{base}/git/commits",
                  {"message": msg, "tree": new_tree["sha"], "parents": [parent]})
    if branch_exists:
        _api(token, "PATCH", f"{base}/git/refs/heads/{args.branch}",
             {"sha": commit["sha"], "force": True})
    else:
        _api(token, "POST", f"{base}/git/refs",
             {"ref": f"refs/heads/{args.branch}", "sha": commit["sha"]})
    print(f"已发布 {n_up} 个文件 -> {GH_OWNER}/{GH_REPO}@{args.branch} "
          f"commit {commit['sha'][:10]}")
    return 0


def cmd_pull(args):
    """GitHub 分支 -> 本地镜像（baseline 覆盖，inbox 只新建、绝不覆盖同名）。"""
    args.branch = getattr(args, "branch", None) or _gh_conn()["kb_branch"]
    token = _gh_token()          # 可为空：公开仓库匿名读
    base = f"/repos/{GH_OWNER}/{GH_REPO}"
    try:
        ref = _api(token, "GET", f"{base}/git/ref/heads/{args.branch}")
        head = ref["object"]["sha"]
        commit = _api(token, "GET", f"{base}/git/commits/{head}")
        tree = _api(token, "GET",
                    f"{base}/git/trees/{commit['tree']['sha']}?recursive=1")
    except RuntimeError as e:
        print(f"拉取失败：{e}")
        return 1
    root = args.root
    os.makedirs(os.path.join(root, "inbox"), exist_ok=True)
    n_new = n_same = n_skip = 0
    for it in tree.get("tree", []):
        if it["type"] != "blob" or not (
                it["path"] == "baseline.json" or it["path"].startswith("inbox/")):
            continue
        blob = _api(token, "GET", f"{base}/git/blobs/{it['sha']}")
        data = base64.b64decode(blob.get("content", ""))
        dst = os.path.join(root, *it["path"].split("/"))
        if os.path.isfile(dst) and open(dst, "rb").read() == data:
            n_same += 1
            continue
        if os.path.isfile(dst) and it["path"] != "baseline.json":
            print(f"   跳过同名 inbox 文件（不覆盖本地）：{it['path']}")
            n_skip += 1
            continue
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        tmp = dst + ".tmp"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, dst)
        n_new += 1
    print(f"pull 完成：新增/更新 {n_new}，一致 {n_same}，本地冲突跳过 {n_skip} "
          f"<- {GH_OWNER}/{GH_REPO}@{args.branch}")
    return 0


def cmd_serve(args):
    import http.server
    root = args.root
    if not os.path.isfile(os.path.join(root, "baseline.json")):
        print(f"无 baseline.json：{root}")
        return 1

    handler = lambda *a, **kw: http.server.SimpleHTTPRequestHandler(
        *a, directory=root, **kw)
    httpd = http.server.ThreadingHTTPServer(("0.0.0.0", args.port), handler)
    print(f"更新库镜像：http://本机IP:{args.port}/  （客户端设 VT_SYNC_ROOT 指向它）")
    print("Ctrl+C 停止")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


def cmd_schedule(args):
    if getattr(sys, "frozen", False):
        run = f'"{sys.executable}"'            # exe 自身即入口
    else:
        run = f'"{sys.executable}" "{os.path.abspath(__file__)}"'
    print("# 管理员工具定期维护（复制后在管理员终端执行；仅打印，不注册）：")
    print(f'schtasks /Create /TN "{args.task_name}-weekly" /SC WEEKLY /D SUN '
          f'/ST 03:00 /TR "{run} cycle --days {args.days} --collect '
          f'--apply --publish" /F')
    print("# cycle = collect（收编工具箱自动上传）→ compact → prune → publish 一条链。")
    return 0


def cmd_cycle(args):
    if getattr(args, "collect", False):
        try:
            cmd_collect(args)
        except Exception as e:  # noqa: BLE001  收集失败不阻断整理
            print(f"collect 跳过（{e}）")
    rc = cmd_compact(args)
    if rc:
        return rc
    cmd_prune(args)
    if args.publish:
        return cmd_publish(args)
    return 0


# ---------------------------------------------------------------------------
# selftest：隔离环境端到端
# ---------------------------------------------------------------------------
def cmd_selftest(args):
    fails = []

    def check(label, cond, detail=""):
        print(("  [OK] " if cond else "  [FAIL] ") + label + (f"  {detail}" if detail else ""))
        if not cond:
            fails.append(label)

    def ent(i, table, mode, key, value, ts, author="u1", op="upsert", sup=None):
        return {"id": f"id{i}", "author": author, "ts": ts, "op": op,
                "table": table, "mode": mode, "key": key, "value": value,
                "supersedes": sup, "evidence": {}}

    old = "2026-01-01T00:00:00.000+00:00"
    with tempfile.TemporaryDirectory() as tmp:
        root = os.path.join(tmp, "remote")
        os.makedirs(os.path.join(root, "inbox"))

        class A:
            pass
        sa = A()
        sa.root, sa.script, sa.force = root, DEFAULT_SCRIPT, False

        # init（真实脚本 AST 读表，不落默认库）
        rc = cmd_init(sa)
        check("init 成功（AST 静态读内置表）", rc == 0)
        meta, base, files, bad = load_library(root)
        check("baseline 条目充足", len(base) > 1000, f"={len(base)}")
        check("全部为系统维护者条目",
              all(e["author"] == "system" for e in base))

        # 模拟两个客户端 inbox
        write_jsonl(os.path.join(root, "inbox", "clientA",
                                 "2026-01-05T000000.000-aaaa.jsonl"),
                    [ent(900, "LEARNED_CANDIDATE", "bi", "测试错", "测试对", old)])
        b = ent(901, "BILINGUAL_TERMS", "bi", "共词", "旧值", old)
        c = ent(902, "BILINGUAL_TERMS", "bi", "共词", "新值",
                "2026-02-01T00:00:00.000+00:00", sup="id901")
        write_jsonl(os.path.join(root, "inbox", "clientB",
                                 "2026-01-06T000000.000-bbbb.jsonl"), [b])
        write_jsonl(os.path.join(root, "inbox", "clientC",
                                 "2026-02-01T000000.000-cccc.jsonl"), [c])

        # 冲突样例
        d1 = ent(903, "ENTITIES_VARIANT", "ko", "同词", "甲", old, author="u1")
        d2 = ent(904, "ENTITIES_VARIANT", "ko", "同词", "乙", old, author="u2")
        write_jsonl(os.path.join(root, "inbox", "clientD",
                                 "2026-03-01T000000.000-dddd.jsonl"), [d1, d2])

        meta, base, files, bad = load_library(root)
        applied, conflicts = det_merge(base + [e for f in files for e in f["entries"]])
        check("冲突隔离生效（同词甲乙共存判冲突）",
              any(k[2] == "同词" for k in conflicts), f"{len(conflicts)} 组")
        check("取代链正确（共词取新值）",
              applied.get(("BILINGUAL_TERMS", "bi", "共词"), {}).get("value") == "新值")

        # prune（阈值 30 天：A/B 超龄；C/D 有新贡献或含冲突不回收）
        class PA:
            pass
        pa = PA(); pa.root, pa.days, pa.apply = root, 30, True
        moved = over_age_safe(root, 30, files, base, apply_=True)
        mn = {m[1] for m in moved}
        check("回收被取代文件B", any("bbbb" in x for x in mn), str(mn))
        check("未回收独有生效A", not any("aaaa" in x for x in mn))
        sig_mid = signature(base + [e for g in load_library(root)[2] for e in g["entries"]])
        sig_full = signature(base + [e for f in files for e in f["entries"]])
        # prune 后基线未变：applied 应与 prune 前一致（A/C 仍在，B 贡献已被取代）
        applied2, conflicts2 = det_merge(base + [e for g in load_library(root)[2]
                                                 for e in g["entries"]])
        check("prune 无损（生效集不变）", applied2.get(("BILINGUAL_TERMS", "bi", "共词"),
             {}).get("value") == "新值")

        # compact：折叠 + promoted 淘汰 + 冲突保留在归档外
        class CA:
            pass
        ca = CA(); ca.root, ca.script = root, DEFAULT_SCRIPT
        rc = cmd_compact(ca)
        check("compact 成功", rc == 0)
        meta2, base2, files2, _ = load_library(root)
        check("seq 递增", int(meta2.get("seq") or 0) == int(meta.get("seq") or 0) + 1)
        check("inbox 已清空", files2 == [])
        check("归档存在", os.path.isdir(os.path.join(
            root, "archive", f"seq_{meta2.get('seq')}")))
        applied3, conflicts3 = det_merge(base2)
        check("新基线已含 A 的增量",
              any(k[2] == "测试错" for k in applied3))
        check("冲突组不折叠（同词不在新基线）",
              not any(k[2] == "同词" for k in applied3))

        # publish/pull 涉真实远端，selftest 一律不联网：只验证 CLI 面可达
        check("publish/pull 入口存在",
              callable(cmd_publish) and callable(cmd_pull))
        print("  [NOTE] selftest 不联网；publish/pull 请手动小步验证")

        # 幂等：再跑一次 load/merge 与上结果一致
        sig1 = signature(base2 + [e for g in load_library(root)[2] for e in g["entries"]])
        sig2 = signature(base2 + [e for g in load_library(root)[2] for e in g["entries"]])
        check("确定性：两次合并逐字节一致", sig1 == sig2)

    print("\n" + ("selftest 全部通过 ✅" if not fails
                  else f"selftest 失败 {len(fails)} 项 ❌：{fails}"))
    return 0 if not fails else 1


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def build_parser():
    ap = argparse.ArgumentParser(
        description="视频工具箱 · 校准知识更新库管理员工具（完全独立程序）")
    ap.add_argument("--root", default=os.environ.get("VT_SYNC_ROOT") or DEFAULT_ROOT,
                    help="更新库目录（默认 data/calib_sync_remote 或 VT_SYNC_ROOT）")
    ap.add_argument("--script", default=DEFAULT_SCRIPT,
                    help="知识脚本路径（init/compact 静态读内置表用）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init", help="生成首版 baseline.json")
    p.add_argument("--force", action="store_true", help="覆盖已有基线")
    p.set_defaults(fn=cmd_init)

    p = sub.add_parser("status", help="盘点更新库")
    p.add_argument("--days", type=int, default=30)
    p.set_defaults(fn=cmd_status)

    p = sub.add_parser("compact", help="折叠全部增量进新基线（淘汰+归档）")
    p.set_defaults(fn=cmd_compact)

    p = sub.add_parser("prune", help="回收超龄且无贡献的 inbox 文件")
    p.add_argument("--days", type=int, default=30)
    p.add_argument("--apply", action="store_true")
    p.set_defaults(fn=cmd_prune)

    p = sub.add_parser("archive-prune", help="清理过旧 archive/seq_* 归档")
    p.add_argument("--days", type=int, default=180)
    p.add_argument("--delete", action="store_true")
    p.add_argument("--force", action="store_true")
    p.set_defaults(fn=cmd_archive_prune)

    p = sub.add_parser("publish", help="本地更新库 -> GitHub 分支")
    p.add_argument("--branch", default=None,
                   help="默认取内置 yaml 的 kb_branch（缺省 kb-repo）")
    p.set_defaults(fn=cmd_publish)

    p = sub.add_parser("pull", help="GitHub 分支 -> 本地镜像")
    p.add_argument("--branch", default=None,
                   help="默认取内置 yaml 的 kb_branch（缺省 kb-repo）")
    p.set_defaults(fn=cmd_pull)

    p = sub.add_parser("collect",
                       help="收集分支（工具箱退出自动上传处）-> 更新库收件箱")
    p.add_argument("--branch", default=None,
                   help="默认取内置 yaml 的 collect_branch（缺省 main）")
    p.add_argument("--author", default="collect",
                   help="收编条目的署名（inbox 子目录名）")
    p.set_defaults(fn=cmd_collect)

    p = sub.add_parser("cycle", help="(collect) -> compact -> prune -> (publish)")
    p.add_argument("--days", type=int, default=30)
    p.add_argument("--collect", action="store_true",
                   help="先收编收集分支（工具箱退出自动上传）再整理")
    p.add_argument("--apply", action="store_true", help="prune 实际执行")
    p.add_argument("--publish", action="store_true", help="收尾发布到 GitHub")
    p.set_defaults(fn=cmd_cycle)

    p = sub.add_parser("maintainers", help="维护者名单 list/add/remove")
    p.add_argument("op", choices=["list", "add", "remove"])
    p.add_argument("value", nargs="?", default="")
    p.set_defaults(fn=cmd_maintainers)

    p = sub.add_parser("serve", help="把更新库起成局域网 HTTP 镜像")
    p.add_argument("--port", type=int, default=8123)
    p.set_defaults(fn=cmd_serve)

    p = sub.add_parser("schedule", help="打印定期维护的计划任务命令")
    p.add_argument("--days", type=int, default=30)
    p.add_argument("--task-name", default="VideoToolbox-KB")
    p.set_defaults(fn=cmd_schedule)

    p = sub.add_parser("selftest", help="隔离环境端到端断言")
    p.set_defaults(fn=cmd_selftest)
    return ap


def main(argv=None):
    # 只把「无法编码的字符」替换掉（避免个别 emoji 触发 UnicodeEncodeError），
    # 绝不要改 encoding：Windows 控制台按代码页（中文系统 cp936）解读输出字节，
    # 强改成 utf-8 会让整屏中文变成乱码（菜单头/子命令输出两段编码不一致）。
    try:
        sys.stdout.reconfigure(errors="replace")
        sys.stderr.reconfigure(errors="replace")
    except Exception:
        pass
    args = build_parser().parse_args(argv)
    return args.fn(args) or 0


# ---------------------------------------------------------------------------
# 交互菜单（无参数 / 双击 exe 时使用）
# ---------------------------------------------------------------------------
#: (序号, 命令, 菜单默认附加参数, 说明)
_MENU_ITEMS = [
    ("1", "status", [], "盘点更新库（只读：基线 / 增量 / 生效 / 冲突 / 可回收）"),
    ("2", "pull", [], "从 GitHub 分支拉回本地镜像"),
    ("3", "collect", [], "收编收集分支（工具箱退出时自动上传处）→ 收件箱"),
    ("4", "compact", [], "折叠增量进新基线（旧基线与 inbox 归档，只移不删）"),
    ("5", "prune", [], "回收超龄且无贡献的 inbox 文件（默认 dry-run）"),
    ("6", "cycle", ["--collect"], "一键日常：collect → compact → prune（加 --publish 收尾发布）"),
    ("7", "publish", [], "本地更新库 → GitHub 分支（Git Data API）"),
    ("8", "maintainers", ["list"], "维护者名单；带参数即 add / remove，例如：8 add 你的名字"),
    ("9", "serve", [], "把更新库起成局域网 HTTP 镜像（占住窗口，Ctrl+C 返回）"),
    ("10", "archive-prune", [], "清理过旧 archive/seq_* 归档（默认移到 _cold，不物删）"),
    ("11", "schedule", [], "打印定期维护的 Windows 计划任务命令"),
    ("12", "selftest", [], "隔离环境端到端自检（不联网）"),
    ("13", "init", [], "生成首版 baseline.json（仅全新更新库需要，--force 覆盖）"),
]


def _print_menu():
    print("=" * 66)
    print("  视频工具箱 · 校准知识更新库 —— 管理员工具")
    print("=" * 66)
    print(f"  更新库    : {os.environ.get('VT_SYNC_ROOT') or DEFAULT_ROOT}")
    # 知识表只在 init / compact 时用于静态读取内置术语（本工具不依赖工具箱源码）：
    # 随附就显示路径，没随附就提示可用 --script 指定，避免显示一条不存在的路径。
    if os.path.isfile(DEFAULT_SCRIPT):
        print(f"  知识表    : {DEFAULT_SCRIPT}")
    else:
        print("  知识表    : 未随附（仅 init / compact 需要，可用 --script 指定）")
    print("-" * 66)
    for key, cmd, extra, desc in _MENU_ITEMS:
        arg = (" " + " ".join(extra)) if extra else ""
        print(f"  [{key:>2}] {cmd}{arg}")
        print(f"        {desc}")
    print("-" * 66)
    print("  输入序号或命令名执行（如 4 / compact / 8 add 张三）；h 重印菜单；q 退出")


def _pause(msg="按回车键关闭…"):
    try:
        input(msg)
    except (EOFError, KeyboardInterrupt, OSError):
        pass


def interactive_menu():
    """无参数 / 双击 exe 时的交互菜单，执行完回到菜单。

    双击 kb_admin.exe 曾经「一闪而过」：subcommand 是 required，没有参数就直接
    sys.exit(2)，控制台窗口随即关闭、什么都看不到。现在无参数即进菜单；
    命令行的子命令用法（kb_admin.exe status 等）完全不变。
    """
    _print_menu()
    by_key = {k: (c, e) for k, c, e, _ in _MENU_ITEMS}
    by_cmd = {c: (c, e) for _, c, e, _ in _MENU_ITEMS}
    while True:
        try:
            choice = input("\n请选择 > ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if choice.lower() in ("", "q", "quit", "exit"):
            return 0
        if choice.lower() in ("h", "?", "help"):
            _print_menu()
            continue
        parts = choice.split()
        head, rest = parts[0], parts[1:]
        hit = by_key.get(head) or by_cmd.get(head)
        if not hit:
            print(f"  [x] 没有「{head}」这一项：请输入 1-{len(_MENU_ITEMS)}、命令名，或 h 看菜单")
            continue
        cmd, extra = hit
        argv = [cmd, *extra, *rest]
        print(f"\n>>> kb_admin {' '.join(argv)}\n")
        try:
            rc = main(argv)
        except SystemExit as e:                 # 子命令内部 sys.exit
            rc = e.code if isinstance(e.code, int) else 1
        except KeyboardInterrupt:
            print("\n  已中断（Ctrl+C）")
            rc = 130
        except Exception:
            traceback.print_exc()
            rc = 1
        print(f"\n[完成] 退出码 {rc}")


def _entry():
    """入口：无参数（含双击 exe）→ 交互菜单；带参数 → 原命令行行为。"""
    interactive = len(sys.argv) <= 1
    try:
        return interactive_menu() if interactive else main()
    except KeyboardInterrupt:
        print("\n  已中断（Ctrl+C）")
        return 130
    except SystemExit:
        raise
    except BaseException:
        # 双击场景看不到报错（窗口会立刻关闭）→ 打印后停住等回车
        traceback.print_exc()
        if interactive:
            _pause("\n程序出错，按回车键关闭…")
        return 1


if __name__ == "__main__":
    raise SystemExit(_entry())
