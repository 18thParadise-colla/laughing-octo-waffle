from __future__ import annotations

import logging
import re
from dataclasses import asdict
from datetime import datetime
from typing import Optional

import numpy as np

from warrant_scanner.models import AssetSnapshot, OptionQuote, ScoredOption
from warrant_scanner.util.fx import FxProvider

logger = logging.getLogger(__name__)


def parse_days_to_maturity(maturity_str: str) -> Optional[int]:
    if not maturity_str:
        return None
    maturity_str = maturity_str.strip()
    # common formats: DD.MM.YYYY
    for fmt in ("%d.%m.%Y", "%d.%m.%y"):
        try:
            dt = datetime.strptime(maturity_str, fmt)
            return max(0, (dt - datetime.now()).days)
        except Exception:
            continue

    # fallback: try to find date in string
    m = re.search(r"(\d{2}\.\d{2}\.\d{4})", maturity_str)
    if m:
        try:
            dt = datetime.strptime(m.group(1), "%d.%m.%Y")
            return max(0, (dt - datetime.now()).days)
        except Exception:
            return None
    return None


def _score_spread(spread_pct: float) -> int:
    if spread_pct <= 0.8:
        return 25
    if spread_pct <= 1.2:
        return 20
    if spread_pct <= 1.8:
        return 15
    if spread_pct <= 2.5:
        return 10
    return 5


def _score_omega(omega: float) -> int:
    if 6 <= omega <= 10:
        return 25
    if 4 <= omega <= 12:
        return 20
    if 3 <= omega <= 15:
        return 15
    return 5


def _score_strike(distance_pct: float) -> int:
    if distance_pct <= 0.02:
        return 20
    if distance_pct <= 0.05:
        return 15
    if distance_pct <= 0.10:
        return 10
    return 5


def _score_theta(theta_pct: float) -> int:
    if theta_pct <= 0.5:
        return 15
    if theta_pct <= 1.0:
        return 12
    if theta_pct <= 2.0:
        return 8
    return 3


def _score_vola(impl_vola: float) -> int:
    if 20 <= impl_vola <= 40:
        return 10
    if 15 <= impl_vola <= 50:
        return 7
    return 4


def _score_aufgeld(aufgeld_pct: float) -> int:
    if aufgeld_pct <= 2:
        return 5
    if aufgeld_pct <= 5:
        return 3
    return 1


def _score_breakeven(move_needed_pct: float) -> int:
    if abs(move_needed_pct) <= 3:
        return 10
    if abs(move_needed_pct) <= 5:
        return 8
    if abs(move_needed_pct) <= 8:
        return 5
    return 2


def _score_leverage(hebel: float, premium_abs: float) -> int:
    # heuristic: higher leverage for less paid premium is better
    if premium_abs <= 0:
        return 2
    ratio = hebel / (premium_abs * 100)
    if ratio > 0.5:
        return 5
    if ratio > 0.3:
        return 4
    return 2


