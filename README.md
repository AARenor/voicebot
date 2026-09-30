# Voicebot (ET hotel/spa, Pipecat + LiveKit SIP)

Slow high-quality build. See ARCHITECTURE.md (v0.3) for the full plan.

## Layout

```
voicebot/
  ARCHITECTURE.md
  requirements.txt (+ requirements-phase2.txt for Pipecat/media ML)
  .env.example        # copy to .env, never commit .env
  README.md
  app/
    turn.py           # run_turn: hear -> think (+tools) -> book -> speak
    pipeline.py       # routing tables + endpointing budget (descriptors)
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
      easyappointments.py  # $0 demo double (REAL REST: avail/appts)
    knowledge/        # SQLite FTS FAQ ingest + retrieve + ET seed
    callslog.py       # SQLite turn/call log (masked peers, 30d retention)
    dashboard/        # staff holds queue (live API) + static UI
```

## Quickstart (Phase 1, $0)

1. `pip install -r requirements.txt`
2. `cp .env.example .env` (+ fill GROQ_API_KEY)
3. `python -m app.server` (browser WebSocket demo)
4. Phase 2: 1 DIDHub EE DID ($2.50) -> LiveKit SIP eu-inbound.

## Rules

- ET-first per-language routing; never send ET to non-ET voices.
- Prices only verbatim from live PMS offers (`price_quote_id`), never embeddings.
- No PAN in pipeline (payment links only). No secrets in repo.
