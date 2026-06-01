# Knowledge base (the source of truth)

This folder is the engine's source of truth: owner-confirmed facts the agent reasons over and
the **only** thing it may ground customer-facing claims in. It never invents a fact about a
service, price, or policy — anything it can't ground, it **escalates** to the owner.

## Active as of Layer 2 (Draft & Propose)

Layer 2 introduces the first **customer-facing output** (drafted follow-ups), so this folder is now
load-bearing. The files below are **scaffolded as gap-marked templates** — no real data — and the
owner fills them in batches. A draft may only state what a **confirmed** file supports; anything else
**escalates** (it is never guessed).

| File | Holds |
|------|-------|
| `services.md`     | services offered **and explicitly not offered**, plus the next step per service |
| `pricing.md`      | rates, call-out / trip fee, estimate policy (never invent a number) |
| `service-area.md` | geographic area served / not served |
| `policies.md`     | hours, scheduling, cancellation, guarantees |
| `faqs.md`         | the real questions prospects ask, plus objection handling |
| `voice.md`        | tone notes + real sample replies (email **and** SMS) so drafts sound like the owner |

## The frontmatter / gap contract (the loader and grounding gate depend on this)

Every file starts with YAML frontmatter:

```yaml
---
topic: pricing
status: gap            # gap | confirmed — ONLY "confirmed" is usable for grounding a draft
confirmed_by:          # owner name/email — REQUIRED to flip status to confirmed
confirmed_on:          # YYYY-MM-DD       — REQUIRED to flip status to confirmed
---
```

- **`status: gap`** (or any unconfirmed value, or missing `confirmed_by`/`confirmed_on`) ⇒
  `tools/knowledge_loader.py` marks the file **unusable**, and `tools/check_draft_grounding.py`
  **refuses** any draft that cites it. This is the fabrication guardrail in code.
- Flip to **`status: confirmed`** only when `confirmed_by` and `confirmed_on` are both filled **and**
  no `[GAP — OWNER CONFIRM]` markers remain in the body (the loader reports `has_gaps`).
- **Provenance is mandatory:** who confirmed it, when. We never invent pricing, policies, services, or
  any product fact — not even as a placeholder presented as real.

> Filled-in files are business-specific. Keep any repo containing real `knowledge/` **private**.
