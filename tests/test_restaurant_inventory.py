"""Actual SQLite inventory checks; no remote restaurant/provider is contacted."""

import asyncio
import copy
import json
import sqlite3
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.booking.restaurant import RestaurantAdapter
from app.restaurant_data import load_restaurant_data

NOW = datetime(2026, 10, 3, 10, tzinfo=ZoneInfo("Europe/Tallinn"))
DAY = "2026-10-05"
GUEST = {"email": "restaurant+owned-call@example.invalid"}


@pytest.mark.parametrize(
    "change", ["closure", "capacity", "hours", "duration", "removed_table"]
)
def test_confirm_rechecks_current_restaurant_rules(adapter, change):
    async def run():
        slot = await exact_slot(adapter)
        hold = await adapter.create_hold(slot["slotId"])
        if change == "closure":
            adapter.data["closures"][DAY] = {
                language: "Closed" for language in ("et", "en", "ru")
            }
        elif change == "capacity":
            next(
                table
                for table in adapter.data["tables"]
                if table["id"] == slot["providerId"]
            )["capacity"] = 2
        elif change == "hours":
            adapter.data["opening_hours"]["monday"]["end"] = "19:30"
        elif change == "duration":
            adapter.data["reservation_duration_minutes"] = 120
        else:
            adapter.data["tables"] = [
                table
                for table in adapter.data["tables"]
                if table["id"] != slot["providerId"]
            ]
        assert await adapter.confirm(hold.hold_id, GUEST, "rules-changed") == {
            "error": "slot_unavailable"
        }
        assert (await adapter.get_operator_bookings(DAY))["items"] == []

    asyncio.run(run())


@pytest.fixture
def adapter(tmp_path):
    return RestaurantAdapter(
        str(tmp_path / "restaurant.db"), allow_writes=True, now=lambda: NOW
    )


async def exact_slot(adapter, *, day=DAY, start="19:00", party=4, table=None):
    slots = await adapter.search_tables(day, party, table)
    return next(slot for slot in slots if slot["start"][11:16] == start)


@pytest.mark.parametrize(
    "party,capacities",
    [(1, {2, 4, 6}), (2, {2, 4, 6}), (3, {4, 6}), (4, {4, 6}), (5, {6}), (6, {6})],
)
def test_party_size_filters_real_table_capacity(adapter, party, capacities):
    slots = asyncio.run(adapter.search_tables(DAY, party))
    assert slots
    assert {slot["table_capacity"] for slot in slots} == capacities
    assert all(slot["party_size"] == party for slot in slots)


@pytest.mark.parametrize("party", [0, -1, 7, 100, True, False, 2.5, "4", None])
def test_invalid_party_size_rejected_before_quotes(adapter, party):
    with pytest.raises(ValueError, match="party_size"):
        asyncio.run(adapter.search_tables(DAY, party))
    assert adapter._quotes == {}


@pytest.mark.parametrize(
    "day", ["2026-10-02", "2027-04-01", "2026-02-30", "2026-1-1", "tomorrow", None]
)
def test_invalid_or_unbounded_dates_rejected(adapter, day):
    with pytest.raises((ValueError, TypeError)):
        asyncio.run(adapter.search_tables(day, 2))


def test_full_dining_duration_must_fit_inside_opening_hours(adapter):
    slots = asyncio.run(adapter.search_tables("2026-10-04", 4))
    times = {slot["start"][11:16] for slot in slots}
    assert min(times) == "12:00"
    assert max(times) == "18:30"
    assert "19:00" not in times
    assert all(
        datetime.fromisoformat(slot["end"]) - datetime.fromisoformat(slot["start"])
        == timedelta(minutes=90)
        for slot in slots
    )


def test_closed_day_and_exception_never_offer_tables(tmp_path):
    data = load_restaurant_data()
    data["opening_hours"]["monday"] = None
    data["closures"]["2026-10-06"] = {
        language: "Closed fixture" for language in ("et", "en", "ru")
    }
    adapter = RestaurantAdapter(
        str(tmp_path / "closed.db"), data=data, allow_writes=True, now=lambda: NOW
    )
    assert asyncio.run(adapter.search_tables(DAY, 2)) == []
    assert asyncio.run(adapter.search_tables("2026-10-06", 2)) == []


