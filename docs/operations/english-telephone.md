# English telephone support

The native worker recognizes English and Estonian and uses a dedicated Azure
voice for each. English supports the existing fictional hotel/spa catalogue,
opening hours, availability, owned holds, exact room quotes, booking recaps,
confirmation, cancellation and approved FAQs. This remains the same synthetic
demo; real hotel reservations, payments and human transfer are not enabled.

## Configuration

| Variable | Default | Meaning |
| --- | --- | --- |
| `VOICEBOT_TELEPHONE_LANGUAGE` | `auto` | Detect language per spoken turn; `en` or `et` locks the call language and sends an explicit recognition hint. |
| `AZURE_VOICE` / `AZURE_LANG` | `et-EE-AnuNeural` / `et-EE` | Existing Estonian voice and locale. |
| `AZURE_EN_VOICE` / `AZURE_EN_LANG` | `en-US-JennyNeural` / `en-US` | English voice and matching locale; e.g. `en-GB-SoniaNeural` / `en-GB`. |

The existing Azure key/region and Groq key are reused. No new account, model
provider or dependency is required. Invalid voice/locale pairs fail before paid
requests. The high accuracy `whisper-large-v3` model remains the default.

In automatic mode the initial Estonian greeting is followed by an English
invitation spoken with Jenny. The caller can start speaking English immediately,
or say “English, please.” Language requests and detected language update the
dialogue and voice together. Numbers, short yes/no answers and saved fictional
guest names retain the active language. There is no permanent transcript/audio
storage. History records the effective language and closed outcome codes.

The pinned Groq LiveKit plugin requests ordinary JSON, which omits Whisper's
detected language. `TelephoneSTT` implements the public LiveKit STT interface and
requests Groq `verbose_json` directly through async HTTP. LiveKit still supplies
VAD streaming adaptation, metrics, bounded retries and cancellation. No expected
booking or consent words are supplied as a recognition prompt. High-confidence
silence metadata with poor recognition scores suppresses a hallucinated
transcript; this is a conservative heuristic, not a guarantee of acoustic accuracy.

English numeric dates such as `10/11/2026`, or a booking request “at ten” without
AM/PM, require clarification before booking tools can run. Recaps speak explicit
English dates, AM/PM times and Tallinn local time while preserving backend
service, provider, room and fictional guest names. Missing details are requested
one at a time using approved questions. Relative dates use the current Tallinn
date. These checks improve handling of ambiguity; they do not establish a
measured speech accuracy or latency advantage over Estonian.

## Confirmation and failure behavior

The English consent prompt is “Yes, I confirm.” Confirmation needs an owned
prepared hold, a complete uninterrupted recap and a subsequent explicit final
caller commitment. A bare “yes,” question, mixed yes/no response, expired hold,
interim recognition result or another call's ID cannot authorize a booking.
“Please cancel this test booking” cancels only the latest owned booking in this
call. Writes still use the existing durable journals and idempotency rules.

A language-only request during a pending proposal repeats the same recap in the
new language and resets delivery/approval. A commitment in a different language
cannot approve the earlier recap. An uncertain backend write locks further
mutations and produces an English explanation. Backend errors cannot select a
successful booking phrase, and model prose cannot substitute for a receipt.

The native worker has an independent English PCM failure message, so a failed
Azure request does not trigger another synthesis request. The Twilio bridge
uses a cached bilingual message when the caller's language is still unknown.
Its historical `/api/twilio/unavailable-et.wav` URL is retained; the served asset
now contains both languages and remains under the existing ten-second limit.
English fallback audio was generated offline with Windows Microsoft Zira; it
contains no caller recording and is distinct from the live Azure Jenny voice.

HTTP demo turns can use `language: "en"`. Their stateless Azure voice view keeps
simultaneous English and Estonian turns from changing each other's voice.
`/api/status` describes configuration, including the language mode and English
voice; it does not prove the separately deployed worker's revision or readiness.

## Deploy the telephone worker

GitHub/web application deployment does not rebuild the separate telephone
worker or Twilio bridge. Use existing protected server credentials and the exact
shared persistent `/data` volume identified by `manage.py`. Do not create a new
booking volume or print expanded Compose configuration.

After updating the server checkout to the reviewed GitHub revision and waiting
for active calls to finish:

```sh
python3 deploy/telephony/manage.py validate --source-container "$VOICEBOT_WEB_CONTAINER"
python3 deploy/telephony/manage.py build --source-container "$VOICEBOT_WEB_CONTAINER"
python3 deploy/telephony/manage.py up --source-container "$VOICEBOT_WEB_CONTAINER"
python3 deploy/telephony/manage.py up --twilio --source-container "$VOICEBOT_WEB_CONTAINER"
```

`manage.py` preserves optional English voice and mode settings from the trusted
web container. Compose defaults enable both languages if those optional values
are absent. The bridge shares the rebuilt image for its bilingual fallback.

## Verification

Local policy/provider fixtures verify recognition request shape, language
metadata, English dialogue and voice selection, spa/room writes and cancellation,
expired/foreign/interrupted/undelivered consent, language switching, unknown
writes, provider failure, in-flight cancellation and independent fallback PCM.
These fixtures do not contact Groq/Azure or the telephone carrier.

With the private worker running and protected credentials available, the
conversation probe performs actual synthetic caller audio, a spoken English
recap, decline without a write, consent, independent exact date/time backend
readback and cancellation. It cleans only its own fictional records. This uses
paid provider capacity and remains a private-room check, not PSTN verification:

```sh
python deploy/telephony/conversation_probe.py --source-container livekit-worker-1 --language en
python deploy/telephony/conversation_probe.py --source-container livekit-worker-1 --language et
```

Then make an actual incoming call to the configured phone number. Check English
and Estonian speech, language changes, AM/PM/date clarification, a full recap,
decline, confirmation, receipt readback, cancellation, interruption and clean
disconnect. Until those calls pass, live English behavior is unverified.

Provider references: [Groq speech-to-text](https://console.groq.com/docs/speech-to-text),
[LiveKit STT plugins](https://docs.livekit.io/agents/models/stt/),
[LiveKit Groq](https://docs.livekit.io/agents/models/stt/plugins/groq),
[Azure voice language support](https://learn.microsoft.com/en-us/azure/cognitive-services/speech-service/language-support).
