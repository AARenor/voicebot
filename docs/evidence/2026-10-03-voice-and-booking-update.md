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
tests passed. After preserving the later natural telephone changes at
`67d0d2c`, the complete pinned media suite passed 1188 tests (5 skipped,
36 subtests) on `0df3d72`.

Protected production checks on `0df3d72` now return
`Mis kellaajaks soovid testbroneeringut?` for both the user's exact
`Tere, tahaks homme bruneerida spaad?` and its corrected spelling, with zero
model calls, no warnings and audio returned in 416 and 261 ms respectively.
The current one-use recap delivery protocol also passed live spa and room
preparation, explicit reading acknowledgement, confirmation, independent
booking read and cancellation. All test-owned bookings were cancelled and
sessions deleted. This was HTTP and decoded generated audio, not physical
microphone or playback verification.

The same production check exposed an additional hours question failure:
`Mis kell spaateenindaja töötab ja millal on tema lõunapaus? Palun kontrolli
tööplaani.` It now selects an actual catalogue read and its canonical database
hours/breaks reply without model-generated prose. A recognized hours request
does not become a booking inquiry merely because it includes `tahaks teada`;
explicit booking spellings remain excluded. Backend failures, unknown writes
and owned recap priorities are preserved. The focused HTTP, hours, native
terminal and speech suite passed 93 tests. HTTP regressions verify both typed
and mocked recognized input through the actual Azure SSML client boundary,
including `9 kuni kell 17` and `12 kuni kell 13`. Ruff and the whitespace diff
check passed.

The patch was then reconciled with concurrent Russian language and browser
audio changes at `42c421a`, preserving their full language handling and audio
format. The integrated focused checks passed 100 tests. The complete pinned
media suite passed 1248 tests (5 skipped, 36 subtests); a stale call-history
assertion was updated for the intended default `auto` recognition and now also
covers explicit `et`. An initial check could not find Node until its process
PATH was refreshed; the full rerun passed. Ruff and the diff check passed.

Post-deployment protected production checks on the hours patch `8d2a733`
returned the actual catalogue working hours and lunch break with one tool read,
zero model calls, no warnings or booking changes, and reply audio in 812 ms.
Generated Estonian speech fixtures for both the exact reported phrase and its
corrected spelling were submitted with the browser's default automatic language
mode. Both were recognized and returned the canonical time question plus audio,
with no warnings, model calls or booking changes; total durations were 1034 and
737 ms. This verifies the live speech API with generated audio and does not
establish the user's physical microphone hardware. The generated hours audio
was also recognized without a speech-provider warning; its transcript confirmed
17 but did not retain the word `kuni`, so it is not used as proof of the exact
spoken wording. Exact clock expansion is covered at the Azure SSML boundary.

A live headless Chrome check then exercised the actual dashboard microphone
button with a generated recording of the exact typo phrase as its fake audio
device. The application's `getUserMedia` capture used mono 48 kHz, its recorder
uploaded a 136576-byte mono PCM16 WAV at 16 kHz, and live recognition returned
the exact `Tere, tahaks homme bruneerida spaad?`. The answer was the canonical
time question with no warnings, errors, model calls or booking changes; its
API turn took 1140 ms. Both the greeting and the 3.096-second reply reached
the audio player's `ended` event. Capture stopped, the test session was
deleted, the operator credential was cleared, and the isolated browser was
closed. No speech/provider responses were mocked in this browser check. Its
input device was synthetic, so the user's physical microphone remains outside
this verification.

## Final requirements audit and native handoff correction

The audit found a conditional web/native state mismatch in deployment:
`manage.py` copied `STAY_STATE_DB`, while Compose hardcoded the default room
database and call log. Compose now uses the source application's effective
room/history paths, and the manager overwrites incidental caller environment
values with those source paths or the existing defaults. Paths must remain in
the actual shared `/data` mount; temporary/in-memory and outside-mount paths
fail before Compose runs. The source's `STAY_DEMO_WRITES` value is also preserved:
absence uses its existing enabled default, while explicit empty or `0` stays
disabled. This repairs supported custom deployment configurations; it is not
claimed as the cause of the earlier reported PSTN failure.

Provider-free tests now exercise the real native SDK hours tool executor,
canonical results/error replies and normalized speech with zero model calls.
Focused Russian tests cover approved database facts, current delivered consent,
language switching, numeric follow-ups, selected voice, actual cached fallback
bytes/history and real SDK spa/room confirmation and cancellation. Dedicated
modules passed 19 native terminal, 26 Russian and 29 deployment tests; these
overlapping checks are not added together as unique coverage.
The complete pinned media suite then passed 1298 tests, with 5 skipped and
36 subtests passed, in 87.25 seconds. Skips remain the opt-in installed backend
checks and unavailable Docker Compose parser. Ruff and the whitespace diff
check passed. No server deployment or carrier call was performed from Windows.

| Requested requirement | Current evidence | Release state |
| --- | --- | --- |
| Current model and transcription stack | Live status matches GPT-OSS 120B/full Whisper v3; both remain in Groq's production catalogue | Configured and accepted in live browser turns |
| Database working hours and prompt context | Actual catalogue hours/breaks, Tallinn current date and canonical guarded replies | Verified in HTTP and native SDK checks |
| Integrated spa and room booking | Shared owned lifecycle; live preparation, later reading/consent, independent read and cancellation for both kinds | Verified for fictional demo inventory |
| Public hotel/spa pitch with phone number | Live Meretuule page, three room cards, spa service, configured contact and source-matching assets | Verified public rendering |
| Working Kõneproov | Live Chrome capture/upload/recognition and complete audio playback of the exact reported phrase | Verified with synthetic audio input |
| Improved incoming telephone pipeline | Native SDK, PCM, interruption, consent, fallback and deployment checks | Matching worker deployment and real incoming call acceptance remain required |

The authenticated telephone metadata read contains six records, none active or
with a booking; the newest started at `2026-10-03T09:41:56Z`, had zero recognized
turns and ended seven seconds later. Five records need attention. These dated
records and their `synthetic` data label neither establish the current worker
revision nor prove a successful incoming dialogue. No transcripts, guests,
credentials or call identifiers were included in the diagnostic summary.

Model availability was rechecked against the primary
[Groq model catalogue](https://console.groq.com/docs/models),
[deprecation list](https://console.groq.com/docs/deprecations) and
[speech guidance](https://console.groq.com/docs/speech-to-text).
No speculative provider/model replacement was made during this audit.

## Remaining release gaps

GitHub master pushes deploy only the Coolify web/API application. The native
telephone worker and Twilio bridge require a separate server deployment.
The other server operator will inspect those
services, preserve their exact shared volume, rebuild/restart them and test
the actual incoming call. A subsequent public audit at
`2026-10-03T10:43Z` confirms the hotel page and public property endpoint now
display configured contact `+17574278729`; its carrier assignment and incoming
dialogue remain unproven by that public read. The hotel serves three room types,
spa service and database working hours; its JavaScript/CSS match current source,
with no browser errors or horizontal overflow at 1440, 390 and 320 pixels.
Physical browser
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
