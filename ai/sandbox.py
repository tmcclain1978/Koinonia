# ai/sandbox.py
from __future__ import annotations
import os, json, math, csv, uuid, threading, time
from datetime import datetime
from typing import List, Dict, Any
from collections import deque

from flask import Blueprint, request, jsonify, send_file
from flask_login import login_required, current_user

from ai.engine import AIEngine
from engine.datasources.integrations.schwab_adapter import SchwabClient

sandbox_bp = Blueprint("sandbox_api", __name__, url_prefix="/api/sandbox")

# ---- lightweight math/helpers (no scipy) ----
def _ndist_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

def _bs_price(S: float, K: float, T_years: float, sigma: float, call_put: str) -> float:
    if S <= 0 or K <= 0 or T_years <= 0 or sigma <= 0: return 0.0
    d1 = (math.log(S / K) + 0.5 * sigma * sigma * T_years) / (sigma * math.sqrt(T_years))
    d2 = d1 - sigma * math.sqrt(T_years)
    if call_put.upper() == "CALL":
        return S * _ndist_cdf(d1) - K * _ndist_cdf(d2)
    else:
        return K * _ndist_cdf(-d2) - S * _ndist_cdf(-d1)

def _annualized_hv(closes: List[float]) -> float:
    if not closes or len(closes) < 22: return 0.0
    rets = [math.log(closes[i]/closes[i-1]) for i in range(1, len(closes))]
    mu = sum(rets)/len(rets)
    var = sum((r-mu)**2 for r in rets)/max(1, len(rets)-1)
    return math.sqrt(var)*math.sqrt(252)

def _ema(vals: List[float], span: int) -> List[float]:
    if not vals: return []
    a = 2/(span+1); out=[vals[0]]
    for v in vals[1:]: out.append(a*v + (1-a)*out[-1])
    return out

def _rsi(vals: List[float], period: int = 14) -> float:
    if len(vals) < period+1: return 50.0
    diffs = [vals[i]-vals[i-1] for i in range(1,len(vals))]
    gains = [max(0,d) for d in diffs]; losses = [max(0,-d) for d in diffs]
    ag = sum(gains[-period:])/period; al = sum(losses[-period:])/period
    if al == 0: return 100.0
    rs = ag/al; return 100 - 100/(1+rs)

def _features_from_window(window: List[Dict[str, Any]]) -> Dict[str, float]:
    closes = [c["close"] for c in window]
    ema9 = _ema(closes, 9)[-1]
    ema20 = _ema(closes, 20)[-1] if len(closes) >= 20 else closes[-1]
    rsi14 = _rsi(closes, 14)
    ret1 = (closes[-1]/closes[-2]-1.0) if len(closes) > 1 else 0.0
    return {"ema9": ema9, "ema20": ema20, "rsi14": rsi14, "ret1": ret1}

# Simple fallback policy if model not provided
def _policy_rule(feats: Dict[str, float]) -> Dict[str, Any]:
    if feats["ema9"] > feats["ema20"] and feats["rsi14"] > 52: return {"type":"SINGLE","side":"CALL"}
    if feats["ema9"] < feats["ema20"] and feats["rsi14"] < 48: return {"type":"SINGLE","side":"PUT"}
    return {"type":"HOLD"}

# AI instance (loads model if AI_MODEL_PATH set)
AI = AIEngine(os.getenv("AI_MODEL_PATH"))

# Storage
_SANDBOX_DIR = "/mnt/data/sandbox_runs"
_sessions: Dict[str, Dict[str, Any]] = {}

def _ensure_dir(p): os.makedirs(p, exist_ok=True)
def _write_jsonl(rows, path):
    with open(path, "w", encoding="utf-8") as f:
        for r in rows: f.write(json.dumps(r, separators=(",",":"))+"\n")
def _write_csv(rows, path):
    if not rows: open(path,"w").close(); return
    headers = sorted({k for r in rows for k in r.keys()})
    import csv
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=headers); w.writeheader()
        for r in rows: w.writerow({k:r.get(k,"") for k in headers})
