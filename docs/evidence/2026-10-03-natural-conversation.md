# Natural conversation verification — 2026-10-03

English and Estonian now share reviewed conversational replies, shorter
missing-detail questions, focused catalogue reads and configurable Azure speech
delivery. Jenny uses its documented friendly style; Anu keeps its native style
with adjusted pacing and pronunciation aliases. Recaps use a slower rate, while
literal booking text and explicit consent remain authoritative.

The feature incorporates upstream `0088edf`, including scoped native recap
playback, HTTP playback receipts, empty-response recovery and website speech
reliability. The native social shortcut is combined with empty-response recovery
in one `llm_node`. Repeat and language-switch proposals receive a new pending
identity, rejecting delayed completion from the earlier reading.

## Local checks

Windows Python 3.13.15; media dependencies retain the project's LiveKit Agents
and plugins 1.8.4 pins. Provider interactions use synthetic fixtures.

| Check | Result |
| --- | --- |
| `.venv-media/Scripts/python.exe -m pytest -q tests` | 1083 passed, 5 skipped, 36 subtests passed |
| `.venv/Scripts/python.exe -m pytest -q tests` | 874 passed, 49 skipped, 36 subtests passed |
| `flake8.cmd --select=E4,E7,E9,F` on changed Python files | Passed; existing E402 bootstrap exception retained in test_demo_worker.py |
| `basedpyright.cmd` on conversation.py, languages.py, speech_delivery.py and telephone_tts.py | Zero errors, warnings or notes |
| Broader BasedPyright comparison across six affected application/deployment modules | 36 errors on both this feature and upstream `0088edf`; no new error fingerprints. Dynamic-data warnings: 1494 versus 1477. This broader check does not pass. |
| `uv pip check` in core and media environments | Compatible installed packages |
| Python compilation and `git diff --check` | Passed |

New regression coverage includes whole-utterance social matching, mixed booking
requests, approved questions, bounded variation state, repeat delivery/expiry,
stale native SpeechHandle callbacks, backend-error truth, authenticated HTTP
social replies, focused verified reads, configuration bounds, XML escaping,
pronunciation aliases, voice-specific styling and neutral rollback.

The native Azure test exercises the installed plugin's actual outbound SSML
request construction and PCM stream using a fake HTTP session. It checks complete
per-request markup, recap rate, language switching and normal-rate restoration.
The HTTP fixture checks that a 401 retry keeps identical speech markup. Neither
test contacts Azure. Full suites include existing English/Estonian booking,
consent, cancellation, interruption and failure regressions.

An initial bare pytest discovery also collected an audit checkout nested under
ignored output and failed with duplicate module names. The audit checkout was
removed and full runs target the repository's `tests` directory. The existing
Starlette/httpx TestClient deprecation warning remains.

## Live limits

No live Azure/Groq request, Docker build, worker deployment, provider audio
listening or incoming telephone call was performed. Docker and provider/server
credentials are unavailable here, and the user confirmed server access cannot
be supplied. GitHub delivery is the requested handoff; worker activation belongs
to the server operator.

No measured acoustic-quality or latency advantage is claimed. See the
[configuration and activation runbook](../operations/natural-conversation.md)
for deployment and listening checks.
