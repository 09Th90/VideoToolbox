# 字幕校准报告（二次校准版）· 鸣潮 3.7「ADHD REACTS to Wuthering Waves Version 3.7 Hsin MAIN QUEST」

## 一、总览

| 项 | 值 |
| --- | --- |
| 片源 | `【字幕】ADHD REACTS to Wuthering Waves Version 3.7 Hsin MAIN QUEST.en-谷歌翻译.srt` |
| 作者/来源 | kettletoro（YouTube reaction，英文原声 + 谷歌机翻中文） |
| 模式 | `bi`（中英双语，自动识别） |
| 规模 | 883 条 cue，原文 CRLF、无 BOM |
| 中文行改动 | **198 处** |
| `verify` | ✅ 883 cue，时间轴差 0 / 参考行差 0 / CRLF / BOM 全一致 |
| `align-audit` | ✅ 串位 0 / 接缝叠字 0 / 起首标点 0 / 超宽 0 |

## 二、二次校准（以官方中文为依据逐句核查）

### 2.1 漏校专名（参考行命中官方名、中文行缺失）

| cue | 原文 | 校准后 | 依据 |
| --- | --- | --- | --- |
| `40` | 我们再次前往歧管 | **我们再次前往万相神宫** | manifold sanctum = 万相神宫（玄方城控制中枢，灰机 wiki） |
| `237` | 摇摆姐妹 | **锁暝姐妹** | Sister Swinging = Swaming = 锁暝 |
| `308` | Seen的记忆 | **心月狐的记忆** | Seen's memories = Shin = 心月狐 |
| `315/316` | 玄方的朝月会 / Hold比我自己还要美丽 | **玄方城的朝月会 / 比我自己还要美丽** | Shanfang Hold = 玄方城，清除英文残留 Hold |
| `362-365` | 名字里 / 以 / 这片土地的岁主，跟随我的 / 指挥部 | **以 / 心月狐的名义，以这片土地的岁主的名义，/ 跟随我的 / 指挥。** | 原文漏译 "seen the moon fox"，整句重排 |
| `383` | 等待结束 | **玄方城的完工** | Hold's completion，the Hold = 玄方城 |
| `385` | 这就是“领地”的完成方式 | **这就是玄方城的完成方式** | the Hold was completed |
| `397` | 这个固定点 | **这个玄方城** | this hold |
| `455` | Shwenfong的建立 | **玄方城的建立** | 英文残留 Shwenfong = 玄方城 |
| `488` | 苏希安的力量 | **溯心的力量** | Sushian = Sushin = 溯心 |
| `706` | 亲身体验月亮节 | **亲身体验朝月会** | the Moon Festival = 朝月会 |
| `739` | 因为吴刚才 | **因为鸣潮刚才** | Wua = WuWa = 鸣潮 |
| `880/881` | 《枯萎战争》 / Waves主线任务 | **《鸣潮》 / 主线任务** | War of Withering Waves = 鸣潮，清除英文残留 |

### 2.2 谷翻「Shin/Sin」变体大面积漏校

英文 ASR 把心月狐（Hsin/Shin）听成 `Sin`，谷歌一律按常用词直译，共 12 处：

| 英文 | 谷翻错形 | cue |
| --- | --- | --- |
| Sin | 辛 / 罪 / 罪恶 | 168 / 178 / 180 / 212 / 570 / 647 / 648 / 772 |
| Shin | 信 / 真 | 773 / 702 |
| Shing | 成 | 42 |
| Sin | 辛本人 | 252 |

### 2.3 其他错译/漏译

- `#72/73` 追踪心脏内的异常 / Realms → 追踪**心境**内的异常 /（删英文残留）
- `#85/107/118/386/692` 天神/天界/天界生物 → **天人**（celestials 官方中文）
- `#516` 被塔西特蹂躏的王风 → 被**残象**蹂躏的**玄方**（Tacet Discord / Schwangfong）
- `#537` 漂泊者是[__]**裁判** → 漂泊者是[__]**御者**（arbiter）
- `#656` 看，Simiracrim 枢纽 → 看，**梦枢天罗**
- `#853/855` 弗赖杜斯 → **残星会**（Fraidus）
- `#857` 银杏巡逻员 → **今州**巡逻员（Gingjo）
- `#871` 小蜂群 → 小**锁暝**（Little Swarming）

## 三、脚本同步（`subtitle_calib_merged.py`）

新增 ENTITIES 沉淀块（2026-10-10 本片，`modes=("bi",)`）：

