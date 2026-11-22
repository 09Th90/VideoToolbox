<!-- @version 3.2.5 -->
# 视频工具箱 v3.1.4 变更说明（2026-11-20）

**主题：修「设置页只剩背景图」——发布清单漏发 Jev 客户端致整页构建中断；
安装包同步缺口一并补齐，门禁补盲防复发。**
延续 v3.1.3：全部改动走我方源码与发布链，引擎 site-packages 本体零改动。

## 修复 · 设置页整页空白（v3.1.3 安装版报障）

根因（安装版 logs\crash.log 2026-11-20 17:28:33 主线程 traceback）：
`SettingsPage.__init__ → _build_ai_card → _sync_plan_warn →
core/shared/decision.py decision_mod()` 按 `TOOLS_DIR` 动态加载
`tools\decision_client.py`，而该文件**从未进任何发布清单**（iss / 在线
tools 包 / IFW COMPONENTS 三处一致地漏），冻结态抛 FileNotFoundError；
`_LazyPageShell.ensure()` 的 builder 中断 → 真身未入壳布局 → 壳被背景
绘制覆盖＝整页只剩自定义背景图。源码模式因 TOOLS_DIR 指向仓库 tools 而
不复现，故此前门禁全绿未揪出。

- `settings_page.py`：`decision_mod()` 调用加 try/except 降级（与
  `ai_plan_risk` 同口径）；缺失时 Jev 提示「客户端缺失或加载失败…不会
  调用；重装或在线更新可补齐」，**绝不阻断建页**。
- `lazy_shell.py`：builder 抛异常时落盘 traceback（crash.log「页面构建」
  段）并挂占位控件明示错误与日志位置——对齐自动化页占位模式，杜绝任何
  单点失败再变成「静默空白页」。
- 三处发布清单同步补 `tools/decision_client.py`：`packaging/视频工具箱.iss`、
  `packaging/online_release/build_online_release.py` PACKAGES["tools"]、
  `packaging/installer_src/build_online_installer.py` COMPONENTS。

## 修复 · 安装包同步缺口（离线/在线口径不一致）

- iss 补 `tools/download_open_source_deps.py`（在线 tools 包早有、离线漏）
  与五个顶层共享接缝源码副本 `src/engine_{asr_data,cache,entities,paths,
  task_factory}.py`（离线安装后曾停留旧版，与在线 code 包口径不一致）。
- `check_install_sync.py` 补盲：通配 Source 按 Excludes 展开 os.walk 全量
  比对（此前只比 31 个单文件，_internal/src 子目录全盲＝31/31 假绿），
  新增 exe 与 dist 产物逐字节比对。本轮对 v3.1.3 安装目录跑出 905 对比、
  精确报出 decision_client 缺失与 8 处陈旧＝缺口实证。
- `check_iss_sources.py` 新增动态加载扫描：src 全量 `TOOLS_DIR, "<字面量>"`
  join 的 .py 文件断言三处清单同步声明（AST import 闭包查不到
  spec_from_file_location 这类运行时路径加载，正是本次漏发机制）。

## 回归门禁

- 新自检 `_selftest_settings_resilience.py` 8/8：缺 Jev 客户端时设置页仍
  完整构建（12 项布局）+ 降级文案；builder 炸 → 占位控件 + crash.log
  「页面构建」段 + ensure 幂等。
- `check_iss_sources` 绿（动态加载字面量 2 个三处同步）；`_selftest_gui`、
  `_selftest_online_setup/xval`、`_selftest_self_update` 18/18、
  `_selftest_update_pending` 16/16、`_selftest_drop_routing` 22/22 全过。
- 已知基线（不修）：`_selftest_vt_engine` C 组 `FasterWhisperModelEnum`
  差 `small.en`（引擎 site-packages 零改动口径）。

## 升级说明

- v3.1.3 及更早用户经「检查更新」或在线安装器升级即可补齐
  `tools/decision_client.py`（在线 tools 包本轮已含）；设置页随即恢复。
- 离线安装包 `VideoToolbox_Setup_v3.1.4.exe` 本轮仅本地留存，不上传 GitHub。
- 即便未来再漏可选组件，设置页也只会降级提示 Jev 不可用，不会整页空白；
  任何惰性页构建失败都会显示占位错误页并在 crash.log 留堆栈。