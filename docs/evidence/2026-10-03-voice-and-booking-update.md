# Voice, rooms and website update — 2026-10-03

## Implemented

- Shared configurable Groq `openai/gpt-oss-120b` chat and `whisper-large-v3`
  Estonian transcription for HTTP turns and the separate native worker.
  Completion budgets, short reasoning and truncated-response rejection are
  explicit. Azure Anu remains the Estonian voice.
- HTTP turn stage timings and closed STT/LLM/TTS warnings. A failed audio reply
  preserves the text response. Native stage failures and bounded latency
  summaries avoid logging conversation contents or provider credentials.
- Actual LiveKit SDK fallback history now matches the cached audible apology.
  Late speech events cannot label a different speech handle as that apology.
- Shared call-owned spa and room tools, provider working-plan opening hours,
  exact owned room quotes and delivered-recap/subsequent-consent rules.
  Late preparation reads cannot restore an old proposal after a newer turn.
- Finite fictional room inventory with durable SQLite quotes, exclusive
  expiring holds, confirmation/cancellation receipts and idempotency.
  The HTTP app and native worker must share the existing persistent `/data`
  volume and room database path. This does not connect a real hotel PMS.
- Operator-authenticated direct spa/room controls, calendar reconciliation and
  cancellation. Public `/hotel` shows property information, current catalogue,
  room types, provider spa hours and the configured contact number. Its public
  endpoints omit guest and appointment records. Missing phone configuration
  does not produce an invented number.
- Windows journal locking/timezone support, deterministic SQLite connection
  cleanup and Windows-compatible credential-free subprocess checks.

## Local verification

Environment: Windows, Python 3.12; provider-free fixtures unless stated below.
These suites are focused application/SDK tests, not CPU-intensive scans.

| Check | Result |
| --- | --- |
| HTTP environment: `.venv/Scripts/python.exe -m pytest tests -q` | 573 passed, 38 skipped, 5 subtests passed |
| Pinned media SDK plus HTTP dependencies: `.venv-media/Scripts/python.exe -m pytest tests -q` | 716 passed, 5 skipped, 5 subtests passed |
| `uv pip check` in both environments | Compatible installed packages |
| Ruff E4/E7/E9/F checks on changed Python files | Passed |
| Node syntax checks for dashboard/hotel controllers and new browser checks | Passed |
| `git diff --check` | Passed |

The native suite exercises installed LiveKit SDK behavior. It does not contact
an actual Groq/Azure account, prove two-way carrier audio or redeploy a server.
Docker Compose is unavailable locally. Remaining warnings concern Python 3.12
`audioop` deprecation and Starlette's deprecated httpx TestClient integration.

The browser fixture runs the actual HTTP booking routes and durable room
adapter with fictional Easy!Appointments and speech fixtures. Spa and room
search, displayed recap, confirmation, read and cancellation have been
exercised in Chromium. Declining creates no booking, cross-session cancellation
is rejected, and an uncertain receipt causes one write with repetition locked.
All three browser suites passed with no JavaScript errors. Public catalogue errors, absent/configured phone,
working-plan breaks, reduced motion and 320–1440px layouts are covered.
Synthetic microphone capture and a valid short MP3 exercise browser cleanup;
they do not prove the user's physical microphone or live speech providers.
Local preview artifacts are in the ignored `output/playwright/` directory;
their phone number `+12025550109` is a fictional fixture.

## Live deployment and checks

At 06:37 UTC on 2026-10-03, before any deployment of this change set, both
`https://robot.arleserver.cfd/health` and `https://coolify.arleserver.cfd/`
returned HTTP 530 with a Cloudflare Tunnel error page. Earlier site reads had
succeeded. This prevented public deployment verification at that time; the outage's cause
has not been established from application code.

The tunnel subsequently recovered. At approximately 06:50 UTC, GitHub master
and the published source matched commit `976d4b4d89072c0fe25b4ef158ec8853c324c5ac`.
Public health returned 200; `/hotel`, the public property/catalogue APIs and
`/api/status` returned 200. Both dashboard/hotel HTML files and all four
content-versioned CSS/JS assets matched the source bytes exactly. The public
status reports the new HTTP model configuration and room capability. This does
not establish the separately deployed worker's version or provider acceptance.

Read-only live Chromium checks found three room cards, one Easy service,
weekday 09:00–12:00 / 13:00–17:00 spa hours, closed weekends, working FAQs and
room/spa booking links. The public hotel and signed-out dashboard fit
320–1440px without overflow, JavaScript errors or failed public requests.
Private booking/stay reads and session creation without authorization returned
403 with `no-store` in the initial unauthenticated checks. The live public phone
DTO remains unconfigured (`number:null`), and the page reports that honestly.

Subsequent operator-authenticated production checks contacted the live Groq,
Azure and booking backends. A text greeting, a database working-plan question
and a synthetic audio round trip returned nonempty MP3 replies without warnings
or fallback. These three sample turns took 2197.6, 1939.2 and 1265.0 ms total;
the audio-input turn included 509.3 ms transcription. The hours answer used a
database tool and included the break. These are individual observations, not
a latency guarantee or proof of the user's physical microphone.

Direct production spa and room controls searched availability, prepared the
canonical recap, acknowledged it, confirmed exactly one fictional booking of
each kind, verified each through an independent calendar read, and cancelled
both. A final read found no active booking owned by either test session.

