# Voicebot (ET hotel/spa, Pipecat + LiveKit SIP)

Slow high-quality build. See ARCHITECTURE.md (v0.2) for the full plan.

## Layout

```
voicebot/
  ARCHITECTURE.md
  requirements.txt
  .env.example        # copy to .env, never commit .env
  README.md
  app/
    pipeline.py       # VAD -> STT -> LLM tools -> TTS, per-language routing
    server.py         # browser WebSocket now, SIP webhook later
    booking/
      base.py         # StayAdapter / SlotAdapter ABCs + hold ledger types
      apaleo.py       # first paid adapter (stub)
      mews.py         # second (stub)
      cloudbeds.py    # third (stub)
      zenoti.py       # spa parallel (stub)
      qloapps.py      # $0 demo double (stub)
      easyappointments.py  # $0 demo double (stub)
    knowledge/        # FAQ ingest + retrieve (stub)
    dashboard/        # staff holds queue (stub)
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
