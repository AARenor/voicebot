"""Website synthesis is not delivery of a recap to a consenting operator."""

import asyncio
import base64

import pytest

from tests.test_product_demo import (
    AUTH,
    CONSENT,
    BookingLlm,
    client,
    install_backend,
    start,
)


def post(client, session_id, text, receipt=None):
    body = {"session_id": session_id, "text": text}
    if receipt is not None:
        body["recap_delivery_id"] = receipt
    return client.post("/api/turn", json=body, headers=AUTH)


def prepare(client, tmp_path, **options):
    day, records, writes = install_backend(client, tmp_path, **options)
    client.app.state.stack["llm_primary"] = BookingLlm(day)
    session_id = start(client)
    response = post(client, session_id, "Soovin testbroneeringut")
    assert response.status_code == 200
    return session_id, response.json(), records, writes


def test_start_session_returns_spoken_greeting_without_a_model_turn(client):
    result = client.post("/api/demo/session", headers=AUTH)
    assert result.status_code == 200
    data = result.json()
    assert base64.b64decode(data.get("audio_b64", "")).decode() == data["greeting"]
    assert not client.app.state.stack["llm_primary"].messages


def test_http_synthesized_recap_without_playback_cannot_authorize_a_write(
    client, tmp_path
):
    session_id, prepared, records, writes = prepare(client, tmp_path)
    assert prepared["audio_b64"]
    assert post(client, session_id, CONSENT).status_code == 200
    assert not records and not writes, "synthesis was treated as browser playback"


def test_delivery_receipt_then_new_explicit_consent_authorizes_one_owned_write(
    client, tmp_path
):
    session_id, prepared, records, writes = prepare(client, tmp_path)
    session = client.app.state.demo_sessions.sessions[session_id]
    assert (
        not session.tools.pending["delivery"] and not session.tools.pending["approved"]
    )
    receipt = prepared["recap_delivery_id"]
    assert isinstance(receipt, str) and len(receipt) == 32
    result = post(client, session_id, CONSENT, receipt)
    assert result.status_code == 200 and result.json()["booking_ids"] == ["42"]
    assert (
        records
        and sum(
            r.method == "POST" and r.url.path.endswith("/appointments") for r in writes
        )
        == 1
    )
    assert session.recap_delivery is None


@pytest.mark.parametrize(
    "text", ["Ei, ära kinnita.", "Jah, kinnitan. Ei, ära kinnita.", "Võib-olla", "jah"]
)
def test_receipt_never_substitutes_for_unambiguous_final_consent(
    client, tmp_path, text
):
    session_id, prepared, records, writes = prepare(client, tmp_path)
    result = post(client, session_id, text, prepared["recap_delivery_id"])
    assert result.status_code == 200
    assert not records and not writes and not result.json()["booking_changes"]


@pytest.mark.parametrize(
    "reason", ["foreign_session", "wrong_receipt", "new_preparation", "expired"]
)
def test_stale_foreign_or_expired_receipt_cannot_authorize_a_write(
    client, tmp_path, reason
):
    session_id, prepared, records, writes = prepare(client, tmp_path)
    session = client.app.state.demo_sessions.sessions[session_id]
    receipt = prepared["recap_delivery_id"]
    if reason == "foreign_session":
        session_id = start(client)
    elif reason == "wrong_receipt":
        receipt = "0" * 32
    elif reason == "new_preparation":
        assert asyncio.run(
            session.tools.prepare_demo_booking(session.tools.pending["hold_id"])
        )["ok"]
    else:
        session.tools.pending["expires_at"] = 0
    result = post(client, session_id, CONSENT, receipt)
    assert result.status_code == 200
    assert not records and not writes and not result.json()["booking_changes"]


@pytest.mark.parametrize("receipt", [True, [], {}, "not-a-receipt", "a" * 33])
def test_malformed_receipt_rejected_before_paid_providers(client, receipt):
    session_id = start(client)
    spoken = len(client.app.state.stack["tts"].spoken)
    result = post(client, session_id, CONSENT, receipt)
    assert result.status_code == 400
    assert not client.app.state.stack["llm_primary"].messages
    assert len(client.app.state.stack["tts"].spoken) == spoken


