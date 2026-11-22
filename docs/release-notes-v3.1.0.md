<!-- @version 3.2.5 -->
# 视频工具箱 v3.1.0 变更说明（2026-11-18）

**主题：校准联网查证重构 + Jev 影子复核 + 声纹二次判定。** 三条线都保持
「本地判定为准、模型只做影子建议」：正式字幕、时间轴、声纹 keep/review/drop
一个字节都不改。

## 校准 · 联网查证 v2（整体重写，约 760 行）

`features/calibrate/calib_web_agent.py` 重构，修掉 12 项实测缺陷：

- **中文 URL 必崩**（`UnicodeEncodeError`）→ `_encode_url()` 对 path/query
  分别 quote，wiki 链接抓取实测 `200 / 566KB`；
- **Bing 英文查询拿到 `bing.com/ck/a` 跳转链** → 解 base64url 还原真实地址；
- **噪声当证据回填**（「崔林特尔梅之金」→「崔姓_百度百科」）→ 整词/2-gram
  相关性过滤，4/4 噪声拦截；
- **来源不分级** → 官网 > 维基 > 百科 > 社区四级排序 + 标题匹配度排序；
- **正文从头截断只剩导航** → 6,000 字符 + 关键词窗口（命中处前后各 1,200）；
- **DDG 白等 12s** → 独立 5s 超时，仅前两个 Bing 都失败才尝试；
- **证据无预算**（32 轮累积进 prompt）→ 证据 8,000 / 音画 6,000 字符裁剪，
  保留最近片段；
- **工具请求被静默丢弃** → 单轮上限 2 个，且明确回填「其余 N 个未执行」；
- 另有 BWIKI `Referer`（567 需要）、`wikitext` 返回 dict 兼容、SPA 查询域名
  二次过滤、长模板参数保留等修复。

**五站官方源适配**（全部真实请求实测）：PRTS、BWIKI（鸣潮/方舟/战双/终末地
zmd）、wiki.gg（终末地）、终末地 Wiki（fz sitemap 标题索引）、库街区
（公开检索 API，鸣潮=9 / 战双=2，免密）、森空岛（公开签名接口，`item/info`
可还原「佩丽卡」档案正文）。检索耗时 0.6–4.1s，同术语换措辞命中缓存 0.000s。

- 自检：`selftest_web_agent_v2.py` **33 PASS / 0 FAIL**（8 组）。

## 校准 · 本地证据闸门 + Jev 影子复核

新增 `features/calibrate/calib_evidence.py` / `calib_decision.py`：

- **本地证据闸门**（确定性规则，零 API 请求）：`status=conflict` 直接
  `questionable`；`status=missing` 或 `clean_replacement=false` 直接
  `manual_review`；只有「证据 ok 且只做错形→官方名的最小替换」才送 Jev；
- Jev（`decision-model-preview`，System One 结构化影子决策）只复核干净替换，
  路由 `consistent / manual_review / questionable`，**不改 accepted、不改正式
  SRT、不改时间轴**；报告单列 `gated / gate_reasons / jev_evaluated`；
- 激活门控严格：全局 AI 启用 + `decision_mode=shadow` + 密钥存在 + HTTPS 且
  主机名匹配 `token-plan.*.maas.aliyuncs.com`；普通百炼、火山方舟、QwenCloud
  均不激活，关闭后零请求。

**评测（2026-11-18，399 条本地一致性样本，310 train / 89 eval）**：

| 形态 | accuracy | 正例召回 | 负例拦截 |
|---|---:|---:|---:|
| baseline choice | 0.3820 | 1.0000 | 0.0000 |
| evidence_text noul few-shot | **0.6966** | 0.6471 | **0.7273** |

本地闸门 + Jev 风险分数（0.70）在留出集：binary accuracy 0.9888、正例召回
0.9706、consistent precision 1.0、review rate 0.6292；只用本地闸门时
precision/召回均为 1.0、review rate 0.618。结论：**Jev 单独不足以自动放行，
生产策略定为「本地闸门分流、Jev 只做影子语义提示」。**
（`.calib.srt` 为规则/模型产物，非人工金标，以上数字只表示与本地官方名的一致性。）

## 声纹 · 本地二次判定与筛选模式

