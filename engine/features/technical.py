import numpy as np, pandas as pd

def ema(s: pd.Series, n: int) -> pd.Series: return s.ewm(span=n, adjust=False).mean()
def rsi(close: pd.Series, n: int=14) -> pd.Series:
    d = close.diff()
    up, dn = d.clip(lower=0), -d.clip(upper=0)
    rs = up.rolling(n).mean() / dn.rolling(n).mean().replace(0, np.nan)
    return 100 - (100/(1+rs))

def stoch_k(df: pd.DataFrame, n: int=14) -> pd.Series:
    ll = df['low'].rolling(n).min(); hh = df['high'].rolling(n).max()
    return 100 * (df['close']-ll)/(hh-ll)

def make_feats(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["ema9"]  = ema(out["close"], 9)
    out["ema20"] = ema(out["close"], 20)
    out["rsi14"] = rsi(out["close"], 14)
    out["stoch14"] = stoch_k(out, 14)
    out["trend_up"] = (out["ema9"] > out["ema20"]).astype(int)
    return out
