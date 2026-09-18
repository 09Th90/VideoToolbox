# -*- coding: utf-8 -*-
# @version 1.14.1
"""为仓库内**自研的当前版本文件**打版本号标记，并生成《文件版本清单》。

背景（v1.12.1）：仅靠文件名无法判断一份文件属于哪一版——同名不同内容的情况
（例如本地已改但未推送、或线上还是旧版）肉眼看不出来。本脚本做两件事：

  1. **首行打标**：在每个自研当前版本文件的首行插入统一标记行
     `@version <版本>`（按文件类型套用该类型的注释语法），使 `grep @version`
     即可确认任意文件属于哪一版；再次运行时按新版本号**原地改写**，幂等。
  2. **生成清单**：生成 `文件版本清单.md`，逐条列出仓库内**全部**已跟踪文件的
     归类、SHA-1 与大小，用于逐条核对「线上文件 = 当前版本代码」。

不改动的文件（有意为之，改动它们有害）：
  · 第三方 / 合规原件——GPL 许可全文、组件来源声明、上游 prompts 与翻译器实现
    （prompts 会被当作提示词投给 LLM，插入注释会污染提示词）；
  · `history/` 历史归档——本就是早期版本快照，标成当前版本是错的；
  · 运行期数据（学习库、inbox/outbox）与二进制（png/exe）。

用法（在 src 目录）：
    python stamp_versions.py             # 打标 + 生成清单
    python stamp_versions.py --check     # 只报告会改哪些文件
"""
import argparse
import hashlib
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
MANIFEST = "文件版本清单.md"

#: 文件名（无扩展名者）→ 注释语法 (前缀, 后缀)
STYLE_BY_EXT = {
    ".py": ("# ", ""),
    ".spec": ("# ", ""),
    ".ps1": ("# ", ""),
    ".bat": ("rem ", ""),
    ".iss": ("; ", ""),
    ".isl": ("; ", ""),
    ".qs": ("// ", ""),
    ".xml": ("<!-- ", " -->"),
    ".md": ("<!-- ", " -->"),
    ".html": ("<!-- ", " -->"),
    ".htm": ("<!-- ", " -->"),
    ".txt": ("", ""),
    ".gitignore": ("# ", ""),
}
#: 按文件名兜底（无扩展名文件）
STYLE_BY_NAME = {".gitignore": ("# ", "")}

MARKER_RE = re.compile(r"^\s*(?:#|;|//|rem\s+|<!--)?\s*@version\s+(\S+?)\s*(?:-->)?\s*$",
                       re.IGNORECASE)

#: 第三方 / 合规原件——原文保持，不得追加标记
THIRD_PARTY = {
    "build/Languages/ChineseSimplified.isl",
    "docs/VideoCaptioner_GPL-3.0.txt",
    "docs/VideoCaptioner_组件来源.txt",
}
THIRD_PARTY_PREFIX = ("docs/vc_prompts_official/", "docs/vc_translate_impl/")

#: 历史归档 / 早期版本留档——不属当前版本
HISTORY_PREFIX = ("history/",)
HISTORY_FILES = {
    "docs/开发报告书_v1.10.8_校准知识中心化同步.md",
    "build/VideoToolbox_Setup_v1.12.0.sha256.txt",
}

#: 运行期数据与占位文件——不入版本管理
RUNTIME_FILES = {
    "subtitle_learned_kb.json",
    "inbox/.gitkeep",
    "outbox/.gitkeep",
}
RUNTIME_PREFIX = ("inbox/", "outbox/")

#: 二进制 / 无注释语法的自研文件——属于当前版本但无法打标
NO_MARKER_EXT = {".png", ".jpg", ".jpeg", ".exe", ".7z", ".ico", ".zip"}
NO_MARKER_REASON = {
    ".png": "二进制（界面预览图）",
    ".jpg": "二进制",
    ".jpeg": "二进制",
    ".exe": "二进制（可执行文件）",
    ".7z": "二进制（压缩包）",
    ".json": "JSON 无注释语法",
}


def current_version():
    p = os.path.join(ROOT, "src", "video_toolbox_qt.py")
    m = re.search(r'VERSION\s*=\s*"([\d.]+)"', open(p, encoding="utf-8").read())
    if not m:
        raise SystemExit("无法从 src/video_toolbox_qt.py 读取当前版本")
    return m.group(1)


def tracked_files():
    import subprocess
    r = subprocess.run(["git", "-c", "core.quotepath=false", "ls-files"],
                       cwd=ROOT, capture_output=True)
    return [l for l in r.stdout.decode("utf-8", "replace").splitlines() if l.strip()]


def style_for(rel):
    _, ext = os.path.splitext(rel)
    if ext.lower() in STYLE_BY_EXT:
        return STYLE_BY_EXT[ext.lower()]
    if rel in STYLE_BY_NAME:
        return STYLE_BY_NAME[rel]
    return None


def marker_line(rel, version):
    st = style_for(rel)
    if st is None:
        return None
    pre, suf = st
    return "%s@version %s%s" % (pre, version, suf)


