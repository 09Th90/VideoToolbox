<!-- @version 2.5.2 -->
# PyQt5 → PySide6 迁移清单

> 生成日期：2026-10-13。**本清单里的每个数字都是从仓库实测得来的**，不是估算。
> 口径：`grep` 统计 `src/` 与 `scripts/`；`tools/` 下那5400 余处是第三方库
> 自身的 PyQt5 代码，不在迁移范围内。

## 一、为什么要换

| | PyQt5 | PySide6 |
|---|---|---|
| 许可 | **GPLv3**（商业授权另购） | **LGPLv3**（动态链接，可闭源分发） |
| 维护方 | Riverbank（商业） | Qt 官方 |
| Python 绑定风格 | 略偏 C++ | 更 Pythonic |

对本项目的直接收益：**界面层代码从 GPLv3 约束下解放**，与此前「引擎能力自研化」
同一方向；同时去掉对商业授权的潜在需求。

## 二、规模（实测）

| 目录 | 引用处数 | 涉及文件 |
|---|---|---|
| `src/` | 99 | 45 |
| `scripts/` | 63 | 16 |
| `packaging/` | 1393 | 12（打包配置里的 PyQt5 DLL/Qt5 路径引用） |
| **合计（代码）** | **约 162** | **61** |

> `tools/` 下的 5406 处是第三方库（qfluentwidgets 等）自己的 PyQt5 引用，
> **不迁**——换包后它们自然消失。

用到的 Qt 子模块仅 4 个，迁移面比想象小：

| 子模块 | 引用次数 |
|---|---|
| `PyQt5.QtWidgets` | 41 |
| `PyQt5.QtCore` | 36 |
| `PyQt5.QtGui` | 17 |
| `PyQt5.QtTest` | 2 |

## 三点之二、⚠ 许可现状（迁移前必须知道，2026-10-13 核实）

### 1. 换 PySide6 解决的是「框架」许可，不是「组件库」许可

| 组件 | 现状 | 换PySide6 后 |
|---|---|---|
| Qt 绑定 | PyQt5 = **GPLv3** | PySide6 = **LGPLv3** ✅ 受益 |
| Fluent 组件库 | `PyQt-Fluent-Widgets` = GPLv3（仅非商业） | `PySide6-Fluent-Widgets` = **双许可：非商业 GPLv3 / 商用需购买** ⚠ 未变 |

⇒ **换PySide6 只把「Qt 绑定」这一层从 GPLv3 解放为 LGPLv3**；界面组件库
`qfluentwidgets` 无论哪个变体都是 GPLv3 起步，商用需另购许可。
如果驱动迁移的理由是「摆脱 GPL」，那这个理由**只兑现一半**。

### 2. 四个变体包名相同，不能共存

`PyQt-Fluent-Widgets` / `PyQt6-` / `PySide2-` / `PySide6-Fluent-Widgets`
**装出来的包名都叫 `qfluentwidgets`**。官方明确警告不可同时安装。
⇒ 切换必须**彻底卸载旧包再装新包**，不能并存试用。

### 3. ⚠ 发现一个既存合规缺口（与迁移无关，但更要紧）

`docs/第三方组件来源与许可声明.txt` 里**没有登记 PyQt5，也没有登记
qfluentwidgets**——而这两者都被打进 exe、都是 GPLv3。声明里目前只登记了
NewPipe Extractor 与早期字幕引擎两个 GPL 组件。

这是**当前就存在的**声明不完整，与要不要换 PySide6 无关。建议在迁移之前
或至少同期补上，否则「随包分发 GPLv3 二进制却不告知」这一状态持续存在。

---

## 三之三、API 差异清单（须逐项改）

### 3.1 批量替换（可脚本化）

| PyQt5 | PySide6 | 处数 | 说明 |
|---|---|---|---|
| `PyQt5.QtCore` | `PySide6.QtCore` | — | 仅换包名 |
| `PyQt5.QtWidgets` | `PySide6.QtWidgets` | — | 仅换包名 |
| `PyQt5.QtGui` | `PySide6.QtGui` | — | 仅换包名 |
| `pyqtSignal` | `Signal` | **92+** | PySide6 去掉 `pyqt` 前缀；含 1 处 `pyqtSignal as _pyqtSig` 需单独确认 |
| `pyqtSlot` | `Slot` | 0 | 未使用 |
| `pyqtProperty` | `Property` | 0 | 未使用 |

### 3.2 实测后修正（2026-10-13 隔离环境验证，**原先判断有误**）

隔离环境 `E:\vt_pyside6_probe\venv` 实测（PySide6 6.12.0 / Qt 6.12.0 /
PySide6-Fluent-Widgets 1.11.3），探针 `build/_probe_pyside6.py` **15 项全通过**。

