# Voicebot deployment handoff — 2026-10-03

The Windows development session can push GitHub and check public HTTPS. The
server operator will deploy the separate telephone services. Web pushes use
the existing Coolify deployment; they do not rebuild the native worker.

## Existing host

Use the existing `/home/arle/voicebot` checkout. Inspect its branch and worktree
before updating; preserve any local work. Update `master` with a fast-forward
only. Identify the current trusted web container as `VOICEBOT_WEB_CONTAINER`.
Keep the existing named `/data` storage and both booking database paths;
the worker and web application must use the same volume.

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

Set the web application's `PUBLIC_PHONE_NUMBER` in Coolify to its existing
assigned inbound E.164 number, then redeploy. The public hotel currently has
no configured number. Fictional test numbers in the repository are not its
assigned contact number.

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
Estonian audio, interruption, the complete canonical booking recap followed by
explicit consent, an independently readable booking, owned cancellation and
hangup. Verify both spa and room flows and clean up fictional test bookings.
Synthetic audio and private SDK tests do not establish a successful PSTN call.

On `robot.arleserver.cfd`, verify Demovestlus with typed text and the physical
microphone, including reply playback. The identified live conversation failure
is Groq HTTP 429; usage limits are shared across the provider organization.
Compact planning and canonical server replies reduce requests. Check the
provider's actual account limits if throttling remains under normal use.

See [native runtime](../../deploy/telephony/README.md),
[Twilio runbook](../../TWILIO.md), [Coolify storage](../../COOLIFY.md) and
[verification evidence](../evidence/2026-10-03-voice-and-booking-update.md).
