#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
b.py - 足球比分模拟分析脚本（独立计算模块）
功能：
1. 从 GitHub 加载 numberofgoals.xml、odds_config.xml、windrawwin.xml
2. 按 XML 原始顺序遍历比赛，仅处理比赛时间 ≤ 当前时间 + 24 小时的场次
3. 使用模拟算法计算胜平负概率、期望进球、期望赔付、总进球高概率区间
4. 输出结果到 data/analysis_output.json（可被 c.py 读取展示）
"""

import json
import os
import time
import datetime
from datetime import timezone, timedelta
import requests
import xml.etree.ElementTree as ET
import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple

# ================= 常量定义 =================
MAX_GOALS = 5                     # 最大进球数（赔率表定义）
SIM_N = 500_000                   # 每次模拟次数
XML_BASE_URL = "https://raw.githubusercontent.com/52483588/xml/refs/heads/main/"
OUTPUT_DIR = "data"
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "analysis_output.json")

# 需要下载的 XML 文件列表
XML_FILES = [
    "numberofgoals.xml",
    "odds_config.xml",
    "windrawwin.xml"
]

# ================= 辅助函数 =================
def get_beijing_time() -> datetime.datetime:
    """返回当前北京时间（带时区）"""
    beijing_tz = timezone(timedelta(hours=8))
    return datetime.datetime.now(beijing_tz)

def beijing_time_str() -> str:
    return get_beijing_time().strftime("%Y-%m-%d %H:%M:%S")

def parse_gt_to_datetime(gt_raw: str) -> Optional[datetime.datetime]:
    """
    解析 XML 中的 gt 字段，支持：
    - "YYYYMMDD HH:MM"  例如 "20260508 01:30"
    - 纯数字14位 "YYYYMMDDHHMMSS"（兼容旧格式）
    返回北京时间 datetime 对象，失败返回 None
    """
    if not gt_raw:
        return None
    gt_raw = gt_raw.strip()
    beijing_tz = timezone(timedelta(hours=8))
    
    # 格式1: "20260508 01:30"
    if ' ' in gt_raw and ':' in gt_raw:
        try:
            parts = gt_raw.split()
            date_str = parts[0]
            time_str = parts[1]
            year = int(date_str[:4])
            month = int(date_str[4:6])
            day = int(date_str[6:8])
            hour, minute = map(int, time_str.split(':'))
            dt = datetime.datetime(year, month, day, hour, minute)
            return dt.replace(tzinfo=beijing_tz)
        except (ValueError, IndexError):
            pass
    
    # 格式2: 纯数字14位
    if len(gt_raw) == 14 and gt_raw.isdigit():
        try:
            dt = datetime.datetime.strptime(gt_raw, "%Y%m%d%H%M%S")
            return dt.replace(tzinfo=beijing_tz)
        except ValueError:
            pass
    
    return None

def format_gt_display(gt_raw: str) -> str:
    """将原始 gt 字符串格式化为 'YYYY-MM-DD HH:MM:SS' 便于阅读"""
    if not gt_raw:
        return "未知"
    
    if ' ' in gt_raw and ':' in gt_raw:
        try:
            date_part, time_part = gt_raw.split()
            year = date_part[:4]
            month = date_part[4:6]
            day = date_part[6:8]
            return f"{year}-{month}-{day} {time_part}:00"
        except:
            pass
    
    if len(gt_raw) == 14 and gt_raw.isdigit():
        try:
            dt = datetime.datetime.strptime(gt_raw, "%Y%m%d%H%M%S")
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except:
            pass
    
    return gt_raw

# ================= XML 解析模块 =================
def parse_numberofgoals(xml_content: str) -> Tuple[Dict[str, Dict], List[str]]:
    root = ET.fromstring(xml_content)
    result = {}
    ordered_ids = []
    for fixture in root.findall(".//Fixture"):
        match_id = fixture.get("id")
        if not match_id:
            continue
        ordered_ids.append(match_id)
        data = {}
        for i in range(1, 7):
            key = f"h{i}"
            val = fixture.get(key)
            try:
                data[key] = float(val) if val is not None else 0.0
            except ValueError:
                data[key] = 0.0
        for i in range(1, 7):
            key = f"a{i}"
            val = fixture.get(key)
            try:
                data[key] = float(val) if val is not None else 0.0
            except ValueError:
                data[key] = 0.0
        result[match_id] = data
    return result, ordered_ids

def parse_odds_config(xml_content: str) -> Dict[str, Dict]:
    root = ET.fromstring(xml_content)
    result = {}
    fields = ["gt","st","sh","sa"]
    for fixture in root.findall(".//Fixture"):
        match_id = fixture.get("id")
        if not match_id:
            continue
        data = {}
        for f in fields:
            val = fixture.get(f)
            data[f] = val if val is not None else None
        result[match_id] = data
    return result

def parse_windrawwin(xml_content: str) -> Dict[str, Dict]:
    root = ET.fromstring(xml_content)
    result = {}
    fields = ["ho","do","ao"]
    for fixture in root.findall(".//Fixture"):
        match_id = fixture.get("id")
        if not match_id:
            continue
        data = {}
        for f in fields:
            val = fixture.get(f)
            data[f] = float(val) if val is not None else 0.0
        result[match_id] = data
    return result

class FootballDataLoader:
    def __init__(self):
        self.numberofgoals = {}
        self.odds_config = {}
        self.windrawwin = {}
        self.ordered_ids = []

    def load_from_dict(self, file_dict: Dict[str, str]):
        for filename, content in file_dict.items():
            if "numberofgoals" in filename:
                ng_data, ordered = parse_numberofgoals(content)
                self.numberofgoals = ng_data
                self.ordered_ids = ordered
            elif "odds_config" in filename:
                self.odds_config = parse_odds_config(content)
            elif "windrawwin" in filename and "firsthalf" not in filename:
                self.windrawwin = parse_windrawwin(content)

    def get_odds_for_match(self, match_id: str) -> Tuple[List[float], List[float]]:
        if match_id not in self.numberofgoals:
            return [1.0]*6, [1.0]*6
        data = self.numberofgoals[match_id]
        home_odds = [data.get(f"h{i}", 1.0) for i in range(1, 7)]
        away_odds = [data.get(f"a{i}", 1.0) for i in range(1, 7)]
        return home_odds, away_odds

    def get_match_basic_info(self, match_id: str) -> Dict[str, Optional[str]]:
        if match_id not in self.odds_config:
            return {"gt": None, "st": None, "sh": None, "sa": None}
        cfg = self.odds_config[match_id]
        return {
            "gt": cfg.get("gt"),
            "st": cfg.get("st"),
            "sh": cfg.get("sh"),
            "sa": cfg.get("sa")
        }

    def get_windrawwin_odds(self, match_id: str) -> Tuple[float, float, float]:
        if match_id in self.windrawwin:
            data = self.windrawwin[match_id]
            return data.get("ho", 0.0), data.get("do", 0.0), data.get("ao", 0.0)
        return 0.0, 0.0, 0.0

# ================= 赔率转概率 =================
def odds_to_probs(odds_home: List[float], odds_away: List[float]) -> Tuple[List[float], List[float]]:
    def calc_E(odds_list):
        sum_inv = sum(1 / o for o in odds_list[:6])
        if sum_inv == 0:
            return [0.0] * 5
        C = 1 / sum_inv
        D = [C / o for o in odds_list[:5]]
        E = []
        cum_D = 0
        for d in D:
            e = d / (1 - cum_D) if (1 - cum_D) > 0 else 0
            E.append(e)
            cum_D += d
        return E

    if len(odds_home) < 6:
        odds_home = odds_home + [1.0] * (6 - len(odds_home))
    if len(odds_away) < 6:
        odds_away = odds_away + [1.0] * (6 - len(odds_away))

    home_probs = calc_E(odds_home[:6])
    away_probs = calc_E(odds_away[:6])
    return home_probs, away_probs

# ================= 核心模拟函数 =================
def simulate_goals_vectorized(probs, n_sims):
    rand_vals = np.random.random((n_sims, 5))
    success = rand_vals >= np.array(probs)
    goals = np.zeros(n_sims, dtype=int)
    for i in range(n_sims):
        row = success[i]
        if np.all(row):
            goals[i] = 5
        else:
            goals[i] = np.argmin(row)
    return goals

def run_simulation(home_p, away_p, n_sims):
    start_time = time.time()
    home_goals = simulate_goals_vectorized(home_p, n_sims)
    away_goals = simulate_goals_vectorized(away_p, n_sims)
    results = pd.DataFrame({
        'home_goals': home_goals,
        'away_goals': away_goals
    })
    results['score'] = results['home_goals'].astype(str) + '-' + results['away_goals'].astype(str)
    results['total_goals'] = results['home_goals'] + results['away_goals']

    score_counts = results['score'].value_counts().reset_index()
    score_counts.columns = ['比分', '频次']
    score_counts['概率'] = score_counts['频次'] / n_sims

    home_win_prob = (results['home_goals'] > results['away_goals']).mean()
    draw_prob = (results['home_goals'] == results['away_goals']).mean()
    away_win_prob = (results['home_goals'] < results['away_goals']).mean()

    exp_home = results['home_goals'].mean()
    exp_away = results['away_goals'].mean()

    total_goals_dist = results['total_goals'].value_counts().sort_index()
    total_goals_df = pd.DataFrame({
        '总进球': total_goals_dist.index,
        '频次': total_goals_dist.values,
        '概率': total_goals_dist.values / n_sims
    })

    home_goal_dist = pd.Series(home_goals).value_counts().sort_index()
    away_goal_dist = pd.Series(away_goals).value_counts().sort_index()
    for g in range(6):
        if g not in home_goal_dist.index:
            home_goal_dist[g] = 0
        if g not in away_goal_dist.index:
            away_goal_dist[g] = 0
    home_goal_dist = home_goal_dist.sort_index()
    away_goal_dist = away_goal_dist.sort_index()

    elapsed = time.time() - start_time
    return {
        'score_counts': score_counts,
        'home_win_prob': home_win_prob,
        'draw_prob': draw_prob,
        'away_win_prob': away_win_prob,
        'exp_home': exp_home,
        'exp_away': exp_away,
        'total_goals_df': total_goals_df,
        'home_goal_dist': home_goal_dist,
        'away_goal_dist': away_goal_dist,
        'n_sims': n_sims,
        'elapsed': elapsed
    }

# ================= 主控制逻辑 =================
def load_xml_files() -> Optional[FootballDataLoader]:
    """从当前目录读取 XML 文件，若失败则从 GitHub 下载"""
    xml_contents = {}
    for fname in XML_FILES:
        if os.path.exists(fname):
            with open(fname, "r", encoding="utf-8") as f:
                xml_contents[fname] = f.read()
        else:
            print(f"⚠️ 本地文件 {fname} 不存在")
            break
    else:
        loader = FootballDataLoader()
        loader.load_from_dict(xml_contents)
        print("✅ 使用本地 XML 文件（当前目录）")
        return loader

    print("⬇️ 本地 XML 文件未找到，从 GitHub 下载...")
    xml_contents = {}
    for fname in XML_FILES:
        url = XML_BASE_URL + fname
        try:
            resp = requests.get(url, timeout=15)
            if resp.status_code == 200:
                xml_contents[fname] = resp.text
            else:
                print(f"❌ 下载失败 {fname} (HTTP {resp.status_code})")
                return None
        except Exception as e:
            print(f"❌ 请求异常 {fname}: {e}")
            return None
    loader = FootballDataLoader()
    loader.load_from_dict(xml_contents)
    print("✅ 从 GitHub 下载完成")
    return loader

def main():
    print(f"[{beijing_time_str()}] 开始批量分析脚本 b.py")
    print(f"模拟次数: {SIM_N:,}")

    loader = load_xml_files()
    if loader is None:
        print("数据加载失败，退出")
        return

    ordered_ids = loader.ordered_ids
    print(f"总共发现 {len(ordered_ids)} 场比赛（按原始顺序）")

    now_beijing = get_beijing_time()
    print(f"当前北京时间: {now_beijing.strftime('%Y-%m-%d %H:%M:%S')}")
    print("开始处理，遇到比赛时间 > 当前时间+4小时 则停止\n")

    records = []
    processed_count = 0
    stop_reason = None

    for match_id in ordered_ids:
        basic = loader.get_match_basic_info(match_id)
        gt_raw = basic.get("gt")
        if not gt_raw:
            print(f"跳过 {match_id}: 缺少比赛时间(gt)")
            continue

        match_time = parse_gt_to_datetime(gt_raw)
        if match_time is None:
            print(f"跳过 {match_id}: 时间解析失败 ({gt_raw})")
            continue

        delta = match_time - now_beijing
        if delta.total_seconds() < -1.5 * 3600:
            print(f"⏪ 跳过过去比赛 {match_id}: {match_time}")
            continue
        if delta.total_seconds() > 2 * 3600:
            print(f"⏹️ 停止于 {match_id} (比赛时间超出未来2小时)")
            stop_reason = f"遇到比赛时间超出未来2小时: {match_id}"
            break

        print(f"处理 {match_id}: {basic.get('sh')} vs {basic.get('sa')}  时间: {match_time.strftime('%Y-%m-%d %H:%M')}")

        home_odds, away_odds = loader.get_odds_for_match(match_id)
        home_probs, away_probs = odds_to_probs(home_odds, away_odds)

        sim_data = run_simulation(home_probs, away_probs, SIM_N)

        home_win_prob = sim_data['home_win_prob']
        draw_prob = sim_data['draw_prob']
        away_win_prob = sim_data['away_win_prob']
        exp_home = sim_data['exp_home']
        exp_away = sim_data['exp_away']

        ho, do, ao = loader.get_windrawwin_odds(match_id)
        exp_ho = home_win_prob * ho
        exp_do = draw_prob * do
        exp_ao = away_win_prob * ao
        exp_x = 1 / (1 / ho + 1 / do + 1 / ao)

        # ----- 修改部分：总进球概率分布 -----
        total_df = sim_data['total_goals_df'].copy()
        prob_map = {}
        for g in range(8):  # 0-6
            prob = total_df[total_df['总进球'] == g]['概率'].values
            prob_map[g] = prob[0] if len(prob) > 0 else 0.0
        prob_7plus = total_df[total_df['总进球'] >= 7]['概率'].sum()
        # 格式化输出，例如 "0:12.5% 1:15.2% ... 7+:5.1%"
        total_prob_str = " ".join([f"{g}:{prob_map[g]:.1%}" for g in range(7)] + [f"7+:{prob_7plus:.1%}"])
        # -----------------------------

        display_time = format_gt_display(gt_raw)

        record = {
            "match_id": match_id,
            "时间": display_time,
            "赛事": basic.get("st", "未知"),
            "主队": basic.get("sh", "未知"),
            "客队": basic.get("sa", "未知"),
            "胜概率": f"{home_win_prob:.2%}",
            "平概率": f"{draw_prob:.2%}",
            "负概率": f"{away_win_prob:.2%}",
            "主进球": f"{exp_home:.3f}",
            "客进球": f"{exp_away:.3f}",
            "胜赔付": f"{exp_ho:.4f}",
            "平赔付": f"{exp_do:.4f}",
            "负赔付": f"{exp_ao:.4f}",
            "平均赔付": f"{exp_x:.4f}",
            "轮次>10%": total_prob_str,   # 字段名保持不变，内容改为概率分布
            "记录时间": beijing_time_str()
        }
        records.append(record)
        processed_count += 1

    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)

    output_data = {
        "generated_at": beijing_time_str(),
        "total_processed": processed_count,
        "stop_reason": stop_reason,
        "simulation_params": {
            "n_sims": SIM_N,
            "max_goals": MAX_GOALS
        },
        "records": records
    }

    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    json_file_ts = os.path.join(OUTPUT_DIR, f"analysis_output_{timestamp}.json")

    with open(json_file_ts, "w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)
    print(f"✅ JSON 历史版本: {json_file_ts}")

    print(f"\n✅ 分析完成！共处理 {processed_count} 场比赛")

if __name__ == "__main__":
    main()
