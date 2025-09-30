CREATE UNIQUE INDEX IF NOT EXISTS idx_candles_symbol_tf_ts ON Candles(symbol, tf, ts);
CREATE UNIQUE INDEX IF NOT EXISTS idx_indicators_symbol_tf_ts_name ON Indicators(symbol, tf, ts, name);
