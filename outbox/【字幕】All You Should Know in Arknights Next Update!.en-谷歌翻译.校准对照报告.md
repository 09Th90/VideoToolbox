# 字幕校准对照报告（二次校准·101 处中文改动）

只改含汉字的中文行，序号 / 时间轴 / 空行 / CRLF / 无 BOM / 英文参考行全部零改动。
本片 132 cue、822 行，一次成型（体量小，无需分段）。

## 相对首版（95 处）的二校新增（6 处 + 2 处回改）
| cue | 机翻 | 二校后 | 依据 |
| --- | --- | --- | --- |
| 30 | 穆缪之后的战术先锋 → 缪缪 | 缪尔赛思之后的战术家 | Muelsyse 官方名=缪尔赛思（旧目标"缪缪"是昵称非官方，回改）|
| 48 | 致即将成为干员的Thumphy | 致即将成为干员的珊比 | Thumpy=六星重装·本源铁卫珊比（700g 图鉴截图 Crackborne→裂响 / Thumpy→珊比，百度百科+夏活公告交叉确认）|
| 51 | 一个能减少敌人的施法者 | 一个能减少敌人的术师 | Caster 官方职业名=术师；GALLUS² 天赋"使敌人法术抗性降低" |
| 51 | 阻力持续几秒 | 法术抗性持续几秒 | resistance 在此=法术抗性 |
| 75 | 治疗师的医护人员 | 疗养师的医疗干员 | Therapist 官方医疗子职业=疗养师（流明/锡兰/絮雨/清流）|
| 115 | 红色令牌…证书商店 | 采购凭证…凭证交易所 | 官方公告用语：采购凭证商店 / 采购中心-凭证交易所 |
| 125 | 暴行新娘皮肤 | 暴行「又一年秋季」皮肤 | 官方活动服饰名：忒斯特收藏系列-又一年秋季-暴行 |
| 127 | 标准池，用于kernel | 标准寻访，用于中坚甄选 | Kernel Locating=中坚甄选官方英文名（官网活动预告）；standard=标准寻访 |
| 129 | 你在人生中见过 | 你在直播见过 | livestream 被 ASR 断成 life stream，谷翻"人生中" |

## 存疑清零
首版三处存疑（Thumphy / kernel / 遥）经核实：Thumphy=珊比、kernel=中坚甄选已定稿；
遥（Haruka，东国偶像，本名紫野遥）官方名即"遥"，首版正确，无需改。

## 结构校验
- verify：timestamp diffs 0 / reference diffs 0 / 序号·参考行·CRLF·BOM 全一致。
- 逐行 diff（822 行）：101 处差异全部落在含汉字行，非中文行被改 0。
- align-audit：无串位嫌疑；两次独立运行输出逐字节一致（幂等）。

## 脚本优化（subtitle_calib_merged.py，本次同步沉淀）
1. **--ak 分支改造**：旧实现只改每 cue 首中文行、ctx 锚点只取末行英文 → 谷翻片
   「中文2行+英文2行」结构下第二中文行整片漏校、佐证词在英文首行时 ctx 失效。
   现按"含汉字=中文行"逐行校准全部中文行，锚点=全部英文行拼接后规整空白
   （修 ASR 行尾双空格导致跨行佐证词漏命中，如 #56 加维尔）。英文行一律不动。
2. **AK_TERMS 补录**（官方名，裸键安全）：维伊/裂响/珊比/GALLUS²/提丰/归溟幽灵鲨/
   缄默德克萨斯/信仰搅拌机/守望者/缪尔赛思；"凯尔希异格"回改为官方全名"凯尔希·思衡托"。
3. **AK_CONTEXT 修正+新增**：修 `\bbenablers?\b`→`\benablers?\b` 正则笔误；
   新增 限量版/限制→限定、明星→一星、标准6星→常驻六星、CN服务器→国服、重新部署→再部署、
   元素伤害→元素损伤、名次→放置、施法者→术师、治疗师→疗养师、腐蚀→侵蚀、
   原始防御者→本源铁卫、战术先锋→战术家、红色令牌→采购凭证、证书商店→凭证交易所、
   kernel→中坚甄选、life stream→直播 等锚定规则。

