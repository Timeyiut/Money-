#!/usr/bin/env python3
"""Runs in CI only. Searches Gmail for bank e-statement PDFs, unlocks the
password-protected ones with candidates derived from the account holder's
ID number / birthday, pulls out a headline balance figure, and appends the
result to data/statements.json.

Nothing sensitive is ever written to disk or logged:
- the PDF password candidates only ever live in memory for this process
- the raw PDF bytes and decrypted text are never written to the repo
- only the small structured fields below end up in data/statements.json

Required environment variables (set as GitHub Actions secrets):
  GMAIL_CLIENT_ID
  GMAIL_CLIENT_SECRET
  GMAIL_REFRESH_TOKEN     -- from tools/gmail_oauth_setup.py
  BANK_ID_NUMBER          -- e.g. A123456789
  BANK_BIRTHDAY           -- e.g. 1990-01-31

Optional:
  GMAIL_SEARCH_QUERY      -- overrides the default Gmail search query
  STATEMENTS_JSON_PATH    -- defaults to data/statements.json
"""
from __future__ import annotations

import base64
import io
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import pikepdf
import pdfplumber
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

DEFAULT_QUERY = (
    '(subject:(對帳單 OR 帳單 OR 月結 OR 月結單 OR 交易明細 OR statement OR e-statement) '
    'has:attachment filename:pdf) -subject:消費通知 newer_than:45d'
)

BALANCE_PATTERNS = [
    re.compile(r"(本期應繳|應繳總金額|本期帳單金額)[^\d]{0,10}([\d,]+)"),
    re.compile(r"(帳戶餘額|存款餘額|活期存款餘額)[^\d]{0,10}([\d,]+)"),
    re.compile(r"(信用卡.{0,4}應繳|Total Amount Due)[^\d]{0,10}([\d,]+)"),
]


def build_password_candidates(id_number: str, birthday: str) -> list[str]:
    """PDF-password conventions used by the banks that actually send to this
    inbox, built from ID number + birthday. Tried in order until one unlocks
    the file.

    The rules are stated in the statement emails themselves:
      華南/永豐/國泰/王道/土銀/兆豐  full ID number, uppercase
      台新信用卡                     last 2 of ID + MMDD  (6 chars)
      星展信用卡                     last 4 of ID + MMDD  (8 chars)

    None of those need a birth year, so BANK_BIRTHDAY accepts either just
    "MM-DD" / "MMDD", or a full "YYYY-MM-DD" if you'd rather also try the
    year-based formats some other banks use (kept below as a fallback).
    """
    id_number = id_number.strip().upper()
    digits = re.sub(r"\D", "", birthday)
    if len(digits) == 4:  # MM-DD or MMDD, no year supplied
        y = None
        m, d = int(digits[:2]), int(digits[2:])
    else:  # YYYY-MM-DD or YYYYMMDD
        y, m, d = int(digits[:-4]), int(digits[-4:-2]), int(digits[-2:])
    mmdd = f"{m:02d}{d:02d}"

    candidates = [
        id_number,
        id_number[-2:] + mmdd,
        id_number[-4:] + mmdd,
        id_number + mmdd,
    ]
    if y is not None:
        yyyymmdd = f"{y:04d}{mmdd}"
        candidates += [
            yyyymmdd,
            id_number + yyyymmdd,
            f"{y % 100:02d}{mmdd}",
            f"{y - 1911:03d}{mmdd}",
            id_number + f"{y - 1911:03d}{mmdd}",
        ]
    # de-dupe while preserving order
    seen = set()
    result = []
    for c in candidates:
        if c not in seen:
            seen.add(c)
            result.append(c)
    return result


def try_unlock_and_extract(pdf_bytes: bytes, passwords: list[str]) -> str | None:
    """Returns extracted text, or None if the PDF couldn't be opened."""
    # Try unprotected first.
    attempts = [None] + passwords
    for pw in attempts:
        try:
            with pikepdf.open(io.BytesIO(pdf_bytes), password=pw or "") as pdf:
                buf = io.BytesIO()
                pdf.save(buf)
                buf.seek(0)
                with pdfplumber.open(buf) as doc:
                    return "\n".join(page.extract_text() or "" for page in doc.pages)
        except pikepdf.PasswordError:
            continue
        except Exception:
            continue
    return None


def extract_amount(text: str) -> tuple[str, str] | tuple[None, None]:
    for pattern in BALANCE_PATTERNS:
        match = pattern.search(text)
        if match:
            return match.group(1), match.group(2)
    return None, None


def gmail_service():
    creds = Credentials(
        token=None,
        refresh_token=os.environ["GMAIL_REFRESH_TOKEN"],
        client_id=os.environ["GMAIL_CLIENT_ID"],
        client_secret=os.environ["GMAIL_CLIENT_SECRET"],
        token_uri="https://oauth2.googleapis.com/token",
    )
    return build("gmail", "v1", credentials=creds)


def iter_pdf_attachments(service, message_id: str):
    msg = service.users().messages().get(userId="me", id=message_id).execute()
    parts = msg.get("payload", {}).get("parts", []) or []
    stack = list(parts)
    while stack:
        part = stack.pop()
        stack.extend(part.get("parts", []) or [])
        filename = part.get("filename") or ""
        if not filename.lower().endswith(".pdf"):
            continue
        body = part.get("body", {})
        attachment_id = body.get("attachmentId")
        if not attachment_id:
            continue
        attachment = (
            service.users()
            .messages()
            .attachments()
            .get(userId="me", messageId=message_id, id=attachment_id)
            .execute()
        )
        data = base64.urlsafe_b64decode(attachment["data"])
        yield filename, data, msg


def main() -> int:
    id_number = os.environ["BANK_ID_NUMBER"]
    birthday = os.environ["BANK_BIRTHDAY"]
    query = os.environ.get("GMAIL_SEARCH_QUERY", DEFAULT_QUERY)
    out_path = Path(os.environ.get("STATEMENTS_JSON_PATH", "data/statements.json"))

    passwords = build_password_candidates(id_number, birthday)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    existing = json.loads(out_path.read_text()) if out_path.exists() else []
    seen_ids = {row["message_id"] for row in existing}

    service = gmail_service()
    results = service.users().messages().list(userId="me", q=query, maxResults=25).execute()
    messages = results.get("messages", [])

    new_rows = []
    for m in messages:
        if m["id"] in seen_ids:
            continue
        for filename, pdf_bytes, msg in iter_pdf_attachments(service, m["id"]):
            text = try_unlock_and_extract(pdf_bytes, passwords)
            headers = {h["name"]: h["value"] for h in msg["payload"].get("headers", [])}
            row = {
                "message_id": m["id"],
                "subject": headers.get("Subject", ""),
                "from": headers.get("From", ""),
                "date": headers.get("Date", ""),
                "attachment": filename,
                "unlocked": text is not None,
                "fetched_at": datetime.now(timezone.utc).isoformat(),
            }
            if text:
                label, amount = extract_amount(text)
                row["label"] = label
                row["amount"] = amount
            new_rows.append(row)

    if new_rows:
        combined = existing + new_rows
        out_path.write_text(json.dumps(combined, ensure_ascii=False, indent=2) + "\n")
        print(f"Added {len(new_rows)} new statement record(s) to {out_path}")
    else:
        print("No new statement emails found.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
