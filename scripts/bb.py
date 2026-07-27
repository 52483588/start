#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
b.py - 足球比分分析脚本（优化版）
功能：
1. 从 GitHub 加载 numberofgoals.xml、odds_config.xml、windrawwin.xml
2. 按 XML 原始顺序遍历比赛，处理比赛时间在 [当前时间-1.5小时, 当前时间+12小时] 的场次
3. 使用归一化算法计算胜平负概率、期望进球、期望赔付、总进球概率分布
4. 输出结果到 data/analysis_output.json（可被 c.py 读取展示）
"""

import json
import os
import datetime
from datetime import timezone, timedelta
import requests
import xml.etree.ElementTree as ET
import numpy as np
from typing import Dict, List, Optional, Tuple

# ================= 常量定义 =================
MAX_GOALS = 5                     # 最大进球数（赔率表定义）
XML_BASE_URL = "https://raw.githubusercontent.com/52483588/xml/refs/heads/main/"
OUTPUT_DIR = "data"
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "analysis_output.json")  # 固定文件名，不加时间戳

# 需要下载的 XML 文件列表
XML_FILES = [
    "numberofgoals.xml",
    "odds_config.xml",
    "windrawwin.xml"
]

# 时间范围常量（小时）
PAST_HOURS = 12     # 过去12小时的比赛仍然处理
FUTURE_HOURS = 24     # 未来24小时的比赛全部处理


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
    """解析进球赔率 XML"""
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
    """解析比赛配置 XML（时间、球队等）"""
    root = ET.fromstring(xml_content)
    result = {}
    fields = ["gt", "st", "sh", "sa"]
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
    """解析胜平负赔率 XML"""
    root = ET.fromstring(xml_content)
    result = {}
    fields = ["ho", "do", "ao"]
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
    """足球数据加载器"""
    
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
        """获取主客队进球赔率（6个）"""
        if match_id not in self.numberofgoals:
            return [1.0] * 6, [1.0] * 6
        data = self.numberofgoals[match_id]
        home_odds = [data.get(f"h{i}", 1.0) for i in range(1, 7)]
        away_odds = [data.get(f"a{i}", 1.0) for i in range(1, 7)]
        return home_odds, away_odds

    def get_match_basic_info(self, match_id: str) -> Dict[str, Optional[str]]:
        """获取比赛基本信息（时间、球队等）"""
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
        """获取胜平负赔率"""
        if match_id in self.windrawwin:
            data = self.windrawwin[match_id]
            return data.get("ho", 0.0), data.get("do", 0.0), data.get("ao", 0.0)
        return 0.0, 0.0, 0.0


# ================= 赔率转概率（归一化算法）=================
def odds_to_probs_normalized(odds_home: List[float], odds_away: List[float]) -> Tuple[np.ndarray, np.ndarray]:
    """
    使用归一化（Softmax风格）将赔率转换为概率分布
    
    参数:
        odds_home: 主队赔率列表（6个值：0球、1球...5球+）
        odds_away: 客队赔率列表（6个值）
    
    返回:
        home_probs: 主队进球概率数组 [p0, p1, p2, p3, p4, p5+]，长度6，和为1
        away_probs: 客队进球概率数组，长度6，和为1
    """
    def normalize(odds: List[float]) -> np.ndarray:
        # 补齐到6个
        if len(odds) < 6:
            odds = odds + [1.0] * (6 - len(odds))
        else:
            odds = odds[:6]
        
        # 计算赔率倒数（概率未归一化）
        inv_odds = np.array([1.0 / max(o, 0.01) for o in odds])  # 避免除零
        
        total = inv_odds.sum()
        if total == 0:
            return np.ones(6) / 6
        
        # 归一化得到概率分布
        probs = inv_odds / total
        return probs
    
    home_probs = normalize(odds_home)
    away_probs = normalize(odds_away)
    return home_probs, away_probs


# ================= 进球概率分布计算（无需模拟）=================
def calculate_goal_distribution(home_probs: np.ndarray, away_probs: np.ndarray) -> Dict:
    """
    根据主客队进球概率分布，直接计算所有比分概率
    
    参数:
        home_probs: 主队进球概率 [p0, p1, p2, p3, p4, p5+]
        away_probs: 客队进球概率 [p0, p1, p2, p3, p4, p5+]
    
    返回:
        包含各种统计结果的字典
    """
    # 构建比分概率矩阵（6x6，最后一个表示5+）
    score_probs = np.outer(home_probs, away_probs)
    
    # 计算胜平负概率
    home_win_prob = 0.0
    draw_prob = 0.0
    away_win_prob = 0.0
    
    for i in range(6):
        for j in range(6):
            if i > j:
                home_win_prob += score_probs[i, j]
            elif i == j:
                draw_prob += score_probs[i, j]
            else:
                away_win_prob += score_probs[i, j]
    
    # 计算期望进球
    goals = np.array([0, 1, 2, 3, 4, 5])
    exp_home = np.sum(goals * home_probs)
    exp_away = np.sum(goals * away_probs)
    
    # 计算总进球概率分布（0-10+）
    total_probs = {}
    for total in range(11):  # 0-10
        prob = 0.0
        for i in range(min(total + 1, 6)):
            j = total - i
            if 0 <= j < 6:
                prob += score_probs[i, j]
        total_probs[total] = prob
    
    # 7+ 的概率（总进球≥7）
    prob_7plus = 1.0 - sum(total_probs[t] for t in range(7))
    
    return {
        'score_probs': score_probs,
        'home_win_prob': home_win_prob,
        'draw_prob': draw_prob,
        'away_win_prob': away_win_prob,
        'exp_home': exp_home,
        'exp_away': exp_away,
        'total_probs': total_probs,
        'prob_7plus': prob_7plus
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


def format_total_prob_str(total_probs: Dict[int, float], prob_7plus: float) -> str:
    """格式化总进球概率分布字符串"""
    parts = []
    for g in range(7):  # 0-6
        prob = total_probs.get(g, 0.0)
        parts.append(f"{g}:{prob:.1%}")
    parts.append(f"7+:{prob_7plus:.1%}")
    return " ".join(parts)


def main():
    print(f"[{beijing_time_str()}] 开始批量分析脚本 b.py（优化版）")
    print(f"时间范围：过去 {PAST_HOURS} 小时 ～ 未来 {FUTURE_HOURS} 小时")

    loader = load_xml_files()
    if loader is None:
        print("数据加载失败，退出")
        return

    ordered_ids = loader.ordered_ids
    print(f"总共发现 {len(ordered_ids)} 场比赛（按原始顺序）")

    now_beijing = get_beijing_time()
    print(f"当前北京时间: {now_beijing.strftime('%Y-%m-%d %H:%M:%S')}")
    
    # 计算时间边界
    past_cutoff = now_beijing - timedelta(hours=PAST_HOURS)
    future_cutoff = now_beijing + timedelta(hours=FUTURE_HOURS)
    print(f"处理范围: {past_cutoff.strftime('%Y-%m-%d %H:%M')} ～ {future_cutoff.strftime('%Y-%m-%d %H:%M')}\n")

    records = []
    processed_count = 0
    skipped_past = 0
    skipped_future = 0
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

        # 时间过滤：只处理 [过去PAST_HOURS小时, 未来FUTURE_HOURS小时] 的比赛
        if match_time < past_cutoff:
            skipped_past += 1
            continue
        
        if match_time > future_cutoff:
            # 由于 XML 是按时间顺序的，遇到未来超出范围的可以直接停止
            print(f"⏹️ 停止于 {match_id} (比赛时间超出未来 {FUTURE_HOURS} 小时)")
            stop_reason = f"遇到比赛时间超出未来 {FUTURE_HOURS} 小时: {match_id}"
            break

        print(f"处理 {match_id}: {basic.get('sh')} vs {basic.get('sa')}  时间: {match_time.strftime('%Y-%m-%d %H:%M')}")

        # 获取赔率并转换为概率
        home_odds, away_odds = loader.get_odds_for_match(match_id)
        home_probs, away_probs = odds_to_probs_normalized(home_odds, away_odds)
        
        # 计算各种概率分布
        dist = calculate_goal_distribution(home_probs, away_probs)

        # 获取胜平负赔率并计算期望赔付
        ho, do, ao = loader.get_windrawwin_odds(match_id)
        exp_ho = dist['home_win_prob'] * ho if ho > 0 else 0
        exp_do = dist['draw_prob'] * do if do > 0 else 0
        exp_ao = dist['away_win_prob'] * ao if ao > 0 else 0
        
        # 计算平均赔付（调和平均）
        if ho > 0 and do > 0 and ao > 0:
            exp_x = 1 / (1/ho + 1/do + 1/ao)
        else:
            exp_x = 0

        # 格式化总进球概率分布
        total_prob_str = format_total_prob_str(dist['total_probs'], dist['prob_7plus'])

        display_time = format_gt_display(gt_raw)

        record = {
            "match_id": match_id,
            "时间": display_time,
            "赛事": basic.get("st", "未知"),
            "主队": basic.get("sh", "未知"),
            "客队": basic.get("sa", "未知"),
            "胜概率": f"{dist['home_win_prob']:.2%}",
            "平概率": f"{dist['draw_prob']:.2%}",
            "负概率": f"{dist['away_win_prob']:.2%}",
            "主进球": f"{dist['exp_home']:.3f}",
            "客进球": f"{dist['exp_away']:.3f}",
            "胜赔付": f"{exp_ho:.4f}",
            "平赔付": f"{exp_do:.4f}",
            "负赔付": f"{exp_ao:.4f}",
            "平均赔付": f"{exp_x:.4f}",
            "轮次>10%": total_prob_str,
            "记录时间": beijing_time_str()
        }
        records.append(record)
        processed_count += 1

    # 确保输出目录存在
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)

    output_data = {
        "generated_at": beijing_time_str(),
        "total_processed": processed_count,
        "skipped_past": skipped_past,
        "stop_reason": stop_reason,
        "time_range": {
            "past_hours": PAST_HOURS,
            "future_hours": FUTURE_HOURS,
            "cutoff_start": past_cutoff.strftime("%Y-%m-%d %H:%M:%S"),
            "cutoff_end": future_cutoff.strftime("%Y-%m-%d %H:%M:%S")
        },
        "records": records
    }

    # 写入固定文件名（不加时间戳，直接覆盖）
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)
    
    print(f"\n✅ 分析完成！共处理 {processed_count} 场比赛")
    print(f"   跳过过去比赛: {skipped_past} 场")
    print(f"   输出文件: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
