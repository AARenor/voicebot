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
from inspect import getattr_static
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from starlette.requests import Request
else:
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
    from .providers.demo_voices import DemoVoices
    from .providers.gemini import GeminiClient
    from .providers.groq import GroqClient
    from .providers.voice_config import SpeechConfig
    from .providers.speech_delivery import SpeechDelivery

    stack: dict = {
        "stt": None,
        "llm_primary": None,
        "llm_secondary": None,
        "tts": None,
        "voices": DemoVoices.from_env(),
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
        speech = SpeechConfig.from_env()
        stack["tts"] = AzureTtsClient(
            os.environ["AZURE_SPEECH_KEY"],
            os.environ["AZURE_REGION"],
            os.environ.get("AZURE_VOICE", "et-EE-AnuNeural"),
            os.environ.get("AZURE_LANG", "et-EE"),
            languages={lang: speech.voice_for(lang) for lang in ("et", "en", "ru")},
            delivery=SpeechDelivery.from_env(),
        )
    from .business import (
        business_type,
        restaurant_database,
        restaurant_dispatcher,
        restaurant_writes_enabled,
    )

    stack["business_type"] = business_type()
    if stack["business_type"] == "hotel_spa":
        # Stay priority: Apaleo (API-first) -> Mews (coverage) -> Cloudbeds.
        if os.environ.get("APALEO_CLIENT_ID") and os.environ.get(
            "APALEO_CLIENT_SECRET"
        ):
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
                        api_prefix=os.environ.get(
                            "EASY_API_PREFIX", "/index.php/api/v1"
                        ),
                        state_db=os.environ.get(
                            "EASY_STATE_DB", "/data/easy-booking.db"
                        ),
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
    if stack["business_type"] == "hotel_spa":
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
    if stack["business_type"] == "restaurant":
        from .booking.restaurant import RestaurantAdapter
        from .restaurant_data import load_restaurant_data

        data = load_restaurant_data()
        adapter = RestaurantAdapter(
            restaurant_database(), data=data, allow_writes=restaurant_writes_enabled()
        )
        stack.update(
            stay=None,
            slot=adapter if adapter.operational else None,
            booking_reader=adapter,
            restaurant_data=data,
            dispatcher=restaurant_dispatcher(adapter, data),
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
    producers = set()
    streams = set()

    @asynccontextmanager
    async def lifespan(app):
        yield
        # Disconnect never cancels a to_thread write/TTS. Drain ownership first.
        for stream in tuple(streams):
            stream.disconnect()
        if producers:
            await asyncio.gather(*producers, return_exceptions=True)
        sessions.clear()
        # Release provider sockets on shutdown/reload (no behavior change).
        seen = set()
        for key in (
            "stt",
            "llm_primary",
            "llm_secondary",
            "tts",
            "voices",
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
    app.state.turn_producers = producers
    app.state.turn_streams = streams

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
            (
                "/api/demo/",
                "/api/holds/",
                "/api/booking/",
                "/api/call-history",
                "/api/restaurant/",
            )
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
            stack.get("business_type", "hotel_spa")
            if stack.get("business_type") == "restaurant"
            else "easyappointments"
            if stack["booking_reader"] is not None
            else None
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
        from .providers.voice_config import SpeechConfig, VoiceConfig
        from .providers.speech_delivery import SpeechDelivery

        config = getattr(stack.get("llm_primary"), "config", VoiceConfig())
        speech = SpeechConfig.from_env()
        delivery = SpeechDelivery.from_env()
        return {
            "business_type": stack.get("business_type", "hotel_spa"),
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
                    "language": "auto",
                    "languages": ["et", "en", "ru"],
                },
                "llm": {"provider": "groq", "model": config.chat_model},
                "tts": {
                    "provider": "azure",
                    "voice": os.environ.get("AZURE_VOICE", "et-EE-AnuNeural"),
                },
            },
            "capabilities": app.state.capabilities,
            "telephone": {
                "language_mode": speech.mode,
                "supported_languages": ["et", "en", "ru"],
                "english_voice": speech.english_voice,
                "russian_voice": speech.voice_for("ru")[0],
                "speaking_style": delivery.mode,
                "speech_rate": delivery.rate,
                "recap_rate": delivery.recap_rate,
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

    @app.get("/api/demo/voices")
    def demo_voices(authorization: str | None = Header(default=None)):
        from .hackathon import voice_metadata

        dashboard_api._require_operator(authorization)
        stack = app.state.stack
        registry = stack.get("voices")
        rows = (
            registry.catalog(azure=stack["tts"])
            if registry is not None
            else [
                {
                    "id": "azure",
                    "label": "Azure",
                    "languages": ["et", "en", "ru"],
                    "configured": stack["tts"] is not None,
                    "available": stack["tts"] is not None,
                    "disabled_reason": (
                        None if stack["tts"] is not None else "not_configured"
                    ),
                    "streaming": voice_metadata(stack["tts"], "et")["streaming"],
                }
            ]
        )
        try:
            silence_ms = int(os.environ.get("VOICEBOT_MIC_SILENCE_MS", "650"))
        except ValueError:
            silence_ms = 650
        return {
            "voices": rows,
            "endpointing_ms": silence_ms if 300 <= silence_ms <= 2000 else 650,
        }

    @app.post("/api/turn")
    async def voice_turn(
        request: Request, authorization: str | None = Header(default=None)
    ):
        """Fictional HTTP turn. Optional session_id owns multi-turn state.

        Auth before providers; only text/audio, ET/EN/RU/auto language, voice,
        session_id and a next-input canonical recap delivery receipt pass.
        Without a session the call is isolated and cannot reuse another hold.
        Never retries a mutation automatically, never accepts browser history.
        """
        import time

        from .hackathon import (
            SESSION_TTL,
            DemoSession,
            choose_speaker,
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
            from .call_factory import make_call_tools

            # Check an explicit standalone profile before constructing call state.
            selected = choose_speaker(stack, body.get("voice", "azure"))
            session = DemoSession(
                operator_scope(authorization),
                make_call_tools(stack["dispatcher"]),
                time.monotonic() + SESSION_TTL,
                turn_count=1,
                voice_id=body.get("voice", "azure"),
            )
        recap_delivery_id = body.get("recap_delivery_id")
        try:
            if key is not None:
                selected = choose_speaker(stack, session.voice_id)
            if key is None:
                callslog.history_safe(
                    call_history.start,
                    session.tools.call_id,
                    "browser",
                    session.tools.language if language == "auto" else language,
                )
            if recap_delivery_id is not None:
                # Reject before a streamed response commits 200 headers, while
                # retaining the same one-use boundary before paid recognition.
                session.consume_recap_delivery(recap_delivery_id)
                recap_delivery_id = None
        except BaseException:
            if key is not None:
                sessions.release(session)
            raise

        streaming = any(
            part.split(";", 1)[0].strip().lower() == "application/x-ndjson"
            for part in request.headers.get("accept", "").split(",")
        )
        events = None
        if streaming:
            from .browser_audio import AudioEvents, StreamingSpeaker

            originating_turn = session.turn_count

            def invalidate_receipt():
                with sessions.lock:
                    if session.turn_count == originating_turn:
                        session.recap_delivery = None

            events = AudioEvents(invalidate_receipt)
            streams.add(events)
            selected = StreamingSpeaker(selected, events)

        async def produce():
            try:
                response = await run_demo_turn(
                    session,
                    stack,
                    audio,
                    text,
                    language,
                    recap_delivery_id=recap_delivery_id,
                    tts_override=selected,
                    emit=events.emit if events is not None else None,
                )
                response["session_id"] = key
                if key is None:
                    # Isolated turns have no reusable state to acknowledge next time.
                    response["recap_delivery_id"] = None
                    response["recap_expires_in_s"] = None
                response["call_id"] = session.tools.call_id
                try:
                    callslog.log_call(
                        callslog.get_default(),
                        response["language"],
                        "",
                        "HTTP voice turn",
                        response["outcome"],
                    )
                except Exception:
                    pass
            except Exception:
                if events is None:
                    raise
                session.recap_delivery = None
                response = {
                    "detail": "private_operation_failed",
                    "tts_failed": True,
                    "recap_delivery_id": None,
                    "audio_type": "audio/mpeg",
                    "session_id": key,
                    "call_id": session.tools.call_id,
                }
            finally:
                if events is not None and events.closed.is_set():
                    invalidate_receipt()
                if key is not None:
                    sessions.release(session)
                else:
                    callslog.history_safe(call_history.end, session.tools.call_id)
            if events is not None:
                await events.finish(response)
            return response

        if events is None:
            return await produce()
        producer = asyncio.create_task(produce())
        producers.add(producer)
        producer.add_done_callback(producers.discard)
        producer.add_done_callback(lambda _: streams.discard(events))
        return events.response()

    @app.post("/api/demo/session")
    async def start_demo_session(
        request: Request, authorization: str | None = Header(default=None)
    ):
        import base64
        from fastapi import HTTPException

        from .hackathon import (
            choose_speaker,
            operator_scope,
            read_session_settings,
            voice_metadata,
        )
        from .turn import _speak

        dashboard_api._require_operator(authorization)
        language, voice_id = await read_session_settings(request)
        stack = app.state.stack
        if stack["llm_primary"] is None or stack["tts"] is None:
            raise HTTPException(503, "voice_stack_not_configured")
        speaker = choose_speaker(stack, voice_id)
        data = sessions.create(
            stack["dispatcher"],
            operator_scope(authorization),
            language=language,
            voice_id=voice_id,
        )
        if callable(getattr_static(speaker, "for_language", None)):
            speaker = speaker.for_language(data["language"])
        try:
            audio = await asyncio.wait_for(_speak(speaker, data["greeting"]), 25)
        except TimeoutError:
            audio = b""
        data.update(
            audio_b64=base64.b64encode(audio).decode(),
            audio_type="audio/mpeg",
            tts_failed=not bool(audio),
            voice=voice_metadata(speaker, data["language"], voice_id),
        )
        return data

    @app.delete("/api/demo/session/{session_id}")
    def end_demo_session(
        session_id: str, authorization: str | None = Header(default=None)
    ):
        from .hackathon import operator_scope

        dashboard_api._require_operator(authorization)
        return sessions.end(session_id, operator_scope(authorization))

    if dashboard_api.router is not None:
        if stack.get("business_type") == "restaurant":
            from fastapi import APIRouter

            history_router = APIRouter()
            history_router.routes = [
                route
                for route in dashboard_api.router.routes
                if route.path.startswith(
                    ("/api/calls", "/api/call-history", "/api/metrics")
                )
            ]
            app.include_router(history_router)
        else:
            app.include_router(dashboard_api.router)

    from fastapi.responses import FileResponse, Response

    from .booking_web import add_booking_routes

    if stack.get("business_type") == "restaurant":
        from .restaurant_web import add_restaurant_routes

        add_restaurant_routes(app, sessions)
    else:
        add_booking_routes(app, sessions)
    hotel_dir = os.path.join(os.path.dirname(__file__), "hotel", "static")
    public_restaurant_dir = os.path.join(
        os.path.dirname(__file__), "restaurant", "public"
    )

    @app.get("/hotel", include_in_schema=False)
    @app.get("/hotel/", include_in_schema=False)
    def hotel_page(request: Request):
        if (request.url.hostname or "").lower().rstrip(".") == "robot.arleserver.cfd":
            return Response(
                status_code=410,
                headers={"Cache-Control": "no-store", "X-Robots-Tag": "noindex"},
            )
        return FileResponse(
            os.path.join(
                public_restaurant_dir
                if stack.get("business_type") == "restaurant"
                else hotel_dir,
                "index.html",
            ),
            media_type="text/html",
        )

    @app.get("/restaurant-public.js", include_in_schema=False)
    def public_restaurant_script():
        return FileResponse(
            os.path.join(public_restaurant_dir, "restaurant-public.js"),
            media_type="application/javascript",
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
    if stack.get("business_type") == "restaurant":
        # Keep local fonts available without any third-party browser requests.
        app.mount(
            "/fonts",
            StaticFiles(directory=os.path.join(static_dir, "fonts")),
            name="fonts",
        )
        static_dir = os.path.join(os.path.dirname(__file__), "restaurant", "static")
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
