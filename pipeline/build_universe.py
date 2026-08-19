#!/usr/bin/env python3
"""Build the point-in-time-eligible USDT-M perp universe from real Binance data.

Lesson from v1 (single-day 24h volume snapshot, 180-day listing minimum): it let
newly-listed hype tokens with a one-day volume spike dominate the ranking. Fixed by
using 30-day trailing average notional volume and a 365-day minimum listing age.
"""
import json
import time
import urllib.request
from datetime import datetime, timezone

FAPI = "https://fapi.binance.com"

def get(path, params=None):
    url = f"{FAPI}{path}"
    if params:
        url += "?" + "&".join(f"{k}={v}" for k, v in params.items())
    with urllib.request.urlopen(url, timeout=20) as resp:
        return json.load(resp)

def trailing_30d_avg_notional(symbol):
    klines = get("/fapi/v1/klines", {"symbol": symbol, "interval": "1d", "limit": 30})
    if len(klines) < 30:
        return None
    # kline[7] = quote asset volume (already in USDT for USDT-M contracts)
    notionals = [float(k[7]) for k in klines]
    return sum(notionals) / len(notionals)

def main():
    info = get("/fapi/v1/exchangeInfo")
    perps = [
        s for s in info["symbols"]
        if s["contractType"] == "PERPETUAL"
        and s["quoteAsset"] == "USDT"
        and s["status"] == "TRADING"
    ]
    print(f"Total live USDT-M perpetuals: {len(perps)}")

    now_ms = int(time.time() * 1000)
    listing_cutoff = now_ms - 365 * 86400 * 1000  # 365 days min listing age

    eligible = [s for s in perps if s["onboardDate"] <= listing_cutoff]
    print(f"Eligible by listing age (>=365d): {len(eligible)}")

    # Pre-filter by 24h ticker to avoid computing 30d avg for all 400+ eligible symbols
    tickers = {t["symbol"]: t for t in get("/fapi/v1/ticker/24hr")}
    prelim = sorted(eligible, key=lambda s: -float(tickers.get(s["symbol"], {}).get("quoteVolume", 0)))[:80]

    rows = []
    for s in prelim:
        sym = s["symbol"]
        try:
            avg30 = trailing_30d_avg_notional(sym)
        except Exception as e:
            print(f"  skip {sym}: {e}")
            continue
        if avg30 is None:
            continue
        rows.append({
            "symbol": sym,
            "onboard_date": datetime.fromtimestamp(s["onboardDate"] / 1000, tz=timezone.utc).date().isoformat(),
            "avg_30d_notional_usd": avg30,
        })
        time.sleep(0.05)  # stay well under rate limits

    rows.sort(key=lambda r: -r["avg_30d_notional_usd"])
    top30 = [r for r in rows if r["avg_30d_notional_usd"] >= 25_000_000][:30]

    print(f"\nUniverse (top 30 by 30d avg notional, >= $25M/day threshold, >=365d listed): {len(top30)} symbols")
    for r in top30:
        print(f"  {r['symbol']:12s} ${r['avg_30d_notional_usd']/1e6:8.1f}M   listed {r['onboard_date']}")

    with open("universe_snapshot.json", "w") as f:
        json.dump({
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "rule": "top30_by_30d_avg_notional_usd_min25M_min365d_listed",
            "universe": top30,
        }, f, indent=2)
    print("\nWrote universe_snapshot.json")

if __name__ == "__main__":
    main()
