<!-- @version 3.1.0 -->
# 视频工具箱 v3.0.0 变更说明（2026-11-15）

**主题：全量功能解耦 + 模块独立文件夹。** 架构级升级，对外接口与数据布局保持兼容。

## 架构

- **功能注册表**（`src/features/_registry.py`，纯标准库）：16 个功能各自独立成包
  （feature.py 清单 / cli.py 子命令 / page.py 页面），pkgutil 自动发现、逐包
  try/except 隔离——**单个功能损坏或缺失只标记该功能不可用，不影响程序启动**。
  `registry().service(fid, name)` 惰性解析跨功能服务；`probe(fid)` 零副作用探活。
- **GUI 壳层**（`src/vt_app/`）：boot/widgets/scheduler/lazy_shell/engine_ui/
  win_resize/bus + 首页/设置页/主窗口。入口 `video_toolbox_qt.py` 由 12540 行
  收薄至 657 行（VERSION 锚点/main()/MSVC 修复/兼容再导出）。
- **消息总线**：旧 `_dispatch` 路由表整体删除；页面按前缀自订阅（dl_/cal_/lib_/
  sp_/pipe_state），主线程 120ms 泵、每轮 ≤200 条。
- **新增功能三步**：复制 `features/_template/` → 改清单 → 完成。CLI 子命令自动
  装配、GUI 页自动挂载、打包自动收集，无需改入口/主窗口/打包清单。

## 模块独立文件夹（28 个实现模块归位）

- 功能专属实现全部迁入 `src/features/<id>/`：split / translate / compose /
  transcribe / subtitle_edit / library / pipeline / download / calibrate /
  voiceprint / automation / harness。
- **硬搬迁、无转发壳**：引用一律 `features.<id>.<模块>` 单一路径，杜绝双模块
  实例（保护 selftest monkeypatch 与 calib_merge_core._log 单例注入）。
- **src 顶层只留**：入口三件（video_toolbox_qt/agent_cli/video_toolbox facade）、
  壳层三件（ui_theme/qt_compat/vt_update_check）、共享接缝六件（engine_asr_data/
  engine_entities/engine_cache/engine_paths/engine_task_factory/subtitle_editor_core）。
- 路径锚点硬化为 AGENTS.md 标记查找（≤6 级 + 新深度回落）；独立 CLI 保留：
  `speaker_voiceprint.py list/enroll/...`、`voiceprint_sync.py sync/status`、
  `bili_auto_submit.py --probe/...`（新路径见说明书 §4）。
- 位置约定入文档：说明书 §2.7、`_template/README`、`features/__init__`、
  `core/__init__` 依赖规则（跨层例外：download/calibrate/asr/shared）。

## 质量与修复

- GUI 自检引擎内嵌组加 60s 轮询保护 + 超时 SKIP（不伪装通过）：**172 PASS / 0 FAIL**。
- vt_ui_golden 基线重采集 + 三处对照缺陷修复（豁免索引/主题钉 LIGHT+#009faa/
  属性豁免定性）：**home 51/51、setting 60/60，OVERALL IDENTICAL**。
- 打包：spec `collect_submodules('features'/'vt_app')` + iss `src\features\*`
  recursesubdirs 自动收集；**bili_auto_submit 安装版分发缺口随迁补齐**。
- 冒烟 J 组改递归 glob，源码语法覆盖 253 个文件全过。

## 兼容性

- `video_toolbox.py` facade **162 个公开符号零漂移**；agent_cli 子命令与 JSON
  信封不变（21/21 自检过）；数据目录布局不变，无需迁移。
- 校准铁律不变：序号/时间轴/空行/换行/BOM 原样，只动文字。

## 门禁汇总（发布前全绿）

features 17/0 · core_api 162 · GUI 172/0 · golden IDENTICAL · agent_cli 21/0 ·
13 个功能专属自检全过 · iss 42 · doc drift 8/8 · qss 71/71 · 单例探针 OK ·
独立 CLI 三冒烟 OK。