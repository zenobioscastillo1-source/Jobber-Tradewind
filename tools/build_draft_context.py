"""Assemble the per-Request drafting BRIEF the agent writes from (Layer 2, no network).

Single responsibility: gather, don't compose. It joins one Request + its linked Client (from
fetch_new_requests.py output) with the knowledge manifest, and emits a brief that makes the
grounding boundary explicit:
  - the request/client facts to address,
  - the CONFIRMED knowledge the draft may rely on (full content), and
  - the GAPPED topics the draft may NOT claim (it must escalate them instead).

The AGENT then writes email_subject/email_body/sms_body in the owner's voice, aimed at next_step,
citing the knowledge files used in draft_grounding and listing anything uncovered in
ungrounded_flags. tools/check_draft_grounding.py enforces that boundary before logging.

Writes .tmp/draft_context_<request_id>.json.

Usage:
  python tools/build_draft_context.py --request-id <rid>
  python tools/build_draft_context.py --request-id <rid> --requests-file .tmp/new_requests.json
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from knowledge_loader import load_knowledge

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REQUESTS = ROOT / ".tmp" / "new_requests.json"


def _safe(rid: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", rid)


def build_context(request: dict, manifest: dict) -> dict:
    client = request.get("client") or {}
    confirmed = [{"topic": f["topic"], "name": f["name"], "is_sample": f.get("is_sample", False),
                  "content": f["content"]}
                 for f in manifest["files"] if f["usable"]]
    gapped_topics = [f["topic"] for f in manifest["files"] if not f["usable"]]
    return {
        "request": {
            "request_id": request.get("request_id", ""),
            "created_at": request.get("created_at", ""),
            "title": request.get("title", ""),
            "source": request.get("source", ""),
        },
        "client": {
            "client_id": client.get("id", ""),
            "client_name": client.get("name", ""),
            "emails": client.get("emails", []),
            "phones": client.get("phones", []),
            "address": client.get("address_str", ""),
        },
        "knowledge": {
            "confirmed": confirmed,
            "gapped_topics": gapped_topics,
            "gaps": manifest["gaps"],
        },
        "drafting_rules": [
            "State ONLY facts backed by a confirmed knowledge file; cite each in draft_grounding.",
            "Anything the lead asks that maps to a gapped topic (or no file at all) -> add to "
            "ungrounded_flags and DO NOT answer it.",
            "Never invent pricing, services, policies, or service-area facts.",
            "Write BOTH an email variant (subject+body) and a short SMS variant.",
            "Aim at one concrete next_step: confirm details / book an assessment / send a quote.",
        ],
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Build a per-Request drafting brief.")
    ap.add_argument("--request-id", required=True, help="The Request id to build a brief for.")
    ap.add_argument("--requests-file", default=str(DEFAULT_REQUESTS),
                    help="fetch_new_requests.py output (default .tmp/new_requests.json).")
    ap.add_argument("--out", help="Where to write the brief (default .tmp/draft_context_<rid>.json).")
    args = ap.parse_args()

    data = json.loads(Path(args.requests_file).read_text(encoding="utf-8"))
    request = next((r for r in data.get("requests", [])
                    if r.get("request_id") == args.request_id), None)
    if request is None:
        raise SystemExit(f"ERROR: request_id {args.request_id} not found in {args.requests_file}")

    manifest = load_knowledge()
    context = build_context(request, manifest)

    out_path = Path(args.out) if args.out else ROOT / ".tmp" / f"draft_context_{_safe(args.request_id)}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(context, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"brief for {args.request_id} -> {out_path}; "
          f"{len(context['knowledge']['confirmed'])} confirmed topic(s), "
          f"{len(context['knowledge']['gapped_topics'])} gapped: "
          f"{', '.join(context['knowledge']['gapped_topics']) or '(none)'}")


if __name__ == "__main__":
    main()
