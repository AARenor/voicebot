# Twilio carrier bridge

## Design and scope

This is a separate, single-process aiohttp server, not a second agent loop.
Inbound Twilio Media Streams are translated to a microphone participant in a
private LiveKit room. The existing `voicebot` agent handles speech, tool safety,
fictional guests, approval, and booking ownership unchanged. No Twilio account
API calls, outbound calls, number purchases, recordings, caller details, or
transcripts are added.

The alternatives are direct SIP (requires a carrier-reachable SIP edge) and a
new carrier-specific agent (duplicates safety and providers). This bridge uses
the existing HTTPS edge and native worker instead.

### Trust boundaries

1. `POST /api/twilio/voice` verifies `X-Twilio-Signature` with the fixed public
   HTTPS URL and every bounded, untrimmed form parameter. It requires the
   configured AccountSid, exact assigned E.164 To number, and a valid CallSid.
2. A valid webhook issues a random binding, held only in memory for 30 seconds.
   Pending retries for the same call reuse the binding. At most 16 are pending.
3. `/api/twilio/media` verifies the signature before accepting the socket. Its
   connected/start handshake must match the account, call, binding, stream ID,
   and mono 8 kHz mu-law format. Bindings are consumed once; active and recently
   used calls cannot be authorized again. At most two calls reach LiveKit.
4. Each call owns an opaque UUID room and participant. No phone number or Twilio
   identifier is attached to a room, worker, or persisted record.
5. Inbound frames are bounded by payload size, sequence, timestamps, rate, and
   total duration. Outbound 20 ms frames are paced and share one send lock with
   interruption clears. Only the native agent can send `voicebot.interruption`.
6. Stop, disconnect, protocol error, setup failure, 45-second first-audio
   timeout, or 600-second call limit closes tracks, disconnects, deletes only the
   owned room, and closes the API client. All cleanup waits are bounded.

Cached `app/audio/unavailable-et.wav` is reused for capacity/provider failures;
no additional TTS call is made. Closing the stream lets Twilio execute the
following `<Hangup/>`. Missing fresh environment configuration fails closed.

### Implementation and verification plan

- [x] RED/GREEN: fixed-URL signatures, strict webhook parsing, identity gates,
  pending retry, nonce expiry/replay, and capacity bounds.
- [x] RED/GREEN: media protocol, mu-law/PCM conversion, serialized interruption,
  rates/timeouts, native dispatch, and owned-room teardown using mocked LiveKit.
- [x] Add separate compose routing and a bounded synthetic protocol probe.
- [x] Run scoped/full tests, parse/syntax checks, failure-path checks, and a
  self-review. Public synthetic WSS and private native audio are verified;
  real carrier activation remains a separate operator gate.

Independent review fixes (bounded to this bridge/security/probe and its tests):

- [x] RED/GREEN: stop/disconnect/protocol rejection during blocked RTC setup
  cancels setup before paid dispatch; one socket reader, bounded newest audio.
- [x] RED/GREEN: native clear discards the old SDK stream/queue, recreates a
  capacity-one stream on the same trusted track, and keeps the call open.
- [x] RED/GREEN: native-only audible mark required by the synthetic media probe;
  bridge fallback cannot produce a PASS.
- [x] RED/GREEN: optional trusted source-container media credentials; fresh
  Twilio fields only from the caller environment, static failure/exit handling.

## Official references

Checked 2026-10-02 using Context7 `/llmstxt/twilio_llms_txt` and official pages:

