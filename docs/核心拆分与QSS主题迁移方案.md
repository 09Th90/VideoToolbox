<!-- @version 2.3.1 -->
# 核心单体拆分 + 自写 QSS 主题迁移 · 方案

> 2026-10-16 立。两项工程共享同一套「先立接口测试再动刀」纪律。
> 测试桩：`scripts/dev/_selftest_core_api.py`（拆分）、`scripts/dev/_selftest_qss_migration.py`（QSS）。

## 1. 目标与验收

| 工程 | 目标 | 硬性验收 |
|---|---|---|
| A. 拆核心单体 | `src/video_toolbox.py`（9221 行）按域拆入 `src/core/<域>/`，原文件退化为 facade 薄再导出层 | ① `_selftest_core_api` PASS（150 公开符号 + 69 常量基线不漂移）；② 既有自检基线不降（asr_proto 207 / download_cancel 29 / pipeline 64 / smoke 60-61 / GUI 全过 / vc 全过）；③ 调用方 `import video_toolbox` 零改动 |
| B. 自写 QSS 主题 | qfluentwidgets（GPL-3.0）整体替换为自研 `src/vt_fluent/`（QSS 主题 + Fluent 风格控件库），**Fluent 风格零损失** | ① `_selftest_qss_migration` 残留归零；② `vt_ui_golden` 控件树 IDENTICAL + `_sel_shots` 截图黄金比对；③ 深浅色 / 高 DPI / 全部交互态（hover/pressed/disabled/focus）逐项对照验收；④ 随包许可声明移除 qfluentwidgets 后合规成立 |

## 2. 现状盘点（v2.3.1）

### 2.1 单体职责分区（约数，行号区间粗估）

| 域 | 内容 | 规模 |
|---|---|---|
| ASR 协议适配 | `_asr_*` 各服务商 submit、协议推断/纠偏、chunk/lazy-cache 补丁、声纹筛选、vc 转录 UI 补丁 | ~4000 行 |
| 共享底座 | 文本编解码、路径/数据根、vc 引擎嵌入胶水、进程/代理（mihomo）、AI 双通道、配置存取 | ~2100 行 |
| 下载链 | yt-dlp 全链（8 阶段可中止）、NPE fallback、cookie/CDP、代理选点、信息/画质探测、音画合并 | ~1500 行 |
| 校准 + GitHub 同步 | `calib_ai_*`（Agent 级校准）、校准知识/声纹收件箱同步 | ~900 行 |
| SRT 工具 + 入口 | `srt_time_to_ms` 系、滚动字幕稳定化、`main()` 编排 | ~750 行 |

### 2.2 qfluentwidgets 使用面（QSS 工程需求清单）

71 个符号 / 15 个文件，完整清单钉在 `scripts/dev/_golden/qss_usage.json`（由 parity 测试维护，只许收缩）。按文件分三组：

| 组 | 文件 | 符号规模 |
|---|---|---|
| 宿主 GUI | `video_toolbox_qt.py` | ~32（FluentWindow/NavigationWidget/各控件） |
| 引擎 UI 包 | `vt_engine_ui/*`（8 文件） | ~30（SettingCard 全家桶/CommandBar/RoundMenu/TableView…） |
| 其余页 + 主题层 | `ui_theme.py`、`auto_vision_page.py`、`harness_page.py`、`speaker_voiceprint_page.py`、`subtitle_compose.py`、`qt_compat.py`、`video_toolbox.py` | ~9 |

## 3. 目标架构

### 3.1 核心拆分（六域 = 五域 + shared 底座）

```
src/
  video_toolbox.py      # facade：from core.<域> import *（显式再导出，AST 顶层无函数体）
  core/
    __init__.py
    shared/             # 文本编解码/进程/代理/vc 胶水/AI 通道/配置（被多域共用，单独成域防依赖倒置）
    download/           # yt-dlp 链 / NPE / cookie / 探测 / 音画合并
    asr/                # ASR 协议适配 / vc 转录补丁 / 声纹筛选
    translate/          # 翻译路由补丁（vc_translate_route_patch）
    calibrate/          # Agent 级校准 + GitHub 知识同步
    pipeline/           # main 编排 + SRT 工具链
```

**facade 纪律**：拆分后 `video_toolbox.py` 每个原公开符号都必须来自 `core.<域>` 的再导出；`_selftest_core_api` 的进度档对 `done` 域强制断言「facade 无该域函数体」。

