from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

import yfinance as yf


@dataclass
class FxRate:
    pair: str
    rate: float
    ts: float


class FxProvider:
    """Very small FX helper based on yfinance.

    We try to convert between currencies using Yahoo tickers like EURUSD=X.
    This is best-effort: if Yahoo doesn't have the pair, we return None.
    """

    def __init__(self, ttl_sec: int = 3600):
        self.ttl_sec = ttl_sec
        self._cache: dict[str, FxRate] = {}

    def _pair_ticker(self, from_ccy: str, to_ccy: str) -> str:
        return f"{from_ccy.upper()}{to_ccy.upper()}=X"

    def get_rate(self, from_ccy: str, to_ccy: str) -> Optional[float]:
        if not from_ccy or not to_ccy:
            return None
        from_ccy = from_ccy.upper()
        to_ccy = to_ccy.upper()
        if from_ccy == to_ccy:
            return 1.0

        pair = self._pair_ticker(from_ccy, to_ccy)
        cached = self._cache.get(pair)
        now = time.time()
        if cached and now - cached.ts < self.ttl_sec:
            return cached.rate

        try:
            df = yf.download(pair, period="5d", interval="1d", progress=False)
            if df is None or df.empty:
                return None
            # yfinance can return multiindex columns
            if hasattr(df.columns, "nlevels") and df.columns.nlevels > 1:
                df.columns = df.columns.get_level_values(0)
            df = df.dropna()
            if df.empty:
                return None
            rate = float(df["Close"].iloc[-1])
            if rate <= 0:
                return None
            self._cache[pair] = FxRate(pair=pair, rate=rate, ts=now)
            return rate
        except Exception:
            return None

    def convert(self, amount: float, from_ccy: str, to_ccy: str) -> Optional[float]:
        rate = self.get_rate(from_ccy, to_ccy)
        if rate is None:
            return None
        return amount * rate
