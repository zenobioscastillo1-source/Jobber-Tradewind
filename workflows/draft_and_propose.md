# Workflow: Draft & Propose (Layer 2)

## Objective
For each newly-surfaced Jobber **Request**, produce **drafted output held for the owner's approval**,
changing nothing: (1) a **follow-up message** to the lead (email + SMS variants), grounded only in
owner-confirmed `knowledge/` facts and aimed at a concrete next step; and (2) for the duplicate/gap
records Layer 1 flagged, a **proposed cleanup** ("here's what I would change"). Both land in the Sheet
with their provenance and an approve/edit/reject control. **Nothing is sent and nothing is written to
Jobber** — execution is Layer 3.

## Guardrails (read before running)
- **Read-only to Jobber; no new scopes; no send capability.** Layer 2 only *proposes* and *drafts*.
- **No invented facts (load-bearing this layer).** A draft may state **only** what a `knowledge/`
  file with `status: confirmed` (+ provenance, no gap markers) supports. Anything else →
  `ungrounded_flags`, escalate, do **not** answer. `tools/check_draft_grounding.py` enforces this;
  a draft that cites a gapped/unknown file **fails the gate**.
- **Proposals use only real record values.** Merge field-changes are copied from actual Jobber
  records — never fabricated. Missing values with no source record are gathered via the follow-up
  draft, not guessed.
- **High-confidence only (this layer's scope).** Strong duplicates → merge proposals. Possible-tier
  dupes and sourceless gaps → review note / follow-up, not a merge proposal.
- **Everything waits for the owner.** Approval is the default state. Escalate on doubt.

## Required inputs / config (.env)
- Everything Layer 1 needs, plus `DRAFTS_TAB` (default `Follow-up Drafts`) and `PROPOSALS_TAB`
  (default `Cleanup Proposals`). Both tabs are created automatically on first write.
- `knowledge/` populated by the owner in batches. Until a file is confirmed, drafts that would rely
  on it escalate — that is expected and safe.

## Preconditions
- Layer 1 has run: `Requests` / `Client Hygiene` populated, cursor advanced
  (see [ingest_and_surface.md](ingest_and_surface.md)). `.tmp/new_requests.json` holds the batch.

## Steps

1. **Load + validate the knowledge base.**
   ```
   python tools/knowledge_loader.py            # -> .tmp/knowledge_context.json
   ```
   Prints which files are confirmed/usable vs. GAPPED. If everything is gapped, drafts will all
   escalate — acceptable while content is pending.

2. **Read dedup state (so nothing is drafted/proposed twice).**
   ```
   python tools/get_processed_ids.py           # -> .tmp/processed_ids.json
   ```
   Carries `drafted_request_ids` and `proposed_ids` (empty until the L2 tabs exist).

### A. Follow-up drafts (one per new Request not already drafted)

3. **Build the drafting brief.**
   ```
   python tools/build_draft_context.py --request-id <rid>   # -> .tmp/draft_context_<rid>.json
   ```
   The brief lists the request/client facts, the **confirmed** knowledge the draft may use, and the
   **gapped topics it may NOT claim**.

4. **Agent composes the draft (judgment).** From the brief, write `email_subject` / `email_body` /
   `sms_body` in the owner's voice (`knowledge/voice.md`), aimed at one `next_step` (confirm details /
   book an assessment / send a quote). Cite the knowledge files used in `draft_grounding` (e.g.
   `services.md; service-area.md`). Put anything the lead asked that the knowledge base doesn't cover
   into `ungrounded_flags` and **do not answer it**. Assemble the full row (Drafts schema) to a file.

5. **Run the grounding gate (deterministic).**
   ```
   python tools/check_draft_grounding.py --draft-file <draft_row.json> --emit-row .tmp/_draft_row.json
   ```
   - PASS, no ungrounded asks → it emits the row with `status=drafted`.
   - PASS, but ungrounded asks present → it emits the row with `status=needs_owner_input` (escalation).
   - FAIL (cites a gapped/unknown file) → exit code 1, no row emitted; **fix the draft** (remove the
     unsupported claim or escalate it) and re-run. Never log a failed draft.

6. **Log the draft (idempotent upsert, dedup on request_id).**
   ```
   python tools/log_to_sheet.py --target drafts --row-file .tmp/_draft_row.json
   ```
   First write also applies the approve/edit/reject dropdown to the `status` column.

### B. Cleanup proposals (per Layer-1-flagged client)

7. **Gather duplicate signals** (reuse Layer 1's tool; its matches now carry the full sibling record):
   ```
   <client.json> | python tools/find_duplicate_clients.py > .tmp/dup_<cid>.json
   ```

8. **Propose the cleanup (deterministic, high-confidence only).**
   ```
   python tools/propose_cleanup.py --client-file <client.json> --matches-file .tmp/dup_<cid>.json --out .tmp/_proposal.json
   ```
   - `decision=merge_proposal` → `proposal` holds the row; go to step 9.
   - `decision=needs_followup` → no proposal; the gap is handled by the follow-up draft (section A).
   - `decision=review_note` → possible-tier only; surface the note to the owner, no merge row.
   - `decision=none` → nothing to propose.

9. **Log the proposal (idempotent upsert, dedup on proposal_id).**
   ```
   python tools/log_to_sheet.py --target proposals --row-file <proposal-row.json>
   ```

### C. Wrap up

10. **Advance state / summarize.** Drafts and proposals dedup on their own keys, so re-runs are safe;
    no separate cursor for Layer 2 (the Layer 1 cursor already governs which Requests are in scope).
    Report: how many drafts (drafted vs needs_owner_input), how many merge proposals, every escalated
    `ungrounded_flag`, and any review notes. **Take no external action.**

## How approval flows to Layer 3
The owner reviews each row and sets the `status` dropdown: `approved` / `edit` / `rejected` (pasting a
revised version into `owner_edit` when `edit`). Any non-system status is owner-owned and the log tool
never overwrites it (same guardrail as Layer 1). Layer 3 (gated, not built) will read `approved`
drafts/proposals and perform the send / Jobber merge — that is the only place execution happens.

## Edge cases & learnings
*(Append findings over time — propose changes to the owner, don't silently overwrite, per CLAUDE.md.)*
- **Empty knowledge base:** every draft escalates (`needs_owner_input`). Correct behavior — fill
  `knowledge/` in batches; drafts firm up on the next run.
- **`voice.md` empty:** the gate doesn't block (voice isn't a factual claim), but drafts fall back to a
  neutral professional tone — note it and ask for real samples.
- **Possible-tier duplicates:** not auto-merged this layer; they surface as review notes pending a
  real-data noise signal (the sandbox is currently empty by choice).
- **A draft needs a fact that's gapped:** that's not a failure of the system — it's the guardrail
  working. Escalate the specific ask; the owner confirms it into `knowledge/`.
