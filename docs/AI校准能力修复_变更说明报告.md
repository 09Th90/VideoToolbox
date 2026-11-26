<!-- @version 3.3.1 -->
# AI 校准能力修复 · 变更说明报告

- 日期：2026-11-24
- 触发：实测鸣潮 4.0 新联邦实机 reaction 片（251 cue），工具箱 AI 校准第二轮 **采纳 0 处**，远逊第三方整句重写（241 条）。
- 范围：P0（破 0 采纳）+ P1（堵污染 + 一致性）**已完成并验证**；P2（架构重构）**部分完成 + 分期清单**。
- 硬约束：**零 GUI 改动**（page.py / settings_page.py 未触碰）；允许前后端暂不统一，前端由用户手动补（清单见 §5）。
- 改动规模：16 个后端文件，+1954 / -84 行（含本任务前已存在的在途改动）。

---

## 1. 根因（诊断结论）

| # | 根因 | 机理 |
|---|---|---|
| ① | term 默认禁改写 | 系统提示词只许换名词，机翻腔句子级问题结构性改不动 |
| ② | 查证与采纳断裂 | `validate_change` 只认静态 KB canonicals，联网查到的官方名进不了闸门 |
| ③ | resume 空 KB 死锁 | 二轮基线吃光已知错形 → hot=0 → 逐块注入 KB 为空 |
| ④ | 拒绝静默无回路 | 闸门拒绝只记报告，模型无机会整改 |
| ⑤ | 逃生门自锁 | suggest_rewrite 需 ≥6 条拒绝，但 term 提示词抑制重写提议 |
| ⑥ | 污染入口 | AI `_candidates` 穷举短键先行候选（机械替换器本身正确）；learn 错误沉淀跨片自动 confirmed |
| ⑦ | 盲替换 | INCLUDE_REF_MODES 漏 wuwa-40*/ak-arcaea，参考行不喂 |
| ⑧ | 官方核对窄通道 | build_meta 裸 chat 无联网，新名全标 low → 采纳条件（high）全跳过 |

## 2. 已完成并验证（P0 + P1）

### P0 · 破 0 采纳
| 改动 | 文件 | 说明 |
|---|---|---|
| 结构化检索 + 统一分级 | calib_web_agent.py | `search_structured`（title/url/tier/snippet/exact）；`tier_key_of` 统一分级，补 kurobbs.com，消除「同页两级别」矛盾；search/fetch 文本逐字不变 |
| 证据入闸门 | calib_ai_agent.py | 会话 `verified_evidence`（仅 official/wiki 级）；`validate_change/rewrite` 加 `verified_evidence` 参；`_verified_hit` 三条件（≥2 字 / 不在原文 / 与 diff 新区间相交）防公共前缀误放 |
| 确定性候选 | calib_ai_agent.py | `_longest_match_replace` + `_candidates` 改最长匹配唯一结果，拦「西吉兰机甲→西格莉卡兰机甲」污染 |
| 机翻腔自动 rewrite | calib_ai_agent.py + core/calibrate/ai.py | hot==0 双语片自动切 rewrite；ai.py 默认 term 视为未锁定传 None 启用自动路由 |
| 拒绝整改回路 | calib_ai_agent.py | `build_reject_feedback` + 每块最多 1 次反馈重问 |
| 参考行补全 | calib_ai_agent.py | INCLUDE_REF_MODES 补 wuwa-40ko/ign/pv/reveal、ak-arcaea |
| resume 空 KB 破解 | calib_ai_agent.py | `fallback_rules_text` 注入官方名全集 + 会话证据 |
| build_meta 联网佐证 | calib_ai_agent.py | `_verify_official_terms_web`：低把握干净中文官方名经 A 级来源佐证升 high → 可采纳 |
| web 默认启用 | tools/ai_client.py | `calib_web_enabled` 默认 True（证据通道开箱即用） |
| 退全量告警 | calib_ai_agent.py | `build_rules` len<10 退全量显式告警（仅 pgr=0 触发） |

