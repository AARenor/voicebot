"""Easy!Appointments demo double (SlotAdapter, spa side only).

GPL-3.0. Shapes below follow the real openapi.yml v1.0.0 (fetched
2026-09-30 from github.com/alextselegidis/easyappointments):
  GET /availabilities?providerId&serviceId&date -> 200: string[] (times)
  POST /appointments (AppointmentPayload) -> 201: AppointmentRecord
  DELETE /appointments/{id} -> 204 (404 treated as success: idempotent)
  AppointmentPayload: {start, end, customerId, providerId, serviceId,
    notes?, status?, location?}; CustomerPayload: {firstName, lastName,
    email?, phone?, ...}; ServiceRecord: {id, duration (min), price, ...}
  Auth: BearerToken OR BasicAuth per spec.
Single-resource slots — never rooms. Self-host per property.
Auth scheme + API prefix are constructor params: VERIFY both against the
property's openapi.yml at deploy (defaults match upstream layout).
"""

from __future__ import annotations

from datetime import datetime, timedelta

import httpx

from .base import Hold, HoldLedger, SlotAdapter, UnknownQuoteError
from ..providers.errors import ProviderError, raise_for_provider


def _parse_start(value: str) -> datetime:
    """Accept our slot format with or without seconds (API emits both)."""
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(str(value), fmt)
        except (ValueError, TypeError):
            continue
    raise ProviderError(f"easy.confirm: bad start: {value!r}")


def _required_int(value, name: str) -> int:
    try:
        return int(str(value))
    except (ValueError, TypeError) as exc:
        raise ProviderError(f"easy.confirm: bad {name}: {exc}") from exc


def _optional_int(value) -> int | None:
    if value is None or value == "":
        return None
    return _required_int(value, "providerId")


def _path_segment(value: str) -> str:
    """Booking ids are int-like per AppointmentRecord; reject path junk."""
    if not str(value).isdigit():
        raise ProviderError(f"easy.cancel: bad booking_id: {value!r}")
    return str(value)


