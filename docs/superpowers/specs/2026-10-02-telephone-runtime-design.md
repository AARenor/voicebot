# Telephone runtime — BUILD design

## Outcome and scope

Finish the synthetic spa voicebot's missing continuous media path. DIDWW is the intended replaceable carrier, not an application dependency. No number purchase or provider account changes. A real carrier call and public NAT forwarding remain explicit external gates until independently verified.

## Evidence and chosen approach

The host has LiveKit server 1.13.7, SIP 1.17.0 and Redis running privately on the `coolify` Docker network. They expose no host media ports; no agent worker exists. The host has only LAN/Tailscale addresses. Existing Groq/Azure HTTP turns and Easy!Appointments remain operational.

Three approaches considered:

1. **Native LiveKit Agents with provider plugins (chosen).** One isolated job per call, native VAD/interruption/lifecycle, reuse Dispatcher and price validation. This is the existing architecture's minimal media runtime.
2. Custom WebRTC loop around HTTP `run_turn`: duplicates playout, turn detection and cancellation; reject.
3. New hosted bot/PBX or another framework: adds migration, cost and duplicated state; reject unless a measured capability gap appears.

## Worker

Separate worker image with exactly pinned tested LiveKit Agents/Groq/Azure/Silero packages. One call-scoped adapter/Dispatcher and history per job; the Easy journal uses the same persistent host volume as HTTP, preserving cross-process write locking. Limit concurrent jobs and total call duration. Start only with complete provider/media configuration and explicit synthetic-demo opt-in.

Expose only operational slot tools. A small bridge delegates validation/execution to Dispatcher, but rejects foreign holds/bookings and model-supplied customer IDs. Namespace write keys server-side and keep a stable key for retries of a logical action. Unknown errors are closed codes, not exception strings. Do not claim cancellation of arbitrary previous bookings or a human transfer that is not configured.

Buffer each spoken reply before TTS and apply the existing price gate using that turn's tool results. No unverified price reaches audio. Start in Estonian with Anu, identify as an AI demo, and disclose synthetic appointments. Generic seeded property policies are not available in telephone tools. Store only static lifecycle/outcome events; never transcripts, audio, raw caller attributes or tool arguments. An independently cached static Estonian audio message provides audible fallback if a provider fails.

## Media and SIP

Promote sanitized, digest-pinned Compose/config into `deploy/telephony/`; reuse existing media deployment safely and preserve prior configuration for rollback. Secrets are environment-only, including YAML config bodies supplied through supported `LIVEKIT_CONFIG`/`LIVEKIT_KEYS` and `SIP_CONFIG_BODY` environment variables; never render credential files.

Use private Redis, reachable internal LiveKit API, restricted SIP signaling and RTP, and explicit advertised media addresses. Static DIDWW inbound routing targets a dedicated SIP address, not the HTTP website or Cloudflare web proxy. LiveKit inbound trunks require exact numbers, carrier IP allowlists and digest authentication; dispatch rules bind exact trunk IDs and create unique rooms for the named agent. No public wildcard trunk. A loopback-only synthetic trunk proves SIP dispatch without a purchased number.

Public carrier readiness is not inferred from configuration, host listeners, room audio, or loopback. On this LAN host it also needs router forwarding or another verified public SIP edge. Do not add a paid VPS or broad network changes to conceal this dependency.

## Web privacy and readiness

Authenticate call-summary reads and apply `Cache-Control: no-store` to private API responses, including failures. Stop storing full HTTP turn text in the call log by default. Preserve existing status fields; distinguish configured media from verified worker/dispatch/carrier readiness. No environment flag alone can make a carrier-call proof true.

## Verification contracts

- Failing tests first: credential/demo gates; owned IDs and stable keys; price suppression; closed errors; private/no-store call reads and PII-free logs.
- Real SDK construction/import and worker health; clean-environment config validation with expected nonzero failures.
- Two isolated room jobs with actual audio, Estonian speech recognition/output and interruption/hangup; provider-failure audible fallback and bounded duration.
- Authenticated synthetic SIP INVITE creates the correct unique room/job; unauthenticated/wrong-number requests fail closed.
- Synthetic backend booking/cancel is independently verified and cleaned up. Full relevant repo checks and one independent diff review before delivery.
- Number/account activation, public NAT reachability and a real DIDWW PSTN call are separate evidence gates, never invented.

## Sources checked 2026-10-02

- DIDWW inbound SIP: https://doc.didww.com/voice/inbound-trunks/creating-a-new-sip-trunk.html (updated 2026-10-01): static host/IP, digest authentication, codec/RTP configuration.
- LiveKit Agents/telephony references are recorded with exact installed API/version evidence in the implementation verification log.