### P1 · 堵污染 + 一致性
| 改动 | 文件 | 说明 |
|---|---|---|
| 机械冲突闸门 | calib_merge_core.py + build_calib_monolith.py | `term_registry_conflicts` 三检（同表长键二次命中 / 孤儿短键切碎官方键 = hard，角色名共存 = warning）；构建期硬闸；**23 条孤儿污染补长键修复归零**（hard 0 / warn 27） |
| 数据表修复 | bilingual/ark/endfield/misc/ja/ko.py | 补长键（Exostrider→隧者、CloudEndfield→云·终末地、Luciana→露西亚 等），保字面量序 |
| learn 状态机加固 | learn.py + cli.py | 版式修复（`_cue_zh_ref` 兼容英文在上）；count 按源文件去重（`__legacy__` 迁移）；uncorrected 分文件可重置；`_canonical_collision` 撞名审查（应用形态、≥3 字官名子串 + ≥2 共享字编辑距、存量祖父条款）；单片快路径（canonicals/--force）；命中内建表改 conflict 标记非静默删；CLI `--force` |
| 跨 cue 一致性 pass | calib_ai_agent.py | `_cross_cue_consistency` 纯字符串全片扫书名号断裂 / 相邻重复 / 同源异译，报告-only（三b 小节），不自动改产物 |
| audit 交付门禁 | kb.py + calib_ai_agent.py | `audit_gate_findings`（附加函数，零漂移安全）；calibrate 8d 段取高置信残留机械补校 + 重验 + 回滚保护；无锚点判 inconclusive |

## 3. 验证汇总

| 项 | 结果 |
|---|---|
| AI 链自检 `_selftest_calib_ai.py` | 全过（W1-① 14 例 + W1-② 29 例 + 既有，含证据闸门 / 确定性候选 / 自动路由 / 整改回路 / 参考行 / 退全量） |
| calib_core 自检 `_selftest_calib_core.py` | **PASS 608 / FAIL 0**（learn + 数据表 + 冲突闸门无回归） |
| monolith 重建 `--check` | **CHECK OK**（hard 0 / warn 27 共存对） |
| 本片实测 `--wuwa40reveal` | 242 处改动；**西格莉卡兰 0 / 西吉兰 0 / 永明官员 0**；隧铠 4 / 永明的烬焰 1 / 露希尔 5 / 小沧龙 5 / 普罗米厄 2 / 塔图因 4 / 莫斯艾斯利 5 |
| **不动点证明** | 复跑 SHA256 `7302F91C01BAA850…` 与第三方过程文档 §4.9 记录的 v2 终稿 SHA **完全一致**——逐字节复现批准终稿 |
| 重建后零漂移回归 | **PASS 608 / FAIL 0**（monolith 重建后 ref≡pkg 行为 parity 确认） |

> 13 一键重跑片 A/B：本机仅 wuwaall 等少数片源在位，其余源文件缺失无法全量 A/B；wuwaall 仅 Exostrider 属修复方向。完整 A/B 需在片源齐备环境补跑。

## 4. P2 架构重构 · 分期清单（设计就绪，需专门回归批次）

本次已完成 P2 的 `audit_gate_findings` 门禁函数与本片不动点（经侧车）。以下为**尚未落地**的架构重构，按计划需 13 片逐字节 A/B + 零漂移兜底，建议独立批次推进：

| 项 | 设计要点 | 风险 |
|---|---|---|
| 注册表图层驱动 | MODE_REGISTRY 加 layout/layers/markers/sidecar；engine.py:109-112 硬编码集合改读注册表；新模式 1 处注册 | 33 模式行为对齐，需全量 A/B |
| ctx 索引化 | CONTEXT_MAP wrong 建 Automaton（复用 acindex），scan 候选再正则，保原序 + 重扫语义 | 语义等价须证明 |
| 知识单源统一 | 以 kb._kb_view 为唯一真源，engine/audit/AI 统一消费；修 audit 口径<执行口径（ak-ja 并表）；五库（扁平/ENTITIES/learned/侧车/wiki_supplement/applied）收敛 | 迁移 + 热路径预编译 |
| 会话级回灌机制 | 查证确认新词当轮固化（真源→重建→CHECK）+ 回灌后复跑 SHA 门禁（通用机制，本片已经侧车达成） | 与 sync 通道语义对齐 |
| detect 表驱动 | markers 打分合一 modes.py:35 与 engine.py:275；侧车加 cue 数 + 首末序号签名校验 | detect 行为变更需回归 |
| 引擎证据包 | 每行附 applied[(wrong,right,来源,ctx)] JSON 侧车 → AI base/prompt/validate 消费，破「基线改完即无据」 | 接口新增 |

