"""Shared low-level Google Sheets read/write helpers for the Jobber engine (Layer 1).

Single responsibility: the Sheet plumbing the logging/state/dedup tools reuse — resolve the
spreadsheet id, check/create a tab, write its header, find a row by its key column, and read
a column. Keeps each tool small and consistent. All durable records (rows, cursor) live in
the Sheet, never in .tmp/ (CLAUDE.md).
"""
from __future__ import annotations

import os
import sys

from dotenv import load_dotenv

from google_auth import normalize_spreadsheet_id, sheets_service  # noqa: F401 (re-export convenience)


def get_spreadsheet_id() -> str:
    load_dotenv()
    sid = normalize_spreadsheet_id(os.environ.get("SPREADSHEET_ID", ""))
    if not sid:
        sys.exit("ERROR: SPREADSHEET_ID is not set in .env (see .env.example).")
    return sid


def quote_tab(tab: str) -> str:
    """Quote a tab name for an A1 range when it contains spaces or special chars."""
    if any(c in tab for c in " '!"):
        return "'" + tab.replace("'", "''") + "'"
    return tab


def _tab_titles(svc, sid: str) -> set[str]:
    meta = svc.spreadsheets().get(
        spreadsheetId=sid, fields="sheets.properties.title"
    ).execute()
    return {s["properties"]["title"] for s in meta.get("sheets", [])}


def sheet_id_for_tab(svc, sid: str, tab: str) -> int | None:
    """Return the numeric sheetId for a tab title (needed for batchUpdate grid ranges)."""
    meta = svc.spreadsheets().get(
        spreadsheetId=sid, fields="sheets.properties(sheetId,title)"
    ).execute()
    for s in meta.get("sheets", []):
        if s["properties"]["title"] == tab:
            return s["properties"]["sheetId"]
    return None


def tab_exists(svc, sid: str, tab: str) -> bool:
    return tab in _tab_titles(svc, sid)


def ensure_tab(svc, sid: str, tab: str) -> None:
    """Create the tab if it does not already exist (idempotent)."""
    if tab in _tab_titles(svc, sid):
        return
    svc.spreadsheets().batchUpdate(
        spreadsheetId=sid,
        body={"requests": [{"addSheet": {"properties": {"title": tab}}}]},
    ).execute()


def ensure_header(svc, sid: str, tab: str, columns: list[str]) -> None:
    """Write the header row if missing, or rewrite it if it doesn't match the schema prefix."""
    first = svc.spreadsheets().values().get(
        spreadsheetId=sid, range=f"{quote_tab(tab)}!1:1"
    ).execute().get("values", [])
    current = first[0] if first else []
    if current[: len(columns)] != columns:
        svc.spreadsheets().values().update(
            spreadsheetId=sid,
            range=f"{quote_tab(tab)}!A1",
            valueInputOption="RAW",
            body={"values": [columns]},
        ).execute()


def ensure_dropdown(svc, sid: str, tab: str, col_index: int, values: list[str]) -> None:
    """Apply a data-validation dropdown (ONE_OF_LIST) to one column from row 2 down (idempotent).

    Reversible Sheet write (autonomous-OK per CLAUDE.md — only Jobber writes/sends are gated).
    showCustomUi renders the chip; strict=False so system-written values pass without a warning.
    `col_index` is the 0-based column offset of the target column.
    """
    grid_id = sheet_id_for_tab(svc, sid, tab)
    if grid_id is None:
        return
    svc.spreadsheets().batchUpdate(
        spreadsheetId=sid,
        body={"requests": [{
            "setDataValidation": {
                "range": {"sheetId": grid_id, "startRowIndex": 1,
                          "startColumnIndex": col_index, "endColumnIndex": col_index + 1},
                "rule": {
                    "condition": {"type": "ONE_OF_LIST",
                                  "values": [{"userEnteredValue": v} for v in values]},
                    "showCustomUi": True,
                    "strict": False,
                },
            }
        }]},
    ).execute()


def find_row_by_key(svc, sid: str, tab: str, key_value: str,
                    status_idx: int | None) -> tuple[int | None, str]:
    """Return (1-based row number, status value) for the row whose column A == key_value.

    (None, "") if not found. `status_idx` is the 0-based column offset of the status
    field (used for the owner-edit guardrail); pass None if the tab has no status column.
    """
    rows = svc.spreadsheets().values().get(
        spreadsheetId=sid, range=f"{quote_tab(tab)}!A2:Z"
    ).execute().get("values", [])
    for i, row in enumerate(rows):
        if row and row[0] == key_value:
            status = ""
            if status_idx is not None and len(row) > status_idx:
                status = row[status_idx]
            return i + 2, status  # +2: skip header row 1, convert 0-based -> 1-based
    return None, ""


def column_a_values(svc, sid: str, tab: str) -> list[str]:
    """Return non-empty values of column A from row 2 down (keys/ids; header excluded)."""
    rows = svc.spreadsheets().values().get(
        spreadsheetId=sid, range=f"{quote_tab(tab)}!A2:A"
    ).execute().get("values", [])
    return [r[0] for r in rows if r and r[0].strip()]
