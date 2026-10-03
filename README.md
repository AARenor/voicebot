# Restaurant voicebot — Estonian, English and Russian

Restaurant reception is the default business pipeline. The assistant collects a
reservation date, exact local arrival time and total guest count, assigns a
suitable table, reads the canonical recap and waits for explicit consent before
confirmation. Cancellation is limited to the caller's owned reservation.

Approved restaurant knowledge covers the menu, declared allergens, opening and
kitchen hours and policies. Routine replies come from validated venue data.
Unknown prices, allergy safety, accessibility and exceptional requests require
staff verification. This demo cannot transfer real calls, take payments or place
food orders. Restaurant specialization uses approved knowledge and conversation
policy; it does not claim fine-tuned model weights.

**The bundled Meretuule Demo Restaurant and every reservation are fictional.**
Real restaurant information and a verified production booking connector have not
been supplied. ET/EN/RU language detection, Azure speech, optional modern voice
profiles and guarded incremental browser playback are retained. The native
LiveKit telephone worker selects the same restaurant policy and database.

On `robot.arleserver.cfd`, select **English**, **Eesti** or **???????**, connect
with your existing operator token and start **Try the voice assistant**. The
restaurant form also provides an explicit review, read acknowledgement,
confirmation and owned cancellation flow. The token stays in page memory.

See the [restaurant operations guide](docs/operations/restaurants.md),
[restaurant verification report](docs/evidence/2026-10-03-restaurant-pipeline.md)
and [deployment guide](COOLIFY.md). GitHub web deployment and telephone worker
rollout are separate; configuration alone does not verify a carrier call.
The [modern voice guide](docs/operations/modern-voices.md) documents optional
provider configuration, fallback and streaming limits.

`VOICEBOT_BUSINESS_TYPE=restaurant` is the default. The former hotel/spa mode
is retained as an explicit rollback with `VOICEBOT_BUSINESS_TYPE=hotel_spa`.
Historical hotel/spa research and evidence describe that earlier product scope.

## Layout

```
voicebot/
  ARCHITECTURE.md
  requirements.txt (+ requirements-telephony.lock.txt: separate media worker)
  .env.example        # environment-variable names; never store real keys here
  README.md
  app/
    turn.py           # run_turn: hear -> think (+tools) -> book -> speak
    pipeline.py       # routing tables + endpointing budget (descriptors)
    worker.py         # actual continuous LiveKit Agents session, separate image
    telephone.py      # shared ownership, delivered-recap consent and speech guards
    hackathon.py      # bounded memory-only authenticated HTTP conversations
    booking_web.py    # direct website controls using the same owned call tools
    server.py         # FastAPI: dashboard, /api/status, POST /api/turn
    providers/        # Groq (STT+chat), Gemini (failover), Azure TTS
    booking/
      base.py         # StayAdapter / SlotAdapter ABCs + hold ledger types
      tools.py        # LLM tool schemas + Dispatcher + price gate
      apaleo.py       # first paid adapter (stub: wire with PMS creds)
      mews.py         # second (stub)
      cloudbeds.py    # third (stub)
      zenoti.py       # spa parallel (stub)
      qloapps.py      # $0 demo double (stub)
      easyappointments.py  # real spa REST adapter, opt-in demo + durable writes
      demo_stay.py     # finite fictional rooms, durable quotes/holds/bookings
    knowledge/        # SQLite FTS FAQ ingest + retrieve + ET seed
    callslog.py       # SQLite turn/call log (masked peers, 30d retention)
    dashboard/        # protected provider bookings/catalogue + text/microphone UI
    hotel/            # public fictional hotel/spa pitching website
```

## Quickstart

1. `pip install -r requirements.txt`
2. Supply provider/operator credentials through protected environment storage;
   `.env.example` documents names, not a place for real keys. Never paste keys
   into chat, command arguments or committed files.
3. `python -m app.server` (dashboard + HTTP voice-turn demo)
4. Use the separate pinned media environment/deployment for continuous voice;
   regular HTTP dependencies do not include the native audio runtime. Real
   provider calls may incur usage; no carrier purchase is performed here.

## Installed booking demo

Easy!Appointments **1.6.0** runs as a private separate service with persistent
MySQL storage. The existing HTTP dialogue uses `SlotAdapter` → `Dispatcher` →
the documented REST API for catalogue, slots, booking and cancellation.
See [installation and operator runbook](deploy/easyappointments/README.md).
This is synthetic spa data, not hotel room inventory or a real-property release.
Canonical repository: **Parnuhakk/voicebot** (branch `master`).

