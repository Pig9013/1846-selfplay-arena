'use strict';
/* 1846 human-vs-AI board. Talks to the Ruby bridge on :1847 (or ?bridge=…). */
const params = new URLSearchParams(location.search);
const BRIDGE = (params.get('bridge') || 'http://127.0.0.1:1847').replace(/\/$/, '');
const $ = id => document.getElementById(id);
const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const money = v => v === null || v === undefined ? '—' : '$' + Number(v).toLocaleString('en-US');
const ROUND = {'Draft Round':'私营公司分配','Stock Round':'股票轮','Operating Round':'营运轮'};
const HEX_COLOR = {white:'空白',yellow:'黄',green:'绿',brown:'棕',gray:'灰',red:'外域',blue:'水域'};
const PLAYER_TINT = ['#d98a5b', '#7fa9d0', '#a9c47f', '#c79ad0', '#d0c07a'];
const STEP_HINT = {
  DraftDistribution: '竞标私营公司：出价最高者得到；Pass 牌表示放弃本轮。',
  Draft2pDistribution: '竞标私营公司：出价最高者得到。',
  BuySellParShares: '股票轮：买入 / 卖出股票，或开办新公司；点「结束行动」结束。',
  TrackAndToken: '为当前公司铺轨或设站：地图上点亮的格子有可选行动。',
  SpecialTrack: '特殊铺轨：只能铺指定地块。',
  Track: '铺轨：地图上点亮的格子有可选行动。',
  Token: '设置车站：点亮的城市位可选。',
  Route: '营运：选择线路组合，确认后进入分红决策。',
  Dividend: '分红：全额/半额发放会让股价右移，留存则左移。',
  BuyTrain: '购买列车；买新车会推进时代并淘汰旧车。',
  BuyCompany: '收购私营公司：把它的能力并入你的公司。',
  Assign: '把私营公司的能力指派到地块或公司。',
  IssueShares: '公司增发股票换取现金。',
  Bankrupt: '无法偿还时宣告破产。',
};
const NOISE = [/chooses a company$/, /has no valid actions and passes/, / passes$/];
const CAT_ICON = {
  lay_tile:'铺轨', place_token:'设站', run_routes:'营运', dividend:'分红', buy_train:'买列车',
  discard_train:'淘汰', buy_company:'收购', assign:'指派', bid:'竞标', par:'开办',
  buy_shares:'买股', sell_shares:'卖股', bankrupt:'破产', pass:'结束行动'
};

let state = null, renderedAction = -1, busy = false, category = null, pending = null;
let hexFilter = null, rejected = new Set(), toastTimer = null, lastLogScroll = 0;

/* ---------------- data helpers ---------------- */
function corpOf(id){ return (state?.corporations || []).find(c => c.id === id); }
function corpColor(id){ const c = corpOf(id); return c ? readable(c.color) : '#888'; }
// Very dark company colours (NYC) vanish on a dark card; lift them for display.
function readable(color){
  const m = /^#([0-9a-f]{6})$/i.exec(color || '');
  if (!m) return color || '#888';
  const n = parseInt(m[1], 16);
  const r = n >> 16 & 255, g = n >> 8 & 255, b = n & 255;
  const lum = 0.299 * r + 0.587 * g + 0.114 * b;
  if (lum >= 55) return color;
  const lift = v => Math.round(v + (255 - v) * 0.55);
  return '#' + [lift(r), lift(g), lift(b)].map(v => v.toString(16).padStart(2, '0')).join('');
}
function playerOf(id){ return (state?.players || []).find(p => p.id === String(id)); }
function actorName(id){
  const p = playerOf(id);
  if (p) return p.name;
  const c = corpOf(id);
  if (c) return c.name;
  return id;
}
function actingName(){
  const acting = state?.acting;
  if (!acting) return '';
  const corp = corpOf(acting);
  return corp ? corp.name : '';
}
function nowWho(){
  if (!state) return '—';
  if (state.finished) return '对局结束';
  const acting = actingName();
  if (state.human_turn) return '你' + (acting ? ' · ' + acting : '');
  return 'AI 行动中 · ' + actorName(state.entity) + (acting ? ' · ' + acting : '');
}

/* ---------------- transport ---------------- */
async function api(path, data){
  const res = await fetch(BRIDGE + path, data ? {
    method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data)
  } : {});
  if (!res.ok) throw new Error('HTTP ' + res.status);
  return res.json();
}
function conn(ok, text){
  const el = $('conn');
  el.textContent = ok ? '已连接' : (text || '连接中断');
  el.className = 'conn' + (ok ? '' : ' bad');
}
function toast(message){
  const el = $('toast');
  el.textContent = message;
  el.classList.add('on');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove('on'), 3200);
}

