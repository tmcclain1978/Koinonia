import os, requests
from typing import Optional, Dict, Any
UW_TOKEN=os.getenv('UW_TOKEN',''); UW_API=os.getenv('UW_API_URL','https://api.unusualwhales.com')

def get_flow_snapshot(symbol:str)->Optional[Dict[str,Any]]:
    if not UW_TOKEN: return None
    try:
        r=requests.get(f"{UW_API}/v1/flow/{symbol.upper()}", headers={'Authorization':f'Bearer {UW_TOKEN}'}, timeout=10)
        if r.status_code!=200: return None
        return r.json()
    except Exception: return None
