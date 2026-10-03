"""Restaurant API integration, with actual SQLite and local provider doubles."""

import base64
import hashlib
import json
from datetime import datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app.business import business_type
from app.languages import CONSENT
from app.restaurant_call import COPY
from app.server import build_stack, create_app

AUTH = {"Authorization": "Bearer restaurant-fixture-operator"}
ROOT = Path(__file__).resolve().parents[1]


class Provider:
    def __init__(self):
        self.spoken = []
        self.recognized_languages = []

    def transcribe(self, audio, *, language=None):
        self.recognized_languages.append(language)
        return "What is on the menu?"

    def synthesize(self, text):
        self.spoken.append(text)
        return (Path(__file__).parent / "fixtures/speech-tone.mp3").read_bytes()


class NoModelNeeded:
    def chat(self, messages, tools=None):
        raise AssertionError("Restaurant routine used ungrounded model prose")


@pytest.fixture
def client(tmp_path, monkeypatch):
    from app import callslog

    for key in ("GROQ_API_KEY", "GEMINI_API_KEY", "AZURE_SPEECH_KEY"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("VOICEBOT_BUSINESS_TYPE", "restaurant")
    monkeypatch.setenv("RESTAURANT_DEMO_WRITES", "1")
    monkeypatch.setenv("RESTAURANT_STATE_DB", str(tmp_path / "restaurant.db"))
    monkeypatch.setenv("OPERATOR_TOKEN", "restaurant-fixture-operator")
    monkeypatch.setenv("CALLS_DB", str(tmp_path / "calls.db"))
    callslog.reset_default()
    app = create_app()
    provider = Provider()
    app.state.stack.update(stt=provider, tts=provider, llm_primary=NoModelNeeded())
    app.state.capabilities.update(text_turn_ready=True, audio_turn_ready=True)
    with TestClient(app) as result:
        result.provider = provider
        yield result
    callslog.reset_default()


def tomorrow():
    return (
        datetime.now(ZoneInfo("Europe/Tallinn")).date() + timedelta(days=1)
    ).isoformat()


def start(client, language="en", direct=False):
    response = client.post(
        "/api/booking/session" if direct else "/api/demo/session",
        json={"language": language},
        headers=AUTH,
    )
    assert response.status_code == 200, response.text
    return response.json()


def turn(client, session, text, *, language="en", receipt=None):
    body = {"session_id": session, "text": text, "language": language}
    if receipt:
        body["recap_delivery_id"] = receipt
    response = client.post("/api/turn", json=body, headers=AUTH)
    assert response.status_code == 200, response.text
    return response.json()


def prepared(client, language="en"):
    session = start(client, language, direct=True)["session_id"]
    response = client.post(
        "/api/restaurant/reservation/prepare",
        json={
            "session_id": session,
            "date": tomorrow(),
            "start_time": "14:00",
            "party_size": 4,
        },
        headers=AUTH,
    )
    assert response.status_code == 200 and response.json().get("ok"), response.text
    return session, response.json()


def test_restaurant_is_default_and_legacy_provider_credentials_do_not_reenable_old_workflows(
    tmp_path,
):
    with patch.dict(
        "os.environ",
        {
            "EASY_BASE_URL": "https://not-contacted.invalid",
            "EASY_API_KEY": "fixture",
            "EASY_DEMO_WRITES": "1",
            "EASY_STATE_DB": str(tmp_path / "old.db"),
        },
        clear=True,
    ):
        assert business_type() == "restaurant"
        stack = build_stack()
    assert stack["business_type"] == "restaurant"
    assert type(stack["slot"]).__name__ == "RestaurantAdapter"
    assert stack["stay"] is None
    assert not (tmp_path / "old.db").exists()
    assert not (tmp_path / "stay-booking.db").exists()
    assert (tmp_path / "restaurant-booking.db").exists()


def test_default_restaurant_status_and_public_knowledge_are_truthful(client):
    status = client.get("/api/status").json()
    assert status["business_type"] == "restaurant"
    assert status["telephone"]["supported_languages"] == ["et", "en", "ru"]
    assert status["telephone"]["carrier_call_verified"] is False
    assert status["capabilities"]["stay_booking_ready"] is False
    assert status["capabilities"]["booking_view_source"] == "restaurant"
    public = client.get("/api/public/restaurant").json()
    assert public["synthetic"] is True
    assert public["restaurant"]["address"] is None
    assert public["allergy_safety_verified"] is False
    text = json.dumps(public)
    assert "restaurant-fixture-operator" not in text
    assert "example.invalid" not in text
    assert "booking" not in client.get("/api/public/catalogue").json()


@pytest.mark.parametrize(
    "path",
    [
        "/api/rooms",
        "/api/stays",
        "/api/holds",
        "/api/booking/search",
        "/api/booking/prepare",
    ],
)
def test_legacy_room_spa_and_example_queue_routes_not_exposed(client, path):
    assert client.get(path, headers=AUTH).status_code in (404, 405)
    assert client.post(path, json={}, headers=AUTH).status_code in (404, 405)


@pytest.mark.parametrize("language", ["et", "en", "ru", "auto"])
def test_initial_restaurant_greeting_selects_actual_language(client, language):
    data = start(client, language)
    selected = "et" if language == "auto" else language
    assert data["language"] == selected
    assert data["greeting"] == COPY[selected]["greeting"]
    assert client.provider.spoken[-1] == data["greeting"]
    assert base64.b64decode(data["audio_b64"])


@pytest.mark.parametrize(
    "language,question",
    [
        ("et", "Milline on menüü?"),
        ("en", "What is on the menu?"),
        ("ru", "Что есть в меню?"),
    ],
)
def test_routine_menu_and_hours_are_grounded_without_model_calls(
    client, language, question
):
    data = start(client, language)
    answer = turn(client, data["session_id"], question, language=language)
    assert answer["warnings"] == []
    assert answer["booking_changes"] == []
    assert answer["language"] == language
    assert "spa" not in answer["reply"].casefold()
    assert answer["reply"] == client.provider.spoken[-1]


@pytest.mark.parametrize(
    "language,utterance",
    [
        ("et", "Soovin homme lauda neljale kell 14.00"),
        ("en", "A table for four tomorrow at 2 pm"),
        ("ru", "Столик на четверых завтра в 14:00"),
    ],
)
def test_browser_voice_policy_books_only_after_recap_receipt(
    client, language, utterance
):
    data = start(client, language)
    answer = turn(client, data["session_id"], utterance, language=language)
    assert answer["recap_delivery_id"]
    assert CONSENT[language] in answer["reply"]
    assert "4" in answer["reply"] and "90" in answer["reply"]
    assert answer["booking_changes"] == []
    confirmed = turn(
        client,
        data["session_id"],
        CONSENT[language],
        language=language,
        receipt=answer["recap_delivery_id"],
    )
    assert confirmed["booking_changes"][0]["action"] == "confirmed"
    assert confirmed["reply"] == COPY[language]["confirmed"]
    page = client.get("/api/bookings?date=" + tomorrow(), headers=AUTH).json()
    assert len(page["items"]) == 1 and page["source"] == "restaurant"


def test_audio_language_is_sent_to_recognition_and_restaurant_reply(client):
    session = start(client, "en")["session_id"]
    response = client.post(
        "/api/turn",
        json={
            "session_id": session,
            "audio_b64": base64.b64encode(b"RIFF-fixture-synthetic-audio").decode(),
            "language": "en",
        },
        headers=AUTH,
    )
    assert response.status_code == 200
    assert client.provider.recognized_languages == ["en"]
    assert response.json()["language"] == "en"
    assert "Vegetable soup" in response.json()["reply"]


@pytest.mark.parametrize("language", ["et", "en", "ru"])
def test_direct_table_booking_recap_confirmation_and_owned_cancel(client, language):
    session, result = prepared(client, language)
    assert CONSENT[language] in result["recap_text"]
    body = {"session_id": session, "hold_id": result["hold_id"], "consent": True}
    denied = client.post("/api/booking/confirm", json=body, headers=AUTH)
    assert denied.status_code == 409
    # Failed early confirmation invalidates the proposal; prepare a fresh recap.
    tools = client.app.state.demo_sessions.sessions[session].tools
    refreshed = asyncio_run(
        tools.dispatch("prepare_demo_booking", {"hold_id": result["hold_id"]})
    )
    assert refreshed["ok"]
    assert (
        client.post(
            "/api/booking/recap",
            json={"session_id": session, "hold_id": result["hold_id"]},
            headers=AUTH,
        ).status_code
        == 200
    )
    confirmed = client.post("/api/booking/confirm", json=body, headers=AUTH)
    assert confirmed.status_code == 200 and confirmed.json()["ok"] is True
    identifier = str(confirmed.json()["booking"]["id"])
    cancelled = client.post(
        "/api/booking/cancel",
        json={"session_id": session, "booking_id": identifier, "consent": True},
        headers=AUTH,
    )
    assert cancelled.status_code == 200 and cancelled.json()["ok"] is True
    page = client.get("/api/bookings?date=" + tomorrow(), headers=AUTH).json()
    assert page["items"][0]["status"] == "cancelled"


def asyncio_run(awaitable):
    import asyncio

    return asyncio.run(awaitable)


@pytest.mark.parametrize(
    "path",
    [
        "/api/booking/session",
        "/api/restaurant/reservation/prepare",
        "/api/booking/recap",
        "/api/booking/confirm",
        "/api/booking/cancel",
    ],
)
def test_auth_precedes_body_and_every_private_response_is_no_store(client, path):
    for headers in ({}, {"Authorization": "Bearer wrong"}):
        response = client.post(path, content=b"not-json", headers=headers)
        assert response.status_code == 403
        assert response.headers["Cache-Control"] == "no-store"


@pytest.mark.parametrize(
    "extra",
    [
        {"guest": {"email": "real@example.com"}},
        {"consent": True},
        {"restaurant_id": "other"},
        {"kind": "stay"},
    ],
)
def test_untrusted_booking_fields_are_rejected(client, extra):
    session = start(client, direct=True)["session_id"]
    response = client.post(
        "/api/restaurant/reservation/prepare",
        json={
            "session_id": session,
            "date": tomorrow(),
            "start_time": "14:00",
            "party_size": 4,
            **extra,
        },
        headers=AUTH,
    )
    assert response.status_code == 400
    assert response.headers["Cache-Control"] == "no-store"
    assert client.app.state.demo_sessions.sessions[session].busy is False


def test_restaurant_page_and_assets_are_local_and_content_versioned(client):
    urls = []

    class Parser(HTMLParser):
        def handle_starttag(self, tag, attrs):
            values = dict(attrs)
            if tag == "script":
                urls.append(values["src"])
            elif tag == "link" and values.get("rel") == "stylesheet":
                urls.append(values["href"])

    page = client.get("/")
    assert page.status_code == 200 and 'id="demo-language"' in page.text
    Parser().feed(page.text)
    for url in urls:
        parsed = urlsplit(url)
        assert not parsed.netloc
        content = (
            ROOT / "app/restaurant/static" / parsed.path.lstrip("/")
        ).read_bytes()
        assert parse_qs(parsed.query)["v"] == [hashlib.sha256(content).hexdigest()[:12]]
        assert client.get(url).content == content
    assert (
        client.get("/hotel", headers={"Host": "robot.arleserver.cfd"}).status_code
        == 410
    )
