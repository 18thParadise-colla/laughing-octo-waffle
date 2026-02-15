from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ScannerConfig:
    # Market data windowing
    period: str = "6mo"
    interval: str = "1d"

    # Asset prefilter thresholds
    min_rows: int = 80
    atr_pct_min: float = 0.02
    atr_pct_max: float = 0.05
    range_15_min: float = 0.025
    min_asset_score: int = 12

    # Onvista search
    days_min: int = 9
    days_max: int = 16
    spread_ask_pct_min: float = 0.3
    spread_ask_pct_max: float = 3.0
    broker_id_ing: int = 4

    # HTTP
    request_timeout_sec: int = 15
    max_retries: int = 3
    retry_delay_sec: float = 1.0
    polite_delay_sec: float = 2.0

    # Enrichment
    max_detail_enrich: int | None = None  # None = enrich all prefiltered

    # FX
    fx_cache_ttl_sec: int = 3600
