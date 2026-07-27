/**
 * stats.js - 纯计算模块（无 DOM 依赖）
 * 所有函数都是 pure，方便单测和复用
 */

const Stats = (function () {
  'use strict';

  // ===== 1. 赔率 → 公平概率（标准化到总和=1）=====
  function normalizeOdds(oddsArr) {
    const invs = [];
    let sumInv = 0;
    for (let i = 0; i < 6; i++) {
      const v = parseFloat(oddsArr[i]);
      const eff = isNaN(v) || v <= 0 ? 9999 : v;
      const inv = 1 / eff;
      invs.push(inv);
      sumInv += inv;
    }
    if (sumInv === 0) {
      return [1 / 6, 1 / 6, 1 / 6, 1 / 6, 1 / 6, 1 / 6];
    }
    const probs = invs.map((x) => x / sumInv);
    const s = probs.reduce((a, b) => a + b, 0);
    return probs.map((p) => p / s);
  }

  // ===== 2. 主客队各自进球分布 → 总进球分布 tg[0..6] + tg[7] = 7+ =====
  function calcTotalGoals(hp, ap) {
    const tg = [0, 0, 0, 0, 0, 0, 0, 0];
    tg[0] = (hp[0] || 0) * (ap[0] || 0);
    tg[1] = (hp[0] || 0) * (ap[1] || 0) + (hp[1] || 0) * (ap[0] || 0);
    tg[2] = (hp[0] || 0) * (ap[2] || 0) + (hp[1] || 0) * (ap[1] || 0) + (hp[2] || 0) * (ap[0] || 0);
    tg[3] = (hp[0] || 0) * (ap[3] || 0) + (hp[1] || 0) * (ap[2] || 0) +
            (hp[2] || 0) * (ap[1] || 0) + (hp[3] || 0) * (ap[0] || 0);
    tg[4] = (hp[0] || 0) * (ap[4] || 0) + (hp[1] || 0) * (ap[3] || 0) +
            (hp[2] || 0) * (ap[2] || 0) + (hp[3] || 0) * (ap[1] || 0) +
            (hp[4] || 0) * (ap[0] || 0);
    tg[5] = (hp[0] || 0) * (ap[5] || 0) + (hp[1] || 0) * (ap[4] || 0) +
            (hp[2] || 0) * (ap[3] || 0) + (hp[3] || 0) * (ap[2] || 0) +
            (hp[4] || 0) * (ap[1] || 0) + (hp[5] || 0) * (ap[0] || 0);
    tg[6] = (hp[1] || 0) * (ap[5] || 0) + (hp[2] || 0) * (ap[4] || 0) +
            (hp[3] || 0) * (ap[3] || 0) + (hp[4] || 0) * (ap[2] || 0) +
            (hp[5] || 0) * (ap[1] || 0);
    let sum06 = 0;
    for (let i = 0; i <= 6; i++) sum06 += tg[i];
    tg[7] = Math.max(0, 1 - sum06);
    return tg;
  }

  // ===== 3. 主客队各自进球分布 → 净胜球分布 (9 桶: -4以下到+4以上) =====
  function calcGoalDiff(hp, ap) {
    const hProb = [0, 0, 0, 0, 0, 0, 0];
    const aProb = [0, 0, 0, 0, 0, 0, 0];
    let sumH = 0, sumA = 0;
    for (let i = 0; i < 6; i++) {
      hProb[i + 1] = hp[i];
      aProb[i + 1] = ap[i];
      sumH += hp[i];
      sumA += ap[i];
    }
    hProb[0] = Math.max(0, 1 - sumH);
    aProb[0] = Math.max(0, 1 - sumA);

    const gd = new Array(13).fill(0);
    for (let hg = 0; hg <= 6; hg++) {
      for (let ag = 0; ag <= 6; ag++) {
        gd[hg - ag + 6] += hProb[hg] * aProb[ag];
      }
    }
    const result = new Array(9).fill(0);
    for (let d = -6; d <= 6; d++) {
      const val = gd[d + 6];
      if (d < -4) result[0] += val;
      else if (d > 4) result[8] += val;
      else result[d + 4] += val;
    }
    return result;
  }

  // ===== 4. 亚盘 EV (大小球) =====
  function calcAsianEV(handicap, overOdds, underOdds, totalProb) {
    const intPart = Math.floor(handicap);
    const frac = Math.round((handicap - intPart) * 100) / 100;
    let pOver = 0, pPush = 0, pUnder = 0;

    if (Math.abs(frac - 0.5) < 0.01) {
      for (let g = 0; g < 7; g++) if (g > handicap) pOver += totalProb[g];
      pOver += totalProb[7];
      pUnder = 1 - pOver;
    } else if (Math.abs(frac) < 0.01) {
      for (let g = 0; g < 7; g++) {
        if (g > handicap) pOver += totalProb[g];
        else if (Math.abs(g - handicap) < 0.01) pPush += totalProb[g];
      }
      pOver += totalProb[7];
      pUnder = 1 - pOver - pPush;
    } else if (Math.abs(frac - 0.25) < 0.01 || Math.abs(frac - 0.75) < 0.01) {
      const lo = frac < 0.5 ? intPart : intPart + 0.5;
      const hi = frac < 0.5 ? intPart + 0.5 : intPart + 1.0;
      const rL = calcAsianEV(lo, overOdds, underOdds, totalProb);
      const rH = calcAsianEV(hi, overOdds, underOdds, totalProb);
      return {
        evOver: (rL.evOver + rH.evOver) / 2,
        evUnder: (rL.evUnder + rH.evUnder) / 2,
        fairOver: ((rL.evOver + rH.evOver) / 2 + 1) / overOdds,
        fairUnder: ((rL.evUnder + rH.evUnder) / 2 + 1) / underOdds,
      };
    } else {
      for (let g = 0; g < 7; g++) if (g > handicap) pOver += totalProb[g];
      pOver += totalProb[7];
      pUnder = 1 - pOver;
    }

    const evOver = pOver * (overOdds - 1) - pUnder;
    const evUnder = pUnder * (underOdds - 1) - pOver;
    return {
      evOver, evUnder,
      fairOver: (evOver + 1) / overOdds,
      fairUnder: (evUnder + 1) / underOdds,
    };
  }

  // ===== 5. 亚盘 EV (让球/净胜球) =====
  function calcAsianEVForGD(handicap, homeOdds, awayOdds, gdProbs) {
    const gdValues = [-4, -3, -2, -1, 0, 1, 2, 3, 4];
    let pHomeWin = 0, pHomeHalf = 0, pPush = 0, pAwayHalf = 0, pAwayWin = 0;

    for (let i = 0; i < gdValues.length; i++) {
      const g = gdValues[i];
      const I = g + handicap;
      const prob = gdProbs[i];
      if (I >= 0.5) {
        pHomeWin += prob;
      } else if (I >= 0.25 && I < 0.5) {
        if (Math.abs(I - 0.25) < 1e-6) pHomeHalf += prob;
        else pHomeWin += prob;
      } else if (Math.abs(I) < 1e-6) {
        pPush += prob;
      } else if (I <= -0.5) {
        pAwayWin += prob;
      } else if (I <= -0.25 && I > -0.5) {
        if (Math.abs(I + 0.25) < 1e-6) pAwayHalf += prob;
        else pAwayWin += prob;
      }
    }

    const evHome = pHomeWin * (homeOdds - 1) + pHomeHalf * ((homeOdds - 1) / 2) +
                   pPush * 0 + pAwayHalf * (-0.5) + pAwayWin * (-1);
    const evAway = pAwayWin * (awayOdds - 1) + pAwayHalf * ((awayOdds - 1) / 2) +
                   pPush * 0 + pHomeHalf * (-0.5) + pHomeWin * (-1);

    return {
      evHome, evAway,
      fairHome: (evHome + 1) / homeOdds,
      fairAway: (evAway + 1) / awayOdds,
    };
  }

  // ===== 6. 时间相关工具 =====
  function parseFileTimestamp(folderName) {
    const parts = folderName.split('_');
    if (parts.length !== 2) return null;
    const [dateStr, timeStr] = parts;
    if (dateStr.length !== 8) return null;
    const y = parseInt(dateStr.substring(0, 4), 10);
    const m = parseInt(dateStr.substring(4, 6), 10) - 1;
    const d = parseInt(dateStr.substring(6, 8), 10);
    const h = parseInt(timeStr.substring(0, 2), 10);
    const mi = parseInt(timeStr.substring(2, 4), 10);
    const s = parseInt(timeStr.substring(4, 6), 10);
    return new Date(y, m, d, h, mi, s);
  }

  function parseMatchTime(matchTimeStr) {
    if (!matchTimeStr) return null;
    const parts = matchTimeStr.trim().split(' ');
    if (parts.length < 2) return null;
    const [dateStr, timeStr] = parts;
    if (dateStr.length !== 8) return null;
    const y = parseInt(dateStr.substring(0, 4), 10);
    const m = parseInt(dateStr.substring(4, 6), 10) - 1;
    const d = parseInt(dateStr.substring(6, 8), 10);
    const tParts = timeStr.split(':');
    const h = parseInt(tParts[0], 10);
    const mi = parseInt(tParts[1], 10);
    const s = tParts[2] ? parseInt(tParts[2], 10) : 0;
    return new Date(y, m, d, h, mi, s);
  }

  function getTimeStatus(folderName, matchTimeStr) {
    const fileTime = parseFileTimestamp(folderName);
    const matchTime = parseMatchTime(matchTimeStr);
    if (!fileTime || !matchTime) return null;
    return fileTime < matchTime ? 'before' : 'after';
  }

  // ===== 7. 泊松分布基础 =====
  function poissonPmf(lam, k) {
    if (lam <= 0) return k === 0 ? 1 : 0;
    let lp = -lam + k * Math.log(lam);
    for (let i = 2; i <= k; i++) lp -= Math.log(i);
    return Math.exp(lp);
  }

  function poissonCdf(lam, k) {
    let s = 0;
    for (let i = 0; i <= k; i++) s += poissonPmf(lam, i);
    return s;
  }

  function pAtLeast(lam, k) { return 1 - poissonCdf(lam, k - 1); }
  function pAtMost(lam, k) { return poissonCdf(lam, k); }

  // ===== 8. 盘口类型识别 =====
  function detectType(line) {
    const d = Math.round((Math.abs(line) % 1) * 100) / 100;
    if (d === 0.5) return 'half';
    if (d === 0) return 'integer';
    if (d === 0.25 || d === 0.75) return 'quarter';
    return null;
  }

  // ===== 9. OU 单变量泊松：盘口 → 命中概率 [over, under] =====
  function halfProbs(lam, line) {
    return [pAtLeast(lam, Math.round(line + 0.5)), pAtMost(lam, Math.round(line - 0.5))];
  }
  function intProbs(lam, line) {
    return [pAtLeast(lam, Math.round(line + 1)), pAtMost(lam, Math.round(line - 1))];
  }
  function qtrProbs(lam, line) {
    const lo = line - 0.25, hi = line + 0.25;
    const lt = detectType(lo), ht = detectType(hi);
    const pLo = lt === 'half' ? halfProbs(lam, lo) : intProbs(lam, lo);
    const pHi = ht === 'half' ? halfProbs(lam, hi) : intProbs(lam, hi);
    return [0.5 * pLo[0] + 0.5 * pHi[0], 0.5 * pLo[1] + 0.5 * pHi[1]];
  }
  function lineProbsRaw(lam, line) {
    const t = detectType(line);
    if (t === 'half') return halfProbs(lam, line);
    if (t === 'integer') return intProbs(lam, line);
    return qtrProbs(lam, line);
  }
  function lineProbsNorm(lam, line) {
    const r = lineProbsRaw(lam, line);
    const total = r[0] + r[1];
    return total > 0 ? [r[0] / total, r[1] / total] : [0.5, 0.5];
  }

  // ===== 10. Win 双变量泊松：净胜球分布 =====
  const WIN_MAX_G = 25;

  function goalDiff(lamH, lamA) {
    const ph = [], pa = [];
    for (let i = 0; i <= WIN_MAX_G; i++) {
      ph.push(poissonPmf(lamH, i));
      pa.push(poissonPmf(lamA, i));
    }
    const probs = {};
    for (let d = -WIN_MAX_G; d <= WIN_MAX_G; d++) {
      let p = 0;
      if (d >= 0) {
        for (let i = 0; i <= WIN_MAX_G - d; i++) p += ph[i + d] * pa[i];
      } else {
        const da = -d;
        for (let i = 0; i <= WIN_MAX_G - da; i++) p += ph[i] * pa[i + da];
      }
      if (p > 1e-12) probs[d] = p;
    }
    return probs;
  }

  function diffSum(probs, lo, hi) {
    let s = 0;
    for (let d = lo; d <= hi; d++) s += probs[d] || 0;
    return s;
  }

  function winHalfProbs(diff, line) {
    const th = Math.round(-line + 0.5);
    const ta = Math.round(-line - 0.5);
    let home = 0, away = 0;
    for (let d = th; d <= WIN_MAX_G; d++) home += diff[d] || 0;
    for (let d = -WIN_MAX_G; d <= ta; d++) away += diff[d] || 0;
    return [home, away];
  }

  function winIntProbs(diff, line) {
    const push = Math.round(-line);
    const th = push + 1, ta = push - 1;
    let home = 0, away = 0;
    for (let d = th; d <= WIN_MAX_G; d++) home += diff[d] || 0;
    for (let d = -WIN_MAX_G; d <= ta; d++) away += diff[d] || 0;
    return [home, away];
  }

  function winQtrProbs(diff, line) {
    const lo = line - 0.25, hi = line + 0.25;
    const lt = detectType(lo), ht = detectType(hi);
    const pLo = lt === 'half' ? winHalfProbs(diff, lo) : winIntProbs(diff, lo);
    const pHi = ht === 'half' ? winHalfProbs(diff, hi) : winIntProbs(diff, hi);
    return [0.5 * pLo[0] + 0.5 * pHi[0], 0.5 * pLo[1] + 0.5 * pHi[1]];
  }

  function winLineRaw(diff, line) {
    const t = detectType(line);
    if (t === 'half') return winHalfProbs(diff, line);
    if (t === 'integer') return winIntProbs(diff, line);
    return winQtrProbs(diff, line);
  }

  function winLineNorm(diff, line) {
    const r = winLineRaw(diff, line);
    const total = r[0] + r[1];
    return total > 0 ? [r[0] / total, r[1] / total] : [0.5, 0.5];
  }

  // ===== 11. 公平概率（两家赔率反推）=====
  function fairProb(o1, o2) {
    const m = 1 / o1 + 1 / o2;
    return [(1 / o1) / m, (1 / o2) / m];
  }

  // ===== 12. OU 优化：找最优 λ（黄金分割 + 网格扫描）=====
  function poissonObjective(lam, lines) {
    let total = 0;
    for (const lv in lines) {
      const od = lines[lv];
      const fp = fairProb(od.over, od.under);
      const mp = lineProbsNorm(lam, parseFloat(lv));
      total += (mp[0] - fp[0]) * (mp[0] - fp[0]) + (mp[1] - fp[1]) * (mp[1] - fp[1]);
    }
    return total;
  }

  function optimizePoisson(lines) {
    let best = 2.5, bestV = Infinity;
    for (let lam = 0.3; lam <= 8.0; lam += 0.01) {
      const v = poissonObjective(lam, lines);
      if (v < bestV) { bestV = v; best = lam; }
    }
    let a = Math.max(0.1, best - 0.5), b = best + 0.5;
    const phi = (Math.sqrt(5) - 1) / 2;
    let c = b - phi * (b - a), d = a + phi * (b - a);
    let fc = poissonObjective(c, lines), fd = poissonObjective(d, lines);
    for (let i = 0; i < 50; i++) {
      if (Math.abs(b - a) < 1e-10) break;
      if (fc < fd) { b = d; d = c; fd = fc; c = b - phi * (b - a); fc = poissonObjective(c, lines); }
      else { a = c; c = d; fc = fd; d = a + phi * (b - a); fd = poissonObjective(d, lines); }
    }
    const lam = (a + b) / 2;
    return { lam, sse: poissonObjective(lam, lines) };
  }

  // ===== 13. Win 优化：双变量（网格 + Nelder-Mead）=====
  function winObjective(lamH, lamA, lines) {
    if (lamH <= 0 || lamA <= 0) return 1e10;
    const diff = goalDiff(lamH, lamA);
    let total = 0;
    for (const lv in lines) {
      const od = lines[lv];
      const fp = fairProb(od.home, od.away);
      const mp = winLineNorm(diff, parseFloat(lv));
      total += (mp[0] - fp[0]) * (mp[0] - fp[0]) + (mp[1] - fp[1]) * (mp[1] - fp[1]);
    }
    return total;
  }

  function nelderMead(lines, maxIter = 200) {
    let simplex = [[1.5, 1.5], [2.5, 1.5], [1.5, 2.5]];
    let fvals = [
      winObjective(simplex[0][0], simplex[0][1], lines),
      winObjective(simplex[1][0], simplex[1][1], lines),
      winObjective(simplex[2][0], simplex[2][1], lines),
    ];
    const alpha = 1, gamma = 2, rho = 0.5, sigma = 0.5;
    for (let iter = 0; iter < maxIter; iter++) {
      const idx = [0, 1, 2].sort((a, b) => fvals[a] - fvals[b]);
      simplex = [simplex[idx[0]], simplex[idx[1]], simplex[idx[2]]];
      fvals = [fvals[idx[0]], fvals[idx[1]], fvals[idx[2]]];
      const std = Math.sqrt(((fvals[1] - fvals[0]) ** 2 + (fvals[2] - fvals[0]) ** 2) / 3);
      if (std < 1e-12) break;
      const x0 = [(simplex[0][0] + simplex[1][0]) / 2, (simplex[0][1] + simplex[1][1]) / 2];
      const xr = [x0[0] + alpha * (x0[0] - simplex[2][0]), x0[1] + alpha * (x0[1] - simplex[2][1])];
      const fr = winObjective(xr[0], xr[1], lines);
      if (fr >= fvals[0] && fr < fvals[1]) {
        simplex[2] = xr; fvals[2] = fr;
      } else if (fr < fvals[0]) {
        const xe = [x0[0] + gamma * (xr[0] - x0[0]), x0[1] + gamma * (xr[1] - x0[1])];
        const fe = winObjective(xe[0], xe[1], lines);
        simplex[2] = fe < fr ? xe : xr;
        fvals[2] = Math.min(fe, fr);
      } else {
        const xc = [x0[0] + rho * (simplex[2][0] - x0[0]), x0[1] + rho * (simplex[2][1] - x0[1])];
        const fc = winObjective(xc[0], xc[1], lines);
        if (fc < fvals[2]) {
          simplex[2] = xc; fvals[2] = fc;
        } else {
          for (let si = 1; si < 3; si++) {
            simplex[si] = [
              simplex[0][0] + sigma * (simplex[si][0] - simplex[0][0]),
              simplex[0][1] + sigma * (simplex[si][1] - simplex[0][1]),
            ];
            fvals[si] = winObjective(simplex[si][0], simplex[si][1], lines);
          }
        }
      }
    }
    return { lamH: simplex[0][0], lamA: simplex[0][1], sse: fvals[0] };
  }

  function winOptimize(lines) {
    let best = { lamH: 1.5, lamA: 1.5, sse: Infinity };
    for (let lh = 0.3; lh <= 5.0; lh += 0.2) {
      for (let la = 0.3; la <= 5.0; la += 0.2) {
        const sse = winObjective(lh, la, lines);
        if (sse < best.sse) best = { lamH: lh, lamA: la, sse };
      }
    }
    const refined = nelderMead(lines);
    if (refined.sse < best.sse) best = refined;
    return best;
  }

  // ===== 14. 数据解析：把 ou/win raw 数据转换成泊松用的 lines =====
  function buildPoissonLines(ou) {
    const lines = {};
    if (ou.oo && ou.uo && ou.li) {
      const hc = parseFloat(ou.li) / 4;
      const ov = parseFloat(ou.oo);
      const un = parseFloat(ou.uo);
      if (!isNaN(hc) && !isNaN(ov) && !isNaN(un) && ov >= 1.01 && un >= 1.01) {
        lines[hc.toFixed(2)] = { over: ov, under: un };
      }
    }
    const hivStr = ou.hi_var || '';
    if (hivStr) {
      const segs = hivStr.split('#');
      const grpMap = {}, grpOrder = [];
      for (const seg of segs) {
        const parts = seg.trim().split(',');
        if (parts.length < 5) continue;
        const hv = parseFloat(parts[1]) / 4;
        const key = hv.toFixed(2);
        if (!grpMap[key]) { grpMap[key] = { over: '', under: '' }; grpOrder.push(key); }
        const dir = parts[4].trim().toUpperCase();
        const odds = parseFloat(parts[0]) / 1000;
        if (dir === 'H') grpMap[key].over = odds;
        else if (dir === 'L') grpMap[key].under = odds;
      }
      for (const hk of grpOrder) {
        const entry = grpMap[hk];
        if (entry.over && entry.under &&
            parseFloat(entry.over) >= 1.01 && parseFloat(entry.under) >= 1.01) {
          lines[hk] = { over: parseFloat(entry.over), under: parseFloat(entry.under) };
        }
      }
    }
    return lines;
  }

  function buildWinPoissonLines(win) {
    const lines = {};
    if (win.g && win.gg && win.ho && win.ao) {
      const gDir = win.g;
      const ggVal = parseFloat(win.gg);
      const hcapRaw = (ggVal - 1) / 4;
      const handicap = gDir === 'H' ? -hcapRaw : hcapRaw;
      const hv = parseFloat(win.ho);
      const av = parseFloat(win.ao);
      if (!isNaN(handicap) && !isNaN(hv) && !isNaN(av) && hv >= 1.01 && av >= 1.01) {
        lines[handicap.toFixed(2)] = { home: hv, away: av };
      }
    }
    const varStr = win.var || '';
    if (varStr) {
      const parts = varStr.split(',');
      for (let vi = 0; vi + 4 < parts.length; vi += 5) {
        const dir = parts[vi];
        const ggVal2 = parseFloat(parts[vi + 1]);
        const homeOdds = parseFloat(parts[vi + 2]);
        const awayOdds = parseFloat(parts[vi + 3]);
        const hcapRaw2 = (ggVal2 - 1) / 4;
        const hcap2 = dir === 'H' ? -hcapRaw2 : hcapRaw2;
        const key = hcap2.toFixed(2);
        if (!lines[key] && !isNaN(homeOdds) && !isNaN(awayOdds) &&
            homeOdds >= 1.01 && awayOdds >= 1.01) {
          lines[key] = { home: homeOdds, away: awayOdds };
        }
      }
    }
    return lines;
  }

  // ===== 15. 偏差计算 =====
  function computeDeviations(lam, lines) {
    const devs = {};
    for (const lv in lines) {
      const od = lines[lv];
      const fp = fairProb(od.over, od.under);
      const mp = lineProbsNorm(lam, parseFloat(lv));
      devs[lv] = {
        over: (mp[0] - fp[0]) * 100,
        under: (mp[1] - fp[1]) * 100,
      };
    }
    return devs;
  }

  function computeWinDeviations(lamH, lamA, lines) {
    const diff = goalDiff(lamH, lamA);
    const devs = {};
    for (const lv in lines) {
      const od = lines[lv];
      const fp = fairProb(od.home, od.away);
      const mp = winLineNorm(diff, parseFloat(lv));
      devs[lv] = {
        home: (mp[0] - fp[0]) * 100,
        away: (mp[1] - fp[1]) * 100,
      };
    }
    return devs;
  }

  // ===== 16. 总进球/净胜球分布（0..6 + 7+） =====
  function computePoissonTg(lam) {
    const tg = [];
    let sumP = 0;
    for (let k = 0; k <= 6; k++) {
      const pk = poissonPmf(lam, k);
      tg.push(pk);
      sumP += pk;
    }
    tg.push(Math.max(0, 1 - sumP));
    return tg;
  }

  function computeWinGoalDiffBins(lamH, lamA) {
    if (lamH === null || lamA === null) return null;
    const diff = goalDiff(lamH, lamA);
    const bucketRanges = [
      [-WIN_MAX_G, -4], [-3, -3], [-2, -2], [-1, -1], [0, 0],
      [1, 1], [2, 2], [3, 3], [4, WIN_MAX_G],
    ];
    return bucketRanges.map(([lo, hi]) => diffSum(diff, lo, hi));
  }

  // ===== 17. SSE 格式化 =====
  function formatSSE(sse) {
    if (sse === 0) return '0';
    const abs = Math.abs(sse);
    if (abs >= 0.001 && abs < 1000) return sse.toFixed(4);
    const exp = Math.floor(Math.log10(abs));
    const mantissa = sse / Math.pow(10, exp);
    return mantissa.toFixed(2) + 'e' + exp;
  }

  // ===== 新增：解析 hi_var / var 为结构化数据（供 UI 复用）=====
  function parseHiVarGroups(hivStr) {
    if (!hivStr) return [];
    const lines = hivStr.split('#');
    const grpMap = {}, grpOrder = [];
    for (const line of lines) {
      const parts = line.trim().split(',');
      if (parts.length < 5) continue;
      const hv = parseFloat(parts[1]) / 4;
      const key = hv.toFixed(2);
      if (!grpMap[key]) { grpMap[key] = { over: '', under: '' }; grpOrder.push(key); }
      const dir = parts[4].trim().toUpperCase();
      const odds = (parseFloat(parts[0]) / 1000).toFixed(2);
      if (dir === 'H') grpMap[key].over = odds;
      else if (dir === 'L') grpMap[key].under = odds;
    }
    return grpOrder.map((hk) => ({
      over: grpMap[hk].over, under: grpMap[hk].under, hcap: hk,
    }));
  }

  function parseWinVarGroup(str) {
    if (!str) return [];
    const parts = str.split(',');
    const groups = [];
    for (let i = 0; i + 4 < parts.length; i += 5) {
      const dir = parts[i];
      const ggVal = parseFloat(parts[i + 1]);
      const homeOdds = parts[i + 2];
      const awayOdds = parts[i + 3];
      const hcapRaw = (ggVal - 1) / 4;
      const handicap = (dir === 'H') ? -hcapRaw : hcapRaw;
      groups.push({ over: homeOdds, under: awayOdds, hcap: handicap.toFixed(2) });
    }
    return groups;
  }

  // ===== 18. 高层：分析一行（OU + Win 共用入口，避免重复计算）=====
  /**
   * 对一个 rec 做一次 hp/ap 归一化,同时算出 TG 和 GD。
   * 返回 { hp, ap, tgProbs, gdProbs, ouLines, ouResult, ouDevs, ouTg,
   *        winLines, winResult, winDevs, winGd,
   *        ouGroups, winGroups }  -- 新增预解析的盘口分组
   * 任何一步失败都不会抛错,出错字段返回 null。
   */
  function analyzeRow(rec) {
    const out = {
      hp: null, ap: null, tgProbs: null, gdProbs: null,
      ouLines: {}, ouResult: null, ouDevs: {}, ouTg: null, ouLam: null, ouSse: null,
      winLines: {}, winResult: null, winDevs: {}, winGd: null, winLamH: null, winLamA: null, winSse: null,
      ouGroups: [],   // 新增
      winGroups: [],  // 新增
    };
    if (!rec) return out;

    const ng = rec.ng || {};
    const ngCols = ['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'a1', 'a2', 'a3', 'a4', 'a5', 'a6'];
    const hasNg = ngCols.every((k) => ng[k] && parseFloat(ng[k]) > 0);
    if (hasNg) {
      const homeOdds = [ng.h1, ng.h2, ng.h3, ng.h4, ng.h5, ng.h6];
      const awayOdds = [ng.a1, ng.a2, ng.a3, ng.a4, ng.a5, ng.a6];
      out.hp = normalizeOdds(homeOdds);
      out.ap = normalizeOdds(awayOdds);
      out.tgProbs = calcTotalGoals(out.hp, out.ap);
      out.gdProbs = calcGoalDiff(out.hp, out.ap);
    }

    // OU 泊松
    try {
      out.ouLines = buildPoissonLines(rec.ou || {});
      if (Object.keys(out.ouLines).length > 0) {
        const r = optimizePoisson(out.ouLines);
        out.ouLam = r.lam;
        out.ouSse = r.sse;
        out.ouTg = computePoissonTg(r.lam);
        out.ouDevs = computeDeviations(r.lam, out.ouLines);
        out.ouResult = r;
      }
    } catch (e) { /* ignore */ }

    // Win 泊松
    try {
      out.winLines = buildWinPoissonLines(rec.win || {});
      if (Object.keys(out.winLines).length > 0) {
        const r = winOptimize(out.winLines);
        out.winLamH = r.lamH;
        out.winLamA = r.lamA;
        out.winSse = r.sse;
        out.winGd = computeWinGoalDiffBins(r.lamH, r.lamA);
        out.winDevs = computeWinDeviations(r.lamH, r.lamA, out.winLines);
        out.winResult = r;
      }
    } catch (e) { /* ignore */ }

    // 预解析盘口分组（供 UI 直接使用）
    if (rec.ou) {
      out.ouGroups = parseHiVarGroups(rec.ou.hi_var || '');
    }
    if (rec.win) {
      out.winGroups = parseWinVarGroup(rec.win.var || '');
    }

    return out;
  }

  return {
    normalizeOdds, calcTotalGoals, calcGoalDiff,
    calcAsianEV, calcAsianEVForGD,
    parseFileTimestamp, parseMatchTime, getTimeStatus,
    poissonPmf, poissonCdf, pAtLeast, pAtMost,
    detectType,
    lineProbsRaw, lineProbsNorm,
    goalDiff, diffSum, winLineNorm,
    fairProb,
    poissonObjective, optimizePoisson,
    winObjective, winOptimize, nelderMead,
    buildPoissonLines, buildWinPoissonLines,
    computeDeviations, computeWinDeviations,
    computePoissonTg, computeWinGoalDiffBins,
    formatSSE,
    parseHiVarGroups, parseWinVarGroup, // 导出以便其他可能使用（但 app.js 可用 analyzeRow 返回的）
    analyzeRow, // 顶层入口
  };
})();