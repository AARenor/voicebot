# Operator website and booking visibility — implementation contract

Status: **researched proposal, not implemented**. MODE RESEARCH,2026-10-01.
Evidence: [three-round ledger](RESEARCH.md), [verification](EVIDENCE.md).

## Architecture decision

Keep one deployable FastAPI app and the existing plain HTML/JS dashboard.
`robot.arleserver.cfd` is the operator control plane: static UI, private data
reads and operator-authenticated HTTP voice turns. Easy!Appointments is booking
truth; MySQL belongs exclusively to it. SQLite journal coordinates this sole
writer, not inventory. Do not add React, Redis, another database, public Easy
admin embedding, webhooks or a separate booking service for a read-only panel.

```text
CURRENT website browser → GET dashboard API → synthetic holds/metrics
CURRENT website browser → GET calls API → persisted summaries (privacy gap)
CURRENT authorized HTTP client → /api/turn → run_turn → Dispatcher
  → SlotAdapter → private Easy REST → authoritative MySQL
                        └─ persistent write journal / file lock

PROPOSED authorized website browser → GET /api/bookings
  → private provider read-through → allowlisted schedule DTO → booking panel
```

The current page does **not** submit `/api/turn` or display provider bookings.
All proposed endpoints/capabilities below are contracts, not existing APIs.
No public telephone receptionist or real-guest readiness is implied.

## Phase A — contain read privacy, before adding data

Touched implementation paths when a BUILD task is requested:
`app/dashboard/api.py`, `app/server.py`, `app/dashboard/static/index.html`,
`app/callslog.py`; tests `tests/test_dashboard.py`, `tests/test_callslog.py`.

- Reuse `_require_operator` for `/api/calls` and new provider read routes.
  No configured operator credential→503; absent/wrong credential→403, matching
  current contract. Auth must run **before** any provider/local data lookup.
- Keep `/health` minimal/public. Public status may show only coarse readiness;
  no catalogue, record IDs, provider URLs, credentials or call summaries.
- Browser attaches its operator header to protected GETs as well as writes.
  No logged-out fetch of protected resources. Logout clears sensitive DOM/state
  and aborts outstanding requests; never fall back to demo data on auth errors.
- `Cache-Control: no-store` for sensitive reads including error responses;
  CDN caching disabled for those routes. Do not treat Cloudflare1010 as app auth.
- Replace raw heard/reply call summaries with minimal operational outcome by
  default before real guest use; explicit approved retention/identity policy
  needed for anything richer. Do not delete existing logs in this research goal.
- Existing sessionStorage Bearer input is a bounded demo stopgap; do not add
  another browser-stored provider credential. Production needs real operator
  identity/roles and revocation, designed separately rather than guessed here.

## Phase B — minimal read-only bookings panel

Paths: `app/booking/easyappointments.py` (provider-specific read operation),
`app/dashboard/api.py` (protected route), `app/server.py` (read capability
injection), `app/dashboard/static/index.html` (panel),
`tests/test_easyappointments_safety.py`, `tests/test_dashboard.py`,
`tests/test_easyappointments_installed.py` plus a headless UI regression.
Do not expand the generic StayAdapter/SlotAdapter mutation contract for an
operator-only projection. No direct MySQL access from Python/browser.

**Proposed `GET /api/bookings?date=YYYY-MM-DD&page=1&length=50`**:

1. Authenticate operator. Validate exact date, page1–100, bounded length1–50.
   Proposed synthetic default date window:31 days back through90 days ahead
   relative to the configured venue day; review limits before real-property use.
   Never forward user-controlled URL, `fields`, `with`, sort, keyword or filters.
2. Require a separately wired provider **read capability**, independent of
   `EASY_DEMO_WRITES`. Current stack sets slot=None when writes disabled; do not
   misleadingly report that read-only operation already works in that mode.
   Construction may use the same adapter/client, but read access must not
   advertise/enable confirm/cancel. Failure to open write journal must not grant
   writes merely to make viewing possible.
3. Query documented private `/appointments` with date/page/length,
   deterministic `sort=+start,+id`, fixed
   `fields=id,start,end,status,serviceId,providerId`.
   `page/length`, not invented start-offset pagination. Do not request customer
   aggregates, free-text notes, booking hashes, links or calendar identifiers.
4. Independently validate/project upstream payload into a dedicated response
   model. Positive IDs, coherent start/end, known service/provider mapping;
   malformed payload→closed502, never raw provider body/exception text.
5. Display local start/end plus explicit provider IANA timezone. For this
   synthetic instance use verified Europe/Tallinn, not browser/device timezone.
   For an ambiguous/nonexistent DST time mark `time_state: ambiguous|invalid`;
   do not synthesize a UTC instant or silently choose fold. Unknown timezone
   also needs a visible warning. Require future DST fixtures before UTC output.
   Read timezone from verified server-side provider metadata using fixed
   allowlisted fields; current `get_slot_catalogue` strips timezone, so do not
   assume it already supplies this information. Invalid syntax/coherence is502;
   syntactically valid DST gaps/folds are explicit warnings, not guessed instants.

Suggested DTO (field names are the proposal, not upstream promises):

