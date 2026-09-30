# Voicebot (ET hotel/spa, LiveKit SIP + Agents target)

Slow high-quality build. See ARCHITECTURE.md (v1.0) for the truth-first plan.

## Layout

```
voicebot/
  ARCHITECTURE.md
  requirements.txt (+ requirements-phase2.txt: legacy candidates to repin)
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
3. `python -m app.server` (dashboard + HTTP voice-turn demo)
4. Telephone phase: approved Estonian DID/trunk -> self-hosted LiveKit SIP ->
   individual room dispatch -> LiveKit Agents worker.

## Rules

- ET-first per-language routing; never send ET to non-ET voices.
- Prices only verbatim from live PMS offers (`price_quote_id`), never embeddings.
- No PAN in pipeline (payment links only). No secrets in repo.
