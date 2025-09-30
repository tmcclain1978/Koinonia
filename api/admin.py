from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from .auth import require_role
from .db import SessionLocal
from .models import User

router = APIRouter(prefix="/admin", tags=["admin"])

def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()

class EntitlementsIn(BaseModel):
    trade_enabled: bool | None = None
    can_trade_paper: bool | None = None
    can_trade_live: bool | None = None
    daily_risk_limit_usd: float | None = None
    max_open_contracts: int | None = None
    allowed_symbols_csv: str | None = None

@router.get("/users/{user_id}/entitlements")
def get_entitlements(user_id: int, _=Depends(require_role("admin")), db: Session = Depends(get_db)):
    u = db.query(User).get(user_id)
    if not u: raise HTTPException(404)
    return {
        "user_id": u.id,
        "trade_enabled": u.trade_enabled,
        "can_trade_paper": u.can_trade_paper,
        "can_trade_live": u.can_trade_live,
        "daily_risk_limit_usd": u.daily_risk_limit_usd,
        "max_open_contracts": u.max_open_contracts,
        "allowed_symbols_csv": u.allowed_symbols_csv,
    }

@router.put("/users/{user_id}/entitlements")
def update_entitlements(user_id: int, body: EntitlementsIn, _=Depends(require_role("admin")), db: Session = Depends(get_db)):
    u = db.query(User).get(user_id)
    if not u: raise HTTPException(404)
    for k, v in body.dict(exclude_unset=True).items():
        setattr(u, k, v)
    db.commit()
    return {"ok": True}
