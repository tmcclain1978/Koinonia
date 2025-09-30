(function(){
  const qs = (s, r=document) => r.querySelector(s);
  const qsa = (s, r=document) => Array.from(r.querySelectorAll(s));
  const setText = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };

  // --- Tickers
  const tickersEl = qs('#tickers');
  function parseTickers() {
    const raw = (qs('#ticker-input')?.value || '').split(/[,\s]+/).map(s=>s.trim().toUpperCase()).filter(Boolean);
    const unique = [...new Set(raw)];
    renderChips(unique);
    return unique;
  }
  function renderChips(list){
    if (!tickersEl) return;
    tickersEl.innerHTML = '';
    list.forEach(s => {
      const chip = document.createElement('div'); chip.className = 'chip';
      chip.innerHTML = `${s} <button title="Remove">×</button>`;
      chip.querySelector('button').onclick = () => {
        const cur = parseTickers().filter(x => x !== s);
        qs('#ticker-input').value = cur.join(',');
        renderChips(cur);
      }
      tickersEl.appendChild(chip);
    });
  }

  // --- Signals
  async function loadSignals() {
    const syms = parseTickers();
    if (syms.length === 0) { setText('signals-status','Add at least one symbol'); return; }
    setText('signals-status','Loading…');
    try{
      const url = `/api/ai/options/signals?symbols=${encodeURIComponent(syms.join(','))}`;
      const res = await fetch(url);
      const data = await res.json();
      renderSignals(data);
      setText('signals-status', `Loaded ${syms.length} symbol(s)`);
    }catch(e){
      setText('signals-status', 'Error loading signals');
      console.error(e);
    }
  }
  function renderSignals(data){
    const tbody = qs('#signals-table tbody');
    tbody.innerHTML = '';
    const rows = Array.isArray(data) ? data : (data.rows || data.signals || []);
    rows.forEach(r => {
      const tr = document.createElement('tr');
      const conf = (r.confidence!=null) ? (r.confidence*100).toFixed(1)+'%' : '—';
      tr.innerHTML = `<td>${r.symbol || r.ticker || '—'}</td>
                      <td>${r.signal || r.action || '—'}</td>
                      <td>${conf}</td>
                      <td>${r.updated_at || r.ts || '—'}</td>`;
      tbody.appendChild(tr);
    });
  }

  // --- Backtest
  async function runBacktest(){
    const symbol = qs('#bt-symbol').value.trim().toUpperCase();
    const strategy = qs('#bt-strategy').value;
    const period = qs('#bt-period').value;
    setText('bt-out','Running…');
    try{
      // Minimal generic payload; adjust to your server schema if needed
      const payload = { symbol, strategy, period };
      const res = await fetch('/api/paper/options/simulate', {
        method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify(payload)
      });
      const data = await res.json().catch(()=>({}));
      document.getElementById('bt-out').textContent = JSON.stringify(data, null, 2);
    }catch(e){
      document.getElementById('bt-out').textContent = 'Error running backtest';
      console.error(e);
    }
  }

  // --- Payoff (simple expiry payoff curves)
  function computePayoff(kind, S, K, premium){
    // returns payoff at expiry (not P/L with time)
    if (kind === 'long_call')  return Math.max(S - K, 0) - premium;
    if (kind === 'short_call') return -(Math.max(S - K, 0) - premium);
    if (kind === 'long_put')   return Math.max(K - S, 0) - premium;
    if (kind === 'short_put')  return -(Math.max(K - S, 0) - premium);
    return 0;
  }
  function plotPayoff(){
    const S0 = Number(qs('#pf-price').value || 100);
    const K  = Number(qs('#pf-strike').value || S0);
    const p  = Number(qs('#pf-premium').value || 0);
    const kind = qs('#pf-kind').value;

    const canvas = qs('#payoff');
    const ctx = canvas.getContext('2d');
    const W = canvas.width = canvas.clientWidth || 640;
    const H = canvas.height;

    // x range around S0
    const Smin = Math.max(1, S0*0.5), Smax = S0*1.5;
    const N = 120;
    const xs = Array.from({length:N}, (_,i)=> Smin + (i/(N-1))*(Smax-Smin));
    const ys = xs.map(S => computePayoff(kind, S, K, p));

    // scale
    const ymin = Math.min(...ys), ymax = Math.max(...ys);
    const pad = 24; const x0 = pad; const y0 = H - pad; const x1 = W - pad; const y1 = pad;
    const x = S => x0 + (S - Smin)/(Smax - Smin) * (x1 - x0);
    const y = v => y0 - (v - ymin)/(ymax - ymin) * (y0 - y1);

    // clear
    ctx.clearRect(0,0,W,H);
    // axes
    ctx.strokeStyle = '#294063'; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(x0,y0); ctx.lineTo(x1,y0); ctx.stroke(); // x
    ctx.beginPath(); ctx.moveTo(x0,y0); ctx.lineTo(x0,y1); ctx.stroke(); // y

    // zero line
    const yZero = y(0);
    ctx.strokeStyle = '#3b82f6'; ctx.setLineDash([4,4]);
    ctx.beginPath(); ctx.moveTo(x0,yZero); ctx.lineTo(x1,yZero); ctx.stroke();
    ctx.setLineDash([]);

    // curve
    ctx.strokeStyle = '#8de0ff'; ctx.lineWidth = 2;
    ctx.beginPath();
    xs.forEach((S,i)=> { const yy = y(ys[i]); (i?ctx.lineTo:ctx.moveTo).call(ctx, x(S), yy); });
    ctx.stroke();
  }

  // --- IV/OI Heatmap (built from /api/schwab/chains)
  async function buildHeatmap(){
    const sym = qs('#hm-symbol').value.trim().toUpperCase();
    const res = await fetch('/api/schwab/chains', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ symbol: sym })
    });
    const data = await res.json().catch(()=> ({}));
    renderHeatmap(data);
  }
  function renderHeatmap(data){
    const root = qs('#heatmap');
    root.innerHTML = '';
    // Expect Schwab-like shape; adapt defensively
    const calls = data?.callExpDateMap || {};
    const puts  = data?.putExpDateMap  || {};
    const expiries = Object.keys(calls).length ? Object.keys(calls) : Object.keys(puts);
    const strikes  = expiries.length ? Object.keys(calls[expiries[0]] || puts[expiries[0]] || {}) : [];
    const takeExp = expiries.slice(0, 8); // show first 8 expiries
    // Header
    const grid = document.createElement('div'); grid.className = 'hm-grid';
    grid.appendChild(cell('Strike', 'hm-cell hm-head hm-strike'));
    takeExp.forEach(e => grid.appendChild(cell(e.split(':')[0], 'hm-cell hm-head')));
    // Rows by strike
    strikes.forEach(str => {
      grid.appendChild(cell(str, 'hm-cell hm-strike'));
      takeExp.forEach(e => {
        const chain = (calls[e]?.[str] || puts[e]?.[str] || [])[0] || {};
        const iv = (chain.volatility!=null) ? Number(chain.volatility) : null;
        const oi = (chain.openInterest!=null) ? Number(chain.openInterest) : null;
        const score = colorScale(iv, oi); // 0..1
        const c = document.createElement('div');
        c.className = 'hm-cell';
        c.style.background = `rgba(125, 200, 255, ${0.10 + 0.35*score})`;
        c.style.color = '#e5f0ff';
        c.title = `IV: ${iv ?? '—'}  OI: ${oi ?? '—'}`;
        c.textContent = (iv!=null ? (iv*100).toFixed(0)+'%' : '—');
        grid.appendChild(c);
      });
    });
    root.appendChild(grid);
    function cell(txt, cls){ const d=document.createElement('div'); d.className=cls; d.textContent=txt; return d; }
    function colorScale(iv, oi){
      // simple heuristic: high OI and mid/high IV pop brighter
      const ivn = (iv==null) ? 0 : Math.min(1, Math.max(0, iv)); // if IV already 0..1
      const oin = (oi==null) ? 0 : Math.min(1, Math.log10(1+oi)/5); // normalize OI
      return 0.4*ivn + 0.6*oin;
    }
  }

  // --- Greeks (use your analytics endpoint; display whatever keys exist)
  async function loadGreeks(){
    const sym = qs('#grk-symbol').value.trim().toUpperCase();
    try{
      const res = await fetch(`/api/options/analytics_stats?symbol=${encodeURIComponent(sym)}`);
      const data = await res.json().catch(()=> ({}));
      const tbody = qs('#greeks-table tbody'); tbody.innerHTML='';
      const flat = (data && typeof data==='object') ? data : {};
      Object.keys(flat).forEach(k=>{
        const tr=document.createElement('tr');
        tr.innerHTML=`<td>${k}</td><td>${formatNum(flat[k])}</td>`;
        tbody.appendChild(tr);
      });
    }catch(e){
      console.error(e);
    }
    function formatNum(v){
      if (v==null) return '—';
      if (typeof v==='number') return v.toLocaleString(undefined, {maximumFractionDigits:4});
      return String(v);
    }
  }

  // --- Wire events
  qs('#btn-add')?.addEventListener('click', parseTickers);
  qs('#btn-clear')?.addEventListener('click', () => { qs('#ticker-input').value=''; tickersEl.innerHTML=''; });
  qs('#btn-load')?.addEventListener('click', loadSignals);
  qs('#btn-backtest')?.addEventListener('click', runBacktest);
  qs('#btn-payoff')?.addEventListener('click', plotPayoff);
  qs('#btn-heatmap')?.addEventListener('click', buildHeatmap);
  qs('#btn-greeks')?.addEventListener('click', loadGreeks);

  // initial
  parseTickers(); plotPayoff();

})();

