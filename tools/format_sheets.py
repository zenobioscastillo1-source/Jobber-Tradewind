"""Apply the shared visual style to every tracking-Sheet tab (Layer 1).

Single responsibility: make the owner's Sheet readable and pleasant — it changes only
*formatting* (colors, fonts, banding, frozen panes, conditional-format status chips, column
widths), never a single cell *value*. That makes it a reversible Sheet write, which CLAUDE.md
authorizes autonomously (only Jobber writes / outbound sends are gated).

The palette is lifted from the owner's reference sheet "Jobber-Zephyr" so every tab matches that
look: a dark-navy header band, white / pale-mint row banding, and Tailwind-style status chips
(emerald = good, amber = attention, red = urgent, sky/teal/indigo/slate = informational).

Per tab it:
  - freezes row 1 (header) and column A (the dedup key),
  - paints the header band (navy bg, light bold centered text) and a comfortable header height,
  - adds white / pale-mint alternating row banding across the schema columns,
  - colors each status / flag / tier column with conditional-format chips (see CHIPS below),
  - sets readable per-column widths (narrow ids, wide free-text), and uses Arial throughout.

Idempotent: existing banding and conditional-format rules on a tab are removed first, so a
re-run refreshes the look instead of stacking duplicates. Tabs that don't exist yet are skipped.

Reads SPREADSHEET_ID and the tab-name env vars from .env (same as the other Sheet tools).

Usage:
  python tools/format_sheets.py                 # style every known tab that exists
  python tools/format_sheets.py --target scoring requests
"""
from __future__ import annotations

import argparse
import os

from dotenv import load_dotenv

from google_auth import sheets_service
from sheet_schema import STATE_TAB_DEFAULT, STATE_TAB_ENV, TARGETS
from sheets_io import get_spreadsheet_id

# --- Palette (exact values from the "Jobber-Zephyr" reference sheet) -----------------------
INK = "#0E1626"      # header band background (dark navy)
PAPER = "#EAF1F8"    # header text (near-white)
BODY_INK = "#1F2937" # body text (dark slate, softer than pure black)
BAND_A = "#FFFFFF"   # banding band 1 (white)
BAND_B = "#EFFDF8"   # banding band 2 (pale mint)

# Status-chip pairs: (background, foreground). Tailwind 100/800 tints, straight from the reference.
RED = ("#FEE2E2", "#991B1B")      # urgent / blocking
AMBER = ("#FEF3C7", "#92400E")    # needs attention
EMERALD = ("#D1FAE5", "#065F46")  # good / done / approved
SKY = ("#E0F2FE", "#075985")      # informational / fresh
TEAL = ("#CCFBF1", "#115E59")     # in-progress / edited
INDIGO = ("#E0E7FF", "#3730A3")   # secondary category
SLATE = ("#EEF2F6", "#475569")    # neutral / deferred / none

# Per-tab conditional-format chips: {column_name: {cell_value: (bg, fg)}}.
# A special "*" value means "color the cell whenever it is non-empty" (used for flags).
CHIPS: dict[str, dict[str, dict[str, tuple[str, str]]]] = {
    "requests": {
        "duplicate_flag": {"strong": RED, "possible": AMBER, "none": SLATE},
        "incomplete_flag": {"yes": AMBER, "no": EMERALD},
        "status": {"surfaced": SKY, "needs_review": AMBER, "reviewed": EMERALD},
    },
    "hygiene": {
        "issue": {"both": RED, "duplicate": INDIGO, "incomplete": AMBER},
        "duplicate_flag": {"strong": RED, "possible": AMBER, "none": SLATE},
        "status": {"needs_review": AMBER, "merged": EMERALD, "completed": EMERALD},
    },
    "scoring": {
        "priority_tier": {"hot": RED, "warm": AMBER, "cool": SKY, "defer": SLATE},
        "status": {"scored": SKY, "chasing": TEAL, "deferred": SLATE, "reviewed": EMERALD},
    },
    "drafts": {
        "status": {"drafted": SKY, "needs_owner_input": AMBER, "approved": EMERALD,
                   "edit": TEAL, "rejected": RED},
        "ungrounded_flags": {"*": RED},   # any escalated gap is worth flagging red
    },
    "proposals": {
        "status": {"proposed": SKY, "approved": EMERALD, "edit": TEAL, "rejected": RED},
        "confidence": {"strong": EMERALD},
    },
}


def _rgb(hex_str: str) -> dict:
    h = hex_str.lstrip("#")
    return {"red": int(h[0:2], 16) / 255, "green": int(h[2:4], 16) / 255, "blue": int(h[4:6], 16) / 255}