/* ---------------- polling ---------------- */
async function poll(){
  if (busy) return;
  try {
    const data = await api('/state');
    conn(true);
    const changed = data.action_count !== renderedAction || data.finished !== state?.finished;
    state = data;
    if (changed) {
      renderedAction = data.action_count;
      if (!busy) { category = null; pending = null; hexFilter = null; rejected = new Set(); }
      renderAll();
    } else {
      renderHeader();
      renderTurn();
    }
  } catch (error) {
    conn(false);
  }
}

/* ---------------- rendering ---------------- */
function renderAll(){
  renderHeader();
  renderPlayers();
  renderCorps();
  renderPrivates();
  renderMarket();
  renderDepot();
  renderLog();
  renderDock();
  drawMap();
  renderResult();
}

function renderHeader(){
  if (!state) return;
  const undo = $('undo');
  if (undo){
    undo.disabled = !state.undo || !!state.finished;
    undo.textContent = state.undo ? '撤回 (' + state.undo + ')' : '撤回';
  }
  $('roundName').textContent = (ROUND[state.round] || state.round) + (state.round_num ? ' ' + state.round_num : '');
  $('phaseName').textContent = '时代 ' + state.phase;
  $('bankCash').textContent = money(state.bank);
  renderTurn();
}
function renderTurn(){
  $('turnWho').textContent = nowWho();
  $('stepLabel').textContent = state?.step || '';
  $('stepHint').textContent = STEP_HINT[state?.step_class] || '点亮的格子可以铺轨/设站；点格子查看详情。';
}

function sharesHtml(corp){
  const holders = corp.holders || {};
  const order = ['ipo', 'market'];
  const players = Object.keys(holders).filter(k => k !== 'ipo' && k !== 'market');
  const parts = [];
  if (holders.ipo) parts.push({key:'ipo', label:'公司', percent:holders.ipo, color:'#5d7383'});
  players.forEach(id => {
    const index = state.players.findIndex(p => p.id === String(id));
    parts.push({key:id, label:actorName(id), percent:holders[id], color: PLAYER_TINT[(index + PLAYER_TINT.length) % PLAYER_TINT.length]});
  });
  if (holders.market) parts.push({key:'market', label:'股票池', percent:holders.market, color:'#3b4d58'});
  return parts;
}

function renderPlayers(){
  if (!state) return;
  $('players').innerHTML = state.players.map(p => {
    const acting = state.entity_type === 'player' && String(state.entity) === p.id;
    const shares = p.shares.length
      ? p.shares.map(s => '<span class="share" title="' + esc(s.corp) + '"><i style="background:' + corpColor(s.corp) + '"></i>' + esc(s.corp) + ' ' + s.percent + '%</span>').join('')
      : '<span class="muted" style="font-size:11px">未持股</span>';
    const privs = p.privates.length
      ? '<div class="privs">' + p.privates.map(v => '<span title="' + esc(v.name) + '">' + esc(v.id) + '</span>').join('') + '</div>' : '';
    return '<div class="pcard' + (p.id === state.you ? ' me' : '') + (acting ? ' acting' : '') + '">' +
      '<div class="prow"><b>' + esc(p.name) + '</b><span>' + money(p.cash) + '</span></div>' +
      '<div class="pmeta">总资产 ' + money(p.value) + (acting ? ' · 行动中' : '') + '</div>' +
      '<div class="shares">' + shares + '</div>' + privs + '</div>';
  }).join('');
}

