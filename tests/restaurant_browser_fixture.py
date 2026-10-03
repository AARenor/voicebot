"""Real restaurant routes with local synthetic audio; no paid providers."""

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from app.server import create_app as server_app

_storage = tempfile.TemporaryDirectory(prefix="voicebot-restaurant-browser-")


class FixtureSpeech:
    def transcribe(self, audio, *, language=None):
        return {"et": "Milline on menüü?", "ru": "Что есть в меню?"}.get(
            language, "What is on the menu?"
        )

    def synthesize(self, text):
        return (Path(__file__).parent / "fixtures/speech-tone.mp3").read_bytes()

    def close(self):
        pass


class FixtureLlm:
    def chat(self, messages, tools=None):
        return {
            "content": "I can help with restaurant table reservations, the menu and opening hours. How can I help?"
        }


def create_app():
    with patch.dict(
        "os.environ",
        {
            "VOICEBOT_BUSINESS_TYPE": "restaurant",
            "RESTAURANT_DEMO_WRITES": "1",
            "RESTAURANT_STATE_DB": str(Path(_storage.name) / "restaurant.db"),
            "CALLS_DB": str(Path(_storage.name) / "calls.db"),
            "OPERATOR_TOKEN": "restaurant-fixture-operator",
        },
        clear=True,
    ):
        from app import callslog

        callslog.reset_default()
        app = server_app()
        callslog.get_default()
    os.environ["OPERATOR_TOKEN"] = "restaurant-fixture-operator"
    speech = FixtureSpeech()
    app.state.stack.update(stt=speech, tts=speech, llm_primary=FixtureLlm())
    app.state.capabilities.update(text_turn_ready=True, audio_turn_ready=True)
    return app
