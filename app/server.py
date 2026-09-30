"""Call server: browser WebSocket now, SIP webhook later (Phase 2).

Also serves the operator dashboard (static UI + /api/*) when fastapi is
installed. Without fastapi the module still imports (create_app raises
a clear error only when called).
"""

from __future__ import annotations

import os


def create_app():
    """FastAPI app factory (import fastapi lazily; keeps checks light)."""
    from fastapi import FastAPI
    from fastapi.staticfiles import StaticFiles

    from .dashboard import api as dashboard_api

    app = FastAPI(title="voicebot-et")

    @app.get("/health")
    def health() -> dict:
        return {"ok": True}

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
