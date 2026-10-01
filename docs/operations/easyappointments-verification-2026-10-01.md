# Easy!Appointments installation verification — 2026-10-01

Scope: synthetic spa demo on the existing Docker/Coolify host; no real guest
data, paid vendor onboarding, public booking domain or telephone worker.

## Verified installation

- Easy!Appointments **1.6.0**, official image digest
  `sha256:ab35b8872d5d3328fa3afb641a89a75f3c6f96f3fb98d6d6d3447fff9d357fa1`.
  Installed `application/config/app.php` reports version `1.6.0`.
- MySQL 8.0 image digest
  `sha256:7dcddc01f13bab2f15cde676d44d01f61fc9f99fe7785e86196dfc07d358ae2b`.
- Compose project `voicebot-booking`; both containers healthy. Admin/UI is
  loopback-only `127.0.0.1:8088`; database has no published host port.
- Persistent database/app volumes; service/provider/API authentication survived
  `docker restart voicebot-booking-booking-db-1 voicebot-booking-easyappointments-1`.
- Official UI installer used an environment-held strong administrator password,
  not the weak CLI default. Settings API activated Bearer auth. Notifications,
  Google/CalDAV sync and external webhooks are disabled.
- Synthetic service **1** (Demo spa consultation, 30 minutes), provider **2**
  (Demo Therapist, Europe/Tallinn), weekdays 09:00–17:00, 12:00–13:00 break.

## Executed checks

| Check | Result |
| --- | --- |
| `.venv/bin/pytest -q` | **135 passed**, 4 opt-in installed tests skipped; one existing Starlette/httpx deprecation warning |
| `EASY_LIVE_TESTS=1` + runtime endpoint/credential, `.venv/bin/pytest -q tests/test_easyappointments_installed.py` | **4 passed**, against installed 1.6.0; test fixtures cleaned up |
| Installed lifecycle | invalid Bearer → 401; malformed appointment rejected without write; customer/create/read/update/delete and slot restoration passed |
| Installed pipeline | real `build_stack` → `Dispatcher` → `run_turn` → catalogue/search/hold/confirm/cancel passed with deterministic LLM/TTS doubles |
| Installed new customer | adapter creates first/last/email/phone from trusted guest fields; full provider-name lookup and cancellation passed |
| Installed contention/recovery | two adapters/holds on one slot → exactly one booking and stale-slot loser; real committed POST + injected response loss → unknown, restart/reconcile → same ID; fresh interpreter replay passed |
| Independent review | initial journal/customer-write findings fixed; narrow final customer-durability/hygiene re-review **PASS bounded demo**, safety suite **31 passed** |
| `docker --config /tmp/opencode/voicebot-docker build -t voicebot:easyappointments-integration .` | passed; separate Docker config avoids existing buildx activity permissions without changing them |
| Built non-root container, Coolify network | uid 10001 creates `/data` journal; real private catalogue read and all five slot tools verified |
| Compose parse in clean environment | rejects missing credentials; passes with explicitly supplied runtime values; no resolved config printed |
| `php -l /var/www/html/config.php` | passed; missing/empty required runtime environment fails rather than using image defaults |
| `.env.local`, `.env.production`, SQLite ignore rules | `git check-ignore` passed; protected credential store mode **600** |
| Intended-file / link / secret gate | 23 intended staged files, 21 local links, credential-pattern scan and staged whitespace check passed; `.opencode/` excluded |

## Deployed end-to-end proof

Code commit **`9a8d1d2`** was pushed to **Parnuhakk/voicebot** and deployed by
Coolify application 13, deployment `hmtaktfbf8tcargom8f3ro0x` (**finished**).
The running non-root container reports that source commit, the explicit demo
opt-in and `/data/easy-booking.db`; it reads the real private catalogue and
advertises all five slot tools. `/health` and `/api/status` return 200;
unauthenticated `/api/turn` returns 403.

An authenticated synthetic Estonian **text** request to the deployed
`POST /api/turn`, using the configured real **Groq LLM and Azure TTS**, returned:

```text
HTTP 200
tools_used: 3
fallback_used: false
tts_failed: false
audio_present: true
```

Independent Easy API readback found exactly one newly created appointment
(reference **21**), with service 1, provider 2 and synthetic customer 3. The
verification then deleted only that test appointment. This proves deployed
search → hold → confirm and nonempty synthesized audio. It does not test
microphone/STT audio, SIP/carrier transport or real guest traffic.

## Failure behavior

Appointment writes have durable pending state before POST. An uncertain outcome
blocks fresh keys too; only one valid exact marker match can resolve it. Customer
creates have a separate durable pending stage before POST: cancellation/process
death/timeout/malformed successful responses never cause blind same/fresh-key
customer retries. Uncertain customer creation requires operator recovery.
Known terminal errors are stored as closed, body-free results; raw guest fields
and malformed backend echoes are not persisted in the write journal.

The real API's PUT preserves the original end datetime: rescheduling checks send
both start and end. No rescheduling tool was added to SlotAdapter.

## Release limits

This verifies the controlled single-host writer, not atomic upstream exclusion
against independent admin/UI/API writers. The original privacy/caller ownership,
multi-host state and telephone/SIP gates remain open. Automated booking tests
use LLM/TTS doubles; the separate deployed smoke above also verifies one real
LLM/TTS text-turn execution, not sustained capacity or carrier behavior.

Operational entry point: [booking runbook](../../deploy/easyappointments/README.md).
Canonical repository and Coolify source: **Parnuhakk/voicebot**, branch `master`.
