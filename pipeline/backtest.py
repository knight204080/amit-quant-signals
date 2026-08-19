#!/usr/bin/env python3
"""V1 baseline strategy backtest: cross-sectional momentum + funding carry,
dollar-neutral long/short on Binance USDT-M perps, vol-targeted, daily rebalance.

Honest limitation stated up front: this uses the CURRENT top-30 universe applied
retroactively across the full history, not a point-in-time-reconstructed universe.
That is a real survivorship-bias risk for the earlier years, where in reality the
tradable universe was smaller and different. Flagged explicitly rather than hidden,
same standard as the site's existing funding-signal piece.
"""
import glob
import json
import math
import os

import numpy as np
import pandas as pd

DATA_DIR = "data/raw/binance/futures"
COST_TAKER_BPS = 5
COST_SLIPPAGE_BPS = 3
VOL_TARGET_ANN = 0.12
N_LONG = 6
N_SHORT = 6
MOM_WEIGHT = 0.8
CARRY_WEIGHT = 0.2


def load_universe():
    with open("universe_snapshot.json") as f:
        return [u["symbol"] for u in json.load(f)["universe"]]


def load_symbol(sym):
    kpath = f"{DATA_DIR}/klines_1d/{sym}.parquet"
    fpath = f"{DATA_DIR}/funding/{sym}.parquet"
    if not os.path.exists(kpath) or not os.path.exists(fpath):
        return None
    k = pd.read_parquet(kpath)
    k = k.rename(columns={"open_time": "date"})
    k["date"] = pd.to_datetime(k["date"]).dt.floor("D")
    k = k.drop_duplicates("date").set_index("date").sort_index()

    f = pd.read_parquet(fpath)
    f["date"] = pd.to_datetime(f["fundingTime"]).dt.floor("D")
    daily_funding = f.groupby("date")["fundingRate"].mean()  # avg of ~3 prints/day
    k["funding"] = daily_funding.reindex(k.index)
    k["funding"] = k["funding"].ffill().fillna(0.0)
    return k[["close", "volume", "quote_volume", "funding"]]


def build_panel(universe):
    frames = {}
    for sym in universe:
        df = load_symbol(sym)
        if df is not None and len(df) > 60:
            frames[sym] = df
    all_dates = sorted(set().union(*[df.index for df in frames.values()]))
    idx = pd.DatetimeIndex(all_dates)

    close = pd.DataFrame({s: frames[s]["close"].reindex(idx) for s in frames})
    funding = pd.DataFrame({s: frames[s]["funding"].reindex(idx) for s in frames})
    return close, funding


def cross_sectional_z(row):
    valid = row.dropna()
    if len(valid) < 6:
        return row * np.nan
    mu, sd = valid.mean(), valid.std()
    if sd == 0 or np.isnan(sd):
        return row * np.nan
    return (row - mu) / sd


def realized_vol(close, window=20):
    ret = np.log(close).diff()
    return ret.rolling(window).std() * math.sqrt(365)


def newey_west_tstat(x, lags):
    x = np.asarray(x, dtype=float)
    x = x[~np.isnan(x)]
    n = len(x)
    mean = x.mean()
    resid = x - mean
    s0 = np.mean(resid ** 2)
    lrv = s0
    for lag in range(1, lags + 1):
        w = 1 - lag / (lags + 1)
        gamma = np.mean(resid[lag:] * resid[:-lag])
        lrv += 2 * w * gamma
    se = math.sqrt(max(lrv, 0) / n)
    return mean / se if se > 0 else float("nan"), mean, se, n


def block_bootstrap_sharpe(returns, block_size=21, n_boot=5000, seed=None):
    returns = returns.dropna().values
    n = len(returns)
    n_blocks = n // block_size
    rng = np.random.default_rng(seed)
    sharpes = []
    for _ in range(n_boot):
        idxs = rng.integers(0, n - block_size, size=n_blocks)
        sample = np.concatenate([returns[i:i + block_size] for i in idxs])
        mu, sd = sample.mean(), sample.std()
        if sd > 0:
            sharpes.append(mu / sd * math.sqrt(365))
    return np.array(sharpes)


def run_backtest(close, funding, exclude_symbol=None):
    symbols = [c for c in close.columns if c != exclude_symbol]
    close = close[symbols]
    funding = funding[symbols]

    log_ret = np.log(close).diff()
    mom_7 = np.log(close / close.shift(7))
    mom_21 = np.log(close / close.shift(21))
    mom_raw = 0.5 * mom_7 + 0.5 * mom_21

    funding_smooth = funding.rolling(3).median()
    carry_raw = -funding_smooth

    vol20 = realized_vol(close, 20)

    mom_z = mom_raw.apply(cross_sectional_z, axis=1)
    carry_z = carry_raw.apply(cross_sectional_z, axis=1)
    composite = MOM_WEIGHT * mom_z + CARRY_WEIGHT * carry_z

    dates = composite.index
    daily_returns = []
    turnovers = []
    prev_weights = pd.Series(0.0, index=symbols)

    for i in range(30, len(dates) - 1):
        d, d1 = dates[i], dates[i + 1]
        scores = composite.loc[d].dropna()
        if len(scores) < (N_LONG + N_SHORT):
            daily_returns.append(0.0)
            turnovers.append(0.0)
            continue

        longs = scores.nlargest(N_LONG).index
        shorts = scores.nsmallest(N_SHORT).index

        iv = 1.0 / vol20.loc[d].reindex(longs.union(shorts))
        iv = iv.replace([np.inf, -np.inf], np.nan).dropna()
        if len(iv) < (N_LONG + N_SHORT) * 0.6:
            daily_returns.append(0.0)
            turnovers.append(0.0)
            continue

        w = pd.Series(0.0, index=symbols)
        long_iv = iv.reindex(longs).dropna()
        short_iv = iv.reindex(shorts).dropna()
        if long_iv.sum() > 0:
            w.loc[long_iv.index] = 0.5 * long_iv / long_iv.sum()
        if short_iv.sum() > 0:
            w.loc[short_iv.index] = -0.5 * short_iv / short_iv.sum()

        port_vol_forecast = math.sqrt((w ** 2 * vol20.loc[d].reindex(w.index).fillna(0) ** 2).sum())
        gross_scale = min(1.5, VOL_TARGET_ANN / port_vol_forecast) if port_vol_forecast > 0 else 0.0
        w = w * gross_scale

        r_next = log_ret.loc[d1].reindex(symbols).fillna(0.0)
        f_next = funding.loc[d1].reindex(symbols).fillna(0.0)

        price_pnl = (w * r_next).sum()
        funding_pnl = (w * f_next).sum() * -1  # long pays if funding positive

        turnover = (w - prev_weights).abs().sum()
        cost = turnover * (COST_TAKER_BPS + COST_SLIPPAGE_BPS) / 10000

        daily_returns.append(price_pnl + funding_pnl - cost)
        turnovers.append(turnover)
        prev_weights = w

    ret_series = pd.Series(daily_returns, index=dates[30:len(dates) - 1])
    return ret_series, np.mean(turnovers)


