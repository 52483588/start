/**
 * app.js - UI 逻辑（依赖 stats.js, his_data.js）
 * 只做：事件绑定、表格渲染、跨视图状态。
 * 不包含任何纯数学计算。
 */

(function () {
  'use strict';

  // ===== 立即显示 loading (his_data.js 同步解析期间的兜底) =====
  function injectEarlyLoading() {
    if (document.getElementById('appLoading')) return;
    const div = document.createElement('div');
    div.id = 'appLoading';
    div.style.cssText = 'position:fixed;inset:0;background:rgba(240,242,245,0.95);' +
      'display:flex;flex-direction:column;align-items:center;justify-content:center;z-index:9999;' +
      'font-family:"Microsoft YaHei",sans-serif;color:#1a3c6e;';
    div.innerHTML = '<style>@keyframes _wbSpin{to{transform:rotate(360deg)}}</style>' +
      '<div style="width:50px;height:50px;border:5px solid #c0c8d0;border-top-color:#2563a8;' +
      'border-radius:50%;animation:_wbSpin 0.9s linear infinite;margin-bottom:16px"></div>' +
      '<div style="font-size:15px;font-weight:600">正在加载历史数据...</div>' +
      '<div style="font-size:12px;color:#888;margin-top:4px">数据量较大，请稍候</div>';
    (document.body || document.documentElement).appendChild(div);
  }
  if (document.body) {
    injectEarlyLoading();
  } else {
    document.addEventListener('DOMContentLoaded', injectEarlyLoading);
  }

  // ===== 全局状态 =====
  const state = {
    DATA: (typeof RAW_DATA !== 'undefined') ? RAW_DATA : {},
    FOLDERS: (typeof FOLDERS !== 'undefined') ? FOLDERS : [],
    allLeagues: {},
    leagueNames: [],
    currentIdIndex: {},
    currentRows: [],
    currentMatchId: '',
    currentView: 'ou', // 'ou' | 'win'
    precomputed: [],   // [{folder, rec, analysis}]
  };

  // ===== DOM 引用 =====
  const $ = (id) => document.getElementById(id);
  const els = {
    leagueSelect: $('leagueSelect'),
    searchInput: $('searchInput'),
    autocomplete: $('autocomplete'),
    tableOu: $('tableOu'),
    tableWin: $('tableWin'),
    noResultOu: $('noResultOu'),
    noResultWin: $('noResultWin'),
    hintOu: $('hintOu'),
    hintWin: $('hintWin'),
    matchInfo: $('matchInfo'),
    infoId: $('infoId'),
    infoTime: $('infoTime'),
    infoLeague: $('infoLeague'),
    infoHome: $('infoHome'),
    infoAway: $('infoAway'),
    infoCount: $('infoCount'),
    legend: $('legend'),
    statusTip: $('statusTip'),
    btnSearch: $('btnSearch'),
    btnClear: $('btnClear'),
    btnOu: $('btnOu'),
    btnWin: $('btnWin'),
    btnOuReport: $('btnOuReport'),
    btnExportOu: null,
    btnExportWin: null,
    loading: null,
  };

  // ===== 工具：转义 HTML 防 XSS =====
  function esc(s) {
    if (s === null || s === undefined) return '';
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  // ===== 1. 启动：建联赛索引 =====
  function buildLeagueIndex() {
    const leagueSet = {};
    for (const folder of state.FOLDERS) {
      const fd = state.DATA[folder] || {};
      for (const id in fd) {
        const oc = (fd[id] && fd[id].oc) || {};
        if (!oc.st) continue;
        const ln = oc.st;
        if (!leagueSet[ln]) {
          leagueSet[ln] = {};
          state.leagueNames.push(ln);
        }
        if (!leagueSet[ln][id]) {
          leagueSet[ln][id] = {
            gt: oc.gt || '', st: oc.st || '',
            sh: oc.sh || '', sa: oc.sa || '',
          };
        }
      }
    }
    state.leagueNames.sort();
    state.allLeagues = leagueSet;
  }

  function populateLeagues() {
    const sel = els.leagueSelect;
    for (const ln of state.leagueNames) {
      const opt = document.createElement('option');
      opt.value = ln;
      opt.textContent = ln + ' (' + Object.keys(state.allLeagues[ln]).length + '场)';
      sel.appendChild(opt);
    }
  }

  function show(el) { if (el) el.hidden = false; }
  function hide(el) { if (el) el.hidden = true; }

  // ===== 2. 联赛切换 =====
  function onLeagueChange() {
    const selVal = els.leagueSelect.value;
    els.searchInput.value = '';
    els.autocomplete.hidden = true;
    els.tableOu.innerHTML = '';
    els.tableWin.innerHTML = '';
    hide(els.matchInfo);
    hide(els.noResultOu);
    hide(els.noResultWin);
    show(els.hintOu);
    show(els.hintWin);
    hide(els.legend);
    els.statusTip.textContent = '';
    hide(els.btnOuReport);
    hideExportButtons();

    if (!selVal) {
      state.currentIdIndex = {};
      els.searchInput.disabled = true;
      els.searchInput.placeholder = '先选择联赛，再输入/选择赛事ID或球队名';
      return;
    }
    els.searchInput.disabled = false;
    els.searchInput.placeholder = '输入ID或球队名搜索...';
    state.currentIdIndex = state.allLeagues[selVal] || {};
    els.statusTip.textContent = '当前联赛共 ' + Object.keys(state.currentIdIndex).length + ' 场比赛';
  }

  // ===== 3. Autocomplete =====
  function updateAutocomplete() {
    const q = els.searchInput.value.trim().toLowerCase();
    const leagueSel = els.leagueSelect.value;
    if (!leagueSel || !q) { els.autocomplete.hidden = true; return; }
    const matches = [];
    for (const id in state.currentIdIndex) {
      const info = state.currentIdIndex[id];
      const text = (id + ' ' + (info.sh || '') + ' ' + (info.sa || '') + ' ' + (info.gt || '')).toLowerCase();
      if (text.indexOf(q) !== -1) matches.push(id);
      if (matches.length >= 20) break;
    }
    if (!matches.length) { els.autocomplete.hidden = true; return; }

    const frag = document.createDocumentFragment();
    for (const id of matches) {
      const info = state.currentIdIndex[id];
      const hlInfo = info.sh ? (info.sh + ' vs ' + info.sa) : '';
      const timeStr = info.gt ? info.gt.substring(4, 6) + '/' + info.gt.substring(6, 8) : '';
      const div = document.createElement('div');
      div.dataset.id = id;
      div.innerHTML = '<b>' + esc(id) + '</b> <span style="color:#888;font-size:11px">' +
        esc(hlInfo) + (timeStr ? ' [' + esc(timeStr) + ']' : '') + '</span>';
      frag.appendChild(div);
    }
    els.autocomplete.innerHTML = '';
    els.autocomplete.appendChild(frag);
    els.autocomplete.hidden = false;
  }

  els.autocomplete.addEventListener('click', (e) => {
    const div = e.target.closest('div[data-id]');
    if (!div) return;
    selectId(div.dataset.id);
  });

  function selectId(id) {
    els.searchInput.value = id;
    els.autocomplete.hidden = true;
    doSearch();
  }

  els.searchInput.addEventListener('input', updateAutocomplete);
  els.searchInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { els.autocomplete.hidden = true; doSearch(); }
    if (e.key === 'Escape') { els.autocomplete.hidden = true; }
  });
  document.addEventListener('click', (e) => {
    if (!e.target.closest('.autocomplete-wrapper')) els.autocomplete.hidden = true;
  });

  // ===== 4. 查询 =====
  function doSearch() {
    const id = els.searchInput.value.trim();
    if (!id) return;
    const leagueSel = els.leagueSelect.value;
    if (leagueSel && !state.currentIdIndex[id]) {
      show(els.noResultOu);
      show(els.noResultWin);
      hide(els.hintOu);
      hide(els.hintWin);
      hide(els.matchInfo);
      hide(els.legend);
      els.statusTip.textContent = '该ID不属于所选联赛，请重新选择联赛或ID';
      return;
    }
    hide(els.hintOu);
    hide(els.hintWin);
    hide(els.noResultOu);
    hide(els.noResultWin);
    els.tableOu.innerHTML = '';
    els.tableWin.innerHTML = '';
    hide(els.matchInfo);
    show(els.legend);

    state.currentMatchId = id;
    state.currentRows = [];
    state.precomputed = [];
    for (const folder of state.FOLDERS) {
      const fd = state.DATA[folder] || {};
      const rec = (fd && fd[id]) ? fd[id] : null;
      state.currentRows.push({ folder, rec });
      state.precomputed.push({ folder, rec, analysis: Stats.analyzeRow(rec) });
    }

    const hasAny = state.currentRows.some((r) => r.rec !== null);
    if (!hasAny) {
      show(els.noResultOu);
      show(els.noResultWin);
      els.statusTip.textContent = '';
      return;
    }

    let firstOc = null;
    for (const r of state.precomputed) {
      if (r.rec && r.rec.oc) { firstOc = r.rec.oc; break; }
    }
    if (firstOc) {
      els.infoId.textContent = firstOc.id || state.currentMatchId;
      els.infoTime.textContent = formatMatchTime(firstOc.gt);
      els.infoLeague.textContent = firstOc.st || '-';
      els.infoHome.textContent = firstOc.sh || '-';
      els.infoAway.textContent = firstOc.sa || '-';
    } else {
      els.infoId.textContent = state.currentMatchId;
      els.infoTime.textContent = '-';
      els.infoLeague.textContent = '-';
      els.infoHome.textContent = '-';
      els.infoAway.textContent = '-';
    }
    const count = state.currentRows.filter((r) => r.rec !== null).length;
    els.infoCount.textContent = count;
    show(els.matchInfo);

    els.statusTip.textContent = '共找到 ' + count + ' 个时间段的数据';

    buildOuTable();
    buildWinTable();

    if (count > 0) {
      show(els.btnOuReport);
      showExportButtons(true);
    } else {
      hide(els.btnOuReport);
      showExportButtons(false);
    }
  }

  // ===== 5. 表格通用：计算变化列 class =====
  function cellClass(prev, cur) {
    if (prev === undefined || prev === null) return '';
    if (cur === '' || cur === null || cur === undefined) return '';
    return prev !== cur ? ' changed' : '';
  }

  function formatMatchTime(gt) {
    if (!gt) return '-';
    const m = gt.match(/^(\d{4})(\d{2})(\d{2})\s+(\d{1,2}:\d{2})/);
    if (m) return m[2] + '/' + m[3] + ' ' + m[4];
    return gt;
  }

  function pctChangeClass(prevVal, curVal, threshold = 0.005) {
    if (prevVal === undefined || prevVal === null || prevVal === '') return '';
    if (curVal === null) return '';
    if (Math.abs(prevVal - curVal) > threshold) return ' changed';
    return '';
  }

  // ===== 6. 表格构建（使用预解析的 ouGroups / winGroups）=====
  const NG_COLS = ['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'a1', 'a2', 'a3', 'a4', 'a5', 'a6'];
  const TG_LABELS = ['TG0', 'TG1', 'TG2', 'TG3', 'TG4', 'TG5', 'TG6', 'TG7+'];
  const GD_LABELS = ['+4+', '+3', '+2', '+1', '0', '-1', '-2', '-3', '-4-'];

  function buildOuTable() {
    const container = els.tableOu;
    container.innerHTML = '';
    const table = document.createElement('table');
    table.setAttribute('aria-label', '大小球盘口历史时序数据');

    const theadParts = [];
    theadParts.push('<caption class="sr-only">大小球盘口历史时序数据（大小球赔率、泊松 λ、EV、偏差）</caption><thead>');
    theadParts.push('<tr><th rowspan="2" scope="col">时间戳</th>' +
      '<th colspan="12" class="group-ng" scope="colgroup">进球分布赔率</th>' +
      '<th colspan="8" class="group-tg" scope="colgroup">总进球概率</th>' +
      '<th rowspan="2" class="group-lam" scope="col">λ/SSE</th>' +
      '<th colspan="9" class="group-ou-base" scope="colgroup">大小球赔率 + 公平概率 + EV</th></tr>');
    theadParts.push('<tr class="subheader-row">');
    for (const k of NG_COLS) theadParts.push('<th class="group-ng" scope="col">' + k.toUpperCase() + '</th>');
    for (const lbl of TG_LABELS) theadParts.push('<th class="group-tg" scope="col">' + lbl + '</th>');
    theadParts.push('<th class="group-ou-base" scope="col">大球OO</th>' +
      '<th class="group-ou-base" scope="col">小球UO</th>' +
      '<th class="group-ou-base ou-divider" scope="col">盘口LI</th>' +
      '<th class="group-ou-hv1" scope="col">HV1大</th>' +
      '<th class="group-ou-hv1" scope="col">HV1小</th>' +
      '<th class="group-ou-hv1 ou-divider" scope="col">HV1盘</th>' +
      '<th class="group-ou-hv2" scope="col">HV2大</th>' +
      '<th class="group-ou-hv2" scope="col">HV2小</th>' +
      '<th class="group-ou-hv2" scope="col">HV2盘</th>');
    theadParts.push('</tr></thead>');
    table.innerHTML = theadParts.join('') + '<tbody></tbody>';
    container.appendChild(table);
    const tbody = table.querySelector('tbody');

    let prevNg = null, prevTg = null, prevOuLines = null;

    for (const item of state.precomputed) {
      const { folder, rec, analysis } = item;
      const tr = document.createElement('tr');
      if (!rec) {
        tr.innerHTML = '<td class="folder-cell">' + esc(folder) + '</td>' +
          '<td colspan="30" class="missing">— 该时间段无此赛事 —</td>';
        tbody.appendChild(tr);
        continue;
      }

      const matchGt = rec.oc && rec.oc.gt ? rec.oc.gt : null;
      const timeStatus = Stats.getTimeStatus(folder, matchGt);
      const timeClass = timeStatus === 'before' ? 'time-before' :
                        timeStatus === 'after' ? 'time-after' : '';
      const ng = rec.ng || {};
      const ou = rec.ou || {};

      const curNg = NG_COLS.map((k) => ng[k] || '');
      const parts = ['<td class="folder-cell ' + timeClass + '">' + esc(folder) + '</td>'];

      for (let ni = 0; ni < NG_COLS.length; ni++) {
        const nval = ng[NG_COLS[ni]] || '<span class="missing">-</span>';
        const nchg = cellClass(prevNg && prevNg[ni], ng[NG_COLS[ni]]);
        parts.push('<td class="ng-val' + nchg + '">' + nval + '</td>');
      }

      const tgProbs = analysis.tgProbs;
      const poissonTgProbs = analysis.ouTg;
      const curTg = tgProbs ? tgProbs.slice() : new Array(8).fill('');

      for (let tgi = 0; tgi < 8; tgi++) {
        const tval = tgProbs ? (tgProbs[tgi] * 100).toFixed(1) + '%' : '<span class="missing">-</span>';
        const tchg = pctChangeClass(prevTg && prevTg[tgi], tgProbs ? tgProbs[tgi] : null);
        const poissonVal = poissonTgProbs ? (poissonTgProbs[tgi] * 100).toFixed(1) + '%' : '';
        const topVal = tgProbs ? tgProbs[tgi] : -1;
        const botVal = poissonTgProbs ? poissonTgProbs[tgi] : -1;
        const topColor = (topVal >= 0 && botVal >= 0)
          ? (topVal >= botVal ? '#dc2626' : '#111') : '#000';
        parts.push('<td class="tg-val' + tchg + '" style="line-height:1.7;vertical-align:middle">' +
          '<span style="font-weight:700;color:' + topColor + '">' + tval + '</span>' +
          '<br><span style="font-size:11px;color:#888">' + poissonVal + '</span></td>');
      }

      let lamCell = '<span class="missing">-</span>';
      if (analysis.ouLam !== null) {
        lamCell = '<span style="font-weight:700;font-size:13px">' + analysis.ouLam.toFixed(3) + '</span>' +
          '<br><span style="font-size:11px;color:#555">' + Stats.formatSSE(analysis.ouSse) + '</span>';
      }
      parts.push('<td class="ou-val" style="line-height:1.7">' + lamCell + '</td>');

      // 使用预解析的 ouGroups
      const hivGroups = analysis.ouGroups; // 直接使用
      const allLines = [
        { over: ou.oo || '', under: ou.uo || '', hcap: ou.li ? (parseFloat(ou.li) / 4).toFixed(2) : '' },
        hivGroups[0] || { over: '', under: '', hcap: '' },
        hivGroups[1] || { over: '', under: '', hcap: '' },
      ];
      const prevLines = prevOuLines;
      for (let lix = 0; lix < 3; lix++) {
        const line = allLines[lix];
        const pLine = prevLines ? prevLines[lix] : null;
        const ovStr = line.over, unStr = line.under, hcStr = line.hcap;
        const ovNum = parseFloat(ovStr) || 0, unNum = parseFloat(unStr) || 0, hcNum = parseFloat(hcStr) || 0;
        const chO = (pLine && ovStr && pLine.over !== ovStr) ? ' changed' : '';
        const chU = (pLine && unStr && pLine.under !== unStr) ? ' changed' : '';
        const chH = (pLine && hcStr && pLine.hcap !== hcStr) ? ' changed' : '';
        const divClass = (lix === 0) ? ' ou-divider' : '';
        if (!ovStr && !unStr && !hcStr) {
          parts.push('<td class="ou-val"><span class="missing">-</span></td>' +
            '<td class="ou-val"><span class="missing">-</span></td>' +
            '<td class="ou-val' + divClass + '"><span class="missing">-</span></td>');
        } else {
          let cellO = ovStr, cellU = unStr;
          if (tgProbs && ovNum > 0 && unNum > 0 && !isNaN(hcNum)) {
            try {
              const res = Stats.calcAsianEV(hcNum, ovNum, unNum, tgProbs);
              if (res.fairOver > 0) {
                cellO += '<span class="fp-line">公平P:' + (res.fairOver * 100).toFixed(1) + '%</span>';
              }
              if (!isNaN(res.evOver)) {
                cellO += '<span class="ev-line ' + (res.evOver > 0 ? 'ev-pos' : 'ev-neg') + '">EV ' +
                  (res.evOver >= 0 ? '+' : '') + res.evOver.toFixed(2) + '</span>';
              }
              if (analysis.ouDevs[hcStr] && analysis.ouDevs[hcStr].over !== undefined) {
                const dev = analysis.ouDevs[hcStr].over;
                cellO += '<span class="dev-line ' + (dev >= 0 ? 'dev-pos' : 'dev-neg') + '">' +
                  (dev >= 0 ? '+' : '') + dev.toFixed(2) + '%</span>';
              }
              if (res.fairUnder > 0) {
                cellU += '<span class="fp-line">公平P:' + (res.fairUnder * 100).toFixed(1) + '%</span>';
              }
              if (!isNaN(res.evUnder)) {
                cellU += '<span class="ev-line ' + (res.evUnder > 0 ? 'ev-pos' : 'ev-neg') + '">EV ' +
                  (res.evUnder >= 0 ? '+' : '') + res.evUnder.toFixed(2) + '</span>';
              }
              if (analysis.ouDevs[hcStr] && analysis.ouDevs[hcStr].under !== undefined) {
                const dev = analysis.ouDevs[hcStr].under;
                cellU += '<span class="dev-line ' + (dev >= 0 ? 'dev-pos' : 'dev-neg') + '">' +
                  (dev >= 0 ? '+' : '') + dev.toFixed(2) + '%</span>';
              }
            } catch (e) { /* ignore */ }
          }
          parts.push('<td class="ou-val' + chO + '">' + cellO + '</td>' +
            '<td class="ou-val' + chU + '">' + cellU + '</td>' +
            '<td class="ou-val' + chH + divClass + '">' + esc(hcStr) + '</td>');
        }
      }
      tr.innerHTML = parts.join('');
      tbody.appendChild(tr);
      prevNg = curNg;
      prevTg = curTg;
      prevOuLines = allLines.slice();
    }
  }

  function buildWinTable() {
    const container = els.tableWin;
    container.innerHTML = '';
    const table = document.createElement('table');
    table.setAttribute('aria-label', '让球盘口历史时序数据');

    const theadParts = [];
    theadParts.push('<caption class="sr-only">让球盘口历史时序数据（让球赔率、双变量泊松 λ₁/λ₂、EV、偏差）</caption><thead>');
    theadParts.push('<tr><th rowspan="2" scope="col">时间戳</th>' +
      '<th colspan="12" class="group-ng" scope="colgroup">进球分布赔率</th>' +
      '<th colspan="9" class="group-tg" scope="colgroup">净胜球概率</th>' +
      '<th rowspan="2" class="group-lam" scope="col">λ₁/λ₂<br>SSE</th>' +
      '<th colspan="9" class="group-win-base" scope="colgroup">让球赔率 + 公平概率 + EV</th></tr>');
    theadParts.push('<tr class="subheader-row">');
    for (const k of NG_COLS) theadParts.push('<th class="group-ng" scope="col">' + k.toUpperCase() + '</th>');
    for (const lbl of GD_LABELS) theadParts.push('<th class="group-tg" scope="col">' + lbl + '</th>');
    theadParts.push('<th class="group-win-base" scope="col">主队</th>' +
      '<th class="group-win-base" scope="col">客队</th>' +
      '<th class="group-win-base ou-divider" scope="col">盘口</th>' +
      '<th class="group-win-hv1" scope="col">HV1主</th>' +
      '<th class="group-win-hv1" scope="col">HV1客</th>' +
      '<th class="group-win-hv1 ou-divider" scope="col">HV1盘</th>' +
      '<th class="group-win-hv2" scope="col">HV2主</th>' +
      '<th class="group-win-hv2" scope="col">HV2客</th>' +
      '<th class="group-win-hv2" scope="col">HV2盘</th>');
    theadParts.push('</tr></thead>');
    table.innerHTML = theadParts.join('') + '<tbody></tbody>';
    container.appendChild(table);
    const tbody = table.querySelector('tbody');

    let prevNg = null, prevGd = null, prevWinLines = null;

    for (const item of state.precomputed) {
      const { folder, rec, analysis } = item;
      const tr = document.createElement('tr');
      if (!rec) {
        tr.innerHTML = '<td class="folder-cell">' + esc(folder) + '</td>' +
          '<td colspan="31" class="missing">— 该时间段无此赛事 —</td>';
        tbody.appendChild(tr);
        continue;
      }

      const matchGt = rec.oc && rec.oc.gt ? rec.oc.gt : null;
      const timeStatus = Stats.getTimeStatus(folder, matchGt);
      const timeClass = timeStatus === 'before' ? 'time-before' :
                        timeStatus === 'after' ? 'time-after' : '';
      const ng = rec.ng || {};
      const win = rec.win || {};

      const curNg = NG_COLS.map((k) => ng[k] || '');
      const parts = ['<td class="folder-cell ' + timeClass + '">' + esc(folder) + '</td>'];

      for (let ni = 0; ni < NG_COLS.length; ni++) {
        const nval = ng[NG_COLS[ni]] || '<span class="missing">-</span>';
        const nchg = cellClass(prevNg && prevNg[ni], ng[NG_COLS[ni]]);
        parts.push('<td class="ng-val' + nchg + '">' + nval + '</td>');
      }

      const gdProbs = analysis.gdProbs;
      const winPoissonGd = analysis.winGd;
      const curGd = gdProbs ? gdProbs.slice() : new Array(9).fill('');

      for (let gi = 0; gi < 9; gi++) {
        const origIdx = 8 - gi;
        const gval = gdProbs ? (gdProbs[origIdx] * 100).toFixed(1) + '%' : '<span class="missing">-</span>';
        const gchg = pctChangeClass(prevGd && prevGd[origIdx], gdProbs ? gdProbs[origIdx] : null);
        const winGdVal = winPoissonGd ? (winPoissonGd[origIdx] * 100).toFixed(1) + '%' : '';
        const wTop = gdProbs ? gdProbs[origIdx] : -1;
        const wBot = winPoissonGd ? winPoissonGd[origIdx] : -1;
        const wColor = (wTop >= 0 && wBot >= 0)
          ? (wTop >= wBot ? '#dc2626' : '#111') : '#000';
        parts.push('<td class="tg-val' + gchg + '" style="line-height:1.7;vertical-align:middle">' +
          '<span style="font-weight:700;color:' + wColor + '">' + gval + '</span>' +
          '<br><span style="font-size:11px;color:#888">' + winGdVal + '</span></td>');
      }

      let winLamCell = '<span class="missing">-</span>';
      if (analysis.winLamH !== null) {
        winLamCell = '<span style="font-weight:700;font-size:13px">' +
          analysis.winLamH.toFixed(3) + '/' + analysis.winLamA.toFixed(3) + '</span>' +
          '<br><span style="font-size:11px;color:#555">' + Stats.formatSSE(analysis.winSse) + '</span>';
      }
      parts.push('<td class="win-val" style="line-height:1.7">' + winLamCell + '</td>');

      // 使用预解析的 winGroups
      const varGroups = analysis.winGroups; // 直接使用
      let baseHandicap = '', baseHomeOdds = '', baseAwayOdds = '';
      if (win.g && win.gg && win.ho && win.ao) {
        const ggVal = parseFloat(win.gg);
        const hcapRaw = (ggVal - 1) / 4;
        const handicap = (win.g === 'H') ? -hcapRaw : hcapRaw;
        baseHandicap = handicap.toFixed(2);
        baseHomeOdds = win.ho;
        baseAwayOdds = win.ao;
      }
      const allLines = [
        { over: baseHomeOdds, under: baseAwayOdds, hcap: baseHandicap },
        varGroups[0] || { over: '', under: '', hcap: '' },
        varGroups[1] || { over: '', under: '', hcap: '' },
      ];
      const prevLines = prevWinLines;
      for (let lix = 0; lix < 3; lix++) {
        const line = allLines[lix];
        const pLine = prevLines ? prevLines[lix] : null;
        const ovStr = line.over, unStr = line.under, hcStr = line.hcap;
        const ovNum = parseFloat(ovStr) || 0, unNum = parseFloat(unStr) || 0, hcNum = parseFloat(hcStr) || 0;
        const chO = (pLine && ovStr && pLine.over !== ovStr) ? ' changed' : '';
        const chU = (pLine && unStr && pLine.under !== unStr) ? ' changed' : '';
        const chH = (pLine && hcStr && pLine.hcap !== hcStr) ? ' changed' : '';
        const divClass = (lix === 0) ? ' ou-divider' : '';
        if (!ovStr && !unStr && !hcStr) {
          parts.push('<td class="win-val"><span class="missing">-</span></td>' +
            '<td class="win-val"><span class="missing">-</span></td>' +
            '<td class="win-val' + divClass + '"><span class="missing">-</span></td>');
        } else {
          let cellO = ovStr, cellU = unStr;
          if (gdProbs && ovNum > 0 && unNum > 0 && !isNaN(hcNum)) {
            try {
              const res = Stats.calcAsianEVForGD(hcNum, ovNum, unNum, gdProbs);
              if (res.fairHome > 0) {
                cellO += '<span class="fp-line">公平P:' + (res.fairHome * 100).toFixed(1) + '%</span>';
              }
              if (!isNaN(res.evHome)) {
                cellO += '<span class="ev-line ' + (res.evHome > 0 ? 'ev-pos' : 'ev-neg') + '">EV ' +
                  (res.evHome >= 0 ? '+' : '') + res.evHome.toFixed(2) + '</span>';
              }
              if (analysis.winDevs[hcStr] && analysis.winDevs[hcStr].home !== undefined) {
                const dev = analysis.winDevs[hcStr].home;
                cellO += '<span class="dev-line ' + (dev >= 0 ? 'dev-pos' : 'dev-neg') + '">' +
                  (dev >= 0 ? '+' : '') + dev.toFixed(2) + '%</span>';
              }
              if (res.fairAway > 0) {
                cellU += '<span class="fp-line">公平P:' + (res.fairAway * 100).toFixed(1) + '%</span>';
              }
              if (!isNaN(res.evAway)) {
                cellU += '<span class="ev-line ' + (res.evAway > 0 ? 'ev-pos' : 'ev-neg') + '">EV ' +
                  (res.evAway >= 0 ? '+' : '') + res.evAway.toFixed(2) + '</span>';
              }
              if (analysis.winDevs[hcStr] && analysis.winDevs[hcStr].away !== undefined) {
                const dev = analysis.winDevs[hcStr].away;
                cellU += '<span class="dev-line ' + (dev >= 0 ? 'dev-pos' : 'dev-neg') + '">' +
                  (dev >= 0 ? '+' : '') + dev.toFixed(2) + '%</span>';
              }
            } catch (e) { /* ignore */ }
          }
          parts.push('<td class="win-val' + chO + '">' + cellO + '</td>' +
            '<td class="win-val' + chU + '">' + cellU + '</td>' +
            '<td class="win-val' + chH + divClass + '">' + esc(hcStr) + '</td>');
        }
      }
      tr.innerHTML = parts.join('');
      tbody.appendChild(tr);
      prevNg = curNg;
      prevGd = curGd;
      prevWinLines = allLines.slice();
    }
  }

  // ===== 7. 清除 / 视图切换 =====
  function doClear() {
    els.searchInput.value = '';
    els.tableOu.innerHTML = '';
    els.tableWin.innerHTML = '';
    hide(els.matchInfo);
    hide(els.noResultOu);
    hide(els.noResultWin);
    show(els.hintOu);
    show(els.hintWin);
    hide(els.legend);
    els.statusTip.textContent = '';
    hide(els.btnOuReport);
    hideExportButtons();
    if (els.leagueSelect) {
      els.leagueSelect.value = '';
      onLeagueChange();
    }
  }

  function switchView(view) {
    state.currentView = view;
    const viewOu = $('viewOu');
    const viewWin = $('viewWin');
    if (view === 'ou') {
      els.btnOu.classList.add('active');
      els.btnOu.setAttribute('aria-selected', 'true');
      els.btnWin.classList.remove('active');
      els.btnWin.setAttribute('aria-selected', 'false');
      viewOu.classList.add('active');
      viewWin.classList.remove('active');
    } else {
      els.btnWin.classList.add('active');
      els.btnWin.setAttribute('aria-selected', 'true');
      els.btnOu.classList.remove('active');
      els.btnOu.setAttribute('aria-selected', 'false');
      viewWin.classList.add('active');
      viewOu.classList.remove('active');
    }
  }

  // ===== 8. CSV 导出（使用预解析数据） =====
  function csvEscape(s) {
    if (s === null || s === undefined) return '';
    const str = String(s);
    if (/[",\n]/.test(str)) return '"' + str.replace(/"/g, '""') + '"';
    return str;
  }

  function exportCsv(type) {
    if (!state.precomputed.length) {
      alert('暂无数据，请先查询一个比赛ID');
      return;
    }
    const isOu = type === 'ou';
    const headers = ['时间戳', '赛前/赛后', ...NG_COLS.map((k) => k.toUpperCase())];
    if (isOu) {
      for (const l of TG_LABELS) headers.push(l + '%', '泊松' + l + '%');
      headers.push('λ', 'SSE');
      for (const i of [0, 1, 2]) {
        const tag = i === 0 ? '基础' : ('HV' + i);
        headers.push(tag + '大/主', tag + '公平P_大/主', tag + 'EV_大/主', tag + '偏差_大/主');
        headers.push(tag + '小/客', tag + '公平P_小/客', tag + 'EV_小/客', tag + '偏差_小/客');
        headers.push(tag + '盘口');
      }
    } else {
      for (const l of GD_LABELS) headers.push(l + '%', '泊松' + l + '%');
      headers.push('λ₁', 'λ₂', 'SSE');
      for (const i of [0, 1, 2]) {
        const tag = i === 0 ? '基础' : ('HV' + i);
        headers.push(tag + '主', tag + '公平P_主', tag + 'EV_主', tag + '偏差_主');
        headers.push(tag + '客', tag + '公平P_客', tag + 'EV_客', tag + '偏差_客');
        headers.push(tag + '盘口');
      }
    }

    const rows = [headers.map(csvEscape).join(',')];
    for (const item of state.precomputed) {
      const { folder, rec, analysis } = item;
      if (!rec) continue;
      const matchGt = rec.oc && rec.oc.gt ? rec.oc.gt : null;
      const ts = Stats.getTimeStatus(folder, matchGt);
      const ng = rec.ng || {};
      const row = [folder, ts || ''];
      for (const k of NG_COLS) row.push(ng[k] || '');
      if (isOu) {
        for (let i = 0; i < 8; i++) {
          row.push(analysis.tgProbs ? (analysis.tgProbs[i] * 100).toFixed(2) : '');
          row.push(analysis.ouTg ? (analysis.ouTg[i] * 100).toFixed(2) : '');
        }
        row.push(analysis.ouLam !== null ? analysis.ouLam.toFixed(4) : '');
        row.push(analysis.ouSse !== null ? analysis.ouSse.toExponential(4) : '');
      } else {
        for (let i = 0; i < 9; i++) {
          const origIdx = 8 - i;
          row.push(analysis.gdProbs ? (analysis.gdProbs[origIdx] * 100).toFixed(2) : '');
          row.push(analysis.winGd ? (analysis.winGd[origIdx] * 100).toFixed(2) : '');
        }
        row.push(analysis.winLamH !== null ? analysis.winLamH.toFixed(4) : '');
        row.push(analysis.winLamA !== null ? analysis.winLamA.toFixed(4) : '');
        row.push(analysis.winSse !== null ? analysis.winSse.toExponential(4) : '');
      }
      // 3 行盘口：使用预解析的 ouGroups / winGroups
      const ou = rec.ou || {}, win = rec.win || {};
      if (isOu) {
        const hivGroups = analysis.ouGroups; // 预解析
        const lines = [
          { over: ou.oo || '', under: ou.uo || '', hcap: ou.li ? (parseFloat(ou.li) / 4).toFixed(2) : '' },
          hivGroups[0] || { over: '', under: '', hcap: '' },
          hivGroups[1] || { over: '', under: '', hcap: '' },
        ];
        for (const line of lines) {
          const ov = parseFloat(line.over) || 0, un = parseFloat(line.under) || 0, hc = parseFloat(line.hcap) || 0;
          if (analysis.tgProbs && ov > 0 && un > 0 && !isNaN(hc)) {
            try {
              const res = Stats.calcAsianEV(hc, ov, un, analysis.tgProbs);
              const dev = (analysis.ouDevs[line.hcap] || {});
              row.push(line.over, (res.fairOver * 100).toFixed(2), res.evOver.toFixed(4),
                dev.over !== undefined ? dev.over.toFixed(2) : '');
              row.push(line.under, (res.fairUnder * 100).toFixed(2), res.evUnder.toFixed(4),
                dev.under !== undefined ? dev.under.toFixed(2) : '');
            } catch (e) {
              row.push(line.over, '', '', '', line.under, '', '', '');
            }
          } else {
            row.push(line.over, '', '', '', line.under, '', '', '');
          }
          row.push(line.hcap);
        }
      } else {
        let baseH = '', baseA = '', baseHc = '';
        if (win.g && win.gg && win.ho && win.ao) {
          const ggVal = parseFloat(win.gg);
          const hcapRaw = (ggVal - 1) / 4;
          const handicap = (win.g === 'H') ? -hcapRaw : hcapRaw;
          baseHc = handicap.toFixed(2);
          baseH = win.ho; baseA = win.ao;
        }
        const vg = analysis.winGroups; // 预解析
        const lines = [
          { over: baseH, under: baseA, hcap: baseHc },
          vg[0] || { over: '', under: '', hcap: '' },
          vg[1] || { over: '', under: '', hcap: '' },
        ];
        for (const line of lines) {
          const ov = parseFloat(line.over) || 0, un = parseFloat(line.under) || 0, hc = parseFloat(line.hcap) || 0;
          if (analysis.gdProbs && ov > 0 && un > 0 && !isNaN(hc)) {
            try {
              const res = Stats.calcAsianEVForGD(hc, ov, un, analysis.gdProbs);
              const dev = (analysis.winDevs[line.hcap] || {});
              row.push(line.over, (res.fairHome * 100).toFixed(2), res.evHome.toFixed(4),
                dev.home !== undefined ? dev.home.toFixed(2) : '');
              row.push(line.under, (res.fairAway * 100).toFixed(2), res.evAway.toFixed(4),
                dev.away !== undefined ? dev.away.toFixed(2) : '');
            } catch (e) {
              row.push(line.over, '', '', '', line.under, '', '', '');
            }
          } else {
            row.push(line.over, '', '', '', line.under, '', '', '');
          }
          row.push(line.hcap);
        }
      }
      rows.push(row.map(csvEscape).join(','));
    }

    const bom = '\uFEFF';
    const csv = bom + rows.join('\n');
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${state.currentMatchId}_${type}_${new Date().toISOString().slice(0, 10)}.csv`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  // ===== 9. 导出按钮 =====
  function showExportButtons(show) {
    if (!els.btnExportOu) {
      els.btnExportOu = document.createElement('button');
      els.btnExportOu.textContent = '导出 CSV';
      els.btnExportOu.style.cssText = 'background:#27ae60;color:#fff;border:none;border-radius:6px;padding:9px 18px;cursor:pointer;font-family:inherit;font-weight:600;font-size:14px;white-space:nowrap;';
      els.btnExportOu.addEventListener('click', () => exportCsv('ou'));
      els.btnExportWin = document.createElement('button');
      els.btnExportWin.textContent = '导出 CSV';
      els.btnExportWin.style.cssText = els.btnExportOu.style.cssText;
      els.btnExportWin.addEventListener('click', () => exportCsv('win'));
      els.btnOu.parentElement.appendChild(els.btnExportOu);
      els.btnWin.parentElement.appendChild(els.btnExportWin);
    }
    els.btnExportOu.style.display = show ? 'inline-block' : 'none';
    els.btnExportWin.style.display = show ? 'inline-block' : 'none';
  }
  function hideExportButtons() {
    if (els.btnExportOu) els.btnExportOu.style.display = 'none';
    if (els.btnExportWin) els.btnExportWin.style.display = 'none';
  }

  // ===== 10. OU 报告 =====
  function generateOuReport() {
    if (!state.precomputed.length) {
      alert('暂无数据，请先查询一个比赛ID');
      return;
    }
    const results = [];
    for (const item of state.precomputed) {
      const { folder, rec } = item;
      if (!rec) continue;
      const matchGt = rec.oc && rec.oc.gt ? rec.oc.gt : null;
      const isAfter = Stats.getTimeStatus(folder, matchGt) === 'after';
      const ou = rec.ou || {};
      const ng = rec.ng || {};
      const ooVal = parseFloat(ou.oo), uoVal = parseFloat(ou.uo), liVal = parseFloat(ou.li);
      if (isNaN(ooVal) || isNaN(uoVal) || isNaN(liVal) || ooVal <= 0 || uoVal <= 0) continue;
      const hasNg = NG_COLS.every((k) => ng[k] && parseFloat(ng[k]) > 0);
      if (!hasNg) continue;
      const homeOdds = NG_COLS.slice(0, 6).map((k) => ng[k]);
      const awayOdds = NG_COLS.slice(6, 12).map((k) => ng[k]);
      const hp = Stats.normalizeOdds(homeOdds);
      const ap = Stats.normalizeOdds(awayOdds);
      const tgProbs = Stats.calcTotalGoals(hp, ap);
      if (!tgProbs) continue;
      const handicap = liVal / 4;
      const displayHandicap = handicap.toFixed(2);
      let res;
      try {
        res = Stats.calcAsianEV(handicap, ooVal, uoVal, tgProbs);
        if (!res || isNaN(res.fairOver) || isNaN(res.fairUnder)) continue;
      } catch (e) { continue; }
      const overFairP = res.fairOver, underFairP = res.fairUnder;
      const overEV = res.evOver, underEV = res.evUnder;
      const pickOver = overFairP >= underFairP;
      const pickEV = pickOver ? overEV : underEV;
      const warning = pickEV >= 0 ? 'reversed' : (pickEV > -0.020 ? 'deviated' : '');
      const conclusion = pickOver ? '大球' : '小球';
      const concClass = pickOver ? 'over' : 'under';
      const threshold = pickOver ? ('>=' + displayHandicap) : ('<=' + displayHandicap);
      const bestFairP = pickOver ? overFairP : underFairP;
      results.push({
        folder, handicap: displayHandicap,
        fairP: (bestFairP * 100).toFixed(1),
        ev: pickEV, conclusion, concClass, threshold, warning,
      });
      if (isAfter) break;
    }
    if (!results.length) {
      alert('没有可分析的有效盘口数据（第一个盘口）');
      return;
    }
    sendOuReportToFootball(results);
  }

  function sendOuReportToFootball(results) {
    try {
      const payload = {
        type: 'OU_REPORT',
        matchId: state.currentMatchId,
        results: results.map((r) => ({
          folder: r.folder, handicap: r.handicap, fairP: r.fairP,
          ev: r.ev, conclusion: r.conclusion, concClass: r.concClass,
          threshold: r.threshold, warning: r.warning,
        })),
      };
      if (window.opener && !window.opener.closed) {
        window.opener.postMessage(payload, '*');
      } else {
        window.postMessage(payload, '*');
      }
    } catch (e) { /* ignore */ }
  }

  // ===== 11. 跨窗口接收 =====
  window.addEventListener('message', (e) => {
    if (location.origin && e.origin && e.origin !== 'null' && e.origin !== location.origin) return;
    if (!e.data || e.data.type !== 'FAIRPLAY_FILL') return;
    const league = e.data.league || '';
    const matchId = e.data.matchId || '';
    if (league && els.leagueSelect) {
      for (const opt of els.leagueSelect.options) {
        if (opt.value === league) {
          els.leagueSelect.value = league;
          onLeagueChange();
          break;
        }
      }
    }
    setTimeout(() => {
      if (matchId) {
        els.searchInput.disabled = false;
        els.searchInput.value = matchId;
      }
      doSearch();
    }, 200);
  });

  // ===== 12. Loading 隐藏 =====
  function ensureLoading() {
    if (els.loading) return els.loading;
    els.loading = document.getElementById('appLoading');
    return els.loading;
  }
  function hideLoading() {
    const el = els.loading || document.getElementById('appLoading');
    if (el && el.parentNode) el.parentNode.removeChild(el);
    els.loading = null;
  }

  // ===== 13. 初始化 =====
  function init() {
    buildLeagueIndex();
    populateLeagues();
    els.leagueSelect.addEventListener('change', onLeagueChange);
    els.btnSearch.addEventListener('click', doSearch);
    els.btnClear.addEventListener('click', doClear);
    els.btnOu.addEventListener('click', () => switchView('ou'));
    els.btnWin.addEventListener('click', () => switchView('win'));
    if (els.btnOuReport) els.btnOuReport.addEventListener('click', generateOuReport);
    // 保留对外接口（调试或外部调用）
    window.doSearch = doSearch;
    window.doClear = doClear;
    window.switchView = switchView;
    window.onLeagueChange = onLeagueChange;
    window.generateOuReport = generateOuReport;
    window.selectId = selectId;
    hideLoading();
  }

  function bootstrap() {
    ensureLoading();
    init();
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', bootstrap);
  } else {
    bootstrap();
  }
})();