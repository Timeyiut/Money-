#!/usr/bin/env python3
"""Runs in CI only. Historical backtest for 00919: compares two entry/exit
rules around each ex-dividend event, using real TWSE daily prices and the
official ex-dividend reference table — not a simulation, not a projection
of future results.

Strategy A (參與除息): buy at the close of the 1st trading day of the
  ex-dividend month, hold through the ex-dividend date, sell once the
  price has filled (closed at or above the pre-ex-dividend close) or
  after MAX_HOLD_DAYS trading days if it never fills within that window.
  Return = (exit_price - entry_price + dividend) / entry_price.

Strategy B (除息前賣掉): same entry, but sell at the close of the last
  trading day before the ex-dividend date. Return = (exit_price -
  entry_price) / entry_price. No dividend included — you don't hold
  through the ex-dividend date.

Data sources (official TWSE, public, no auth):
  - Daily prices: /rwd/zh/afterTrading/STOCK_DAY (one call per month)
  - Ex-dividend reference table: /rwd/zh/exRight/TWT49U

Writes data/backtest_00919.json. Set DEBUG_DUMP=1 to print raw API
responses to the log instead of writing the file, for verifying field
layout against a live response.
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import date, timedelta
from urllib.request import Request, urlopen

STOCK_NO = "00919"
MAX_HOLD_DAYS = 60
HEADERS = {"User-Agent": "Mozilla/5.0"}


def fetch_json(url: str):
    req = Request(url, headers=HEADERS)
    with urlopen(req, timeout=20) as resp:
        return json.loads(resp.read())


def fetch_dividend_table() -> list[dict]:
    url = f"https://www.twse.com.tw/rwd/zh/exRight/TWT49U?stkNo={STOCK_NO}&response=json"
    data = fetch_json(url)
    if os.environ.get("DEBUG_DUMP"):
        print("--- dividend table raw ---")
        print(json.dumps(data, ensure_ascii=False, indent=2)[:3000])
    return data.get("data", [])


def fetch_month_prices(year_month: str) -> list[dict]:
    """year_month like '20250601'. Returns list of {date: 'YYYY-MM-DD', close: float}."""
    url = f"https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY?date={year_month}&stockNo={STOCK_NO}&response=json"
    data = fetch_json(url)
    if data.get("stat") != "OK":
        return []
    rows = []
    for row in data.get("data", []):
        # row[0] is ROC date like '114/06/03'; row[6] is closing price with commas
        roc = row[0].split("/")
        y = int(roc[0]) + 1911
        d = f"{y:04d}-{int(roc[1]):02d}-{int(roc[2]):02d}"
        close = float(row[6].replace(",", ""))
        rows.append({"date": d, "close": close})
    return rows


def month_iter(start: date, end: date):
    cur = date(start.year, start.month, 1)
    while cur <= end:
        yield cur
        cur = date(cur.year + (cur.month == 12), cur.month % 12 + 1, 1)


def main() -> int:
    debug = bool(os.environ.get("DEBUG_DUMP"))

    dividend_rows = fetch_dividend_table()
    if debug:
        return 0

    if not dividend_rows:
        print("No dividend rows found.", file=sys.stderr)
        return 1

    # Pull the full price history from the first dividend event's month to today.
    today = date.today()
    price_by_date: dict[str, float] = {}
    listed_start = date(2023, 10, 1)  # 00919 listed 2023/10; safe lower bound
    for m in month_iter(listed_start, today):
        ym = f"{m.year:04d}{m.month:02d}01"
        try:
            month_rows = fetch_month_prices(ym)
        except Exception as e:  # noqa: BLE001
            print(f"warn: failed to fetch {ym}: {e}", file=sys.stderr)
            month_rows = []
        for row in month_rows:
            price_by_date[row["date"]] = row["close"]
        time.sleep(0.3)  # be polite to the API

    sorted_dates = sorted(price_by_date)

    def trading_days_from(d: str, offset: int) -> str | None:
        """offset can be negative (go back) or positive (go forward)."""
        if d not in sorted_dates:
            # find nearest date <= d
            candidates = [x for x in sorted_dates if x <= d]
            if not candidates:
                return None
            d = candidates[-1]
        idx = sorted_dates.index(d)
        j = idx + offset
        if 0 <= j < len(sorted_dates):
            return sorted_dates[j]
        return None

    results = []
    for row in dividend_rows:
        # TWT49U fields vary; be defensive about column positions.
        # Typical layout: [除權息日期, 股票代號, 名稱, 除權息前收盤價, 除權息參考價,
        #                   權值+息值, 權值, 息值, 隔日漲停價, 隔日跌停價, 詳細資料]
        try:
            ex_date_roc = row[0]
            roc = ex_date_roc.split("/")
            ex_year = int(roc[0]) + 1911
            ex_date = f"{ex_year:04d}-{int(roc[1]):02d}-{int(roc[2]):02d}"
            pre_close = float(str(row[3]).replace(",", ""))
            dividend_str = str(row[7]).replace(",", "") if len(row) > 7 else "0"
            dividend = float(dividend_str) if dividend_str not in ("", "-") else 0.0
        except (ValueError, IndexError) as e:
            print(f"warn: could not parse dividend row {row}: {e}", file=sys.stderr)
            continue

        if ex_date > today.isoformat():
            continue

        month_start = f"{ex_date[:7]}-01"
        entry_date = None
        for d in sorted_dates:
            if d >= month_start:
                entry_date = d
                break
        if entry_date is None or entry_date >= ex_date:
            continue
        entry_price = price_by_date[entry_date]

        # Strategy B: sell the trading day before ex-dividend
        exit_b_date = trading_days_from(ex_date, -1)
        if exit_b_date is None or exit_b_date <= entry_date:
            continue
        exit_b_price = price_by_date[exit_b_date]
        return_b = (exit_b_price - entry_price) / entry_price

        # Strategy A: hold through ex-dividend, sell once price >= pre_close (filled),
        # else after MAX_HOLD_DAYS trading days
        ex_idx = sorted_dates.index(ex_date) if ex_date in sorted_dates else None
        fill_date = None
        fill_price = None
        if ex_idx is not None:
            for j in range(ex_idx, min(ex_idx + MAX_HOLD_DAYS, len(sorted_dates))):
                d = sorted_dates[j]
                p = price_by_date[d]
                if p >= pre_close:
                    fill_date = d
                    fill_price = p
                    break
        if fill_date is None:
            j = min(ex_idx + MAX_HOLD_DAYS, len(sorted_dates) - 1) if ex_idx is not None else None
            if j is not None:
                fill_date = sorted_dates[j]
                fill_price = price_by_date[fill_date]
        if fill_price is None:
            continue
        return_a = (fill_price - entry_price + dividend) / entry_price

        results.append(
            {
                "ex_date": ex_date,
                "dividend": dividend,
                "entry_date": entry_date,
                "entry_price": entry_price,
                "strategy_a_exit_date": fill_date,
                "strategy_a_exit_price": fill_price,
                "strategy_a_return_pct": round(return_a * 100, 2),
                "strategy_a_filled": fill_price is not None and fill_price >= pre_close,
                "strategy_b_exit_date": exit_b_date,
                "strategy_b_exit_price": exit_b_price,
                "strategy_b_return_pct": round(return_b * 100, 2),
            }
        )

    if not results:
        print("No backtest rows produced.", file=sys.stderr)
        return 1

    n = len(results)
    a_returns = [r["strategy_a_return_pct"] for r in results]
    b_returns = [r["strategy_b_return_pct"] for r in results]
    summary = {
        "events": n,
        "strategy_a_avg_return_pct": round(sum(a_returns) / n, 2),
        "strategy_a_win_rate_pct": round(sum(1 for x in a_returns if x > 0) / n * 100, 1),
        "strategy_b_avg_return_pct": round(sum(b_returns) / n, 2),
        "strategy_b_win_rate_pct": round(sum(1 for x in b_returns if x > 0) / n * 100, 1),
        "a_beats_b_count": sum(1 for r in results if r["strategy_a_return_pct"] > r["strategy_b_return_pct"]),
    }

    out = {"stock": STOCK_NO, "summary": summary, "events": results}
    out_path = "data/backtest_00919.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