The room demo stores inventory, expiring exclusive holds and idempotent booking
receipts in `STAY_STATE_DB` (default beside the Easy journal at
`/data/stay-booking.db`). When unset, `STAY_DEMO_WRITES` follows the existing
`EASY_DEMO_WRITES` opt-in; explicit `0` disables it. The web app and telephone
worker must mount the same persistent volume and room database path. No real
hotel PMS connection, payment or notification is implied by demo inventory.

Direct bookings use `/api/booking/session`, `/search`, `/prepare`, `/recap`,
`/confirm` and `/cancel`. The displayed backend recap is acknowledged before
the explicit confirmation button is accepted. Operator authentication applies
to every step and to `/api/rooms` and `/api/stays`. Public `/api/public/property`
and `/api/public/catalogue` contain only property/contact and catalogue DTOs;
they expose no guests or appointment records. `PUBLIC_PHONE_NUMBER` can specify
the demo phone contact; otherwise the configured Twilio/SIP number is used.

## Website architecture

The canonical guest website is [Meretuule](https://meretuule.arleserver.cfd/).
The [operator dashboard](https://robot.arleserver.cfd/) retains booking and
voice-demo workflows. The former public addresses
`https://robot.arleserver.cfd/hotel` and `https://robot.arleserver.cfd/hotel/`
are retired: the public ingress permanently redirects them with HTTP 301 to
`https://meretuule.arleserver.cfd/`, preserving query strings. Direct requests
to the application's robot-host handler return HTTP 410 if the ingress redirect
is not used. Use the Meretuule root in guest-facing links; `/hotel` remains an
internal proxy rewrite target and a local preview route.
See the [Meretuule domain runbook](deploy/meretuule/README.md).

`/api/bookings` and `/api/catalogue` read Easy REST through explicit allowlisted
DTOs. `/api/demo/session` and `/api/turn` share native booking ownership/consent;
the browser selects the actual booking day after a successful write. Operator
credentials, conversation and microphone data are not persisted in the browser.
The old example queue is labelled separately and never used as availability.
`/api/call-history` lists actual browser/telephone session metadata with channel
and attention filters. Session details show recognition activity, provider
failures and owned spa/room booking receipts; booking links open the relevant
day's records. New tables migrate additively inside `CALLS_DB`. Web and worker
must use the same persistent `/data/calls.db` volume. Earlier technical log
rows remain separate because they cannot reconstruct a conversation history.
No audio, raw transcripts or guest contacts are stored in this history. The
existing 30-day technical retention applies; process-loss end times are
estimates from the last recorded activity.
See the [original panel contract](docs/research/website-booking-architecture/DESIGN.md).
The [older interactive diagram](.archify/architecture-website-booking-20261001-213712/website-booking.html)
is a historical source snapshot, not current deployment evidence.

### Dashboard development

The dashboard uses native HTML/CSS/JavaScript, with locally served Figtree fonts
(SIL Open Font License in `app/dashboard/static/fonts/OFL.txt`). No frontend
build step or third-party browser requests are required.

Run the local server on port 8765 and check the browser workflow with:

```powershell
.venv/Scripts/python.exe -m uvicorn app.server:create_app --factory --port 8765
# In a second terminal, from the repository root:
New-Item -ItemType Directory -Force output/playwright
playwright-cli.cmd -s=voicebot-ui open http://127.0.0.1:8765
playwright-cli.cmd -s=voicebot-ui run-code --filename tests/dashboard_browser_checks.js
```

The browser check intercepts API calls with local fictional fixtures; it does
not verify live speech or booking providers. It checks authentication, paging,
empty/stale states, chat, microphone-denial guidance, logout during a pending
read, keyboard navigation, reduced motion, and layouts from 320 to 1440 pixels.
It also checks call filters/details, receipt links, digital silence, actual
browser capture of a synthetic tone and filtered resampling to 16 kHz mono WAV.
Screenshots go to `output/playwright/`. Committed
[desktop](docs/evidence/dashboard-redesign/desktop.png) and
[mobile](docs/evidence/dashboard-redesign/mobile.png) previews use those fixtures.
The latest call-history previews and verification limits are recorded in
[the call-history handoff](docs/evidence/2026-10-03-call-history.md).

## Rules

- ET-first per-language routing; never send ET to non-ET voices.
- Prices only verbatim from live PMS offers (`price_quote_id`), never embeddings.
- No PAN in pipeline (payment links only). No secrets in repo.
