# Restaurant voicebot — current architecture and historical research

Status: **restaurant-only fictional pipeline, 2026-10-03**. Release acceptance is
recorded separately; implementation/configuration is not production readiness.

This document separates what is running from what is planned. A component is
not “ready” because credentials exist or a container starts; it is ready only
after its real workflow passes end-to-end verification.

## Current restaurant pipeline

The current product is a restaurant reservation assistant in Estonian, English
and Russian. Both HTTP and native startup default to the disclosed fictional
restaurant profile and table-only Dispatcher. An unavailable restaurant ledger
fails closed, never falls back to the archived hotel/spa adapters.

`Browser controls / HTTP dialogue / LiveKit telephone Agent`
→ `CallTools` (owned IDs, exact delivered recap, subsequent explicit consent,
server idempotency, sticky uncertainty)
→ restaurant-scoped `Dispatcher`
→ `DemoTableAdapter`
→ shared persistent `/data/restaurant-booking.db`.

Date, exact Tallinn time, all seated diners, actual table capacity and the whole
two-hour sitting define availability. SQLite transactions allocate an adequate
physical table, recheck it on confirmation and preserve replay results. Separate
readback verifies stored reservations; call history keeps contact-free table
receipts and original kinds of archived records. The public Meretuule page is
read-only; operator/demo writes require authentication. No real restaurant/POS
connector, price, payment, notification or real-customer collection is implied.

The existing signed incoming HTTPS/WSS route and private LiveKit media plane
remain unchanged. Website and worker are independently deployed/source-verified;
image build or public HTTP success alone is not native/PSTN acceptance.
See [the restaurant design](docs/superpowers/specs/2026-10-03-restaurant-pipeline-design.md)
for the domain contract, safeguards, migration boundaries and verification gates.

## Archived architecture and earlier acceptance snapshots

**The remainder records the former hotel/spa design and dated pilot results,
not active restaurant inventory, current deployment proof or PSTN acceptance.**
Its candidate vendors, stubs, diagrams and earlier measurements are retained as
research history rather than silently reinterpreted as restaurant functionality.

Historical vendor/model research from the earlier draft is summarized in
[`docs/research/stack-research-2026-09-29.md`](docs/research/stack-research-2026-09-29.md).

## 1. Goal and non-negotiable invariants

The product is an inbound English/Estonian telephone receptionist for hotels
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
| Operator web/API | `robot.arleserver.cfd`; authenticated provider booking/catalogue reads and a fictional text/microphone demo | Browser/deployment evidence is recorded in the dated hackathon report |
| HTTP voice turn | `POST /api/demo/session`, `/api/turn` and session deletion use bounded server-owned history and shared call tools | HTTP audio/text, not a telephone media loop |
| LLM | Groq `openai/gpt-oss-20b` works, including tool calls | Primary only; no configured secondary |
| Speech | Telephone Groq Whisper detects English/Estonian; Azure Jenny/Anu follows the call language | New English behavior is locally verified; live English carrier verification remains pending |
| FAQ | Approved fictional profile/FAQ/guests loaded from `data/demo/telephone-demo.json`; generic hotel seed is not advertised | Fictional spa only; no real-property policies or prices |
| Call log | Operator-authenticated no-store reads; HTTP/native calls journal only static technical outcomes | No new transcripts; historical content/retention still require real-guest release review |
| Dashboard booking view | Read-only Easy REST projection; successful guarded conversation changes select the actual booking day | No seeded appointments or private guest fields; old demo queue is explicitly separate |
| LiveKit server | Digest-pinned private LiveKit/SIP/Redis and worker manifests in `deploy/telephony`; deployed authenticated SIP dispatch and greeting RTP verified | Internal pilot; public NAT and carrier ingress remain unverified |
| First carrier target | Existing US Twilio number; HTTPS bidirectional Media Streams adapter to private LiveKit | Fresh rotated authentication, account webhook configuration and a real incoming call are separate gates |
| Alternative SIP ingress | Private authenticated LiveKit SIP; host is on a private LAN and only localhost SIP ports are published | Public SIP/RTP edge remains unverified; Twilio HTTPS avoids that particular prerequisite |
| Continuous call agent | `app/worker.py` runs Agents 1.8.4 with Groq/Azure/Silero; real spoken recap/decline/consent/create/read/cancel and two isolated jobs pass | Synthetic pilot; PSTN and real-property release remain gated |
| Hotel booking | Apaleo, Mews, Cloudbeds, and QloApps drivers are stubs | No operational `StayAdapter` |
| Spa booking | Private Easy!Appointments 1.6.0 installed; real HTTP catalogue/search/hold/confirm/cancel and synthetic race/recovery tests pass | Explicit demo-write opt-in; not real-property or independent-writer readiness |
| Persistent booking state | HTTP and worker share `/data/easy-booking.db`; single-host lock/outcome replay; shared tools enforce owned IDs, server keys and transcript consent after delivered recap | Unknown writes remain sticky and block further writes; process-local ownership does not survive restart |
| Concurrency | Three HTTP turns and two isolated real-provider room jobs verified | Two-job private worker cap; carrier channel/overflow testing remains |

