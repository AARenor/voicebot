# Natural English and Estonian conversation

The telephone worker and protected HTTP demo share conversational wording and
Azure speech delivery. The existing Groq models, Azure voices and booking
adapters remain in use. No new provider account or dependency is required.

## Conversation

The assistant introduces itself as AI and explains that bookings are synthetic.
Later turns use shorter questions and avoid repeating the introduction. Planning
instructions request one missing detail at a time and preserve details already
given. Approved alternatives cover spa service/date/time, room arrival/departure,
guest counts and room type.

Standalone greetings, thanks, goodbyes, declines, repeat requests, frustration,
identity and human-transfer questions use reviewed bilingual replies directly.
These turns need no model request. Repeated social turns can select a different
reviewed reply within the same call. Mixed requests such as “Thanks, book a room”
still reach planning. The bounded conversation state stores intent and counters,
not the caller's words.

Service questions read the verified service choices without also reciting the
working schedule. Opening-hours questions read the verified schedule and explain
that appointment availability requires a separate check. Backend names, quotes,
receipts and FAQ answers retain their authoritative wording.

“Could you repeat that?” during a pending proposal repeats the exact owned
recap. The hold and expiry stay the same, but delivery and consent reset. A late
playback event from the previous reading cannot approve the new reading. The
caller must hear the repeated recap and then give fresh explicit consent.

## Speech settings

| Variable | Default | Behavior |
| --- | --- | --- |
| `VOICEBOT_SPEAKING_STYLE` | `natural` | Shared speech styling; `neutral` removes prosody, pronunciation aliases and expressive style. |
| `VOICEBOT_SPEECH_RATE` | `0.98` | Normal rate multiplier, accepted range `0.85`–`1.15`. |
| `VOICEBOT_RECAP_RATE` | `0.94` | Recap multiplier, capped at the normal rate so recaps never become faster. |

English `en-US-JennyNeural` uses Azure's supported `friendly` style at degree
`0.8`. Estonian Anu and other configured voices keep their normal voice style,
with the shared rate adjustment. Voice and locale continue to follow the active
language. Invalid settings fail before provider requests and do not echo values.

Estonian ISO dates, date-times, `kell HH:MM` and `Europe/Tallinn` use SSML
pronunciation aliases. For example, `kell 10:30` is pronounced “kell kümme
kolmkümmend”. The literal recap text stays unchanged, so delivery comparisons
and the transcript still use the exact server recap. Invalid dates/times remain
literal. All speech text is escaped before markup is introduced.

The native provider renders complete markup for each synthesis request **after**
LiveKit splits plain text into sentences. HTTP synthesis uses the same renderer.
This prevents sentence tokenization from splitting XML tags. Existing scoped
playback receipts, interrupted-recap handling, independent cached failure audio
and uncertain-write protection remain active.

`/api/status` reports the selected style and rates. It describes application
configuration and does not establish the telephone worker's deployed revision.

## Activation and listening

GitHub changes must reach both the web process and the separate telephone worker.
The deployment helper preserves these three optional settings from the trusted
web container; Compose supplies the defaults when they are absent. Follow the
[English telephone deployment runbook](english-telephone.md#deploy-the-telephone-worker)
using the existing shared booking volume.

To return to neutral speech, set `VOICEBOT_SPEAKING_STYLE=neutral` and restart
the affected processes. Conversational wording remains available.

With provider and server access, compare English and Estonian calls for clear
dates/times, comfortable pacing, short questions, repeated recaps, interruption,
explicit confirmation and cancellation. Local fixtures verify policy and request
construction; they cannot establish audible naturalness or live call latency.

Provider references:
[Azure SSML voice and prosody](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/speech-synthesis-markup-voice),
[Azure voice/style support](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/language-support),
[LiveKit Azure TTS](https://docs.livekit.io/agents/models/tts/azure/).
