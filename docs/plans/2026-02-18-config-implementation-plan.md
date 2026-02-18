# Implementation Plan: config.yaml Integration

## Tasks

### Task 1: Create config.yaml
- **File**: `config.yaml`
- **Content**: All configuration values as designed
- **Dependencies**: None

### Task 2: Add config loading function
- **File**: `warrants_searcher_v6_fixed_3.py`
- **Changes**: Add `load_config()` function with yaml import
- **Dependencies**: Task 1

### Task 3: Replace hardcoded values with config references
- **File**: `warrants_searcher_v6_fixed_3.py`
- **Changes**:
  - Replace period/interval in `check_basiswert()`
  - Replace indicator windows (SMA, RSI, ATR, Volatility)
  - Replace scoring thresholds (score += X values)
  - Replace filter thresholds (min_score, atr_min_pct, etc.)
  - Replace timeout/delay values in INGOptionsFinder
- **Dependencies**: Task 2

### Task 4: Add --config CLI argument
- **File**: `warrants_searcher_v6_fixed_3.py`
- **Changes**: Extend argparse with --config flag
- **Dependencies**: Task 2

### Task 5: Commit and create PR
- **Files**: All changed files
- **Changes**: git add, commit, push, pr create
- **Dependencies**: Task 3, Task 4
