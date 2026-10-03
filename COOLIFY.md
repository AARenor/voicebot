# Deploy to Coolify → robot.arleserver.cfd

Dashboard + API in one container. Coolify terminates TLS and proxies to
port 8000. No secrets are baked into the image (see `.dockerignore`).

## 0. Prereqs

- Canonical repository: `Parnuhakk/voicebot`, branch `master`.
  Coolify's repository source must use the organization, not the former personal repo.
- DNS `robot.arleserver.cfd` → your Coolify server IP (A record).
- Coolify server with a configured wildcard or per-domain TLS (Let's Encrypt).

## 1. Create the service

1. Coolify → New Resource → **Dockerfile** (public/private repo, branch).
2. Build context / Dockerfile location: repo root if you push `voicebot/`
   as the repo root; otherwise set base directory to `voicebot/`.
3. Port: **8000**. Health check path: **/health**.
4. Domains → add `https://robot.arleserver.cfd` (TLS on, force HTTPS on).

The separate public Meretuule website uses `https://meretuule.arleserver.cfd/`
through the [host-specific dynamic proxy route](deploy/meretuule/README.md).
This is the canonical guest address. `https://robot.arleserver.cfd/` remains
the operator dashboard and the destination for booking and voice-demo links.
The former guest paths `https://robot.arleserver.cfd/hotel` and
`https://robot.arleserver.cfd/hotel/` permanently redirect at public ingress
with HTTP 301 to `https://meretuule.arleserver.cfd/`, preserving query strings.
The application's robot-host handler returns HTTP 410 when that redirect is
not used. `/hotel` remains the internal proxy rewrite target and local preview
route.

## 2. Environment (Coolify → Environment Variables)

Minimum (demo runs without providers):
```
PORT=8000
VOICEBOT_BUSINESS=restaurant
RESTAURANT_STATE_DB=/data/restaurant-booking.db
OPERATOR_TOKEN=<long random string>   # required to confirm/cancel holds
```
Later (live voice — mirrors `.env.example` exactly):
```
GROQ_API_KEY=...
GEMINI_API_KEY=...
LIVEKIT_URL=...  LIVEKIT_API_KEY=...  LIVEKIT_API_SECRET=...  # all three required for configured media status
SIP_TRUNK_ADDRESS=...  SIP_AUTH_USERNAME=...  SIP_AUTH_PASSWORD=...  SIP_INBOUND_NUMBER=...
AZURE_SPEECH_KEY=...  AZURE_REGION=...  AZURE_VOICE=et-EE-AnuNeural  AZURE_LANG=et-EE
LANGFUSE_PUBLIC_KEY=...  LANGFUSE_SECRET_KEY=...  OTEL_EXPORTER_OTLP_ENDPOINT=...
CALLS_DB=/data/calls.db
VOICEBOT_PROD=1
```
Never commit these — Coolify env only (mirrors `.env.example`).

Restaurant mode does not depend on or activate the archived hotel/spa credentials.
Keep existing booking databases/services intact during the pivot. Their
[historical runbook](deploy/easyappointments/README.md) is not an active restaurant
connector or authorization for real customer traffic.

Single-process assumption: in-memory search/hold snapshots + demo STORE diverge if
replicas scale past 1 — keep Coolify replicas at exactly 1.

Scale continuous-call **agent workers** separately from this web/API container.
The fictional table ledger uses `RESTAURANT_STATE_DB=/data/restaurant-booking.db`
on this same volume. The native worker uses the identical restaurant database
path. Existing room/spa receipts and history survive unchanged alongside the new
ledger; never initialize a different worker volume for this feature. Public restaurant
pitching content is served at `https://meretuule.arleserver.cfd/`, using the
internal `/hotel` handler; its contact number comes from
`PUBLIC_PHONE_NUMBER`, or the configured Twilio/SIP number. The public DTOs
contain catalogue/property information, and all booking writes retain operator
authentication and call-owned confirmation rules.
The restaurant SQLite transactions coordinate table holds across web/native
processes on this shared single-host volume. HTTP sessions still live in one
web process; database persistence does not distribute their consent ownership.

**Required:** configure `/data` explicitly under application **Persistent Storage**.
Dockerfile `VOLUME ["/data"]` alone creates an anonymous volume per replacement
container; it does not provide redeployment durability. If data already exists,
reference its exact existing Docker volume name rather than initializing a new
one. The telephone worker must reference the same volume. Verify both mount names
and journal row counts after deployment; never silently move either process to a
new empty journal. This private pilot preserves the original volume; unused
anonymous volumes were not deleted.

Do not increase web replicas until holds use Redis and logs use
Postgres or a single-writer service. See
[`docs/operations/concurrency-and-capacity.md`](docs/operations/concurrency-and-capacity.md).

## 3. Automatic deployment from GitHub

The existing production application deploys pushes and merges to `master` in
`Parnuhakk/voicebot` through a signed GitHub repository webhook. It uses the
public-repository source; no GitHub App installation or Actions workflow is needed.

- Coolify: keep repository `Parnuhakk/voicebot`, branch `master`, **Auto Deploy**
  enabled, preview deployments disabled, and watch paths empty.
- GitHub → repository **Settings → Webhooks**: active hook **691219586**, event
  **push** only, content type **application/json**, SSL verification enabled.
  Callback: `https://coolify.arleserver.cfd/webhooks/source/github/events/manual`.
- Reuse the application's existing GitHub signing value from Coolify's
  **Webhooks** settings when repairing the hook. Never commit or log that value.
  The receiver verifies `X-Hub-Signature-256` against the raw request body.
- GitHub sends pushes for all branches; Coolify matches the repository and
  configured branch. Other branches and unmerged pull requests do not deploy
  production. Deployment is skipped when every nonempty commit message in the
  push contains `[skip ci]` or `[skip cd]`.

To verify a deployment, push a normal change to `master`, then inspect the hook's
**Recent Deliveries** and the application's **Deployments**. Require a push for
`refs/heads/master`, a queued deployment for its commit, and a finished deployment
running that revision. A successful creation ping is not deployment proof;
HTTP 200 alone is also insufficient because rejected signatures return a failed
result with HTTP 200. After deployment, verify health plus the existing `/data`
mount and journal counts (see Persistent Storage requirements above).
The hook deploys the web/API application. On the existing Arle host,
`voicebot-release-sync.timer` then synchronizes the native worker and Twilio
bridge to the same healthy published `master` revision. It checks every minute,
waits while voice rooms are active, preserves the shared journal and existing
bridge credentials, and never restarts the booking or media infrastructure.
See the [telephone release pipeline](deploy/telephony/README.md#automatic-release-synchronization).
Only pushed/merged `master` changes deploy; uncommitted work and other branches
remain outside production. A `[skip cd]` documentation push does not create a
new web release, so synchronization waits for the next ordinary deployment.

## 4. Verify

- `https://robot.arleserver.cfd/health` → `{"ok": true}`
- `https://robot.arleserver.cfd/` → disclosed fictional operator dashboard
   (restaurant ledger, catalogue, text/microphone demo and technical calls).
- `https://meretuule.arleserver.cfd/` → public fictional restaurant website;
  its homepage links use this exact canonical root.
- Public robot `/hotel` and `/hotel/` → HTTP 301 with the exact canonical
  Meretuule root in `Location` (query strings preserved). A direct app request
  using the robot hostname → HTTP 410 with no `Location` header.
- Confirm/cancel without or with a wrong client token → 403. 503 means
  the server itself has no `OPERATOR_TOKEN` configured — check Coolify env.
- `/api/tables` and `/api/table-bookings` require operator authentication and
  return `Cache-Control: no-store`. Availability, delivered recap, later consent,
  independent readback and owned cancellation must all pass; a healthy container
  does not verify them. Preserve the signed incoming telephone routes unchanged.

## 5. Local mirror (same as Coolify builds)

```
cd voicebot
docker build -t voicebot:local .
docker run --rm -p 8000:8000 -e OPERATOR_TOKEN=demo-token voicebot:local
```

## Notes

- The [natural conversation profile](docs/operations/natural-conversation.md)
  shares voice pacing and pronunciation across HTTP/native speech. Browser
  replies use high-fidelity 48 kHz / 96 kbit/s MP3; native PCM remains 24 kHz.
- Optional [modern website voice profiles](docs/operations/modern-voices.md)
  use server-only provider credentials and a locked session selector. Azure
  remains the default/fallback. Incremental MP3 playback improves buffering on
  supported browsers; Google REST stays explicitly buffered. An available
  configuration does not prove live audio quality or telephone activation.
- Mutations, demo sessions, `/api/turn`, `/api/calls`, `/api/bookings` and
  `/api/catalogue` require operator authorization; responses/errors are `no-store`.
  The operator token exists only in page memory; logout clears private content,
  audio/microphone and late in-flight replies. No browser-to-provider credentials.
- The container runs as non-root `voicebot` (uid 10001).
- The separate [private telephone deployment](deploy/telephony/README.md) uses
  LiveKit/SIP/Redis and shares the existing booking volume. Public SIP ingress
  cannot be supplied by this HTTP proxy. The first US Twilio carrier path instead
  uses a separately deployed signed HTTPS/WSS bridge on `/api/twilio/`, forwarding
  to private LiveKit. Do not fold its media runtime into this HTTP image. Fresh
  rotated credentials and a real incoming call remain activation gates.
  Postgres/Langfuse remain target components, not deployed claims.
