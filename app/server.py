"""Call server: browser WebSocket now, SIP webhook later (Phase 2).

Also serves the operator dashboard (static UI + /api/*) when fastapi is
installed. Providers/adapters are built from environment; anything
unconfigured stays absent and is reported (without secrets) on
/api/status. Without fastapi the module still imports (create_app raises
a clear error only when called).
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
    stack["demo"] = stack["stt"] is None
    return stack


def create_app():
    """FastAPI app factory (import fastapi lazily; keeps checks light)."""
    from fastapi import FastAPI
    from fastapi.staticfiles import StaticFiles

    from .dashboard import api as dashboard_api

    app = FastAPI(title="voicebot-et")
    app.state.stack = build_stack()

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
                    "tts",
                    "stay",
                    "slot",
                    "livekit",
                )
            },
            "demo": stack["demo"],
        }

    if dashboard_api.router is not None:
        app.include_router(dashboard_api.router)

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
