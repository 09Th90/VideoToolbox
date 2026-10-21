<!-- @version 2.5.1 -->
# calib_entity —— 对象级校准（已部署）

> **部署位置**：`src/calib_entity/`（2026-10-19 从根目录迁入）。
> `calib_ai_agent.py` 三处接入（作品隔离 / 外文名降级 / tag 佐证并入标题），
> spec 已登记 `collect_submodules('calib_entity')`，一键回退 `VT_CALIB_OPT=0`。
> 底层仍**只读** `subtitle_calib_merged.py`，不改它一行。

## 为什么要有这一层

评估结论（详见 `docs/校准对象级能力评估_2026-10-18.md`）：

- 知识层已经对象化了（`Entity` 538 条），但**执行层是纯字符串替换**——`process()` 313 行里
  `Entity`/`ENTITIES`/`canonical`/`category` 零引用（唯一命中在注释）；
- `_register_entities()` 是**单向投影**：实体 → 扁平表，没有反馈回路；
- 结果：一个错形只能对应一个目标；歧义靠「规则书写顺序」模拟；`kb_view()` 还有两个实际 bug
  （重复登记时 later-wins 覆盖 `en/ja/ko`、纯元数据对象 modes 丢失）。

本包先把**不改变任何输出**的三件事做掉（P0 + P1）：

| 能力 | 解决什么 |
|---|---|
| `spec` | 折叠出唯一对象库：去重、补 modes、`aliases` 与 `variants` 分字段、导出 JSON |
| `index` | 按模式建 Aho-Corasick：一次扫描得本行候选键 + 命中对象，去掉「长键必须写在短键前」的顺序合同 |
| `shadow` | 证明「索引预筛无损」（逐字节比对），并量化「单遍 vs 串行」的语义分叉 |
| `lint` | 对象级体检：重复身份 / 一词多目标 / 短键抢跑 / 别名混装 / 子串级联 |

## 目录

```
src/calib_entity/
  __init__.py
  spec.py          对象规格层（折叠/去重/kind/modes/别名候选/JSON 导出）
  index.py         Aho-Corasick + ModeIndex（候选预筛、单遍最长替换、串行复现）
  shadow.py        影子双跑（等价性验证、语义分叉量化、Markdown 报告）
  lint.py          对象级体检（error/warn/info 三级）
  cli.py           命令行入口
  _selftest.py     自检（45 项：正向 + 负向，含 opt 补丁）
  _baseline.json   工作树实测基线（仅工作树有；缺失则自检改跑结构不变式）
  opt/             优化补丁集（对应 2026-10-19 思考链评估的四个失效点）
    source_guard.py  片源识别：标题/文件名/台词三通道
    kb_scope.py      作品维度隔离（对象级 + 词条级）
    kb_inject.py     注入安全化：外文官方名不该当错形
    adopt.py         采纳 .calib.md 第四节的官方中文核对
```

## 优化补丁（opt/）——从评估到可执行

2026-10-19 的思考链对比定位了四个失效点，`opt/` 各对应一个：

| 失效点 | 模块 | 命令 |
|---|---|---|
| 片源识别失败（终末地词条整表没加载） | `source_guard` | `cli.py source <srt>` |
| 跨作品词条污染（`Mizuki→水月` 注入终末地片） | `kb_scope` | `cli.py scope --work 终末地` |
| 外文官方名被当错形（同一根因的另一半） | `kb_inject` | `cli.py inject --mode bi` |
| 报告识别了、产物没落盘 | `adopt` | `cli.py adopt <md> --apply <srt>` |

### 实测（终末地 Si 片源）

**片源识别**

```
$ cli.py source "...Si.en-谷歌翻译.calib.r2.srt"
片源模式：endobi  置信度 high  作品 终末地
  依据：标题命中 endfield, arknights: endfield
```

同一句「好的，操作员文件。」在两种表下的结果：

| 模式 | 键数 | 结果 |
|---|---|---|
| `bi`（实况） | 1685 | 原样不动 |
| `endobi`（修正） | 570 | 「干员文件」 |

**注入规则规模**

