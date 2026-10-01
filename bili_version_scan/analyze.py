# -*- coding: utf-8 -*-
"""B站「最近版本」视频：标题 / 标签 高频词与短语分析 -> Excel

输入 raw.json（scan.py 产出），输出 xlsx。
"""
import json
import os
import re
import sys
from collections import Counter, defaultdict

import jieba

BASE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(BASE, 'raw.json')
OUT = os.path.join(BASE, 'B站版本视频标题标签高频词分析.xlsx')

# ---------------------------------------------------------------- 相关性过滤
# 蹭标签识别：这些标签只表示「参与激励活动」，不代表内容与游戏有关
INCENTIVE = re.compile(r'创作激励|激励计划|创作计划|应援计划|创作者应援|激励企划|创作企划|萌新计划')

# 信号词：命中即认定与该游戏相关（游戏名 + 本版本名）
SIGNAL = {
    '鸣潮': ['鸣潮', '蜃云灯影', '凡尘剑心'],
    '终末地': ['终末地', '雪凇幽梦', '雪淞幽梦'],
    '明日方舟': ['明日方舟', '月行水上'],
    '战双帕弥什': ['战双', '远信回响'],
}


def is_relevant(game, r):
    sig = SIGNAL[game]
    if any(s in r['title'] for s in sig):
        return True
    plain = [t for t in r['tag_list'] if not INCENTIVE.search(t)]
    return any(any(s in t for s in sig) for t in plain)


# ---------------------------------------------------------------- 分词配置
USER_WORDS = [
    '鸣潮', '明日方舟', '终末地', '战双帕弥什', '战双', '库洛', '鹰角', '海猫',
    '雪凇幽梦', '月行水上', '远信回响', '蜃云灯影', '歧海循光', '凡尘剑心',
    '共鸣者', '声骸', '索拉里斯', '玄方', '清宵', '景燃', '锁暝', '心月狐',
    '漂泊者', '菲比', '糯糯', '达妮娅', '坎特蕾拉', '卡提希娅', '洛瑟菈',
    '干员', '罗德岛', '泰拉', '女神异闻录', '结城理', '阿米娅', '佩丽卡',
    '提弗洛斯', '普瑞赛斯', '管理员', '阿达希尔', '陈千语', '萨卡兹',
    '构造体', '机体', '涂装', '意识', '露西亚', '卡列尼娜', '比安卡',
    '赛琳娜', '阿德莱德', '多米尼克', '万小ci', '露莎卡',
    '卡池', '抽卡', '保底', '出货', '欧皇', '非酋', '零氪', '氪金', '白嫖',
    '前瞻', '实机', '攻略', '解析', '测评', '二创', '同人', '混剪', 'GMV',
    '高燃', '手书', '翻唱', '配队', '阵容', '强度', '榜单', '排行', '排行',
    '兑换码', '福利', '开荒', '速通', '无伤', '满命', '满级', '毕业', '潜能',
    '立绘', '皮肤', '时装', '剧情', '联动', '活动', '版本', '直播', '录播',
    '解说', '教学', '新手', '回归', '开箱', '模拟器', '手游', '二游',
    'cos', 'Cos', 'COS', 'cosplay', 'Cosplay', 'MMD', 'AMV', 'PV', 'CG',
    '3.6', '3.7', '1.5', '4K', '60帧', '无UI', '摆完挂机', '抄作业', '以防你不知道',
]
for w in USER_WORDS:
    jieba.add_word(w, freq=100000)

STOP = set('''的 了 是 在 我 你 他 她 它 们 这 那 有 和 与 就 都 也 还 又 很 太 更 最 不 没 要 会 能 可
可以 一个 什么 怎么 如何 为什么 吗 呢 吧 啊 呀 哦 嗯 一 二 三 四 五 六 七 八 九 十 个 只 把 被 给 让
从 到 对 为 以 及 而 但 却 则 之 其 此 该 各 些 好 真 说 看 来 去 做 用 想 觉得 感觉 现在 已经 就是
这个 那个 我们 你们 他们 自己 一下 一起 大家 还是 但是 因为 所以 如果 虽然 然后 而且 以及 还有 没有
不是 不能 不要 真的 好像 其实 应该 可能 一定 非常 特别 超级 直接 完全 终于 居然 竟然 到底 视频 分享
推荐 系列 第 期 集 时候 这样 那样 为何 今天 昨天 明天 以后 之前 之后 东西 事情 地方 问题 方式 样子
我的 你的 他的 她的 这些 那些 知道 这么 那么 多少 什么 怎么 为啥 咋 的话 一句 一直 已经 一下 起来
出来 过来 下来 上去 进去 回来 上去 之上 之下 之中 之类 等等 另外 其他 其它 别的 每个 某个 某些 各种
各自 之后 之后 于是 只是 不过 而且 甚至 尤其 例如 比如 就像 好像 似乎 大概 也许 或许 当然 果然
依然 仍然 依旧 重新 再次 一起 一同 分别 各自 相互 互相 突然 忽然 立刻 马上 终于 最终 最后 首先
其次 再次 平时 通常 一般 经常 常常 有时 偶尔 总是 从来 一直 始终 曾经 从来 一般 一样 类似 相同
不同 各种 全部 所有 整个 部分 主要 重要 简单 复杂 容易 困难 大 小 多 少 高 低 长 短 新 旧 老
上 下 前 后 中 里 外 内 左 右 东 西 南 北 人 事 物 时间 空间 世界 现在 未来 过去 开始 结束
哈哈 嘿嘿 嘻嘻 啊啊 呜呜 呜呜呜 233 666 2333 23333'''.split())

