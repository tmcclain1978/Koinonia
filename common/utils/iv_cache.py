import os, sqlite3
from typing import Optional, List, Tuple
DB_PATH=os.getenv("IV_DB_PATH","/mnt/data/iv_history.sqlite3")
SCHEMA="""
CREATE TABLE IF NOT EXISTS iv_history (
  symbol TEXT NOT NULL,
  asof TEXT NOT NULL,
  iv REAL NOT NULL,
  PRIMARY KEY (symbol, asof)
);
"""
def _conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    return sqlite3.connect(DB_PATH)
def init():
    conn=_conn()
    with conn: conn.executescript(SCHEMA)
    conn.close()
def insert(symbol:str, asof:str, iv:float):
    conn=_conn()
    with conn: conn.execute("INSERT OR REPLACE INTO iv_history(symbol,asof,iv) VALUES (?,?,?)", (symbol.upper(),asof,float(iv)))
    conn.close()
def series(symbol:str, lookback_days:int=252)->List[Tuple[str,float]]:
    conn=_conn(); cur=conn.cursor()
    cur.execute("SELECT asof, iv FROM iv_history WHERE symbol=? ORDER BY asof ASC", (symbol.upper(),))
    rows=cur.fetchall(); conn.close()
    return rows[-lookback_days:]
def percentile(symbol:str, current_iv:float, lookback_days:int=252)->float:
    rows=series(symbol, lookback_days)
    if not rows: return 0.5
    vals=[v for _,v in rows if v is not None]
    if not vals: return 0.5
    less_eq=sum(1 for v in vals if v<=current_iv)
    return less_eq/len(vals)
def upsert_and_percentile(symbol:str, asof:str, iv:float, lookback_days:int=252)->float:
    insert(symbol, asof, iv)
    return percentile(symbol, iv, lookback_days)
