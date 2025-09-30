import os, asyncio, httpx
from typing import Optional, List
UW_TOKEN=os.getenv('UW_TOKEN',''); UW_API=os.getenv('UW_API_URL','https://api.unusualwhales.com')
def _headers(): return {'Authorization':f'Bearer {UW_TOKEN}'} if UW_TOKEN else {}
async def flow_series(symbol:str, lookback_days:int=20)->Optional[List[float]]:
    if not UW_TOKEN: return None
    url=f"{UW_API}/v1/flow/timeseries/{symbol.upper()}"
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            r=await client.get(url, headers=_headers(), params={'window':lookback_days})
            if r.status_code!=200: return None
            js=r.json() or {}; series=js.get('series') or []
            return [float(x.get('value',0)) for x in series][-lookback_days:] or None
        except Exception: return None
