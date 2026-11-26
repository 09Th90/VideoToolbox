<!-- @version 3.3.1 -->
# 全局 AI 设置 · UI 重设计规格

版本 v1 · 2026-11-24
预览文件：`docs/ui-redesign/全局AI设置-重设计预览.html`（浅色 / 深色 / 主题色可切换）
截图参考：`预览-浅色.png`、`预览-深色.png`

---

## 0. 结论

- **同宽 1040 基线，卡高从约 1040px 压到约 470px**（决策区展开）；决策区收起约 345px。
- 主表单从 10 行压到 3 行 + 1 个可折叠子区；主操作回到卡头，次操作贴近它所作用的字段。
- 解决原版四个结构问题：**标签不对齐、重复开关、长说明撑行、主次操作同权**。
- 颜色、圆角、卡片材质全部沿用 `src/ui_theme.py` 的 token，落地不动全局皮肤。

---

## 1. 原版诊断（基于截图）

| # | 问题 | 具体表现 | 影响 |
|---|---|---|---|
| 1 | 标签列宽不固定 | `srow()` / `label_row()` 用 `BodyLabel` 的自然宽度：「密钥」约 46px，「独立凭据（可选）」约 130px | 输入框起点相差 60~90px，整页没有竖向对齐线 |
| 2 | 单字段独占一行、输入框拉满 | 4 个短字段（密钥 / 地址 / 文本 / 视觉）各占一行，地址框宽 1300px | 视觉动线长，卡高 1040px，信息密度低 |
| 3 | 长说明直接铺在表单里 | 两段 caption 各占 1~2 行，夹在字段与按钮之间 | 字段间距被撑开，说明与字段的从属关系反而看不清 |
| 4 | 同一开关出现两次 | 「Jev 影子决策」与「决策模型启用」是同一个 `decision_enabled` | 用户不知道以哪个为准，两处状态同步还容易出 bug |
| 5 | 主次操作同权 | 测试接口 / 自动匹配 / 保存并应用 三个按钮同排、同尺寸 | 主操作不突出，「未保存」提示挤在按钮后面 |
| 6 | 风险提示脱离上下文 | 红色提示在卡片最底部，与「接口地址」隔了 5 个区块 | 看到提示时已经离设置项很远 |

---

## 2. 信息架构

```
全局 AI（一张卡，1040）
├─ 卡头    标题 / 启用状态 / 当前模型 / 未保存 / [保存并应用]
├─ 基础连接（12 栅格，3 行）
│   ├─ 启用 AI                密钥
│   ├─ 接口地址 [测试接口] [自动匹配]
│   └─ 文本模型               视觉模型
├─ 决策模型（可折叠子卡，头部是唯一总闸）
│   ├─ 决策模式               区域端点
│   ├─ 独立凭据 [测试决策模型]
│   └─ 单行说明
├─ 第二音色影子（单行实验项）
└─ 风险条（单行 + 查看详情）
```

设计原则：

1. **一列一条对齐线**：标签固定 84px，所有输入从同一 x 开始。
2. **主操作离开表单**：保存进卡头；测试 / 自动匹配贴着接口地址，不再单独占一行。
3. **开关只留一个**：Jev 总闸收进决策子卡头部，关掉时仍可见状态，展开才配置细节。
4. **说明降级为一行**：主提示单行 11.5px + 省略号，完整文案进 tooltip；不换行。
5. **风险提示贴着地址**：以 32px 警示条收在卡片底部，与地址栏同卡、只差一次视线移动。

---

## 3. 栅格与尺寸

| 项目 | 值 | 说明 |
|---|---|---|
| 基准宽度 | 1040（内容 1004） | 窄于 820 转单列；窄于 720 标签上置 |
| 栅格 | 12 列 / gutter 12 | 双列字段各 6 列；决策区 7 + 5 |
| 行距 | 8 | 表单行之间 |
| 标签列 | 84（固定） + 10 间距 | 中文 4~5 字 + 可选徽标仍能放下 |
| 控件高 | 30 | 输入 / 下拉 / 主按钮统一 |
| 小按钮 | 26 | 测试、自动匹配、查看详情 |
| 开关 | 36 × 20 | 圆形手柄 16，行程 16 |
| 胶囊 | 20 高 | 状态 / 模型 / 徽标 |
| 卡片内边距 | 18 左右 / 16 上下 | 仅本卡，不改 `card()` 全局的 14/12 |
| 圆角 | 卡片 10 / 子卡 8 / 控件 6 / 胶囊 999 | 与前两项 token 对齐，不额外引入半径 |
| 区块间距 | 12 | 表单 → 子卡 → 实验项 → 风险条 |
| 卡头 | 标题 22 行高，下缘 12 到分割线 | 分割线 1px `--line` |

