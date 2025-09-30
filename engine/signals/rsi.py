import pandas as pd

def compute_rsi(close: pd.Series, period: int = 14) -> pd.Series:
  delta = close.diff()
  up = delta.clip(lower=0).ewm(alpha=1/period, adjust=False).mean()
  down = (-delta.clip(upper=0)).ewm(alpha=1/period, adjust=False).mean()
  rs = up / (down + 1e-9)
  return 100 - (100 / (1 + rs))
