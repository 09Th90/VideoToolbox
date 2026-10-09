# -*- coding: utf-8 -*-
# @version 1.18.3
"""B站「最近版本」视频扫描器

策略：
  * 用 search/type 接口 + pubtime_begin_s/pubtime_end_s 把结果限制在版本窗口内；
  * order=click（窗口内按播放量降序）为主，翻页直到整页播放量 < 阈值；
  * order=pubdate（窗口内按时间降序）为辅，补充覆盖；
  * 客户端再做 播放量>=5000 + 相关性 过滤（剔除「蹭创作激励标签」的无关视频）。

输出：raw.json —— {游戏: [视频, ...]}
"""
import urllib.request
import urllib.parse
import json
import time
import re
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(BASE, 'raw.json')

UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')

MIN_PLAY = 5000

# 版本窗口与检索词（依据官方更新公告）
GAMES = {
    '鸣潮': dict(
        version='3.6「蜃云灯影，凡尘剑心」',
        win=('2026-08-20', '2026-09-29'),
        kw=['鸣潮', '鸣潮3.6', '蜃云灯影'],
        names=['鸣潮'],
    ),
    '终末地': dict(
        version='1.5「雪凇幽梦」',
        win=('2026-09-02', '2026-09-29'),
        kw=['终末地', '明日方舟终末地', '雪凇幽梦'],
        names=['终末地'],
    ),
    '明日方舟': dict(
        version='SideStory「月行水上」',
        win=('2026-09-04', '2026-09-29'),
        kw=['明日方舟', '月行水上'],
        names=['明日方舟'],
    ),
    '战双帕弥什': dict(
        version='「远信回响」',
        win=('2026-09-24', '2026-09-29'),
        kw=['战双帕弥什', '战双', '远信回响'],
        names=['战双'],
    ),
}

# 「创作激励」类标签是重灾区（无关视频也挂它），相关性判定时先剔除
INCENTIVE_PAT = re.compile(r'创作激励|激励计划|创作计划')


def _buvid():
    req = urllib.request.Request('https://api.bilibili.com/x/frontend/finger/spi',
                                 headers={'User-Agent': UA})
    d = json.load(urllib.request.urlopen(req, timeout=20))
    return d['data']['b_3'], d['data']['b_4']


B3, B4 = _buvid()
HEAD = {
    'User-Agent': UA,
    'Referer': 'https://www.bilibili.com/',
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'zh-CN,zh;q=0.9',
    'Origin': 'https://www.bilibili.com',
    'Cookie': 'buvid3=%s; buvid4=%s' % (B3, B4),
}


def _ts(s):
    return int(time.mktime(time.strptime(s, '%Y-%m-%d')))


def api(params, retry=4):
    url = 'https://api.bilibili.com/x/web-interface/search/type?' + urllib.parse.urlencode(params)
    for i in range(retry):
        try:
            req = urllib.request.Request(url, headers=HEAD)
            return json.load(urllib.request.urlopen(req, timeout=25))
        except Exception as e:
            sys.stderr.write('  retry%d %s\n' % (i, e))
            time.sleep(2.0 * (i + 1))
    return None


def clean(t):
    t = re.sub(r'</?em[^>]*>', '', t or '')
    t = t.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>').replace('&quot;', '"')
    return t.strip()


def tags_of(v):
    return [x.strip() for x in (v.get('tag') or '').split(',') if x.strip()]


def relevance(game_cfg, title, tag_list):
    """命中游戏本体名才算相关；仅靠「创作激励」标签命中的一律判为无关。"""
    plain = [t for t in tag_list if not INCENTIVE_PAT.search(t)]
    for nm in game_cfg['names']:
        if nm in title:
            return True
        if any(nm == t or nm in t for t in plain):
            return True
    return False


def collect():
    out = {}
    for game, cfg in GAMES.items():
        b = _ts(cfg['win'][0])
        e = _ts(cfg['win'][1]) + 86399
        seen = {}
        stats = []
        for kw in cfg['kw']:
            # --- 主：窗口内按播放量降序 ---
            for page in range(1, 51):
                d = api({'search_type': 'video', 'keyword': kw, 'page': page,
                         'order': 'click', 'pubtime_begin_s': b, 'pubtime_end_s': e})
                if not d or d.get('code') != 0 or not d.get('data') or not d['data'].get('result'):
                    break
                res = d['data']['result']
                plays = [int(r.get('play') or 0) for r in res]
                for r in res:
                    _absorb(r, seen, game, cfg, kw, b, e)
                stats.append('click/%s/p%d:%d' % (kw, page, len(res)))
                if max(plays) < MIN_PLAY:
                    break
                time.sleep(0.55)
            # --- 辅：窗口内按发布时间降序 ---
            for page in range(1, 11):
                d = api({'search_type': 'video', 'keyword': kw, 'page': page,
                         'order': 'pubdate', 'pubtime_begin_s': b, 'pubtime_end_s': e})
                if not d or d.get('code') != 0 or not d.get('data') or not d['data'].get('result'):
                    break
                res = d['data']['result']
                for r in res:
                    _absorb(r, seen, game, cfg, kw, b, e)
                if min(int(r.get('pubdate') or 0) for r in res) < b:
                    break
                time.sleep(0.55)
            time.sleep(0.5)
        rows = [v for v in seen.values() if v['play'] >= MIN_PLAY]
        rows.sort(key=lambda x: -x['play'])
        out[game] = rows
        print('%-10s %-22s %s~%s  >=%d播放: %3d 条 (候选 %d)' % (
            game, cfg['version'], cfg['win'][0], cfg['win'][1], MIN_PLAY, len(rows), len(seen)))
        sys.stdout.flush()
    json.dump(out, open(RAW, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('总计 %d 条 -> %s' % (sum(len(v) for v in out.values()), RAW))


def _absorb(r, seen, game, cfg, kw, b, e):
    bv = r.get('bvid')
    if not bv or bv in seen:
        return
    pd = int(r.get('pubdate') or 0)
    if not (b <= pd <= e):
        return
    title = clean(r.get('title'))
    tl = tags_of(r)
    if not relevance(cfg, title, tl):
        return
    seen[bv] = dict(
        bvid=bv,
        game=game,
        version=cfg['version'],
        title=title,
        author=r.get('author'),
        play=int(r.get('play') or 0),
        danmaku=int(r.get('video_review') or 0),
        like=int(r.get('like') or 0),
        favorites=int(r.get('favorites') or 0),
        pubdate=time.strftime('%Y-%m-%d', time.localtime(pd)),
        duration=r.get('duration'),
        tag_list=tl,
        tag=' , '.join(tl),
        url='https://www.bilibili.com/video/' + bv,
        kw=kw,
        desc=clean(r.get('description'))[:300],
    )


if __name__ == '__main__':
    collect()
