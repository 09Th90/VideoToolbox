<!-- @version 3.3.1 -->
# 视频工具箱 v3 正式程序 UI 更新报告

- 版本：`3.3.2`
- 日期：2026-11-26
- 范围：`src/` 下运行的 PySide6 正式程序（不是 HTML 样例）
- 结论：五批次 UI 迁移已落地；后端、配置 schema、CLI 语义未改；`harness\` 只读未动。

![首页](screenshots-v3/01-首页.png)

## 一、做了什么

### 1. 壳层与设计系统

- `src/ui_theme.py`：浅/深色 token 更新为 v3 值，新增 `bg` / `nav` 与 `UI_METRICS`；保留用户主题色 `#009FAA` 与全局默认 `#45C877`。
- `src/vt_fluent/_theme.py`：`DESIGN_TOKENS` 对齐 v3。
- 新增 `src/vt_app/shell.py`：`ShellTopBar`（品牌、面包屑、窗口按钮）与 `ShellStatusBar`（本机模式、主题、配置、版本）。
- `ShellTopBar` 覆盖原标题栏后可拖动窗口：左键按下走系统 `startSystemMove()`，双击最大化/还原；子标签透明鼠标事件，不抢拖动。
- `MainWindow` 改为覆盖式顶栏 / 状态栏；内容边距 `48 + 26`；导航下限 200px，修复“设置”被底栏遮挡。
- 顶栏色块统一：窗口实底改用 `nav`（浅色 `#FBFCFD` / 深色 `#1A1D21`），内容页 `StackedWidget` 独立铺 `bg`（`#F2F4F6` / `#14171A`），左导航、顶部标题、右侧窗口按钮不再出现灰/白分段。
- 共用 `PageHeader` 仍保留供首页/设置使用；2026-11-26 起全部功能页移除页头，只留顶栏面包屑，`ScrollPage(show_header=False)` 不再生成标题和说明。`StackedWidget` 外框线改为 `border:none`，页面内容不再有左上角框线。
- 页面背景可读性雾化随背景遮罩联动：0% 完全不加雾化（原图直出），0→50% 线性渐入，50% 后保持原强度；浅色 `rgba(247,249,250,180)`、深色 `rgba(14,17,20,150)`。
- 遮罩语义纠正（2026-11-25）：`section_dim_card_fill()` 从“反向透明度”改为“直接不透明度”——0 = alpha 0 全透明，100 = 完全不透明；背景遮罩 0% 时不再叠加任何固定雾化。两张滑杆上限由 90 提到 100，设置页“板块遮罩”更名“卡片不透明度”，0% 实测可见背景原图。

### 2. 设置：6 块入口 + 6 个二级页

- 设置首页由长列表改为 3×2 六块入口：全局 AI、ASR 语音识别、字幕引擎与校准、下载与存储、界面与外观、更新与关于。
- 点卡片进入独立二级页，左上“← 返回设置”，顶栏面包屑同步；原 `SettingsPage` 的 `sp.*` 属性全部保留，旧代码引用不破。
- 分组映射：
  - 全局 AI → `ai`
  - ASR → `asr`
  - 字幕引擎与校准 → `subtitle`
  - 下载与存储 → `download`
  - 界面与外观 → `appearance`
  - 更新与关于 → `maintenance`
- 外观页两张遮罩滑杆即时生效，当前配置 50% / 50%。语义已纠正为“数值即不透明/压暗强度”：0% 真正全透明，100% 完全压暗或实色；滑杆范围同步改为 0–100%，原“板块遮罩”更名为“卡片不透明度”。
- 修复 `showEvent` 会把刚打开的二级页重置回入口的问题，新增 `_detail_pending` 30ms 保护。
- 设置入口“配置分区”、脚注改为随主题重刷的局部 QSS，深色下不再“深字压暗底”。

### 3. 视频处理 / 合并 / 切片 / 视频库

- 视频下载：移除页头，三段固定切换条上移；原四张卡合并为「任务输入」单层分区（链接、保存位置、画质检测、字幕开关、进度、加入队列）。
- 并行任务表标题行右侧的「下载并发上限」改为 24px 标签 + 150px 数值框，值、上下箭头完整可见，不再被表头裁切。
- 画质列表加 `QualityList` 主题 QSS 与空态占位；检测失败也回占位，不再是一块空白。
- 并行任务表最小高度压缩、日志 110；任务输入分区标题行右侧放暂停/取消与并发数。
- 音画合并：二级“自动配对 / 手动合并”固定宽 360 左对齐；输入/输出目录改单行；去掉多余顶部说明。
- 视频切片：去掉顶部说明，压缩间距；三段标题随分段同步（视频下载 / 音画合并 / 视频切片）。
- 视频库：`CARD_W=286 / THUMB_W=260 / THUMB_H=146`，1440 宽 4 列；文件名改两行完整显示（34px 固定高），不再尾部省略。
- 真实目录 `D:\原片` 扫描：7 个视频、18.95 GB（截图时点的真实数量）。

