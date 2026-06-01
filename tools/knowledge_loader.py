"""Load + VALIDATE the knowledge base; emit a grounding manifest (Layer 2, no network).

Single responsibility: read every knowledge/*.md, parse its frontmatter, and report which files
are usable for grounding a customer-facing draft vs. which are still GAPPED. It invents nothing —
it only reports what the owner has confirmed.

A file is grounding-USABLE only when ALL of:
  - status: confirmed  (real, owner-confirmed)  OR  status: sample  (demo content, NOT real)
  - confirmed_by is non-empty   (provenance: who)
  - confirmed_on is non-empty   (provenance: when)
  - no "[GAP - OWNER CONFIRM]" markers remain in the body
Anything else is a GAP: the file cannot back a draft claim, and tools/check_draft_grounding.py
will refuse any draft that cites it. (A file flipped to status: confirmed but still missing
provenance or holding gap markers is a misconfiguration -> reported as a gap, never trusted.)

`status: sample` is usable so the grounded drafting path can be demonstrated WITHOUT inventing
facts presented as real — every sample file is tagged `is_sample: true`, the gate reports a draft
as `sample_grounded`, and a later send layer must refuse sample-grounded output. It is a demo mode,
never a substitute for owner-confirmed facts.

Frontmatter is a simple `key: value` block between leading `---` fences (no YAML dep needed).

Writes .tmp/knowledge_context.json:
  {"files": [{name, topic, status, confirmed_by, confirmed_on, has_gaps, is_sample, usable,
              reasons, content}],
   "confirmed_topics": [...], "sample_topics": [...], "gaps": [{name, reasons}]}

Usage:
  python tools/knowledge_loader.py
  python tools/knowledge_loader.py --out .tmp/knowledge_context.json
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KNOWLEDGE_DIR = ROOT / "knowledge"
DEFAULT_OUT = ROOT / ".tmp" / "knowledge_context.json"

GAP_MARKER = re.compile(r"\[GAP", re.IGNORECASE)  # matches "[GAP - OWNER CONFIRM]" (any dash)
FRONTMATTER = re.compile(r"^\s*---\s*\n(.*?)\n---\s*\n?(.*)$", re.DOTALL)


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Split a markdown file into (frontmatter dict, body). No fence -> ({}, whole text)."""
    m = FRONTMATTER.match(text)
    if not m:
        return {}, text
    meta: dict[str, str] = {}
    for line in m.group(1).splitlines():
        line = line.split("#", 1)[0]  # strip trailing inline comments
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip()
    return meta, m.group(2)


def assess_file(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    meta, body = parse_frontmatter(text)
    status = (meta.get("status") or "").strip().lower()
    confirmed_by = (meta.get("confirmed_by") or "").strip()
    confirmed_on = (meta.get("confirmed_on") or "").strip()
    has_gaps = bool(GAP_MARKER.search(body))

    reasons: list[str] = []
    if status not in ("confirmed", "sample"):
        reasons.append(f"status is '{status or 'unset'}' (need 'confirmed' or 'sample')")
    if not confirmed_by:
        reasons.append("missing confirmed_by (provenance: who)")
    if not confirmed_on:
        reasons.append("missing confirmed_on (provenance: when)")
    if has_gaps:
        reasons.append("body still contains [GAP - OWNER CONFIRM] markers")

    return {
        "name": path.name,
        "topic": (meta.get("topic") or path.stem).strip(),
        "status": status,
        "confirmed_by": confirmed_by,
        "confirmed_on": confirmed_on,
        "has_gaps": has_gaps,
        "is_sample": status == "sample",
        "usable": not reasons,
        "reasons": reasons,
        "content": body.strip(),
    }


def load_knowledge(knowledge_dir: Path = KNOWLEDGE_DIR) -> dict:
    files = [assess_file(p) for p in sorted(knowledge_dir.glob("*.md"))
             if p.name.lower() != "readme.md"]
    return {
        "files": files,
        "confirmed_topics": [f["topic"] for f in files if f["usable"]],
        "sample_topics": [f["topic"] for f in files if f["usable"] and f["is_sample"]],
        "gaps": [{"name": f["name"], "reasons": f["reasons"]} for f in files if not f["usable"]],
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Load + validate the knowledge base into a manifest.")
    ap.add_argument("--out", default=str(DEFAULT_OUT), help="Where to write the manifest JSON.")
    ap.add_argument("--knowledge-dir", default=str(KNOWLEDGE_DIR), help="knowledge/ directory.")
    args = ap.parse_args()

    manifest = load_knowledge(Path(args.knowledge_dir))
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    usable = len(manifest["confirmed_topics"])
    total = len(manifest["files"])
    n_sample = len(manifest["sample_topics"])
    sample_note = f" ({n_sample} are SAMPLE/demo, not real)" if n_sample else ""
    print(f"{usable}/{total} knowledge file(s) usable for grounding{sample_note} -> {out_path}")
    if manifest["confirmed_topics"]:
        print("  usable: " + ", ".join(manifest["confirmed_topics"]))
    for g in manifest["gaps"]:
        print(f"  GAP {g['name']}: {'; '.join(g['reasons'])}")


if __name__ == "__main__":
    main()
