"""Fictional restaurant: real SQLite inventory, expiry and atomic writes."""

import asyncio
import importlib
import importlib.util
import json
import re
import sqlite3
import time
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from app.booking.base import Hold, UnknownQuoteError
from app.demo import load_demo_data, scoped_guest
from app.providers.errors import ProviderError


ROOT = Path(__file__).resolve().parents[1]
GUEST = {
    "firstName": "Demo",
    "lastName": "Esimene",
    "email": "demo.esimene+tabletest01@example.invalid",
    "phone": "+12025550101",
}


def new_adapter(path, **kwargs):
    assert importlib.util.find_spec("app.booking.demo_table") is not None, (
        "table adapter missing"
    )
    module = importlib.import_module("app.booking.demo_table")
    return module.DemoTableAdapter(str(path), **kwargs)


@pytest.fixture
def adapter(tmp_path):
    return new_adapter(tmp_path / "restaurant.db")


@pytest.fixture
def day():
    return (
        datetime.now(ZoneInfo("Europe/Tallinn")).date() + timedelta(days=10)
    ).isoformat()


async def offer(adapter, day, start_time="16:00", party_size=2):
    offers = await adapter.search_tables(day, start_time, party_size)
    assert len(offers) == 1
    return offers[0]


def freeze_clock(monkeypatch, instant):
    module = importlib.import_module("app.booking.demo_table")
    now = datetime.fromisoformat(instant).timestamp()
    monkeypatch.setattr(
        module, "time", SimpleNamespace(time=lambda: now, monotonic=time.monotonic)
    )


def test_catalogue_is_fictional_physical_inventory(tmp_path):
    adapter = new_adapter(tmp_path / "restaurant.db")
    catalogue = asyncio.run(adapter.get_table_catalogue())
    assert catalogue["synthetic"] is True
    assert catalogue["source"] == "demo_table"
    assert catalogue["venue"]["name"] == "Meretuule restoran"
    assert catalogue["venue"]["timezone"] == "Europe/Tallinn"
    assert catalogue["venue"]["address"] is None
    assert [(t["id"], t["capacity"]) for t in catalogue["tables"]] == [
        ("table-01", 2),
        ("table-02", 2),
        ("table-03", 4),
        ("table-04", 4),
        ("table-05", 6),
    ]
    assert catalogue["rules"] == {
        "opening_time": "12:00",
        "closing_time": "22:00",
        "duration_minutes": 120,
        "horizon_days": 90,
        "min_party_size": 1,
        "max_party_size": 6,
        "children_count_toward_party_size": True,
        "combine_tables": False,
    }


@pytest.mark.parametrize(
    "party_size,capacity", [(1, 2), (2, 2), (3, 4), (4, 4), (5, 6), (6, 6)]
)
def test_search_preserves_exact_request_without_booking_or_price(
    adapter, day, party_size, capacity
):
    async def run():
        result = await offer(adapter, day, "17:15", party_size)
        assert re.fullmatch(r"table_offer_[a-f0-9]{32}", result["table_offer_id"])
        assert result["kind"] == "table"
        assert result["date"] == day and result["start_time"] == "17:15"
        assert result["party_size"] == party_size and result["capacity"] == capacity
        assert result["duration_minutes"] == 120
        start, end = (datetime.fromisoformat(result[k]) for k in ("start", "end"))
        assert start.utcoffset() is not None and end.utcoffset() is not None
        assert start.strftime("%Y-%m-%d %H:%M") == day + " 17:15"
        assert (end.timestamp() - start.timestamp()) == 7200
        assert datetime.fromisoformat(result["expires_at"]).timestamp() > time.time()
        assert result["quoted_total"] is None and "price_quote_id" not in result
        assert (await adapter.get_operator_bookings(day))["items"] == []

    asyncio.run(run())


@pytest.mark.parametrize("party_size", [True, False, None, "2", 2.0, 0, -1, 7, {}, []])
def test_headcount_is_required_strict_integer_including_children(
    adapter, day, party_size
):
    with pytest.raises(ProviderError, match="party size"):
        asyncio.run(adapter.search_tables(day, "16:00", party_size))


@pytest.mark.parametrize(
    "bad_date",
    ["20261005", "2026-1-05", "2026-10-5", "2026-02-30", None, True, 20261005],
)
def test_search_rejects_noncanonical_dates(adapter, bad_date):
    with pytest.raises(ProviderError):
        asyncio.run(adapter.search_tables(bad_date, "16:00", 2))


