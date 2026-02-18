# Design: config.yaml für Warrants-Script

## Overview

Externalize hardcoded configuration values into a `config.yaml` file for easier tuning without code changes.

## Struktur der config.yaml

```yaml
# === TECHNISCHE PARAMETER ===
yahoo:
  period: "6mo"
  interval: "1d"
  min_data_points: 80

indicators:
  sma_short: 20
  sma_long: 50
  rsi_window: 14
  atr_window: 14
  volatility_window: 14
  range_lookback: 15

# === SCORING GEWICHTUNG ===
scoring:
  trend:
    uptrend_bullish: 4
  momentum:
    positive_rsi_confirmed: 3
    positive_only: 2
  atr:
    ideal_volatile_confirmed: 3
    ideal_volatile_only: 2
    high_volatile: 1
  volume:
    above_average: 2
  sideways:
    penalty: -5
  min_score: 7
  atr_min_pct: 0.02
  atr_max_pct: 0.05
  sideways_max_pct: 0.025
  rsi_min: 50
  rsi_max: 70

# === FORECAST ANALYSTEN ===
forecast:
  timeout: 8
  upside_strong: 15
  upside_moderate: 5

# === SCRAPING / ONVISTA ===
scraper:
  delay: 2.0
  timeout: 15
  retry_delay: 1
  max_retries: 3

# === CLI DEFAULT ARGS ===
cli:
  default_tickers: ["AAPL", "MSFT", "GOOGL"]
  output_format: "table"
```

## Lade-Logik

1. Default-Werte in Python als Fallback
2. `config.yaml` aus aktuellen Verzeichnis laden
3. Mit `argparse` können Werte überschrieben werden
4. Credentials via Environment Variables

## Implementierung

Siehe Implementation Plan: `docs/plans/2026-02-18-config-implementation-plan.md`
