#!/usr/bin/env python3
"""One-off probe: try a few candidate TWSE endpoints/params for a
per-stock historical ex-dividend list and print what each actually
returns, so the real one can be identified from live evidence instead
of guessing. Delete this file once backtest_00919.py is fixed."""
import json
from urllib.request import Request, urlopen

HEADERS = {"User-Agent": "Mozilla/5.0"}


def try_fetch(label, url):
    print(f"\n=== {label} ===\n{url}")
    try:
        req = Request(url, headers=HEADERS)
        with urlopen(req, timeout=20) as resp:
            body = resp.read().decode("utf-8", errors="replace")
        print(body[:1500])
    except Exception as e:  # noqa: BLE001
        print(f"ERROR: {e}")


try_fetch(
    "TWT49U with stockNo param",
    "https://www.twse.com.tw/rwd/zh/exRight/TWT49U?stockNo=00919&response=json",
)
try_fetch(
    "TWT49U with date range + stkNo",
    "https://www.twse.com.tw/rwd/zh/exRight/TWT49U?date=20260101&stkNo=00919&response=json",
)
try_fetch(
    "openapi.twse.com.tw t187ap09 (股利分派情形)",
    "https://openapi.twse.com.tw/v1/opendata/t187ap09_L",
)
try_fetch(
    "openapi.twse.com.tw exRight list",
    "https://openapi.twse.com.tw/v1/exchangeReport/TWT49U",
)
