#!/usr/bin/env python3
"""Runs in CI. Fetches a continuous multi-year daily closing-price series
for a fixed pool of symbols and writes data/price_history.json.

This exists specifically to back the 投資 tab's "情境模擬練習" (scenario
practice) card: that feature replays a real historical stretch of price
action up to some day, asks the user what they'd do, then reveals what
actually happened next. Every other data file in this repo is either a
single latest snapshot (prices.json) or an event-day summary
(backtest_*.json, momentum.json) -- none of them holds a continuous
day-by-day series, which is the one thing scenario replay needs.

Market (上市/上櫃) is looked up from a fixed table, not guessed from the
ticker prefix -- guessing has already produced wrong answers once in this
repo (see fetch_momentum.py's git history), so every symbol here reuses a
classification already verified working in an earlier script.

Source: TWSE STOCK_DAY (上市) / TPEx tradingStock (上櫃) -- the same
endpoints tools/fetch_momentum.py and tools/backtest_00631L.py already
use successfully.
"""
from __future__ import annotations

import json
import sys
import time
from datetime import date
from urllib.request import Request, urlopen

HEADERS = {"User-Agent": "Mozilla/5.0"}

# code, name, market -- market classifications carried over from
# tools/fetch_momentum.py, already corrected there once.
SYMBOLS = [
    ("00631L", "元大台灣50正2", "上市"),
    ("00919", "群益台灣精選高息", "上市"),
    ("3105", "穩懋", "上櫃"),
    ("8021", "尖點", "上市"),
    ("4979", "華星光", "上櫃"),
    ("3363", "上詮", "上櫃"),
    ("4977", "眾達-KY", "上市"),
    ("3450", "聯鈞", "上市"),
    ("6451", "訊芯-KY", "上市"),
    ("3587", "閎康", "上櫃"),
    ("3289", "宜特", "上櫃"),
]

YEARS_BACK = 2  # was 3; a live run at 3 took >15min and got cancelled --
                # 2 years (~490 trading days) is still far more than the
                # 70 days any one practice round needs, at ~2/3 the requests
OUT_PATH = "data/price_history.json"
REQUEST_TIMEOUT = 8  # was 25 -- with ~260 requests in this script, a slow
                     # endpoint eating 25s each is what actually blew the
                     # runtime past 15 minutes; fail fast instead
MAX_ATTEMPTS = 1  # no retry: a month that fails just leaves a gap in that
                  # symbol's series (fine for a practice tool), instead of
                  # doubling the worst-case wall-clock time for a retry
                  # that's unlikely to succeed if the first try timed out


def fetch_json(url: str) -> dict:
    with urlopen(Request(url, headers=HEADERS), timeout=REQUEST_TIMEOUT) as resp:
        return json.loads(resp.read())


def fetch_twse_month(code: str, ym: str) -> list[dict]:
    url = f"https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY?date={ym}&stockNo={code}&response=json"
    data = fetch_json(url)
    if data.get("stat") != "OK":
        return []
    rows = []
    for row in data.get("data", []):
        try:
            roc = row[0].split("/")
            y = int(roc[0]) + 1911
            d = f"{y:04d}-{int(roc[1]):02d}-{int(roc[2]):02d}"
            close = float(str(row[6]).replace(",", ""))
        except (ValueError, IndexError):
            continue
        if close > 0:
            rows.append({"date": d, "close": close})
    return rows


def fetch_tpex_month(code: str, ym: str) -> list[dict]:
    d = f"{ym[:4]}/{ym[4:6]}/01"
    url = f"https://www.tpex.org.tw/www/zh-tw/afterTrading/tradingStock?code={code}&date={d}&id=&response=json"
    data = fetch_json(url)
    raw_rows = []
    for table in data.get("tables", []) or []:
        raw_rows.extend(table.get("data", []) or [])
    if not raw_rows:
        raw_rows = data.get("aaData", []) or data.get("data", []) or []
    rows = []
    for row in raw_rows:
        try:
            parts = str(row[0]).strip().split("/")
            year = int(parts[0])
            if year < 1911:
                year += 1911
            d = f"{year:04d}-{int(parts[1]):02d}-{int(parts[2]):02d}"
            close = float(str(row[6]).replace(",", ""))
        except (ValueError, IndexError, TypeError):
            continue
        if close > 0:
            rows.append({"date": d, "close": close})
    return rows


def month_iter(start: date, end: date):
    cur = date(start.year, start.month, 1)
    while cur <= end:
        yield f"{cur.year:04d}{cur.month:02d}01"
        cur = date(cur.year + (cur.month == 12), cur.month % 12 + 1, 1)


def split_adjust(dates: list[str], closes: list[float]) -> list[float]:
    """Same back-adjustment as tools/backtest_00631L.py -- an unexplained
    single-day ratio outside plausible daily trading range is a split or
    consolidation, not a real move, and a replay game showing a fake 90%
    overnight cliff would just be teaching the wrong lesson."""
    adjusted = list(closes)
    for i in range(1, len(adjusted)):
        if adjusted[i - 1] <= 0:
            continue
        ratio = adjusted[i] / adjusted[i - 1]
        if ratio < 0.3 or ratio > 3.0:
            for j in range(i):
                adjusted[j] *= ratio
    return adjusted


def fetch_series(code: str, market: str, months: int) -> list[dict]:
    today = date.today()
    start_month = today.year * 12 + today.month - months
    start = date(start_month // 12, start_month % 12 + 1, 1)
    fetch = fetch_twse_month if market == "上市" else fetch_tpex_month

    by_date: dict[str, float] = {}
    for ym in month_iter(start, today):
        try:
            for row in fetch(code, ym):
                by_date[row["date"]] = row["close"]
        except Exception as e:  # noqa: BLE001
            print(f"warn: {code} {ym}: {e}", file=sys.stderr, flush=True)
        time.sleep(0.15)

    dates = sorted(by_date)
    closes = split_adjust(dates, [by_date[d] for d in dates])
    return [{"date": d, "close": round(c, 3)} for d, c in zip(dates, closes)]


def main() -> int:
    out = {}
    for code, name, market in SYMBOLS:
        t0 = time.time()
        print(f"fetching {code} {name} ({market})...", file=sys.stderr, flush=True)
        series = fetch_series(code, market, YEARS_BACK * 12)
        out[code] = {"name": name, "market": market, "series": series}
        print(f"{code} {name}: {len(series)} trading days ({time.time()-t0:.1f}s)", flush=True)

    payload = {"generated_at": date.today().isoformat(), "years_back": YEARS_BACK, "symbols": out}
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
    print(f"Wrote {OUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
