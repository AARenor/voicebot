"""Call server: dashboard + HTTP voice turn today, SIP webhook Phase 2.

Serves the operator dashboard (static UI + /api/*) and POST /api/turn
(full voice turn over HTTP: audio in, reply audio out) when fastapi is
installed. Providers/adapters are built from environment; anything
unconfigured stays absent, is reported (without secrets) on /api/status,
and voice turns fail closed with 503 demo-gate. Without fastapi the
module still imports (create_app raises a clear error only when called).
Single-worker assumption: in-memory HoldLedger + demo STORE diverge if
replicas scale past 1 — do not scale Coolify replicas (see COOLIFY.md).
"""

from __future__ import annotations

import asyncio
import os
import sqlite3

try:
    from starlette.requests import Request
except ImportError:  # keep provider-only installations importable
    Request = None


def build_stack() -> dict:
    """Construct providers/adapters from env. Never logs or returns keys."""
    from .booking.apaleo import ApaleoAdapter
    from .booking.cloudbeds import CloudbedsAdapter
    from .booking.easyappointments import EasyAppointmentsAdapter
    from .booking.mews import MewsAdapter
    from .providers.azure_tts import AzureTtsClient
    from .providers.gemini import GeminiClient
    from .providers.groq import GroqClient

    stack: dict = {
        "stt": None,
        "llm_primary": None,
        "llm_secondary": None,
        "tts": None,
        "stay": None,
        "slot": None,
        "booking_reader": None,
        "livekit": None,
        "faq_db": None,
    }
    if os.environ.get("GROQ_API_KEY"):
        stack["stt"] = GroqClient(os.environ["GROQ_API_KEY"])
        stack["llm_primary"] = stack["stt"]
    if os.environ.get("GEMINI_API_KEY"):
        # Text-only secondary: failover answers, never function-calls.
        stack["llm_secondary"] = GeminiClient(os.environ["GEMINI_API_KEY"])
    if os.environ.get("AZURE_SPEECH_KEY") and os.environ.get("AZURE_REGION"):
        stack["tts"] = AzureTtsClient(
            os.environ["AZURE_SPEECH_KEY"],
            os.environ["AZURE_REGION"],
            os.environ.get("AZURE_VOICE", "et-EE-AnuNeural"),
            os.environ.get("AZURE_LANG", "et-EE"),
        )
    # Stay priority: Apaleo (API-first) -> Mews (coverage) -> Cloudbeds.
    if os.environ.get("APALEO_CLIENT_ID") and os.environ.get("APALEO_CLIENT_SECRET"):
        stack["stay"] = ApaleoAdapter(
            os.environ["APALEO_CLIENT_ID"], os.environ["APALEO_CLIENT_SECRET"]
        )
    elif all(
        os.environ.get(k)
        for k in (
            "MEWS_CLIENT_TOKEN",
            "MEWS_ACCESS_TOKEN",
            "MEWS_CLIENT",
            "MEWS_API_BASE_URL",
        )
    ):
        stack["stay"] = MewsAdapter(
            os.environ["MEWS_CLIENT_TOKEN"],
            os.environ["MEWS_ACCESS_TOKEN"],
            os.environ["MEWS_CLIENT"],
            os.environ["MEWS_API_BASE_URL"],
        )
    elif os.environ.get("CLOUDBEDS_API_KEY"):
        stack["stay"] = CloudbedsAdapter(os.environ["CLOUDBEDS_API_KEY"])
    if os.environ.get("EASY_BASE_URL") and os.environ.get("EASY_API_KEY"):
        read_options = {
            "auth_scheme": os.environ.get("EASY_AUTH_SCHEME", "Bearer "),
            "api_prefix": os.environ.get("EASY_API_PREFIX", "/index.php/api/v1"),
        }
        stack["booking_reader"] = EasyAppointmentsAdapter(
            os.environ["EASY_BASE_URL"],
            os.environ["EASY_API_KEY"],
            **read_options,
        )
        # Sole-writer demo gate: credentials alone never advertise booking
        # tools. Explicit opt-in plus a persistent journal are required
        # (upstream 1.6.0 creation does not reject overlaps).
        if os.environ.get("EASY_DEMO_WRITES") == "1":
            try:
                stack["slot"] = EasyAppointmentsAdapter(
                    os.environ["EASY_BASE_URL"],
                    os.environ["EASY_API_KEY"],
                    auth_scheme=os.environ.get("EASY_AUTH_SCHEME", "Bearer "),
                    api_prefix=os.environ.get("EASY_API_PREFIX", "/index.php/api/v1"),
                    state_db=os.environ.get("EASY_STATE_DB", "/data/easy-booking.db"),
                    allow_writes=True,
                )
            except Exception:
                # Journal unwritable: stay unwired, never half-operational.
                stack["slot"] = None
    if all(
        os.environ.get(k)
        for k in ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET")
    ):
        # Self-hosted media plane (livekit:7880 on the coolify network).
        # Reachability is verified at deploy; status only reports config.
        stack["livekit"] = {
            "url": os.environ["LIVEKIT_URL"],
            "api_key": os.environ["LIVEKIT_API_KEY"],
        }
    if stack["slot"] is None and os.environ.get("ZENOTI_API_KEY"):
        # Independent fallback: media plane (LiveKit) and spa PMS are
        # orthogonal — Zenoti must survive LiveKit being configured.
        from .booking.zenoti import ZenotiAdapter

        stack["slot"] = ZenotiAdapter(os.environ["ZENOTI_API_KEY"])
    if (
        stack["stay"] is None
        and os.environ.get("STAY_DEMO_WRITES", os.environ.get("EASY_DEMO_WRITES"))
        == "1"
    ):
        from .booking.demo_stay import DemoStayAdapter

        # Keep room inventory beside the existing persistent booking journal.
        # This is explicitly fictional inventory, never a live hotel PMS.
        state_dir = os.path.dirname(
            os.environ.get("EASY_STATE_DB", "/data/easy-booking.db")
        )
        try:
            stack["stay"] = DemoStayAdapter(
                os.environ.get("STAY_STATE_DB")
                or os.path.join(state_dir, "stay-booking.db")
            )
        except (OSError, ValueError, sqlite3.Error):
            stack["stay"] = None
    from .booking.tools import Dispatcher

    # The HTTP demo uses the approved fictional profile through CallTools.
    # Never seed or expose generic real-hotel FAQ promises here.
    stack["dispatcher"] = Dispatcher(
        stay=stack["stay"],
        slot=stack["slot"],
    )
    stack["demo"] = stack["stt"] is None
    return stack


