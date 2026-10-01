# ADR-0003: Booking provider is truth; local state coordinates only

- Status: **Accepted; implemented for controlled single-host Easy demo, production incomplete**
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

Choose option 3. In the distributed target, Redis stores short-lived holds,
caller ownership, pending keys, rate budgets, and cached idempotent results.
The installed single-host Easy demo instead uses ephemeral holds and a durable
SQLite write journal/file lock. Customer and appointment writes persist pending
state before side effects; uncertainty blocks new confirmations until safe
reconciliation or operator recovery. This does not establish caller ownership,
cross-host exclusion or inventory protection against independent writers.
The booking provider remains the
only inventory and booking authority. Confirmation revalidates inventory and
price. Ambiguous writes are queried by provider correlation/customer/time
before any retry.

Operator website projections must read provider truth through private
allowlisted APIs. The demo queue, local hold and journal are not a bookings
calendar. See [website design](../research/website-booking-architecture/DESIGN.md)
for the researched, not-yet-implemented read-only panel and its test contract.

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