| 口径 | 规则数 | 外文名当错形 | 其中纯拉丁 |
|---|---|---|---|
| `bi`（实况） | 3452 | 204 | 139 |
| `bi` + 作品隔离 | 2651 | 121 | 72 |
| `endobi` + 作品隔离（修正后） | **874** | **6** | **2** |

**采纳报告**：解析 2 条 → 采纳 2 条 → 应用 1 处（`操作员文件 → 干员档案`），
字节 6781→6778、CRLF 292 行不变、仅 1 行中文变化。

### 根因备注

`calib_ai_agent.build_rules()` 第 386-389 行把实体的 `en/ja/ko` 直接 append 进
「错形」列表，于是规则表里出现 `Mizuki → 水月`。`select_rules()` 再按「错形出现在
参考行」判 warm —— 本片参考行有 `Mizuki Shigeru`，必然注入。模型据此把「水木茂」
改成「水月茂」。

`kb_inject.build_rules_safe()` 把外文名降级为**锚点**（只用于判断「这段在讲这个实体」），
不再作为替换指令；配合 `kb_scope` 的作品隔离，才算把这条链路堵住。

## 用法（cwd = 程序根）

```bash
# 对象库摘要 / 导出
python src/calib_entity/cli.py summary
python src/calib_entity/cli.py export --out data/entities/entities.json

# 对象级体检（--fail-on error 可当门禁）
python src/calib_entity/cli.py lint --fail-on error
python src/calib_entity/cli.py lint --out data/tmp/kb_lint.md

# 索引规模
python src/calib_entity/cli.py index --mode bi

# 等价性验证：必须 EQUIVALENT / EQUIVALENT_WITH_FALLBACK（exit 0）
python src/calib_entity/cli.py verify outbox/xxx.srt --mode bi

# 语义分叉量化：单遍最长 vs 串行（差异属预期，exit 0）
python src/calib_entity/cli.py onepass outbox/xxx.srt --mode bi

# 自检
python src/calib_entity/_selftest.py

# 优化补丁
python src/calib_entity/cli.py source <片源.srt>                       # 片源识别
python src/calib_entity/cli.py scope --work 终末地 --mode bi --explain "Mizuki,操作员"
python src/calib_entity/cli.py inject --mode bi --work 终末地          # 注入规则瘦身
python src/calib_entity/cli.py adopt <报告.md> --emit ENDFIELD_BI_TERMS
```

也可 `python -m calib_entity.cli <子命令>`。

## 实测（2026-10-18，本机）

**体检**（真实库）：`error 102 / warn 27 / info 1570`

| 检查项 | 数量 |
|---|---|
| `dup_canonical` | 47（多余条目 109） |
| `longkey_order` | 38 |
| `multi_target` | 17 |
| `alias_candidate` | 5 个对象（NTE / COD / MSR / MJO / LF1+ALF，均有 note 依据） |
| `self_substring` | 6 |
| `cascade_substring` | 2 |
| `hollow` / `hollow_ost` | 14 / 134 |

**等价性验证**（5 个成品 × 4 种模式，各抽前 800 行）：

| 片源 | 模式 | 规模 | verdict |
|---|---|---|---|
| WISH GRANTED!! Hsin 3.7 | bi | 全量 4682 行 | `EQUIVALENT_WITH_FALLBACK`（差异 1 行） |
| WuWa Exploration Quests | bi | 全量 8697 行 | `EQUIVALENT_WITH_FALLBACK`（差异 2 行，2.6 s） |
| ADHD REACTS 3.7 | bi | 800 行 | `EQUIVALENT` |
| RHODES ISLAND（终末地） | endobi | 710 行 | `EQUIVALENT` |
| 方舟PV | ak | 628 行 | `EQUIVALENT` |
| 鸣潮梦州 | ko | 800 行 | `EQUIVALENT` |

差异行回退全表重跑后 **100% 复现基准**（`fallback_ok == differ`），这是 `verify` 允许
`EQUIVALENT_WITH_FALLBACK` 的充要条件。

唯一差异行（全量样本 line 10674）值得留档：

