"""Score one Jobber Request for priority (read-only "Score & Prioritize" layer, no network).

Single responsibility: apply tools/scoring_rules.score_lead to one Request + its linked Client and
print the result. No judgment, no I/O beyond reading the request and printing JSON — fully
deterministic and testable. The AGENT then confirms/overrides the tier and writes the one-line
priority_reason before logging to the Prioritized Leads tab.

Pick the request one of three ways:
  --request-file  : a JSON object {request_id, title, source, created_at, client:{...}} (or {"request": {...}})
  --request-id    : look it up by id inside a fetch_new_requests.py batch (--requests-file)
  (stdin)         : pipe the request JSON in

Optional:
  --matches-file  : find_duplicate_clients.py output for this client; a 'strong' signal marks an
                    existing customer (informational — same optional-matches pattern as propose_cleanup.py).

Usage:
  python tools/score_lead.py --request-file req.json
  python tools/score_lead.py --request-id <rid> --requests-file .tmp/new_requests.json
  echo '{...request...}' | python tools/score_lead.py
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from scoring_rules import score_lead

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REQUESTS = ROOT / ".tmp" / "new_requests.json"


def _load_request(args: argparse.Namespace) -> dict:
    if args.request_id:
        data = json.loads(Path(args.requests_file).read_text(encoding="utf-8"))
        req = next((r for r in data.get("requests", []) if r.get("request_id") == args.request_id), None)
        if req is None:
            sys.exit(f"ERROR: request_id {args.request_id} not found in {args.requests_file}")
        return req
    raw = open(args.request_file, encoding="utf-8").read() if args.request_file else sys.stdin.read()
    if not raw.strip():
        sys.exit("ERROR: no request provided (use --request-file / --request-id, or pipe JSON to stdin).")
    obj = json.loads(raw)
    return obj.get("request", obj)   # accept either a bare request or {"request": {...}}


def main() -> None:
    ap = argparse.ArgumentParser(description="Score one Request for lead priority.")
    ap.add_argument("--request-file", help="JSON of one Request (+ linked client); omit to read stdin.")
    ap.add_argument("--request-id", help="Score a request by id from a fetch_new_requests.py batch.")
    ap.add_argument("--requests-file", default=str(DEFAULT_REQUESTS),
                    help="Batch file for --request-id (default .tmp/new_requests.json).")
    ap.add_argument("--matches-file", help="find_duplicate_clients.py output (optional; marks existing customer).")
    args = ap.parse_args()

    request = _load_request(args)
    dup_signal = None
    if args.matches_file and Path(args.matches_file).exists():
        dup_signal = json.loads(Path(args.matches_file).read_text(encoding="utf-8")).get("signal")

    print(json.dumps(score_lead(request, request.get("client"), dup_signal), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
