# -*- coding: utf-8 -*-
"""仓库更新的 git 空间条目级合并（不碰工作区）。

背景：本地 main 领先 10 commit，origin/main 有 4 个另一实例的校准知识同步
commit，两个同步文件真实分叉。合并必须：
  1. 用 calib_merge_core 的 merge_calib_script / merge_learned_kb 做条目级
     三方合并（与 App 退出前 _pull_and_merge 同口径，避免 git 文本三方合并
     在 EOL/条目顺序上制造噪声）；
  2. 全程不读写工作区的两个同步文件——并发会话正在改写 subtitle_learned_kb.json
     （09:07 有未提交写入），`git merge` 的冲突标记会毁掉它的成果。

做法：本地内容取 HEAD blob（不是工作区），远程取 origin/main blob，
合并结果直接 hash-object 成 blob，用临时索引构造双亲合并提交。

用法：
  python _merge_sync_gitspace.py plan      # 只算不写：打印 added/conflicts 与双 base 对比
  python _merge_sync_gitspace.py apply     # 写 blob + 临时索引 + commit-tree + 更新 main
"""
import os
import subprocess
import sys

ROOT = r"D:\Agent Work\软件开发\视频工具箱"
sys.path.insert(0, os.path.join(ROOT, "src"))
import calib_merge_core as mmc  # noqa: E402

CALIB = "subtitle_calib_merged.py"
KB = "subtitle_learned_kb.json"
JSONL = "vp_inbox/3377a8c1-3a57-4815-88b1-beea66f7e359/2026-10-12T145925.339+0000-a8eb.jsonl"
BASE_SNAPSHOT = os.path.join(ROOT, "data", "calib_sync_base.py")
SCRATCH = os.path.join(ROOT, "data", "tmp", "_merge_gitspace")


def git(*args, **kw):
    return subprocess.run(["git"] + list(args), cwd=ROOT, capture_output=True, **kw)


def show(ref):
    p = git("show", ref)
    if p.returncode != 0:
        raise SystemExit("git show %s failed: %s" % (ref, p.stderr.decode("utf-8", "replace")))
    return p.stdout


def to_crlf(text):
    return text.replace("\r\n", "\n").replace("\n", "\r\n").encode("utf-8")


def compute():
    """返回 (calib_crlf_bytes, kb_lf_bytes, 报告list)"""
    rep = []
    local_calib = show("HEAD:" + CALIB).decode("utf-8")
    remote_calib = show("origin/main:" + CALIB).decode("utf-8")
    base_git = show("5c978b1:" + CALIB).decode("utf-8")  # 真正的共同祖先
    base_snap = ""
    if os.path.isfile(BASE_SNAPSHOT):
        with open(BASE_SNAPSHOT, "rb") as f:
            base_snap = f.read().decode("utf-8")

    results = {}
    for tag, base in (("git-base(5c978b1)", base_git), ("snapshot(calib_sync_base)", base_snap)):
        merged, added, conflicts = mmc.merge_calib_script(local_calib, remote_calib, base)
        compile(merged, CALIB, "exec")  # 双保险
        results[tag] = merged
        rep.append("[calib/%s] added=%d conflicts=%d len=%d->%d"
                   % (tag, added, len(conflicts), len(local_calib), len(merged)))
        for c in conflicts:
            rep.append("        conflict: " + c)
    calib_merged = results["git-base(5c978b1)"]
    if results["git-base(5c978b1)"] != results["snapshot(calib_sync_base)"]:
        rep.append("[calib] 两个 base 结果不同！详见 data/tmp/_merge_gitspace/ 下产物")
        os.makedirs(SCRATCH, exist_ok=True)
        for tag, txt in results.items():
            with open(os.path.join(SCRATCH, "calib_%s.py" % tag.split("(")[0]), "wb") as f:
                f.write(to_crlf(txt))
    else:
        rep.append("[calib] 两个 base 结果一致 ✓")

    local_kb = show("HEAD:" + KB).decode("utf-8")
    remote_kb = show("origin/main:" + KB).decode("utf-8")
    merged_kb, kadded, kconf = mmc.merge_learned_kb(local_kb, remote_kb)
    import json as _json
    _json.loads(merged_kb)
    rep.append("[kb] added=%d conflicts=%d len=%d->%d"
               % (kadded, kconf, len(local_kb), len(merged_kb)))
    kb_lf = merged_kb.replace("\r\n", "\n").encode("utf-8")

    # 只写 scratch 落盘核对，不碰工作区同步文件
    os.makedirs(SCRATCH, exist_ok=True)
    with open(os.path.join(SCRATCH, "merged_calib.py"), "wb") as f:
        f.write(to_crlf(calib_merged))
    with open(os.path.join(SCRATCH, "merged_kb.json"), "wb") as f:
        f.write(kb_lf)
    return to_crlf(calib_merged), kb_lf, rep


def hash_object(data):
    p = subprocess.run(["git", "hash-object", "-w", "--no-filters", "--stdin"],
                       cwd=ROOT, input=data, capture_output=True)
    if p.returncode != 0:
        raise SystemExit("hash-object failed: " + p.stderr.decode("utf-8", "replace"))
    return p.stdout.decode().strip()


