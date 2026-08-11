#!/usr/bin/env python3
"""Runs in CI only. Pulls TWSE daily closing prices for the holdings
tracked in index.html's HOLDINGS array and writes data/prices.json.

Source: TWSE OpenAPI STOCK_DAY_ALL — official, public, no auth needed.
This is the previous/latest trading day's closing price, not an
intraday tick feed. That's a deliberate tradeoff: it's the only free
data source that's realistically callable without a backend, and it's
plenty fresh for a personal dashboard checked every so often rather
than used for trading decisions.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.request import Request, urlopen

CODES = ["00878", "00981A", "6531"]
URL = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"


def main() -> int:
    req = Request(URL, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(req, timeout=20) as resp:
        rows = json.loads(resp.read())

    by_code = {row.get("Code"): row for row in rows}
    out = []
    missing = []
    for code in CODES:
        row = by_code.get(code)
        if not row:
            missing.append(code)
            continue
        out.append(
            {
                "code": code,
                "name": row.get("Name"),
                "close": row.get("ClosingPrice"),
                "date": row.get("Date"),
            }
        )

    if missing:
        print(f"Warning: codes not found in TWSE data: {missing}", file=sys.stderr)

    out_path = Path("data/prices.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n")
    print(f"Wrote {len(out)} price(s) to {out_path}")
    return 0 if not missing else 1


if __name__ == "__main__":
    sys.exit(main())
