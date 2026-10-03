# Concurrent calls: isolation, limits, and scaling

Decision snapshot: **2026-09-30**. This document defines how the voicebot must
handle multiple callers without mixing conversations, double-booking, or
overloading speech/LLM providers.

## Executive decision

- One inbound call gets one unique LiveKit room, one agent job, one isolated
  agent subprocess, and one call-scoped conversation/booking context.
- The hackathon admission limit is **3 simultaneous calls**. The fourth call
  must overflow to a human, carrier queue, or voicemail; it must not ring
  indefinitely or enter a half-working bot session.
- The carrier/SIP edge provides the hard three-channel admission cap, while
  LiveKit SIP advertises matching routing capacity and the agent worker applies
  the same job limit. Do not assume `max_active_calls` alone rejects call four;
  current LiveKit source describes it as affinity-based and it must be tested.
- Keep the dashboard/API at one Coolify replica while holds, demo commands,
  FAQ writes, and the call log are process-local/SQLite. Scale agent workers
  separately. Redis/Postgres are required before scaling stateful components.
- Booking systems remain the source of truth. Availability is rechecked at
  confirmation, writes carry idempotency keys, and a race for the last room or
  slot produces one winner and a fresh-alternatives response for the other
  caller.

## Current state — do not overclaim

The deployed `/api/turn` path already offloads blocking STT, LLM, and TTS calls
from the event loop (`app/turn.py`) and has a concurrent-turn regression test.
On 2026-09-30, three concurrent production text turns all returned HTTP 200
with generated audio in **3.09 seconds wall time** (individual completion times
1.77s, 2.07s, and 3.06s). Command and sanitized output:
[`../evidence/2026-09-30-http-concurrency-smoke.md`](../evidence/2026-09-30-http-concurrency-smoke.md).

That does **not** mean three phone calls work today:

- LiveKit and LiveKit SIP run internally, but SIP/RTP ports are not public.
- No carrier inbound trunk or dispatch rule exists yet.
- The continuous LiveKit Agents worker is not implemented; Pipecat is not in
  the provisional path, and ADR-0001 option 2 is fallback only if the spike
  rejects LiveKit Agents;
  `app/pipeline.py` still describes Phase 2 wiring.
- The web app runs one Uvicorn worker and one Coolify replica.
- `HoldLedger` is thread-safe in one process but explicitly loses state on
  restart and cannot coordinate replicas (`app/booking/base.py`).
- The dashboard's demo command store and SQLite connections are process-local.

## Target call path

```text
PSTN caller
  -> carrier channel
  -> carrier/SIP-edge admission (3 channels)
  -> livekit-sip capacity signal (max_active_calls = 3)
  -> SIP individual dispatch rule (roomPrefix = "call-")
  -> unique room call-<random suffix>
  -> named LiveKit agent job
  -> isolated agent subprocess + AgentSession
  -> STT -> LLM/tools -> booking API -> TTS
  -> audio only to that caller's room
```

LiveKit's individual dispatch rule creates a different room for every caller.
The agent server automatically balances jobs across registered workers and
spawns a subprocess for each job. This is the primary conversation and failure
isolation boundary.

Official references:

