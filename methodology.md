# Methodology: PFC Momentum-Carry v1.0.0

**Strategy version:** pfc-momentum-carry-v1.0.0
**Inception:** 2026-08-19
**Author:** Amit Rathore

## What this is

A dollar-neutral, cross-sectional long/short strategy on liquid Binance USDT-M perpetual futures, combining price momentum and funding-rate carry. Rebalanced daily. This document is versioned: any change to the rules below is a new version with a dated changelog entry, not a silent edit.

## Universe

- Binance USDT-M perpetual futures only.
- Minimum 365 days listed.
- Top 30 symbols by **30-day trailing average daily notional volume**, minimum $25M/day.
- Reconstituted from a fresh snapshot; current membership is stored in `universe_snapshot.json` with a generation timestamp.

**Known limitation, stated plainly:** the backtest below applies the *current* universe retroactively across the full 2020-2026 history. This is not a point-in-time-reconstructed universe. This is a real survivorship-bias risk, since the actual tradable set of liquid perps in 2020 was smaller and different from today's. A properly point-in-time universe would require archived historical volume rankings, which are not yet built. This is a real gap in the current backtest, not a hidden one.

## Signal

For each eligible symbol at each daily timestamp:

- **Momentum**: `0.5 × log(close_t / close_t-7) + 0.5 × log(close_t / close_t-21)`, cross-sectionally z-scored across the universe.
- **Funding carry**: negative of the 3-day median funding rate, cross-sectionally z-scored.
- **Composite**: `0.8 × momentum_z + 0.2 × carry_z`.

## Why 80/20, not the originally planned 60/40

The initial plan (informed by a multi-model research panel) proposed a 60/40 momentum/carry blend. Testing against real backfilled data (2020-2026, 30 symbols) showed this was wrong:

| Weighting | Full-sample Sharpe | Newey-West t-stat |
|---|---|---|
| Momentum only (100/0) | 0.731 | 1.806 |
| 90/10 | 0.786 | 1.947 |
| **80/20** | **0.858** | **2.157** |
| 60/40 (original plan) | 0.614 | 1.520 |

Carry alone, in isolation, was weak (Sharpe 0.350, t-stat 0.928, worse drawdown at -24.5%) and diluted the composite when weighted too heavily. 80/20 was not picked because it was the single best score among several tested, since that would be a real data-snooping risk, and is flagged as such. It was picked because a **split-sample check** (early period 2020-01 to 2023-07 used for selection; late period 2023-07 to 2026-08 held out as a true out-of-sample test) showed 80/20 winning independently in *both* non-overlapping windows:

| Weighting | Early-period Sharpe (selection window) | Late-period Sharpe (out-of-sample) | Late-period NW t-stat |
|---|---|---|---|
| 100/0 | 1.140 | 0.555 | 0.969 |
| 90/10 | 1.172 | 0.596 | 1.025 |
| **80/20** | **1.241** | **0.687** | **1.219** |
| 60/40 | 0.614 | 0.678 | 1.166 |

## The honest expectation, stated up front

**The strategy's apparent edge has clearly decayed over time**, and the recent out-of-sample period does not clear conventional statistical significance on its own (t-stat 1.22, versus the ~1.96 threshold usually used). The full-sample Sharpe of 0.858 is a flattering historical number; the realistic forward expectation, based on the most recent ~3 years alone, is closer to **Sharpe 0.6-0.7**, and even that estimate carries real uncertainty. This matches a well-known pattern in published systematic strategies generally (in-sample/early performance overstates what persists), and is stated here explicitly rather than left for someone else to discover.

This is not a disqualifying finding. It is the expected, honest shape of a real, modest signal, and it is exactly the standard this project holds itself to elsewhere (see the [funding-signal backtest piece](https://amitrathore.io/research/funding-signal-backtest), which found a similar "real but overstated by naive analysis" pattern in a different signal).

## Portfolio construction

- Long the top 6 composite scores, short the bottom 6.
- Inverse-20-day-realized-volatility weights within each leg.
- Portfolio scaled to a 12% annualized volatility target, gross exposure capped at 1.5×.

## Costs

- 5 bps taker fee + 3 bps slippage per unit of daily turnover (both sides). No maker rebates assumed. No VIP fee tier assumed.
- Funding P&L applied using the realized daily funding rate on each position.
- Average daily turnover in backtest: ~21%. All results above are net of these costs.

## Risk management (V1)

- No leverage beyond the vol-targeting scale factor (capped at 1.5× gross).
- Position-level cap implicit via inverse-vol weighting; no single symbol should ever dominate the book, verified via leave-one-symbol-out testing (full-sample Sharpe 0.858; range across single-symbol exclusions was 0.449-0.717, and no symbol's removal caused a collapse, but WLDUSDT, HOMEUSDT, and ZECUSDT contributed the most to the measured edge).
- Drawdown/circuit-breaker rules and a formal kill switch are **not yet implemented** in the live signal generator. This is a known gap for the next iteration, not a hidden one. The historical max drawdown in backtest was -19.4%.
- Signal integrity: every signal is SHA-256 hashed and committed to a version-controlled repository at generation time, before any outcome is known.

## What's not in V1

- No ML layer. The composite signal above is fully deterministic and auditable.
- No real capital. This is a simulated/paper track record with realistic cost assumptions, clearly labeled as such.
- No point-in-time universe reconstruction (see Universe section).
- No formal drawdown circuit breaker in the automated pipeline yet.

## Changelog

**v1.0.0, 2026-08-19**
Initial live signal. Weighting selected via split-sample validation (see above). First signal hash: `5e2d392d505e3500...`. Daily automation via cron (00:10 UTC) established, pushing to a public GitHub repository.
