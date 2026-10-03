# Private Easy!Appointments booking service

## Architecture

```text
operator-authenticated POST /api/turn
  → run_turn (bounded four tool rounds)
  → Dispatcher / SlotAdapter
  → EasyAppointmentsAdapter
      ├─ /data/easy-booking.db + file lock (voicebot data volume)
      └─ documented /index.php/api/v1/*
           → voicebot-easyappointments:80 (Coolify network)
           → booking-db:3306 (internal network / persistent volume)
```

The canonical app repository is **Parnuhakk/voicebot**, branch `master`.
The separate Compose project is `voicebot-booking`; images are pinned by
digest to the verified Easy!Appointments **1.6.0** and MySQL 8.0 artifacts.
No database host port is published. Admin/API access from the host is
`http://127.0.0.1:8088`; no public booking/admin domain was added.

## Install / recreate

1. Use Docker Compose on the Coolify host. The `coolify` external network must
   already exist (use a separate reviewed override for another host).
2. Supply strong `EASY_DB_PASSWORD`, `EASY_DB_ROOT_PASSWORD`,
   `EASY_ADMIN_PASSWORD` and `EASY_API_KEY` through the environment. On this
   host their authoritative protected store is
   `~/.config/opencode/api-keys.env` (mode 600). Never export them into repo
   files, URLs, logs or terminal output.
3. Start from the repository root:

   ```bash
   source ~/.config/opencode/api-keys.env
   docker compose -f deploy/easyappointments/compose.yml config --quiet
   docker compose -f deploy/easyappointments/compose.yml up -d
   docker compose -f deploy/easyappointments/compose.yml ps
   ```

   Do **not** run plain `compose config`: it resolves and prints credentials.
   The custom `config.php` reads runtime environment values rather than letting
   the official image entrypoint write database credentials into a PHP file.
4. For a new empty database only, complete the official installer in the UI.
   Use username `voicebot-admin` and the environment-held strong admin password,
   not the CLI's default seeded administrator credentials. Do not reinstall or
   run `console install`/`migrate fresh` against an existing volume.
5. Configure Settings → API credential from `EASY_API_KEY`. The supported API
   also allows `PUT /settings/api_token` with admin Basic Authentication.
   Never print the response: it contains the credential.
6. Configure the synthetic dataset listed below. Disable customer, provider and
   admin notifications; leave Google/CalDAV sync and webhooks disabled.
7. Run the opt-in installed tests below before allowing demo writes.

For remote operator access, tunnel your chosen SSH host:

```bash
ssh -N -L 8088:127.0.0.1:8088 <your-configured-ssh-host>
```

Then open `http://localhost:8088`. The instance `BASE_URL` uses this same URL.
Retrieve the admin password locally through the protected store/password
workflow; it is deliberately absent from this document. Keep admin access
restricted to inspection/configuration: competing UI/API bookings violate the
demo's sole-writer assumption.

## Existing synthetic dataset (spa)

- Company: **Voicebot Synthetic Spa Demo**.
- Service: **Demo spa consultation**, 30 minutes, 30-minute slots, one attendant.
  ID **1** in this installation, not a universal upstream default.
- Provider: **Demo Therapist**, ID **2**, compatible with service 1;
  timezone **Europe/Tallinn**.
- Monday–Friday **09:00–17:00**, break **12:00–13:00**; weekends closed.
- Notification destinations use `example.invalid`; notifications and external
  sync are disabled. No real guests or property policies were imported.
- New customer payloads use `firstName`, `lastName`, `email`, `phone` or an
  existing positive `customerId`. Let the catalogue supply service/provider IDs.
- The provider's configured price is not a voice quote. Slot snapshots have no
  `price_quote_id`; do not speak treatment prices from this demo.

The website and telephone assistant now represent the fictional Meretuule Köök
restaurant. This existing spa catalogue is **not** a restaurant table backend.
Restaurant sessions deliberately expose no slot, stay, or booking tools, even
when legacy `EASY_DEMO_WRITES=1` is enabled. Do not use the spa service or
therapist as a restaurant reservation. Restaurant bookings require a separately
configured and reviewed synthetic dataset before restaurant tools can be
enabled.

