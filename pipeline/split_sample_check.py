#!/usr/bin/env python3
import sys
sys.path.insert(0, "pipeline")
import backtest as bt
from backtest import load_universe, build_panel, run_backtest
import pandas as pd

universe = load_universe()
close, funding = build_panel(universe)

split = pd.Timestamp("2023-07-01", tz="UTC")
close_early = close[close.index < split]
funding_early = funding[funding.index < split]
close_late = close[close.index >= split]
funding_late = funding[funding.index >= split]

print("EARLY PERIOD (2020-01 to 2023-07), in-sample selection window:")
for mw, cw in [(1.0, 0.0), (0.9, 0.1), (0.8, 0.2), (0.6, 0.4)]:
    bt.MOM_WEIGHT, bt.CARRY_WEIGHT = mw, cw
    r, _ = run_backtest(close_early, funding_early)
    sh = r.mean() / r.std() * (365 ** 0.5) if r.std() > 0 else float("nan")
    print(f"  mom={mw} carry={cw}: Sharpe {sh:.3f}  n={len(r.dropna())}")

print()
print("LATE PERIOD (2023-07 to 2026-08), true out-of-sample test:")
for mw, cw in [(1.0, 0.0), (0.9, 0.1), (0.8, 0.2), (0.6, 0.4)]:
    bt.MOM_WEIGHT, bt.CARRY_WEIGHT = mw, cw
    r, _ = run_backtest(close_late, funding_late)
    sh = r.mean() / r.std() * (365 ** 0.5) if r.std() > 0 else float("nan")
    nw_t, mean, se, n = bt.newey_west_tstat(r.values, lags=5)
    print(f"  mom={mw} carry={cw}: Sharpe {sh:.3f}  NW-t {nw_t:.3f}  n={n}")