> 高度预算：卡头 44 + 分割线 13 + 表单 3×30 + 2×8 + 提示 20 + 子卡 38 + 展开体 132 + 实验行 38 + 风险条 40 + 上下内边距 32 ≈ **470px**。

---

## 4. 字号层级

| 用途 | 字号 / 行高 | 字重 | 颜色 |
|---|---|---|---|
| 卡标题 | 15 / 22 | 600 | `--text` |
| 卡副标题 | 12 / 18 | 400 | `--dim` |
| 子卡标题 | 12.5 / 18 | 600 | `--text` |
| 字段标签 | 12.5 / 18 | 400 | `--dim` |
| 输入值 | 13 / 18 | 400 | `--text` |
| 说明 / 状态 | 11.5 / 16 | 400 | `--faint` |
| 胶囊 | 10.5 / 1 | 500 | 语义色 |
| 按钮 | 12.5 / 1 | 500 | 主按钮 `--on-accent` |

Qt 落地时用 `QFont.setPixelSize()`：标签 12、输入 13、说明 11、标题 15。**不要靠 QSS 的 `font-size: 12.5px`**，不同 DPI 下会取整不一致。

---

## 5. 颜色 token

| 角色 | 浅色 | 深色 | 来源 |
|---|---|---|---|
| 预览画布 | `#F1F3F5` | `#15171A` | 仅预览文件；应用内沿用 `page_base` / Mica，不改页面底色 |
| 卡片 | `#FFFFFF` | `#26292E` | `tokens.card` |
| 子卡 | `#F8FAFB` | `#2B2F34` | 新增，比卡片高一阶 |
| 描边 | `#E1E4E8` | `#3A3E45` | `tokens.card_border` |
| 输入底 | `#F6F8FA` | `#2B2E33` | `tokens.input_bg` |
| 主文字 | `#1F2226` | `#E8EAED` | `tokens.text` |
| 次文字 | `#697077` | `#9BA0A8` | `tokens.text_dim` |
| 辅助字 | `#8A929B` | `#7C848C` | 新增；仅说明 / 页脚，正文勿用 |
| 主题色 | `ui_theme.get_accent()` | 同左 | 预览用 `#0E8C96` |
| 主题色淡底 | 主题色 10% | 主题色 18% | `rgba(accent,.10/.18)` |
| 主题色描边 | 主题色 26% | 主题色 40% | `rgba(accent,.26/.40)` |
| 成功 | `#178A5B` | `#5BCB9A` | 预留 |
| 警示字 / 底 / 边 | `#A8641A` / `#FFF7E8` / `#F0DFC2` | `#E0B06A` / 10% / 28% | 风险条 |
| 卡片阴影 | `0 1px 2px rgba(20,28,38,.04), 0 12px 30px rgba(20,28,38,.07)` | 加深 | 预览用；`UICard` 本身无阴影，落地可省略（要加只加本卡 `QGraphicsDropShadowEffect`，别全局加） |

**对比度**：`--dim` 对白卡约 5.0:1，可做小字正文；`--faint` 约 3.2:1，只做辅助说明（若产品要求 WCAG AA，说明文字统一改用 `--dim`）。

---

## 6. 组件规范

### 6.1 输入 / 下拉（30 高）

| 状态 | 底 | 边 | 其他 |
|---|---|---|---|
| 默认 | `--input` | `--line` | 圆角 6，左右 9 内边距 |
| Hover | `--input-hover` | `--line-strong` | 150ms |
| Focus | `--input-hover` | `--accent` | 外圈 `0 0 0 3px rgba(accent,.14)` |
| Disabled | 同默认 | `--line` | 整体 55% 不透明 |
| Error | `--input` | `#D9534F` | 同 focus 的淡红外圈（本卡未用） |

下拉箭头用 6×6 的 45° 双边框，距右 11，**不要用系统原生三角**。

### 6.2 开关（36×20）

- 关：轨道 `#CBD3DB`（深色 `#3E444C`），白手柄 16，左 2 上 2。
- 开：轨道 `--accent`，手柄 `translateX(16px)`；过渡 180ms `cubic-bezier(.2,.8,.2,1)`。
- 键盘焦点：2px `--accent` 外圈、偏移 2。
- 开关旁的状态字用 11.5px `--faint`，**不要**在开关内写「开 / 关」。

### 6.3 胶囊

