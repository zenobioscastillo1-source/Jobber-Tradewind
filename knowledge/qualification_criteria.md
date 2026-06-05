---
topic: qualification_criteria
status: sample         # SAMPLE/demo content — fictional business, NOT real. Usable only to demo scoring.
confirmed_by: SAMPLE DATA — fictional "GreenLeaf Landscaping" (not a real business)
confirmed_on: 2026-06-05
---

# Lead qualification criteria  (SAMPLE — fictional GreenLeaf Landscaping)

This is the owner-confirmed "why" the agent reasons over when it prioritises a lead. The deterministic
weights that turn these signals into a 0–100 score live in `tools/scoring_rules.py` (one auditable
place to tune, like the hygiene thresholds in `tools/hygiene_rules.py`). This file is the human
explanation; that file is the encoding. Keep them in sync.

## Capacity posture (the whole reason this layer exists)
GreenLeaf is **capacity-constrained, not lead-starved** — more leads come in than the crew can take.
So the goal is **triage, not volume**: chase the high-fit jobs fast, and **politely defer** the
low-fit ones (a warm "we're near capacity, may we add you to our waitlist?" reply) rather than ignore
them. Deferral is a kindness, not a rejection.

## What raises a lead's priority
- **Lead source / intent.** Referrals are gold (they already trust us). Then organic / website
  enquiries (active intent). Paid search is mid. **Facebook / social leads are mostly low-intent**
  ("how much for mowing?") and rank lowest by default.
- **Job value.** Big installs and projects beat one-off odd jobs:
  - High — full landscape installs, patios, retaining walls, irrigation systems, remodels, "new" builds.
  - Medium — recurring maintenance (mowing/lawn-care contracts): smaller per-visit, but strong
    lifetime value, so still worth taking when capacity allows.
  - Low — small one-off repairs / "just a quick quote" for a tiny job.
- **Urgency.** Time-sensitive wording — "emergency", "asap", "storm damage", "this week", "before
  [event/date]" — means chase now; these convert if answered fast and go cold if not.
- **Service-area fit.** In our Austin metro (see `service-area.md`: Austin, Round Rock, Pflugerville,
  Cedar Park, Leander) is a clean yes. Outside the metro is case-by-case / travel surcharge → lower
  priority, and never promise service — flag for the owner.
- **Contactability.** A lead we can actually reach (has a phone or email) outranks one with no way to
  respond. An unreachable lead can't be chased no matter how good the job looks.
- **Competing quotes.** If the lead mentions they're "getting other quotes" / "comparing", it's
  time-sensitive — prioritise so we're not last to reply.

## Priority tiers (the agent's final call)
- **hot** — chase today. High-fit + (high value or urgent), in-area, reachable. Personal reply fast.
- **warm** — standard follow-up within the day. Good fit, no urgency, or solid recurring-revenue work.
- **cool** — low priority. Small/low-value or weak-intent but still in-area and worth a light touch.
- **defer** — politely deflect to a waitlist. Out-of-area, unreachable, or low-intent/low-value such
  that taking it would crowd out better work while we're at capacity.

## How deferrals are handled (customer-facing → must be grounded)
A `cool`/`defer` lead still gets a reply — a warm waitlist / "near capacity" note drafted through the
**Layer 2 grounded drafting** path (`build_draft_context` → draft → `check_draft_grounding`), in the
owner's voice (`voice.md`), held for approval. The *score* is internal triage and is never shown to
the customer; only the drafted reply is, and it states nothing that isn't in confirmed knowledge.
