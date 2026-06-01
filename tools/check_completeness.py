"""Deterministic completeness check for one client (Layer 1, no network).

Single responsibility: apply the strict completeness rule (see hygiene_rules.completeness:
complete = name AND email AND phone AND address) to one canonical client record and print
the result. No judgment, no I/O beyond stdin/stdout — fully deterministic and testable.

Usage:
  python tools/check_completeness.py --client-file client.json
  echo '{...client...}' | python tools/check_completeness.py
"""
from __future__ import annotations

import argparse
import json
import sys

from hygiene_rules import completeness


def main() -> None:
    ap = argparse.ArgumentParser(description="Check one client record for completeness.")
    ap.add_argument("--client-file", help="JSON of one canonical client; omit to read stdin.")
    args = ap.parse_args()

    raw = open(args.client_file, encoding="utf-8").read() if args.client_file else sys.stdin.read()
    if not raw.strip():
        sys.exit("ERROR: no client payload provided (use --client-file or pipe JSON to stdin).")
    client = json.loads(raw)
    print(json.dumps(completeness(client), indent=2))


if __name__ == "__main__":
    main()
