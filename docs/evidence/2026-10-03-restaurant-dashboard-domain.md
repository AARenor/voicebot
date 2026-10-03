# Restaurant dashboard and named public demo

## Requested surfaces and source

- Operator dashboard: <https://robot.arleserver.cfd/>.
- Public fictional **Meretuule restoran** demo: <https://meretuule.arleserver.cfd/>.
- Reused committed restaurant source `61051d4`, published restaurant telephone
  answers `7df7edb`, and published voice/delivery repairs `3db9fb8`. No files from
  another owner's dirty worktree were copied. Further published-master integration
  and deployment acceptance are recorded below when verified.
- Existing Coolify application 13 serves both hosts. Its stable service is
  `https-0-zs7s830dsrlo4j81s0ohgpgc@docker`. The existing Meretuule ingress rewrites
  only `/` internally to `/hotel`; robot `/hotel` paths redirect to the canonical
  public root. The compatibility filename is not a hotel product.
- Existing restaurant pages already have the correct canonical links and a
  table-only composer/ledger. No new frontend, application, DNS record, provider
  credential or repository dependency was needed.

## Reproduced integration defects and narrow fixes

1. Restaurant core disabled the reviewed FAQ language/matching shortcuts. Real
   Dispatcher construction and HTTP routing reproduced 21 failures. The shared
   matcher now uses only the bank selected by trusted business state; caller
   `business`/`domain` fields are rejected. Mixed requests retain the entire
   booking clause for planning; the bounded preference parser was not weakened.
2. Published browser receipt validation understood slot/stay inventories but not
   `held_tables`. Valid-audio restaurant confirmation regressions failed until
   the table inventory was added to the same pending-object/expiry/ownership
   validator. No automatic acknowledgement or consent was introduced.
3. The reachable public configuration advertised retired hotel/spa and provider
   samples. Restaurant configuration now exposes only selected fictional venue,
   business and synthetic mode; the legacy fixture branch is preserved.
4. Replanning the sole six-seat table blocked on its own allocation. Identical
   owned live sittings reuse their hold, with fresh preparation and no renewed
   expiry/consent. Replacement searches retire only owned, unconfirmed holds in
   a transaction; foreign, confirmed and uncertain-write capacity is untouched.
   Released hold-action receipts are evicted, not confirmation/cancellation
   receipts. Real-adapter failures were reproduced before each fix.
5. Exact selected restaurant manual FAQ questions also identify their language,
   including “Is this a real restaurant?”. No archived hotel/spa bank is imported.
6. Published nonblocking post-write ledger refresh and strict native/MSE/NDJSON
   recap delivery were retained during the merge. The stalled direct-read browser
   regression failed before the nonblocking refresh was restored.

## Verification before deployment

Isolated Python suite command, with a fresh temporary directory for each run:

```sh
env -i PATH=/usr/bin:/bin HOME=/tmp/opencode LANG=C.UTF-8 \
  PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 EASY_LIVE_TESTS=0 \
  /tmp/opencode/restaurant-telephone-venv/bin/python -m pytest -q -ra \
  -p no:cacheprovider --tb=short --basetemp=/tmp/opencode/restaurant-dashboard-after-review-final
```

- At this recorded checkpoint: **3278 passed, 36 subtests passed, 5 skipped**, two
  upstream warnings, 64.27 seconds. Four skips require private legacy backend
  opt-in; one requires an explicitly selected local Docker image. Later replay,
  streamed-table receipt and published-master checks must supersede this count.
- Eight local browser journeys passed with the actual durable restaurant adapter
  and fictional providers, widths 320–1440, zero external requests/browser errors.
  Covered search/prepare/exact reading/separate confirmation/independent ledger/
  owned cancellation, cross-session 409, same-hold stale receipt denial, uncertain
  write lockout, microphone races, English, modern voices and guarded streaming.
- **48 Chromium delivery checks passed**, including one-use receipts, stalled
  reads, contiguous playback, seeking, interruption, stale callbacks, microphone
  capture, preparation expiry, MSE/EOF and truthful provider-failure behavior.
- Cached Playwright 1.63.0 / Chromium 153.0.8010.12 was reused; no browser download.
- Two independent OpenAI/Codex-account static review lanes: initial blocking
  findings were reproduced and fixed; Round 2 found no remaining P0/P1. Its P2
  released-hold replay finding was subsequently reproduced and fixed. Final
  published-master integration requires the last review/verification round.
- Strict live predeploy acceptance correctly failed with the existing title
  `Meretuule — hotelli ja spaa demo`. Local passing tests do not prove activation.

## Preservation and activation boundary

Count-only predeployment inspection verified healthy web/worker/bridge and the
original shared volume
`f2349b476eddc16df2bad6d3ed0b5e46d20a77390fdfb78f7d8cd20e924e26db`.
SQLite integrity checks passed for existing spa, stay and call-history databases;
restaurant state was not yet present. The safe baseline is
`/tmp/opencode/restaurant-dashboard-before-runtime.json`; no customer rows,
credentials, audio or transcripts were saved. A shared-rollout-lock check found
zero active rooms. Preserve signed incoming carrier routing and existing media
infrastructure; update only reviewed web/worker/bridge source and controller
profile reconciliation.

Deployment, served-source identity, live browser URLs/auth/asset checks and fresh
persistence acceptance remain unverified until the activation section is added.
No physical microphone, real PSTN call, real restaurant reservation, allergy
safety, kitchen notification, food order or payment acceptance is claimed.
