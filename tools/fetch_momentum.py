#!/usr/bin/env python3
"""Runs in CI. Measures where a watchlist of Taiwan stocks currently sits
inside its own 52-week price/volume history.

This is a *measuring tape*, not a signal generator. Every number below is
backward-looking and arithmetic — position inside the 52w range, trailing
returns, volume ratio, realised volatility. Nothing here forecasts a price,
scores a stock, or ranks them into a buy list. What the numbers mean for
your money is your call, not this script's.

Price history: TWSE STOCK_DAY for 上市, TPEx tradingStock for 上櫃. Both are
the exchanges' own published daily closes.

Writes data/momentum.json.

Optional env:
  DEBUG_DUMP=1   print the first raw response per source and exit early
"""
from __future__ import annotations

import json
import os
import statistics
import sys
import time
from datetime import date
from urllib.request import Request, urlopen

HEADERS = {"User-Agent": "Mozilla/5.0"}

# code, display name, market. Market decides which exchange endpoint to hit.
# 上市 = TWSE, 上櫃 = TPEx.
WATCHLIST = [
    ("3105", "穩懋", "上櫃", "砷化鎵/磷化銦 磊晶代工"),
    ("8021", "尖點", "上櫃", "微鑽針・CNC 刀具"),
    ("4979", "華星光", "上櫃", "光通訊 光收發模組"),
    ("3363", "上詮", "上櫃", "光通訊 被動元件"),
    ("4977", "眾達-KY", "上櫃", "光通訊 收發模組"),
    ("3450", "聯鈞", "上櫃", "光電 雷射模組"),
    ("6451", "訊芯-KY", "上市", "IC 封裝測試"),
    ("3587", "閎康", "上市", "半導體材料分析"),
    ("3289", "宜特", "上市", "半導體驗證分析"),
]


def fetch_twse_month(code: str, ym: str) -> list[dict]:
    url = (
        "https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY"
        f"?date={ym}&stockNo={code}&response=json"
    )
    with urlopen(Request(url, headers=HEADERS), timeout=25) as resp:
        data = json.loads(resp.read())
    if data.get("stat") != "OK":
        return []
    rows = []
    for row in data.get("data", []):
        parsed = parse_roc_row(row, volume_index=1, close_index=6, volume_scale=1)
        if parsed:
            rows.append(parsed)
    return rows


def fetch_tpex_month(code: str, ym: str) -> list[dict]:
    # TPEx wants YYYY/MM/DD and returns the whole month for that stock.
    d = f"{ym[:4]}/{ym[4:6]}/01"
    url = (
        "https://www.tpex.org.tw/www/zh-tw/afterTrading/tradingStock"
        f"?code={code}&date={d}&id=&response=json"
    )
    with urlopen(Request(url, headers=HEADERS), timeout=25) as resp:
        data = json.loads(resp.read())
    raw_rows = []
    for table in data.get("tables", []) or []:
        raw_rows.extend(table.get("data", []) or [])
    if not raw_rows:
        raw_rows = data.get("aaData", []) or data.get("data", []) or []
    rows = []
    for row in raw_rows:
        # TPEx daily columns: 日期 成交仟股 成交仟元 開盤 最高 最低 收盤 漲跌 筆數
        parsed = parse_roc_row(row, volume_index=1, close_index=6, volume_scale=1000)
        if parsed:
            rows.append(parsed)
    return rows


def parse_roc_row(row, volume_index: int, close_index: int, volume_scale: int):
    """Turns one exchange row into {date, close, volume}. Returns None for
    rows that aren't real trading days (holidays print '--' or blanks)."""
    try:
        parts = str(row[0]).strip().split("/")
        if len(parts) != 3:
            return None
        year = int(parts[0])
        if year < 1911:  # ROC year
            year += 1911
        d = f"{year:04d}-{int(parts[1]):02d}-{int(parts[2]):02d}"
        close = float(str(row[close_index]).replace(",", ""))
        volume = float(str(row[volume_index]).replace(",", "")) * volume_scale
    except (ValueError, IndexError, TypeError):
        return None
    if close <= 0:
        return None
    return {"date": d, "close": close, "volume": volume}


