from dataclasses import dataclass
from enum import Enum
import time
from typing import Optional, Dict

class Mode(str, Enum):
    DEMO = "demo"
    LIVE = "live"

@dataclass
class RiskLimits:
    max_orders_per_hour: int = 30
    max_daily_loss: float = 0.0  # 0 disables
    max_position: float = 0.0    # 0 disables

class CircuitBreaker(Exception):
    pass

class OrderRouter:
    def __init__(self, mode: Mode = Mode.DEMO, risk: RiskLimits = RiskLimits()):
        self.mode = mode
        self.risk = risk
        self._order_count_window: Dict[int,int] = {}  # epoch_hour -> count
        self._daily_pnl: float = 0.0
        self._idempotency: set[str] = set()

    def _tick_window(self):
        h = int(time.time()//3600)
        self._order_count_window.setdefault(h,0)
        for k in list(self._order_count_window.keys()):
            if k < h-2:
                self._order_count_window.pop(k, None)
        return h

    def can_place(self, stake: float, idemp_key: Optional[str]=None):
        if idemp_key and idemp_key in self._idempotency:
            return False, "duplicate_order"
        h = self._tick_window()
        if self.risk.max_orders_per_hour and self._order_count_window[h] >= self.risk.max_orders_per_hour:
            raise CircuitBreaker("order_rate_exceeded")
        if self.risk.max_position and stake > self.risk.max_position:
            raise CircuitBreaker("stake_exceeds_position_cap")
        if self.risk.max_daily_loss and self._daily_pnl < -abs(self.risk.max_daily_loss):
            raise CircuitBreaker("daily_loss_limit_reached")
        return True, "ok"

    def mark_filled(self, pnl: float, idemp_key: Optional[str]=None):
        h = self._tick_window()
        self._order_count_window[h] += 1
        self._daily_pnl += pnl
        if idemp_key:
            self._idempotency.add(idemp_key)
