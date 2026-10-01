# Website booking architecture — verification evidence

2026-10-01, MODE RESEARCH; no application/credential/provider mutations.

## R1 recorded evidence

- `git status --short --branch`: master tracks origin/master; only preexisting
  `.opencode/` untracked before this goal.
- Source baseline `5e1c10c868d8fdceeae2184b8503811ce9e6288e`, canonical org origin.
- `webfetch https://robot.arleserver.cfd/health`:200 `{"ok":true}`.
- `webfetch .../api/status`: slot true, operator commands false, demo-data true.
- Read `app/server.py`, `app/dashboard/api.py`, UI lines280–492 and pinned
  deployment Compose: real booking dispatcher separate from synthetic UI queue.
- Public urllib probes returned Cloudflare403/error1010 even for health;
  source/client discrepancy recorded, no auth/protection conclusion inferred.
  Sanitized transport report retained at
  `/tmp/opencode/website-booking-architecture/runtime-readonly.json`.

R2/R3 and final artifact/repository/delivery verification follow below.

## R2 primary contracts and deployed runtime

- Stable1.6 REST/controller/Api/model fetched; pagination `page,length`, signed
  sort and explicit fields established from exact implementation (no invented
  offset API). Wrong guessed controller filename404 corrected to
  `Appointments_api_v1.php`; no claim based on failed fetch.
- Context7 official FastAPI dependency/DTO docs; OWASP deny-default/every-request
  auth; MDN no-store versus no-cache checked.
- `docker exec` deployed voicebot read-only probe: private catalogue reachable,
  one service/provider, five tools; filtered upstream list200/zero rows,
  invalid Bearer401; SOURCE_COMMIT9a8d1d2….
- Same runtime app probes: calls200/noauth/one summary-bearing row/no-cacheheader
  (content omitted), demo holds200/two rows, bookings404/absentOpenAPI.
- Browser read inspection: live page renders demo banner, two holds, disabled
  confirm buttons and one call; fetched routes are status/holds/calls/metrics.
  Calls response summaries/peer/service redacted before DOM insertion, only
  row count/boolean evidence returned. No credential entered.

## R3 disconfirming and unhappy-path evidence

- Browser confirmed: Demo badge/banner, two synthetic holds, disabled confirm
  buttons, one summary-bearing call; no live bookings section/voice form;
  `/api/bookings`404. Call summaries/peer/service sanitized before rendering.
- Runtime credentials never returned; wrong upstream Bearer401; no provider
  writes, auth settings or deployed behavior changed.
- Repository trace: adapter638–653 local holds,694–750 pending reconciliation,
  786–823 prerequisite/appointment durability; callslog122–160 and server288–297
  demonstrate raw-summary privacy gate. `/api/status` booleans not reachability.
- `.venv/bin/python` zoneinfo roundtrip success/failure probe: spring03:30 has
  zero valid roundtrips; autumn03:30 has two distinct valid offsets. Pass.
- Official Python/MDN/OWASP gap sources corroborated; remaining single-authority
  product contracts and empty populated-list-proof gap explicitly labeled.

## Artifact and repository verification

- Diagram sources pinned to5e1c10c…; `git diff 9a8d1d2 5e1c10c -- app deploy
  Dockerfile requirements.txt` has no differences. Current running behavior
  and diagram's inspected implementation bytes match, despite docs revisions.
- Archify3.0.1 first rejected excessive width, then measured label gaps and a
  route crossing. Evidence-based compact reflow repaired them. Final `finalize
  architecture ... --repo-root /home/arle/voicebot --quality showcase --json`
  returned **PASS** for validate/deliver/strictcheck/browser-check, no diagnostics.
- Specification SHA256bf10ebfe211bbecda9690b0ba9e0ce34ef5295cffeec2ab802edd3323c3d1477;
  HTML SHA2564820dc100abaac1cc54ba9ffa922a41bf85409d3b4fe08f25b6cb60b29eaf62c.
  [diagram and receipts](../../../.archify/architecture-website-booking-20261001-213712/README.md).
- Separate `visual-check --summary --require-provenance` **PASS** automated
  containment/readability/chrome/theme/captures. Four light/dark desktop captures;
  owner inspected1440light and2048dark, verified route direction, separate paths,
  no crossings/clipping. Receipts' automated visualReview state is distinguished
  from this actual screenshot review. Declared vertical scrolling is accepted.
- `.venv/bin/pytest -q`: **135 passed,4 skipped,1 existing Starlette/httpx warning**.
  Installed tests intentionally not run: they mutate provider data; read-only
  research probes already verify current reachability/auth/privacy.
- Agent Reach1.5.0 and Archify3.0.1 update checks report current; no updates made.

## Review and delivery disposition

Single-session review, no delegated agent: separately re-traced current claims
to pinned source/runtime, then reviewed the proposal against privacy/writer/DST/
pagination counterexamples. Corrected a conflicting next-page DTO proposal,
wrong UI escape-helper wording, and clarified target Redis versus current SQLite
in ADR0003. Proposed capabilities remain explicitly not implemented. No P0/P1
in the research deliverables; live read-privacy R001 and operator-projection
R019 remain open application work, not falsely closed by documentation.
Final intended-file/link/secret/whitespace and remote delivery checks recorded
in the goal evidence and final terminal report after commit/push.

Generator formatting exception: full staged `git diff --check` reports15
indent-only blank lines in the validated generated HTML. Count-only inspection
verified all15 are empty whitespace, not code/text. Preserve artifact bytes and
provenance; strict authored-file diff checks exclude only that exact HTML path.
No application code, repo formatting configuration or generator was changed
to hide the diagnostic. This is a disclosed artifact-formatting exception,
not a claim that the full unqualified whitespace check passed.
