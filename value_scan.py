#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
value_scan.py ——「一键分析 · 有价值场次汇总」独立算法版（Python 实现）

功能：
  复现 match_analysis_template.html 中「一键分析全部」的算法逻辑：
    1. 从官方盘口数据 his_data.js 加载 RAW_DATA / FOLDERS / SCORE_DATA_*
    2. 对每场可做 Poisson 模型的比赛，反推主客队 λ，计算总进球/净胜球分布
    3. 计算 胜平负(1X2) / 大小球(OU) / 让球(AH) 三类的 EV 与 Kelly
    4. 提取存在正 EV 的「最优价值玩法」，记录盘口
    5. 按开赛时间从早到晚排序，输出 CSV 到 ../../xml/scripts/docs/

数据桥接：his_data.js 是 JS 文件，Python 不便直接解析，故用 node 子进程
          把所需数据 dump 成 JSON 后，由本脚本完成全部分析（算法纯 Python）。

用法：python value_scan.py
依赖：node（探测顺序：环境变量 WORKBUDDY_NODE > PATH 上的 node > WorkBuddy 内置路径）
可配置环境变量：
  HIS_DATA  盘口数据文件 his_data.js 的路径（默认：脚本同目录或 ../../xml/scripts/docs/）
  OUT_CSV   输出 CSV 的完整路径（默认：脚本同目录 value_matches.csv）