**域间依赖规则**（负向桩已立：core 引擎层禁 import Qt/qfluentwidgets）：
- `shared` 不依赖任何域；`download/asr/translate/calibrate` 只准依赖 `shared`；
- `pipeline` 可依赖全部（编排层）；域间横向依赖一律走 `shared` 或由 pipeline 组装。

### 3.2 自研 QSS 主题库

```
src/vt_fluent/
  __init__.py           # __all__ = 全量符号（parity 测试读它）
  _theme.py             # Theme / setTheme / setThemeColor / isDarkTheme / qconfig / ConfigItem / FluentStyleSheet
  _qss/                 # light.qss / dark.qss / common.qss（自写，与 qfluentwidgets 行为等价）
  _icon.py              # FluentIcon 枚举 + Segoe Fluent Icons 字体 QIcon 引擎
  _window.py            # FluentWindow / NavigationInterface / NavigationWidget
  _buttons.py           # PushButton / PrimaryPushButton / ToolButton 系 / HyperlinkButton / PillPushButton
  _inputs.py            # LineEdit / PasswordLineEdit / TextEdit / ComboBox / EditableComboBox / SpinBox / CompactSpinBox / CheckBox / SwitchButton / Slider
  _display.py           # BodyLabel 系 / CardWidget / SimpleCardWidget / ScrollArea / SegmentedWidget / ProgressBar / ProgressRing / ListWidget / TableWidget / TableView
  _feedback.py          # InfoBar / InfoBarPosition / MessageBox / MessageBoxBase
  _menu.py              # Action / RoundMenu / CommandBar
  _setting.py           # SettingCard 全家桶 / ExpandLayout / SettingCardGroup
```

**零损失验收口径**：每个控件对照 qfluentwidgets 的行为清单（默认/hover/pressed/disabled/checked 态、尺寸度量、动效时长、键盘焦点序）逐项打勾；`ui_theme.py` 的 `build_app_qss()` 已有自研 QSS 底子，主题令牌（accent/深浅/卡片底/导航底）全部收进 `_theme.py` 单一权威；`qt_compat.install_spinbox_fix` 的 Qt 6.12.0 SpinBox 补丁改挂 `vt_fluent.SpinBox` 后随 qfluentwidgets 一并退役。

## 4. 接口测试体系（已就位）

| 测试 | 职责 | 当前状态 |
|---|---|---|
| `scripts/dev/_selftest_core_api.py` | 公开 API 基线（150 符号 + 69 常量 + 签名）、DOMAIN_MAP 施工清单、行为抽查 9 项、core 禁 GUI 负向桩、域进度档 | ✅ 首跑 PASS |
| `scripts/dev/_selftest_qss_migration.py` | qfluentwidgets 使用面基线（71 符号/15 文件）、只许收缩不许新增、vt_fluent parity | ✅ 首跑 PASS；B0 后 parity 绿（71 符号全覆盖） |
| `scripts/dev/_selftest_vt_fluent_theme.py` | 主题令牌 parity（B0 门）：ThemeColor 七档 × 6 主题色 × 明暗逐值、renderQss 逐字节、ConfigItem 语义、字体 | ✅ B0 首跑 PASS |
| `scripts/dev/_selftest_vt_fluent_icon.py` | 图标渲染 parity（B0 门）：175 成员面 + 59 图标 × 明暗 × 4 尺寸合成像素逐项 | ✅ B0 首跑 PASS（472/472） |
| `scripts/dev/vt_ui_contract.py` / `vt_ui_lint.py` / `vt_ui_golden.py` | UI 契约 AST / lint / 黄金样本（既有，QSS 切换期继续守护） | ✅ 基线全过 |
| `scripts/dev/_gen_vt_fluent_icons.py` | 图标数据再生成（dev 期；前置 qfluentwidgets 已装） | ✅ 工具就位 |

图标艺术字口径：vt_fluent 内嵌 59 个使用面图标（黑变体单份，fill 运行期按主题替换）；
使用面外成员可导入、渲染报错并指引跑再生成脚本。底层图形源自 Microsoft
Fluent System Icons（MIT），自研引擎 + 自写 QSS 承担 Fluent 外观。

## 5. 施工顺序

### A. 拆分（每域一门：搬 → facade 再导出 → 置 SPLIT_STATUS=done → 跑全量自检）

