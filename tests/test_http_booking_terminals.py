"""Canonical booking actions do not spend another provider request."""

import base64
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.booking.demo_stay import DemoStayAdapter
from app.booking.tools import Dispatcher
from app.providers.errors import RateLimitedError
from app.languages import CONSENT
from tests.test_product_demo import (
    AUTH,
    SimpleLlm,
    call,
    install_backend,
    send,
    start,
)
from tests.test_product_demo import client as demo_client

client = demo_client


@pytest.mark.parametrize("kind", ["slot", "stay"])
@pytest.mark.parametrize("language", ["et", "en"])
def test_prepare_consent_cancel_use_one_model_request(client, tmp_path, kind, language):
    if kind == "slot":
        day, records, writes = install_backend(client, tmp_path)
        name, args = "plan_demo_booking", {"date": day, "start_time": "10:00"}
    else:
        adapter = DemoStayAdapter(str(tmp_path / "stay.db"))
        client.app.state.stack.update(stay=adapter, dispatcher=Dispatcher(stay=adapter))
        day = datetime.now(ZoneInfo("Europe/Tallinn")).date() + timedelta(days=12)
        name, args = (
            "plan_demo_stay",
            {
                "checkin": day.isoformat(),
                "checkout": (day + timedelta(days=2)).isoformat(),
                "adults": 2,
                "children": 0,
                "room_type": "garden-double",
            },
        )

    class OnlyPlanning:
        calls = 0

        def chat(self, messages, tools=None):
            self.calls += 1
            if self.calls > 1:
                raise RateLimitedError("PRIVATE provider rate limit")
            return call(name, args)

    model = OnlyPlanning()
    client.app.state.stack["llm_primary"] = model
    session = start(client)
    request = (
        "Please prepare a test booking."
        if language == "en"
        else "Palun valmista testbroneering ette."
    )
    prepared = send(client, session, request, language=language).json()
    assert prepared["outcome"] == "tools_ok" and prepared["warnings"] == []
    assert prepared["booking_ids"] == prepared["booking_changes"] == []
    assert CONSENT[language] in prepared["reply"]
    assert base64.b64decode(prepared["audio_b64"]).decode() == prepared["reply"]
    state = client.app.state.demo_sessions.sessions[session].tools
    assert not state.pending["delivery"] and not state.pending["approved"]
    assert prepared["recap_delivery_id"], (
        "synthesis did not issue its delivery assertion"
    )
    assert model.calls == 1

    confirmed = send(
        client,
        session,
        CONSENT[language],
        language=language,
        recap_delivery_id=prepared["recap_delivery_id"],
    ).json()
    assert confirmed["outcome"] == "tools_ok" and confirmed["warnings"] == []
    assert len(confirmed["booking_changes"]) == 1
    assert confirmed["booking_changes"][0]["action"] == "confirmed"
    assert model.calls == 1 and confirmed["timings_ms"]["llm"] == 0
    if kind == "slot":
        assert len(records) == 1

    request = (
        "Please cancel this test booking."
        if language == "en"
        else "Palun tühista see testbroneering."
    )
    cancelled = send(client, session, request, language=language).json()
    assert cancelled["outcome"] == "tools_ok" and cancelled["warnings"] == []
    assert cancelled["booking_changes"][0]["action"] == "cancelled"
    assert model.calls == 1 and cancelled["timings_ms"]["llm"] == 0
    if kind == "slot":
        assert not records
    assert "PRIVATE" not in str((prepared, confirmed, cancelled))


@pytest.mark.parametrize(
    "next_turn", ["Ei, ära kinnita.", "Jah, võib-olla.", "Kas see on päris spaa?"]
)
def test_terminal_shortcut_requires_trusted_later_consent(client, tmp_path, next_turn):
    day, records, writes = install_backend(client, tmp_path)

    class Planning:
        def chat(self, messages, tools=None):
            return call("plan_demo_booking", {"date": day, "start_time": "10:00"})

    client.app.state.stack["llm_primary"] = Planning()
    session = start(client)
    assert (
        send(client, session, "Palun valmista testbroneering ette.").json()["outcome"]
        == "tools_ok"
    )
    client.app.state.stack["llm_primary"] = SimpleLlm(error=RateLimitedError("PRIVATE"))
    result = send(client, session, next_turn).json()
    assert not records and not writes
    assert result["booking_changes"] == []
    assert client.app.state.demo_sessions.sessions[session].tools.pending is None


def test_failed_recap_audio_does_not_enable_terminal_confirmation(client, tmp_path):
    day, records, writes = install_backend(client, tmp_path)

    class Planning:
        def chat(self, messages, tools=None):
            return call("plan_demo_booking", {"date": day, "start_time": "10:00"})

    class FailedSpeech:
        def synthesize(self, text):
            raise RuntimeError("PRIVATE audio failure")

    client.app.state.stack.update(llm_primary=Planning(), tts=FailedSpeech())
    session = start(client)
    prepared = send(client, session, "Palun valmista testbroneering ette.").json()
    assert prepared["tts_failed"] and prepared["recap_delivery_id"]
    state = client.app.state.demo_sessions.sessions[session].tools
    assert state.pending and not state.pending["delivery"]
    client.app.state.stack["llm_primary"] = SimpleLlm(error=RateLimitedError("PRIVATE"))
    result = client.post(
        "/api/turn",
        json={"session_id": session, "text": "Jah, kinnitan."},
        headers=AUTH,
    ).json()
    assert result["booking_changes"] == [] and not records and not writes


@pytest.mark.parametrize("language", ["et", "en"])
def test_missing_room_choice_returns_backend_options_without_model_followup(
    client, tmp_path, language
):
    adapter = DemoStayAdapter(str(tmp_path / "stay.db"))
    client.app.state.stack.update(stay=adapter, dispatcher=Dispatcher(stay=adapter))
    day = datetime.now(ZoneInfo("Europe/Tallinn")).date() + timedelta(days=12)

    class Planning:
        calls = 0

        def chat(self, messages, tools=None):
            self.calls += 1
            if self.calls > 1:
                raise RateLimitedError("PRIVATE")
            return call(
                "plan_demo_stay",
                {
                    "checkin": day.isoformat(),
                    "checkout": (day + timedelta(days=2)).isoformat(),
                    "adults": 2,
                    "children": 0,
                },
            )

    model = Planning()
    client.app.state.stack["llm_primary"] = model
    session = start(client)
    request = "Please find a demo room." if language == "en" else "Palun otsi demotube."
    result = send(client, session, request, language=language).json()
    assert model.calls == 1 and result["outcome"] == "tools_ok"
    question = (
        "Which room type would you prefer?"
        if language == "en"
        else "Millist toatüüpi eelistad?"
    )
    assert question in result["reply"]
    assert result["warnings"] == [] and result["booking_changes"] == []
    assert client.app.state.demo_sessions.sessions[session].tools.pending is None
