# Restaurant-only voicebot — implementation design

## Intent and scope

The user has changed the product to restaurants only and requests implementation,
bug repair and deployment of other contributors' changes. Default website,
operator booking controls and native telephone dialogue must reserve fictional
restaurant tables, not hotel rooms or spa appointments. Keep the existing
incoming telephone route, authentication, multilingual voice, call history,
exact recap delivery and later consent. No actual restaurant/customer mutation,
outbound call, purchase, invented contact details or production-readiness claim.

Starting published revision: `abd5f38`, including contributor PRs 1–5, natural
conversation, English/Russian speech, browser English and release synchronization.
All named contributor implementation branches inspected are already in master.
The exclusive modern-voices branch contains a design/plan only, not another
implementation to deploy. Preserve subsequent published commits by normal merge.

## Options and selected approach

1. Rename spa slots: rejected. It cannot represent party size, physical-table
   capacity, full sitting overlap or restaurant closing time.
2. Add one concrete SQLite fictional table adapter and extend the shared
   Dispatcher/CallTools boundary: selected. Reuses existing safety and voice
   infrastructure without a second pipeline or additional dependency.
3. Add a commercial restaurant/POS connector now: rejected. No real restaurant,
   connector/account or authorization was supplied. Keep this demonstrably
   fictional and provider-neutral until such integration is explicitly scoped.

## Domain and persistence

Add `app/booking/demo_table.py::DemoTableAdapter`, patterned after the existing
durable DemoStayAdapter, and `data/demo/restaurant-demo.json`. Restaurant is
"Meretuule restoran", explicitly fictional. Retain approved guest fixtures and
their existing reserved contact/call-scoping rules; do not collect real contacts.
Seed five physical tables with capacities 2, 2, 4, 4 and 6, daily opening
12:00–22:00 Tallinn time, a 120-minute sitting, 90-day horizon and party size
1–6 including all seated children. No combined tables, time substitution or
invented prices. The catalogue is the authority for these demo rules.

Use a separate persistent `/data/restaurant-booking.db` (optional
`RESTAURANT_STATE_DB` override under the same shared volume). Preserve every
existing booking/history database; no drop, clear or wholesale migration.
Transactionally persist offers, holds, reservations and idempotent write results.
Use `BEGIN IMMEDIATE`, fingerprinted keys, unique confirmed hold and interval
overlap `existing.start < requested.end AND existing.end > requested.start`.
Only confirmed reservations and unexpired holds occupy tables. Pick the
smallest adequate available table deterministically inside the hold transaction.
Expiry, cancellation and exact adjacency release/permit capacity safely.

Validate canonical YYYY-MM-DD/HH:MM, strictly integer headcounts (not booleans,
floats or implicit defaults), future instants, horizon and whole sitting within
opening hours. Reject nonexistent/ambiguous local instants rather than silently
normalizing them. Store explicit timezone-aware starts/ends and canonical local
date/time. Hold `quoted_total` is None; no authorized price is invented.

Adapter interface follows the existing asynchronous concrete adapters:

* `get_table_catalogue()` → venue, tables and rules.
* `search_tables(date, start_time, party_size)` → list of exact offers containing
  `table_offer_id`, local date/time, aware start/end, party size, duration,
  capacity, table identity/name and expiry.
* `create_hold(table_offer_id)` / `get_hold(hold_id)` → existing Hold envelope.
* `confirm(hold_id, guest, idempotency_key)` → authoritative table-prefixed
  reservation receipt; no guest supplied by model or arbitrary UI contact.
* `cancel(booking_id, idempotency_key)` → durable authoritative cancellation.
* `get_operator_bookings(date)` → authenticated independent reservation readback.

## Shared policy and runtime contract

Extend Dispatcher with `table=` and an explicit business selector. Legacy
unit/test callers may use their explicit existing slot/stay setup; actual
server/worker startup sets business="restaurant" and table-only defaults.
An unavailable restaurant backend fails closed, never selects a hotel/spa backend.

Extend CallTools rather than invent a parallel policy. Restaurant sessions must
reject legacy tool dispatch even if legacy adapters are accidentally wired.
Conversation model schemas advertise only:

* `get_demo_profile`, `get_table_catalogue`;
* `plan_demo_table(date, start_time, party_size, guest_fixture_id="guest-001")`;
* `confirm_table_booking(hold_id)`, `cancel_table_booking(booking_id)`.

Internally the same policy supports `search_tables`, `hold_table` and
`prepare_demo_table` for direct controls. Planning performs catalogue/availability,
owned hold and preparation only; no confirmation. Preserve supersession checks
after awaits, server-generated idempotency, owned offer/hold/booking sets,
fixture locking, later affirmative final transcript, exact expiry and language-
change invalidation. Add table names to every mutation-attempt, sticky uncertainty,
preparation invalidation, SDK tool, canonical speech and history-receipt guard.

