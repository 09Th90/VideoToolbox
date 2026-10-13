# -*- coding: utf-8 -*-
# @version 2.0.0
"""声纹模板 GitHub 往返自检（临时分支，验完即删，不碰 main）。

验证 v1.19.0 修复的两条路径：
  1. 只读：main 分支递归树能否拿到 vp_inbox/（校验 ?recursive=1 生效）
  2. 往返：临时分支上 push 本机增量 -> 删掉本地副本 -> pull 拉回，内容逐字节一致
"""
import json
import os
import shutil
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "src"))
os.environ["VT_NO_VP_SYNC"] = "0"

import video_toolbox as e  # noqa: E402

BRANCH = "vp-selftest-" + time.strftime("%H%M%S")
ok_all = True


def step(msg, cond):
    global ok_all
    print("  [%s] %s" % ("PASS" if cond else "FAIL", msg))
    if not cond:
        ok_all = False


cfg = e._sync_conn()
token = e._gh_token(cfg)
print("token:", ("有（%s...）" % token[:6]) if token else "无")
if not token:
    sys.exit("无 GitHub token，无法自检")

# ---------- 1. 只读：main 的递归树 ----------
print("\n== 1. main 分支递归树（只读）==")
tree = e._gh_remote_tree(cfg, token)
step("递归树可拉取", isinstance(tree, dict) and len(tree) > 0)
step("树里含仓库根文件 subtitle_calib_merged.py",
     bool(tree) and "subtitle_calib_merged.py" in tree)
n_main = len([p for p in (tree or {}) if p.startswith("vp_inbox/")])
step("递归子目录可见（树里有 src/ 下的文件，证明 recursive 生效）",
     bool(tree) and any(p.startswith("src/") for p in tree))
print("  main 上现有 vp_inbox 文件数：%d（修复前应为 0）" % n_main)

# ---------- 2. 造一条声纹增量 ----------
print("\n== 2. 造一条本地声纹增量 ==")
import voiceprint_sync as vps  # noqa: E402

name = "_selftest_主播_%s" % time.strftime("%H%M%S")
emb = [0.01 * (i % 17) for i in range(192)]
tmpl = {"name": name, "dim": 192, "created": "2026-10-11", "updated": "2026-10-11",
        "seconds": 12.5, "embedding": emb, "weight": 3.0, "clips": 3,
        "mix": [{"fp": vps.embedding_fp(emb), "v": emb, "w": 3.0, "n": 3,
                 "author": vps.config()["client_id"][:8]}]}
open(vps._pending_path(), "a", encoding="utf-8").close() if not os.path.isfile(
    vps._pending_path()) else None
vps.queue_upsert(name, tmpl)
step("入队成功", vps.pending_count() > 0)
vps.push(quiet=True)
locals_files = e._vp_inbox_local_files()
step("已落到本地 vp_inbox（%d 个文件）" % len(locals_files), len(locals_files) > 0)
rel, abspath = locals_files[-1]
body = open(abspath, encoding="utf-8").read()
print("  增量文件：%s（%d 字节）" % (rel, len(body)))

# ---------- 3. 建临时分支并上传 ----------
print("\n== 3. 临时分支 %s 往返 ==" % BRANCH)
base = "repos/%s/%s" % (cfg["owner"], cfg["repo"])
ok, ref = e._gh_request_any("GET", f"{base}/git/ref/heads/{cfg['branch']}", token)
step("读到 main head", ok)
main_sha = ref["object"]["sha"] if ok else ""
ok, _ = e._gh_request_any("POST", f"{base}/git/refs", token,
                          {"ref": f"refs/heads/{BRANCH}", "sha": main_sha})
step("临时分支已创建", ok)
if not ok:
    sys.exit("建分支失败，中止（未做写操作）")

tcfg = dict(cfg)
tcfg["branch"] = BRANCH
try:
    rtree = e._gh_remote_tree(tcfg, token) or {}
    step("临时分支树可读（%d 项）" % len(rtree), len(rtree) > 0)

    # push：把本机新增的 vp_inbox 文件做成 tree 条目并真正提交
    entries, n = e._gh_push_vp_inbox(tcfg, token, rtree)
    step("push 生成 %d 个 tree 条目" % n, n >= 1)
    ok, com0 = e._gh_request_any("GET", f"{base}/git/commits/{main_sha}", token)
    step("读到 main commit（取 base_tree）", ok)
    base_tree = com0["tree"]["sha"] if ok else ""
    ok, tree2 = e._gh_request_any("POST", f"{base}/git/trees", token,
                                  {"base_tree": base_tree, "tree": entries})
    step("创建 tree 成功", ok)
    if ok:
        ok, com = e._gh_request_any("POST", f"{base}/git/commits", token, {
            "message": "selftest: 声纹增量往返（临时分支，稍后删除）",
            "tree": tree2["sha"], "parents": [main_sha]})
        step("创建 commit 成功", ok)
        if ok:
            ok, _ = e._gh_request_any("PATCH", f"{base}/git/refs/heads/{BRANCH}",
                                      token, {"sha": com["sha"], "force": False})
            step("分支指向新 commit", ok)

    # pull：删掉本地副本后拉回
    os.remove(abspath)
    step("本地副本已删除", not os.path.isfile(abspath))
    got = e._gh_pull_vp_inbox(tcfg, token)
    step("pull 拉回 %d 个文件" % got, got >= 1)
    back = open(abspath, encoding="utf-8").read() if os.path.isfile(abspath) else ""
    step("内容逐字节一致", back == body)
    if back != body:
        print("  原：%r" % body[:120])
        print("  回：%r" % back[:120])

    # 幂等：再拉一次不应重复写
    again = e._gh_pull_vp_inbox(tcfg, token)
    step("重复拉取幂等（第二次 0 个）", again == 0)
finally:
    # ---------- 4. 清理 ----------
    ok, _ = e._gh_request_any("DELETE", f"{base}/git/refs/heads/{BRANCH}", token)
    step("临时分支已删除", ok)
    try:
        os.remove(abspath)
    except OSError:
        pass

print("\n结果：%s" % ("全部通过" if ok_all else "有失败项"))
raise SystemExit(0 if ok_all else 1)
