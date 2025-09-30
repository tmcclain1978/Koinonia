# fastapi_app.py
from __future__ import annotations
from typing import List, Optional
from pydantic import BaseModel, Field
from fastapi import FastAPI, HTTPException, Query
import anyio

from engine_gateway import EngineGateway, EngineUnavailable

app = FastAPI(title="AI Advisor FastAPI", version="0.2.0")

# --------- Schemas ----------------------------------------------------------
class OptionSignal(BaseModel):
    symbol: str
    side: str = Field(regex="^(CALL|PUT)$")
    confidence: float = Field(ge=0.0, le=1.0)
    expires_in_min: int = Field(ge=1)

class ProposeRequest(BaseModel):
    symbols: List[str]
    risk_budget: float = Field(default=1000.0, ge=0)

# --------- Helpers ----------------------------------------------------------
async def _get_gateway() -> EngineGateway:
    # Engine may block on first import; run it in a thread to keep FastAPI async
    return await anyio.to_thread.run_sync(EngineGateway.instance)

# --------- Endpoints --------------------------------------------------------
@app.get("/health")
async def health():
    gw = await _get_gateway()
    return gw.health()

@app.get("/ai/options/signals", response_model=List[OptionSignal])
async def get_option_signals(symbols: Optional[str] = Query(None, description="CSV of symbols")):
    gw = await _get_gateway()
    syms = [s.strip().upper() for s in (symbols or "AAPL,MSFT,NVDA").split(",") if s.strip()]
    try:
        # Run blocking engine call in a worker thread
        result = await anyio.to_thread.run_sync(gw.get_option_signals, syms)
        return [OptionSignal(**r) for r in result]
    except EngineUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e))

@app.post("/ai/options/propose", response_model=List[OptionSignal])
async def propose(req: ProposeRequest):
    gw = await _get_gateway()
    syms = [s.strip().upper() for s in req.symbols if s.strip()]
    try:
        result = await anyio.to_thread.run_sync(gw.propose_trades, syms, req.risk_budget)
        # Reuse OptionSignal for simplicity; or create a richer Proposal model with size/price/etc.
        return [OptionSignal(**{k: v for k, v in r.items() if k in OptionSignal.model_fields}) for r in result]
    except EngineUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e))
