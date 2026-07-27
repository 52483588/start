#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
c.py - 足球比分分析展示应用（Streamlit）
功能：
- 读取 b.py 生成的 analysis_output.json 文件
- 展示比赛分析记录表，支持筛选、排序、导出 CSV
- 显示数据更新时间、模拟参数等统计信息
- 总进球概率分布以8列展示（0球~7+球）
- 胜赔付、平赔付、负赔付高于平均赔付时高亮显示（黄色背景+黑色加粗）
"""

import streamlit as st
import pandas as pd
import json
import os
import re
from datetime import datetime

# 页面配置
st.set_page_config(
    page_title="足球分析记录库",
    page_icon="⚽",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 数据文件目录
DATA_DIR = "data"

# 页面样式
st.markdown("""
<style>
    .main-header { font-size: 32px; font-weight: bold; color: #1F4E79; text-align: center; margin-bottom: 10px; }
    .sub-header { font-size: 20px; font-weight: 600; color: #2C3E50; margin-top: 15px; margin-bottom: 10px; border-bottom: 2px solid #e0e0e0; padding-bottom: 5px; }
    .metric-box { background-color: #f8f9fa; padding: 15px; border-radius: 8px; text-align: center; box-shadow: 0 2px 4px rgba(0,0,0,0.05); }
    .metric-value { font-size: 28px; font-weight: bold; color: #1F4E79; }
    .metric-label { font-size: 14px; color: #6c757d; }
</style>
""", unsafe_allow_html=True)


def parse_goal_probs(prob_str: str):
    """
    解析总进球概率分布字符串，返回一个字典，键为 '0球'~'7+球'，值为百分比字符串（如 '12.5%'）
    """
    default = {f"{g}球": "0.0%" for g in range(7)}
    default["7+球"] = "0.0%"
    if not prob_str or prob_str in ("待模拟", "无"):
        return default
    # 格式示例: "0:12.5% 1:15.2% 2:10.3% 3:8.2% 4:5.1% 5:3.0% 6:1.8% 7+:1.5%"
    parts = prob_str.split()
    result = default.copy()
    for part in parts:
        if ':' in part:
            key, val = part.split(':', 1)
            if key == '7+':
                result["7+球"] = val
            elif key.isdigit():
                result[f"{key}球"] = val
    return result


@st.cache_data(ttl=600)
def load_data():
    """加载 data/ 目录下所有 JSON 文件，合并 records 并展开总进球概率分布列；若无有效文件则返回 None"""
    if not os.path.isdir(DATA_DIR):
        return None
    json_files = sorted(
        [f for f in os.listdir(DATA_DIR) if f.endswith(".json")],
        key=lambda f: os.path.getmtime(os.path.join(DATA_DIR, f))
    )
    if not json_files:
        return None

    all_records = []
    latest_generated_at = ""
    total_processed = 0
    simulation_count = 0  # 注意 b.py 输出的是 n_sims，字段名可能不同，暂保留

    for fname in json_files:
        fpath = os.path.join(DATA_DIR, fname)
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                records = data.get("records", [])
                # 为每条记录解析总进球概率分布，添加8个新字段
                for rec in records:
                    prob_str = rec.get("轮次>10%", "")
                    probs = parse_goal_probs(prob_str)
                    for k, v in probs.items():
                        rec[k] = v
                all_records.extend(records)
                gen_at = data.get("generated_at", "")
                if gen_at > latest_generated_at:
                    latest_generated_at = gen_at
                    total_processed = data.get("total_processed", 0)
                    sim_params = data.get("simulation_params", {})
                    simulation_count = sim_params.get("n_sims", 0)
        except Exception as e:
            st.warning(f"读取文件 {fname} 失败: {e}")
            continue

    if not all_records:
        return None

    return {
        "generated_at": latest_generated_at,
        "total_processed": total_processed,
        "simulation_count": simulation_count,
        "records": all_records,
    }

def highlight_payout_style(df):
    """
    使用 pandas.DataFrame.style 实现条件格式化
    1. 胜概率、平概率、负概率三列中大于等于50%的单元格为红色背景
    2. 对胜赔付、平赔付、负赔付三列：
       - 赔付值 >= 平均赔付时：
         - 若对应概率 >= 50%，红色背景+黑色加粗
         - 若对应概率 < 50%，黄色背景+黑色加粗
       - 赔付值 < 平均赔付时：普通显示
    3. 对总进球概率列（0球~7+球），概率 >= 9.5% 的单元格为浅绿色背景+黑色加粗
    """
    styles = pd.DataFrame('', index=df.index, columns=df.columns)

    prob_payout_map = {
        '胜概率': '胜赔付',
        '平概率': '平赔付',
        '负概率': '负赔付'
    }

    # 1. 概率列高亮（≥50%）
    for prob_col in ['胜概率', '平概率', '负概率']:
        if prob_col in df.columns:
            try:
                prob_values = pd.to_numeric(df[prob_col].str.rstrip('%'), errors='coerce')
                mask = (prob_values >= 50) & (~prob_values.isna())
                styles.loc[mask, prob_col] = 'background-color: #ff0000; color: #ffffff; font-weight: bold;'
            except Exception:
                pass

    # 2. 赔付列高亮
    avg_col = '平均赔付'
    for prob_col, payout_col in prob_payout_map.items():
        if payout_col in df.columns and avg_col in df.columns:
            try:
                payout_values = pd.to_numeric(df[payout_col], errors='coerce')
                avg_values = pd.to_numeric(df[avg_col], errors='coerce')
                prob_values = pd.to_numeric(df[prob_col].str.rstrip('%'), errors='coerce')

                mask_ge = (payout_values >= avg_values) & (~payout_values.isna()) & (~avg_values.isna())
                mask_red = mask_ge & (prob_values >= 50) & (~prob_values.isna())
                mask_yellow = mask_ge & (prob_values < 50) & (~prob_values.isna())

                styles.loc[mask_red, payout_col] = 'background-color: #ff0000; color: #ffffff; font-weight: bold;'
                styles.loc[mask_yellow, payout_col] = 'background-color: #ffeb3b; color: #000000; font-weight: bold;'
            except Exception:
                pass

    # 3. 总进球概率列高亮（≥9.5%）
    score_cols = ["0球", "1球", "2球", "3球", "4球", "5球", "6球", "7+球"]
    for col in score_cols:
        if col in df.columns:
            try:
                # 将百分比字符串（如 "12.5%"）转为浮点数
                prob_vals = df[col].astype(str).str.rstrip('%').astype(float)
                mask = (prob_vals >= 9.5) & (~prob_vals.isna())
                styles.loc[mask, col] = 'background-color: #d4edda; color: #000000; font-weight: bold;'  # 浅绿色背景
            except Exception:
                pass

    return styles



def main():
    st.markdown('<p class="main-header">⚽ 足球分析记录库</p>', unsafe_allow_html=True)

    data = load_data()
    if data is None:
        st.warning(f"未找到 `{DATA_DIR}/` 目录下的 JSON 数据文件。请先运行 b.py 生成分析结果。")
        st.info("**b.py** 会从 GitHub 获取最新赔率并模拟生成数据，通常由 GitHub Actions 定时执行。")
        return

    stop_reason = data.get("stop_reason")
    if stop_reason:
        st.info(f"⏹️ 停止原因: {stop_reason}")

    records = data.get("records", [])
    if not records:
        st.info("暂无任何比赛记录。")
        return

    df = pd.DataFrame(records)

    # ========== 筛选与排序侧边栏 ==========
    st.sidebar.header("🔍 数据筛选")

    if st.sidebar.button("🔄 强制刷新数据（从文件重新加载）"):
        load_data.clear()
        st.rerun()

    if "赛事" in df.columns:
        leagues = sorted(df["赛事"].unique())
        selected_leagues = st.sidebar.multiselect(
            "选择联赛", options=leagues, default=leagues
        )
        if selected_leagues:
            df = df[df["赛事"].isin(selected_leagues)]

    search_term = st.sidebar.text_input("🔎 搜索主队/客队", value="")
    if search_term:
        mask = df["主队"].str.contains(search_term, case=False) | df["客队"].str.contains(search_term, case=False)
        df = df[mask]

    # 可排序的列：原有列 + 新增的8个概率列
    sort_options = ["记录时间", "胜概率", "平概率", "负概率", "胜赔付", "平赔付", "负赔付", "主进球", "客进球"]
    sort_options.extend([f"{g}球" for g in range(7)] + ["7+球"])

    sort_col = st.sidebar.selectbox("排序依据", options=sort_options)
    ascending = st.sidebar.checkbox("升序", value=False)

    # 排序逻辑
    df_sorted = df.copy()
    # 对于百分比列（包括新概率列），需要转换为数值排序
    if sort_col in ["胜概率", "平概率", "负概率"] + [f"{g}球" for g in range(7)] + ["7+球"]:
        # 统一处理：去掉百分号转浮点数
        df_sorted[sort_col + "_数值"] = df_sorted[sort_col].str.rstrip('%').astype(float)
        df_sorted = df_sorted.sort_values(sort_col + "_数值", ascending=ascending)
        df_sorted = df_sorted.drop(columns=[sort_col + "_数值"])
    elif sort_col in ["胜赔付", "平赔付", "负赔付", "主进球", "客进球"]:
        df_sorted[sort_col + "_数值"] = pd.to_numeric(df_sorted[sort_col], errors='coerce')
        df_sorted = df_sorted.sort_values(sort_col + "_数值", ascending=ascending)
        df_sorted = df_sorted.drop(columns=[sort_col + "_数值"])
    elif sort_col == "记录时间":
        df_sorted = df_sorted.sort_values(sort_col, ascending=ascending)

    # ========== 重新排列列顺序 ==========
    # 移除原始的总进球列（轮次>10%），替换为8个新列
    base_cols = ["时间", "赛事", "主队", "客队", "胜概率", "平概率", "负概率",
                 "主进球", "客进球", "胜赔付", "平赔付", "负赔付", "平均赔付"]
    goal_cols = [f"{g}球" for g in range(7)] + ["7+球"]
    other_cols = ["记录时间", "match_id"]  # match_id 可能不展示但保留
    # 过滤实际存在的列
    final_cols = [c for c in base_cols + goal_cols + other_cols if c in df_sorted.columns]
    df_sorted = df_sorted[final_cols]

    # ========== 应用高亮样式 ==========
    styled_df = df_sorted.style.apply(highlight_payout_style, axis=None)

    # ========== 结果展示 ==========
    st.markdown('<p class="sub-header">📋 比赛分析记录</p>', unsafe_allow_html=True)
    st.caption(f"当前显示 {len(df_sorted)} 条记录（共 {len(records)} 条）")
    st.caption(f"📅 最新数据生成时间: {data.get('generated_at', '未知')}  |  🎲 模拟次数: {data.get('simulation_count', 0):,}")

    # 配置列宽
    col_config = {
        "match_id": st.column_config.TextColumn("ID", width=60),
        "时间": st.column_config.TextColumn("时间", width=120),
        "赛事": st.column_config.TextColumn("赛事", width="auto"),
        "主队": st.column_config.TextColumn("主队", width="auto"),
        "客队": st.column_config.TextColumn("客队", width="auto"),
        "胜概率": st.column_config.TextColumn("胜概率", width=60),
        "平概率": st.column_config.TextColumn("平概率", width=60),
        "负概率": st.column_config.TextColumn("负概率", width=60),
        "主进球": st.column_config.TextColumn("主进球", width=60),
        "客进球": st.column_config.TextColumn("客进球", width=60),
        "胜赔付": st.column_config.TextColumn("胜赔付", width=60),
        "平赔付": st.column_config.TextColumn("平赔付", width=60),
        "负赔付": st.column_config.TextColumn("负赔付", width=60),
        "平均赔付": st.column_config.TextColumn("平均赔付", width=60),
        "记录时间": st.column_config.TextColumn("记录时间", width=120),
    }
    # 为8个概率列添加配置
    for g in range(7):
        col_config[f"{g}球"] = st.column_config.TextColumn(f"{g}球", width=55)
    col_config["7+球"] = st.column_config.TextColumn("7+球", width=55)

    st.dataframe(
        styled_df,
        use_container_width=True,
        hide_index=True,
        column_config=col_config
    )

    # ========== 简单统计 ==========
    with st.expander("📈 简单统计（基于当前筛选结果）"):
        col_win, col_draw, col_loss = st.columns(3)
        try:
            avg_home = df_sorted["胜概率"].str.rstrip('%').astype(float).mean()
            avg_draw = df_sorted["平概率"].str.rstrip('%').astype(float).mean()
            avg_away = df_sorted["负概率"].str.rstrip('%').astype(float).mean()
            with col_win:
                st.metric("平均主胜概率", f"{avg_home:.2f}%")
            with col_draw:
                st.metric("平均平局概率", f"{avg_draw:.2f}%")
            with col_loss:
                st.metric("平均客胜概率", f"{avg_away:.2f}%")
        except:
            st.info("无法计算平均值（数据格式问题）")

    # ========== 导出 CSV ==========
    csv_data = df_sorted.to_csv(index=False).encode('utf-8')
    st.download_button(
        label="📥 导出当前筛选结果为 CSV",
        data=csv_data,
        file_name=f"analysis_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
        mime="text/csv",
        use_container_width=True
    )


if __name__ == "__main__":
    main()
