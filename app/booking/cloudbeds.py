"""Cloudbeds StayAdapter (third — gateway-dependent payments).

postReservation adds a reservation (developers.cloudbeds.com/reference/
post_postreservation-2). PCI: raw PAN ONLY to POST vault/v1/tokens/card
(api.payments.cloudbeds.com) -> PaymentMethodId UUID -> postCreditCard/
postCharge/pay-by-link operate on tokens. Never PAN to postReservation.
Capabilities discovery: getHotelDetails, getPaymentMethods,
getPaymentsCapabilities.
"""

from __future__ import annotations

from .base import Hold, HoldLedger, StayAdapter, UnknownQuoteError
from ..providers.errors import ProviderError


class CloudbedsAdapter(StayAdapter):
    def __init__(
        self, api_key: str, base_url: str = "https://api.cloudbeds.com"
    ) -> None:
        self._key = api_key
        self._base = base_url.rstrip("/")
        self._holds = HoldLedger()
        self._quotes: dict[str, dict] = {}

    def __repr__(self) -> str:
        return "CloudbedsAdapter(redacted)"

    async def search_availability(
        self, checkin: str, checkout: str, party: dict
    ) -> list[dict]:
        raise NotImplementedError("wire getAvailableRoomTypes in Phase 2")

    async def create_hold(self, price_quote_id: str) -> Hold:
        try:
            quote = self._quotes[price_quote_id]
        except KeyError:
            raise UnknownQuoteError(price_quote_id) from None
        try:
            total = str(quote["total"])
        except KeyError as exc:
            raise ProviderError("cloudbeds: malformed quote snapshot") from exc
        return self._holds.create(
            price_quote_id=price_quote_id,
            quoted_total=total,
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
        raise NotImplementedError("tokenize-first + postReservation")

    async def cancel(self, booking_id: str, idempotency_key: str) -> dict:
        replayed = self._holds.check_replay(idempotency_key)
        if replayed is not None:
            return replayed
        raise NotImplementedError("wire cancel in Phase 2")
