# Private telephone pilot (2026-10-02)

**Implemented:** continuous LiveKit Agents worker, Estonian Groq/Azure audio,
call-scoped guarded booking tools, private reproducible LiveKit/SIP/Redis,
and exact-number authenticated inbound provisioning.

**Not verified:** public carrier edge on this LAN host, purchased DIDWW number,
real PSTN call, human transfer, or real-property release. Buying a number alone
will not make the host publicly reachable. `robot.arleserver.cfd` is the HTTP
website, not a SIP/RTP endpoint.

## Runtime

- Agents/plugins 1.8.4, RTC 1.1.20, API 1.2.1; complete Python 3.12 runtime graph:
  `requirements-telephony.lock.txt`. Docker base/media/Redis are digest-pinned.
- Existing `livekit` Compose project/Redis volume are reused. Explicit
  `voicebot-media-redis` alias avoids a DNS collision with another authenticated
  Redis on the shared Docker network.
- Worker: `python -m app.worker start`, two call processes, process-local dialogue,
  VAD endpointing/interruption, no cloud-inference turn detector, 30-second drain.
  Caller arrival is bounded to 30 seconds, conversation to 600 seconds afterward.
- Native schemas delegate to Dispatcher: catalogue, search, `hold_slot`, confirm,
  cancel. Model-supplied write keys/customer IDs and foreign call IDs are rejected.
  Retries reuse successes and per-call/action keys. Telephone search requires a
  catalogue-backed provider; the backend returns empty availability without one.
- Same `/data/easy-booking.db` volume as HTTP: never use a per-call journal.
  Easy remains a controlled single-host sole-writer **synthetic** backend, not
  safe against independent admin/API writers or distributed hosts.
- Complete replies pass a conservative price/currency denylist before TTS;
  the slot pilot cannot quote prices. This is not exhaustive semantic validation.
  Generic FAQ/property promises
  and hotel stubs are excluded. Cached Estonian WAV supplies an independent
  audible failure message. No recording/transcript persistence. SDK child logs
  are suppressed because they can contain tool arguments/text.
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
config changes. Deploy after jobs finish; the 40-second Docker stop grace exceeds
the worker drain. Old `/home/arle/livekit` files remain untouched as an operator
rollback reference, not the canonical deployment. Do not automatically alternate
two different manifests against the same project.

## Synthetic proofs

Install pinned media requirements in isolated Python 3.12. These tests use real
providers/private demo writes and may incur provider usage. Output is metrics
and codes only, not credentials or transcripts.

```bash
python -m pytest tests -q
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

These are **private proofs**, not public NAT, DIDWW interoperability, regulatory
approval, carrier channel capacity or real-caller operation. The booking probe
invokes SDK tools directly, not a full spoken-consent booking conversation; that
release check remains. Never relabel a synthetic test as PSTN.

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
