"""The selected browser language applies from the first spoken greeting."""

import base64
from unittest.mock import Mock
import xml.etree.ElementTree as ET

import httpx
import pytest

from app.languages import ENGLISH
from app.providers.azure_tts import AzureTtsClient
from tests.test_product_demo import (
    AUTH,
    BookingLlm,
    client as demo_client,
    install_backend,
    send,
)

client = demo_client


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
    if effective == "en":
        assert data["greeting"] == ENGLISH["greeting"]
    assert base64.b64decode(data["audio_b64"]).decode() == data["greeting"]
    assert not client.app.state.stack["llm_primary"].messages
    assert session.turn_count == 0
    assert result.headers["Cache-Control"] == "no-store"


@pytest.mark.parametrize("body", [None, {}, {"language": "auto"}])
def test_legacy_session_start_keeps_estonian_greeting(client, body):
    result = client.post(
        "/api/demo/session",
        headers=AUTH,
        **({"json": body} if body is not None else {})
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
        assert "".join(documents[0].itertext()) == ENGLISH["greeting"]
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
    client, tmp_path
):
    day, records, writes = install_backend(client, tmp_path)
    client.app.state.stack["llm_primary"] = BookingLlm(day)
    session = client.post(
        "/api/demo/session", headers=AUTH, json={"language": "en"}
    ).json()["session_id"]
    recap = send(client, session, "I would like a test booking", language="en").json()
    assert "Yes, I confirm." in recap["reply"] and recap["recap_delivery_id"]
    assert not records
    confirmed = send(client, session, "Yes, I confirm.", language="en").json()
    assert confirmed["booking_ids"] == ["42"] and len(records) == 1
    cancelled = send(
        client, session, "Please cancel this test booking.", language="en"
    ).json()
    assert cancelled["reply"] == ENGLISH["cancelled"] and not records
    assert (
        sum(
            request.method == "POST" and request.url.path.endswith("/appointments")
            for request in writes
        )
        == 1
    )


def test_english_greeting_synthesis_failure_keeps_english_text(client):
    client.app.state.stack["tts"].synthesize = Mock(side_effect=RuntimeError("PRIVATE"))
    result = client.post("/api/demo/session", headers=AUTH, json={"language": "en"})
    assert result.status_code == 200
    assert result.json()["greeting"] == ENGLISH["greeting"]
    assert result.json()["tts_failed"] and not result.json()["audio_b64"]
    assert "PRIVATE" not in result.text
