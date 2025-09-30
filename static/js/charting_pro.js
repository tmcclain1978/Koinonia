// charting_pro.js
(function () {
  const elRoot = document.getElementById('chart-root');
  if (!elRoot) {
    console.warn('[charting_pro] #chart-root not found.');
    return;
  }

  const canvas = document.createElement('canvas');
  const ctx = canvas.getContext('2d');
  elRoot.appendChild(canvas);

  function resize() {
    const dpr = Math.max(1, window.devicePixelRatio || 1);
    const rect = elRoot.getBoundingClientRect();
    canvas.style.width = rect.width + 'px';
    canvas.style.height = rect.height + 'px';
    canvas.width = Math.floor(rect.width * dpr);
    canvas.height = Math.floor(rect.height * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    draw();
  }
  window.addEventListener('resize', resize);

  let state = {
    symbol: (document.querySelector('#paper-form [name="symbol"]')?.value || 'AAPL').toUpperCase(),
    tf: '1d',
    type: 'candles',
    overlays: { ema20: false, ema50: false, vwap: false, bbands: false },
    data: [],
    px: { min: 0, max: 1 },
  };

  const symInput = document.querySelector('#paper-form [name="symbol"]');
  symInput?.addEventListener('change', () => {
    state.symbol = (symInput.value || 'AAPL').toUpperCase();
    load();
  });

  window.addEventListener('chart:option', (e) => {
    const { type, value } = e.detail || {};
    if (type === 'timeframe') { state.tf = value; load(); }
    if (type === 'type') { state.type = value; draw(); }
    if (type === 'overlay') {
      if (value && value.key in state.overlays) {
        state.overlays[value.key] = !!value.enabled;
        draw();
      }
    }
  });

  // NEW: auto-reload hooks from paper actions
  const refreshFromEvent = (e) => {
    const d = e.detail || {};
    if (d.symbol) state.symbol = (d.symbol || '').toUpperCase() || state.symbol;
    load();
  };
  window.addEventListener('paper:preview:done', refreshFromEvent);
  window.addEventListener('paper:simulate:done', refreshFromEvent);
  window.addEventListener('paper:place:done', refreshFromEvent);

  // expose manual reload API
  window.ChartingPro = Object.assign(window.ChartingPro || {}, {
    reload: (symbol) => {
      if (symbol) state.symbol = String(symbol).toUpperCase();
      load();
    }
  });

  const TF_TO_INTERVAL = { '1m': '1m', '5m': '5m', '15m': '15m', '1h': '1h', '1d': '1d' };

  async function load() {
    const interval = TF_TO_INTERVAL[state.tf] || '1d';
    try {
      const r = await fetch('/api/candles/history', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symbol: state.symbol, interval, limit: 300 }),
      });
      if (!r.ok) throw new Error(await r.text());
      const payload = await r.json();
      const arr = Array.isArray(payload) ? payload : (payload.candles || []);
      state.data = normalizeCandles(arr);
    } catch (err) {
      console.warn('[charting_pro] history fetch failed, using synthetic data:', err);
      state.data = generateSynthetic();
    }
    draw();
  }

  function normalizeCandles(arr) {
    return arr.map(d => {
      const t = (d.t ?? d.time ?? d.timestamp);
      const o = num(d.o ?? d.open);
      const h = num(d.h ?? d.high);
      const l = num(d.l ?? d.low);
      const c = num(d.c ?? d.close);
      const v = num(d.v ?? d.volume ?? 0);
      return (isFinite(o) && isFinite(h) && isFinite(l) && isFinite(c)) ? { t, o, h, l, c, v } : null;
    }).filter(Boolean);
  }
  function num(x){ const n = typeof x === 'string' ? parseFloat(x) : +x; return isFinite(n) ? n : NaN; }

  function generateSynthetic() {
    const out = []; let price = 100; let t = Date.now() - 300 * 24 * 3600 * 1000;
    for (let i = 0; i < 300; i++) {
      const drift = (Math.random() - 0.5) * 2;
      const o = price, c = Math.max(1, o + drift);
      const h = Math.max(o, c) + Math.random() * 1.2;
      const l = Math.min(o, c) - Math.random() * 1.2;
      out.push({ t, o, h, l, c, v: 1000 + Math.random() * 5000 });
      t += 24 * 3600 * 1000; price = c;
    }
    return out;
  }

  function ema(src, period){ const k=2/(period+1); let prev; return src.map((v,i)=>{ if(v==null)return null; if(i===0||prev==null){prev=v;return v;} const e=v*k+prev*(1-k); prev=e; return e; });}
  function sma(src, p){ const out=[]; let sum=0; for(let i=0;i<src.length;i++){ const v=src[i]; sum+=v??0; if(i>=p) sum-=src[i-p]??0; out[i]=(i>=p-1)?sum/p:null; } return out; }
  function stdev(src,p){ const out=[]; for(let i=0;i<src.length;i++){ if(i<p-1){out[i]=null; continue;} const s=src.slice(i-p+1,i+1); const m=s.reduce((a,b)=>a+b,0)/p; const v=s.reduce((a,b)=>a+(b-m)**2,0)/p; out[i]=Math.sqrt(v);} return out; }
  function computeVWAP(cs){ const out=[]; let pv=0,vv=0; for(let i=0;i<cs.length;i++){ const {h,l,c,v}=cs[i]; const tp=(h+l+c)/3; pv+=tp*(v||0); vv+=(v||0); out[i]=vv>0?pv/vv:null; } return out; }
  function toHeikin(cs){ const out=[]; let prevHAo=null, prevHAc=null; for(const d of cs){ const haC=(d.o+d.h+d.l+d.c)/4; const haO=(prevHAo==null||prevHAc==null)?(d.o+d.c)/2:(prevHAo+prevHAc)/2; const haH=Math.max(d.h,haO,haC); const haL=Math.min(d.l,haO,haC); out.push({t:d.t,o:haO,h:haH,l:haL,c:haC,v:d.v}); prevHAo=haO; prevHAc=haC; } return out; }

  function draw() {
    if (!ctx) return;
    const W = canvas.clientWidth, H = canvas.clientHeight;
    ctx.clearRect(0,0,W,H); fillRect(0,0,W,H,'#0a0f1a');
    if (!state.data || state.data.length < 2) { drawText('No data', W/2-25, H/2, '#94a3b8'); return; }

    const series = state.type === 'heikin' ? toHeikin(state.data) : state.data;
    let min=+Infinity, max=-Infinity;
    for (const d of series){ if (d.l<min) min=d.l; if (d.h>max) max=d.h; }
    const pad=(max-min)*0.05||1; min-=pad; max+=pad; state.px={min,max};

    const L=52, R=20, T=10, B=18;
    const plotW=W-L-R, plotH=H-T-B, x0=L, y0=T;
    drawGrid(x0,y0,plotW,plotH,min,max);

    const N=series.length;
    const xAt=(i)=>x0+(i/(N-1))*plotW;
    const yAt=(p)=>y0+(1-(p-min)/(max-min))*plotH;

    if (state.type==='line') {
      strokePath(()=>{ for(let i=0;i<N;i++){ const x=xAt(i), y=yAt(series[i].c); if(i===0) ctx.moveTo(x,y); else ctx.lineTo(x,y);} }, '#cbd5e1', 1.5);
    } else {
      const w=Math.max(1,(plotW/N)*0.7);
      for(let i=0;i<N;i++){
        const d=series[i]; const x=xAt(i);
        if (state.type==='bars'){
          strokeLine(x,yAt(d.h),x,yAt(d.l),'#64748b',1);
          strokeLine(x-w/2,yAt(d.o),x,yAt(d.o),'#9ca3af',1);
          strokeLine(x,yAt(d.c),x+w/2,yAt(d.c),'#cbd5e1',1);
        } else { // candles
          const up=d.c>=d.o;
          const bodyTop=yAt(Math.max(d.o,d.c));
          const bodyBot=yAt(Math.min(d.o,d.c));
          const bodyH=Math.max(1, bodyBot-bodyTop);
          strokeLine(x,yAt(d.h),x,yAt(d.l),'#475569',1);
          fillRect(x-w/2, bodyTop, w, bodyH, up ? '#22c55e' : '#ef4444');
        }
      }
    }

    const closes = series.map(d=>d.c);
    if (state.overlays.ema20) drawSeries(ema(closes,20), xAt, yAt, '#f59e0b');
    if (state.overlays.ema50) drawSeries(ema(closes,50), xAt, yAt, '#8b5cf6');
    if (state.overlays.vwap)  drawSeries(computeVWAP(series), xAt, yAt, '#38bdf8');
    if (state.overlays.bbands){
      const p=20, mult=2;
      const basis=sma(closes,p), sd=stdev(closes,p);
      const upper=basis.map((b,i)=> (b==null||sd[i]==null)?null:b+mult*sd[i]);
      const lower=basis.map((b,i)=> (b==null||sd[i]==null)?null:b-mult*sd[i]);
      drawSeries(basis,xAt,yAt,'#e5e7eb');
      drawSeries(upper,xAt,yAt,'#94a3b8');
      drawSeries(lower,xAt,yAt,'#94a3b8');
    }

    ctx.fillStyle='#9aa0a6'; ctx.font='12px system-ui,-apple-system,Segoe UI,Roboto,Arial';
    const steps=4;
    for(let i=0;i<=steps;i++){
      const p=min+(i/steps)*(max-min);
      const y=yAt(p);
      ctx.fillText(formatPrice(p),4,y+4);
    }
  }

  function fillRect(x,y,w,h,color){ ctx.fillStyle=color; ctx.fillRect(x,y,w,h); }
  function strokeLine(x1,y1,x2,y2,color,width){ ctx.strokeStyle=color; ctx.lineWidth=width||1; ctx.beginPath(); ctx.moveTo(x1,y1); ctx.lineTo(x2,y2); ctx.stroke(); }
  function strokePath(builder,color,width){ ctx.strokeStyle=color; ctx.lineWidth=width||1; ctx.beginPath(); builder(); ctx.stroke(); }
  function drawText(txt,x,y,color){ ctx.fillStyle=color||'#cbd5e1'; ctx.font='12px system-ui,-apple-system,Segoe UI,Roboto,Arial'; ctx.fillText(txt,x,y); }
  function drawGrid(x,y,w,h){ strokeLine(x,y,x+w,y,'#1f2937',1); strokeLine(x,y+h,x+w,y+h,'#1f2937',1); strokeLine(x,y,x,y+h,'#1f2937',1); strokeLine(x+w,y,x+w,y+h,'#1f2937',1); for(let i=1;i<4;i++){ const yy=y+(i/4)*h; strokeLine(x,yy,x+w,yy,'#162033',1);} }
  function drawSeries(values,xAt,yAt,color){ strokePath(()=>{ for(let i=0;i<values.length;i++){ const v=values[i]; if(v==null) continue; const x=xAt(i), y=yAt(v); if(i===0 || values[i-1]==null) ctx.moveTo(x,y); else ctx.lineTo(x,y);} }, color, 1.5); }
  function formatPrice(p){ if(p>=1000)return p.toFixed(0); if(p>=100)return p.toFixed(1); if(p>=10)return p.toFixed(2); return p.toFixed(3); }

  resize();
  load();
})();
