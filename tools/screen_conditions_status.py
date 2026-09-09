#!/usr/bin/env python3
"""Runs in CI. Shows, for each stock in the existing watchlist, whether
each of the same 6 conditions tools/backtest_momentum_screen.py backtests
is CURRENTLY true or false -- and nothing more.

This is explicitly a measuring tape, not a screener: the output is not
sorted, not scored (no "X/6 conditions met" tally), and carries no
buy/watch/rank signal of any kind. The user asked for this to become a
stock-picking strategy; that was declined -- turning a backward-looking
backtest into a live "here's what to buy today" list is exactly the
specific-stock/timing call this project stays out of. What's built here
instead just answers "is condition N true for stock X right now," the
same kind of factual, backward-looking arithmetic tools/fetch_momentum.py
already does for range position / trailing return / volume ratio. What
the reader does with that fact is entirely their own judgement.

Conditions (identical definitions to backtest_momentum_screen.py):
  1. 股價位於月線之上            close > 20-day SMA of close
  2. 10日漲幅大於5%              close[-1]/close[-11] - 1 > 5%
  3. 股價1日振幅大於3%           (high-low)/prev_close > 3%, most recent day
  4. 成交量創5日新高             today's volume is the max of the last 5 days
  5. 股價盤中創5日新高           today's high is the max of the last 5 days
  6. 5日均量大於1000張           mean(volume[-5:]) > 1,000,000 shares

Reuses the exact fetch/parse code from backtest_momentum_screen.py so the
live numbers are computed the same way the historical backtest was.

Writes data/momentum_screen_status.json.
"""
from __future__ import annotations

import statistics
import sys
from datetime import date

from backtest_momentum_screen import WATCHLIST, SHARES_PER_LOT, fetch_history


def status_for_stock(code: str, name: str, history: list[dict]) -> dict:
    closes = [r["close"] for r in history]
    highs = [r["high"] for r in history]
    lows = [r["low"] for r in history]
    volumes = [r["volume"] for r in history]
    n = len(history)
    i = n - 1  # latest trading day

    month_line = sum(closes[i - 19 : i + 1]) / 20
    ret_10d = (closes[i] / closes[i - 10] - 1) * 100 if i >= 10 else None
    amplitude = (highs[i] - lows[i]) / closes[i - 1] * 100 if closes[i - 1] > 0 else None
    vol_5d_max = max(volumes[i - 4 : i + 1])
    high_5d_max = max(highs[i - 4 : i + 1])
    avg_vol_5d = statistics.mean(volumes[i - 4 : i + 1])

    return {
        "code": code,
        "name": name,
        "last_date": history[-1]["date"],
        "close": round(closes[i], 2),
        "conditions": {
            "above_month_line": {"met": closes[i] > month_line, "close": round(closes[i], 2), "month_line": round(month_line, 2)},
            "return_10d_over_5pct": {"met": ret_10d is not None and ret_10d > 5, "return_10d_pct": round(ret_10d, 2) if ret_10d is not None else None},
            "amplitude_over_3pct": {"met": amplitude is not None and amplitude > 3, "amplitude_pct": round(amplitude, 2) if amplitude is not None else None},
            "volume_5d_high": {"met": volumes[i] >= vol_5d_max, "volume": volumes[i], "max_5d": vol_5d_max},
            "high_5d_high": {"met": highs[i] >= high_5d_max, "high": highs[i], "max_5d": high_5d_max},
            "avg_volume_5d_over_1000_lots": {"met": avg_vol_5d > 1000 * SHARES_PER_LOT, "avg_volume_5d_lots": round(avg_vol_5d / SHARES_PER_LOT, 1)},
        },
    }


def main() -> int:
    results = []
    for code, name, market in WATCHLIST:  # fixed watchlist order -- never resorted by how many conditions are met
        history = fetch_history(code, market)
        if len(history) < 25:
            results.append({"code": code, "name": name, "error": f"只取到 {len(history)} 個交易日，資料不足"})
            continue
        results.append(status_for_stock(code, name, history))

    out = {
        "generated_at": date.today().isoformat(),
        "conditions_legend": [
            "股價位於月線（20日均線）之上",
            "10日漲幅大於5%",
            "股價1日振幅（(最高-最低)/前一日收盤）大於3%",
            "成交量創5日新高",
            "股價盤中最高價創5日新高",
            "5日均量大於1000張",
        ],
        "disclaimer": (
            "純粹顯示每檔股票目前每個條件是否成立的事實，刻意不排序、不計分、不標記「符合幾項」，"
            "也不是買進/觀察建議。歷史上符合全部6項之後的走勢統計見 data/backtest_momentum_screen.json，"
            "但過去統計不代表現在符合就會重演。"
        ),
        "stocks": results,
    }
    import json
    with open("data/momentum_screen_status.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
        f.write("\n")
    for r in results:
        if "error" in r:
            print(f"{r['code']} {r['name']}: {r['error']}")
        else:
            met = [k for k, v in r["conditions"].items() if v["met"]]
            print(f"{r['code']} {r['name']} ({r['last_date']}): {len(met)}/6 conditions true")
    return 0


if __name__ == "__main__":
    sys.exit(main())
