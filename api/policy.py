import os, datetime
from typing import Tuple, Optional
from sqlalchemy.orm import Session
from .models import TradeAudit, User

ENABLE_TRADING = os.getenv("ENABLE_TRADING","false").lower()=="true"

def _today_bounds():
    now = datetime.datetime.utcnow()
    start = datetime.datetime(year=now.year, month=now.month, day=now.day)
    end = start + datetime.timedelta(days=1)
    return start, end

def _user_today_risk(db: Session, user_id: int) -> float:
    start, end = _today_bounds()
    q = db.query(TradeAudit).filter(
        TradeAudit.user_id==user_id,
        TradeAudit.created_at >= start,
        TradeAudit.created_at < end
    )
    # Sum only accepted/submitted paper/live risk; tune to your needs
    total = 0.0
    for row in q.all():
        total += float(row.risk_usd or 0)
    return total

def _count_open_contracts_hint(db: Session, user_id: int) -> int:
    # For a lightweight gate: count today's submitted contracts logged.
    start, end = _today_bounds()
    q = db.query(TradeAudit).filter(
        TradeAudit.user_id==user_id,
        TradeAudit.created_at >= start,
        TradeAudit.created_at < end,
        TradeAudit.status.in_(("submitted","accepted"))
    )
    return q.count()

def can_execute_trade(
    db: Session,
    user: User,
    mode: str,            # 'paper' | 'live'
    symbol: str,
    risk_usd: float,
    contracts: int
) -> Tuple[bool, Optional[str]]:
    # user active?
    if not user.is_active:
        return False, "user_inactive"

    # master toggle
    if not user.trade_enabled:
        return False, "user_trade_disabled"

    # global live switch
    if mode == "live" and not ENABLE_TRADING:
        return False, "live_trading_globally_disabled"

    # per-user mode
    if mode == "live" and not user.can_trade_live:
        return False, "user_live_disabled"
    if mode == "paper" and not user.can_trade_paper:
        return False, "user_paper_disabled"

    # symbol allowlist (optional)
    allowlist = [s.strip().upper() for s in (user.allowed_symbols_csv or "").split(",") if s.strip()]
    if allowlist and symbol.upper() not in allowlist:
        return False, "symbol_not_allowed"

    # risk cap
    used = _user_today_risk(db, user.id)
    if used + risk_usd > float(user.daily_risk_limit_usd or 0):
        return False, f"daily_risk_limit_exceeded:{used:.2f}/{user.daily_risk_limit_usd:.2f}"

    # contract cap
    open_count = _count_open_contracts_hint(db, user.id)
    if (open_count + contracts) > int(user.max_open_contracts or 0):
        return False, "max_open_contracts_exceeded"

    return True, None
