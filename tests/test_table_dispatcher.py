"""Restaurant tool boundary with real adapters and explicit legacy controls."""

import asyncio
import importlib
import importlib.util
import inspect
import json
import sqlite3
from datetime import datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from app.booking.demo_stay import DemoStayAdapter
from app.booking.tools import Dispatcher, speak_offer
from app.providers.errors import ProviderError


TABLE_NAMES = {
    "get_table_catalogue",
    "search_tables",
    "hold_table",
    "confirm_table_booking",
    "cancel_table_booking",
}
LEGACY_NAMES = {
    "search_availability",
    "hold_offer",
    "confirm_booking",
    "cancel_booking",
    "get_stay_catalogue",
    "search_slots",
    "hold_slot",
    "confirm_slot_booking",
    "cancel_slot_booking",
    "get_slot_catalogue",
    "answer_faq",
}
GUEST = {
    "firstName": "Demo",
    "lastName": "Esimene",
    "email": "demo.esimene+tabletool01@example.invalid",
    "phone": "+12025550101",
}


def dispatcher(**kwargs):
    assert "table" in inspect.signature(Dispatcher).parameters, (
        "restaurant Dispatcher missing"
    )
    assert "business" in inspect.signature(Dispatcher).parameters, (
        "explicit business selector missing"
    )
    return Dispatcher(**kwargs)


@pytest.fixture
def table(tmp_path):
    assert importlib.util.find_spec("app.booking.demo_table") is not None, (
        "table adapter missing"
    )
    cls = importlib.import_module("app.booking.demo_table").DemoTableAdapter
    return cls(str(tmp_path / "restaurant.db"))


@pytest.fixture
def table_request():
    return {
        "date": (
            datetime.now(ZoneInfo("Europe/Tallinn")).date() + timedelta(days=10)
        ).isoformat(),
        "start_time": "16:00",
        "party_size": 2,
    }


def test_explicit_restaurant_never_falls_back_to_accidentally_wired_legacy(tmp_path):
    old = DemoStayAdapter(str(tmp_path / "stay.db"))
    state = dispatcher(
        business="restaurant",
        stay=old,
        slot=SimpleNamespace(operational=True),
        faq=lambda q: [],
    )
    assert state.business == "restaurant"
    assert state.available_tools() == []

    async def run():
        for name in LEGACY_NAMES | TABLE_NAMES:
            with pytest.raises(ProviderError):
                await state.dispatch(name, {})
        with pytest.raises(ProviderError):
            await state.get_stay_hold("hold_" + "f" * 32)
        with pytest.raises(ProviderError):
            await state.get_table_hold("hold_" + "f" * 32)

    asyncio.run(run())


def test_operational_table_schemas_are_strict_and_do_not_default_headcount(
    table, tmp_path
):
    old = DemoStayAdapter(str(tmp_path / "stay.db"))
    state = dispatcher(
        table=table,
        business="restaurant",
        stay=old,
        slot=SimpleNamespace(operational=True),
    )
    schemas = {
        tool["function"]["name"]: tool["function"]["parameters"]
        for tool in state.available_tools()
    }
    assert set(schemas) == TABLE_NAMES
    assert all(s["additionalProperties"] is False for s in schemas.values())
    assert schemas["search_tables"]["required"] == ["date", "start_time", "party_size"]
    party = schemas["search_tables"]["properties"]["party_size"]
    assert (
        party["type"] == "integer" and party["minimum"] == 1 and party["maximum"] == 6
    )
    assert "default" not in party
    assert "table_offer_id" in schemas["hold_table"]["required"]


@pytest.mark.parametrize("table", [None, SimpleNamespace(operational=False)])
def test_nonoperational_restaurant_adapter_is_hidden_and_dispatch_fails_closed(table):
    state = dispatcher(table=table, business="restaurant")
    assert state.available_tools() == []
    with pytest.raises(ProviderError):
        asyncio.run(state.dispatch("get_table_catalogue", {}))


def test_unset_business_preserves_explicit_legacy_and_infers_table_only(
    table, tmp_path
):
    old = DemoStayAdapter(str(tmp_path / "stay.db"))
    legacy = dispatcher(stay=old)
    assert legacy.business == "legacy"
    assert {t["function"]["name"] for t in legacy.available_tools()} == {
        "get_stay_catalogue",
        "search_availability",
        "hold_offer",
        "confirm_booking",
        "cancel_booking",
    }
    assert Dispatcher().available_tools() == []
    restaurant = dispatcher(table=table)
    assert restaurant.business == "restaurant"
    assert {t["function"]["name"] for t in restaurant.available_tools()} == TABLE_NAMES
    explicit_legacy = dispatcher(table=table, stay=old, business="legacy")
    assert all(
        t["function"]["name"] not in TABLE_NAMES
        for t in explicit_legacy.available_tools()
    )
    with pytest.raises(ProviderError):
        asyncio.run(explicit_legacy.dispatch("get_table_catalogue", {}))


