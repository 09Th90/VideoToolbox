<!-- @version 2.2.5 -->
# PyQt5 → PySide6 迁移方案书

> 版本：v1.0　|　编制日期：2026-10-14
> 依据：`docs/PySide6迁移清单.md`（实测数据）+隔离环境验证结论
> 隔离验证环境：`E:\vt_pyside6_probe\venv`（Python 3.12.10）
>
> **执行状态（2026-10-14）：五阶段全部执行完毕**，用户已拍板「执行、完成迁移」。
> 各阶段标记与执行记录见文末「九、执行记录」——其中 4 处方案书预判被实测
> 修正（videocaptioner 漏项 / Qt6 API 差异 / PySide6 自带 MSVC runtime /
> 引擎资源停发），处置方式均记录在案。

---

## 一、结论先行：可行，且比原估轻

**可行性已验证**（探针 15/15 通过）。真正的风险不在代码量，而在**打包链路的 DLL 布局**。

| 维度 | 结论 |
|---|---|
| 环境 | PySide6 6.12.0 / Qt 6.12.0 / PySide6-Fluent-Widgets 1.11.3 |
| 18 个 qfluent API | 全部存在 |
| 主题切换 / Mica 云母| 真实生效 |
| 受影响文件 | **40 个 `.py`**（`src/` + `scripts/`） |
| **必改代码** | **约 119 处**（105 `pyqtSignal` + 102 处import + 12 处硬编码路径，去重后约 100 个改动点） |
| **不必改** | `exec_()` 11 处、`QHeaderView.Fixed` 8 处、96 处 `.emit()` |
| 最大风险 | 打包链路的 DLL/插件路径（PyQt5 `Qt5/` 两级→ PySide6 扁平布局） |

### 精确计数（`PyQt5.X` 全形式，含 `import` 与 `from ... import`）

| 符号 | 出现次数 |
|---|---|
| `PyQt5.QtCore` | 38 |
| `PyQt5.QtWidgets` | 44 |
| `PyQt5.QtGui` | 18 |
| `PyQt5.QtTest` | 2 |
| `pyqtSignal` | **105** |

---

## 二、原估与实测的差异（务必先看）

迁移清单初稿里有**三处判断被实测推翻**，这是工作量下降的主要原因：

| 原判断 | 实测 | 影响 |
|---|---|---|
| 「PySide6 已移除 `exec_()`，11 处必改」 | ❌ 保留向后兼容 | **省 11 处** |
| 「`QHeaderView.Fixed` 裸枚举不存在，会崩」 | ❌ 仍可用 | **省 8 处** |
| 「`AcrylicLabel` 缺失是遗留障碍」 | ❌ 项目零处引用它 | **消除 1 个假风险** |

⇒ 实际工作量从「约 120 处 + 逐个甄别枚举」降到「约 100 处机械替换」。

---

## 三、必改清单（已逐行定位）

### 3.1 批量替换（40 个文件，可脚本化）

| 模式 | 出现次数 | 说明 |
|---|---|---|
| `PyQt5.QtCore` → `PySide6.QtCore` | 38 | 仅换包名 |
| `PyQt5.QtWidgets` → `PySide6.QtWidgets` | 44 | 仅换包名 |
| `PyQt5.QtGui` → `PySide6.QtGui` | 18 | 仅换包名 |
| `PyQt5.QtTest` → `PySide6.QtTest` | 2 | 仅换包名 |
| `pyqtSignal` → `Signal` | **105** | PySide6 去掉 `pyqt` 前缀 |

> ⚠ 含 1 处 `pyqtSignal as _pyqtSig` 别名导入，需单独确认是否同步改别名。
>
> ⚠ 计数口径：上表是符号**出现次数**（同一文件多次 import 分开计），
> 与「改动文件数 40」不是一回事，替换脚本按出现处替换。

### 3.2 API 差异（1 处，必须手工改）

`src/ui_theme.py:401`
```python
# 现状（PySide6 版已移除该函数）
from qfluentwidgets import isSystemDarkTheme
# 改为
from qfluentwidgets import isDarkThemeMode
```
`isDarkThemeMode()` 配合 `Theme.AUTO` 使用，语义等价。

### 3.3 硬编码路径（12 处，最易漏）

**布局差异是根本原因**：