### 4. 字幕处理 / 字幕编辑

- 字幕处理页移除页头；外层 `UICard` 已去掉，第三方引擎根卡片保留为唯一界面层，宿主白底由 `_paint_engine_host()` 跟随主题。
- 引擎宿主套 `QScrollArea`：窗口缩到 880×620 时出现滚动条，而不是被引擎最小高度钳到 700；窗口缩放回归探针已恢复全过。
- 字幕编辑页 `video_host` 加 `WA_StyledBackground`，视频预览区真正黑底；媒体条、时间轴、属性面板保留原控件与交互。
- 设置-字幕引擎页保留第三方原表单，只做外层页头/返回、扁平分区与文字可读性修正。

### 5. 流水线 / AI 托管 / 自动化 / 实时字幕

- 流水线移除页头；无任务时新增「阶段顺序」单层分区，按真实 `STAGES` 列出：下载完成 → 智能合并 → 语音转录 → 字幕翻译 → 字幕校准 → 二次校准 → 发布素材 → 成品输出。
- `PAGE_TITLES` 补 `PipelinePage`，修复流水线面包屑一直显示“首页”。
- AI 托管：内容边距 `22/14`，移除页头；任务输入/状态/输出改为三段单层分区。
- 自动化：移除 `PageHeader`；长说明改短句 + tooltip；模板采集状态改三行短文案，窗口截图提示可换行。
- 实时字幕：`ScrollPage` 使用 `show_header=False`，采集/运行状态/字幕流/日志改为单层分区，不再显示重复的标题与说明。

### 6. 长文案可读性清理

- 全局 AI：端点说明改短句，订阅端点细节放 tooltip；决策模型说明缩短。
- 字幕引擎：校准提示缩短，完整解释放 tooltip。
- 更新与关于：程序更新说明缩短，完整升降级规则放 tooltip。
- 下载与存储：旧引擎数据提示缩短，旧路径列表放 tooltip；cookies 占位文案缩短。
- 自动化：PrintWindow 说明、模板采集状态改短句；缺失模板清单放 tooltip。

### 7. 验收反馈修复（2026-11-26）

- **功能页去页头**：字幕处理、实时字幕、视频库、流水线、字幕编辑、视频处理（下载/合并/切片）、AI 托管、自动化不再显示页内大标题和灰色说明；页面身份由顶栏面包屑承担。`ScrollPage` 新增 `show_header` 开关，`show_header=False` 时不创建标题控件，内容顶部边距 16→12。
- **去外框线**：`light.qss` / `dark.qss` 的 `StackedWidget` 由 `border:1px solid` 改为 `border:none`，页面左上角和内容四周不再出现灰色框线。
- **底部状态栏融合**：`ShellStatusBar` 背景改 `t["bg"]`（浅 `#F2F4F6` / 深 `#14171A`），去掉 `border-top`；几何改为 `setGeometry(nav_w, height-26, width-nav_w, 26)`，只占内容区，左侧导航自然延伸到底，不再横跨整窗形成亮带。
- **深色白色块**：`QTableCornerButton` 纳入原生子控件切片，表角不再走默认白 palette；`TableBase` 统一 `setCornerButtonEnabled(False)`，直接隐藏角按钮，深色下表头左上角不留方块。`SmoothScrollDelegate` 自建的两条游离滚动条构造后立即 `hide()`，日志、视频库、设置页左上角不再出现白色原生滚动条块。
- **数字基线**：`SpinBoxBase` 的行编辑保留 `AlignVCenter`，并加 `textMargins(0, 0, 0, 4)`；AI 校准的 400 / 60000 / 1000000 / 65536 与同行标签视觉居中，不再贴框底。
- **下载并发上限**：`max_spin` 固定宽 150、最小高 33；标签改 `BodyLabel`、右对齐、垂直居中，数值与箭头完整显示。

### 8. 去分层结构（2026-11-26）

