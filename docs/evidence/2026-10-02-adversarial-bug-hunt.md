# Adversarial bug hunt — 2026-10-02

**This is a fictional pilot, not a production approval.** The user requested
more testing and concrete mistakes, not another happy-path readiness claim.
This round uses isolated HTTP fixtures, actual headless Chromium, deterministic
fault injection and bounded synthetic provider/media checks. No outbound phone
call, purchase, real guest write or credential disclosure is authorized here.

## Baseline

The tracked tree started clean at `3b05923`; the operator dashboard redesign
and active signed Twilio bridge were preserved. Existing untracked `.opencode/`
and `:memory:.ses` are unrelated and remain uncommitted.
During testing, the independent documentation-only revision `9b4e8f0` landed
on `master`. It was fast-forwarded without overwriting the in-progress repairs;
the new signed GitHub auto-deployment documentation was preserved.

- Pinned media full suite: **590 passed / 4 skipped**.
- Core full suite: **471 passed / 30 skipped**.
- Native worker dependency check: no broken requirements.
- Live pre-test storage: **22 booking-journal rows / 33 call rows**, both SQLite
  integrity checks `ok`. These are audit/journal counts, not active appointments.
- Bridge health `configured=true`; unsigned public POST **403 + no-store**.

Passing the old suites did not mean the additional negative paths were correct.

## Bug ledger

Twenty defects were reproduced in the initial independent/owner discovery;
review found one additional pre-existing receipt defect. **20 of these 21 are
repaired; one P2 remains open.** The independent review also caught a race in
the initial repair itself; that is recorded below rather than counted as another
pre-existing defect. P1 means high priority, P2 medium, P3 lower priority.

