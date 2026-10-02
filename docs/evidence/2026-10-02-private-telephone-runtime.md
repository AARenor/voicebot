# Private telephone runtime verification — 2026-10-02

Scope: carrier-independent BUILD of the missing continuous worker, private SIP
dispatch, call-owned booking bridge and HTTP call privacy. **No number purchase,
DIDWW account mutation, public edge deployment or real PSTN call.**

## Implementation and deployed topology

`app/worker.py` runs native LiveKit Agents 1.8.4 (RTC 1.1.20, API 1.2.1), with
Groq Estonian STT/LLM, Azure Anu TTS and local Silero VAD. Named `voicebot` jobs
run in separate processes, with two-job capacity and a 30-second drain. The
booking Dispatcher/adapters stay media-framework independent.

`app/telephone.py` exposes only the five real spa tools: catalogue, provider-
required search, `hold_slot`, confirm and cancel. Call-local ownership, rejection
of model-supplied customer IDs, stable server-controlled write identities,
closed provider errors and pre-synthesis price/currency denylist are tested.
The pilot cannot quote prices; the denylist is not exhaustive semantic validation.
Consent is an agent instruction, not a separately proven authorization signal.

`deploy/telephony/compose.yaml` was applied to the existing `livekit` project;
operator files outside this repo were not overwritten. LiveKit/SIP/Redis and
Python base images are digest-pinned; complete Python dependencies are pinned.
The worker shares the HTTP container's existing `/data/easy-booking.db` volume.
Loopback-only published ports: API 7880, SIP TCP/UDP 5060, worker health 8081.
No Redis/RTP/RTC media host ports are published. Internal services still share
the trusted `coolify` network. A generic Redis DNS collision was fixed with the
explicit `voicebot-media-redis` alias and mounted-config checksum recreation.

## Commands and results

Commands below ran from `/home/arle/voicebot`; `MEDIA_PY` denotes the verified
`/tmp/opencode/voicebot-telephony-venv/bin/python` Python 3.12 environment.

| Check | Command | Observed result |
|---|---|---|
| Full media-enabled suite | `$MEDIA_PY -m pytest tests -q` | **164 passed, 4 skipped** in 3.38 s; installed-backend opt-in tests skipped; one existing Starlette/httpx deprecation warning |
| Existing HTTP-only environment | `.venv/bin/python -m pytest tests -q` | **148 passed, 7 skipped** in 1.66 s; media/installed-backend opt-ins skipped; same warning |
| Private Compose/shared state | `python3 deploy/telephony/manage.py validate --source-container "$WEB_CONTAINER"` | PASS; exact existing persistent volume identified; expanded credentials never printed |
| Image build | `DOCKER_CONFIG=/tmp/opencode/docker-voicebot python3 deploy/telephony/manage.py build --source-container "$WEB_CONTAINER"` | Exit 0, locked runtime installed; final worker image config digest `sha256:116ce91680ece779b51d336ba83c2ca5d36f6e8b38bec653c163286279942e12` |
| Apply private pilot | `python3 deploy/telephony/manage.py up --source-container "$WEB_CONTAINER"` | Four services running; worker healthy; final check found zero restarts |
| Two concurrent real audio jobs | `$MEDIA_PY deploy/telephony/probe.py --source-container livekit-worker-1 --concurrent` | Both PASS: 1580/2201 audio frames, each 1 final input turn and 2 spoken replies; separate rooms/jobs |
| Spoken interruption | `$MEDIA_PY deploy/telephony/probe.py --source-container livekit-worker-1 --barge-in` | PASS: 1378 frames, input STT and reply, greeting stopped during caller speech |
| Forced provider failure | `$MEDIA_PY deploy/telephony/failure_probe.py` | Isolated named clone with invalid Azure credential: 376000 received PCM bytes; independently transcribed cached apology, 0.914 similarity; clone cleaned; normal worker untouched |
| Graceful drain | `$MEDIA_PY deploy/telephony/failure_probe.py --drain` | PASS: SIGTERM, new job refused, exit 0, active call room terminated; clone cleaned |
| Authenticated SIP dispatch/media | `$MEDIA_PY deploy/telephony/sip_probe.py` | PASS: unauthenticated challenge; digest INVITE 200; source/negotiated-codec checked 187 RTP packets / 100 voiced packets; greeting content independently verified; SIP + agent isolated room observed; BYE 200 and room teardown |
| Wrong-number ingress | Same SIP probe | Wrong number never answered or dispatched during monitored 35-second window; bridge may send provisional ringing rather than a final 4xx; own trunk/rule/room cleaned |
| Real booking bridge | `docker exec -i livekit-worker-1 python - < deploy/telephony/booking_probe.py` | PASS: native SDK tools → persistent journal → installed Easy API; appointment independently read, foreign cancellation rejected, owned cancellation verified by subsequent 404; synthetic appointment/customer cleaned |
| Installed dependency consistency | `docker exec livekit-worker-1 pip check` | No broken requirements |
| Whitespace | `git diff --check` | Exit 0 |

