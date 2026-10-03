# Private telephone pilot (2026-10-02)

**Implemented:** continuous LiveKit Agents worker, Estonian/English/Russian Groq/Azure audio,
call-scoped guarded booking tools, private reproducible LiveKit/SIP/Redis,
and exact-number authenticated inbound provisioning.

Automatic Estonian/English/Russian recognition and voice switching, including
localized booking recaps, consent, cancellation and FAQs, are configured through
`VOICEBOT_TELEPHONE_LANGUAGE`, `AZURE_EN_VOICE`/`AZURE_EN_LANG` and
`AZURE_RU_VOICE`/`AZURE_RU_LANG`.
See [English telephone deployment and verification](../../docs/operations/english-telephone.md).
This code change requires rebuilding the separate worker; a web deployment alone
does not update telephone calls. Live English/Russian/PSTN behavior remains unverified.

`VOICEBOT_TELEPHONE_LANGUAGE=auto` uses the existing Estonian opening and English
invitation, then selects a supported caller language from final recognition.
Use `et`, `en` or `ru` to force one language from the initial greeting. Russian
speech defaults to `ru-RU-SvetlanaNeural` and `ru-RU`; English configuration and
cached English failure audio remain supported. Russian has no cached failure
recording: if speech synthesis fails, it uses the Estonian cached apology and
retains that exact Estonian text in assistant session history. Caller-language
metadata still records Russian. Native deployment and verification are covered
in [the deployment handoff](../../docs/operations/voicebot-release-2026-10-03.md).

**First carrier direction:** the user supplied an existing US Twilio number.
Its separately signed HTTPS/WSS Media Streams bridge forwards into this private
native worker, avoiding a public SIP/RTP edge. The exposed authentication
credential is never used and must be rotated before account activation.

**Not verified:** real Twilio/PSTN call, public SIP/RTP edge, human transfer or
real-property release. `robot.arleserver.cfd` can route Twilio HTTPS streams but
is not a SIP/RTP endpoint. DIDWW remains an optional later SIP path.

## Runtime

- Agents/plugins 1.8.4, RTC 1.1.20, API 1.2.1; complete Python 3.12 runtime graph:
  `requirements-telephony.lock.txt`. Docker base/media/Redis are digest-pinned.
- Existing `livekit` Compose project/Redis volume are reused. Explicit
  `voicebot-media-redis` alias avoids a DNS collision with another authenticated
  Redis on the shared Docker network.
- Worker: `python -m app.worker start`, two call processes, process-local dialogue,
  VAD endpointing/interruption, no cloud-inference turn detector, 900-second drain
  budget covering setup, the bounded call and cleanup.
  Caller arrival is bounded to 30 seconds, conversation to 600 seconds afterward.
- Final recognition carries Groq's detected language metadata; unsupported
  languages retain the existing safe clarification behavior. Numeric and
  ambiguous short turns retain the caller's current language. Azure voice
  selection is held for each complete synthesis stream, including all sentence
  chunks, until completion or cancellation. A language change invalidates pending
  recap consent: a fresh complete recap must be delivered before its explicit
  confirmation phrase can authorize a booking.
- Conversation schemas expose catalogue, spa/room search, owned holds, preparation,
  confirmation and cancellation. Compact `plan_demo_booking` also resolves spa
  catalogue/search/hold/preparation without repeated model round trips.
  Model-supplied write keys/customer IDs and foreign call IDs are rejected.
  Retries reuse successes and per-call/action keys. Telephone search requires a
  catalogue-backed provider; the backend returns empty availability without one.
- Same `/data/easy-booking.db` volume as HTTP: never use a per-call journal.
  The fictional room demo also shares `/data/stay-booking.db`; its opt-in follows
  `EASY_DEMO_WRITES` unless `STAY_DEMO_WRITES` explicitly overrides it. Room holds,
  inventory and booking receipts persist; this is not a real hotel PMS.
  Configure the web application's `/data` Persistent Storage explicitly in
  Coolify; Dockerfile `VOLUME` alone is anonymous and changes on redeployment.
  See `COOLIFY.md` and verify both mount names after upgrades.
  Easy remains a controlled single-host sole-writer **synthetic** backend, not
  safe against independent admin/API writers or distributed hosts.
- Complete replies pass a conservative price/currency guard before TTS. Spa
  appointments cannot quote prices; fictional room prices must match an owned
  provider quote exactly. This is not exhaustive semantic validation.
  Preparation does not grant consent: the specific canonical recap must finish
  delivery, then a subsequent affirmative final transcript authorizes the owned
  write. Failed/blocked/interrupted delivery invalidates approval. Success speech
  is guarded by execution/state, including cancelled-receipt replay.
  Only the approved fictional profile/FAQ and owned inventory are exposed;
  spa opening hours come from the provider working plan. Superseded reads cannot
  restore a proposal after a caller changes their mind. Cached English/Estonian
  WAV supplies an independent audible failure message; Russian calls use the
  Estonian cache. No recording/transcript persistence. SDK child logs are
  suppressed because they can contain tool arguments/text.
