"""Actual startup defaults are restaurant-only even with legacy credentials."""

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from app.server import build_stack


def test_default_runtime_ignores_legacy_booking_credentials(tmp_path):
    with patch.dict(
        "os.environ",
        {
            "RESTAURANT_STATE_DB": str(tmp_path / "tables.db"),
            "EASY_BASE_URL": "https://fixture.invalid",
            "EASY_API_KEY": "fixture",
            "EASY_DEMO_WRITES": "1",
            "EASY_STATE_DB": str(tmp_path / "legacy.db"),
            "STAY_DEMO_WRITES": "1",
            "STAY_STATE_DB": str(tmp_path / "stays.db"),
            "ZENOTI_API_KEY": "fixture",
            "CLOUDBEDS_API_KEY": "fixture",
        },
        clear=True,
    ):
        stack = build_stack()
    assert stack.get("business") == "restaurant"
    assert stack["table"].operational
    assert stack["slot"] is None and stack["stay"] is None
    assert stack["booking_reader"] is None
    assert not (tmp_path / "legacy.db").exists()
    assert not (tmp_path / "stays.db").exists()
    assert stack["dispatcher"].business == "restaurant"
    names = {tool["function"]["name"] for tool in stack["dispatcher"].available_tools()}
    assert "search_tables" in names
    assert not names & {
        "search_slots",
        "search_availability",
        "confirm_slot_booking",
        "confirm_booking",
    }
    # This adapter opens and closes a connection per transaction; no close hook.


def test_missing_restaurant_storage_fails_closed_not_to_legacy(tmp_path):
    path = tmp_path / "not-a-directory"
    path.write_text("fixture")
    with patch.dict(
        "os.environ",
        {
            "RESTAURANT_STATE_DB": str(path / "tables.db"),
            "EASY_BASE_URL": "https://fixture.invalid",
            "EASY_API_KEY": "fixture",
            "EASY_DEMO_WRITES": "1",
            "ZENOTI_API_KEY": "fixture",
        },
        clear=True,
    ):
        stack = build_stack()
    assert stack.get("business") == "restaurant"
    assert stack["table"] is None
    assert stack["slot"] is None and stack["stay"] is None
    assert stack["dispatcher"].business == "restaurant"
    assert not stack["dispatcher"].available_tools()


def test_invalid_business_configuration_never_enables_legacy():
    with patch.dict("os.environ", {"VOICEBOT_BUSINESS": "restarant"}, clear=True):
        with pytest.raises(ValueError, match="business"):
            build_stack()


def test_native_entrypoint_has_no_legacy_booking_construction():
    source = Path("app/worker.py").read_text()
    entrypoint = source[source.index("async def entrypoint(") :]
    assert "DemoTableAdapter(" in entrypoint
    assert 'business="restaurant"' in entrypoint
    assert "EasyAppointmentsAdapter(" not in entrypoint
    assert "DemoStayAdapter(" not in entrypoint


def test_native_cleanup_deletes_its_room_without_an_adapter_close_hook(tmp_path):
    pytest.importorskip("livekit.agents")
    from app.booking.demo_table import DemoTableAdapter
    from app.worker import cleanup_call

    delete = AsyncMock()
    ctx = SimpleNamespace(
        room=SimpleNamespace(name="fixture-owned-room"),
        api=SimpleNamespace(room=SimpleNamespace(delete_room=delete)),
        shutdown=Mock(),
    )
    adapter = DemoTableAdapter(str(tmp_path / "tables.db"))
    asyncio.run(cleanup_call(ctx, None, adapter))
    delete.assert_awaited_once()
    assert delete.call_args.args[0].room == "fixture-owned-room"
    ctx.shutdown.assert_called_once()
