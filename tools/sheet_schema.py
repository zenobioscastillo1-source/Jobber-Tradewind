"""Canonical Google Sheet schemas for the Jobber engine (Layer 1).

Single source of truth for column order on each tab, the dedup key column, and which
`status` values are 'system-owned' (safe to overwrite) vs owner-edited (never overwrite).
Every Sheet tool imports from here so the layout never drifts.
"""
from __future__ import annotations

# One row per Request surfaced from Jobber. Dedup key = request_id (column A).
REQUESTS_COLUMNS = [
    "request_id",        # dedup key (Jobber Request id); row existence = surfaced
    "created_at",        # Request.createdAt (ISO8601)
    "request_title",     # Request.title
    "request_source",    # Request.source
    "client_id",         # linked Client id
    "client_name",       # companyName, else "firstName lastName"
    "client_emails",     # all client emails, "; "-joined
    "client_phones",     # all client phones, "; "-joined
    "client_address",    # formatted billing/property address
    "duplicate_flag",    # AGENT: strong / possible / none
    "duplicate_of",      # tool: matching client ids, "; "-joined
    "duplicate_reason",  # AGENT: one-line rationale
    "incomplete_flag",   # rule: yes / no
    "missing_fields",    # rule: missing required fields, "; "-joined
    "status",            # surfaced / needs_review / (owner sets e.g. reviewed)
    "surfaced_at",       # ISO timestamp the system logged the row
    "owner_notes",       # free text for the owner
]

# One row per FLAGGED Client (duplicate and/or incomplete). Dedup key = client_id (column A).
HYGIENE_COLUMNS = [
    "client_id",             # dedup key (Jobber Client id)
    "client_name",
    "client_emails",
    "client_phones",
    "client_address",
    "issue",                 # duplicate / incomplete / both
    "duplicate_flag",        # strong / possible / none
    "duplicate_of",          # matching client ids, "; "-joined
    "duplicate_reason",      # AGENT one-line rationale
    "missing_fields",        # rule: missing required fields, "; "-joined
    "first_seen_request_id", # the Request that first surfaced this client
    "status",                # needs_review / (owner sets e.g. merged / completed)
    "surfaced_at",           # ISO timestamp the system logged the row
    "owner_action",          # free text: what the owner did in Jobber
]

# ---- Layer 2 (Draft & Propose) tabs ------------------------------------------------------
# Both are read-only to Jobber: drafted output held for the owner's approval, nothing executed.

# One row per follow-up DRAFT (email + SMS variants). Dedup key = request_id (column A).
DRAFTS_COLUMNS = [
    "request_id",        # dedup key (the Request this follow-up answers)
    "client_id",         # linked Client id
    "client_name",
    "request_title",     # what the lead asked about
    "next_step",         # AGENT: the concrete CTA (confirm details / book assessment / quote)
    "email_subject",     # AGENT: email variant subject
    "email_body",        # AGENT: email variant body, in the owner's voice
    "sms_body",          # AGENT: short SMS variant
    "draft_grounding",   # AGENT: knowledge/ files (provenance) every claim rests on, "; "-joined
    "ungrounded_flags",  # GATE/AGENT: asks knowledge/ can't cover -> escalated, NOT answered
    "status",            # system: drafted / needs_owner_input ; owner dropdown: approved / edit / rejected
    "owner_edit",        # owner pastes a revised draft here (used by Layer 3 when status=edit)
    "drafted_at",        # ISO timestamp the system logged the row
    "owner_notes",       # free text for the owner
]

# One row per PROPOSED cleanup (high-confidence only). Dedup key = proposal_id (column A).
PROPOSALS_COLUMNS = [
    "proposal_id",        # dedup key (deterministic: type + sorted client ids)
    "proposal_type",      # merge_duplicates / complete_from_source
    "primary_client_id",  # the record proposed to keep
    "related_client_ids", # duplicate/source record id(s), "; "-joined
    "client_name",
    "proposed_change",    # human-readable summary of the exact change
    "field_changes",      # structured field=value list (values ONLY from real records), "; "-joined
    "rationale",          # why — built on Layer 1's duplicate_reason / missing_fields
    "source_flag",        # links back to Hygiene issue: duplicate / incomplete / both
    "confidence",         # strong (high-confidence only this layer)
    "status",             # system: proposed ; owner dropdown: approved / edit / rejected
    "owner_edit",         # owner pastes an amended change here (used by Layer 3 when status=edit)
    "proposed_at",        # ISO timestamp the system logged the row
    "owner_notes",        # free text for the owner
]

