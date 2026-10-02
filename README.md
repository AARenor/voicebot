# Voicebot — fictional Estonian spa hackathon demo

LiveKit Agents, Groq STT/LLM, Azure Anu speech and private Easy!Appointments
**1.6.0**. The dashboard reads actual provider bookings and offers a protected
text/microphone demo. Only fictional guests and approved fictional FAQ data.
Spoken writes require an owned slot, a delivered recap and subsequent explicit
consent. Model prose is not booking evidence.

Start with [the hackathon playbook](HACKATHON.md) and [architecture](ARCHITECTURE.md).
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
    knowledge/        # SQLite FTS FAQ ingest + retrieve + ET seed
    callslog.py       # SQLite turn/call log (masked peers, 30d retention)
    dashboard/        # protected provider bookings/catalogue + text/microphone UI
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

## Website architecture

`/api/bookings` and `/api/catalogue` read Easy REST through explicit allowlisted
DTOs. `/api/demo/session` and `/api/turn` share native booking ownership/consent;
the browser selects the actual booking day after a successful write. Operator
credentials, conversation and microphone data are not persisted in the browser.
The old example queue is labelled separately and never used as availability.
See the [original panel contract](docs/research/website-booking-architecture/DESIGN.md).
The [older interactive diagram](.archify/architecture-website-booking-20261001-213712/website-booking.html)
is a historical source snapshot, not current deployment evidence.

## Rules

- ET-first per-language routing; never send ET to non-ET voices.
- Prices only verbatim from live PMS offers (`price_quote_id`), never embeddings.
- No PAN in pipeline (payment links only). No secrets in repo.
