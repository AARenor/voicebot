# Hackathon verification — 2026-10-02

Scope: fictional **Meretuule Demo Spa**, Easy!Appointments 1.6.0, native LiveKit
Agents, Groq STT/LLM and Azure Anu replies. The supplied US Twilio number is the
first carrier target. No number purchase, outbound call, account mutation,
recording, real guest data or use of the exposed credential occurred.

## Verified software and private speech

```sh
/tmp/opencode/voicebot-telephony-venv/bin/python -m pytest tests -q
.venv/bin/python -m pytest tests -q
docker exec livekit-worker-1 pip check
```

- Pinned media environment: **589 passed, 4 skipped**; core environment:
  **470 passed, 30 skipped**. No deselections. Optional live/external tests remain
  opt-in; the native proofs below were run explicitly.
- Dependency check: **No broken requirements found**. Expected warnings:
  existing FastAPI/TestClient HTTPX deprecation and Python 3.12 `audioop`.
- Independent review reproduced and closed the delivered-recap, ungrounded
  success speech, logout-race, cancelled-confirmation replay and sticky uncertain
  mutation defects. Three subsequent transport P2s were fixed with RED/GREEN
  tests: pre-dispatch stop, stale queued audio after clear, and false-positive
  adapter-fallback probe. No remaining verified P0/P1 in those scoped reviews.

```sh
/tmp/opencode/voicebot-telephony-venv/bin/python deploy/telephony/conversation_probe.py --source-container livekit-worker-1
docker exec -i livekit-worker-1 python - < deploy/telephony/booking_probe.py
```

- Real sequential native audio: **7 final STT inputs, 6 spoken replies, 3216
  voiced frames**. Two canonical recaps delivered; no pre-consent or decline
  write; exact spoken consent; owned appointment independently read through REST;
  exact spoken cancellation independently verified by REST **404**.
- Direct SDK probe also passed shared-journal creation/read/cancellation,
  premature-write/decline rejection and foreign-call cancellation rejection.
- Caller fixtures use Kert; the bot replies with Anu. Short exact phrases
  **“Jah, kinnitan.” / “Jah, tühista.”** avoid an observed later-turn compound-word
  ASR error. Both passed bounded sequential ASR controls; long explicit phrases
  remain compatible. Bare yes, mixed/negative replies, undelivered/expired recap,
  foreign targets and unknown-write retries remain rejected. No fuzzy consent.
- Silero uses its supported defaults. A smaller-padding candidate was reverted
  because it alone did not verify a fix. No lossless-audio preservation claim.
- Exact owned appointment/customer cleanup ran; audio/transcripts stayed in
  memory. These tests report **carrier_verified=false**.

## Browser

Built the final HTTP image and ran the credential-safe Chromium proof at
`http://127.0.0.1:8029` using `/tmp/opencode/voicebot-browser-proof.py`.

All assertions passed: no anonymous private fetch; wrong authentication rejected;
live catalogue/bookings; actionable microphone denial; in-memory fictional
microphone audio through real STT and reply playback; canonical recap before
write; consented booking with independent REST readback and actual-day selection;
cancellation/empty panel; end/logout cleanup of private DOM/audio/microphone and
storage; mobile without overflow; **zero JavaScript errors**. No credentials in
browser storage. Screenshots remained local, not committed.

## Public HTTPS/WSS, not PSTN

The dedicated `voicebot-twilio` Compose project uses the existing `coolify`
network and HTTPS edge, priority **10000** for `/api/twilio/`, `https`/TLS
`letsencrypt`, HTTP redirect and loopback-only **8082**. No booking volume or
speech/booking-provider credentials are given to the adapter.

`/tmp/opencode/voicebot-twilio-public-proof.py` generated a transient synthetic
signing fixture in memory, admitted no PSTN call and always restored the bridge:

- unsigned webhook **403 + no-store**, signed TwiML **200**;
- unsigned WSS rejected; signed mono 8 kHz mu-law to the real private worker;
- native audible output and fixed `voicebot-native-audio` provenance mark;
- actual native VAD interruption sends carrier `clear`;
- one opaque room with native worker, consumed-binding replay rejected;
- owned private room acknowledged as cleaned;
- fixture removed: private `configured=false`; public voice/media again
  **503 + no-store**, before worker allocation.

The initial immediate-public request reached the website catchall while Docker
health was starting. Waiting for **Docker healthy plus the correct public gate**
resolved it. Private HTTP liveness is not proxy readiness.

This proves an existing public HTTPS/WSS edge, **not Twilio carrier
interoperability or a real telephone conversation**. Fresh rotated credentials,
the assigned number's POST webhook and an independent incoming phone call remain
external activation gates. [Activation commands](../../TWILIO.md).

## Failure, concurrency, drain and private SIP

```sh
/tmp/opencode/voicebot-telephony-venv/bin/python deploy/telephony/probe.py --source-container livekit-worker-1 --concurrent
/tmp/opencode/voicebot-telephony-venv/bin/python deploy/telephony/probe.py --source-container livekit-worker-1 --barge-in
/tmp/opencode/voicebot-telephony-venv/bin/python deploy/telephony/failure_probe.py
/tmp/opencode/voicebot-telephony-venv/bin/python deploy/telephony/failure_probe.py --drain
/tmp/opencode/voicebot-telephony-venv/bin/python deploy/telephony/sip_probe.py
```

- Two isolated real-provider jobs passed; both returned STT and reply audio.
- Barge-in passed: greeting stopped during caller speech.
- Invalid-Azure clone returned independently cached Estonian fallback over RTC;
  **376000 PCM bytes**, expected words present, ASR similarity **0.942**.
- Separate clone's SIGTERM drain rejected a new job, exited **0**, terminated its
  active room and was removed without stopping the normal worker.
- Private SIP: unauthenticated challenge, digest-authenticated **200**, **196 RTP
  packets / 100 voiced**, independent greeting content, BYE acknowledgement,
  isolated SIP/agent room and teardown; wrong number never answered/dispatched.
  Only uniquely owned temporary trunk/rule were removed. This is not public SIP.
- Clean `env -i` SIP preflight exited **2**, naming five missing prerequisites and
  explicitly denying public/carrier verification. Fresh-Twilio-missing probe
  exited **1**, static `twilio_probe_configuration_missing`, before inspection.

## Preservation and delivery

Coolify application **13** uses `Parnuhakk/voicebot.git`, branch `master`.
Explicit `/data` persistent storage and HTTP/native/staging mounts all reference
the original volume. Before final deployment, booking journal **20 rows** (the
original 7 plus scoped synthetic verification writes), calls **28 rows**, both
SQLite integrity checks **ok**. New rows: 15 static native summaries and 12
static HTTP summaries; no new saved transcripts. Historical rows were retained.

Release commit/push, public HTTP source fingerprints and final redeployment
readback are recorded below after delivery; local verification is not deployment.