# ---- Score & Prioritize (read-only) tab --------------------------------------------------
# Internal triage: rank each surfaced Request by likely value/fit. The score is NOT customer-facing
# (it never leaves the Sheet); only a deferral *reply* (a Layer 2 draft) is. One row per Request.

# Dedup key = request_id (column A).
SCORING_COLUMNS = [
    "request_id",          # dedup key (the Request this score is for)
    "created_at",          # Request.createdAt (ISO8601)
    "request_title",       # Request.title
    "request_source",      # Request.source
    "client_id",           # linked Client id
    "client_name",
    "score",               # tool: deterministic 0-100 (tools/scoring_rules.py)
    "priority_tier",       # AGENT: hot / warm / cool / defer (confirms the tool's suggestion)
    "priority_reason",     # AGENT: one-line rationale
    "top_signals",         # tool: source/value/urgency/area/reachable summary, "; "-joined
    "recommended_action",  # AGENT: chase today / follow up / defer to waitlist
    "deferral_drafted",    # cross-link: yes/no (a Layer 2 waitlist draft was queued for cool/defer)
    "status",              # system: scored ; owner dropdown: chasing / deferred / reviewed
    "surfaced_at",         # ISO timestamp the system logged the row
    "owner_notes",         # free text for the owner
]

# Per-target Sheet config. The tab name itself is resolved at runtime from .env.
# Optional "dropdowns" is a list of data-validation lists, each pinned to a named column, so the
# owner picks from a chip instead of typing (showCustomUi, non-strict — system values pass without
# a warning). A tab may carry several (e.g. an owner status AND a priority tier).
TARGETS = {
    "requests": {
        "columns": REQUESTS_COLUMNS,
        "key": "request_id",
        "tab_env": "REQUESTS_TAB",
        "tab_default": "Requests",
        # status values the system itself sets; ANY other value = owner-edited, never overwrite
        "system_statuses": {"", "surfaced", "needs_review"},
    },
    "hygiene": {
        "columns": HYGIENE_COLUMNS,
        "key": "client_id",
        "tab_env": "HYGIENE_TAB",
        "tab_default": "Client Hygiene",
        "system_statuses": {"", "needs_review"},
    },
    "drafts": {
        "columns": DRAFTS_COLUMNS,
        "key": "request_id",
        "tab_env": "DRAFTS_TAB",
        "tab_default": "Follow-up Drafts",
        "system_statuses": {"", "drafted", "needs_owner_input"},
        "dropdowns": [{"column": "status",
                       "values": ["approved", "edit", "rejected", "drafted", "needs_owner_input"]}],
    },
    "proposals": {
        "columns": PROPOSALS_COLUMNS,
        "key": "proposal_id",
        "tab_env": "PROPOSALS_TAB",
        "tab_default": "Cleanup Proposals",
        "system_statuses": {"", "proposed"},
        "dropdowns": [{"column": "status",
                       "values": ["approved", "edit", "rejected", "proposed"]}],
    },
    "scoring": {
        "columns": SCORING_COLUMNS,
        "key": "request_id",
        "tab_env": "SCORING_TAB",
        "tab_default": "Prioritized Leads",
        "system_statuses": {"", "scored"},
        "dropdowns": [
            # AGENT-confirmed priority tier — the owner can re-pick it from a chip (hot..defer).
            {"column": "priority_tier", "values": ["hot", "warm", "cool", "defer"]},
            {"column": "status", "values": ["chasing", "deferred", "reviewed", "scored"]},
        ],
    },
}

# _state tab: simple key|value rows (column A = key, column B = value). Durable control-state.
STATE_TAB_ENV = "STATE_TAB"
STATE_TAB_DEFAULT = "_state"
STATE_KEYS = ["last_seen_cursor", "last_run_at", "last_run_count"]
