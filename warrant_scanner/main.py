from __future__ import annotations

import argparse
import logging
import time

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


def get_tickers_dynamically() -> list[str]:
    # Default list lives in the package to avoid legacy-script import cycles.
    from warrant_scanner.tickers import get_default_tickers

    return get_default_tickers()


def run(config: ScannerConfig, tickers: list[str], option_type: str = "call", debug: bool = False) -> pd.DataFrame:
    is_call = option_type.lower() == "call"

    assets = []
    for t in tickers:
        logger.info("Checking asset %s", t)
        snap = check_asset(t, config)
        if snap:
            assets.append(snap)

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

    df.to_csv(args.out, index=False, encoding="utf-8-sig")
    logger.info("Exported: %s (%d rows)", args.out, len(df))


if __name__ == "__main__":
    main()