- 用户以局部裁图指出「页面底色 → 外层卡片 → 内层卡片/控件」的三层同心圆角是错误方向；本轮不再逐页微调卡片皮肤，而是改共用件和页面结构。
- `vt_app/widgets.card()` 从 `UICard` 改为 **扁平分区**：分组标题、说明、行内容，标题下一条 1px 分区线；不再绘制卡片底板、圆角、描边和 hover，输入框/下拉/按钮只保留自己的一层边界。
- 新增 `surface_card()` 承接真正需要“一张卡”的位置：首页 3 张入口卡、视频库缩略图；`UICard` 继续只用于这些单层卡片。
- 新增 `FlatBody`：滚动页内容区铺一块**无圆角、无边框、无阴影**的单层内容面，颜色仍取 `section_dim_card_fill()`，所以「卡片不透明度」滑杆继续生效；它只作页面底，不再形成第二张卡。
- 设置页 10 个二级页 builder 全部走新 `card()`：目录、Cookie、全局 AI、ASR、字幕引擎、下载与存储、界面与外观、更新与关于等不再出现“大卡套小卡”。
- 视频下载/合并/切片/实时字幕/流水线/引擎宿主/自动化/AI 托管的分组壳同步扁平化；`workbench` 外层 `UICard` 去掉，引擎宿主只保留 `QWidget#EngineHost` 一层底色。
- 边界：第三方字幕引擎、qfluentwidgets 原生设置卡、视频库缩略图等**单层卡片保留**；禁止的是卡内再套同类卡片，不是删除所有卡片。第三方引擎内部布局不重写，只处理页面级外壳。
- 验收：`_selftest_gui.py` 全过；`_selftest_vt_fluent_qss.py` PASS 54；`_selftest_vt_fluent_widgets.py` PASS 224；18 张截图按去分层版本重截。

## 二、最终截图

目录：`docs/ui-redesign/screenshots-v3/`（18 张，统一 1440×900，浅色、50% / 50%、主题色 `#009FAA`，全部按当前版本重截，含统一顶栏与去分层结构）。

| 文件 | 页面 | 说明 |
|---|---|---|
| `01-首页.png` | 首页 | 双卡 + 常用入口；无虚构队列 |
| `02-视频下载.png` | 视频处理 / 视频下载 | 任务输入单层分区、画质空态、并行任务表 |
| `03-音画合并.png` | 视频处理 / 音画合并 | 自动配对单层分区、输入输出单行 |
| `04-视频切片.png` | 视频处理 / 视频切片 | 切片参数单层分区与预览 |
| `05-视频库.png` | 视频库 | 真实 7 个视频、4 列、两行文件名；缩略图单层卡 |
| `06-实时字幕.png` | 实时字幕 | 采集/状态/字幕流/日志单层分区 |
| `07-字幕处理.png` | 字幕处理 | 默认语音转录、第三方引擎根卡唯一层 |
| `08-字幕编辑.png` | 字幕编辑 | 黑底视频区、属性面板 |
| `09-流水线.png` | 流水线 | 去页头；阶段顺序与任务进度单层分区 |
| `10-AI托管.png` | AI 托管 | 去页头；三段单层分区 |
| `11-自动化.png` | 自动化 | 去页头；模板采集 + 投稿任务单层卡 |
| `12-设置入口.png` | 设置 | 3×2 六个单层入口卡 |
| `13-设置-全局AI.png` | 设置 / 全局 AI | 主配置 + 决策模型扁平分区 |
| `14-设置-ASR.png` | 设置 / ASR | 本地模型与测试扁平分区 |
| `15-设置-字幕引擎.png` | 设置 / 字幕引擎与校准 | AI 校准扁平分区 + 第三方单层设置卡 |
| `16-设置-下载与存储.png` | 设置 / 下载与存储 | 目录、Cookie 扁平分区 |
| `17-设置-界面与外观.png` | 设置 / 界面与外观 | 50% / 50% 拉条；“卡片不透明度”0=全透明 |
| `18-设置-更新与关于.png` | 设置 / 更新与关于 | 版本与许可扁平分区 |

> 截图由 `data/tmp/_shoot_v3.py` 抓取，原始像素按系统 DPI 输出后统一缩放到 1440×900；程序逻辑宽度为 1440。字幕处理页等待引擎三段构建完成后再截，避免只截到「正在准备」占位。

## 三、验证结果

