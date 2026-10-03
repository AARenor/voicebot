# Natural English and Estonian conversation

The telephone worker and protected HTTP demo share conversational wording and
Azure speech delivery. The existing Groq models, Azure voices and booking
adapters remain in use. No new provider account or dependency is required.

## Conversation

The restaurant assistant introduces itself as a virtual assistant in a fictional
demo. Estonian instructions request idiomatic Estonian, consistent informal
address, a direct answer followed by a short explanation when needed, and usually
one to three complete sentences. They avoid English terminology, fragmented
phrases, repeated introductions and an unnecessary follow-up question on every
turn. Reviewed FAQ wording remains exact rather than being freely paraphrased.

Restaurant identity and staff-transfer replies use their own reviewed wording.
They do not offer legacy spa or hotel bookings. Menu/allergen, food-order,
opening-hours and table-reservation questions use reviewed answers. Hours and
restaurant bookings remain unconfigured; the assistant does not invent them.
Legacy spa/stay integrations retain their separate catalogue and recap policy.

Standalone greetings, thanks, goodbyes, declines, repeat requests, frustration,
identity and human-transfer questions use reviewed replies in Estonian, English
or Russian directly.
These turns need no model request. Repeated social turns can select a different
reviewed reply within the same call. Mixed requests such as “Thanks, book a room”
still reach planning. The bounded conversation state stores intent and counters,
not the caller's words.

In legacy spa/stay integrations, service questions read the verified service
choices without also reciting the working schedule. Opening-hours questions read
the verified schedule and explain
that appointment availability requires a separate check. Backend names, quotes,
receipts and FAQ answers retain their authoritative wording.

“Could you repeat that?” during a pending proposal repeats the exact owned
recap. The hold and expiry stay the same, but delivery and consent reset. A late
playback event from the previous reading cannot approve the new reading. The
caller must hear the repeated recap and then give fresh explicit consent.

## Speech settings

| Variable | Default | Behavior |
| --- | --- | --- |
| `VOICEBOT_SPEAKING_STYLE` | `natural` | Shared speech styling; `neutral` removes prosody, pronunciation aliases, pause settings and expressive style. |
| `VOICEBOT_SPEECH_RATE` | `0.98` | Normal rate multiplier, accepted range `0.85`–`1.15`. |
| `VOICEBOT_RECAP_RATE` | `0.94` | Recap multiplier, capped at the normal rate so recaps never become faster. |

English `en-US-JennyNeural` uses Azure's supported `friendly` style at degree
`0.8`. Estonian Anu and other configured voices keep their normal voice style,
with the shared rate adjustment. Voice and locale continue to follow the active
language. Invalid settings fail before provider requests and do not echo values.

Estonian speech uses explicit Azure silence settings: zero leading silence,
120 ms at the end of a synthesis request, and 200 ms between sentences. Recaps
use a 240 ms tail and 320 ms sentence boundary. The shared renderer applies this
to both HTTP replies and native per-sentence synthesis, reducing silence added
between separate sentence requests. English and Russian delivery retain their
existing settings. These are a listening preset, not measured proof of perceived
naturalness. See [Azure's documented silence settings](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/speech-synthesis-markup-structure#add-silence).

Estonian ISO dates, date-times, `kell H`, `kell H:MM`, valid clock ranges and
`Europe/Tallinn` use SSML pronunciation aliases. For example, `kell 9:30` is
pronounced “kell üheksa kolmkümmend”. Clock-range normalization and aliases occur
at synthesis, while the displayed reply stays unchanged. Delivery comparisons
and the transcript still use the exact server recap. Invalid dates/times remain
literal. Prices, quantities and identifiers are not reinterpreted as clocks.
All speech text is escaped before markup is introduced.

The native provider renders complete markup for each synthesis request **after**
LiveKit splits plain text into sentences. HTTP synthesis uses the same renderer.
This prevents sentence tokenization from splitting XML tags. Existing scoped
playback receipts, interrupted-recap handling, independent cached failure audio
and uncertain-write protection remain active.

`/api/status` reports the selected style and rates. It describes application
configuration and does not establish the telephone worker's deployed revision.

Browser reply audio uses Azure's high-fidelity 48 kHz / 96 kbit/s mono MP3 output,
instead of the previous downsampled 16 kHz / 32 kbit/s output. This preserves the
same voices, wording and speech settings, but increases transferred audio bytes.
The native worker retains 24 kHz PCM; PSTN codec bandwidth is unchanged.
See [Azure's supported audio formats](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/rest-text-to-speech#convert-text-to-speech).
Higher fidelity is objectively verifiable, not proof that listeners perceive a
voice as human. Listening preference remains separate from configuration tests.

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