```
PyQt5:   site-packages/PyQt5/Qt5/plugins/platforms/   （两级）
         site-packages/PyQt5/Qt5/bin/*.dll
PySide6: site-packages/PySide6/plugins/platforms/       （扁平，无 Qt5/ 层）
         site-packages/PySide6/*.dll（Qt6*.dll 与 .pyd 同级）
```

| 文件 | 行 | 现状 |
|---|---|---|
| `src/video_toolbox_qt.py` | 9830 | `os.path.join(base, "PyQt5", "Qt5", "plugins")` |
| `src/video_toolbox.py` | 537 | `need = {"PyQt5": "PyQt5", ...}` 依赖自检表 |
| `scripts/dev/_probe_sel_bg.py` | 30 | `EMBEDDED_SITE_PACKAGES + PyQt5/Qt5/plugins` |
| `scripts/dev/_selftest_gui.py` | 26 | 同上 |
| `scripts/dev/_selftest_vc.py` | 4 处 | 同上 |
| `scripts/dev/_selftest_merge_manual.py` | 8 | 同上 |
| `scripts/dev/_selftest_speaker.py` | — | 同上 |
| `scripts/dev/_selftest_speaker_voiceprint_ui.py` | — | 同上 |
| `scripts/dev/_shot_sel.py` | 4 | 同上 |
| `scripts/dev/_probe_update_dialog_layout.py` | 13 | 同上 |
| `scripts/dev/_selftest_exe_dll.py` | 48 | `me + PyQt5/Qt5/bin`（DLL 冲突自检） |
| `scripts/dev/_smoke_all.py` | — | 依赖自检列表含 `"PyQt5"` |

---

## 四、一个**利好**：历史DLL 冲突将自动消失

项目里`_fix_msvc_runtime_shadow()`（`video_toolbox_qt.py:106`）是为**特定历史问题**写的：
2026-10-09曾出现 exe 内并存两套同名 MSVC runtime，`PyQt5\Qt5\bin\MSVCP140.dll`（14.26，2020 年）
顶掉根目录新版，导致 onnxruntime `DllMain` 失败。

**实测 PySide6 不自带 MSVC runtime**（`Qt/bin/` 与 `Qt/lib/` 下均无 `MSVCP140*` / `VCRUNTIME140*`）。

⇒ 迁移后该冲突的**根源自动消失**，`_fix_msvc_runtime_shadow()` 变成无害的冗余代码
（**建议保留**，作为防御性措施无成本）。

---

## 五、执行阶段（每阶段独立可回滚）

### 阶段 0：环境落地　✅ 已执行（2026-10-14）
在正式环境装PySide6 + PySide6-Fluent-Widgets[full]。

⚠️ **两侧必须同步**：`C:\bld\qt_build`（打包环境）与 `tools\python`（运行副本）。
只装一侧会重演「源码模式正常、打包后 ImportError」的老问题。

**验收**：`python -c "import PySide6, qfluentwidgets"` 两侧都通过。

---

### 阶段 1：机械替换　✅ 已执行（2026-10-14，另补 4 类 Qt6 API 修正，见执行记录）
1. 备份：`git stash` 不够，用 `git branch backup/pyside6-migration` 存一份基线；
2. 脚本替换 `PyQt5.*` → `PySide6.*`、`pyqtSignal` → `Signal`；
3. 逐文件 `py_compile` 验证；
4. 改 `ui_theme.py:401` 的 `isSystemDarkTheme`；
5. 改 12 处硬编码路径。

**验收**：
- `grep -rn "PyQt5" src/ scripts/` 归零
- 所有改动文件 `py_compile` 通过
- `_selftest_vc.py` 通过

---

### 阶段 2：GUI 实跑验证　✅ 已执行（2026-10-14，四项自检全绿）
在 PySide6 环境里启动真实界面，验证：
- 七个导航页正常渲染
- 主题切换（浅/深/跟随系统）
- Mica 云母效果
- 字幕编辑页（libmpv 播放 + 时间轴拖拽）

**验收**：`_selftest_gui.py`、`_selftest_speaker.py`、`_selftest_merge_manual.py` 全绿；
`_shot_sel.py` 截图无空白块。

---