function renderCorps(){
  if (!state) return;
  $('corps').innerHTML = '<div class="minihead"><span>铁路公司</span><span>' + state.corporations.length + '</span></div>' +
    state.corporations.map(c => {
      const shares = sharesHtml(c);
      const bar = shares.map(s => '<i style="width:' + s.percent + '%;background:' + s.color + '" title="' + esc(s.label) + ' ' + s.percent + '%"></i>').join('');
      const trains = c.trains.length ? c.trains.map(t => '<span class="train">' + esc(t) + '</span>').join('') : '<span class="muted" style="font-size:11px">无列车</span>';
      const tokens = c.tokens.length ? c.tokens.map(t => '<span>' + esc(t) + '</span>').join('') : '<span>未设站</span>';
      const meta = [
        c.owner ? '总裁 ' + actorName(c.owner) : '未开办',
        '金库 ' + money(c.cash),
        c.price ? '股价 ' + money(c.price) : '',
        c.par ? '原价 ' + money(c.par) : ''
      ].filter(Boolean).join(' · ');
      const isActing = (state.acting && c.id === state.acting) || c.id === state.entity;
      return '<div class="ccard' + (isActing ? ' acting' : '') + '" style="--cc:' + readable(c.color) + '">' +
        '<div class="chead"><span class="dot"></span><b>' + esc(c.name) + '</b><span class="price">' + (c.price ? money(c.price) : (c.type === 'minor' ? '独立' : '未开办')) + '</span></div>' +
        '<div class="cmeta">' + meta + '</div>' +
        '<div class="trains">' + trains + '</div>' +
        '<div class="tok">' + tokens + '</div>' +
        '<div class="bar">' + bar + '</div></div>';
    }).join('');
}

function renderPrivates(){
  if (!state) return;
  const unsold = (state.privates || []).filter(p => !p.owner);
  const sold = (state.privates || []).filter(p => p.owner);
  const rows = (list, showOwner) => list.map(p => '<div class="privitem"><b>' + esc(p.id) + '</b><span>' +
    (showOwner ? esc(actorName(p.owner)) : money(p.min_bid)) + '</span></div>').join('');
  $('privatesBox').innerHTML =
    (sold.length ? '<div class="minihead"><span>已售私营</span><span>' + sold.length + '</span></div><div class="privlist">' + rows(sold, true) + '</div>' : '') +
    (unsold.length ? '<div class="minihead"><span>待售私营</span><span>起价</span></div><div class="privlist">' + rows(unsold, false) + '</div>' : '');
}

function renderMarket(){
  if (!state || !state.market) return;
  const chips = {};
  (state.market.corporations || []).forEach(c => { (chips[c.index] = chips[c.index] || []).push(c); });
  $('market').innerHTML = (state.market.cells || []).map((cell, index) => {
    const list = chips[index] || [];
    return '<div class="mcell' + (cell.par ? ' par' : '') + '">' + cell.price +
      '<div class="chips">' + list.map(c => '<span class="chip" style="background:' + c.color + '" title="' + esc(c.id) + ' ' + money(c.price) + '"></span>').join('') + '</div></div>';
  }).join('');
}

function renderDepot(){
  if (!state || !state.depot) return;
  $('depot').innerHTML = state.depot.map(t =>
    '<div><span>' + esc(t.name) + ' 号车</span><span>' + money(t.price) + ' ×' + t.count + '</span></div>').join('');
}

function renderLog(){
  if (!state) return;
  const box = $('log');
  const nearBottom = box.scrollTop + box.clientHeight >= box.scrollHeight - 40;
  box.innerHTML = (state.log || []).map(entry => {
    const who = entry.actor ? actorName(entry.actor) : '';
    const mine = String(entry.actor) === String(state.you) ? ' me' : '';
    const detail = (entry.detail || []).filter(d => !NOISE.some(re => re.test(d)))
      .map(d => '<div class="detail">' + esc(d) + '</div>').join('');
    return '<div class="logline' + mine + '"><span class="n">' + entry.n + '</span><div><span class="who">' + esc(who) + '</span> ' + esc(entry.text) + detail + '</div></div>';
  }).join('');
  $('logCount').textContent = (state.log || []).length + ' 条';
  if (nearBottom) box.scrollTop = box.scrollHeight;
}

function renderResult(){
  const panel = $('result');
  if (!state || !state.finished || !state.result){ panel.classList.add('hidden'); return; }
  const rows = Object.entries(state.result).sort((a, b) => b[1] - a[1])
    .map(([id, value]) => '<div>' + esc(actorName(id)) + '　' + money(value) + '</div>').join('');
  panel.innerHTML = '<h2>对局结束</h2>' + rows + '<p class="muted">完整记录已写入 runs\\human\\对局日志.txt</p>' +
    '<button class="secondary" onclick="restartGame()" style="border:1px solid #6b8494;padding:8px 18px;border-radius:6px">再来一局</button>';
  panel.classList.remove('hidden');
}

