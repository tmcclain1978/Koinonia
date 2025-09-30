import os
from typing import List, Dict, Any
from ..utils.http import new_client, with_backoff

class FMPSource:
    def __init__(self):
        self.base = os.getenv("FMP_API_BASE", "https://financialmodelingprep.com")
        self.key  = os.getenv("FMP_API_KEY")
        if not self.key:
            raise RuntimeError("FMP_API_KEY not set")
        self.session = new_client()

    def _params(self, extra=None):
        p = {"apikey": self.key}
        if extra: p.update(extra)
        return p

    def news(self, symbol: str, limit: int = 20) -> List[Dict[str, Any]]:
        # /api/v3/stock_news?tickers=AAPL&limit=50
        url = f"{self.base}/api/v3/stock_news"
        resp = with_backoff(lambda: self.session.get(url, params=self._params({"tickers": symbol.upper(), "limit": limit})))
        resp.raise_for_status()
        js = resp.json()
        return [{"title": n.get("title"), "url": n.get("url"), "published": n.get("publishedDate")} for n in js]

    def earnings_calendar(self, symbol: str):
        url = f"{self.base}/api/v3/earning_calendar"
        resp = with_backoff(lambda: self.session.get(url, params=self._params({"symbol": symbol.upper(), "limit": 10})))
        resp.raise_for_status(); return resp.json()

    def technicals(self, symbol: str, indicator: str = "rsi", period: int = 14):
        # /api/v3/technical_indicator/daily/AAPL?period=14&type=rsi
        url = f"{self.base}/api/v3/technical_indicator/daily/{symbol.upper()}"
        resp = with_backoff(lambda: self.session.get(url, params=self._params({"period": period, "type": indicator})))
        resp.raise_for_status(); return resp.json()
