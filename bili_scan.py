# -*- coding: utf-8 -*-
# @version 1.16.5
"""B站版本热榜扫描：抓取指定关键词在时间窗口内的视频（标题/标签/播放量）。"""
import urllib.request, urllib.parse, json, time, os, sys, hashlib, re

BASE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(BASE, 'bili_raw.json')

UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')


def get_buvid():
    req = urllib.request.Request('https://api.bilibili.com/x/frontend/finger/spi',
                                 headers={'User-Agent': UA})
    d = json.load(urllib.request.urlopen(req, timeout=20))
    return d['data']['b_3'], d['data']['b_4']


B3, B4 = get_buvid()
HEAD = {
    'User-Agent': UA,
    'Referer': 'https://www.bilibili.com/',
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'zh-CN,zh;q=0.9',
    'Origin': 'https://www.bilibili.com',
    'Cookie': 'buvid3=%s; buvid4=%s' % (B3, B4),
}


def ts(s):
    return int(time.mktime(time.strptime(s, '%Y-%m-%d')))


def api(params, retry=4):
    url = 'https://api.bilibili.com/x/web-interface/search/type?' + urllib.parse.urlencode(params)
    for i in range(retry):
        try:
            req = urllib.request.Request(url, headers=HEAD)
            return json.load(urllib.request.urlopen(req, timeout=25))
        except Exception as e:
            sys.stderr.write('retry%d %s\n' % (i, e))
            time.sleep(2.5 * (i + 1))
    return None


GAMES = {
    '鸣潮': dict(kw=['鸣潮', '鸣潮3.6', '清宵 鸣潮', '景燃', '蜃云灯影'],
              win=('2026-08-20', '2026-09-29')),
    '终末地': dict(kw=['终末地', '明日方舟 终末地', '雪凇幽梦', '提福洛斯'],
               win=('2026-09-02', '2026-09-28')),
    '明日方舟': dict(kw=['明日方舟', '月行水上', '明日方舟 联动', '方舟 P3R'],
                win=('2026-09-05', '2026-09-28')),
    '战双帕弥什': dict(kw=['战双帕弥什', '战双', '歧海循光', '卡列尼娜 战双'],
                 win=('2026-08-19', '2026-09-28')),
}

MIN_PLAY = 5000


def clean(t):
    return re.sub(r'</?em[^>]*>', '', t or '')


def main():
    out = {}
    total = 0
    for game, cfg in GAMES.items():
        b = int(time.mktime(time.strptime(cfg['win'][0], '%Y-%m-%d')))
        e = int(time.mktime(time.strptime(cfg['win'][1], '%Y-%m-%d'))) + 86399
        seen = {}
        for kw in cfg['kw']:
            for order in ('click', 'pubdate'):
                for page in range(1, 26):
                    d = api({'search_type': 'video', 'keyword': kw, 'page': page,
                             'order': order, 'pubtime_begin_s': b, 'pubtime_end_s': e})
                    if not d or d.get('code') != 0 or not d.get('data') or not d['data'].get('result'):
                        break
                    res = d['data']['result']
                    for r in res:
                        bv = r.get('bvid')
                        if not bv or bv in seen:
                            continue
                        pd = r.get('pubdate', 0)
                        if not (b <= pd <= e):
                            continue
                        seen[bv] = dict(
                            bvid=bv, title=clean(r.get('title')), author=r.get('author'),
                            play=r.get('play', 0), danmaku=r.get('video_review', 0),
                            like=r.get('like', 0), favorites=r.get('favorites', 0),
                            pubdate=time.strftime('%Y-%m-%d', time.localtime(pd)),
                            duration=r.get('duration'), tag=(r.get('tag') or ''),
                            url='https://www.bilibili.com/video/' + bv,
                            kw=kw, game=game,
                            desc=(clean(r.get('description')) or '')[:300],
                        )
                    if len(res) < 20:
                        break
                    time.sleep(1.1)
                time.sleep(1.0)
        rows = [v for v in seen.values() if v['play'] >= MIN_PLAY]
        rows.sort(key=lambda x: -x['play'])
        out[game] = rows
        total += len(rows)
        print('%-8s 窗口 %s~%s  >=5000播放: %d 条 (共抓 %d)' % (game, cfg['win'][0], cfg['win'][1], len(rows), len(seen)))
        sys.stdout.flush()
    json.dump(out, open(RAW, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('总计', total, '->', RAW)


if __name__ == '__main__':
    main()
