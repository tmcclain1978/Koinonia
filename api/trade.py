# api/trade.py
from __future__ import annotations

from typing import Optional, Literal, Any
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .auth import current_user_cookie as current_user
from .db import SessionLocal
from .models import TradeAudit, User
from .policy import can_execute_trade
from engine.datasources.router import DataRouter

router = APIRouter(prefix="/trade", tags=["trade"])

class TradeIn(BaseModel):
    mode: Literal["paper", "live"] = "paper"     # <- use Literal instead of regex
    suggestion: dict
    risk_usd: float = Field(300.0, ge=0)
    contracts: int = Field(1, ge=1)

class TradeOut(BaseModel):
    status: str
    reason: Optional[str] = None
    provider_response: Optional[dict] = None

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.post("/place", response_model=TradeOut)
def place_trade(body: TradeIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    symbol = (body.suggestion.get("ticker") or "").upper()
    strategy = body.suggestion.get("strategy") or "unknown"

    ok, reason = can_execute_trade(db, user, body.mode, symbol, body.risk_usd, body.contracts)
    status = "accepted" if ok else "rejected"

    # audit
    audit = TradeAudit(
        user_id=user.id, mode=body.mode, symbol=symbol,
        strategy=strategy, risk_usd=body.risk_usd, status=status, reason=reason or ""
    )
    db.add(audit); db.commit()

    if not ok:
        raise HTTPException(status_code=403, detail=reason)

    if body.mode == "paper":
        return TradeOut(status="submitted", provider_response={"paper": True})

    # live: submit to Schwab (stub mapping)
    try:
        router = DataRouter()
        schwab_order = _map_suggestion_to_schwab_order(body.suggestion, body.contracts)
        resp = router.place_order(account_id=_pick_user_account(user), order=schwab_order)
        audit.status = "submitted"; db.commit()
        return TradeOut(status="submitted", provider_response=resp)
    except Exception as e:
        audit.status = "error"; audit.reason = f"broker_error:{e}"; db.commit()
        raise HTTPException(status_code=502, detail="broker_error")

def _pick_user_account(user: User) -> str:
    # TODO: look up user's Schwab account id
    return "YOUR_SCHWAB_ACCOUNT_ID"

def _map_suggestion_to_schwab_order(suggestion: dict, contracts: int) -> dict:
    # TODO: map legs/action/type/strike/expiry to Schwab schema
    legs = suggestion.get("legs", [])
    return {"stub": True, "contracts": contracts, "legs": legs}