def summarize(ret_series, label):
    ann_ret = ret_series.mean() * 365
    ann_vol = ret_series.std() * math.sqrt(365)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else float("nan")
    downside = ret_series[ret_series < 0].std() * math.sqrt(365)
    sortino = ann_ret / downside if downside and downside > 0 else float("nan")
    cum = (1 + ret_series).cumprod()
    dd = (cum / cum.cummax() - 1).min()
    nw_t, mean, se, n = newey_west_tstat(ret_series.values, lags=5)

    print(f"\n=== {label} ===")
    print(f"  n days: {len(ret_series)}  ({ret_series.index.min().date()} to {ret_series.index.max().date()})")
    print(f"  Annualized return: {ann_ret*100:.2f}%")
    print(f"  Annualized vol:    {ann_vol*100:.2f}%")
    print(f"  Sharpe:            {sharpe:.3f}")
    print(f"  Sortino:           {sortino:.3f}")
    print(f"  Max drawdown:      {dd*100:.2f}%")
    print(f"  Newey-West t-stat (mean daily return, 5 lags): {nw_t:.3f}")
    return {"sharpe": sharpe, "ann_ret": ann_ret, "max_dd": dd, "nw_t": nw_t}


def main():
    universe = load_universe()
    print(f"Universe: {len(universe)} symbols")
    close, funding = build_panel(universe)
    print(f"Panel shape: {close.shape}, date range {close.index.min().date()} to {close.index.max().date()}")

    ret_series, avg_turnover = run_backtest(close, funding)
    print(f"Average daily turnover: {avg_turnover:.3f}")
    base = summarize(ret_series, "V1 baseline: momentum(0.6) + funding-carry(0.4), full sample")

    print("\n=== Block bootstrap Sharpe distribution (5000 resamples, 21-day blocks) ===")
    boot = block_bootstrap_sharpe(ret_series, block_size=21, n_boot=5000, seed=42)
    lo, hi = np.percentile(boot, [5, 95])
    print(f"  Point Sharpe: {ret_series.mean()/ret_series.std()*math.sqrt(365):.3f}")
    print(f"  90% bootstrap CI: [{lo:.3f}, {hi:.3f}]")
    print(f"  Fraction of bootstrap draws with Sharpe <= 0: {(boot <= 0).mean()*100:.1f}%")

    print("\n=== Leave-one-symbol-out sensitivity (does one symbol drive the result?) ===")
    loo_sharpes = {}
    for sym in universe:
        if sym not in close.columns:
            continue
        r, _ = run_backtest(close, funding, exclude_symbol=sym)
        sh = r.mean() / r.std() * math.sqrt(365) if r.std() > 0 else float("nan")
        loo_sharpes[sym] = sh
    full_sharpe = ret_series.mean() / ret_series.std() * math.sqrt(365)
    sorted_loo = sorted(loo_sharpes.items(), key=lambda kv: kv[1])
    print(f"  Full-universe Sharpe: {full_sharpe:.3f}")
    print(f"  Range when dropping one symbol: [{sorted_loo[0][1]:.3f} ({sorted_loo[0][0]}), {sorted_loo[-1][1]:.3f} ({sorted_loo[-1][0]})]")
    print(f"  Most impactful single-symbol drops:")
    for sym, sh in sorted_loo[:3] + sorted_loo[-3:]:
        print(f"    drop {sym:12s} -> Sharpe {sh:.3f}  (delta {sh-full_sharpe:+.3f})")

    with open("backtest_results.json", "w") as f:
        json.dump({
            "universe_size": len(universe),
            "n_days": len(ret_series),
            "sharpe": float(full_sharpe),
            "bootstrap_ci_90": [float(lo), float(hi)],
            "fraction_boot_le_zero": float((boot <= 0).mean()),
            "newey_west_t": float(base["nw_t"]),
            "ann_ret": float(base["ann_ret"]),
            "max_dd": float(base["max_dd"]),
            "avg_turnover": float(avg_turnover),
            "loo_sharpe_range": [float(sorted_loo[0][1]), float(sorted_loo[-1][1])],
        }, f, indent=2)
    print("\nWrote backtest_results.json")


if __name__ == "__main__":
    main()
