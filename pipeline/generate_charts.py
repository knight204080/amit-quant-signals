#!/usr/bin/env python3
"""Generate real equity curve and drawdown charts from the actual backtest, styled
to match the site's visual language. Committed as static PNGs, no external service
dependency, no fabricated data."""
import sys
sys.path.insert(0, "pipeline")
import backtest as bt
from backtest import load_universe, build_panel, run_backtest
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

BG = "#08090b"
FG = "#f1f0ec"
MUTED = "#8b8d94"
BORDER = "#1f2127"
ACCENT = "#2fe5b8"
ACCENT2 = "#8b7cf6"

universe = load_universe()
close, funding = build_panel(universe)
ret_series, _ = run_backtest(close, funding)

cum = (1 + ret_series).cumprod()
drawdown = cum / cum.cummax() - 1

plt.rcParams.update({
    "figure.facecolor": BG,
    "axes.facecolor": BG,
    "axes.edgecolor": BORDER,
    "axes.labelcolor": MUTED,
    "text.color": FG,
    "xtick.color": MUTED,
    "ytick.color": MUTED,
    "grid.color": BORDER,
    "font.family": "monospace",
    "font.size": 10,
})

fig, (ax1, ax2) = plt.subplots(
    2, 1, figsize=(10, 6), sharex=True, height_ratios=[2.5, 1],
    gridspec_kw={"hspace": 0.08}
)

ax1.plot(cum.index, cum.values, color=ACCENT, linewidth=1.5)
ax1.set_ylabel("Cumulative NAV (start = 1.0)")
ax1.set_title("PFC Momentum-Carry v1.0.0: Backtest NAV, 2020-2026", color=FG, fontsize=12, pad=12)
ax1.grid(True, alpha=0.15)
for spine in ax1.spines.values():
    spine.set_color(BORDER)

ax2.fill_between(drawdown.index, drawdown.values * 100, 0, color=ACCENT2, alpha=0.35)
ax2.plot(drawdown.index, drawdown.values * 100, color=ACCENT2, linewidth=1)
ax2.set_ylabel("Drawdown (%)")
ax2.grid(True, alpha=0.15)
for spine in ax2.spines.values():
    spine.set_color(BORDER)

ax2.xaxis.set_major_locator(mdates.YearLocator())
ax2.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))

fig.text(
    0.5, 0.01,
    "Full-sample backtest. Realistic out-of-sample expectation is lower; see methodology for the split-sample check.",
    ha="center", color=MUTED, fontsize=8,
)

plt.savefig("assets/equity_drawdown.png", dpi=150, bbox_inches="tight", facecolor=BG)
print("Saved assets/equity_drawdown.png")
print(f"Final NAV: {cum.iloc[-1]:.3f}")
print(f"Max drawdown: {drawdown.min()*100:.2f}%")