def _col_width(name: str) -> int:
    """A readable width (px) per column, by what the column holds."""
    if name.endswith("_id") or name in ("score",):
        return 120
    if name in ("created_at", "surfaced_at", "drafted_at", "proposed_at"):
        return 150
    if name in ("duplicate_flag", "incomplete_flag", "issue", "priority_tier",
                "status", "confidence", "deferral_drafted"):
        return 120
    if name in ("client_name", "request_source", "missing_fields"):
        return 150
    if name in ("client_emails", "client_phones", "client_address", "duplicate_of",
                "related_client_ids", "top_signals", "next_step", "email_subject", "sms_body"):
        return 190
    # free-text: titles, reasons, bodies, notes, change summaries
    return 300


def _sheet_meta(svc, sid: str) -> dict[str, dict]:
    """Map tab title -> {sheetId, rowCount, bandedRangeIds[], condFormatCount}."""
    got = svc.spreadsheets().get(
        spreadsheetId=sid,
        fields=("sheets.properties(sheetId,title,gridProperties.rowCount),"
                "sheets.bandedRanges.bandedRangeId,sheets.conditionalFormats"),
    ).execute()
    out: dict[str, dict] = {}
    for sh in got.get("sheets", []):
        p = sh["properties"]
        out[p["title"]] = {
            "sheetId": p["sheetId"],
            "rowCount": p.get("gridProperties", {}).get("rowCount", 1000),
            "bandedRangeIds": [b["bandedRangeId"] for b in sh.get("bandedRanges", [])],
            "condFormatCount": len(sh.get("conditionalFormats", [])),
        }
    return out


def build_requests(gid: int, columns: list[str], row_count: int,
                   chips: dict, band_ids: list[int], cf_count: int) -> list[dict]:
    """All batchUpdate requests to fully (re)style one tab."""
    ncols = len(columns)
    reqs: list[dict] = []

    # 1) Freeze header row + key column.
    reqs.append({"updateSheetProperties": {
        "properties": {"sheetId": gid,
                       "gridProperties": {"frozenRowCount": 1, "frozenColumnCount": 1}},
        "fields": "gridProperties.frozenRowCount,gridProperties.frozenColumnCount"}})

    # 2) Body default format: Arial, dark-slate text, top-aligned, wrapped.
    reqs.append({"repeatCell": {
        "range": {"sheetId": gid, "startRowIndex": 1, "startColumnIndex": 0, "endColumnIndex": ncols},
        "cell": {"userEnteredFormat": {
            "verticalAlignment": "TOP", "wrapStrategy": "WRAP",
            "textFormat": {"fontFamily": "Arial", "fontSize": 10,
                           "foregroundColor": _rgb(BODY_INK)}}},
        "fields": "userEnteredFormat(verticalAlignment,wrapStrategy,textFormat)"}})

    # 3) Header band: navy bg, light bold centered text.
    reqs.append({"repeatCell": {
        "range": {"sheetId": gid, "startRowIndex": 0, "endRowIndex": 1,
                  "startColumnIndex": 0, "endColumnIndex": ncols},
        "cell": {"userEnteredFormat": {
            "backgroundColor": _rgb(INK),
            "horizontalAlignment": "CENTER", "verticalAlignment": "MIDDLE",
            "wrapStrategy": "WRAP",
            "textFormat": {"fontFamily": "Arial", "fontSize": 11, "bold": True,
                           "foregroundColor": _rgb(PAPER)}}},
        "fields": "userEnteredFormat(backgroundColor,horizontalAlignment,verticalAlignment,wrapStrategy,textFormat)"}})

    # 4) A taller header row for breathing room.
    reqs.append({"updateDimensionProperties": {
        "range": {"sheetId": gid, "dimension": "ROWS", "startIndex": 0, "endIndex": 1},
        "properties": {"pixelSize": 34}, "fields": "pixelSize"}})

    # 5) Drop any prior banding, then add white / pale-mint banding over the schema columns.
    for bid in band_ids:
        reqs.append({"deleteBanding": {"bandedRangeId": bid}})
    reqs.append({"addBanding": {"bandedRange": {
        "range": {"sheetId": gid, "startRowIndex": 0, "endRowIndex": row_count,
                  "startColumnIndex": 0, "endColumnIndex": ncols},
        "rowProperties": {"headerColor": _rgb(INK),
                          "firstBandColor": _rgb(BAND_A), "secondBandColor": _rgb(BAND_B)}}}})

    # 6) Clear prior conditional formats, then add this tab's status/flag chips.
    for _ in range(cf_count):
        reqs.append({"deleteConditionalFormatRule": {"sheetId": gid, "index": 0}})
    for col_name, value_map in chips.items():
        if col_name not in columns:
            continue
        cidx = columns.index(col_name)
        rng = {"sheetId": gid, "startRowIndex": 1, "endRowIndex": row_count,
               "startColumnIndex": cidx, "endColumnIndex": cidx + 1}
        for value, (bg, fg) in value_map.items():
            condition = ({"type": "NOT_BLANK"} if value == "*"
                         else {"type": "TEXT_EQ", "values": [{"userEnteredValue": value}]})
            reqs.append({"addConditionalFormatRule": {"index": 0, "rule": {
                "ranges": [rng],
                "booleanRule": {"condition": condition, "format": {
                    "backgroundColor": _rgb(bg),
                    "textFormat": {"bold": True, "foregroundColor": _rgb(fg)}}}}}})

    # 7) Per-column widths.
    for cidx, name in enumerate(columns):
        reqs.append({"updateDimensionProperties": {
            "range": {"sheetId": gid, "dimension": "COLUMNS",
                      "startIndex": cidx, "endIndex": cidx + 1},
            "properties": {"pixelSize": _col_width(name)}, "fields": "pixelSize"}})

    return reqs


