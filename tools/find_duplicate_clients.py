"""Duplicate-client SIGNALS for one client (Layer 1, read-only).

Single responsibility: gather the deterministic evidence the agent needs to decide whether
a client is a likely duplicate. It does a TARGETED per-lead search of Jobber's `clients`
connection by the subject client's normalized emails/phones (strong-tier candidates) and by
a name term (possible-tier candidates), then applies hygiene_rules. It emits the matches
plus a suggested tier; the AGENT makes the final strong/possible/none call + reason.

Cost/safety: only targeted searches, each bounded by --max-candidates. A full account-wide
scan would be a BULK read needing owner sign-off (CLAUDE.md) — this tool never does that.

Usage:
  python tools/find_duplicate_clients.py --client-file client.json
  echo '{...client...}' | python tools/find_duplicate_clients.py --max-candidates 10
"""
from __future__ import annotations

import argparse
import json
import sys

from hygiene_rules import (ADDR_THRESHOLD, NAME_THRESHOLD, address_similarity,
                           emails_overlap, name_similarity, phones_overlap)
from jobber_auth import graphql
from jobber_queries import CLIENTS_SEARCH_QUERY, normalize_client


def _search(term: str, first: int) -> list[dict]:
    if not term.strip():
        return []
    body = graphql(CLIENTS_SEARCH_QUERY, {"term": term, "first": first})
    nodes = (((body.get("data") or {}).get("clients") or {}).get("nodes")) or []
    return [normalize_client(n) for n in nodes]


def _unique_terms(client: dict) -> list[str]:
    terms = list(client.get("emails") or []) + list(client.get("phones") or [])
    name_term = client.get("company_name") or client.get("last_name") or client.get("name") or ""
    if name_term:
        terms.append(name_term)
    seen, out = set(), []
    for t in terms:
        t = (t or "").strip()
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return out


def find_duplicates(client: dict, max_candidates: int) -> dict:
    cid = client.get("id", "")
    search_terms = _unique_terms(client)

    candidates: dict[str, dict] = {}
    for term in search_terms:
        for cand in _search(term, max_candidates):
            if cand.get("id") and cand["id"] != cid:
                candidates[cand["id"]] = cand

    exact, fuzzy = [], []
    for cand in candidates.values():
        matched_on = []
        if emails_overlap(client.get("emails", []), cand.get("emails", [])):
            matched_on.append("email")
        if phones_overlap(client.get("phones", []), cand.get("phones", [])):
            matched_on.append("phone")
        if matched_on:
            # "record" carries the full canonical sibling so downstream (Layer 2 propose_cleanup)
            # can build merge field-changes from REAL values. Additive — Layer 1 readers ignore it.
            exact.append({"client_id": cand["id"], "name": cand.get("name", ""),
                          "matched_on": matched_on, "record": cand})
            continue
        ns = name_similarity(client.get("name", ""), cand.get("name", ""))
        as_ = address_similarity(client.get("address_str", ""), cand.get("address_str", ""))
        if ns >= NAME_THRESHOLD and as_ >= ADDR_THRESHOLD:
            fuzzy.append({"client_id": cand["id"], "name": cand.get("name", ""),
                          "name_score": round(ns, 2), "address_score": round(as_, 2),
                          "record": cand})

    signal = "strong" if exact else ("possible" if fuzzy else "none")
    return {
        "client_id": cid,
        "signal": signal,
        "exact_matches": exact,
        "fuzzy_candidates": fuzzy,
        "searched_terms": search_terms,
        "candidates_examined": len(candidates),
        "note": "targeted per-lead search only; account-wide scan needs owner sign-off",
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Gather duplicate-client signals for one client.")
    ap.add_argument("--client-file", help="JSON of the subject canonical client; omit to read stdin.")
    ap.add_argument("--max-candidates", type=int, default=10,
                    help="Cap candidates fetched per search term (cost guard). Default 10.")
    args = ap.parse_args()

    raw = open(args.client_file, encoding="utf-8").read() if args.client_file else sys.stdin.read()
    if not raw.strip():
        sys.exit("ERROR: no client payload provided (use --client-file or pipe JSON to stdin).")
    client = json.loads(raw)
    print(json.dumps(find_duplicates(client, args.max_candidates), indent=2))


if __name__ == "__main__":
    main()