@pytest.mark.parametrize(
    "bad_time",
    ["12", "12:0", "012:00", "12:00:00", "24:00", "12:60", " 12:00", None, True, 12],
)
def test_search_rejects_noncanonical_times(adapter, day, bad_time):
    with pytest.raises(ProviderError):
        asyncio.run(adapter.search_tables(day, bad_time, 2))


def test_future_horizon_and_whole_sitting_must_fit_opening_hours(adapter, monkeypatch):
    freeze_clock(monkeypatch, "2026-10-03T12:00:00+03:00")

    async def run():
        for date, start in [
            ("2026-10-02", "16:00"),
            ("2026-10-03", "12:00"),
            ("2027-01-02", "16:00"),
            ("2026-10-04", "11:59"),
            ("2026-10-04", "20:01"),
            ("2026-10-04", "22:00"),
        ]:
            with pytest.raises(ProviderError):
                await adapter.search_tables(date, start, 2)
        assert (await offer(adapter, "2026-10-03", "12:01"))["start_time"] == "12:01"
        assert (await offer(adapter, "2027-01-01", "20:00"))["end_time"] == "22:00"
        assert (await offer(adapter, "2026-10-04", "12:00"))["start_time"] == "12:00"

    asyncio.run(run())


@pytest.mark.parametrize(
    "date,clock,offset",
    [
        ("2027-03-28", "2027-03-01T12:00:00+02:00", "+03:00"),
        ("2026-10-25", "2026-10-01T12:00:00+03:00", "+02:00"),
    ],
)
def test_tallinn_dst_gap_and_ambiguity_are_not_normalized(
    adapter, monkeypatch, date, clock, offset
):
    freeze_clock(monkeypatch, clock)
    with pytest.raises(ProviderError, match="local time"):
        asyncio.run(adapter.search_tables(date, "03:30", 2))
    result = asyncio.run(offer(adapter, date))
    assert result["start"].endswith(offset) and result["end"].endswith(offset)


def test_hold_reallocates_smallest_free_table_and_owns_its_recap(adapter, day):
    async def run():
        first, second = await offer(adapter, day), await offer(adapter, day)
        assert first["table_id"] == second["table_id"] == "table-01"
        held = await adapter.create_hold(first["table_offer_id"])
        other = await new_adapter(adapter._path).create_hold(second["table_offer_id"])
        assert isinstance(held, Hold) and held.quoted_total is None
        assert held.payload["kind"] == "table"
        assert held.price_quote_id == first["table_offer_id"]
        assert other.payload["recap"]["table_id"] == "table-02"
        assert other.payload["recap"]["table_name"] == "Laud 2"
        assert other.payload["recap"]["party_size"] == 2
        assert other.payload["recap"]["start_time"] == "16:00"
        assert (
            await adapter.create_hold(first["table_offer_id"])
        ).hold_id == held.hold_id
        restored = await new_adapter(adapter._path).get_hold(other.hold_id)
        assert restored.payload == other.payload
        assert not restored.expired()
        assert (await adapter.get_operator_bookings(day))["items"] == []

    asyncio.run(run())


@pytest.mark.parametrize(
    "party_size,expected_capacities", [(1, [2, 2, 4, 4, 6]), (6, [6])]
)
def test_concurrent_connections_cannot_oversell_tables(
    adapter, day, party_size, expected_capacities
):
    async def run():
        adapters = [new_adapter(adapter._path) for _ in range(8)]
        offers = [await offer(a, day, party_size=party_size) for a in adapters]
        results = await asyncio.gather(
            *(a.create_hold(o["table_offer_id"]) for a, o in zip(adapters, offers)),
            return_exceptions=True,
        )
        holds = [h for h in results if isinstance(h, Hold)]
        failures = [h for h in results if not isinstance(h, Hold)]
        assert (
            sorted(h.payload["recap"]["capacity"] for h in holds) == expected_capacities
        )
        assert len({h.payload["recap"]["table_id"] for h in holds}) == len(holds)
        assert all(isinstance(e, ProviderError) for e in failures)
        assert await adapter.search_tables(day, "16:00", party_size) == []

    asyncio.run(run())


def test_same_offer_concurrent_holds_are_one_reservation(adapter, day):
    async def run():
        result = await offer(adapter, day, party_size=6)
        holds = await asyncio.gather(
            *(
                new_adapter(adapter._path).create_hold(result["table_offer_id"])
                for _ in range(5)
            )
        )
        assert len({h.hold_id for h in holds}) == 1
        with sqlite3.connect(adapter._path) as db:
            assert db.execute("SELECT COUNT(*) FROM table_holds").fetchone()[0] == 1

    asyncio.run(run())