/* ---------------- action dock ---------------- */
const GROUPED = new Set(['par', 'buy_shares', 'sell_shares', 'lay_tile', 'place_token', 'buy_company']);
function hexLabel(id){
  const hex = (state?.board?.hexes || []).find(h => h.id === id);
  return hex ? hex.id + (hex.location ? ' ' + hex.location : '') : id;
}
function privateName(id){
  const found = (state?.privates || []).find(p => p.id === id);
  return found ? found.name : id;
}
function renderGroups(options){
  const isCorpGroup = ['par', 'buy_shares', 'sell_shares'].includes(category);
  const isCompanyGroup = category === 'buy_company';
  const map = new Map();
  for (const o of options){
    const key = isCompanyGroup ? (o.company || '?') : isCorpGroup ? (o.corp || o.company || '?') : (o.hex || '?');
    if (!map.has(key)) map.set(key, []);
    map.get(key).push(o);
  }
  return [...map.entries()].map(([key, list]) => {
    let head;
    if (isCompanyGroup){
      const owner = list[0].owner;
      head = esc(privateName(key)) + (owner ? ' <span class="muted">· ' + esc(actorName(owner)) + ' 持有</span>' : '');
    } else if (isCorpGroup){
      head = '<i style="background:' + corpColor(key) + '"></i>' + esc(corpOf(key) ? corpOf(key).name : key);
    } else {
      head = esc(hexLabel(key));
    }
    const items = category === 'par' ? list.slice().sort((a, b) => (a.par || 0) - (b.par || 0)) : list;
    const chips = items.map(o => '<button class="ochip" data-pick="' + o.pick + '" title="' + esc(o.label) + '">' +
      esc(o.short || o.label) + (o.cost && o.type !== 'par' && o.type !== 'buy_company' ? ' <span class="cost">' + money(o.cost) + '</span>' : '') + '</button>').join('');
    return '<div class="ogroup"><div class="oghead">' + head + '</div><div class="ochips">' + chips + '</div></div>';
  }).join('');
}
function selectPending(pick){
  pending = (state.candidates || []).find(c => c.pick === pick) || null;
  renderDock();
  drawMap();
}

function filteredOptions(){
  if (!state || !category) return [];
  return (state.candidates || []).filter(c =>
    c.type === category && !rejected.has(c.pick) && (!hexFilter || c.hex === hexFilter));
}

function renderDock(){
  const prompt = $('prompt'), cats = $('cats'), opts = $('opts'), confirm = $('confirmBox');
  confirm.classList.add('hidden');
  confirm.innerHTML = '';
  if (!state) return;
  if (state.finished) {
    prompt.innerHTML = '<b>对局结束</b><span></span>';
    cats.innerHTML = ''; opts.innerHTML = '';
    return;
  }
  if (!state.human_turn) {
    prompt.innerHTML = '<b>AI 行动中…</b><span class="muted">' + esc(actorName(state.entity)) + '</span>';
    cats.innerHTML = ''; opts.innerHTML = '<div class="empty">轮到你的回合时，这里会出现可选行动。</div>';
    return;
  }
  if (pending) {
    prompt.innerHTML = '<b>' + esc(CAT_ICON[pending.type] || pending.type) + '</b><span class="muted">确认这一步</span>';
    cats.innerHTML = ''; opts.innerHTML = '';
    confirm.innerHTML = '<b>' + esc(pending.label) + '</b><small class="muted">' + esc(pending.sub || '') + '</small>' +
      '<div class="row"><button class="go" id="doConfirm">确认执行</button><button class="cancel" id="doCancel">取消</button></div>';
    confirm.classList.remove('hidden');
    $('doConfirm').onclick = () => submit(pending.pick);
    $('doCancel').onclick = () => { pending = null; renderDock(); drawMap(); };
    return;
  }
  if (category) {
    const options = filteredOptions();
    const who = actingName();
    prompt.innerHTML = '<b>' + esc((who ? who + ' · ' : '') + (CAT_ICON[category] || category)) + '</b><span class="muted">' +
      (hexFilter ? '已筛选 ' + esc(hexFilter) + ' · ' : '') + options.length + ' 个选项' +
      (category === 'lay_tile' || category === 'place_token' ? ' · 可点地图格子' : '') + '</span>';
    cats.innerHTML = '<button class="cat" id="backCats"><span>← 返回行动</span><span class="count">' + (state.groups.length) + '</span></button>';
    $('backCats').onclick = () => { category = null; hexFilter = null; renderDock(); drawMap(); };
    if (!options.length) {
      opts.innerHTML = '<div class="empty">该筛选下没有可选行动，点地图其他格子或返回。</div>';
    } else if (GROUPED.has(category)) {
      opts.innerHTML = renderGroups(options);
    } else {
      opts.innerHTML = options.map(o =>
        '<button class="opt" data-pick="' + o.pick + '"><b>' + esc(o.label) + '</b><small>' + esc(o.sub || '') +
        (o.cost ? ' <span class="cost">' + money(o.cost) + '</span>' : '') + '</small></button>').join('');
    }
    opts.querySelectorAll('[data-pick]').forEach(button => {
      button.onclick = () => selectPending(Number(button.dataset.pick));
    });
    return;
  }
  prompt.innerHTML = '<b>轮到你行动</b><span class="muted">选择行动类型</span>';
  opts.innerHTML = '';
  cats.innerHTML = (state.groups || []).map(g =>
    '<button class="cat' + (g.type === 'pass' ? ' pass' : '') + '" data-cat="' + g.type + '">' +
    '<span>' + esc(g.label) + '</span><span class="count">' + g.count + '</span></button>').join('');
  cats.querySelectorAll('[data-cat]').forEach(button => {
    button.onclick = () => { category = button.dataset.cat; hexFilter = null; renderDock(); drawMap(); };
  });
}

