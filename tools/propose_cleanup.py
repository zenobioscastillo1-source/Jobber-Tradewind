"""Propose a concrete, high-confidence cleanup for one flagged client (Layer 2, no network).

Single responsibility: turn Layer 1's duplicate/completeness SIGNALS into a specific "here's what
I would change" proposal — deterministically, and using ONLY values that exist in real records.
It proposes; it never executes (Jobber stays read-only; merges/edits are Layer 3).

Scope decision = HIGH-CONFIDENCE ONLY:
  - STRONG duplicate group (shared email/phone) -> a `merge_duplicates` proposal: keep the most
    complete record as primary and carry over the other record(s)' real values (this also closes
    gaps a sibling can fill). field_changes are sourced from real records, never invented.
  - POSSIBLE-tier only (fuzzy name+address, different contact) -> NO merge; a review note for the
    owner (these are not auto-proposed given no real-data noise signal yet).
  - INCOMPLETE with no source value (no strong sibling to supply it) -> NO proposal; needs_followup
    so the gap is gathered via the follow-up draft. We never fabricate a missing value.

Inputs:
  --client-file   subject canonical client (full record; the flagged lead's Client).
  --matches-file  find_duplicate_clients.py output for that client (signal + matches, each match
                  carries its full `record`). Omit if you have no duplicate signals.

Builds directly on tools/hygiene_rules.py (the same rule module Layer 1 uses) for completeness +
normalization, so classification never drifts from Layer 1.

Writes the result to stdout (and --out): {client_id, decision, proposal|null, needs_followup,
missing_fields, review_note}. `decision` in {merge_proposal, needs_followup, review_note, none}.

Usage:
  python tools/propose_cleanup.py --client-file client.json --matches-file dup_signals.json
  python tools/propose_cleanup.py --client-file client.json    # no dup signals -> completeness only
"""
from __future__ import annotations

import argparse
import datetime
import json
from pathlib import Path

from hygiene_rules import completeness, normalize_email, normalize_phone
from jobber_queries import format_address

NOW = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def _score(client: dict) -> int:
    """How complete a record is (4 = name+email+phone+address all present). Higher = better primary."""
    return 4 - len(completeness(client)["missing_fields"])


def _has_full_address(client: dict) -> bool:
    addr = client.get("address") or {}
    return bool((addr.get("street1") or "").strip() and (addr.get("city") or "").strip())


def _pick_primary(group: list[dict]) -> dict:
    """Most complete record wins; deterministic tie-break by id (stable across re-runs)."""
    return sorted(group, key=lambda c: (-_score(c), c.get("id", "")))[0]


def _field_changes(primary: dict, others: list[dict]) -> list[str]:
    """Real values from `others` that would enrich `primary`. Nothing invented."""
    changes: list[str] = []
    p_emails = {normalize_email(e) for e in (primary.get("emails") or []) if normalize_email(e)}
    p_phones = {normalize_phone(p) for p in (primary.get("phones") or []) if normalize_phone(p)}

    for sib in others:
        sid = sib.get("id", "")
        for e in sib.get("emails") or []:
            ne = normalize_email(e)
            if ne and ne not in p_emails:
                changes.append(f"add email {e.strip()} (from {sid})")
                p_emails.add(ne)
        for p in sib.get("phones") or []:
            npn = normalize_phone(p)
            if npn and npn not in p_phones:
                changes.append(f"add phone {p.strip()} (from {sid})")
                p_phones.add(npn)
        if not _has_full_address(primary) and _has_full_address(sib):
            changes.append(f"set address {sib.get('address_str') or format_address(sib.get('address'))} (from {sid})")
        if not (primary.get("name") or "").strip() and (sib.get("name") or "").strip():
            changes.append(f"set name {sib['name'].strip()} (from {sid})")
    return changes


def propose(client: dict, matches: dict | None) -> dict:
    matches = matches or {}
    cid = client.get("id", "")
    comp = completeness(client)
    strong = [m["record"] for m in matches.get("exact_matches", []) if m.get("record")]
    possible = [m["record"] for m in matches.get("fuzzy_candidates", []) if m.get("record")]
    matched_on = sorted({mo for m in matches.get("exact_matches", []) for mo in m.get("matched_on", [])})

    result = {"client_id": cid, "decision": "none", "proposal": None,
              "needs_followup": False, "missing_fields": comp["missing_fields"], "review_note": ""}

    if strong:
        group = [client] + strong
        primary = _pick_primary(group)
        others = [c for c in group if c.get("id") != primary.get("id")]
        changes = _field_changes(primary, others)
        other_ids = [c.get("id", "") for c in others]
        proposal_id = "merge:" + "+".join(sorted(c.get("id", "") for c in group))
        source_flag = "both" if comp["incomplete"] else "duplicate"
        change_summary = ("; ".join(changes)) if changes else "no field changes (records agree)"
        proposed_change = (f"Merge {', '.join(other_ids)} into {primary.get('id')} "
                           f"({primary.get('name')}); carry over: {change_summary}. "
                           f"Then archive the merged duplicate record(s).")
        rationale = (f"Strong duplicate: shares {', '.join(matched_on) or 'contact info'} "
                     f"with {', '.join(other_ids)}.")
        if comp["incomplete"] and changes:
            rationale += f" Merge also fills missing {', '.join(comp['missing_fields'])} from the sibling."
        result["decision"] = "merge_proposal"
        result["proposal"] = {
            "proposal_id": proposal_id,
            "proposal_type": "merge_duplicates",
            "primary_client_id": primary.get("id", ""),
            "related_client_ids": "; ".join(other_ids),
            "client_name": primary.get("name", ""),
            "proposed_change": proposed_change,
            "field_changes": "; ".join(changes),
            "rationale": rationale,
            "source_flag": source_flag,
            "confidence": "strong",
            "status": "proposed",
            "owner_edit": "",
            "proposed_at": NOW,
            "owner_notes": "",
        }
        if possible:
            result["review_note"] = (f"Also has possible-tier match(es) "
                                     f"{', '.join(c.get('id','') for c in possible)} — not auto-merged.")
        return result

    if comp["incomplete"]:
        # No strong sibling to supply a value -> never fabricate; gather via the follow-up draft.
        result["decision"] = "needs_followup"
        result["needs_followup"] = True
        result["review_note"] = (f"Incomplete (missing {', '.join(comp['missing_fields'])}) with no "
                                 f"source record — resolve via follow-up draft, do not invent values.")
        if possible:
            result["review_note"] += (f" Possible-tier match(es): "
                                      f"{', '.join(c.get('id','') for c in possible)}.")
        return result

    if possible:
        result["decision"] = "review_note"
        result["review_note"] = (f"Possible duplicate(s) {', '.join(c.get('id','') for c in possible)} "
                                 f"(same name+address, different contact). Review manually; "
                                 f"not auto-proposed (high-confidence-only this layer).")
        return result

    return result


def main() -> None:
    ap = argparse.ArgumentParser(description="Propose a high-confidence cleanup for one flagged client.")
    ap.add_argument("--client-file", required=True, help="JSON of the subject canonical client.")
    ap.add_argument("--matches-file", help="find_duplicate_clients.py output for this client.")
    ap.add_argument("--out", help="Optional path to also write the result JSON.")
    args = ap.parse_args()

    client = json.loads(Path(args.client_file).read_text(encoding="utf-8"))
    matches = json.loads(Path(args.matches_file).read_text(encoding="utf-8")) if args.matches_file else None
    result = propose(client, matches)

    text = json.dumps(result, indent=2, ensure_ascii=False)
    print(text)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
