from __future__ import annotations

import argparse
import logging
import time
from math import floor

import pandas as pd

from warrant_scanner.config import ScannerConfig
from warrant_scanner.analysis.assets import check_asset
from warrant_scanner.onvista.client import OnvistaClient
from warrant_scanner.onvista.details import enrich_with_details
from warrant_scanner.reporting.export import scored_to_frame
from warrant_scanner.scoring.option_scoring import compute_scored_option
from warrant_scanner.util.fx import FxProvider
from warrant_scanner.util.logging_utils import setup_logging

logger = logging.getLogger(__name__)

MAX_TOTAL_SCORE = 115
MAX_ASSET_SCORE = 12


def _fmt_num(value: float | None, digits: int = 2) -> str:
    if value is None or pd.isna(value):
        return "n/a"
    return f"{float(value):.{digits}f}"


def _safe_float(value: object, fallback: float = 0.0) -> float:
    if value is None or pd.isna(value):
        return fallback
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _build_stakeholder_info(row: pd.Series) -> str:
    reasons: list[str] = []
    if _safe_float(row.get("spread_pct")) <= 0.8:
        reasons.append("enger Spread für saubere Ausführung")
    if _safe_float(row.get("theta_pct_per_day")) <= 5:
        reasons.append("geringer Zeitwertverlust")
    if abs(_safe_float(row.get("move_needed_pct"))) <= 3:
        reasons.append("Break-even mit kleiner Bewegung erreichbar")

    if not reasons:
        reasons.append("ausgewogenes Chancen/Risiko-Profil")

    return (
        f"Fokus auf {row['ticker']} mit WKN {row['wkn']} "
        f"({', '.join(reasons)})."
    )


def _print_console_summary(df: pd.DataFrame, option_type: str, budget_eur: float = 200.0) -> None:
    if df.empty:
        return

    is_call = option_type.lower() == "call"
    top = df.iloc[0]

    asset_close = _safe_float(top.get("asset_close"))
    strike = _safe_float(top.get("basispreis"))
    entry = _safe_float(top.get("mid"))
    if entry <= 0:
        entry = _safe_float(top.get("ask"))

    spread_pct = _safe_float(top.get("spread_pct"))
    omega = _safe_float(top.get("omega"))
    leverage = _safe_float(top.get("hebel"))
    impl_vol = _safe_float(top.get("impl_vola"))
    aufgeld = _safe_float(top.get("aufgeld_pct"))
    theta_abs = _safe_float(top.get("theta_per_day"))
    theta_pct = _safe_float(top.get("theta_pct_per_day"))
    move_needed = _safe_float(top.get("move_needed_pct"))
    intrinsic = _safe_float(top.get("intrinsic_value"))
    extrinsic = _safe_float(top.get("extrinsic_value"))
    extrinsic_pct = _safe_float(top.get("extrinsic_pct"))
    breakeven = top.get("breakeven")
    days = int(_safe_float(top.get("days_to_maturity"), 0))

    strike_dev = abs(strike - asset_close) / asset_close * 100 if asset_close > 0 else 0.0
    pieces = floor(budget_eur / entry) if entry > 0 else 0
    cost = pieces * entry
    rest = budget_eur - cost
    stop = entry * 0.9
    risk = pieces * (entry - stop)

    ratio = _safe_float(top.get("bezugsverhaeltnis"), 1.0) or 1.0

    def _pl(move_pct: float) -> float:
        if asset_close <= 0:
            return 0.0
        scenario_close = asset_close * (1 + move_pct / 100)
        if is_call:
            scenario_intrinsic = max(0.0, scenario_close - strike) * ratio
        else:
            scenario_intrinsic = max(0.0, strike - scenario_close) * ratio
        return scenario_intrinsic - entry

    scenario_1 = move_needed
    scenario_2 = move_needed + 2.0
    scenario_3 = move_needed + 5.0

    print("─" * 76)
    print(f"   Gesamt-Score: {int(_safe_float(top.get('total_score'))):d}/{MAX_TOTAL_SCORE} ⭐")
    print(
        f"   Strike: {_fmt_num(strike, 1)} | Kurs: {_fmt_num(asset_close, 3)} EUR | "
        f"Abweichung: {_fmt_num(strike_dev, 1)}%"
    )
    print(
        f"   Omega: {_fmt_num(omega, 1)} | Hebel: {_fmt_num(leverage, 1)} | "
        f"Spread: {_fmt_num(spread_pct, 2)}%"
    )
    print(
        f"   Laufzeit: {days} Tage | Impl.Vola: {_fmt_num(impl_vol, 1)}% | "
        f"Aufgeld: {_fmt_num(aufgeld, 1)}%"
    )
    print(f"   Zeitwertverlust: {_fmt_num(theta_abs, 4)} EUR/Tag ({_fmt_num(theta_pct, 1)}%/Tag)")
    print(
        f"   Break-Even: {_fmt_num(_safe_float(breakeven), 2)} EUR "
        f"(benötigt {move_needed:+.1f}% Bewegung)"
    )
    print(
        f"   Innerer Wert: {_fmt_num(intrinsic, 3)} EUR | "
        f"Zeitwert: {_fmt_num(extrinsic, 3)} EUR ({_fmt_num(extrinsic_pct, 0)}%)"
    )
    print(
        f"   Asset-Score: {int(_safe_float(top.get('asset_score'))):d}/{MAX_ASSET_SCORE} | "
        f"Emittent: {top.get('emittent', 'n/a')}"
    )
    print(
        f"   ├─ Spread-Score: {int(_safe_float(top.get('spread_score'))):d}/25 | "
        f"Omega-Score: {int(_safe_float(top.get('omega_score'))):d}/25"
    )
    print(
        f"   ├─ Strike-Score: {int(_safe_float(top.get('strike_score'))):d}/20 | "
        f"Theta-Score: {int(_safe_float(top.get('theta_score'))):d}/15"
    )
    print(
        f"   ├─ Vola-Score: {int(_safe_float(top.get('vola_score'))):d}/10 | "
        f"Aufgeld-Score: {int(_safe_float(top.get('aufgeld_score'))):d}/5"
    )
    print(
        f"   ├─ Break-Even-Score: {int(_safe_float(top.get('breakeven_score'))):d}/10 | "
        f"Leverage-Score: {int(_safe_float(top.get('leverage_score'))):d}/5"
    )
    print(f"   Stakeholder-Info: {_build_stakeholder_info(top)}")
    print(
        "   P/L-Simulation (vereinfacht, nur innerer Wert): "
        f"{scenario_1:+.1f}% -> { _pl(scenario_1):+.3f} EUR | "
        f"{scenario_2:+.1f}% -> { _pl(scenario_2):+.3f} EUR | "
        f"{scenario_3:+.1f}% -> { _pl(scenario_3):+.3f} EUR"
    )
    print(
        f"   200€-Setup (Stop 10%): Stück {pieces} | Entry {entry:.3f}€ | "
        f"Stop {stop:.3f}€ | Kosten {cost:.2f}€ | Rest {rest:.2f}€ | Risiko {risk:.2f}€"
    )