async function submit(pick){
  if (busy) return;
  busy = true;
  try {
    const data = await api('/choose', {pick});
    if (data.ok) {
      category = null; pending = null; hexFilter = null;
      state = data.snapshot;
      renderedAction = state.action_count;
      renderAll();
    } else {
      // Engine refusals and reluctant sellers both come back as ok:false;
      // neither is a reason to restart the table, but that exact offer is dead.
      rejected.add(pick);
      pending = null;
      toast(data.error || '这一步没有被接受');
      if (data.snapshot) { state = data.snapshot; }
      renderDock();
      drawMap();
    }
  } catch (error) {
    toast('提交失败：' + error.message);
  } finally {
    busy = false;
  }
}

async function undoMove(){
  if (busy) return;
  busy = true;
  try {
    const data = await api('/undo', {});
    if (data.ok){
      state = data.snapshot;
      renderedAction = state.action_count;
      category = null; pending = null; hexFilter = null; rejected = new Set();
      renderAll();
      toast('已撤回上一步');
    } else {
      toast(data.error || '撤回失败');
    }
  } catch (error) {
    toast('撤回失败：' + error.message);
  } finally {
    busy = false;
  }
}

async function restartGame(){
  if (!window.confirm('重新开始会放弃当前对局，确定吗？')) return;
  pending = null; category = null; busy = true;
  try {
    if (!params.get('bridge')) {
      await fetch('/api/human/stop', {method:'POST', headers:{'Content-Type':'application/json'}, body:'{}'});
      await fetch('/api/human/start', {method:'POST', headers:{'Content-Type':'application/json'}, body:'{}'});
    }
    renderedAction = -1;
    await poll();
  } catch (error) {
    toast('重新开始失败：' + error.message);
  } finally { busy = false; }
}

/* ---------------- map ---------------- */
const HEX_FILL = {white:'#f7f3e3',yellow:'#e8c96a',green:'#93aa86',brown:'#b78d6b',gray:'#a8aba6',red:'#c47a68',blue:'#a9c6cd'};
const R = 33, SX = Math.sqrt(3) / 2 * R, SY = 1.5 * R;
const HEX_POINTS = Array.from({length:6}, (_, i) => {
  const a = (30 + i * 60) * Math.PI / 180;
  return (R * Math.cos(a)).toFixed(2) + ',' + (R * Math.sin(a)).toFixed(2);
}).join(' ');
function edgePoint(edge, radius){
  const a = (120 + edge * 60) * Math.PI / 180;
  return [radius * Math.cos(a), radius * Math.sin(a)];
}
function cityOffsets(n){
  if (n <= 1) return [[0,0]];
  if (n === 2) return [[-0.42*R,0],[0.42*R,0]];
  if (n === 3) return [[-0.5*R,0.06*R],[0,0.06*R],[0.5*R,0.06*R]];
  if (n === 4) return [[-0.4*R,-0.34*R],[0.4*R,-0.34*R],[-0.4*R,0.38*R],[0.4*R,0.38*R]];
  return Array.from({length:n}, (_, i) => [(i - (n - 1) / 2) * 0.55 * R, 0]);
}
function nodePos(point, cityCount){
  if (point.edge !== undefined) return edgePoint(point.edge, R * Math.sqrt(3) / 2);
  if (point.kind === 'offboard') return [0, 0];
  return cityOffsets(Math.max(cityCount, 1))[point.node] || [0, 0];
}

