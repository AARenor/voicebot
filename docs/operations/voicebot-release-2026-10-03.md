# Voicebot deployment handoff — 2026-10-03

The Windows development session can push GitHub and check public HTTPS. The
server operator will deploy the separate telephone services. Web pushes use
the existing Coolify deployment; they do not rebuild the native worker.

The Russian-caller update extends the existing Estonian/English native pipeline.
Groq recognition returns detected language metadata; approved Russian replies,
recaps and Azure speech use that selected language. Default mode remains
`VOICEBOT_TELEPHONE_LANGUAGE=auto`; use `et`, `en` or `ru` to lock the caller
language from the initial greeting. Russian defaults are
`AZURE_RU_VOICE=ru-RU-SvetlanaNeural` and `AZURE_RU_LANG=ru-RU`.
Keep existing Estonian and English voice settings. Optional overrides belong in
the trusted source web container environment before the native rebuild/restart.

There is no Russian cached provider-failure recording. Russian calls use the
independent Estonian apology if synthesis fails, and assistant session history
retains the actual Estonian text; English calls keep the English cached apology.
Language changes invalidate pending recap consent. Static syntax/diff checks do
not establish live audio behavior: native deployment and actual Russian call
verification remain pending.

## Existing host

Use the existing `/home/arle/voicebot` checkout. Inspect its branch and worktree
before updating; preserve any local work. Update `master` with a fast-forward
only. Identify the current trusted web container as `VOICEBOT_WEB_CONTAINER`.
Keep the existing named `/data` storage and both booking database paths;
the worker and web application must use the same volume.
The deployment manager now copies the web application's effective room and call
history database paths, including custom filenames under `/data`, and its exact
room-write setting. Caller shell overrides cannot select another database or
enable room writes that the web source disabled. Validation rejects paths outside
the shared mount and nonpersistent call logs before running Compose.

```bash
cd /home/arle/voicebot
git status --short
git branch --show-current
git pull --ff-only origin master
python3 deploy/telephony/manage.py validate --source-container "$VOICEBOT_WEB_CONTAINER"
DOCKER_CONFIG=/tmp/opencode/docker-voicebot python3 deploy/telephony/manage.py build --source-container "$VOICEBOT_WEB_CONTAINER"
python3 deploy/telephony/manage.py up --source-container "$VOICEBOT_WEB_CONTAINER"
python3 deploy/telephony/manage.py validate --twilio --source-container "$VOICEBOT_WEB_CONTAINER"
python3 deploy/telephony/manage.py up --twilio --source-container "$VOICEBOT_WEB_CONTAINER"
```

`manage.py` reuses trusted container configuration in memory. Do not copy
credentials into Git, shell arguments, logs or expanded Compose output.

The public property endpoint and hotel page checked at
`2026-10-03T10:43Z` now expose the configured contact `+17574278729`, including
its `tel:` link. Preserve the existing `PUBLIC_PHONE_NUMBER` during deployment.
Its presence on the page does not establish carrier assignment or a working
incoming conversation; verify the configured route and actual call below.
Fictional test numbers in the repository are not its assigned contact number.

## Verify the deployed telephone pipeline

Use the existing media virtual environment after the worker is healthy:

```bash
MEDIA_PY=/tmp/opencode/voicebot-telephony-venv/bin/python
$MEDIA_PY deploy/telephony/conversation_probe.py --source-container livekit-worker-1
$MEDIA_PY deploy/telephony/probe.py --source-container livekit-worker-1 --concurrent
$MEDIA_PY deploy/telephony/probe.py --source-container livekit-worker-1 --barge-in
$MEDIA_PY deploy/telephony/twilio_probe.py --source-container "$VOICEBOT_WEB_CONTAINER"
$MEDIA_PY deploy/telephony/twilio_probe.py --source-container "$VOICEBOT_WEB_CONTAINER" --media
```

Then place an actual incoming call to the existing number. Verify two-way
Estonian, English and Russian audio on separate calls, interruption, the complete
canonical booking recap followed by explicit consent, an independently readable
booking, owned cancellation and hangup. Switch languages during a call and verify
that an earlier recap cannot authorize a booking until a fresh recap in the
selected language has finished playing. Verify Russian catalogue/FAQ replies,
numeric-turn language retention and the documented Estonian cached fallback
during speech-provider failure. Verify both spa and room flows and clean up
fictional test bookings.
Synthetic audio and private SDK tests do not establish a successful PSTN call.

On `robot.arleserver.cfd`, verify Demovestlus with typed text and the physical
microphone, including reply playback. Test the reported request “Tere, tahaks
homme bruneerida spaad?”, then supply a time and verify that no booking is
created before the complete recap and later consent. Opening hours should be
spoken as “9 kuni kell 17” rather than a dash-separated range.
HTTP voice preparation now returns a one-use `recap_delivery_id`. A scripted
positive check must explicitly read or complete playback of that exact recap,
then include its ID with the subsequent consent turn in the same session.
Returning synthesized bytes alone does not authorize confirmation. The browser
tracks completed playback or explicit reading; test stale, interrupted and
foreign recap assertions as rejection cases.
One identified live conversation failure was Groq HTTP 429; usage limits are
shared across the provider organization. A separate clarification fault
rejected harmless questions with an unverified-success warning; the patch
supplies canonical missing-field questions from trusted user inquiry state.
Compact planning and canonical server replies reduce requests. Check the
provider's actual account limits if throttling remains under normal use.

See [native runtime](../../deploy/telephony/README.md),
[Twilio runbook](../../TWILIO.md), [Coolify storage](../../COOLIFY.md) and
[verification evidence](../evidence/2026-10-03-voice-and-booking-update.md).
