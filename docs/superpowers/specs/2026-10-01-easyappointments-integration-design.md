# Easy!Appointments integration design

## Scope

Install pinned Easy!Appointments 1.6.0 on the existing Docker host with a
persistent MySQL database and synthetic spa services/providers. Connect the
existing HTTP voice-turn pipeline through SlotAdapter and Dispatcher. Do not
implement the absent telephone worker or claim public caller readiness.

## Approach

Use a separate Compose stack rather than embedding PHP in the Python app.
Keep database off host ports and booking UI/API bound to loopback. Connect the
booking web service to the existing Coolify network for voicebot access. Keep
all generated credentials solely in protected runtime environment storage.
Expose the operator UI only through an authenticated access path or SSH tunnel.

Reuse SlotAdapter and its existing search/hold/confirm/cancel workflow. Add a
read-only service/provider catalogue so the model need not invent numeric IDs.
Keep StayAdapter unchanged; room-night booking is out of scope.

## Safety and persistence

Upstream 1.6.0 REST appointment creation does not reject overlaps. This demo
therefore requires voicebot to be the sole booking writer. Coordinate writes
through persistent SQLite state on the existing data volume, serialize the
availability-check/create sequence, and return a typed conflict for a stale
slot. Do not advertise booking tools by credentials alone: explicit demo-write
opt-in and a persistent journal are required.

Write a durable pending outcome before appointment POST with a deterministic opaque marker
in appointment notes. Reconcile unknown outcomes through the documented read
API before any retry. An unresolved write must stay fail-closed even after a
process restart; no automatic repeated POST. Only a uniquely matched provider
record may turn an uncertain write into success. Do not persist raw guest data
in the coordination journal (only opaque request IDs and minimal customer/booking
record IDs). Customer creation also has durable pending state before POST; an
uncertain customer write blocks new confirmations pending operator recovery,
including new-key retries. Customer creation failures and malformed responses
must fail closed. Cancellation is idempotent, after booking reference validation.

Synthetic provider schedules are Europe/Tallinn working hours; notification,
calendar sync and external outbound webhooks stay disabled. Real property
traffic remains blocked by existing privacy, ownership and telephony gates.

## Verification

- Automated test-first regression for readiness gate, catalogue/ID handling,
  required fields, stale slots, concurrency and ambiguous-write recovery.
- Real installed API: read catalogue/availability; create, read, update and
  cancel synthetic appointment; invalid auth and unavailable slot.
- Existing Dispatcher and run_turn: use real booking adapter with deterministic
  model/TTS doubles for a repeatable booking tool-chain; separately verify
  deployed configured pipeline and provider networking.
- Full repository tests, Compose parse, journal persistence/restart evidence,
  redacted secret scan, independent review; commit and push intended files.

## Non-goals and limits

No room PMS, no paid vendor onboarding, no public admin/default credentials,
no general-purpose booking framework. SQLite coordination protects this
voicebot's writer on one host, not independent writes through Easy!Appointments
UI, integrations or another host. Production requires provider-enforced
inventory exclusion or a controlled universal writer, caller ownership,
approved content and privacy controls.
