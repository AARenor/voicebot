"""The selected browser language applies from the first spoken greeting."""

import base64
import asyncio
import json
from datetime import datetime, timedelta
from unittest.mock import Mock
from unittest.mock import patch
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo

import httpx
import pytest
from fastapi.testclient import TestClient

from app.booking.demo_table import DemoTableAdapter
from app.booking.tools import Dispatcher
from app.languages import ENGLISH, TABLE_GREETINGS
from app.providers.azure_tts import AzureTtsClient
from app.server import create_app
from tests.test_product_demo import (
    AUTH,
    Speaker,
    SimpleLlm,
    send,
)


@pytest.fixture
def client(monkeypatch, tmp_path):
    from app import callslog

    state_db = str(tmp_path / "restaurant.db")
    with patch.dict(
        "os.environ",
        {"OPERATOR_TOKEN": "fixture-operator", "RESTAURANT_STATE_DB": state_db},
        clear=True,
    ):
        callslog.reset_default()
        app = create_app()
    monkeypatch.setenv("OPERATOR_TOKEN", "fixture-operator")
    table = DemoTableAdapter(state_db)
    app.state.stack.update(
        business="restaurant",
        table=table,
        slot=None,
        stay=None,
        dispatcher=Dispatcher(table=table, business="restaurant"),
        llm_primary=SimpleLlm(),
        tts=Speaker(),
    )
    with TestClient(app) as result:
        yield result
    callslog.reset_default()


@pytest.mark.parametrize(
    "language,effective", [("auto", "et"), ("et", "et"), ("en", "en"), ("ru", "ru")]
)
def test_initial_language_owns_greeting_and_session_without_model_turn(
    client, language, effective
):
    result = client.post("/api/demo/session", headers=AUTH, json={"language": language})
    assert result.status_code == 200
    data = result.json()
    session = client.app.state.demo_sessions.sessions[data["session_id"]]
    assert data["language"] == session.tools.language == effective
    assert data["greeting"] == session.tools.greeting
    assert data["greeting"] == TABLE_GREETINGS[effective]
    assert base64.b64decode(data["audio_b64"]).decode() == data["greeting"]
    assert not client.app.state.stack["llm_primary"].messages
    assert session.turn_count == 0
    assert result.headers["Cache-Control"] == "no-store"


@pytest.mark.parametrize("body", [None, {}, {"language": "auto"}])
def test_legacy_session_start_keeps_estonian_greeting(client, body):
    result = client.post(
        "/api/demo/session",
        headers=AUTH,
        **({"json": body} if body is not None else {}),
    )
    assert result.status_code == 200 and result.json()["greeting"].startswith("Tere!")


@pytest.mark.parametrize(
    "body",
    [
        {"language": "de"},
        {"language": None},
        {"language": []},
        {"language": 1},
        {"language": "en", "consent": True},
        [],
        "en",
    ],
)
def test_invalid_session_settings_create_nothing_and_echo_no_values(client, body):
    result = client.post("/api/demo/session", headers=AUTH, json=body)
    assert result.status_code == 400
    assert not client.app.state.demo_sessions.sessions
    assert not client.app.state.stack["tts"].spoken


@pytest.mark.parametrize("content,status", [(b"{", 400), (b"x" * 1025, 413)])
def test_session_request_is_bounded_and_malformed_json_is_closed(
    client, content, status
):
    assert (
        client.post("/api/demo/session", headers=AUTH, content=content).status_code
        == status
    )
    assert not client.app.state.demo_sessions.sessions
    assert client.post("/api/demo/session", content=content).status_code == 403


def test_english_greeting_uses_jenny_without_mutating_estonian_voice(client):
    bodies = []

    def handler(request):
        if request.url.path.endswith("issueToken"):
            return httpx.Response(200, text="fixture-token")
        bodies.append(request.content.decode())
        return httpx.Response(200, content=b"fixture-audio")

    speaker = AzureTtsClient(
        "fixture",
        "fixture",
        "et-EE-AnuNeural",
        "et-EE",
        transport=httpx.MockTransport(handler),
        languages={
            "en": ("en-US-JennyNeural", "en-US"),
            "et": ("et-EE-AnuNeural", "et-EE"),
        },
    )
    client.app.state.stack["tts"] = speaker
    try:
        for language in ("en", "et", "en"):
            result = client.post(
                "/api/demo/session", headers=AUTH, json={"language": language}
            )
            assert result.status_code == 200 and not result.json()["tts_failed"]
        documents = [ET.fromstring(body) for body in bodies]
        assert [document.find(".//{*}voice").get("name") for document in documents] == [
            "en-US-JennyNeural",
            "et-EE-AnuNeural",
            "en-US-JennyNeural",
        ]
        assert "".join(documents[0].itertext()) == TABLE_GREETINGS["en"]
    finally:
        speaker.close()


