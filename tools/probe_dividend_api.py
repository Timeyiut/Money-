#!/usr/bin/env python3
"""Final probe: MOPS (公開資訊觀測站) per-company dividend distribution
query, and Yuanta's public dividend content page. Delete once resolved."""
from urllib.request import Request, urlopen
from urllib.parse import urlencode

HEADERS = {"User-Agent": "Mozilla/5.0"}


def try_fetch(label, url, data=None, method="GET"):
    print(f"\n=== {label} ===\n{url}")
    try:
        body_bytes = urlencode(data).encode() if data else None
        req = Request(url, data=body_bytes, headers=HEADERS, method=method)
        with urlopen(req, timeout=20) as resp:
            body = resp.read().decode("utf-8", errors="replace")
        print(body[:2000])
    except Exception as e:  # noqa: BLE001
        print(f"ERROR: {e}")


# MOPS 股利分派情形 (t05st09) — historically POST-based, per-company query
try_fetch(
    "MOPS t05st09 dividend query",
    "https://mops.twse.com.tw/mops/web/ajax_t05st09",
    data={"encodeURIComponent": "1", "step": "1", "co_id": "00919", "year": ""},
    method="POST",
)
try_fetch(
    "Yuanta dividend content page",
    "https://www.yuanta.com.tw/file-repository/content/dividend/index.html",
)
