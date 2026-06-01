"""The grounding GATE for a composed follow-up draft (Layer 2, no network).

Single responsibility: enforce the fabrication guardrail in code (the auditable companion to
hygiene_rules.py). Given the agent's draft row + the knowledge manifest, it checks citation
integrity and decides the AUTHORITATIVE status the row gets logged with — so the agent can't
quietly mark an ungrounded draft as ready.

Rules:
  - draft_grounding lists the knowledge files the draft rests on. Every cited file MUST exist
    and be usable (status: confirmed + provenance + no gap markers, per knowledge_loader).
      * cites an unknown file        -> VIOLATION (fail)
      * cites a gapped/unconfirmed   -> VIOLATION (fail)  [this is the fabrication risk]
  - ungrounded_flags non-empty -> the draft is correctly escalating an uncovered ask:
    resolved_status is forced to "needs_owner_input" (this is a PASS — escalation is correct).
  - otherwise -> resolved_status "drafted" (PASS).

Note the honest scope: the gate verifies CITATIONS, not prose semantics. It guarantees a draft
never cites something unconfirmed and that flagged asks escalate; the agent remains responsible
for actually flagging uncovered asks rather than answering them (build_draft_context spells out
the gapped topics so it can).

`draft_grounding` / `ungrounded_flags` may be a "; "-joined string (Sheet row format) or a list.

Usage:
  python tools/check_draft_grounding.py --draft-file draft_row.json
  python tools/check_draft_grounding.py --draft-file draft_row.json --emit-row .tmp/draft_row.json
  echo '{...draft row...}' | python tools/check_draft_grounding.py
Exit code 1 when the draft FAILS (citation violation) so a workflow halts before logging.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from knowledge_loader import load_knowledge


def _as_list(value) -> list[str]:
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    return [p.strip() for p in str(value or "").split(";") if p.strip()]


def check_grounding(draft: dict, manifest: dict) -> dict:
    by_name = {f["name"]: f for f in manifest["files"]}
    cited = _as_list(draft.get("draft_grounding"))
    ungrounded = _as_list(draft.get("ungrounded_flags"))

    violations: list[str] = []
    sample_cited: list[str] = []
    for name in cited:
        f = by_name.get(name)
        if f is None:
            violations.append(f"cites unknown knowledge file '{name}'")
        elif not f["usable"]:
            violations.append(f"cites gapped/unconfirmed file '{name}' ({'; '.join(f['reasons'])})")
        elif f.get("is_sample"):
            sample_cited.append(name)

    if violations:
        resolved_status = "needs_owner_input"
    elif ungrounded:
        resolved_status = "needs_owner_input"
    else:
        resolved_status = "drafted"

    return {
        "request_id": draft.get("request_id", ""),
        "passed": not violations,
        "resolved_status": resolved_status,
        "cited": cited,
        "ungrounded_flags": ungrounded,
        "violations": violations,
        # Transparency: a draft grounded on SAMPLE (demo) knowledge is flagged so it is never
        # mistaken for one grounded on owner-confirmed facts (a later send layer must refuse these).
        "sample_grounded": bool(sample_cited),
        "sample_cited": sample_cited,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Validate a draft's grounding before logging.")
    ap.add_argument("--draft-file", help="JSON draft row; omit to read stdin.")
    ap.add_argument("--emit-row", help="On PASS, write the draft row here with status set to "
                                       "the gate's resolved_status (deterministic, pipeline-ready).")
    args = ap.parse_args()

    raw = open(args.draft_file, encoding="utf-8").read() if args.draft_file else sys.stdin.read()
    if not raw.strip():
        sys.exit("ERROR: no draft payload provided (use --draft-file or pipe JSON to stdin).")
    draft = json.loads(raw)

    manifest = load_knowledge()
    result = check_grounding(draft, manifest)
    print(json.dumps(result, indent=2, ensure_ascii=False))

    if result["passed"] and args.emit_row:
        row = dict(draft)
        row["status"] = result["resolved_status"]
        Path(args.emit_row).parent.mkdir(parents=True, exist_ok=True)
        Path(args.emit_row).write_text(json.dumps(row, ensure_ascii=False), encoding="utf-8")
        print(f"emitted row (status={result['resolved_status']}) -> {args.emit_row}", file=sys.stderr)

    if not result["passed"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
