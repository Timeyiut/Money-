#!/usr/bin/env python3
"""Runs in CI. Same historical backtest as tools/backtest_momentum_screen.py
(the 6-condition momentum/breakout screen), but against a much broader
universe than the 9-stock watchlist: the top 50 TWSE-listed (上市) common
stocks by most recent trading value.

Why "top 50 by trading value" and not literally "the whole market" or
"the official 0050 index": scanning ~2000 listed securities' full daily
OHLCV history in one CI job isn't realistic against free public
endpoints (the 9-stock version already needs several hundred requests;
2000 stocks would be tens of thousands, both too slow for a CI job and
inconsiderate to a free public API). And there's no free, sandbox- or
CI-reachable feed of the *official* 0050 index membership -- that comes
from the fund manager's own holdings page or commercial data vendors.
Top-50-by-trading-value from TWSE's own STOCK_DAY_ALL is a reasonable,
fully self-contained proxy for "the large, liquid, actively-traded part
of the market" using a data source this project already trusts, and its
selection is disclosed plainly in the output rather than presented as
"the TWSE 50 index."

Scope: 上市 (TWSE) only, common stock codes only (plain 4-digit numeric
codes -- excludes ETFs, depositary receipts, preferred shares). 上櫃
(TPEx) names are excluded here; that's a real scope limit, not an
oversight.

This is still backtest-only, same as backtest_momentum_screen.py: it
measures what happened after the 6 conditions fired historically. It
does not output today's matches and is not a screener.

Writes data/backtest_momentum_screen_top50.json.
"""
from __future__ import annotations

import json
import sys
import time
from datetime import date
from urllib.request import Request, urlopen

from backtest_momentum_screen import HEADERS, HORIZONS, fetch_history, screen_stock, summarize

STOCK_DAY_ALL_URL = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
TOP_N = 50
REQUEST_TIMEOUT = 15


def fetch_top_n_universe(n: int) -> list[tuple[str, str, str]]:
    """Returns [(code, name, '上市'), ...] for the n TWSE-listed common
    stocks with the highest trading value on the most recent session.
    Filters to plain 4-digit numeric codes so ETFs/warrants/depositary
    receipts don't crowd out ordinary shares."""
    with urlopen(Request(STOCK_DAY_ALL_URL, headers=HEADERS), timeout=REQUEST_TIMEOUT) as resp:
        rows = json.loads(resp.read())

    candidates = []
    for row in rows:
        code = row.get("Code", "")
        # Plain common-stock codes only: 4 digits, not starting with "00"
        # (every TWSE-listed ETF -- 0050, 0056, 00631L's non-leveraged
        # siblings, etc. -- uses a 00xx-prefixed code).
        if not (len(code) == 4 and code.isdigit()) or code.startswith("00"):
            continue
        try:
            trade_value = float(str(row.get("TradeValue", "0")).replace(",", ""))
        except ValueError:
            continue
        candidates.append((trade_value, code, row.get("Name", code)))

    candidates.sort(key=lambda t: t[0], reverse=True)
    return [(code, name, "上市") for _, code, name in candidates[:n]]


def main() -> int:
    try:
        universe = fetch_top_n_universe(TOP_N)
    except Exception as e:  # noqa: BLE001
        print(f"error: could not fetch top-{TOP_N} universe: {e}", file=sys.stderr)
        return 1
    print(f"Universe: top {len(universe)} TWSE common stocks by trading value ({universe[0][1]}...{universe[-1][1]})")

    per_stock = []
    all_events = []
    for code, name, market in universe:
        history = fetch_history(code, market)
        if len(history) < 60:
            print(f"warn: {code} {name} only got {len(history)} trading days, skipping", file=sys.stderr)
            per_stock.append({"code": code, "name": name, "error": f"只取到 {len(history)} 個交易日，資料不足"})
            continue
        result = screen_stock(code, name, history)
        per_stock.append(result)
        all_events.extend(result["events"])
        print(f"{code} {name}: {result['trading_days']} 個交易日，{len(result['events'])} 次符合全部6條件")
        time.sleep(0.2)

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
        "universe": (
            f"TWSE（上市）成交金額前{TOP_N}大的一般股票（依產生當天最新一日成交金額排序），"
            "不是官方0050指數成分股名單，也不含上櫃股票——這是技術上可行、資料來源可自我驗證的近似"
            "「市場中大型活躍股」範圍，範圍選取方式已如實揭露，不宣稱等於0050。"
        ),
        "source": "TWSE STOCK_DAY_ALL（選股範圍）+ STOCK_DAY（個股日K）官方資料",
        "disclaimer": (
            "全部為機械式規則的歷史事件回顧統計，樣本數有限，"
            "不是訊號、不是預測、不是進出場建議，也不代表這6個條件今天是否成立。"
        ),
        "aggregate": summarize(all_events),
        "per_stock": per_stock,
    }
    with open("data/backtest_momentum_screen_top50.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(json.dumps(out["aggregate"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