def main():
    if len(sys.argv) < 2 or sys.argv[1] == "plan":
        _, _, rep = compute()
        print("\n".join(rep))
        print("(plan only; 用 apply 落合并提交)")
        return 0
    if sys.argv[1] != "apply":
        raise SystemExit(__doc__)

    calib_bytes, kb_bytes, rep = compute()
    print("\n".join(rep))

    calib_sha = hash_object(calib_bytes)
    kb_sha = hash_object(kb_bytes)
    jp = git("rev-parse", "origin/main:" + JSONL)
    if jp.returncode != 0:
        raise SystemExit("jsonl blob missing: " + jp.stderr.decode("utf-8", "replace"))
    jsonl_sha = jp.stdout.decode().strip()
    print("blobs: calib=%s kb=%s jsonl=%s" % (calib_sha[:8], kb_sha[:8], jsonl_sha[:8]))

    # 工作区状态记录（不阻塞）：合并只读 HEAD/origin/main blob，与工作区无关；
    # 但事后刷新工作区 calib 副本前要确认它没被并发会话改写。
    for path in (CALIB, KB):
        d = git("diff", "HEAD", "--", path)
        state = "dirty(并发未提交)" if d.stdout.strip() else "clean"
        print("worktree %s: %s" % (path, state))

    # 临时索引：HEAD 树 + 替换两个同步文件 + 并入远端 jsonl 收件记录
    idx = os.path.join(SCRATCH, "merge.index")
    os.makedirs(SCRATCH, exist_ok=True)
    if os.path.exists(idx):
        os.remove(idx)
    env = dict(os.environ, GIT_INDEX_FILE=idx)
    r = subprocess.run(["git", "read-tree", "HEAD"], cwd=ROOT, env=env,
                       capture_output=True)
    if r.returncode != 0:
        raise SystemExit("read-tree failed: " + r.stderr.decode("utf-8", "replace"))
    for mode, sha, path in (("100644", calib_sha, CALIB),
                            ("100644", kb_sha, KB),
                            ("100644", jsonl_sha, JSONL)):
        r = subprocess.run(["git", "update-index", "--add", "--cacheinfo",
                            "%s,%s,%s" % (mode, sha, path)],
                           cwd=ROOT, env=env, capture_output=True)
        if r.returncode != 0:
            raise SystemExit("update-index %s failed: %s" % (path, r.stderr))
    r = subprocess.run(["git", "write-tree"], cwd=ROOT, env=env, capture_output=True)
    if r.returncode != 0:
        raise SystemExit("write-tree failed: " + r.stderr.decode("utf-8", "replace"))
    tree = r.stdout.decode().strip()
    print("tree:", tree)

    # ---- 护栏：合并树不许丢任何 origin/main 上的文件（2026-10-13 踩坑复盘）----
    # 上一轮（8ab2689）把 origin/main 上新增的 vp_inbox 声纹增量记录**静默丢掉**
    # 了：临时索引里那条 update-index 没生效（原因已不可考），write-tree 出的树
    # 缺该文件，脚本仍照常推进 main ⇒ 远端客户端从此拉不到那条声纹，
    # 表现为「声纹数量不对」。故在 update-ref 之前逐条核对：
    #   ① 三个目标路径都在合并树里、且 blob 与预期一致；
    #   ② 合并树相对 origin/main 没有任何删除。
    # 任一不满足直接 SystemExit，绝不动 main。
    for path, sha in ((JSONL, jsonl_sha), (CALIB, calib_sha), (KB, kb_sha)):
        p = git("rev-parse", "%s:%s" % (tree, path))
        got = p.stdout.decode().strip()
        if p.returncode != 0 or got != sha:
            raise SystemExit("护栏拦截：合并树缺少/不符 %s（want=%s got=%s rc=%d）"
                             % (path, sha[:8], got[:8], p.returncode))
    p = git("diff", "--name-status", "--diff-filter=D", "origin/main", tree)
    deleted = [l for l in p.stdout.decode("utf-8", "replace").splitlines() if l.strip()]
    if deleted:
        raise SystemExit("护栏拦截：合并树相对 origin/main 有删除，拒绝推进 main：\n  "
                         + "\n  ".join(deleted))
    print("护栏 OK：目标路径齐全且合并树无任何删除（origin/main -> %s）" % tree[:8])

    msg = ("merge: 合并 origin/main 4 个校准知识同步 commit 到 dev 2.0.0\n"
           "\n"
           "origin/main 领先的 9f0c4ba/354cbe3/575c671/a5f4dea（另一实例 2026-10-12\n"
           "11:11~23:15 推送）与本地 10 个提交在两个同步文件上真实分叉。\n"
           "\n"
           "用 calib_merge_core 条目级三方合并（与 App 退出前 _pull_and_merge 同口径）：\n"
           "- subtitle_calib_merged.py：本地 2.0.0 内容全保留，远端新增条目并入，\n"
           "  CRLF blob 风格不变；\n"
           "- subtitle_learned_kb.json：候选级并集；\n"
           "- vp_inbox/3377a8c1-…-a8eb.jsonl 声纹同步收件记录（来自 575c671）随合并引入。\n"
           "\n"
           "全程 git 空间操作未读写工作区：并发会话正在改写学习库（未提交），\n"
           "其改动原样保留在工作区。")
    r = subprocess.run(["git", "commit-tree", tree, "-p", "HEAD", "-p", "origin/main",
                        "-m", msg], cwd=ROOT, capture_output=True)
    if r.returncode != 0:
        raise SystemExit("commit-tree failed: " + r.stderr.decode("utf-8", "replace"))
    commit = r.stdout.decode().strip()
    r = git("update-ref", "refs/heads/main", commit)
    if r.returncode != 0:
        raise SystemExit("update-ref failed: " + r.stderr.decode("utf-8", "replace"))
    print("merge commit:", commit)
    return 0


if __name__ == "__main__":
    sys.exit(main())