## 5. 前端手动补接线清单（本次零 GUI 改动，允许暂不统一）

| 前端项 | 位置 | 需补内容 |
|---|---|---|
| 风格自动路由说明 | settings_page.py calib_style 卡片 | 默认 term 现含「hot==0 自动切 rewrite」语义；界面宜注明「自动」档，避免用户误以为 term 恒不改写 |
| web 默认值 | settings_page.py:1500/1667 | `calib_web_enabled` 默认已改 True；界面默认勾选态同步 |
| 跨 cue 一致性呈现 | 校准报告视图 | 报告新增「三b、跨 cue 一致性候选」节，界面若渲染报告需兼容 |
| audit 门禁呈现 | 校准日志/报告 | 新增 8d audit 门禁日志（机械补校 N 处 / inconclusive），界面日志透传即可 |
| 新配置键白名单 | settings_page.py 收集 + DEFAULT_CONFIG | 本次未新增配置键（跨 cue/audit 恒开）；若后续加开关须进 DEFAULT_CONFIG 白名单，否则保存被重置（D 探测结论） |
| 模式列表核对 | page.py MODES | wuwa-40reveal 已存在（前序任务加入），核对显示名一致 |

## 6. 残留风险与后续

- **`_verified_hit` 精度**：取最长有据子串，理论上「半佐证前缀」可能放行未佐证全名（如「永明的烈焰」借「永明的」）。可选硬化「佐证片段须覆盖改动区间主体」，但需权衡召回（过严退回 0 采纳），列为后续。
- **P2 架构重构**：见 §4，建议独立批次 + 全量 A/B。
- **13 片 A/B**：片源齐备环境补跑。
- **reaction 残留**：第三方终稿故意保留 reaction/3.x（口语/版本号），audit 扫 1 会报但属白名单判断，非缺陷。

## 7. 改动文件清单

```
src/features/calibrate/calib_ai_agent.py   (+681)  证据闸门/确定性候选/自动路由/整改回路/参考行/resume/build_meta佐证/跨cue/audit门禁
src/features/calibrate/calib_web_agent.py  (+88)   结构化检索/统一分级
src/features/calibrate/calib_merge_core.py (+284)  机械冲突闸门
src/calib_core/learn.py                    (+221)  状态机加固
src/calib_core/kb.py                       (+65)   audit_gate_findings
src/calib_core/cli.py                      (+14)   learn --force
src/calib_core/data/{bilingual,ark,endfield,misc,ja,ko}.py  污染长键修复
src/core/calibrate/ai.py                   style=None 自动路由接线
tools/ai_client.py                         calib_web_enabled 默认 True
scripts/dev/build_calib_monolith.py        (+24)   构建期冲突硬闸
scripts/dev/_selftest_calib_ai.py          (+305)  新用例
```

## 8. 交付后回归修复（2026-11-25 实测 PGR 片暴露）

### 8.1 陈旧 monolith（审查抓出）
- 现象：上一会话末次 src 改动后未重建产物 → shipped monolith 含旧 `_MODE_NAMES`（12 旧别名键）→ 一键复跑报「MODE_REGISTRY 与视图不一致」、`--check` FAIL。
- 处置：重建 monolith → CHECK OK、本片不动点 SHA `7302f91c…ce9ad` 保持、core 双跑 608/0。**src 代码无误，纯流程疏漏**。
- 教训：交付前必须「重建 → --check → 本片复跑 SHA」三连终验（建议固化进发布门禁）。

### 8.2 整片单块超时 + 内容审核盲目重问（本轮改动引入，已修）
- 根因：自动改派 rewrite 发生在分块**之后**，249 条双语片先按 term 预算（400/60000）切成 1 巨块；rewrite 整片单块输出巨大 → 300s 无响应超时；`data_inspection_failed` 400 被当「无效 JSON」盲目重问同内容 → 再被拒 → 超时 ×3 空转。
- 修复（`calib_ai_agent.py`）：
  1. **rewrite 收紧分块**：路由后按最终 style 重切，`REWRITE_CHUNK_CUES=60 / REWRITE_CHUNK_CHARS=16000`（249 条→5 块）。
  2. **内容审核二分隔离**：`_is_content_inspection` 识别永久拒绝，二分隔离（小块更易过审）而非重问，单条跳过。
  3. **超时多条块二分**：`_is_timeout` 识别 300s 超时，多条块二分而非重问同一超时块。
