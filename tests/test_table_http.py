"""Restaurant direct/voice HTTP flows share actual durable policy and readback."""

import base64
import json
from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app import callslog
from app.server import create_app
from app.languages import CONSENT

AUTH = {"Authorization": "Bearer fixture-operator"}


class Speaker:
    def synthesize(self, text):
        return text.encode()


class Planner:
    def __init__(self, day):
        self.calls = 0
        self.day = day

    def chat(self, messages, tools=None):
        self.calls += 1
        return {
            "content": None,
            "tool_calls": [
                {
                    "id": "call_fixture",
                    "type": "function",
                    "function": {
                        "name": "plan_demo_table",
                        "arguments": json.dumps(
                            {
                                "date": self.day,
                                "start_time": "18:00",
                                "party_size": 4,
                            }
                        ),
                    },
                }
            ],
        }


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("OPERATOR_TOKEN", "fixture-operator")
    monkeypatch.setenv("CALLS_DB", str(tmp_path / "calls.db"))
    day = (
        datetime.now(ZoneInfo("Europe/Tallinn")).date() + timedelta(days=8)
    ).isoformat()
    with patch.dict(
        "os.environ",
        {
            "OPERATOR_TOKEN": "fixture-operator",
            "CALLS_DB": str(tmp_path / "calls.db"),
            "RESTAURANT_STATE_DB": str(tmp_path / "tables.db"),
        },
        clear=True,
    ):
        callslog.reset_default()
        app = create_app()
    app.state.stack.update(llm_primary=Planner(day), tts=Speaker())
    with TestClient(app) as result:
        result.fixture_day = day
        yield result
    callslog.reset_default()


def post(client, name, body):
    return client.post("/api/booking/" + name, json=body, headers=AUTH)


def prepare(client):
    session = post(client, "session", {}).json()["session_id"]
    result = post(
        client,
        "search",
        {
            "session_id": session,
            "kind": "table",
            "date": client.fixture_day,
            "start_time": "18:00",
            "party_size": 4,
        },
    )
    assert result.status_code == 200, result.text
    offer = result.json()["offers"][0]
    result = post(
        client,
        "prepare",
        {
            "session_id": session,
            "kind": "table",
            "table_offer_id": offer["table_offer_id"],
        },
    )
    assert result.status_code == 200, result.text
    return session, result.json()


def test_direct_restaurant_reservation_and_owned_cancellation(client):
    session, prepared = prepare(client)
    assert prepared["kind"] == "table"
    assert "18:00" in prepared["recap_text"]
    state = client.app.state.demo_sessions.sessions[session]
    assert state.tools.pending["kind"] == "table"
    assert not state.tools.bookings
    assert (
        client.get(
            "/api/table-bookings", params={"date": client.fixture_day}, headers=AUTH
        ).json()["items"]
        == []
    )
    assert (
        post(
            client,
            "recap",
            {
                "session_id": session,
                "hold_id": prepared["hold_id"],
                "recap_delivery_id": prepared["recap_delivery_id"],
            },
        ).status_code
        == 200
    )
    confirmed = post(
        client,
        "confirm",
        {
            "session_id": session,
            "kind": "table",
            "hold_id": prepared["hold_id"],
            "consent": True,
        },
    )
    assert confirmed.status_code == 200, confirmed.text
    booking_id = confirmed.json()["booking"]["id"]
    assert booking_id.startswith("table_")
    assert confirmed.json()["booking_changes"][0]["kind"] == "table"
    rows = client.get(
        "/api/table-bookings", params={"date": client.fixture_day}, headers=AUTH
    )
    assert rows.status_code == 200
    booking = next(row for row in rows.json()["items"] if row["id"] == booking_id)
    assert booking["party_size"] == 4
    assert "email" not in rows.text and "phone" not in rows.text
    foreign = post(client, "session", {}).json()["session_id"]
    assert (
        post(
            client,
            "cancel",
            {
                "session_id": foreign,
                "kind": "table",
                "booking_id": booking_id,
                "consent": True,
            },
        ).status_code
        == 409
    )
    cancelled = post(
        client,
        "cancel",
        {
            "session_id": session,
            "kind": "table",
            "booking_id": booking_id,
            "consent": True,
        },
    )
    assert cancelled.status_code == 200, cancelled.text
    rows = client.get(
        "/api/table-bookings", params={"date": client.fixture_day}, headers=AUTH
    ).json()["items"]
    assert not any(
        row["id"] == booking_id and row["status"] == "confirmed" for row in rows
    )
    history = client.get("/api/call-history", headers=AUTH)
    assert history.status_code == 200, history.text
    entry = next(
        row for row in history.json()["items"] if row["id"] == state.tools.call_id
    )
    assert entry["bookings"][0]["id"] == booking_id
    assert entry["bookings"][0]["action"] == "cancelled"


