# Voicebot — fictional Estonian hotel and spa demo

LiveKit Agents, Groq STT/LLM, Azure Anu speech and private Easy!Appointments
**1.6.0**. The dashboard reads actual provider bookings and offers a protected
text/microphone demo, direct spa and room booking, and a public hotel pitch at
`/hotel`. Room inventory is a finite, persistent fictional PMS; Easy!Appointments
continues to supply spa services, working plans and appointment availability.
Only fictional guests and approved fictional FAQ data.
Spoken writes require an owned hold, a delivered recap and subsequent explicit
consent. Model prose is not booking evidence.

Both voice transports use configurable Groq `openai/gpt-oss-120b` and
`whisper-large-v3` with Estonian transcription, plus Azure Anu speech. See
`GROQ_CHAT_MODEL`, `GROQ_STT_MODEL` and `GROQ_MAX_COMPLETION_TOKENS` in
`.env.example`. Configuration is reported by `/api/status`; it is not evidence
of an actual successful carrier call. HTTP turns return per-stage timings and
closed warning codes, and the native worker logs bounded latency summaries.

Start with [the hackathon playbook](HACKATHON.md) and [architecture](ARCHITECTURE.md).
The [adversarial bug ledger](docs/evidence/2026-10-02-adversarial-bug-hunt.md)
records the earlier defects and live speech failures. The
[2026-10-03 update](docs/evidence/2026-10-03-voice-and-booking-update.md)
records the repaired SDK fallback, room/website changes and current verification gaps.
**This fictional pilot is not production-approved.**
The first carrier target is the supplied **US Twilio number** over signed HTTPS
Media Streams, avoiding the missing public SIP/RTP edge. Fresh rotated credentials,
number webhook activation and a real incoming phone call remain separate gates.
The alternative [private SIP deployment](deploy/telephony/README.md) is retained.
See [Twilio environment/deployment and activation](TWILIO.md); no public SIP/RTP
route is required for that path.

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

`/api/bookings` and `/api/catalogue` read Easy REST through explicit allowlisted
DTOs. `/api/demo/session` and `/api/turn` share native booking ownership/consent;
the browser selects the actual booking day after a successful write. Operator
credentials, conversation and microphone data are not persisted in the browser.
The old example queue is labelled separately and never used as availability.
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
Screenshots go to `output/playwright/`. Committed
[desktop](docs/evidence/dashboard-redesign/desktop.png) and
[mobile](docs/evidence/dashboard-redesign/mobile.png) previews use those fixtures.

## Rules

- ET-first per-language routing; never send ET to non-ET voices.
- Prices only verbatim from live PMS offers (`price_quote_id`), never embeddings.
- No PAN in pipeline (payment links only). No secrets in repo.
