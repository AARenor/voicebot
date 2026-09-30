"""Booking adapters: Stay (night inventory) vs Slot (time resources).

Split exists because night-inventory (room x date x rate x occupancy,
prePaymentGrossAmount, guarantee types) and slot-resources (service x
provider x time-slot x booking lifecycle) leak through any single interface.
Shared: auth, idempotency keys, confirmation envelope, TTL hold ledger.
"""

from __future__ import annotations

import abc
import dataclasses
import time
import uuid

CLOCK = time.monotonic  # TTLs use monotonic time (immune to clock jumps).


@dataclasses.dataclass
class UnknownQuoteError(LookupError):
    """create_hold referenced an unknown price_quote_id (typed, not KeyError)."""

    quote_id: str = ""

    def __str__(self) -> str:
        return self.quote_id or super().__str__()


@dataclasses.dataclass
class Hold:
    hold_id: str
    price_quote_id: str
    # Verbatim PMS string, never recomputed. None = no price on this track
    # (slot holds, $0 demos): never utter a price without a pricing call.
    quoted_total: str | None
    currency: str
    expires_at: float
    payload: dict

    def expired(self, now: float | None = None) -> bool:
        return (CLOCK() if now is None else now) > self.expires_at


class HoldLedger:
    """Adapter-side TTL reservations. PMS is truth on confirm.

    Single-worker constraint: no lock, no background sweep — unretrieved
    holds evict lazily on get(). Do not share across processes without
    adding a lock + sweep. Idempotency: confirm()/cancel() results are
    recorded per idempotency_key; replays return the recorded envelope
    without touching the PMS again.
    """

    def __init__(self, ttl_seconds: int = 600) -> None:
        self._ttl = ttl_seconds
        self._holds: dict[str, Hold] = {}
        self._idempotent: dict[str, dict] = {}
        self._pending: set[str] = set()  # keys with a PMS call in flight

    def check_replay(self, idempotency_key: str) -> dict | None:
        """Return recorded result if this key was seen, else None."""
        return self._idempotent.get(idempotency_key)

    def reserve(self, idempotency_key: str) -> bool:
        """Mark a PMS call in flight. False = already recorded or running.

        Crash/restart window: maps are in-memory, so a restart loses both
        pending and recorded keys — post-restart retries MUST reconcile
        against PMS truth (list/get before re-POST), never blindly
        re-book. Single-worker demo constraint.
        """
        if idempotency_key in self._idempotent or idempotency_key in self._pending:
            return False
        self._pending.add(idempotency_key)
        return True

    def record(self, idempotency_key: str, result: dict) -> dict:
        self._pending.discard(idempotency_key)
        self._idempotent[idempotency_key] = result
        return result

    def release_pending(self, idempotency_key: str) -> None:
        """Free a pending key WITHOUT recording (PMS call failed).

        Callers must wrap everything after reserve() so any exception
        releases the key — otherwise the first attempt's failure blocks
        all same-key retries forever (poisoned idempotency).
        """
        self._pending.discard(idempotency_key)

    def create(
        self,
        price_quote_id: str,
        quoted_total: str | None,
        currency: str,
        payload: dict,
    ) -> Hold:
        hold = Hold(
            hold_id="hold_" + uuid.uuid4().hex[:12],
            price_quote_id=price_quote_id,
            quoted_total=quoted_total,
            currency=currency,
            expires_at=CLOCK() + self._ttl,
            payload=payload,
        )
        self._holds[hold.hold_id] = hold
        return hold

    def get(self, hold_id: str) -> Hold | None:
        hold = self._holds.get(hold_id)
        if hold is None or hold.expired():
            self._holds.pop(hold_id, None)
            return None
        return hold

    def release(self, hold_id: str) -> None:
        self._holds.pop(hold_id, None)


class StayAdapter(abc.ABC):
    """Night-inventory PMS (Apaleo, Mews, Cloudbeds, QloApps demo)."""

    @abc.abstractmethod
    async def search_availability(
        self, checkin: str, checkout: str, party: dict
    ) -> list[dict]:
        """Return live priced offers; each carries a price_quote_id."""

    @abc.abstractmethod
    async def create_hold(self, price_quote_id: str) -> Hold:
        """Snapshot offer into TTL hold. Never charge here."""

    @abc.abstractmethod
    async def confirm(self, hold_id: str, guest: dict, idempotency_key: str) -> dict:
        """Re-price against PMS truth, then book. Reject on price move."""

    @abc.abstractmethod
    async def cancel(self, booking_id: str, idempotency_key: str) -> dict: ...


class SlotAdapter(abc.ABC):
    """Slot-resource scheduler (Zenoti, Easy!Appointments, Cal, Fresha-staff)."""

    @abc.abstractmethod
    async def search_slots(
        self, service: str, date: str, provider: str | None = None
    ) -> list[dict]: ...

    @abc.abstractmethod
    async def create_hold(self, slot_id: str) -> Hold: ...

    @abc.abstractmethod
    async def confirm(
        self, hold_id: str, guest: dict, idempotency_key: str
    ) -> dict: ...

    @abc.abstractmethod
    async def cancel(self, booking_id: str, idempotency_key: str) -> dict: ...
