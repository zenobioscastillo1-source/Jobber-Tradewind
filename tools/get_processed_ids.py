"""Read already-surfaced/-drafted/-proposed ids from the Sheet for dedup (Layers 1-2).

Single responsibility: read. The durable processed-state (CLAUDE.md) is row existence in the
data tabs — the Sheet is the system of record, never .tmp/. Reads column A of each tab:
request_id (Requests), client_id (Client Hygiene), and — when present — request_id (Follow-up
Drafts) and proposal_id (Cleanup Proposals). Output feeds fetch_new_requests.py --exclude-ids
(so no Request is surfaced twice) and the Layer 2 loop (so nothing is drafted/proposed twice).

Reads SPREADSHEET_ID and the tab-name env vars from .env. Layer 2 tabs are optional: if a tab
doesn't exist yet, its id list is simply empty.

Writes .tmp/processed_ids.json:
  {"request_ids": [...], "client_ids": [...], "drafted_request_ids": [...], "proposed_ids": [...]}.

Usage:
  python tools/get_processed_ids.py
  python tools/get_processed_ids.py --out .tmp/processed_ids.json
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from dotenv import load_dotenv

from google_auth import sheets_service
from sheet_schema import TARGETS
from sheets_io import column_a_values, get_spreadsheet_id, tab_exists

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = ROOT / ".tmp" / "processed_ids.json"


def main() -> None:
    ap = argparse.ArgumentParser(description="Read surfaced request/client ids from the Sheet.")
    ap.add_argument("--out", default=str(DEFAULT_OUT), help="Where to write the JSON.")
    args = ap.parse_args()

    load_dotenv()
    sid, svc = get_spreadsheet_id(), sheets_service()

    def _keys(target: str) -> list[str]:
        tab = os.environ.get(TARGETS[target]["tab_env"], TARGETS[target]["tab_default"]).strip()
        return column_a_values(svc, sid, tab) if tab_exists(svc, sid, tab) else []

    request_ids = _keys("requests")
    client_ids = _keys("hygiene")
    drafted_request_ids = _keys("drafts")      # Layer 2 — empty until the Drafts tab exists
    proposed_ids = _keys("proposals")          # Layer 2 — empty until the Proposals tab exists

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(
        {"request_ids": request_ids, "client_ids": client_ids,
         "drafted_request_ids": drafted_request_ids, "proposed_ids": proposed_ids},
        indent=2), encoding="utf-8")
    print(f"{len(request_ids)} request_id(s), {len(client_ids)} client_id(s), "
          f"{len(drafted_request_ids)} drafted, {len(proposed_ids)} proposed -> {out_path}")


if __name__ == "__main__":
    main()
