"""Read/write the durable control-state in the Sheet's _state tab (Layer 1).

Single responsibility: the last-seen Request cursor + run metadata. This is durable state —
losing it means re-scanning or missing Requests — so it lives in the Sheet, never in .tmp/
(CLAUDE.md). The _state tab is simple key|value rows (column A = key, column B = value).

`set` is the cursor-advance step in the workflow; the agent calls it ONLY after the run's
rows have been written, so a mid-run crash safely re-processes (dedup prevents duplicates).

Reads SPREADSHEET_ID and STATE_TAB from .env.

Usage:
  python tools/sheet_state.py get                          # prints last_seen_cursor (empty if unset)
  python tools/sheet_state.py get --key last_run_at
  python tools/sheet_state.py set --cursor <CURSOR> --count 7
"""
from __future__ import annotations

import argparse
import datetime
import os

from dotenv import load_dotenv

from google_auth import sheets_service
from sheet_schema import STATE_KEYS, STATE_TAB_DEFAULT, STATE_TAB_ENV
from sheets_io import ensure_tab, get_spreadsheet_id, quote_tab, tab_exists


def _tab() -> str:
    load_dotenv()
    return os.environ.get(STATE_TAB_ENV, STATE_TAB_DEFAULT).strip()


def _read(svc, sid: str, tab: str) -> dict:
    rows = svc.spreadsheets().values().get(
        spreadsheetId=sid, range=f"{quote_tab(tab)}!A1:B"
    ).execute().get("values", [])
    return {r[0]: (r[1] if len(r) > 1 else "") for r in rows if r and r[0].strip()}


def _write(svc, sid: str, tab: str, state: dict) -> None:
    ensure_tab(svc, sid, tab)
    values = [[k, str(state.get(k, ""))] for k in STATE_KEYS]
    svc.spreadsheets().values().update(
        spreadsheetId=sid, range=f"{quote_tab(tab)}!A1",
        valueInputOption="RAW", body={"values": values},
    ).execute()


def main() -> None:
    ap = argparse.ArgumentParser(description="Read/write the _state control tab.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("get", help="Print a state value (default key: last_seen_cursor).")
    g.add_argument("--key", default="last_seen_cursor", choices=STATE_KEYS)
    s = sub.add_parser("set", help="Advance the cursor and record run metadata.")
    s.add_argument("--cursor", required=True, help="The new last_seen_cursor value.")
    s.add_argument("--count", type=int, default=0, help="Requests surfaced this run.")
    args = ap.parse_args()

    sid, tab, svc = get_spreadsheet_id(), _tab(), sheets_service()

    if args.cmd == "get":
        # Read-only: if the tab doesn't exist yet, the value is simply unset.
        state = _read(svc, sid, tab) if tab_exists(svc, sid, tab) else {}
        print(state.get(args.key, ""))
        return

    state = _read(svc, sid, tab) if tab_exists(svc, sid, tab) else {}
    state["last_seen_cursor"] = args.cursor
    state["last_run_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    state["last_run_count"] = args.count
    _write(svc, sid, tab, state)
    print(f"state updated: last_seen_cursor={args.cursor} last_run_count={args.count}")


if __name__ == "__main__":
    main()