def insert_index(lines, rel):
    """返回标记行应插入的下标：跳过 shebang / 编码声明 / XML 声明 / @echo off。"""
    idx = 0
    if lines and lines[0].startswith("#!"):
        idx = 1
    if idx < len(lines) and re.match(r"^#.*coding[:=]", lines[idx]):
        idx += 1
    elif idx == 0 and len(lines) > 1 and re.match(r"^#.*coding[:=]", lines[1]):
        idx = 2
    if idx == 0 and lines and lines[0].lstrip().startswith("<?xml"):
        idx = 1
    if rel.lower().endswith(".bat") and lines and \
            lines[0].strip().lower().startswith("@echo off"):
        idx = 1
    return idx


def stamp_one(rel, version, check=False):
    """返回 (状态, 说明)。状态: 'ok' 已改 / 'same' 已是最新 / 'skip' 不可打标。"""
    path = os.path.join(ROOT, *rel.split("/"))
    want = marker_line(rel, version)
    if want is None:
        _, ext = os.path.splitext(rel)
        return "skip", NO_MARKER_REASON.get(ext.lower(), "无注释语法")
    raw = open(path, "rb").read()
    text = raw.decode("utf-8")
    lines = text.splitlines(keepends=True)
    eol = "\r\n" if b"\r\n" in raw else "\n"

    # 前 8 行内已有标记 → 原地改写
    for i, l in enumerate(lines[:8]):
        m = MARKER_RE.match(l.rstrip("\r\n"))
        if m:
            if m.group(1) == version:
                return "same", "已是 @version %s" % version
            nl = lines[i].endswith("\r\n") and "\r\n" or \
                (lines[i].endswith("\n") and "\n" or eol)
            new = want + nl
            if check:
                return "ok", "将改写第 %d 行：%s → %s" % (
                    i + 1, l.rstrip("\r\n"), want)
            lines[i] = new
            open(path, "w", encoding="utf-8", newline="").write("".join(lines))
            return "ok", "改写第 %d 行 → %s" % (i + 1, want)

    idx = insert_index(lines, rel)
    if check:
        return "ok", "将在第 %d 行插入： %s" % (idx + 1, want)
    lines.insert(idx, want + eol)
    open(path, "w", encoding="utf-8", newline="").write("".join(lines))
    return "ok", "已插入第 %d 行： %s" % (idx + 1, want)


#: 刻意不打标的文件——清单「版本标记」列显示的归类理由
SKIP_REASON = {
    "第三方/合规原件": "不适用：第三方/合规原件，刻意保持逐字节原样",
    "历史归档": "不适用：历史归档（早期版本快照，非当前版本）",
    "运行期数据/占位": "不适用：运行期生成，不入版本管理",
}


def classify(rel):
    """返回 (类别, 是否应为当前版本代码)。"""
    if rel.startswith(HISTORY_PREFIX) or rel in HISTORY_FILES:
        return "历史归档", False
    if rel in THIRD_PARTY or rel.startswith(THIRD_PARTY_PREFIX):
        return "第三方/合规原件", False
    if rel in RUNTIME_FILES or rel.startswith(RUNTIME_PREFIX):
        return "运行期数据/占位", False
    return "当前版本", True


