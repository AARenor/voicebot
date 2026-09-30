"""Zenoti SlotAdapter (spa parallel track).

Lifecycle: create booking -> reserve slot -> confirm -> collect payment
(docs.zenoti.com/docs/service-booking-apis). Auth apikey or bearer flow.
Prereqs live in PMS: services, employee schedules, center hours, processor.
"""

from __future__ import annotations

from .base import Hold, HoldLedger, SlotAdapter


class ZenotiAdapter(SlotAdapter):
    def __init__(self, api_key: str, base_url: str = "https://api.zenoti.com") -> None:
        self._key = api_key
        self._base = base_url.rstrip("/")
        self._holds = HoldLedger()

    def __repr__(self) -> str:
        return "ZenotiAdapter(redacted)"

    async def search_slots(
        self, service: str, date: str, provider: str | None = None
    ) -> list[dict]:
        raise NotImplementedError("wire slot search in Phase 2")

    async def create_hold(self, slot_id: str) -> Hold:
        # No price on slot holds: confirm must price via PMS, and no price
        # may be uttered without a live pricing call (fidelity guard).
        return self._holds.create(
            price_quote_id=slot_id,
            quoted_total=None,
            currency="EUR",
            payload={"slot_id": slot_id},
        )

    async def confirm(self, hold_id: str, guest: dict, idempotency_key: str) -> dict:
        replayed = self._holds.check_replay(idempotency_key)
        if replayed is not None:
            return replayed
        hold = self._holds.get(hold_id)
        if hold is None:
            return {"ok": False, "error": "hold_expired_or_unknown"}
        raise NotImplementedError("reserve slot -> confirm")

    async def cancel(self, booking_id: str, idempotency_key: str) -> dict:
        replayed = self._holds.check_replay(idempotency_key)
        if replayed is not None:
            return replayed
        raise NotImplementedError("wire cancel in Phase 2")