def _print_asset_screening(asset_rows: list[dict[str, object]], min_asset_score: int) -> None:
    print("\n📊 SCHRITT 1: Analysiere Basiswerte...\n")

    if not asset_rows:
        print("⚠️ Keine Basiswerte geprüft.")
        return

    for row in asset_rows:
        ticker = str(row["ticker"])
        if bool(row["has_data"]):
            score = int(_safe_float(row["score"]))
            os_ok = "✅" if bool(row["os_ok"]) else "❌"
            print(f"  Prüfe {ticker}... Score: {score} | OS_OK: {os_ok}")
        else:
            print(f"  Prüfe {ticker}... ❌ Keine Daten")

    qualified = [
        r for r in asset_rows if bool(r["has_data"]) and bool(r["os_ok"]) and int(_safe_float(r["score"])) >= min_asset_score
    ]

    if not qualified:
        print("\n❌ Keine qualifizierten Basiswerte gefunden.")
        return

    df = pd.DataFrame(qualified).sort_values(["score", "ticker"], ascending=[False, True])
    display_df = pd.DataFrame(
        {
            "Ticker": df["ticker"],
            "Score": df["score"].astype(int),
            "Close": df["close"].map(lambda x: float(x) if x is not None else float("nan")),
            "ATR_%": df["atr_pct"].map(lambda x: _safe_float(x) * 100),
            "Long_Strike": df["long_strike"],
            "Short_Strike": df["short_strike"],
        }
    )

    print(f"\n✅ {len(display_df)} qualifizierte Basiswerte gefunden:\n")
    print(
        display_df.to_string(
            index=False,
            formatters={
                "Score": lambda x: f"{int(x):d}",
                "Close": lambda x: _fmt_num(x, 2),
                "ATR_%": lambda x: _fmt_num(x, 2),
                "Long_Strike": lambda x: _fmt_num(x, 2),
                "Short_Strike": lambda x: _fmt_num(x, 2),
            },
        )
    )


