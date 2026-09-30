# ADR-0003: Booking provider is truth; local state coordinates only

- Status: **Accepted principle; implementation incomplete**
- Date: 2026-09-30

## Context

Concurrent callers and retries can race for the same inventory. Process memory
cannot prove availability or exactly-once writes, and a timeout does not reveal
whether a remote provider committed the booking.

## Considered options

1. Trust local holds as inventory reservations.
2. Retry failed POST requests blindly.
3. Use local durable coordination, then revalidate/reconcile provider truth.

## Decision outcome

Choose option 3. Redis stores short-lived holds, caller ownership, pending keys,
rate budgets, and cached idempotent results. The booking provider remains the
only inventory and booking authority. Confirmation revalidates inventory and
price. Ambiguous writes are queried by provider correlation/customer/time
before any retry.

## Consequences

- Good: restart/replica coordination without pretending Redis owns inventory.
- Good: deterministic behavior for concurrent callers and retries.
- Bad: each provider needs a reconciliation strategy; some private APIs may not
  expose adequate correlation/search.
- Bad: exactly-once cannot be promised until provider semantics are tested.

## Confirmation

A provider adapter is live-write capable only after same-slot, same-key,
commit-then-timeout, process-restart, and unknown-result tests prove one remote
booking or a fail-closed manual-reconciliation outcome.