```text
source: easyappointments
data_mode: synthetic
fetched_at: UTC ISO timestamp
date: YYYY-MM-DD
page: positive integer
length: bounded integer
has_more: false|unknown (false for short page; unknown for full page)
items: [
  id, start_local, end_local, timezone, time_state,
  provider_id, provider_name, service_id, service_name, status
]
```

Pagination detail: **do not** change upstream length to length+1 while retaining
upstream page, which changes the offset. Prefer fixed provider page/length and
`has_more: unknown` for a full page, or explicitly implement validated offset
translation/multi-page reads. Final minimal DTO therefore uses
`has_more: false|unknown`, omits `next_page`, and shows “load next page” only
for a full page. No exact total-count claim. Stable source, populated paging
fixtures and cleanup-managed live test must verify this before shipping.

Label status as a provider value, not a guaranteed semantic enum. A deleted
appointment is absent, not evidence of cancellation outcome to reconstruct.
Do not call every returned row “created by the voicebot”: marker notes are
excluded, so the initial panel shows all appointments on the controlled
synthetic instance. Future multi-property filters require server-side scope
authorization, not arbitrary ID parameters.

## UX and capability truth

- First panel: **Broneeringud**, “Easy!Appointments · sünteetiline demo”, date,
  **Europe/Tallinn**, provider/service/start/end/status/reference, last-successful
  refresh time. No guest names, emails, phone, notes or invented prices.
- Distinct empty, loading, unauthorized, unconfigured and provider-unavailable
  states. Error must not render an empty successful schedule. Retained rows must
  say **Aegunud andmed** with last-success timestamp; never appear live/current.
- Reuse30s polling only while visible and authenticated; abort on logout,
  no overlapping refreshes, back off on429/5xx and stop on403. Refresh button
  and pagination state are keyboard accessible; `aria-live=polite` announces
  refresh/error summary, not every row. Mobile stacked rows preserve labels.
- Use labeled native date/select controls, semantic table/caption/header cells,
  visible keyboard focus, tabular numerals and long-label wrapping. Mirror safe
  date/page state in the URL, never credentials/customer fields. Keep50 rows per
  page so a virtualization library is unnecessary. Errors give a next action
  (authenticate, retry, check configuration), not just an HTTP code. Preserve
  zoom and reduced-motion preferences; do not hide overflowing content to pass
  tests. Locale formatting must preserve wall-time/zone semantics above.
- Keep **Näidisjärjekord** and **Näidismõõdikud** visibly separate from provider
  schedule. Scope “PMS-i ei kirjutata” to queue demo actions; the separate
  HTTP voice pipeline can create synthetic appointments when explicitly opted in.
- Render provider labels via textContent/escaped text, never raw innerHTML.
- Proposed status adds `booking_read_ready` and `booking_view_source`; report
  configuration separately from last successful provider health/read time.
  Existing `slot_booking_ready` is not a successful-read timestamp.

## Phase C — optional later features, not part of minimal read scope

- Browser text/audio demo form may call existing authenticated `/api/turn`,
  explicitly synthetic; confirm trusted customer/ownership constraints and
  warn which operations can write. Carrier/SIP integration is a separate gate.
- Booking commands must use one operator command service → existing guarded
  adapter (auth, stable idempotency, recheck, file lock/journal). Never wire a
  second browser→Easy POST or turn synthetic hold IDs into real booking IDs.
- Show an authenticated aggregate “write recovery needed” indicator only
  after a safe journal-read API is designed; pending customer/appointment is
  not a confirmed booking. No “clear journal/retry new key” button.
- Uncertain customer create requires reviewed operator reconciliation; an
  uncertain appointment resolves only through unique provider correlation.
  Protect journal and database backups as one unit. Keep one app replica.

## BUILD acceptance tests (required before enabling the panel)

1. No/wrong/missing-config auth→403/403/503 and **zero** provider reads;
   successful private read→200; all private successes/errors no-store.
2. `EASY_DEMO_WRITES=0` can view configured schedule but no write tools;
   confirm/cancel direct methods still deny. Unconfigured read→503.
3. Empty provider array→200 empty-state; malformed fields/time/IDs→502; network
   timeout→504; upstream401→closed502/configuration issue;429/5xx→503 with bounded
   Retry-After where safe. Raw backend values and credentials never leak.
4. DTO/OpenAPI/DOM forbid notes, hashes, customerId/contacts, calendar/link
   fields; service label `<img onerror=...>` renders literal text only.
5. Positive bounded page/length, deterministic two-page fixture with no
   missing/duplicate rows; provider reads include only fixed fields/params.
6. Tallinn winter/summer/gap/fold fixtures and browser in another timezone;
   precise local display or explicit warning, never guessed UTC offset.
7. Logout during in-flight read clears rows and ignores late responses;
   error/stale states and keyboard/mobile behavior; demo/live banners separate.
8. Installed fixture creates a synthetic appointment through the existing
   sole writer, privately lists it through the proposed API, independently
   reads provider truth, cancels via guarded adapter and checks disappearance;
   cleanup on success/failure. No blind writes after timeouts.
9. Full repo suite and existing same-slot/unknown-write regressions stay green;
   staged secret scan, one replica, deployed auth/private-read/empty/error proof.

Current verification is of the **research and architecture artifacts**, not
these unimplemented acceptance tests. The safe next build is Phase A+B only.
