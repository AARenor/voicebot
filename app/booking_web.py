"""Website booking controls using the same call-owned tools as voice turns."""

from __future__ import annotations

import json
import os
import re
import uuid
from datetime import date, datetime
from zoneinfo import ZoneInfo

from fastapi import Header, HTTPException, Request
from fastapi.responses import JSONResponse

from .dashboard.api import _require_operator
from .demo import load_demo_data
from .hackathon import operator_scope, table_receipt_metadata
from . import call_history, callslog


async def _body(request):
    content = bytearray()
    async for chunk in request.stream():
        if len(content) + len(chunk) > 8192:
            raise HTTPException(413, "booking_body_too_large")
        content.extend(chunk)
    try:
        value = json.loads(content)
    except (ValueError, UnicodeError, RecursionError):
        raise HTTPException(400, "booking_arguments_invalid") from None
    if not isinstance(value, dict):
        raise HTTPException(400, "booking_arguments_invalid")
    return value


def _fields(body, allowed, required=()):
    if set(body) - set(allowed) or any(key not in body for key in required):
        raise HTTPException(400, "booking_arguments_invalid")


def _kind(body, tools=None):
    if body.get("kind") not in ("slot", "stay", "table"):
        raise HTTPException(400, "booking_kind_invalid")
    if getattr(tools, "business", None) == "restaurant" and body["kind"] != "table":
        raise HTTPException(400, "restaurant_booking_required")
    return body["kind"]


def _day(value, *, future=False, max_days=365):
    try:
        day = date.fromisoformat(value)
        today = datetime.now(ZoneInfo("Europe/Tallinn")).date()
        if (
            day.isoformat() != value
            or not (0 if future else -31) <= (day - today).days <= max_days
        ):
            raise ValueError()
    except (TypeError, ValueError):
        raise HTTPException(400, "booking_date_invalid") from None
    return value


def _result(result):
    if not isinstance(result, dict):
        result = {"error": "booking_unavailable"}
    result = {"synthetic": True, **result}
    if result.get("error") or result.get("ok") is False:
        result["ok"] = False
        code = result.get("error", "booking_unavailable")
        status = (
            503
            if code
            in {
                "booking_unavailable",
                "mutation_outcome_unknown",
                "write_outcome_unknown",
                "cancel_outcome_unknown",
            }
            else 409
        )
        return JSONResponse(result, status_code=status)
    return result


def _remember_booking(session, body, result, kind, cancel):
    """Optional calendar metadata must never erase a completed write receipt."""
    changes = []
    try:
        if not cancel and isinstance(result.get("booking"), dict):
            booking = result["booking"]
            booking_id = str(booking["id"])
            details = {"id": booking_id, "kind": kind, "timezone": "Europe/Tallinn"}
            if kind == "stay":
                details.update(
                    date=booking["checkin"],
                    checkin=booking["checkin"],
                    checkout=booking["checkout"],
                )
            elif kind == "table":
                details = table_receipt_metadata(booking)
            else:
                slot = session.tools.held_slots[body["hold_id"]]
                details.update(date=slot["date"], start_local=slot["start"])
            session.booking_details[booking_id] = details
            result["booking_id"] = booking_id
            changes.append({"action": "confirmed", **details})
        elif cancel and body["booking_id"] in session.booking_details:
            changes.append(
                {"action": "cancelled", **session.booking_details[body["booking_id"]]}
            )
    except (KeyError, TypeError, ValueError, AttributeError):
        pass  # Keep the provider's receipt; do not guess its booking date.
    result["booking_changes"] = changes
    callslog.history_safe(
        call_history.record_result,
        session.tools.call_id,
        "booking_cancelled" if cancel else "booking_confirmed",
        changes=changes,
    )


