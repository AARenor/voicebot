"""QloApps demo double (StayAdapter, $0 dev only).

OSL-3.0 PrestaShop fork (PHP/MySQL), Docker webkul/qloapps_docker.
No public booking REST found — adapter maps rate tables directly;
NEVER run live inventory on it without mapping availability/rate tables.
Network-copyleft: legal read before multi-tenant hosting.
"""

from __future__ import annotations

from .base import Hold, HoldLedger, StayAdapter


class QloAppsAdapter(StayAdapter):
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._holds = HoldLedger()

    def __repr__(self) -> str:
        return "QloAppsAdapter(redacted)"

    async def search_availability(
        self, checkin: str, checkout: str, party: dict
    ) -> list[dict]:
        raise NotImplementedError("map rate tables in Phase 1")

    async def create_hold(self, price_quote_id: str) -> Hold:
        # $0 demo: no price — never utter one on this track.
        return self._holds.create(
            price_quote_id=price_quote_id,
            quoted_total=None,
            currency="EUR",
            payload={},
        )

    async def confirm(self, hold_id: str, guest: dict, idempotency_key: str) -> dict:
        replayed = self._holds.check_replay(idempotency_key)
        if replayed is not None:
            return replayed
        hold = self._holds.get(hold_id)
        if hold is None:
            return {"ok": False, "error": "hold_expired_or_unknown"}
        raise NotImplementedError("wire confirm in Phase 1")

    async def cancel(self, booking_id: str, idempotency_key: str) -> dict:
        replayed = self._holds.check_replay(idempotency_key)
        if replayed is not None:
            return replayed
        raise NotImplementedError("wire cancel in Phase 1")
