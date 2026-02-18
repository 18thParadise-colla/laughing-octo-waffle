# Design: config.yaml for Warrants Script

## Overview
Externalize hardcoded configuration values into a `config.yaml` file.

## Structure
- yahoo: period, interval, min_data_points
- indicators: sma_short, sma_long, rsi_window, atr_window, etc.
- scoring: all threshold values and weights
- forecast: timeout, upside thresholds
- scraper: delay, timeout, retry settings
- cli: defaults