适用于本地运行与 GitHub Actions 等 CI 环境（Linux/macOS 运行器）。
"""

import json
import math
import os
import csv
import subprocess
import sys
import shutil

# ---------------- 路径配置（本地 / CI 通用，均可用环境变量覆盖） ----------------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def _resolve_node():
    """node 可执行文件探测顺序：
    环境变量 WORKBUDDY_NODE  >  PATH 上的 node  >  本机 WorkBuddy 内置（兜底，保持本地原行为）
    CI（Linux/macOS）上 PATH 里的 node 会被优先命中；本机 Windows 若无 node on PATH 则回退内置路径。
    """
    return (os.environ.get("WORKBUDDY_NODE")
            or shutil.which("node")
            or r"C:\Users\52483\.workbuddy\binaries\node\versions\22.22.2\node.exe")


def _resolve_his_data():
    """数据文件 his_data.js 解析顺序：
    环境变量 HIS_DATA
      > 旧布局 ../../xml/scripts/docs/his_data.js（本机正式数据）
      > 仓库常见布局 scripts/docs/his_data.js（与脚本同级的 scripts/docs 下）
      > 脚本同目录
    注：脚本同目录若也有一份 his_data.js（多为旧副本），不会优先于官方数据目录。
    """
    env = os.environ.get("HIS_DATA")
    if env:
        return env
    candidates = [
        os.path.normpath(os.path.join(SCRIPT_DIR, "..", "..", "xml", "scripts", "docs", "his_data.js")),
        os.path.join(SCRIPT_DIR, "scripts", "docs", "his_data.js"),
        os.path.join(SCRIPT_DIR, "his_data.js"),
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return candidates[0]


def _resolve_out_csv(his_data):
    """输出 CSV 解析：环境变量 OUT_CSV  >  与数据文件同目录的 value_matches.csv
    （默认落到数据文件旁边，既还原本机行为，也便于 CI 提交/取回产物）
    """
    env = os.environ.get("OUT_CSV")
    if env:
        return env
    return os.path.join(os.path.dirname(os.path.abspath(his_data)), "value_matches.csv")


NODE = _resolve_node()
HIS_DATA = _resolve_his_data()
OUT_CSV = _resolve_out_csv(HIS_DATA)
OUT_DIR = os.path.dirname(os.path.abspath(OUT_CSV))


# =====================================================================
# 1. 泊松模型基础
# =====================================================================
def poisson_pmf(lam, k):
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    lp = -lam + k * math.log(lam)
    for i in range(2, k + 1):
        lp -= math.log(i)
    return math.exp(lp)


def fair_probs(odds):
    inv = [1.0 / max(float(o), 0.01) for o in odds]
    margin = sum(inv)
    return [p / margin for p in inv]


def model_probs(lam):
    arr = [poisson_pmf(lam, k) for k in range(0, 7)]  # P(0)..P(6)
    s = sum(arr)
    arr.append(max(0.0, 1.0 - s))                      # P(>=6) 放在 index 6
    return arr


def objective_single(lam, odds):
    fp = fair_probs(odds)        # 6 桶
    mp = model_probs(lam)        # 8 元素：P(0)..P(6), P(>=7)
    # 第 6 桶 = P(>=5) = mp[5]+mp[6]+mp[7]（mp.slice(5) 含索引 5,6,7）
    mp6 = [mp[0], mp[1], mp[2], mp[3], mp[4], mp[5] + mp[6] + mp[7]]
    return sum((mp6[i] - fp[i]) ** 2 for i in range(6))


def optimize_lambda(odds):
    """网格粗搜 + 黄金分割精修，等价 stats.js optimizeLambdaSingle"""
    best_lam, best_val = 1.0, float("inf")
    lam = 0.1
    while lam <= 6.0 + 1e-9:
        v = objective_single(lam, odds)
        if v < best_val:
            best_val, best_lam = v, lam
        lam += 0.01
    a = max(0.05, best_lam - 0.5)
    b = best_lam + 0.5
    phi = (math.sqrt(5) - 1) / 2
    c = b - phi * (b - a)
    d = a + phi * (b - a)
    fc = objective_single(c, odds)
    fd = objective_single(d, odds)
    for _ in range(50):
        if abs(b - a) < 1e-10:
            break
        if fc < fd:
            b, d, fd = d, c, fc
            c = b - phi * (b - a)
            fc = objective_single(c, odds)
        else:
            a, c, fc = c, d, fd
            d = a + phi * (b - a)
            fd = objective_single(d, odds)
    return (a + b) / 2


def calc_tg(lam_h, lam_a):
    """总进球分布 tg[0..7]，tg[7]=P(>=7)"""
    max_k = 25
    ph = [poisson_pmf(lam_h, k) for k in range(max_k + 1)]
    pa = [poisson_pmf(lam_a, k) for k in range(max_k + 1)]
    tg = [0.0] * 8
    for t in range(0, 7):
        p = sum(ph[i] * pa[t - i] for i in range(0, t + 1))
        tg[t] = p
    sum06 = sum(tg[0:7])
    tg[7] = max(0.0, 1.0 - sum06)
    return tg


def calc_gd(lam_h, lam_a):
    """净胜球分布（9 桶）：[-inf,-4],[-3],[-2],[-1],[0],[1],[2],[3],[4,inf]"""
    max_k = 25
    ph = [poisson_pmf(lam_h, k) for k in range(max_k + 1)]
    pa = [poisson_pmf(lam_a, k) for k in range(max_k + 1)]
    diff = {}
    for d in range(-max_k, max_k + 1):
        p = 0.0
        if d >= 0:
            for i in range(d, max_k + 1):
                p += ph[i] * pa[i - d]
        else:
            da = -d
            for i in range(0, max_k - da + 1):
                p += ph[i] * pa[i + da]
        if p > 1e-12:
            diff[d] = p
    bucket_ranges = [(-max_k, -4), (-3, -3), (-2, -2), (-1, -1), (0, 0),
                     (1, 1), (2, 2), (3, 3), (4, max_k)]
    return [sum(diff.get(d, 0.0) for d in range(lo, hi + 1)) for (lo, hi) in bucket_ranges]


# =====================================================================
# 2. 价值计算
# =====================================================================
def kelly(p, odds):
    ev = p * odds - 1
    if ev <= 0:
        return 0.0
    return min(0.25, ev / (odds - 1))


def _sum_tg(tg, a, b):
    return sum(tg[g] for g in range(a, b + 1) if g < len(tg))


def compute_ou(tg, line, oo, uo):
    """大小球 EV + 归一化模型概率（等价模板 computeOu）"""
    k = math.floor(line)
    frac = round((line - k) * 100) / 100
    p_over = p_under = push = 0.0
    ev_over = ev_under = 0.0
    if abs(frac - 0.5) < 0.01:
        f = _sum_tg(tg, k + 1, 7)
        p_over, p_under = f, 1 - f
        ev_over = f * (oo - 1) - (1 - f)
        ev_under = (1 - f) * (uo - 1) - f
    elif abs(frac) < 0.01:  # 整数盘，存在走水
        f = _sum_tg(tg, k + 1, 7)
        u = _sum_tg(tg, 0, k - 1)
        p_over, p_under = f, u
        push = tg[k] if k < len(tg) else 0.0
        ev_over = f * (oo - 1) - u
        ev_under = u * (uo - 1) - f
    elif abs(frac - 0.25) < 0.01:
        f = _sum_tg(tg, k + 1, 7)
        hl = tg[k] if k < len(tg) else 0.0
        lo = _sum_tg(tg, 0, k - 1)
        p_over, p_under = f + 0.5 * hl, lo + 0.5 * hl
        ev_over = f * (oo - 1) + hl * (-0.5) - lo
        ev_under = lo * (uo - 1) + hl * (0.5 * (uo - 1)) - f
    elif abs(frac - 0.75) < 0.01:
        f = _sum_tg(tg, k + 2, 7)
        hw = tg[k + 1] if k + 1 < len(tg) else 0.0
        lo = _sum_tg(tg, 0, k)
        p_over, p_under = f + 0.5 * hw, lo + 0.5 * hw
        ev_over = f * (oo - 1) + hw * (0.5 * (oo - 1)) - lo
        ev_under = lo * (uo - 1) + hw * (-0.5) - f
    else:
        f = _sum_tg(tg, k + 1, 7)
        p_over, p_under = f, 1 - f
        ev_over = f * (oo - 1) - (1 - f)
        ev_under = (1 - f) * (uo - 1) - f
    s = p_over + p_under
    if s > 0:
        p_over /= s
        p_under /= s
    m = 1.0 / oo + 1.0 / uo
    return {
        "line": line, "oo": oo, "uo": uo,
        "modelOver": p_over, "modelUnder": p_under, "push": push,
        "evOver": ev_over, "evUnder": ev_under,
        "kOver": kelly(p_over, oo), "kUnder": kelly(p_under, uo),
        "fairOver": (1.0 / oo) / m, "fairUnder": (1.0 / uo) / m, "margin": m,
    }


def calc_asian_ev_for_gd(handicap, home_odds, away_odds, gd):
    """让球 EV（等价 stats.calcAsianEVForGD）"""
    gd_values = [-4, -3, -2, -1, 0, 1, 2, 3, 4]
    pHomeWin = pHomeHalf = pPush = pAwayHalf = pAwayWin = 0.0
    for i, g in enumerate(gd_values):
        I = g + handicap
        prob = gd[i]
        if I >= 0.5:
            pHomeWin += prob
        elif I >= 0.25 and I < 0.5:
            if abs(I - 0.25) < 1e-6:
                pHomeHalf += prob
            else:
                pHomeWin += prob
        elif abs(I) < 1e-6:
            pPush += prob
        elif I <= -0.5:
            pAwayWin += prob
        elif I <= -0.25 and I > -0.5:
            if abs(I + 0.25) < 1e-6:
                pAwayHalf += prob
            else:
                pAwayWin += prob
    ev_home = (pHomeWin * (home_odds - 1) + pHomeHalf * ((home_odds - 1) / 2)
               + pPush * 0 + pAwayHalf * (-0.5) + pAwayWin * (-1))
    ev_away = (pAwayWin * (away_odds - 1) + pAwayHalf * ((away_odds - 1) / 2)
               + pPush * 0 + pHomeHalf * (-0.5) + pHomeWin * (-1))
    fair_home = (1.0 / home_odds) / (1.0 / home_odds + 1.0 / away_odds)
    fair_away = (1.0 / away_odds) / (1.0 / home_odds + 1.0 / away_odds)
    return ev_home, ev_away, fair_home, fair_away


def _js_remainder(a, b):
    """JS 风格余数（向零截断），等价于 JS 的 a % b"""
    return a - b * math.trunc(a / b)


def _is_quarter(h):
    r = round(h * 4)
    return abs(h * 4 - r) < 0.01 and (_js_remainder(r, 2) == 1)


def _gd_win_prob(gd, h):
    p = 0.0
    for i in range(len(gd)):
        d = i - 4
        if d > -h + 1e-9:
            p += gd[i]
    return p


def _gd_lose_prob(gd, h):
    p = 0.0
    for i in range(len(gd)):
        d = i - 4
        if d < -h - 1e-9:
            p += gd[i]
    return p


def ah_model_probs(gd, h):
    """让球归一化模型概率（等价模板 ahModelProbs）"""
    if _is_quarter(h):
        home = 0.5 * _gd_win_prob(gd, h + 0.25) + 0.5 * _gd_win_prob(gd, h - 0.25)
        away = 0.5 * _gd_lose_prob(gd, h + 0.25) + 0.5 * _gd_lose_prob(gd, h - 0.25)
        push = 0.0
    else:
        home = _gd_win_prob(gd, h)
        away = _gd_lose_prob(gd, h)
        push = 1.0 - home - away
    if home + away > 0:
        s = home + away
        home /= s
        away /= s
    return home, away, push


# =====================================================================
# 3. 单场分析
# =====================================================================
def analyze_match(rec):
    oc = rec.get("oc", {})
    ng = rec.get("ng") or {}
    ou = rec.get("ou") or {}
    win = rec.get("win") or {}
    wdw = rec.get("wdw") or {}
    if not ng.get("h1"):
        return None
    h_odds = [float(ng["h%d" % i]) for i in range(1, 7)]
    a_odds = [float(ng["a%d" % i]) for i in range(1, 7)]
    lam_h = optimize_lambda(h_odds)
    lam_a = optimize_lambda(a_odds)
    tg = calc_tg(lam_h, lam_a)
    gd = calc_gd(lam_h, lam_a)

    home_win = gd[5] + gd[6] + gd[7] + gd[8]
    draw = gd[4]
    away_win = gd[0] + gd[1] + gd[2] + gd[3]

    if wdw.get("ho") is not None and wdw.get("do") is not None and wdw.get("ao") is not None:
        ho = float(wdw["ho"]); do = float(wdw["do"]); ao = float(wdw["ao"])
        ev_h = home_win * ho - 1
        ev_d = draw * do - 1
        ev_a = away_win * ao - 1
        wdw_res = {
            "evH": ev_h, "evD": ev_d, "evA": ev_a,
            "kH": kelly(home_win, ho), "kD": kelly(draw, do), "kA": kelly(away_win, ao),
        }
    else:
        # 缺 1X2 赔率：不参与正 EV 判定（等价模板中 NaN>0 为 false）
        wdw_res = {"evH": float("-inf"), "evD": float("-inf"), "evA": float("-inf"),
                   "kH": 0.0, "kD": 0.0, "kA": 0.0}

    ou_res = None
    if ou.get("oo") and ou.get("li"):
        line = float(ou["li"]) / 4.0
        ou_res = compute_ou(tg, line, float(ou["oo"]), float(ou["uo"]))

    ah_res = None
    if win.get("ho") and win.get("ao"):
        gg = float(win["gg"])
        hcap_raw = (gg - 1) / 4.0
        handicap = (-hcap_raw) if win["g"] == "H" else hcap_raw
        r = calc_asian_ev_for_gd(handicap, float(win["ho"]), float(win["ao"]), gd)
        home, away, push = ah_model_probs(gd, handicap)
        ah_res = {
            "handicap": handicap, "ho": float(win["ho"]), "ao": float(win["ao"]),
            "modelHomeEff": home, "modelAwayEff": away, "push": push,
            "evHome": r[0], "evAway": r[1], "fairHome": r[2], "fairAway": r[3],
            "kH": kelly(home, float(win["ho"])), "kA": kelly(away, float(win["ao"])),
        }

    return {
        "id": oc.get("id", ""), "league": oc.get("st", ""),
        "home": oc.get("sh", ""), "away": oc.get("sa", ""),
        "gameTime": oc.get("gt", ""),
        "lamH": lam_h, "lamA": lam_a, "tg": tg, "gd": gd,
        "wdw": wdw_res, "ou": ou_res, "ah": ah_res,
    }


def best_value(m):
    c = [
        ("胜平负-主胜", m["wdw"]["evH"], m["wdw"]["evH"] > 0),
        ("胜平负-平", m["wdw"]["evD"], m["wdw"]["evD"] > 0),
        ("胜平负-客胜", m["wdw"]["evA"], m["wdw"]["evA"] > 0),
    ]
    if m["ou"]:
        c.append(("大小球-大", m["ou"]["evOver"], m["ou"]["evOver"] > 0))
        c.append(("大小球-小", m["ou"]["evUnder"], m["ou"]["evUnder"] > 0))
    if m["ah"]:
        c.append(("让球-主", m["ah"]["evHome"], m["ah"]["evHome"] > 0))
        c.append(("让球-客", m["ah"]["evAway"], m["ah"]["evAway"] > 0))
    pos = [x for x in c if x[2]]
    pos.sort(key=lambda x: -x[1])
    return pos[0] if pos else None


def fmt_handicap(mkt, m):
    if mkt.startswith("胜平负"):
        return "胜平负"
    if mkt.startswith("大小球"):
        return ("%.2f" % m["ou"]["line"]).rstrip("0").rstrip(".") + "球"
    if mkt.startswith("让球"):
        h = m["ah"]["handicap"]
        magnitude = ("%.2f" % abs(h)).rstrip("0").rstrip(".")
        sign = "+" if h > 0 else ("-" if h < 0 else "")
        return sign + magnitude + "球"
    return "-"


def kelly_of(mkt, m):
    if mkt.startswith("胜平负"):
        if "主" in mkt:
            return m["wdw"]["kH"]
        if "平" in mkt:
            return m["wdw"]["kD"]
        return m["wdw"]["kA"]
    if mkt.startswith("大小球"):
        return m["ou"]["kOver"] if "大" in mkt else m["ou"]["kUnder"]
    if mkt.startswith("让球"):
        return m["ah"]["kH"] if "主" in mkt else m["ah"]["kA"]
    return 0.0


# =====================================================================
# 4. 数据加载（node 桥接）
# =====================================================================
def load_data(his_data_path):
    dump_js = (
        "const fs=require('fs');const vm=require('vm');"
        "const code=fs.readFileSync(process.argv[1],'utf8');"
        "const sb={};vm.createContext(sb);vm.runInContext(code,sb);"
        "const out={RAW_DATA:sb.RAW_DATA,FOLDERS:sb.FOLDERS};"
        "for(const k in sb){if(k.startsWith('SCORE_DATA_')&&Array.isArray(sb[k]))out[k]=sb[k];}"
        "process.stdout.write(Buffer.from(JSON.stringify(out),'utf8'));"
    )
    if not NODE or not (os.path.exists(NODE) or shutil.which(NODE)):
        sys.exit("未找到 node：请在 PATH 安装 node，或用环境变量 WORKBUDDY_NODE 指定其路径")
    try:
        res = subprocess.run([NODE, "-e", dump_js, his_data_path],
                             capture_output=True, check=True)
    except FileNotFoundError:
        sys.exit("node 不可执行（%s）：请检查路径或将其加入 PATH" % NODE)
    return json.loads(res.stdout.decode("utf-8"))


# =====================================================================
# 5. 主流程
# =====================================================================
def main():
    if not os.path.exists(HIS_DATA):
        sys.exit("未找到数据文件: " + HIS_DATA)
    data = load_data(HIS_DATA)
    raw = data["RAW_DATA"]
    folders = data["FOLDERS"]

    # 每场取最新快照（folder 名即时间戳，字符串序=时间序）
    records = {}
    for f in folders:
        mm = raw.get(f)
        if not mm:
            continue
        for mid, rec in mm.items():
            if mid not in records or f > records[mid][0]:
                records[mid] = (f, rec)

    # 比分索引
    score = {}
    for k in data:
        if k.startswith("SCORE_DATA_") and isinstance(data[k], list):
            for s in data[k]:
                key = s.get("homeTeam", "") + "|" + s.get("awayTeam", "")
                score[key] = s

    # 可分析场次（按开赛时间升序）
    all_ids = [mid for mid, (_, rec) in records.items()
               if (rec.get("oc") or {}).get("gt")]
    all_ids.sort(key=lambda mid: (records[mid][1].get("oc") or {}).get("gt", ""))

    rows = []
    scanned = 0
    for mid in all_ids:
        rec = records[mid][1]
        m = analyze_match(rec)
        if not m:
            continue
        scanned += 1
        bv = best_value(m)
        if not bv:
            continue
        mkt, ev, _ = bv
        sc = score.get(m["home"] + "|" + m["away"])
        actual = sc.get("score") if (sc and sc.get("scoreNote") == "完场") else "未完场"
        rows.append({
            "id": m["id"], "league": m["league"], "home": m["home"],
            "away": m["away"], "gameTime": m["gameTime"],
            "mkt": mkt, "handicap": fmt_handicap(mkt, m),
            "ev": ev, "k": kelly_of(mkt, m), "actual": actual,
        })

    # 按开赛时间从早到晚
    rows.sort(key=lambda r: r["gameTime"])

    os.makedirs(OUT_DIR, exist_ok=True)
    header = ["场次ID", "联赛", "主队", "客队", "开赛时间",
              "最优玩法", "盘口", "EV", "Kelly", "实际赛果"]
    with open(OUT_CSV, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        for r in rows:
            w.writerow([r["id"], r["league"], r["home"], r["away"], r["gameTime"],
                        r["mkt"], r["handicap"],
                        "%.2f%%" % (r["ev"] * 100), "%.2f%%" % (r["k"] * 100),
                        r["actual"]])

    print("扫描可分析场次: %d" % scanned)
    print("正 EV 价值场次: %d  ->  已写入 %s" % (len(rows), OUT_CSV))
    if rows:
        print("首场: %s %s  %s(%s) EV=%.2f%%" %
              (rows[0]["gameTime"], rows[0]["mkt"], rows[0]["handicap"],
               rows[0]["home"] + " vs " + rows[0]["away"], rows[0]["ev"] * 100))
        print("末场: %s %s  %s EV=%.2f%%" %
              (rows[-1]["gameTime"], rows[-1]["mkt"], rows[-1]["handicap"], rows[-1]["ev"] * 100))


if __name__ == "__main__":
    main()
