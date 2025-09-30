import os, time, requests
from typing import List, Dict, Any, Optional
POLYGON_API='https://api.polygon.io'
POLYGON_KEY=os.getenv('POLYGON_API_KEY','')

def _get(url, params):
    if not POLYGON_KEY: return None
    p=dict(params or {}); p['apiKey']=POLYGON_KEY
    try:
        r=requests.get(url, params=p, timeout=10)
        if r.status_code!=200: return None
        return r.json()
    except Exception: return None

def get_most_active(limit=100):
    url=f"{POLYGON_API}/v2/snapshot/locale/us/markets/stocks/most-actives"
    js=_get(url,{})
    if js and 'tickers' in js:
        return [{'symbol':t.get('ticker'),'volume':t.get('day',{}).get('v',0)} for t in js['tickers'][:limit]]
    fallback=['SPY','QQQ','IWM','AAPL','NVDA','AMD','MSFT','META','TSLA','AMZN']
    return [{'symbol':s,'volume':0} for s in fallback[:limit]]

def get_snapshot(symbols):
    out={}
    for s in symbols:
        url=f"{POLYGON_API}/v2/snapshot/locale/us/markets/stocks/tickers/{s.upper()}"
        js=_get(url,{})
        if js and 'ticker' in js:
            tk=js['ticker']; bp=tk.get('lastQuote',{}).get('p'); ap=tk.get('lastQuote',{}).get('P')
            spread=None
            try:
                if bp and ap: spread=max(0.0, float(ap)-float(bp))
            except Exception: pass
            out[s]={'price':tk.get('lastTrade',{}).get('p'),'volume':tk.get('day',{}).get('v'),'bid':bp,'ask':ap,'spread':spread}
        time.sleep(0.05)
    return out

def get_aggregates(symbol, timespan='day', limit=60):
    url=f"{POLYGON_API}/v2/aggs/ticker/{symbol.upper()}/range/1/{timespan}/2024-01-01/2026-01-01"
    js=_get(url, {'limit':limit})
    if js and 'results' in js: return js['results'][-limit:]
    return None
