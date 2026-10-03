"""Direct controls cannot authorize a replacement with an old recap receipt."""

import asyncio
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from tests.test_booking_web import client, post, start  # noqa: F401


def prepare(client):
    session = start(client)
    day = datetime.now(ZoneInfo("Europe/Tallinn")).date() + timedelta(days=20)
    search = post(
        client,
        "search",
        {
            "session_id": session,
            "kind": "stay",
            "checkin": day.isoformat(),
            "checkout": (day + timedelta(days=1)).isoformat(),
            "adults": 2,
            "children": 0,
            "room_type": "spa-suite",
        },
    )
    assert search.status_code == 200, search.text
    offer = search.json()["offers"][0]
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
    return session, prepared.json()


def test_hold_id_alone_does_not_acknowledge_the_current_proposal(client):
    session, prepared = prepare(client)
    acknowledged = post(
        client,
        "recap",
        {
            "session_id": session,
            "hold_id": prepared["hold_id"],
        },
    )
    assert acknowledged.status_code == 400
    assert not client.app.state.demo_sessions.sessions[session].tools.pending[
        "delivery"
    ]


def test_receipt_is_one_use_and_exact_preparation_owned(client):
    session, prepared = prepare(client)
    assert isinstance(prepared.get("recap_delivery_id"), str)
    body = {
        "session_id": session,
        "hold_id": prepared["hold_id"],
        "recap_delivery_id": prepared["recap_delivery_id"],
    }
    assert post(client, "recap", body).status_code == 200
    assert post(client, "recap", body).status_code == 409


@pytest.mark.parametrize("change", ["language", "recap_text"])
def test_receipt_cannot_acknowledge_changed_text_on_the_same_pending_object(
    client, change
):
    session, prepared = prepare(client)
    state = client.app.state.demo_sessions.sessions[session]
    pending = state.tools.pending
    if change == "language":
        state.tools.language = "en"
    else:
        pending["recap"]["guest_name"] = "Demo Teine"
    assert state.tools.pending is pending
    response = post(
        client,
        "recap",
        {
            "session_id": session,
            "hold_id": prepared["hold_id"],
            "recap_delivery_id": prepared["recap_delivery_id"],
        },
    )
    assert response.status_code == 409
    assert not pending["delivery"]


def test_old_receipt_cannot_acknowledge_same_hold_reprepared_by_voice_tools(client):
    session, prepared = prepare(client)
    state = client.app.state.demo_sessions.sessions[session]
    old = state.tools.pending
    result = asyncio.run(
        state.tools.dispatch(
            "prepare_demo_stay",
            {
                "hold_id": prepared["hold_id"],
                "guest_fixture_id": "guest-002",
            },
        )
    )
    assert result.get("ok") is True, result
    assert state.tools.pending is not old
    assert state.tools.pending["hold_id"] == prepared["hold_id"]
    acknowledged = post(
        client,
        "recap",
        {
            "session_id": session,
            "hold_id": prepared["hold_id"],
            "recap_delivery_id": prepared.get("recap_delivery_id", "0" * 32),
        },
    )
    assert acknowledged.status_code == 409
    assert not state.tools.pending["delivery"]
    denied = post(
        client,
        "confirm",
        {
            "session_id": session,
            "kind": "stay",
            "hold_id": prepared["hold_id"],
            "consent": True,
        },
    )
    assert denied.status_code == 409


@pytest.mark.parametrize("receipt", [False, [], "not-an-id", "f" * 33])
def test_malformed_receipt_fails_before_any_delivery(client, receipt):
    session, prepared = prepare(client)
    acknowledged = post(
        client,
        "recap",
        {
            "session_id": session,
            "hold_id": prepared["hold_id"],
            "recap_delivery_id": receipt,
        },
    )
    assert acknowledged.status_code == 400
    assert not client.app.state.demo_sessions.sessions[session].tools.pending[
        "delivery"
    ]