def sha1(path):
    h = hashlib.sha1()
    with open(path, "rb") as fp:
        for chunk in iter(lambda: fp.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git_blob_hashes(rels):
    """批量算 **git blob SHA-1**（经 filters 归一化），与 GitHub tree API 的 sha 同口径。

    普通文件 SHA-1 与 git blob SHA-1 **不相等**（后者对 `blob <len>\\0<内容>` 计算，
    且 `core.autocrlf=true` 下会把 CRLF 归一化为 LF）。清单要能直接和 GitHub 上
    同名文件的 sha 对上，就必须用这个口径——否则逐条比对会全部对不上。
    """
    import subprocess
    out = {}
    CH = 200
    for i in range(0, len(rels), CH):
        batch = rels[i:i + CH]
        inp = "\n".join(os.path.join(ROOT, *r.split("/")) for r in batch) + "\n"
        try:
            r = subprocess.run(["git", "-c", "core.quotepath=false",
                                "hash-object", "--stdin-paths"],
                               cwd=ROOT, input=inp.encode("utf-8"),
                               capture_output=True)
            hashes = r.stdout.decode("utf-8", "replace").split()
            if len(hashes) != len(batch):
                raise RuntimeError("数量不符 %d != %d" % (len(hashes), len(batch)))
            out.update(zip(batch, hashes))
        except Exception as e:  # noqa: BLE001 —— 无 git 环境时退回普通 SHA-1
            print("   [warn] git hash-object 不可用（%s），退回普通 SHA-1" % e)
            for rel in batch:
                out[rel] = sha1(os.path.join(ROOT, *rel.split("/")))
    return out


def build_manifest(version, stamp_results):
    rows = {"当前版本": [], "第三方/合规原件": [], "历史归档": [], "运行期数据/占位": []}
    rels = [r for r in sorted(tracked_files()) if r != MANIFEST]
    blobs = git_blob_hashes(rels)
    for rel in rels:
        path = os.path.join(ROOT, *rel.split("/"))
        if not os.path.isfile(path):
            rows["运行期数据/占位"].append((rel, "（工作区缺失）", "-", "-"))
            continue
        cat, _ = classify(rel)
        if rel in stamp_results:
            st, note = stamp_results[rel]
            mark = "已打标" if st in ("ok", "same") else "未打标：" + note
        else:
            # 刻意跳过的文件：给出归类理由，避免出现空的「未打标：」
            mark = SKIP_REASON.get(cat, "—")
        rows[cat].append((rel, mark, blobs.get(rel, "-"),
                          str(os.path.getsize(path))))

    out = []
    out.append("# 文件版本清单")
    out.append("")
    out.append("- **当前版本**：v%s" % version)
    out.append("- **生成方式**：`cd src && python stamp_versions.py`（自动生成，请勿手工编辑）")
    out.append("- **SHA-1 口径**：下表列出的是 **git blob SHA-1**（经 git filters 归一化，"
               "`core.autocrlf=true` 下 CRLF 已转 LF），与 GitHub 上同名文件的 blob sha "
               "**同口径、可直接逐条比对**——一致即证明内容完全相同。"
               "注意普通文件 SHA-1（`sha1sum` 那种）与此**不相等**，不可拿来对比。")
    out.append("- **另一种核验方式**：每个自研当前版本文件首行带 `@version %s` 标记，"
               "`grep -rn \"@version\" .` 可一眼确认某文件属于哪一版。" % version)
    out.append("")
    out.append("分类说明：**当前版本**＝构成 v%s 的自研代码/脚本/配置/文档；"
               "**第三方/合规原件**＝上游或法律原件，刻意保持逐字节原样"
               "（prompts 会被当提示词投给 LLM，插注释会污染）；"
               "**历史归档**＝早期版本快照，本就不属当前版本；"
               "**运行期数据/占位**＝程序运行时生成，不入版本管理。" % version)
    out.append("")
    order = ["当前版本", "第三方/合规原件", "历史归档", "运行期数据/占位"]
    total = 0
    for cat in order:
        items = rows[cat]
        total += len(items)
        out.append("## %s（%d 个）" % (cat, len(items)))
        out.append("")
        out.append("| # | 文件 | 版本标记 | git blob SHA-1（= GitHub） | 字节 |")
        out.append("|---|------|----------|---------------------------|------|")
        for i, (rel, mark, h, sz) in enumerate(items, 1):
            out.append("| %d | `%s` | %s | `%s` | %s |" % (i, rel, mark, h, sz))
        out.append("")
    out.append("---")
    out.append("")
    out.append("合计 **%d** 个已跟踪文件（不含本清单自身）。" % total)
    open(os.path.join(ROOT, MANIFEST), "w", encoding="utf-8", newline="\n").write(
        "\n".join(out) + "\n")
    return total, {k: len(v) for k, v in rows.items()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只报告，不写入")
    ap.add_argument("--version", help="覆盖版本号（默认读源码里的 VERSION）")
    args = ap.parse_args()
    version = args.version or current_version()
    print("当前版本：v%s%s" % (version, "（--check 空跑）" if args.check else ""))

    targets, skipped, results = [], [], {}
    for rel in sorted(tracked_files()):
        cat, is_current = classify(rel)
        if rel == MANIFEST:
            continue
        path = os.path.join(ROOT, *rel.split("/"))
        if not os.path.isfile(path):
            continue
        if not is_current:
            skipped.append((rel, cat))
            continue
        targets.append(rel)

    print("\n== 打标（当前版本自研文件 %d 个）==" % len(targets))
    n_ok = n_same = n_skip = 0
    for rel in targets:
        st, note = stamp_one(rel, version, check=args.check)
        results[rel] = (st, note)
        if st == "ok":
            n_ok += 1
            print("   [改] %-58s %s" % (rel, note))
        elif st == "same":
            n_same += 1
        else:
            n_skip += 1
            print("   [未打标] %-54s %s" % (rel, note))
    print("   已修改 %d / 已最新 %d / 未打标 %d" % (n_ok, n_same, n_skip))

    if skipped:
        print("\n== 刻意不打标（%d 个）==" % len(skipped))
        bycat = {}
        for rel, cat in skipped:
            bycat.setdefault(cat, []).append(rel)
        for cat, items in bycat.items():
            print("   %s：%d 个" % (cat, len(items)))

    if args.check:
        print("\n（--check 模式，未写入；也未生成清单）")
        return 0

    total, counts = build_manifest(version, results)
    print("\n== 清单已生成 ==")
    print("   %s：共 %d 个已跟踪文件" % (MANIFEST, total))
    for k, v in counts.items():
        print("     %-14s %d" % (k, v))
    print("\n提示：发布前请确认清单里的「当前版本」条目都带 @version %s 标记。" % version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