@pytest.mark.parametrize("language", ["et", "en", "ru"])
def test_voice_restaurant_confirm_cancel_and_history_need_no_followup_model(
    client, language
):
    session = client.post(
        "/api/demo/session", json={"language": language}, headers=AUTH
    ).json()["session_id"]

    def turn(text, **extra):
        result = client.post(
            "/api/turn",
            json={"session_id": session, "text": text, "language": language, **extra},
            headers=AUTH,
        )
        assert result.status_code == 200, result.text
        return result.json()

    requests = {
        "et": f"Palun laud neljale {client.fixture_day} kell 18:00.",
        "en": f"Please reserve a table for four on {client.fixture_day} at 18:00.",
        "ru": f"Пожалуйста, столик на четырёх человек {client.fixture_day} в 18:00.",
    }
    proposed = turn(requests[language])
    assert proposed["recap_delivery_id"]
    assert proposed["booking_ids"] == []
    assert base64.b64decode(proposed["audio_b64"]).decode() == proposed["reply"]
    assert client.app.state.stack["llm_primary"].calls == 1
    confirmed = turn(
        CONSENT[language],
        recap_delivery_id=proposed["recap_delivery_id"],
    )
    assert confirmed["outcome"] == "tools_ok", confirmed
    assert len(confirmed["booking_ids"]) == 1
    assert client.app.state.stack["llm_primary"].calls == 1
    assert confirmed["booking_changes"][0]["kind"] == "table"
    cancelled = turn(
        {
            "et": "Jah, tühista.",
            "en": "Please cancel this test booking.",
            "ru": "Да, отмените.",
        }[language]
    )
    assert cancelled["outcome"] == "tools_ok", cancelled
    assert client.app.state.stack["llm_primary"].calls == 1
    assert cancelled["booking_changes"][0]["action"] == "cancelled"
    history = client.get("/api/call-history", headers=AUTH)
    assert history.status_code == 200, history.text
    rows = [
        row
        for row in history.json()["items"]
        if row["id"] == client.app.state.demo_sessions.sessions[session].tools.call_id
    ]
    assert rows[0]["bookings"][0]["kind"] == "table"
    assert rows[0]["bookings"][0]["action"] == "cancelled"


@pytest.mark.parametrize("path", ["/api/tables", "/api/table-bookings"])
def test_restaurant_reads_are_authenticated_private_and_no_store(client, path):
    assert client.get(path).status_code == 403
    assert client.get(path).headers["Cache-Control"] == "no-store"
    response = client.get(path, headers=AUTH)
    assert response.status_code == 200, response.text
    assert response.headers["Cache-Control"] == "no-store"


def test_public_restaurant_catalogue_never_advertises_spa_or_rooms(client):
    profile = client.get("/api/public/property")
    catalogue = client.get("/api/public/catalogue")
    assert profile.status_code == catalogue.status_code == 200
    assert "restoran" in profile.json()["property"]["name"].casefold()
    assert profile.json()["capabilities"]["table_booking_ready"]
    assert "tables" in catalogue.json() and "rules" in catalogue.json()
    assert not {"rooms", "services", "providers"} & catalogue.json().keys()
    assert "guest" not in catalogue.text
    assert len(catalogue.json()["menu"]) == 3
    assert all(
        "Fiktiivne" in item["description_et"] for item in catalogue.json()["menu"]
    )
    assert not any(
        "price" in item or "allergen_free" in item for item in catalogue.json()["menu"]
    )


@pytest.mark.parametrize("kind", ["slot", "stay"])
def test_restaurant_direct_controls_reject_legacy_kinds(client, kind):
    session = post(client, "session", {}).json()["session_id"]
    for path in ("search", "prepare", "confirm", "cancel"):
        response = post(client, path, {"session_id": session, "kind": kind})
        assert response.status_code == 400, response.text
        assert response.json()["detail"] == "restaurant_booking_required"
    assert not client.app.state.demo_sessions.sessions[session].busy


def test_restaurant_mode_does_not_enable_old_demo_queue_mutations(client):
    for action in ("confirm", "cancel"):
        response = client.post("/api/holds/hold_demo_sea12/" + action, headers=AUTH)
        assert response.status_code == 503, response.text


def test_restaurant_property_never_reads_accidentally_wired_spa_catalogue(client):
    class Archived:
        calls = 0

        async def get_slot_catalogue(self):
            self.calls += 1
            return {
                "providers": [
                    {"working_hours": {"monday": {"start": "09:00", "end": "17:00"}}}
                ]
            }

    archived = Archived()
    client.app.state.stack["booking_reader"] = archived
    result = client.get("/api/public/property")
    assert result.status_code == 200
    assert result.json()["property"]["hours_scope"] == "restaurant_sittings"
    assert archived.calls == 0
