# Restaurant pivot implementation plan

1. Pin published master, read existing domain/tool/voice/UI contracts, capture
   storage/configuration hashes and review this design before code changes.
2. Parallel disjoint backend and policy implementation with failing-first tests;
   frontend follows the explicit table/offer/receipt contract. Owner wires actual
   startup/direct HTTP/native paths and repairs private-image packaging.
3. Adapt the active restaurant browser acceptance journeys while keeping legacy
   adapter/consent tests explicit. Add direct same-hold recap-generation regression
   and table receipt/history/terminal-action coverage.
4. Full clean-environment core/media and local headless browser suites, package
   smoke/default nonroot UID proof, self-review and independent adversarial review.
   Reproduce and repair concrete findings without unrequested dependency changes.
5. Refresh/preserve published contributor changes by safe normal merge; stage
   only intended source/docs/tests, credential/syntax scan, commit and push.
6. Verify public served assets and compiled source, safely reconcile separately
   deployed worker/bridge with no active rooms, retain shared data and carrier
   configuration, run bounded fictional restaurant provider dialogue/readback.
7. Compare preservation snapshots, audit evidence once, report actual revisions,
   checks and remaining limits, and close file-backed goal through its tool.