| ID / severity | Reproduced defect | Current state / regression |
| --- | --- | --- |
| B01 P1 | Creation/cancellation accepted `202`, redirects or other non-completion statuses as authoritative cached success while inventory contradicted them. | Fixed: creation requires **201**, cancellation **204 / documented 404**. Ambiguous responses stay unknown, no blind replay. `test_adversarial_adapter.py`. |
| B02 P1 | SDK process shutdown was 10 s despite its 15 s pre-cancellation wait; Docker's 40 s grace also expired before the full drain/cleanup budget. | Fixed: process shutdown 40 s and Docker grace 120 s; native-contract budget regression. `test_adversarial_media.py`. |
| B03 P1 | Fatal-error apology used `SOURCE_UNKNOWN`, ignored by the microphone-only bridge; replacement of an old mic was also ignored. Old-track EOF could end the call before replacement. | Fixed: subscribed microphone fallback from the already-bound agent; terminal track epoch rejects retired-mic controls and protects replacement output. `test_adversarial_media.py`. |
| B04 P1 | A historical cancellation replay replaced a fresh native confirmation's spoken receipt without a new DELETE. | Fixed: cached replay cannot overwrite an established current-turn mutation. Native policy regression in `test_adversarial_policy.py`. |
| B05 P2 | Fractional pages and impossible calendar dates in dashboard links produced invalid reads. | Fixed: bounded integer page / native date-input fallback. `dashboard_browser_checks.js`. |
| B06 P2 | Stalled login, reads or turns permanently trapped controls. | Fixed: 30 s read/session/auth and 120 s turn deadlines; stale data retained, uncertain writes never replayed automatically. Node and real-browser abort regressions. |
| B07 P2 | Non-string Groq HTTP STT success payloads became invented utterances. | Fixed: typed rejection before LLM dialogue; five payload subtests in `test_providers.py`. |
| B08 P2 | A waiter reused an expired or already-consumed pre-lock hold snapshot. | Fixed: live hold rechecked under writer lock after same-key durable replay. `test_adversarial_adapter.py`. |
| B09 P2 | Failed search validation retained ownership of its valid prefix, allowing an unreturned deterministic slot ID to be held. | Fixed: validate the full batch before atomic ownership update. `test_adversarial_policy.py`. |
| B10 P2 | An unrelated later read error hid a completed write in speech and UI status. | Fixed: receipt retained, secondary failure disclosed separately; price gate and sticky mutation uncertainty preserved. `test_adversarial_policy.py`, Node UI checks. |
| B11 P2 | FastAPI parsed oversized unauthenticated non-object bodies and echoed megabytes before route-level bounds ran. | Fixed: authenticate first; bound streamed bytes at **750,000** before JSON parsing, including misleading/missing Content-Length; small static invalid-JSON errors. `test_adversarial_policy.py`. |
| B12 P2 | Equivalent `10:30` / `10:30:00` availability strings falsely invalidated the same slot. | Fixed: parsed wall-time comparison. `test_adversarial_adapter.py`. |
| B13 P2 | Abandoned expired holds accumulated beyond all other map bounds. | Fixed: prune on creation, cap live holds at 5,000; oldest evicted holds fail closed. `test_adversarial_adapter.py`. |
| B14 P2 | Carrier clear resumed forwarding while native interruption was still incomplete, allowing old PCM after clear. | Fixed: prompt clear, nonce-matched resume only after native Future completion; failed/cancelled/timeout interruption fails closed, all predecessor controls owned and cancelled. `test_adversarial_media.py`, native SDK tests. |
| B15 P2 | Native output errors became a normal silent close. | Fixed: closed failure flag, fallback when usable and error close **1011**. `test_adversarial_media.py`. |
| B16 P2 | First-audio/failure paths waited for serial SDK cleanup before carrier termination. | Fixed: stop output and bounded fallback/socket termination precede slow cleanup. `test_adversarial_media.py`. |
| B17 P2 | Provider/session construction errors bypassed adapter and owned-room cleanup. | Fixed: lifecycle protection begins before allocation; partial resources tolerated. `test_adversarial_media.py`. |
| B18 P2 | Cached native apology PCM is labelled with the original greeting in ephemeral assistant history. | **OPEN**, exact PCM plus real AgentSession history reproduced. Named **xfail**, not a pass. No unauthorized consent demonstrated; recap invalidation still holds. |
| B19 P2 | A custom bridge dispatch name was not passed to worker registration. | Fixed: shared `VOICEBOT_AGENT_NAME` Compose setting; parsed-manifest regression. |
| B20 P3 | Malformed duration/end range created a customer before deterministic appointment failure. | Fixed: 1–1440-minute bound and complete range calculation before customer POST. `test_adversarial_adapter.py`. |
| B21 P3 | Failure-player source closure was skipped when publication/unpublication failed. | Fixed: independent bounded source finalizer. `test_adversarial_media.py`. |

The fixes are deliberately small: no new dependencies, provider API expansion,
dashboard redesign, unguarded retry, or weakened booking consent.

## Software verification and live failures

```sh
.venv/bin/python -m pytest tests -q
/tmp/opencode/voicebot-telephony-venv/bin/python -m pytest tests -q
node tests/dashboard_ui_checks.cjs app/dashboard/static/dashboard.js app/dashboard/static/index.html
node /tmp/opencode/voicebot-browser-fixtures.cjs
docker exec livekit-worker-1 pip check
git diff --check
# In an environment inheriting only the private demo credential:
EASY_LIVE_TESTS=1 .venv/bin/python -m pytest tests/test_easyappointments_installed.py -q
```

- Final integrated software suites: **504 core passed / 31 skipped**,
  **640 media passed / 4 skipped / 1 xfailed**, plus five passing payload
  subtests. The xfail is **B18**, not hidden in the passing count. Suites overlap; these are not
  additive unique-test counts. No deselections.
- Opt-in installed Easy!Appointments **1.6.0** suite: **4 passed**; real
  validation, creation/update/cancellation, same-slot contention, committed-write
  timeout/restart reconciliation and trusted-customer creation. Each test removed
  its exact owned fictional appointment/customer; isolated journals, no paid
  speech providers. These were the four optional skips in the default media run.
