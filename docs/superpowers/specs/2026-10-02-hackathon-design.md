# Synthetic voicebot hackathon — BUILD design

## Scope

A disclosed fictional Estonian spa demo on the existing LiveKit/Groq/Azure and
Easy!Appointments stack. No real-property promises, number purchase, outbound
calls, paid infrastructure, notifications, or public wildcard media exposure.

## Minimal product

- Load approved fictional profile/FAQ/guest fixtures from the saved JSON, never
  its example bookings or stale dates as availability. The agent resolves live
  service/provider IDs and uses actual backend availability.
- Use a fictional guest fixture instead of asking a presenter for real contact
  data. Prepare an owned held slot and recap before confirmation. A deterministic
  gate requires a subsequent affirmative final user transcript; model-supplied
  consent cannot authorize a write. Approval is bound to the specific fully
  delivered recap, not merely preparation. Failed/blocked/interrupted delivery,
  decline or a new proposal invalidates approval. Mutation-success speech must
  be backed by a successful current write; an old receipt after cancellation is
  not a new booking.
- Booking status speech is server-rendered from this turn's authoritative
  mutation receipt, never classified from model prose or licensed by an older
  receipt. Otherwise speak only approved fictional FAQ/static guidance. Unknown
  mutations persist as uncertain for the entire conversation and cannot be
  retried or described as confirmed on a later turn.
- Native authorization observes the SDK's completed, aggregated user-turn
  transcript before reply generation, not each individually final STT fragment.
  Allow a short natural pause at dates/names without ending a caller's turn;
  VAD interruption remains immediate.
- Native sequential ASR controls support the exact short commitments
  `Jah, kinnitan.` and `Jah, tühista.` at both default and shorter VAD pre-roll.
  Use the short canonical confirmation prompt; retain the existing long explicit
  phrases as compatible aliases. The specific target is already bound by owned,
  delivered recap/latest owned booking, not by guessing model arguments. Bare
  yes, negatives and mixed replies are not consent. No spelling/fuzzy matching.
  Keep supported VAD defaults: the pre-roll candidate alone did not prove a
  fix, and no lossless-audio preservation claim is warranted.
- Preserve call ownership, stable write identities, closed errors, no prices and
  no persisted transcripts. Same-call cancellation requires explicit user intent.
- Reuse the current operator dashboard and protected routes. Show live catalogue,
  availability, booking outcomes and truthful telephone readiness. Add a usable
  authenticated fallback demo over the existing HTTP speech/text stack where
  public WebRTC media is not available; never call this a telephone call.
- Prepare an environment-only carrier activation/preflight with exact number,
  source restrictions and digest authentication. Reuse the private SIP proof.
  Public ingress can only be advertised ready with independent outside evidence.

## Acceptance

Real-provider multi-turn speech must produce a synthetic appointment that a
separate REST client can read, then cancel it and verify absence. Browser tests
cover operator authentication, live demo, errors and readiness. Full regression,
independent diff review, deployed source proof and secret hygiene precede ship.

## Alternatives rejected

New frontend framework/PBX/framework migration adds no hackathon value. Importing
example appointments creates stale promises. A prompt-only consent check lets
the model grant itself permission. Cloudflare HTTP reachability is not SIP/RTP.

## Twilio-first carrier update

The user selected an already assigned US Twilio number for the first tests;
Estonian speech and the existing private worker/backend remain unchanged.
The pasted authentication credential is compromised, must be rotated, and is
never retrieved, saved or used. Replacement values are environment-only.

Chosen path: Twilio bidirectional Media Streams over the existing HTTPS/WSS
domain into a small separately deployed carrier adapter, then private LiveKit
room audio into the existing native worker. This avoids creating a public
SIP/RTP edge. Alternative Twilio SIP still needs the unavailable external UDP
route; a hosted PBX or a second dialogue runtime would add unnecessary state.

- Validate fixed-public-URL webhook and WebSocket signatures, the configured
  account and exact destination number. Bind stream start to an opaque one-use
  short-lived webhook nonce before allocating a room/provider job. Never trust
  forwarded host headers or persist caller IDs, audio or transcripts.
- Convert mono 8 kHz mu-law at the transport boundary. Reuse native STT/LLM/TTS,
  ownership, consent, failure and interruption policy; never build a second bot.
- Bound pending/active calls, payloads, call duration and first-audio wait. Clear
  buffered carrier audio on native interruption and independently clean owned
  tracks/tasks/rooms after stop/disconnect/error. Keep APIs and health private.
- Route only `/api/twilio/` through existing Traefik with higher priority than
  the website. Fresh credentials absent means fail closed, not silent readiness.
- TDD protocol/auth/replay/cleanup/codec paths, then a real WSS-to-private-worker
  synthetic wire probe. This proves the adapter, not Twilio/PSTN. Actual account
  webhook configuration and an independent incoming phone call remain separately
  evidenced activation gates; no purchase or outbound call is authorized.
