import os, asyncio, httpx
from typing import Dict, Any, Optional, List
TRADIER_API=os.getenv('TRADIER_API_URL','https://api.tradier.com')
TRADIER_TOKEN=os.getenv('TRADIER_TOKEN','')
def _headers(): return {'Authorization': f'Bearer {TRADIER_TOKEN}', 'Accept':'application/json'}
async def quotes(symbols: List[str])->Optional[Dict[str,Any]]:
    if not TRADIER_TOKEN: return None
    url=f"{TRADIER_API}/v1/markets/quotes"
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            r=await client.get(url, headers=_headers(), params={'symbols':','.join(symbols)})
            if r.status_code!=200: return None
            return r.json()
        except Exception: return None
async def expirations(symbol:str)->List[str]:
    if not TRADIER_TOKEN: return []
    url=f"{TRADIER_API}/v1/markets/options/expirations"
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            r=await client.get(url, headers=_headers(), params={'symbol':symbol,'includeAllRoots':'true','strikes':'false'})
            if r.status_code!=200: return []
            js=r.json() or {}; exps=js.get('expirations',{}).get('date',[])
            return [exps] if isinstance(exps,str) else exps
        except Exception: return []
async def chain(symbol:str, expiration:str, greeks:bool=True)->Optional[Dict[str,Any]]:
    if not TRADIER_TOKEN: return None
    url=f"{TRADIER_API}/v1/markets/options/chains"
    params={'symbol':symbol,'expiration':expiration}
    if greeks: params['greeks']='true'
    async with httpx.AsyncClient(timeout=12) as client:
        try:
            r=await client.get(url, headers=_headers(), params=params)
            if r.status_code!=200: return None
            return r.json()
        except Exception: return None
