<!-- @version 2.5.3 -->
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
  _anim.py              # 共享动画基建（B1 落地）：背景过渡/阴影/指示器滑动/
                        # 平滑滚动 + singledispatchmethod（对齐上游 overload.py）
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
| `scripts/dev/_selftest_vt_fluent_widgets.py` | 控件族 parity（B1 门）：几何度量 + 标签字体 + SwitchButton/CheckBox 8 态×明暗色矩阵 + 进度条/滑杆态色 | ✅ B1 首跑 PASS（218 项） |
| `scripts/dev/_selftest_vt_fluent_b2b3.py` | B2/B3 可用性：SettingCard/CommandBar/RoundMenu/InfoBar/导航项/FluentWindow 几何对照 + 菜单/InfoBar/设置卡/窗口功能冒烟 | ✅ 首跑 PASS（38 项） |
| `scripts/dev/vt_ui_contract.py` / `vt_ui_lint.py` / `vt_ui_golden.py` | UI 契约 AST / lint / 黄金样本（既有，QSS 切换期继续守护） | ✅ 基线全过 |
| `scripts/dev/_gen_vt_fluent_icons.py` | 图标数据再生成（dev 期；前置 qfluentwidgets 已装） | ✅ 工具就位 |

图标艺术字口径：vt_fluent 内嵌 59 个使用面图标（黑变体单份，fill 运行期按主题替换）；
使用面外成员可导入、渲染报错并指引跑再生成脚本。底层图形源自 Microsoft
Fluent System Icons（MIT），自研引擎 + 自写 QSS 承担 Fluent 外观。

## 5. 施工顺序

### A. 拆分（每域一门：搬 → facade 再导出 → 置 SPLIT_STATUS=done → 跑全量自检）

| 步 | 域 | 门 | 状态 |
|---|---|---|---|
| A0 | core 骨架 + spec `collect_submodules('core')` + `check_deps.py` own_modules 递归（两层包防误报，同 online_release 坑） | core_api 的 NEG-CORE 档转正、check_deps 无误报 | ✅ 2026-10-16 完成（接口测试先立：core_api 黄金基线 + qss_migration 使用面基线双护） |
| A1 | **shared 底座**（textio/log/paths/runtime/proc/proxy/config/ai/vcsettings 九模块）+ **download 域**（deps/urls/ytdlp_util/cookies/npe/media/util 七模块） | download_cancel 29/29、core_api PASS（download=done 严格档） | ✅ 2026-10-16 完成（`f79d312`；单体 9221→5475 行） |
| A2 | **asr 域全量**：protocol（协议推断/守卫+九服务商 submit+词级聚合）/ patches（协议注入+分块几何）/ engine_config / voiceprint / ui_patch / runtime_patches；shared 收口两族（env/uibrand） | asr_proto 207/0、asr_language ALL PASS、speaker/vc/rate_limit_sql、七接缝全 PASS、smoke D+E 15/15 | ✅ 2026-10-16 完成（`6ee0854`+`4371c40`；单体 5475→1338 行，域进度档 2/6） |
| A3 | translate（vc_translate_route_patch）/ calibrate（calib_ai_* + GitHub 同步族 + sync_env_into）/ pipeline（rolling SRT + main） | _selftest_translate / _selftest_calib_ai / _smoke_all 全量 / pipeline 自检 | ✅ 2026-10-18 完成（`2c2dd2a` A3-1 + `42f0394` A3-2 + `1ed611f` A3-3；A3-2 追认 sync_env_into 移域 shared→calibrate） |
| A4 | facade 收口（video_toolbox.py 只剩再导出 + 版本头 + CLI 守门；SPLIT_STATUS 全 done） | core_api 全档 + 全量自检复跑 | ✅ 2026-10-18 完成（`01c9512`；facade **223 行零函数体**，CLI 守门补回，测试双形态适配 B 区在途 API） |

**单体行数轨迹**：9221 → 5475（A1）→ 2676（A2a）→ **1338（A2b）**。facade 残留 = translate 1 符号 + calibrate 16 符号 + pipeline 4 符号 + main。

### B. QSS 迁移（每控件一族一门：vt_fluent 实现 → parity 绿 → 切一个文件的 import → golden/截图验收）

