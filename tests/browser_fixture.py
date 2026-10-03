"""Local browser integration app with the real routes and fictional providers.

Run with: uvicorn tests.browser_fixture:create_app --factory --port 8765
The token is a public test fixture, not a deployment credential. No external
provider is contacted. The committed MP3 test tone is synthetic audio.
"""

from __future__ import annotations

import os
import sqlite3
import tempfile
import threading
from contextlib import asynccontextmanager, closing
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.booking.demo_table import DemoTableAdapter
from app.booking.tools import Dispatcher
from app.server import create_app as server_app

_storage = tempfile.TemporaryDirectory(prefix="voicebot-browser-", dir="/tmp/opencode")


class FixtureSpeech:
    def transcribe(self, audio, *, language="et"):
        return "Hello!" if language == "en" else "Tere!"

    def synthesize(self, text):
        return (Path(__file__).parent / "fixtures/speech-tone.mp3").read_bytes()

    def for_language(self, language):
        return self

    def close(self):
        pass


class FixtureLlm:
    def chat(self, messages, tools=None):
        return {"content": "Tere! Kuidas saan aidata?"}


def create_app():
    # The actual production adapter owns capacity and receipts. Its durable DB is
    # private disposable test state; no real providers or deployment env are used.
    state_dir = Path(tempfile.mkdtemp(prefix="restaurant-", dir=_storage.name))
    state_db = str(state_dir / "restaurant.db")
    fixture_env = {
        "OPERATOR_TOKEN": "fixture-operator",
        "PUBLIC_PHONE_NUMBER": "+12025550109",
        "VOICEBOT_BUSINESS": "restaurant",
        "RESTAURANT_STATE_DB": state_db,
        "CALLS_DB": str(state_dir / "calls.db"),
    }
    with patch.dict(
        os.environ,
        fixture_env,
        clear=True,
    ):
        from app import callslog

        callslog.reset_default()
        app = server_app()
    os.environ.update(fixture_env)
    app.state.fixture_state_db = state_db
    table = app.state.stack["table"]
    assert isinstance(table, DemoTableAdapter)
    speech = FixtureSpeech()
    app.state.stack.update(
        business="restaurant",
        slot=None,
        booking_reader=None,
        stay=None,
        table=table,
        dispatcher=Dispatcher(table=table, business="restaurant"),
        stt=speech,
        tts=speech,
        llm_primary=FixtureLlm(),
    )
    app.state.capabilities.update(
        text_turn_ready=True,
        audio_turn_ready=True,
        slot_booking_ready=False,
        stay_booking_ready=False,
        table_booking_ready=True,
        booking_read_ready=True,
        booking_view_source="fictional_restaurant",
    )
    return app


def create_streaming_app():
    """Gate synthetic audio on the actual guarded route for native browser tests.

    The gate lets a real browser prove first playback precedes provider
    completion. It is a synthetic fixture, not a provider latency benchmark.
    """
    from fastapi import Header, HTTPException
    from tests.test_table_http import Planner

    gate = threading.Event()
    progress = {"started": False, "completed": False}

    class DelayedSpeech(FixtureSpeech):
        def stream(self, text):
            gate.clear()
            progress.update(started=True, completed=False)
            audio = self.synthesize(text)
            # A 0.19-second prefix is below Chromium's native startup buffer.
            # Repeat existing MP3 frames, preserving its single initial ID3 tag,
            # so the test can advance and then starve before synthesis ends.
            offset = 0
            if audio.startswith(b"ID3"):
                offset = 10 + sum(audio[6 + i] << (7 * (3 - i)) for i in range(4))
            audio = audio[:offset] + audio[offset:] * 20
            split = len(audio) // 2
            yield audio[:split]
            if not gate.wait(10):
                raise RuntimeError("synthetic browser gate expired")
            yield audio[split:]
            progress["completed"] = True

    app = create_app()
    static_route = app.router.routes.pop()
    assert static_route.name == "dashboard"
    original_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(application):
        async with original_lifespan(application):
            try:
                yield
            finally:
                gate.set()

    app.router.lifespan_context = lifespan
    day = (
        datetime.now(ZoneInfo("Europe/Tallinn")).date() + timedelta(days=7)
    ).isoformat()
    app.state.stack["llm_primary"] = Planner(day)
    app.state.stack["tts"] = DelayedSpeech()

    def fixture_authorized(authorization):
        if authorization != "Bearer fixture-operator":
            raise HTTPException(status_code=403)

    @app.get("/test/stream/state")
    def stream_state(authorization: str | None = Header(default=None)):
        fixture_authorized(authorization)
        # Count authoritative durable results, never simulated provider writes.
        with closing(
            sqlite3.connect(f"file:{app.state.fixture_state_db}?mode=ro", uri=True)
        ) as db:
            writes, records = db.execute(
                "SELECT (SELECT COUNT(*) FROM table_writes),"
                " (SELECT COUNT(*) FROM table_bookings)"
            ).fetchone()
        return {**progress, "writes": writes, "records": records}

    @app.post("/test/stream/release")
    def release_stream(authorization: str | None = Header(default=None)):
        fixture_authorized(authorization)
        gate.set()
        return {"ok": True}

    # The production catch-all static mount must remain after fixture controls.
    app.router.routes.append(static_route)
    return app
