#!/usr/bin/env python3
"""Runs in CI. Historical backtest of a 6-condition momentum/breakout
screen against the same individual-stock watchlist tools/fetch_momentum.py
already tracks.

The 6 conditions (as given, unchanged):
  1. 股價位於月線之上            close > 20-day SMA of close
  2. 10日漲幅大於5%              close[i]/close[i-10] - 1 > 5%
  3. 股價1日振幅大於3%           (high-low)/prev_close > 3%
  4. 成交量創5日新高             today's volume is the max of the last 5 days
  5. 股價盤中創5日新高           today's high is the max of the last 5 days
  6. 5日均量大於1000張           mean(volume[-5:]) > 1,000,000 shares (1張=1000股)

This is the same kind of study as tools/backtest_00631L.py: a fixed,
mechanical rule evaluated the same way on every historical day, then a
fixed-horizon forward return is measured from each day the rule fired.
It answers "historically, what happened after all 6 conditions lined up
on this exact day" -- it does not pick a stock to buy, does not rank
candidates, and produces no signal for today. Running this same rule
against *today's* live data to output a buy list would be exactly the
stock-picking call this project deliberately stays out of; this script
only ever looks backward.

Universe: the existing WATCHLIST from tools/fetch_momentum.py (9 Taiwan
stocks already tracked in this repo) -- not a full-market scan, which
would need OHLCV history for every listed security and is far too much
CI time/bandwidth to fetch. Results describe how this rule would have
performed on these 9 names, nothing broader.

Price source: TWSE STOCK_DAY (上市) / TPEx tradingStock (上櫃), same
endpoints tools/fetch_momentum.py already uses, extended here to also
keep open/high/low (fetch_momentum.py only needed close+volume).

Writes data/backtest_momentum_screen.json.
"""
from __future__ import annotations

import json
import statistics
import sys
import time
from datetime import date
from urllib.request import Request, urlopen

HEADERS = {"User-Agent": "Mozilla/5.0"}
REQUEST_TIMEOUT = 15
YEARS_BACK = 2
HORIZONS = [5, 10, 20, 60]
SHARES_PER_LOT = 1000  # 1 張 = 1000 股

