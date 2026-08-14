#!/usr/bin/env python3
"""Runs in CI only. Pulls daily closing prices for the holdings tracked in
index.html's HOLDINGS array and writes data/prices.json.

Sources, tried in order per code:
  1. TWSE OpenAPI STOCK_DAY_ALL   — 上市
  2. TPEx OpenAPI daily quotes    — 上櫃

Both are official, public, no auth needed. These are the previous/latest
trading day's *closing* prices, not an intraday tick feed — that's a
deliberate tradeoff, it's the only free data realistically callable
without a backend.

Two robustness rules, both learned from real failures:
  - A code that can't be resolved never fails the run. Earlier this script
    returned 1 on any miss, which failed the workflow step and skipped the
    commit entirely, so one unknown code froze *all* prices at their old
    values.
  - A code missing from today's feed keeps its last known price from the
    existing prices.json (with that older date attached) instead of
    disappearing, so the page doesn't silently fall back to cost basis.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.request import Request, urlopen

CODES = ["00878", "00981A", "6531", "00405A", "1303", "00955"]

TWSE_URL = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
TPEX_URL = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes"
OUT_PATH = Path("data/prices.json")


def fetch_json(url: str):
    req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def first_field(row: dict, *names: str):
    """The two exchanges name their columns differently, and TPEx has
    renamed its fields before. Take whichever key is actually present."""
    for name in names:
        value = row.get(name)
        if value not in (None, "", "--"):
            return value
    return None


def index_twse(rows) -> dict[str, dict]:
    out = {}
    for row in rows:
        code = row.get("Code")
        if not code:
            continue
        out[code] = {
            "name": row.get("Name"),
            "close": row.get("ClosingPrice"),
            "date": row.get("Date"),
            "source": "TWSE",
        }
    return out


def index_tpex(rows) -> dict[str, dict]:
    out = {}
    for row in rows:
        code = first_field(row, "SecuritiesCompanyCode", "Code", "CompanyCode")
        if not code:
            continue
        out[str(code).strip()] = {
            "name": first_field(row, "CompanyName", "Name"),
            "close": first_field(row, "Close", "ClosingPrice"),
            "date": first_field(row, "Date", "date"),
            "source": "TPEx",
        }
    return out


def main() -> int:
    lookup: dict[str, dict] = {}
    for label, url, indexer in (
        ("TWSE", TWSE_URL, index_twse),
        ("TPEx", TPEX_URL, index_tpex),
    ):
        try:
            rows = fetch_json(url)
            found = indexer(rows)
            # TWSE is queried first and wins ties; only fill gaps from TPEx.
            for code, data in found.items():
                lookup.setdefault(code, data)
            print(f"{label}: indexed {len(found)} securities")
        except Exception as e:  # noqa: BLE001
            print(f"warn: {label} fetch failed: {e}", file=sys.stderr)

    previous = {}
    if OUT_PATH.exists():
        try:
            previous = {row["code"]: row for row in json.loads(OUT_PATH.read_text())}
        except Exception as e:  # noqa: BLE001
            print(f"warn: could not read existing {OUT_PATH}: {e}", file=sys.stderr)

    out = []
    fresh, stale, missing = [], [], []
    for code in CODES:
        hit = lookup.get(code)
        if hit and hit.get("close") not in (None, "", "--"):
            out.append(
                {
                    "code": code,
                    "name": hit["name"],
                    "close": hit["close"],
                    "date": hit["date"],
                }
            )
            fresh.append(code)
        elif code in previous:
            out.append(previous[code])
            stale.append(f"{code}(keeping {previous[code].get('date')})")
        else:
            missing.append(code)

    if stale:
        print(f"Not in today's feed, kept last known: {', '.join(stale)}", file=sys.stderr)
    if missing:
        print(f"No price found and no previous value: {', '.join(missing)}", file=sys.stderr)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n")
    print(f"Wrote {len(out)} price(s) to {OUT_PATH} ({len(fresh)} fresh)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