| 检查 | 结果 |
|---|---|
| `scripts/dev/_selftest_gui.py` | 2026-11-26 复跑：全部通过 |
| `_selftest_vt_fluent_qss.py` | PASS 54 |
| `_selftest_vt_fluent_widgets.py` | 2026-11-26 复跑：PASS 224 |
| 深色抽检 | `data/tmp/flatdark2/`：首页、视频下载、视频库、流水线、实时字幕、设置-下载/字幕引擎；表角、游离滚动条白块已消失，扁平分区在深色下保持可读 |
| `_selftest_vt_fluent_theme.py` | PASS（6 主题色 × 明暗 × 7 档 + QSS） |
| `_selftest_settings_resilience.py` | FAIL 0 |
| `_selftest_settings_import_race.py` | PASS 11 / FAIL 0 |
| `_selftest_download_queue_gui.py` | 10/10 |
| `_selftest_merge_manual.py` | ALL PASS |
| `_probe_window_resize.py` | ALL PASS（P1-P8 + N1-N3，880×620 可缩回） |
| `vt_ui_golden.py all` | 首页、设置均 `IDENTICAL` |
| `_probe_home_nav.py` | PASS 24 / FAIL 0（Qt 收尾退出码 `-1073740791`，历史问题） |
| `_selftest_pipeline.py` | 77 项中 74 PASS；3 项失败与本批 UI 无关：CALIB1 真实校准脚本、旧链接链自动补 TRANSCRIBE、状态文件已写出 |
| `data/tmp/test_topbar_drag.py` | 标签鼠标穿透、`startSystemMove()`、手动回退、双击最大化均通过 |
| `test_masks_dynamic.py` | 滑杆 50→0 即时生效，标签 0%/0%，可见卡片 alpha 全为 0 |
| 顶栏逐像素采样 | 浅色 x=0…2870 全为 `(251,252,253)`；深色动画结束后全为 `(26,29,33)`；内容区仍为 `(242,244,246)` / `(20,23,26)` |

窗口缩放说明：字幕处理页加滚动区后，880×620 不再被引擎最小高度撑回 700；这对应用户此前多次反馈的“转录页无法缩小”，本次回归探针已守住。

## 四、已知边界

1. **第三方字幕引擎内部布局未重写**：字幕处理/翻译/校准页只改了外层壳体（去页头、去页面级外套卡、扁平分区、滚动区）；引擎内部表单仍保持原布局。`harness\` 与第三方引擎内部按约束不动。
2. **字幕编辑仍是浅色属性面板 + 黑底预览**，没有完全做成 v3 样张的深色三栏；功能与控件未改。
3. **首页保留留白**：不伪造任务队列、统计或最近记录；因此双卡 + 常用入口以下为空白，属于产品口径，不是数据缺失。
4. **0% 的透明范围**：作用于 `FlatBody` 内容面与保留的单层卡片底板；输入框、列表、表格、日志等内容控件仍是实底，否则文字会直接压在背景图上不可读。0% 已让内容面和卡片底板全透，控件实底是最后一道可读性底线。
5. **部分页面首屏超过 900 高**：视频下载日志、合并/切片底部按钮在 900 高窗口需滚动查看；页面本身是 `ScrollPage`。
6. **带背景图页面的状态栏边界**：底栏已与内容区同色、无分隔线；但背景图只铺页面内容区，背景图与底栏之间仍有一条“图结束、纯色开始”的自然边界，不是状态栏底色造成的亮带。
7. **深色截图**：正式 18 张截图仍按用户当前 `light / 50 / 50` 配置；深色验证图单独放在 `data/tmp/dark_check2/`，不混入正式截图集。
8. **无 git 回滚点**：本机无 `git` 命令，本轮没有提交记录；回滚依据是下方改动文件清单与 `data/tmp` 配置备份。

## 五、改动文件

- 主题/壳层：`src/ui_theme.py`、`src/vt_fluent/_theme.py`、`src/vt_fluent/_qss/light.qss`、`src/vt_fluent/_qss/dark.qss`、`src/vt_app/shell.py`
- 主窗/共用件：`src/vt_app/main_window.py`、`src/vt_app/widgets.py`
- Fluent 控件：`src/vt_fluent/_display.py`（表角按钮隐藏）、`src/vt_fluent/_anim.py`（游离滚动条隐藏）、`src/vt_fluent/_inputs.py`（SpinBox 数字基线）
- 首页/设置：`src/vt_app/home_page.py`、`src/vt_app/settings_page.py`
- 功能页：`src/features/download/page.py`、`merge/page.py`、`split/page.py`、`library/page.py`、`workbench/page.py`、`subtitle_edit/page.py`、`pipeline/page.py`、`harness/harness_page.py`、`automation/auto_vision_page.py`、`live/page.py`
- 开发自检：`scripts/dev/_selftest_gui.py`、`_selftest_vt_fluent_qss.py`、`_selftest_vt_fluent_widgets.py`、`_selftest_settings_resilience.py`、`_probe_window_resize.py`
- 交付物：`docs/ui-redesign/原版UI更新报告.md`、`docs/ui-redesign/screenshots-v3/`（18 张）、`docs/ui-redesign/视频工具箱-v3截图-18张.zip`
- 内部临时物：`data/tmp/_shoot_v3.py`、`data/tmp/dark_check2/`、`data/tmp/dark_check/`、`data/tmp/*_crop*.png`

## 六、启动方式

```powershell
cd "D:\Agent Work\软件开发\视频工具箱"
tools\python\python.exe src\video_toolbox_qt.py
```

程序版本 `3.3.1`；`data/ui_custom.json` 保持 `light / 50 / 50 / #009FAA`，未重置用户外观配置。