`/api/status` currently reports wiring and derived capabilities. In particular,
`livekit: true` means credentials are configured; it does **not** mean a phone
call can reach an agent. `serving_demo_data: true` remains intentional until
real operator and booking data replace the demo store. The separate `telephone`
status explicitly keeps public-ingress/carrier verification false. Worker HTTP
health alone is not a registration, booking or PSTN proof.
The dated [hackathon verification](docs/evidence/2026-10-02-hackathon-verification.md)
separately records the tested public signed WSS edge; conservative status flags
are not substituted for carrier acceptance evidence.

Live traffic is blocked by the P0/P1 items in
[`docs/architecture/risk-register.md`](docs/architecture/risk-register.md).
Historical public call-summary exposure was observed on the deployed site.
Authentication/no-store and static new-turn summaries address that specific
gap; real guest release still requires the remaining privacy/safety gates.

## 3. Target topology

### System context

```mermaid
flowchart LR
    Guest[Guest / caller] -->|PSTN call| Carrier[Estonian DID + SIP carrier]
    Carrier -->|SIP + RTP| Voicebot[Voicebot system]
    Staff[Reception staff] -->|HTTPS| Voicebot
    Voicebot -->|STT / LLM / TTS| AI[Groq + Azure]
    Voicebot -->|availability + booking writes| Booking[Hotel / spa booking system]
    Voicebot -->|warm transfer| Human[Human receptionist]
```

### Container view

```mermaid
flowchart LR
    Carrier[Carrier / SIP edge]
    Staff[Operator browser]
    AI[Groq + Azure]
    PMS[Booking provider]
    Human[Human handoff]

    subgraph Voicebot
      SIP[LiveKit SIP]
      LK[LiveKit server]
      Agent[LiveKit Agents workers]
      Web[FastAPI dashboard/API]
      Redis[(Redis)]
      DB[(Postgres target)]
    end

    Carrier --> SIP --> LK --> Agent
    Agent --> AI
    Agent --> PMS
    Agent --> Human
    Agent --> Redis
    Agent --> DB
    Staff --> Web
    Web --> Redis
    Web --> DB
    Web -. read/projection .-> PMS
```

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

For the first US Twilio test the media entrance is instead:

```text
US telephone number -> Twilio <Connect><Stream> -> HTTPS/WSS carrier adapter
  -> private individual LiveKit room -> the same LiveKit Agents worker
```

Only the adapter's `/api/twilio/` routes are public. Signed webhook plus signed
WebSocket/start validation and a one-use call binding precede room allocation.
There is no second dialogue loop or booking writer. Carrier-side account and
PSTN proof are not inferred from a synthetic WSS test. The SIP diagrams above
remain an alternative transport, not an immediate US-number prerequisite.

Mutation status is rendered by the server from current-turn execution receipts,
not model language or a historical booking. Otherwise speech is limited to exact
approved fictional FAQ/static guidance and canonical recaps. Typed unknown
confirmation/cancellation outcomes persist across the call/session, including
the HTTP response/log, and block repeat mutations pending independent operator
readback. A transcript recognition miss cannot be converted into consent by
fuzzy matching. Native policy observes the completed SDK user turn, not each
provider-final STT fragment; endpointing is fixed 1.2–3 seconds, interruption VAD
remains immediate. These synthetic safeguards are not real-guest authorization.