- Existing deprecations: FastAPI/TestClient's HTTPX path, and Python 3.12
  `audioop` in the media suite. No new test warning is introduced.
- Node authentication/privacy/timeout checks: `ui_checks_ok`.
- Chromium fixture checks: six widths **320–1440 px**, malformed deep links,
  bad/good authentication, paging, stale/empty rows, text conversation,
  microphone-denial guidance, keyboard navigation, reduced motion,
  logout during a delayed read and stalled-network recovery; **zero JS errors**.
- An initial loopback-only HTTP test image at **8030** passed the real-provider
  browser proof: microphone STT, Azure playback, delivered canonical recap,
  consented fictional creation, independent REST readback, cancellation **404**,
  actual-day panel selection, end/logout/storage cleanup and mobile layout.
  The exact new fictional customer was cleaned. `carrier_verified=false`.
- Later integrated-image real-provider verification at **8031** timed out twice
  waiting for the consented booking's row. The instrumented second run confirmed
  authentication, privacy, microphone/STT/playback and delivered canonical recap
  passed first; no active appointment remained at the probe slot on independent
  REST readback. These failed runs are **not** substituted with the earlier
  successful 8030 proof. That image predates the final historical-replay repair.
- Two native spoken lifecycle attempts failed: first no exact affirmative/no
  consented booking; then exact affirmation created a booking, but spoken
  cancellation was not recognized. Owned appointment/customer/room cleanup ran.
  Direct in-memory ASR recognized the same confirmation fixture **3/3**. Room
  segmentation/model/provider reliability remains an acceptance gap; consent
  was not relaxed to fuzzy matching, and tests were not repeated until green.
- Signed configured Twilio HTTPS/WSS/native-PCM/replay smoke passed. Its native
  provenance mark can also identify cached apology audio; it does **not** prove
  healthy STT/LLM/TTS, carrier playback or a real PSTN call.
- The JavaScript content-versioned URL was updated with the changed script;
  the existing asset-hash regression prevents publishing a stale URL.
- Reviewed media-image fault injection: forced Azure authentication failure
  yielded **375,040 PCM bytes**, independently transcribed as the cached Estonian
  apology (similarity **0.95**). An owned active-job clone under actual Docker
  stop with **120 s** grace rejected new work, terminated its room and exited
  **0**. Normal worker and bridge were not stopped by these tests.
- The proposed missing-HTTP-hold-ID hypothesis was rejected: existing trusted
  context already contains the current ID. Five offline real-policy cases cover
  approved, declined, expired, uncertain and cancellation turns; a single
  provider-choice diagnostic selected the exact owned confirmation arguments
  with **zero writes**. This does not clear the intermittent live failure; no
  speculative prompt change or retry-until-green loop was shipped.

The first browser MCP attempt hit its sandbox's missing `URL` global; the
native Node/Playwright runner was used for product assertions. The first local
Docker build hit the host's root-owned buildx activity path; an isolated
credential-free Docker configuration built the test image successfully. Neither
environment failure is represented as a product defect or a passing test.

## Independent review and testing mistakes caught

The first integrated review returned **FAIL** for B04 and a late-clear race in
the initial B03 repair. Both were reproduced with gated, credential-free
RED regressions before repair. Terminal fallback selection now retires the
old track's controls immediately; task/stream resources are selected after
predecessor completion and all pending controls are owned during close.

The full suite also caught an introduced price-guard ordering regression and
a test-only inherited `__new__` patch leaking into later constructors. The
price guard was restored; the test patches the factory at its module boundary
instead. Neither failure was dismissed by deleting an existing assertion.
The two final software suite results above include these corrections.
Round 2 returned **Verdict: PASS**, with seven independent isolated checks for
receipt replay, overlapping controls, stale/foreign controls, terminal fallback,
predecessor cleanup and both cancellation meanings. No remaining code-backed
P0/P1 was found in that repair scope. This is not production or PSTN approval.

