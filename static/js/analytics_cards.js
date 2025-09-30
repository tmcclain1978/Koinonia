// V15: analytics_cards.js — fetch overview KPIs and inject into elements if they exist
(function(){
  async function fetchJSON(url){ const r = await fetch(url); return await r.json(); }
  function setText(sel, v){ const el=document.querySelector(sel); if (el) el.textContent = v; }
  function renderEquity(sel, equity){
    const el=document.querySelector(sel); if (!el) return;
    // lightweight sparkline
    const w=el.clientWidth||240, h=el.clientHeight||48;
    const c=document.createElement('canvas'); c.width=w; c.height=h; el.innerHTML=''; el.appendChild(c);
    const ctx=c.getContext('2d'); ctx.clearRect(0,0,w,h);
    if (!equity || !equity.length) { ctx.fillText('No data', 6, 14); return; }
    const vals=equity.map(p=>p[1]); const min=Math.min(...vals), max=Math.max(...vals);
    const xw = w / (equity.length-1 || 1);
    ctx.beginPath();
    equity.forEach((p,i)=>{
      const x = i*xw;
      const y = h - ( (p[1]-min) / ((max-min)||1) ) * (h-2) - 1;
      i?ctx.lineTo(x,y):ctx.moveTo(x,y);
    });
    ctx.strokeStyle = '#60a5fa'; ctx.stroke();
  }
  async function load(){
    try{
      const j = await fetchJSON('/api/analytics/overview?range=180d');
      if (!j.ok) return;
      const d = j.data;
      setText('#kpiTotalTrades', d.totalTrades);
      setText('#kpiWinRate', (d.winRate||0).toFixed(1)+'%');
      setText('#kpiNetPnL', (d.netPnL||0).toFixed(2));
      setText('#kpiAvgPnL', (d.avgPnL||0).toFixed(2));
      renderEquity('#kpiEquitySpark', d.equity);
    }catch(e){ console.warn('analytics load failed', e); }
  }
  document.addEventListener('DOMContentLoaded', load);
})();