- Host API `127.0.0.1:7880`, SIP UDP/TCP `127.0.0.1:5060`, worker health
  `127.0.0.1:8081`. RTP 10000–10100 and RTC UDP 7882/TCP 7881 stay on Docker.
  Trusted services on `coolify` can still reach them; this is not isolation
  from a compromised co-tenant.

## Deployment without credential files

`manage.py` reads the existing **trusted** voicebot web container environment
through Docker in memory. It identifies the exact persistent `/data` volume and
passes only required values to Compose. It never renders `.env`, credential YAML
or expanded Compose output. Docker environment inspection remains privileged.

```bash
cd /home/arle/voicebot
python3 deploy/telephony/manage.py validate --source-container "$VOICEBOT_WEB_CONTAINER"
DOCKER_CONFIG=/tmp/opencode/docker-voicebot python3 deploy/telephony/manage.py build --source-container "$VOICEBOT_WEB_CONTAINER"
python3 deploy/telephony/manage.py up --source-container "$VOICEBOT_WEB_CONTAINER"
```

Temporary Docker config avoids this host's root-owned buildx activity file; it
contains no registry login. Config checksums recreate LiveKit when its mounted
config changes. Deploy after jobs finish; the 1000-second worker Docker stop grace
exceeds the SDK drain and both process-cleanup budgets. Old `/home/arle/livekit`
files remain untouched as an operator
rollback reference, not the canonical deployment. Do not automatically alternate
two different manifests against the same project.

