#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
stats_python.py — 足球大小球「统计视图」独立 Python 实现
========================================================
把 index.html 中「📊 统计」标签页的全部功能用纯 Python 重写，不依赖浏览器。
数据源：his_data.js（含 FOLDERS / RAW_DATA / SCORE_DATA_*）。

支持两种模式：
  1. 默认（统计视图）：生成详细的统计报表（CSV / HTML），适合人工查看。
  2. --update 模式：增量更新模式，从最新文件夹提取记录，合并到历史 stats.csv，
     供后续自动化分析使用（适合 GitHub Workflow 每日运行）。

用法示例：
  python stats_python.py                         # 默认：首条、±24h、输出 CSV
  python stats_python.py --order last            # 用每场末条完整数据
  python stats_python.py --predict big --size big
  python stats_python.py --all --csv out.csv --html report.html
  python stats_python.py --now "20260717 12:00"  # 指定“当前”时间，便于复现
  python stats_python.py --update                # 增量更新模式（默认输出 stats.csv）
  python stats_python.py --update --output my_stats.csv
"""

import os
import re
import sys
import json
import csv
import argparse
from datetime import datetime, timedelta
from functools import lru_cache

# ============================================================
# 1. 数据加载：从 his_data.js 解析 FOLDERS / RAW_DATA / SCORE_DATA_*
# ============================================================

def _extract_balanced(text, start_idx, open_ch, close_ch):
    """从 text[start_idx]（必须是 open_ch）起，做带字符串感知的括号匹配，
    返回包含首尾括号的子串，可直接 json.loads。"""
    assert text[start_idx] == open_ch, "start_idx 未指向开放括号"
    depth = 0
    in_str = False
    esc = False
    i = start_idx
    n = len(text)
    while i < n:
        c = text[i]
        if in_str:
            if esc:
                esc = False
            elif c == '\\':
                esc = True
            elif c == '"':
                in_str = False
        else:
            if c == '"':
                in_str = True
            elif c == open_ch:
                depth += 1
            elif c == close_ch:
                depth -= 1
                if depth == 0:
                    return text[start_idx:i + 1]
        i += 1
    return text[start_idx:]


def load_data(path):
    """解析 his_data.js，返回 (folders, raw_data, score_arrays)。"""
    with open(path, 'r', encoding='utf-8') as f:
        text = f.read()

    # FOLDERS
    m = re.search(r'var\s+FOLDERS\s*=\s*', text)
    if not m:
        raise RuntimeError("未在 %s 中找到 var FOLDERS" % path)
    folders = json.loads(_extract_balanced(text, text.index('[', m.end()), '[', ']'))

    # RAW_DATA
    m2 = re.search(r'var\s+RAW_DATA\s*=\s*', text)
    if not m2:
        raise RuntimeError("未在 %s 中找到 var RAW_DATA" % path)
    raw_data = json.loads(_extract_balanced(text, text.index('{', m2.end()), '{', '}'))

    # 所有 SCORE_DATA_* 数组
    score_arrays = []
    for mm in re.finditer(r'var\s+(SCORE_DATA_\w+)\s*=\s*', text):
        arr = json.loads(_extract_balanced(text, text.index('[', mm.end()), '[', ']'))
        if isinstance(arr, list):
            score_arrays.append(arr)

    return folders, raw_data, score_arrays


# ============================================================
# 2. 泊松 / 盘口基础数学（移植自 stats.js）
# ============================================================

@lru_cache(maxsize=None)
def poisson_pmf(lam, k):
    import math
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    lp = -lam + k * math.log(lam)
    for i in range(2, k + 1):
        lp -= math.log(i)
    return math.exp(lp)


def poisson_cdf(lam, k):
    s = 0.0
    for i in range(0, k + 1):
        s += poisson_pmf(lam, i)
    return s


def p_at_least(lam, k):
    return 1 - poisson_cdf(lam, k - 1)


def p_at_most(lam, k):
    return poisson_cdf(lam, k)


def detect_type(line):
    import math
    d = round((abs(line) % 1) * 100) / 100
    if abs(d - 0.5) < 0.01:
        return 'half'
    if abs(d) < 0.01:
        return 'integer'
    if abs(d - 0.25) < 0.01 or abs(d - 0.75) < 0.01:
        return 'quarter'
    return None


def half_probs(lam, line):
    return [p_at_least(lam, round(line + 0.5)), p_at_most(lam, round(line - 0.5))]


def int_probs(lam, line):
    return [p_at_least(lam, round(line + 1)), p_at_most(lam, round(line - 1))]


def qtr_probs(lam, line):
    lo = line - 0.25
    hi = line + 0.25
    lt = detect_type(lo)
    ht = detect_type(hi)
    p_lo = half_probs(lam, lo) if lt == 'half' else int_probs(lam, lo)
    p_hi = half_probs(lam, hi) if ht == 'half' else int_probs(lam, hi)
    return [0.5 * p_lo[0] + 0.5 * p_hi[0], 0.5 * p_lo[1] + 0.5 * p_hi[1]]


def line_probs_raw(lam, line):
    t = detect_type(line)
    if t == 'half':
        return half_probs(lam, line)
    if t == 'integer':
        return int_probs(lam, line)
    return qtr_probs(lam, line)


def line_probs_norm(lam, line):
    r = line_probs_raw(lam, line)
    total = r[0] + r[1]
    return [r[0] / total, r[1] / total] if total > 0 else [0.5, 0.5]


def fair_prob(o1, o2):
    m = 1.0 / o1 + 1.0 / o2
    return [(1.0 / o1) / m, (1.0 / o2) / m]


def poisson_objective(lam, lines):
    total = 0.0
    for lv, od in lines.items():
        fp = fair_prob(od['over'], od['under'])
        mp = line_probs_norm(lam, float(lv))
        total += (mp[0] - fp[0]) ** 2 + (mp[1] - fp[1]) ** 2
    return total


def _frange(a, b, step):
    i = 0
    while True:
        v = round(a + i * step, 10)
        if v > b + 1e-9:
            break
        yield v
        i += 1


def optimize_poisson(lines):
    """移植 stats.js optimizePoisson：网格 0.3..8.0(step .01) + 黄金分割(50 次)。"""
    best = 2.5
    best_v = float('inf')
    for lam in _frange(0.3, 8.0, 0.01):
        v = poisson_objective(lam, lines)
        if v < best_v:
            best_v = v
            best = lam
    a = max(0.1, best - 0.5)
    b = best + 0.5
    phi = (5 ** 0.5 - 1) / 2
    c = b - phi * (b - a)
    d = a + phi * (b - a)
    fc = poisson_objective(c, lines)
    fd = poisson_objective(d, lines)
    for _ in range(50):
        if abs(b - a) < 1e-10:
            break
        if fc < fd:
            b = d
            d = c
            fd = fc
            c = b - phi * (b - a)
            fc = poisson_objective(c, lines)
        else:
            a = c
            c = d
            fc = fd
            d = a + phi * (b - a)
            fd = poisson_objective(d, lines)
    return (a + b) / 2


def fair_probs(odds):
    inv = [1.0 / max(o, 0.01) for o in odds]
    margin = sum(inv)
    return [p / margin for p in inv]


def model_probs(lam):
    arr = []
    s = 0.0
    for k in range(0, 7):
        p = poisson_pmf(lam, k)
        arr.append(p)
        s += p
    arr.append(max(0.0, 1 - s))
    return arr


def objective_single(lam, odds):
    fp = fair_probs(odds)
    mp = model_probs(lam)
    mp6 = mp[0:5] + [sum(mp[5:])]
    return sum((mp6[i] - fp[i]) ** 2 for i in range(6))


def optimize_lambda_single(odds):
    """移植 stats.js optimizeLambdaSingle：网格 0.1..6.0(step .01) + 黄金分割(50 次)。"""
    best_lam = 1.0
    best_v = float('inf')
    for lam in _frange(0.1, 6.0, 0.01):
        v = objective_single(lam, odds)
        if v < best_v:
            best_v = v
            best_lam = lam
    a = max(0.05, best_lam - 0.5)
    b = best_lam + 0.5
    phi = (5 ** 0.5 - 1) / 2
    c = b - phi * (b - a)
    d = a + phi * (b - a)
    fc = objective_single(c, odds)
    fd = objective_single(d, odds)
    for _ in range(50):
        if abs(b - a) < 1e-10:
            break
        if fc < fd:
            b = d
            d = c
            fd = fc
            c = b - phi * (b - a)
            fc = objective_single(c, odds)
        else:
            a = c
            c = d
            fc = fd
            d = a + phi * (b - a)
            fd = objective_single(d, odds)
    return (a + b) / 2


def calc_tg_from_poisson(lam_h, lam_a):
    """移植 stats.js calcTgFromPoisson：返回长度 8 的总进球概率 [0..6, 7+]。"""
    if lam_h is None or lam_a is None:
        return None
    max_k = 25
    ph = [poisson_pmf(lam_h, k) for k in range(0, max_k + 1)]
    pa = [poisson_pmf(lam_a, k) for k in range(0, max_k + 1)]
    tg = [0.0] * 8
    for t in range(0, 7):
        p = 0.0
        for i in range(0, t + 1):
            p += ph[i] * pa[t - i]
        tg[t] = p
    sum06 = sum(tg[0:7])
    tg[7] = max(0.0, 1 - sum06)
    return tg


def build_poisson_lines(ou):
    """移植 stats.js buildPoissonLines：从 ou.{oo,uo,li,hi_var} 构造 lines（hc -> {over,under}）。"""
    lines = {}
    if ou.get('oo') and ou.get('uo') and ou.get('li'):
        try:
            hc = float(ou['li']) / 4
            ov = float(ou['oo'])
            un = float(ou['uo'])
            if not (isnan(hc) or isnan(ov) or isnan(un)) and ov >= 1.01 and un >= 1.01:
                lines[round(hc, 2)] = {'over': ov, 'under': un}
        except (ValueError, TypeError):
            pass
    hiv = ou.get('hi_var', '') or ''
    if hiv:
        for seg in hiv.split('#'):
            parts = seg.strip().split(',')
            if len(parts) < 5:
                continue
            try:
                hv = float(parts[1]) / 4
            except (ValueError, TypeError):
                continue
            key = round(hv, 2)
            if key not in lines:
                lines[key] = {'over': None, 'under': None}
            direction = parts[4].strip().upper()
            try:
                odds = float(parts[0]) / 1000
            except (ValueError, TypeError):
                continue
            if direction == 'H':
                lines[key]['over'] = odds
            elif direction == 'L':
                lines[key]['under'] = odds
        # 仅保留上下盘赔率都有效的
        for k in list(lines.keys()):
            e = lines[k]
            if e['over'] and e['under'] and e['over'] >= 1.01 and e['under'] >= 1.01:
                continue
            del lines[k]
    return lines


def analyze_row(rec):
    """移植 stats.js analyzeRow 的 OU/NG 部分，返回所需字段。"""
    out = {'ngLamTotal': None, 'ouLam': None, 'ngTgProbs': None}
    ng = rec.get('ng', {}) or {}
    ng_cols = ['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'a1', 'a2', 'a3', 'a4', 'a5', 'a6']
    has_ng = all(ng.get(k) is not None and _to_float(ng[k]) > 0 for k in ng_cols)
    if has_ng:
        home_odds = [float(ng[k]) for k in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']]
        away_odds = [float(ng[k]) for k in ['a1', 'a2', 'a3', 'a4', 'a5', 'a6']]
        lam_h = optimize_lambda_single(home_odds)
        lam_a = optimize_lambda_single(away_odds)
        out['ngLamTotal'] = lam_h + lam_a
        out['ngTgProbs'] = calc_tg_from_poisson(lam_h, lam_a)
    ou = rec.get('ou', {}) or {}
    ou_lines = build_poisson_lines(ou)
    if ou_lines:
        out['ouLam'] = optimize_poisson(ou_lines)
    return out


def calc_ou_probs_from_dist(total_prob, handicap):
    """移植 app.js calcOUProbsFromDist：总进球分布 -> 大小球原始概率。"""
    import math
    int_part = math.floor(handicap)
    frac = round((handicap - int_part) * 100) / 100

    if abs(frac - 0.5) < 0.01:
        p_over = 0.0
        for g in range(0, 7):
            if g > handicap:
                p_over += total_prob[g]
        p_over += total_prob[7]
        return {'pOver': p_over, 'pUnder': 1 - p_over}
    elif abs(frac) < 0.01:
        p_over = 0.0
        p_under = 0.0
        for g in range(0, 7):
            if g > handicap:
                p_over += total_prob[g]
            elif g < handicap:
                p_under += total_prob[g]
        p_over += total_prob[7]
        return {'pOver': p_over, 'pUnder': p_under}
    elif abs(frac - 0.25) < 0.01:
        lo = int_part
        hi = int_part + 0.5
        r_l = calc_ou_probs_from_dist(total_prob, lo)
        r_h = calc_ou_probs_from_dist(total_prob, hi)
        return {'pOver': (r_l['pOver'] + r_h['pOver']) / 2,
                'pUnder': (r_l['pUnder'] + r_h['pUnder']) / 2}
    elif abs(frac - 0.75) < 0.01:
        lo = int_part + 0.5
        hi = int_part + 1.0
        r_l = calc_ou_probs_from_dist(total_prob, lo)
        r_h = calc_ou_probs_from_dist(total_prob, hi)
        return {'pOver': (r_l['pOver'] + r_h['pOver']) / 2,
                'pUnder': (r_l['pUnder'] + r_h['pUnder']) / 2}
    return {'pOver': 0.5, 'pUnder': 0.5}


def _to_float(v):
    try:
        return float(v)
    except (ValueError, TypeError):
        return float('nan')


def isnan(v):
    return v != v


# ============================================================
# 3. 比分匹配（移植自 app.js：TRAD2SIMP / lookupScoreForRec）
# ============================================================

TRAD2SIMP = {
    '黃': '黄', '陝': '陕', '東': '东', '廣': '广', '來': '来', '門': '门', '國': '国',
    '陽': '阳', '聯': '联', '隊': '队', '華': '华', '爾': '尔', '維': '维', '亞': '亚',
    '與': '与', '體': '体', '會': '会', '員': '员', '圖': '图', '場': '场', '義': '义',
    '務': '务', '實': '实', '學': '学', '興': '兴', '軍': '军', '師': '师', '馬': '马',
    '鳥': '鸟', '魚': '鱼', '車': '车', '貝': '贝', '見': '见', '長': '长', '開': '开',
    '關': '关', '點': '点', '為': '为', '這': '这', '個': '个', '們': '们', '說': '说',
    '話': '话', '時': '时', '間': '间', '後': '后', '處': '处', '當': '当', '對': '对',
    '從': '从', '無': '无', '飛': '飞', '島': '岛', '鄉': '乡', '縣': '县', '銀': '银',
    '錢': '钱', '銅': '铜', '錦': '锦', '鐵': '铁', '鋼': '钢', '際': '际', '雲': '云',
    '專': '专', '業': '业', '萬': '万', '發': '发', '產': '产', '經': '经', '紅': '红',
    '綠': '绿', '級': '级', '統': '统', '結': '结', '終': '终', '組': '组', '織': '织',
    '網': '网', '認': '认', '識': '识', '讀': '读', '誰': '谁', '請': '请', '謝': '谢',
    '證': '证', '語': '语', '詞': '词', '試': '试', '過': '过', '進': '进', '運': '运',
    '遠': '远', '邊': '边', '還': '还', '週': '周', '動': '动', '態': '态', '應': '应',
    '愛': '爱', '戰': '战', '戶': '户', '書': '书', '禮': '礼', '視': '视', '覺': '觉',
    '親': '亲', '顏': '颜', '風': '风', '飯': '饭', '飲': '饮', '館': '馆', '魯': '鲁',
    '鮑': '鲍', '鵬': '鹏', '鶴': '鹤', '鷹': '鹰', '麥': '麦', '麗': '丽', '龍': '龙',
    '參': '参', '雙': '双', '臺': '台', '灣': '湾', '豐': '丰', '樂': '乐', '勝': '胜',
    '剛': '刚', '創': '创', '劉': '刘', '盧': '卢', '羅': '罗', '蘇': '苏', '蔣': '蒋',
    '許': '许', '鄭': '郑', '鄧': '邓', '陳': '陈', '吳': '吴', '張': '张', '楊': '杨',
    '趙': '赵', '孫': '孙', '範': '范', '賴': '赖', '連': '连', '餘': '余', '湯': '汤',
    '馮': '冯', '譚': '谭', '廖': '廖', '賈': '贾', '葉': '叶', '費': '费', '賀': '贺',
    '鍾': '钟', '嶺': '岭', '莊': '庄', '鎮': '镇', '壢': '坜', '蘭': '兰', '蓮': '莲',
    '舊': '旧', '藍': '蓝', '寶': '宝', '鳳': '凤', '獅': '狮', '鱷': '鳄', '鯨': '鲸',
    '鯊': '鲨', '燕': '燕', '鴿': '鸽', '烏': '乌', '鴉': '鸦', '雞': '鸡', '鴨': '鸭',
    '鵝': '鹅', '鯉': '鲤', '鱒': '鳟', '鮭': '鲑', '魷': '鱿', '蟹': '蟹', '蝦': '虾',
    '龜': '龟', '蛇': '蛇',
}


def norm_score_str(s):
    if not s:
        return ''
    s = str(s).strip()
    return ''.join(TRAD2SIMP.get(ch, ch) for ch in s)


def norm_gt(gt):
    if not gt:
        return ''
    m = re.match(r'^(\d{4})(\d{2})(\d{2})\s*(\d{2}):(\d{2})', str(gt).strip())
    if m:
        return '%s-%s-%s %s:%s' % (m.group(1), m.group(2), m.group(3), m.group(4), m.group(5))
    return str(gt).strip()


def build_score_index(score_arrays):
    """构建比分索引（仅含 scoreNote=='完场'）。键：联赛|主|客 等。"""
    index = {
        'by_full': {}, 'by_home_away': {}, 'by_league_home': {}, 'by_league_away': {},
    }
    for arr in score_arrays:
        for e in arr:
            if not e:
                continue
            if (e.get('scoreNote') or '') != '完场':
                continue
            h = norm_score_str(e.get('homeTeam'))
            a = norm_score_str(e.get('awayTeam'))
            t = norm_score_str(e.get('tournament'))
            if not h or not a:
                continue
            sc = (e.get('score') or '').__str__().strip()
            if not sc:
                continue
            try:
                tg = float(e.get('totalGoals'))
                tg_str = ('%g' % tg) if tg == int(tg) else ('%.1f' % tg)
            except (ValueError, TypeError):
                tg_str = ''
            entry = {
                'score': sc,
                'totalGoals': tg_str,
                'date': (e.get('startDate') or '').strip(),
                'note': e.get('scoreNote') or '',
            }
            index['by_full'].setdefault('%s|%s|%s' % (t, h, a), []).append(entry)
            index['by_home_away'].setdefault('%s|%s' % (h, a), []).append(entry)
            index['by_league_home'].setdefault('%s|%s' % (t, h), []).append(entry)
            index['by_league_away'].setdefault('%s|%s' % (t, a), []).append(entry)
    return index


def _parse_score_date(s):
    if not s:
        return None
    m = re.match(r'^(\d{4})-(\d{2})-(\d{2})\s*(\d{2}):(\d{2})', s)
    if not m:
        return None
    return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)),
                   int(m.group(4)), int(m.group(5)))


def _pick_score_by_date(cands, gt_norm):
    if len(cands) == 1:
        return cands[0]
    for c in cands:
        if c['date'] and c['date'] == gt_norm:
            return c
    # 无精确匹配时，取日期最接近者（日期为 YYYY-MM-DD HH:MM，可直接按时间差比较）
    target = _parse_score_date(gt_norm)
    best = cands[0]
    best_diff = float('inf')
    for c in cands:
        cd = _parse_score_date(c['date'])
        if cd is None:
            continue
        diff = abs((cd - (target or cd)).total_seconds())
        if diff < best_diff:
            best_diff = diff
            best = c
    return best


def lookup_score_for_rec(index, league, home, away, gt):
    h = norm_score_str(home)
    a = norm_score_str(away)
    t = norm_score_str(league)
    if not h or not a:
        return None
    gt_norm = norm_gt(gt)
    cand = (index['by_full'].get('%s|%s|%s' % (t, h, a))
            or index['by_home_away'].get('%s|%s' % (h, a))
            or index['by_league_home'].get('%s|%s' % (t, h))
            or index['by_league_away'].get('%s|%s' % (t, a)))
    if not cand:
        return None
    e = _pick_score_by_date(cand, gt_norm)
    return {'score': e['score'], 'totalGoals': e['totalGoals'], 'scoreNote': e['note']}


# ============================================================
# 4. 时间工具（移植 parseGtToDate / getBeijingTime）
# ============================================================

def parse_gt_to_date(gt):
    if not gt:
        return None
    gt = str(gt).strip()
    if ' ' in gt and ':' in gt:
        parts = gt.split(' ', 1)
        date_part = parts[0]
        time_part = parts[1]
        if len(date_part) != 8:
            return None
        y = int(date_part[0:4])
        mo = int(date_part[4:6])
        d = int(date_part[6:8])
        t = time_part.split(':')
        h = int(t[0])
        mi = int(t[1])
        return datetime(y, mo, d, h, mi)
    if len(gt) == 14 and gt.isdigit():
        y = int(gt[0:4])
        mo = int(gt[4:6])
        d = int(gt[6:8])
        h = int(gt[8:10])
        mi = int(gt[10:12])
        s = int(gt[12:14])
        return datetime(y, mo, d, h, mi, s)
    return None


def beijing_now(now_str=None):
    """返回“北京时间”的 naive datetime（与 JS new Date() 在 Beijing 环境下的行为一致）。"""
    if now_str:
        return parse_gt_to_date(now_str) or datetime.utcnow() + timedelta(hours=8)
    return datetime.utcnow() + timedelta(hours=8)


# ============================================================
# 5. 分析记录 + 单场处理（原有统计视图用）
# ============================================================

NG_COLS = ['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'a1', 'a2', 'a3', 'a4', 'a5', 'a6']


def build_analysis_records(folders, raw_data, now, use_all):
    """移植 loadAnalysisData：从最新文件夹取 ±24h（或 --all）的记录。"""
    latest = folders[-1]
    folder_data = raw_data.get(latest, {})
    past = now - timedelta(hours=24)
    future = now + timedelta(hours=24)

    records = []
    for mid, rec in folder_data.items():
        ng = rec.get('ng', {}) or {}
        if not any(_to_float(ng.get(k)) > 0 for k in NG_COLS):
            continue
        oc = rec.get('oc', {}) or {}
        gt = oc.get('gt', '')
        md = parse_gt_to_date(gt)
        if md is None:
            continue
        if not use_all:
            if md < past or md > future:
                continue
        home_odds = [_to_float(ng[k]) for k in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']]
        away_odds = [_to_float(ng[k]) for k in ['a1', 'a2', 'a3', 'a4', 'a5', 'a6']]
        if any(o <= 0 or isnan(o) for o in home_odds + away_odds):
            continue
        records.append({
            'id': mid,
            'gt': gt,
            'league': oc.get('st', '') or '',
            'home': oc.get('sh', '') or '',
            'away': oc.get('sa', '') or '',
        })
    records.sort(key=lambda r: r['gt'])
    return records, latest


def process_match(rec, folders, raw_data, score_index, order):
    """移植 runStats 内 processMatch：按 order 选首条/末条完整快照，计算预测与比分。"""
    ordered = folders if order == 'first' else list(reversed(folders))
    chosen = None
    chosen_folder = None
    for folder in ordered:
        fd = raw_data.get(folder, {}) or {}
        r = fd.get(rec['id'])
        if not r or not r.get('ou'):
            continue
        ou = r.get('ou', {})
        try:
            oo = float(ou.get('oo'))
            uo = float(ou.get('uo'))
            li = float(ou.get('li'))
        except (ValueError, TypeError):
            continue
        if not (oo > 0) or not (uo > 0) or isnan(li):
            continue
        ng = r.get('ng', {}) or {}
        if not all(ng.get(k) is not None and _to_float(ng[k]) > 0 for k in NG_COLS):
            continue
        chosen = r
        chosen_folder = folder
        break

    hc_num = None
    analysis = None
    if chosen is not None:
        hc_num = float(chosen['ou']['li']) / 4
        analysis = analyze_row(chosen)

    lam_total_str = '-'
    lam_str = '-'
    lam_ratio_str = '-'
    if analysis and analysis['ngLamTotal'] is not None:
        lam_total_str = '%.3f' % analysis['ngLamTotal']
        if analysis['ouLam'] is not None:
            lam_str = '%.3f' % analysis['ouLam']
            lam_ratio_str = lam_total_str + ' / ' + lam_str
        else:
            lam_ratio_str = lam_total_str + ' / -'

    p_over_norm = None
    p_under_norm = None
    if analysis and analysis['ngTgProbs'] and len(analysis['ngTgProbs']) >= 8 and hc_num is not None:
        ou_raw = calc_ou_probs_from_dist(analysis['ngTgProbs'], hc_num)
        total_div = ou_raw['pOver'] + ou_raw['pUnder']
        if total_div > 0:
            p_over_norm = ou_raw['pOver'] / total_div
            p_under_norm = ou_raw['pUnder'] / total_div

    predict = ''
    if p_over_norm is not None and p_under_norm is not None:
        if p_over_norm > p_under_norm:
            predict = '大'
        elif p_under_norm > p_over_norm:
            predict = '小'

    score_info = lookup_score_for_rec(score_index, rec['league'], rec['home'], rec['away'], rec['gt'])
    score_str = '-'
    tg_str = '-'
    size = ''
    if score_info:
        score_str = score_info['score']
        tg_str = score_info['totalGoals']
        tg_num = _to_float(score_info['totalGoals'])
        if hc_num is not None and not isnan(tg_num):
            if tg_num > hc_num:
                size = '大'
            elif tg_num < hc_num:
                size = '小'
            else:
                size = '平'

    correct = ''
    if predict and size:
        correct = '忽略' if size == '平' else ('对' if predict == size else '错')

    return {
        'id': rec['id'],
        'league': rec['league'],
        'home': rec['home'],
        'away': rec['away'],
        'folder': chosen_folder,
        'hc_num': hc_num,
        'hc_str': ('%.2f' % hc_num) if hc_num is not None else '-',
        'score': score_str,
        'totalGoals': tg_str,
        'size': size,
        'hasScore': bool(score_info),
        'pOverNorm': p_over_norm,
        'pUnderNorm': p_under_norm,
        'predict': predict,
        'correct': correct,
        'lamTotalStr': lam_total_str,
        'lamStr': lam_str,
        'lamRatioStr': lam_ratio_str,
    }


# ============================================================
# 6. 汇总 + 筛选 + 输出（原有统计视图用）
# ============================================================

def summarize(rows):
    pred_over = corr_over = pred_under = corr_under = pred_total = corr_total = 0
    for r in rows:
        if r['predict'] and r['size'] and r['size'] != '平':
            pred_total += 1
            if r['predict'] == '大':
                pred_over += 1
                if r['correct'] == '对':
                    corr_over += 1
            else:
                pred_under += 1
                if r['correct'] == '对':
                    corr_under += 1
            if r['correct'] == '对':
                corr_total += 1
    rate_over = (corr_over / pred_over) if pred_over else 0
    rate_under = (corr_under / pred_under) if pred_under else 0
    rate_all = (corr_total / pred_total) if pred_total else 0
    return {
        'predOver': pred_over, 'corrOver': corr_over, 'rateOver': rate_over,
        'predUnder': pred_under, 'corrUnder': corr_under, 'rateUnder': rate_under,
        'predTotal': pred_total, 'corrTotal': corr_total, 'rateAll': rate_all,
    }


def apply_filters(rows, f_predict, f_size, f_league):
    out = rows
    if f_predict:
        if f_predict == 'big':
            out = [r for r in out if r['predict'] == '大']
        elif f_predict == 'small':
            out = [r for r in out if r['predict'] == '小']
        elif f_predict == 'none':
            out = [r for r in out if r['predict'] == '']
    if f_size:
        if f_size == 'big':
            out = [r for r in out if r['size'] == '大']
        elif f_size == 'small':
            out = [r for r in out if r['size'] == '小']
        elif f_size == 'draw':
            out = [r for r in out if r['size'] == '平']
        elif f_size == 'none':
            out = [r for r in out if not r['hasScore']]
    if f_league:
        out = [r for r in out if r['league'] == f_league]
    return out


def export_csv(rows, path):
    header = ['赛事ID', '联赛', '主队', '客队', '盘口', '快照', '比分', '总进球', '大小',
              '大率', '小率', '预测', '正确', 'λ总', 'λ']
    lines = [','.join(header)]
    for r in rows:
        prob_over = ('%.1f%%' % (r['pOverNorm'] * 100)) if r['pOverNorm'] is not None else ''
        prob_under = ('%.1f%%' % (r['pUnderNorm'] * 100)) if r['pUnderNorm'] is not None else ''
        cells = [
            r['id'], r['league'], r['home'], r['away'], r['hc_str'], r['folder'] or '',
            r['score'], r['totalGoals'], r['size'] or '', prob_over, prob_under,
            ('预测' + r['predict']) if r['predict'] else '',
            r['correct'] or '', r['lamTotalStr'], r['lamStr'],
        ]
        lines.append(','.join(_csv_cell(c) for c in cells))
    with open(path, 'w', encoding='utf-8-sig', newline='') as f:
        f.write('\r\n'.join(lines))


def _csv_cell(v):
    s = '' if v is None else str(v)
    if any(ch in s for ch in [',', '"', '\r', '\n']):
        return '"' + s.replace('"', '""') + '"'
    return s


def print_table(rows, limit=None):
    headers = ['赛事ID', '联赛', '主队', '客队', '盘口', '快照', '比分', '总', '大小',
               '大%', '小%', '预测', '正确', 'λ总/λ']
    widths = [8, 10, 10, 10, 6, 16, 7, 5, 5, 7, 7, 7, 5, 13]

    def clip(s, w):
        s = '' if s is None else str(s)
        if len(s) > w:
            return s[:w - 1] + '…'
        return s

    line = ' | '.join(clip(headers[i], widths[i]).ljust(widths[i]) for i in range(len(headers)))
    print(line)
    print('-' * len(line))
    shown = rows if limit is None else rows[:limit]
    for r in shown:
        prob_over = ('%.1f' % (r['pOverNorm'] * 100)) if r['pOverNorm'] is not None else '-'
        prob_under = ('%.1f' % (r['pUnderNorm'] * 100)) if r['pUnderNorm'] is not None else '-'
        vals = [
            r['id'], r['league'], r['home'], r['away'], r['hc_str'], r['folder'] or '',
            r['score'], r['totalGoals'], r['size'] or '', prob_over, prob_under,
            ('预测' + r['predict']) if r['predict'] else '-',
            r['correct'] or '-', r['lamRatioStr'],
        ]
        print(' | '.join(clip(str(vals[i]), widths[i]).ljust(widths[i]) for i in range(len(headers))))
    if limit is not None and len(rows) > limit:
        print('… 另有 %d 行未显示，详见 CSV/HTML 导出' % (len(rows) - limit))


def export_html(rows, summary, path, order, filters):
    pred_over = summary['predOver']; corr_over = summary['corrOver']
    pred_under = summary['predUnder']; corr_under = summary['corrUnder']
    rate_all = summary['rateAll']
    cards = (
        '<div class="card"><div class="num">%d</div><div class="lbl">预测大球场次</div>'
        '<div class="sub">%d 正确 · %.1f%%</div></div>' % (pred_over, corr_over, summary['rateOver'] * 100) +
        '<div class="card"><div class="num">%d</div><div class="lbl">预测小球场次</div>'
        '<div class="sub">%d 正确 · %.1f%%</div></div>' % (pred_under, corr_under, summary['rateUnder'] * 100) +
        '<div class="card"><div class="num">%.1f%%</div><div class="lbl">整体预测正确率</div>'
        '<div class="sub">%d / %d 场（仅统计有比分的场次，平局已忽略）</div></div>'
        % (rate_all * 100, summary['corrTotal'], summary['predTotal'])
    )
    rows_html = []
    for r in rows:
        prob_over = ('%.1f%%' % (r['pOverNorm'] * 100)) if r['pOverNorm'] is not None else '-'
        prob_under = ('%.1f%%' % (r['pUnderNorm'] * 100)) if r['pUnderNorm'] is not None else '-'
        corr_cls = ('corr-ok' if r['correct'] == '对' else ('corr-bad' if r['correct'] == '错'
                    else ('corr-ign' if r['correct'] == '忽略' else '')))
        size_cls = ('size-over' if r['size'] == '大' else ('size-under' if r['size'] == '小'
                   else ('size-draw' if r['size'] == '平' else '')))
        rows_html.append(
            '<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td>'
            '<td>%s</td><td>%s</td><td class="%s">%s</td><td>%s / %s</td>'
            '<td>%s</td><td class="%s">%s</td><td>%s</td></tr>' % (
                _esc(r['id']), _esc(r['league']), _esc(r['home']), _esc(r['away']),
                _esc(r['hc_str']), _esc(r['folder'] or ''), _esc(r['score']),
                _esc(r['totalGoals']), size_cls, _esc(r['size'] or '-'),
                _esc(prob_over), _esc(prob_under),
                _esc(('预测' + r['predict']) if r['predict'] else '-'),
                corr_cls, _esc(r['correct'] or '-'), _esc(r['lamRatioStr'])))
    html = """<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>大小球统计（%s）</title>
