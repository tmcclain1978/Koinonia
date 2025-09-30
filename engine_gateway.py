# engine_gateway.py
from __future__ import annotations
import threading
from typing import List, Dict, Any, Optional

class EngineUnavailable(RuntimeError):
    pass

class EngineGateway:
    """
    Thread-safe, lazy-loaded wrapper around your AI engine.
    Replace the import paths and method calls in `_load_engine` and
    the public methods below to match your real engine API.
    """
    _instance: Optional["EngineGateway"] = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._engine = None
        self._loaded = False
        self._load_error: Optional[str] = None
        self._load_engine()

    @classmethod
    def instance(cls) -> "EngineGateway":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    # ---- internal ---------------------------------------------------------
    def _load_engine(self) -> None:
        try:
            # TODO: Adjust these imports to your actual engine modules
            # Examples seen in your codebase: StrategyConfig, PocketOptionsAIEngine, etc.
            from ai.pocket_option_ai_engine import PocketOptionsAIEngine  # <-- adjust if different
            from ai.strategy_config import StrategyConfig                  # <-- adjust if different

            cfg = StrategyConfig()  # or StrategyConfig.from_env()
            self._engine = PocketOptionsAIEngine(cfg)
            self._loaded = True
            self._load_error = None
        except Exception as e:
            self._engine = None
            self._loaded = False
            self._load_error = f"{type(e).__name__}: {e}"

    def _ensure_ready(self) -> None:
        if not self._loaded or self._engine is None:
            raise EngineUnavailable(self._load_error or "engine not loaded")

    # ---- public API -------------------------------------------------------
    def health(self) -> Dict[str, Any]:
        return {
            "loaded": self._loaded,
            "error": self._load_error,
            "engine": type(self._engine).__name__ if self._engine else None,
        }

    def get_option_signals(self, symbols: List[str]) -> List[Dict[str, Any]]:
        """
        Map to your engine’s real inference method.
        Return a JSON-serializable list of signals.
        """
        self._ensure_ready()

        # EXAMPLE ONLY: adapt this to your engine’s method name & return schema
        # For instance, maybe you have: self._engine.signals_for(symbols)
        try:
            # result = self._engine.signals_for(symbols)
            # return result
            # Temporary stand-in if the above method differs:
            out = []
            for s in symbols:
                # Replace with actual engine outputs
                out.append({
                    "symbol": s,
                    "side": "CALL",
                    "confidence": 0.70,
                    "expires_in_min": 15,
                })
            return out
        except Exception as e:
            raise EngineUnavailable(f"Inference failed: {e}")

    def propose_trades(self, symbols: List[str], risk_budget: float) -> List[Dict[str, Any]]:
        """
        Map to your engine’s proposal method.
        """
        self._ensure_ready()
        try:
            # result = self._engine.propose(symbols=symbols, risk_budget=risk_budget)
            # return result
            return [{
                "symbol": s,
                "side": "CALL",
                "size": min(100.0, risk_budget / max(1, len(symbols))),  # example sizing
                "confidence": 0.66,
                "expires_in_min": 15,
            } for s in symbols]
        except Exception as e:
            raise EngineUnavailable(f"Proposal failed: {e}")