class EasyAppointmentsAdapter(SlotAdapter):
    def __init__(
        self,
        base_url: str,
        api_key: str,
        auth_scheme: str = "Bearer ",
        api_prefix: str = "/index.php/api/v1",
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._base = base_url.rstrip("/") + api_prefix
        self._key = api_key
        self._holds = HoldLedger()
        self._slots: dict[str, dict] = {}  # slot_id -> slot snapshot
        self._http = httpx.AsyncClient(
            headers={"Authorization": f"{auth_scheme}{api_key}"},
            timeout=30.0,
            transport=transport,
        )

    def __repr__(self) -> str:
        return "EasyAppointmentsAdapter(redacted)"

    async def close(self) -> None:
        await self._http.aclose()

    async def search_slots(
        self, service: str, date: str, provider: str | None = None
    ) -> list[dict]:
        params: dict = {"serviceId": service, "date": date}
        if provider is not None:
            params["providerId"] = provider
        response = await self._http.get(f"{self._base}/availabilities", params=params)
        raise_for_provider(response, "easy.search_slots")
        try:
            times = response.json()
            if isinstance(times, dict) and "data" in times:
                times = times["data"]  # defensive envelope unwrap
            if not isinstance(times, list):
                raise ProviderError(
                    f"easy.search_slots: bad payload: {type(times).__name__}"
                )
            slots = []
            for t in times:
                start = f"{date} {t}" if " " not in str(t) else str(t)
                # '|' separator: service ids are integer-like, never contain
                # it; empty provider stays empty (no '-' collision).
                slot_id = f"{service}|{provider or ''}|{start}"
                slot = {
                    "slotId": slot_id,
                    "serviceId": service,
                    "providerId": provider,
                    "date": date,
                    "start": start,
                }
                self._slots[slot_id] = slot
                slots.append(slot)
            return slots
        except (ValueError, TypeError, AttributeError) as exc:
            raise ProviderError(f"easy.search_slots: bad payload: {exc}") from exc

    async def _ensure_customer(self, guest: dict) -> int:
        """Return customerId: reuse guest's, else create via /customers."""
        if guest.get("customerId") is not None:
            return _required_int(guest.get("customerId"), "customerId")
        body = {
            "firstName": guest.get("firstName", ""),
            "lastName": guest.get("lastName", ""),
            "email": guest.get("email", ""),
            "phone": guest.get("phone", ""),
        }
        response = await self._http.post(f"{self._base}/customers", json=body)
        raise_for_provider(response, "easy.ensure_customer")
        try:
            return int(response.json()["id"])
        except (KeyError, ValueError, TypeError) as exc:
            raise ProviderError(f"easy.ensure_customer: bad payload: {exc}") from exc

    async def _service_duration(self, service_id: str) -> int:
        response = await self._http.get(f"{self._base}/services/{service_id}")
        raise_for_provider(response, "easy.service")
        try:
            return int(response.json()["duration"])
        except (KeyError, ValueError, TypeError) as exc:
            raise ProviderError(f"easy.service: bad payload: {exc}") from exc

    async def create_hold(self, slot_id: str) -> Hold:
        # $0 demo: no price — never utter one on this track.
        try:
            slot = self._slots[slot_id]
        except KeyError:
            raise UnknownQuoteError(slot_id) from None
        return self._holds.create(
            price_quote_id=slot_id,
            quoted_total=None,
            currency="EUR",
            payload={"slot": dict(slot)},
        )

    async def confirm(self, hold_id: str, guest: dict, idempotency_key: str) -> dict:
        replayed = self._holds.check_replay(idempotency_key)
        if replayed is not None:
            return replayed
        hold = self._holds.get(hold_id)
        if hold is None:
            return {"ok": False, "error": "hold_expired_or_unknown"}
        if not self._holds.reserve(idempotency_key):
            return {"ok": False, "error": "confirm_in_progress"}
        if not self._holds.reserve(f"confirm:{hold_id}"):
            self._holds.release_pending(idempotency_key)
            return {"ok": False, "error": "hold_already_confirming"}
        try:
            slot = hold.payload["slot"]
            customer_id = self._holds.get_memo(idempotency_key, "customerId")
            if customer_id is None:
                customer_id = await self._ensure_customer(guest)
                self._holds.memo(idempotency_key, "customerId", customer_id)
            minutes = await self._service_duration(str(slot["serviceId"]))
            start = _parse_start(slot["start"])
            body = {
                "start": start.strftime("%Y-%m-%d %H:%M:%S"),
                "end": (start + timedelta(minutes=minutes)).strftime(
                    "%Y-%m-%d %H:%M:%S"
                ),
                "customerId": customer_id,
                "providerId": _optional_int(slot.get("providerId")),
                "serviceId": _required_int(slot.get("serviceId"), "serviceId"),
                "notes": guest.get("notes", ""),
                "status": "Booked",
            }
            body = {k: v for k, v in body.items() if v is not None}
            response = await self._http.post(f"{self._base}/appointments", json=body)
            raise_for_provider(response, "easy.confirm")
        except Exception:
            self._holds.release_pending(idempotency_key)
            self._holds.release_pending(f"confirm:{hold_id}")
            raise
        try:
            result = {"ok": True, "booking": response.json()}
        except ValueError as exc:
            self._holds.release_pending(idempotency_key)
            self._holds.release_pending(f"confirm:{hold_id}")
            raise ProviderError(f"easy.confirm: bad payload: {exc}") from exc
        self._holds.release(hold_id)  # consumed: no reconfirm with new key
        return self._holds.record(idempotency_key, result)

    async def cancel(self, booking_id: str, idempotency_key: str) -> dict:
        replayed = self._holds.check_replay(idempotency_key)
        if replayed is not None:
            return replayed
        if not self._holds.reserve(idempotency_key):
            return {"ok": False, "error": "cancel_in_progress"}
        try:
            booking_ref = _path_segment(booking_id)
            response = await self._http.delete(
                f"{self._base}/appointments/{booking_ref}"
            )
            if response.status_code == 404:
                # Already gone: idempotent cancel counts as success.
                return self._holds.record(
                    idempotency_key,
                    {"ok": True, "booking_id": booking_id, "already_gone": True},
                )
            raise_for_provider(response, "easy.cancel")
        except Exception:
            self._holds.release_pending(idempotency_key)
            raise
        result = {"ok": True, "booking_id": booking_id}
        return self._holds.record(idempotency_key, result)