<style>
body{font-family:-apple-system,"Microsoft YaHei",sans-serif;background:#f5f7fa;color:#1f2a37;margin:0;padding:18px;}
h1{font-size:18px;margin:0 0 4px;}
.meta{color:#8a94a6;font-size:12px;margin-bottom:14px;}
.cards{display:flex;flex-wrap:wrap;gap:14px;margin-bottom:16px;}
.card{background:#fff;border:1px solid #e2e6ea;border-radius:10px;padding:12px 18px;min-width:190px;box-shadow:0 1px 3px rgba(0,0,0,.05);}
.card .num{font-size:26px;font-weight:800;color:#1a3c6e;line-height:1.1;}
.card .lbl{font-size:13px;margin-top:4px;}
.card .sub{font-size:12px;color:#8a94a6;margin-top:2px;}
table{border-collapse:collapse;background:#fff;width:100%%;font-size:13px;box-shadow:0 1px 3px rgba(0,0,0,.05);}
th,td{border-bottom:1px solid #eef1f4;padding:7px 10px;text-align:center;white-space:nowrap;}
th{background:#f5f7fa;color:#33445a;font-weight:700;}
td.size-over{color:#c62828;font-weight:700;} td.size-under{color:#2e7d32;font-weight:700;} td.size-draw{color:#757575;font-weight:700;}
.corr-ok{color:#2e7d32;font-weight:700;} .corr-bad{color:#c62828;font-weight:700;} .corr-ign{color:#8a94a6;}
td.left{text-align:left;}
</style></head><body>
<h1>足球大小球统计视图（独立 Python 版）</h1>
<div class="meta">预测数据口径：<b>%s</b> ｜ 筛选：%s ｜ 共 %d 场，其中 %d 场有完场比分</div>
<div class="cards">%s</div>
<table><thead><tr>
<th>赛事ID</th><th>联赛</th><th>主队</th><th>客队</th><th>盘口</th><th>快照</th>
<th>比分</th><th>总进球</th><th>大小</th><th>大/小概率</th><th>预测</th><th>正确</th><th>λ总/λ</th>
</tr></thead><tbody>%s</tbody></table>
</body></html>""" % (
        order, order, _esc(filters), len(rows),
        sum(1 for r in rows if r['hasScore']), cards, ''.join(rows_html))
    with open(path, 'w', encoding='utf-8') as f:
        f.write(html)


def _esc(s):
    s = '' if s is None else str(s)
    return (s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;'))


# ============================================================
# 7. 新增：增量更新模式（--update）
# ============================================================

def pick_snapshot_for_id(mid, folders, raw_data, order='first'):
    """按 order 在全部文件夹中为某场比赛挑选第一条/末条完整快照。
    first=最老（开盘），last=最新（临场）。返回 (rec, folder) 或 (None, None)。"""
    ordered = folders if order == 'first' else list(reversed(folders))
    for folder in ordered:
        fd = raw_data.get(folder, {}) or {}
        r = fd.get(mid)
        if not r or not r.get('ou'):
            continue
        ou = r.get('ou', {})
        try:
            oo = float(ou.get('oo'))
            uo = float(ou.get('uo'))
            li = float(ou.get('li'))
        except (ValueError, TypeError):
            continue
        if not (oo > 0) or not (uo > 0) or isnan(li):
            continue
        ng = r.get('ng', {}) or {}
        if not all(ng.get(k) is not None and _to_float(ng[k]) > 0 for k in NG_COLS):
            continue
        return r, folder
    return None, None


def update_stats(data_path, output_path, order='first'):
    """
    增量更新模式：
      1. 从 his_data.js 中取最新文件夹的所有有效记录（含 ng 和 ou）
      2. 计算预测、比分匹配等
      3. 与已有的 stats.csv 合并（按 id 去重，保留最新）
      4. 输出新的 stats.csv
    """
    print("📥 加载数据源:", data_path)
    folders, raw_data, score_arrays = load_data(data_path)
    if not folders:
        print("❌ 没有找到任何文件夹")
        sys.exit(1)

    latest = folders[-1]
    print("📁 最新文件夹:", latest)
    folder_data = raw_data.get(latest, {})
    if not folder_data:
        print("❌ 最新文件夹无数据")
        sys.exit(1)

    score_index = build_score_index(score_arrays)

    new_records = []  # 存放新生成的记录（字典）

    for mid, _ in folder_data.items():
        # 按 order 选取每场比赛的快照：first=最老（开盘），last=最新（临场）
        chosen, snap_folder = pick_snapshot_for_id(mid, folders, raw_data, order)
        if chosen is None:
            continue
        rec = chosen
        oc = rec.get('oc', {})
        if not oc:
            continue
        league = oc.get('st', '')
        home = oc.get('sh', '')
        away = oc.get('sa', '')
        gt = oc.get('gt', '')
        if not gt:
            continue

        ng = rec.get('ng', {})
        ou = rec.get('ou', {})
        # 检查是否有完整的 ng 和 ou
        ng_cols = ['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'a1', 'a2', 'a3', 'a4', 'a5', 'a6']
        has_ng = all(ng.get(k) is not None and _to_float(ng[k]) > 0 for k in ng_cols)
        has_ou = (ou.get('oo') and ou.get('uo') and ou.get('li'))
        if not has_ng or not has_ou:
            # 缺少必要数据，跳过（无法计算预测）
            continue

        try:
            oo = float(ou['oo'])
            uo = float(ou['uo'])
            li = float(ou['li'])
            if not (oo > 0 and uo > 0 and li > 0):
                continue
        except (ValueError, TypeError):
            continue

        # 计算分析
        analysis = analyze_row(rec)
        hc_num = li / 4.0

        # 计算预测概率
        p_over_norm = None
        p_under_norm = None
        predict = ''
        if analysis and analysis['ngTgProbs'] and len(analysis['ngTgProbs']) >= 8:
            ou_raw = calc_ou_probs_from_dist(analysis['ngTgProbs'], hc_num)
            total_div = ou_raw['pOver'] + ou_raw['pUnder']
            if total_div > 0:
                p_over_norm = ou_raw['pOver'] / total_div
                p_under_norm = ou_raw['pUnder'] / total_div
                if p_over_norm > p_under_norm:
                    predict = '大'
                elif p_under_norm > p_over_norm:
                    predict = '小'

        # 匹配比分
        score_info = lookup_score_for_rec(score_index, league, home, away, gt)
        score_str = '-'
        total_goals_str = '-'
        size = ''
        if score_info:
            score_str = score_info['score']
            total_goals_str = score_info['totalGoals']
            tg_num = _to_float(score_info['totalGoals'])
            if not isnan(tg_num):
                if tg_num > hc_num:
                    size = '大'
                elif tg_num < hc_num:
                    size = '小'
                else:
                    size = '平'

        # 正确性
        correct = ''
        if predict and size:
            correct = '忽略' if size == '平' else ('对' if predict == size else '错')

        lam_total = '%.3f' % analysis['ngLamTotal'] if analysis.get('ngLamTotal') is not None else ''
        lam = '%.3f' % analysis['ouLam'] if analysis.get('ouLam') is not None else ''

        new_records.append({
            'id': mid,
            'gt': gt,
            'league': league,
            'home': home,
            'away': away,
            'hc': '%.2f' % hc_num,
            'folder': snap_folder,
            'score': score_str,
            'totalGoals': total_goals_str,
            'size': size,
            'predict': predict,
            'correct': correct,
            'lamTotal': lam_total,
            'lam': lam,
        })

    print(f"✅ 从最新文件夹提取了 {len(new_records)} 条有效记录")

    # 读取历史 stats.csv（如果存在）
    hist_dict = {}
    if os.path.exists(output_path):
        with open(output_path, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            # 确保列存在
            if 'id' in reader.fieldnames:
                for row in reader:
                    hist_dict[row['id']] = row
        print(f"📂 读取历史记录 {len(hist_dict)} 条")
    else:
        print("📂 历史文件不存在，将新建")

    # 合并：新记录覆盖旧记录（按 id）
    for rec in new_records:
        hist_dict[rec['id']] = rec

    # 转为列表并排序（按 gt 时间）
    merged = list(hist_dict.values())
    merged.sort(key=lambda x: x.get('gt', ''))

    # 写入输出
    fieldnames = ['id', 'gt', 'league', 'home', 'away', 'hc', 'folder',
                  'score', 'totalGoals', 'size', 'predict', 'correct', 'lamTotal', 'lam']
    with open(output_path, 'w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in merged:
            writer.writerow(row)

    print(f"💾 已保存 {len(merged)} 条记录到 {output_path}")


# ============================================================
# 8. 主程序
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description='足球大小球「统计视图」独立 Python 实现（数据源 his_data.js）')
    here = os.path.dirname(os.path.abspath(__file__))
    default_data = os.path.normpath(os.path.join(here, '..', '..', 'xml', 'scripts', 'docs', 'his_data.js'))
    parser.add_argument('--data', default=default_data, help='his_data.js 路径（默认 ../../xml/scripts/docs/his_data.js）')
    parser.add_argument('--order', choices=['first', 'last'], default='first',
                        help='取每场的第一条 / 末条完整数据（默认 first）')
    parser.add_argument('--predict', choices=['big', 'small', 'none'], default='',
                        help='筛选预测方向：big=预测大, small=预测小, none=未预测')
    parser.add_argument('--size', choices=['big', 'small', 'draw', 'none'], default='',
                        help='筛选大小：big=大, small=小, draw=平, none=无比分')
    parser.add_argument('--league', default='', help='筛选联赛（精确匹配）')
    parser.add_argument('--csv', default='', help='CSV 导出路径（默认 大小球统计_YYYY-MM-DD.csv）')
    parser.add_argument('--html', default='', help='HTML 报告导出路径（可选）')
    parser.add_argument('--all', action='store_true', help='忽略 ±24h 窗口，使用最新文件夹全部含 NG 记录')
    parser.add_argument('--now', default='', help='指定“当前”时间，格式 "YYYYMMDD HH:MM"，用于复现窗口')
    parser.add_argument('--limit', type=int, default=None, help='控制台仅显示前 N 行（CSV/HTML 仍含全部）')
    # 新增参数
    parser.add_argument('--update', action='store_true', help='增量更新模式：从最新文件夹提取记录，合并到历史 stats.csv')
    parser.add_argument('--output', default='stats.csv', help='update 模式下输出 CSV 路径')

    args = parser.parse_args()

    if args.update:
        # 执行增量更新（按 --order 选择每场最老/最新快照）
        update_stats(args.data, args.output, args.order)
        return

    # === 原有统计视图模式 ===
    if not os.path.exists(args.data):
        print('错误：找不到数据源 %s' % args.data, file=sys.stderr)
        sys.exit(1)

    print('加载数据：%s' % args.data)
    folders, raw_data, score_arrays = load_data(args.data)
    print('  FOLDERS 数：%d ｜ RAW_DATA 文件夹：%d ｜ SCORE_DATA 数组：%d'
          % (len(folders), len(raw_data), len(score_arrays)))

    score_index = build_score_index(score_arrays)

    now = beijing_now(args.now) if args.now else beijing_now()
    records, latest = build_analysis_records(folders, raw_data, now, args.all)
    print('最新文件夹：%s ｜ 分析记录数：%d（%s）'
          % (latest, len(records), ('全部' if args.all else '±24h 窗口')))

    if not records:
        print('无符合条件的分析记录，退出。')
        sys.exit(0)

    rows = []
    for rec in records:
        try:
            rows.append(process_match(rec, folders, raw_data, score_index, args.order))
        except Exception as e:
            print('  [警告] 处理 %s 失败：%s' % (rec.get('id'), e), file=sys.stderr)

    # 筛选
    rows = apply_filters(rows, args.predict, args.size, args.league)
    summary = summarize(rows)

    with_score = sum(1 for r in rows if r['hasScore'])
    print('\n=== 汇总（口径：%s，平局已忽略）===' % ('首条完整数据' if args.order == 'first' else '末条完整数据'))
    print('共 %d 场，其中 %d 场有完场比分' % (len(rows), with_score))
    print('预测大球：%d 场，正确 %d（%.1f%%）' % (summary['predOver'], summary['corrOver'], summary['rateOver'] * 100))
    print('预测小球：%d 场，正确 %d（%.1f%%）' % (summary['predUnder'], summary['corrUnder'], summary['rateUnder'] * 100))
    print('整体预测正确率：%d / %d = %.1f%%' % (summary['corrTotal'], summary['predTotal'], summary['rateAll'] * 100))
    print('\n=== 明细 ===')
    print_table(rows, limit=args.limit)

    # CSV
    csv_path = args.csv or ('大小球统计_%s.csv' % datetime.now().strftime('%Y-%m-%d'))
    export_csv(rows, csv_path)
    print('\nCSV 已导出：%s' % os.path.abspath(csv_path))

    # HTML
    if args.html:
        filters_desc = '预测=%s 大小=%s 联赛=%s' % (
            args.predict or '全部', args.size or '全部', args.league or '全部')
        export_html(rows, summary, args.html, args.order, filters_desc)
        print('HTML 已导出：%s' % os.path.abspath(args.html))


if __name__ == '__main__':
    main()