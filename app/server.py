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

import os


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
        "livekit": None,
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
        stack["slot"] = EasyAppointmentsAdapter(
            os.environ["EASY_BASE_URL"], os.environ["EASY_API_KEY"]
        )
    if os.environ.get("LIVEKIT_URL") and os.environ.get("LIVEKIT_API_KEY"):
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
    from .booking.tools import Dispatcher
    from .knowledge import open_db, retrieve
    from .knowledge.seed import seed as seed_faq

    faq_db = open_db()
    seed_faq(faq_db)
    stack["dispatcher"] = Dispatcher(
        stay=stack["stay"],
        slot=stack["slot"],
        faq=lambda question: retrieve(faq_db, question, lang="et"),
    )
    stack["demo"] = stack["stt"] is None
    return stack


def create_app():
    """FastAPI app factory (import fastapi lazily; keeps checks light)."""
    from fastapi import FastAPI, Header
    from fastapi.staticfiles import StaticFiles

    from .dashboard import api as dashboard_api

    app = FastAPI(title="voicebot-et")
    app.state.stack = build_stack()
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
        }

    @app.post("/api/turn")
    def voice_turn(
        body: dict, authorization: str | None = Header(default=None)
    ) -> dict:
        """Full voice turn over HTTP (Phase 1 voice path, demo-gated).

        Auth: operator token required (paid providers behind this
        endpoint). Body: {audio_b64?: str, text?: str, language?: et|en|ru}.
        Caps: text ≤500 chars, audio_b64 ≤700k chars (~500KB decoded).
        Requires stt (or text), llm_primary and tts — else 503.
        """
        import base64

        from fastapi import HTTPException  # noqa: F811 (already imported)

        from .turn import run_turn

        from .dashboard import api as dashboard_api

        dashboard_api._require_operator(authorization)
        stack = app.state.stack
        language = body.get("language", "et")
        if language not in ("et", "en", "ru"):
            language = "et"
        audio_b64 = body.get("audio_b64", "")
        text = body.get("text", "")
        if not isinstance(audio_b64, str) or len(audio_b64) > 700_000:
            raise HTTPException(413, "audio_b64 too large")
        if not isinstance(text, str) or len(text) > 500:
            raise HTTPException(413, "text too large")
        if audio_b64:
            if stack["stt"] is None:
                raise HTTPException(503, "stt not configured (demo mode)")
            try:
                audio = base64.b64decode(audio_b64, validate=True)
            except Exception:
                raise HTTPException(400, "bad audio_b64") from None
            if len(audio) > 524_288:
                raise HTTPException(413, "audio too large")
        elif text.strip():
            audio = b""
        else:
            raise HTTPException(400, "audio_b64 or text required")
        if stack["llm_primary"] is None or stack["tts"] is None:
            raise HTTPException(503, "voice stack not configured (demo mode)")
        stt = stack["stt"] if audio_b64 else None
        result = _run_async(
            run_turn(
                audio,
                stt,
                stack["llm_primary"],
                stack["tts"],
                stack["dispatcher"],
                llm_secondary=stack["llm_secondary"],
                language=language,
                text=text if not audio_b64 else None,
            )
        )
        return {
            "text_heard": result["text_heard"],
            "reply": result["reply"],
            "audio_b64": base64.b64encode(result["audio"]).decode(),
            "tools_used": len(result["tool_results"]),
            "fallback_used": result["fallback_used"],
            "tts_failed": result.get("tts_failed", False),
        }

    if dashboard_api.router is not None:
        app.include_router(dashboard_api.router)

    static_dir = os.path.join(os.path.dirname(__file__), "dashboard", "static")
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="dashboard")
    return app


def _run_async(coro):
    """Run one coroutine synchronously (voice turn inside sync route)."""
    import asyncio

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop is not None:
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result()
    return asyncio.run(coro)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.server:create_app",
        factory=True,
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8000")),
    )
