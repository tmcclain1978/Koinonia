from typing import List, Dict, Any
from adapters import polygon_adapter as poly
from features.compute_features import build_features

def _z(x): return 0.0 if x is None else x

def _tradable(f): return f.get('equity_adv',0)>=5_000_000 and f.get('spread_score',0)>=0.5

def rank(feats: Dict[str,Dict[str,Any]]):
    out=[]
    for sym,f in feats.items():
        if not _tradable(f): continue
        long_iv_bonus=max(0.0,(0.4-f.get('iv_percentile',0.5)))
        score=0.25*_z(f.get('rs_20'))+0.2*_z(f.get('ema_stack'))+0.15*long_iv_bonus+0.25*_z(f.get('flow_z'))+0.15*_z(f.get('spread_score'))
        strat='debit_vertical' if f.get('iv_percentile',0.5)>0.4 else 'long_option'
        rationale=[]
        if f.get('ema_stack',0)>0: rationale.append('Uptrend (stacked EMAs)')
        if f.get('rs_20',0)>0: rationale.append('Positive 20d RS vs SPY')
        if f.get('iv_percentile',0.5)<0.4: rationale.append('Relatively cheap IV')
        if f.get('spread_score',0)>=0.7: rationale.append('Tight spreads')
        out.append({'symbol':sym,'strategy':strat,'score':round(score,3),'rationale':rationale,'suggested_contract':None,'stop_plan':'premium_stop_35pct_or_time_14:30ET','sizing_hint':'risk ≤ 0.5R'})
    return sorted(out, key=lambda x:x['score'], reverse=True)

def generate_picks(n:int=10)->List[Dict[str,Any]]:
    universe=[u['symbol'] for u in poly.get_most_active(limit=100)]
    feats=build_features(universe)
    ranked=rank(feats)
    return ranked[:n]