- 本地聚类**第二遍**：先合并近重复簇，再用冻结簇心对全部有效 cue 重指派；
  离群 cue 只在彼此之间重新立簇；
- `filter_srt()` 保留 `[(cue, state, score)]` 公共契约，另返回 `decisions`
  （原序号/起止毫秒/状态/分数/来源/原因/ASR 说话人/本地簇）；
- 短 cue 只有在逐条打分仍失败、且前后邻居同属一个有效本地簇时才借簇分
  （`short_context`），其余保持存疑；
- 模式：`recall`（默认，review 进正式 SRT）/ `precision`（正式 SRT 只含 keep，
  review 写 `<原名>_待复核.srt`，同名追加序号不覆盖历史）；旧 `keep_review=False`
  与 CLI `--strict` 均映射 precision；
- GUI 声纹选择器的策略/名单/自动筛选开关同存 `_selection.json` 的
  `filter_mode`，三个写入函数保留未知键；
- Jev 影子路由（`voiceprint_decision.py`）：只对本地二次判定后仍为 review 的
  cue 给 `routine_review / priority_manual / insufficient_evidence`，不碰
  CAM++ 分数与 keep/review/drop。

## 实体层与片源模式

- 四站 Wiki（明日方舟/战双/鸣潮/终末地）抓通落盘：对象库 3490，
  作品标注 563（16.1%）→ 731（20.9%），新增标注 168（high 266 / medium 12 /
  low 85，冲突 6）；运行时覆盖层 `data/entities/wiki_work_overlay.json` 只应用
  high/medium 且原 category 为空的条目，写入 134 个对象；
- 新增三个片源术语/语境表：`--arcak`（Arcaea×明日方舟联动直播）、
  `--ssv`（星之救援者评测）、`--tga26`（TGA 2026 游戏大奖直播）；
- `--ssv/--arcak/--tga26` 均支持显式旗标与模式名归一化（含中文别名），
  与 `bi` 表隔离，只在本模式内生效。

## 决策客户端与配置

- 新增 `tools/decision_client.py` + `core/shared/decision.py` 共享加载缝：
  严格 `POST /compatible-mode/v1/systemone`，正文只含
  `model/state/questions`，支持 choice/noul/score 响应校验，不生成文本；
- 复用全局 AI 的 `base_url/api_key`，不新增第二套凭据；配置新增
  `decision_mode / decision_timeout / decision_max_items / decision_batch_size`
  （默认 shadow、12s、32 条、每批 8 条，异常按批降级并记录原因）；
- 设置页新增 Jev 影子复核开关，关闭后零 Jev 请求。

## 新增评测与自检

- `scripts/dev/_selftest_decision.py`：门控、三类 Schema、声纹/校准影子不改写、
  本地证据闸门与异常降级，模拟响应 **36 PASS / 0 FAIL**（不联网）；
- `scripts/dev/_selftest_settings_import_race.py`、`_selftest_speaker_voiceprint.py`
  新增声纹聚类/二次判定/精准模式/待复核备份用例（含真 CAM++）；
- `scripts/dev/eval_jev_calib.py` / `eval_jev_gate.py`：真实 Token Plan 判定集
  评测与离线闸门评估；
- `scripts/dev/voiceprint_filter_eval.py`：真实标注 manifest 评测入口，
  `out_path=None` 只读运行，不改原 SRT/媒体/模板。

## 兼容性

- 校准铁律不变：序号/时间轴/空行/换行/BOM 原样，只动文字；
- 声纹 `filter_srt()` 公共判定契约不变，新增字段向后兼容；
- 数据目录布局不变，无需迁移；旧配置无 `decision_*` 时按默认值运行；
- `subtitle_calib_merged.py` 为生成物，已按 `build_calib_monolith.py` 重新生成
  并通过 `--check` 一致性校验。

## 门禁汇总（发布前全绿）

语法 400 个受跟踪 `.py` 全过 · 校准单文件 CHECK OK（1104 Entity）·
`_selftest_decision` 36/0 · `selftest_web_agent_v2` 33/0 ·
`_selftest_speaker_voiceprint` 通过（含真 CAM++）· `_selftest_calib_ai` 通过 ·
`_selftest_calib_core` 通过 · doc drift 通过 · 密钥扫描通过。
