# Implementation plan: modern demo voices

Design: [reviewed specification](../specs/2026-10-03-modern-voices-design.md).
Use test-first implementation and preserve ordinary JSON compatibility.

## Ordered steps and ownership

1. **Provider lane:** own new modern-provider/registry modules, Azure byte streaming
   and provider/registry tests only. Return observed RED/GREEN commands, exact public
   interfaces, bounded failure behavior and configuration requirements. Do not edit
   server, shared turn/session code, static assets, dependencies or deployment.
2. **Backend lane:** after provider interface agreement, own guarded transport hooks,
   session speech selection, NDJSON helper and backend tests. Preserve one turn
   execution, producer-owned cleanup, normal JSON and receipt authority. No provider
   or static-file edits.
3. **Frontend lane:** after protocol agreement, own dashboard static assets and
   JS/browser tests. Implement selector, MP3 MSE/Blob playback, strict ACK/generation
   cleanup and bounded 650 ms endpointing. Recompute existing asset hashes. No Python
   production or provider edits.
4. **Integrator:** own written spec/plan, requirements/environment examples and
   operational docs; reconcile lane interfaces and dependencies. Re-read each change,
   run full/focused/core/media/browser checks and independently review final diff.
5. **Delivery:** safely integrate later upstream changes, commit/push only reviewed
   intended files and verify signed-webhook deployment, health and preserved volume.
   Record actual configured provider and audio evidence; no unauthenticated provider
   calls, guest/booking writes, new credentials or subjective/PSTN claims.

## Acceptance contracts

- Every nontrivial new behavior has a runnable regression observed failing first.
- Catalog reveals configuration readiness only and rejects unknown/unavailable choices.
- Provider request text is the exact guarded input; selected voice is session-owned.
- Azure remains default and fallback, but no fallback audio is appended after partial
  provider output. No failure or transport retry repeats a booking operation.
- First fixture audio chunk arrives before synthesis completion. Terminal receipt is
  absent on interrupted/failed synthesis and retained only after full actual playback.
- Logout, seeking, stale callbacks and failed end-session requests cannot grant ACKs.
- Complete suite results list failures/skips honestly; native release remains separate.
- Final deployed sources contain the reviewed change and retain the existing journal.
