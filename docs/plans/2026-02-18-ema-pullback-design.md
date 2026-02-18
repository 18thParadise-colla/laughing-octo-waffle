# Design: EMA-Pullback Check

## Overview
Add EMA-Pullback scoring to basiswert-check after trend confirmation.

## Einbauort
After Trend-Check (line ~227), as separate score block:

```python
# Trend (Close > SMA20 > SMA50)
if close > sma20 > sma50:
    score += 4

# → EMA-Pullback check
```

## Logik
```python
# EMA-Pullback: Preis läuft zum EMA zurück nach Rücksetzer
pullback_tolerance = 0.03  # ±3%
pullback_distance = (sma20 - close) / close

if close > sma50:  # Trend intakt
    if abs(pullback_distance) <= pullback_tolerance:
        score += 2
        reasons.append("✔ EMA-Pullback: Close nahe SMA20")
    elif close < sma20:
        reasons.append("⚠ Unter SMA20 - kein Pullback")
    else:
        reasons.append("ℹ️ Kein EMA-Pullback")
```

## Config
```yaml
scoring:
  pullback:
    tolerance_pct: 0.03
    score: 2
```

## Implementation
See implementation plan.
