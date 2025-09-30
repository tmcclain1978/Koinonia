import os, requests
from typing import Dict, Any, Optional, List
TRADIER_API=os.getenv('TRADIER_API_URL','https://api.tradier.com')
TRADIER_TOKEN=os.getenv('TRADIER_TOKEN','')

def _headers(): return {'Authorization': f'Bearer {TRADIER_TOKEN}', 'Accept':'application/json'}

def get_quotes(symbols: List[str])->Optional[Dict[str,Any]]:
    if not TRADIER_TOKEN: return None
    url=f"{TRADIER_API}/v1/markets/quotes"; params={'symbols':','.join(symbols)}
    try:
        r=requests.get(url, headers=_headers(), params=params, timeout=10)
        if r.status_code!=200: return None
        return r.json()
    except Exception: return None