### 阶段 3：打包链路改造　✅ 已执行（2026-10-14；MSVC 判据按实测扩写）
**这一步最易漏**，因为 spec 里那 1393 处 PyQt5 引用**绝大部分是注释**（真实代码引用 0 处），
但注释里描述的DLL 布局问题是真的。

必查项：
- [ ] `packaging/视频工具箱.spec`：`hiddenimports` 是否含 PyQt5 特有模块
- [ ] spec 的 `datas` / `binaries`：PyQt5 的 `Qt5\bin\*.dll` 与 `Qt5\plugins` 收集规则
- [ ] `packaging/视频工具箱.iss`：随包分发的 DLL 列表
- [ ] `_fix_msvc_runtime_shadow()` 调用时机（须在 Qt 导入之前，位置不变）
- [ ] `check_deps.py` 是否需加 PySide6 口径
- [ ] `_selftest_exe_dll.py` 的路径判据（`PyQt5/Qt5/bin` → `PySide6`）

**验收**：`check_install_sync.py` 缺失 0；安装后各功能页可用。

---

### 阶段 4：许可声明更新　✅ 已执行（2026-10-14，含历史缺口补登）
`docs/第三方组件来源与许可声明.txt` 需同步：
- PyQt5 → PySide6（许可从 GPLv3 变**LGPLv3**，是本次迁移的合规收益）
- PyQt-Fluent-Widgets → PySide6-Fluent-Widgets（**注意：仍是 GPLv3 非商业/商用需购买**）

⚠️ 顺带补一个**既存缺口**：该声明目前**既没登记 PyQt5 也没登记 qfluentwidgets**，
而两者都被打进 exe 且都是 GPLv3。此状态与迁移无关、当前就存在，建议同期补上。

---

## 六、风险登记

| 风险 | 等级 | 缓解 |
|---|---|---|
| 打包链路 DLL/插件路径未改全| **高** | 阶段 3 逐项打勾；`_selftest_exe_dll.py` 改判据后重跑 |
| 两侧环境只装一侧 | 中 | 阶段 0 验收要求两侧都import 成功 |
| `pyqtSignal as _pyqtSig` 别名遗漏 | 低 | 替换脚本单独处理这一处 |
| `ui_theme` 深路径 import 差异 | 低 | 阶段 2 实跑验证 |
| qfluentwidgets 新版 API 行为差异 | 低 | 已验证 18 个 API 可用 + 主题切换生效 |

---

## 七、待你决策的三件事（2026-10-14 已由用户拍板「执行，完成迁移」）

1. **是否现在就推进**阶段 0/1（装环境 + 机械替换）？—— **是，已推进**。
2. **双环境切换策略**：采用「先 `tools\python` 验证、GUI 全绿后再动
   `C:\bld\qt_build`（阶段 3 前装）」的保守顺序；PyQt5 两侧均保留未卸。
3. **qfluentwidgets 商用许可**：仍待作者按软件用途自行判断——PySide6-Fluent-
   Widgets 依旧 GPLv3，已在许可声明中显著标注（商用需另购，与迁移无关）。

---

## 八、回滚方案

**前提已验证**：两套环境目前**完全隔离、互不可见**——

| 环境 | 有 PyQt5 | 有 PySide6 |
|---|---|---|
| `C:\bld\qt_build`（打包） | ✅ | ✅（2026-10-14 已装） |
| `E:\vt_pyside6_probe\venv`（隔离） | ❌ | ✅ |

