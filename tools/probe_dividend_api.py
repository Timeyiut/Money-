#!/usr/bin/env python3
"""Final probe round: legacy flat endpoint + the ETFortune page (may embed
JSON). Delete once resolved."""
from urllib.request import Request, urlopen

HEADERS = {"User-Agent": "Mozilla/5.0"}


def try_fetch(label, url):
    print(f"\n=== {label} ===\n{url}")
    try:
        req = Request(url, headers=HEADERS)
        with urlopen(req, timeout=20) as resp:
            body = resp.read().decode("utf-8", errors="replace")
        print(body[:2500])
    except Exception as e:  # noqa: BLE001
        print(f"ERROR: {e}")


try_fetch(
    "legacy flat TWT49U",
    "https://www.twse.com.tw/exchangeReport/TWT49U?response=json&date=20240101&stockNo=00919",
)
try_fetch(
    "ETFortune institute page (may embed JSON)",
    "https://www.twse.com.tw/zh/ETFortune-institute/etfInfo/00919",
)