## Voicebot runtime settings

```text
EASY_BASE_URL=http://voicebot-easyappointments
EASY_API_KEY=<runtime environment only>
EASY_DEMO_WRITES=1
EASY_STATE_DB=/data/easy-booking.db
```

These values belong in Coolify's **runtime-only** environment. The journal must
be on the existing persistent `/data` volume. Keep exactly one voicebot replica.
Missing credentials, a non-writable journal, or `EASY_DEMO_WRITES` other than `1`
leave the slot adapter unwired and its tools unadvertised. This gate is a
controlled-demo opt-in, not a property/production readiness certificate.

Available tools: `get_slot_catalogue`, `search_slots`, `hold_slot`,
`confirm_slot_booking`, `cancel_slot_booking`. A hold is only a local short-lived
snapshot, **not** a remote inventory reservation. Availability is checked again
inside a single-host write lock before confirmation.

Upstream 1.6.0's appointment REST POST does not reject overlap. The journal and
lock protect this voicebot's controlled writer, not independent UI/integration
writes or another host with a different journal. Unknown appointment writes
remain durable and fail closed; never erase the journal to retry. Reconcile
the marker through provider reads; do not blindly repeat POST with a new key.
An unresolved write blocks **all new confirmations**, including fresh keys.
Customer creation has a separate durable pending stage: uncertainty there cannot
be resolved by an appointment marker. Stop demo writes and reconcile the
authoritative customer record with an operator before any reviewed journal
recovery; do not delete pending state or retry customer POST under a fresh key.
Minimal customer/booking IDs are stored for restart recovery, not names,
contact details, notes, backend error bodies or raw guest payloads.
Use the operator-authenticated HTTP demo with synthetic input only: public
call-log privacy, caller ownership and the telephone worker remain release gates.

## Verification

```bash
source ~/.config/opencode/api-keys.env
export EASY_BASE_URL=http://127.0.0.1:8088
export EASY_LIVE_TESTS=1
.venv/bin/pytest -q tests/test_easyappointments_installed.py
```

Tests create and clean up only their own synthetic customers/appointments:
unauthorized request, malformed appointment, live catalogue/availability,
customer/appointment create/read/update/delete, full factory/Dispatcher/dialogue
tool chain, same-slot contention, and committed POST followed by a simulated
lost response and adapter restart. The last test uses the real backend and
injects the timeout only after the actual 201 response.
Another installed check verifies new-customer creation through the adapter,
including display-name mapping and full provider-name lookup. Unit regressions
cover cancellation during a committed customer write, malformed customer IDs,
same-key concurrent waiters and fresh-key attempts while a write is unresolved.

For update/reschedule through the REST API, supply **both `start` and `end`**:
1.6.0 PUT preserves the original end if only start changes. Update is an API
smoke check, not an added SlotAdapter tool. LLM/TTS doubles keep this booking
proof deterministic; it is not a paid-provider speech or carrier/SIP proof.

## Operations and durability

- `restart: unless-stopped` handles host/container restarts; both services have
  health checks. Database and app storage have named volumes.
- Back up the MySQL booking data **and** voicebot `/data/easy-booking.db` plus
  associated journal files as one operational unit, using the protected backup
  path and encryption policy. Do not run `down -v` or delete either volume.
- PHP source/config is pinned/read-only where supplied; state is on volumes.
  Updating an image requires a reviewed digest, backup, migrations and the
  installed contract tests; never replace a tag with `latest`.
- To disable booking without deleting data, set `EASY_DEMO_WRITES=0` in Coolify
  and redeploy the voicebot. Keep the backend and journal for reconciliation.
- See [design](../../docs/superpowers/specs/2026-10-01-easyappointments-integration-design.md)
  and [architecture release gates](../../ARCHITECTURE.md).