| canonical | 新增变体（裸键） | 新增条件变体（ctx 参考行锚定） |
| --- | --- | --- |
| 心月狐 | — | Sin→辛/罪/罪恶、Shing→成、Shuin→修院、Seen（整词残留） |
| 锁暝 | 斯沃明 | Swaming→游水、Swinging→摇摆 |
| 玄方城 | Shwenfong / Shenfong / 神丰堡 / 山坊 / 山芳 | Schwangfong→王风、the Hold→领地/固定点、Hold's→等待结束 |
| 天人 | — | celestials→天界生物/天界幻影/天神/天界 |
| 溯心 | 苏希安 | — |
| 梦枢天罗 | 西米拉克林 | nexus→枢纽（组合形先于单形） |
| 万相神宫 | — | manifold→歧管 |
| 朝月会 | — | Moon Festival→月亮节 |
| 鸣潮 | 枯萎战争 | Wua→吴 |
| 梦州 | — | Mongjo/Mojo/Mongo→蒙乔 |
| 今州 | — | Gingjo/Jingo→银杏 |
| 御者 | — | arbiter→裁判 |
| 残星会 | 弗赖杜斯 | — |

另在扁平 `CONTEXT_MAP` 追加 2 条三元组（目标需保留原句虚词、非 canonical）：
`Shin→真终于/心月狐终于`、`Shin→叫信/叫心月狐`。

**验证**：`AST OK`、行尾 CRLF 一致、`terms-check` 无新增二次命中隐患；用更新后脚本重跑源文件，新增规则全部按预期命中。

## 四、中文标题与标签

### 推荐标题

> **《ADHD 反应鸣潮 3.7 心月狐主线：以为要看她大杀四方，结果哭成泪人》**

备选：

- 《ADHD 速通鸣潮 3.7 心月狐主线：一场"如何写好神的故事"的大师课》
- 《我本想看她的力量与狡猾，却被鸣潮 3.7 主线看哭了｜ADHD 反应》

### 10 个标签

`鸣潮`  `鸣潮3.7`  `镜锁妄世心照红尘`  `玄方篇`  `心月狐`  `锁暝`  `鸣潮主线剧情`  `剧情解说`  `游戏反应视频`  `ADHD`

## 五、完整对照表（198 处）