def create_app():
    """FastAPI app factory (import fastapi lazily; keeps checks light)."""
    from contextlib import asynccontextmanager

    from fastapi import FastAPI, Header
    from fastapi.staticfiles import StaticFiles

    from .dashboard import api as dashboard_api
    from .hackathon import DemoSessions

    stack = build_stack()
    sessions = DemoSessions()

    @asynccontextmanager
    async def lifespan(app):
        yield
        sessions.clear()
        # Release provider sockets on shutdown/reload (no behavior change).
        seen = set()
        for key in (
            "stt",
            "llm_primary",
            "llm_secondary",
            "tts",
            "slot",
            "stay",
            "booking_reader",
        ):
            client = stack.get(key)
            if client is None or id(client) in seen:
                continue
            seen.add(id(client))
            close = getattr(client, "close", None)
            if not callable(close):
                continue
            try:
                result = close()
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                pass
        try:
            stack["faq_db"].close()
        except Exception:
            pass

    app = FastAPI(title="voicebot-et", lifespan=lifespan)
    app.state.stack = stack
    app.state.demo_sessions = sessions

    @app.middleware("http")
    async def private_responses(request, call_next):
        private = request.url.path in (
            "/api/calls",
            "/api/turn",
            "/api/bookings",
            "/api/catalogue",
            "/api/reset",
            "/api/rooms",
            "/api/stays",
        ) or request.url.path.startswith(
            ("/api/demo/", "/api/holds/", "/api/booking/", "/api/call-history")
        )
        try:
            response = await call_next(request)
        except Exception:
            if not private:
                raise
            from fastapi.responses import JSONResponse

            return JSONResponse(
                {"detail": "private_operation_failed"},
                status_code=500,
                headers={"Cache-Control": "no-store"},
            )
        if private:
            response.headers["Cache-Control"] = "no-store"
        return response

    advertised = {
        tool["function"]["name"] for tool in stack["dispatcher"].available_tools()
    }
    capabilities = {
        "text_turn_ready": stack["llm_primary"] is not None
        and stack["tts"] is not None,
        "audio_turn_ready": stack["stt"] is not None
        and stack["llm_primary"] is not None
        and stack["tts"] is not None,
        "stay_booking_ready": "search_availability" in advertised,
        "slot_booking_ready": "search_slots" in advertised,
        "booking_read_ready": stack["booking_reader"] is not None,
        "booking_view_source": (
            "easyappointments" if stack["booking_reader"] is not None else None
        ),
        # Dashboard queue is still explicit demo state; never claim a PMS write.
        "operator_hold_commands_ready": False,
        "serving_demo_data": True,
    }
    # Injection point for Phase 2: a real operator command service flips
    # operator_hold_commands_ready and serving_demo_data together.
    app.state.capabilities = capabilities
    dashboard_api.configure_mode(
        demo=stack["demo"],
        commands_ready=capabilities["operator_hold_commands_ready"],
    )
    if app.state.stack["demo"]:
        # Demo mode only: seed sample calls so the UI is alive before
        # the first real call. Production file DBs are never seeded.
        from . import callslog

        callslog.seed_demo(callslog.get_default())

    @app.get("/health")
    def health() -> dict:
        return {"ok": True}

    @app.get("/api/status")
    def status() -> dict:
        stack = app.state.stack
        from .providers.voice_config import VoiceConfig

        config = getattr(stack.get("llm_primary"), "config", VoiceConfig())
        return {
            "wired": {
                name: stack[name] is not None
                for name in (
                    "stt",
                    "llm_primary",
                    "llm_secondary",
                    "tts",
                    "stay",
                    "slot",
                    "livekit",
                )
            },
            "demo": stack["demo"],
            "models": {
                "stt": {
                    "provider": "groq",
                    "model": config.stt_model,
                    "language": "et",
                },
                "llm": {"provider": "groq", "model": config.chat_model},
                "tts": {
                    "provider": "azure",
                    "voice": os.environ.get("AZURE_VOICE", "et-EE-AnuNeural"),
                },
            },
            "capabilities": app.state.capabilities,
            "telephone": {
                "media_credentials_configured": stack["livekit"] is not None,
                "worker_health_probe": "separate_private_endpoint",
                "public_ingress_verified": False,
                "carrier_call_verified": False,
                "release_scope": "synthetic_private_pilot",
            },
        }

    def reader_or_raise(authorization):
        from fastapi import HTTPException

        dashboard_api._require_operator(authorization)
        reader = app.state.stack.get("booking_reader")
        if reader is None:
            raise HTTPException(503, "booking_reader_not_configured")
        return reader

    async def private_read(operation):
        from fastapi import HTTPException

        from .booking.easyappointments import BookingReadError

        try:
            return await operation
        except BookingReadError as exc:
            headers = {"Retry-After": str(exc.retry_after)} if exc.retry_after else None
            raise HTTPException(exc.status, exc.code, headers=headers) from None
        except Exception:
            raise HTTPException(502, "booking_payload_invalid") from None

    @app.get("/api/bookings", response_model=dashboard_api.BookingPage)
    async def bookings(
        date: str | None = None,
        page: str = "1",
        length: str = "50",
        authorization: str | None = Header(default=None),
    ):
        from datetime import date as calendar_date
        from datetime import datetime
        from zoneinfo import ZoneInfo

        from fastapi import HTTPException

        reader = reader_or_raise(authorization)
        today = datetime.now(ZoneInfo("Europe/Tallinn")).date()
        day = date if date is not None else today.isoformat()
        try:
            parsed = calendar_date.fromisoformat(day)
            if parsed.isoformat() != day or not -31 <= (parsed - today).days <= 90:
                raise ValueError()
            if (
                not page.isascii()
                or not page.isdecimal()
                or not length.isascii()
                or not length.isdecimal()
            ):
                raise ValueError()
            number, size = int(page), int(length)
            if not 1 <= number <= 100 or not 1 <= size <= 50:
                raise ValueError()
        except (ValueError, TypeError):
            raise HTTPException(400, "booking_query_invalid") from None
        return await private_read(
            reader.get_operator_bookings(day, page=number, length=size)
        )

    @app.get("/api/catalogue")
    async def catalogue(authorization: str | None = Header(default=None)):
        reader = reader_or_raise(authorization)
        return await private_read(reader.get_operator_catalogue())

    @app.post("/api/turn")
    async def voice_turn(
        request: Request, authorization: str | None = Header(default=None)
    ) -> dict:
        """Fictional HTTP turn. Optional session_id owns multi-turn state.

        Auth before providers; only text/audio, language and session_id pass.
        Without a session the call is isolated and cannot reuse another hold.
        Never retries a mutation automatically, never accepts browser history.
        """
        import time

        from .hackathon import (
            SESSION_TTL,
            DemoSession,
            operator_scope,
            read_turn_body,
            run_demo_turn,
            validate_input,
        )
        from . import callslog, call_history

        dashboard_api._require_operator(authorization)
        body = await read_turn_body(request)
        stack = app.state.stack
        audio, text, language = validate_input(body, stack)
        key = body.get("session_id")
        if key is not None:
            session = sessions.acquire(key, operator_scope(authorization))
        else:
            from .telephone import CallTools

            session = DemoSession(
                operator_scope(authorization),
                CallTools(stack["dispatcher"]),
                time.monotonic() + SESSION_TTL,
                turn_count=1,
            )
        try:
            if key is None:
                callslog.history_safe(
                    call_history.start, session.tools.call_id, "browser", language
                )
            response = await run_demo_turn(session, stack, audio, text, language)
        finally:
            if key is not None:
                sessions.release(session)
            else:
                callslog.history_safe(call_history.end, session.tools.call_id)
        response["session_id"] = key
        response["call_id"] = session.tools.call_id
        try:
            callslog.log_call(
                callslog.get_default(),
                language,
                "",
                "HTTP voice turn",
                response["outcome"],
            )
        except Exception:
            pass
        return response

    @app.post("/api/demo/session")
    async def start_demo_session(authorization: str | None = Header(default=None)):
        from fastapi import HTTPException

        from .hackathon import operator_scope

        dashboard_api._require_operator(authorization)
        stack = app.state.stack
        if stack["llm_primary"] is None or stack["tts"] is None:
            raise HTTPException(503, "voice_stack_not_configured")
        return sessions.create(stack["dispatcher"], operator_scope(authorization))

    @app.delete("/api/demo/session/{session_id}")
    def end_demo_session(
        session_id: str, authorization: str | None = Header(default=None)
    ):
        from .hackathon import operator_scope

        dashboard_api._require_operator(authorization)
        return sessions.end(session_id, operator_scope(authorization))

    if dashboard_api.router is not None:
        app.include_router(dashboard_api.router)

    from fastapi.responses import FileResponse, Response

    from .booking_web import add_booking_routes

    add_booking_routes(app, sessions)
    hotel_dir = os.path.join(os.path.dirname(__file__), "hotel", "static")

    @app.get("/hotel", include_in_schema=False)
    @app.get("/hotel/", include_in_schema=False)
    def hotel_page(request: Request):
        if (request.url.hostname or "").lower().rstrip(".") == "robot.arleserver.cfd":
            return Response(
                status_code=410,
                headers={"Cache-Control": "no-store", "X-Robots-Tag": "noindex"},
            )
        return FileResponse(
            os.path.join(hotel_dir, "index.html"), media_type="text/html"
        )

    @app.get("/hotel.css", include_in_schema=False)
    def hotel_css():
        return FileResponse(os.path.join(hotel_dir, "hotel.css"), media_type="text/css")

    @app.get("/hotel.js", include_in_schema=False)
    def hotel_js():
        return FileResponse(
            os.path.join(hotel_dir, "hotel.js"), media_type="application/javascript"
        )

    @app.get("/hotel/coastal-hotel.svg", include_in_schema=False)
    def hotel_illustration():
        return FileResponse(
            os.path.join(hotel_dir, "coastal-hotel.svg"), media_type="image/svg+xml"
        )

    static_dir = os.path.join(os.path.dirname(__file__), "dashboard", "static")
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="dashboard")
    return app


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.server:create_app",
        factory=True,
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8000")),
    )
