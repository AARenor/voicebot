# English telephone implementation verification — 2026-10-03

The telephone worker now detects English/Estonian speech and selects Azure
Jenny/Anu, with localized booking questions, verified reads, recaps, consent,
cancellation, approved FAQs and provider-independent failure audio. English
clarifies ambiguous numeric dates and AM/PM hours before booking tools execute.
Language switching resets pending recap approval. The Twilio bridge has bounded
bilingual fallback audio for failures before language detection.

The existing Groq models, booking adapters, durable journals, call ownership,
explicit demo opt-ins, interruption handling and transcript privacy boundaries
are preserved. HTTP `language: "en"` follows the same policy and uses a stateless
English Azure voice view. An English private-room conversation probe and a
[deployment/runbook](../operations/english-telephone.md) are included.

## Local verification

Windows Python 3.13.15; the installed LiveKit Agents/Groq/Azure plugins match
the repository's 1.8.4 pins, with httpx 0.28.1. Docker targets its existing
Python 3.12 media image. These local checks use provider-free synthetic fixtures.

| Check | Result |
| --- | --- |
| Media environment full suite | 948 passed, 5 skipped, 36 subtests passed |
| Core environment full suite | 781 passed, 43 skipped, 36 subtests passed |
| `flake8.cmd --select=E4,E7,E9,F` on changed Python files | Passed; existing E402 bootstrap exceptions are limited to conversation_probe.py and test_demo_worker.py |
| `basedpyright.cmd --pythonpath .venv-media/Scripts/python.exe --level error` on languages.py, telephone_stt.py and voice_config.py | Zero errors |
| Broader BasedPyright comparison on seven affected application/deployment modules | 32 existing errors remain, compared with 128 on upstream master at 99fac8f; no new error fingerprints |
| `uv pip check` in both project environments | Compatible installed packages |
| Python compilation and `git diff --check` | Passed |

Coverage includes actual outbound STT/SSML request construction, automatic and
fixed language modes, provider language metadata, synthetic silence rejection,
in-flight cancellation, English spa and durable room lifecycles, explicit consent,
foreign/expired/undelivered/interim recaps, language switching, uncertain writes,
backend error truth, independent cached PCM, concurrent HTTP voice isolation and
preservation of deployment settings/shared storage. Estonian regressions remain
in the full suites. English spa/room planning, receipts, consent and cancellation
also exercise the newly added trusted terminal shortcuts, without further model
requests; standalone approved English greetings/FAQs need no model request.

The feature was rebased onto upstream master at `92dcb01`, including the latest
Meretuule domain redirect. Five existing
adversarial tests failed unchanged on that upstream commit because their fixtures
expected provider calls that the new trusted terminal shortcuts bypass. The
ownership assertions now check direct server actions; the mixed-tool error test
isolates the shared guard with shortcuts disabled, preserving its failure
coverage. The affected 28 tests passed again after their fixture imports were
cleaned up for Flake8.

The remaining warning is Starlette's existing deprecated
httpx TestClient integration. Broad repository typing is not a passing gate;
the remaining diagnostics and dynamic-data warnings are not hidden by this report.

## Live verification limits

No live Groq/Azure speech request, private worker deployment, Docker build or
incoming PSTN call was performed. No provider/server credentials are available
in this workspace and no existing SSH key/configuration was found. Server
connection information was requested separately. Live English speech quality,
recognition accuracy, latency and carrier behavior therefore remain unverified.

GitHub/web deployment updates the web application. Activating these changes on
the telephone number requires rebuilding the separate native worker and bridge
using the existing protected credentials and shared volume, then running the
English/Estonian private-room probes and a real incoming telephone check. The
code does not mark carrier readiness verified or claim an acoustic performance
advantage over Estonian based on local fixtures.
