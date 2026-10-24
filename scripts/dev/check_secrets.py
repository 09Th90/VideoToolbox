# -*- coding: utf-8 -*-
# @version 2.6.0
"""仓库密钥扫描器（2026-10-22 安全整改）。

背景：2026-10-15 提交 ``8f82721`` 把设置页快照里的两把有效 API Key 带进了
public 仓库，暴露 6 天半。GitHub 自带的 secret scanning 只认各厂商的
**公开格式**，对 ``sk-sp-`` 这类私有前缀不告警（``non_provider_patterns``
当时是关的），所以本地/CI 必须有一道自己的门禁。

三种模式：

    python scripts/dev/check_secrets.py              # 扫工作区已跟踪文件
    python scripts/dev/check_secrets.py --staged     # 只扫暂存区（pre-commit）
    python scripts/dev/check_secrets.py --all        # 扫全部历史 blob（pre-push/审计）
    python scripts/dev/check_secrets.py --all --include-unreachable
                                                     # 连孤儿/悬空对象一起扫

退出码：0 = 干净；1 = 命中；2 = 用法错误。

设计约束：
  · 正则与 ``vt_ui_golden.py`` 的 ``SECRET_PATTERNS`` **同源**（直接 import），
    避免两处规则漂移。
  · 输出**只打脱敏值**（前 8 位 + 后 4 位 + 长度），绝不回显明文——否则
    扫描器自己就成了新的泄露点。
  · 白名单只放**确认是假值**的串（测试常量、文档占位符），不做模糊放行。
"""
import argparse
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))


def _load_patterns():
    """从 vt_ui_golden.py 取同一份规则（同目录，纯标准库，可安全 import）。"""
    sys.path.insert(0, HERE)
    try:
        import vt_ui_golden as g
        return g.SECRET_PATTERNS, g._SECRET_RE
    finally:
        try:
            sys.path.remove(HERE)
        except ValueError:
            pass


SECRET_PATTERNS, SECRET_RE = _load_patterns()

#: 已确认是**假值**、允许存在的串。加白名单必须在注释里写清出处。
ALLOWLIST = (
    # scripts/dev/_selftest_asr_proto.py:881 —— 协议自检用的哨兵常量，
    # 刻意写得不像真 key，且长度不足以匹配任何 SECRET_PATTERNS。
    "sk-SECRET-must-not-leak",
    # 本文档与审计报告里的脱敏示例（含省略号，正则本就不匹配，列此防放宽规则后误报）。
    "sk-sp-H.DP…-blE",
    "sk-iZXQF3y…fHSO",
)

#: 扫描器自身含规则字面量，跳过以免自我误报。
SELF_SKIP = ("scripts/dev/check_secrets.py",)

#: 只扫文本类扩展名（历史模式用；工作区模式另加二进制嗅探）。
TEXT_EXT = {
    ".py", ".json", ".md", ".txt", ".yaml", ".yml", ".bat", ".spec", ".iss",
    ".js", ".ts", ".html", ".qss", ".ini", ".cfg", ".log", ".xml", ".toml",
    ".env", ".ps1", ".sh", ".jsonl", ".tsv", ".csv", ".gitignore", ".gitattributes",
}

#: 体积上限：超过 8MB 的文本文件跳过（历史里有 90MB 的 7z，不属文本）。
MAX_BYTES = 8 * 1024 * 1024


def _mask(v):
    if len(v) <= 14:
        return "%s(len=%d)" % (v[:4], len(v))
    return "%s...%s(len=%d)" % (v[:8], v[-4:], len(v))


def _is_allowlisted(v):
    return any(a in v for a in ALLOWLIST)


def _scan_text(text, path, hits):
    for m in SECRET_RE.finditer(text):
        v = m.group(0)
        if _is_allowlisted(v):
            continue
        line = text.count("\n", 0, m.start()) + 1
        hits.append((path, line, _mask(v)))


def _norm_path(p):
    return p.replace("\\", "/")


def _git(*args, **kw):
    return subprocess.run(["git", "-C", REPO] + list(args), capture_output=True,
                          text=True, encoding="utf-8", errors="replace", **kw)


