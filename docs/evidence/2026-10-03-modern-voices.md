# Modern website voice verification — 2026-10-03

## Scope and preserved release

The user requested implementation of newer voice choices and lower browser-demo
delay. Azure remains the default/fallback; provider profiles are session-owned.
The same guarded turn retains authorization, ownership, exact prices, canonical
recaps, delivery receipts and later explicit consent. No carrier action, new
account provisioning, voice cloning or real guest booking was performed.

Feature commit `d8447bc` follows the design/plan commit `96a3c25`. Normal merge
`b85f5df` incorporates concurrent upstream `251500f`, preserving all 28
upstream-only paths. The only overlapping path is `COOLIFY.md`; native lifecycle,
release synchronization and reviewed FAQ changes were not discarded or rewritten.
Final fixture hardening and this evidence follow that merge.
An additional normal merge incorporated `f1547310b0f4e67b4743a3250ba1da2bbeadd7e2`,
which changes only two upstream native tests to match FAQ policy and await async
cleanup. Modern-voice production code remains unchanged.

## Regression results

- Isolated task interpreter: Python 3.12.3 with pinned core dependencies,
  `websockets==17.1`, `google-auth[requests]==2.59.1`, `pytest==9.1.1`.
- Final core: `python -m pytest tests -q --tb=short` — **2,511 passed,
  57 skipped, 36 passing subtests**, one existing Starlette/httpx deprecation
  warning, 33.82 seconds.
- Final pinned media: read-only `voicebot-telephone:b1940070d94b`, network disabled,
  isolated test dependencies and native site-packages first in `PYTHONPATH`,
  `python -m pytest tests -q -p no:cacheprovider --tb=short` — **2,742 passed,
  9 skipped, 36 passing subtests**, existing audioop/Starlette warnings,
  51.40 seconds. The earlier baseline failure and its upstream test alignment
  are recorded below rather than represented as a modern-voice repair.
- Independent final review: all six feature modules — **128 passed**. Syntax and
  whitespace checks passed. Three review rounds left no outstanding P0/P1/P2
  findings in the modern-voice change.
- All eight exported browser suites passed on Chromium 153.0.8010.12 with real
  advancing synthetic audio and no page errors. Existing dashboard, public hotel,
  booking, microphone-race and English-demo coverage stayed intact.

Counts overlap across suites; do not sum them. Fixtures do not establish provider
pronunciation, human preference, actual caller latency or a successful PSTN call.

## Observed RED/GREEN and review fixes

Provider, registry, guarded transport, selection and UI tests were observed failing
before their respective implementation. Tests cover exact provider wire requests,
immutable language views, header-only credentials, missing configuration,
bounded/malformed/truncated audio, one pre-output Azure fallback, no fallback after
partial output, cancellation and cleanup.

The actual pinned WebSocket client/server fixture verifies ElevenLabs connection
options and audio before terminal completion. It does not verify a live account;
the current ElevenLabs guide/reference inconsistency remains in the runbook.
Google REST is explicitly buffered rather than mislabeled native streaming.

Independent review found two issues, both reproduced RED then fixed:

- A native underrun followed by resumed playback could automatically acknowledge
  a recap. Waiting/stalled interruption is now sticky and generation-scoped;
  only the separate explicit text-reading acknowledgment remains available.
- The frontend wire limit ignored base64 expansion. Separate 8 MiB decoded and
  12 MiB wire bounds now accept the server-valid maximum while retaining limits.

Cross-lane tests also reproduced and repaired the catalog envelope mismatch,
unbounded queue backpressure and late old-turn disconnect invalidation. The
catalog carries validated 300–2000 ms endpointing, defaulting to 650 ms. A stalled
transport retires after 120 seconds without canceling or replaying owned work;
late invalidation cannot clear a later turn's receipt.

## Actual native browser streaming evidence

The final complete browser command used the existing installed Playwright package
and `with_server.py` with **`exec`-prefixed** fixture servers on ports 8765/8776:

```text
node tests/run_browser_checks.cjs
```

The gated local fixture emitted valid MP3 while synthesis remained unfinished.
Native playback advanced to **0.035475 seconds**, measured **209 ms** after the
synthetic test's send timestamp, before provider completion. This number is
fixture evidence, **not an Azure/cloud/PSTN latency benchmark**. An actual native
buffer underrun occurred; later successful `done`/EOF and playback completion
did not grant automatic acknowledgment. Explicit reading remained functional.
The fixture performed **zero writes** and no real provider requests.

The companion native check passed seeking rejection, blocked autoplay controls,
truncation/decoding failure, full played coverage, Blob fallback and logout cleanup.
The broader voice suite passed eight turns; the modern fixture passed six.

Earlier fixture failures were not hidden: an old decode-error fixture awaited
playback of a source cleanup had removed; it now reloads valid audio before the
microphone-overlap test. Appended control routes were shadowed by the catch-all
static mount; an observed RED test and route ordering repair cover that boundary.
A stale shell-child fixture server also explained repeated old-source results;
targeted owned-process cleanup and `exec`-based restart fixed the harness. Both
ports were verified released after the final run.

## Separately reproduced native baseline

`tests/test_native_booking_terminals.py::test_native_speech_normalizes_hours_after_guard_without_replacing_history`
failed at line 190 before the final upstream test alignment: expected
`09:00–17:00`, received the upstream clarification
reply after `Mis on tööajad?`. The **identical failure** reproduces at unchanged
`251500f587595715948f9597c0d67a6644e98fd4` in a detached clean worktree under the
same pinned media environment. The failing test and native/FAQ code are unchanged
by this voice feature. No unrelated repair was attempted or claimed.
Upstream `f154731` subsequently changed that fixture to the explicit spa-hours
question consistent with the reviewed FAQ policy. The final full media suite
then passed all 2,742 tests with nine skips; this resolution belongs to the
preserved upstream change, not new voice generation logic.

An earlier pre-merge media run hit a timing-sensitive Twilio cleanup assertion.
The current and unchanged pre-merge targeted modules each passed 15 tests with
one skip; that failure did not recur in either full integrated media run. It is
not represented as a defect fixed by the modern-voice implementation.

## Live configuration and delivery boundary

The pre-publication production snapshot was healthy on `251500f`. Azure and
operator authorization were configured; ElevenLabs, Cartesia and Google speech
credentials were absent. Their catalog entries must remain unavailable until
configured. No paid synthesis or account validation for those providers occurred.

The existing signed GitHub master webhook remains the web deployment path and
the same shared `/data` volume must be preserved. Final deployment revision,
health, aggregate journal counts and synthetic live Azure checks are recorded
in the file-backed goal evidence after publication, not inferred from these
local suites. The separate native rollout remains owned by its existing goal;
new web provider choices are not telephone activation or subjective acceptance.
