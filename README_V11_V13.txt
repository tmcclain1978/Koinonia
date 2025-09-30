V11–V13 Rebase Delta
--------------------
This bundle upgrades your uploaded server.py and charting_pro.js with:
- V11: SSE live stream via /api/chart/stream + in-memory cache (synthetic fallback)
- V12: Indicator plugin registry (BB, %B, ATR, Keltner, Supertrend)
- V13: Multi-pane layout manager (Price / Volume / RSI / MACD) with a resize handle

Files included:
- server.py                  (updated with LiveCache, backfill, SSE endpoint)
- static/js/charting_pro.js  (enhanced with registry, panes, SSE client)

How to apply:
1) Copy these files into your project (or run apply_delta.sh).
2) Ensure your app serves /static/js/charting_pro.js and that your dashboard includes it.
3) Start the server and open the dashboard. You should see multi-pane charts and live updates.

Notes:
- SSE currently uses a 1s synthetic jitter for ticks and tries Schwab price_history for backfill.
- Replace _updater_thread() internals with your Schwab quotes bridge when ready.
