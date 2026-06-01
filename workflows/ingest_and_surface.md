# Workflow: Ingest & Surface (Layer 1)

## Objective
Pull newly-created Jobber **Requests**, read each Request and its linked **Client**, flag likely
**duplicate** and **incomplete** clients, and surface everything to the tracking Google Sheet for the
owner to review and fix manually in Jobber. Read → detect → surface. Nothing here changes Jobber data
or reaches a customer.

> **Next layer:** once Requests/Clients are surfaced here, [draft_and_propose.md](draft_and_propose.md)
> (Layer 2) drafts owner-approval-gated follow-ups + cleanup proposals from this same data — still
> read-only to Jobber, still sending nothing.

## Guardrails (read before running)
- **No irreversible actions this layer.** No Jobber writes/mutations (no merging, editing, completing,
  or creating anything), no messages/drafts/sends. The OAuth scopes are **read Clients + read Requests**
  only — there is no capability to write.
- **Tools read & write; judgment is the agent's.** The tools emit deterministic signals; the agent
  decides the final `duplicate_flag` (strong/possible/none) and the one-line `duplicate_reason`.
- **Escalate on doubt.** Anything ambiguous or outside this workflow → flag it for the owner, take no
  action. Surfacing "I wasn't sure, here's why" is always correct.
- **Cost:** routine per-lead reads are pre-authorized. A bulk/backfill (raising `MAX_FETCH` for a large
  first import, or any account-wide client scan) is **not** — confirm with the owner first.
- Knowledge-base grounding isn't exercised yet (no customer-facing claims this layer), but the
  escalate-on-doubt habit it depends on starts here.

## Required inputs / config (.env)
- `JOBBER_CLIENT_ID`, `JOBBER_CLIENT_SECRET`, `JOBBER_REDIRECT_URI`, `JOBBER_API_VERSION`
- `SPREADSHEET_ID`, `REQUESTS_TAB` (default `Requests`), `HYGIENE_TAB` (default `Client Hygiene`),
  `STATE_TAB` (default `_state`)
- `MAX_FETCH` — per-run safety cap (default 50)

Owner one-time setup (Jobber app + scopes + sandbox, Google Sheet + OAuth client, GraphiQL field
confirmation) lives in [../README.md](../README.md). Tokens are bootstrapped once with
`python tools/jobber_auth.py --authorize`.

## Steps

1. **Confirm connectivity (first run / after any token issue).**
   ```
   python tools/jobber_auth.py --smoke
   ```
   → prints reachability + `extensions.cost`. If it 401s, re-run `--authorize`.

2. **Read durable state.**
   ```
   python tools/sheet_state.py get                 # last_seen_cursor (empty on first run)
   python tools/get_processed_ids.py               # -> .tmp/processed_ids.json
   ```

3. **Poll new Requests + linked Clients.**
   ```
   python tools/fetch_new_requests.py --after "<last_seen_cursor>" --exclude-ids .tmp/processed_ids.json
   ```
   → `.tmp/new_requests.json` = `{new_cursor, fetched, requests:[{request_id, created_at, title,
   source, client{...}}]}`. (Omit `--after` on the very first run.)

4. **Per Request's Client, gather hygiene signals (agent loops over `new_requests.json`).**
   For each request's `client` object, run the two deterministic tools (pipe the client JSON in):
   ```
   <client.json>  | python tools/find_duplicate_clients.py     # -> {signal, exact_matches, fuzzy_candidates}
   <client.json>  | python tools/check_completeness.py         # -> {incomplete, missing_fields}
   ```