- [Individual SIP dispatch rules](https://docs.livekit.io/telephony/accepting-calls/dispatch-rule/)
- [LiveKit agent server and worker pools](https://docs.livekit.io/agents/server/)
- [Self-hosted agent deployments](https://docs.livekit.io/deploy/custom/deployments/)
- [LiveKit SIP resource-limit configuration](https://github.com/livekit/sip/blob/main/pkg/config/config.go)

## Call-scoped state

Each agent job constructs a new `CallContext` containing only that call's:

- LiveKit room and SIP call ID;
- masked caller identity;
- language and disclosure/recording consent state;
- conversation history;
- active price quote/hold IDs;
- tool-call and booking idempotency namespace;
- transfer/handoff state;
- per-call deadline and turn count.

Do not store conversation history, current guest details, or active holds in a
module global. Read-only FAQ data and immutable property configuration may be
shared. Provider HTTP connection pools may be shared only if the client is
documented thread-safe; otherwise create one client per job process.

Room names use a random suffix rather than a raw telephone number. Logs retain
only the existing masked peer representation.

## Admission control and overload behavior

Three limits must agree:

1. **Carrier channels:** at least three simultaneous inbound channels.
2. **LiveKit SIP:** configure `max_active_calls: 3` and a conservative
   `max_cpu_utilization` before exposing SIP publicly. In current source,
   `max_active_calls` controls service affinity/routing capacity; verify whether
   it rejects excess calls in this single-instance inbound topology.
3. **Agent workers:** a load function marks the worker unavailable at three
   active jobs; `num_idle_processes` prewarms job processes to avoid cold-start
   delay.

The room setting `max_participants: 50` is not a call limit. Calls use separate
rooms, normally with one SIP participant and one agent participant each.

When capacity is full:

1. reject/decline the new bot call at the carrier or SIP edge promptly;
2. let the carrier route it to the receptionist, a short queue, or voicemail;
3. emit an `over_capacity` metric;
4. never accept the call and then leave the caller in silence.

For the hackathon, configure the carrier to three channels with overflow. If
the carrier cannot enforce that policy and fourth-call testing shows LiveKit's
capacity signal is not a hard gate, put a minimal SBC (Asterisk, Kamailio, or
OpenSIPS) in front of LiveKit to enforce active-dialog admission.

Global Call Forwarding documents that one SIP channel carries one concurrent
call and advertises 10-channel SIP trunks, but the Estonia trial number's
included channel count is not public. Confirm it after account approval. A
single-channel carrier product prevents concurrency before LiveKit is reached.

Carrier reference:
[Global Call Forwarding SIP trunking](https://www.globalcallforwarding.com/sip-trunking/).

## Why the hackathon cap is three

Provider limits are organization/resource-wide, not per caller. The following
table and three-call calculation describe the original 2026-09-30 pilot.
The 2026-10-03 defaults use `openai/gpt-oss-120b` and `whisper-large-v3`;
their actual account quotas must be checked before applying this calculation
or increasing concurrency. This historical table is not current capacity proof.

| Historical provider path | Recorded base limit |
| --- | --- |
| Groq `openai/gpt-oss-20b` | 30 RPM, 1,000 RPD, 8,000 TPM, 200,000 TPD |
| Groq `whisper-large-v3-turbo` | 20 RPM, 2,000 RPD, 7,200 audio sec/hour, 28,800 audio sec/day |
| Azure Speech TTS F0 | 20 transactions per 60 seconds |

Sources:

- [Groq rate limits](https://console.groq.com/docs/rate-limits)
- [Azure Speech quotas and limits](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/speech-services-quotas-and-limits)

The dialogue loop can issue up to three LLM calls for one user turn (initial
response plus two tool rounds). A conservative fast-conversation bound is:

```text
3 callers × 3 user turns/minute × 3 LLM requests/turn = 27 LLM RPM
3 callers × 3 user turns/minute = 9 STT RPM and 9 TTS requests/minute
```

That calculation left little LLM burst headroom below 30 RPM, so the original
three-call cap was a ceiling, not a target average. Its proposed Redis-backed
provider token bucket was 27 LLM RPM,
18 STT RPM, and 18 TTS requests/60s so isolated job subprocesses share one
budget. Honor `retry-after` on 429 responses.

The live Groq key returned request-limit headers matching 1,000 RPD and 8,000
TPM on 2026-09-30. Exact account limits must still be read from Groq's Limits
page because organizations can differ.

Additional guardrails:

- maximum call duration: 10 minutes for the hackathon;
- maximum user turns: 20;
- one in-flight turn per call;
- at most two tool rounds (already enforced by `app/turn.py`);
- pre-render static overload, repeat, and handoff prompts so provider failure
  does not require another TTS request;
- configure the secondary LLM before public testing; it is currently absent.

## Booking races and idempotency

Two callers may ask for the same last room or treatment slot. Correct behavior:

1. Search returns an offer/slot snapshot with provider ID and expiry.
2. A hold uses a call-scoped random ID and a ten-minute TTL.
3. Confirmation re-reads live provider availability and price.
4. The write uses an idempotency key such as
   `<provider>:<room>:<tool-call>:confirm`.
5. The PMS/booking system's unique inventory transaction decides the winner.
6. A conflict returns `no_longer_available`; the bot offers fresh alternatives.

The current in-memory `HoldLedger` has an `RLock` and blocks concurrent
same-key submits within one process, but it is not sufficient for agent
subprocesses or replicas. Before multi-worker booking writes:

- move holds, pending keys, memo data, and idempotent results to Redis;
- use an atomic `SET key value NX EX <ttl>` reservation/lock;
- namespace by provider/property and booking action;
- reconcile unknown retry outcomes by reading the PMS before repeating a POST;
- keep the PMS/booking system as inventory truth, never Redis.

## Persistence and scaling boundaries

### Hackathon

- one LiveKit SIP instance, capped at 3 calls;
- one registered agent server, up to 3 active job subprocesses;
- one dashboard/API replica;
- external Groq/Azure providers;
- Redis for LiveKit, provider rate limits, and—before real booking
  concurrency—holds/idempotency;
- carrier overflow to a human or voicemail.

### Pilot

- paid/increased provider quotas;
- confirmed carrier channel count (for example 10);
- two or more agent worker replicas registered with LiveKit;
- Redis-backed state and provider rate limiter;
- Postgres call/event log, or an internal single-writer log service;
- health and Prometheus endpoints on LiveKit SIP;
- pinned LiveKit server/SIP image versions instead of mutable `latest` tags.

### Production

- multiple SIP and agent instances sharing Redis;
- autoscale agent workers from active jobs, CPU, and turn latency;
- regional redundancy and carrier failover;
- per-property and per-provider concurrency budgets;
- tested graceful drain so deployments do not terminate active calls.

Do not add Coolify web replicas before moving state out of memory/SQLite. Agent
workers are a separate deployment and can scale independently from the web UI.

## Observability

Record these without unmasked phone numbers or raw provider credentials:

- active and admitted calls;
- carrier/SIP rejections and overflow calls;
- agent jobs active, queued, rejected, and drained;
- setup-to-first-audio latency p50/p95;
- STT, LLM, TTS request counts and 429s;
- calls by outcome: booked, answered, transferred, fallback, failed;
- booking conflicts and idempotent replay count;
- provider latency and error rate;
- call duration and turns per call.

Alert before limits, not after: active calls >= 3, LLM RPM >= 27, STT RPM >=
18, TTS requests/60s >= 18, any provider 429 burst, or any booking duplicate.

## Verification plan

1. Keep the existing concurrent `/api/turn` test and live three-request smoke.
2. Add a call-session isolation test: different rooms, histories, guests, and
   holds never cross.
3. Add a same-slot race test: two confirmations produce one booking.
4. Use SIPp or three real phones to place three simultaneous inbound calls.
5. Place a fourth call and verify deterministic carrier overflow.
6. Force Groq/Azure 429 responses and verify wait prompt/fallback/handoff.
7. Restart/drain one agent worker during a call and verify no duplicate booking.
8. Run a 30-minute three-call soak; check latency, memory, media, and logs.

No concurrency claim is production-ready until steps 2–8 pass with the actual
carrier and booking system.

Open release blockers outside pure capacity (public call summaries, payment
fields, caller ownership, same-slot safety, and truthful readiness) are tracked
in [`../architecture/risk-register.md`](../architecture/risk-register.md).
