# @version 2.4.0
"""对象级校准 —— 并行开发包（P0 身份治理 + P1 对象索引）。

设计约束（并行开发期）：

* **只读** ``subtitle_calib_merged``：import 它取数据，不 patch、不回写、不改一行源码；
* 不进入打包口径（不在 ``src/`` 下），不触发 ``check_deps.py`` / spec 变更；
* 全部能力可在命令行独立运行，验证通过后再谈合并进主脚本。

模块分工：

    spec     扁平表 + ENTITIES -> 唯一 EntitySpec 集合（去重、补 modes、分离别名候选）
    index    按模式构建 Aho-Corasick 自动机（关键词匹配、最长优先、候选预筛）
    shadow   影子双跑：索引预筛与原引擎逐字节比对；单遍语义与串行语义差异量化
    lint     对象级体检（重复身份 / 空壳 / 长键序 / 一词多目标 / 级联）
    cli      子命令入口
"""

__all__ = ["spec", "index", "shadow", "lint"]
__version__ = "0.1.0-parallel"
