# -*- coding: utf-8 -*-
"""把官方 VideoCaptioner 新版的两类实现套用到内置引擎（幂等，可重复执行）。

来源：E:\\VideoCaptioner（官方安装版）。相关内容已归档进本仓库 docs\\ 下，
本脚本负责覆盖到 tools\\python 的 site-packages：

  docs\\vc_prompts_official\\*.md   → videocaptioner\\core\\prompts\\<类>\\<名>.md
  docs\\vc_translate_impl\\*.py    → videocaptioner\\core\\translate\\<名>.py

为什么要脚本：site-packages 属于运行时依赖，重装 tools\\python 会丢失改动；
「归档 + 一键套用」保证改动可复现。覆盖前自动备份现状到
data\\tmp\\vc_official_backup_<时间戳>\\。

用法（在 src 目录）：python apply_vc_official.py [--check]
  --check  只对比不写入，打印将要变化的文件。
"""
import argparse
import hashlib
import os
import shutil
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ENGINE_SP = os.path.join(ROOT, "tools", "python", "Lib", "site-packages",
                         "videocaptioner")

#: 官方提示词（docs/vc_prompts_official）→ 引擎 prompts 对应文件
PROMPTS = {
    "translate_standard.md": "core/prompts/translate/standard.md",
    "translate_reflect.md": "core/prompts/translate/reflect.md",
    "translate_single.md": "core/prompts/translate/single.md",
    "optimize_subtitle.md": "core/prompts/optimize/subtitle.md",
    "split_semantic.md": "core/prompts/split/semantic.md",
    "split_sentence.md": "core/prompts/split/sentence.md",
    "analysis_video.md": "core/prompts/analysis/video.md",
}
#: 官方翻译器实现（docs/vc_translate_impl）→ 引擎 translate 对应文件
TRANSLATORS = {
    "google_translator.py": "core/translate/google_translator.py",
    "bing_translator.py": "core/translate/bing_translator.py",
    "deeplx_translator.py": "core/translate/deeplx_translator.py",
    # v1.12.0：base 补丁——失败条目不写缓存（防端点失败结果污染缓存 7 天）
    "base.py": "core/translate/base.py",
    # v1.12.0：LLM 提示词传 target_language.value（枚举对象渲染成字面量）
    "llm_translator.py": "core/translate/llm_translator.py",
    # v1.11.0：字幕线程的「取消」修复（stop() 补停翻译器线程池）
    "subtitle_thread.py": "ui/thread/subtitle_thread.py",
}


def _sha(path):
    with open(path, "rb") as f:
        return hashlib.sha1(f.read()).hexdigest()[:10]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只对比不写入")
    args = ap.parse_args()

    jobs = []
    for src_dir, table, tag in (("vc_prompts_official", PROMPTS, "提示词"),
                                ("vc_translate_impl", TRANSLATORS, "翻译器")):
        base = os.path.join(ROOT, "docs", src_dir)
        for fname, rel in table.items():
            src = os.path.join(base, fname)
            dst = os.path.join(ENGINE_SP, *rel.split("/"))
            if not os.path.isfile(src):
                print(f"[{tag}] 缺少归档文件：{src}")
                continue
            same = os.path.isfile(dst) and _sha(src) == _sha(dst)
            jobs.append((tag, src, dst, rel, same))

    pending = [j for j in jobs if not j[4]]
    for tag, src, dst, rel, same in jobs:
        mark = "已是官方版" if same else ("将覆盖" if args.check else "已覆盖")
        print(f"[{tag}] {rel:<44} {mark}")

    if args.check or not pending:
        print(f"共 {len(jobs)} 项，待套用 {len(pending)} 项。")
        return 0

    backup = os.path.join(ROOT, "data", "tmp",
                          f"vc_official_backup_{time.strftime('%Y%m%d_%H%M%S')}")
    for tag, src, dst, rel, _same in pending:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if os.path.isfile(dst):
            bdst = os.path.join(backup, *rel.split("/"))
            os.makedirs(os.path.dirname(bdst), exist_ok=True)
            shutil.copy2(dst, bdst)
        shutil.copy2(src, dst)
        print(f"[{tag}] 写入 {dst}")
    if any(os.listdir(backup) for _ in [0]) and os.path.isdir(backup):
        print(f"原文件已备份到 {backup}")
    print("完成。提示词带 LRU 缓存，重启程序后生效。")
    return 0


if __name__ == "__main__":
    sys_exit = main()
    raise SystemExit(sys_exit)
