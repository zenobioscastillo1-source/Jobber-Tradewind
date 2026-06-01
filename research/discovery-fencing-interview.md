# Discovery — Fencing-vertical interview (anonymized)

- **Date:** 2026-06-01
- **Type:** RAW INTERVIEW NOTES — first-hand discovery. **NOT confirmed knowledge.**
- **Source:** Informal interview with someone working in the fencing trade (a Jobber user).
- **Privacy:** **Anonymized.** No individual and no company is named. The conversation was informal and
  given without consent to attribution, so only the generalized pains and voice direction are recorded.
- **Significance:** First real **market validation** for Tradewind — a Jobber-using business in the
  **fencing** trade, the same home-services funnel we target.

> ⚠️ This file is research, not a source of truth. Nothing here may be used to ground a
> customer-facing draft. `knowledge/` remains the only grounding source, and only with
> owner-confirmed facts. This is recorded so it's available when we scope the lead-scoring layer
> or onboard a real fencing client — **not a build trigger.**

---

## Who they are

- **Vertical:** fencing (install/repair) — a home-services business on Jobber, same funnel we target
  (Request → Quote → Job → Invoice).
- **Brand voice to customers:** **gentle, friendly, formal.** (Real, usable voice direction — see
  "Product implications" for where it lands.)

## Pain points (in their words)

1. **Capacity-constrained, not lead-starved** — has a lot of customers but *cannot take them all*.
2. **Lead intake is a bottleneck** — manual, slow.
3. **Messy business data in Jobber** — duplicates, incomplete records.
4. **Facebook leads are mostly "trash"** — low intent, accidental form fills, noise.
5. **Manual replies** — the owner/team answers chat and email entirely by hand.

---

## How this maps to what we've built

| Pain | Maps to | Status |
|------|---------|--------|
| 2 — Lead intake bottleneck | Layer 1 triage + ingest (poll new Requests, read linked Client) | **Already built** |
| 3 — Messy data | Layer 1 hygiene detection (duplicate/incomplete flags) + Layer 2 proposed cleanups | **Already built** |
| 5 — Manual replies | Layer 2 grounded drafting with owner approval gate (email + SMS) | **Already built** |
| 1 — Can't take all leads | **Lead scoring / prioritization** — which leads deserve a fast warm response vs. a polite deferral | **NEW — not yet addressed** |
| 4 — Facebook leads are trash | **Source-based lead-quality filtering** — feeds scoring (Facebook vs. referral vs. organic as a quality signal) | **Partially new** |

**On Pain 1 (the real gap):** the current triage classifies leads as real / spam / existing, but does
**not rank by value or fit**. A capacity-constrained business doesn't need *more* leads — it needs to
know *which* leads to chase fast and which to gently defer. That ranking is the missing capability.

**On Pain 4:** automatically flagging low-intent Facebook leads is, on its own, high-value for this
kind of business. It's a special case of the scoring problem: **lead source is a quality signal.**

---

## What this means for the product

- **The lead-scoring / qualification layer is the gap between "nice tool" and "must-have."** For a
  capacity-constrained business, prioritization is the headline value, not drafting volume.
- **Proposed knowledge addition (when we scope it):** a `knowledge/qualification_criteria.md` template
  holding **vertical-specific scoring signals**, e.g.:
  - lead **source** (Facebook vs. referral vs. organic vs. website),
  - **job scope / size**,
  - **urgency**,
  - **property type**,
  - **location / service-area fit**,
  - whether they mention **competing quotes**.
  Like the rest of `knowledge/`, these criteria must be **owner-confirmed per business**, never invented.
- **Voice direction is real and reusable:** "gentle, friendly, formal" — note as the reference tone for
  when a **fencing-business instance** gets its own `voice.md`. (Distinct from the GreenLeaf *sample*
  voice currently in `knowledge/voice.md`, which is demo data.)

---

## Open questions / for later scoping

- Where does scoring sit — a new layer, or a signal added to Layer 1 triage that Layer 2 reads to
  decide *warm response vs. polite deferral*?
- What's the deferral path? (A "we're at capacity, here's our timeline / waitlist" drafted reply is
  itself a Layer 2-style grounded draft.)
- How much of "Facebook = low intent" generalizes vs. is specific to this one business's ad setup?
- Scoring is **probabilistic judgment** — under WAT it belongs in the agent layer, with the
  deterministic signals (source, scope keywords, area fit) extracted by tools. Keep that split.

**Reminder: don't build from this yet.** Discovery only.
