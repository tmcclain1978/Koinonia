from fastapi import APIRouter, Depends, Query
from typing import List, Dict, Any
from .auth import current_user_cookie as current_user
from datetime import datetime, timedelta
import random

router = APIRouter(prefix="/analytics", tags=["analytics"])

@router.get("/ivrank")
def ivrank(symbol: str = Query(..., min_length=1), user=Depends(current_user)):
    """
    Stub: returns IV rank over lookback periods.
    Replace with real vendor calc: IV_rank = (IV_today - IV_min) / (IV_max - IV_min).
    """
    points = []
    today = datetime.utcnow()
    base = random.uniform(0.2, 0.6)
    for i in range(60):
        points.append({"t": (today - timedelta(days=60-i)).isoformat(), "ivr": max(0.0, min(1.0, base + random.uniform(-0.2,0.2)))})
    ivr_today = points[-1]["ivr"]
    return {"symbol": symbol.upper(), "series": points, "ivr_today": ivr_today}

@router.get("/oi-heatmap")
def oi_heatmap(symbol: str = Query(..., min_length=1), user=Depends(current_user)):
    """
    Stub: OI/Vol by strike×expiry for CALL/PUT.
    Replace with real options chain aggregation.
    """
    expiries = ["2025-10-18","2025-11-15","2026-01-17"]
    strikes = [i for i in range(80, 141, 5)]
    grid_call = []
    grid_put = []
    for e in expiries:
        for k in strikes:
            grid_call.append({"expiry": e, "strike": k, "oi": random.randint(50, 5000)})
            grid_put.append({"expiry": e, "strike": k, "oi": random.randint(50, 5000)})
    return {"symbol": symbol.upper(), "expiries": expiries, "strikes": strikes, "call": grid_call, "put": grid_put}

@router.get("/news")
def news(symbol: str = Query(..., min_length=1), user=Depends(current_user)):
    """
    Stub: latest headlines + sentiment (-1..1).
    Swap with vendor + FinBERT scoring if installed.
    """
    sample = [
        {"title": f"{symbol.upper()} announces product update", "url": "#", "published": datetime.utcnow().isoformat(), "sentiment": round(random.uniform(-1,1),2)},
        {"title": f"Analyst upgrades {symbol.upper()}", "url": "#", "published": datetime.utcnow().isoformat(), "sentiment": round(random.uniform(-1,1),2)},
    ]
    return {"symbol": symbol.upper(), "items": sample}

@router.get("/backtest")
def backtest(symbol: str = Query(..., min_length=1), user=Depends(current_user)):
    """
    Stub: daily PnL curve, win rate, avg RR.
    Replace with your real walk-forward harness.
    """
    days = 90
    pnl = 0.0
    curve = []
    for i in range(days):
        ret = random.uniform(-0.03, 0.05)
        pnl = pnl * (1 + ret)
        curve.append({"t": i, "equity": round(10000*(1+pnl),2)})
    return {
        "symbol": symbol.upper(),
        "win_rate": round(random.uniform(0.45,0.65), 2),
        "avg_rr": round(random.uniform(1.5, 3.0), 2),
        "trades": random.randint(30, 120),
        "equity_curve": curve
    }
