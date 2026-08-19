#!/usr/bin/env python3
"""Generate today's live signal: refresh recent data, compute the composite score,
build target weights, hash the result, and append to the immutable signal log.

Designed to run daily via cron, independent of the RTX machine. This is pure
CPU/pandas work per the panel's conclusion that V1 does not need the GPU.
"""
import hashlib
import json
import math
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, "pipeline")
import backtest as bt
from backtest import load_universe, build_panel, cross_sectional_z, realized_vol

VOL_TARGET_ANN = 0.12
N_LONG, N_SHORT = 6, 6
MOM_WEIGHT, CARRY_WEIGHT = 0.8, 0.2


def sha256_of(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True).encode()).hexdigest()


def already_published(signal_date):
    if not os.path.exists("signals.jsonl"):
        return False
    with open("signals.jsonl") as f:
        for line in f:
            if line.strip():
                existing = json.loads(line)
                if existing.get("signal_date") == signal_date:
                    return True
    return False


def main():
    universe = load_universe()
    close, funding = build_panel(universe)

    import numpy as np
    mom_7 = np.log(close / close.shift(7))
    mom_21 = np.log(close / close.shift(21))
    mom_raw = 0.5 * mom_7 + 0.5 * mom_21
    funding_smooth = funding.rolling(3).median()
    carry_raw = -funding_smooth
    vol20 = realized_vol(close, 20)

    mom_z = mom_raw.apply(cross_sectional_z, axis=1)
    carry_z = carry_raw.apply(cross_sectional_z, axis=1)
    composite = MOM_WEIGHT * mom_z + CARRY_WEIGHT * carry_z

    latest_date = composite.index[-1]

    if already_published(latest_date.date().isoformat()):
        print(f"SKIP: signal for {latest_date.date().isoformat()} already published. Not duplicating.")
        return

    scores = composite.loc[latest_date].dropna()

    if len(scores) < (N_LONG + N_SHORT):
        print(f"ABORT: only {len(scores)} valid scores, need {N_LONG+N_SHORT}. Not publishing signal.")
        return

    longs = scores.nlargest(N_LONG)
    shorts = scores.nsmallest(N_SHORT)

    iv = 1.0 / vol20.loc[latest_date].reindex(longs.index.union(shorts.index))
    iv = iv.replace([float("inf"), float("-inf")], float("nan")).dropna()

    positions = []
    long_iv = iv.reindex(longs.index).dropna()
    short_iv = iv.reindex(shorts.index).dropna()
    port_vol_forecast_sq = 0.0

    for sym, score in longs.items():
        if sym not in long_iv.index:
            continue
        w = 0.5 * long_iv[sym] / long_iv.sum()
        positions.append({
            "symbol": sym, "side": "long", "weight_raw": round(float(w), 6),
            "composite_score": round(float(score), 4),
            "momentum_z": round(float(mom_z.loc[latest_date, sym]), 4),
            "carry_z": round(float(carry_z.loc[latest_date, sym]), 4),
            "vol_20d_ann": round(float(vol20.loc[latest_date, sym]), 4),
        })
    for sym, score in shorts.items():
        if sym not in short_iv.index:
            continue
        w = -0.5 * short_iv[sym] / short_iv.sum()
        positions.append({
            "symbol": sym, "side": "short", "weight_raw": round(float(w), 6),
            "composite_score": round(float(score), 4),
            "momentum_z": round(float(mom_z.loc[latest_date, sym]), 4),
            "carry_z": round(float(carry_z.loc[latest_date, sym]), 4),
            "vol_20d_ann": round(float(vol20.loc[latest_date, sym]), 4),
        })

    port_vol_forecast = math.sqrt(sum(
        (p["weight_raw"] ** 2) * (p["vol_20d_ann"] ** 2) for p in positions
    ))
    gross_scale = min(1.5, VOL_TARGET_ANN / port_vol_forecast) if port_vol_forecast > 0 else 0.0
    for p in positions:
        p["weight_final"] = round(p["weight_raw"] * gross_scale, 6)

    signal = {
        "signal_date": latest_date.date().isoformat(),
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "strategy_version": "pfc-momentum-carry-v1.0.0",
        "params": {"mom_weight": MOM_WEIGHT, "carry_weight": CARRY_WEIGHT,
                   "n_long": N_LONG, "n_short": N_SHORT, "vol_target_ann": VOL_TARGET_ANN},
        "universe_size": len(universe),
        "gross_scale": round(gross_scale, 4),
        "positions": positions,
    }
    signal["signal_hash"] = sha256_of(signal)

    with open("signals.jsonl", "a") as f:
        f.write(json.dumps(signal) + "\n")

    print(f"Signal generated for {signal['signal_date']}")
    print(f"  hash: {signal['signal_hash'][:16]}...")
    print(f"  gross scale: {gross_scale:.3f}")
    print(f"  longs:  {[p['symbol'] for p in positions if p['side']=='long']}")
    print(f"  shorts: {[p['symbol'] for p in positions if p['side']=='short']}")


if __name__ == "__main__":
    main()
