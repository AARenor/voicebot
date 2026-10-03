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

## Live verification gap

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
403 with `no-store`; no live booking write was attempted. The live public phone
DTO remains unconfigured (`number:null`), and the page reports that honestly.

GitHub master pushes deploy only the Coolify web/API application. The native
telephone worker and Twilio bridge require a separate server deployment.
Existing server access is still needed to inspect those
services, preserve their exact shared volume, rebuild/restart them and test
the actual incoming call. It is also needed to supply the existing inbound
number as `PUBLIC_PHONE_NUMBER` in the web application. Authenticated browser
speech, volume/journal continuity and native deployment remain unverified.
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