A stronger live conversational spa check subsequently fetched the catalogue
successfully, then hit an LLM follow-up failure after one tool execution while
preparing the requested appointment. The turn returned a closed LLM warning
and fallback; no booking was created. At that stage conversational booking was
not established. New provider diagnostics distinguish a closed failure cause
and HTTP status without returning provider bodies or exception text. The
diagnostic patch passed 76 HTTP tests (6 native skips, 32 subtests), 43 native
provider tests (32 subtests), lint/syntax checks and the Chromium dashboard
suite at 320–1440px, including rate-limit/rejected-request guidance.

Commit `529f461` was pushed to master and the live content-versioned dashboard
asset matched its source exactly. Repeating the protected conversation then
identified `rate_limited` / HTTP 429 after two tool executions; no booking was
created. The subsequent fix uses compact backend planning and trusted canonical
responses: preparation does not ask the model to rewrite its recap, and later
server-authorized confirmation/cancellation uses the existing guarded tool
executor. Focused HTTP tests verify one model request for an entire fictional
spa or room prepare/confirm/cancel flow, with zero additional model requests
for consent or cancellation. Failed recap audio and ambiguous consent still
prevent writes. Room selection remains explicit when the requested type is
missing or ambiguous.

After commit `fd46c83`, fully specified production Estonian text conversations
completed spa and room preparation, a separate consent turn, confirmation,
independent calendar read and cancellation. All six turns returned decodable
MP3 audio with no warning or fallback. Preparation took 2719.3 ms for spa and
1823.0 ms for the room; confirmation took 317.6 and 321.2 ms, and cancellation
224.2 and 166.2 ms. Each flow used one planning model call; consent and
cancellation used none. No booking existed before consent. Final reads found
no active booking owned by either session, and the sessions were deleted.
These are typed HTTP checks with synthetic guests, not physical microphone or
PSTN evidence.

A subsequent user report supplied “Tere, tahaks homme bruneerida spaad?” and
the exact unverified-success warning. Protected production text checks
reproduced the same warning for both `bruneerida` and correctly spelled
`broneerida`, with zero tools, zero booking changes and no provider warning.
Local mocked speech-input checks traced it to the final speech allowlist:
ordinary missing-field question paraphrases were rejected. It was not a
booking receipt or a provider failure in those reproduced turns. The patch
adds narrow Estonian spa intent clarification and preserves a sanitized
date/time across follow-ups, while keeping actual writes behind the existing
owned recap and later explicit consent. Clock ranges are formatted at the
Azure speech boundary as `9 kuni kell 17`; displayed database text is retained.

The patch was reconciled with the concurrent English telephone changes on
upstream `f541da6`. Native terminal selection ignores SDK configuration
metadata while preserving real conversation items, and late model chunks are
withheld after a newer final user turn. Regression checks include real SDK
tool execution, both languages, complete/interrupted recap playback, metadata
after a user/tool item, and preservation of the selected speech language.

Local checks before the subsequent website reliability integration:

| Check | Result |
| --- | --- |
| Core HTTP environment, full `tests -q` | 872 passed, 44 skipped, 36 subtests passed |
| Pinned media environment, full `tests -q` | 1055 passed, 5 skipped, 36 subtests passed |
| Ruff E4/E7/E9/F on changed Python files | Passed |
| Git whitespace diff check | Passed |

Core skips include unavailable native SDK tests; four installed booking tests
require an explicit live backend opt-in and one check requires Docker Compose.
The media warnings remain `audioop` and Starlette/httpx deprecations. These are
focused application tests and synthetic SDK checks, not live carrier proof.

The latest website reliability changes at `0088edf` were also preserved,
including one-use HTTP recap delivery assertions, originating speech handle
callbacks and silence recovery. The HTTP inquiry test now asserts that
preparation has not been delivered or approved before the explicit reading
assertion; internal requested dates remain ISO while spa recaps use natural
Estonian dates. The integrated core suite passed 910 tests (45 skipped,
36 subtests), and 141 focused native playback, terminal, silence and English
tests passed. The complete media suite is rerun separately before the final
live verification record.

## Remaining release gaps

GitHub master pushes deploy only the Coolify web/API application. The native
telephone worker and Twilio bridge require a separate server deployment.
The other server operator will inspect those
services, preserve their exact shared volume, rebuild/restart them and test
the actual incoming call. It is also needed to supply the existing inbound
number as `PUBLIC_PHONE_NUMBER` in the web application. Physical browser
microphone/playback, arbitrary live conversational follow-ups, volume/journal continuity
and native deployment remain unverified.
No successful public PSTN call is claimed here.

See [Coolify deployment](../../COOLIFY.md),
[native deployment](../../deploy/telephony/README.md) and
[Twilio activation](../../TWILIO.md). After deployment, verify the deployed
revision/assets, provider acceptance, authenticated browser speech and a real
incoming Twilio call with two-way Estonian audio, interruption and owned
booking/read/cancellation. Keep readiness unverified until those checks pass.

Model references checked for the implementation:
[Groq models](https://console.groq.com/docs/models),
[speech-to-text](https://console.groq.com/docs/speech-to-text) and
[reasoning](https://console.groq.com/docs/reasoning).
