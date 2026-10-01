# Stack research archive — 2026-09-29

This file preserves the rationale behind architecture draft v0.3. It is
historical research, not current implementation truth. The exact superseded
document remains available in Git commit `c52d948`.

## Findings that still matter

- LiveKit SIP supports self-hosted SIP/WebRTC bridging and individual dispatch
  rules. LiveKit Agents now supplies the process-per-call runtime and is the
  selected agent framework.
- Groq Whisper is a practical Estonian STT path for the hackathon. The
  TalTechNLP Estonian Whisper model remains a self-hosting candidate after
  latency and hardware tests.
- Azure Speech provides supported Estonian neural voices
  `et-EE-AnuNeural` and `et-EE-KertNeural`.
- Hotel-night inventory and appointment-slot inventory require different
  adapter contracts.
- Apaleo, Mews, Cloudbeds, and Zenoti are credible later connectors but require
  property/vendor access and write-path verification.
- QloApps and Easy!Appointments remain open-source demo options; the
  [QloApps webservice documentation](https://devdocs.qloapps.com/webservice/advanced-api-uses)
  (accessed 2026-09-30) supersedes the old claim that no booking API exists.
- Prices may be spoken only from a live provider quote identifier.
- FreeSWITCH/Jambonz/experimental agent gateways were rejected for the initial
  path because LiveKit already covers SIP and adding a second media stack would
  increase operational risk.

## Findings superseded by later evidence

- DIDHub, Telnyx, and Twilio Estonia availability was marketing/coverage, not
  reliable live inventory. The active carrier path is provider-neutral and the
  current number application is with Global Call Forwarding.
- `llama-3.1-8b-instant` was retired. Groq's documented replacement
  `openai/gpt-oss-20b` is deployed.
- The proposed Mistral/Gemini/Groq multi-provider order was never implemented.
  Production currently has Groq only; secondary LLM readiness is an explicit
  gate.
- Pipecat plus LiveKit Agents duplicated call lifecycle responsibilities.
  Architecture v1.0 selects LiveKit Agents only.
- The initial hackathon plan centered on Apaleo/Mews, then a BOUK trial.
  BOUK's API/support is Professional-only, so the final open-source comparison
  selects Easy!Appointments 1.6.0 for a spa-slot demo. QloApps is retained only
  if room-night semantics become mandatory. Both still require deployed write
  tests; see
  [`open-source-booking-backends.md`](open-source-booking-backends.md).
- Pärnu adoption is now evidenced property by property in
  [`parnu-booking-systems.md`](parnu-booking-systems.md), including stale BOUK
  migrations and SALBOS dominance among major spa hotels.

## Research cautions retained

- Vendor pages do not prove inventory, API entitlement, or production quality.
- Search-engine indexing can preserve stale booking engines after a property
  migrates.
- “Free tier” limits change and must be read from the account/provider headers.
- Model benchmark scores do not replace Estonian names, dates, prices, accents,
  noise, barge-in, and human-listening tests.
- No workflow ships from documentation alone; every write path needs real API
  evidence, unhappy-path tests, and a human fallback.
