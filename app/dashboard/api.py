"""Dashboard JSON API (FastAPI router).

Synthetic reads are open; call history is operator-only. Mutations (confirm/cancel)
require OPERATOR_TOKEN as `Authorization: Bearer <token>`; without a
configured token they fail closed with 503.
"""

from __future__ import annotations

import hmac
import os
import threading
import time
from typing import Literal

from . import demo

try:
    from fastapi import APIRouter, Header, HTTPException
    from pydantic import BaseModel

    class BookingRow(BaseModel):
        id: int
        start_local: str
        end_local: str
        timezone: str | None
        time_state: Literal["valid", "ambiguous", "invalid", "unknown_timezone"]
        provider_id: int
        provider_name: str
        service_id: int
        service_name: str
        status: str

    class BookingPage(BaseModel):
        source: Literal["easyappointments", "restaurant"]
        data_mode: Literal["synthetic"]
        fetched_at: str
        date: str
        page: int
        length: int
        has_more: Literal[False, "unknown"]
        items: list[BookingRow]

    class CallBooking(BaseModel):
        id: str
        kind: Literal["slot", "stay"] = "slot"
        action: Literal["confirmed", "cancelled"]
        date: str
        start_local: str
        timezone: Literal["Europe/Tallinn"]
        checkout: str | None = None

    class CallSession(BaseModel):
        id: str
        started_at: str
        updated_at: str
        ended_at: str | None
        channel: Literal["browser", "telephone"]
        language: str
        status: Literal["active", "ended", "expired"]
        outcome: str
        turns: int
        recognized_turns: int
        typed_turns: int
        empty_turns: int
        stt_errors: int
        tts_errors: int
        provider_errors: int
        vad_events: int
        duration_s: int
        bookings: list[CallBooking]
        needs_attention: bool
        data_mode: Literal["synthetic"]

    class CallSummary(BaseModel):
        total: int
        active: int
        with_booking: int
        needs_attention: int

    class CallHistoryPage(BaseModel):
        items: list[CallSession]
        page: int
        length: int
        has_more: bool
        summary: CallSummary
        fetched_at: str
        data_mode: Literal["synthetic"]

    class CallEvent(BaseModel):
        id: int
        at: str
        kind: str
        outcome: str

    class CallHistoryDetail(BaseModel):
        session: CallSession
        events: list[CallEvent]

    router = APIRouter(prefix="/api")
    _LOCK = threading.Lock()  # demo single-worker guard (see COOLIFY notes)
    _DEMO_MODE = True
    _COMMANDS_READY = False

    def configure_mode(*, demo: bool, commands_ready: bool) -> None:
        """Server-owned capability gate for dashboard mutations."""
        global _DEMO_MODE, _COMMANDS_READY
        with _LOCK:
            _DEMO_MODE = bool(demo)
            _COMMANDS_READY = bool(commands_ready)

    def _require_command_service() -> None:
        # Demo actions may mutate the explicit demo store. Outside demo, never
        # imply a PMS write until a real command service is injected.
        if not _DEMO_MODE and not _COMMANDS_READY:
            raise HTTPException(503, "operator hold commands not configured")

    def _require_operator(authorization: str | None) -> None:
        expected = os.environ.get("OPERATOR_TOKEN", "").strip()
        if not expected:
            raise HTTPException(503, "operator token not configured")
        provided = authorization or ""
        # Bytes compare: never raises on non-ASCII header input (latin-1).
        if not hmac.compare_digest(
            provided.encode("utf-8"), f"Bearer {expected}".encode("utf-8")
        ):
            raise HTTPException(403, "forbidden")

    @router.get("/holds")
    def list_holds() -> dict:
        now = time.time()
        with _LOCK:
            rows = list(demo.STORE["holds"])
        holds = []
        for hold in rows:
            holds.append(
                {**hold, "expires_in_s": max(0, int(hold["expires_at"] - now))}
            )
        return {"holds": holds}

    def _pending_or_raise(hold_id: str) -> dict:
        """Pending, unexpired hold or HTTP error (410 when stale).

        Callers must hold _LOCK (check + status flip are one atomic
        section in confirm/cancel).
        """
        for hold in demo.STORE["holds"]:
            if hold["hold_id"] == hold_id and hold["status"] == "pending":
                if hold["expires_at"] < time.time():
                    raise HTTPException(410, "hold expired")
                return hold
        raise HTTPException(404, "hold not found or not pending")

    @router.post("/holds/{hold_id}/confirm")
    def confirm_hold(
        hold_id: str, authorization: str | None = Header(default=None)
    ) -> dict:
        _require_operator(authorization)
        _require_command_service()
        with _LOCK:
            hold = _pending_or_raise(hold_id)
            hold["status"] = "confirmed"
            return {"ok": True, "hold_id": hold_id, "status": "confirmed"}

    @router.post("/holds/{hold_id}/cancel")
    def cancel_hold(
        hold_id: str, authorization: str | None = Header(default=None)
    ) -> dict:
        _require_operator(authorization)
        _require_command_service()
        with _LOCK:
            hold = _pending_or_raise(hold_id)
            hold["status"] = "cancelled"
            return {"ok": True, "hold_id": hold_id, "status": "cancelled"}

    @router.post("/reset")
    def reset_demo(authorization: str | None = Header(default=None)) -> dict:
        _require_operator(authorization)
        with _LOCK:
            demo.reset()
        return {"ok": True}

    @router.get("/calls")
    def list_calls(authorization: str | None = Header(default=None)) -> dict:
        from .. import callslog

        _require_operator(authorization)
        return {"calls": callslog.list_calls(callslog.get_default())}

    @router.get("/call-history", response_model=CallHistoryPage)
    def call_history(
        page: str = "1",
        length: str = "20",
        channel: str = "all",
        result: str = "all",
        authorization: str | None = Header(default=None),
    ):
        from .. import call_history, callslog

        _require_operator(authorization)
        try:
            if not all(
                value.isascii() and value.isdecimal() for value in (page, length)
            ):
                raise ValueError()
            return call_history.list_sessions(
                callslog.get_default(),
                page=int(page),
                length=int(length),
                channel=channel,
                result=result,
            )
        except ValueError:
            raise HTTPException(400, "call_history_query_invalid") from None

    @router.get("/call-history/{call_id}", response_model=CallHistoryDetail)
    def call_history_detail(
        call_id: str, authorization: str | None = Header(default=None)
    ):
        from .. import call_history, callslog

        _require_operator(authorization)
        try:
            item = call_history.detail(callslog.get_default(), call_id)
        except ValueError:
            item = None
        if item is None:
            raise HTTPException(404, "call_history_unknown")
        return item

    @router.get("/config")
    def get_config() -> dict:
        return {"config": demo.STORE["config"]}

    @router.get("/metrics")
    def get_metrics() -> dict:
        return {"metrics": demo.STORE["metrics"]}

except ImportError:  # fastapi not installed (unit-test envs)
    router = None