def scan_worktree():
    """扫工作区里**已被 git 跟踪**的文件（未跟踪文件不入库，不算泄露面）。"""
    hits = []
    out = _git("ls-files", "-z")
    if out.returncode != 0:
        print("git ls-files 失败:", out.stderr[:300], file=sys.stderr)
        return hits
    for rel in out.stdout.split("\0"):
        if not rel:
            continue
        rel_n = _norm_path(rel)
        if rel_n in SELF_SKIP:
            continue
        ext = os.path.splitext(rel_n)[1].lower()
        if ext not in TEXT_EXT and os.path.basename(rel_n) not in (".gitignore", ".gitattributes"):
            continue
        p = os.path.join(REPO, rel)
        try:
            if os.path.getsize(p) > MAX_BYTES:
                continue
            with open(p, encoding="utf-8", errors="replace") as f:
                _scan_text(f.read(), rel_n, hits)
        except OSError:
            continue
    return hits


def scan_staged():
    """只扫暂存区（pre-commit 用）。"""
    hits = []
    out = _git("diff", "--cached", "--name-only", "--diff-filter=ACM", "-z")
    for rel in out.stdout.split("\0"):
        if not rel:
            continue
        rel_n = _norm_path(rel)
        if rel_n in SELF_SKIP:
            continue
        blob = _git("show", ":%s" % rel)
        if blob.returncode != 0:
            continue
        _scan_text(blob.stdout, rel_n, hits)
    return hits


def scan_all(include_unreachable=False):
    """扫全部历史 blob。"""
    hits = []
    if include_unreachable:
        out = _git("cat-file", "--batch-all-objects",
                   "--batch-check=%(objecttype) %(objectname)")
        pairs = []
        for line in out.stdout.splitlines():
            parts = line.split()
            if len(parts) == 2 and parts[0] == "blob":
                pairs.append((parts[1], "(unreachable)"))
    else:
        out = _git("rev-list", "--all", "--objects")
        pairs = []
        for line in out.stdout.splitlines():
            parts = line.split(" ", 1)
            if len(parts) == 2:
                pairs.append((parts[0], parts[1]))

    # 只保留文本类路径（不可达对象没有路径，一律扫）
    targets = []
    for sha, path in pairs:
        if path != "(unreachable)":
            pn = _norm_path(path)
            if pn in SELF_SKIP:
                continue
            ext = os.path.splitext(pn)[1].lower()
            if ext not in TEXT_EXT and os.path.basename(pn) not in (".gitignore", ".gitattributes"):
                continue
        targets.append((sha, path))

    CHUNK = 400
    for i in range(0, len(targets), CHUNK):
        batch = targets[i:i + CHUNK]
        inp = "".join(sha + "\n" for sha, _ in batch).encode()
        p = subprocess.run(["git", "-C", REPO, "cat-file", "--batch"],
                           input=inp, capture_output=True)
        data = p.stdout
        pos = 0
        for sha, path in batch:
            nl = data.find(b"\n", pos)
            if nl < 0:
                break
            header = data[pos:nl].decode("utf-8", "replace")
            pos = nl + 1
            try:
                size = int(header.split()[-1])
            except (ValueError, IndexError):
                continue
            content = data[pos:pos + size]
            pos += size + 1
            if size > MAX_BYTES:
                continue
            try:
                text = content.decode("utf-8")
            except UnicodeDecodeError:
                continue
            _scan_text(text, "%s@%s" % (_norm_path(path), sha[:8]), hits)
    return hits


def main(argv=None):
    ap = argparse.ArgumentParser(description="仓库密钥扫描器")
    ap.add_argument("--staged", action="store_true", help="只扫暂存区")
    ap.add_argument("--all", action="store_true", help="扫全部历史 blob")
    ap.add_argument("--include-unreachable", action="store_true",
                    help="配合 --all：连不可达对象一起扫")
    args = ap.parse_args(argv)

    if args.staged:
        mode, hits = "staged", scan_staged()
    elif args.all:
        mode = "all"
        hits = scan_all(args.include_unreachable)
    else:
        mode, hits = "worktree", scan_worktree()

    if not hits:
        print("[secrets] %s: clean" % mode)
        return 0

    print("[secrets] %s: %d 处命中" % (mode, len(hits)))
    for path, line, masked in hits:
        print("  %s:%s  %s" % (path, line, masked))
    print("\n如确认是假值，请在 check_secrets.py 的 ALLOWLIST 里加白名单并注明出处。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
