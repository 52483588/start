#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
抓取 understat.com 联赛原始 JSON 并存为 data/us_<League>_<Year>.json

年份含义：understat 的 year 指赛季起始年。
  - us_EPL_2025.json  = 2025/26 赛季（已完成）
  - us_EPL_2026.json  = 2026/27 赛季（当前进行中，需周更）

用法：
  # 抓单个联赛单季
  python fetch_understat.py --league EPL --year 2026

  # 抓全部 5 大联赛的当前赛季
  python fetch_understat.py --all --year 2026

  # 抓某联赛最近两季（2025 + 2026）
  python fetch_understat.py --league EPL --year 2025,2026

  # 指定输出目录（默认 ./data）
  python fetch_understat.py --all --year 2026 --out-dir data

  # GitHub Actions 周更当前赛季（自动用系统当前年份）
  python fetch_understat.py --all --year auto

注意：understat 数据**不含真实庄家赔率**。要做 EV/Kelly 请用 football-data 的 CSV
（fetch_footballdata.yml / fetch_data.py footballdata 子命令）。
"""

import argparse
import gzip
import json
import os
import ssl
import sys
import time
import urllib.request

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE

UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')

# understat 的 5 大联赛代码
LEAGUES = {
    'EPL': 'EPL',
    'La_Liga': 'La_Liga',
    'Bundesliga': 'Bundesliga',
    'Serie_A': 'Serie_A',
    'Ligue_1': 'Ligue_1',
}

# 别名（输入更友好）
ALIASES = {
    'epl': 'EPL', 'premier': 'EPL', '英超': 'EPL',
    'laliga': 'La_Liga', 'la_liga': 'La_Liga', '西甲': 'La_Liga',
    'bundesliga': 'Bundesliga', '德甲': 'Bundesliga',
    'seriea': 'Serie_A', 'serie_a': 'Serie_A', '意甲': 'Serie_A',
    'ligue1': 'Ligue_1', 'ligue_1': 'Ligue_1', '法甲': 'Ligue_1',
}


def open_url(url, referer=None, timeout=25, retries=2):
    hdrs = [('User-Agent', UA)]
    if referer:
        hdrs.append(('Referer', referer))
        hdrs.append(('X-Requested-With', 'XMLHttpRequest'))
    op = urllib.request.build_opener(urllib.request.HTTPSHandler(context=CTX))
    op.addheaders = hdrs
    last = None
    for _ in range(retries + 1):
        try:
            return op.open(url, timeout=timeout).read()
        except Exception as e:
            last = e
            time.sleep(0.6)
    raise last


def us_fetch(league, year):
    """抓取并解析单个联赛单季的原始 JSON（gzip）。"""
    url = 'https://understat.com/main/getLeagueData/%s/%d' % (league, year)
    ref = 'https://understat.com/league/%s/%d' % (league, year)
    raw = open_url(url, ref)
    # 部分响应不带 gzip 头；尝试解压，失败则按原文解码
    try:
        text = gzip.decompress(raw).decode('utf-8')
    except Exception:
        text = raw.decode('utf-8')
    return json.loads(text)


def resolve_leagues(spec):
    if spec.strip().lower() == 'all':
        return list(LEAGUES.keys())
    out = []
    for part in spec.split(','):
        p = part.strip()
        if not p:
            continue
        if p in LEAGUES:
            out.append(p)
        elif p in ALIASES:
            out.append(ALIASES[p])
        else:
            # 允许小写直接匹配
            key = p if p in LEAGUES else None
            if key is None and p.lower() in [k.lower() for k in LEAGUES]:
                key = [k for k in LEAGUES if k.lower() == p.lower()][0]
            if key:
                out.append(key)
            else:
                print('  ! 未知联赛代码，跳过: %s' % p)
    return out


def resolve_years(spec):
    spec = spec.strip()
    if spec == 'auto':
        # 当前赛季：系统年份即起始年（如 2026 → 2026/27）
        y = time.gmtime().tm_year
        return [y]
    out = []
    for part in spec.split(','):
        part = part.strip()
        if '-' in part:
            y0, y1 = part.split('-')
            out.extend(range(int(y0), int(y1) + 1))
        elif part:
            out.append(int(part))
    return sorted(set(out))


def main():
    ap = argparse.ArgumentParser(description='抓取 understat 联赛原始 JSON')
    ap.add_argument('--league', default='EPL', help='联赛代码，逗号分隔，或 all（5 大联赛）')
    ap.add_argument('--all', action='store_true', help='抓取全部 5 大联赛（等价于 --league all）')
    ap.add_argument('--year', default='auto', help='赛季起始年，逗号分隔，或 auto（当前年）')
    ap.add_argument('--out-dir', default='data', help='输出目录，默认 ./data')
    ap.add_argument('--force', action='store_true', help='即使文件已存在也重新抓取')
    a = ap.parse_args()

    if a.all:
        a.league = 'all'

    leagues = resolve_leagues(a.league)
    years = resolve_years(a.year)
    if not leagues:
        print('没有可抓取的联赛，退出。')
        sys.exit(1)
    if not years:
        print('没有可抓取的年份，退出。')
        sys.exit(1)

    os.makedirs(a.out_dir, exist_ok=True)
    print('抓取 understat: 联赛=%s 年份=%s → %s/' % (leagues, years, a.out_dir))

    ok = 0
    for lg in leagues:
        for y in years:
            fname = 'us_%s_%d.json' % (lg, y)
            fpath = os.path.join(a.out_dir, fname)
            if os.path.exists(fpath) and not a.force:
                print('  · 已存在，跳过（用 --force 覆盖）: %s' % fname)
                ok += 1
                continue
            try:
                d = us_fetch(lg, y)
                dates = d.get('dates', [])
                results = [m for m in dates if m.get('isResult')]
                with open(fpath, 'w', encoding='utf-8') as f:
                    json.dump(d, f, ensure_ascii=False)
                print('  ✓ %s: 总 %d 场，已完赛 %d 场' % (fname, len(dates), len(results)))
                ok += 1
            except Exception as e:
                print('  ! %s 抓取失败: %s' % (fname, str(e)[:80]))
            time.sleep(0.4)  # 礼貌限速，避免被封

    print('完成：成功 %d / 计划 %d。' % (ok, len(leagues) * len(years)))


if __name__ == '__main__':
    main()