@pytest.mark.parametrize("confirmed", [False, True])
def test_whole_interval_overlap_blocks_and_exact_adjacency_allows(
    adapter, day, confirmed
):
    async def run():
        held = await adapter.create_hold(
            (await offer(adapter, day, party_size=6))["table_offer_id"]
        )
        if confirmed:
            assert (await adapter.confirm(held.hold_id, GUEST, "occupy-table"))["ok"]
        for start in ("14:01", "15:00", "16:00", "17:59"):
            assert await adapter.search_tables(day, start, 6) == []
        assert (await offer(adapter, day, "14:00", 6))["end_time"] == "16:00"
        assert (await offer(adapter, day, "18:00", 6))["start_time"] == "18:00"

    asyncio.run(run())


def test_expired_offer_and_hold_fail_closed_and_release_capacity(adapter, day):
    async def run():
        expired = await offer(adapter, day, party_size=6)
        with sqlite3.connect(adapter._path) as db:
            db.execute(
                "UPDATE table_offers SET expires_at=0 WHERE id=?",
                (expired["table_offer_id"],),
            )
        with pytest.raises(UnknownQuoteError):
            await adapter.create_hold(expired["table_offer_id"])
        fresh = await offer(adapter, day, party_size=6)
        held = await adapter.create_hold(fresh["table_offer_id"])
        assert datetime.fromisoformat(
            held.payload["expires_at"]
        ) <= datetime.fromisoformat(fresh["expires_at"])
        with sqlite3.connect(adapter._path) as db:
            db.execute(
                "UPDATE table_holds SET expires_at=0 WHERE id=?", (held.hold_id,)
            )
        restarted = new_adapter(adapter._path)
        assert await restarted.get_hold(held.hold_id) is None
        failure = await restarted.confirm(held.hold_id, GUEST, "expired-once")
        assert failure == {"ok": False, "error": "hold_expired_or_unknown"}
        assert (
            await new_adapter(adapter._path).confirm(
                held.hold_id, GUEST, "expired-once"
            )
            == failure
        )
        replacement = await restarted.create_hold(fresh["table_offer_id"])
        assert replacement.hold_id != held.hold_id
        assert replacement.payload["recap"]["table_id"] == "table-05"

    asyncio.run(run())


@pytest.mark.parametrize("same_key", [False, True])
def test_concurrent_confirmations_have_one_authoritative_receipt(
    adapter, day, same_key
):
    async def run():
        held = await adapter.create_hold(
            (await offer(adapter, day, party_size=6))["table_offer_id"]
        )
        results = await asyncio.gather(
            *(
                new_adapter(adapter._path).confirm(
                    held.hold_id, GUEST, "race-once" if same_key else f"race-{i}"
                )
                for i in range(5)
            )
        )
        assert sum(r["ok"] for r in results) == (5 if same_key else 1)
        if same_key:
            assert all(r == results[0] for r in results)
        receipt = next(r for r in results if r["ok"])
        assert receipt["kind"] == receipt["booking"]["kind"] == "table"
        assert re.fullmatch(r"table_[a-f0-9]{32}", receipt["booking_id"])
        assert receipt["booking"]["id"] == receipt["booking_id"]
        assert receipt["booking"]["status"] == "confirmed"
        for key in (
            "date",
            "start_time",
            "start",
            "end",
            "party_size",
            "duration_minutes",
            "table_id",
            "table_name",
            "capacity",
        ):
            assert receipt["booking"][key] == held.payload["recap"][key]
        assert (await adapter.get_operator_bookings(day))["items"] == [
            receipt["booking"]
        ]
        with pytest.raises(ProviderError):
            await adapter.create_hold(held.price_quote_id)

    asyncio.run(run())


def test_restart_replay_readback_and_cancellation_preserve_authority(adapter, day):
    async def run():
        held = await adapter.create_hold(
            (await offer(adapter, day, party_size=6))["table_offer_id"]
        )
        result = await new_adapter(adapter._path).confirm(
            held.hold_id, GUEST, "confirm-once"
        )
        assert result["ok"] and result["booking"]["guest_name"] == "Demo Esimene"
        restarted = new_adapter(adapter._path)
        assert await restarted.confirm(held.hold_id, GUEST, "confirm-once") == result
        assert await restarted.get_hold(held.hold_id) is None
        assert await restarted.search_tables(day, "16:00", 6) == []
        cancellation = await restarted.cancel(result["booking_id"], "cancel-once")
        assert cancellation["ok"] and cancellation["status"] == "cancelled"
        assert cancellation["kind"] == "table"
        assert (
            await new_adapter(adapter._path).cancel(result["booking_id"], "cancel-once")
            == cancellation
        )
        assert (await offer(restarted, day, party_size=6))["capacity"] == 6
        readback = await restarted.get_operator_bookings(day)
        assert readback["items"][0]["status"] == "cancelled"
        assert "email" not in json.dumps(readback) and "phone" not in json.dumps(
            readback
        )
        other_day = (datetime.fromisoformat(day).date() + timedelta(days=1)).isoformat()
        assert (await restarted.get_operator_bookings(other_day))["items"] == []
        assert len((await restarted.get_operator_bookings())["items"]) == 1

    asyncio.run(run())


