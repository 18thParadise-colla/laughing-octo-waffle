from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Optional

import pandas as pd
import yfinance as yf

from warrant_scanner.config import ScannerConfig
from warrant_scanner.models import AssetSnapshot
from warrant_scanner.analysis.indicators import (
    calculate_atr,
    calculate_recent_volatility,
    calculate_rsi,
)

logger = logging.getLogger(__name__)


def download_ohlcv(ticker: str, period: str, interval: str) -> pd.DataFrame:
    df = yf.download(ticker, period=period, interval=interval, progress=False)
    if df is None or df.empty:
        return pd.DataFrame()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df.dropna()


def get_ticker_currency(ticker: str) -> str:
    try:
        info = yf.Ticker(ticker).info
        ccy = info.get("currency") or ""
        return str(ccy) if ccy else ""
    except Exception:
        return ""


def check_asset(ticker: str, config: ScannerConfig) -> Optional[AssetSnapshot]:
    df = download_ohlcv(ticker, config.period, config.interval)
    if df.empty or len(df) < config.min_rows:
        return None

    required = {"Open", "High", "Low", "Close", "Volume"}
    if not required.issubset(set(df.columns)):
        return None

    df = df.copy()
    df["SMA20"] = df["Close"].rolling(20).mean()
    df["SMA50"] = df["Close"].rolling(50).mean()
    df["ATR14"] = calculate_atr(df, 14)
    df["ATR5"] = calculate_atr(df, 5)
    df["RSI14"] = calculate_rsi(df, 14)
    df["Vol_Mean"] = df["Volume"].rolling(20).mean()
    df["Recent_Vol"] = calculate_recent_volatility(df, 14)
    df = df.dropna()
    if df.empty:
        return None

    latest = df.iloc[-1]
    prev10 = df.iloc[-11] if len(df) >= 11 else df.iloc[0]

    close = float(latest["Close"])
    sma20 = float(latest["SMA20"])
    sma50 = float(latest["SMA50"])
    atr = float(latest["ATR14"])
    atr_pct = atr / close if close else 0.0
    recent_vol = float(latest["Recent_Vol"])
    rsi = float(latest["RSI14"])
    volume = float(latest["Volume"])
    vol_mean = float(latest["Vol_Mean"])

    atr5 = float(latest["ATR5"])
    long_strike = round(close + atr5 * 1.5, 2)
    short_strike = round(close - atr5 * 1.5, 2)

    score = 0
    reasons: list[str] = []

    # Trend
    if close > sma20 > sma50:
        score += 4
        reasons.append("✔ Aufwärtstrend (Close > SMA20 > SMA50)")
    else:
        reasons.append("✘ Kein sauberer Aufwärtstrend")

    # Momentum w/ RSI confirmation
    if close > float(prev10["Close"]) and 50 < rsi < 70:
        score += 3
        reasons.append(f"✔ Positives Momentum + RSI({rsi:.0f}) bestätigt")
    elif close > float(prev10["Close"]):
        score += 2
        reasons.append(f"⚠ Momentum ok aber RSI({rsi:.0f}) warnt")
    else:
        reasons.append("✘ Momentum nicht bestätigt")

    # Volatility
    if config.atr_pct_min <= atr_pct <= config.atr_pct_max and recent_vol >= 0.8:
        score += 3
        reasons.append(f"✔ ATR ideal + Recent Vol aktiv ({recent_vol:.1f}%)")
    elif config.atr_pct_min <= atr_pct <= config.atr_pct_max:
        score += 2
        reasons.append(f"⚠ ATR ok aber Recent Vol niedrig ({recent_vol:.1f}%)")
    elif atr_pct > config.atr_pct_max:
        score += 1
        reasons.append(f"⚠ Sehr hohe Volatilität ({atr_pct*100:.2f}%)")
    else:
        reasons.append(f"✘ Zu wenig Volatilität ({atr_pct*100:.2f}%)")

    # Volume
    if volume > vol_mean:
        score += 2
        reasons.append("✔ Volumen über Durchschnitt")
    else:
        reasons.append("✘ Volumen unter Durchschnitt")

    # Sideways filter via 15d range
    range_15 = (
        df["High"].rolling(15).max() - df["Low"].rolling(15).min()
    ).iloc[-1] / close

    if range_15 < config.range_15_min:
        score -= 5
        reasons.append("✘ Seitwärtsmarkt (Theta-Gefahr)")
    else:
        reasons.append("✔ Genug Range, kein Seitwärtsmarkt")

    os_ok = score >= 7 and atr_pct >= config.atr_pct_min and range_15 >= config.range_15_min
    reasons.append(
        "✅ OPTIONS-SCHEIN-TAUGLICH" if os_ok else "❌ Nicht optionsschein-tauglich"
    )

    currency = get_ticker_currency(ticker) or ""

    snap = AssetSnapshot(
        ticker=ticker,
        close=round(close, 4),
        currency=currency,
        atr_abs=round(atr, 4),
        atr_pct=round(atr_pct, 6),
        recent_vol_pct=round(recent_vol, 4),
        rsi=round(rsi, 3),
        score=score,
        os_ok=os_ok,
        long_strike=long_strike,
        short_strike=short_strike,
        reasoning=" | ".join(reasons),
    )

    logger.debug("Asset snapshot: %s", asdict(snap))
    return snap
