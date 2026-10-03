# Natural receptionist language — 2026-10-03

## Changes

- Estonian, English and Russian thanks are brief acknowledgments, not another booking prompt. Requests for a person retain the demo's explicit transfer limitation without pitching a test booking; the reviewed FAQ copy has the same change.
- Existing Estonian spa inquiries ask for the missing date, then the missing time. User-supplied date/time survive a bounded repeat or repair request; mixed polite booking requests still reach planning.
- Repeat requests reuse the last checked approved clarification. Frustration receives a short reviewed apology and that same question, rather than restarting the conversation. Only language/question/variant identities are retained, never caller prose, availability, prices or recap contents. Unrelated replies and language changes clear the identity.
- English replay also recognizes existing fixed clarification aliases, including native empty-response recovery and ambiguity questions. Default modern wording stays first in each choice list.
- Children are asked for one count, with “null” and “none” accepted by the existing anchored planning-input matcher. These words never authorize a booking.

Example Estonian flow: “Mis kuupäev sulle sobiks?” → caller supplies tomorrow → “Mis kell sulle sobiks?” → repeat → the same time question. Repair: “Vabandust. Võtame ühe asja korraga. Mis kell sulle sobiks?”

## Safety and evidence

Canonical hotel facts, exact prices, action status, booking recaps, hold ownership, renewed recap delivery and later explicit consent remain server-controlled. Unknown writes cannot be hidden by polite or contextual replies. No new dependencies, model/provider settings or voice settings were added.

- TDD: 15 intended initial failures plus two child-question failures preceded implementation. Review regressions independently reproduced 12 failures with one passing numeric-zero control before the fixes.
- Focused conversation/inquiry/truth/language suites: **311 passed, 13 skipped**.
- Complete core: **2550 passed, 57 skipped, 36 passing subtests** (`/tmp/opencode/voicebot-modern-voices-testenv-20261003/bin/python -m pytest tests -q --tb=short`).
- Complete pinned-media: **2781 passed, 9 skipped, 36 passing subtests**, using the read-only, network-disabled `voicebot-telephone:b1940070d94b` invocation recorded in `2026-10-03-modern-voices.md`. Suite counts overlap and must not be summed. Existing Starlette/httpx and pinned-image audioop deprecation warnings remain.
- One initial full-suite fixture still expected the superseded combined date/time prompt. Its independent literal was updated to the intentionally emitted date-only question; the exact approved-speech guard assertion was retained.
- Independent review: round1 reproduced two P2 gaps (advertised zero-count words and legacy English replay), both fixed with RED/GREEN regressions. Round2 rechecked the HTTP reproductions and found no remaining P0/P1/P2 issues. The dedicated review backend was unavailable; a default general-agent fallback completed both reviews without changing provider configuration.
- Automatic formatter layout changes in touched Python files were separated from semantics with AST comparisons. Existing Russian translations remain unchanged; two approved question translations were added. FAQ data changes are limited to three transfer-limit answer strings, not facts or schema.

These checks establish deterministic wording and safety behavior, not subjective human listening preference, physical microphone behavior or PSTN acceptance. Automatic deployment and safe owned-session acceptance are recorded in `/home/arle/.opencode/goals/natural-voicebot-language/EVIDENCE.md`; the probe never confirms or cancels a booking.
