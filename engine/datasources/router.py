from .polygon import PolygonSource
from .fmp import FMPSource
from .schwab import SchwabSource

class DataRouter:
    def __init__(self):
        self.poly = PolygonSource()
        self.fmp  = FMPSource()

    def candles(self, symbol, timeframe="1d", limit=200):
        try: return self.poly.candles(symbol, timeframe, limit)
        except Exception: return self.fmp.candles(symbol, timeframe, limit)

    def options_chain(self, symbol, expiry=None):
        try: return self.poly.options_chain(symbol, expiry)
        except Exception: return self.fmp.options_chain(symbol, expiry)

    def news(self, symbol, limit=20):
        return self.fmp.news(symbol, limit)
