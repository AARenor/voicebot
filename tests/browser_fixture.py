"""Local browser integration app with the real routes and fictional providers.

Run with: uvicorn tests.browser_fixture:create_app --factory --port 8765
The token is a public test fixture, not a deployment credential. No external
provider is contacted. The committed MP3 test tone is synthetic audio.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from app.booking.demo_table import DemoTableAdapter
from app.booking.tools import Dispatcher
from app.server import create_app as server_app

_storage = tempfile.TemporaryDirectory(prefix="voicebot-browser-", dir="/tmp/opencode")


class FixtureSpeech:
    def transcribe(self, audio, *, language="et"):
        return "Hello!" if language == "en" else "Tere!"

    def synthesize(self, text):
        return (Path(__file__).parent / "fixtures/speech-tone.mp3").read_bytes()

    def close(self):
        pass


class FixtureLlm:
    def chat(self, messages, tools=None):
        return {"content": "Tere! Kuidas saan aidata?"}


def create_app():
    # The actual production adapter owns capacity and receipts. Its durable DB is
    # private disposable test state; no real providers or deployment env are used.
    state_db = str(Path(_storage.name) / "restaurant.db")
    with patch.dict(
        os.environ,
        {"OPERATOR_TOKEN": "fixture-operator", "RESTAURANT_STATE_DB": state_db},
        clear=True,
    ):
        app = server_app()
    os.environ["OPERATOR_TOKEN"] = "fixture-operator"
    os.environ["PUBLIC_PHONE_NUMBER"] = "+12025550109"
    table = DemoTableAdapter(state_db)
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
        booking_view_source="demo_table",
    )
    return app
