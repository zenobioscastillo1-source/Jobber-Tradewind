"""Idempotent upsert of one row to a tracking Sheet tab (Layer 1).

Single responsibility: write to the Sheet. No classification or hygiene judgment happens
here — the agent decides flags and hands this tool a complete row payload. The target tab
and its schema are chosen with --target:
  requests : one row per Request   (dedup key request_id)
  hygiene  : one row per flagged Client (dedup key client_id)

Idempotent upsert keyed by that tab's key column:
  - Key not present  -> append a new row.
  - Key present      -> skip by default (already surfaced). With --update, refresh the row
    ONLY if its `status` is still a system value (per sheet_schema.TARGETS). If the owner has
    touched the row (any other status), leave it alone — owner edits are never overwritten.

The tab and header row are created automatically if missing (bootstrap).

Reads SPREADSHEET_ID and the tab-name env vars from .env.

Usage:
  python tools/log_to_sheet.py --target requests --row-file row.json
  echo '{...}' | python tools/log_to_sheet.py --target hygiene
  python tools/log_to_sheet.py --target requests --row-file row.json --update
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from dotenv import load_dotenv

from google_auth import sheets_service
from sheet_schema import TARGETS
from sheets_io import (ensure_dropdown, ensure_header, ensure_tab, find_row_by_key,
                       get_spreadsheet_id, quote_tab)


def _read_payload(row_file: str | None) -> dict:
    raw = open(row_file, encoding="utf-8").read() if row_file else sys.stdin.read()
    if not raw.strip():
        sys.exit("ERROR: no row payload provided (use --row-file or pipe JSON to stdin).")
    return json.loads(raw)


def main() -> None:
    ap = argparse.ArgumentParser(description="Idempotent upsert of one row to a tracking tab.")
    ap.add_argument("--target", choices=sorted(TARGETS), required=True,
                    help="Which tab/schema: 'requests' or 'hygiene'.")
    ap.add_argument("--row-file", help="JSON file with the row payload; omit to read stdin.")
    ap.add_argument("--update", action="store_true",
                    help="If the row exists and is still system-owned, refresh it.")
    args = ap.parse_args()

    load_dotenv()
    cfg = TARGETS[args.target]
    columns, key = cfg["columns"], cfg["key"]
    status_idx = columns.index("status") if "status" in columns else None
    tab = os.environ.get(cfg["tab_env"], cfg["tab_default"]).strip()

    payload = _read_payload(args.row_file)
    key_val = str(payload.get(key, "")).strip()
    if not key_val:
        sys.exit(f"ERROR: row payload must include a non-empty '{key}'.")

    sid = get_spreadsheet_id()
    svc = sheets_service()
    ensure_tab(svc, sid, tab)
    ensure_header(svc, sid, tab, columns)

    # Optional: apply each owner-facing data-validation dropdown (e.g. status, priority tier).
    for dd in cfg.get("dropdowns", []):
        if dd["column"] in columns:
            ensure_dropdown(svc, sid, tab, columns.index(dd["column"]), dd["values"])

    row_num, status = find_row_by_key(svc, sid, tab, key_val, status_idx)
    values = [str(payload.get(c, "")) for c in columns]

    if row_num is None:
        svc.spreadsheets().values().append(
            spreadsheetId=sid, range=f"{quote_tab(tab)}!A1",
            valueInputOption="RAW", insertDataOption="INSERT_ROWS",
            body={"values": [values]},
        ).execute()
        print(f"APPENDED {key}={key_val} -> {tab}")
        return

    if not args.update:
        print(f"SKIPPED duplicate {key}={key_val} (already surfaced)")
        return

    if status not in cfg["system_statuses"]:
        print(f"SKIPPED {key}={key_val}: owner-edited (status='{status}'), not overwriting")
        return

    svc.spreadsheets().values().update(
        spreadsheetId=sid, range=f"{quote_tab(tab)}!A{row_num}",
        valueInputOption="RAW", body={"values": [values]},
    ).execute()
    print(f"UPDATED row {row_num} {key}={key_val} -> {tab}")


if __name__ == "__main__":
    main()