---

## 附：全部 101 条改动对照

`4` | 主线故事第17集 | **主线故事第17章** | will be life on October 14,
`4` | 将于10月14日出生 | **将于10月14日上线** | will be life on October 14,
`5` | 我们将继续在乌尔苏斯的旅程， | **我们将继续在乌萨斯的旅程，** | and search for a way to bring back the old well.
`6` | CN 服务器七周年纪念 | **国服七周年纪念** | the 7th anniversary for CN server,
`9` | 并给你看第17集 | **并给你看第17章** | stage mechanics and enemies.
`10` | 首先，让我们看看新的操作员 | **首先，让我们看看新的干员** | First, let's see the new operators.
`11` | 我们会有新的限量版 | **我们会有新的限定** | banner, with 5 new operators.
`11` | 旗帜，新增5个干员 | **卡池，新增5个干员** | banner, with 5 new operators.
`12` | 本事件的限制是 | **本事件的限定是** | none other than Kal sey alter.
`12` | 正是卡尔·塞·阿尔特 | **正是凯尔希·思衡托** | none other than Kal sey alter.
`15` | 无论如何，未来五个月所有运营商的意见 | **无论如何，未来五个月所有干员的意见** | Anyway, from all operators in the next 5 months,
`16` | 我认为Kal sey alter是 | **我认为凯尔希·思衡托是** | the top priority to get.
`17` | 是一名守望人，一个能飞的医护人员 | **是一名守望者，一个能飞的医疗干员** | is a watch man medic, a medic who can fly
`18` | 但当其他典型中的人 | **但当其他职业分支中的人** | fly during their skills.
`19` | Kal Sey凭借她的才华将永远飞翔 | **凯尔希凭借她的天赋将永远飞翔** | Kal sey will forever fly, thanks to her talent.
`21` | 她的技能2是轻松获得范围真伤害的来源 | **她的技能2是轻松获得范围真实伤害的来源** | Her skill 2 is an easy source of AOE true damage,
`22` | 这也能治疗操作员 | **这也能治疗干员** | that got caught in the blast.
`24` | 以及另外两个操作员 | **以及另外两个干员** | and 2 other operators.
`25` | 这被视为重新部署 | **这被视为再部署** | It is considered as redeployment,
`27` | 与此同时，标准的6星 | **与此同时，常驻六星** | her is our favorite scam artist Closure.
`27` | 她是我们最喜欢的骗子Closure | **她是我们最喜欢的骗子可露希尔** | her is our favorite scam artist Closure.
`30` | 穆穆之后的战术先锋 | **缪尔赛思之后的战术家** | tactician vanguard after Mumu.
`31` | 结局是最好的之一 | **可露希尔是最好的之一** | units to start your stage.
`32` | 可以减少3，或4，具有潜力 | **可以减少3，或4，具有潜能** | can be reduced by 3, or 4 with potential.
`34` | 即使闭合是激活状态 | **即使可露希尔是激活状态** | just simply in the squad.
`38` | 相比卡尔，她的优先级其实更低 | **相比凯尔希，她的优先级其实更低** | Compared to Kal, she's honestly a lower priority.
`41` | 一个叫Viy的新角色 | **一个叫维伊的新角色** | A new character called Viy.
`42` | 他是神秘施法者 | **他是秘术师** | He is a mystic caster.
`44` | 神秘施法者能达到的还算不错的水平 | **秘术师能达到的还算不错的水平** | as decent as mystic caster can get.
`45` | 抽卡5星是个叫克拉克伯恩的人 | **抽卡5星是个叫裂响的人** | The gacha 5 star is someone called Crackborne.
`46` | 专注于腐蚀的原始防御者 | **专注于侵蚀的本源铁卫** | Primal defender that focuses on corrosion.
`47` | 作为罐体单元或腐蚀 | **作为坦克单位或侵蚀** | enabler, she's honestly not great.
`47` | 纵容者，说实话她并不好 | **启动器，说实话她并不好** | enabler, she's honestly not great.
`48` | 致即将成为操作员的Thumphy | **致即将成为干员的珊比** | for upcoming operator Thumphy,
`50` | 这次更新中的明星，名为Gallus | **这次更新中的一星，名为GALLUS²** | star in this update, called Gallus.
`51` | 一个能减少敌人的施法者 | **一个能减少敌人的术师** | resistance for a few seconds
`51` | 阻力持续几秒 | **法术抗性持续几秒** | resistance for a few seconds
`53` | 这些之前的限量赛将获得 | **这些之前的限定干员将获得** | a rate up in the limited banner.
`53` | 限量卡池中的卡率提升 | **限定卡池中的概率提升** | a rate up in the limited banner.
`54` | Kal sey alter 或她的潜力 | **凯尔希·思衡托 或她的潜能** | is guaranteed at 300 pulls.
`55` | 幽灵变形的火花消耗也降低了 | **归溟幽灵鲨的黄票兑换消耗也降低了** | And the spark cost for specter alter is reduced,
`56` | 加维尔也是同样的情况 | **百炼嘉维尔也是同样的情况** | alter in the next limited banner.
`56` | 下一个限量卡池 | **下一个限定卡池** | alter in the next limited banner.
`57` | 新算符尚未完整 | **新干员尚未完整** | without some new skins.
`59` | 然后这里是重播的皮肤， | **然后这里是复刻皮肤，** | and more should be available
`61` | 记住我可能会买到一些东西 | **记住我可能会弄错一些东西** | wrong from the Chinese translation,
`62` | 所以一定要之后再仔细检查各个阶段 | **所以一定要之后再仔细检查各个关卡** | so make sure to examine the stages again later.
`63` | 第17集，看起来我们正在战斗 | **第17章，看起来我们正在战斗** | In episode 17, it looks like we are fighting in
`64` | 乌尔苏斯的秘密实验室和 | **乌萨斯的秘密实验室和** | fighting their bio weapons.
`65` | 在这些阶段，你的操作员将持续进行 | **在这些关卡，你的干员将持续进行** | take a DoT damage from chemical leak.
`66` | 只要你带足够的医疗兵 | **只要你带足够的医疗干员** | as long as you bring enough medic.
`67` | 泄露可以增强敌人能力 | **泄漏可以增强敌人能力** | leak can enhance enemy abilities.
`68` | 每当你的操作员受到伤害 | **每当你的干员受到伤害** | whenever your operators take damage,
`69` | 你可以用它来定位漏水源 | **你可以用它来定位泄漏源** | you can use to locate the leak source.
`72` | 或者在该格子上放置一个操作员，或者 | **或者在该格子上放置一个干员，或者** | surrounding 4 tiles to stop the leak.
`72` | 用4块瓷砖围住堵漏 | **用4块格子围住堵漏** | surrounding 4 tiles to stop the leak.
`73` | 但小心点，那个操作员 | **但小心点，那个干员** | will be stunned temporarily,
`73` | 会暂时昏迷 | **会暂时眩晕** | will be stunned temporarily,
`74` | 这一集会非常有眩晕效果 | **这一章会非常有眩晕效果** | this episode is going to be quite stun heavy,
`75` | 所以可能要带个晕眩装备 | **所以可能要带个眩晕对策** | counter like a therapist medic.
`75` | 反击就像治疗师的医护人员 | **反击就像疗养师的医疗干员** | counter like a therapist medic.
`78` | 赛段还会有 | **关卡还会有** | this leak mark or something.
`78` | 这个漏水痕迹什么的 | **这个泄漏标记什么的** | this leak mark or something.
`80` | 将在第17集战斗 | **将在第17章战斗** | will fight in Episode 17
`81` | 至于老板 | **至于Boss** | As for the boss.
`82` | 我们将与卡尔·赛机械形态战斗 | **我们将与凯尔希机械形态战斗** | We'll be fighting Kal sey mechanical form.
`85` | 所有物理和术技伤害都会被处理 | **所有物理和法术伤害都会被处理** | from outside the wall will be reduced.
`86` | 墙内的操作员 | **墙内的干员** | operators inside the wall.
`87` | 所以通常你想要名次 | **所以通常你想要放置** | your operators somewhere,
`87` | 你的操作员们在某处 | **你的干员们在某处** | your operators somewhere,
`89` | 无论是使用元素伤害还是真实伤害 | **无论是使用元素损伤还是真实伤害** | by using either elemental or true damage.
`91` | 这会对操作员造成伤害和眩晕 | **这会对干员造成伤害和眩晕** | that will damage and stun operators.
`93` | 但同样的抵抗 | **但同样的法术抗性** | but the same resistance.
`94` | 有点像《我之剑3》里的那个中路Boss，如果有的话 | **有点像集成战略3里的那个中路Boss，如果有的话** | boss is defeated, but the other one still alive,
`101` | 屏风打断她的能力 | **屏幕打断她的能力** | screen to interrupt her ability.
`102` | 最终让旧水井恢复 | **最终让旧井恢复** | eventually bring back the old well.
`103` | 清除所有这些章节阶段 | **清除所有这些章节关卡** | should give you about 40 yellow rocks.
`103` | 应该能给你大约40块黄色石头 | **应该能给你大约40块至纯源石** | should give you about 40 yellow rocks.
`104` | 第17集引入的材料 | **第17章引入的材料** | materials introduced in episode 17.
`107` | 新模块 | **新模组** | For new module.
`108` | 没有新的原型模块 | **没有新的职业分支模组** | No new archetype module.
`109` | 但所有新的操作员原型 | **但所有新的干员职业分支** | already have module will instantly get one.
`109` | 已经有模块的人会立刻获得一个 | **已经有模组的人会立刻获得一个** | already have module will instantly get one.
`110` | 还有第二个模块是关于Degen的， | **还有第二个模组是关于锏的，** | Sankta grandpa, and Texas alter.
`110` | Sankta爷爷，德州祭坛 | **信仰搅拌机，缄默德克萨斯** | Sankta grandpa, and Texas alter.
`111` | 以及一个专门的模块 | **以及一个专门的模组** | for Specter alter and Typhon.
`111` | 为幽灵祭坛和泰丰 | **为归溟幽灵鲨和提丰** | for Specter alter and Typhon.
`112` | 新的操作员记录和悖论模拟 | **新的干员密录和悖论模拟** | New operator record and paradox simulation.
`115` | 红色令牌新增内容 | **采购凭证新增内容** | shop, and certificate shop.
`115` | 商店，证书商店 | **商店，凭证交易所** | shop, and certificate shop.
`117` | 但对收复局有重大更新 | **但对生息演算有重大更新** | algorithm should be available soon.
`119` | 星级选择器，以及新的界面主题 | **星级自选券，以及新的界面主题** | star selector, and new UI theme.
`121` | 比如免费10次抽取，免费每日Orundum，还有 | **比如免费10次抽取，免费每日合成玉，还有** | 1 free daily pull on the limited banner.
`121` | 限量卡池每日免费抽卡一次 | **限定卡池每日免费抽卡一次** | 1 free daily pull on the limited banner.
`122` | 新增了总登录奖励 | **新增了累计登录奖励** | There's a new total login reward,
`123` | 在总共登录1500天后 | **在累计登录1500天后** | after a total of 1500 days of login.
`124` | 一部以卡尔·赛为主角的新短漫画 | **一部以凯尔希为主角的新短漫画** | been released on Arknights official website.
`125` | 你的那部分，这样我们都能得到Savage新娘皮肤 | **你的那部分，这样我们都能得到暴行「又一年秋季」皮肤** | your part, so we all can get Savage bride skin.
`126` | 我们换了个新的高级六星选择器 | **我们换了个新的高级六星自选券** | We got a new premium 6 star selector.
`127` | 标准池，以及这个用于kernel的 | **标准寻访，以及这个用于中坚甄选的** | standard pool, and this one for kernel.
`129` | 虽然有些事情你在人生中见过 | **虽然有些事情你在直播见过** | stream are probably only available in Japan,