def test_overlapping_holds_and_adjacent_intervals(adapter):
    async def run():
        original = await exact_slot(adapter, table="3")
        held = await adapter.create_hold(original["slotId"])
        other = await adapter.search_tables(DAY, 4, "3")
        times = {slot["start"][11:16] for slot in other}
        assert "19:00" not in times and "18:45" not in times and "19:15" not in times
        assert "17:30" in times
        assert (await adapter.get_hold(held.hold_id)).payload["party_size"] == 4

    asyncio.run(run())


def test_two_independent_instances_cannot_hold_same_interval(adapter):
    async def run():
        other = RestaurantAdapter(adapter.state_db, allow_writes=True, now=lambda: NOW)
        first_slot, second_slot = await asyncio.gather(
            exact_slot(adapter, table="5", party=6),
            exact_slot(other, table="5", party=6),
        )
        results = await asyncio.gather(
            adapter.create_hold(first_slot["slotId"]),
            other.create_hold(second_slot["slotId"]),
            return_exceptions=True,
        )
        assert sum(not isinstance(result, BaseException) for result in results) == 1
        assert sum(isinstance(result, ValueError) for result in results) == 1

    asyncio.run(run())


def test_expired_hold_releases_table_and_cannot_confirm(adapter):
    async def run():
        slot = await exact_slot(adapter, table="5", party=6)
        held = await adapter.create_hold(slot["slotId"])
        adapter._now = lambda: NOW + timedelta(seconds=121)
        assert await adapter.get_hold(held.hold_id) is None
        assert (await adapter.confirm(held.hold_id, GUEST, "expired-key"))[
            "error"
        ] == "hold_expired_or_unknown"
        assert await exact_slot(adapter, table="5", party=6)

    asyncio.run(run())


def test_confirmation_is_durable_and_idempotent_across_restart(adapter):
    async def run():
        slot = await exact_slot(adapter, table="3")
        held = await adapter.create_hold(slot["slotId"])
        result = await adapter.confirm(held.hold_id, GUEST, "confirmation-key")
        assert result["ok"] is True
        restarted = RestaurantAdapter(
            adapter.state_db, allow_writes=True, now=lambda: NOW
        )
        assert (
            await restarted.confirm(held.hold_id, GUEST, "confirmation-key") == result
        )
        assert await restarted.confirm(held.hold_id, GUEST, "new-retry-key") == result
        items = (await restarted.get_operator_bookings(DAY))["items"]
        assert len(items) == 1
        assert items[0]["service_id"] == 4
        assert items[0]["provider_id"] == 3
        assert items[0]["end_local"].endswith("20:30:00")

    asyncio.run(run())


def test_duplicate_confirms_in_parallel_make_one_reservation(adapter):
    async def run():
        slot = await exact_slot(adapter)
        held = await adapter.create_hold(slot["slotId"])
        results = await asyncio.gather(
            *(adapter.confirm(held.hold_id, GUEST, "same-key") for _ in range(8))
        )
        assert all(result == results[0] for result in results)
        assert len((await adapter.get_operator_bookings(DAY))["items"]) == 1

    asyncio.run(run())


def test_same_key_for_different_write_is_rejected(adapter):
    async def run():
        held = await adapter.create_hold((await exact_slot(adapter))["slotId"])
        result = await adapter.confirm(held.hold_id, GUEST, "reused-key")
        assert (await adapter.cancel(str(result["booking"]["id"]), "reused-key"))[
            "error"
        ] == "idempotency_conflict"
        assert (await adapter.get_operator_bookings(DAY))["items"][0][
            "status"
        ] == "confirmed"

    asyncio.run(run())


def test_cancellation_is_idempotent_and_releases_capacity(adapter):
    async def run():
        held = await adapter.create_hold(
            (await exact_slot(adapter, table="5", party=6))["slotId"]
        )
        result = await adapter.confirm(held.hold_id, GUEST, "confirm")
        identifier = str(result["booking"]["id"])
        cancelled = await adapter.cancel(identifier, "cancel")
        assert cancelled["ok"] is True
        assert await adapter.cancel(identifier, "cancel") == cancelled
        assert await exact_slot(adapter, table="5", party=6)
        assert (await adapter.confirm(held.hold_id, GUEST, "confirm-new"))[
            "error"
        ] == "already_cancelled"

    asyncio.run(run())


