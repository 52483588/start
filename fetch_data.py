# -*- coding: utf-8 -*-
"""
足球数据抓取脚本 —— 给 GAP 工具准备输入

用法:
  python fetch_data.py understat --league EPL --years 2019-2025 --out epl.csv
  python fetch_data.py understat --league EPL --years 2019-2025 --synth-odds --out epl.csv
  python fetch_data.py footballdata --league E0 --seasons 2324,2425,2526 --out fd.csv
  python fetch_data.py diag                      # 诊断各数据源连通性

understat 联赛代码: EPL, La_Liga, Bundesliga, Serie_A, Ligue_1, RFPL
football-data 联赛代码: E0(英超) E1(英冠) E2 E3 EC  D1(德甲) D2  SP1(西甲) SP2
                        I1(意甲) I2  F1(法甲) F2  N1(荷甲)  P1(葡超)  T1(土超)
                        G1(希超)  B1(比甲)  SC0(苏超) SC1 SC2 SC3
"""
import argparse, csv, gzip, json, os, sys, time, urllib.request, ssl

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')


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


# ---------------- understat ----------------
def us_fetch(league, year):
    url = 'https://understat.com/main/getLeagueData/%s/%d' % (league, year)
    ref = 'https://understat.com/league/%s/%d' % (league, year)
    return json.loads(gzip.decompress(open_url(url, ref)).decode('utf-8'))


def us_to_rows(league, years, synth_odds=False):
    """返回 CSV 行。指标: XGH/XGA(xG) NPPGH/NPPGA(npxG) DEEPH/DEEPA(前场推进)"""
    rows = []
    for y in years:
        try:
            d = us_fetch(league, y)
        except Exception as e:
            print('  ! %s %d 抓取失败: %s' % (league, y, str(e)[:60]))
            continue
        teams = d.get('teams', {})
        idx = {}
        for tv in teams.values():
            for rec in tv.get('history', []):
                idx[(rec['date'], rec['h_a'])] = (tv.get('title'), rec)
        n = 0
        for m in d.get('dates', []):
            if not m.get('isResult'):
                continue
            hh = idx.get((m['datetime'], 'h'))
            aa = idx.get((m['datetime'], 'a'))
            if not hh or not aa:
                continue
            hname, hrec = hh
            aname, arec = aa
            gh, ga = int(m['goals']['h']), int(m['goals']['a'])
            r = {
                'Div': league,
                'Date': m['datetime'][:10],
                'HomeTeam': hname, 'AwayTeam': aname,
                'FTHG': gh, 'FTAG': ga,
                'FTR': 'H' if gh > ga else ('D' if gh == ga else 'A'),
                'XGH': round(float(hrec['xG']), 4), 'XGA': round(float(arec['xG']), 4),
                'NPPGH': round(float(hrec['npxG']), 4), 'NPPGA': round(float(arec['npxG']), 4),
                'DEEPH': int(hrec['deep']), 'DEEPA': int(arec['deep']),
            }
            if synth_odds:
                fc = m.get('forecast') or {}
                try:
                    pw, pdw, pl = float(fc['w']), float(fc['d']), float(fc['l'])
                    s = pw + pdw + pl
                    pw, pdw, pl = max(pw / s, 0.01), max(pdw / s, 0.02), max(pl / s, 0.01)
                    t = pw + pdw + pl
                    pw, pdw, pl = pw / t, pdw / t, pl / t
                    ov = 1.055
                    r['B365H'] = round(1 / (pw * ov), 2)
                    r['B365D'] = round(1 / (pdw * ov), 2)
                    r['B365A'] = round(1 / (pl * ov), 2)
                except Exception:
                    pass
            rows.append(r)
            n += 1
        print('  %s %d: %d 场' % (league, y, n))
    rows.sort(key=lambda x: x['Date'])
    return rows


# ---------------- football-data.co.uk ----------------
def fd_fetch(season, league):
    url = 'https://www.football-data.co.uk/mmz4281/%s/%s.csv' % (season, league)
    return open_url(url, timeout=40).decode('utf-8-sig', 'ignore')