function legalHexes(){
  if (!category || !state) return new Set();
  return new Set((state.candidates || []).filter(c => c.type === category && c.hex && !rejected.has(c.pick)).map(c => c.hex));
}

let mapKey = '';
function drawMap(){
  if (!state || !state.board) return;
  const hexes = state.board.hexes || [];
  if (!hexes.length) return;
  const key = [state.action_count, category, hexFilter, pending ? pending.pick : -1, rejected.size].join('|');
  if (key === mapKey) return;
  mapKey = key;

  const minX = Math.min(...hexes.map(h => h.x)), minY = Math.min(...hexes.map(h => h.y));
  const maxX = Math.max(...hexes.map(h => h.x)), maxY = Math.max(...hexes.map(h => h.y));
  const pad = 18;
  const width = (maxX - minX) * SX + pad * 2 + SX * 2;
  const height = (maxY - minY) * SY + pad * 2 + SY * 2;
  const svg = $('map');
  svg.setAttribute('viewBox', '0 0 ' + width + ' ' + height);
  svg.setAttribute('preserveAspectRatio', 'xMidYMid meet');
  const at = h => [(h.x - minX) * SX + pad + SX, (h.y - minY) * SY + pad + SY];
  const legal = legalHexes();
  const picked = pending && pending.hex;
  const parts = [];

  for (const h of hexes){
    if (h.hidden) continue;
    const [x, y] = at(h);
    const isLegal = legal.has(h.id);
    const isPicked = picked === h.id;
    const isFiltered = hexFilter === h.id;
    let g = '<g class="hex" data-hex="' + h.id + '" transform="translate(' + x.toFixed(2) + ',' + y.toFixed(2) + ')">';
    g += '<polygon points="' + HEX_POINTS + '" fill="' + (HEX_FILL[h.color] || '#fff') + '" stroke="' +
      (isPicked ? '#c96b1e' : isLegal ? '#c9a227' : isFiltered ? '#7a5a1d' : '#9aa392') + '" stroke-width="' +
      (isPicked ? 3.2 : isLegal ? 2.6 : 1) + '"' + (isLegal && !isPicked ? ' stroke-dasharray="5 3"' : '') + '/>';

    for (const path of (h.paths || [])){
      const a = nodePos(path[0], h.cities.length), b = nodePos(path[1], h.cities.length);
      const both = path[0].edge !== undefined && path[1].edge !== undefined;
      g += '<path d="M' + a[0].toFixed(2) + ',' + a[1].toFixed(2) + ' ' + (both ? 'Q0,0 ' : '') + b[0].toFixed(2) + ',' + b[1].toFixed(2) +
        '" stroke="#3d453c" fill="none" stroke-width="3" stroke-linecap="round" opacity="0.85"/>';
    }
    const offs = cityOffsets(h.cities.length);
    (h.cities || []).forEach((c, i) => {
      const cx = c.anchor !== undefined && c.anchor !== null ? edgePoint(c.anchor, R * 0.44)[0] : (offs[i] || [0,0])[0];
      const cy = c.anchor !== undefined && c.anchor !== null ? edgePoint(c.anchor, R * 0.44)[1] : (offs[i] || [0,0])[1];
      const r = c.slots > 1 ? 11 : 9;
      g += '<circle cx="' + cx + '" cy="' + cy + '" r="' + r + '" fill="#fffdf3" stroke="#39402f" stroke-width="1.2"/>';
      if (c.slots > 1) g += '<circle cx="' + cx + '" cy="' + cy + '" r="' + (r - 3.2) + '" fill="none" stroke="#b9b39a" stroke-width="0.8"/>';
      (c.tokens || []).forEach((t, j) => {
        const dx = cx + (j - (c.tokens.length - 1) / 2) * 7;
        g += '<circle cx="' + dx + '" cy="' + cy + '" r="4.4" fill="' + t.color + '" stroke="#fff" stroke-width="0.8"/>';
      });
      if (!(c.tokens || []).length) g += '<text x="' + cx + '" y="' + (cy + 2.6) + '" font-size="6.4" text-anchor="middle" fill="#37402f">' + c.revenue + '</text>';
      if (c.blocked_by && c.blocked_by.length) g += '<text x="' + cx + '" y="' + (cy + 3.2) + '" font-size="7" text-anchor="middle" fill="#b23a2e">×</text>';
    });
    if (h.offboards && h.offboards.length){
      const o = h.offboards[0];
      g += '<text y="2" text-anchor="middle" font-size="13" font-weight="700" fill="#fff6ec">' + o.revenue + '</text>';
      if (o.bonus) g += '<text y="14" text-anchor="middle" font-size="6.4" fill="#ffe0c9">+' + o.bonus + '</text>';
      if (o.label) g += '<text y="-13" text-anchor="middle" font-size="7" font-weight="700" fill="#fff6ec" letter-spacing="1">' + o.label + '</text>';
    }
    if (h.cost > 20) g += '<g transform="translate(' + (R*0.62).toFixed(1) + ',' + (-R*0.52).toFixed(1) + ')"><rect x="-9" y="-6" width="18" height="11" rx="2" fill="#fff8ec" stroke="#8a5a3b" stroke-width="0.7"/><text y="2" text-anchor="middle" font-size="6.2" fill="#6b4429">$' + h.cost + '</text></g>';
    if (h.label) g += '<g transform="translate(' + (-R*0.55).toFixed(1) + ',' + (-R*0.62).toFixed(1) + ')"><rect x="-8" y="-5.6" width="16" height="11" rx="5.5" fill="#3b4236" opacity="0.88"/><text y="2.4" text-anchor="middle" font-size="6.4" font-weight="700" fill="#fff8e6">' + h.label + '</text></g>';
    g += '<text x="' + (-R*0.78).toFixed(1) + '" y="' + (R*0.92).toFixed(1) + '" font-size="5.6" fill="' + (h.color === 'red' ? '#fff2e6' : '#6b7263') + '">' + h.id + '</text>';
    if (h.location) g += '<text y="' + (R*0.78).toFixed(1) + '" text-anchor="middle" font-size="5.4" fill="' + (h.color === 'red' ? '#fff2e6' : '#5c6553') + '">' + (h.location.length > 16 ? h.location.slice(0, 15) + '…' : h.location) + '</text>';
    g += '</g>';
    parts.push(g);
  }

  if (pending && pending.preview && pending.hex){
    const h = hexes.find(x => x.id === pending.hex);
    if (h){
      const [x, y] = at(h);
      const pv = pending.preview;
      let g = '<g class="ghost" transform="translate(' + x.toFixed(2) + ',' + y.toFixed(2) + ')" pointer-events="none">';
      g += '<polygon points="' + HEX_POINTS + '" fill="' + (HEX_FILL[pv.color] || '#eee') + '" opacity="0.96" stroke="#c96b1e" stroke-width="3"/>';
      for (const path of (pv.paths || [])){
        const a = nodePos(path[0], (pv.cities || []).length), b = nodePos(path[1], (pv.cities || []).length);
        const both = path[0].edge !== undefined && path[1].edge !== undefined;
        g += '<path d="M' + a[0].toFixed(2) + ',' + a[1].toFixed(2) + ' ' + (both ? 'Q0,0 ' : '') + b[0].toFixed(2) + ',' + b[1].toFixed(2) +
          '" stroke="#23291f" fill="none" stroke-width="3.4" stroke-linecap="round"/>';
      }
      const offs = cityOffsets((pv.cities || []).length);
      (pv.cities || []).forEach((c, i) => {
        const anchored = c.anchor !== undefined && c.anchor !== null;
        const cx = anchored ? edgePoint(c.anchor, R * 0.44)[0] : (offs[i] || [0,0])[0];
        const cy = anchored ? edgePoint(c.anchor, R * 0.44)[1] : (offs[i] || [0,0])[1];
        const r = c.slots > 1 ? 11 : 9;
        g += '<circle cx="' + cx + '" cy="' + cy + '" r="' + r + '" fill="#fffdf3" stroke="#23291f" stroke-width="1.3"/>';
        if (c.slots > 1) g += '<circle cx="' + cx + '" cy="' + cy + '" r="' + (r - 3.2) + '" fill="none" stroke="#b9b39a" stroke-width="0.8"/>';
        g += '<text x="' + cx + '" y="' + (cy + 2.6) + '" font-size="6.6" text-anchor="middle" fill="#37402f">' + c.revenue + '</text>';
      });
      (pv.towns || []).forEach((t, i) => {
        const cx = (offs[i] || [0,0])[0], cy = (offs[i] || [0,0])[1];
        g += '<circle cx="' + cx + '" cy="' + cy + '" r="6" fill="#fffdf3" stroke="#23291f" stroke-width="1.2"/>';
        g += '<text x="' + cx + '" y="' + (cy + 2.4) + '" font-size="6" text-anchor="middle" fill="#37402f">' + t.revenue + '</text>';
      });
      if (pv.label) g += '<g transform="translate(' + (-R*0.55).toFixed(1) + ',' + (-R*0.62).toFixed(1) + ')"><rect x="-8" y="-5.6" width="16" height="11" rx="5.5" fill="#3b4236" opacity="0.88"/><text y="2.4" text-anchor="middle" font-size="6.4" font-weight="700" fill="#fff8e6">' + pv.label + '</text></g>';
      g += '<text y="' + (R*0.92).toFixed(1) + '" text-anchor="middle" font-size="6.4" fill="#3b4236" font-weight="700">' + pv.name + ' 号瓦（转 ' + (pending.rotation ?? 0) + '）</text>';
      g += '</g>';
      parts.push(g);
    }
  }

  svg.innerHTML = parts.join('');
  svg.onclick = event => {
    const node = event.target.closest('[data-hex]');
    if (!node) return;
    const id = node.dataset.hex;
    const hex = hexes.find(x => x.id === id);
    showHex(hex);
    const usable = category && (state.candidates || []).some(c => c.type === category && c.hex === id && !rejected.has(c.pick));
    if (usable){
      hexFilter = hexFilter === id ? null : id;
      renderDock();
      drawMap();
    }
  };
}

