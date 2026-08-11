#!/usr/bin/env python3
"""Last probe: CMoney forum stock page, which may server-render dividend
history into the HTML (unlike Yuanta's client-rendered SPA). Delete once
resolved."""
from urllib.request import Request, urlopen

HEADERS = {"User-Agent": "Mozilla/5.0"}


def try_fetch(label, url):
    print(f"\n=== {label} ===\n{url}")
    try:
        req = Request(url, headers=HEADERS)
        with urlopen(req, timeout=20) as resp:
            body = resp.read().decode("utf-8", errors="replace")
        # look for anything resembling a dividend table/keyword hits
        for kw in ["除息", "股利", "配息", "dividend"]:
            idx = body.find(kw)
            if idx != -1:
                print(f"[found '{kw}' at {idx}] ...{body[max(0,idx-100):idx+400]}...")
        print(f"(total length {len(body)})")
    except Exception as e:  # noqa: BLE001
        print(f"ERROR: {e}")


try_fetch("CMoney forum stock page", "https://www.cmoney.tw/forum/stock/00919")
try_fetch("CMoney ETF dividend page", "https://www.cmoney.tw/etf/tw/00919-dividend")
