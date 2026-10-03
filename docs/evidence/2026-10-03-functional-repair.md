# Functional repair verification — 2026-10-03

This repair starts from the published application, not the original concurrent
dirty checkout. It preserves the subsequent microphone/session UX, canonical
booking shortcuts, Meretuule domain, natural dialogue, ET/EN/RU speech and the
English browser controls, multilingual booking FAQs and safe release
synchronization, selectable modern voices and incremental playback through
published master `e58a494`, including contextual receptionist follow-ups. The supported demo
remains fictional; no real PMS connector, carrier
acceptance or physical-microphone result is invented.

## Corrected behavior

- Same-call spa cancellation permits a fresh owned hold for the same slot,
  retaining consumed-hold and historical-write protections.
- Proven failure before a remote write is a durable known failure, not a sticky
  unknown outcome. Ambiguous remote writes remain blocked from automatic retry.
- Same-guest rebooking reuses only the adapter's own validated customer-creation
  result, bound to its backend and all four cleaned guest fields. It never looks
  up a customer by email or lets an explicit ID seed that proof. Existing bounded
  memory storage, durable failure replay and unresolved-write blocking remain.
- HTTP synthesis/rendering does not deliver a booking recap. An opaque receipt
  binds the current owned preparation; full playback or deliberate reading
  precedes its one-use acknowledgement with a later confirmation input.
- The browser uses the preparation deadline, not the longer session deadline.
  Seeking, interruption, stale callbacks, logout and expiry cannot grant consent.
  Direct booking likewise requires reading and a separate confirmation action.
- Finished conversation and booking controls no longer wait for unrelated reads.
- ET/EN/RU speech uses validated matching voices, including per-turn overrides;
  unsupported languages fail explicitly. Native empty replies remain audible,
  silent synthesis cannot deliver recaps, and canonical native booking actions
  reuse the same trusted state shortcuts without redundant model requests.
  Repeating or translating an unapproved recap preserves its original hold and
  deadline but issues a fresh delivery receipt and still requires later consent.
- SIP/worker/bridge names remain aligned. Scoped worker replacement preserves
  the existing shared volume and does not restart LiveKit/SIP/Redis; bridge
  configuration is reused in memory and mismatches fail before replacement.
- NDJSON receipts appear only in a successful, complete terminal response.
  Malformed, empty or partial synthesis cannot arm one; expired, foreign and
  consumed receipts return 409 before streaming headers or paid recognition.
  Browser MSE playback requires complete transport and actual contiguous playback;
  interrupted audio may use deliberate reading only after validated canonical text.

## Local verification

Red regressions reproduced each correction before its implementation, including
the independently reviewed preparation deadline and custom-agent drift.

| Check | Result |
| --- | --- |
| Full core suite, cleared environment | 2678 passed, 58 skipped, 36 subtests passed |
| Full Python 3.12 pinned media/SDK suite, network disabled | 2931 passed, 10 skipped, 36 subtests passed |
| Real Chromium recap/playback/read/expiry/unhappy-path suite | 48 passed, zero external requests |
| All eight local browser suites, including modern voices, streaming and microphone races | Passed, zero page errors or external requests |
| Host Compose parser checks covering both release manifests and bridge isolation | 5 passed |
| Scoped Python fatal/name lint and diff whitespace | Passed |

These suite selections overlap and must not be summed. Core skips cover missing
native dependencies and installed-backend opt-in. The full media run exercises
actual pinned native imports; its ten skips are four live installed-backend
tests, five Docker Compose parser cases and one optional website-WebSocket
dependency absent from the telephone image. All five parser cases and the
website provider tests passed separately on the host. Existing Starlette
TestClient and Python 3.12 audioop deprecation warnings remain disclosed.

The native worker and bridge are separate deployments: the published release
reconciler updates only those existing services after the web release is healthy.
Local evidence above is not a live-provider, public
PSTN, production-readiness or human-audibility certificate. Deployment, bounded
configured-provider checks and owned synthetic write/read/cancel cleanup must be
recorded separately before claiming those outcomes.

The actual native SDK pipeline tests finalize real user turns and execute the
SDK tool path; they are not merely generated tool-call-shape assertions. Positive
synthesis fixtures contain actual nonzero PCM. Negative empty, silent, truncated,
interrupted and stale-identity cases remain present. No live provider credentials
are passed to the offline suites. The independent review and deployed acceptance
are documented separately in the goal evidence; local tests are not a carrier
or physical-microphone certificate. Independent round-three review passed with
162 focused tests and 11 additional denial/configuration probes, zero socket
connection attempts and no evidence-backed outstanding P0/P1/P2 finding.
The subsequent published FAQ/release-sync, modern voices and streaming changes
were merged without overwriting the repairs. An independent backend integration
addendum passed 98 tests and eight probes with zero socket attempts. The full
counts above are from the final combined source, not the earlier review snapshot.
Published deterministic JS fixtures were aligned with canonical DOM ownership,
preparation TTL and actual current audio identity; no production guard was relaxed.
The final independent frontend addendum passed 54 cases/probes; combined with
the backend review it gives a qualified FINAL-INTEGRATION PASS, with no evidenced
outstanding P0/P1/P2 finding. It does not certify deployment or human hearing.

The first deployed same-guest rebooking probe exposed the installed backend's
unique-email customer constraint, absent from the original different-guest
fixture. A strict retained-customer fixture reproduced three failures before
the minimal reuse correction; twelve additional witnesses retain consent,
guest/call isolation and ambiguous-write protections. The original failed
synthetic attempt was independently reconciled and its history preserved;
no ambiguous write was automatically retried. The updated full counts above
include this follow-up; live acceptance is recorded separately in the goal.
Independent review of the reuse delta passed 41 regressions and 21 additional
edge/concurrency probes with zero sockets and no evidenced P0/P1/P2 finding.
The newer, separately reviewed language release was merged without conflicts;
its eleven published paths remain byte-identical. Complete combined checks
above preserve both updates; deployment and provider acceptance remain separate.