```
原文   : ' Cause Qing Xiao ' s still here.
串行   : ' Cause 清宵' s still here.      ← 命中 Qing Xiao，随后「清宵 」(带空格) 二次命中，吃掉空格
单遍   : ' Cause 清宵 ' s still here.     ← 只命中 Qing Xiao
```

说明两件事：

1. **索引预筛不是天然无损**：串行替换会造出新键（目标名含另一个键），所以 `shadow.verify`
   必须保留「差异行回退全表重跑」的兜底——本项目实测兜底率 1/4682（0.02%），性能无感。
2. 旧引擎里存在**靠二次命中实现去空格**的隐式行为（`清宵 ` → `清宵`）。这类键本质上是
   ASR 断词问题，应由独立的断词归一步骤处理，而不是塞进术语表当副作用。

## 安装版实测（D:\VideoToolbox2.3.0，2026-10-19）

安装目录有 `subtitle_calib_merged.py` 但**没有 tools/python**（运行时在 onefile exe 里），
用工作树解释器 + 切 cwd 即可运行，不需要给安装版装 Python：

```bash
cd /d/VideoToolbox2.3.0
VT_DATA_ROOT="D:/VideoToolbox2.3.0" VT_NO_SYNC=1 \
  "D:/Agent Work/软件开发/视频工具箱/tools/python/python.exe" calib_entity/cli.py summary
```

| 项 | 工作树 | 安装版 v2.3.0 |
|---|---|---|
| 对象总数 | 1773 | 1766 |
| 有对象身份 | 429（24.2%） | 418（23.7%） |
| 变体 / ctx | 3920 / 2097 | 3861 / 2058 |
| 重复登记 | 47 个（多余 109） | 45 个（多余 89） |
| lint | error 102 / warn 27 | error 99 / warn 24 |
| 自检 | 25 PASS（精确基线） | 24 PASS + 1 SKIP（不变式） |

差异来源：工作树有 10-16~10-18 未提交的校准沉淀——多 7 个对象（乔比、余烬、使命召唤、
偶像、少女前线、明日方舟骑士、边缘行者），26 个对象变体增长（佩丽卡 +7、罗德岛 +5），
鸣潮 ctx +14。

等价性在安装版同样成立：`bi` 全量 4682 行 → `EQUIVALENT_WITH_FALLBACK`（1 行差异、回退可复现），
`endobi` 710 行 → `EQUIVALENT`。安装版主链路 `src/agent_cli.py calibrate` 未受影响。

**部署安全性**：`check_install_sync.py` 按 iss 清单逐个比 sha256（不扫描额外文件），
`vt_installed.json` 程序运行时不读 ⇒ 新增 `calib_entity/` 不会触发任何校验告警。

## Wiki 补全（wiki/）

对象库 1773 个对象里只有 305 个能说清自己属于哪个作品（17.2%），作品隔离因此只能覆盖一小半。
`wiki/` 从四个游戏的 wiki 抓角色/专名名单，回填作品归属。

| 作品 | 源 | 抓取的分类/前缀 | 条数 |
|---|---|---|---|
| 明日方舟 | wiki.biligame.com/arknights | `Category:干员` | 434 |
| 战双帕弥什 | wiki.biligame.com/zspms | 构造体 / 人物 / 世界观人物 + `世界观/`、`人物档案/` 前缀 | 724 |
| 鸣潮 | wiki.biligame.com/wutheringwaves | 共鸣者 / 声骸 / 敌人 / 武器 + `名词注释/`、`设定拾遗/` 前缀 | 739 |
| 终末地 | endfield.wiki.gg | Operators / Characters（英文名） | 244 |

**结果**

```
对象 1773 | 作品标注 305 (17.2%) -> 430 (24.3%)
  wiki 命中 236，其中 125 个是原本无 category 的真补全
  置信度 high 180 / medium 2 / low 54，跨作品冲突 6
```

隔离效果（把补丁应用到内存副本后重跑 `kb_scope`）：

| 片源作品 | 隔离的专名数 |
|---|---|
| 终末地 | 103 → **198** |
| 鸣潮 | 45 → **125** |
| 明日方舟 | 60 → **84** |

**置信度口径**

