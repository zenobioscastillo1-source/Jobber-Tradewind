"""Deterministic hygiene rules — the duplicate-match and completeness logic in one
auditable place (Layer 1). These are the RULES the agent's judgment sits on top of: the
tools emit signals from these functions, and the agent makes the final 'likely duplicate'
call for the fuzzy/possible tier (CLAUDE.md keeps judgment in the agent layer).

DUPLICATE MATCH (approved decision):
  strong   = normalized email match OR normalized phone match
  possible = fuzzy name match AND fuzzy address match (when contact info differs)
  Normalization: email -> lowercase + strip; phone -> digits only, last 10.
  Fuzzy thresholds: NAME_THRESHOLD / ADDR_THRESHOLD (difflib ratio in 0..1). Tune here.

COMPLETENESS (approved decision, strict):
  complete = name AND email AND phone AND address all present.
  - name    present: companyName OR firstName OR lastName non-empty
  - email   present: at least one non-empty email
  - phone   present: at least one non-empty phone
  - address present: a street line (street1) AND a city
  Missing categories are reported back to the owner.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher

NAME_THRESHOLD = 0.85
ADDR_THRESHOLD = 0.80


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def normalize_phone(phone: str) -> str:
    digits = re.sub(r"\D", "", phone or "")
    return digits[-10:] if len(digits) >= 10 else digits


def _ratio(a: str, b: str) -> float:
    a, b = (a or "").strip().lower(), (b or "").strip().lower()
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def name_similarity(a: str, b: str) -> float:
    return _ratio(a, b)


def address_similarity(a: str, b: str) -> float:
    return _ratio(a, b)


def emails_overlap(a: list[str], b: list[str]) -> bool:
    sa = {normalize_email(x) for x in (a or []) if normalize_email(x)}
    sb = {normalize_email(x) for x in (b or []) if normalize_email(x)}
    return bool(sa & sb)


def phones_overlap(a: list[str], b: list[str]) -> bool:
    sa = {normalize_phone(x) for x in (a or []) if normalize_phone(x)}
    sb = {normalize_phone(x) for x in (b or []) if normalize_phone(x)}
    return bool(sa & sb)


def completeness(client: dict) -> dict:
    """Strict rule: name AND email AND phone AND address. Returns {incomplete, missing_fields}."""
    missing: list[str] = []
    has_name = bool((client.get("company_name") or "").strip()
                    or (client.get("first_name") or "").strip()
                    or (client.get("last_name") or "").strip())
    has_email = any((e or "").strip() for e in (client.get("emails") or []))
    has_phone = any((p or "").strip() for p in (client.get("phones") or []))
    addr = client.get("address") or {}
    has_address = bool((addr.get("street1") or "").strip() and (addr.get("city") or "").strip())

    if not has_name:
        missing.append("name")
    if not has_email:
        missing.append("email")
    if not has_phone:
        missing.append("phone")
    if not has_address:
        missing.append("address")
    return {"incomplete": bool(missing), "missing_fields": missing}
