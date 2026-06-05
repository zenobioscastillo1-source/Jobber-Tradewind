"""Deterministic lead-scoring rules — the one auditable place that turns a Request's signals
into a 0-100 priority score (read-only "Score & Prioritize" layer). Same shape as
tools/hygiene_rules.py: the deterministic SIGNALS + a suggested tier live here; the AGENT makes
the final `priority_tier` call and writes the one-line `priority_reason` (CLAUDE.md keeps judgment
in the agent layer). The human-readable "why" behind these weights is knowledge/qualification_criteria.md
— keep the two in sync.

SCORING MODEL (sample/approved decision — tune the constants below):
  score = source + job_value + urgency + service_area + contactability   (clamped 0..100)
  Each signal contributes points from the tables below; the agent may override the resulting tier.

  Why these signals: home-services owners interviewed are CAPACITY-constrained, not lead-starved —
  they need to chase the right jobs fast and politely defer the rest. So we reward trusted sources,
  high-value/urgent jobs, in-area + reachable leads, and rank low-intent/out-of-area/unreachable down.

  Tiers (suggested; agent confirms): hot >= 75, warm >= 55, cool >= 35, else defer.

Everything here is pure + offline (no network, no Jobber calls): it scores the batch Layer 1 already
fetched. Scoring is INTERNAL triage (like the duplicate/incomplete flags) — never a customer-facing
claim — so it does NOT pass the knowledge grounding gate. Only a deferral *reply* (Layer 2 draft) does.
"""
from __future__ import annotations

from hygiene_rules import completeness

# --- Lead source -> points (max 30). Confirm the real Request.source values in GraphiQL. ----------
SOURCE_WEIGHTS = {
    "referral": 30,   # word-of-mouth: already trusts us
    "organic": 22,    # found us + reached out: active intent
    "website": 22,
    "google": 14, "search": 14, "ads": 14, "paid": 14,   # mid intent
    "facebook": 6, "instagram": 6, "social": 6,           # mostly low-intent
}
SOURCE_UNKNOWN_POINTS = 12   # source absent or unrecognised -> neutral, and flag it

# --- Job value -> points (max 28). Vertical-specific keywords; tune for the owner's trade. ---------
HIGH_VALUE_POINTS, MEDIUM_VALUE_POINTS, LOW_VALUE_POINTS, NEUTRAL_VALUE_POINTS = 28, 16, 6, 12
HIGH_VALUE_KEYWORDS = [
    "install", "installation", "patio", "retaining wall", "irrigation", "sprinkler system",
    "hardscape", "remodel", "renovation", "redesign", "landscape design", "full ", "project",
    "paver", "deck", "drainage", "sod", "new lawn", "build", "grading", "outdoor kitchen",
]
MEDIUM_VALUE_KEYWORDS = [
    "maintenance", "mowing", "mow", "weekly", "monthly", "recurring", "lawn care", "upkeep",
    "cleanup", "clean up", "clean-up", "trim", "fertiliz", "edging", "seasonal",
]
LOW_VALUE_KEYWORDS = [
    "quote", "estimate", "small", "quick", "repair", "fix", "price", "one-time", "single",
    "a few", "minor",
]

# --- Urgency -> points (max 20). Any hit = time-sensitive. -----------------------------------------
URGENCY_POINTS = 20
URGENCY_KEYWORDS = [
    "emergency", "asap", "urgent", "right away", "right now", "immediately", "today", "tonight",
    "this week", "next week", "this weekend", "next weekend", "storm", "flood", "burst", "leak",
    "no water", "deadline", "before our event", "before the event",
]

# --- Service-area fit -> points (max 12). Keep SERVICE_AREA_CITIES in sync with service-area.md. ---
IN_AREA_POINTS, UNKNOWN_AREA_POINTS, OUT_OF_AREA_POINTS = 12, 4, 0
SERVICE_AREA_CITIES = {"austin", "round rock", "pflugerville", "cedar park", "leander"}

# --- Contactability -> points (max 8). Can we actually reach them? --------------------------------
CONTACTABLE_POINTS = 8

# --- Tier thresholds (suggested; agent confirms the final tier) -----------------------------------
TIER_THRESHOLDS = [("hot", 75), ("warm", 55), ("cool", 35)]   # below the lowest -> "defer"

RECOMMENDED_ACTION = {
    "hot":  "Call / personal reply today",
    "warm": "Personal follow-up within the day",
    "cool": "Light-touch follow-up when capacity allows",
    "defer": "Send a warm waitlist / near-capacity reply (Layer 2 draft)",
}