5. **Agent assessment (judgment).** For each Request:
   - `duplicate_flag`: `strong` if `exact_matches` (shared normalized email/phone); `possible` if
     `fuzzy_candidates` (fuzzy name **and** address); else `none`. Write a one-line `duplicate_reason`
     and put the matched client ids in `duplicate_of`.
   - `incomplete_flag` = `yes`/`no` from the completeness result; `missing_fields` = the list.
   - If something falls outside this workflow (unexpected shape, a client you can't read), note it for
     the owner and move on — no external action.

6. **Surface rows (idempotent upsert).**
   - One row per Request → Requests tab (set `status=surfaced`, or `needs_review` if it has any flag;
     set `surfaced_at` to now):
     ```
     python tools/log_to_sheet.py --target requests --row-file <request_row.json>
     ```
   - One row per **flagged** Client (duplicate and/or incomplete) → Client Hygiene tab
     (`issue` = duplicate/incomplete/both; `status=needs_review`):
     ```
     python tools/log_to_sheet.py --target hygiene --row-file <client_row.json>
     ```
   The tool appends if new, skips if the key already exists (dedup), and never overwrites an
   owner-edited row.

7. **Advance the cursor — only after the rows above are written.**
   ```
   python tools/sheet_state.py set --cursor "<new_cursor from new_requests.json>" --count <surfaced>
   ```
   Doing this last means a crash mid-run re-processes safely; dedup prevents duplicate rows.

8. **Summarize for the owner.** Report counts (new Requests, flagged clients by issue type), list every
   `needs_review` client with its `duplicate_reason` / `missing_fields`, and flag anything that fell
   outside this workflow. Take no external action.

## Sheet schema (canonical order in tools/sheet_schema.py)
- **Requests tab** — dedup key `request_id`: `request_id · created_at · request_title · request_source ·
  client_id · client_name · client_emails · client_phones · client_address · duplicate_flag ·
  duplicate_of · duplicate_reason · incomplete_flag · missing_fields · status · surfaced_at · owner_notes`
- **Client Hygiene tab** — dedup key `client_id`: `client_id · client_name · client_emails ·
  client_phones · client_address · issue · duplicate_flag · duplicate_of · duplicate_reason ·
  missing_fields · first_seen_request_id · status · surfaced_at · owner_action`
- **_state tab** — key|value rows: `last_seen_cursor · last_run_at · last_run_count`

- **Processed-state:** row existence in the Requests/Hygiene tabs (the system of record), never `.tmp/`.
- **Owner review/act (read-only layer):** owner filters Hygiene tab `status = needs_review`, reviews
  `duplicate_of` / `missing_fields`, then **manually merges or completes the record in Jobber** (Layer 1
  can't write). The owner records what they did in `owner_action` / `status`; the log tool treats any
  non-system status as owner-owned and won't overwrite it.

## Webhook receiver — DESIGN ONLY (not built this layer)
Jobber's production trigger is webhooks; the polling reader above is the Layer 1 stand-in (no public URL
needed). When we build the receiver later it must have three properties, derived from Jobber's docs:
1. **Authenticity:** verify the `X-Jobber-Hmac-SHA256` header = base64(HMAC-SHA256(raw request body,
   **app client secret**)); reject on mismatch.
2. **Speed:** respond `200` within **~1 second**, so it must **enqueue** the payload and process it
   asynchronously through the same ingest path above (never do the GraphQL reads inline in the handler).
3. **Idempotency:** delivery is **at-least-once**, so dedupe on payload identity (topic + object id +
   occurredAt) against the **same** Sheet processed-state — a re-delivered event must never double-surface.
Subscribe topic: `REQUEST_CREATE` (confirm the exact `WebHookTopicEnum` value in GraphiQL). Hosting needs
a public URL (a dev tunnel) — a later step, not Layer 1.

## Edge cases & learnings
*(Append findings over time — propose changes to the owner, don't silently overwrite, per CLAUDE.md.)*
- **Schema names unconfirmed:** the `Request`/`Client` field names, the `clients` search argument, and
  the `requests` ordering live in `tools/jobber_queries.py`. If a query 400s on an unknown field/arg,
  confirm the real name in GraphiQL and fix it **there** (single source of truth).
- **Throttling:** `jobber_auth.graphql()` retries on 429/`THROTTLED` using `throttleStatus`. Persistent
  throttling means lower `MAX_FETCH` or add delay between runs — don't hammer it.
- **Token refresh & rotation:** handled automatically; the rotated refresh token is persisted. If refresh
  fails, re-run `python tools/jobber_auth.py --authorize` to re-consent (read-only scopes only).
- **Cursor monotonicity:** `fetch_new_requests.py` only suggests `new_cursor`; the workflow advances the
  stored cursor in step 7 after logging. Never advance it before rows are written.
- **At-least-once / re-runs:** dedup on `request_id` / `client_id` means re-running never duplicates rows.
- **Client with no contact info:** completeness flags it `incomplete`; duplicate search may find nothing —
  that's fine, surface it as incomplete for the owner.
- **Pagination cap:** a run stops at `MAX_FETCH`; the next run continues from the advanced cursor. Raising
  the cap for a big first import is a bulk run and needs owner sign-off.
