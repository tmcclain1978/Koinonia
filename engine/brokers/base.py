from __future__ import annotations
from dataclasses import dataclass
from typing import Protocol, Dict, Any, Optional, Tuple
import time

class BrokerError(Exception):
    pass

class TransientBrokerError(BrokerError):
    pass

class PermanentBrokerError(BrokerError):
    pass

class BrokerAdapter(Protocol):
    def place_order(self, side: str, stake: float, symbol: str, idempotency_key: Optional[str]) -> Dict[str, Any]:
        ...

@dataclass
class RetryPolicy:
    attempts: int = 3
    backoff_sec: float = 0.5

def with_retries(fn, policy: RetryPolicy) -> Tuple[bool, Dict[str, Any] | str]:
    last_err: str = ""
    for i in range(1, policy.attempts + 1):
        try:
            res = fn()
            return True, res
        except TransientBrokerError as e:
            last_err = f"transient:{e}"
            time.sleep(policy.backoff_sec * i)
        except PermanentBrokerError as e:
            return False, f"permanent:{e}"
        except Exception as e:
            last_err = f"unexpected:{e}"
            time.sleep(policy.backoff_sec * i)
    return False, last_err or "failed_after_retries"
