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
- The public presentation reuses the earlier committed Meretuule restaurant
  wording/design, existing local fonts/CSS and the current restaurant DTO.
  Archived hotel/spa assets remain separate for explicit rollback mode.
- Published telephone FAQ `7df7edb` contributes the reviewed unsupported-note
  and food/takeaway/delivery answers. Current explicitly fictional menu data and
  allergen declarations remain authoritative; no real menu or allergy safety is
  asserted.

## Reproduced defects

- Four failing-first public-route/link checks exposed restaurant `/hotel` 410
  behind the existing public-root rewrite and zero dashboard demo links. The
  selected public renderer now works on the guest host while direct robot
  `/hotel` stays 410. Both operator links use the canonical Meretuule root.
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

## Executed verification

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
