# Functional repair verification — 2026-10-03

This repair starts from the published application, not the original concurrent
dirty checkout. It preserves the subsequent microphone/session UX, canonical
booking shortcuts, Meretuule domain, natural dialogue, ET/EN/RU speech and the
English browser controls, multilingual booking FAQs and safe release
synchronization through published master `f154731`. The supported demo
remains fictional; no real PMS connector, carrier
acceptance or physical-microphone result is invented.

## Corrected behavior

- Same-call spa cancellation permits a fresh owned hold for the same slot,
  retaining consumed-hold and historical-write protections.
- Proven failure before a remote write is a durable known failure, not a sticky
  unknown outcome. Ambiguous remote writes remain blocked from automatic retry.
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

## Local verification

Red regressions reproduced each correction before its implementation, including
the independently reviewed preparation deadline and custom-agent drift.

| Check | Result |
| --- | --- |
| Full core suite, cleared environment | 2482 passed, 58 skipped, 36 subtests passed |
| Full Python 3.12 pinned media/SDK suite, network disabled | 2736 passed, 9 skipped, 36 subtests passed |
| Real Chromium recap/playback/read/expiry/unhappy-path suite | 31 passed, zero external requests |
| All six local browser suites, including English and microphone races | Passed, zero page errors or external requests |
| Host Compose parser checks covering both release manifests and bridge isolation | 5 passed |
| Scoped Python fatal/name lint and diff whitespace | Passed |

These suite selections overlap and must not be summed. Core skips cover missing
native dependencies and installed-backend opt-in. The full media run exercises
actual pinned native imports; its nine skips are four live installed-backend
tests and five Docker Compose parser cases unavailable inside the disposable
harness. All five parser cases passed separately on the host. Existing Starlette
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
The subsequent published FAQ/release-sync and test-cleanup changes were merged
without overwriting the repairs; the full counts above are from that final
combined source, not the earlier review snapshot.