def test_fingerprinted_keys_cannot_change_guest_target_or_operation(adapter, day):
    async def run():
        held = await adapter.create_hold(
            (await offer(adapter, day, party_size=6))["table_offer_id"]
        )
        other = await adapter.create_hold(
            (await offer(adapter, day, "18:00", 6))["table_offer_id"]
        )
        result = await adapter.confirm(held.hold_id, GUEST, "same-key")
        guest2 = scoped_guest(
            load_demo_data(ROOT / "data/demo/restaurant-demo.json"),
            "guest-002",
            "tabletest01",
        )
        for replay in (
            await adapter.confirm(held.hold_id, guest2, "same-key"),
            await adapter.confirm(other.hold_id, GUEST, "same-key"),
            await adapter.cancel(result["booking_id"], "same-key"),
        ):
            assert replay == {"ok": False, "error": "idempotency_conflict"}
        items = (await adapter.get_operator_bookings(day))["items"]
        assert len(items) == 1 and items[0]["status"] == "confirmed"

    asyncio.run(run())


@pytest.mark.parametrize(
    "field,value",
    [
        ("email", "guest@example.com"),
        ("email", "demo.other@example.invalid"),
        ("email", "demo.esimene+short@example.invalid"),
        ("phone", "+37255555555"),
        ("firstName", "Actual"),
        ("customerId", 7),
    ],
)
def test_only_approved_reserved_fixture_contacts_can_be_confirmed(
    adapter, day, field, value
):
    async def run():
        held = await adapter.create_hold((await offer(adapter, day))["table_offer_id"])
        with pytest.raises(ProviderError, match="fictional guest"):
            await adapter.confirm(held.hold_id, {**GUEST, field: value}, "not-approved")
        assert (await adapter.get_operator_bookings(day))["items"] == []

    asyncio.run(run())


@pytest.mark.parametrize(
    "field,value", [("active", 0), ("capacity", 1), ("name", "Changed table")]
)
def test_confirmation_rechecks_owned_physical_table(adapter, day, field, value):
    async def run():
        held = await adapter.create_hold(
            (await offer(adapter, day, party_size=6))["table_offer_id"]
        )
        with sqlite3.connect(adapter._path) as db:
            db.execute(
                f"UPDATE restaurant_tables SET {field}=? WHERE id='table-05'", (value,)
            )
        result = await adapter.confirm(held.hold_id, GUEST, "changed-table")
        assert result == {"ok": False, "error": "table_unavailable"}
        assert (await adapter.get_operator_bookings(day))["items"] == []

    asyncio.run(run())


def test_hold_and_confirm_recheck_time_after_search(adapter, monkeypatch):
    freeze_clock(monkeypatch, "2026-10-03T12:00:00+03:00")

    async def run():
        first = await offer(adapter, "2026-10-03", "12:01")
        second = await offer(adapter, "2026-10-03", "12:01")
        held = await adapter.create_hold(first["table_offer_id"])
        freeze_clock(monkeypatch, "2026-10-03T12:01:00+03:00")
        with pytest.raises(ProviderError):
            await adapter.create_hold(second["table_offer_id"])
        assert (await adapter.confirm(held.hold_id, GUEST, "start-passed"))[
            "ok"
        ] is False
        assert (await adapter.get_operator_bookings())["items"] == []

    asyncio.run(run())