- 验证：针对性测试全过（内容审核二分无重问 / 超时二分 / 249 条 term 1 块→rewrite 5 块）；py_compile ✓；重建 CHECK OK；AI 链自检全部通过（0 FAIL）。
- **生效条件**：GUI 进程已加载旧代码，**须重启工具箱**下一轮 GUI 校准才生效；CLI 走重建 monolith 已生效。

## 9. 流水线校准重构 + 发布素材新功能（2026-11-25）

### 9.1 一校改 AI 精确校准（Part 1）
- `pipeline._stage_calib1_run`：由机械脚本改为 `engine.calib_ai_run(round_no=1, style="rewrite", mode_flag="", task_instruction=CALIB1_INSTRUCTION)`，检索官方/wiki + 名词精译 + 上下文优化，自动选游戏模式。
- 自定义指令通道：`calib_ai_run`/`calibrate` 增 `task_instruction` 参，经 `_run_block` 的 `scope_text` 前置注入 `build_user_prompt`（全链透传，无需改 `_ask_block` 签名）。
- 复用指纹方法版本：`_fingerprint/_reusable/_mark_reusable` 增 `method` 参（注入 `__method__` 键），一校 `ai1`/二校 `ai2`/publish `pub1`，旧机械产物不被误复用。

### 9.2 二校 + 脚本同步优化（Part 2）
- `_stage_calib2_run`：`calib_ai_run(round_no=2, resume_from=src, task_instruction=CALIB2_INSTRUCTION)`；临时置 `VT_SESSION_PROMOTE=1`（用完还原）启用会话固化，把确认改动同步进真源 ENTITIES + 重建 monolith（带撞名审查/回滚守卫）。

### 9.3 按片源自动选游戏模式（Part 3）
- detect 打分基础设施已存在（`modes.detect_mode_score` 按 MODE_REGISTRY markers 取 top1）；本次给 `pgr-en/ak/limbus/gfl2` 补高判别 markers。PGR 片实测认出 `pgr-en`（战双/帕弥什/PGR 3 命中）。wuwa-ja/ko 保持语言专属（英文鸣潮本走 bi 含鸣潮术语）。

### 9.4 发布素材新功能（Part 4，流水线阶段 + 独立命令）
- 新包 `src/features/publish/`：`publish_material.py`（后端）/`feature.py`/`cli.py`/`page.py`；`_api/commands/publish.py` 编排；`_api/__init__.py` + `spec.py` 登记（parity 三方一致）。
- CLI：`agent_cli publish <srt> [--video --game --streamer --title-en --out]`。
- 后端 `generate_material`：解析带时间戳字幕 + ffprobe 时长 + LLM 一次调用 → 代码侧强制约束（标题【游戏名】钩子【主播名】≤80字、10 tag 去标题词补足、10 章节首0/≥5s/≤16字/均分兜底）→ 写 `投稿信息.txt`（严格对齐 `bili_auto_submit.load_material`）+ `发布素材.md`。
- 流水线 `STAGE_PUBLISH`：calib2 后、package 前（6 处注册 + 旧链迁移），optional=True。
- 配置默认：`publish_default_game/publish_default_streamer`（DEFAULT_CONFIG，PATCH 保磁盘值，调用可覆盖）。
- **真实 AI 实测**（PGR 片）：标题「【战双帕弥什】大招锐评下：满分10分给15分，丝带芭蕾把评分表打爆【Amethyst】」（43字）、10 tag 无重复、10 段剧情章节（首0/间距≥5s/标题≤16字）、ffprobe 时长 13:01。

### 9.5 验证
- monolith 重建 CHECK OK；calib_ai 自检全部通过；**calib_core PASS 608 / FAIL 0**；本片 `--wuwa40reveal` 不动点 SHA `7302f91c…` 保持；流水线旧链迁移补 publish、calib1/2 AI 化均验证；publish 真实 AI 实测产出合规标题/10tag/10段。
- **GUI 须重启**加载新代码（模块缓存）；publish 页经注册表 services 自动装配。