def add_booking_routes(app, sessions):
    """Register controls before the root static mount; no LLM is needed."""

    def restaurant_mode():
        return (
            getattr(app.state.stack["dispatcher"], "business", "legacy") == "restaurant"
        )

    async def table_catalogue():
        reader = getattr(app.state.stack.get("table"), "get_table_catalogue", None)
        if not callable(reader):
            raise HTTPException(503, "table_booking_not_configured")
        try:
            return await reader()
        except Exception:
            raise HTTPException(502, "table_catalogue_unavailable") from None

    @app.get("/api/public/property")
    async def public_property():
        data = load_demo_data(business="restaurant" if restaurant_mode() else "legacy")
        number = (
            os.environ.get("PUBLIC_PHONE_NUMBER")
            or os.environ.get("TWILIO_PHONE_NUMBER")
            or os.environ.get("SIP_INBOUND_NUMBER")
        )
        if not isinstance(number, str) or not re.fullmatch(
            r"\+[1-9][0-9]{6,14}", number
        ):
            number = None
        profile = dict(data["profile"])
        if restaurant_mode():
            try:
                profile["restaurant_rules"] = (await table_catalogue())["rules"]
                profile["hours_source"] = "fictional_restaurant_catalogue"
                profile["hours_scope"] = "restaurant_sittings"
            except (HTTPException, KeyError):
                pass
        reader = (
            None
            if restaurant_mode()
            else (app.state.stack.get("slot") or app.state.stack.get("booking_reader"))
        )
        catalogue_read = getattr(reader, "get_slot_catalogue", None)
        if callable(catalogue_read):
            try:
                catalogue = await catalogue_read()
                providers = catalogue.get("providers", [])
                hours = [
                    provider["working_hours"]
                    for provider in providers
                    if isinstance(provider.get("working_hours"), dict)
                ]
                if (
                    hours
                    and len(hours) == len(providers)
                    and all(plan == hours[0] for plan in hours)
                ):
                    profile["working_hours"] = hours[0]
                    profile["hours_source"] = "easyappointments_provider_working_plan"
                    profile["hours_scope"] = "spa_treatments"
            except Exception:
                # An unavailable plan stays absent; reference examples are not
                # evidence of the current provider schedule.
                pass
        return {
            "synthetic": True,
            "property": profile,
            "faq": data["faq"],
            "phone": {
                "number": number,
                "href": f"tel:{number}" if number else None,
                "configured": bool(number),
            },
            "capabilities": {
                key: app.state.capabilities[key]
                for key in (
                    "slot_booking_ready",
                    "stay_booking_ready",
                    "table_booking_ready",
                )
            },
            "booking_access": "operator_demo",
        }

    async def room_catalogue():
        adapter = app.state.stack.get("stay")
        reader = getattr(adapter, "get_stay_catalogue", None)
        if not callable(reader):
            raise HTTPException(503, "stay_booking_not_configured")
        try:
            return await reader()
        except Exception:
            raise HTTPException(502, "room_catalogue_unavailable") from None

    @app.get("/api/public/catalogue")
    async def public_catalogue():
        if restaurant_mode():
            try:
                catalogue = await table_catalogue()
                return {
                    "synthetic": True,
                    "source": "fictional_restaurant",
                    "data_mode": "synthetic",
                    "tables": catalogue["tables"],
                    "rules": catalogue["rules"],
                    "venue": catalogue.get("venue"),
                    "menu": catalogue.get("menu", []),
                    "restaurant_error": None,
                }
            except HTTPException:
                return {
                    "synthetic": True,
                    "source": "fictional_restaurant",
                    "data_mode": "synthetic",
                    "tables": [],
                    "rules": None,
                    "restaurant_error": "table_catalogue_unavailable",
                }
        result = {
            "synthetic": True,
            "source": "easyappointments",
            "data_mode": "synthetic",
            "services": [],
            "providers": [],
            "rooms": None,
            "spa_error": None,
        }
        reader = app.state.stack.get("booking_reader")
        if reader is not None:
            try:
                catalogue = await reader.get_operator_catalogue()
                # Catalogue DTO omits contacts, appointments and credentials.
                result["services"] = catalogue["services"]
                result["providers"] = catalogue["providers"]
            except Exception:
                result["spa_error"] = "catalogue_unavailable"
        else:
            result["spa_error"] = "booking_reader_not_configured"
        try:
            result["rooms"] = await room_catalogue()
        except HTTPException:
            pass
        return result

    @app.get("/api/tables")
    async def tables(authorization: str | None = Header(default=None)):
        _require_operator(authorization)
        return await table_catalogue()

    @app.get("/api/table-bookings")
    async def table_bookings(
        date: str | None = None,
        authorization: str | None = Header(default=None),
    ):
        _require_operator(authorization)
        if date is not None:
            _day(date)
        reader = getattr(app.state.stack.get("table"), "get_operator_bookings", None)
        if not callable(reader):
            raise HTTPException(503, "table_booking_not_configured")
        try:
            return await reader(date)
        except Exception:
            raise HTTPException(502, "table_bookings_unavailable") from None

    @app.get("/api/rooms")
    async def rooms(authorization: str | None = Header(default=None)):
        _require_operator(authorization)
        return await room_catalogue()

    @app.get("/api/stays")
    async def stays(
        date: str | None = None, authorization: str | None = Header(default=None)
    ):
        _require_operator(authorization)
        if date is not None:
            _day(date)
        reader = getattr(app.state.stack.get("stay"), "get_operator_bookings", None)
        if not callable(reader):
            raise HTTPException(503, "stay_booking_not_configured")
        try:
            return await reader(date)
        except Exception:
            raise HTTPException(502, "stay_bookings_unavailable") from None

    @app.post("/api/booking/session")
    async def start(authorization: str | None = Header(default=None)):
        _require_operator(authorization)
        return sessions.create(
            app.state.stack["dispatcher"], operator_scope(authorization)
        )

    async def owned(request, authorization):
        _require_operator(authorization)
        body = await _body(request)
        session = sessions.acquire(
            body.get("session_id"), operator_scope(authorization)
        )
        return body, session

    @app.post("/api/booking/search")
    async def search(
        request: Request, authorization: str | None = Header(default=None)
    ):
        body, session = await owned(request, authorization)
        try:
            kind = _kind(body, session.tools)
            if kind == "table":
                _fields(
                    body,
                    {"session_id", "kind", "date", "start_time", "party_size"},
                    {"date", "start_time", "party_size"},
                )
                args = {
                    "date": _day(body["date"], future=True, max_days=90),
                    "start_time": body["start_time"],
                    "party_size": body["party_size"],
                }
                name = "search_tables"
            elif kind == "slot":
                _fields(
                    body,
                    {"session_id", "kind", "service", "provider", "date"},
                    {"service", "provider", "date"},
                )
                args = {
                    "service": body["service"],
                    "date": _day(body["date"], future=True, max_days=90),
                }
                args["provider"] = body["provider"]
                name = "search_slots"
            else:
                _fields(
                    body,
                    {
                        "session_id",
                        "kind",
                        "checkin",
                        "checkout",
                        "adults",
                        "children",
                        "room_type",
                    },
                    {"checkin", "checkout"},
                )
                args = {
                    "checkin": _day(body["checkin"], future=True),
                    "checkout": _day(body["checkout"], future=True),
                    "adults": body.get("adults", 2),
                    "children": body.get("children", 0),
                }
                if body.get("room_type"):
                    args["room_type"] = body["room_type"]
                name = "search_availability"
            session.tools.observe_user_text("Otsin uut broneeringut.", is_final=True)
            session.booking_recap_delivery = None
            return _result(await session.tools.dispatch(name, args))
        finally:
            sessions.release(session)

    @app.post("/api/booking/prepare")
    async def prepare(
        request: Request, authorization: str | None = Header(default=None)
    ):
        body, session = await owned(request, authorization)
        try:
            kind = _kind(body, session.tools)
            identifier = {
                "slot": "slot_id",
                "stay": "price_quote_id",
                "table": "table_offer_id",
            }[kind]
            _fields(
                body,
                {"session_id", "kind", identifier, "guest_fixture_id"},
                {identifier},
            )
            session.tools.observe_user_text(
                "Palun valmista valitud broneering ette.", is_final=True
            )
            session.booking_recap_delivery = None
            held = await session.tools.dispatch(
                {"slot": "hold_slot", "stay": "hold_offer", "table": "hold_table"}[
                    kind
                ],
                {identifier: body[identifier]},
            )
            if (
                not isinstance(held, dict)
                or held.get("error")
                or not held.get("hold_id")
            ):
                return _result(held)
            args = {
                "hold_id": held["hold_id"],
                "guest_fixture_id": body.get("guest_fixture_id", "guest-001"),
            }
            result = await session.tools.dispatch(
                {
                    "slot": "prepare_demo_booking",
                    "stay": "prepare_demo_stay",
                    "table": "prepare_demo_table",
                }[kind],
                args,
            )
            if isinstance(result, dict) and not result.get("error"):
                session.booking_recap_delivery = {
                    "id": uuid.uuid4().hex,
                    "pending": session.tools.pending,
                }
                result = {
                    **result,
                    "hold_id": held["hold_id"],
                    "recap_text": session.tools.render_recap(held["hold_id"]),
                    "kind": kind,
                    "recap_delivery_id": session.booking_recap_delivery["id"],
                }
            return _result(result)
        finally:
            sessions.release(session)

    @app.post("/api/booking/recap")
    async def recap(request: Request, authorization: str | None = Header(default=None)):
        body, session = await owned(request, authorization)
        try:
            _fields(
                body,
                {"session_id", "hold_id", "recap_delivery_id"},
                {"hold_id", "recap_delivery_id"},
            )
            identity = body["recap_delivery_id"]
            if not isinstance(identity, str) or not re.fullmatch(
                r"[a-f0-9]{32}", identity
            ):
                raise HTTPException(400, "booking_recap_receipt_invalid")
            receipt, session.booking_recap_delivery = (
                session.booking_recap_delivery,
                None,
            )
            if not (
                receipt
                and receipt["id"] == identity
                and receipt["pending"] is session.tools.pending
                and receipt["pending"] is not None
                and receipt["pending"]["hold_id"] == body["hold_id"]
                and session.tools.mark_recap_delivered(body["hold_id"])
            ):
                raise HTTPException(409, "booking_recap_expired_or_unknown")
            return {"acknowledged": True, "hold_id": body["hold_id"]}
        finally:
            sessions.release(session)

    async def mutate(request, authorization, *, cancel=False):
        body, session = await owned(request, authorization)
        try:
            kind = _kind(body, session.tools)
            identifier = "booking_id" if cancel else "hold_id"
            _fields(
                body,
                {"session_id", "kind", identifier, "consent"},
                {identifier, "consent"},
            )
            if body["consent"] is not True:
                raise HTTPException(400, "explicit_consent_required")
            # This endpoint is the explicit UI button, distinct from model tool
            # arguments. A separate recap acknowledgement precedes confirmation.
            session.tools.observe_user_text(
                "Jah, tühista." if cancel else "Jah, kinnitan.", is_final=True
            )
            if cancel and not session.tools.authorize_cancellation(body["booking_id"]):
                raise HTTPException(
                    409, "booking_not_owned_or_cancellation_unavailable"
                )
            name = (
                {
                    "slot": "cancel_slot_booking",
                    "stay": "cancel_booking",
                    "table": "cancel_table_booking",
                }
                if cancel
                else {
                    "slot": "confirm_slot_booking",
                    "stay": "confirm_booking",
                    "table": "confirm_table_booking",
                }
            )[kind]
            result = await session.tools.dispatch(name, {identifier: body[identifier]})
            if isinstance(result, dict):
                result = {**result, "kind": kind}
                if result.get("ok") is True and not result.get("error"):
                    _remember_booking(session, body, result, kind, cancel)
            return _result(result)
        finally:
            sessions.release(session)

    @app.post("/api/booking/confirm")
    async def confirm(
        request: Request, authorization: str | None = Header(default=None)
    ):
        return await mutate(request, authorization)

    @app.post("/api/booking/cancel")
    async def cancel(
        request: Request, authorization: str | None = Header(default=None)
    ):
        return await mutate(request, authorization, cancel=True)
