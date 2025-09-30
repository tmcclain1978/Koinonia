# candle_routes.py
from __future__ import annotations
from flask import Blueprint, request, jsonify
from flask_login import login_required, current_user
from engine.datasources.integrations.schwab_adapter import SchwabClient

candle_routes = Blueprint("candle_routes", __name__)

@candle_routes.post("/history")
@login_required
def candles_history():
    """
    Body: { "symbol": "AAPL", "period": "5D", "interval": "1m" }
    Pass through to Schwab price history.
    """
    data = request.get_json(force=True) if request.data else {}
    symbol   = (data.get("symbol") or request.args.get("symbol") or "AAPL").upper()
    period   = data.get("period") or request.args.get("period") or "5D"
    interval = data.get("interval") or request.args.get("interval") or "1m"

    uid = getattr(current_user, "id", "demo-user")
    c = SchwabClient(uid)
    resp = c.price_history(symbol, period=period, interval=interval)
    # normalize shape: keep just the candles if present
    return jsonify(resp)

@candle_routes.get("/latest")
@login_required
def candles_latest():
    """
    Quick “last candle” helper using 1D/1m and returning the tail.
    Query: ?symbol=AAPL
    """
    symbol = (request.args.get("symbol") or "AAPL").upper()
    uid = getattr(current_user, "id", "demo-user")
    c = SchwabClient(uid)
    resp = c.price_history(symbol, period="1D", interval="1m")
    candles = resp.get("candles") or []
    last = candles[-1] if candles else None
    return jsonify({"symbol": symbol, "last": last, "count": len(candles)})
