#!/usr/bin/env python3
"""Runs in CI only. Pulls daily closing prices for the holdings tracked in
index.html's HOLDINGS array and writes data/prices.json.

Sources, tried in order per code:
  1. Yahoo Finance chart API  — small per-stock request, covers 上市 (.TW)
     and 上櫃 (.TWO) alike, and carries the *current* session's price
     rather than waiting for an end-of-day file.
  2. TWSE OpenAPI STOCK_DAY_ALL  — 上市, official
  3. TPEx OpenAPI daily quotes   — 上櫃, official

Yahoo leads because the two official bulk files were measured to be a day
behind at 16:23 Taipei (run 31783672530) and TPEx's ~4MB payload aborts
mid-stream often enough to wipe out every 上櫃 holding. The official
endpoints stay as fallbacks so a third party changing its API can't leave
the page with no data at all.

Market suffix is discovered, not hardcoded: each code tries .TW then .TWO.
Guessing 上市/上櫃 by code prefix has already produced wrong answers in
this repo (see tools/fetch_momentum.py's history), so this asks instead.

Robustness rules, both learned from real failures:
  - An unresolvable code never fails the run. Returning 1 on any miss
    failed the workflow step, skipped the commit, and froze *every* price.
  - A code missing from today's feeds keeps its last known price (with
    that older date attached) rather than disappearing, which would make
    the page silently fall back to cost basis.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen

CODES = ["00981A", "00405A", "00955"]  # 00878/6531/1303 dropped: 華南 holdings cleared out, nothing left tracking them

YAHOO_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=5d"
TWSE_URL = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
TPEX_URL = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes"
OUT_PATH = Path("data/prices.json")

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json",
    "Accept-Encoding": "identity",
    "Connection": "close",
}


def fetch_json(url: str, attempts: int = 4, timeout: int = 60):
    """TPEx's multi-megabyte payload routinely cuts the stream short
    (IncompleteRead), so every source retries with backoff and asks for an
    unencoded body."""
    last_error = None
    for attempt in range(1, attempts + 1):
        try:
            with urlopen(Request(url, headers=HEADERS), timeout=timeout) as resp:
                return json.loads(resp.read())
        except Exception as e:  # noqa: BLE001
            last_error = e
            if attempt < attempts:
                time.sleep(2 * attempt)
    raise last_error


def fetch_yahoo(code: str) -> dict | None:
    for suffix in (".TW", ".TWO"):
        try:
            data = fetch_json(YAHOO_URL.format(symbol=code + suffix), attempts=2, timeout=25)
        except Exception:  # noqa: BLE001
            continue
        try:
            meta = data["chart"]["result"][0]["meta"]
        except (KeyError, IndexError, TypeError):
            continue
        price = meta.get("regularMarketPrice")
        if price in (None, 0):
            continue
        stamp = meta.get("regularMarketTime")
        date = time.strftime("%Y-%m-%d", time.gmtime(stamp + 8 * 3600)) if stamp else None
        return {
            "name": meta.get("longName") or meta.get("shortName") or code,
            "close": f"{float(price):.2f}",
            "date": date,
            "source": f"Yahoo{suffix}",
        }
    return None


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
        if code:
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
        if code:
            out[str(code).strip()] = {
                "name": first_field(row, "CompanyName", "Name"),
                "close": first_field(row, "Close", "ClosingPrice"),
                "date": first_field(row, "Date", "date"),
                "source": "TPEx",
            }
    return out


def load_official() -> dict[str, dict]:
    lookup: dict[str, dict] = {}
    for label, url, indexer in (
        ("TWSE", TWSE_URL, index_twse),
        ("TPEx", TPEX_URL, index_tpex),
    ):
        try:
            found = indexer(fetch_json(url))
            for code, data in found.items():
                lookup.setdefault(code, data)  # TWSE queried first, wins ties
            print(f"{label}: indexed {len(found)} securities")
        except Exception as e:  # noqa: BLE001
            print(f"warn: {label} fetch failed: {e}", file=sys.stderr)
    return lookup


def main() -> int:
    resolved: dict[str, dict] = {}
    for code in CODES:
        hit = fetch_yahoo(code)
        if hit:
            resolved[code] = hit
        time.sleep(0.4)
    print(f"Yahoo: resolved {len(resolved)}/{len(CODES)}")

    if len(resolved) < len(CODES):
        official = load_official()
        for code in CODES:
            if code not in resolved and code in official:
                hit = official[code]
                if hit.get("close") not in (None, "", "--"):
                    resolved[code] = hit

    previous = {}
    if OUT_PATH.exists():
        try:
            previous = {row["code"]: row for row in json.loads(OUT_PATH.read_text())}
        except Exception as e:  # noqa: BLE001
            print(f"warn: could not read existing {OUT_PATH}: {e}", file=sys.stderr)

    out, stale, missing = [], [], []
    for code in CODES:
        hit = resolved.get(code)
        if hit:
            out.append(
                {
                    "code": code,
                    "name": hit["name"],
                    "close": hit["close"],
                    "date": hit["date"],
                    "source": hit["source"],
                }
            )
        elif code in previous:
            out.append(previous[code])
            stale.append(f"{code}(keeping {previous[code].get('date')})")
        else:
            missing.append(code)

    if stale:
        print(f"Not in any feed, kept last known: {', '.join(stale)}", file=sys.stderr)
    if missing:
        print(f"No price and no previous value: {', '.join(missing)}", file=sys.stderr)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n")
    for row in out:
        print(f"  {row['code']:<7} {row['close']:>9}  {row['date']}  {row.get('source','?')}")
    print(f"Wrote {len(out)} price(s) to {OUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
