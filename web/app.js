'use strict';
const $ = id => document.getElementById(id);
const styles = {balanced:'均衡经营',growth:'留存发展',income:'优先分红',random:'随机基线',lmstudio:'LM Studio',neural:'神经网络'};
const statusNames = {running:'自战中',paused:'已暂停',complete:'已完成',error:'遇到问题',stopped:'已停止',interrupted:'上次中断'};
const actionNames = {bid:'选择私营公司',par:'开办铁路',buy_shares:'买入股票',sell_shares:'出售股份',lay_tile:'铺轨 / 升级',place_token:'设置车站',run_routes:'列车营运',dividend:'分红决策',buy_train:'购买列车',discard_train:'淘汰列车',pass:'结束步骤',buy_company:'收购私营公司',bankrupt:'紧急处置'};
const roundNames = {'Draft Round':'私营公司分配','Stock Round':'股票轮','Operating Round':'营运轮'};
const colorNames = {white:'空白',yellow:'黄',green:'绿',brown:'棕',gray:'灰',red:'外域',blue:'水域'};
const hexFill = {white:'#f7f3e3',yellow:'#e8c96a',green:'#93aa86',brown:'#b78d6b',gray:'#a8aba6',red:'#c47a68',blue:'#a9c6cd'};
const edgeTypeColor = {mountain:'#8a5a3b',water:'#3c6f8f',impassable:'#333'};
let selected=null, replay=null, items=[], latest=null, playTimer=null, busy=false, lastFrameKey='', pollBusy=false;
const esc = value => String(value ?? '').replace(/[&<>"']/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const money = value => '$' + Number(value ?? 0).toLocaleString('en-US');
async function api(path, data){
 const response = await fetch(path, data ? {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)} : {});
 const value=await response.json(); if(!response.ok) throw new Error(value.error || '操作失败'); return value;
}
function notice(s=''){ $('notice').textContent=s; }
function seats(){
 const old=[...$('seats').querySelectorAll('select')].map(x=>x.value);
 $('seats').innerHTML=Array.from({length:Number($('players').value)},(_,i)=>`<label class="seat"><span class="seat-number">${i+1}</span><select aria-label="AI ${i+1} 的策略">${Object.entries(styles).map(([k,v])=>`<option value="${k}" ${k===(old[i] || ['balanced','growth','income','balanced','growth'][i])?'selected':''}>${v}</option>`).join('')}</select></label>`).join('');
}
function config(){return {players:Number($('players').value),seed:Number($('seed').value),strategies:[...$('seats').querySelectorAll('select')].map(e=>e.value),model:$('model').value,count:Number($('count').value)};}
$('players').addEventListener('change',seats); seats();
$('setup').addEventListener('submit',async e=>{e.preventDefault();if(busy)return;busy=true;notice();$('start').disabled=true;try{const r=await api('/api/start',config());await selectRun(r.id);}catch(e){notice(e.message);}finally{busy=false;await refresh();}});
$('batchStart').onclick=async()=>{try{notice();await api('/api/batch',config());await refresh();}catch(e){notice(e.message);}};
$('detect').onclick=async()=>{try{
 const r=await api('/api/models');
 const neural=r.neural||{};
 let html='';
 if(neural.available){
   const online=neural.server&&neural.server.ok;
   html+=`<div class="model-row"><b>神经网络检查点</b><span>latest.pt · 第 ${neural.step||0} 步</span><em class="${online?'ok':'warn'}">${online?'推理服务在线':'推理服务未启动（会自动回退到启发式）'}</em></div>`;
 }else{
   html+='<div class="model-row"><b>神经网络检查点</b><span>尚未生成</span><em class="warn">下一次训练会创建</em></div>';
 }
 const external=(r.providers||[]);
 if(external.length){
   html+=external.map(p=>`<div class="model-row"><b>${esc(p.label)}</b><span>${esc(p.url)}</span><em class="ok">${p.models.length} 个模型</em></div>`).join('');
 }else{
   html+='<div class="model-row"><b>外部语言模型</b><span>未发现</span><em class="muted">可选，不影响自战</em></div>';
 }
 $('modelStatus').innerHTML=html;
 const options=[]; const lm=external.find(p=>p.id==='lmstudio');
 if(lm){ for(const m of (lm.models||[])) options.push({value:m,label:'LM Studio · '+m}); }
 $('model').innerHTML=options.length?options.map(o=>`<option value="${esc(o.value)}">${esc(o.label)}</option>`).join(''):'<option value="">不使用外部模型</option>';
 $('lmstatus').textContent=lm?'已连接 LM Studio；选择「LM Studio」席位时才会调用。':'未发现 LM Studio。Ollama 等其他服务仅作检测提示，当前决策器只接入 LM Studio。启发式与神经网络席位不受影响。';
}catch(e){notice(e.message);}};
async function refresh(){
 const data=await api('/api/runs'); items=data.runs;
 $('start').disabled=!!data.active || !!data.batch.active || busy;
 $('batchStart').disabled=$('start').disabled;
 $('batchStatus').replaceChildren();
 if(data.batch.active){$('batchStatus').textContent=`批量自战 ${data.batch.index} / ${data.batch.total||'∞'} `;const b=document.createElement('button');b.textContent='停止批次';b.className='secondary';b.onclick=async()=>{await api('/api/batch-stop',{});await refresh();};$('batchStatus').append(b);}
 else if(data.batch.error){$('batchStatus').textContent='最近批次：'+data.batch.error;}
 $('history').innerHTML=items.length?items.slice(0,40).map(r=>`<button class="history-item ${r.id===selected?'selected':''}" data-run="${r.id}"><span class="history-main"><span>${r.config.players} 人 · 种子 ${r.config.seed}</span><span>${statusNames[r.status] || r.status}</span></span><small>${new Date(r.created*1000).toLocaleString('zh-CN',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'})} · ${r.action_count || 0} 步${r.elapsed?' · '+Math.round(r.elapsed)+' 秒':''}</small></button>`).join(''):'<p class="muted">暂无对局记录</p>';
 $('history').querySelectorAll('[data-run]').forEach(e=>e.onclick=()=>selectRun(e.dataset.run));
 if(!selected && (data.active || items[0]?.id)) await selectRun(data.active || items[0].id);
 if(data.batch.active && data.batch.current && selected!==data.batch.current && replay===null) await selectRun(data.batch.current);
 if(selected) await updateState();
}
async function selectRun(id){selected=id;replay=null;lastFrameKey='';stopPlay();notice();await updateState();}
async function updateState(){
 const id=selected; if(!id)return;
 const data=await api('/api/state?id='+id); if(id!==selected)return;
 latest=data;
 const r=data.summary;
 $('status').textContent=statusNames[r.status] || r.status;$('status').className='badge '+r.status;
 $('title').textContent=`${r.config.players} 人自战 · 种子 ${r.config.seed}`;
 const winner=r.result?Object.entries(r.result).sort((a,b)=>b[1]-a[1])[0]:null;
 $('subtitle').textContent=r.error || (winner?`本局胜者 AI ${winner[0]} · ${money(winner[1])} · ${r.action_count} 步 · ${Math.round(r.elapsed || 0)} 秒`:`${r.config.strategies.map(s=>styles[s]).join(' / ')} · 自动保存记录`);
 $('timeline').max=Math.max(0,r.frames-1); if(replay===null)$('timeline').value=$('timeline').max;
 $('frameLabel').textContent=`${replay===null?Math.max(0,r.frames-1):replay} / ${Math.max(0,r.frames-1)}`;
 const active=['running','paused'].includes(r.status);
 $('pause').disabled=!active;$('stop').disabled=!active;$('pause').textContent=r.status==='paused'?'继续自战':'暂停自战';
 $('step').disabled=r.status!=='paused';
 $('live').textContent=replay===null?'最新状态':'回到最新';
 const files=[['game.json','对局 JSON'],['transitions.jsonl','训练记录'],['对局日志.txt','文字日志']];
 $('downloads').innerHTML=files.filter(([f])=>f!=='对局日志.txt'||r.status==='complete').map(([f,label])=>`<a href="/api/download?id=${id}&file=${encodeURIComponent(f)}">${label} ↓</a>`).join('');
 if(replay===null && data.state){
  const key=id+':'+data.state.action_count+':'+r.status;
  if(key!==lastFrameKey){render(data);lastFrameKey=key;}
 }
}
function render(frame){
 const s=frame.state;if(!s)return;
 $('round').textContent=`${s.turn} · ${roundNames[s.round] || s.round}${s.round==='Operating Round'?' '+s.round_num:''}`;
 $('phase').textContent=s.phase+(s.tile_slots?(' · '+(s.tile_slots.lay?'可铺':'')+(s.tile_slots.upgrade?'可升级':'')+' '+s.tile_slots.corp):'');$('bank').textContent=money(s.bank);$('actions').textContent=s.action_count;
 const max=Math.max(...s.players.map(p=>p.value),1);
 $('playerCards').innerHTML=s.players.slice().sort((a,b)=>b.value-a.value).map(p=>`<div class="player-card"><div class="player-top"><span class="player-name">${esc(p.name)}<span class="strategy-pill">${esc(styles[p.strategy])}</span></span><span class="wealth">${money(p.value)}</span></div><div class="asset-bar"><i style="width:${100*p.value/max}%"></i></div><div class="player-detail">现金 <b>${money(p.cash)}</b>　${Object.entries(p.shares).filter(([,v])=>v).map(([c,v])=>`<b>${esc(c)}</b> ${v}%`).join(' · ') || '尚未持股'}${p.privates.length?'<br>私营：'+p.privates.map(esc).join('、'):''}</div></div>`).join('');
 $('companies').innerHTML=s.corporations.map(c=>`<tr><td><i class="corp-dot" style="background:${esc(c.color)}"></i>${esc(c.name)}</td><td>${c.owner==='market'?'托管':c.owner?'AI '+esc(c.owner):'未开办'}</td><td>${money(c.cash)}</td><td>${c.price?money(c.price):'—'}</td><td>${c.trains.map(t=>`<span class="train">${esc(t)}</span>`).join('') || '—'}</td><td class="muted">${c.stations.filter(Boolean).map(esc).join(' · ') || '—'}</td><td class="muted">${(c.privates&&c.privates.length)?c.privates.map(x=>esc(x.name)).join('、'):'—'}</td></tr>`).join('');
 const filter=$('companyFilter').value;
 $('companyFilter').innerHTML='<option value="">全部公司</option>'+s.corporations.filter(c=>c.floated).map(c=>`<option value="${esc(c.id)}">${esc(c.id)}</option>`).join('');$('companyFilter').value=filter;
 const d=frame.decision;
 if(d){const a=d.chosen.action;const details=Object.fromEntries(Object.entries(a).filter(([k])=>!['type','entity','entity_type','created_at','id','auto_actions'].includes(k)));
  $('candidateCount').textContent=`${d.candidate_count} 个提议`;
  $('decision').innerHTML=`<div class="decision-entity">${esc(a.entity_type==='player'?'AI '+a.entity:a.entity)} · 第 ${s.action_count} 步</div><div class="decision-type">${esc(actionNames[a.type] || a.type)}</div><p>${esc(d.chosen.reason)}</p>${Object.keys(details).length?`<pre>${esc(JSON.stringify(details,null,2))}</pre>`:''}${d.policy?`<p class="policy-note">${d.policy.source==='lmstudio'?'LM Studio：'+esc(d.policy.reason):'本地模型未返回有效选择，已使用规则机器人。'+esc(d.policy.error)}</p>`:''}${d.rejected?.length?`<p class="policy-note">引擎拒绝 ${d.rejected.length} 个提议后，执行了合法行动。</p>`:''}`;
 }else{$('candidateCount').textContent='开局';$('decision').innerHTML='<p class="placeholder">对局已建立，等待第一个行动。</p>';}
 const logs=frame.logs || [];const nearEnd=$('logs').scrollTop+$('logs').clientHeight >= $('logs').scrollHeight-40;$('logs').innerHTML=logs.map(l=>`<div class="log-line">${esc(l)}</div>`).join('');if(nearEnd || replay!==null)$('logs').scrollTop=$('logs').scrollHeight;
 drawMap(frame);
}
let mapFrame=null;
const R = 33, SX = Math.sqrt(3)/2*R, SY = 1.5*R;
const HEX_POINTS = Array.from({length:6},(_,i)=>{const a=(30+i*60)*Math.PI/180;return (R*Math.cos(a)).toFixed(2)+','+(R*Math.sin(a)).toFixed(2);}).join(' ');
function edgePoint(edge, radius){const a=(120+edge*60)*Math.PI/180;return [radius*Math.cos(a), radius*Math.sin(a)];}
function cityOffsets(n){
 if(n<=1) return [[0,0]];
 if(n===2) return [[-0.42*R,0],[0.42*R,0]];
 if(n===3) return [[-0.5*R,0.06*R],[0,0.06*R],[0.5*R,0.06*R]];
 if(n===4) return [[-0.4*R,-0.34*R],[0.4*R,-0.34*R],[-0.4*R,0.38*R],[0.4*R,0.38*R]];
 return Array.from({length:n},(_,i)=>[(i-(n-1)/2)*0.55*R,0]);
}
function drawMap(frame){
 mapFrame=frame;const board=frame.board;if(!board || !board.hexes || !board.hexes.length)return;
 $('empty').style.display='none';$('map').style.display='block';
 const hexes=board.hexes;
 const minX=Math.min(...hexes.map(h=>h.x)),minY=Math.min(...hexes.map(h=>h.y));
 const maxX=Math.max(...hexes.map(h=>h.x)),maxY=Math.max(...hexes.map(h=>h.y));
 const pad=46, R=33, SX=Math.sqrt(3)/2*R, SY=1.5*R;
 const at=h=>[(h.x-minX)*SX+pad+SX,(h.y-minY)*SY+pad+SY];
 const width=(maxX-minX)*SX+pad*2+SX*2, height=(maxY-minY)*SY+pad*2+SY*2;
 $('map').setAttribute('viewBox','0 0 '+width+' '+height);
 $('map').setAttribute('preserveAspectRatio','xMidYMid meet');
 const highlight=$('companyFilter').value;
 const action=frame.decision && frame.decision.chosen ? frame.decision.chosen.action : null;
 const routeHexes=new Set(action && action.routes ? action.routes.flatMap(r=>r.connections ? r.connections.flat() : []) : []);
 const selectedHex=action ? action.hex : null;
 const parts=[];
 for(const h of hexes){
  if(h.hidden) continue;
  const pos=at(h), x=pos[0], y=pos[1];
  const stroke=h.id===selectedHex?'#dc603c':routeHexes.has(h.id)?'#628b31':'#9aa392';
  let g='<g class="hex" data-hex="'+h.id+'" transform="translate('+x.toFixed(2)+','+y.toFixed(2)+')">';
  g+='<polygon points="'+HEX_POINTS+'" fill="'+(hexFill[h.color]||'#fff')+'" stroke="'+stroke+'" stroke-width="'+(h.id===selectedHex||routeHexes.has(h.id)?2.4:0.7)+'"/>';
  const n=h.cities.length;
  const nodePos=(p)=>{
    if(p.edge!==undefined) return edgePoint(p.edge, R*Math.sqrt(3)/2);
    if(p.kind==='offboard') return [0,0];
    return cityOffsets(Math.max(n,1))[p.node] || [0,0];
  };
  for(const path of h.paths){
    const a=nodePos(path[0]), b=nodePos(path[1]);
    const bothEdges=path[0].edge!==undefined && path[1].edge!==undefined;
    g+='<path d="M'+a[0].toFixed(2)+','+a[1].toFixed(2)+' '+(bothEdges?'Q0,0 ':'')+b[0].toFixed(2)+','+b[1].toFixed(2)+'" stroke="#3d453c" fill="none" stroke-width="3" stroke-linecap="round" opacity="0.85"/>';
  }
  const offs=cityOffsets(n);
  h.cities.forEach((c,i)=>{
    const cx=c.anchor!==undefined && c.anchor!==null ? edgePoint(c.anchor, R*0.44)[0] : offs[i][0];
    const cy=c.anchor!==undefined && c.anchor!==null ? edgePoint(c.anchor, R*0.44)[1] : offs[i][1];
    const r=c.slots>1?11:9;
    const blocked=c.blocked_by && c.blocked_by.length;
    g+='<circle cx="'+cx+'" cy="'+cy+'" r="'+r+'" fill="#fffdf3" stroke="'+(blocked?'#b23a2e':'#39402f')+'" stroke-width="'+(blocked?2:1.2)+'"/>';
    if(c.slots>1) g+='<circle cx="'+cx+'" cy="'+cy+'" r="'+(r-3.2)+'" fill="none" stroke="#b9b39a" stroke-width="0.8"/>';
    c.tokens.forEach((t,j)=>{
      const dx=cx+(j-(c.tokens.length-1)/2)*7;
      g+='<circle cx="'+dx+'" cy="'+cy+'" r="4.2" fill="'+t.color+'" stroke="'+(highlight===t.id?'#ecff94':'#fff')+'" stroke-width="'+(highlight===t.id?2.4:0.8)+'"/>';
    });
    if(!c.tokens.length) g+='<text x="'+cx+'" y="'+(cy+2.6)+'" font-size="6.4" text-anchor="middle" fill="#37402f">'+c.revenue+'</text>';
    if(blocked) g+='<text x="'+cx+'" y="'+(cy+3.2)+'" font-size="7" text-anchor="middle" fill="#b23a2e">×</text>';
  });
  if(h.offboards && h.offboards.length){
    const o=h.offboards[0];
    g+='<text y="2" text-anchor="middle" font-size="13" font-weight="700" fill="#fff6ec">'+o.revenue+'</text>';
    if(o.bonus) g+='<text y="14" text-anchor="middle" font-size="6.4" fill="#ffe0c9">+'+o.bonus+'</text>';
    if(o.label) g+='<text y="-13" text-anchor="middle" font-size="7" font-weight="700" fill="#fff6ec" letter-spacing="1">'+o.label+'</text>';
  }
  if(h.cost>20) g+='<g transform="translate('+(R*0.62).toFixed(1)+','+(-R*0.52).toFixed(1)+')"><rect x="-9" y="-6" width="18" height="11" rx="2" fill="#fff8ec" stroke="#8a5a3b" stroke-width="0.7"/><text y="2" text-anchor="middle" font-size="6.2" fill="#6b4429">$'+h.cost+'</text></g>';
  for(const b of (h.borders||[])){
    if(!b.cost) continue;
    const bp=edgePoint(b.edge, R*0.86);
    const col=edgeTypeColor[b.type] || '#555';
    g+='<g transform="translate('+bp[0].toFixed(1)+','+bp[1].toFixed(1)+')"><circle r="7.2" fill="'+(b.crossed?'#efe6d8':'#fffdf5')+'" stroke="'+col+'" stroke-width="1.1" stroke-dasharray="'+(b.crossed?'2 1.6':'0')+'"/><text y="2.2" text-anchor="middle" font-size="6" fill="'+col+'">'+b.cost+'</text></g>';
  }
  if(h.assignments && h.assignments.length) g+='<circle cx="'+(R*0.55).toFixed(1)+'" cy="'+(R*0.55).toFixed(1)+'" r="4.4" fill="#cf7951" stroke="#fff" stroke-width="0.8"><title>'+h.assignments.join(',')+'</title></circle>';
  if(h.label) g+='<g transform="translate('+(-R*0.55).toFixed(1)+','+(-R*0.62).toFixed(1)+')"><rect x="-8" y="-5.6" width="16" height="11" rx="5.5" fill="#3b4236" opacity="0.88"/><text y="2.4" text-anchor="middle" font-size="6.4" font-weight="700" fill="#fff8e6">'+h.label+'</text></g>';
  g+='<text x="'+(-R*0.78).toFixed(1)+'" y="'+(R*0.92).toFixed(1)+'" font-size="5.6" fill="'+(h.color==='red'?'#fff2e6':'#6b7263')+'">'+h.id+'</text>';
  if(h.location) g+='<text y="'+(R*0.78).toFixed(1)+'" text-anchor="middle" font-size="5.4" fill="'+(h.color==='red'?'#fff2e6':'#5c6553')+'">'+(h.location.length>16?h.location.slice(0,15)+'…':h.location)+'</text>';
  g+='</g>';
  parts.push(g);
 }
 $('map').innerHTML=parts.join('');
 $('map').querySelectorAll('[data-hex]').forEach(el=>el.onclick=()=>{
   const h=hexes.find(q=>q.id===el.dataset.hex);
   const cities=h.cities.map(c=>'城 '+c.revenue+' / '+c.slots+' 位'+(c.tokens.length?' · '+c.tokens.map(t=>t.id).join(','):'')+(c.blocked_by&&c.blocked_by.length?' · 已堵死':'')).join('；');
   const offs=h.offboards.map(o=>'外域 '+o.revenue+(o.bonus?' (+'+o.bonus+')':'')+(o.groups&&o.groups.length?' ['+o.groups.join('/')+']':'')+(o.label?' '+o.label:'')).join('；');
   const brd=(h.borders||[]).filter(b=>b.cost).map(b=>'边'+b.edge+' '+b.type+' $'+b.cost+(b.crossed?'已通':'未通')).join(' ');
   const assigned=(h.assignments&&h.assignments.length)?h.assignments:[];
   let bonusText='';
   if(assigned.length){
     const ports=(h.icons||[]).filter(function(x){return x==='port';}).length;
     const meat=(h.icons||[]).indexOf('meat')>=0, boom=(h.icons||[]).indexOf('boom')>=0;
     const value=ports?20*ports:(meat?30:(boom?20:0));
     bonusText=' · 奖励 '+assigned.join('、')+(value?(' +$'+value):'');
   }
   $('hexInfo').textContent=h.id+' '+(h.location||'')+' · '+(colorNames[h.color]||h.color)+'瓦 '+h.tile+' · 铺轨成本 $'+h.cost+(h.terrain>20?('（山地 '+h.terrain+'）'):'')+' '+brd+' '+cities+' '+offs+bonusText;
 });
 $('tileStock').innerHTML=(board.tile_stock||[]).map(t=>'<span class="stock '+t.color+'" title="'+t.color+' · 城市 '+t.cities+'"><b>'+t.name+'</b>'+(t.unlimited?'∞':t.count)+'</span>').join('');
 $('phaseNote').textContent=board.phase+' 时代 · 可用 '+(board.phase_tiles||[]).map(c=>colorNames[c]||c).join('/')+' · 列车 '+(board.train||'—');
}

$('companyFilter').onchange=()=>mapFrame&&drawMap(mapFrame);
$('mapZoom').onclick=()=>{$('map').classList.toggle('zoom');$('mapZoom').textContent=$('map').classList.contains('zoom')?'适应窗口':'放大地图';};
async function seek(index){if(!selected||!latest?.summary.frames)return;const id=selected;index=Math.max(0,Math.min(index,latest.summary.frames-1));replay=index;const frame=await api(`/api/frame?id=${id}&index=${index}`);if(id!==selected||replay!==index)return;render(frame);$('timeline').value=index;$('frameLabel').textContent=`${index} / ${latest.summary.frames-1}`;$('live').textContent='回到最新';}
function stopPlay(){if(playTimer)clearInterval(playTimer);playTimer=null;$('play').textContent='▶';}
$('timeline').oninput=()=>{stopPlay();seek(Number($('timeline').value)).catch(e=>notice(e.message));};
$('first').onclick=()=>{stopPlay();seek(0);};$('back').onclick=()=>{stopPlay();seek((replay??(latest?.summary.frames-1 || 0))-1);};$('next').onclick=()=>{stopPlay();seek((replay??0)+1);};
$('play').onclick=()=>{if(playTimer){stopPlay();return;}if(!selected)return;if(replay===null)replay=0;$('play').textContent='Ⅱ';let waiting=false;playTimer=setInterval(async()=>{if(waiting)return;if(replay>=latest.summary.frames-1){stopPlay();return;}waiting=true;try{await seek(replay+1);}finally{waiting=false;}},450);};
$('live').onclick=()=>{stopPlay();replay=null;lastFrameKey='';updateState();};
$('pause').onclick=async()=>{try{await api('/api/control',{id:selected,action:latest.summary.status==='paused'?'resume':'pause'});await updateState();}catch(e){notice(e.message);}};
$('stop').onclick=async()=>{try{await api('/api/control',{id:selected,action:'stop'});await refresh();}catch(e){notice(e.message);}};
$('step').onclick=async()=>{try{await api('/api/control',{id:selected,action:'step'});await updateState();}catch(e){notice(e.message);}};
$('refresh').onclick=()=>refresh().catch(e=>notice(e.message));
refresh().catch(e=>notice(e.message));
setInterval(async()=>{if(pollBusy)return;pollBusy=true;try{await refresh();}catch(e){notice('本地服务暂未响应，请检查平台是否仍在运行。');}finally{pollBusy=false;}},1400);
async function refreshTrain(){
 try{
  const t=await api('/api/train'); const s=t.status||{};
  $('trainState').textContent=t.running?(s.continuous?'持续训练中':'训练中'):'已停止';
  $('trainState').className='muted '+(t.running?'live':'');
  $('trainGames').textContent=s.games||0;
  $('trainDecisions').textContent=(s.decisions||0).toLocaleString('en-US');
  $('trainSteps').textContent=s.train_steps||0;
  $('trainLoss').textContent=Number.isFinite(s.loss)?s.loss.toFixed(3):'—';
  $('trainWinrate').textContent=Number.isFinite(s.winrate)?(s.winrate*100).toFixed(0)+'%':'—';
  $('trainStart').disabled=!!t.running; $('trainStop').disabled=!t.running;
  const last=(t.log&&t.log.length)?t.log[t.log.length-1]:null;
  const report=(t.reports&&t.reports.length)?t.reports[0]:null;
  $('trainExtra').innerHTML=[
    '已跑 <b>'+(s.games||0)+'</b> 局',
    '退化 <b>'+(s.degenerate||0)+'</b> 局',
    '速率 <b>'+(s.rate??0)+'</b> 局/分',
    '人类先验 <b>'+(s.human_prior_weight??10)+'</b>',
    last?('损失 <b>'+Number(last.loss||0).toFixed(3)+'</b>'):'',
    report?('<a href="/api/report?file='+encodeURIComponent(report.name)+'" target="_blank">最近分析：'+esc(report.name)+'</a>'):''
  ].filter(Boolean).join(' · ');
  $('trainNote').textContent=last?('最近一步：'+(last.step||0)+' 步 · 样本 '+(last.samples||0)+' · 损失 '+Number(last.loss||0).toFixed(3)+' · 数据文件 '+t.samples):'自战记录写入 train\\data，模型写入 train\\checkpoints\\latest.pt。';
 }catch(e){}
}
$('trainStart').onclick=async()=>{try{await api('/api/train',{action:'start',workers:Number($('trainWorkers').value),minutes:Number($('trainMinutes').value),human_prior_weight:Number($('humanPrior').value)});await refreshTrain();}catch(e){notice(e.message);}};
$('trainStop').onclick=async()=>{try{await api('/api/train',{action:'stop'});await refreshTrain();}catch(e){notice(e.message);}};
$('analyze').onclick=async()=>{try{notice('正在读取自战记录生成分析…');const r=await api('/api/analyze',{});notice(r.report?('分析已生成：'+r.report):'分析已生成');await refreshTrain();}catch(e){notice(e.message);}};
refreshTrain(); setInterval(refreshTrain, 4000);