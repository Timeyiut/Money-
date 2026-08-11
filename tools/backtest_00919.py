#!/usr/bin/env python3
"""Runs in CI. Historical backtest for 00919: compares two entry/exit
rules around each real ex-dividend event.

Ex-dividend dates, reference prices, and fill-completion dates are
transcribed from Goodinfo's 除權息日程 table (user-supplied screenshot,
2026/08/11) — https://goodinfo.tw/tw/StockDividendSchedule.asp?STOCK_ID=00919
No scriptable public source for this per-stock history was found after
six probe rounds against TWSE, MOPS, Yuanta and CMoney; see git log for
that trail. The dividend amount per event is derived from TWSE's own
published formula (not guessed): 息值 = 除息前收盤價 − 除息參考價.

Daily closing prices come from the TWSE STOCK_DAY endpoint, which is
independently verified working (same one tools/fetch_prices.py uses).

Strategy A (參與除息): buy at the close of the 1st trading day of the
  ex-dividend month, hold through the ex-dividend date, sell at the
  close of the table's 填息完成日 (fill-completion date). Return =
  (exit_price - entry_price + dividend) / entry_price.

Strategy B (除息前賣掉): same entry, sell at the close of the last
  trading day before the ex-dividend date. Return = (exit_price -
  entry_price) / entry_price. No dividend — you exit before it's paid.

Writes data/backtest_00919.json.
"""
from __future__ import annotations

import json
import sys
import time
from datetime import date
from urllib.request import Request, urlopen

STOCK_NO = "00919"
HEADERS = {"User-Agent": "Mozilla/5.0"}

# ex_date, ref_price (除息參考價), fill_date (填息完成日) — chronological.
# Source: Goodinfo 00919 除權息日程, screenshot dated 2026/08/11.
DIVIDEND_EVENTS = [
    ("2023-06-16", 19.78, "2023-07-18"),
    ("2023-09-18", 21.35, "2023-12-04"),
    ("2023-12-18", 22.30, "2024-02-20"),
    ("2024-03-18", 25.17, "2024-03-19"),
    ("2024-06-24", 26.24, "2026-05-25"),
    ("2024-09-23", 23.46, "2024-09-27"),
    ("2024-12-20", 23.25, "2025-02-24"),
    ("2025-03-18", 23.02, "2026-01-19"),
    ("2025-06-17", 21.77, "2025-12-22"),
    ("2025-09-16", 21.25, "2025-11-13"),
    ("2025-12-16", 21.65, "2025-12-17"),
    ("2026-03-17", 23.13, "2026-04-22"),
    ("2026-06-16", 29.69, "2026-06-18"),
]


def fetch_month_prices(year_month: str) -> list[dict]:
    url = f"https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY?date={year_month}&stockNo={STOCK_NO}&response=json"
    req = Request(url, headers=HEADERS)
    with urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read())
    if data.get("stat") != "OK":
        return []
    rows = []
    for row in data.get("data", []):
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
    earliest = min(date.fromisoformat(e[0]) for e in DIVIDEND_EVENTS)
    latest_fill = max(date.fromisoformat(e[2]) for e in DIVIDEND_EVENTS)
    today = date.today()
    range_end = max(latest_fill, today)

    price_by_date: dict[str, float] = {}
    for m in month_iter(date(earliest.year, earliest.month, 1), range_end):
        ym = f"{m.year:04d}{m.month:02d}01"
        try:
            rows = fetch_month_prices(ym)
        except Exception as e:  # noqa: BLE001
            print(f"warn: failed to fetch {ym}: {e}", file=sys.stderr)
            rows = []
        for row in rows:
            price_by_date[row["date"]] = row["close"]
        time.sleep(0.25)

    sorted_dates = sorted(price_by_date)

    def nearest_at_or_before(d: str) -> str | None:
        candidates = [x for x in sorted_dates if x <= d]
        return candidates[-1] if candidates else None

    def trading_day_before(d: str) -> str | None:
        candidates = [x for x in sorted_dates if x < d]
        return candidates[-1] if candidates else None

    results = []
    for ex_date, ref_price, fill_date in DIVIDEND_EVENTS:
        month_start = f"{ex_date[:7]}-01"
        entry_date = next((x for x in sorted_dates if x >= month_start), None)
        if entry_date is None or entry_date >= ex_date:
            print(f"skip {ex_date}: no valid entry date", file=sys.stderr)
            continue
        entry_price = price_by_date[entry_date]

        pre_close_date = trading_day_before(ex_date)
        if pre_close_date is None:
            print(f"skip {ex_date}: no pre-close date", file=sys.stderr)
            continue
        pre_close = price_by_date[pre_close_date]
        dividend = round(pre_close - ref_price, 4)

        # Strategy B: sell the day before ex-dividend
        return_b = (pre_close - entry_price) / entry_price

        # Strategy A: sell at the table's fill-completion date
        fill_lookup = nearest_at_or_before(fill_date)
        if fill_lookup is None or fill_lookup not in price_by_date:
            print(f"skip {ex_date}: no price for fill date {fill_date}", file=sys.stderr)
            continue
        fill_price = price_by_date[fill_lookup]
        return_a = (fill_price - entry_price + dividend) / entry_price

        results.append(
            {
                "ex_date": ex_date,
                "ref_price": ref_price,
                "dividend": dividend,
                "entry_date": entry_date,
                "entry_price": entry_price,
                "pre_close_date": pre_close_date,
                "pre_close": pre_close,
                "strategy_a_exit_date": fill_lookup,
                "strategy_a_exit_price": fill_price,
                "strategy_a_return_pct": round(return_a * 100, 2),
                "strategy_a_fill_days": (date.fromisoformat(fill_date) - date.fromisoformat(ex_date)).days,
                "strategy_b_exit_date": pre_close_date,
                "strategy_b_exit_price": pre_close,
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
        "b_beats_a_count": sum(1 for r in results if r["strategy_b_return_pct"] > r["strategy_a_return_pct"]),
    }

    out = {
        "stock": STOCK_NO,
        "source": "Goodinfo 除權息日程 (user-supplied 2026/08/11) + TWSE STOCK_DAY closing prices",
        "summary": summary,
        "events": results,
    }
    with open("data/backtest_00919.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
