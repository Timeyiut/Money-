#!/usr/bin/env python3
"""Runs in CI only. Polls mis.twse.com.tw's free 5-level quote endpoint
throughout a single trading session and appends every snapshot to
data/orderbook/orderbook_<date>.jsonl.

Why this exists: tools/simulate_avellaneda_stoikov.py had to assume its
order-arrival-intensity parameters (A, k) because no free source publishes
real order-book fill-rate data for Taiwan-listed stocks. The user rejected
that ("不需要模擬的數據") and asked for a collector that accumulates real
intraday 5-level snapshots on the next trading day instead.

Honest limits, disclosed to the user before this was written and still
true after it: this is periodic-snapshot data (one poll every
POLL_INTERVAL_SECONDS), not tick-level order flow. It can support a real
estimate of intraday mid-price volatility and bid/ask spread behaviour.
It CANNOT rigorously recover order-arrival intensity the way tick data
would -- any A/k derived from it later is still an approximation, just a
better-grounded one than borrowing the paper's own illustrative numbers.

Mechanics:
  - One HTTP request per poll covers all SYMBOLS (pipe-separated ex_ch).
  - Runs until Taipei local time passes SESSION_END, or until
    MAX_RUNTIME_SECONDS elapses, whichever comes first (a hard backstop
    in case clock math or the workflow's cron is ever off).
  - Self-commits every COMMIT_EVERY_N_POLLS polls so a killed/timed-out
    job still leaves most of the day's data pushed, not just what was
    sitting in an uncommitted working tree when it died.
  - A single symbol failing to resolve in a poll is logged and skipped;
    it never aborts the whole poll (one flaky response shouldn't blank
    out every other symbol's snapshot for that timestamp).
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.request import Request, urlopen

HEADERS = {"User-Agent": "Mozilla/5.0"}

# ex_ch format: <exchange>_<code>.tw  (tse=上市, otc=上櫃)
# Same symbols used in simulate_avellaneda_stoikov.py's calibration pass.
SYMBOLS = ["tse_00631L.tw", "otc_3105.tw", "tse_8021.tw", "tse_00919.tw"]

QUOTE_URL = "https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch=" + "|".join(SYMBOLS) + "&json=1&delay=0"

TAIPEI_OFFSET = timedelta(hours=8)
SESSION_END_HOUR, SESSION_END_MINUTE = 13, 35  # 5 min past the 13:30 bell, buffer for a late last tick
MAX_RUNTIME_SECONDS = 5 * 3600  # hard backstop regardless of wall-clock math
POLL_INTERVAL_SECONDS = 20
COMMIT_EVERY_N_POLLS = 30  # ~10 min at the interval above

OUT_DIR = Path("data/orderbook")


def taipei_now() -> datetime:
    return datetime.now(timezone.utc) + TAIPEI_OFFSET


def fetch_snapshot() -> dict | None:
    try:
        req = Request(QUOTE_URL, headers=HEADERS)
        with urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except Exception as e:  # noqa: BLE001
        print(f"warn: quote fetch failed: {e}", file=sys.stderr)
        return None


def extract_row(msg: dict, polled_at: str) -> dict:
    def levels(key: str) -> list[str]:
        raw = msg.get(key, "")
        return [x for x in raw.split("_") if x != ""]

    return {
        "polled_at": polled_at,
        "code": msg.get("c"),
        "name": msg.get("n"),
        "exchange": msg.get("ex"),
        "quote_time": msg.get("t"),
        "quote_date": msg.get("d") or msg.get("^"),
        "last": msg.get("z"),
        "prev_close": msg.get("y"),
        "open": msg.get("o"),
        "high": msg.get("h"),
        "low": msg.get("l"),
        "volume": msg.get("v"),
        "bid_prices": levels("b"),
        "bid_sizes": levels("g"),
        "ask_prices": levels("a"),
        "ask_sizes": levels("f"),
    }


def commit_and_push(out_path: Path, n_polls: int) -> None:
    try:
        subprocess.run(["git", "add", str(out_path)], check=True)
        diff = subprocess.run(["git", "diff", "--cached", "--quiet"])
        if diff.returncode == 0:
            return  # nothing new staged
        subprocess.run(
            ["git", "commit", "-m", f"chore: append order book snapshots ({n_polls} polls so far)"],
            check=True,
        )
        subprocess.run(["git", "push"], check=True)
        print(f"Committed and pushed after {n_polls} polls.")
    except subprocess.CalledProcessError as e:  # noqa: BLE001
        # A failed periodic commit must not kill the collection loop --
        # the next periodic commit, or the final one, can still catch up.
        print(f"warn: periodic commit/push failed: {e}", file=sys.stderr)


def main() -> int:
    started = time.monotonic()
    today = taipei_now().strftime("%Y-%m-%d")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / f"orderbook_{today}.jsonl"

    session_end = taipei_now().replace(
        hour=SESSION_END_HOUR, minute=SESSION_END_MINUTE, second=0, microsecond=0
    )

    n_polls = 0
    n_rows = 0
    with open(out_path, "a", encoding="utf-8") as fh:
        while True:
            now = taipei_now()
            if now >= session_end:
                print(f"Reached session end ({SESSION_END_HOUR:02d}:{SESSION_END_MINUTE:02d} Taipei). Stopping.")
                break
            if time.monotonic() - started >= MAX_RUNTIME_SECONDS:
                print("Reached max runtime backstop. Stopping.")
                break

            data = fetch_snapshot()
            polled_at = now.strftime("%Y-%m-%dT%H:%M:%S+08:00")
            if data and data.get("msgArray"):
                for msg in data["msgArray"]:
                    row = extract_row(msg, polled_at)
                    fh.write(json.dumps(row, ensure_ascii=False) + "\n")
                    n_rows += 1
                fh.flush()
            else:
                print(f"warn: no msgArray in response at {polled_at}", file=sys.stderr)

            n_polls += 1
            if n_polls % COMMIT_EVERY_N_POLLS == 0:
                commit_and_push(out_path, n_polls)

            time.sleep(POLL_INTERVAL_SECONDS)

    commit_and_push(out_path, n_polls)
    print(f"Done. {n_polls} polls, {n_rows} snapshot rows written to {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