- 高 20，左右 8，圆角 999，1px 边。
- 状态胶囊：主题色 10% 底 + 26% 边 + `--accent-ink` 字 + 5px 圆点。
- 模型胶囊：等宽字体 10px，最大宽 200，超出省略。
- 前瞻徽标：9.5px，4px 圆角，弱化边色，不用胶囊形。

### 6.4 按钮

| 类型 | 高 | 用途 | 规格 |
|---|---|---|---|
| Primary | 30 | 保存并应用 | 主题色实底，白字（浅色主题色亮度 > 0.62 时改深字） |
| Ghost | 30 | 次操作 | 透明底 + 1px `--line`，hover 填 `--sub` |
| Small ghost | 26 | 测试接口 / 自动匹配 / 测试决策模型 / 查看详情 | 字号 11.5，左右 9 |

### 6.5 决策子卡

- 背景 `--sub`、1px `--line`、圆角 8、整体内缩 0。
- 头部 38 高：20×20 折叠钮 + 标题 + 徽标 + 状态（右对齐）+ 唯一总闸。
- 折叠：`chevron` 由下转右（-90°），体区 `max-height 240 → 0`、`opacity 1 → 0`、上下 padding 收起，260ms。
- 体区第一行两列（7/5），第二行独立凭据 + 测试按钮（填满整行）。
- **默认态建议**：`decision_enabled == False` 时收起；打开开关时自动展开。

### 6.6 实验项行 / 风险条 / Toast

- 实验项：38 高，标题 12.5/600 + 弱徽标 + 11.5 状态 + 右侧开关；与子卡间距 4。
- 风险条：32 高，13px 图标 + 11.5 文案 + 右侧「查看详情」，圆角 6，警示色三件套。
- Toast：底部居中，卡片底 + 1px 边 + 8px 圆角，8/13 内边距，2.2s 自动消失。

---

## 7. Qt / QSS 落地

### 7.1 布局：把 `srow` 换成固定标签列的 `QGridLayout`

现卡片的问题是 `BodyLabel` 自然宽度。本卡内部改用 4 列网格（标签 84 / 字段 / 标签 84 / 字段），**不要动全局 `srow()`**：

```python
# card() 返回的是 (UICard, QVBoxLayout)；标题由自定义卡头承担，不再让 card() 生成
box, lay = card()
box.setObjectName("GlobalAiCard")          # QSS 作用域
lay.setContentsMargins(18, 16, 18, 16)     # 仅本卡；card() 默认 14/12
lay.setSpacing(8)

grid = QGridLayout()
grid.setContentsMargins(0, 0, 0, 0)
grid.setHorizontalSpacing(12)
grid.setVerticalSpacing(8)
grid.setColumnMinimumWidth(0, 84)
grid.setColumnMinimumWidth(2, 84)
grid.setColumnStretch(1, 1)
grid.setColumnStretch(3, 1)

def field_label(text, parent, width=84):
    lab = CaptionLabel(text, parent)
    lab.setObjectName("FieldLabel")
    lab.setFixedWidth(width)
    lab.setTextColor(QColor(ui_theme.tokens()["text_dim"]))
    f = lab.font()
    f.setPixelSize(12)
    lab.setFont(f)
    return lab

# 行 0：启用 AI | 密钥
grid.addWidget(field_label("启用 AI", box), 0, 0)
grid.addWidget(self.ai_enabled, 0, 1, Qt.AlignLeft)
grid.addWidget(field_label("密钥", box), 0, 2)
grid.addWidget(self.ai_key, 0, 3)

# 行 1：接口地址整行（输入 + 行内次操作 + 单行说明）
ep = QWidget(box)
ep_lay = QVBoxLayout(ep)
ep_lay.setContentsMargins(0, 0, 0, 0)
ep_lay.setSpacing(4)
ep_lay.addWidget(row(self.ai_base, test_btn, match_btn, spacing=6))
ep_lay.addWidget(self.ai_hint)              # fit_caption 单行 + tooltip
grid.addWidget(field_label("接口地址", box), 1, 0, Qt.AlignTop)
grid.addWidget(ep, 1, 1, 1, 3)

# 行 2：文本 / 视觉模型
grid.addWidget(field_label("文本模型", box), 2, 0)
grid.addWidget(self.ai_model, 2, 1)
grid.addWidget(field_label("视觉模型", box), 2, 2)
grid.addWidget(self.ai_vision, 2, 3)
```

要点：