def test_tenant_isolation_applies_to_inventory_receipts_and_cancellation(adapter):
    async def run():
        held = await adapter.create_hold(
            (await exact_slot(adapter, table="5", party=6))["slotId"]
        )
        result = await adapter.confirm(held.hold_id, GUEST, "tenant-key")
        data = load_restaurant_data()
        data["restaurant_id"] = "other-restaurant"
        other = RestaurantAdapter(
            adapter.state_db, data=data, allow_writes=True, now=lambda: NOW
        )
        assert (await other.get_operator_bookings(DAY))["items"] == []
        assert (await other.cancel(str(result["booking"]["id"]), "cancel-key"))[
            "error"
        ] == "booking_unknown"
        assert await exact_slot(other, table="5", party=6)

    asyncio.run(run())


@pytest.mark.parametrize(
    "email", ["real@example.com", "", None, "invalid", "name@example.invalid.evil"]
)
def test_demo_never_stores_real_guest_contacts(adapter, email):
    result = asyncio.run(adapter.confirm("unknown", {"email": email}, "key"))
    assert result == {"error": "synthetic_guest_required"}


def test_database_and_public_dtos_do_not_store_or_expose_contact_data(adapter):
    async def run():
        held = await adapter.create_hold((await exact_slot(adapter))["slotId"])
        result = await adapter.confirm(held.hold_id, GUEST, "private-key")
        assert GUEST["email"] not in json.dumps(result)
        assert GUEST["email"] not in json.dumps(
            await adapter.get_operator_bookings(DAY)
        )

    asyncio.run(run())
    with sqlite3.connect(adapter.state_db) as connection:
        dump = "\n".join(connection.iterdump())
    assert GUEST["email"] not in dump


def test_read_only_adapter_does_not_create_a_database(tmp_path):
    path = tmp_path / "absent.db"
    adapter = RestaurantAdapter(str(path), allow_writes=False)
    assert not path.exists()
    assert adapter.operational is False
    assert asyncio.run(adapter.get_operator_bookings(DAY))["items"] == []
    assert not path.exists()


@pytest.mark.parametrize(
    "field,value",
    [
        ("maximum_party_size", True),
        ("reservation_duration_minutes", 0),
        ("slot_interval_minutes", -1),
        ("timezone", "Invalid/Timezone"),
        ("restaurant_id", "../other"),
        ("synthetic", False),
        ("opening_hours", {}),
        ("menu", []),
        ("tables", []),
    ],
)
def test_restaurant_configuration_fails_closed(tmp_path, field, value):
    data = load_restaurant_data()
    data[field] = value
    path = tmp_path / "configuration.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="^restaurant_configuration_invalid$"):
        load_restaurant_data(path)


def test_unsourced_menu_prices_and_duplicate_tables_rejected(tmp_path):
    for change in ("price", "table"):
        data = copy.deepcopy(load_restaurant_data())
        if change == "price":
            data["menu"][0]["price"] = "12.00 EUR"
        else:
            data["tables"].append(copy.deepcopy(data["tables"][0]))
        path = tmp_path / (change + ".json")
        path.write_text(json.dumps(data), encoding="utf-8")
        with pytest.raises(ValueError):
            load_restaurant_data(path)


@pytest.mark.parametrize("policy", [
    None,
    True,
    "Dogs are welcome",
    {"et": "Lubatud"},
    {"et": "Lubatud", "en": "Allowed", "ru": ""},
    {"et": "Lubatud", "en": "Allowed", "ru": 1},
    {"et": "Lubatud", "en": "Allowed", "ru": "\x00"},
    {"et": "Lubatud", "en": "Allowed", "ru": "a" * 1201},
    {"et": "Lubatud", "en": "Allowed", "ru": "Можно", "de": "Erlaubt"},
])
def test_malformed_pet_policy_fails_configuration_validation(tmp_path, policy):
    data = load_restaurant_data()
    data["pet_policy"] = policy
    path = tmp_path / "restaurant.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="^restaurant_configuration_invalid$"):
        load_restaurant_data(path)


def test_pet_policy_is_optional_and_translated_rules_are_normalized(tmp_path):
    data = load_restaurant_data()
    data.pop("pet_policy", None)
    path = tmp_path / "restaurant.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    assert "pet_policy" not in load_restaurant_data(path)
    data["pet_policy"] = {language: "  Dogs are welcome.  " for language in ("et", "en", "ru")}
    path.write_text(json.dumps(data), encoding="utf-8")
    assert load_restaurant_data(path)["pet_policy"] == {
        language: "Dogs are welcome." for language in ("et", "en", "ru")
    }
