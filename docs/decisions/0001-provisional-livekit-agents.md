# ADR-0001: Provisionally use LiveKit Agents as the call runtime

- Status: **Proposed — acceptance blocked on spike**
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
- Risk: Estonian endpointing, non-streaming Whisper/Azure latency, barge-in, and
  overload behavior are unmeasured.

## Confirmation

Accept this ADR only after a pinned-version spike passes all six checks in
`ARCHITECTURE.md` section 4, including two concurrent calls, Estonian audio,
barge-in, forced provider failure, and graceful drain. Until then dependency
and image choices remain provisional.

## Revisit trigger

Revisit when the spike fails a required capability or when Pipecat demonstrates
a measured material improvement that outweighs the second runtime.