def fd_to_rows(seasons, leagues):
    raw = []
    for s in seasons:
        for lg in leagues:
            try:
                t = fd_fetch(s, lg)
                lines = [x for x in t.replace('\r\n', '\n').split('\n') if x.strip()]
                if len(lines) < 2:
                    print('  ! %s %s 空' % (s, lg)); continue
                raw.append(lines)
                print('  %s %s: %d 行' % (s, lg, len(lines) - 1))
            except Exception as e:
                print('  ! %s %s 失败: %s' % (s, lg, str(e)[:60]))
    if not raw:
        return []
    head = raw[0][0].split(',')
    rows = []
    for lines in raw:
        for ln in lines[1:]:
            cells = next(csv.reader([ln]))
            if len(cells) < len(head) - 2:
                continue
            rows.append(dict(zip(head, cells)))
    return rows


def write_csv(rows, out):
    if not rows:
        print('没有数据可写'); return
    fields = []
    for r in rows:
        for k in r.keys():
            if k not in fields:
                fields.append(k)
    with open(out, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
        w.writeheader()
        w.writerows(rows)
    print('写出 %s：%d 行' % (out, len(rows)))
    print('列：' + ','.join(fields))


def diag():
    print('=== 数据源连通性诊断 ===\n')
    targets = [
        ('football-data.co.uk (CSV)', 'https://www.football-data.co.uk/mmz4281/2425/E0.csv'),
        ('understat.com (xG)', 'https://understat.com/main/getLeagueData/EPL/2025'),
        ('sporttery.cn', 'https://www.sporttery.cn/'),
        ('github.com', 'https://github.com/'),
    ]
    try:
        import urllib.request
        print('当前 urllib 检测到的代理:', urllib.request.getproxies())
    except Exception:
        pass
    print()
    for name, url in targets:
        for label, kwargs in [('系统代理', {}), ('直连', {'no_proxy': True})]:
            try:
                if kwargs.get('no_proxy'):
                    op = urllib.request.build_opener(
                        urllib.request.ProxyHandler({}),
                        urllib.request.HTTPSHandler(context=CTX))
                else:
                    op = urllib.request.build_opener(urllib.request.HTTPSHandler(context=CTX))
                op.addheaders = [('User-Agent', UA)]
                t0 = time.time()
                r = op.open(url, timeout=15)
                print('  %-28s %-6s OK   %s  (%.1fs)' % (name, label, r.status, time.time() - t0))
                break
            except Exception as e:
                print('  %-28s %-6s FAIL %s' % (name, label, str(e)[:55]))
    print('\n若 football-data 走系统代理失败、直连也超时，说明它对你当前网络不可达；')
    print('可换用 understat（有 xG/npxG/前场推进），或在你自己的网络环境里再跑 footballdata 子命令。')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('source', choices=['understat', 'footballdata', 'diag'])
    ap.add_argument('--league', default='EPL')
    ap.add_argument('--years', default='2019-2025')
    ap.add_argument('--seasons', default='2324,2425,2526')
    ap.add_argument('--out', default='matches.csv')
    ap.add_argument('--synth-odds', action='store_true',
                    help='understat 无真实赔率；开启时用其赛前预测反推赔率（仅供流程演示，非真实赔率）')
    a = ap.parse_args()

    if a.source == 'diag':
        diag(); return
    if a.source == 'understat':
        if '-' in a.years:
            y0, y1 = a.years.split('-'); years = list(range(int(y0), int(y1) + 1))
        else:
            years = [int(x) for x in a.years.split(',')]
        print('抓取 understat %s %s ...' % (a.league, years))
        rows = us_to_rows(a.league, years, a.synth_odds)
        write_csv(rows, a.out)
        if not a.synth_odds:
            print('\n注意：未生成赔率列。要做 EV / Kelly 分析，请自备赔率，或加 --synth-odds 生成演示用赔率。')
    else:
        seasons = [s.strip() for s in a.seasons.split(',')]
        leagues = [x.strip() for x in a.league.split(',')]
        print('抓取 football-data.co.uk %s %s ...' % (seasons, leagues))
        rows = fd_to_rows(seasons, leagues)
        write_csv(rows, a.out)


if __name__ == '__main__':
    main()
