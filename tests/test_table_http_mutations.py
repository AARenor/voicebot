"""HTTP turn adapter applies its existing mutation limit to table operations."""

import asyncio
from types import SimpleNamespace

import pytest

from app.hackathon import _TurnTools


@pytest.mark.parametrize("name", ["confirm_table_booking", "cancel_table_booking"])
def test_second_table_write_is_not_sent_to_native_policy(name):
    class Native:
        calls = 0

        async def dispatch(self, name, arguments):
            self.calls += 1
            return {"error": "write_outcome_unknown"}

    native = Native()
    tools = _TurnTools(SimpleNamespace(tools=native, booking_details={}))
    first = asyncio.run(tools.dispatch(name, {}))
    second = asyncio.run(tools.dispatch(name, {}))
    assert first["error"] == "write_outcome_unknown"
    assert second["error"] == "mutation_retry_forbidden"
    assert native.calls == 1


@pytest.mark.parametrize("name", ["confirm_table_booking", "cancel_table_booking"])
def test_exception_during_table_write_never_looks_safely_retryable(name):
    class Native:
        async def dispatch(self, name, arguments):
            raise RuntimeError("PRIVATE synthetic failure")

    tools = _TurnTools(SimpleNamespace(tools=Native(), booking_details={}))
    result = asyncio.run(tools.dispatch(name, {}))
    assert result == {"error": "mutation_outcome_unknown"}
    assert "PRIVATE" not in str(tools.results)


def test_authoritative_table_receipt_survives_as_browser_readback_metadata():
    booking = {
        "id": "table_" + "a" * 32,
        "kind": "table",
        "date": "2026-12-01",
        "start": "2026-12-01T18:00:00+02:00",
        "party_size": 4,
    }

    class Native:
        async def dispatch(self, name, arguments):
            return {"ok": True, "booking": booking}

    session = SimpleNamespace(tools=Native(), booking_details={})
    tools = _TurnTools(session)
    asyncio.run(tools.dispatch("confirm_table_booking", {"hold_id": "fixture"}))
    assert tools.changes == [
        {
            "action": "confirmed",
            "id": booking["id"],
            "kind": "table",
            "date": "2026-12-01",
            "start_local": "2026-12-01 18:00:00",
            "timezone": "Europe/Tallinn",
        }
    ]