def build_state(gid: int) -> list[dict]:
    """Light styling for the durable `_state` control tab (key | value)."""
    reqs: list[dict] = [{
        "updateSheetProperties": {
            "properties": {"sheetId": gid, "gridProperties": {"frozenColumnCount": 1}},
            "fields": "gridProperties.frozenColumnCount"}},
        {"repeatCell": {
            "range": {"sheetId": gid, "startColumnIndex": 0, "endColumnIndex": 1},
            "cell": {"userEnteredFormat": {
                "backgroundColor": _rgb(INK),
                "textFormat": {"fontFamily": "Arial", "fontSize": 10, "bold": True,
                               "foregroundColor": _rgb(PAPER)}}},
            "fields": "userEnteredFormat(backgroundColor,textFormat)"}},
        {"updateDimensionProperties": {
            "range": {"sheetId": gid, "dimension": "COLUMNS", "startIndex": 0, "endIndex": 1},
            "properties": {"pixelSize": 170}, "fields": "pixelSize"}},
        {"updateDimensionProperties": {
            "range": {"sheetId": gid, "dimension": "COLUMNS", "startIndex": 1, "endIndex": 2},
            "properties": {"pixelSize": 320}, "fields": "pixelSize"}}]
    return reqs


def format_all(svc=None, sid=None, targets: list[str] | None = None) -> dict[str, str]:
    """Style each requested tab that exists. Returns {tab: 'styled' | 'absent'}."""
    load_dotenv()
    svc = svc or sheets_service()
    sid = sid or get_spreadsheet_id()
    targets = targets or list(TARGETS)

    meta = _sheet_meta(svc, sid)
    results: dict[str, str] = {}
    requests: list[dict] = []

    for target in targets:
        cfg = TARGETS[target]
        tab = os.environ.get(cfg["tab_env"], cfg["tab_default"]).strip()
        if tab not in meta:
            results[tab] = "absent"
            continue
        m = meta[tab]
        requests += build_requests(m["sheetId"], cfg["columns"], m["rowCount"],
                                   CHIPS.get(target, {}), m["bandedRangeIds"], m["condFormatCount"])
        results[tab] = "styled"

    # The durable _state tab, if present, gets a light touch too.
    state_tab = os.environ.get(STATE_TAB_ENV, STATE_TAB_DEFAULT).strip()
    if state_tab in meta:
        requests += build_state(meta[state_tab]["sheetId"])
        results[state_tab] = "styled"

    if requests:
        svc.spreadsheets().batchUpdate(spreadsheetId=sid, body={"requests": requests}).execute()
    return results


def main() -> None:
    ap = argparse.ArgumentParser(description="Apply the shared visual style to the tracking Sheet tabs.")
    ap.add_argument("--target", nargs="*", choices=sorted(TARGETS), default=None,
                    help="Subset of tabs to style (default: all).")
    args = ap.parse_args()

    results = format_all(targets=args.target)
    for tab, state in results.items():
        mark = "OK " if state == "styled" else "-- "
        print(f"  {mark}{tab:<20} {state}")
    print("Done. Formatting only - no cell values changed.")


if __name__ == "__main__":
    main()