## Production-release gaps remain

1. **No independent incoming PSTN acceptance.** Signed HTTPS/WSS and private
   audio are not evidence that the carrier number provides reliable two-way
   speech, interruption, booking/cancellation and hangup to a real caller.
   The failed live room/browser lifecycle runs above are additional evidence
   against claiming reliable voice operation, even before carrier acceptance.
2. **Exposed-token revocation is not independently verified.** Current locally
   supplied credentials authenticate; that does not prove the previous token
   was revoked. No account-side credential mutation is performed by this hunt.
3. **Booking deployment is a sole-writer, single-host synthetic backend.** It
   is not approved for independent admin/API writers, distributed replicas,
   real guest data or a real property's inventory.
4. **Operational acceptance is incomplete:** provider-wide quota/overload
   policy, real carrier overflow/human transfer, sustained load/soak, disaster
   recovery and restore drills are not proven by these short tests.
5. **Browser hardening gap:** public responses did not expose CSP,
   `X-Content-Type-Options` or HSTS headers during this read-only check. No XSS
   exploit was demonstrated; the current UI renders provider text with
   `textContent`, not HTML. This is not a penetration-test certificate.
6. **Historical capacity guidance is not live capacity evidence.** The dated
   September architecture discusses a three-channel target; the current
   private runtime/Twilio admission limit is two. Public SIP/RTP is still an
   unverified alternative, not a requirement of the active Twilio stream route.

## Delivery and preservation verification

- Repairs committed and pushed as **`ae587e5`**. Only the 21 intended files were
  staged; the documentation-only upstream update and unrelated untracked files
  were preserved. Scan of intended files against eight configured credential
  values and key patterns found **zero matches**; `git diff --check` passed.
- The signed GitHub push hook queued Coolify application **13**, deployment
  **227**, and finished at the exact code revision
  **`ae587e511aa34a2f87489d131cc19d95bd75c191`**. No second deployment was queued
  manually. The independently reviewed image was deployed to the worker and
  bridge only; existing booking, Redis, SIP and LiveKit services were preserved.
  GitHub delivery **`3846079768883625984`** matched `refs/heads/master` and this
  commit, returned HTTP **200**, and the receiver's per-application status was
  **`success`** (not merely a successful HTTP transport).
- Web/API, worker and bridge are healthy. Ten source/asset hashes in each
  container match the committed files. Worker Docker stop grace is **120 s**;
  worker and bridge dispatch names match. `pip check`: no broken requirements.
- Public HTML and versioned JavaScript match local bytes through the public
  endpoint; script version **`a6662cc5f1c3`** equals its SHA-256 prefix.
  Deployed Chromium at **390 px** passed malformed-link recovery, no overflow,
  zero JavaScript errors and **zero anonymous private fetches**.
- Actual public HTTP: anonymous private reads **403 + no-store**; oversized
  unauthenticated turn **403** before JSON parsing; authenticated invalid JSON
  **400**, oversized body **413**, small private errors; authenticated booking
  read **200 + no-store**. Unsigned Twilio voice POST remains **403 + no-store**.
- Fresh configured credentials passed the deployed signed HTTPS/WSS/native-PCM
  mark and consumed-nonce replay gate. **Still not a carrier call.** Bridge
  health remains `configured=true`; there were **zero active rooms** after the
  probe, so no owned synthetic call was left running.
- The exact original `/data` volume remains mounted by web and worker. Every
  pre-deployment row hash was preserved: booking journal **25 → 25**, calls
  **48 → 49** (one new synthetic media summary); both integrity checks **ok**.
  The earlier pre-test baseline was 22/33; the difference is test audit history,
  not active inventory. Owned adversarial test containers were removed without
  deleting volumes; the existing `voicebot-hackathon-check` was left healthy.
- This post-deployment evidence is a documentation-only follow-up using
  `[skip cd]`; it does not restart services or change the verified application
  source. **Shipping these repairs clears none of the open production gates.**