The web/API container is not in the continuous real-time media path. It serves the
operator UI, configuration-safe status, and internal event/command endpoints.
The call worker is deployed separately and scales independently.

## 4. Provisional real-time framework: LiveKit Agents

The implemented choice for the synthetic pilot is **LiveKit Agents** as the only call runtime. Do not
put Pipecat and LiveKit Agents in the same production call path unless a spike
proves a named LiveKit capability gap.

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

The implemented private worker is `app/worker.py`; `app/pipeline.py` remains a
reference routing descriptor, not the media runtime. Pipecat was removed from
the active dependency plan; the separate media lock pins the tested runtime.

The private spike now has a pinned runtime and executable room/SIP/failure/drain
probes. The following are private acceptance checks, not a real carrier proof:

1. inbound SIP or loopback room dispatch to one job per call;
2. two simultaneous isolated calls;
3. Estonian Groq STT + Azure Anu output and measured first-audio latency;
4. barge-in/endpointing behavior on Estonian names, dates, and prices;
5. forced 429/TTS-failure behavior with audible fallback;
6. graceful drain and an explicit policy for state loss on crash redispatch.

Decision rationale and alternatives:
[`ADR-0001`](docs/decisions/0001-provisional-livekit-agents.md).

Official references:

- [Voice AI quickstart](https://docs.livekit.io/agents/start/voice-ai-quickstart/)
- [Agent server](https://docs.livekit.io/agents/server/)
- [Groq STT plugin](https://docs.livekit.io/agents/models/stt/plugins/groq/)
- [Groq LLM plugin](https://docs.livekit.io/agents/models/llm/plugins/groq/)
- [Azure Speech TTS plugin](https://docs.livekit.io/agents/models/tts/plugins/azure/)
- [Silero VAD plugin](https://docs.livekit.io/agents/logic/turns/vad/)

## 5. Inbound call lifecycle and remaining production gates

The native worker implements isolated rooms/jobs, AI disclosure, continuous
speech, guarded tools, bounded cleanup and static outcome logging. HTTP uses
the same booking policy but is a different transport. The SIP carrier ingress,
human transfer and real-guest notice/retention parts below remain release gates.

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

Implemented synthetic hackathon limits:

- at most **2 native jobs**; the Twilio adapter has its own matching active cap;
- native calls at most 10 minutes after a bounded caller-arrival wait;
- HTTP sessions: 10-minute TTL, 16 sessions, 24 turns, one in-flight turn/session;
- no shared provider-rate token bucket is deployed; compact planning reduces
  repeated model/tool round trips, but actual provider quota can still reject;
- bounded first-audio/failure behavior; no verified carrier queue/human overflow.

The two-job cap is a tested private-worker ceiling, not a claim that the current
account can sustain two full booking conversations. A real LLM 429 was observed
during the spoken booking probe; presentation success requires the dated audio
evidence, not a theoretical requests-per-minute calculation. Carrier/account
limits can impose a lower ceiling. Redis rate budgets and larger capacity remain
future work, not hidden prerequisites represented as implemented features.

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

An adapter's `operational` flag is a release assertion, not a declaration by
the class author. Easy!Appointments now defaults to non-operational. Its explicit
`EASY_DEMO_WRITES=1` gate permits only the controlled synthetic demo with a
persistent SQLite write journal. Confirmation rechecks provider availability
inside a file lock. The real-instance tests cover same-slot contention and
commit-then-timeout/restart reconciliation; they do not certify independent UI
writes, multiple hosts, real guest privacy or caller ownership.

Every hold and idempotency key is owned by a call/session namespace. Possession
of a hold ID alone must never authorize another caller to confirm or cancel it.

### Hackathon provider decision

1. **Selected backend:** self-hosted Easy!Appointments 1.6.0 for a
   spa-treatment or consultation slot demo, only after deployed write-path
   tests.
2. **Room-specific fallback:** QloApps only if multi-night inventory, nightly
   rates, and occupancy become mandatory.
3. Cal.diy and LibreBooking have writable open-source APIs, but add deployment
   or domain-model complexity without improving the selected demo.
4. Do not buy BOUK Professional or block the hackathon on proprietary partner
   onboarding. BOUK, SALBOS, and D-EDGE remain production connector targets.

The first-party comparison and rejection reasons are in
[`docs/research/open-source-booking-backends.md`](docs/research/open-source-booking-backends.md).

**Installed topology (2026-10-01):** the private `voicebot-booking` Compose
project runs pinned Easy!Appointments 1.6.0 and persistent MySQL. The booking
service is `voicebot-easyappointments:80` on the Coolify network; its admin UI
binds only to host loopback port 8088 and MySQL has no published host port.
The existing org repository **Parnuhakk/voicebot** supplies the Python image.
`build_stack` → `Dispatcher` → `SlotAdapter` connects the four-round HTTP
dialogue to the documented REST API. `/data/easy-booking.db` persists write
outcomes on the voicebot data volume; local holds still expire on restart.
See the [deployment/operator runbook](deploy/easyappointments/README.md).
The [installation evidence](docs/operations/easyappointments-verification-2026-10-01.md)
includes a deployed operator-authenticated text turn with real Groq/Azure,
three booking tools, independent appointment readback and nonempty audio.

### Production connector targets

- SALBOS is the strongest Pärnu spa-hotel target.
- BOUK is confirmed at multiple Pärnu accommodation properties.
- D-EDGE is present at Hestia Strand. Its [official developer portal](https://docs.d-edge.com/overview/get-started/explore-our-apis)
  exposes
  Quotation and Booking Engine APIs plus a credential-free mock; production
  access requires a signed partnership.
- Apaleo/Mews/Cloudbeds/Zenoti remain later generic connectors, not current
  demo dependencies.

Property evidence, safe market claims, and the explicitly modelled summer
missed-call opportunity are in
[`docs/research/parnu-booking-systems.md`](docs/research/parnu-booking-systems.md).

## 8. State ownership and persistence
### Website control plane and booking visibility

`https://robot.arleserver.cfd` serves the static operator dashboard and FastAPI
API in the same Coolify deployment. Two paths must not be conflated:

1. **Implemented booking path:** authenticated HTTP session/turn or native voice
   → shared `CallTools` ownership/consent policy → `Dispatcher` → `SlotAdapter` → private Easy REST
   → authoritative MySQL. The journal on `/data` coordinates writes/recovery.
2. **Implemented visual path:** browser → authenticated `/api/bookings`,
   `/api/catalogue`, `/api/calls`; schedule/catalogue come from the provider,
   not `demo.STORE`. Call rows contain static technical outcomes. The text/mic
   form runs a bounded fictional conversation. Logout aborts requests, stops
   audio/microphone and clears private DOM; late results cannot restore it.

**Implemented read boundary:** operator-authenticated,
`Cache-Control: no-store` provider schedule read → explicit allowlisted DTO →
read-only bookings panel. No direct DB/browser-provider access, embedded admin,
extra event bus or independent booking writer. Read capability must be separate
from the write opt-in so disabling booking does not require disabling visibility.
Protect existing call reads and minimize summaries before real guest use;
public Cloudflare403 for one client is not an authorization boundary.

The [three-round research](docs/research/website-booking-architecture/RESEARCH.md),
[implementation/test contract](docs/research/website-booking-architecture/DESIGN.md)
and [historical research evidence](docs/research/website-booking-architecture/EVIDENCE.md)
cover the original contract. The current implementation/tests extend it with
safe DTOs, errors, polling, Tallinn DST, demo labels and conversation outcomes.
The [interactive current-system diagram](.archify/architecture-website-booking-20261001-213712/website-booking.html)
is a historical source snapshot; its proposed next-slice labels are not current
deployment evidence. Use the dated hackathon evidence and current source instead.

### Persistence boundaries

| State | Current | Target | Authority |
| --- | --- | --- | --- |
| Conversation and consent | Call or authenticated HTTP-session memory; subsequent final transcript after delivered recap | Same boundary; optional durable recovery only if explicitly designed | Shared CallTools context |
| Holds | Process memory with call-owned IDs; backend writer rechecks availability | Redis with TTL and atomic reservation if scaling requires it | Booking provider on confirm |
| Easy write outcomes | Persistent SQLite journal/file lock; opaque markers, pending prerequisite/appointment writes and durable replay | Caller-owned durable requests and provider/universal-writer exclusion across hosts | Booking provider reads plus local coordination |
| Provider rate budgets | None | Redis token buckets | Provider headers/limits |
| FAQ content | SQLite | Postgres or controlled content store | Property-approved content |
| Call/booking events | SQLite | Postgres | Append-only application events |
| Dashboard bookings | Allowlisted read-only provider projection; no guest contact fields | Same projection; events only if needed | Provider |
| Room/slot inventory | External when connected | External only | PMS/booking system |

Keep one FastAPI/Coolify replica until process-local state is removed. Agent
workers may scale separately once Redis-backed holds and rate limits exist.

## 9. Failure policy

| Failure | Caller behavior | System behavior | Status |
| --- | --- | --- | --- |
| Carrier channels full | Human/queue/voicemail overflow | Count `carrier_overflow` | Target; carrier unverified |
| Agent capacity full | Bounded unavailable/hangup behavior; no promised human route | Worker admission and bridge active cap | Private worker exists; carrier overflow unverified |
| STT error/empty audio | Short repeat prompt | No LLM or booking call | Current HTTP behavior |
| LLM 429/transient | Native cached unavailability speech; HTTP explicit fallback | No blind mutation retry; closed diagnostics omit provider bodies | Native fallback exists; no configured native secondary |
| TTS failure | Native cached speech; HTTP text plus explicit no-audio warning | Failed recap cannot authorize confirmation | Native failure probe; HTTP regression tests |
| Booking slot/room race | Explain it is no longer available; offer refreshed options | Easy demo rechecks under single-host lock; typed stale-slot loser | Verified synthetic slot writer; independent writes/rooms remain target |
| Unknown booking write result | Ask caller to wait; do not repeat blindly | Durable pending state; unique appointment marker read/reconcile; uncertain customer creates require operator recovery | Verified Easy demo timeout/restart/fresh-key fail-closed behavior; caller/production gates remain |
| Worker deployment/restart | Active calls drain before shutdown | Stop new jobs, allow deadline, then terminate | Private drain probe implemented |
| Dashboard command unavailable | Staff sees read-only state | Fail closed; no demo mutation in live mode | Partly current; mode inconsistencies tracked |
| Generic/unapproved FAQ | Explain unavailable real-property policy | Only approved fictional profile/FAQ is exposed | Shared fictional tools implemented |
| Agent crash redispatch | Apologize/restart or transfer; never reconstruct booking state from guesswork | Recover durable state or fail closed | Target; policy absent |

Static disclosure, repeat, overload, and handoff prompts should be prerecorded
so a provider outage does not require another API call.

## 10. Security, privacy, and payments

- Disclose that the caller is speaking with AI at call start.
- Recording/transcription is off until the approved Estonian/EU notice,
  consent, purpose, retention, access, and deletion policy is implemented.
- The current call-log code has a 30-day technical pruning default. This is not
  an approved legal retention policy; owner, lawful basis, backups, deletion,
  and DPIA status remain Gate 0 work (R-018).
- Mask phone numbers before storage; do not put raw caller IDs in room names.
- Keep transcripts out of general application logs and LLM traces by default.
- Protect every endpoint returning real call, guest, or booking data with
  operator authentication and rate limits.
- Send only the minimum guest fields required by the booking provider.
- Enforce an allowlisted guest schema and reject payment-card/PAN/CVV/expiry
  fields at the first trust boundary.
- Never collect PAN/CVV by voice. Send a provider-hosted payment link or use a
  PCI-scoped tokenized checkout.
- Scope operator commands with a runtime bearer token and audit successful
  mutations.
- Rotate any exposed credential immediately and restart every consumer.

## 11. Deployment boundaries

### Web/control deployment

- FastAPI dashboard and internal APIs;
- one replica during the hackathon;
- persistent `/data` volume for SQLite call log and Easy write journal;
- separate pinned private Easy PHP/MySQL stack with persistent booking volumes;
- health endpoint proves process health, not downstream provider health.

### Media deployment

- LiveKit server + Redis;
- private LiveKit SIP with loopback signaling and unpublished RTP; digest-pinned
  images/configuration, health and executable probes;
- optional signed Twilio HTTPS/WSS adapter over the existing reverse proxy;
- only for a later public SIP path: verified external SDP/RTP advertisement and
  restricted carrier firewall. Those public SIP conditions are not yet proven.

Pinned private manifests, lockfile, credential-safe management and executable
probes are in `deploy/telephony/`. The optional Twilio bridge is a separate
Compose project using the same media image and private network. No wildcard
SIP/RTP publication is part of the HTTPS carrier path. See the carrier runbook
for exact signature URLs, transport bounds and remaining account/PSTN gates.

### Agent deployment

- separate LiveKit Agents container/process;
- named inbound agent matching the dispatch rule;
- prewarmed job processes and graceful drain;
- no public HTTP exposure beyond internal health/metrics;
- independent scaling from the dashboard.

Mutable `latest` image tags are acceptable only during setup. Pin verified
LiveKit server/SIP versions before the first external call test.

## 12. Service levels and evidence gates

Hackathon **aspirational targets**; none is a telephone-runtime claim until its
quality scenario below passes:

| Area | Target / gate |
| --- | --- |
| Call setup | Aspirational: p95 < 5 seconds from carrier INVITE to greeting; measure at SIP edge and first audio |
| Turn latency | Aspirational: first audio p50 <= 1.5s, p95 <= 3s; measure inside AgentSession |
| Concurrent calls | 3 complete calls; caller four follows tested overflow |
| Disclosure | 100% of calls receive AI notice |
| Price safety | 100% of spoken prices tied to current provider quote |
| Booking safety | No duplicate writes in same-slot and retry tests |
| Handoff | One spoken command transfers with context |
| Provider failure | Forced 429/error produces fallback or handoff, not silence |
| Demo proof | Booking appears inside the selected booking system |

Full telephone acceptance requires real carrier calls, not only HTTP tests or
configured status flags. The separately verified booking installation/HTTP demo
does not close this telephone gate.

### Quality scenarios

| ID | Context and stimulus | Required response and measurable evidence | Current status |
| --- | --- | --- | --- |
| Q-01 Isolation | Separate callers speak and create different holds | No room/history/guest/hold crosses sessions | Two private audio jobs and ownership regressions exist; three complete carrier calls unverified |
| Q-02 Inventory race | Two calls confirm the same last room/slot | Exactly one remote booking; loser receives typed conflict and refreshed choices | Synthetic single-host Easy writer test passed; real calls/independent writers/room inventory still blocked |
| Q-03 Ambiguous write | Provider commits, client times out, process restarts, retry arrives | Provider query/reconciliation returns original result; no second booking | Easy journal/reconciliation and fresh-interpreter replay passed; production caller/multi-host recovery still blocked |
| Q-04 Provider outage | STT/LLM/TTS returns 429/5xx | Cached native speech or explicit HTTP warning; never false write success | Native failure probe and HTTP regressions exist; real carrier failure remains unverified |
| Q-05 Privacy | Unauthenticated/late reads or model-supplied private guest fields | Deny reads, clear on logout, reject fields, store static outcomes | Current auth/DTO/lifecycle tests; historical data/legal retention still a real-guest gate |
| Q-06 Truthful readiness | Credentials present but no carrier proof | Configured is distinct from operational; no environment flag creates a proof | Status keeps public/PSTN verification false; separate dated evidence required |
| Q-07 Deployment | SIGTERM during an active call | New jobs stop; calls drain within deadline | Private clone drain probe exists; carrier drain remains unverified |
| Q-08 Provider change | Add one supported booking provider | New adapter + contract tests; no changes to core dialogue/tool policy | Design accepted, unproved |

Google SRE guidance treats SLOs as measured user outcomes, not declarations.
Latency rows remain aspirational until the first real-call dataset exists.

## 13. Execution plan

### Gate 0 — remove live-traffic blockers

1. Authenticate real call/guest/booking reads and stop storing raw dialogue by
   default.
2. Enforce guest-field allowlists and reject payment-like data.
3. Disable generic FAQ and real-property Easy!Appointments tools until property
   and privacy gates pass; synthetic demo writes require explicit opt-in.
4. Add caller ownership and durable idempotency/reconciliation design.
5. Implement audible static fallback and truthful readiness states.
6. Add a one-process startup guard until state migration is complete.

### Gate A — booking proof

The synthetic 1.6.0 installation and opt-in contract suite are now provided:
`tests/test_easyappointments_installed.py` verifies API lifecycle, factory/
Dispatcher/dialogue integration, same-slot contention and timeout/restart
reconciliation. Production release still requires the R-003/R-004 universal
writer/inventory and ownership gates; this is not a telephone proof.

1. Deploy stable Easy!Appointments 1.6.0 and configure a demo service,
   provider, and working schedule.
2. Store the Settings-issued API credential only in the runtime environment.
3. Validate the existing adapter against the real instance for availability,
   create, cancel, authorization failure, retry, and malformed payloads; smoke
   test the API's update operation separately because rescheduling is not in
   the current `SlotAdapter` contract.
4. Pass same-slot race and commit-then-timeout reconciliation tests before
   enabling live writes.
5. Evaluate QloApps only if room-night semantics return to scope.

### Gate B — telephone proof

1. Rotate the exposed Twilio authentication credential; verify the assigned US
   number/account and actual channel/trial restrictions without a purchase.
2. Deploy the separately signed HTTPS/WSS bridge to the existing private native
   worker; verify the real wire path with a synthetic stream, not a PSTN claim.
3. Configure the exact number's incoming webhook only with fresh authorized
   credentials. No other number/account settings or outbound calls.
4. Complete an independent inbound phone call in Estonian with booking/read/cancel,
   interruption, hangup and failure evidence.
5. For a later SIP carrier, additionally verify and restrict a public SIP/RTP edge
   and exact inbound trunk/dispatch rule; HTTPS alone is not that UDP edge.

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

Linked ADR rows have standalone rationale. `DEC-*` rows are inline constraints,
not full ADRs; promote one to a file when it becomes costly or contentious.

| ID | Decision | Status |
| --- | --- | --- |
| [ADR-0001](docs/decisions/0001-provisional-livekit-agents.md) | LiveKit Agents as sole runtime | Implemented private synthetic pilot; real carrier gate remains |
| [ADR-0002](docs/decisions/0002-separate-stay-slot-adapters.md) | Separate hotel-night and appointment-slot adapters | Accepted; implementations gated |
| [ADR-0003](docs/decisions/0003-provider-truth-idempotency.md) | Provider truth with durable local coordination | Implemented for controlled Easy demo; production ownership/distribution incomplete |
| DEC-004 | Self-host LiveKit media/SIP; carrier remains replaceable | Private pinned manifests in repo; Twilio-first HTTPS entrance |
| DEC-005 | Hide non-operational booking tools from the LLM | Implemented; Easy defaults off and requires explicit verified-demo opt-in |
| DEC-006 | One room/job/context per call; current native cap 2 | Private two-job audio proof; larger/carrier capacity unverified |
| DEC-007 | One web replica until Redis/Postgres migration | Procedural constraint only; executable guard pending |
| DEC-008 | Easy!Appointments 1.6.0 for the spa-demo; QloApps only for mandatory room semantics | Installed and deployed HTTP write path verified; production release gates remain |
| DEC-009 | Provider-backed dashboard remains read-only; fictional conversation owns writes | Implemented with operator auth and explicit synthetic labels |

## 15. Open decisions that block implementation

1. Carrier approval: assigned number, direct SIP destination support, source IP
   ranges, codecs, and simultaneous channel count.
2. Real-property booking authorization and universal writer/inventory
   exclusion. The synthetic Easy instance, schedule, runtime credential and
   lifecycle proof are complete; they do not authorize production traffic.
3. Human handoff destination and operating hours.
4. Approved property content: services, prices, policies, hours, and staff.
5. Recording/transcription consent and retention policy.
6. Secondary LLM provider before public tests.
7. Cancellation ownership: caller self-service, operator-only, or deferred.

## 16. Risks and technical debt

The ranked register is
[`docs/architecture/risk-register.md`](docs/architecture/risk-register.md).
No live rollout proceeds with an open P0. P1 items require resolution before a
property pilot. Risks close only with linked executable evidence.

Everything else is implementation work, not an unresolved architecture choice.
