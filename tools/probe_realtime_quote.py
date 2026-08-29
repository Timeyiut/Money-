#!/usr/bin/env python3
"""One-off diagnostic: confirm mis.twse.com.tw's free real-time 5-level
quote endpoint is reachable from a GitHub Actions runner (it's blocked
from the local sandbox by the egress proxy) and print its raw response
so the real field layout can be checked before building a real collector
around it.

Not wired into any scheduled workflow -- run via workflow_dispatch only,
throwaway once the format is confirmed.
"""
from __future__ import annotations

import json
import sys
from urllib.request import Request, urlopen

HEADERS = {"User-Agent": "Mozilla/5.0"}

# ex_ch format: <exchange>_<code>.tw  (tse=上市, otc=上櫃)
CODES = ["tse_2330.tw", "tse_00631L.tw", "otc_3105.tw"]


def main() -> int:
    url = "https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch=" + "|".join(CODES) + "&json=1&delay=0"
    req = Request(url, headers=HEADERS)
    with urlopen(req, timeout=20) as resp:
        raw = resp.read()
    print("HTTP status:", resp.status)
    try:
        data = json.loads(raw)
        print(json.dumps(data, ensure_ascii=False, indent=2)[:4000])
    except Exception as e:  # noqa: BLE001
        print("Could not parse JSON:", e)
        print(raw[:2000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