| 序号 | 原文中文（机翻） | 校准后中文 | 英文参考行 | 类型 |
| --- | --- | --- | --- | --- |
| `4` | 可操作的哨兵，凭借她的性感 | **可操作的岁主，凭借她的性感** | playable Sentinel, given her sultry | 专名/术语 |
| `15` | 枯萎波浪3.7版任务多动症 | **鸣潮3.7版任务多动症** | Withering Waves version 3.7 quest ADHD. | 专名/术语 |
| `17` | 试图找到新。看起来是 | **试图找到心月狐。看起来是** | trying to find Shin. Seems to be a | 专名/术语 |
| `29` | 我喜欢Swing的设计 | **我喜欢锁暝的设计** | I like Swing's design. | 专名/术语 |
| `40` | >> 我们再次前往歧管 | **>> 我们再次前往万相神宫** | >> Once again, we head to the manifold | 二次校准 |
| `41` | 与丁晓同在圣殿，见见斯瓦明 | **与丁晓同在神宫，见见锁暝** | sanctum with Ting Xiao and meet Swaming | 二次校准 |
| `42` | 他也在找成。我们进去了 | **他也在找心月狐。我们进去了** | who's also looking for Shing. We enter | 专名/术语 |
| `43` | 与斯沃明和发现的圣所 | **与锁暝和发现的万相神宫** | the sanctum with Swaming and discover | 专名/术语 |
| `44` | 情况非常不对劲。天体 | **情况非常不对劲。天人** | something is very wrong. The celestials | 专名/术语 |
| `46` | 圣所里有异常。其中一个 | **万相神宫里有异常。其中一个** | anomaly in the sanctum. One of the | 专名/术语 |
| `47` | 天体，卢勒，意识到我们已经 | **天人，卢勒，意识到我们已经** | celestials, Lurer, upon realizing we had | 专名/术语 |
| `72` | 追踪心脏内的异常 | **追踪心境内的异常** | tracking the anomalies within the heart | 二次校准 |
| `73` | Realms，突然发生了这种事 | **突然发生了这种事** | realms, suddenly this happens. | 二次校准 |
| `85` | 天神们谈论的 | **天人谈论的** | Celestials talked about. | 二次校准 |
| `96` | 等等，艾比为什么这么矮？艾比 | **等等，阿布为什么这么矮？阿布** | Wait, why Abby so short? Abby. | 专名/术语 |
| `97` | 为什么艾比比我高？呃 | **为什么阿布比我高？呃** | Why is Abby taller than me? Uhoh. | 专名/术语 |
| `98` | 艾比。呃 | **阿布。呃** | Abby. Uhoh. | 专名/术语 |
| `106` | 通过这样做，我们模拟了清醒月亮 | **通过这样做，我们模拟了朝月** | doing so, we simulated the waking moon | 专名/术语 |
| `107` | 天界的节日 | **天人的节日** | festival for the celestials within this | 二次校准 |
| `109` | 天界幻影见到她的孩子一号 | **天人幻影见到她的孩子一号** | celestial phantom to see her child one | 二次校准 |
| `117` | 哨兵 | **岁主** | Sentinel. | 专名/术语 |
| `118` | >>等等，天神到底是怎么死的？ | **>>等等，天人到底是怎么死的？** | >> Wait, but how does Celestial even die? | 二次校准 |
| `126` | 清醒月节，进入一扇门 | **朝月会，进入一扇门** | Waking Moon Festival and enter a door | 专名/术语 |
| `134` | 直到我们终于到达了西米拉克林 | **直到我们终于到达了梦枢天罗** | until we finally reach the similacrim | 二次校准 |
| `135` | 核心，Nexus。但当我们进入每一个 | **核心。但当我们进入每一个** | nexus, the core. But as we enter each | 二次校准 |
| `137` | 显然我们正在重温申的经历 | **显然我们正在重温心月狐的经历** | clear we're actually reliving Shin's | 专名/术语 |
| `156` | >> 一个文明舱 | **>> 一个文明之匣** | >> A civilization capsule. | 专名/术语 |
| `159` | 通过哨兵谐振器维持 | **通过岁主共鸣者维持** | sustained from the Sentinel resonator's | 专名/术语 |
| `161` | >>哨兵谐振器。哨兵是谁 | **>>岁主共鸣者。岁主是谁** | >> Sentinel resonator. Who was the Sentinel | 专名/术语 |
| `162` | 共振腔？她是怎么死的？ | **共鸣者？她是怎么死的？** | resonator? And how did she die? | 专名/术语 |
| `168` | >>等等，她杀了辛 | **>>等等，她杀了心月狐** | >> Wait, she killed Sin. | 二次校准 |
| `178` | 我们现在所知的罪是谁？为什么他们会 | **我们现在所知的心月狐是谁？为什么他们会** | who was the sin we know now? Why do they | 二次校准 |
| `180` | 当年杀死辛那么狠？ | **当年杀死心月狐那么狠？** | to kill Sin so bad back then? | 二次校准 |
| `184` | >> 如果你是Sheen的分形形式 | **>> 如果你是心月狐的分形形式** | >> If you are a fractal form of Sheen the | 专名/术语 |
| `185` | 月狐，那现实呢？ | **心月狐，那现实呢？** | Moon Fox, then what of the real | 专名/术语 |
| `186` | 哨兵？ | **岁主？** | Sentinel? | 专名/术语 |
| `194` | >> 是原版哨兵吗？ | **>> 是原版岁主吗？** | >> Is it the original sentinel? | 专名/术语 |
| `200` | 仲裁者 | **御者** | Arbiter, | 专名/术语 |
| `204` | 保护Schwangfong堡垒。希恩 | **保护玄方城堡垒。心月狐** | protecting Schwangfong Hold. Sheen the | 专名/术语 |
| `205` | 月狐把心给了你，而你 | **把心给了你，而你** | Moonf Fox gave you its heart, and you | 专名/术语 |
| `206` | 把你的交给了Schwangfong Hold。只要 | **把你的交给了玄方城。只要** | gave yours to Schwangfong Hold. As long | 二次校准 |
| `210` | 重要的是你的想法。希恩 | **重要的是你的想法。心月狐** | What matters is what you think. Sheen, | 专名/术语 |
| `212` | >> 所以，这并不是真正的罪恶 | **>> 所以，这并不是真正的心月狐** | >> So, this isn't the real sin the moon | 二次校准 |
| `213` | 狐狸。她只是它的一个分形 | **她只是它的一个分形** | fox. She's just a fractal of it. | 二次校准 |
| `220` | 心境异常已解决，罗弗 | **心境异常已解决，漂泊者** | heart realm's anomaly resolved, Rover | 专名/术语 |
| `222` | 首先，我们被切换到斯瓦明的 | **首先，我们被切换到锁暝的** | first, we're switched to Swaming's | 专名/术语 |
| `229` | 斯瓦明的背景故事。第六个印章是 | **锁暝的背景故事。第六个印章是** | Swaming's backstory. The sixth seal is | 专名/术语 |
| `237` | 总之，摇摆姐妹。你救了我们 | **总之，锁暝姐妹。你救了我们** | anyway, Sister Swinging. You saved our | 二次校准 |
| `240` | >> 我们为被称为“海豹”而感到自豪 | **>> 我们为被称为“封印”而感到自豪** | >> And we were proud to be called the seal | 专名/术语 |
| `251` | 就这样挣扎。然后游水 | **就这样挣扎。然后锁暝** | struggling like this. Then Swaming | 二次校准 |
| `252` | 最终遇见了辛本人。或者说是 | **最终遇见了心月狐本人。或者说是** | finally encounters Sin herself. Or is | 二次校准 |
| `255` | 蜂拥而至 | **锁暝** | swarming. | 专名/术语 |
| `261` | 哨兵事务部，你已经投入了两个 | **谛天鉴，你已经投入了两个** | Sentinel Affairs, you have devoted two | 专名/术语 |
| `263` | 胶囊并升为总监。现在轮到你了 | **文明之匣并升为州监。现在轮到你了** | capsule and risen to intendant. Now you | 专名/术语 |
| `266` | 朱红锁，每一次密封 | **玄朱锁，每一次密封** | Vermillion locks, each sealing of | 专名/术语 |
| `290` | 起诉 | **锁暝** | Suing. | 专名/术语 |
| `291` | 你现在是督察了。哨兵报 | **你现在是督察了。岁主报** | You are an intendant now. The Sentinel | 专名/术语 |
| `299` | 哨兵。又一次犯下叛国罪 | **岁主。又一次犯下叛国罪** | Sentinel. yet again committing treason. | 专名/术语 |
| `302` | 哨兵事务总监？她和 | **岁主事务州监？她和** | intendant of sentinel affairs? She and | 专名/术语 |
| `303` | 月狐绝不会做出那样的事 | **心月狐绝不会做出那样的事** | the moon fox would never do such a | 专名/术语 |
| `305` | 你不是她，也不是哨兵 | **你不是她，也不是岁主** | You are not her and you are no sentinel. | 专名/术语 |
| `306` | >> 哦，走开，恶魔。回归罗弗 | **>> 哦，走开，恶魔。回归漂泊者** | >> Ooh, be gone, fiend. Back with Rover in | 专名/术语 |
| `308` | 体验更多Seen的记忆。在 | **体验更多心月狐的记忆。在** | experience more of Seen's memories. in | 二次校准 |
| `313` | >> 谢谢你，哨兵女士，感谢你屈服 | **>> 谢谢你，岁主女士，感谢你屈服** | >> Thank you, Lady Sentinel, for bending | 专名/术语 |
| `315` | 山坊的清醒月节 | **玄方城的朝月会** | The Waking Moon Festival in Shanfang | 二次校准 |
| `316` | Hold比我自己还要美丽 | **比我自己还要美丽** | hold is even more beautiful than I ever | 二次校准 |
| `319` | 不惜一切代价守护施万方 | **不惜一切代价守护玄方** | guard Schwanfong at all costs. | 专名/术语 |
| `330` | 一年。我成了传说中的哨兵 | **一年。我成了传说中的岁主** | a year. I became the fabled sentinel who | 专名/术语 |
| `362` | 平民。通知所有单位。名字里 | **平民。通知所有单位。以** | civilians. Notify all units. In the name | 二次校准 |
| `363` | 以 | **心月狐的名义，以这片土地的岁主的名义，** | of seen the moon fox in the name of the | 二次校准 |
| `364` | 这片土地的哨兵，跟随我的 | **跟随我的** | sentinel of this land, follow my | 二次校准 |
| `365` | 指挥部 | **指挥。** | command. | 二次校准 |
| `383` | 等待结束 | **玄方城的完工** | Hold's completion. | 二次校准 |
| `385` | 这就是“领地”的完成方式 | **这就是玄方城的完成方式** | that's how the Hold was completed. | 二次校准 |
| `386` | >> 提出成为天界生物。其为 | **>> 提出成为天人。其为** | >> Offering to become celestials. It is as | 二次校准 |
| `395` | >> 这场战斗决定了山芳的命运 | **>> 这场战斗决定了玄方的命运** | >> This battle determines Shanfang's fate. | 二次校准 |
| `396` | 申夫人，从今以后，我们与 | **心月狐夫人，从今以后，我们与** | Lady Shin, from now on, we are one with | 专名/术语 |
| `397` | 这个固定点 | **这个玄方城** | this hold. | 二次校准 |
| `403` | 哨兵 | **岁主** | sentinel. | 专名/术语 |
| `407` | 月狐希恩。带着霜之心 | **心月狐。带着霜之心** | Sheen the Moon Fox. With the frost heart | 专名/术语 |
| `408` | 领域异常解决，Shin 终于 | **领域异常解决，心月狐 终于** | realm anomaly resolved, Shin is finally | 专名/术语 |
| `410` | 显现她的人形。还有一辆漫游车 | **显现她的人形。还有一辆漂泊者** | manifest her human form. And a rover | 专名/术语 |
| `411` | 由朱红锁警告 | **由玄朱锁警告** | warned by Vermillion Lock given to us | 专名/术语 |
| `412` | 之前被Swaming说Shin是 | **之前被锁暝说心月狐是** | earlier by Swaming that Shin is | 专名/术语 |
| `415` | 丑陋的真相。我们了解了申的病情 | **丑陋的真相。我们了解了心月狐的病情** | the ugly truth. We learn what Shin has | 专名/术语 |
| `427` | Schwangfong。嗯 | **玄方城。嗯** | Schwangfong. Mhm. | 专名/术语 |
| `430` | 再次见到月狐希恩。但是 | **再次见到心月狐。但是** | to see Sheen the moon fox once more. But | 专名/术语 |
| `433` | >> Sheen，告诉我，是 | **>> 心月狐，告诉我，是** | >> Sheen, tell me, was the cost of | 专名/术语 |
| `434` | 重塑文明舱 你的 | **重塑文明之匣 你的** | remolding the civilization capsule your | 专名/术语 |
| `440` | >>仲裁者 | **>>御者** | >> Arbiter, | 专名/术语 |
| `442` | 你做得很好，希恩 | **你做得很好，心月狐** | You did well, Sheen. | 专名/术语 |
| `447` | >>仲裁者，别试图 | **>>御者，别试图** | >> Arbiter, don't try to | 专名/术语 |
| `451` | >> 希恩 | **>> 心月狐** | >> Sheen. | 专名/术语 |
| `452` | 哨兵死了 | **岁主死了** | The Sentinel is dead. | 专名/术语 |
| `455` | >> Shwenfong的建立 | **>> 玄方城的建立** | >> The founding of Shwenfong | 二次校准 |
| `457` | 文明舱 | **文明之匣** | civilization capsule. | 专名/术语 |
| `461` | 福克斯托付给我的。但我，我，我 | **狐狸托付给我的。但我，我，我** | fox had entrusted me with. But I but I I | 专名/术语 |
| `468` | 所以，她用的是文明舱 | **所以，她用的是文明之匣** | So, her using the civilization capsule | 专名/术语 |
| `469` | 导致哨兵死亡 | **导致岁主死亡** | caused the Sentinel to die. | 专名/术语 |
| `475` | 文明舱停止吸取我的血 | **文明之匣停止吸取我的血** | civilization capsule stopped draining my | 专名/术语 |
| `479` | 仲裁者 | **御者** | Arbiter, | 专名/术语 |
| `482` | 月狐，不是缩小的弗拉普托形态 | **心月狐，不是缩小的弗拉普托形态** | moon fox, not a diminished frapto form. | 专名/术语 |
| `485` | >> Rover 真吓人。天哪 | **>> 漂泊者 真吓人。天哪** | >> Rover is so scary. Oh my god. | 专名/术语 |
| `488` | >> 如果我夺回苏希安的力量，我可以 | **>> 如果我夺回溯心的力量，我可以** | >> If I reclaimed Sushian's power, I could | 二次校准 |
| `489` | 唤醒哨兵的意志，从中 | **唤醒岁主的意志，从中** | awaken the Sentinel's will from the | 专名/术语 |
| `491` | 胶囊。这是真正的意志 | **文明之匣。这是真正的意志** | capsule. Its true will. | 专名/术语 |
| `493` | >> 如果我自首，真正的哨兵 | **>> 如果我自首，真正的岁主** | >> If I gave myself up, the true sentinel | 专名/术语 |
| `496` | 真正的哨兵 | **真正的岁主** | true sentinel. | 专名/术语 |
| `497` | 你已经是月狐的一部分了 | **你已经是心月狐的一部分了** | You're already a piece of the moon fox. | 专名/术语 |
| `499` | 归来的真正是哨兵 | **归来的真正是岁主** | that what returns is truly the sentinel, | 专名/术语 |
| `501` | >>我认为她在各方面都是哨兵 | **>>我认为她在各方面都是岁主** | >> I think she's a sentinel in every sense | 专名/术语 |
| `503` | >> 希恩。我从一开始就带着这个 | **>> 心月狐。我从一开始就带着这个** | >> Sheen. I've had this on me since I first | 专名/术语 |
| `511` | 我更像是仲裁者 | **我更像是御者** | me as arbiter more than anything else. | 专名/术语 |
| `513` | 哨兵回应 | **岁主回应** | sentinel back. | 专名/术语 |
| `516` | 在被塔西特蹂躏的王风中 | **在被残象蹂躏的玄方中** | in a Schwangfong ravaged by Tacit | 二次校准 |
| `518` | 你自己。如果真正的哨兵...... | **你自己。如果真正的岁主......** | yourself. If the true Sentinel had made | 专名/术语 |
| `520` | 更明智，更无懈可击地为Schwangfang服务 | **更明智，更无懈可击地为玄方城服务** | wiser, more foolproof for Schwangfang, | 专名/术语 |
| `523` | 绝不会让Muyu的混乱吞噬 | **绝不会让木禺的混乱吞噬** | would never have let Muyu's chaos take | 专名/术语 |
| `528` | 作为仲裁者的责任 | **作为御者的责任** | responsibility as arbiter. | 专名/术语 |
| `530` | >>与哨兵的恶行 | **>>与岁主的恶行** | >> and the wrongdoings of the sentinel's | 专名/术语 |
| `534` | 蒙乔前进。你会背叛 | **梦州前进。你会背叛** | of Mongjo forward. Will you betray the | 专名/术语 |
| `535` | 希望他们能放进你身上？天哪，Rover真是 | **希望他们能放进你身上？天哪，漂泊者真是** | hopes they place in you? Damn, Rover is | 专名/术语 |
| `537` | Rover是[ __ ]裁判，兄弟。I | **漂泊者是[ __ ]御者，兄弟。I** | Rover is the [ __ ] arbiter, bro. I | 二次校准 |
| `540` | >> 与蜂群重聚，我们准备 | **>> 与锁暝重聚，我们准备** | >> Reunited with swarming, we prepared to | 专名/术语 |
| `541` | 当这突如其来时，面对苏辛 | **当这突如其来时，面对溯心** | face Sushin when suddenly this happens. | 专名/术语 |
| `556` | >> Sheen的频率也在这里。你不能 | **>> 心月狐的频率也在这里。你不能** | >> Sheen's frequency is here too. You can't | 专名/术语 |
| `559` | >>走吧，仲裁者。它会引领我们 | **>>走吧，御者。它会引领我们** | >> let's go, Arbiter. It will lead us to | 专名/术语 |
| `560` | 寿司不可避免 | **穗穗不可避免** | sushi in the inevitable. | 专名/术语 |
| `564` | 我永远无法成为曾经的哨兵 | **我永远无法成为曾经的岁主** | I can never become the sentinel I was | 专名/术语 |
| `570` | [ __ ] 逻辑。天哪，辛 | **[ __ ] 逻辑。天哪，心月狐** | [ __ ] logic. Oh my god, Sin. | 二次校准 |
| `579` | >>哨兵，如果你在这里，我就闭嘴 | **>>岁主，如果你在这里，我就闭嘴** | >> Sentinel, if you are here, I'll sush. | 专名/术语 |
| `581` | >> 蜂拥而至，绝不给我机会 | **>> 锁暝，绝不给我机会** | >> And swarm me will not give the chance. | 专名/术语 |
| `582` | >> 那是最初的哨兵 | **>> 那是最初的岁主** | >> That was the original sentinel. | 专名/术语 |
| `583` | 哦，是原版哨兵 | **哦，是原版岁主** | Oh, it's the original Sentinel. | 专名/术语 |
| `584` | 哨兵 | **岁主** | Sentinel, | 专名/术语 |
| `589` | 重塑文明舱 | **重塑文明之匣** | Remolding the civilization capsule would | 专名/术语 |
| `598` | 能找到新道路的哨兵 | **能找到新道路的岁主** | sentinel who can find a new path | 专名/术语 |
| `616` | 文明舱数百年来的存在 | **文明之匣数百年来的存在** | civilization capsule for centuries to | 专名/术语 |
| `620` | 你是 Mojo 的核心 | **你是梦州的核心** | You are the very heart of Mojo. | 二次校准 |
| `622` | 真正的哨兵。我觉得她是 | **真正的岁主。我觉得她是** | legit sentinel. I feel like she's the | 专名/术语 |
| `623` | 大多数哨兵哨兵都能做到。你 | **大多数岁主岁主都能做到。你** | most sentinel sentinel could be. You | 专名/术语 |
| `626` | 哨兵们鼓励着她 | **岁主们鼓励着她** | sentinels encouraging her. | 专名/术语 |
| `636` | 仲裁者 | **御者** | Arbiter. | 专名/术语 |
| `637` | 哨兵希恩，月狐，来了 | **岁主心月狐，来了** | Sentinel Sheen, the Moon Fox, has come | 二次校准 |
| `639` | 那是原版哨兵，对吧？ | **那是原版岁主，对吧？** | That's the OG Sentinel, right? | 专名/术语 |
| `642` | [ __ ]哨兵？ | **[ __ ]岁主？** | [ __ ] Sentinel? | 专名/术语 |
| `647` | 因为罪恶，但还是 | **因为心月狐，但还是** | cuz of Sin, but still. | 二次校准 |
| `648` | 天哪 [ __ ] 罪恶真酷 | **天哪 [ __ ] 心月狐真酷** | Holy [ __ ] Sin is so cool. | 二次校准 |
| `650` | >>无限城堡 | **>>无限城** | >> Infinity Castle. | 专名/术语 |
| `655` | 电影院 | **大片** | cinema. | 专名/术语 |
| `656` | >> 看，Simiracrim Nexus | **>> 看，梦枢天罗** | >> Look, similacrim nexus. | 二次校准 |
| `657` | 我们的文明舱太广大了，太 | **我们的文明之匣太广大了，太** | Our civilization capsule is so vast, so | 专名/术语 |
| `688` | 胶囊快完成了 | **文明之匣快完成了** | capsule is nearly complete. | 专名/术语 |
| `689` | 弗雷杜斯偷走的残骸不会 | **残星会偷走的残骸不会** | The remains the Fraidus stole will no | 专名/术语 |
| `690` | 不再足以动摇蒙乔 | **不再足以动摇梦州** | longer be enough to shake Mongjo. | 专名/术语 |
| `691` | 我会阻止神丰堡的崩溃 | **我会阻止玄方城的崩溃** | I will stop Shenfong Hold's collapse and | 二次校准 |
| `692` | 召集那些意志的天神 | **召集那些意志的天人** | gather those celestials whose wills are | 二次校准 |
| `697` | 秘密。这不适合做哨兵 | **秘密。这不适合做岁主** | secrets. It is unbefitting a sentinel. | 专名/术语 |
| `701` | 成为独一无二的哨兵 | **成为独一无二的岁主** | of becoming a sentinel like no other. | 专名/术语 |
| `702` | 苏辛离开，真终于完全恢复 | **溯心离开，心月狐终于完全恢复** | With Sushin gone and Shin finally fully | 二次校准 |
| `703` | 接受了自己作为哨兵的角色 | **接受了自己作为岁主的角色** | accepting her role as the Sentinel, the | 专名/术语 |
| `704` | 危机得以避免。圣所回归 | **危机得以避免。万相神宫回归** | crisis is averted. The sanctum returns | 专名/术语 |
| `705` | 恢复正常，申终于真正明白了 | **恢复正常，心月狐终于真正明白了** | to normal and Shin finally actually gets | 专名/术语 |
| `706` | 亲身体验月亮节 | **亲身体验朝月会** | to experience the Moon Festival herself. | 二次校准 |
| `707` | >> 《清醒月节》。感觉像是 | **>> 《朝月会》。感觉像是** | >> The Waking Moon Festival. It feels like | 专名/术语 |
| `709` | >> Sheen，你怎么还在这里？整个 | **>> 心月狐，你怎么还在这里？整个** | >> Sheen, why are you still here? The whole | 专名/术语 |
| `716` | >> 蒙乔的暗流还未 | **>> 梦州的暗流还未** | >> The dark currents of Mong Joe have yet | 专名/术语 |
| `717` | 要从根本上清除。希恩 | **要从根本上清除。心月狐** | to be purged at the root. Whether Sheen | 专名/术语 |
| `719` | 重要的是哨兵是否 | **重要的是岁主是否** | What matters is whether the Sentinel | 专名/术语 |
| `722` | 现在是正式的哨兵了吗？ | **现在是正式的岁主了吗？** | full-fledged Sentinel now or no? | 专名/术语 |
| `731` | 艾比 | **阿布** | Abby. | 专名/术语 |
| `733` | 仲裁者 | **御者** | Arbiter. | 专名/术语 |
| `735` | 醒月节以及所有的 | **朝月会以及所有的** | waking moon festival and all the | 专名/术语 |
| `739` | 这里也有，因为吴刚才 | **这里也有，因为鸣潮刚才** | scene here, too, because Wua just | 二次校准 |
| `769` | >> 仲裁者，你打算写什么？愿我赢 | **>> 御者，你打算写什么？愿我赢** | >> What will you write, Arbiter? May I win | 专名/术语 |
| `771` | 枯萎的波浪 | **鸣潮** | withering waves. | 专名/术语 |
| `772` | 我可以买《罪恶P6》吗？我开玩笑的 | **我可以买《心月狐P6》吗？我开玩笑的** | May I get Sin P6? I'm just kidding. | 二次校准 |
| `773` | 那不可能。但我能叫信吗？ | **那不可能。但我能叫心月狐吗？** | That's not happening. But may I get Shin | 二次校准 |
| `776` | 谢谢。仲裁者 | **谢谢。御者** | Thank you. Arbiter, | 专名/术语 |
| `779` | 一起。仲裁者 | **一起。御者** | together. Arbiter. | 专名/术语 |
| `801` | 为什么？你的妹妹斯瓦明是 | **为什么？你的妹妹锁暝是** | why? Your sister, Swaming, is | 专名/术语 |
| `803` | 她带领蒙乔跨越了几个世纪 | **她带领梦州跨越了几个世纪** | She carried Mong Joe through centuries | 专名/术语 |
| `804` | 当哨兵不在时 | **当岁主不在时** | when the Sentinel wasn't there to govern | 专名/术语 |
| `807` | >> Sheen将成为一个不一样的哨兵 | **>> 心月狐将成为一个不一样的岁主** | >> Sheen will become a Sentinel like no | 专名/术语 |
| `821` | 谢谢你，仲裁者。仲裁者，如果 | **谢谢你，御者。御者，如果** | Thank you, Arbiter. Arbiter, if the | 专名/术语 |
| `822` | 哨兵看到有人脸上带着悲伤的表情 | **岁主看到有人脸上带着悲伤的表情** | Sentinel saw someone with a sad face at | 专名/术语 |
| `829` | 更多他们见到Shin时的[ __ ] | **更多他们见到心月狐时的[ __ ]** | more of their [ __ ] at seeing Shin | 专名/术语 |
| `837` | 真的杀了原哨兵？ | **真的杀了原岁主？** | actually killed the original Sentinel? | 回滚坏键 |
| `839` | Sante字体的谜团是 | **稷廷字体的谜团是** | of Sante lettering, those mysteries are | 专名/术语 |
| `842` | 来吧。希恩，月狐。还没到时候 | **来吧。心月狐，心月狐。还没到时候** | come. Sheen, the moon fox. It's not time | 专名/术语 |
| `844` | >> 还没有。你为什么不叫我希恩？ | **>> 还没有。你为什么不叫我心月狐？** | >> Not yet. Why don't you call me Sheen? | 专名/术语 |
| `846` | >> 正如我之前对哨兵说话的那样，我 | **>> 正如我之前对岁主说话的那样，我** | >> As I address the Sentinel before, so I | 专名/术语 |
| `853` | 一个被弗赖杜斯陷害的逃犯 | **一个被残星会陷害的逃犯** | A fugitive framed by the Fraidus, | 二次校准 |
| `855` | 弗雷杜斯 | **残星会** | Fraidus. | 专名/术语 |
| `857` | >> 与人有深厚联系的银杏巡逻员 | **>> 与人有深厚联系的今州巡逻员** | >> The Gingjo patroller who has deep ties | 二次校准 |
| `871` | 小蜂群的派对很安静 | **小锁暝的派对很安静** | party for Little Swarming were quite | 二次校准 |
| `880` | 我迫不及待想玩《枯萎战争》 | **我迫不及待想玩《鸣潮》** | I can't wait to play War of Withering | 二次校准 |
| `881` | Waves主线任务。那我先走了 | **主线任务。那我先走了** | Waves main story quest. So, I'll see you | 二次校准 |

## 六、遗留问题（未自动改）

- **学习库跨片源坏裸键**：`骑士→明日方舟`、`真的→其实`、`这种情况→这最后`、`应得的→不配拥有` 等在会话期间被并发会话反复增删，会误伤本片；本片已逐条回滚，建议长期 `learned-reject` 或做片源隔离。
- **未翻译英文残片**：`#441/449/480 I`、`#627/743 A`、`#835 A,`（英文 ASR 把单词单独成 cue）。
- **整行连词**：`#320 但是`、`#782 所以`（机翻把连词单独成 cue）。
- **存疑未改**（无官方依据，不臆断）：`#50 Orbiter/轨道者`、`#166 Sention`、`#551 Shuin/修院`、`#809 Sen/千`、`#831 withering wives`、`#112 Ruba`、`#120 mechanic/机械师`、`#351 Outr Rididers`、`#350 Yuan Fortress`。
