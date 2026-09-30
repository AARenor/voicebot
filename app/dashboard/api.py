"""Dashboard JSON API (FastAPI router).

Read endpoints are open (demo data). Mutating endpoints (confirm/cancel)
require OPERATOR_TOKEN as `Authorization: Bearer <token>`; without a
configured token they fail closed with 503.
"""

from __future__ import annotations

import hmac
import os
import threading
import time

from . import demo

try:
    from fastapi import APIRouter, Header, HTTPException

    router = APIRouter(prefix="/api")
    _LOCK = threading.Lock()  # demo single-worker guard (see COOLIFY notes)

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
        holds = []
        for hold in demo.STORE["holds"]:
            holds.append(
                {**hold, "expires_in_s": max(0, int(hold["expires_at"] - now))}
            )
        return {"holds": holds}

    @router.post("/holds/{hold_id}/confirm")
    def confirm_hold(
        hold_id: str, authorization: str | None = Header(default=None)
    ) -> dict:
        _require_operator(authorization)
        with _LOCK:
            for hold in demo.STORE["holds"]:
                if hold["hold_id"] == hold_id and hold["status"] == "pending":
                    hold["status"] = "confirmed"
                    return {"ok": True, "hold_id": hold_id, "status": "confirmed"}
        raise HTTPException(404, "hold not found or not pending")

    @router.post("/holds/{hold_id}/cancel")
    def cancel_hold(
        hold_id: str, authorization: str | None = Header(default=None)
    ) -> dict:
        _require_operator(authorization)
        with _LOCK:
            for hold in demo.STORE["holds"]:
                if hold["hold_id"] == hold_id and hold["status"] == "pending":
                    hold["status"] = "cancelled"
                    return {"ok": True, "hold_id": hold_id, "status": "cancelled"}
        raise HTTPException(404, "hold not found or not pending")

    @router.post("/reset")
    def reset_demo(authorization: str | None = Header(default=None)) -> dict:
        _require_operator(authorization)
        with _LOCK:
            demo.reset()
        return {"ok": True}

    @router.get("/calls")
    def list_calls() -> dict:
        return {"calls": demo.STORE["calls"]}

    @router.get("/config")
    def get_config() -> dict:
        return {"config": demo.STORE["config"]}

    @router.get("/metrics")
    def get_metrics() -> dict:
        return {"metrics": demo.STORE["metrics"]}

except ImportError:  # fastapi not installed (unit-test envs)
    router = None
