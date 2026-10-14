# -*- coding: utf-8 -*-
# @version 2.2.5
"""批量比对 5c978b1..HEAD 改动文件的 blob 行尾是否发生翻转。

注意事项：
- `git diff --name-only` 会把非 ASCII 路径引号化，必须加 `-z` 再 split；
- `git cat-file --batch` 的响应头是 blob sha，与请求的文件名不是一回事，
  只能按请求顺序一一对应。
"""
import subprocess
import sys

ROOT = r"D:\Agent Work\软件开发\视频工具箱"


def batch_blobs(ref, files):
    """返回 {文件名: blob字节 或 None(缺失)}，严格按请求顺序。"""
    out = {}
    req = "\n".join("%s:%s" % (ref, f) for f in files)
    p = subprocess.run(["git", "cat-file", "--batch"], cwd=ROOT,
                       input=req.encode("utf-8"), stdout=subprocess.PIPE)
    if p.returncode != 0:
        raise SystemExit("git cat-file --batch failed: %s" % p.stderr)
    data = p.stdout
    pos = 0
    idx = 0
    while pos < len(data) and idx < len(files):
        nl = data.index(b"\n", pos)
        header = data[pos:nl].decode("utf-8", "replace")
        pos = nl + 1
        parts = header.split()
        if len(parts) == 3 and parts[1] == "blob":
            size = int(parts[2])
            out[files[idx]] = data[pos:pos + size]
            pos += size
            if pos < len(data) and data[pos:pos + 1] == b"\n":
                pos += 1  # 每个对象内容后有一个换行
        else:
            out[files[idx]] = None  # missing
        idx += 1
    if idx != len(files):
        raise SystemExit("batch response count mismatch: %d != %d" % (idx, len(files)))
    return out


def main():
    changed = subprocess.run(
        ["git", "diff", "--name-only", "-z", "5c978b1", "HEAD"],
        cwd=ROOT, capture_output=True, check=True,
    ).stdout.decode("utf-8").split("\0")
    changed = [f for f in changed if f]
    old = batch_blobs("5c978b1", changed)
    new = batch_blobs("HEAD", changed)
    missing = [f for f in changed if old.get(f) is None or new.get(f) is None]
    flips = []
    crlf_both = []
    for f in changed:
        o, n = old[f], new[f]
        if o is None or n is None:
            continue
        co, cn = o.count(b"\r"), n.count(b"\r")
        if (co == 0) != (cn == 0):
            flips.append((f, co, cn))
        if co and cn:
            crlf_both.append("%s (%d->%d)" % (f, co, cn))
    print("changed files:", len(changed))
    print("missing (added/removed):", missing)
    print("EOL flips:", len(flips))
    for f, co, cn in flips:
        print("  FLIP %s  old_cr=%d new_cr=%d" % (f, co, cn))
    print("CRLF-blob files (both sides):", crlf_both)
    # worktree 行尾复查（i/ 与 w/ 不一致即潜在的隐形归一化）
    eol = subprocess.run(["git", "ls-files", "--eol", "-z"], cwd=ROOT,
                         capture_output=True, check=True).stdout
    blocks = eol.split(b"\0")
    weird = []
    changed_set = set(changed)
    for b in blocks:
        if not b:
            continue
        meta, _, path = b.partition(b"\t")
        path_s = path.decode("utf-8", "replace")
        if path_s not in changed_set:
            continue
        cols = meta.decode("utf-8", "replace").split()
        if len(cols) < 2:
            continue
        i_eol, w_eol = cols[0], cols[1]
        if w_eol == "w/mixed" or (i_eol == "i/crlf" and w_eol != "w/crlf") \
                or (i_eol == "i/lf" and w_eol not in ("w/crlf", "w/lf")):
            weird.append("%s %s %s" % (path_s, i_eol, w_eol))
    print("worktree EOL anomalies:", weird or "none")


if __name__ == "__main__":
    sys.exit(main())
