#!/usr/bin/env python3
"""Incremental daily refresh: append only new klines/funding since the last stored bar,
instead of re-downloading full history. Run this daily, not the full backfill.py."""
import json
import sys
import time

import pandas as pd

sys.path.insert(0, "pipeline")
from backfill import fetch_daily_klines, fetch_funding  # noqa: E402

kline_cols = ["open_time", "open", "high", "low", "close", "volume", "close_time",
              "quote_volume", "trades", "taker_buy_base", "taker_buy_quote", "ignore"]


def refresh_symbol(sym):
    kpath = f"data/raw/binance/futures/klines_1d/{sym}.parquet"
    fpath = f"data/raw/binance/futures/funding/{sym}.parquet"

    k_old = pd.read_parquet(kpath)
    last_open_ms = int(k_old["open_time"].max().timestamp() * 1000)
    new_klines = fetch_daily_klines(sym, last_open_ms + 1)
    if new_klines:
        k_new = pd.DataFrame(new_klines, columns=kline_cols)
        k_new["open_time"] = pd.to_datetime(k_new["open_time"], unit="ms", utc=True)
        for c in ["open", "high", "low", "close", "volume", "quote_volume"]:
            k_new[c] = k_new[c].astype(float)
        k_new = k_new[["open_time", "open", "high", "low", "close", "volume", "quote_volume", "trades"]]
        combined = pd.concat([k_old, k_new]).drop_duplicates("open_time").sort_values("open_time")
        combined.to_parquet(kpath, index=False)
        added_k = len(combined) - len(k_old)
    else:
        added_k = 0

    f_old = pd.read_parquet(fpath)
    last_funding_ms = int(f_old["fundingTime"].max().timestamp() * 1000)
    new_funding = fetch_funding(sym, last_funding_ms + 1)
    if new_funding:
        f_new = pd.DataFrame(new_funding)
        f_new["fundingTime"] = pd.to_datetime(f_new["fundingTime"], unit="ms", utc=True)
        f_new["fundingRate"] = f_new["fundingRate"].astype(float)
        f_new = f_new[["fundingTime", "fundingRate"]]
        combined_f = pd.concat([f_old, f_new]).drop_duplicates("fundingTime").sort_values("fundingTime")
        combined_f.to_parquet(fpath, index=False)
        added_f = len(combined_f) - len(f_old)
    else:
        added_f = 0

    return added_k, added_f


def main():
    with open("universe_snapshot.json") as f:
        universe = [u["symbol"] for u in json.load(f)["universe"]]

    for sym in universe:
        try:
            ak, af = refresh_symbol(sym)
            print(f"{sym}: +{ak} klines, +{af} funding")
        except Exception as e:
            print(f"{sym}: FAILED - {e}")
        time.sleep(0.1)


if __name__ == "__main__":
    main()
