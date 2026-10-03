"""Direct website booking reaches provider truth without paid speech calls."""

from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app.booking.demo_stay import DemoStayAdapter
from app.booking.tools import Dispatcher
from app.server import create_app
from tests.test_product_demo import AUTH, install_backend


@pytest.fixture
def client(monkeypatch, tmp_path):
    from app import callslog

    with patch.dict("os.environ", {"OPERATOR_TOKEN": "fixture-operator"}, clear=True):
        callslog.reset_default()
        app = create_app()
    monkeypatch.setenv("OPERATOR_TOKEN", "fixture-operator")
    stay = DemoStayAdapter(str(tmp_path / "stays.db"))
    app.state.stack.update(stay=stay, dispatcher=Dispatcher(stay=stay))
    with TestClient(app) as result:
        yield result
    callslog.reset_default()


def post(client, path, body):
    return client.post("/api/booking/" + path, json=body, headers=AUTH)


def start(client):
    result = post(client, "session", {})
    assert result.status_code == 200, result.text
    return result.json()["session_id"]


@pytest.mark.parametrize(
    "path", ["session", "search", "prepare", "recap", "confirm", "cancel"]
)
def test_operator_required_before_booking_session_or_provider(client, path):
    result = client.post("/api/booking/" + path, json={})
    assert result.status_code == 403
    assert result.headers["Cache-Control"] == "no-store"
    assert not client.app.state.demo_sessions.sessions


def test_direct_spa_booking_requires_displayed_recap_and_explicit_button(
    client, tmp_path
):
    stay = client.app.state.stack["stay"]
    day, records, writes = install_backend(client, tmp_path)
    client.app.state.stack["dispatcher"]._stay = stay
    session = start(client)
    search = post(
        client,
        "search",
        {
            "session_id": session,
            "kind": "slot",
            "service": "6",
            "provider": "2",
            "date": day,
        },
    )
    assert search.status_code == 200, search.text
    slot = search.json()["slots"][0]
    prepared = post(
        client,
        "prepare",
        {"session_id": session, "kind": "slot", "slot_id": slot["slotId"]},
    )
    assert prepared.status_code == 200, prepared.text
    tools = client.app.state.demo_sessions.sessions[session].tools
    assert tools.pending["recap"]["start"].startswith(day)
    assert prepared.json()["recap_text"] == tools.render_recap()
    assert "Demo Esimene" in prepared.json()["recap_text"]
    assert not writes
    hold = prepared.json()["hold_id"]
    denied = post(
        client,
        "confirm",
        {"session_id": session, "kind": "slot", "hold_id": hold, "consent": True},
    )
    assert denied.status_code == 409
    assert not writes
    # Failed/ambiguous consent requires preparing the recap again.
    prepared = post(
        client,
        "prepare",
        {"session_id": session, "kind": "slot", "slot_id": slot["slotId"]},
    )
    hold = prepared.json()["hold_id"]
    acknowledged = post(client, "recap", {"session_id": session, "hold_id": hold})
    assert acknowledged.status_code == 200
    assert acknowledged.json()["acknowledged"] is True
    denied = post(
        client,
        "confirm",
        {"session_id": session, "kind": "slot", "hold_id": hold, "consent": "true"},
    )
    assert denied.status_code == 400
    assert not writes
    confirmed = post(
        client,
        "confirm",
        {"session_id": session, "kind": "slot", "hold_id": hold, "consent": True},
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["ok"] is True
    assert len(records) == 1
    booking = str(confirmed.json()["booking"]["id"])
    foreign = post(
        client,
        "cancel",
        {
            "session_id": start(client),
            "kind": "slot",
            "booking_id": booking,
            "consent": True,
        },
    )
    assert foreign.status_code == 409
    assert records
    cancelled = post(
        client,
        "cancel",
        {"session_id": session, "kind": "slot", "booking_id": booking, "consent": True},
    )
    assert cancelled.status_code == 200, cancelled.text
    assert not records


def test_public_catalogue_does_not_expose_bookings_or_guest_contacts(
    client, monkeypatch
):
    monkeypatch.setenv("TWILIO_PHONE_NUMBER", "+12025550109")
    monkeypatch.setenv("GROQ_API_KEY", "fixture-provider-secret")
    profile = client.get("/api/public/property")
    assert profile.status_code == 200
    assert profile.json()["phone"]["href"] == "tel:+12025550109"
    catalogue = client.get("/api/public/catalogue")
    assert catalogue.status_code == 200
    assert catalogue.json()["services"] == []
    assert catalogue.json()["providers"] == []
    assert catalogue.json()["rooms"] is None
    assert catalogue.json()["restaurant_booking_error"] == "dataset_not_configured"
    assert "guest" not in catalogue.text
    assert "fixture-provider-secret" not in profile.text + catalogue.text
    for path in ("/api/rooms", "/api/stays"):
        response = client.get(path)
        assert response.status_code == 403
        assert response.headers["Cache-Control"] == "no-store"


def test_invalid_booking_request_releases_session(client):
    session = start(client)
    invalid = post(
        client,
        "search",
        {
            "session_id": session,
            "kind": "stay",
            "checkin": "garbage",
            "checkout": "2099-01-03",
        },
    )
    assert invalid.status_code == 400
    assert not client.app.state.demo_sessions.sessions[session].busy


def test_direct_room_booking_and_cancellation_have_durable_receipts(client):
    checkin = (
        datetime.now(ZoneInfo("Europe/Tallinn")).date() + timedelta(days=5)
    ).isoformat()
    checkout = (
        datetime.now(ZoneInfo("Europe/Tallinn")).date() + timedelta(days=7)
    ).isoformat()
    session = start(client)
    search = post(
        client,
        "search",
        {
            "session_id": session,
            "kind": "stay",
            "checkin": checkin,
            "checkout": checkout,
            "adults": 2,
            "children": 0,
            "room_type": "spa-suite",
        },
    )
    assert search.status_code == 200, search.text
    offer = search.json()["offers"][0]
    assert offer["room_type_id"] == "spa-suite"
    prepared = post(
        client,
        "prepare",
        {
            "session_id": session,
            "kind": "stay",
            "price_quote_id": offer["price_quote_id"],
        },
    )
    assert prepared.status_code == 200, prepared.text
    hold = prepared.json()["hold_id"]
    assert offer["quoted_total"] in prepared.json()["recap_text"]
    assert (
        post(client, "recap", {"session_id": session, "hold_id": hold}).status_code
        == 200
    )
    confirmed = post(
        client,
        "confirm",
        {"session_id": session, "kind": "stay", "hold_id": hold, "consent": True},
    )
    assert confirmed.status_code == 200, confirmed.text
    booking = confirmed.json()["booking"]
    assert booking["checkin"] == checkin
    rows = client.get("/api/stays", params={"date": checkin}, headers=AUTH)
    assert any(item["id"] == booking["id"] for item in rows.json()["items"])
    cancelled = post(
        client,
        "cancel",
        {
            "session_id": session,
            "kind": "stay",
            "booking_id": booking["id"],
            "consent": True,
        },
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "cancelled"
    rows = client.get("/api/stays", params={"date": checkin}, headers=AUTH)
    assert not any(
        item["id"] == booking["id"] and item["status"] == "confirmed"
        for item in rows.json()["items"]
    )
    bad_kind = post(client, "prepare", {"session_id": session, "kind": "unknown"})
    assert bad_kind.status_code == 400
    assert not client.app.state.demo_sessions.sessions[session].busy