def month_iter(start: date, end: date):
    cur = date(start.year, start.month, 1)
    while cur <= end:
        yield f"{cur.year:04d}{cur.month:02d}01"
        cur = date(cur.year + (cur.month == 12), cur.month % 12 + 1, 1)


def fetch_history(code: str, market: str, months: int = 15) -> list[dict]:
    today = date.today()
    start_month = today.year * 12 + today.month - months
    start = date(start_month // 12, start_month % 12 + 1, 1)
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


def trailing_return(closes: list[float], days: int):
    if len(closes) <= days:
        return None
    return round((closes[-1] / closes[-1 - days] - 1) * 100, 2)


def measure(code, name, market, note) -> dict:
    history = fetch_history(code, market)
    if len(history) < 60:
        return {
            "code": code, "name": name, "market": market, "note": note,
            "error": f"只取到 {len(history)} 個交易日，資料不足以計算",
        }

    closes = [r["close"] for r in history]
    volumes = [r["volume"] for r in history]
    window = history[-250:] if len(history) >= 250 else history
    w_closes = [r["close"] for r in window]

    high52, low52 = max(w_closes), min(w_closes)
    last = closes[-1]
    span = high52 - low52
    position = round((last - low52) / span * 100, 1) if span > 0 else None

    vol5 = statistics.mean(volumes[-5:])
    vol60 = statistics.mean(volumes[-60:])

    daily_returns = [closes[i] / closes[i - 1] - 1 for i in range(1, len(closes))][-250:]
    annual_vol = round(statistics.pstdev(daily_returns) * (252 ** 0.5) * 100, 1)

    return {
        "code": code,
        "name": name,
        "market": market,
        "note": note,
        "last_date": history[-1]["date"],
        "last_close": round(last, 2),
        "high_52w": round(high52, 2),
        "low_52w": round(low52, 2),
        "range_position_pct": position,
        "below_high_pct": round((last / high52 - 1) * 100, 2),
        "above_low_pct": round((last / low52 - 1) * 100, 2),
        "return_20d_pct": trailing_return(closes, 20),
        "return_60d_pct": trailing_return(closes, 60),
        "return_250d_pct": trailing_return(closes, 250),
        "volume_ratio_5d_60d": round(vol5 / vol60, 2) if vol60 > 0 else None,
        "annualised_vol_pct": annual_vol,
        "trading_days": len(history),
    }


def main() -> int:
    if os.environ.get("DEBUG_DUMP"):
        for code, market in (("3289", "上市"), ("3105", "上櫃")):
            fetch = fetch_twse_month if market == "上市" else fetch_tpex_month
            ym = f"{date.today().year:04d}{date.today().month:02d}01"
            url_kind = "TWSE" if market == "上市" else "TPEx"
            try:
                rows = fetch(code, ym)
                print(f"{url_kind} {code}: {len(rows)} rows -> {rows[:3]}")
            except Exception as e:  # noqa: BLE001
                print(f"{url_kind} {code}: FAILED {e}")
        return 0

    results = [measure(*item) for item in WATCHLIST]

    out = {
        "generated_at": date.today().isoformat(),
        "source": "TWSE STOCK_DAY (上市) + TPEx tradingStock (上櫃) 官方每日收盤資料",
        "disclaimer": (
            "全部為回顧性統計，非預測、非評分、非推薦。位階高低不代表未來漲跌。"
        ),
        "stocks": results,
    }
    with open("data/momentum.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
        f.write("\n")

    for r in results:
        if "error" in r:
            print(f"{r['code']} {r['name']}: {r['error']}")
        else:
            print(
                f"{r['code']} {r['name']}: {r['last_close']} "
                f"位階 {r['range_position_pct']}% 距高 {r['below_high_pct']}% "
                f"量比 {r['volume_ratio_5d_60d']} 60日 {r['return_60d_pct']}%"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
