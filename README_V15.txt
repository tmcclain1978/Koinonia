V15 delta — Options workflow polish + Analytics
===============================================

What you get
------------
- API responses standardized via `_api_ok()` / `_api_err()` helpers.
- **POST /api/trade/validate**: normalizes + validates trade payloads (symbol, side, qty, orderType, limitPrice, optional bracket takeProfit/stopLoss), and enforces risk caps `MAX_QTY` and `MAX_NOTIONAL` (env-configurable).
- **GET  /api/analytics/overview?range=90d**: KPIs (total trades, win rate, net/avg PnL, per-strategy stats, equity curve).
- **GET  /api/analytics/equity?range=180d**: equity curve time series.
- **static/js/trade_workflow.js**: drop-in hooks for Validate → Preview → Submit buttons. IDs expected:
  - #symbol, #side, #orderType, #qty or #quantity, #limitPrice (optional), #takeProfit (optional), #stopLoss (optional)
  - Buttons: #btnPreviewTrade, #btnSubmitTrade
  - Output containers (optional): #previewOut, #submitOut
- **static/js/analytics_cards.js**: fetches KPIs and renders a tiny sparkline into #kpiEquitySpark and fills #kpiTotalTrades, #kpiWinRate, #kpiNetPnL, #kpiAvgPnL if present.

How to apply
------------
1) Copy files into your project (or run apply_delta.sh).
2) Ensure the server restarts.
3) Include the JS on your dashboard where appropriate:
   <script src="/static/js/trade_workflow.js"></script>
   <script src="/static/js/analytics_cards.js"></script>

Notes
-----
- Audit files should be JSON Lines under `data/audit/*.jsonl`. Each line: a JSON object with fields like
  ts (epoch or ISO string), pnl (number), symbol, strategy, qty, entry_price, exit_price, side.
  The code is tolerant and will derive pnl if entry/exit present.
- Risk caps default: MAX_QTY=500, MAX_NOTIONAL=250000; override via env vars.
- No breaking changes to your existing preview/submit endpoints — this is additive.
