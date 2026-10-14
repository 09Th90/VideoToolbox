# -*- coding: utf-8 -*-
# @version 2.2.5
r"""把官方 VideoCaptioner 新版的两类实现套用到内置引擎（幂等，可重复执行）。

来源：E:\\VideoCaptioner（官方安装版）。相关内容已归档进本仓库 docs\\ 下，
本脚本负责覆盖到 tools\\python 的 site-packages：

  docs\\vc_prompts_official\\*.md   → videocaptioner\\core\\prompts\\<类>\\<名>.md
  docs\\vc_translate_impl\\*.py    → videocaptioner\\core\\translate\\<名>.py

为什么要脚本：site-packages 属于运行时依赖，重装 tools\\python 会丢失改动；
「归档 + 一键套用」保证改动可复现。覆盖前自动备份现状到
data\\tmp\\vc_official_backup_<时间戳>\\。

用法（在 src 目录）：
    python apply_vc_official.py [--check]
    python apply_vc_official.py --engine-root C:\bld\qt_build\Lib\site-packages\videocaptioner
  --check        只对比不写入，打印将要变化的文件。
  --engine-root  目标引擎包目录；默认 tools\python\Lib\site-packages\videocaptioner。

⚠️ v1.15.1：本机存在**两份互不相干的引擎副本**——
    ① 运行副本 tools\python\Lib\site-packages\videocaptioner（源码模式 / 随 iss 分发）
    ② 打包副本 <打包环境>\Lib\site-packages\videocaptioner（PyInstaller 解释器里的那份）
   exe 内嵌的引擎代码取自**打包副本**（spec 的 collect_submodules/collect_data_files
   都按打包解释器的 sys.path 收集），所以只套用运行副本时，引擎侧的修复只在源码
   模式生效、**进不了安装包**（表现为「改了 bug，装完还是老样子」）。
   打包前必须对打包环境再跑一次本脚本，例如：
    python src\apply_vc_official.py --engine-root C:\bld\qt_build\Lib\site-packages\videocaptioner
   同理，qfluentwidgets 等被就地打补丁的第三方包也要保持两边一致。
"""
import argparse
import hashlib
import os
import shutil
import time

HERE = os.path.dirname(os.path.abspath(__file__))
#: 脚本位于 <仓库根>/scripts/dev/，tools/ 与 docs/ 在仓库根下
ROOT = os.path.dirname(os.path.dirname(HERE))
#: 默认目标：运行副本（tools\python）。用 --engine-root 指向打包副本。
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
#: 引擎 translate 对应文件的**本地补丁**（翻译器本体已迁至 src/engine_translate.py）
#:
#: v1.20.0 变更（P1 翻译接缝接管）：原先此处从 ``docs/vc_translate_impl/``
#: 回写 6 个第三方文件。其中 5 个是**翻译器实现**（bing/google/deeplx/base/
#: llm_translator），已由 ``src/engine_translate.py``（自研：端点/协议/错误标记
#: 按可观察行为重写）接管 ⇒ 从回写表中**退役**。
#:
#: ⚠ 诚实边界：``subtitle_thread.py`` **仍需保留**在回写表中。它是引擎
#: ``ui/thread/subtitle_thread.py`` 的**本地补丁版**（取消修复 stop() 补停
#: 翻译器线程池 + 说话人提示词注入），属第三方源码的改写件——彻底退役需要
#: 把整个字幕线程重写为自研（P2/P3 范围，非 P1）。本项目**如实**把它单列到
#: ``TRANSLATORS_REMAINING``，使「还剩几处第三方源码」一眼可见，而不是
#: 藏在已退役的表里。
#:
#: ``docs/vc_prompts_official/``（提示词 .md）**保留**：那是提示词文本数据、
#: 不是源码，属资源归档；LLM 翻译/反思翻译仍从那里套用。
TRANSLATORS = {}

#: 仍持有第三方源码的引擎文件（P2/P3 待自研替换）。每项：
#: 归档文件名 → 引擎内相对路径。
TRANSLATORS_REMAINING = {
    # 引擎 ui/thread/subtitle_thread.py 的本地补丁版（P2/P3 重写为自研）
    "subtitle_thread.py": "ui/thread/subtitle_thread.py",
}


def _sha(path):
    with open(path, "rb") as f:
        return hashlib.sha1(f.read()).hexdigest()[:10]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只对比不写入")
    ap.add_argument("--engine-root", default=ENGINE_SP,
                    help="目标引擎包目录（默认 tools\\python 运行副本；"
                         "打包前请指向打包环境的 videocaptioner）")
    args = ap.parse_args()

    engine_sp = os.path.abspath(os.path.expanduser(args.engine_root))
    if not os.path.isdir(engine_sp):
        print(f"[错误] 目标引擎目录不存在：{engine_sp}")
        return 2
    print(f"目标引擎：{engine_sp}")

    jobs = []
    for src_dir, table, tag in (("vc_prompts_official", PROMPTS, "提示词"),
                                ("vc_translate_impl", TRANSLATORS_REMAINING,
                                 "翻译器")):
        base = os.path.join(ROOT, "docs", src_dir)
        for fname, rel in table.items():
            src = os.path.join(base, fname)
            dst = os.path.join(engine_sp, *rel.split("/"))
            if not os.path.isfile(src):
                print(f"[{tag}] 缺少归档文件：{src}")
                continue
            same = os.path.isfile(dst) and _sha(src) == _sha(dst)
            jobs.append((tag, src, dst, rel, same))

    pending = [j for j in jobs if not j[4]]
    for tag, src, dst, rel, same in jobs:
        mark = "已是官方版" if same else ("将覆盖" if args.check else "已覆盖")
        print(f"[{tag}] {rel:<44} {mark}")

    # 透明披露：仍持有第三方源码的归档文件（P2/P3 待自研替换）。
    # 不静默删除——「还剩几处」必须是可见事实，供 P5 清理与 P6 口径统一引用。
    remaining = sorted(TRANSLATORS_REMAINING)
    if remaining:
        print(f"\n[合规] 仍归档 {len(remaining)} 个第三方源码改写件（P2/P3 待替换）："
              f"{', '.join(remaining)}")
        print("       翻译器本体已由 src/engine_translate.py 自研接管；"
              "此处仅为引擎字幕线程补丁，待 P2/P3 重写。")

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

    # 清掉被覆盖文件对应的 __pycache__ 字节码：源码模式下 Python 仍可能按旧 pyc
    # 的时间戳/大小判定命中缓存，出现「文件已换、行为没变」。
    purged = 0
    for _tag, _src, dst, _rel, _same in pending:
        cy = os.path.join(os.path.dirname(dst), "__pycache__")
        if not os.path.isdir(cy):
            continue
        stem = os.path.splitext(os.path.basename(dst))[0]
        for f in os.listdir(cy):
            if f.startswith(stem + ".") and f.endswith(".pyc"):
                try:
                    os.remove(os.path.join(cy, f))
                    purged += 1
                except OSError:
                    pass
    if purged:
        print(f"已清理 {purged} 个过期字节码")
    print("完成。提示词带 LRU 缓存，重启程序后生效。")
    return 0


if __name__ == "__main__":
    sys_exit = main()
    raise SystemExit(sys_exit)