| 项 | 原先判断 | **实测结论** | 迁移影响 |
|---|---|---|---|
| `.exec_()` 11 处 | 「PySide6 已移除，必须改 `.exec()`」 | ❌ **判断错了** —— PySide6 **保留了 `exec_()`**（向后兼容） | **不必改** |
| `setSectionResizeMode` 8 处 | 「裸枚举成员已不存在，会 AttributeError」 | ❌ **判断错了** —— `QHeaderView.Fixed` 仍可用（值 == `ResizeMode.Fixed`） | **不必改** |
| `isSystemDarkTheme` | 未查 | ⚠ **确实被移除** —— 替代品是 `isDarkThemeMode()` | `ui_theme.py:401` 需改 |
| `pyqtSignal` → `Signal` | 92+ 处 | ✅ 需改（`Signal` 是正确名） | 须改 |
| 信号触发 `sig(...)` | 未查 | ⚠ PySide6 **只能 `.emit()`**，`sig(...)` 报 `TypeError: native Qt signal instance is not callable` | ✅ 无影响 —— 本项目 96 处触发**全部已是 `.emit()`** |

⇒ **实际必改项只剩两处**：`pyqtSignal` → `Signal`（92+ 处，可脚本化）、
`isSystemDarkTheme` → `isDarkThemeMode`（1 处，在 `ui_theme.py`）。
原先清单里「19 处 exec_/枚举必须逐个改」的判断作废。

### 3.3 已验证可用的能力（实测）

| 能力 | 结果 |
|---|---|
| 项目用到的 18 个 qfluentwidgets API | **全部存在** |
| 主题切换 `setTheme(LIGHT/DARK)` + `isDarkTheme()` | **真实生效**（LIGHT=False / DARK=True） |
| `setThemeColor` | 生效 |
| `CardWidget` + `BodyLabel` 渲染 | 成功（600×300 非空） |
| `Signal` + `.emit()` | 可用 |

### 3.4 依赖包替换

| 现装 | 问题 | 换成 |
|---|---|---|
| `PyQt-Fluent-Widgets 1.8.4` | 基于 PyQt5，GPLv3 非商业 | `PySide6-Fluent-Widgets 1.11.3` ✅ 已实测可用 |

## 四、迁移步骤（每步可回滚）

0. ~~隔离验证~~ ✅ **已完成**（15/15 通过，见 3.2 / 3.3）；
1. **批量替换**：`pyqtSignal` → `Signal`、`PyQt5.*` → `PySide6.*`
   （脚本化，逐文件 `py_compile` 验证）；
2. **改 1 处**：`ui_theme.py:401` 的 `isSystemDarkTheme` → `isDarkThemeMode`；
3. **重验 `ui_theme.py`**：主题、亚克力/云母材质、卡片取色
   （依赖已验证可用，但它是 1286 行的自研补丁，需实跑）；
4. **改打包链路**：`packaging/视频工具箱.spec` 与 `iss` 里那 1393 处
   Qt5 DLL / 路径引用——**这一步最易漏**，PySide6 的 DLL 布局与 PyQt5 不同
   （`Qt5/bin/*.dll` → `Qt/lib/*.dll`）；
5. **全量自检**：至少 GUI 全过 + `_selftest_vc` + 打包链路自检。

> ### 关于 `AcrylicLabel`（澄清，避免误判）
>
> 装 `[full]` 变体（连带 colorthief / numpy / pillow / scipy）后，
> **`AcrylicLabel` 仍不存在**——该组件在新版里已不提供。
> 但**本项目根本没用它**：`grep` 确认 `src/` 里零处引用。
>
> 项目的云母/亚克力效果实际走的是 **Mica `FluentWindow`**：
> ```python
> w.isMicaEffectEnabled()      # True（存在）
> w.setMicaEffectEnabled(True) # True（存在）
> ```
> 实测 `FluentWindow` 在 PySide6 下**可构造、可渲染**（800×600 非空），
> Mica 接口齐全 ⇒ **云母效果不构成迁移障碍**。
>
> `acrylic_*` 组件（`acrylic_menu` / `acrylic_line_edit` / `acrylic_flyout` 等）
> 仍在 `qfluentwidgets.components.material` 下，如将来要用可从那里取。

## 五、待确认事项

- **本软件是否属于「商业用途」**——这决定 `qfluentwidgets` 的 GPLv3 条款是否
  适用。若属商用，界面组件库需要向作者购买许可（与换不换 PySide6 无关）。
- 现有打包环境 `D:\Agent Work\_bld\qt_build` 与 `tools\python` 都装着 PyQt5，切换时
  **两侧必须同步**，否则会重演「源码模式正常、打包后失败」。
- `docs/第三方组件来源与许可声明.txt` 需补 PyQt5 与 qfluentwidgets 两条
  （见三之二第 3 点）。