import json
import os
from datetime import datetime
import pandas as pd
import argparse


def extract_match_data(item):
    start_date = item.get('startDate', '')
    tournament = item.get('uqTournament', {}).get('fullname', '')
    home_team = item.get('hometeamName', '') or item.get('hometeamNameZh', '')
    away_team = item.get('awayteamName', '') or item.get('awayteamNameZh', '')

    # 即时比分优先取 ft（完场），若无则取 current
    score_obj = item.get('score', {})
    ft_score = score_obj.get('ft', '')
    if ft_score:
        score_str = ft_score
        score_source = '完场'
    else:
        score_str = score_obj.get('current', '')
        score_source = '当前'

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
        'scoreNote': score_source,
        'totalGoals': total_goals,
        'goalDiff': goal_diff
    }


def deduplicate_and_sort(df):
    """单次提取内可能重复（极少），按组合键去重并排序"""
    if df.empty:
        return df
    df['_dup_key'] = df['startDate'] + '|' + df['tournament'] + '|' + df['homeTeam'] + '|' + df['awayTeam']
    df.drop_duplicates(subset=['_dup_key'], keep='last', inplace=True)
    df.drop(columns=['_dup_key'], inplace=True)

    df['startDate'] = df['startDate'].fillna('')
    df.sort_values('startDate', inplace=True)
    return df


def append_to_js(records, js_path):
    """把解析出的比分记录以独立变量数组的形式，追加到 js 文件末尾（不影响原有 RAW_DATA）。"""
    if not records:
        return
    # 目标目录不存在则创建
    js_dir = os.path.dirname(js_path)
    if js_dir and not os.path.exists(js_dir):
        os.makedirs(js_dir, exist_ok=True)

    # 用当前时间做变量后缀，避免重复运行时变量名冲突，同时保留历史批次
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    var_name = f'SCORE_DATA_{stamp}'
    js_array = json.dumps(records, ensure_ascii=False, indent=2)

    block = (
        f"\n// ===== 比分数据（由 parse_scores.py 追加于 {stamp}）=====\n"
        f"var {var_name} = {js_array};\n"
    )

    # 以追加模式写入，内容加在原文件末尾
    with open(js_path, 'a', encoding='utf-8') as f:
        f.write(block)
    print(f"✅ 已追加 {len(records)} 条比分记录至 {js_path}（变量名 {var_name}）")


def main():
    parser = argparse.ArgumentParser(description='解析即时比分 scores.json，覆盖保存 CSV 并追加到 JS')
    parser.add_argument('--input', required=True, help='scores.json 文件路径')
    parser.add_argument('--output', default='scores_now.csv', help='输出 CSV 路径（默认 scores_now.csv）')
    # 默认目标：脚本同目录下的 scripts/docs/his_data.js；传空字符串可跳过 JS 输出
    default_js = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'scripts', 'docs', 'his_data.js')
    parser.add_argument('--js-output', default=default_js, help='追加输出的 JS 文件路径（默认 <脚本目录>/scripts/docs/his_data.js，传空则跳过）')
    args = parser.parse_args()

    with open(args.input, 'r', encoding='utf-8') as f:
        data = json.load(f)
    items = data.get('data', {}).get('list', [])
    records = [extract_match_data(item) for item in items if item.get('startDate')]
    df = pd.DataFrame(records)

    df_result = deduplicate_and_sort(df)

    # 1) 保留原有 CSV 输出
    df_result.to_csv(args.output, index=False, encoding='utf-8-sig')
    print(f"✅ 已保存 {len(df_result)} 条记录至 {args.output}")

    # 2) 追加到 JS 文件（默认开启；--js-output "" 可关闭）
    if args.js_output:
        append_to_js(df_result.to_dict(orient='records'), args.js_output)


if __name__ == '__main__':
    main()