# Same 9-stock watchlist as tools/fetch_momentum.py.
WATCHLIST = [
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


def parse_ohlcv_row(row, volume_index: int, close_index: int, volume_scale: int):
    """Turns one exchange row into {date, open, high, low, close, volume}.
    Returns None for rows that aren't real trading days (holidays print
    '--' or blanks)."""
    try:
        parts = str(row[0]).strip().split("/")
        if len(parts) != 3:
            return None
        year = int(parts[0])
        if year < 1911:
            year += 1911
        d = f"{year:04d}-{int(parts[1]):02d}-{int(parts[2]):02d}"
        close = float(str(row[close_index]).replace(",", ""))
        open_ = float(str(row[close_index - 3]).replace(",", ""))
        high = float(str(row[close_index - 2]).replace(",", ""))
        low = float(str(row[close_index - 1]).replace(",", ""))
        volume = float(str(row[volume_index]).replace(",", "")) * volume_scale
    except (ValueError, IndexError, TypeError):
        return None
    if close <= 0 or high <= 0 or low <= 0:
        return None
    return {"date": d, "open": open_, "high": high, "low": low, "close": close, "volume": volume}


def fetch_twse_month(code: str, ym: str) -> list[dict]:
    url = f"https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY?date={ym}&stockNo={code}&response=json"
    with urlopen(Request(url, headers=HEADERS), timeout=REQUEST_TIMEOUT) as resp:
        data = json.loads(resp.read())
    if data.get("stat") != "OK":
        return []
    return [r for row in data.get("data", []) if (r := parse_ohlcv_row(row, 1, 6, 1))]


def fetch_tpex_month(code: str, ym: str) -> list[dict]:
    d = f"{ym[:4]}/{ym[4:6]}/01"
    url = f"https://www.tpex.org.tw/www/zh-tw/afterTrading/tradingStock?code={code}&date={d}&id=&response=json"
    with urlopen(Request(url, headers=HEADERS), timeout=REQUEST_TIMEOUT) as resp:
        data = json.loads(resp.read())
    raw_rows = []
    for table in data.get("tables", []) or []:
        raw_rows.extend(table.get("data", []) or [])
    if not raw_rows:
        raw_rows = data.get("aaData", []) or data.get("data", []) or []
    return [r for row in raw_rows if (r := parse_ohlcv_row(row, 1, 6, 1000))]


def month_iter(start: date, end: date):
    cur = date(start.year, start.month, 1)
    while cur <= end:
        yield f"{cur.year:04d}{cur.month:02d}01"
        cur = date(cur.year + (cur.month == 12), cur.month % 12 + 1, 1)


def fetch_history(code: str, market: str) -> list[dict]:
    today = date.today()
    start = date(today.year - YEARS_BACK, today.month, 1)
    fetch = fetch_twse_month if market == "上市" else fetch_tpex_month

    by_date: dict[str, dict] = {}
    for ym in month_iter(start, today):
        try:
            for row in fetch(code, ym):
                by_date[row["date"]] = row
        except Exception as e:  # noqa: BLE001
            print(f"warn: {code} {ym}: {e}", file=sys.stderr)
        time.sleep(0.3)
    return [by_date[d] for d in sorted(by_date)]


def screen_stock(code: str, name: str, history: list[dict]) -> dict:
    dates = [r["date"] for r in history]
    closes = [r["close"] for r in history]
    highs = [r["high"] for r in history]
    lows = [r["low"] for r in history]
    volumes = [r["volume"] for r in history]
    n = len(history)

    events = []
    for i in range(20, n):
        month_line = sum(closes[i - 19 : i + 1]) / 20
        cond1 = closes[i] > month_line
        cond2 = i >= 10 and (closes[i] / closes[i - 10] - 1) > 0.05
        cond3 = closes[i - 1] > 0 and (highs[i] - lows[i]) / closes[i - 1] > 0.03
        cond4 = i >= 4 and volumes[i] >= max(volumes[i - 4 : i + 1])
        cond5 = i >= 4 and highs[i] >= max(highs[i - 4 : i + 1])
        cond6 = i >= 4 and statistics.mean(volumes[i - 4 : i + 1]) > 1000 * SHARES_PER_LOT

        if not (cond1 and cond2 and cond3 and cond4 and cond5 and cond6):
            continue

        entry_price = closes[i]
        forward = {}
        for h in HORIZONS:
            j = i + h
            forward[str(h)] = round((closes[j] - entry_price) / entry_price * 100, 2) if j < n else None

        events.append({"date": dates[i], "close": round(entry_price, 2), "forward_return_pct": forward})

    return {"code": code, "name": name, "trading_days": n, "events": events}


def summarize(events: list[dict]) -> dict:
    out = {"events": len(events)}
    for h in HORIZONS:
        vals = [e["forward_return_pct"][str(h)] for e in events if e["forward_return_pct"][str(h)] is not None]
        if vals:
            out[f"avg_return_{h}d_pct"] = round(sum(vals) / len(vals), 2)
            out[f"win_rate_{h}d_pct"] = round(sum(1 for v in vals if v > 0) / len(vals) * 100, 1)
            out[f"sample_{h}d"] = len(vals)
        else:
            out[f"avg_return_{h}d_pct"] = None
            out[f"win_rate_{h}d_pct"] = None
            out[f"sample_{h}d"] = 0
    return out


def main() -> int:
    per_stock = []
    all_events = []
    for code, name, market in WATCHLIST:
        history = fetch_history(code, market)
        if len(history) < 60:
            print(f"warn: {code} {name} only got {len(history)} trading days, skipping", file=sys.stderr)
            per_stock.append({"code": code, "name": name, "error": f"只取到 {len(history)} 個交易日，資料不足"})
            continue
        result = screen_stock(code, name, history)
        per_stock.append(result)
        all_events.extend(result["events"])
        print(f"{code} {name}: {result['trading_days']} 個交易日，{len(result['events'])} 次符合全部6條件")

    out = {
        "generated_at": date.today().isoformat(),
        "conditions": [
            "股價位於月線（20日均線）之上",
            "10日漲幅大於5%",
            "股價1日振幅（(最高-最低)/前一日收盤）大於3%",
            "成交量創5日新高",
            "股價盤中最高價創5日新高",
            "5日均量大於1000張",
        ],
        "universe": "與 data/momentum.json 相同的9檔觀察名單，非全市場掃描",
        "source": "TWSE STOCK_DAY (上市) + TPEx tradingStock (上櫃) 官方日K資料",
        "disclaimer": (
            "全部為機械式規則的歷史事件回顧統計，樣本數有限，"
            "不是訊號、不是預測、不是進出場建議，也不代表這6個條件今天是否成立。"
        ),
        "aggregate": summarize(all_events),
        "per_stock": per_stock,
    }
    with open("data/backtest_momentum_screen.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(json.dumps(out["aggregate"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