Live runtime inspection also confirmed local source/deployed fingerprints match
for worker, telephone policy, SIP provisioning and cached fallback WAV. LiveKit
room/trunk/rule counts were all zero after probes: no dangling test resources,
and **no permanent carrier trunk exists without an assigned number**. Credential/
known-transcript comparisons against worker logs passed without revealing values.

The probe uses Python 3.12's standard-library `audioop`; its Python 3.13 removal
warning is expected. Upgrade work must replace that diagnostic decoding step.

## Failure regressions and independent review

- Privacy/readiness tests first failed on public calls, caching, incomplete
  LiveKit credentials and persisted text. They now cover operator/no-operator/
  invalid-auth paths, no-store errors, static new HTTP summaries and false
  carrier/public readiness even with a misleading environment flag.
- Initial booking fixtures exposed real Dispatcher name/result mismatches;
  tests now use actual schemas and `slots[].slotId`, `hold_id`, `booking.id`.
- SDK initially reserved the entire worker for one job; two idle processes match
  two-job capacity. VAD-state-edge interruption fixes delayed batch-STT barge-in.
- Independent adversarial review identified unended SIP legs, word-price bypass,
  unbounded fatal-close/cancelled cleanup and existing-trunk duration bypass.
  Each was reproduced, fixed and covered by regressions. Room termination and
  adapter/session cleanup are bounded and attempted independently; cancellation
  is propagated only after cleanup. Trunks require ringing 30 s / call 660 s,
  including matching pre-existing objects; no automatic overwrite.
- Dedicated reviewer was unavailable due to provider quota; the read-only
  exploration lane supplied independent audit and bounded follow-ups. Final
  round independently ran **15 worker/SIP tests**, all passed, and found **no
  remaining P0/P1 in the scoped fixes**. No secrets were read by that reviewer.
- Deployment unhappy-path tests cover clean environment, Docker failure,
  validation failure and nonzero exit propagation without sensitive output.

## Release boundary

These proofs demonstrate real provider-backed room audio, protected private SIP
dispatch, lifecycle and native booking-tool integration **separately**. They do
not prove a full spoken-consent booking conversation, a real DIDWW codec/auth
path, public NAT, regulatory eligibility, carrier channel/overflow behavior,
approved property FAQ, human transfer or real-guest readiness.

The LAN host still needs an owner-approved public SIP/RTP route in addition to
the actual DIDWW number. The HTTP Cloudflare/Coolify site is not that route.
`deploy/telephony/README.md` lists exact activation gates. `/api/status.telephone`
keeps public/carrier verification false; secrets/config flags cannot set them true.

## Delivery and public HTTP wire verification

Implementation commit **`cc7ae5658f1f69f2954399234dce2535e158a4e2`** was pushed to
`origin/master` and deployed by Coolify application 13. The worker is a separate
local digest-pinned image; it was deployed and source-fingerprint checked as above.
The intended-file scan checked all 32 implementation files against actual runtime
credential values in memory, plus private-key/provider-token patterns, without
printing values. A pre-existing media identifier used by test fixtures was changed
to a non-production fixture; the targeted dashboard/privacy suite then passed
**25 tests**. Only intended files were staged; goal state and unrelated untracked
`:memory:.ses` were excluded and not deleted.

The first HTTP replacement exposed an existing operational durability defect:
Dockerfile `VOLUME ["/data"]` without Coolify Persistent Storage provisioned a
new anonymous volume. Its Easy journal had zero rows; the original worker journal
had seven. No authenticated writes were sent to that new web instance. Before
further operation, application 13 was explicitly configured to reference the
original volume at `/data`, and safely redeployed the same implementation commit.
The original data was not copied, reset or deleted; unused anonymous volumes were
left intact. This is now an explicit runbook prerequisite in `COOLIFY.md`.

Final wire/runtime checks passed against healthy container
`zs7s830dsrlo4j81s0ohgpgc-100119898144`:

- HTTP and worker **same volume name**, both independently read the preserved
  journal's **7 rows**; both containers healthy. Web server/dashboard source
  fingerprints match the pushed implementation.
- Public HTTPS `/api/calls`: anonymous **403**, invalid bearer **403**, operator
  **200**; all **`Cache-Control: no-store`**. Private body contents withheld.
- Public HTTPS `/api/turn`: GET method/route error **404**, unauthenticated POST
  **403**; both **`Cache-Control: no-store`**.
- Public HTTPS `/api/status`: media credentials configured **true**, public
  ingress verified **false**, carrier call verified **false**.
- Complete installed worker graph matches the **79 pinned packages** in the
  runtime lock; Python syntax parse for app/deployment/tests passes.

This evidence/runbook follow-up is documentation-only; no code differs from the
verified implementation commit. The goal is carrier-independent runtime BUILD,
not authorization for a number purchase or a real-property/PSTN release.
