# Restaurant dashboard and named public demo

## Source and scope

- Operator: <https://robot.arleserver.cfd/>; public fictional Meretuule venue:
  <https://meretuule.arleserver.cfd/>. Existing Coolify application 13 and its
  stable host-scoped Traefik service are reused, with no new DNS, service,
  credential or dependency.
- Published restaurant PR #7 advanced master to `8bab6fb` during integration.
  This release uses `RestaurantCallTools` and `RestaurantAdapter`, selected by
  `VOICEBOT_BUSINESS_TYPE=restaurant`, not the older standalone table core.
  The reviewed historical integration `156a9d5` remains on its pushed feature
  branch as an audit record; it is **not** the deployment source. Only our own
  unfinished merge was aborted before creating a clean worktree on master.
  No other owner's uncommitted source or goal was overwritten.
- Concurrent published domain fix `36a9c3d` supplies the existing authored
  restaurant reception at the canonical Meretuule root and two robot demo links.
  Its ingress removes the obsolete root-to-`/hotel` rewrite. This implementation
  is reused without a new public design or parallel hotel presentation. Our own
  undeployed alternative renderer was removed; its audit history remains in
  `0c457a4`. Archived hotel fixtures remain separate for explicit rollback mode.
- Published telephone FAQ `7df7edb` contributes the reviewed unsupported-note
  and food/takeaway/delivery answers. Current explicitly fictional menu data and
  allergen declarations remain authoritative; no real menu or allergy safety is
  asserted.

## Reproduced defects

- Four failing-first public-route/link checks exposed restaurant `/hotel` 410
  behind the existing public-root rewrite and zero dashboard demo links. The
  first alternative renderer was verified but not deployed. The subsequent
  published domain fix already solves these defects with the authored restaurant
  UI; normal merge preserves it and keeps `/hotel` retired. Its regression first
  failed against our alternative renderer, then was restored to the published
  contract. Both operator links use the canonical Meretuule root.
- Twelve real-constructor/HTTP failures exposed missing published restaurant
  answers. The existing shared bank loader/matcher is used inside the selected
  restaurant subclass, respecting final transcripts and explicit language tags.
  Unknown writes, delivered-recap consent and ownership retain priority.
- Independent review reproduced mixed FAQ/table requests losing their booking
  clause and combined repeats reversing order. ET/EN/RU tests now require the
  actual reservation planner and requested time/headcount. A real HTTP test
  prepares the requested table without confirmation. Repeats render saved IDs
  in caller order. The full suite also caught an overbroad hotel-room inquiry;
  the original domain refusal was retained and freshly verified.

## Initial executed verification (before concurrent domain merge)

```sh
env -i PATH=/usr/bin:/bin HOME=/tmp/opencode LANG=C.UTF-8 \
  PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 EASY_LIVE_TESTS=0 \
  /tmp/opencode/restaurant-telephone-venv/bin/python -m pytest -q -ra \
  -p no:cacheprovider --tb=short \
  --basetemp=/tmp/opencode/restaurant-dashboard-current-final-isolation-green
```

- **3,114 passed; 36 subtests passed; 4 private-backend opt-in skips**; two
  upstream deprecation warnings; 68.25 seconds. Untouched published baseline:
  3,090 passed, the same subtests/skips/warnings.
- Ten local Chromium browser scenarios passed. Retained legacy rollback checks,
  restaurant direct ET/EN/RU confirmation/cancellation, streamed voice recap,
  explicit reading, synthetic microphone WAV and logout isolation passed.
  Public layout at 320–1440 px, canonical links, safe provider text and closed
  failed-catalogue behavior passed. Zero external requests/page errors.
- Two independent Codex-account static reviewers examined the final current
  implementation. Their concrete findings were reproduced and fixed; focused
  final re-review found no remaining P0/P1 in the corrections. Reviewers did not
  independently execute commands or approve production acceptance.
- Private speech harness self-test: **33 boundary cases + 12 restaurant inputs**,
  no provider calls. Live provider acceptance requires the published revision,
  restaurant worker, shared rollout lock and fresh caller/assistant audio checks.

## Activation boundary

Fresh count-only runtime baseline:
`/tmp/opencode/restaurant-dashboard-current-before-runtime.json`.
Web/worker/bridge were healthy `8bab6fb`, zero restarts; worker and web shared the
original `/data` volume. Integrity checks passed for spa, stay, call history and
restaurant databases. Preserve those files and incoming media/carrier routing.

Deployment and fresh live source/URL/storage/provider checks are recorded in the
activation follow-up, not inferred from local tests. No real restaurant booking,
PSTN/physical-microphone acceptance, allergy safety, kitchen notification, food
ordering or payment acceptance is claimed.

## Concurrent publication integration

Publication was safely stopped by the ancestor gate when master advanced to
`36a9c3d`. No force push, overwrite, routing replacement or deployment occurred.
Its authored presentation, canonical links/styles, read-only public acceptance
and disabled unauthenticated booking controls are retained. Installed ingress
and release-controller source already match the published repository files;
no self-upgrade or extra installation is required.

Published PR #8 (`3af499b`) was also normally merged without conflicts. Its
closed whole-turn natural Estonian confirmations, spoken recap dates and saved
reservation list are retained; no reset or replacement of newer master occurred.

## Final prepublication verification

- Fresh full suite after both merges: **3,156 passed; 36 subtests passed; 4
  private-backend opt-in skips; 2 upstream warnings**, 259.50 seconds. Same
  isolated command above, with basetemp
  `/tmp/opencode/restaurant-domain-current-pr8-final`.
- All **nine** retained local Chromium scenarios passed with unchanged
  assertions, zero page errors and zero external requests. Restaurant checks
  include ET/EN/RU preparation/confirmation/cancellation, natural Estonian ASR
  confirmation, saved booking after reload, page reset, voice receipt, synthetic
  microphone WAV and logout isolation. Legacy hotel fixtures are rollback
  regressions, not a second published guest site.
- Initial shared-host attempts had an English timeout and native playback timing
  assertion, then browser launch failures. Memory and swap were full and load
  exceeded 124 on 12 CPUs. Both unchanged legacy cases passed isolated retries.
  Final verification ran each scenario in a separate instance of the same
  Chromium 153.0.8010.12 with a temporary single-renderer adapter outside the repo.
  No test assertions, product code or other services were weakened/restarted.
- Both Codex-account reviewers rechecked the actual merged source: no remaining
  actionable P0/P1/P2 in the scoped domain/auth or phone-bank merge. Their review
  remains static; runtime results are the parent's executed evidence.
- Updated private restaurant audio-harness self-test again passed 33 boundary
  cases and 12 restaurant inputs, zero providers called.

Publication was again deferred, before any push/restart, when published master
advanced to `408cee1`. Its native male/calm voice options, authenticated fixed
auditions and restored operator-dashboard layout were merged normally without
conflicts. The guest host retains its existing restaurant-demo presentation;
the robot host gets the published operator layout rather than a new redesign.

Final source verification after this merge: **3,181 passed; 36 subtests passed;
4 private opt-in skips; 2 upstream warnings**, 66.23 seconds, basetemp
`/tmp/opencode/restaurant-domain-current-408-final`. All nine isolated Chromium
scenarios passed again, including operator layout and unchanged public demo.
Both Codex-account reviewers rechecked this merged bank/domain compatibility
and found no remaining scoped P0/P1/P2. Their inspection remains static only.

Publication and fresh live source/storage/private-speech acceptance remain
pending. Historical initial counts do not stand in for deployment evidence.
