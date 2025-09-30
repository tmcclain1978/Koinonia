from datetime import datetime
from sqlalchemy.orm import declarative_base, Mapped, mapped_column
from sqlalchemy import String, Integer, Boolean, DateTime, Float, Text, ForeignKey

Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(32), default="user")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # --- entitlements / risk ---
    trade_enabled: Mapped[bool] = mapped_column(Boolean, default=False)    # master switch per user
    can_trade_paper: Mapped[bool] = mapped_column(Boolean, default=True)   # allow paper
    can_trade_live: Mapped[bool] = mapped_column(Boolean, default=False)   # allow live
    daily_risk_limit_usd: Mapped[float] = mapped_column(Float, default=300.0)
    max_open_contracts: Mapped[int] = mapped_column(Integer, default=10)
    allowed_symbols_csv: Mapped[str] = mapped_column(Text, default="")     # optional allowlist, e.g. "AAPL,NVDA,SPY"
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class TradeAudit(Base):
    __tablename__ = "trade_audit"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), index=True)
    mode: Mapped[str] = mapped_column(String(8))              # 'paper' | 'live'
    symbol: Mapped[str] = mapped_column(String(16))
    strategy: Mapped[str] = mapped_column(String(64))
    risk_usd: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(32))           # 'accepted','rejected','submitted','error'
    reason: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)