| 步 | 内容 | 门 | 状态 |
|---|---|---|---|
| B0 | `_theme.py` + `_qss/` + `_icon.py`（主题引擎与图标先行） | 深浅色令牌与 qfluentwidgets 逐值对照 | ✅ 2026-10-16 完成（theme 探针 PASS：6 色 × 明暗 × 七档逐值 + QSS 渲染逐字节；icon 探针 PASS：472/472 合成像素；qss_migration parity 绿） |
| B1 | `_buttons.py` / `_inputs.py` / `_display.py`（纯控件族） | 单控件探针（离屏 WA_DontShowOnScreen 量几何 + 态色） | ✅ 2026-10-16 完成（widgets 探针 PASS：218 项——几何/字体/8 态×明暗色矩阵/进度条/滑杆） |
| B2 | `_feedback.py` / `_menu.py` / `_setting.py` | InfoBar 队列/动效、菜单 flyout、设置卡布局 | ✅ 2026-10-18 完成（InfoBar 叠放/滑入、RoundMenu flyout 五档动画、设置卡全家桶 + ExpandLayout） |
| B3 | `_window.py`（FluentWindow + NavigationInterface，最难） | `_probe_home_nav` 23/23 + 导航展开/收起/角标 | ✅ 2026-10-18 完成（自研无边框/Mica/标题栏/导航；b2b3 探针覆盖加页/切换/移除/常驻展开/宽度自适应） |
| B4 | 逐文件切 import（video_toolbox_qt.py → vt_engine_ui/* → 其余页）→ ui_theme 改接 → qt_compat 退役 | qss_migration 残留归零、vt_ui_golden IDENTICAL、_sel_shots 截图黄金 | ✅ 2026-10-18 完成（qss_migration **71/71、残留 0 符号 / 0 文件**；MainWindow 在 vt_fluent 上实例化 9 页/9 导航项、切页与主题切换冒烟通过；qt_compat SpinBox 补丁已重挂 vt_fluent.SpinBoxBase 并验证。⚠ 截图黄金 _sel_shots 待桌面环境补跑） |

B0 落地结构（src/vt_fluent/）：`__init__.py`（71 符号契约面 + 常量枚举
+ B1/B2/B3 pending 桩）、`_theme.py`（qconfig/ConfigItem/ThemeColor/样式表管理/
字体）、`_qss/{common,light,dark}.qss`（合并 QSS，令牌表注释钉值）、
`_icon.py` + `_icons_data.py`（175 成员 + 59 图标内嵌）。AUTO 档系统探测自研
（winreg，不依赖 darkdetect）；FluentStyleSheet 载体为合并文件（规则按类名
作用域，与逐控件分文件渲染等价）。

## 5.1 功能正常性验证（收官快照，2026-10-18 11:10）

六域拆分 + QSS 迁移全部完成后的全量验证：

| 验证层 | 项 | 结果 |
|---|---|---|
| 接口契约 | `_selftest_core_api`（157 符号 + 69 常量 + 行为抽查 + 禁 GUI 桩） | ✅ PASS（**域完成 6/6**） |
| QSS parity | `_selftest_qss_migration` | ✅ **71/71 符号、残留 0 符号 / 0 文件** |
| GUI 全量自检 | `_selftest_gui`（166 项） | ✅ 166/166 |
| GUI 导航探针 | `_probe_home_nav` | ✅ 23/23 |
| CLI | `_selftest_agent_cli` + `python src/video_toolbox.py` 菜单 | ✅ 21/21 + 菜单正常 |
| 下载链 | `_selftest_download_cancel`（8 阶段可中止） | ✅ 29/29 |
| ASR 链 | asr_proto 207/0、asr_language、speaker、vc、rate_limit_sql | ✅ 全过 |
| 引擎七接缝 | `_selftest_engine_*` | ✅ 全 PASS |
| 冒烟 | `_smoke_all` | 60/61（唯一失败 = YouTube 画质风控，环境项） |
| 依赖 | check_deps / py_compile 全树 | ✅ |

收官修复记录（A4 轮）：
1. **CLI 入口守门**：main 搬入 core.pipeline 后 facade 尾部补 `if __name__ == "__main__"`（`python src/video_toolbox.py` 静默失效实证）
2. **测试双形态适配 B 区在途 API**：`_engine_src()` 扩展为 facade + core 全树；导航宽度/遮罩对话框/PushButton 查找改「vt_fluent 优先 + qfluentwidgets 兜底」（B 区 expandWidth 私有化、MaskDialogBase/PushButton 迁自研后测试锚旧类名）
3. **core/calibrate/sync.py `__all__` 补全**：私有全家 + merge_calib_script/merge_learned_kb 别名（seg 原样搬入但漏登记）

## 6. 打包口径变更点（A0/B4 时落地）

1. `packaging/视频工具箱.spec`：`collect_submodules('core')`（显式补 SRC_DIR 再收集，防静默空列表）；vt_fluent 同款。
2. `scripts/dev/check_deps.py`：`own_modules` 改递归收子包（`core/download` 两层否则误报第三方缺失）。
3. `docs/第三方组件来源与许可声明.txt`：qfluentwidgets 移出「已不再随包分发」重打包后才成立。
4. 改 src/ 必须 repack 才生效（onefile 铁律）；发布前 file:// 自测在线发布链。

## 7. 风险与回滚

| 风险 | 缓解 |
|---|---|
| facade 漏再导出 → 运行期 AttributeError | core_api 基线比对（符号级）+ 全量自检；**暂停点实证**：check_names 升级 `import *` 展开 + facade 私有显式块补齐（_fallback_config_path/_path_on_system_drive） |
| core 子包循环依赖 | 依赖规则（§3.1）+ 每域单独 import 探针 |
| collect_submodules 静默空列表（pathex 时序坑） | 照 vt_engine_ui 先例显式补 sys.path；验证读 PYZ-00.pyz toc |
| QSS 迁移视觉回归 | vt_ui_golden 控件树 + _sel_shots 截图黄金 + 逐控件行为清单 |
| SpinBox Qt 6.12.0 回归复犯 | qt_compat 补丁改挂 vt_fluent.SpinBox 前不得退役 |
| 工作树半迁移态 | 每域一提交；git 树可随时 `git stash` 回退到上一门 |
| **monkeypatch 接缝跟随实现域**（A1/A2 累计 5 处实证） | 测试 patch 一律双侧打（engine.* + core 实现模块.*）；asr_proto 的 `_pk/_unpk + _PATCH_MODS` 基础设施可复用 |
| **跨模块 `global`**（A2 实证） | import 审计的盲区——搬段时 grep `global ` 手工复核，改模块属性读写 |
| 探针污染（kb-sync 重放删 @version） | 每轮跑 GUI 探针后 `git checkout -- AGENTS.md CLAUDE.md SKILL.md ×3 .trae` |

## 8. 后续任务清单（收官态，2026-10-18 11:10）

### A 区拆分 —— 全部完成 ✅

| # | 任务 | 状态 |
|---|---|---|
| A3-1 | translate 域（route_patch） | ✅ `2c2dd2a`（v3 流程首单：并行文件先行） |
| A3-2 | calibrate 域（ai + sync 两模块，sync_env_into 追认移域） | ✅ `42f0394` |
| A3-3 | pipeline 域（srt_rolling + main 编排层） | ✅ `1ed611f` |
| A4 | facade 收口：223 行纯再导出 + CLI 守门 + SPLIT_STATUS 全 done | ✅ `01c9512` |

**单体轨迹**：9221 → 5475 → 2676 → 1303 → 398 → **223 行（零函数体）**。域进度 6/6。

### B 区 QSS 迁移 —— 全部完成 ✅（用户主导）

| # | 任务 | 状态 |
|---|---|---|
| B2/B3 | feedback/menu/setting/window 四族 | ✅ `75ef899` |
| B4 | 15 文件切 import，qfluentwidgets 残留归零 | ✅ `2b75b94`（71/71、残留 0） |

### 剩余收尾（联合）

| # | 任务 | 门 | 状态 |
|---|---|---|---|
| 1 | **repack 出包**（PyInstaller onefile；改 src/ 不 repack 不生效——六域 + vt_fluent 全量落地后必须出包） | 打包成功 + PYZ toc 含 core.* 与 vt_fluent.* | ⬜ 待办 |
| 2 | `check_install_sync.py`（37 项 sha256 + 版本指纹）+ 在线发布 file:// 自测 | 全绿 | ⬜ 待办 |
| 3 | `stamp_versions.py` 重生成清单（先 git add） | 清单无漂移 | ⬜ 待办 |
| 4 | 许可声明：qfluentwidgets 已移出随包 → `docs/第三方组件来源与许可声明.txt` 第 3 节重写 + GPL-3.0 义务状态重估 | 合规成立 | ⬜ 待办 |
| 5 | `_sel_shots` 截图黄金补跑（需桌面环境，headless 不可） | 与 golden 比对 | ⬜ 待办 |
| 6 | GitHub push（本地直连；不通走 push_via_git_api.py + blob SHA 校验） | remote 一致 | ⬜ 待办 |
| 7 | memory 基线固化（六域 + B 区完工态写进 MEMORY.md） | — | ⬜ 待办 |
