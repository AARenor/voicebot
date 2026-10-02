import asyncio
from unittest.mock import patch

import pytest

from app.telephone import CallTools, validate_environment, safe_speech
from app.booking.tools import (
    TOOL_SEARCH_SLOTS,
    TOOL_HOLD_SLOT,
    TOOL_CONFIRM_SLOT,
    TOOL_CANCEL_SLOT,
    TOOL_CATALOGUE,
    TOOL_FAQ,
)


class Slots:
    def __init__(self):
        self.calls = []

    def available_tools(self):
        return [
            TOOL_SEARCH_SLOTS,
            TOOL_HOLD_SLOT,
            TOOL_CONFIRM_SLOT,
            TOOL_CANCEL_SLOT,
            TOOL_CATALOGUE,
            TOOL_FAQ,
        ]

    async def dispatch(self, name, args):
        self.calls.append((name, args))
        if name == "hold_slot":
            return {"hold_id": "owned-hold"}
        if name == "confirm_slot_booking":
            return {"ok": True, "booking": {"id": "owned-booking"}}
        return {"ok": True}


ENV = {
    k: "fixture"
    for k in (
        "LIVEKIT_API_KEY",
        "LIVEKIT_API_SECRET",
        "GROQ_API_KEY",
        "AZURE_SPEECH_KEY",
        "AZURE_REGION",
    )
}
ENV.update(
    LIVEKIT_URL="ws://localhost:7880",
    VOICEBOT_TELEPHONE_DEMO="1",
    EASY_DEMO_WRITES="1",
    EASY_BASE_URL="http://localhost",
    EASY_API_KEY="fixture",
    EASY_STATE_DB="/data/journal.db",
)


def test_settings_fail_closed():
    validate_environment(ENV)
    for k in ENV:
        with pytest.raises(ValueError):
            validate_environment({n: v for n, v in ENV.items() if n != k})
    with pytest.raises(ValueError):
        validate_environment({**ENV, "VOICEBOT_TELEPHONE_DEMO": "0"})


def test_call_ownership_and_server_write_keys():
    async def run():
        d = Slots()
        a, b = CallTools(d), CallTools(d)
        assert "faq" not in a.names
        assert (await a.dispatch("confirm_slot_booking", {"hold_id": "foreign"}))[
            "error"
        ] == "not_owned"
        assert not d.calls
        assert (await a.dispatch("confirm_slot_booking", {"hold_id": []}))[
            "error"
        ] == "not_owned"
        assert (await a.dispatch("cancel_slot_booking", {"booking_id": []}))[
            "error"
        ] == "not_owned"
        await a.dispatch(
            "hold_slot", {"slot_id": "fixture", "idempotency_key": "untrusted"}
        )
        assert (await b.dispatch("confirm_slot_booking", {"hold_id": "owned-hold"}))[
            "error"
        ] == "not_owned"
        guest = {
            "firstName": "Demo",
            "lastName": "Guest",
            "email": "demo@example.test",
            "phone": "55512345",
        }
        assert (
            await a.dispatch(
                "confirm_slot_booking",
                {"hold_id": "owned-hold", "guest": {**guest, "customerId": 1}},
            )
        )["error"] == "not_owned"
        args = {"hold_id": "owned-hold", "guest": guest, "idempotency_key": "untrusted"}
        first = await a.dispatch("confirm_slot_booking", args)
        key = d.calls[-1][1]["idempotency_key"]
        before = len(d.calls)
        assert await a.dispatch("confirm_slot_booking", args) == first
        assert len(d.calls) == before
        assert d.calls[-1][1]["idempotency_key"] == key
        assert d.calls[-1][1]["idempotency_key"] != "untrusted"
        assert (
            await b.dispatch("cancel_slot_booking", {"booking_id": "owned-booking"})
        )["error"] == "not_owned"
        assert (
            await a.dispatch("cancel_slot_booking", {"booking_id": "owned-booking"})
        )["ok"]

    asyncio.run(run())


def test_tool_errors_are_closed():
    async def run():
        d = Slots()

        async def fail(*args):
            raise RuntimeError("PII or credentials")

        d.dispatch = fail
        result = await CallTools(d).dispatch("search_slots", {})
        assert result == {"error": "booking_unavailable"}

    asyncio.run(run())


def test_price_guard_runs_before_audio():
    assert "120" not in safe_speech("See maksab 120 eurot.", [])
    assert safe_speech("Tere!", []) == "Tere!"
    assert "120" not in safe_speech("Hind on 120 EUR.", [{"quoted_total": "120"}])
    assert "kakskümmend" not in safe_speech("See maksab sada kakskümmend eurot.", [])


def test_sdk_tools_delegate_without_new_business_logic():
    pytest.importorskip("livekit.agents")
    from app.telephone import sdk_tools

    d = Slots()
    state = CallTools(d)
    search = next(s for s in state.schemas if s["name"] == "search_slots")
    assert "provider" in search["parameters"]["required"]
    tools = sdk_tools(state)
    assert len(tools) == 5
    asyncio.run(tools[0]({"service": "1", "provider": "2", "date": "2026-10-05"}))
    assert d.calls[0][0] == "search_slots"