- 标签固定 84，**同一列输入框左边缘天然对齐**；不要再给输入框 `setMinimumWidth(160)` 之外的自适应逻辑。
- 「启用 AI」行只放开关 + 一行灰字，不要 `srow` 的拉伸尾巴。
- 地址行标签用 `Qt.AlignTop`，并给标签 6px 上边距，让文字与 30px 输入框的基线对齐。
- 长地址仍用 `expand_h()`（Expanding / 最小 160），保证窄窗不被裁；说明与输入同列，不单独占整行。

### 7.2 卡头与动作

```
QHBoxLayout：标题/副标题（VBox） | 状态胶囊 | 模型胶囊 | stretch | 未保存 | 保存并应用
```

- 标题 `StrongBodyLabel` 15px/600；副标题 `CaptionLabel` 12px `text_dim`，必须 `fit_caption()` 单行。
- 状态胶囊、模型胶囊：`QLabel#Chip` + QSS；文本随开关 / 模型输入实时更新。
- 保存按钮 `PrimaryPushButton`，`setFixedHeight(30)`；图标可保留 `FIF.SAVE`。
- 「有未保存的改动」用 10.5px 警示色 + 5px 圆点，放在保存按钮左侧，`_mark_ai_dirty` 时显示、`_ai_save` 后隐藏；不要塞进按钮行尾的 stretch 里。

### 7.3 唯一 Jev 总闸

现在 `self.ai_jev_switch` 与 `self.decision_enabled_switch` 是两个可见控件、同一语义。落地时：

1. 只保留 **一个可见开关实例**（建议 `ai_jev_switch`），放进决策子卡头部；
2. 删除顶部 `label_row("Jev 影子决策", ...)` 与子区 `label_row("决策模型启用", ...)` 两行，以及独立的 `self.ai_jev_hint` 行；
3. 原有 `checkedChanged → _on_jev_switch_toggled / _sync_plan_warn` 的连接全部保留；
4. 若 `_collect_ai` 依赖 `decision_enabled_switch.isChecked()`，改为读保留实例，避免两份状态；
5. 子卡头部右侧的状态文案**不要写死**：沿用现有 `ai_jev_hint` 的分支（客户端缺失 / 地址不符 / 密钥缺失 / 全局 AI 已禁用 / 满足条件），缩成 11.5px 单行，完整原因进 tooltip。预览里的「已关闭 · 不发起决策请求」只是其中一态。

### 7.4 折叠子卡

```python
class JevCard(QFrame):
    # objectName = "JevCard"
    # header: QToolButton(checkable) + 标题 + 状态 + switch
    # body:  QWidget#JevBody（上下两行网格 + 单行提示）
```

- 用 `QPropertyAnimation(body, b"maximumHeight")`：展开 `0 → body.sizeHint().height()`，结束后 `setMaximumHeight(16777215)`；收起 `当前高度 → 0`。
- 不要用 `setVisible(False)` 直接切（会跳变，且滚动区会重排两次）；也不要在滚动区里用 `heightForWidth`。
- 动效 260ms、`OutCubic`；`prefers-reduced-motion` / 低性能档可直接切换。

### 7.5 单行说明（关键约束）

本页在 `QScrollArea` 内，`QLabel` 自动换行会触发 `heightForWidth` 与滚动区互相重排（项目里已有前车之鉴，见 `widgets.fit_caption` 注释）。因此：

- 所有说明统一 `fit_caption(CaptionLabel(...))` + `setWordWrap(False)`；
- 完整文案写进 `setToolTip()`；
- 绝不为「让说明显示全」去开 `wordWrap` 或 `setMinimumHeight`。

### 7.6 风险条

```python
warn = QFrame(box); warn.setObjectName("AiPlanWarn")
warn.setFixedHeight(32)
# QHBoxLayout: 13px 图标 + caption + 「查看详情」flat button
```

- 显隐仍由 `_sync_plan_warn()` 决定（地址含套餐端点才显示），**不要**改成常显；
- 文案保持单行，`查看详情` 可打开 `MessageBox`（现有 `vt_fluent.MessageBox`）或直接复用 tooltip；
- 颜色用 token + `ui_theme.connect_theme` 重刷。

### 7.7 QSS 片段（仅本卡作用域）

