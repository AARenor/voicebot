# Deploy to Coolify → robot.arleserver.cfd

Dashboard + API in one container. Coolify terminates TLS and proxies to
port 8000. No secrets are baked into the image (see `.dockerignore`).

## 0. Prereqs

- This folder (`voicebot/`) pushed to a git repo Coolify can read.
  If not a repo yet: `git init && git add . && git commit -m ...` + push.
- DNS `robot.arleserver.cfd` → your Coolify server IP (A record).
- Coolify server with a configured wildcard or per-domain TLS (Let's Encrypt).

## 1. Create the service

1. Coolify → New Resource → **Dockerfile** (public/private repo, branch).
2. Build context / Dockerfile location: repo root if you push `voicebot/`
   as the repo root; otherwise set base directory to `voicebot/`.
3. Port: **8000**. Health check path: **/health**.
4. Domains → add `https://robot.arleserver.cfd` (TLS on, force HTTPS on).

## 2. Environment (Coolify → Environment Variables)

Minimum (demo runs without providers):
```
PORT=8000
OPERATOR_TOKEN=<long random string>   # required to confirm/cancel holds
```
Later (live voice — mirrors `.env.example` exactly):
```
GROQ_API_KEY=...
GEMINI_API_KEY=...
LIVEKIT_URL=...  LIVEKIT_API_KEY=...  LIVEKIT_API_SECRET=...  # secret reserved; current web app does not read it (R-006)
SIP_TRUNK_ADDRESS=...  SIP_AUTH_USERNAME=...  SIP_AUTH_PASSWORD=...  SIP_INBOUND_NUMBER=...
APALEO_CLIENT_ID=...  APALEO_CLIENT_SECRET=...
MEWS_CLIENT_TOKEN=...  MEWS_ACCESS_TOKEN=...  MEWS_CLIENT=...  MEWS_API_BASE_URL=...
CLOUDBEDS_API_KEY=...  ZENOTI_API_KEY=...
EASY_BASE_URL=...  EASY_API_KEY=...
AZURE_SPEECH_KEY=...  AZURE_REGION=...  AZURE_VOICE=et-EE-AnuNeural  AZURE_LANG=et-EE
LANGFUSE_PUBLIC_KEY=...  LANGFUSE_SECRET_KEY=...  OTEL_EXPORTER_OTLP_ENDPOINT=...
CALLS_DB=/data/calls.db
VOICEBOT_PROD=1
```
Never commit these — Coolify env only (mirrors `.env.example`).

Single-process assumption: in-memory HoldLedger + demo STORE diverge if
replicas scale past 1 — keep Coolify replicas at exactly 1.

Scale continuous-call **agent workers** separately from this web/API container.
Do not increase web replicas until holds/idempotency use Redis and logs use
Postgres or a single-writer service. See
[`docs/operations/concurrency-and-capacity.md`](docs/operations/concurrency-and-capacity.md).

## 3. Verify

- `https://robot.arleserver.cfd/health` → `{"ok": true}`
- `https://robot.arleserver.cfd/` → dashboard (holds table, calls, metrics).
- Confirm/cancel without or with a wrong client token → 403. 503 means
  the server itself has no `OPERATOR_TOKEN` configured — check Coolify env.

## 4. Local mirror (same as Coolify builds)

```
cd voicebot
docker build -t voicebot:local .
docker run --rm -p 8000:8000 -e OPERATOR_TOKEN=demo-token voicebot:local
```

## Notes

- Mutating API (`confirm`/`cancel`/`reset`) needs `Authorization: Bearer
  $OPERATOR_TOKEN`. Reads are open demo data.
- The container runs as non-root `voicebot` (uid 10001).
- Redis/Postgres/Langfuse are Phase 2 (compose will grow then).
