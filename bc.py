#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
bb.py - 足球比分分析脚本（Poisson λ 优化版）
功能：
1. 从 GitHub 加载 numberofgoals.xml、odds_config.xml、windrawwin.xml
2. 按 XML 原始顺序遍历比赛，处理比赛时间在 [当前时间-12小时, 当前时间+24小时] 的场次
3. 利用 goal_exact_calculator.html 的公平概率+Poisson λ 优化算法计算期望进球、胜平负概率、总进球分布
4. 输出结果到 data/analysis_output.json（可被 c.py 读取展示）
"""

import json
import math
import os
import datetime
from datetime import timezone, timedelta
import requests
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional, Tuple

# ================= 常量定义 =================
MAX_GOALS = 5                     # 最大进球数（赔率表定义，最后一项为5+）
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
PAST_HOURS = 24     # 过去12小时的比赛仍然处理
FUTURE_HOURS = 24   # 未来24小时的比赛全部处理


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


# ================= 泊松分布基础函数 =================
def poisson_pmf(lam: float, k: int) -> float:
    """泊松分布概率质量函数 P(X=k)"""
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    lp = -lam + k * math.log(lam)
    for i in range(2, k + 1):
        lp -= math.log(i)
    return math.exp(lp)


def poisson_cdf(lam: float, k: int) -> float:
    """泊松分布累积分布函数 P(X≤k)"""
    s = 0.0
    for i in range(k + 1):
        s += poisson_pmf(lam, i)
    return s


# ================= 赔率 → 公平概率（goal_exact_calculator.html 算法）=================
def fair_probs(odds: List[float]) -> List[float]:
    """
    赔率 → 公平概率（剔除庄家抽水）
    隐含概率 = 1/赔率，公平概率 = 隐含概率 / margin（所有隐含概率之和）
    与 goal_exact_calculator.html 中 fairProbs() 逻辑一致
    """
    implied = [1.0 / max(o, 0.01) for o in odds]
    margin = sum(implied)
    if margin <= 0:
        return [1.0 / len(odds)] * len(odds)
    return [p / margin for p in implied]


def model_probs(lam: float) -> List[float]:
    """
    Poisson(λ) 模型概率分布（用于后续总进球卷积）
    返回 8 个元素：[p(0), p(1), p(2), p(3), p(4), p(5), p(6), p(7+)]
    其中 p(7+) = 1 - CDF(6)
    注意：优化时使用的 6 类概率（0~4,5+）在 _objective 中重新组合
    """
    probs = [poisson_pmf(lam, k) for k in range(7)]  # 0..6
    tail = 1.0 - poisson_cdf(lam, 6)  # 7+
    probs.append(max(tail, 0.0))
    return probs


def _objective(lam: float, odds: List[float]) -> float:
    """
    优化目标函数：SSE = Σ (Poisson模型概率 − 公平概率)²
    赔率表包含 6 个类别：0球,1球,2球,3球,4球,5+球
    因此需要将模型概率重组为对应的 6 类：
        [P0, P1, P2, P3, P4, P(>=5)]
    与 goal_exact_calculator.html 中 objective() 完全一致
    """
    fp = fair_probs(odds)          # 6个公平概率
    mp_full = model_probs(lam)     # 8个模型概率 (0~6,7+)
    # 重组为 6 类
    mp6 = [
        mp_full[0],                # P(0)
        mp_full[1],                # P(1)
        mp_full[2],                # P(2)
        mp_full[3],                # P(3)
        mp_full[4],                # P(4)
        sum(mp_full[5:])           # P(5) + P(6) + P(7+) = P(>=5)
    ]
    return sum((m - f) ** 2 for m, f in zip(mp6, fp))


def optimize_lambda(odds: List[float]) -> Tuple[float, float]:
    """
    网格搜索 + 黄金分割精调 → 找到最优 λ（期望进球）
    与 goal_exact_calculator.html 中 optimize() 逻辑一致

    参数:
        odds: 6个进球赔率 [0球, 1球, 2球, 3球, 4球, 5+球]

    返回:
        (最优λ, SSE)
    """
    # 网格搜索
    best_lam = 1.0
    best_val = float('inf')
    lam = 0.1
    while lam <= 6.0:
        v = _objective(lam, odds)
        if v < best_val:
            best_val = v
            best_lam = lam
        lam += 0.01

    # 黄金分割精调
    phi = (math.sqrt(5) - 1) / 2
    a = max(0.05, best_lam - 0.5)
    b = best_lam + 0.5
    c = b - phi * (b - a)
    d = a + phi * (b - a)
    fc = _objective(c, odds)
    fd = _objective(d, odds)

    for _ in range(50):
        if abs(b - a) < 1e-10:
            break
        if fc < fd:
            b = d
            d = c
            fd = fc
            c = b - phi * (b - a)
            fc = _objective(c, odds)
        else:
            a = c
            c = d
            fc = fd
            d = a + phi * (b - a)
            fd = _objective(d, odds)

    lam_opt = (a + b) / 2
    return lam_opt, _objective(lam_opt, odds)


# ================= 总进球分布 & 胜平负（泊松独立假设）=================
def calc_total_goals_and_wdl(home_probs: List[float], away_probs: List[float]) -> Dict:
    """
    主客队 Poisson 概率独立假设下，计算总进球分布和胜平负概率

    参数:
        home_probs: 主队进球概率 [p(0), ..., p(6), p(7+)]，共8个
        away_probs: 客队进球概率 [p(0), ..., p(6), p(7+)]，共8个

    返回:
        {
            'total_probs': {0: p, ..., 6: p},
            'prob_7plus': float,
            'home_win_prob': float,
            'draw_prob': float,
            'away_win_prob': float,
        }
    """
    n = len(home_probs)  # 8

    # 总进球分布 tg[0..6]
    tg = [0.0] * 7
    for total in range(7):
        prob = 0.0
        for i in range(min(total + 1, n)):
            j = total - i
            if 0 <= j < n:
                prob += home_probs[i] * away_probs[j]
        tg[total] = prob

    total_probs = {i: tg[i] for i in range(7)}
    prob_7plus = max(0.0, 1.0 - sum(tg))

    # 胜平负概率（独立泊松交叉）
    home_win_prob = 0.0
    draw_prob = 0.0
    away_win_prob = 0.0

    for i in range(n):
        for j in range(n):
            p = home_probs[i] * away_probs[j]
            if i > j:
                home_win_prob += p
            elif i == j:
                draw_prob += p
            else:
                away_win_prob += p

    return {
        'total_probs': total_probs,
        'prob_7plus': prob_7plus,
        'home_win_prob': home_win_prob,
        'draw_prob': draw_prob,
        'away_win_prob': away_win_prob,
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
    return "  ".join(parts)


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

        # 使用 Poisson λ 优化获取期望进球和Poisson概率分布
        home_odds, away_odds = loader.get_odds_for_match(match_id)
        exp_home, _ = optimize_lambda(home_odds)
        exp_away, _ = optimize_lambda(away_odds)
        home_probs = model_probs(exp_home)
        away_probs = model_probs(exp_away)

        # 计算总进球分布和胜平负概率
        dist = calc_total_goals_and_wdl(home_probs, away_probs)

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
            "主进球": f"{exp_home:.3f}",
            "客进球": f"{exp_away:.3f}",
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
