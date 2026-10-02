# Meretuule Demo Spa — hackathon playbook

This is a fictional Estonian spa, not a real hotel or guest-service deployment.
Use only the provided fictional guest identities. No payments, emails, SMS,
outbound calls, real addresses, or real prices. Examples are not reservations;
availability and confirmed bookings come from Easy!Appointments.

[Dated verification and explicit remaining gates](docs/evidence/2026-10-02-hackathon-verification.md).

## Channels

1. **Operator browser demo:** the HTTPS website runs the HTTP speech/text path.
   It is a useful fallback for presenting before a telephone number is active,
   but is not a telephone call or public WebRTC proof.
2. **Private voice worker:** LiveKit Agents runs continuous Estonian room audio
   with interruption, owned booking tools and cached failure speech.
3. **First real telephone target — US Twilio:** the already assigned number uses
   signed HTTPS/WSS bidirectional Media Streams into the same private worker.
   This avoids the missing public SIP/RTP edge. Fresh rotated authentication,
   the number's incoming webhook and a verified independent incoming call are
   still required. A synthetic WebSocket probe is not a PSTN call.
4. **Alternative SIP carrier:** number/carrier configuration and a publicly
   reachable SIP/RTP edge are required. This LAN host's SIP edge is unverified;
   website HTTPS cannot supply the UDP media route.

## Presentation sequence

- Explain the fictional spa and AI disclosure; choose a future weekday.
- Ask for a demo spa consultation. The bot resolves the live service/provider
  and offers a real available time; choose the default fictional guest.
- Hear/read the recap. First decline: no booking should appear.
- Ask again, then say **“Jah, kinnitan.”**
- Verify the appointment in the provider-backed bookings panel. A sentence
  claiming success is not proof of a saved booking.
- Say **“Jah, tühista.”**
- Verify the appointment is gone. A different conversation cannot cancel it.
- Demonstrate a closed day, price question, ambiguous consent or interruption.

Conversation state is bounded and memory-only. Restarting/ending a conversation
does not cancel a saved appointment and cannot regain its write ownership.
Do not automatically repeat a write after an uncertain provider result. Use the
read panel/operator backend to inspect it first.

Recaps and mutation status are server-rendered from current execution truth,
not model paraphrases. Only approved fictional FAQ answers/static guidance may
otherwise reach speech. A later request cannot turn an unknown write into success.
Consent/cancellation must match the spoken final intent; ASR mistakes fail closed
and are not fuzzy-matched into permission. This is a synthetic demo, not an
unrestricted natural-language booking service.
The earlier longer explicit confirmation/cancellation phrases remain accepted;
the short exact phrases avoid a demonstrated ASR compound-word failure. Bare
“jah” is not consent, and even a short confirmation cannot authorize a booking
without the specific fully delivered recap.

## Repeatable checks

From `/home/arle/voicebot`, with the pinned media environment:

```bash
MEDIA_PY=/tmp/opencode/voicebot-telephony-venv/bin/python
$MEDIA_PY -m pytest tests -q
$MEDIA_PY deploy/telephony/conversation_probe.py --source-container livekit-worker-1
$MEDIA_PY deploy/telephony/probe.py --source-container livekit-worker-1 --concurrent
$MEDIA_PY deploy/telephony/probe.py --source-container livekit-worker-1 --barge-in
$MEDIA_PY deploy/telephony/sip_probe.py
$MEDIA_PY deploy/telephony/failure_probe.py
$MEDIA_PY deploy/telephony/failure_probe.py --drain
```

Provider checks use real Groq/Azure services and synthetic backend writes. The
conversation probe checks pre-consent/decline, real audio, independent REST
creation/read/cancellation and exact call-scoped cleanup. It never saves audio
or transcripts. These are **private tests, not PSTN**.

## Twilio US activation — first carrier

The previously pasted authentication credential is compromised. Rotate it in
the Twilio account and store only the replacement in protected environment
storage; never paste it into chat or a command argument. Do not use the old one.
Keep Estonian Groq/Azure speech and the existing private booking worker.

The separate [Twilio bridge](TWILIO.md) uses only the website's `/api/twilio/` route; it does not
expose LiveKit/Redis/SIP/health. Its signed incoming webhook returns a bidirectional
stream with an opaque one-use call binding. Follow the bridge runbook for exact
environment names, URL/signature rules, deployment and synthetic wire checks.
Configure only the already assigned number's incoming voice webhook; no purchase,
outbound call, SMS or recording is part of this demo.

The only new account environment values are `TWILIO_AUTH_TOKEN`,
`TWILIO_ACCOUNT_SID`, and `TWILIO_PHONE_NUMBER`. Existing private media credentials
are inherited in memory from the trusted app container. Deploy/validate with:

```bash
python3 deploy/telephony/manage.py validate --twilio --source-container "$VOICEBOT_WEB_CONTAINER"
python3 deploy/telephony/manage.py up --twilio --source-container "$VOICEBOT_WEB_CONTAINER"
```

The assigned number's incoming voice webhook is exactly
`https://robot.arleserver.cfd/api/twilio/voice`, method **POST**. The service derives
the bidirectional stream itself; do not configure SIP, expose UDP, or put keys in
URLs. Bridge health can be alive while `configured=false`; public call routes
then return **503 before admission**, not a ready telephone claim.

After activation, make an independent incoming call and verify two-way Estonian
audio, recap/consent, backend booking/read/cancel, interruption and hangup. Until
that evidence exists the dashboard deliberately says telephone unverified.

## Alternative SIP activation

No carrier account changes or number purchase are automated. Put credentials in
protected environment storage, never chat, CLI arguments or committed files.
Required names:

- `SIP_NUMBER`: actual assigned E.164 number for the selected SIP carrier.
- `SIP_ALLOWED_CIDRS`: actual narrow carrier signaling source networks.
- `SIP_AUTH_USER`, `SIP_AUTH_PASSWORD`: matching digest configuration.
- `SIP_PUBLIC_HOST`: owner-controlled unproxied public SIP edge, **not** the
  dashboard domain. Public DNS alone does not prove reachability.

```bash
$MEDIA_PY deploy/telephony/activate.py check --source-container "$VOICEBOT_WEB_CONTAINER"
$MEDIA_PY deploy/telephony/activate.py provision --source-container "$VOICEBOT_WEB_CONTAINER"
```

`check` returns 2 for missing prerequisites and lists names, never values.
`provision` creates/reuses only exact-matching named inbound objects; mismatches
fail closed. It neither opens ports nor configures DIDWW nor verifies a call.
Both reports keep public/carrier verification false.

For the actual edge, follow [the carrier gates](deploy/telephony/README.md#didww-activation-gates)
and [the host audit](docs/evidence/2026-10-02-public-edge-audit.md). Telephone-only
ingress needs the chosen SIP transport and UDP 10000–10100, correct public SDP
advertisement and carrier-restricted forwarding/firewall. Keep API/RTC, Redis
and worker health private. Never turn the private Compose into wildcard ingress.

Then configure DIDWW static SIP delivery with the actual assigned number and
matching digest credentials. Verify an independent off-LAN real call: two-way
Estonian speech, booking/read/cancel, interruption, hangup, failure and overflow.
No environment switch can turn an unperformed test into a verified carrier call.
