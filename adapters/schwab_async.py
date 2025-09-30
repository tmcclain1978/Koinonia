import os, asyncio, httpx
SCHWAB_API=os.getenv('SCHWAB_API_URL','https://api.schwabapi.com/trader')
from utils import token_manager as tm

def _headers():
    tok=tm.get_bearer(); h={'Accept':'application/json','Content-Type':'application/json'}
    if tok: h['Authorization']=f'Bearer {tok}'
    return h


async def cancel_order(account_id: str, order_id: str) -> dict:
    url = f"{SCHWAB_API}/accounts/{account_id}/orders/{order_id}"
    async with httpx.AsyncClient(timeout=12) as client:
        r = await client.delete(url, headers=_headers())
        try: js = r.json()
        except Exception: js = {"text": r.text}
        return {"status": r.status_code, "response": js}

async def replace_order(account_id: str, order_id: str, order: dict) -> dict:
    url = f"{SCHWAB_API}/accounts/{account_id}/orders/{order_id}"
    async with httpx.AsyncClient(timeout=12) as client:
        r = await client.put(url, headers=_headers(), json=order)
        try: js = r.json()
        except Exception: js = {"text": r.text}
        return {"status": r.status_code, "response": js}

async def quote_mid(symbol: str, is_option: bool=False) -> dict:
    if not is_option:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"{SCHWAB_API}/marketdata/quotes", headers=_headers(), params={'symbols':symbol})
            if r.status_code != 200:
                return {"bid": None, "ask": None, "mid": None}
            q = r.json().get(symbol.upper(), {})
            bid = q.get('bidPrice') or q.get('quote',{}).get('bidPrice')
            ask = q.get('askPrice') or q.get('quote',{}).get('askPrice')
            mid = (float(bid)+float(ask))/2.0 if bid and ask else None
            return {"bid": bid, "ask": ask, "mid": mid}
    else:
        return {"bid": None, "ask": None, "mid": None}
