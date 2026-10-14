# PyQt5 → PySide6 迁移方案书

> 版本：v1.0　|　编制日期：2026-10-14
> 依据：`docs/PySide6迁移清单.md`（实测数据）+隔离环境验证结论
> 隔离验证环境：`E:\vt_pyside6_probe\venv`（Python 3.12.10）

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

### 阶段 0：环境落地　⏳ 待执行
在正式环境装PySide6 + PySide6-Fluent-Widgets[full]。

⚠️ **两侧必须同步**：`C:\bld\qt_build`（打包环境）与 `tools\python`（运行副本）。
只装一侧会重演「源码模式正常、打包后 ImportError」的老问题。

**验收**：`python -c "import PySide6, qfluentwidgets"` 两侧都通过。

---

### 阶段 1：机械替换　⏳ 待执行
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

### 阶段 2：GUI 实跑验证　⏳ 待执行
在 PySide6 环境里启动真实界面，验证：
- 七个导航页正常渲染
- 主题切换（浅/深/跟随系统）
- Mica 云母效果
- 字幕编辑页（libmpv 播放 + 时间轴拖拽）

**验收**：`_selftest_gui.py`、`_selftest_speaker.py`、`_selftest_merge_manual.py` 全绿；
`_shot_sel.py` 截图无空白块。

---

### 阶段 3：打包链路改造　⚠️ **最高风险**
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

### 阶段 4：许可声明更新　⏳ 待执行
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

## 七、待你决策的三件事

1. **是否现在就推进**阶段 0/1（装环境 + 机械替换）？
2. **双环境切换策略**：是「先切 `tools\python` 验证、再切 `C:\bld\qt_build`」，
   还是一次性两边同切？
3. **qfluentwidgets 商用许可**：若本软件属商用，界面组件库需向作者购买许可
   （与换不换 PySide6 无关，但换 PySide6 不会解决这一项）。

---

## 八、回滚方案

**前提已验证**：两套环境目前**完全隔离、互不可见**——

| 环境 | 有 PyQt5 | 有 PySide6 |
|---|---|---|
| `C:\bld\qt_build`（打包） | ✅ | ❌ |
| `E:\vt_pyside6_probe\venv`（隔离） | ❌ | ✅ |

⇒ 只要**不把 PySide6 装进 `qt_build`**、**不卸载 PyQt5**，回滚就是「换回解释器路径」，
零成本。这也是阶段 0 建议**先在隔离环境完成全部验证**的原因。

- 代码层：`git checkout main`，或用阶段 1 建的 `backup/pyside6-migration` 分支；
- 环境层：PySide6 与 PyQt5 分处不同解释器，互不干扰；
- ⚠️ **不建议**在 `tools\python` 里卸载 PyQt5 —— 保留它意味着随时能对比两套行为，
  也是 GUI 出现渲染差异时的排查依据。