Recap includes fictional venue, exact Tallinn date/time, all diners, sitting
duration/table and approved fictional guest. Implement truthful approved speech
and domain clarification/FAQ in Estonian, English and Russian. Don't fall back to
spa/hotel questions or allow the model to invent booking success. Preserve
contributors' natural conversation, language selection, speech normalization,
generation-owned fallback history and speech-handle delivery.

Confirmation/cancellation remain trusted terminal actions requiring zero extra
model requests once policy authorizes them. Both HTTP and native call the same
CallTools. Extend `call_history` with validated `kind="table"` and table-prefixed
receipt IDs without duplicating names/contacts/transcripts into history.

## Direct HTTP and interface contract

Keep `/api/booking/{session,search,prepare,recap,confirm,cancel}` and authentication.
Restaurant requests use `kind="table"`; legacy slot/stay mutations are refused
in restaurant mode. Search fields: date, start_time, party_size. Prepare selects
`table_offer_id` returned to that same session and approved guest fixture only.
Expose `/api/tables` and `/api/table-bookings` as authenticated catalogue/readback.
Public property/catalogue return restaurant identity/rules/capabilities, no active
room/spa offers. Historical records keep their original kind and are never
relabeled restaurant reservations.

Search returns `kind="table"` and `offers`. Preparation returns canonical
`recap`, `hold_id`, `kind="table"` and a one-use `recap_delivery_id` bound to the
identical pending proposal. Direct recap acknowledgement supplies session,
hold and that receipt; a stale acknowledgement for the same hold must not
authorize a replacement preparation. This repairs the direct UI's current
hold-ID-only delivery gap using the existing voice receipt pattern. Client
reading/playback assertion still does not prove the listener heard anything.

The operator has one reservation form: date, time, headcount, availability,
canonical recap, explicit confirm/decline and owned two-step cancellation.
Display fictional identity; no free-form customer contact collection. Preserve
stale-read truthfulness, uncertain-write lockout, auth only in memory, logout and
late-response cleanup, microphone/audio race repairs and responsive accessibility.
Public Meretuule page becomes a restaurant page and links to the authenticated
demo; no anonymous write boundary is added. Keep existing asset paths/domain
routing to avoid unrelated infrastructure changes. History handles table links
and safely displays archived slot/stay metadata without dead DOM targets.

## Packaging bug and deployment

Before edits, the published release worker was unhealthy with 21 restarts:
ModuleNotFoundError for app.booking.easyappointments. Pinned failed image's
booking directory was root-owned0700; default UID10001 could not read it while
UID0 could. A separate rollout restored a manually built healthy worker. Repair
the image packaging with ownership for the existing non-root user; keep private
release archives/state private, never run the service as root or loosen global
permissions. Reproduce with an actual restrictive archive/image import regression.

Preserve published automatic release synchronization, idle-room protection and
draining. Web remains existing Coolify deployment; native worker/bridge must be
checked independently and match the tested published source. Only target those
required services, not Redis/LiveKit/SIP or other applications. Use trusted
container environment in memory, existing named /data volume, private hash-only
before/after snapshots and exact served/source hashes. No raw credentials/logs.

## Verification and ownership

Backend lane: new demo_table.py, new restaurant fixture, booking/tools.py and
backend tests. Policy lane: telephone.py, booking_response.py, call_history.py,
domain conversation/localization and policy tests. Frontend lane: coupled public/
dashboard assets, call-history.js, browser fixture and product/browser tests.
Owner: server.py, hackathon.py, booking_web.py, native startup/HTTP tests,
deployment packaging/config/probes, docs and integration. No overlapping edits.

Tests first, observed failures before implementations. Cover capacity contention,
adjacent/overlapping times, closing overrun, expiry/restart/replay/key conflicts,
booleans/malformed times, negative/ambiguous/early consent, foreign/stale receipts,
same-hold re-preparation, language changes, uncertain writes and old tool denial.
Verify independent readback and owned cancellation, real SDK generated/say
delivery and microphone/privacy races. Full core/media suites and all adapted
browser checks must pass; preserve legacy backend safety coverage as explicit
legacy tests rather than weakening its assertions. Independent Codex-account
review follows the integrated diff; P0/P1 repairs are independently rechecked.
Real-provider synthetic restaurant HTTP/native dialogue is bounded and clearly
not physical microphone or carrier acceptance. Record any provider or acceptance
failure without relabeling it success. Secret/syntax scan, intended-only commit,
safe push and source-verified deployment are required before completion.
