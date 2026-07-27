#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
parse_livescore_sc.py
---------------------
从澳门彩票 Macauslot 现场比分页面（简体版）提取足球比分数据。
支持两种运行方式：
  1. 命令行指定 HTML 文件路径：python parse_livescore_sc.py <html文件路径>
  2. 自动从桌面查找匹配的 HTML 文件

输出文件（与脚本同目录）：
  - livescore_output.txt      -> 纯文本表格
  - livescore_output.json     -> 结构化 JSON 数据
"""

import re
import json
import glob
import sys
import os
from datetime import datetime


def extract_matches(html: str) -> list:
    """
    从 HTML 中提取所有比赛信息。
    """
    matches = []

    # 按日期分块（每块以 <h1> 日期 </h1> 开头）
    date_blocks = list(re.finditer(r'<h1>([^<]+)</h1>', html))

    for i, db in enumerate(date_blocks):
        date_text = db.group(1).strip()
        block_start = db.end()
        block_end = date_blocks[i + 1].start() if i + 1 < len(date_blocks) else len(html)
        section = html[block_start:block_end]

        # 在该日期段内找到所有比赛行 <div class="row dl ...">
        for rm in re.finditer(r'<div class="row dl[^>]*>', section):
            row_start = rm.start()
            # 找下一个 row 或 section 结尾
            next_row = re.search(r'<div class="row dl[^>]*>', section[rm.end():])
            if next_row:
                row_end = rm.end() + next_row.start()
            else:
                row_end = len(section)
            row_html = section[row_start:row_end]

            match = _parse_row(row_html)
            if match:
                match['date'] = date_text
                matches.append(match)

    return matches


def _parse_row(row_html: str) -> dict:
    """解析单行比赛 HTML，返回字典。"""
    # 联赛名
    league = _extract_one(r'<div class="league dd">.*?<p>(.*?)</p>', row_html)
    if not league:
        return None

    # 时间
    match_time = _extract_one(r'<div class="time dd">\s*([\d:]+)\s*</div>', row_html)

    # 主队/客队名
    home = _extract_one(r'<div class="team_payout home[^>]*>.*?<p><span>(.*?)</span>', row_html)
    away = _extract_one(r'<div class="team_payout away[^>]*>.*?<p><span>(.*?)</span>', row_html)
    home = _strip_tags(home) if home else ''
    away = _strip_tags(away) if away else ''

    # 比分
    score_m = re.search(
        r'<div class="team-score">\s*<i>(.*?)</i>\s*<span>:</span>\s*<i>(.*?)</i>',
        row_html, re.DOTALL
    )
    home_score = score_m.group(1).strip() if score_m else ''
    away_score = score_m.group(2).strip() if score_m else ''

    # 半场比分
    half = ''
    half_m = re.search(r'半[场場]\s*(\d+:\d+)', row_html)
    if half_m:
        half = f"半场 {half_m.group(1)}"

    # 状态（完场 / 取消 / 进行中...）
    state = ''
    state_m = re.search(
        r'<div class="state[^>]*>.*?<p>(.*?)</p>', row_html, re.DOTALL
    )
    if state_m:
        state = _strip_tags(state_m.group(1).strip())
        # Simplified Chinese mapping
        state = state.replace('分鐘完', '分钟完')

    # 角球
    corner_m = re.search(r'半[场場]&nbsp;<i>(\d+)</i><span.*?</span><i>(\d+)</i>', row_html)
    corner_h = corner_m.group(1) if corner_m else ''
    corner_a = corner_m.group(2) if corner_m else ''

    return {
        'time': match_time or '',
        'league': league,
        'home_team': home,
        'away_team': away,
        'home_score': home_score,
        'away_score': away_score,
        'half_score': half,
        'state': state,
        'corner_home': corner_h,
        'corner_away': corner_a,
    }


def _extract_one(pattern: str, text: str) -> str:
    """正则提取第一个匹配组的文本，失败返回空字符串。"""
    m = re.search(pattern, text, re.DOTALL)
    return m.group(1).strip() if m else ''


def _strip_tags(text: str) -> str:
    """去除 HTML 标签。"""
    return re.sub(r'<[^>]+>', '', text).strip()


# ──────────────────────────────────────────────
#  输出模块
# ──────────────────────────────────────────────

def save_json(matches: list, filepath: str):
    """保存为 JSON 格式。"""
    output = {
        'source': 'www.macauslot.com/sc/soccer/livescore.html',
        'extracted_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'total_matches': len(matches),
        'matches': matches
    }
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"[JSON] -> {filepath}")


def save_text(matches: list, filepath: str):
    """保存为文本表格。"""
    sep = "=" * 120
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write("澳门彩票 Macauslot - 足球现场比分（简体版）\n")
        f.write(f"{sep}\n")
        f.write(f"来源: https://www.macauslot.com/sc/soccer/livescore.html\n")
        f.write(f"提取时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"比赛总数: {len(matches)}\n")
        f.write(f"{sep}\n")

        current_date = ""
        for m in matches:
            if m['date'] != current_date:
                current_date = m['date']
                f.write(f"\n{current_date}\n")
                f.write("-" * 120 + "\n")

            score = f"{m['home_score']}:{m['away_score']}" if m.get('home_score') or m.get('away_score') else "  -  "
            half = m['half_score'].ljust(10) if m['half_score'] else " " * 10
            st = m['state'].ljust(8) if m['state'] else " " * 8

            corner = ""
            if m['corner_home']:
                corner = f"  角球(半场: {m['corner_home']}:{m['corner_away']})"

            line = f"  {m['time']:>5}  {m['league']:<12}  {m['home_team']:<18} {score:>5}  {m['away_team']:<18}  {half}  {st}{corner}"
            f.write(line + "\n")

        f.write(f"\n{sep}\n")
        f.write(f"共 {len(matches)} 场比赛\n")
    print(f"[TXT] -> {filepath}")


def print_table(matches: list):
    """在控制台打印简表。"""
    header = f"{'日期':<15} {'时间':<7} {'联赛':<10} {'主队':<16} {'比分':>5}  {'客队':<16} {'半场':<9} {'状态':<8}"
    print(header)
    print("=" * 95)
    for m in matches:
        score = f"{m['home_score']:>1}:{m['away_score']:<1}" if m.get('home_score') or m.get('away_score') else " - "
        date_short = m['date'][:10] if '年' in m['date'] else m['date'][:15]
        half = m['half_score'].replace('半场 ', '') if m['half_score'] else ''
        st = m['state'][:6] if m['state'] else ''
        print(f"{date_short:<15} {m['time']:<7} {m['league']:<10} {m['home_team']:<16} {score:>4}  {m['away_team']:<16} {half:<9} {st:<8}")


# ──────────────────────────────────────────────
#  主入口
# ──────────────────────────────────────────────

def main():
    # 确定输入文件路径
    if len(sys.argv) >= 2:
        html_path = sys.argv[1]
    else:
        candidates = sorted(glob.glob(r'C:\Users\52483\Desktop\澳门彩票有限公司*.html'))
        if not candidates:
            print("错误: 未找到桌面澳门彩票 HTML 文件。")
            print("用法: python parse_livescore_sc.py <html文件路径>")
            sys.exit(1)
        html_path = candidates[0]
        print(f"自动检测到: {html_path}")

    # 读取 HTML
    with open(html_path, 'r', encoding='utf-8') as f:
        html = f.read()

    size_kb = len(html) / 1024
    print(f"读取文件完成 ({size_kb:.0f} KB)")

    # 解析
    matches = extract_matches(html)
    print(f"成功提取 {len(matches)} 场比赛数据\n")

    # 打印简表
    print_table(matches)

    # 保存文件（与脚本同目录）
    script_dir = os.path.dirname(os.path.abspath(__file__))
    save_json(matches, os.path.join(script_dir, 'livescore_output.json'))
    save_text(matches, os.path.join(script_dir, 'livescore_output.txt'))

    print(f"\n全部完成！共 {len(matches)} 场比赛。")


if __name__ == '__main__':
    main()
