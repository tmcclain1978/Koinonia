import os, time, secrets
from flask import Blueprint, redirect, request, jsonify, session
from flask_login import login_required, current_user
from auth.schwab_oauth import build_login_url, exchange_code_for_tokens, refresh_tokens
from models.credentials import db, SchwabCredential
from adapters.schwab_api import SchwabAPI

bp = Blueprint("schwab", __name__)

def _get_cred(user_id):
    return SchwabCredential.query.filter_by(user_id=user_id).first()

def _access_supplier():
    cred = _get_cred(current_user.id)
    return cred.get_access_token()

def _refresh_wrapper():
    cred = _get_cred(current_user.id)
    new_tok = refresh_tokens(cred.get_refresh_token())
    SchwabCredential.upsert(current_user.id, new_tok)

def _api():
    return SchwabAPI(_access_supplier, _refresh_wrapper)

@bp.route("/auth/schwab/login")
@login_required
def schwab_login():
    state = secrets.token_urlsafe(16)
    session["schwab_oauth_state"] = state
    return redirect(build_login_url(state))

@bp.route("/auth/schwab/callback")
@login_required
def schwab_callback():
    if request.args.get("state") != session.get("schwab_oauth_state"):
        return "State mismatch", 400
    code = request.args.get("code")
    if not code:
        return "Missing code", 400
    tok = exchange_code_for_tokens(code)
    SchwabCredential.upsert(current_user.id, tok)
    return redirect("/dashboard")  # or your desired page

# ---- Simple API passthroughs ----

@bp.route("/api/schwab/accounts", methods=["GET"])
@login_required
def api_accounts():
    if not _get_cred(current_user.id):
        return jsonify({"linked": False}), 401
    return jsonify(_api().accounts())

@bp.route("/api/schwab/quotes", methods=["GET"])
@login_required
def api_quotes():
    syms = request.args.get("symbols", "")
    symbols = [s.strip().upper() for s in syms.split(",") if s.strip()]
    if not symbols:
        return jsonify({"error": "symbols required"}), 400
    return jsonify(_api().quotes(symbols))

@bp.route("/api/schwab/order", methods=["POST"])
@login_required
def api_order():
    data = request.get_json() or {}
    account_id = data.get("account_id")
    symbol = data.get("symbol", "AAPL").upper()
    side = data.get("side", "BUY").upper()
    qty = int(data.get("qty", 1))

    order_payload = {
        "orderType": "MARKET",
        "session": "NORMAL",
        "duration": "DAY",
        "orderStrategyType": "SINGLE",
        "orderLegCollection": [{
            "instruction": "BUY" if side == "BUY" else "SELL",
            "quantity": qty,
            "instrument": {"symbol": symbol, "assetType": "EQUITY"}
        }]
    }
    res = _api().place_order(account_id, order_payload)
    return jsonify(res), 201