def test_selected_english_recognition_and_audio_reply(client):
    started = client.post(
        "/api/demo/session", headers=AUTH, json={"language": "en"}
    ).json()
    recognizer = Mock()
    recognizer.transcribe.return_value = "Hello!"
    client.app.state.stack["stt"] = recognizer
    result = client.post(
        "/api/turn",
        headers=AUTH,
        json={
            "session_id": started["session_id"],
            "language": "en",
            "audio_b64": base64.b64encode(b"RIFF-fixture").decode(),
        },
    )
    assert result.status_code == 200 and result.json()["language"] == "en"
    recognizer.transcribe.assert_called_once_with(b"RIFF-fixture", language="en")
    assert (
        base64.b64decode(result.json()["audio_b64"]).decode() == result.json()["reply"]
    )


def test_english_session_preserves_booking_delivery_confirmation_and_cancellation(
    client,
):
    day = (
        datetime.now(ZoneInfo("Europe/Tallinn")).date() + timedelta(days=1)
    ).isoformat()
    table = client.app.state.stack["table"]

    class BookingLlm:
        def __init__(self):
            self.messages = []

        def chat(self, messages, tools=None):
            self.messages.append(messages)
            if len(self.messages) == 1:
                return {
                    "tool_calls": [
                        {
                            "id": "table-plan",
                            "type": "function",
                            "function": {
                                "name": "plan_demo_table",
                                "arguments": json.dumps(
                                    {
                                        "date": day,
                                        "start_time": "18:00",
                                        "party_size": 3,
                                    }
                                ),
                            },
                        }
                    ]
                }
            return {"content": "Read the supplied recap."}

    model = BookingLlm()
    client.app.state.stack["llm_primary"] = model
    from tests.test_table_http import Speaker as AudioSpeaker

    client.app.state.stack["tts"] = AudioSpeaker()
    session = client.post(
        "/api/demo/session", headers=AUTH, json={"language": "en"}
    ).json()["session_id"]
    recap = send(
        client, session, f"A table for three on {day} at 6 pm", language="en"
    ).json()
    assert "Yes, I confirm." in recap["reply"] and recap["recap_delivery_id"]
    assert "Meretuule" in recap["reply"] and "18" in recap["reply"]
    assert not asyncio.run(table.get_operator_bookings(day))["items"]
    before_terminal = len(model.messages)
    confirmed = send(client, session, "Yes, I confirm.", language="en").json()
    records = asyncio.run(table.get_operator_bookings(day))["items"]
    assert len(records) == 1 and records[0]["status"] == "confirmed"
    assert confirmed["booking_ids"] == [records[0]["id"]]
    assert records[0]["id"].startswith("table_") and records[0]["party_size"] == 3
    assert len(model.messages) == before_terminal, (
        "confirmation made another model request"
    )
    cancelled = send(
        client, session, "Please cancel this test booking.", language="en"
    ).json()
    assert cancelled["reply"] == ENGLISH["cancelled"]
    cancelled_records = asyncio.run(table.get_operator_bookings(day))["items"]
    assert (
        len(cancelled_records) == 1 and cancelled_records[0]["id"] == records[0]["id"]
    )
    assert cancelled_records[0]["status"] == "cancelled"
    assert len(model.messages) == before_terminal, (
        "cancellation made another model request"
    )


def test_english_greeting_synthesis_failure_keeps_english_text(client):
    client.app.state.stack["tts"].synthesize = Mock(side_effect=RuntimeError("PRIVATE"))
    result = client.post("/api/demo/session", headers=AUTH, json={"language": "en"})
    assert result.status_code == 200
    assert result.json()["greeting"] == TABLE_GREETINGS["en"]
    assert result.json()["tts_failed"] and not result.json()["audio_b64"]
    assert "PRIVATE" not in result.text