```css
#GlobalAiCard QLineEdit,
#GlobalAiCard QComboBox {
    min-height: 28px;          /* + 2px 边框 = 30 */
    max-height: 28px;
    padding: 0 9px;
    border-radius: 6px;
}

#GlobalAiCard QLabel#FieldLabel {
    min-width: 84px;
    max-width: 84px;
}

#GlobalAiCard QFrame#JevCard {
    background: #F8FAFB;
    border: 1px solid #E1E4E8;
    border-radius: 8px;
}

#GlobalAiCard QFrame#JevCard QLineEdit,
#GlobalAiCard QFrame#JevCard QComboBox {
    background: #FFFFFF;       /* 子卡上的输入要提亮一阶 */
}

#GlobalAiCard QLabel#Chip {
    border-radius: 9px;
    padding: 1px 8px;
    border: 1px solid #E1E4E8;
    background: #F6F8FA;
    color: #697077;
}

#GlobalAiCard QFrame#AiPlanWarn {
    background: #FFF7E8;
    border: 1px solid #F0DFC2;
    border-radius: 6px;
}

#GlobalAiCard QPushButton#MiniGhost {
    min-height: 24px;          /* 视觉 26 */
    max-height: 24px;
    padding: 0 9px;
}
```

注意事项：

- `PrimaryPushButton` / `SwitchButton` / `ComboBox` 在 qfluentwidgets 里是自绘控件，**QSS 背景不生效**；高度用 `setFixedHeight`，颜色交给 `setThemeColor`，不要硬写 background。
- 深色主题不能只写死浅色 hex：上述 QSS 需按 `ui_theme.tokens()` 模板化，并在 `connect_theme` 里重新 `setStyleSheet`。
- `QLineEdit` 的 28px 是「内容高度」，加 2px 边框正好 30；若直接写 30 会变成 32。

---

## 8. 迁移对照

| 原版 | 新版 | 备注 |
|---|---|---|
| `label_row("启用 AI", row(switch, None))`（label 自然宽 + 尾部弹性） | 栅格第 0 行第 1 列 | 开关紧跟标签，灰字说明接在后面 |
| `srow("密钥", …)` | 第 0 行第 2 列 | 密码框占满本列，不回填明文 |
| `srow("接口地址", …)` 独占整行 | 第 1 行整行 + 测试/自动匹配行内 | 两个次操作从按钮行迁来 |
| `srow("文本模型")` / `srow("视觉模型")` 各一行 | 第 2 行双列 | 短字段并列 |
| `row(test_btn, match_btn, save_btn, dirty_lbl)` | 保存进卡头；测试/匹配进地址行；dirty 进卡头 | 主操作唯一 |
| `self.ai_hint`（3 行长说明） | 单行 hint + tooltip | 仍保留全部端点信息 |
| `label_row("Jev 影子决策")` + `label_row("决策模型启用")` | 决策子卡头部唯一开关 | 删掉重复入口 |
| 决策区四行 + 独立测试按钮 | 子卡两行 + 行内测试 + 单行说明 | 收起后只留 38px 头 |
| `label_row("第二音色影子")` + caption | 38px 单行实验项 + tooltip | 说明不占第二行 |
| `self.ai_plan_warn`（红色 caption 在卡底） | 32px 警示条 + 查看详情 | 仍按端点条件显隐 |

---

## 9. 验收清单

- [ ] 1040 宽下卡高 ≤ 480（展开）/ ≤ 360（收起），页面不出现横向滚动。
- [ ] 同一列（密钥 / 文本模型；密钥右列 / 视觉模型）输入框左边缘像素级对齐，标签列宽恒为 84。
- [ ] 长 URL、长模型名不撑宽卡片；聚焦时输入框不被裁。
- [ ] 只有一个可见的 Jev 总闸；开关状态与保存值一致。
- [ ] 「未保存」只在编辑后出现，保存后消失；保存仍调用 `_ai_save` 并写入字幕引擎。
- [ ] 浅 / 深 / 跟随系统三档切换后，子卡、警示条、胶囊颜色全部跟随，无浅色残留。
- [ ] 说明均为单行省略 + tooltip，滚动区内无 `wordWrap` 标签。
- [ ] `PasswordLineEdit` 仍不回填明文，空值表示「保持现值」。
- [ ] Tab 顺序：启用 → 密钥 → 地址 → 测试 → 自动匹配 → 文本 → 视觉 → Jev → 模式 → 端点 → 凭据 → 测试决策。
- [ ] 窄于 820 单列、窄于 720 标签上置时，卡头按钮不溢出。

---

## 10. 落地顺序建议

1. **先换布局**：`_build_ai_card` 内改 `QGridLayout` + 固定标签列，去掉本卡的 `srow` / 尾部 stretch；视觉收益最大、风险最小。
2. **再收开关**：删两处重复行，保留单实例，验证 `_collect_ai` 与 `_sync_plan_warn`。
3. **然后做子卡**：`QFrame#JevCard` + `QToolButton` + `maximumHeight` 动画。
4. **最后做胶囊 / 警示条 / Toast**：纯展示件，放最后做主题回归。