function showHex(hex){
  if (!hex) return;
  const cities = (hex.cities || []).map(c => '城 ' + c.revenue + '/' + c.slots + ' 位' + ((c.tokens || []).length ? ' · ' + c.tokens.map(t => t.id).join(',') : '')).join('；');
  const offs = (hex.offboards || []).map(o => '外域 ' + o.revenue + (o.bonus ? ' (+' + o.bonus + ')' : '')).join('；');
  $('hextip').textContent = hex.id + ' ' + (hex.location || '') + ' · ' + (HEX_COLOR[hex.color] || hex.color) + '瓦 ' + hex.tile + ' · 铺轨 $' + hex.cost +
    (hex.terrain > 20 ? '（地形 ' + hex.terrain + '）' : '') + (cities ? ' · ' + cities : '') + (offs ? ' · ' + offs : '');
}

/* ---------------- boot ---------------- */
let pollTimer = null;
function startPolling(){
  if (pollTimer) return;
  pollTimer = setInterval(poll, 900);
}
async function bridgeAlive(){
  try {
    const res = await fetch(BRIDGE + '/health', {cache:'no-store'});
    return res.ok;
  } catch (error) {
    return false;
  }
}
async function startNewGame(){
  const res = await fetch('/api/human/start', {method:'POST', headers:{'Content-Type':'application/json'}, body:'{}'});
  const data = await res.json();
  if (!data.started) throw new Error(data.error || '启动失败');
  renderedAction = -1;
  await poll();
}

