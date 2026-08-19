#!/usr/bin/env python3
"""Backfill daily klines + funding rate history for the universe, from listing or 2020-01-01."""
import json
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
import pandas as pd

FAPI = "https://fapi.binance.com"
START = int(datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)

def get(path, params=None, retries=3):
    url = f"{FAPI}{path}"
    if params:
        url += "?" + "&".join(f"{k}={v}" for k, v in params.items())
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=20) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            if e.code == 429:
                print(f"    rate limited, sleeping 30s...")
                time.sleep(30)
                continue
            raise
        except Exception as e:
            if attempt == retries - 1:
                raise
            time.sleep(2)
    return []

def fetch_daily_klines(symbol, start_ms):
    all_klines = []
    cursor = start_ms
    now_ms = int(time.time() * 1000)
    while cursor < now_ms:
        batch = get("/fapi/v1/klines", {
            "symbol": symbol, "interval": "1d", "startTime": cursor, "limit": 1500,
        })
        if not batch:
            break
        all_klines.extend(batch)
        last_open = batch[-1][0]
        if last_open <= cursor:
            break
        cursor = last_open + 86400_000
        time.sleep(0.08)
        if len(batch) < 1500:
            break
    return all_klines

def fetch_funding(symbol, start_ms):
    all_funding = []
    cursor = start_ms
    now_ms = int(time.time() * 1000)
    while cursor < now_ms:
        batch = get("/fapi/v1/fundingRate", {
            "symbol": symbol, "startTime": cursor, "limit": 1000,
        })
        if not batch:
            break
        all_funding.extend(batch)
        last_time = batch[-1]["fundingTime"]
        if last_time <= cursor:
            break
        cursor = last_time + 1
        time.sleep(0.08)
        if len(batch) < 1000:
            break
    return all_funding

def main():
    with open("universe_snapshot.json") as f:
        universe = json.load(f)["universe"]

    kline_cols = ["open_time","open","high","low","close","volume","close_time",
                  "quote_volume","trades","taker_buy_base","taker_buy_quote","ignore"]

    for i, u in enumerate(universe):
        sym = u["symbol"]
        print(f"[{i+1}/{len(universe)}] {sym} ...", flush=True)

        klines = fetch_daily_klines(sym, START)
        if klines:
            df = pd.DataFrame(klines, columns=kline_cols)
            df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
            for c in ["open","high","low","close","volume","quote_volume"]:
                df[c] = df[c].astype(float)
            df = df[["open_time","open","high","low","close","volume","quote_volume","trades"]]
            df.to_parquet(f"data/raw/binance/futures/klines_1d/{sym}.parquet", index=False)
            print(f"    klines: {len(df)} rows, {df['open_time'].min()} to {df['open_time'].max()}")
        else:
            print(f"    klines: NO DATA")

        funding = fetch_funding(sym, START)
        if funding:
            fdf = pd.DataFrame(funding)
            fdf["fundingTime"] = pd.to_datetime(fdf["fundingTime"], unit="ms", utc=True)
            fdf["fundingRate"] = fdf["fundingRate"].astype(float)
            fdf = fdf[["fundingTime","fundingRate"]]
            fdf.to_parquet(f"data/raw/binance/futures/funding/{sym}.parquet", index=False)
            print(f"    funding: {len(fdf)} rows")
        else:
            print(f"    funding: NO DATA")

    print("\nBackfill complete.")

if __name__ == "__main__":
    main()