// --- Suggestion Card (engine-backed)
async function fetchSuggestion(){
  const sym = (document.getElementById('sg-symbol')?.value || 'AAPL').trim().toUpperCase();
  const out = document.getElementById('sg-out');
  out.textContent = 'Thinking…';
  try{
    const res = await fetch('/api/ai/suggest', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ symbol: sym })
    });
    const data = await res.json();
    if (!res.ok) { out.textContent = 'Error: ' + (data.detail || res.statusText); return; }

    // Pretty-print a concise suggestion
    const legs = (data.legs || []).map(l => `${l.qty||1} ${l.right} ${l.strike} ${l.expiry}`).join(' + ');
    const lines = [
      `Symbol: ${data.ticker || sym}`,
      `Strategy: ${data.strategy || '—'}`,
      legs ? `Legs: ${legs}` : '',
      data.debit!=null ? `Debit: ${data.debit}` : '',
      data.risk_reward!=null ? `R/R: ${data.risk_reward}` : '',
      data.entry_rule ? `Entry: ${data.entry_rule}` : '',
      data.exits ? `Exits: SL ${data.exits.stop_loss_pct}% · TP ${data.exits.take_profit_pct}% · Time ${data.exits.time_exit_days}d` : '',
      data.context ? `Spot: ${data.context.spot} · IV Rank: ${data.context.iv_rank}` : ''
    ].filter(Boolean);
    out.textContent = lines.join('\n');
  }catch(e){
    out.textContent = 'Engine error.';
    console.error(e);
  }
}
document.getElementById('btn-suggest')?.addEventListener('click', fetchSuggestion);