⇒ 代码层回滚：`git checkout backup/pyside6-migration -- <文件>`，或直接从
`history\_cleanup_20261014\pyside6_migration_backup\` 取字节级副本（含
`videocaptioner_pyqt5_orig` 与两侧旧口味 qfluentwidgets/qframelesswindow）。
环境层：PyQt5 未卸载、随时可比；`qfluentwidgets` 导入名唯一，回滚代码须同步
把备份里的旧口味目录放回 site-packages。

- 代码层：`git checkout main`，或用阶段 1 建的 `backup/pyside6-migration` 分支；
- 环境层：PySide6 与 PyQt5 分处不同解释器，互不干扰；
- ⚠️ **不建议**在 `tools\python` 里卸载 PyQt5 —— 保留它意味着随时能对比两套行为，
  也是 GUI 出现渲染差异时的排查依据。

---

## 九、执行记录（2026-10-14 实做，闭环用）

**各阶段验收实测**：
- 阶段 0：两侧 `import PySide6, qfluentwidgets` 通过（6.12.0 / 1.11.3），
  GUI 实际导入的 27 个 qfluentwidgets 符号逐一验证存在。
- 阶段 1：`grep PyQt5 src/ scripts/` = 0；290 个 `from PySide6.X import`
  符号静态校验全部存在；125 个 .py 编译通过；21 个应用模块实导成功。
- 阶段 2：`_selftest_gui.py` 166 PASS / `_selftest_speaker.py` 41 PASS /
  `_selftest_merge_manual.py` 66 PASS / `_selftest_vc.py` 全过（含内嵌工作台
  构建 0 空图）；`_shot_sel.py` 四张截图颜色数 82~186、无空白块；
  主题 light/dark/auto 三档、Mica 开关、字幕编辑页 libmpv 异步链路均验证。
- 阶段 3：PyInstaller 构建成功（exe 119,596,521 字节）；`_selftest_exe_dll.py`
  PASS（动态 import onnxruntime 1.29.0 = OK）；冻结 exe 用
  `VT_SHOT_TAB=subtitle VT_SHOT_MODE=qt` 冒烟通过（1770x1094 真实渲染）；
  `check_deps.py` 依赖闭合；`check_iss_sources.py` 47 通过 / 0 缺失 /
  模块闭包 21/21；ISCC 两次编译成功，日志审计 22,779 个文件、关键件全在包
  （exe / PySide6\Qt6Core.dll / 引擎资源 logo.png / 两份说明书）。
- 阶段 4：`docs/第三方组件来源与许可声明.txt` 新增「界面框架组件」一节。

**方案书预判被实测修正的 4 处**（处置均已完成）：
1. **videocaptioner 漏项（最严重）**：40 文件清单只含 src/ 与 scripts/，
   漏掉 vendored `tools\python\Lib\site-packages\videocaptioner`——其 ui/
   36 个文件直连 PyQt5，与迁移后变 PySide6 口味的 qfluentwidgets 同进程混用
   ⇒ access violation 段错误。已按同一机械规则移植（含
   `QApplication.desktop()`→`primaryScreen()`），tools\python 与 qt_build
   两侧同步；隔离探针环境没有该包，所以 15/15 探针看不到此问题。
2. **Qt6 API 差异不止 1 处**：除 `isSystemDarkTheme` 外还有
   `QVariant` 移除（→None，语义已用 _probe_sel_bg.py 验证）、
   `QShortcut` 移入 QtGui、`AdjustToMinimumContentsLength`→`AdjustToContents`、
   子类/实例访问继承枚举全崩（9 处 → `QAbstractItemView.X`）、
   槽异常默认行为变为走 excepthook（崩溃兜底钩子降级为增强保留）。
3. **PySide6 自带 MSVC runtime（与第四节结论相反）**：exe 解剖实测
   `PySide6\` 5 个 + `shiboken6\` 4 个同名副本；spec 补丁判据已扩为
   `('pyside6','shiboken6')` 前缀，实际改写 6 个，非空转。
4. **引擎静态资源停发（存量问题，非迁移引入）**：2026-10-12 归档
   `tools\videocaptioner\resource` 时误判「已内嵌进 exe」，实际 exe 不含 ⇒
   工作台空图。已从归档复制恢复该目录并重开 iss Source 行；顺带把
   `_selftest_gui` 的堆叠页期望 7→8（v2.1.0 home_page 早于迁移存在）。

**遗留事项**：
- `check_install_sync.py` 需在正式安装到 `D://VideoToolbox` 后跑（本机现有
  该目录是在线安装器的旧版布局；按 13.2 纪律不做无人值守全覆盖安装）。
- qfluentwidgets（PySide6-Fluent-Widgets）若作商用需另购许可（第七节决策 3）。
- exe 由 ~103MB 涨至 ~114MB；在线安装器走 GitHub Releases（2GB/资产），
  不受旧 gh-pages 100MiB 墙影响。
- 备份与回滚：分支 `backup/pyside6-migration` +
  `history\_cleanup_20261014\pyside6_migration_backup\`（40 个改动文件字节级
  副本、videocaptioner_pyqt5_orig、两侧旧口味包、两个一次性脚本）。