- [Request security](https://www.twilio.com/docs/usage/security): exact supplied
  URL, sorted POST parameters, HMAC-SHA1, Base64, constant-time comparison;
  documents the optional trailing slash for voice WSS signature validation.
- [Media Streams overview](https://www.twilio.com/docs/voice/media-streams):
  bidirectional `<Connect><Stream>`, signature validation, TLS port 443, and no
  fixed source-IP allowlist.
- [WebSocket protocol](https://www.twilio.com/docs/voice/media-streams/websocket-messages):
  start metadata, `audio/x-mulaw`, 8000 Hz, mono, base64 media, `clear`, and no
  WAV headers in outgoing payloads.
- [Official Python validator](https://github.com/twilio/twilio-python/blob/main/twilio/request_validator.py):
  sort/deduplicate repeated parameter values; mirrored with the standard
  library to avoid adding a dependency to the pinned media image.
- Native LiveKit publishing/dispatch documentation and aiohttp WebSocket/shutdown
  documentation were also checked via Context7, then against the installed
  pinned SDK signatures and real loopback HTTP/WebSocket tests.

The signature contract is fixed, never reconstructed from Host or forwarded
headers. The voice URL is `https://robot.arleserver.cfd/api/twilio/voice`.
The Stream URL is `wss://robot.arleserver.cfd/api/twilio/media`; signature
validation permits only that exact WSS URL and its documented trailing-slash
variant. No query string, HTTP scheme fallback, foreign host, or path is used.
The synthetic public wire proof corroborates that fixed-URL contract. Twilio's
actual carrier handshake still requires an independent incoming call.

## Credentials

The previous chat-exposed credential is compromised and must be revoked outside
chat. Do not reuse it, retrieve it from a conversation, or persist it here.
Fresh credentials are supplied only through process environment lookups from
the trusted source. Never print compose's interpolated configuration.

Environment: `TWILIO_AUTH_TOKEN`, `TWILIO_ACCOUNT_SID`, `TWILIO_PHONE_NUMBER`,
`LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`; optional
`VOICEBOT_AGENT_NAME` defaults to `voicebot`. The bridge needs no LLM, speech, or
booking credentials: those remain in the native worker.

This document describes the implementation, not a verified real phone call.

## Runtime and wire contracts

Run `python -m app.twilio_bridge` in the rebuilt `voicebot-telephone:local` image:
one process, port 8082. Python 3.12 is required for the standard-library `audioop`
conversion. The already-pinned `aiohttp==3.14.3` supplies both HTTP and WebSockets;
no dependency or lock change is required. A real wire regression showed that the
media environment had no Uvicorn WebSocket backend, so using the existing native
server avoids adding one. No Twilio SDK, alternative agent framework, or new
provider dependency is used.

`LIVEKIT_URL` must use `ws`/`wss` and a private endpoint: `livekit`,
`voicebot-media-livekit`, `localhost`, loopback IP, RFC1918 IP, or unique-local
IPv6. Public hosts/IPs, URL userinfo, query strings, and fragments fail closed.
Compose defaults to the existing private `ws://livekit:7880`. Native API
failover retries are disabled, including agent dispatch.

| Route | Contract |
| --- | --- |
| `POST /api/twilio/voice` | Fixed HTTPS HMAC signature; URL-encoded body ≤16 KiB, ≤64 fields, each value ≤4096 characters. Every form value participates in signing. Account/To/CallSid must each be unambiguous. Private responses are `no-store`. |
| WebSocket `/api/twilio/media` | Fixed WSS HMAC before accept; documented slash signing variant accepted. Actual route accepts with/without slash. Query strings and duplicate signature headers rejected. `connected` then `start`, each within 5 seconds. |
| `GET /api/twilio/unavailable-et.wav` | Generic cached Estonian failure audio only; no credential, identity, or paid synthesis. |
| `GET /health` | **Private liveness**, 200 with `alive:true` and a `configured` boolean, not a carrier-readiness claim. Missing configuration still gives 503 on voice/media before admission. |

Successful TwiML is `<Response><Connect><Stream
url="wss://robot.arleserver.cfd/api/twilio/media"><Parameter name="call_binding"
value="OPAQUE_ONE_USE"/></Stream></Connect><Hangup/></Response>`.
Do not print actual TwiML: its binding is a temporary capability. Capacity
instead returns cached `<Play>` followed by `<Hangup>`, without creating a room.

`start.accountSid` must equal the configured account, `start.callSid` must be
`CA` plus 32 hex characters matching the pending webhook, and both stream IDs
must be the same `MZ` plus 32 hex characters. `start.tracks` is `["inbound"]`;
format is exactly `audio/x-mulaw`, integer `8000`, integer `1`. Custom parameters
contain only `call_binding`. Even capacity rejection consumes a valid binding.

Inbound/outbound audio remains memory-only. JSON messages are ≤4096 bytes;
mu-law payloads are ≤1600 bytes (200 ms), with an 8 kHz token bucket and at most
one second of burst credit. Message rate is ≤100/s with one second of credit;
sequence/chunk order, monotonic timestamps, and a two-second future skew bound
are enforced. Total audio is ≤4.8 million samples/direction; native RTC queues
are bounded and egress uses paced 20 ms frames. The first audible output deadline
includes room setup time. There is no automatic booking or carrier retry.
The single socket reader starts **before** RTC setup and validates every incoming
message throughout it. Stop/disconnect/protocol rejection cancels owned setup;
the pre-dispatch guard also checks the call-ended event after queued input has
had a turn to drain. A stopped caller never resumes setup to dispatch an agent.
Only the newest **8000 samples/16,000 PCM bytes and at most 50 frames** are kept
while RTC is not ready (and under active input backpressure); older queued audio
is discarded, not replayed late. Native input feeding starts only after setup
succeeds. No second socket consumer or new timeout configuration is introduced.
Normal hangup and the duration cutoff close the carrier socket before waiting
for independent RTC/API cleanup; cleanup retains the admission slot until done.

Worker interruption contract: the **native agent participant** publishes
`b"clear"` with `reliable=True`, topic `voicebot.interruption`, on the VAD speaking
edge. Other participants, topics, or payloads are ignored. Carrier `media` and
`clear` sends share a lock; a clear invalidates queued local PCM generations,
cancels the current output task, closes the public SDK `AudioStream`, and creates
a new capacity-one stream on the **same already-authenticated native track**.
This discards pre-clear SDK-buffered frames rather than letting them acquire a
new sender epoch. Reset cancellation does not end the call. Reset failures or
concurrent teardown fail closed and never recreate a stream after call close.

Native provenance uses an ordinary Twilio **outbound mark**, not a custom event:
`event="mark"`, the current `streamSid`, and
`mark={"name":"voicebot-native-audio"}`. The trusted native output path sends it
once per call, directly after its first audible media frame (PCM RMS >32), under
the same send lock. Silence, inbound mark/DTMF messages, foreign participants,
and the bridge's cached failure playback cannot issue this mark. A native
worker's own cached/fallback speech still counts as private-worker provenance;
the mark proves neither provider success nor a successful conversation/booking.

Replay admission uses hashed call-ID tombstones, memory-only for 24 hours,
maximum 1024 entries; saturation fails closed rather than evicting live entries.
Old bindings cannot resume a room after restart. This is intentionally a
single-process pilot, not replicated/durable carrier admission.

## Deployment and operator proof

`deploy/telephony/twilio-compose.yaml` is the separate `voicebot-twilio` project
consumed by the helper's `--twilio validate/up`. It reuses the native
media image and `coolify` network, has no booking volume or paid-provider keys,
and binds host port 8082 only to loopback. It does not build or start LiveKit/SIP.

The confirmed existing edge uses `http`/`https`, TLS `letsencrypt`, and the
robot-host catchall. This bridge adds only `Host(robot.arleserver.cfd)` plus
`PathPrefix(/api/twilio/)`, priority 10000, `https`/TLS, with a matching `http`
redirect. Health and all other ports/paths stay private. These route/priority
boundaries are publicly verified. Do not use a fixed Twilio source-IP list.
After recreating the bridge, wait for Docker health to become **healthy** and
for the public unsigned route to return the bridge's expected 403 or 503.
Private HTTP liveness alone is insufficient: Traefik can temporarily use the
website catchall before the first successful Docker health check.

Configure the existing assigned number's incoming voice webhook to the **exact**
HTTPS voice URL above using POST, only after the exposed credential is revoked
and fresh environment values are injected. No number is purchased or dialled
by this bridge. Account/webhook configuration remains an explicit operator step.

Optional protocol probe:

- `python deploy/telephony/twilio_probe.py`: verifies unauthorized rejection and
  signed TwiML, creates only an expiring synthetic binding, no paid agent.
- `python deploy/telephony/twilio_probe.py --media`: explicitly dispatches one
  native agent, sends synthetic silence, requires **both** audible 8 kHz return
  media and the exact native-audio mark on that stream, then checks consumed-binding
  rejection. A native setup failure followed by cached bridge speech fails this
  probe. Bounded to 75 seconds; no audio/transcript saved.
  This does **not** distinguish native greeting from native fallback speech and
  is **not** evidence of a real carrier/PSTN call or successful conversation.
- Missing environment or transport failures exit 1 with a static code only.

### Repeatable operator commands

Use the pinned Python 3.12 media environment. After rotating the exposed
credential **outside chat**, export only fresh `TWILIO_AUTH_TOKEN`,
`TWILIO_ACCOUNT_SID`, and `TWILIO_PHONE_NUMBER` from the protected environment.
Do not paste their values in shell commands, chat, files, or logs. Set the
non-secret `VOICEBOT_WEB_CONTAINER` to the **current trusted deployed voicebot
web container**, updating it after each deployment; no historical container name
is embedded here.

From `/home/arle/voicebot`, operator activation with freshly rotated credentials:

```sh
python deploy/telephony/manage.py validate --twilio --source-container "$VOICEBOT_WEB_CONTAINER"
python deploy/telephony/manage.py up --twilio --source-container "$VOICEBOT_WEB_CONTAINER"
python deploy/telephony/twilio_probe.py --source-container "$VOICEBOT_WEB_CONTAINER"
```

Explicit paid-agent synthetic proof, still **no PSTN call**:

```sh
python deploy/telephony/twilio_probe.py --source-container "$VOICEBOT_WEB_CONTAINER" --media
```

The probe's optional `--source-container NAME` reuses
`deploy.telephony.manage.environment(NAME)` with captured inspect output, then
copies only `LIVEKIT_API_KEY`/`LIVEKIT_API_SECRET` into its in-memory configuration.
`LIVEKIT_URL` defaults to the compose-consistent private `ws://livekit:7880` unless
the caller supplied another validated private URL. Twilio fields remain solely
the caller's environment values, even if the source contains old Twilio fields;
missing fresh fields fail before any source inspection or network probe. The
helper's existing trusted runtime/shared-journal checks still apply. No private
keys need to be re-entered. Without this flag the fully configured six-variable
environment contract is unchanged. Inspect/config/transport failures print only
a static code and exit nonzero; inherited values are never printed or saved.

Credential configuration and the assigned number's POST webhook are now verified
as described below. An actual incoming call with spoken consent/booking/readback/
cancellation remains the final carrier gate. Do not label a synthetic probe as a
real phone call; revocation of the former chat-exposed credential remains the
owner's responsibility, not something these read-only checks prove.

## Initial transport evidence — 2026-10-02

- Full pinned-media suite: **589 passed, 4 skipped**, no deselections. Core suite:
  **470 passed, 30 skipped**. Optional live/external tests are not fabricated.
- Independent review found three transport P2s; each has RED/GREEN regressions:
  stop during setup cancels before dispatch; clear discards pre-clear SDK-buffered
  audio; adapter fallback cannot satisfy the native-provenance probe. Clean-env
  credential inheritance and failure exit codes are also tested.
- Public signed HTTPS/WSS proof used only fresh, transient **synthetic** account
  fixtures. It verified unsigned rejection, signed TwiML, native mono 8 kHz audio
  and provenance mark, VAD-triggered carrier clear, one isolated native room,
  consumed-binding replay rejection, and acknowledged room cleanup.
- The synthetic fixture was removed afterward. At that initial handoff the bridge had
  `configured=false`; public voice/media returned **503 + no-store** before any
  worker allocation. No real Twilio credential was used, retrieved or saved.
- Real private Groq/Azure speech independently created, read and cancelled an
  owned fictional booking. This is separate from the WSS transport test and is
  **not PSTN verification**.

Commands, boundaries and remaining prerequisites:
[dated hackathon evidence](docs/evidence/2026-10-02-hackathon-verification.md).

## Subsequent credential activation — 2026-10-02

- User-supplied credentials were kept in the protected environment. A read-only
  Twilio API request authenticated successfully, matched the assigned voice number,
  and verified the exact HTTPS webhook, POST method and no application override.
- The trusted current web container's private media credentials were reused.
  Only the separate bridge was recreated; the worker and booking data were not
  replaced. Normal interactive Bash startup loaded the updated protected
  environment without exposing values. An older non-interactive session had
  retained stale credentials.
- Private health now reports `configured=true`; the public unsigned webhook
  returns **403 + no-store**, not the former missing-configuration 503.
- The pinned `twilio_probe.py --media` passed signed HTTPS/WSS, audible native
  output plus provenance mark, and consumed-binding replay rejection using the
  configured credentials. Independent private-room readback confirmed zero
  remaining Twilio rooms after the probe.
- No outbound phone call, number purchase, account mutation or real PSTN proof
  was performed. The bridge is left **active for an incoming phone test**.
