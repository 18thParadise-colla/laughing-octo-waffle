from __future__ import annotations

from dataclasses import asdict

import pandas as pd

from warrant_scanner.models import AssetSnapshot, ScoredOption


def scored_to_frame(scored: list[ScoredOption], asset: AssetSnapshot) -> pd.DataFrame:
    rows = []
    for s in scored:
        o = s.option
        rows.append(
            {
                "ticker": asset.ticker,
                "asset_score": asset.score,
                "asset_close": asset.close,
                "asset_currency": asset.currency,
                **{
                    "wkn": o.wkn,
                    "name": o.name,
                    "basispreis": o.basispreis,
                    "laufzeit": o.laufzeit,
                    "bid": o.bid,
                    "ask": o.ask,
                    "mid": o.mid,
                    "hebel": o.hebel,
                    "omega": o.omega,
                    "impl_vola": o.impl_vola,
                    "spread_pct": o.spread_pct,
                    "aufgeld_pct": o.aufgeld_pct,
                    "emittent": o.emittent,
                    "quote_currency": o.quote_currency,
                    "bezugsverhaeltnis": o.bezugsverhaeltnis,
                },
                **{
                    "days_to_maturity": s.days_to_maturity,
                    "theta_per_day": s.theta_per_day,
                    "theta_pct_per_day": s.theta_pct_per_day,
                    "breakeven": s.breakeven,
                    "move_needed_pct": s.move_needed_pct,
                    "intrinsic_value": s.intrinsic_value,
                    "extrinsic_value": s.extrinsic_value,
                    "extrinsic_pct": s.extrinsic_pct,
                    "spread_score": s.spread_score,
                    "omega_score": s.omega_score,
                    "strike_score": s.strike_score,
                    "theta_score": s.theta_score,
                    "vola_score": s.vola_score,
                    "aufgeld_score": s.aufgeld_score,
                    "breakeven_score": s.breakeven_score,
                    "leverage_score": s.leverage_score,
                    "total_score": s.total_score,
                },
            }
        )

    return pd.DataFrame(rows)
