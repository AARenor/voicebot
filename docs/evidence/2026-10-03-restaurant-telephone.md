# Restaurant telephone answers — 2026-10-03

## Scope and integration boundary

Continue the Estonian/English/Russian telephone experience with short restaurant
answers. The separately owned restaurant pipeline supplies table booking, venue
identity, date/time/diner questions and the existing recap/consent boundaries.
Do not copy or deploy its unpublished work. This complementary payload adds
three reviewed, static answer topics through the existing FAQ loader/matcher:

- Menu, dietary and allergy questions reuse the published uncertainty answer.
  No dishes, ingredients, allergy-free preparation or safe-to-eat guarantees.
- Kitchen notifications and allergy/special-request notes are unsupported.
  The reply never claims staff were contacted or a note saved.
- Food, takeaway and delivery orders are unsupported. Table reservations are
  separate and remain explicitly fictional.

The default 50-question hotel/spa bank is unchanged. Language inference now
accepts the same explicit bank as answer matching, including an empty bank.
Shared routing selects the restaurant bank only from the server-owned business
field. Missing business retains the legacy bank. **Production activation is not
implemented or deployed yet**: it awaits the restaurant owner's published,
reviewed constructor/backend configuration. In particular, legacy booking-047
must not deny table booking in restaurant mode.

## Verification

Task-owned Python 3.12.3 environment: `/tmp/opencode/restaurant-telephone-venv`.
Installed the existing exact core and telephony lock requirements plus pytest
9.0.2; no repository dependency was added and the shared environment was not
modified. All repository test runs use an empty environment, disabled plugin
autoload and `EASY_LIVE_TESTS=0`.

- Failing-first selected-bank language tests: **5 failed, 1 passed** because the
  helper did not accept the explicit bank. Minimal three-line change followed.
- Failing-first restaurant answer tests: **42 failed** because no approved
  restaurant phone bank existed. All focused new tests then **48 passed**.
- Existing FAQ plus selected-bank language tests: **1,218 passed**.
- Full suite after implementation: **2,795 passed, 36 subtests passed, 4 skipped,
  2 upstream warnings**, 53.37 seconds. The four skips require explicit private
  installed-backend opt-in. Warnings concern audioop and Starlette/httpx.
- Existing private audio-boundary self-test: **33 passed**, zero provider calls.
- Independent OpenAI/Codex-account review: **interim PASS, no P0/P1** in the
  four payload files. It read the files but could not rerun tests in that lane;
  executed test evidence above is the owner's. Integrated deployment approval
  remains pending. Codex Spark was catalogued but unsupported by this account,
  so review used the previously working GPT-6.1 Sol path, not Go models.

Full-suite command (working directory is this repository):

```sh
env -i PATH=/usr/bin:/bin HOME=/tmp/opencode LANG=C.UTF-8 \
  PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 EASY_LIVE_TESTS=0 \
  /tmp/opencode/restaurant-telephone-venv/bin/python -m pytest -q -ra \
  -p no:cacheprovider --tb=short \
  --basetemp=/tmp/opencode/restaurant-phone-answer-bank-full-green
```

## Live baseline, not restaurant acceptance

At 13:12:55 UTC, worker/bridge/web were healthy on published `3791c6d`; all 64
app/demo file hashes matched, worker had zero restarts and there were no active
rooms. Shared persistent volume remained unchanged; read-only SQLite quick_check
passed all three existing journals. Automatic ET/EN/RU voices were preserved.
The current worker had no restaurant business setting. These facts are a baseline,
**not** acceptance of restaurant dialogue, a real PSTN call or a real restaurant.

## Shared-routing continuation

Minimal backwards-compatible routing now forwards one selected bank to language
inference and FAQ matching in the shared `CallTools` final-turn observer. No new
public selector, environment switch, booking tool or backend was added.

- Routing tests failed first: **18 failed, 2 passed** (missing approved replies
  and missed English selection). After routing, **1,280 scoped tests passed**.
- Full suite: **2,815 passed, 36 subtests passed, 4 skipped, 2 upstream warnings**,
  55.49 seconds, using the same command above with basetemp
  `/tmp/opencode/restaurant-phone-shared-routing-full`.
- Nine HTTP and nine shared-native topic/language cases prove canonical spoken
  replies, fabricated-claim replacement and no model/backend actions. Two cases
  preserve uncertain-write priority and reject a transcript-based selector.
  Tests deliberately set trusted server state to exercise this routing seam;
  they do **not** prove actual restaurant constructor/backend activation.
- Independent review of the routing seam: **interim PASS, no P0/P1**. It remains
  a static review; deployment is not approved before published-core integration.
- Task-private restaurant audio harness self-test passed **33 boundary cases and
  12 restaurant input cases**, zero provider calls. An attempted guarded allergy
  probe correctly refused the current worker with `RESTAURANT_WORKER_REQUIRED`
  before creating a room or contacting a speech provider. This expected refusal
  is **not** successful restaurant speech acceptance.
