"""Speech-input spa inquiries ask for missing fields without fabricated writes."""

import base64
from datetime import datetime, timedelta
from unittest.mock import Mock
from zoneinfo import ZoneInfo

import pytest

from app.booking.tools import Dispatcher
from app.telephone import ASK_TIME
from tests.test_demo_plan import LiveSlots
from tests.test_product_demo import AUTH, SimpleLlm, call, send, start
from tests.test_product_demo import client as client


@pytest.mark.parametrize("audio_input", [False, True])
@pytest.mark.parametrize("word", ["broneerida", "bruneerida"])
def test_greeting_prefixed_spa_inquiry_is_a_safe_question(client, audio_input, word):
    phrase = f"Tere, tahaks homme {word} spaad?"
    model = SimpleLlm(error=AssertionError("clarification must not call provider"))
    stt = Mock()
    stt.transcribe.return_value = phrase
    client.app.state.stack.update(llm_primary=model, stt=stt)
    session = start(client)
    payload = {"session_id": session, "language": "et"}
    payload.update(
        {"audio_b64": base64.b64encode(b"fixture-speech").decode()}
        if audio_input
        else {"text": phrase}
    )
    response = client.post("/api/turn", json=payload, headers=AUTH)
    assert response.status_code == 200
    result = response.json()
    assert result["reply"] == ASK_TIME
    assert result["text_heard"] == phrase
    assert result["input_status"] == ("recognized" if audio_input else "typed")
    assert result["outcome"] == "ok" and result["warnings"] == []
    assert not result["fallback_used"]
    assert result["tools_used"] == 0
    assert result["booking_ids"] == result["booking_changes"] == []
    assert result["timings_ms"]["llm"] == 0 and model.messages == []
    assert base64.b64decode(result["audio_b64"]).decode() == ASK_TIME
    if audio_input:
        stt.transcribe.assert_called_once_with(b"fixture-speech", language="et")
    else:
        stt.transcribe.assert_not_called()


def test_spoken_typo_inquiry_keeps_tomorrow_for_later_time_and_consent(client):
    day = (
        (datetime.now(ZoneInfo("Europe/Tallinn")) + timedelta(days=1))
        .date()
        .isoformat()
    )
    backend = LiveSlots()
    backend.slots[0].update(date=day, start=day + " 10:30:00")
    stt = Mock()
    stt.transcribe.return_value = "Tere, tahaks homme bruneerida spaad?"

    class Planning:
        calls = 0

        def chat(self, messages, tools=None):
            self.calls += 1
            assert self.calls == 1
            assert day in messages[0]["content"]
            assert "10:30" in messages[0]["content"]
            return call("plan_demo_booking", {"date": day, "start_time": "10:30"})

    model = Planning()
    client.app.state.stack.update(
        dispatcher=Dispatcher(slot=backend),
        stt=stt,
        llm_primary=model,
    )
    session = start(client)
    response = client.post(
        "/api/turn",
        headers=AUTH,
        json={
            "session_id": session,
            "language": "et",
            "audio_b64": base64.b64encode(b"fixture-speech").decode(),
        },
    )
    assert response.json()["reply"] == ASK_TIME
    assert model.calls == 0 and backend.calls == []
    prepared = send(client, session, "Kell 10:30.").json()
    assert prepared["outcome"] == "tools_ok"
    state = client.app.state.demo_sessions.sessions[session].tools
    assert prepared["reply"] == state.render_recap()
    assert state.pending["recap"]["date"] == day
    assert state.pending["recap"]["start"] == day + " 10:30:00"
    assert "10:30" in prepared["reply"]
    assert prepared["booking_ids"] == [] and model.calls == 1
    assert prepared["recap_delivery_id"]
    assert not state.pending["delivery"] and not state.pending["approved"]
    confirmed = send(client, session, "Jah, kinnitan.").json()
    assert confirmed["booking_changes"][0]["action"] == "confirmed"
    cancelled = send(client, session, "Palun tühista see testbroneering.").json()
    assert cancelled["booking_changes"][0]["action"] == "cancelled"
    assert model.calls == 1
    assert sum(name == "confirm" for name, _ in backend.calls) == 1
    assert sum(name == "cancel" for name, _ in backend.calls) == 1


def test_one_question_at_a_time_keeps_the_date_through_repeat_and_repair(client):
    day = (
        (datetime.now(ZoneInfo("Europe/Tallinn")) + timedelta(days=1))
        .date()
        .isoformat()
    )
    backend = LiveSlots()
    backend.slots[0].update(date=day, start=day + " 10:30:00")

    class Planning:
        calls = 0

        def chat(self, messages, tools=None):
            self.calls += 1
            assert self.calls == 1 and day in messages[0]["content"]
            assert "10:30" in messages[0]["content"]
            return call("plan_demo_booking", {"date": day, "start_time": "10:30"})

    model = Planning()
    client.app.state.stack.update(
        dispatcher=Dispatcher(slot=backend), llm_primary=model
    )
    session = start(client)
    for utterance, expected in [
        ("Aitäh, soovin broneerida spaad.", "Mis kuupäev sulle sobiks?"),
        ("Korda palun", "Mis kuupäev sulle sobiks?"),
        ("Homme.", "Mis kell sulle sobiks?"),
        ("See on segane", "Vabandust. Võtame ühe asja korraga. Mis kell sulle sobiks?"),
        ("Korda palun", "Mis kell sulle sobiks?"),
    ]:
        result = send(client, session, utterance).json()
        assert result["reply"] == expected
        assert base64.b64decode(result["audio_b64"]).decode() == expected
        assert result["tools_used"] == 0 and model.calls == 0 and backend.calls == []
        assert result["booking_changes"] == result["booking_ids"] == []
        assert not result["recap_delivery_id"]
    result = send(client, session, "Palun kell 10:30.").json()
    state = client.app.state.demo_sessions.sessions[session].tools
    assert result["reply"] == state.render_recap()
    assert state.pending["recap"]["date"] == day
    assert result["booking_changes"] == result["booking_ids"] == []
    assert not state.pending["delivery"] and not state.pending["approved"]
    assert model.calls == 1
    assert not any(name in {"confirm", "cancel"} for name, _ in backend.calls)
