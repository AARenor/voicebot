# Selectable modern demo voices and incremental audio

## Intent and scope

Add newer voice choices to the existing operator-authenticated website demo and
reduce avoidable response delay. Preserve the existing Azure default, exact
server-approved booking replies, consent, ownership and completed-playback
receipts. Keep the ordinary JSON turn API compatible. Do not provision accounts,
clone voices, modify a carrier, or operate another session's native release goal.

Starting repository revision: `ec2d6c9`. New provider credentials are absent from
the inspected healthy web container; Azure and operator authorization are
configured. Configuration is not a live quality or latency benchmark.

## Approaches

1. **Chosen: optional providers plus streaming through the existing guarded turn.**
   Reuse the same STT, tools, truth/price guard and receipt logic; change only TTS
   selection and transport. This improves Azure too and keeps adoption reversible.
2. Voice-only replacement with the existing fully buffered response is smaller,
   but leaves the measured code-level 1.5-second silence wait and full-audio delay.
3. A speech-to-speech/realtime-agent replacement adds a second dialogue authority
   and could paraphrase bookings. It is outside this request and is rejected.

## Provider boundary

- Provider clients expose synchronous `synthesize(text) -> bytes`, optional
  `stream(text) -> iterable[bytes]`, `for_language(language)` and `close()`.
  Language views do not mutate a shared client. Browser audio is always MP3 with
  its real MIME type; no partial WAV decoder or raw-PCM browser subsystem.
- Azure retains its current 48 kHz / 96 kbps mono format, language voices and
  speech delivery. Add real REST byte iteration without changing ordinary synthesis.
- ElevenLabs uses the documented dialogue WebSocket with `eleven_v4_turbo`, one
  configured licensed voice, header authentication and `mp3_44100_128`. It decodes
  audio envelopes and requires terminal completion; premature EOF is failure.
  Do not invent a v4 Turbo HTTP route, forced-language field or voice ID. The
  current guide/reference discrepancy remains an explicit live-validation caveat.
- Google uses documented Chirp 3 HD REST synthesis for `et-EE`, `en-US`, `ru-RU`,
  with MP3 output. This mode is **buffered provider synthesis**, not native Google
  streaming. Keep the supported gRPC/raw-PCM streaming client out of the browser
  integration. Use a short-lived environment-supplied OAuth credential or official
  refreshing ADC, preferring workload identity; never create a service-account key.
- Cartesia uses the documented streamed `/tts/bytes` contract, bearer header,
  `Cartesia-Version: 2026-08-14`, snapshot `sonic-3.6-2026-08-27`, normalization
  off and MP3 output. It is available for English/Russian, not Estonian.
- Add only dependencies necessary for the verified protocols: pinned `websockets`
  and official `google-auth` with its supported HTTP refresh transport. No new
  frontend or gRPC dependencies and no custom OAuth signing implementation.
- Bound text, audio bytes, socket messages and provider timeouts. Errors exposed
  to callers are closed reason codes, never response bodies, URLs or credentials.

## Selection and readiness

A server-owned catalog exposes opaque profile IDs (`azure`, `elevenlabs`,
`google`, `cartesia`), labels, supported languages, configuration readiness,
transport capability and closed unavailability reasons. Protect it with the
same operator authorization and private/no-store policy as other demo APIs.
Do not expose credentials or claim a configured profile is operational.

The session-start body accepts a validated `voice` choice and stores it on the
owned session. The selector locks for the session lifetime, like language.
Default remains Azure; selected modern providers cover the greeting and turns.
Detected unsupported languages use Azure with explicit effective-voice metadata.
A modern provider failure may fall back once **before audible chunks are sent**;
failure after partial output stops the stream, reports failure and grants no
recap receipt. It never re-executes STT, model planning or booking writes.

## Incremental turn protocol

Negotiate NDJSON with `Accept: application/x-ndjson` on the existing `/api/turn`.
Authorization, bounded parsing, input validation, ownership/busy checks and
private response middleware remain before provider execution. JSON callers keep
the existing response. The new protocol consists of:

1. `reply`: final guarded text and language, emitted only after canonical truth
   and price normalization. Do not publish provisional model tokens.
2. Ordered `audio` events containing bounded base64 MP3 chunks and sequence IDs.
3. `done`: the canonical existing turn response and safe effective-voice/timing
   metadata, without duplicating full audio. Only this event can carry a new
   `recap_delivery_id`, and only for successful complete nonempty synthesis.

One request-local wrapper emits chunks while collecting the actual bytes returned
to existing synthesis/receipt logic. No fake success byte or second dialogue
pipeline. A bounded queue bridges synthesis threads and the event loop. The
producer owns final session release; disconnect disables emission and invalidates
the current delivery receipt but cannot immediately unlock or replay an in-flight
write. Producer work remains tracked and bounded through cleanup/shutdown.

## Browser behavior

Add a native labeled voice selector beside the existing language selector and
show unconfigured choices disabled with clear setup guidance. Use safe text DOM
construction, existing styles, keyboard focus and responsive layout. No redesign.

Read NDJSON with authenticated fetch; never put operator credentials in an audio
URL. Where `MediaSource.isTypeSupported('audio/mpeg')` is true, append serialized
MP3 buffers and begin playback before provider completion. Otherwise collect
bounded bytes and reuse native Blob/audio playback. Failed/incomplete streams
never retry the POST automatically or silently turn partial audio into success.

Playback completion requires successful `done`, complete queued appends/EOF,
actual played coverage and current generation/session/audio identity. Seeking,
underrun, blocked play, truncation, interruption or stale completion cannot arm a
receipt. Logout/end/voice changes retire the playback epoch, abort consumption,
detach callbacks and release readers/source buffers/object URLs.

Default energy silence endpointing becomes 650 ms with a bounded validated
setting, retaining the 200 ms voiced minimum, reset on resumed speech, manual
stop and 15-second cap. This remains energy endpointing, not semantic VAD.
Tests cover initial silence, brief pauses, resumed speech, sample-rate block
quantization, one submission and stale permission/encoding/timer races.

## Verification and rollout

Observe RED/GREEN provider wire, routing, receipt and streaming tests before code.
Test first chunk before blocked synthesis completion, failures before/after audio,
unsupported languages, unavailable/foreign/busy sessions, logout and disconnect.
Run the complete core and pinned-media suites plus existing and new browser
fixtures with advancing synthetic audio; independently review and repair findings.

Commit/push intended secret-free files through normal master integration. The
existing signed webhook deploys the web application automatically; verify its
exact revision, health, same `/data` volume and anonymous privacy boundary.
Verify Azure first-audio behavior using synthetic non-booking text when safe.
New provider audition remains conditional on credentials; subjective naturalness
and PSTN/native acceptance are distinct from tests or web deployment.

## Primary implementation contracts (retrieved 2026-10-03)

- https://elevenlabs.io/docs/eleven-api/guides/how-to/websockets/realtime-tdd.md
- https://elevenlabs.io/docs/overview/models.md
- https://docs.cloud.google.com/text-to-speech/docs/chirp3-hd
- https://docs.cloud.google.com/text-to-speech/docs/reference/rest/v1/text/synthesize
- https://docs.cloud.google.com/docs/authentication/application-default-credentials
- https://docs.cartesia.ai/api-reference/tts/bytes
- https://docs.cartesia.ai/build-with-cartesia/tts-models/latest

Self-review: interfaces, profile scope, Google buffering, fallback after partial
audio, disconnect ownership and playback receipt boundaries are explicit. No
unimplemented protocol is labeled native streaming or operational.
