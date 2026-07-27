import json
import pandas as pd
import argparse
from pathlib import Path


def extract_match_data(item):
    """提取单场比赛所需字段，返回字典"""
    start_date = item.get('startDate', '')
    tournament = item.get('uqTournament', {}).get('fullname', '')
    home_team = item.get('hometeamName', '') or item.get('hometeamNameZh', '')
    away_team = item.get('awayteamName', '') or item.get('awayteamNameZh', '')

    # 比分优先取 ft，若无则取 current
    score_obj = item.get('score', {})
    score_str = score_obj.get('ft', '') or score_obj.get('current', '')

    total_goals = None
    goal_diff = None
    if score_str and ':' in score_str:
        parts = score_str.split(':')
        if len(parts) == 2:
            try:
                h = int(parts[0])
                a = int(parts[1])
                total_goals = h + a
                goal_diff = h - a
            except ValueError:
                pass

    return {
        'startDate': start_date,
        'tournament': tournament,
        'homeTeam': home_team,
        'awayTeam': away_team,
        'score': score_str,
        'totalGoals': total_goals,
        'goalDiff': goal_diff
    }


def deduplicate_and_sort(df):
    """按组合键去重，保留最新（按出现顺序），并按时间排序"""
    # 去重键：startDate + tournament + homeTeam + awayTeam
    df['_dup_key'] = df['startDate'] + '|' + df['tournament'] + '|' + df['homeTeam'] + '|' + df['awayTeam']
    df.drop_duplicates(subset=['_dup_key'], keep='last', inplace=True)
    df.drop(columns=['_dup_key'], inplace=True)

    # 排序
    df['startDate'] = df['startDate'].fillna('')
    df.sort_values('startDate', inplace=True)
    return df


def main():
    parser = argparse.ArgumentParser(description='解析完场比分 results.json，累积去重')
    parser.add_argument('--input', required=True, help='今日 results.json 文件路径')
    parser.add_argument('--history', default='history.csv', help='历史 CSV 文件路径（默认 history.csv）')
    parser.add_argument('--output', default='history.csv', help='输出 CSV 路径（默认与 --history 相同）')
    args = parser.parse_args()

    # 读取今日数据
    with open(args.input, 'r', encoding='utf-8') as f:
        data = json.load(f)
    items = data.get('data', {}).get('list', [])
    new_records = [extract_match_data(item) for item in items if item.get('startDate')]  # 过滤无时间记录
    df_new = pd.DataFrame(new_records)

    # 读取历史数据（若存在）
    if Path(args.history).exists():
        df_hist = pd.read_csv(args.history, encoding='utf-8-sig')
    else:
        df_hist = pd.DataFrame()

    # 合并
    if not df_hist.empty:
        df_combined = pd.concat([df_hist, df_new], ignore_index=True)
    else:
        df_combined = df_new

    # 去重并排序
    df_result = deduplicate_and_sort(df_combined)

    # 保存（UTF-8-BOM）
    df_result.to_csv(args.output, index=False, encoding='utf-8-sig')
    print(f"✅ 已保存 {len(df_result)} 条记录至 {args.output}")


if __name__ == '__main__':
    main()