@pytest.mark.parametrize("operation", ["confirm", "cancel"])
def test_write_failure_rolls_back_inventory_status_and_idempotency(
    adapter, day, operation
):
    async def run():
        held = await adapter.create_hold(
            (await offer(adapter, day, party_size=6))["table_offer_id"]
        )
        receipt = (
            await adapter.confirm(held.hold_id, GUEST, "before-cancel")
            if operation == "cancel"
            else None
        )
        with sqlite3.connect(adapter._path) as db:
            db.execute(
                "CREATE TRIGGER fail_write BEFORE INSERT ON table_writes "
                "BEGIN SELECT RAISE(ABORT, 'private database failure'); END"
            )
        with pytest.raises(ProviderError, match="database unavailable"):
            if receipt:
                await adapter.cancel(receipt["booking_id"], "retry-write")
            else:
                await adapter.confirm(held.hold_id, GUEST, "retry-write")
        with sqlite3.connect(adapter._path) as db:
            assert (
                db.execute(
                    "SELECT COUNT(*) FROM table_writes WHERE key='retry-write'"
                ).fetchone()[0]
                == 0
            )
            assert db.execute(
                "SELECT status FROM table_holds WHERE id=?", (held.hold_id,)
            ).fetchone()[0] == ("confirmed" if receipt else "held")
            assert db.execute(
                "SELECT COUNT(*) FROM table_bookings WHERE status='confirmed'"
            ).fetchone()[0] == bool(receipt)
            db.execute("DROP TRIGGER fail_write")
        result = (
            await adapter.cancel(receipt["booking_id"], "retry-write")
            if receipt
            else await adapter.confirm(held.hold_id, GUEST, "retry-write")
        )
        assert result["ok"]
        assert len((await adapter.get_operator_bookings(day))["items"]) == 1

    asyncio.run(run())


def test_unknown_ids_and_unknown_cancellation_are_durable_closed_results(adapter):
    async def run():
        hold_id, booking_id = "hold_" + "f" * 32, "table_" + "f" * 32
        with pytest.raises(UnknownQuoteError):
            await adapter.create_hold("table_offer_" + "f" * 32)
        assert await adapter.get_hold(hold_id) is None
        assert (await adapter.confirm(hold_id, GUEST, "unknown-hold"))[
            "error"
        ] == "hold_expired_or_unknown"
        result = await adapter.cancel(booking_id, "unknown-booking")
        assert result == {"ok": False, "error": "booking_not_found"}
        assert (
            await new_adapter(adapter._path).cancel(booking_id, "unknown-booking")
            == result
        )
        for method in (adapter.create_hold, adapter.get_hold):
            with pytest.raises(ProviderError):
                await method("injected")
        with pytest.raises(ProviderError):
            await adapter.confirm(hold_id, GUEST, "bad key")
        with pytest.raises(ProviderError):
            await adapter.cancel("stay_" + "f" * 32, "wrong-business")
        with pytest.raises(ProviderError):
            await adapter.get_operator_bookings("20261003")

    asyncio.run(run())


def test_restart_does_not_reset_existing_inventory(adapter):
    with sqlite3.connect(adapter._path) as db:
        db.execute("UPDATE restaurant_tables SET active=0 WHERE id='table-01'")
    catalogue = asyncio.run(new_adapter(adapter._path).get_table_catalogue())
    assert "table-01" not in {t["id"] for t in catalogue["tables"]}


@pytest.mark.parametrize(
    "kwargs",
    [
        {"hold_ttl_seconds": True},
        {"offer_ttl_seconds": 1.5},
        {"hold_ttl_seconds": 0},
        {"offer_ttl_seconds": 3601},
    ],
)
def test_persistent_database_and_strict_ttls_are_required(tmp_path, kwargs):
    with pytest.raises(ValueError):
        new_adapter(tmp_path / "table.db", **kwargs)
    with pytest.raises(ValueError):
        new_adapter(":memory:")


def test_restaurant_profile_retains_approved_guests_and_all_safety_flags():
    path = ROOT / "data/demo/restaurant-demo.json"
    assert path.is_file(), "restaurant profile missing"
    original = json.loads((ROOT / "data/demo/telephone-demo.json").read_text())
    restaurant = json.loads(path.read_text())
    assert restaurant["guests"] == original["guests"]
    assert restaurant["safety"] == original["safety"]
    data = load_demo_data(path)
    assert data["profile"]["name"] == "Meretuule restoran"
    assert data["profile"]["address"] is None
    assert data["profile"]["real_visitor_location"] is False
    assert all(
        key in data["profile"]
        for key in ("description_et", "description_en", "description_ru")
    )
    assert all(
        all("answer_" + language in entry for language in ("et", "en", "ru"))
        for entry in data["faq"]
    )
    assert not re.search(
        r"spaa|spa|hotell|hotel|спа|отель",
        json.dumps(data["faq"], ensure_ascii=False),
        re.I,
    )


@pytest.mark.parametrize(
    "date,start_time", [("9999-12-31", "23:59"), ("0001-01-01", "00:01")]
)
def test_out_of_horizon_date_is_rejected_before_timezone_arithmetic_overflows(
    adapter, date, start_time
):
    with pytest.raises(ProviderError):
        asyncio.run(adapter.search_tables(date, start_time, 2))
