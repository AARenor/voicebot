# Voicebot architecture risk and technical-debt register

Snapshot: **2026-10-01**. P0 blocks any live caller/property traffic. P1 blocks
the pilot unless explicitly resolved. P2 is tracked hardening.

| ID | Priority | Code/runtime evidence | Risk | Release gate / acceptance evidence | Owner |
| --- | --- | --- | --- | --- | --- |
| R-001 | P0 | `app/server.py:263-279`, `app/callslog.py:122-160`, `app/dashboard/api.py:103-107`; production `/api/calls` returned 3 unauthenticated real summaries | Raw caller PII/health/booking speech is persisted and public | `/api/calls` requires operator auth; PII/PAN fuzz turn leaves no raw values in DB/log/API | Web + security |
| R-002 | P0 | `app/booking/tools.py:192-204` returns arbitrary guest keys | PAN/CVV/payment-like data can enter LLM, adapters, or logs | allowlist guest schema; reject PAN/card/CVV/expiry/IBAN-like inputs; regression tests | Booking + security |
| R-003 | P0 (production) | `app/booking/easyappointments.py` write journal/file lock/recheck; `tests/test_easyappointments_installed.py::test_real_same_slot_contention_and_commit_timeout_restart` | Synthetic single-host writer race passes; upstream REST still permits overlapping independent UI/API writes | demo opt-in only; production requires universal controlled writer or provider-enforced inventory exclusion and cross-channel contention proof | Booking |
| R-004 | P0 (production) | `app/booking/easyappointments.py` durable pending/opaque marker reconciliation; `tests/test_easyappointments_safety.py`; installed timeout/restart test | Synthetic committed-write lost-response/restart proof passes; caller ownership, cross-host durability and operator recovery remain unproved | preserve shared journal; unknown outcomes fail closed; production requires owned request IDs, approved recovery and multi-host reconciliation proof | Booking |
| R-005 | P0 | `app/pipeline.py:49-66`; no agent worker/trunk/dispatch/public ports | There is no telephone bot despite configured LiveKit | measured LiveKit Agents spike and one real carrier call with audible booking result | Telephony |
| R-006 | P1 | `app/server.py:78-84,144-195`, `app/dashboard/static/index.html:450-461`; `LIVEKIT_API_SECRET` is not read | Config presence is labelled “ready/connected” without complete credentials, reachability, or signed workflow proof | require complete credential shape; status separates configured/reachable/operational, timestamp, reason; invalid credentials remain non-operational | Web + ops |
| R-007 | P1 | `app/server.py:91-102`, `app/knowledge/seed.py:3-38`, `app/booking/tools.py:245-254` | Generic demo policies can be spoken as property truth | no production FAQ tool without property ID, provenance, version, approval timestamp | Content + booking |
| R-008 | P1 | `app/turn.py:200-205`, `app/server.py:255-282` | TTS failure returns HTTP 200 with silence | non-empty prerecorded fallback or real transfer; forced failure test audible | Voice |
| R-009 | P1 | `app/booking/base.py:29-38,120-137`; shared dispatcher | A caller can confirm another session's hold if the ID crosses contexts | call/session owner on holds/tools; two-session isolation test | Booking |
| R-010 | P1 | `app/booking/base.py:44-52`, `app/callslog.py:62-89`, `app/dashboard/demo.py:1-88` | Replicas/restarts split process state and SQLite can lock/diverge | procedural one-replica pin today; add an executable startup/lease guard in Gate 0; Redis/Postgres before replicas; restart tests | Data + ops |
| R-011 | P1 | `app/turn.py:302-350`; name redaction intentionally absent | Secondary LLM can receive names/free-form identifiers | approved no-training tier or allowlist/minimal failover context; PII fuzz tests | AI + privacy |
| R-012 | P1 | `app/dashboard/api.py:38-47,49-59,103-115`; no ingress rate limiting | Data exposure, auth oracle, and brute-force/cost abuse | uniform auth failure, authenticated real reads, ingress rate limits, audit events, failure tests | Web + ops |
| R-013 | P1 | `requirements-phase2.txt:1-10`, `app/pipeline.py:1-66`; mutable LiveKit `latest` | Dual-framework/model/version drift can recreate rejected design | spike, remove obsolete descriptors, pin exact tested package/image versions | Telephony + ops |
| R-014 | P2 | `app/booking/qloapps.py:1-53` is a stub | “Guaranteed fallback” is not guaranteed | call it candidate until deployed API passes full workflow suite | Booking |
| R-015 | P2 | `app/booking/tools.py` now exposes `cancel_slot_booking`; installed API/Dispatcher cancel tests | Synthetic cancellation works; caller vs operator cancellation ownership remains undefined | explicit ADR/policy plus authenticated caller ownership before production | Product + booking |
| R-016 | P2 (mitigated) | `.gitignore` ignores `.env*` except `.env.example`, local SQLite artifacts; Docker ignores `.env*` | Runtime exports no longer ordinary staging candidates; CI secret scanning remains follow-up | `git check-ignore .env.local .env.production`; redacted staged credential scan before ship | Security + ops |
| R-017 | P1 | tracked compose defines only `voicebot`; LiveKit/SIP/Redis manifests live outside this repository | Media runtime cannot be reproduced or reviewed from the repo and can drift from architecture | add sanitized, pinned deployment manifests or an evidence-backed external deployment inventory before pilot | Telephony + ops |
| R-018 | P2 | `app/callslog.py:1-10,92-104` correctly labels the 30-day prune as a technical default and points to architecture section 10 | Technical pruning may still be mistaken for an approved retention/DPIA policy | document approved retention owner/legal basis; test deletion and backup scope | Privacy + docs |

## Strong controls already present

- Non-operational stay/Zenoti adapters are hidden from LLM tools.
- Currency-attached invented prices are blocked unless present in current tool
  results.
- Provider error bodies are converted to closed tool errors.
- SQLite writes are parameterized; the container is non-root; runtime data is a
  dedicated volume.
- UI inserts hostile data with `textContent`, not `innerHTML`.

## Review policy

Every architecture review updates this table. A risk closes only with a linked
test/command and evidence, not with a prose mitigation. P0/P1 IDs appear in the
execution gates in `ARCHITECTURE.md`.
