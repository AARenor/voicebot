# Modern website voices and response delay

## Scope and selection

This feature belongs to the operator-authenticated website demo, not the separate
telephone worker. Azure remains the default and fallback. Choose a configured
voice before starting a conversation; voice and initial language are fixed for
that owned session. End it to choose another profile.

The catalog at `GET /api/demo/voices` requires operator authorization. It contains
only profile labels, supported languages, configuration/dependency readiness and
transport capability. An available configuration is **not** evidence of a live
successful provider request, native pronunciation, or a human listening preference.
Unconfigured profiles are disabled in the selector rather than silently enabled.

| Profile | Languages | Browser delivery |
| --- | --- | --- |
| Azure (existing) | Estonian, English, Russian | Incremental REST MP3; retains current voices, pronunciation and 48 kHz / 96 kbps output. |
| ElevenLabs v4 Turbo | Estonian, English, Russian | Documented dialogue WebSocket MP3; requires a configured licensed voice and provider acceptance validation. |
| Google Chirp 3 HD | Estonian, English, Russian | Buffered REST MP3; this integration does not claim Google's gRPC native streaming. |
| Cartesia Sonic 3.6 | English, Russian | Incremental HTTP MP3; automatic Estonian turns use Azure and report the fallback. |

All profiles receive the same final guarded reply. They cannot choose prices,
rewrite recaps, execute bookings or supply consent. Provider failure can fall
back to Azure before output begins. Failure after partial streamed audio stops
delivery and cannot issue a completed-recap receipt; it does not rerun booking
operations or automatically retry the turn POST.

## Runtime configuration

Supply credentials through protected server environment storage. Never paste
them into source, notes, committed environment files, browser settings or logs.
`.env.example` lists names with blank credential values.

- **ElevenLabs:** `ELEVENLABS_API_KEY` and `ELEVENLABS_VOICE_ID`. Select a licensed
  voice suitable for the target language; model language coverage does not prove
  every voice pronounces Estonian names well. The integration uses
  `eleven_v4_turbo`, one voice per connection and header authentication. It does
  not create a clone or infer an unverified Estonian library voice ID.
- **Cartesia:** `CARTESIA_API_KEY` and `CARTESIA_VOICE_ID` (a valid configured
  UUID). The model snapshot is `sonic-3.6-2026-08-27` and API version is
  `2026-08-14`. Estonian is not in its supported language list.
- **Google:** prefer `GOOGLE_TTS_USE_ADC=1` with officially managed Application
  Default Credentials, such as workload identity federation or an attached
  service account. The official authentication library refreshes short-lived
  credentials; merely naming an ADC file does not make an arbitrary HTTP client
  refresh it. An externally supplied `GOOGLE_TTS_ACCESS_TOKEN` is supported for
  temporary evaluation, but expires and requires external refresh/redeployment.
  `GOOGLE_CLOUD_QUOTA_PROJECT` supplies the quota project where required. Never
  create or commit a service-account private-key file for this feature.
- Google's voice names are configured by `GOOGLE_TTS_ET_VOICE`,
  `GOOGLE_TTS_EN_VOICE`, `GOOGLE_TTS_RU_VOICE`, defaulting to the respective
  locale's `Chirp3-HD-Kore`. The locale and HD voice family must match.

The documented ElevenLabs realtime guide explicitly supports v4 Turbo while its
WebSocket reference still contains v3-only wording. The implementation uses the
documented v4-aware guide, not an invented HTTP route or forced-language field.
Confirm account access and endpoint acceptance before relying on it for a pilot.
No new provider credentials are manufactured or copied from another account.

Restart/redeploy the web process after configuration changes. The signed GitHub
master webhook remains the code deployment path. Preserve the existing shared
`/data` volume; new voice selection does not need a database or storage migration.
The private native worker continues to use its existing Azure configuration and
requires its own release and acceptance verification.

## Incremental browser audio and endpointing

The browser negotiates NDJSON on the existing authenticated `POST /api/turn`:
final guarded reply, ordered MP3 chunks, then the canonical terminal result. A
recap receipt appears only in a successful terminal result. JSON callers retain
the buffered contract. Provider credentials never reach the browser.

Supported browsers use native MP3 MediaSource append/playback before synthesis
finishes. Other browsers use bounded native Blob playback after completion. No
operator credential is placed in an audio URL. Logout and interruption abort
stream consumption, invalidate late callbacks and release media resources.

Audio receipt acknowledgment requires complete successful delivery and actual
full playback, not the first chunk, a seek to the end, an underrun, synthesis
alone or a stale `ended` event. A later explicit consent turn is still required.
The existing explicit text-reading acknowledgment remains distinct from audio.

`VOICEBOT_MIC_SILENCE_MS` defaults to 650 ms, replacing the older 1.5-second
silence wait. Values from 300 to 2,000 ms are accepted; invalid values use 650 ms.
It is a bounded energy detector, not semantic voice activity
detection: brief pauses, resumed speech, initial silence, the 200 ms voiced
minimum, manual stop and 15-second cap remain important. Test it in the intended
room and adjust within its validated range if pauses are cut off.

A stalled audio consumer is retired after the bounded 120-second transport
lifetime. This stops emission, not an in-flight booking operation or synthesis;
owned work drains before session release. A late disconnect callback cannot
invalidate a later turn's recap receipt.

## Verification and honest latency comparisons

Use synthetic hotel phrases only for audition, including Estonian names,
arrival/departure dates, clock times, exact prices, repeat requests and explicit
confirm/decline wording. Do not perform a real guest booking during a voice test.

Measure from **finished speaking to first audible response** as well as provider
first-chunk and full synthesis timings. Network, recognition, planning/tools,
endpointing and browser playback are additional costs. ElevenLabs' advertised
~100 ms is model inference excluding application/network delay; it is not a
promise of caller-to-audible response time or a measured result for this app.

Wire-level fixtures verify payloads, selection, partial failures, cancellation and
receipt authority. Advancing synthetic audio in a local browser verifies playback,
not provider pronunciation or human preference. New live providers and telephone
calls are acceptance boundaries to record separately, never inferred from a
healthy web deployment or configured catalog.

To roll back voice selection, use Azure for the next session. To roll back speech
styling, follow the [neutral profile](natural-conversation.md). Keep the provider
credentials out of diagnostics; report only profile IDs, fixed reason codes and
bounded timing metadata.

Primary contracts checked 2026-10-03:
[ElevenLabs models](https://elevenlabs.io/docs/overview/models),
[realtime dialogue guide](https://elevenlabs.io/docs/eleven-api/guides/how-to/websockets/realtime-tdd),
[Google Chirp 3 HD](https://docs.cloud.google.com/text-to-speech/docs/chirp3-hd),
[Google REST synthesis](https://docs.cloud.google.com/text-to-speech/docs/reference/rest/v1/text/synthesize),
[Google ADC](https://docs.cloud.google.com/docs/authentication/application-default-credentials),
[Cartesia bytes API](https://docs.cartesia.ai/api-reference/tts/bytes),
[Cartesia model snapshots](https://docs.cartesia.ai/build-with-cartesia/tts-models/latest).
