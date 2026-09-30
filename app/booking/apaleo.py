"""Apaleo StayAdapter (first paid adapter — API-first, EU).

Flow (verified apaleo.dev IBE guides 2026-08-07):
  GET /inventory/v1/properties
  GET /booking/v1/offers?propertyId&arrival&departure&adults&channelCode=Ibe
  collect guest -> Adyen Drop-in authorise prePaymentGrossAmount sum
  POST /booking/v1/bookings with PSP ref
Semantics: charge prePaymentGrossAmount (city tax auto-added, do NOT add);
multi-room = one offers call per room then split totals.
Pricing: EUROS 8/room/mo, EUROS 400/mo floor (apaleo.com/pricing).
"""

from __future__ import annotations

from .base import Hold, HoldLedger, StayAdapter, UnknownQuoteError


class ApaleoAdapter(StayAdapter):
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        base_url: str = "https://api.apaleo.com",
    ) -> None:
        self._cid = client_id
        self._secret = client_secret
        self._base = base_url.rstrip("/")
        self._holds = HoldLedger()
        self._offers: dict[str, dict] = {}  # price_quote_id -> offer snapshot

    def __repr__(self) -> str:
        return "ApaleoAdapter(redacted)"

    async def search_availability(
        self, checkin: str, checkout: str, party: dict
    ) -> list[dict]:
        raise NotImplementedError("wire GET /booking/v1/offers in Phase 2")

    async def create_hold(self, price_quote_id: str) -> Hold:
        try:
            offer = self._offers[price_quote_id]
        except KeyError:
            raise UnknownQuoteError(price_quote_id) from None
        return self._holds.create(
            price_quote_id=price_quote_id,
            quoted_total=str(offer["prePaymentGrossAmount"]),
            currency=str(offer.get("currency", "EUR")),
            payload={"offer": offer},
        )

    async def confirm(self, hold_id: str, guest: dict, idempotency_key: str) -> dict:
        replayed = self._holds.check_replay(idempotency_key)
        if replayed is not None:
            return replayed
        hold = self._holds.get(hold_id)
        if hold is None:
            return {"ok": False, "error": "hold_expired_or_unknown"}
        raise NotImplementedError("re-price + POST /booking/v1/bookings")

    async def cancel(self, booking_id: str, idempotency_key: str) -> dict:
        replayed = self._holds.check_replay(idempotency_key)
        if replayed is not None:
            return replayed
        raise NotImplementedError("wire cancel in Phase 2")