// Never start a silent new game: if the bridge is gone (a crash or a reload
// after one), ask first — the old table may still be what the player means.
function showStartScreen(message){
  const panel = $('result');
  panel.innerHTML = '<h2>1846 · 人类 vs 2 AI</h2>' +
    '<p class="muted">' + esc(message || '对局服务尚未运行。') + '</p>' +
    '<button id="startNew" style="border:1px solid #6b8494;padding:9px 20px;border-radius:6px;background:#78b06a;color:#0c1a10;font-weight:600">开始新对局</button>';
  panel.classList.remove('hidden');
  $('startNew').onclick = async () => {
    panel.classList.add('hidden');
    try {
      await startNewGame();
      startPolling();
    } catch (error) {
      panel.classList.remove('hidden');
      toast('启动失败：' + error.message);
    }
  };
}
async function boot(){
  if (await bridgeAlive()){
    await poll();
    startPolling();
    return;
  }
  if (params.get('bridge')){
    // An explicit bridge that is down: keep polling until it comes back.
    await poll();
    startPolling();
    return;
  }
  showStartScreen('上一局已经结束，或对局服务没有运行。');
}
$('undo').onclick = () => undoMove();
$('restart').onclick = () => restartGame();
const zoomBtn = $('zoom');
if (zoomBtn){
  zoomBtn.onclick = () => {
    const zoomed = $('mapWrap').classList.toggle('zoom');
    zoomBtn.textContent = zoomed ? '适应窗口' : '放大版图';
    mapKey = '';
    drawMap();
  };
}
window.restartGame = restartGame;
boot();
