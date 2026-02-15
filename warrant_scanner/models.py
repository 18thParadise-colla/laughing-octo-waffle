from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class AssetSnapshot:
    ticker: str
    close: float
    currency: str
    atr_abs: float
    atr_pct: float
    recent_vol_pct: float
    rsi: float
    score: int
    os_ok: bool
    long_strike: float
    short_strike: float
    reasoning: str


@dataclass
class OptionQuote:
    wkn: str
    name: str
    basispreis: float
    laufzeit: str
    bid: float
    ask: float
    mid: float
    hebel: float
    omega: float
    impl_vola: float
    spread_pct: float
    spread_abs: float
    aufgeld_pct: float
    ausuebung: str
    emittent: str
    detail_url: Optional[str]

    quote_currency: Optional[str] = None
    bezugsverhaeltnis: Optional[float] = None
    restlaufzeit_tage: Optional[int] = None
    break_even: Optional[float] = None


@dataclass
class ScoredOption:
    option: OptionQuote
    days_to_maturity: int

    theta_per_day: float
    theta_pct_per_day: float

    breakeven: Optional[float]
    move_needed_pct: Optional[float]

    intrinsic_value: Optional[float]
    extrinsic_value: Optional[float]
    extrinsic_pct: Optional[float]

    spread_score: int
    omega_score: int
    strike_score: int
    theta_score: int
    vola_score: int
    aufgeld_score: int
    breakeven_score: int
    leverage_score: int

    total_score: float
