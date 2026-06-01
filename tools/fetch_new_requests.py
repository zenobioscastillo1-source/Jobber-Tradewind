"""Polling reader: fetch new Jobber Requests + their linked Client (Layer 1 trigger, read-only).

Single responsibility: read Jobber. No classification, no hygiene judgment — that is the
agent's job downstream. Resumes from the last-seen cursor (Relay `after`), pages with
`first`, caps the run at MAX_FETCH, excludes already-surfaced request_ids, and pulls each
Request's linked Client in the same BOUNDED query (one level deep — keeps query cost low).

Reads MAX_FETCH from .env. The cursor is passed in via --after (the workflow reads it from
sheet_state first); this tool only SUGGESTS the new cursor in its output. The agent advances
the stored cursor (sheet_state set) ONLY after rows are logged, so a crash safely re-runs.

Writes .tmp/new_requests.json:
  {"new_cursor": "<endCursor or ''>", "fetched": N,
   "requests": [{request_id, created_at, title, source, client:{...canonical...}}, ...]}

Usage:
  python tools/fetch_new_requests.py --after "<cursor>" --exclude-ids .tmp/processed_ids.json
  python tools/fetch_new_requests.py --max 25            # first run, no cursor
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from dotenv import load_dotenv

from jobber_auth import cost_summary, graphql
from jobber_queries import REQUESTS_QUERY, normalize_client

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = ROOT / ".tmp" / "new_requests.json"


def fetch(after: str | None, exclude: set[str], max_fetch: int) -> tuple[list[dict], str, dict | None]:
    collected: list[dict] = []
    cursor = after or None
    last_cursor = after or ""
    last_body: dict | None = None

    while len(collected) < max_fetch:
        page_size = min(100, max_fetch - len(collected))
        last_body = graphql(REQUESTS_QUERY, {"first": page_size, "after": cursor})
        conn = (last_body.get("data") or {}).get("requests") or {}
        nodes = conn.get("nodes") or []

        for node in nodes:
            rid = node.get("id")
            if not rid or rid in exclude:
                continue
            collected.append({
                "request_id": rid,
                "created_at": node.get("createdAt", ""),
                "title": node.get("title", ""),
                "source": node.get("source", ""),
                "client": normalize_client(node.get("client")),
            })
            if len(collected) >= max_fetch:
                break

        page = conn.get("pageInfo") or {}
        last_cursor = page.get("endCursor") or last_cursor
        cursor = page.get("endCursor")
        if not page.get("hasNextPage") or not cursor:
            break

    return collected, last_cursor, last_body


def main() -> None:
    ap = argparse.ArgumentParser(description="Fetch new Jobber Requests + linked Clients.")
    ap.add_argument("--after", help="Resume cursor (last_seen_cursor from sheet_state). Omit for first run.")
    ap.add_argument("--exclude-ids", help="processed_ids.json (skip these request_ids).")
    ap.add_argument("--max", type=int, default=None, help="Override MAX_FETCH cap for this run.")
    ap.add_argument("--out", default=str(DEFAULT_OUT), help="Where to write the JSON.")
    args = ap.parse_args()

    load_dotenv()
    max_fetch = args.max if args.max is not None else int(os.environ.get("MAX_FETCH", "50"))

    exclude: set[str] = set()
    if args.exclude_ids and Path(args.exclude_ids).exists():
        data = json.loads(Path(args.exclude_ids).read_text(encoding="utf-8"))
        exclude = set(data.get("request_ids", []) if isinstance(data, dict) else data)

    requests_out, new_cursor, last_body = fetch(args.after, exclude, max_fetch)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(
        {"new_cursor": new_cursor, "fetched": len(requests_out), "requests": requests_out},
        indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"{len(requests_out)} new request(s) ({len(exclude)} excluded) -> {out_path}; "
          f"new_cursor={new_cursor or '(unchanged)'}")
    if last_body is not None:
        print(cost_summary(last_body))


if __name__ == "__main__":
    main()
