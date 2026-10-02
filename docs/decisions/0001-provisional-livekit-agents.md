# ADR-0001: Provisionally use LiveKit Agents as the call runtime

- Status: **Implemented private pilot — full release acceptance still gated**
- Date: 2026-09-30

## Context

The system already selected self-hosted LiveKit SIP. Earlier plans also listed
Pipecat, but no real-time worker exists and maintaining two orchestration
frameworks would duplicate media buffering, endpointing, lifecycle, tools, and
failure handling.

## Decision drivers

- native SIP room dispatch and agent assignment;
- process-per-call isolation and worker load/drain support;
- Groq, Azure Speech, and Silero plugins;
- smallest support and deployment surface for a one-week hackathon;
- framework-independent booking and safety policy.

## Considered options

1. LiveKit Agents only.
2. Pipecat pipeline using LiveKit transport.
3. LiveKit Agents plus Pipecat.
4. Custom room/audio worker.

## Decision outcome

Provisionally choose option 1. Reject option 3 unless a named component gap is
proved. Option 2 remains the fallback if the spike shows LiveKit Agents cannot
meet Estonian turn-taking or provider requirements. Option 4 has the highest
implementation and reliability cost.

## Consequences

- Good: one room/job lifecycle, native capacity exchange, process isolation,
  graceful drain, fewer dependencies.
- Good: tool wrappers can reuse existing validation, price gates, and adapters.
- Bad: tighter coupling to the LiveKit agent API and plugins.
- Bad: crash redispatch cannot restore process-local conversation/hold state.
- Risk: provider latency has no production distribution; real carrier endpointing,
  carrier overflow and full spoken-consent booking remain unverified. Private
  room barge-in, isolated provider failure and worker drain now have evidence.

## Confirmation

2026-10-02: Python 3.12 / Agents 1.8.4 / RTC 1.1.20 pilot is deployed. Actual
Estonian audio in/out, two isolated concurrent room jobs, authenticated synthetic
SIP dispatch/greeting RTP, native SDK booking/read/cancel, spoken interruption,
forced Azure audible fallback and graceful drain have evidence. See
`docs/evidence/2026-10-02-private-telephone-runtime.md`. These do not prove public
reachability, real carrier operation, or every release check below.

Accept this ADR only after a pinned-version spike passes all six checks in
`ARCHITECTURE.md` section 4, including two concurrent calls, Estonian audio,
barge-in, forced provider failure, and graceful drain. Until then dependency
and image choices remain provisional.

## Revisit trigger

Revisit when the spike fails a required capability or when Pipecat demonstrates
a measured material improvement that outweighs the second runtime.