| 步 | 域 | 门 |
|---|---|---|
| A0 | core 骨架 + spec `collect_submodules('core')` + `check_deps.py` own_modules 递归（两层包防误报，同 online_release 坑） | core_api 的 NEG-CORE 档转正、check_deps 无误报 |
| A1 | download（cookie/ytdlp/NPE/merge/探测） | download_cancel 29/29、pipeline 64/64、core_api PASS |
| A2 | asr（~4000 行，最大头；分 3~4 个提交） | asr_proto 207/0、七接缝 `_selftest_engine_*` 全 PASS |
| A3 | translate → calibrate → pipeline | _selftest_translate / _selftest_calib_ai / _smoke_all |
| A4 | facade 收口（video_toolbox.py 只剩再导出 + 版本头） | core_api 全域 done、全量自检复跑 |

### B. QSS 迁移（每控件一族一门：vt_fluent 实现 → parity 绿 → 切一个文件的 import → golden/截图验收）

| 步 | 内容 | 门 | 状态 |
|---|---|---|---|
| B0 | `_theme.py` + `_qss/` + `_icon.py`（主题引擎与图标先行） | 深浅色令牌与 qfluentwidgets 逐值对照 | ✅ 2026-10-16 完成（theme 探针 PASS：6 色 × 明暗 × 七档逐值 + QSS 渲染逐字节；icon 探针 PASS：472/472 合成像素；qss_migration parity 绿） |
| B1 | `_buttons.py` / `_inputs.py` / `_display.py`（纯控件族） | 单控件探针（离屏 WA_DontShowOnScreen 量几何 + 态色） | 待施工 |
| B2 | `_feedback.py` / `_menu.py` / `_setting.py` | InfoBar 队列/动效、菜单 flyout、设置卡布局 | 待施工 |
| B3 | `_window.py`（FluentWindow + NavigationInterface，最难） | `_probe_home_nav` 23/23 + 导航展开/收起/角标 | 待施工 |
| B4 | 逐文件切 import（video_toolbox_qt.py → vt_engine_ui/* → 其余页）→ ui_theme 改接 → qt_compat 退役 | qss_migration 残留归零、vt_ui_golden IDENTICAL、_sel_shots 截图黄金 | 待施工 |

B0 落地结构（src/vt_fluent/）：`__init__.py`（71 符号契约面 + 常量枚举
+ B1/B2/B3 pending 桩）、`_theme.py`（qconfig/ConfigItem/ThemeColor/样式表管理/
字体）、`_qss/{common,light,dark}.qss`（合并 QSS，令牌表注释钉值）、
`_icon.py` + `_icons_data.py`（175 成员 + 59 图标内嵌）。AUTO 档系统探测自研
（winreg，不依赖 darkdetect）；FluentStyleSheet 载体为合并文件（规则按类名
作用域，与逐控件分文件渲染等价）。

## 6. 打包口径变更点（A0/B4 时落地）

1. `packaging/视频工具箱.spec`：`collect_submodules('core')`（显式补 SRC_DIR 再收集，防静默空列表）；vt_fluent 同款。
2. `scripts/dev/check_deps.py`：`own_modules` 改递归收子包（`core/download` 两层否则误报第三方缺失）。
3. `docs/第三方组件来源与许可声明.txt`：qfluentwidgets 移出「已不再随包分发」重打包后才成立。
4. 改 src/ 必须 repack 才生效（onefile 铁律）；发布前 file:// 自测在线发布链。

## 7. 风险与回滚

| 风险 | 缓解 |
|---|---|
| facade 漏再导出 → 运行期 AttributeError | core_api 基线比对（符号级）+ 全量自检 |
| core 子包循环依赖 | 依赖规则（§3.1）+ 每域单独 import 探针 |
| collect_submodules 静默空列表（pathex 时序坑） | 照 vt_engine_ui 先例显式补 sys.path；验证读 PYZ-00.pyz toc |
| QSS 迁移视觉回归 | vt_ui_golden 控件树 + _sel_shots 截图黄金 + 逐控件行为清单 |
| SpinBox Qt 6.12.0 回归复犯 | qt_compat 补丁改挂 vt_fluent.SpinBox 前不得退役 |
| 工作树半迁移态 | 每域一提交；git 树可随时 `git stash` 回退到上一门 |
