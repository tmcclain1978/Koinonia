# engine/datasources/polygon.py
from __future__ import annotations
from typing import List, Dict, Any, Optional
import os
import datetime as dt
import requests

from .base import MarketDataSource


class PolygonSource(MarketDataSource):
    def __init__(self):
        self.api_key = os.getenv("POLYGON_API_KEY") or ""
        self.base = os.getenv("POLYGON_API_BASE", "https://api.polygon.io")
        self.session = requests.Session()

    # ---------- helpers ----------
    def _auth_params(self) -> Dict[str, str]:
        return {"apiKey": self.api_key} if self.api_key else {}

    # ---------- optional (we route news via FMP) ----------
    def news(self, symbol: str, lookback_days: int = 2) -> List[Dict[str, Any]]:
        # We use FMP for news via DataRouter; keep empty to satisfy the interface.
        return []

    def corporate_actions(self, symbol: str) -> Dict[str, Any]:
        # Not wired yet. Return empty to satisfy the interface.
        return {}

    # ---------- candles (supports 1D) ----------
    def candles(
        self,
        symbol: str,
        tf: str = "1d",
        lookback: int = 200,
        *,
        timeframe: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Supports both signatures:
          - candles(symbol, tf="1d", lookback=200)
          - candles(symbol, timeframe="1d", limit=200)
        Currently only 1d is implemented.
        """
        tf_eff = (timeframe or tf or "1d").lower()
        lb = int(limit if limit is not None else lookback)
        if tf_eff not in ("1d", "1day", "day", "d"):
            raise NotImplementedError("PolygonSource.candles currently supports 1d only")

        end = dt.datetime.utcnow().date()
        # add cushion for weekends/holidays so we still get `lb` points after slicing
        start = end - dt.timedelta(days=max(5, int(lb * 2.2)))

        url = f"{self.base}/v2/aggs/ticker/{symbol.upper()}/range/1/day/{start}/{end}"
        params = {"adjusted": "true", "sort": "asc", "limit": max(5000, lb)}
        params.update(self._auth_params())

        resp = self.session.get(url, params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json() or {}
        results = data.get("results", []) or []

        out: List[Dict[str, Any]] = []
        for row in results[-lb:]:
            out.append({
                "t": row.get("t"),
                "open": float(row.get("o", 0)),
                "high": float(row.get("h", 0)),
                "low": float(row.get("l", 0)),
                "close": float(row.get("c", 0)),
                "volume": float(row.get("v", 0)),
            })
        return out

    # ---------- options (let DataRouter fall back to FMP) ----------
    def options_chain(self, symbol: str, expiry: Optional[str] = None) -> List[Dict[str, Any]]:
        # Intentionally not implemented here; DataRouter will try Polygon then fall back to FMP.
        raise NotImplementedError("Use FMPSource.options_chain via DataRouter")
