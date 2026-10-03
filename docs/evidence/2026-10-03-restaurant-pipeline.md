# Restaurant pipeline verification — 2026-10-03

## Delivered scope

- Restaurant mode is the web and telephone default. Explicit `hotel_spa` mode
  retains earlier fixtures and rollback behavior; its tools and pages are not
  advertised by restaurant mode.
- ET/EN/RU restaurant greetings, one missing detail at a time, menu/allergen
  knowledge, opening/kitchen hours, policies, recaps, confirmation and owned
  cancellation use the same trusted call tools in both transports.
- Persistent, restaurant-scoped SQLite table inventory supports party capacity,
  full dining intervals, temporary holds, closures, overlap prevention and
  durable idempotent confirmation/cancellation receipts.
- The browser has restaurant voice and direct reservation controls, read
  acknowledgement, responsive desktop/mobile layouts, memory-only credentials,
  private no-store responses, voice selection and bounded incremental playback.
- Existing published streaming, speech delivery, contextual dialogue, provider
  and telephone release-sync work was merged and retained.

The specialization is approved venue knowledge and conversation policy, not a
model-weight fine-tune. The bundled venue and reservations are explicitly
fictional; no actual restaurant details were supplied.

## Bugs corrected

1. An empty restaurant inquiry was treated as inactive, losing a multi-turn
   booking request before the caller provided its first detail.
2. A delayed hold read could restore recap state after a newer caller turn.
3. Restaurant provider-fallback handling imported constants from the wrong
   module, failing on quiet or unavailable speech paths.
4. Component guest counts could omit children. Counted adults and children now
   contribute to capacity; ambiguous counts ask for the total.
5. Confirmation could use a hold after its table capacity, hours, duration or
   closure rules changed. Current rules are checked again before writes.
6. Form edits and language changes could diverge from an owned held recap.
   Details and language are locked until its reservation session is ended.
7. An older failed calendar request could erase newer results. Every view read
   is tied to its current generation and sequence.
8. Restaurant worker deployment still required obsolete EasyAppointments
   credentials. Business selection now controls those prerequisites and shares
   the restaurant database/configuration from the trusted web container.
9. Restaurant facts and questions could be lost by repeat/social reply handling.
   Repeats retain approved selector identities, and social wording is reviewed.
10. A new upstream UI test used Windows' default text encoding for UTF-8 assets.
    Explicit UTF-8 reads preserve the actual assertions on this platform.

## Executed checks

Windows, Python 3.13.15, the repository's core/media environments and installed
Chrome 154.0.8037.97 were used. No paid provider or remote booking system was
contacted by these tests.

| Check | Result |
| --- | --- |
| Full core suite | 2,743 passed; 65 skipped; 36 subtests passed |
| Full media suite | 3,005 passed; 10 skipped; 36 subtests passed |
| Restaurant-focused core checks | 150 passed; 16 skipped |
| Nine browser scenarios | All passed; no page script errors or external requests |
| Flake8 | Passed on changed runtime and restaurant tests; E501/W503/E203 ignored for established formatting |
| BasedPyright, six new runtime modules | Zero errors at error level; default warning diagnostics remain for untyped boundaries |
| JavaScript syntax, Python compilation | Passed |
| Core/media dependency compatibility | Passed |
| Git whitespace check | Passed |

Skipped cases require optional media dependencies, private backend opt-in or
platform capabilities. The media suite exercised the installed LiveKit SDK and
restaurant startup wiring with local session/provider doubles in all three
languages. Both suites retain an upstream FastAPI/httpx test-client deprecation
warning; dependency versions were preserved.

The restaurant browser scenario confirmed and cancelled direct reservations in
all three languages; completed a natural multi-turn English voice reservation
through a streamed canonical recap, explicit reading, confirmation and
cancellation; rejected autoplay as consent; captured real browser microphone
input from a synthetic oscillator as 16 kHz mono WAV; and rejected late private
results after disconnect. Desktop 1440 px and mobile 390 px layouts were
inspected. The retained streaming scenario observed early local audio and an
underrun, correctly rejected its recap receipt and allowed explicit reading.
These fixture timings do not measure a live provider's latency or voice quality.

Local logs and screenshots are under ignored `output/playwright/`:
`restaurant-core-tests-final.log`, `restaurant-media-tests-final.log`,
`restaurant-browser-all-final.log`, `restaurant-desktop.png` and
`restaurant-mobile.png`.

## Release and remaining verification

The GitHub release must use published master and the persistent shared `/data`
volume. The website's public restaurant status, language selection and assets
can be checked after auto deployment. Existing authenticated runtime credentials
are required to exercise a live browser turn. The separate telephone worker must
also roll forward, either through its installed release-sync service or an
operator-managed rebuild.

No live-provider restaurant speech, real incoming PSTN call, human transfer,
production restaurant booking connector, verified real menu or food-allergy
safety was established by these local checks. Docker image build and native
server deployment checks could not run on this workstation without Docker or
server access. See [operations and rollback](../operations/restaurants.md).
