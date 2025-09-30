from abc import ABC, abstractmethod
from typing import List, Dict, Any

class MarketDataSource(ABC):
    @abstractmethod
    def candles(self, symbol: str, tf: str = "1d", lookback: int = 200) -> List[Dict[str, Any]]: ...
    @abstractmethod
    def options_chain(self, symbol: str, expiry: str | None = None) -> List[Dict[str, Any]]: ...
    # Make these optional with safe defaults to prevent abstract class errors
    def news(self, symbol: str, lookback_days: int = 2) -> List[Dict[str, Any]]: return []
    def corporate_actions(self, symbol: str) -> Dict[str, Any]: return {}
