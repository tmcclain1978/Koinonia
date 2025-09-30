import os, asyncio, httpx
from typing import List, Dict, Any, Optional
POLYGON_API='https://api.polygon.io'
POLYGON_KEY=os.getenv('POLYGON_API_KEY','')
def _params(extra:dict=None)->dict:
    p=dict(extra or {})
    if POLYGON_KEY: p['apiKey']=POLYGON_KEY
    return p
async def most_actives(limit:int=100)->List[str]:
    if not POLYGON_KEY:
        return ['SPY','QQQ','IWM','AAPL','NVDA','AMD','MSFT','META','TSLA','AMZN'][:limit]
    url=f"{POLYGON_API}/v2/snapshot/locale/us/markets/stocks/most-actives"
    async with httpx.AsyncClient(timeout=10) as client:
        r=await client.get(url, params=_params({}))
        if r.status_code!=200:
            return ['SPY','QQQ','IWM','AAPL','NVDA','AMD','MSFT','META','TSLA','AMZN'][:limit]
        js=r.json(); return [t['ticker'] for t in js.get('tickers',[])][:limit]
async def snapshots(symbols: List[str])->Dict[str,Dict[str,Any]]:
    out={}
    async with httpx.AsyncClient(timeout=10) as client:
        async def fetch(sym):
            url=f"{POLYGON_API}/v2/snapshot/locale/us/markets/stocks/tickers/{sym}"
            try:
                r=await client.get(url, params=_params({}))
                if r.status_code!=200: return sym,None
                js=r.json(); tk=js.get('ticker',{}); lq=tk.get('lastQuote',{}); lt=tk.get('lastTrade',{})
                bid=lq.get('p'); ask=lq.get('P'); spread=None
                try:
                    if bid and ask: spread=max(0.0, float(ask)-float(bid))
                except Exception: spread=None
                return sym, {'price': lt.get('p'), 'volume': tk.get('day',{}).get('v'), 'bid': bid, 'ask': ask, 'spread': spread}
            except Exception:
                return sym,None
        tasks=[fetch(s) for s in symbols]
        for coro in asyncio.as_completed(tasks):
            sym,data=await coro
            if data: out[sym]=data
    return out
async def aggregates(symbol:str, timespan='day', limit=60)->Optional[list]:
    url=f"{POLYGON_API}/v2/aggs/ticker/{symbol}/range/1/{timespan}/2024-01-01/2026-01-01"
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            r=await client.get(url, params=_params({'limit':limit}))
            if r.status_code!=200: return None
            js=r.json(); return js.get('results', [])[-limit:]
        except Exception: return None
