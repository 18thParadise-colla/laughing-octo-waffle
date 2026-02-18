# Design: Relative Strength vs SPY

## Overview
Add Relative Strength check to basiswert-check - measures how a stock performs vs the broader market (SPY).

## Berechnung
```python
# 20-Tage Return der Aktie
stock_return = (close / close_20d_ago) - 1

# 20-Tage Return von SPY
spy_return = (spy_close / spy_close_20d_ago) - 1

# Relative Strength
rel_strength = stock_return - spy_return
```

## Scoring
- +2 Punkte wenn rel_strength > 2% (strong outperformance)
- +1 Punkt wenn rel_strength > 0% (moderate outperformance)
- 0 Punkte wenn <= 0% (underperformance)

## Config
```yaml
scoring:
  relative_strength:
    benchmark: "SPY"
    lookback_days: 20
    strong_outperformance: 2
    moderate_outperformance: 0
```

## Implementation
See code changes.
