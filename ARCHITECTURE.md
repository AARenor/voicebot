# Estonian hotel and spa voicebot — architecture

Status: **v1.0 truth-first architecture, 2026-09-30**.

This document separates what is running from what is planned. A component is
not “ready” because credentials exist or a container starts; it is ready only
after its real workflow passes end-to-end verification.

Historical vendor/model research from the earlier draft is summarized in
[`docs/research/stack-research-2026-09-29.md`](docs/research/stack-research-2026-09-29.md).

## 1. Goal and non-negotiable invariants

The product is an inbound Estonian-language telephone receptionist for hotels
and spas. It must answer routine questions, check live availability, complete
safe bookings, and transfer exceptional cases to a human with context.

Non-negotiable invariants:

1. **No false readiness.** Configured, reachable, and operational are separate
   states.
2. **No invented availability or prices.** Booking systems are the only source
   of inventory and price truth.
3. **No double booking.** Confirmation rechecks provider truth and uses
   idempotency.
4. **No cross-call state.** Every caller has an isolated room, agent session,
   conversation, and booking context.
5. **No dead-end automation.** Unsupported, overloaded, or uncertain workflows
   transfer or fail closed rather than pretending to succeed.
6. **No card data in voice or logs.** Payments use provider-hosted links or
   tokenized flows.
7. **No secrets in source or logs.** Provider credentials live in runtime
   environment storage only.

## 2. Verified as-built status

| Component | Actual state | Operational gate |
| --- | --- | --- |
| Operator web/API | Deployed at `robot.arleserver.cfd`; health endpoint and dashboard work | Healthy production container |
| HTTP voice turn | `POST /api/turn` performs Groq STT/chat and Azure TTS; text and audio paths verified | Working, but not a telephone media loop |
| LLM | Groq `openai/gpt-oss-20b` works, including tool calls | Primary only; no configured secondary |
| Speech | Groq Whisper and Azure `et-EE-AnuNeural` work | Non-streaming HTTP clients |
| FAQ | SQLite FTS repository, thread-safe inside one process | Working |
| Call log | SQLite file, masked peers, 30-day pruning | Single-process only |
| Dashboard commands | Demo queue; writes fail closed outside demo | Not connected to booking-provider commands |
| LiveKit server | Self-hosted server, SIP service, and Redis run on the internal Docker network | Internal connectivity only |
| Public telephone ingress | Carrier account/number is pending; no public SIP/RTP ports, trunk, or dispatch rule | Not operational |
| Continuous call agent | No LiveKit Agents worker; `app/pipeline.py` is a descriptor skeleton | Not implemented |
| Hotel booking | Apaleo, Mews, Cloudbeds, and QloApps drivers are stubs | No operational `StayAdapter` |
| Spa booking | Easy!Appointments driver is implemented but no live instance is configured | No live slot booking |
| Persistent booking state | In-memory hold/idempotency ledger | Lost on restart; cannot coordinate replicas |
| Concurrency | Three concurrent production HTTP turns passed; phone concurrency is untested | Telephone claim remains blocked |

`/api/status` currently reports wiring and derived capabilities. In particular,
`livekit: true` means credentials are configured; it does **not** mean a phone
call can reach an agent. `serving_demo_data: true` remains intentional until
real operator and booking data replace the demo store.

## 3. Target topology

```text
Telephone/media plane

Caller
  -> Estonian DID and carrier channels
  -> public SIP edge / overflow policy
  -> self-hosted LiveKit SIP
  -> individual dispatch rule: call-<random>
  -> LiveKit room
  -> LiveKit Agents worker (one isolated job process per call)
       -> Groq STT
       -> Groq LLM + guarded tools
       -> Azure Estonian TTS
       -> StayAdapter / SlotAdapter

Control/data plane

Operator browser
  -> FastAPI dashboard/API
       -> Postgres: durable call/booking events
       -> Redis: holds, idempotency, admission, provider rate budgets
       -> booking providers: final inventory and booking truth
```

