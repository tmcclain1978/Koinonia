# pocket_option_ai_engine.py
from __future__ import annotations
import os
from typing import Optional, Dict, Any
from ai import AIEngine  # requires ai/__init__.py to export AIEngine

class StrategyConfig(dict):
    """Lightweight stand-in so existing code doesn't break."""
    def __init__(self, **kw): super().__init__(**kw)
    def __getattr__(self, k): return self.get(k)
    def __setattr__(self, k, v): self[k] = v

class PocketOptionsAIEngine:
    def __init__(self, strategy_config: Optional[StrategyConfig] = None, model_path: Optional[str] = None):
        self.config = strategy_config or StrategyConfig()
        self._engine = AIEngine(model_path or os.getenv("AI_MODEL_PATH"))

    def propose(self, *, symbol: str, features: Dict[str, Any], spot: Optional[float] = None) -> Dict[str, Any]:
        """
        Mirrors the API your code already calls. Delegates to our AIEngine.
        Returns: {"type":"HOLD"| "SINGLE", "side"?: "CALL"|"PUT", "confidence": float, ...}
        """
        return self._engine.propose(symbol=symbol, features=features, spot=spot)