- `high`：来自角色类分类（干员/构造体/共鸣者/人物/Operators）——专名密度高
- `low`：来自 `名词注释/`、`世界观/` 这类前缀——含大量通用词（回音/代行者/守林人），
  会与其它站重名，需人工过一遍
- 跨作品同名（艾拉/芳汀/守林人/代行者/佩洛/回音）两边都是 high 时判为歧义，**不采用**

**已知上限**：1537 个对象 wiki 匹配不到，其中 1219 个连 category 都没有——
这些多是机翻错形目标（「那个贝斯」「贝斯下降」）、复合词、或未覆盖的作品（异环/边狱巴士等）。
wiki 只能补「有正式词条的对象」，长尾仍需人工或从其它数据源补。

**反爬注意**：B 站 wiki 缺 `Referer` 直接返回 **HTTP 567**（实测），`WikiClient` 已自动带上。

## 已部署到主程序（2026-10-19）

| 接入点 | 代码位置 | 行为 |
|---|---|---|
| A 作品隔离 | `calib_ai_agent.build_rules(work=...)` | 从文件名/标题推断作品，拦下跨作品专名实体 |
| B 外文名降级 | 同上 `include_names=False` | `en/ja/ko` 不再进错形表，只作锚点 |
| C tag 佐证 | 片源档案 `hay_zh/hay_en` 拼接 | 原始标题并入佐证池 |
| D 官方核对采纳 | `calibrate` 第 9b 步 | 报告第四节「把握=高」条目落盘，应用后重跑 verify |

**D 的采纳条件**（全部满足才改产物）：把握=高 · 目标是中文 · 错形 2~8 字 ·
错形确实出现在产物里。应用后立刻重跑脚本 `verify`，不通过则整批回滚
（用 `.preopt` 备份）。实测：

| 场景 | 结果 |
|---|---|
| 「操作员文件→干员档案」「操作员→干员」 | 采纳 2 条，实际改 1 处（长键先吃），字节 6781→6778，CRLF 292 行不变 |
| 英文目标（`Eso`）/ 低把握 / 片中未出现 / 超长短语 | 4 条全部跳过 |
| 结构损坏的产物 | verify 失败 → 整批回滚，文件未被进一步修改 |

实测（`kb-export` 全量 1773 实体，bi 模式）：

| 口径 | 规则数 | 排除 | `Mizuki` 是否在规则里 |
|---|---|---|---|
| 旧行为 | 2224 | 51 | ✅ 在 |
| 剔外文名 | 2088 | 51 | ❌ 无 |
| 终末地 + 剔 | **1259** | 10 | ❌ 无 |

tag 实测（正文不提作品名的终末地片）：

| 佐证池 | 结果 |
|---|---|
| 只用正文 | 「终末地」被判幻觉剔除，10 个 tag 无作品名 |
| 正文 + 标题 | 「终末地」「明日方舟」都保留 |

一键回退：`VT_CALIB_OPT=0`（模块级开关；包导入失败也自动降级为旧行为）。

## 本包不做的事（边界）

- 不改 `process()`、不接管 ctx 佐证、不处理 `learned_kb` 注入与片源自适应
  （那些是 P2 的活，换语义，必须单独立项）；
- 不擅自把 `alias_candidate` 提升为 `aliases`——只标记，人工确认后才改语义；
- 不重构 `ENTITIES` 源码结构（去重后的对象库是 JSON 视图，原源码仍是权威）。

## 合并路径（验证通过后）

1. `spec.py` → `src/calib_entity/spec.py`，`process()` 改为「从 registry 取对象」；
2. `index.py` → 在 `process()` 里用 `ModeIndex.candidates()` 预筛 ctx 规则
   （ctx 仍需按原顺序执行，只减少遍历量）；
3. `shadow.py` 的 `verify` 固化为发布前门禁（等价性必须 exit 0）；
4. `lint.py` 接进 `kb-lint`，把 `dup_canonical` / `multi_target` / `longkey_order` 升为阻断项；
5. 打包：登记 `hiddenimports`，跑 `check_deps.py` 确认口径。

合并前必须满足：`_selftest.py` 24/24 + 7 个成品 `verify` 全 `EQUIVALENT*` + `kb-lint` error 可解释。
