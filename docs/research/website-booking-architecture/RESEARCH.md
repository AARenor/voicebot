# Website and booking architecture — research ledger

MODE: **RESEARCH**. Verified/observed on **2026-10-01**. Baseline repository:
`https://github.com/Parnuhakk/voicebot`, revision
`5e1c10c868d8fdceeae2184b8503811ce9e6288e`.
No application changes or provider writes are part of this goal.

## Round 1 — discovery and current reality

Query matrix: exact website/Easy!Appointments1.6/API; aliases operator dashboard
and read model; broader FastAPI control plane; opposing iframe/direct admin vs
server-side provider proxy; polling vs webhook; current2026/stable1.6; official
GitHub/OpenAPI, FastAPI, OWASP and MDN primary sources.

Native run `ef6806f9-6b90-45af-b1e6-a32b608b5d40`: ten angles,32 rankedURLs,
10 extracted documents,7 extraction failures, Google circuit-broken. Many
appointments results were off-topic; they are **not** evidence for design
decisions. Exact official sources and local code are the next-round gap closure.
Robots-denied/419/unsafe-DNS sources were not bypassed.

| Claim | Evidence / dated passage | Confidence / corroboration |
| --- | --- | --- |
| Website already hosts the FastAPI app and booking-enabled HTTP turn; UI booking visibility is a different capability | `https://robot.arleserver.cfd/api/status` fetched2026-10-01: `slot_booking_ready:true`, `operator_hold_commands_ready:false`, `serving_demo_data:true`; [server source](https://github.com/Parnuhakk/voicebot/blob/5e1c10c868d8fdceeae2184b8503811ce9e6288e/app/server.py#L155-L178) distinguishes these booleans | High; live status + source agree; configuration-derived booleans alone are not reachability proof |
| Current hold queue and metrics are synthetic, not actual provider bookings | [dashboard API](https://github.com/Parnuhakk/voicebot/blob/5e1c10c868d8fdceeae2184b8503811ce9e6288e/app/dashboard/api.py#L49-L59), lines109–115 read `demo.STORE`; [UI](https://github.com/Parnuhakk/voicebot/blob/5e1c10c868d8fdceeae2184b8503811ce9e6288e/app/dashboard/static/index.html#L440-L488) fetches `/api/holds`, `/api/calls`, metrics/status, never bookings; accessed2026-10-01 | High; independently trace API data owner and browser fetch call sites |
| Existing GET routes do not enforce application operator auth | [API](https://github.com/Parnuhakk/voicebot/blob/5e1c10c868d8fdceeae2184b8503811ce9e6288e/app/dashboard/api.py#L38-L59) shows auth helper not invoked for GET; UI lines313–318 intentionally omit auth for GET | High source claim; public-path behavior needs browser/direct-runtime corroboration without exposing call summaries |
| PHP/MySQL booking service is private and separately persisted | [Compose](https://github.com/Parnuhakk/voicebot/blob/5e1c10c868d8fdceeae2184b8503811ce9e6288e/deploy/easyappointments/compose.yml#L1-L55): loopback8088, Coolify alias, internal DB network and named volumes | High source claim; live service/catalogue probe planned |

Transport discrepancy: a Python urllib request to the public site returned
Cloudflare403/error1010 (browser signature rejection); native webfetch returned
200 for health/status. Do **not** misclassify this as FastAPI auth, a booking
outage, or protection of `/api/calls`. No WAF bypass attempted; next round uses
authorized same-host runtime evidence and normal browser rendering.

R1 gaps: exact stable appointment list/filter/field contract; whether read-only
catalogue should remain available with writes disabled; private bookings view
auth and leakage; browser UI's actual entry points; calendar timezone and
cache/freshness semantics; no telephone or real-property readiness assertion.

## Round 2 — primary contracts and minimal alternatives

Queries/gap closure: stable `1.6.0` REST docs, actual appointment controller,
API pagination/field implementation, FastAPI protected GET/output models,
OWASP authorization and MDN private response caching. All below accessed
**2026-10-01**, not inferred from search snippets.

| Finding | Primary URL + passage | Corroboration / confidence |
| --- | --- | --- |
| Supported appointment reads can power the panel without browser admin scraping | [stable REST docs](https://raw.githubusercontent.com/alextselegidis/easyappointments/1.6.0/docs/rest-api.md): “Every API request must include authentication”, admin Basic or Settings Bearer; [stable controller](https://raw.githubusercontent.com/alextselegidis/easyappointments/1.6.0/application/controllers/api/v1/Appointments_api_v1.php): `date`, `from`, `till`, `serviceId`, `providerId`, fields, list response | High: docs + implementation + installed GET200; invalid Bearer401 |
| Correct pagination is `page` and `length`, not `start` offset | [Api.php](https://raw.githubusercontent.com/alextselegidis/easyappointments/1.6.0/application/libraries/Api.php), lines176–194: `request('length')`, `request('page',1)`, offset `(page-1)*length`; sort at200 uses signed API fields | High: stable source + docs; empty live result cannot prove non-empty paging, so fixture contract test still required |
| Default records include secrets/PII-adjacent fields unnecessary for a schedule panel | [model](https://raw.githubusercontent.com/alextselegidis/easyappointments/1.6.0/application/models/Appointments_model.php), lines594–618 exposes `hash`, `notes`, `customerId`, meeting/calendar IDs and provider timestamps without zone offsets | High stable-source contract; current date-query list is empty, populated field projection not live-tested in this read-only goal |
| Auth must guard reads, not just booking writes | [OWASP Authorization](https://cheatsheetseries.owasp.org/cheatsheets/Authorization_Cheat_Sheet.html): deny by default and validate permissions on every request; [FastAPI scopes/dependencies](https://fastapi.tiangolo.com/advanced/security/oauth2-scopes/) shows protected GET dependencies | High normative guidance from two independent primary sources; an operator Bearer guard is smallest demo mechanism, not full user/role auth |
| Response DTO should explicitly allow fields and prohibit browser caching | [FastAPI response models](https://fastapi.tiangolo.com/tutorial/response-model/) filters output, warns include/exclude keeps full OpenAPI schema; [MDN Cache-Control](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Cache-Control): `no-store` prevents storage, `no-cache` still permits storage (page modified2026-09-17) | High; proposed DTO + no-store is design, not existing behavior |

Context7 resolved FastAPI `/websites/fastapi_tiangolo` and retrieved protected
GET/response-model documentation. No requirement for OAuth/JWT libraries is
introduced: reuse existing operator guard for the synthetic phase.

Options: **server-side read-through JSON panel chosen**, same-origin/operator
auth, no new DB or dependencies. Reject iframe/public Easy admin (would expose
private backend/session and encourage another writer). Reject copying bookings
into demo.STORE (false authority). Defer webhooks/event bus/SSE/new frontend
framework until a measured freshness/load requirement exists. Existing30s UI
polling is sufficient as a starting design, not a capacity benchmark.

R2 read-only live checks: deployed revision `9a8d1d2d5c630525066f0e118fbbed1b5e1c0717`,
one real service/provider reachable; five slot tools present. Filtered upstream
GET returned200/zero rows; wrong credential401. Application `/api/bookings`404
and absent in OpenAPI. Application `/api/calls`200 without operator auth,
one summary-bearing row, no Cache-Control; values deliberately omitted.
`/api/holds`200/two synthetic rows. No provider writes or UI mutations performed.

R2 gaps: render-level privacy/freshness semantics, timezone ambiguity around
Tallinn DST, unknown-write status versus a provider appointment, safe UI error
states, source-filtering limits, future command ownership policy.

## Round 3 — disconfirming, privacy and recovery

Gap queries: unguarded read versus Cloudflare browser filtering; provider truth
versus local hold/journal; API offset-free datetimes/DST; rendering untrusted
labels; credentials-only readiness. Sources accessed **2026-10-01**.

| Hypothesis challenged | Evidence | Resolution / confidence |
| --- | --- | --- |
| “Wired backend means the website displays bookings” | Live `/api/bookings`404, no OpenAPI route; browser fetches only status/holds/calls/metrics; no booking panel/voice form in source | Rejected, high; current pipeline works but dashboard projection does not exist |
| “The edge403 or masked peer makes call reads private” | Normal Playwright unauthenticated page gets calls200, one summary-bearing row; direct app same result. `app/callslog.py:122–160` masks peer but stores/returns summary, server lines288–297 combines heard/reply | Rejected, high; no guest contents copied. Protect reads and minimize logged text before real traffic |
| “The demo banner means no component can book” | `app/dashboard/static/index.html:466–469` uses serving_demo_data; live `slot_booking_ready:true`, separate HTTP dispatcher can write; hold buttons disabled correctly | Rejected, high; scope banner to synthetic queue/metrics and separately show live synthetic backend capability |
| “A hold or journal row is the appointment database” | Adapter lines638–653 local snapshot; lines694–750 reconcile unique provider record; pending_customer cannot safely auto-resolve | Rejected, high local-source + installed proof from earlier verification document. Reads come from provider, pending is diagnostic not confirmed inventory |
| “All upstream start/end values can be converted to UTC without policy” | Stable model594–618 exposes naive strings. [Python zoneinfo](https://docs.python.org/3/library/zoneinfo.html) documents `fold` during ambiguous transitions; local zoneinfo2026 Tallinn roundtrip probe | Rejected, high:2026-03-29 03:30 is nonexistent,2026-10-25 03:30 has +03/+02 alternatives. Preserve local timestamp+zone and mark ambiguity, never guess offset |
| “All labels are harmless HTML” | [MDN textContent](https://developer.mozilla.org/en-US/docs/Web/API/Node/textContent) recommends textContent over raw innerHTML to avoid XSS; existing UI uses textContent at lines351,395–418,434 | Render provider labels as text; require injected-markup regression. High normative guidance, future endpoint not implemented |

Corroboration: official OWASP HTML + [maintained Markdown](https://raw.githubusercontent.com/OWASP/CheatSheetSeries/master/cheatsheets/Authorization_Cheat_Sheet.md)
both say deny-default/every-request validation (same authority, **not** two
independent sources); FastAPI protected-GET example independently supports the
mechanism. Upstream docs/model/controller are one product authority; installed
runtime is an independent observation, not a separate specification.

Remaining explicit gaps: no non-empty live paging/field projection proof in
this read-only goal; provider timezone conversion at DST needs implementation
fixtures; no caller ownership, multi-tenant authorization, production guest
consent/retention policy, sustained provider load, real carrier or STT proof.
Existing Bearer token storage is browser-readable sessionStorage, not robust
operator identity/session management. Do not expose real data under that claim.

R3 conclusion: **protect reads first; add a read-only provider-backed schedule
second; route any future mutations through the existing sole writer**. No
iframe, direct DB query, second POST path, provider credential in browser,
new event bus or additional frontend framework is justified for this phase.

Design-review supplement (2026-10-01): [Web Interface Guidelines](https://raw.githubusercontent.com/vercel-labs/web-interface-guidelines/main/command.md)
requires semantic labeled controls, visible focus, polite async announcements,
URL state, long-content handling and bounded lists. Applied to the **proposed
contract**, not a claim of audited compliance for an unimplemented UI. Single
normative guideline source; future headless acceptance tests remain necessary.