def _print_top_options(df: pd.DataFrame, top_n: int = 3) -> None:
    if df.empty:
        return

    top = df.head(top_n).copy()
    if top.empty:
        return

    print(f"\n🏁 Top {len(top)} Optionsscheine (gesamt):\n")
    print(
        top[
            [
                "ticker",
                "wkn",
                "total_score",
                "mid",
                "spread_pct",
                "hebel",
                "omega",
                "laufzeit",
                "emittent",
            ]
        ].to_string(
            index=False,
            formatters={
                "total_score": lambda x: f"{int(_safe_float(x)):d}",
                "mid": lambda x: _fmt_num(x, 3),
                "spread_pct": lambda x: _fmt_num(x, 2),
                "hebel": lambda x: _fmt_num(x, 2),
                "omega": lambda x: _fmt_num(x, 2),
            },
        )
    )


def get_tickers_dynamically() -> list[str]:
    # Default list lives in the package to avoid legacy-script import cycles.
    from warrant_scanner.tickers import get_default_tickers

    return get_default_tickers()


def run(config: ScannerConfig, tickers: list[str], option_type: str = "call", debug: bool = False) -> pd.DataFrame:
    is_call = option_type.lower() == "call"

    assets = []
    asset_rows: list[dict[str, object]] = []
    for t in tickers:
        logger.info("Checking asset %s", t)
        snap = check_asset(t, config)
        if snap:
            assets.append(snap)
            asset_rows.append(
                {
                    "ticker": snap.ticker,
                    "has_data": True,
                    "score": snap.score,
                    "os_ok": snap.os_ok,
                    "close": snap.close,
                    "atr_pct": snap.atr_pct,
                    "long_strike": snap.long_strike,
                    "short_strike": snap.short_strike,
                }
            )
        else:
            asset_rows.append(
                {
                    "ticker": t,
                    "has_data": False,
                    "score": None,
                    "os_ok": False,
                    "close": None,
                    "atr_pct": None,
                    "long_strike": None,
                    "short_strike": None,
                }
            )

    _print_asset_screening(asset_rows, config.min_asset_score)

    df_assets = pd.DataFrame([a.__dict__ for a in assets])
    if df_assets.empty:
        logger.warning("No assets available")
        return pd.DataFrame()

    df_qualified = df_assets[(df_assets["os_ok"] == True) & (df_assets["score"] >= config.min_asset_score)].copy()
    if df_qualified.empty:
        logger.warning("No qualified assets")
        return pd.DataFrame()

    client = OnvistaClient(config)
    fx = FxProvider(ttl_sec=config.fx_cache_ttl_sec)

    all_frames = []

    for _, row in df_qualified.iterrows():
        ticker = row["ticker"]
        asset = next(a for a in assets if a.ticker == ticker)
        logger.info("Finding options for %s", ticker)

        underlying_names = client.ticker_to_onvista_name(ticker)
        target_strike = asset.long_strike if is_call else asset.short_strike
        strike_min = int(target_strike * 0.90)
        strike_max = int(target_strike * 1.10)

        parsed: list = []
        for underlying in underlying_names:
            for label, url in client.build_search_url_variants(underlying, strike_min, strike_max):
                logger.info("Trying %s / %s", underlying, label)
                opts = client.scrape_options(url, debug_html_path="onvista_debug.html" if debug else None)
                if opts:
                    parsed = opts
                    break
            if parsed:
                break

        if not parsed:
            continue

        # enrich details
        enriched = []
        for i, opt in enumerate(parsed):
            enriched.append(enrich_with_details(client, opt))
            if config.max_detail_enrich and i + 1 >= config.max_detail_enrich:
                break

        scored = [compute_scored_option(o, asset, is_call, fx) for o in enriched]
        scored.sort(key=lambda s: s.total_score, reverse=True)

        frame = scored_to_frame(scored, asset)
        all_frames.append(frame)

        time.sleep(1)

    if not all_frames:
        return pd.DataFrame()

    df = pd.concat(all_frames, ignore_index=True)
    df = df.sort_values("total_score", ascending=False)
    return df


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Warrant/Optionsschein scanner")
    p.add_argument("--min-asset-score", type=int, default=12)
    p.add_argument("--option-type", choices=["call", "put"], default="call")
    p.add_argument("--limit", type=int, default=0, help="Limit number of tickers")
    p.add_argument("--debug", action="store_true")
    p.add_argument("--log-level", default="INFO")
    p.add_argument("--out", default="top_options.csv")
    return p


def main() -> None:
    args = build_arg_parser().parse_args()
    setup_logging(args.log_level)

    config = ScannerConfig(min_asset_score=args.min_asset_score)
    tickers = get_tickers_dynamically()
    if args.limit and args.limit > 0:
        tickers = tickers[: args.limit]

    df = run(config, tickers, option_type=args.option_type, debug=args.debug)
    if df.empty:
        logger.warning("No results")
        return

    _print_console_summary(df, option_type=args.option_type)
    _print_top_options(df, top_n=3)

    df.to_csv(args.out, index=False, encoding="utf-8-sig")
    logger.info("Exported: %s (%d rows)", args.out, len(df))


if __name__ == "__main__":
    main()