# 允许保留的单字词（游戏角色名等）
SINGLE_OK = {'心', '坎', '锁', '暝', '舟', '粥'}

PUNCT_ONLY = re.compile(r'^[\W_]+$')
HAS_CJK = re.compile(r'[\u4e00-\u9fff]')
TOKEN_OK = re.compile(r'^[\u4e00-\u9fffA-Za-z0-9\.]+$')


def tokens(title):
    out = []
    for w in jieba.lcut(title):
        w = w.strip()
        if not w or w in STOP or PUNCT_ONLY.match(w) or not TOKEN_OK.match(w):
            continue
        if len(w) == 1:
            if not HAS_CJK.match(w):
                continue
            if w not in SINGLE_OK:
                continue
        out.append(w)
    return out


def word_freq(titles):
    c = Counter()
    vids = defaultdict(set)
    for i, t in enumerate(titles):
        for w in set(tokens(t)):
            c[w] += 1
            vids[w].add(i)
    return c, vids


def phrase_freq(titles, nmin=2, nmax=3):
    c = Counter()
    vids = defaultdict(set)
    for i, t in enumerate(titles):
        ws = tokens(t)
        for n in range(nmin, nmax + 1):
            for j in range(len(ws) - n + 1):
                seg = ws[j:j + n]
                if all(x in STOP for x in seg):
                    continue
                if len(set(seg)) == 1:      # 去掉「齁 齁 齁」这类重复堆叠
                    continue
                p = ' '.join(seg)
                c[p] += 1
                vids[p].add(i)
    return c, vids


def tag_freq(rows):
    c = Counter()
    games = defaultdict(set)
    for r in rows:
        for t in set(r['tag_list']):
            c[t] += 1
            games[t].add(r['game'])
    return c, games


def main():
    data = json.load(open(RAW, encoding='utf-8'))
    filtered = {}
    for g, rows in data.items():
        filtered[g] = [r for r in rows if is_relevant(g, r)]
        print('%-10s 候选 %4d -> 相关 %4d' % (g, len(rows), len(filtered[g])))

    all_rows = []
    for g, rows in filtered.items():
        all_rows.extend(rows)
    all_rows.sort(key=lambda r: (r['game'], -r['play']))
    titles = [r['title'] for r in all_rows]
    N = len(all_rows)

    gw, gwv = word_freq(titles)
    gp, gpv = phrase_freq(titles)
    gt, gtg = tag_freq(all_rows)

    per = {}
    for g, rows in filtered.items():
        ts = [r['title'] for r in rows]
        per[g] = dict(n=len(rows), w=word_freq(ts), p=phrase_freq(ts), t=tag_freq(rows))

    build_xlsx(filtered, all_rows, N, gw, gwv, gp, gpv, gt, gtg, per)
    # 控制台速览
    print('\n--- 全局标题高频词 TOP30 ---')
    shown = 0
    for w, n in gw.most_common(400):
        if len(gwv[w]) < 2:
            continue
        print('   %-14s %4d  (%d 条视频)' % (w, n, len(gwv[w])))
        shown += 1
        if shown >= 30:
            break
    print('\n--- 全局标题高频短语 TOP25 ---')
    shown = 0
    for p, n in gp.most_common(600):
        if len(gpv[p]) < 3:
            continue
        print('   %-20s %4d  (%d 条视频)' % (p, n, len(gpv[p])))
        shown += 1
        if shown >= 25:
            break
    print('\n--- 全局标签 TOP30 ---')
    for t, n in gt.most_common(30):
        print('   %-28s %4d' % (t, n))


