"""Mews StayAdapter (second — market coverage).

Booking Engine API (NOT Connector):
  [base]/api/distributor/v1/hotels/getAvailability
  [base]/api/distributor/v1/reservations/getPricing  (quote)
  [base]/api/distributor/v1/reservations/price       (total incl.
    AmountToChargeOnConfirmation)
  reservation-group create in same reservations family.
Auth: ClientToken + AccessToken + Client per-request JSON body.
Source: docs.mews.com/booking-engine-guide/booking-engine-api.md.
"""

from __future__ import annotations

from .base import Hold, HoldLedger, StayAdapter, UnknownQuoteError


class MewsAdapter(StayAdapter):
    def __init__(
        self, client_token: str, access_token: str, client: str, api_base_url: str
    ) -> None:
        self._auth = {
            "ClientToken": client_token,
            "AccessToken": access_token,
            "Client": client,
        }
        self._base = api_base_url.rstrip("/")
        self._holds = HoldLedger()
        self._quotes: dict[str, dict] = {}

    def __repr__(self) -> str:
        return "MewsAdapter(redacted)"

    async def search_availability(
        self, checkin: str, checkout: str, party: dict
    ) -> list[dict]:
        raise NotImplementedError("wire getAvailability + getPricing")

    async def create_hold(self, price_quote_id: str) -> Hold:
        try:
            quote = self._quotes[price_quote_id]
        except KeyError:
            raise UnknownQuoteError(price_quote_id) from None
        return self._holds.create(
            price_quote_id=price_quote_id,
            quoted_total=str(quote["total"]),
            currency=str(quote.get("currency", "EUR")),
            payload={"quote": quote},
        )

    async def confirm(self, hold_id: str, guest: dict, idempotency_key: str) -> dict:
        replayed = self._holds.check_replay(idempotency_key)
        if replayed is not None:
            return replayed
        hold = self._holds.get(hold_id)
        if hold is None:
            return {"ok": False, "error": "hold_expired_or_unknown"}
        raise NotImplementedError("re-price via /price + group create")

    async def cancel(self, booking_id: str, idempotency_key: str) -> dict:
        replayed = self._holds.check_replay(idempotency_key)
        if replayed is not None:
            return replayed
        raise NotImplementedError("wire cancel in Phase 2")
