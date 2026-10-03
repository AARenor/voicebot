# English in the website voice demo — 2026-10-03

The operator site's “Proovi kõneabilist” panel now has an accessible language
selector with Auto, Eesti and English. Selecting English translates this panel's
controls, examples, microphone instructions, warnings and consent guidance.
The operator dashboard continues to use its established layout and styling.

The selected language is sent at session creation and on every text/audio turn.
English sessions start with the English AI/demo greeting and Azure Jenny voice;
the shared Azure client is viewed by language without mutating another session.
The initial language is also recorded in the technical call history. Empty
legacy session requests keep the Estonian greeting, while Auto preserves existing
automatic turn recognition, including the upstream Russian support.

Language selection is locked while a session, request or microphone operation
is active. Ending the conversation allows selecting another language. This
keeps pending recaps, recording, playback receipts and consent in the existing
session lifecycle. Changing the selector never supplies consent or performs a
booking. English confirmation remains “Yes, I confirm.”

## Validation

Integrated onto upstream `b194007`, including the latest spa opening-hours
inquiry release, Estonian clarification, Russian telephone support, automatic
ASR history coverage and browser audio fidelity improvements.

| Check | Result |
| --- | --- |
| Media Python suite | 1268 passed, 5 skipped, 36 subtests passed |
| Core Python suite | 1043 passed, 50 skipped, 36 subtests passed |
| Playwright browser suites | English demo, voice playback, microphone races, operator dashboard, hotel and direct booking checks passed in installed Chrome |
| Responsive layouts | English demo inspected at 1440 px and 390 px; existing suites also cover 1024, 768, 700 and 320 px without horizontal overflow |
| Flake8 `--select=E4,E7,E9,F` on changed Python files | Passed |
| BasedPyright comparison on server.py and hackathon.py | 20 existing errors versus 22 on upstream; no new error fingerprints. Broader typing remains a failing check. |
| JavaScript syntax, Python compilation, package compatibility and diff checks | Passed |

New API fixtures cover English/Estonian/Russian initial language, empty legacy
requests, authentication before parsing, unsupported/malformed/oversized settings,
English recognition hints, Azure Jenny request construction, language isolation,
greeting synthesis failure and English booking prepare/read/confirm/cancel.

The new real-browser scenario exercises the actual local API and protected
operator connection, an English greeting, social text replies, English example
payloads, synthetic microphone capture/resampling, reading a recap and sending
its delivery receipt, language locking and returning to Estonian. Provider audio
in this browser fixture is a synthetic tone. Screenshots are local artifacts
under `output/playwright/english-demo-*`.

The updated upstream call-history fixture covers both an explicit Estonian hint
and the default Auto request. These checks are retained alongside the new
English recognition coverage.

The installed Playwright package's default headless-shell binary was absent.
The browser runner now accepts the optional `PLAYWRIGHT_BROWSER_CHANNEL=chrome`
setting to use installed Chrome; no frontend runtime dependency was added.
Provider-only server imports remain supported, while the Request type is visible
to static analysis. Existing Starlette TestClient deprecation warnings remain.

## Deployment and live limits

GitHub delivery updates the web application through its existing deployment.
The public deployed page and content-versioned assets can be checked without an
operator token. An authenticated live conversation and listening to live Azure
audio require the protected operator/provider access, which is unavailable here.
Local fixtures verify language routing and safeguards; they do not establish
live speech quality or a working telephone carrier path.

The separate telephone worker does not need a browser-language selector. These
changes concern the website's HTTP conversation, with no change to that worker's
carrier readiness claims.

References: [FastAPI direct requests](https://fastapi.tiangolo.com/advanced/using-request-directly/)
and [Playwright browser channels](https://playwright.dev/docs/browsers#google-chrome--microsoft-edge).