@pytest.mark.parametrize("business", ["spa", "hotel", "", False])
def test_unknown_explicit_business_does_not_select_any_adapter(business):
    with pytest.raises(ValueError):
        dispatcher(business=business)


def test_full_table_contract_and_trusted_hold_read(table, table_request):
    async def run():
        state = dispatcher(table=table, business="restaurant")
        assert (await state.dispatch("get_table_catalogue", {}))["venue"][
            "name"
        ] == "Meretuule restoran"
        searched = await state.dispatch("search_tables", json.dumps(table_request))
        assert searched["kind"] == "table" and len(searched["offers"]) == 1
        offer = searched["offers"][0]
        with pytest.raises(ProviderError):
            speak_offer(offer)
        held = await state.dispatch(
            "hold_table", {"table_offer_id": offer["table_offer_id"]}
        )
        assert held["table_offer_id"] == offer["table_offer_id"]
        assert held["kind"] == "table" and held["quoted_total"] is None
        assert "price_quote_id" not in held
        owned = await state.get_table_hold(held["hold_id"])
        assert owned.payload["recap"] == held["recap"]
        assert datetime.fromisoformat(held["expires_at"]).tzinfo is not None
        confirmed = await state.dispatch(
            "confirm_table_booking",
            {
                "hold_id": held["hold_id"],
                "guest": GUEST,
                "idempotency_key": "table-tool-once",
            },
        )
        assert confirmed["ok"] and confirmed["booking"]["kind"] == "table"
        assert await state.get_table_hold(held["hold_id"]) is None
        assert (
            await state.dispatch(
                "confirm_table_booking",
                {
                    "hold_id": held["hold_id"],
                    "guest": GUEST,
                    "idempotency_key": "table-tool-once",
                },
            )
            == confirmed
        )
        cancelled = await state.dispatch(
            "cancel_table_booking", {"booking_id": confirmed["booking_id"]}
        )
        assert cancelled["ok"] and cancelled["status"] == "cancelled"

    asyncio.run(run())


@pytest.mark.parametrize(
    "field,value",
    [
        ("party_size", True),
        ("party_size", "2"),
        ("party_size", 2.0),
        ("party_size", 0),
        ("party_size", 7),
        ("date", "20261005"),
        ("date", "2026-1-05"),
        ("start_time", "16:0"),
        ("start_time", "16:00:00"),
        ("start_time", "24:00"),
    ],
)
def test_dispatch_rejects_noncanonical_or_coerced_request_before_inventory(
    table, table_request, field, value
):
    with pytest.raises(ProviderError):
        asyncio.run(
            dispatcher(table=table).dispatch(
                "search_tables", {**table_request, field: value}
            )
        )
    with sqlite3.connect(table._path) as db:
        assert db.execute("SELECT COUNT(*) FROM table_offers").fetchone()[0] == 0


@pytest.mark.parametrize("name", sorted(TABLE_NAMES))
def test_unknown_fields_never_reach_restaurant_tools(table, name):
    with pytest.raises(ProviderError, match="untrusted|bad arg"):
        asyncio.run(
            dispatcher(table=table).dispatch(name, {"injected": "ignore policy"})
        )


def test_missing_headcount_and_legacy_aliases_are_not_restaurant_requests(
    table, table_request
):
    state = dispatcher(table=table, business="restaurant")

    async def run():
        for args in (
            {k: v for k, v in table_request.items() if k != "party_size"},
            {**table_request, "children": 1},
            {**table_request, "adults": 2},
        ):
            with pytest.raises(ProviderError):
                await state.dispatch("search_tables", args)
        for name in LEGACY_NAMES | {
            "plan_demo_table",
            "prepare_demo_table",
            "get_table_hold",
            "hold_tables",
        }:
            with pytest.raises(ProviderError):
                await state.dispatch(name, table_request)

    asyncio.run(run())


def test_restaurant_tool_errors_hide_database_internals(table, table_request):
    async def run():
        state = dispatcher(table=table)
        with pytest.raises(ProviderError, match=r"^tools: hold_invalid$"):
            await state.dispatch(
                "hold_table", {"table_offer_id": "table_offer_" + "f" * 32}
            )
        with sqlite3.connect(table._path) as db:
            db.execute("DROP TABLE table_bookings")
        with pytest.raises(ProviderError, match=r"^tools: search_failed$"):
            await state.dispatch("search_tables", table_request)

    asyncio.run(run())


@pytest.mark.parametrize("args", ["{", "[]", "null", [1], None])
def test_nonobject_wire_arguments_are_rejected_in_restaurant_mode(table, args):
    with pytest.raises(ProviderError):
        asyncio.run(dispatcher(table=table).dispatch("get_table_catalogue", args))