def test_failed_greeting_keeps_text_session_available_without_model_call(client):
    class FailingTts:
        def synthesize(self, text):
            raise RuntimeError("fixture unavailable")

    client.app.state.stack["tts"] = FailingTts()
    result = client.post("/api/demo/session", headers=AUTH)
    assert result.status_code == 200 and result.json()["greeting"].startswith("Tere!")
    assert result.json()["tts_failed"] and not result.json()["audio_b64"]
    assert not client.app.state.stack["llm_primary"].messages


def test_unknown_write_with_valid_delivery_stays_sticky_without_blind_retry(
    client, tmp_path
):
    session_id, prepared, records, writes = prepare(client, tmp_path, unknown=True)
    result = post(client, session_id, CONSENT, prepared["recap_delivery_id"])
    assert result.json()["outcome"] == "unknown_outcome"
    assert (
        records
        and sum(
            r.method == "POST" and r.url.path.endswith("/appointments") for r in writes
        )
        == 1
    )
    client.app.state.stack["llm_primary"] = BookingLlm("2099-01-01")
    result = post(client, session_id, CONSENT, prepared["recap_delivery_id"])
    assert result.json()["outcome"] == "unknown_outcome"
    assert (
        sum(r.method == "POST" and r.url.path.endswith("/appointments") for r in writes)
        == 1
    )


@pytest.mark.parametrize(
    "receipt_kind", ["missing", "valid", "foreign", "stale", "expired", "negative"]
)
def test_stay_http_delivery_receipt_is_preparation_owned_and_preserves_metadata(
    client, tmp_path, receipt_kind
):
    from app.booking.demo_stay import DemoStayAdapter
    from app.booking.tools import Dispatcher
    from tests.test_stay_call_tools import prepared
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    import json

    stay = DemoStayAdapter(str(tmp_path / "stay.db"))
    client.app.state.stack.update(stay=stay, dispatcher=Dispatcher(stay=stay))
    session_id = start(client)
    session = client.app.state.demo_sessions.sessions[session_id]
    day = datetime.now(ZoneInfo("Europe/Tallinn")).date() + timedelta(days=15)
    search = {
        "checkin": day.isoformat(),
        "checkout": (day + timedelta(days=2)).isoformat(),
        "adults": 2,
    }
    ready = asyncio.run(prepared(session.tools, search))

    class StayLlm:
        preparing = True

        def chat(self, messages, tools=None):
            if messages[-1]["role"] == "tool":
                return {"content": "Tere!"}
            context = json.loads(
                messages[0]["content"].split("Server-owned state: ", 1)[1]
            )
            if self.preparing:
                self.preparing = False
                name, args = "prepare_demo_stay", {"hold_id": ready["hold_id"]}
            elif context["booking_ids"]:
                name, args = "cancel_booking", {"booking_id": context["booking_ids"][0]}
            else:
                name, args = "confirm_booking", {"hold_id": ready["hold_id"]}
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": "fixture",
                        "type": "function",
                        "function": {"name": name, "arguments": json.dumps(args)},
                    }
                ],
            }

    # Speak the actual pending recap, but do not execute a confirmation yet.
    client.app.state.stack["llm_primary"] = StayLlm()
    response = post(client, session_id, "Loe kokkuvõte")
    assert response.status_code == 200
    receipt = response.json().get("recap_delivery_id")
    assert receipt and not session.tools.pending["delivery"]
    if receipt_kind == "missing":
        receipt = None
    elif receipt_kind == "foreign":
        session_id = start(client)
    elif receipt_kind == "stale":
        assert asyncio.run(session.tools.prepare_demo_stay(ready["hold_id"]))["ok"]
    elif receipt_kind == "expired":
        session.tools.pending["expires_at"] = 0
    result = post(
        client,
        session_id,
        "Ei, ära kinnita." if receipt_kind == "negative" else CONSENT,
        receipt,
    )
    assert result.status_code == 200
    booked = asyncio.run(stay.get_operator_bookings())["items"]
    if receipt_kind != "valid":
        assert not booked and not result.json()["booking_changes"]
        return
    assert len(booked) == 1
    change = result.json()["booking_changes"][0]
    assert change["kind"] == "stay" and change["date"] == search["checkin"]
    assert change["id"] == booked[0]["id"] and change["id"].startswith("stay_")
    cancelled = post(client, session_id, "Jah, tühista.")
    assert (
        cancelled.status_code == 200
        and cancelled.json()["booking_changes"][0]["action"] == "cancelled"
    )
    remaining = asyncio.run(stay.get_operator_bookings())["items"]
    assert len(remaining) == 1 and remaining[0]["status"] == "cancelled"