def normalize_source(source: str) -> tuple[str, int]:
    """Map a free-text Request.source to (category, points). Unknown -> neutral."""
    s = (source or "").strip().lower()
    if not s:
        return "unknown", SOURCE_UNKNOWN_POINTS
    for key, pts in SOURCE_WEIGHTS.items():
        if key in s:
            return key, pts
    return "other", SOURCE_UNKNOWN_POINTS


def _matches(title: str, keywords: list[str]) -> list[str]:
    t = (title or "").lower()
    return [k.strip() for k in keywords if k in t]


def urgency_signal(title: str) -> dict:
    hits = _matches(title, URGENCY_KEYWORDS)
    return {"urgent": bool(hits), "points": URGENCY_POINTS if hits else 0, "matched": hits}


def job_value_signal(title: str) -> dict:
    """High > medium > low > neutral, by first keyword tier that matches."""
    for level, kws, pts in (
        ("high", HIGH_VALUE_KEYWORDS, HIGH_VALUE_POINTS),
        ("medium", MEDIUM_VALUE_KEYWORDS, MEDIUM_VALUE_POINTS),
        ("low", LOW_VALUE_KEYWORDS, LOW_VALUE_POINTS),
    ):
        hits = _matches(title, kws)
        if hits:
            return {"level": level, "points": pts, "matched": hits}
    return {"level": "unspecified", "points": NEUTRAL_VALUE_POINTS, "matched": []}


def service_area_fit(client: dict) -> dict:
    """in_area if the client's city is in SERVICE_AREA_CITIES; out_of_area if a city is set but not
    served; unknown if no city. Mirrors knowledge/service-area.md."""
    city = ((client.get("address") or {}).get("city") or "").strip()
    if not city:
        return {"fit": "unknown", "points": UNKNOWN_AREA_POINTS, "city": ""}
    if city.lower() in SERVICE_AREA_CITIES:
        return {"fit": "in_area", "points": IN_AREA_POINTS, "city": city}
    return {"fit": "out_of_area", "points": OUT_OF_AREA_POINTS, "city": city}


def contactable(client: dict) -> dict:
    """Reachable if at least one of email/phone is present (reuses the hygiene completeness rule so
    'present' never drifts from Layer 1)."""
    missing = set(completeness(client)["missing_fields"])
    reachable = not ({"email", "phone"} <= missing)   # reachable unless BOTH are missing
    return {"reachable": reachable, "points": CONTACTABLE_POINTS if reachable else 0}


def _tier_for(score: int) -> str:
    for tier, cutoff in TIER_THRESHOLDS:
        if score >= cutoff:
            return tier
    return "defer"


def score_lead(request: dict, client: dict | None = None, dup_signal: str | None = None) -> dict:
    """Score one Request + its linked Client. Returns the deterministic score, suggested tier,
    per-signal breakdown, human-readable reasons, and a recommended action. The agent confirms tier."""
    client = client or request.get("client") or {}
    title = request.get("title", "")

    src_cat, src_pts = normalize_source(request.get("source", ""))
    val = job_value_signal(title)
    urg = urgency_signal(title)
    area = service_area_fit(client)
    contact = contactable(client)

    score = min(100, max(0, src_pts + val["points"] + urg["points"] + area["points"] + contact["points"]))
    existing_customer = (dup_signal == "strong")

    reasons: list[str] = []
    reasons.append(f"Source: {src_cat} ({src_pts} pts)")
    reasons.append(f"Job value: {val['level']}" + (f" ({', '.join(val['matched'])})" if val["matched"] else ""))
    if urg["urgent"]:
        reasons.append(f"Time-sensitive: {', '.join(urg['matched'])}")
    reasons.append({"in_area": f"In service area ({area['city']})",
                    "out_of_area": f"Outside service area ({area['city']}) — travel surcharge / case-by-case",
                    "unknown": "Service area unknown (no city on record)"}[area["fit"]])
    reasons.append("Reachable (email/phone on file)" if contact["reachable"]
                   else "Not reachable (no email or phone) — can't be chased")
    if existing_customer:
        reasons.append("Existing customer (matches a record) — known client")

    tier = _tier_for(score)
    top_signals = "; ".join([
        f"source: {src_cat}",
        f"value: {val['level']}",
        f"urgency: {'yes' if urg['urgent'] else 'no'}",
        f"area: {area['fit']}",
        f"reachable: {'yes' if contact['reachable'] else 'no'}",
    ])

    return {
        "request_id": request.get("request_id", ""),
        "score": score,
        "suggested_tier": tier,
        "signals": {
            "source": {"category": src_cat, "points": src_pts},
            "job_value": val,
            "urgency": urg,
            "service_area": area,
            "contactability": contact,
            "existing_customer": existing_customer,
        },
        "top_signals": top_signals,
        "reasons": reasons,
        "recommended_action": RECOMMENDED_ACTION[tier],
    }