def build_xlsx(filtered, all_rows, N, gw, gwv, gp, gpv, gt, gtg, per):
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    hf = Font(bold=True, color='FFFFFF')
    hfill = PatternFill('solid', fgColor='305496')
    center = Alignment(horizontal='center', vertical='center')

    def sheet(title, headers, rows, widths=None):
        ws = wb.create_sheet(title)
        ws.append(headers)
        for c in ws[1]:
            c.font = hf
            c.fill = hfill
            c.alignment = center
        for r in rows:
            ws.append(r)
        ws.freeze_panes = 'A2'
        if widths:
            for i, w in enumerate(widths, 1):
                ws.column_dimensions[get_column_letter(i)].width = w
        return ws

    # 1 说明
    ws = wb.active
    ws.title = '说明'
    raw_total = sum(1 for _ in all_rows)  # 占位，稍后覆盖
    lines = [
        ['B站「最近一个版本」视频  标题 / 标签  高频词与短语分析', ''],
        ['', ''],
        ['数据来源', 'B站搜索接口 api.bilibili.com/x/web-interface/search/type'],
        ['采集时间', '2026-09-29'],
        ['筛选条件', '播放量 >= 5000'],
        ['范围', '各游戏「最近一个版本」内发布的视频'],
        ['相关性过滤', '标题或标签须命中「游戏名 / 本版本名」；仅挂「创作激励/应援计划」类标签的蹭标签视频已剔除'],
        ['', ''],
        ['游戏', '版本 ｜ 窗口 ｜ 样本量 ｜ 播放中位数 ｜ 播放合计'],
    ]
    for g, rows in filtered.items():
        ver = rows[0]['version'] if rows else ''
        dts = sorted(r['pubdate'] for r in rows)
        rng = '%s ~ %s' % (dts[0], dts[-1]) if dts else '-'
        plays = [r['play'] for r in rows]
        lines.append([g, '%s ｜ %s ｜ %d 条 ｜ %s ｜ %s' % (
            ver, rng, len(rows), '{:,}'.format(_med(plays)), '{:,}'.format(sum(plays)))])
    lines += [
        ['', ''],
        ['样本合计', '%d 条视频' % N],
        ['', ''],
        ['表页说明', '全部视频=明细；标题高频词/短语=对全部标题分词与n-gram统计；标签频次=标签去重计数；分游戏-*=各游戏TOP榜'],
        ['统计口径', '标题词/短语已剔除停用词与单字（保留角色名单字）；词需覆盖>=2条视频、短语需覆盖>=3条视频；短语为2~3词的连续片段'],
        ['注意', '播放量为采集时点快照；B站搜索有结果上限，样本为可达集合而非全站穷举'],
    ]
    for r in lines:
        ws.append(r)
    ws['A1'].font = Font(bold=True, size=14)
    ws.column_dimensions['A'].width = 18
    ws.column_dimensions['B'].width = 100
    for row in ws.iter_rows():
        for c in row:
            c.alignment = Alignment(vertical='center')

    # 2 全部视频
    sheet('全部视频',
          ['游戏', '版本', '标题', 'UP主', '播放量', '点赞', '弹幕', '收藏', '发布时间', '时长', '标签', '链接'],
          [[r['game'], r['version'], r['title'], r['author'], r['play'], r['like'],
            r['danmaku'], r['favorites'], r['pubdate'], r['duration'], r['tag'], r['url']]
           for r in all_rows],
          [11, 22, 60, 18, 10, 9, 8, 8, 11, 8, 55, 40])

    # 3 标题高频词
    words = [(w, n) for w, n in gw.most_common(400) if len(gwv[w]) >= 2]
    sheet('标题高频词',
          ['排名', '词', '出现次数', '覆盖视频数', '覆盖率%'],
          [[i, w, n, len(gwv[w]), round(100.0 * len(gwv[w]) / max(1, N), 1)]
           for i, (w, n) in enumerate(words[:200], 1)],
          [6, 22, 10, 12, 10])

    # 4 标题高频短语
    phrases = [(p, n) for p, n in gp.most_common(600) if len(gpv[p]) >= 3]
    sheet('标题高频短语',
          ['排名', '短语', '出现次数', '覆盖视频数', '覆盖率%'],
          [[i, p, n, len(gpv[p]), round(100.0 * len(gpv[p]) / max(1, N), 1)]
           for i, (p, n) in enumerate(phrases[:200], 1)],
          [6, 30, 10, 12, 10])

    # 5 标签频次
    sheet('标签频次',
          ['排名', '标签', '出现次数', '覆盖率%', '涉及游戏'],
          [[i, t, n, round(100.0 * n / max(1, N), 1), ' / '.join(sorted(gtg[t]))]
           for i, (t, n) in enumerate(gt.most_common(300), 1)],
          [6, 36, 10, 10, 24])

    # 6/7/8 分游戏
    for kind, label in (('w', '词'), ('p', '短语'), ('t', '标签')):
        rows = []
        for g, d in per.items():
            cnt, extra = d[kind]
            for i, (k, n) in enumerate(cnt.most_common(80), 1):
                rows.append([g, i, k, n, len(extra[k])])
        sheet('分游戏-高频%s' % label, ['游戏', '排名', label, '出现次数', '覆盖视频数'],
              rows, [12, 6, 30, 10, 12])

    wb.save(OUT)
    print('\n已生成 ->', OUT)


def _med(a):
    a = sorted(a)
    n = len(a)
    if not n:
        return 0
    return a[n // 2] if n % 2 else (a[n // 2 - 1] + a[n // 2]) // 2


if __name__ == '__main__':
    main()
