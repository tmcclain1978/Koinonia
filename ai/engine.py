# ai/engine.py
from __future__ import annotations

from typing import Optional, Dict, Any, List
import math

# joblib is optional; we degrade gracefully if it's not available
try:
    import joblib  # type: ignore
except Exception:  # pragma: no cover
    joblib = None  # type: ignore

# Optional numeric helpers
try:
    import numpy as np  # type: ignore
except Exception:       # pragma: no cover
    np = None  # type: ignore

# Keys we expect in `features` when using the heuristic.
# You can tweak this list to match what your fetcher produces.
FEATURE_KEYS: List[str] = [
    "close", "prev_close",
    "ma_fast", "ma_slow",
    "rsi", "macd", "macd_signal",
    "vwap", "atr",
]

class AIEngine:
    """
    Tiny decision engine wrapper.
    - If a scikit-learn model is provided (via `model_path`), we use it.
    - Otherwise, we use a transparent heuristic with sensible defaults.

    Returns actions in this normalized shape:
        {"type": "HOLD", "confidence": float}   OR
        {"type": "SINGLE", "side": "CALL"|"PUT", "confidence": float}
    """

    def __init__(self, model_path: Optional[str] = None):
        self.model = None
        if model_path and joblib:
            try:
                self.model = joblib.load(model_path)  # expects a sklearn-like estimator
            except Exception:
                self.model = None  # fail open to heuristic

    # ---------- public API ----------

    def propose(self, *, symbol: str, features: Optional[Dict[str, Any]] = None,
                spot: Optional[float] = None) -> Dict[str, Any]:
        """
        Decide CALL / PUT / HOLD for `symbol`, using a model if available,
        otherwise a heuristic. `features` is a dict; `spot` is the current price.
        """
        # 1) Model path
        if self.model and features:
            side, conf = self._model_decide(features)
            if side is None:
                return {"type": "HOLD", "confidence": conf}
            return {"type": "SINGLE", "side": side, "confidence": conf}

        # 2) Heuristic path
        side, conf = self._heuristic_decide(features or {}, spot)
        if side is None:
            return {"type": "HOLD", "confidence": conf}
        return {"type": "SINGLE", "side": side, "confidence": conf}

    # ---------- model helpers ----------

    def _vectorize(self, features: Dict[str, Any]):
        """Map dict -> 2D array in FEATURE_KEYS order for sklearn."""
        row = [float(features.get(k, 0.0) or 0.0) for k in FEATURE_KEYS]
        if np is not None:
            return np.array([row], dtype=float)
        # fallback plain list-of-lists still works with many sklearn estimators
        return [row]

    def _model_decide(self, features: Dict[str, Any]) -> (Optional[str], float):
        """
        Use predict_proba if available. We assume binary classification with class 1 ≈ CALL.
        If only predict() is available, use a modest fixed confidence.
        """
        X = self._vectorize(features)

        # predict_proba preferred
        if hasattr(self.model, "predict_proba"):
            try:
                proba = self.model.predict_proba(X)[0]
                # Try to infer class ordering if available; else assume [PUT, CALL]
                call_idx = 1
                if hasattr(self.model, "classes_"):
                    # If model.classes_ look like [0,1] we keep call_idx=1.
                    # If they look like ['CALL','PUT'], pick where 'CALL' is.
                    try:
                        classes = list(getattr(self.model, "classes_"))
                        if "CALL" in classes:
                            call_idx = classes.index("CALL")
                        elif "PUT" in classes and len(classes) == 2:
                            call_idx = 1 - classes.index("PUT")
                    except Exception:
                        pass
                call_p = float(proba[call_idx])
                put_p  = float(1.0 - call_p) if len(proba) == 2 else float(proba[1] if call_idx == 1 else 1.0 - proba[1])
                side = "CALL" if call_p >= put_p else "PUT"
                conf = max(call_p, put_p)
                # small threshold to avoid low-confidence churn
                if conf < 0.55:
                    return None, conf
                return side, conf
            except Exception:
                pass  # fall through to predict()

        # plain predict fallback
        if hasattr(self.model, "predict"):
            try:
                pred = self.model.predict(X)[0]
                # Map common label varieties to CALL/PUT
                label = str(pred).upper()
                if label in ("1", "CALL", "LONG", "BUY", "UP"):
                    return "CALL", 0.65
                if label in ("0", "PUT", "SHORT", "SELL", "DOWN"):
                    return "PUT", 0.65
            except Exception:
                pass

        # If model call failed, fall back to heuristic
        return self._heuristic_decide(features, None)

    # ---------- heuristic ----------

    def _heuristic_decide(self, f: Dict[str, Any], spot: Optional[float]) -> (Optional[str], float):
        """
        Simple, transparent decision rule using common indicators:
        - RSI: >55 call bias; <45 put bias
        - MACD vs signal: >0 call bias; <0 put bias
        - Trend: ma_fast > ma_slow -> call bias; reverse -> put bias
        - Price vs VWAP: above -> call bias; below -> put bias
        - Momentum: day pct change > +0.3% -> call; < -0.3% -> put
        The result is a majority vote with confidence = votes / total_votes.
        """
        votes_call = 0
        votes_put  = 0
        total = 0

        def add_vote(cond_call: bool, cond_put: bool):
            nonlocal votes_call, votes_put, total
            total += 1
            if cond_call and not cond_put:
                votes_call += 1
            elif cond_put and not cond_call:
                votes_put += 1

        rsi = _to_float(f.get("rsi"))
        if rsi is not None:
            add_vote(rsi > 55, rsi < 45)

        macd = _to_float(f.get("macd"))
        macd_sig = _to_float(f.get("macd_signal"))
        if macd is not None:
            add_vote(macd > 0, macd < 0)
        elif macd is None and macd_sig is not None:
            add_vote(macd_sig > 0, macd_sig < 0)

        ma_fast = _to_float(f.get("ma_fast"))
        ma_slow = _to_float(f.get("ma_slow"))
        if ma_fast is not None and ma_slow is not None:
            add_vote(ma_fast > ma_slow, ma_fast < ma_slow)

        close = _to_float(f.get("close"))
        prev_close = _to_float(f.get("prev_close"))
        vwap = _to_float(f.get("vwap"))
        if close is not None and vwap is not None:
            add_vote(close > vwap, close < vwap)

        if close is not None and prev_close is not None and prev_close != 0:
            pct = (close - prev_close) / abs(prev_close) * 100.0
            add_vote(pct > +0.30, pct < -0.30)

        # Decide
        if total == 0:
            return None, 0.5
        if votes_call == votes_put:
            return None, 0.5

        side = "CALL" if votes_call > votes_put else "PUT"
        conf = max(votes_call, votes_put) / float(total)
        return side, float(conf)


# ---------- small util ----------

def _to_float(x: Any) -> Optional[float]:
    try:
        if x is None: return None
        return float(x)
    except Exception:
        return None