def compute_scored_option(
    opt: OptionQuote,
    asset: AssetSnapshot,
    is_call: bool,
    fx: FxProvider,
) -> ScoredOption:
    # days
    days = opt.restlaufzeit_tage
    if not isinstance(days, int) or days <= 0:
        days = parse_days_to_maturity(opt.laufzeit)
    days = int(days) if days is not None else 0

    ratio = opt.bezugsverhaeltnis or 1.0
    if ratio <= 0:
        ratio = 1.0

    # Currency handling
    underlying_ccy = (asset.currency or "").upper() or None
    quote_ccy = (opt.quote_currency or "").upper() or None

    premium_quote_ccy = opt.ask
    premium_underlying_ccy = None
    if underlying_ccy and quote_ccy and underlying_ccy != quote_ccy:
        premium_underlying_ccy = fx.convert(premium_quote_ccy, quote_ccy, underlying_ccy)
    else:
        premium_underlying_ccy = premium_quote_ccy

    # Breakeven in underlying units (best effort)
    breakeven = None
    move_needed = None

    if isinstance(opt.break_even, (int, float)) and opt.break_even and opt.break_even > 0:
        breakeven = float(opt.break_even)
        if asset.close > 0:
            move_needed = ((breakeven - asset.close) / asset.close) * 100 if is_call else ((asset.close - breakeven) / asset.close) * 100
    else:
        if premium_underlying_ccy is not None and asset.close > 0:
            premium_underlying_per_unit = premium_underlying_ccy / ratio
            if is_call:
                breakeven = opt.basispreis + premium_underlying_per_unit
                move_needed = ((breakeven - asset.close) / asset.close) * 100
            else:
                breakeven = opt.basispreis - premium_underlying_per_unit
                move_needed = ((asset.close - breakeven) / asset.close) * 100

    # Intrinsic/extrinsic in quote currency are unreliable if currencies mismatch.
    intrinsic = None
    extrinsic = None
    extrinsic_pct = None

    # only compute intrinsic if we can compare strike/close in same currency
    if underlying_ccy and (underlying_ccy == (asset.currency or "").upper()):
        if is_call:
            intrinsic_underlying = max(0.0, asset.close - opt.basispreis) * ratio
        else:
            intrinsic_underlying = max(0.0, opt.basispreis - asset.close) * ratio

        # convert intrinsic to quote currency if needed
        if quote_ccy and underlying_ccy != quote_ccy:
            intrinsic_quote = fx.convert(intrinsic_underlying, underlying_ccy, quote_ccy)
        else:
            intrinsic_quote = intrinsic_underlying

        if intrinsic_quote is not None:
            intrinsic = intrinsic_quote
            extrinsic = max(0.0, opt.ask - intrinsic)
            extrinsic_pct = (extrinsic / opt.ask * 100) if opt.ask > 0 else None

    # Theta approximation: use extrinsic value decay (coherent units)
    theta_per_day = 0.0
    if days > 0 and extrinsic is not None:
        # accelerate near expiry mildly
        accel = np.sqrt(max(1, days - 1)) / np.sqrt(days)
        theta_per_day = (extrinsic / days) * accel

    theta_pct = (theta_per_day / opt.mid * 100) if opt.mid > 0 else 0.0

    # Scores
    spread_score = _score_spread(opt.spread_pct)
    omega_score = _score_omega(opt.omega)

    target_strike = asset.long_strike if is_call else asset.short_strike
    strike_diff_pct = abs(opt.basispreis - target_strike) / target_strike if target_strike else 1.0
    strike_score = _score_strike(strike_diff_pct)

    theta_score = _score_theta(theta_pct)
    vola_score = _score_vola(opt.impl_vola)
    aufgeld_score = _score_aufgeld(opt.aufgeld_pct)

    breakeven_score = _score_breakeven(move_needed) if move_needed is not None else 0
    leverage_score = _score_leverage(opt.hebel, opt.ask)

    total = float(
        spread_score
        + omega_score
        + strike_score
        + theta_score
        + vola_score
        + aufgeld_score
        + breakeven_score
        + leverage_score
    )

    scored = ScoredOption(
        option=opt,
        days_to_maturity=days,
        theta_per_day=round(theta_per_day, 6),
        theta_pct_per_day=round(theta_pct, 3),
        breakeven=round(breakeven, 4) if breakeven is not None else None,
        move_needed_pct=round(move_needed, 4) if move_needed is not None else None,
        intrinsic_value=round(intrinsic, 6) if intrinsic is not None else None,
        extrinsic_value=round(extrinsic, 6) if extrinsic is not None else None,
        extrinsic_pct=round(extrinsic_pct, 3) if extrinsic_pct is not None else None,
        spread_score=spread_score,
        omega_score=omega_score,
        strike_score=strike_score,
        theta_score=theta_score,
        vola_score=vola_score,
        aufgeld_score=aufgeld_score,
        breakeven_score=breakeven_score,
        leverage_score=leverage_score,
        total_score=round(total, 2),
    )
    logger.debug("Scored option: %s", asdict(scored))
    return scored
