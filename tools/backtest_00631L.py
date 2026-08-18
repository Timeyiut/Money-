#!/usr/bin/env python3
"""Runs in CI. Historical backtest for 00631L (元大台灣50正2): what
happened, historically, after a mechanical MA20/MA60 crossover signal.

This is not a trading system and produces no entry/exit recommendation.
The signal rule is fixed and mechanical (a moving-average crossover,
computed the same way every time) specifically so there is no discretion
involved — the point is to measure "what happened after this exact,
repeatable event occurred in the past," not to pick winning trades in
hindsight.

Signal definition:
  黃金交叉 (golden cross): 20-day SMA crosses from <= 60-day SMA to > it.
  死亡交叉 (death cross):   20-day SMA crosses from >= 60-day SMA to < it.

For each crossover, this measures the forward return over fixed horizons
(5/10/20/60 trading days) starting from the crossover day's close. This
is deliberately NOT "buy at the signal, sell whenever you feel like it" —
a fixed holding period is the only way to compare events without
hindsight bias creeping into the exit choice.

00631L is a daily-reset 2x leveraged ETF, so its own price history
already includes volatility decay — the backtest doesn't need to model
that separately, it's baked into the real closes being measured.

Price source: TWSE STOCK_DAY (same endpoint tools/fetch_prices.py and
tools/fetch_momentum.py already use, verified reliable).

Writes data/backtest_00631L.json.
"""
from __future__ import annotations

import json
import sys
import time
from datetime import date
from urllib.request import Request, urlopen

STOCK_NO = "00631L"
HEADERS = {"User-Agent": "Mozilla/5.0"}
HORIZONS = [5, 10, 20, 60]  # trading days
FAST, SLOW = 20, 60  # SMA windows


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


def sma(values: list[float], window: int, i: int) -> float | None:
    if i + 1 < window:
        return None
    return sum(values[i + 1 - window : i + 1]) / window


def main() -> int:
    # 00631L listed 2014-10-31; ~6 years of history gives a reasonable
    # sample of crossovers without an unreasonably long CI fetch.
    today = date.today()
    start = date(today.year - 6, today.month, 1)

    price_by_date: dict[str, float] = {}
    for m in month_iter(start, today):
        ym = f"{m.year:04d}{m.month:02d}01"
        try:
            rows = fetch_month_prices(ym)
        except Exception as e:  # noqa: BLE001
            print(f"warn: failed to fetch {ym}: {e}", file=sys.stderr)
            rows = []
        for row in rows:
            price_by_date[row["date"]] = row["close"]
        time.sleep(0.25)

    dates = sorted(price_by_date)
    closes = [price_by_date[d] for d in dates]
    n = len(dates)
    if n < SLOW + max(HORIZONS) + 5:
        print(f"Not enough history ({n} trading days) to backtest.", file=sys.stderr)
        return 1

    fast_sma = [sma(closes, FAST, i) for i in range(n)]
    slow_sma = [sma(closes, SLOW, i) for i in range(n)]

    events = []
    for i in range(1, n):
        f0, s0, f1, s1 = fast_sma[i - 1], slow_sma[i - 1], fast_sma[i], slow_sma[i]
        if None in (f0, s0, f1, s1):
            continue
        golden = f0 <= s0 and f1 > s1
        death = f0 >= s0 and f1 < s1
        if not (golden or death):
            continue

        entry_price = closes[i]
        forward = {}
        for h in HORIZONS:
            j = i + h
            if j < n:
                forward[str(h)] = round((closes[j] - entry_price) / entry_price * 100, 2)
            else:
                forward[str(h)] = None

        events.append(
            {
                "date": dates[i],
                "type": "golden" if golden else "death",
                "close": entry_price,
                "forward_return_pct": forward,
            }
        )

    def summarize(kind: str) -> dict:
        subset = [e for e in events if e["type"] == kind]
        out = {"events": len(subset)}
        for h in HORIZONS:
            vals = [e["forward_return_pct"][str(h)] for e in subset if e["forward_return_pct"][str(h)] is not None]
            if vals:
                out[f"avg_return_{h}d_pct"] = round(sum(vals) / len(vals), 2)
                out[f"win_rate_{h}d_pct"] = round(sum(1 for v in vals if v > 0) / len(vals) * 100, 1)
                out[f"sample_{h}d"] = len(vals)
            else:
                out[f"avg_return_{h}d_pct"] = None
                out[f"win_rate_{h}d_pct"] = None
                out[f"sample_{h}d"] = 0
        return out

    out = {
        "stock": STOCK_NO,
        "signal": f"{FAST}日均線 vs {SLOW}日均線 交叉（機械式規則，非判斷）",
        "history_range": {"from": dates[0], "to": dates[-1], "trading_days": n},
        "source": "TWSE STOCK_DAY 官方日收盤價",
        "disclaimer": (
            "全部為歷史事件的回顧統計，樣本數有限（見 events 欄位），"
            "不是訊號、不是預測、不是進出場建議。"
        ),
        "golden_cross": summarize("golden"),
        "death_cross": summarize("death"),
        "events": events,
    }
    with open("data/backtest_00631L.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(json.dumps({"golden": out["golden_cross"], "death": out["death_cross"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
