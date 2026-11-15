# 新功能模板（复制即用）

> 本目录以下划线开头，注册表发现器**自动跳过**，不会被当成真实功能。

## 三步新增一个功能

1. 复制本目录为 `src/features/<你的功能名>/`（小写英文，如 `thumbnail`）。
2. 改 `feature.py`：`id` 必须与目录名一致；填 `title/summary/backend/requires/services`；
   有 CLI 子命令就填 `cli=(CliCommand(...),)` 并在 `cli.py` 写 `setup_*` 与 handler；
   有 GUI 页就填 `gui=GuiSpec(...)` 并在 `page.py` 写 `build_page(app)`。
3. 完成。**无需改 agent_cli.py / MainWindow / 打包清单**：
   - CLI 子命令由注册表自动装配；
   - GUI 页由 MainWindow 按 `gui.order` 自动挂载（阶段②起）；
   - 打包侧 spec `collect_submodules('features')` 与 iss `recursesubdirs` 自动收集。

## 硬约束（违反会被 _selftest_features.py 拦下）

- `feature.py` / `cli.py` **模块级禁 import Qt 与重依赖**（后端在 handler 函数体内惰性 import）。
- `page.py` 只经 `vt_app` 基建 + 注册表服务取能力，**禁止反向 import GUI 入口**。
- 功能间互相调用一律 `from features import registry; registry().service("<fid>", "<name>")`，
  禁止跨功能直接 import 后端。
- 后端模块缺失/损坏时，注册表只把本功能标记为不可用，**不得影响程序启动**。
- **实现模块放功能文件夹内**：功能专属后端/引擎/页面一律放本包
  （`src/features/<id>/`），禁止新增 src 顶层域模块；仅共享接缝
  （engine_asr_data/engine_entities/engine_cache/engine_paths/engine_task_factory/
  subtitle_editor_core）留顶层。

## 验证

```bat
tools\python\python.exe scripts\dev\_selftest_features.py
tools\python\python.exe src\agent_cli.py <你的子命令> --help
```