def _run_sandbox(session_id: str, *, symbol: str, period: str, interval: str,
                 expiry_days: int, policy: str, step: int):
    try:
        sess = _sessions[session_id]
        sess.update({"status":"running","progress":0,"summary":{}})
        out_dir = sess["out_dir"]

        # Which Schwab token/user to use (same default as your adapter)
        uid = getattr(current_user, "id", None) or request.headers.get("X-User-Id") or "demo-user"
        c = SchwabClient(uid)

        # 1) fetch candles
        ph = c.price_history(symbol, period=period, interval=interval)
        candles = [c for c in (ph.get("candles") or []) if c.get("close") is not None]
        if len(candles) < 60:
            sess.update({"status":"error","summary":{"error":"Not enough candles"}}); return

        ts = [int(c.get("datetime") or c.get("time") or 0) for c in candles]
        rows = []; i = 30
        total_steps = len(candles) - (step + 1)
        sess["total"] = total_steps

        while i < len(candles) - step:
            window = candles[i-30:i]
            feats = _features_from_window(window)
            sigma = _annualized_hv([w["close"] for w in window]) or 0.2
            S0 = candles[i]["close"]

            # ---- THIS is where your real AI is called ----
            if policy == "rule":
                action = _policy_rule(feats)
            else:
                action = AI.propose(symbol=symbol, features=feats, spot=S0)

            ep = {
                "session": session_id, "t": ts[i], "symbol": symbol,
                "S0": S0, "features": feats, "action": action,
                "expiry_days": expiry_days, "interval": interval
            }

            # exit after N bars
            exit_idx = i + step
            S1 = candles[exit_idx]["close"]; reward = 0.0

            if action.get("type") == "SINGLE":
                side = action["side"]
                K = round(S0)
                T = max(1e-6, expiry_days/252.0)
                entry = _bs_price(S0, K, T, sigma, side)
                T2 = max(1e-6, (expiry_days - step/390.0)/252.0)  # ~1m bars
                exitp = _bs_price(S1, K, T2, sigma, side)
                pnl = (exitp - entry) * 100.0
                reward = pnl
                ep.update({"K":K, "entry":entry, "exit":exitp, "S1":S1})

            next_feats = _features_from_window(candles[exit_idx-30:exit_idx])
            ep.update({"reward": reward, "next_features": next_feats, "done": False})
            rows.append(ep)

            i += 1
            if i % 25 == 0:
                sess["progress"] = int(100 * (i / (len(candles) - step)))

        # write dataset
        _ensure_dir(out_dir)
        jpath = os.path.join(out_dir, "dataset.jsonl")
        cpath = os.path.join(out_dir, "dataset.csv")
        _write_jsonl(rows, jpath); _write_csv(rows, cpath)

        rewards = [r["reward"] for r in rows]
        wins = sum(1 for r in rewards if r > 0); losses = len(rewards) - wins
        sess.update({"status":"done","progress":100,
                     "summary":{"rows":len(rows),"wins":wins,"losses":losses,
                                "avg_reward": (sum(rewards)/len(rewards)) if rewards else 0.0,
                                "jsonl": jpath, "csv": cpath}})
    except Exception as e:
        _sessions[session_id] = {"status":"error","progress":0,"summary":{"error":str(e)}}

# --------- Endpoints ---------

@sandbox_bp.post("/start")
@login_required
def sandbox_start():
    data = request.get_json(force=True)
    symbol = data.get("symbol","AAPL").upper()
    period = data.get("period","5D"); interval = data.get("interval","1m")
    expiry_days = int(data.get("expiry_days", 7))
    policy = data.get("policy","rule")  # "rule" or "model"
    step = int(data.get("step", 30))

    sid = uuid.uuid4().hex[:12]
    out_dir = os.path.join(_SANDBOX_DIR, f"{sid}_{symbol}_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}")
    _ensure_dir(out_dir)
    _sessions[sid] = {"status":"queued","progress":0,"total":0,"summary":{},"out_dir":out_dir}

    t = threading.Thread(target=_run_sandbox, args=(sid,),
                         kwargs={"symbol":symbol,"period":period,"interval":interval,
                                 "expiry_days":expiry_days,"policy":policy,"step":step},
                         daemon=True)
    t.start()
    return jsonify({"session_id": sid, "status":"started"})

@sandbox_bp.get("/status")
@login_required
def sandbox_status():
    sid = request.args.get("session_id","")
    if sid not in _sessions: return jsonify({"error":"unknown session"}), 404
    s = dict(_sessions[sid])
    # redact file paths -> expose URLs
    if "summary" in s:
        summ = dict(s["summary"])
        if "jsonl" in summ: summ["jsonl_url"] = f"/api/sandbox/download?session_id={sid}&fmt=jsonl"; summ.pop("jsonl",None)
        if "csv" in summ:   summ["csv_url"]   = f"/api/sandbox/download?session_id={sid}&fmt=csv";   summ.pop("csv",None)
        s["summary"] = summ
    return jsonify(s)

@sandbox_bp.get("/download")
@login_required
def sandbox_download():
    sid = request.args.get("session_id",""); fmt = request.args.get("fmt","jsonl")
    if sid not in _sessions: return jsonify({"error":"unknown session"}), 404
    s = _sessions[sid]; path = s["summary"].get("jsonl") if fmt=="jsonl" else s["summary"].get("csv")
    if not path or not os.path.exists(path): return jsonify({"error":"file not ready"}), 404
    name = f"sandbox_{sid}.{fmt}"
    return send_file(path, as_attachment=True, download_name=name)