The web/API container is not in the real-time media path. It serves the
operator UI, configuration-safe status, and internal event/command endpoints.
The call worker is deployed separately and scales independently.

## 4. One real-time framework: LiveKit Agents

Use **LiveKit Agents** as the call runtime. Do not put Pipecat and LiveKit
Agents in the same production call path.

Why:

- SIP dispatch already creates and assigns LiveKit rooms.
- `AgentServer` provides job assignment, process-per-call isolation, load
  admission, draining, and horizontal worker balancing.
- `AgentSession` provides turn detection, interruptions, STT/LLM/TTS plumbing,
  and function tools.
- Official plugins cover Groq STT/LLM, Azure Speech TTS, and Silero VAD.
- A second orchestration framework would duplicate lifecycle, buffering,
  endpointing, and failure handling.

The existing `run_turn` HTTP path remains a diagnostic and browser-test path.
The worker should reuse booking validation, FAQ retrieval, PII masking,
idempotency rules, and the price guard—not duplicate business policy.

When the worker lands, remove Pipecat from the active dependency plan and
replace the descriptor-only `app/pipeline.py` with the real LiveKit session
configuration.

Official references:

- [Voice AI quickstart](https://docs.livekit.io/agents/start/voice-ai-quickstart/)
- [Agent server](https://docs.livekit.io/agents/server/)
- [Groq STT plugin](https://docs.livekit.io/agents/models/stt/plugins/groq/)
- [Azure Speech TTS plugin](https://docs.livekit.io/agents/models/tts/plugins/azure/)

## 5. Inbound call lifecycle

1. The carrier admits the call within its purchased channel count. Excess calls
   follow a configured human/queue/voicemail overflow route.
2. LiveKit SIP authenticates the carrier and matches the inbound trunk.
3. An individual dispatch rule creates `call-<random suffix>` and dispatches
   the named agent.
4. A job subprocess creates a call-scoped context and waits for the SIP
   participant.
5. The bot identifies itself as AI and applies the approved recording/consent
   policy before storing any recording or transcript.
6. `AgentSession` runs VAD -> STT -> LLM/tools -> guarded text -> TTS. Barge-in
   cancels only that caller's playout.
7. Booking tools query and write through provider adapters. Guest-facing prices
   are allowed only when tied to the active provider quote.
8. A human-transfer tool sends the caller and a compact context summary to the
   approved destination.
9. Hangup closes the room, releases temporary state, and writes a masked event
   record.

## 6. Multiple callers and capacity

Each caller gets a unique room, agent job process, conversation history, and
booking namespace. No mutable guest or dialogue state is shared.

Hackathon policy:

- admit at most **3 simultaneous calls**;
- cap calls at 10 minutes and 20 user turns;
- share provider budgets through a Redis token bucket;
- send caller four to carrier overflow;
- never accept a caller into a silent room.

The cap follows current free-tier limits: Groq LLM 30 RPM, Groq Whisper 20 RPM,
and Azure Speech F0 20 TTS transactions per 60 seconds. The carrier's trial
channel count remains unknown and may impose a lower cap.

Detailed admission behavior, rate math, booking races, state boundaries, and
load-test gates are in
[`docs/operations/concurrency-and-capacity.md`](docs/operations/concurrency-and-capacity.md).

## 7. Booking architecture

Hotel nights and spa appointments intentionally use different contracts:

```text
StayAdapter
  search_availability(checkin, checkout, party)
  create_hold(price_quote_id)
  confirm(hold_id, guest, idempotency_key)
  cancel(booking_id, idempotency_key)

SlotAdapter
  search_slots(service, date, provider)
  create_hold(slot_id)
  confirm(hold_id, guest, idempotency_key)
  cancel(booking_id, idempotency_key)
```

Shared rules:

- advertise tools only when `operational = True`;
- validate dates, party size, IDs, and guest data before provider calls;
- snapshot provider quotes with a short TTL;
- re-read availability and price immediately before confirmation;
- pass a stable idempotency key to every write where supported;
- after an unknown write outcome, query provider truth before retrying;
- never treat a catalogue scrape or FAQ result as bookable inventory.

### Hackathon provider decision

1. **Preferred single-system demo:** BOUK 14-day trial, only if the trial grants
   documented write API access for rooms and hourly services.
2. **Guaranteed open-source fallback:** QloApps for room nights plus
   Easy!Appointments for spa slots.
3. Do not block the hackathon on Apaleo/Mews partner onboarding.

### Production connector targets

- SALBOS is the strongest Pärnu spa-hotel target.
- BOUK is confirmed at multiple Pärnu accommodation properties.
- D-EDGE is present at Hestia Strand.
- Apaleo/Mews/Cloudbeds/Zenoti remain later generic connectors, not current
  demo dependencies.

Property evidence, safe market claims, and the explicitly modelled summer
missed-call opportunity are in
[`docs/research/parnu-booking-systems.md`](docs/research/parnu-booking-systems.md).

## 8. State ownership and persistence

| State | Current | Target | Authority |
| --- | --- | --- | --- |
| Conversation and consent | Request/call memory | Agent subprocess, destroyed at end | Call context |
| Holds and idempotency | Process memory | Redis with TTL and atomic reservation | Booking provider on confirm |
| Provider rate budgets | None | Redis token buckets | Provider headers/limits |
| FAQ content | SQLite | Postgres or controlled content store | Property-approved content |
| Call/booking events | SQLite | Postgres | Append-only application events |
| Dashboard queue | Demo memory | Projection from durable events/provider state | Provider + event store |
| Room/slot inventory | External when connected | External only | PMS/booking system |

Keep one FastAPI/Coolify replica until process-local state is removed. Agent
workers may scale separately once Redis-backed holds and rate limits exist.

## 9. Failure policy

| Failure | Caller behavior | System behavior |
| --- | --- | --- |
| Carrier channels full | Human/queue/voicemail overflow | Count `carrier_overflow` |
| Agent capacity full | Immediate overflow, never silence | Reject before room acceptance where possible |
| STT error/empty audio | Short repeat prompt | No LLM or booking call |
| LLM 429/transient | Brief prerecorded wait, then secondary or handoff | Honor `retry-after`; circuit-break repeated failures |
| TTS failure | Prerecorded fallback/handoff | Do not return silent success |
| Booking slot/room race | Explain it is no longer available; offer refreshed options | Requery provider; one atomic winner |
| Unknown booking write result | Ask caller to wait; do not repeat blindly | Read provider by idempotency/reference before retry |
| Worker deployment/restart | Active calls drain before shutdown | Stop new jobs, allow deadline, then terminate |
| Dashboard command unavailable | Staff sees read-only state | Fail closed; no demo mutation in live mode |

Static disclosure, repeat, overload, and handoff prompts should be prerecorded
so a provider outage does not require another API call.

## 10. Security, privacy, and payments

- Disclose that the caller is speaking with AI at call start.
- Recording/transcription is off until the approved Estonian/EU notice,
  consent, purpose, retention, access, and deletion policy is implemented.
- Mask phone numbers before storage; do not put raw caller IDs in room names.
- Keep transcripts out of general application logs and LLM traces by default.
- Send only the minimum guest fields required by the booking provider.
- Never collect PAN/CVV by voice. Send a provider-hosted payment link or use a
  PCI-scoped tokenized checkout.
- Scope operator commands with a runtime bearer token and audit successful
  mutations.
- Rotate any exposed credential immediately and restart every consumer.

## 11. Deployment boundaries

### Web/control deployment

- FastAPI dashboard and internal APIs;
- one replica during the hackathon;
- persistent volume only for current SQLite call log;
- health endpoint proves process health, not downstream provider health.

### Media deployment

- LiveKit server + Redis;
- LiveKit SIP with explicit SIP/RTP ports, health, metrics, pinned image tag,
  and tested external IP advertisement;
- public firewall restricted to required protocols and carrier IP ranges where
  the carrier publishes stable ranges.

### Agent deployment

- separate LiveKit Agents container/process;
- named inbound agent matching the dispatch rule;
- prewarmed job processes and graceful drain;
- no public HTTP exposure beyond internal health/metrics;
- independent scaling from the dashboard.

Mutable `latest` image tags are acceptable only during setup. Pin verified
LiveKit server/SIP versions before the first external call test.

## 12. Service levels and evidence gates

Hackathon targets:

| Area | Target / gate |
| --- | --- |
| Call setup | p95 < 5 seconds from carrier INVITE to greeting |
| Turn latency | Measure p50/p95; target first audio p50 <= 1.5s, p95 <= 3s |
| Concurrent calls | 3 complete calls; caller four follows tested overflow |
| Disclosure | 100% of calls receive AI notice |
| Price safety | 100% of spoken prices tied to current provider quote |
| Booking safety | No duplicate writes in same-slot and retry tests |
| Handoff | One spoken command transfers with context |
| Provider failure | Forced 429/error produces fallback or handoff, not silence |
| Demo proof | Booking appears inside the selected booking system |

“Done” requires real carrier calls, not only HTTP tests or configured status
flags.

## 13. Execution plan

### Gate A — booking proof

1. Activate BOUK trial and verify official write API access.
2. If unavailable, deploy QloApps + Easy!Appointments.
3. Implement only the selected adapters.
4. Pass availability, quote, confirm, cancel, expiry, retry, and race tests.

### Gate B — telephone proof

1. Receive the approved Estonian number and written channel count.
2. Publish and firewall SIP/RTP.
3. Create inbound trunk and individual dispatch rule.
4. Implement the LiveKit Agents worker and tool wrappers.
5. Complete one real Estonian call with a visible booking result.

### Gate C — resilience proof

1. Add Redis holds/idempotency and provider rate budgets.
2. Test three simultaneous calls and fourth-call overflow.
3. Force STT/LLM/TTS failures and booking conflicts.
4. Run a 30-minute concurrency soak and inspect metrics/logs.
5. Record a 60-second backup demo only after the live path passes.

### Post-hackathon pilot

- replace the demo booking provider with a property-approved connector;
- move events/logs to Postgres;
- add real operator command projection and audit;
- configure paid provider capacity and secondary LLM;
- run shadow mode before autonomous booking;
- collect local PBX call data to replace modelled missed-call estimates.

## 14. Architecture decisions

| ID | Decision | Status |
| --- | --- | --- |
| ADR-001 | Self-host LiveKit media/SIP; carrier remains replaceable | Accepted |
| ADR-002 | Use LiveKit Agents as the only real-time agent framework | Accepted |
| ADR-003 | Separate hotel-night and appointment-slot adapters | Accepted |
| ADR-004 | Hide non-operational booking tools from the LLM | Implemented |
| ADR-005 | One room/job/context per call; hackathon cap 3 | Accepted, not phone-tested |
| ADR-006 | Booking provider is inventory/price truth | Accepted |
| ADR-007 | One web replica until Redis/Postgres migration | Implemented operational constraint |
| ADR-008 | BOUK trial first; open-source dual-system fallback | Pending trial API verification |
| ADR-009 | Dashboard is read-only/demo until command service exists | Implemented |

## 15. Open decisions that block implementation

1. Carrier approval: assigned number, direct SIP destination support, source IP
   ranges, codecs, and simultaneous channel count.
2. BOUK trial: official API credentials/docs and permission to create/cancel
   test bookings.
3. Human handoff destination and operating hours.
4. Approved property content: services, prices, policies, hours, and staff.
5. Recording/transcription consent and retention policy.
6. Secondary LLM provider before public tests.

Everything else is implementation work, not an unresolved architecture choice.
