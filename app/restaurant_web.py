"""Restaurant web controls; authorization and shared consent precede writes."""

from __future__ import annotations

import copy

from fastapi import Header, HTTPException, Request

from .booking_web import _body, _fields, _remember_booking, _result
from .dashboard.api import _require_operator
from .hackathon import operator_scope, read_session_language
from .languages import CONSENT

CANCEL = {"et": "Jah, tühista.", "en": "Yes, cancel.", "ru": "Да, отмените."}


def add_restaurant_routes(app, sessions):
    @app.get("/api/public/restaurant")
    @app.get("/api/public/property")
    async def restaurant_information():
        data = copy.deepcopy(app.state.stack["restaurant_data"])
        return {
            "synthetic": True,
            "business_type": "restaurant",
            "restaurant": data,
            "supported_languages": ["et", "en", "ru"],
            "table_booking_ready": app.state.capabilities["slot_booking_ready"],
            "booking_access": "operator_demo",
            "allergy_safety_verified": False,
        }

    @app.get("/api/public/catalogue")
    async def menu():
        data = app.state.stack["restaurant_data"]
        return {
            "synthetic": True,
            "business_type": "restaurant",
            "menu": copy.deepcopy(data["menu"]),
        }

    @app.post("/api/booking/session")
    async def start(request: Request, authorization: str | None = Header(default=None)):
        _require_operator(authorization)
        language = await read_session_language(request)
        return sessions.create(
            app.state.stack["dispatcher"],
            operator_scope(authorization),
            language=language,
        )

    async def owned(request, authorization):
        _require_operator(authorization)
        body = await _body(request)
        return body, sessions.acquire(
            body.get("session_id"), operator_scope(authorization)
        )

    @app.post("/api/restaurant/reservation/prepare")
    async def prepare(
        request: Request, authorization: str | None = Header(default=None)
    ):
        body, session = await owned(request, authorization)
        try:
            _fields(
                body,
                {"session_id", "date", "start_time", "party_size", "guest_fixture_id"},
                {"date", "start_time", "party_size"},
            )
            session.tools.observe_user_text(
                "Prepare this restaurant table reservation.",
                language=session.tools.language,
            )
            result = await session.tools.dispatch(
                "plan_restaurant_reservation",
                {
                    key: body[key]
                    for key in ("date", "start_time", "party_size", "guest_fixture_id")
                    if key in body
                },
            )
            if isinstance(result, dict) and result.get("ok") is True:
                result = {
                    **result,
                    "recap_text": session.tools.render_recap(),
                    "kind": "slot",
                    "business_type": "restaurant",
                }
            return _result(result)
        finally:
            sessions.release(session)

    @app.post("/api/booking/recap")
    async def recap(request: Request, authorization: str | None = Header(default=None)):
        body, session = await owned(request, authorization)
        try:
            _fields(body, {"session_id", "hold_id"}, {"hold_id"})
            if not session.tools.mark_recap_delivered(body["hold_id"]):
                raise HTTPException(409, "booking_recap_expired_or_unknown")
            return {"acknowledged": True, "hold_id": body["hold_id"]}
        finally:
            sessions.release(session)

    async def mutate(request, authorization, *, cancel=False):
        body, session = await owned(request, authorization)
        try:
            identifier = "booking_id" if cancel else "hold_id"
            _fields(
                body, {"session_id", identifier, "consent"}, {identifier, "consent"}
            )
            if body["consent"] is not True:
                raise HTTPException(400, "explicit_consent_required")
            language = session.tools.language
            session.tools.observe_user_text(
                CANCEL[language] if cancel else CONSENT[language], language=language
            )
            if cancel and not session.tools.authorize_cancellation(body[identifier]):
                raise HTTPException(
                    409, "booking_not_owned_or_cancellation_unavailable"
                )
            result = await session.tools.dispatch(
                "cancel_slot_booking" if cancel else "confirm_slot_booking",
                {identifier: body[identifier]},
            )
            if (
                isinstance(result, dict)
                and result.get("ok") is True
                and not result.get("error")
            ):
                _remember_booking(session, body, result, "slot", cancel)
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
