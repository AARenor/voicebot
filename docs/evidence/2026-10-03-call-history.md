# Call history and microphone follow-up

## Changes

- Kept the current native HTML/CSS/JavaScript stack, Figtree typography, spa and
  room booking composer, public hotel website and existing server ownership
  rules. The operator dashboard now uses a forest-green palette, a session
  list/detail layout, recognition guidance and links to actual booking dates.
- Added authenticated, `no-store` call-history list/detail routes and additive
  SQLite migrations. Browser conversations and native telephone sessions
  record lifecycle, recognition counters, bounded event timelines, provider
  failure codes and confirmed/cancelled owned spa or room receipts. Historical
  technical log rows remain visible separately; they are not invented calls.
- History stores no recordings, raw transcripts, guest contacts, provider
  payloads or room names. The existing technical 30-day retention applies.
  Timelines cap at 200 events per call; counters continue. Active sessions
  without activity for 15 minutes are closed as interrupted, using their last
  activity as an estimated end time. These durations are not carrier billing.
- Browser recording shows input level and elapsed time, rejects absent/digital
  silence locally, stops microphone tracks, caps capture at 15 seconds and
  resamples through the browser audio filter to 16 kHz mono, 16-bit PCM WAV.
- Recognition forwards the requested supported language and returns separate
  `no_speech` and `stt_unavailable` diagnostics. A provider outage therefore
  produces service-unavailability guidance. General response failure also
  avoids the previous unrelated price response.
- Integrated the newer upstream speech/model configuration and spa/room work
  at `13c624a`, including its shared model settings, timings and cached-apology
  reconciliation. The completed SDK history matches fallback PCM; this does
  not establish that every partial remote transcription already sent was
  reconciled. Regression checks prevent an old failed generation replacing a
  later response.
- Verified the booking journal closes SQLite connections in normal and error
  paths and excludes contenders across threads and native Windows processes.
  Asset line endings are pinned to LF so content-version hashes are stable
  between Windows checkouts and Linux deployments.

## Local verification

- Full native media environment: **752 passed, 5 skipped**, plus 9 subtests.
  No expected failures. Python 3.13 on Windows; the production media image uses
  pinned Python 3.12/Linux and was not rebuilt from this computer.
- Playwright CLI dashboard checks: authentication, call filtering/details,
  receipt navigation, loading/empty/stale states, late responses after logout,
  denied microphone, synthetic voiced capture, silence rejection, actual
  browser resampling, keyboard access and reduced motion. No JavaScript
  exceptions or horizontal overflow at 320, 390, 700, 768, 1024 and 1440 pixels.
- Existing spa/room booking browser checks passed through the actual local
  routes with fictional providers, including consent, cross-session rejection,
  uncertain writes and synthetic reply audio. Hotel website browser checks
  also passed across the same widths and its configured/missing phone cases.
- Python compilation and JavaScript syntax checks passed. New history modules
  pass Flake8. The broader source has existing long prompt/style diagnostics.
  BasedPyright comparison against the same upstream revision introduced zero
  type errors; the broader check remains non-green because of existing errors.
- [Desktop preview](call-history/desktop.png) and
  [mobile preview](call-history/mobile.png) use disclosed fictional fixtures.
  Their counts, bookings and events are not deployed-call evidence.

## Deployment and remaining verification

The web application deploys from `master` through its existing Coolify push
hook. The separate native worker must also be rebuilt/restarted using the
existing deployment workflow, with the exact web/worker `/data` volume
preserved. Otherwise the UI cannot show new telephone-session records. There
is no retrospective transcript/call reconstruction from earlier turn logs.

No deployed worker credentials or SSH connection were available in this local
session. Live provider speech, incoming PSTN audio, interruption and native
deployment remain unverified. The user's repeated unrecognized-speech symptom
cannot be declared fixed on the actual phone from local tests alone.

After deploying, use the protected operator UI to compare browser and telephone
history: input activity without final recognition, explicit provider errors,
and successful recognized turns have different diagnostics. Verify two-way
Estonian speech, interruption and owned booking/cancellation using the existing
[native runbook](../../deploy/telephony/README.md) and
[Twilio runbook](../../TWILIO.md). Preserve the current unverified telephone
readiness until a real incoming call passes.