The Russian-caller changes have only static syntax/diff checks in the development
session. Rebuild/restart the native worker and verify actual calls before claiming
Russian telephone readiness. Provider references:
[Groq speech recognition](https://console.groq.com/docs/speech-to-text) and
[Azure language support](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/language-support).

## Automatic release synchronization

The signed GitHub `master` webhook deploys the web/API through Coolify first.
On the existing Arle host, `voicebot-release-sync.timer` checks every minute
and reconciles only the native worker and Twilio bridge after the website is
healthy on the published `master` commit. It uses an immutable Git archive,
not the potentially dirty working tree, and tags the shared media image with
that full commit. Both services record `voicebot.release` and
`voicebot.web-source` labels; an already-current run is a no-op.

Language/model/prosody settings come from the trusted web environment using
the release's existing manager. The bridge keeps its own configured account
authentication and number in memory, not a stale copy from another service.
The original web/worker journal volume must match. A running call, different
web/master revision or concurrent container replacement defers the update.
Ambiguous/untrusted sources and storage/configuration mismatches fail closed.
Configuration, build or health failures return nonzero
without printing Docker output or credentials; the next timer run retries.
There is no automatic rollback and no recording, booking or paid carrier probe.

The bridge stops new admission during shutdown and waits for admitted media
handlers instead of cancelling active streams. Its drain is bounded; timeout
is an error, not successful completion. The worker SDK drain covers the full
bounded call lifecycle, including a call admitted during an idle-check race.
The controller verifies the stopped bridge's exit status before replacement;
a concurrent source change resumes only the unchanged old bridge and defers.
Stopped/unhealthy owned targets can recover on a later good release, using a
private count-only probe if the worker is unavailable. No probe starts an agent
job or sends caller audio. Both running services must use the identical image
ID, not merely matching tag strings, before synchronization is successful.
The first upgrade of an older cancellation-based bridge still requires an
observed idle maintenance window; this is not a zero-downtime carrier claim.

The controller uses `up --no-deps --no-build --wait` with an explicit service
target. LiveKit, SIP, Redis, booking containers and their volumes are not
recreated. Infrastructure configuration upgrades still require a planned
operator deployment. A documentation-only `[skip cd]` push waits for the next
ordinary successful web release; unmerged branches never deploy.

Install from a reviewed published release on this host (these commands contain
no credentials):

```bash
sudo install -d -m 755 /usr/local/lib/voicebot-release-sync
sudo install -m 644 deploy/telephony/release_sync.py /usr/local/lib/voicebot-release-sync/release_sync.py
install -d -m 700 /home/arle/.local/share/voicebot-release-sync
sudo install -m 644 deploy/telephony/voicebot-release-sync.service /etc/systemd/system/voicebot-release-sync.service
sudo install -m 644 deploy/telephony/voicebot-release-sync.timer /etc/systemd/system/voicebot-release-sync.timer
sudo systemctl daemon-reload
sudo systemctl enable --now voicebot-release-sync.timer
sudo systemctl start voicebot-release-sync.service
```

Verify the oneshot result and timer, then compare both runtime release labels
and source hashes with the published revision. Health and labels alone do not
prove a real PSTN call or acoustic language quality. To suspend synchronization
for a planned manual operation, stop the timer and wait for the oneshot to
finish; restart the timer afterward. Updating controller code or unit files
requires reinstalling those reviewed files and reloading systemd.

## Synthetic proofs

Install pinned media requirements in isolated Python 3.12. These tests use real
providers/private demo writes and may incur provider usage. Output is metrics
and codes only, not credentials or transcripts.

```bash
python -m pytest tests -q
python deploy/telephony/conversation_probe.py --source-container livekit-worker-1
python deploy/telephony/probe.py --source-container livekit-worker-1 --concurrent
python deploy/telephony/probe.py --source-container livekit-worker-1 --barge-in
python deploy/telephony/failure_probe.py
python deploy/telephony/failure_probe.py --drain
python deploy/telephony/sip_probe.py
docker exec -i livekit-worker-1 python - < deploy/telephony/booking_probe.py
docker exec livekit-worker-1 pip check
```

Room proof checks actual input audio, final STT and nonempty reply audio in two
separate rooms/jobs. SIP proof creates only its own gateway-/32 restricted trunk
and bound individual rule: unauthenticated INVITE is challenged, digest INVITE
answers, negotiated/source-checked RTP decodes voiced audio and greeting content
is independently transcribed. It observes SIP plus agent participants, BYE 200
and room teardown. Wrong-number calls never answer or dispatch (the bridge may
ring silently before timeout rather than return a final 4xx). Own trunk/rule are
deleted afterward. Symmetric
RTP requires the caller to send media before receiving it. Booking proof uses
native SDK tools, independently reads the appointment via REST, rejects foreign
cancellation, cancels the owned appointment and cleans the synthetic customer.

The barge-in probe checks greeting audio stops during spoken input; the failure
probe runs a separate named clone with invalid Azure credentials, confirms the
cached availability apology over RTC, and removes the clone. `--drain` checks
SIGTERM, new-job refusal, exit 0 and active-room termination without stopping the
normal worker. Trunks cap ringing at 30 seconds and calls at 660 seconds; mismatched
existing limits fail closed. Session/adapter/room cleanup waits are bounded and
attempted independently, even after cancellation.

These are **private proofs**, not public NAT, carrier interoperability,
regulatory approval, channel capacity or real-caller operation. `booking_probe.py`
invokes SDK tools directly; `conversation_probe.py` is the distinct real-provider
spoken consent/read/cancel check. Only dated successful command output proves
either one. Never relabel a synthetic room/WSS test as PSTN.

## DIDWW activation gates

1. Obtain an assigned eligible Estonian DID; confirm activation/billing/channels
   in the actual account. No purchase or account changes were made here.
2. Provide a verified public SIP edge: unproxied public address with correct
   router forwarding/firewall and advertised RTP address, or owner-approved
   public SIP relay/VPS. Cloudflare's HTTP proxy/tunnel is not this UDP path.
   Do not turn private Compose into a public wildcard listener.
3. Review a dedicated public deployment against current LiveKit SIP docs. Allow
   only carrier-specific sources/signaling/RTP; advertise the actual reachable
   address. Keep Redis/API/worker health private. Test from outside the LAN.
4. Inject `SIP_NUMBER`, `SIP_ALLOWED_CIDRS`, `SIP_AUTH_USER`, `SIP_AUTH_PASSWORD`
   from protected environment storage plus LiveKit credentials. Run
   `python -m app.sip_setup`. Exact E.164 number, narrow carrier CIDRs and digest
   auth are required. Matching named objects are reused, mismatches/ambiguity
   rejected; unrelated objects are never overwritten. No outbound trunk.
5. DIDWW **Voice → Inbound Trunks → Create New → SIP Trunk**, Static Endpoint:
   public Host, matching Port/transport, R-URI `{DID}`, matching digest auth,
   compatible codec and actual assigned DID. With Preferred Server Auto allow
   all documented DIDWW source ranges. Match received number formatting exactly
   to LiveKit. Never use the fictional probe number.
6. Real inbound call from an independent phone: two-way Estonian audio,
   interruption, booking/read/cancel, hangup, concurrency/overflow and audible
   failure. Record dated evidence before changing readiness. `/api/status.telephone`
   keeps public/carrier verification false; no flag manufactures a carrier proof.

Sources checked 2026-10-02:
- https://docs.livekit.io/transport/self-hosting/sip-server/
- https://docs.livekit.io/telephony/accepting-calls/inbound-trunk/
- https://docs.livekit.io/telephony/accepting-calls/dispatch-rule/
- https://docs.livekit.io/agents/server/startup-modes/
- https://doc.didww.com/voice/inbound-trunks/creating-a-new-sip-trunk.html
