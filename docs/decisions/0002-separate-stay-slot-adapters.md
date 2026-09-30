# ADR-0002: Separate stay inventory from appointment slots

- Status: **Accepted; adapter implementations remain gated**
- Date: 2026-09-30

## Context

Hotel stays use date ranges, occupancy, room/rate inventory, taxes, guarantees,
and repricing. Spa appointments use service, provider, room/equipment, and time
slot lifecycles. A single generic booking interface would leak vendor-specific
conditions or discard safety-critical semantics.

## Considered options

1. One generic booking adapter.
2. Separate `StayAdapter` and `SlotAdapter` contracts.
3. Put provider APIs directly in LLM tools.

## Decision outcome

Choose option 2. Tool schemas stay provider-neutral; adapters preserve the
different domain semantics. Provider tools are advertised only after the
adapter opts into operational status and passes its write-path gate.

## Consequences

- Good: hotel and spa rules stay explicit and independently testable.
- Good: a property can use one combined provider or separate systems.
- Bad: combined hotel/spa providers may need two wrappers over one API client.
- Bad: shared guest/payment/cancellation policy must be kept in common code.

## Confirmation

Contract tests require availability/search, quote/hold, confirm, cancel,
expiry, retry, ambiguous outcome, ownership, and same-inventory race behavior.
`operational=True` is permitted only after the provider's required suite passes.
