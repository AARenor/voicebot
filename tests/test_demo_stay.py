"""Fictional hotel inventory: actual date overlap and durable booking writes."""

import asyncio
import sqlite3
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.booking.base import UnknownQuoteError
from app.booking.demo_stay import DemoStayAdapter
from app.booking.tools import Dispatcher
from app.providers.errors import ProviderError


GUEST = {"firstName": "Demo", "lastName": "Esimene",
         "email": "demo.esimene+staytest01@example.invalid", "phone": "+12025550101"}


@pytest.fixture
def adapter(tmp_path):
    return DemoStayAdapter(str(tmp_path / "stay.db"))


@pytest.fixture
def dates():
    day = datetime.now(ZoneInfo("Europe/Tallinn")).date() + timedelta(days=10)
    return day.isoformat(), (day + timedelta(days=2)).isoformat()


async def suite(adapter, dates):
    return (await adapter.search_availability(*dates, {"adults": 2, "room_type": "spa-suite"}))[0]


def test_catalogue_and_search_quote_from_actual_inventory(adapter, dates):
    async def run():
        catalogue = await adapter.get_stay_catalogue()
        assert catalogue["synthetic"] is True
        assert catalogue["property"]["timezone"] == "Europe/Tallinn"
        assert {r["id"]: r["inventory"] for r in catalogue["room_types"]} == {
            "garden-double": 6, "spa-suite": 2, "family-room": 3,
        }
        offers = await adapter.search_availability(*dates, {"adults": 2})
        assert len(offers) == 3
        offer = next(o for o in offers if o["room_type_id"] == "garden-double")
        assert offer["quoted_total"] == "258.00"
        assert offer["available_rooms"] == 6
        assert offer["price_quote_id"].startswith("quote_")
        family = await adapter.search_availability(*dates, {"adults": 2, "children": 2})
        assert [o["room_type_id"] for o in family] == ["family-room"]
        assert await adapter.search_availability(*dates, {"adults": 5}) == []
    asyncio.run(run())


@pytest.mark.parametrize("adults,children", [(True, 0), (0, 0), (2, -1), (2, True), (2, 9)])
def test_invalid_occupancy(adapter, dates, adults, children):
    with pytest.raises(ProviderError):
        asyncio.run(adapter.search_availability(*dates, {"adults": adults, "children": children}))


def test_bad_dates_and_unknown_quotes_fail_closed(adapter, dates):
    with pytest.raises(ProviderError):
        asyncio.run(adapter.search_availability(dates[1], dates[0], {"adults": 2}))
    with pytest.raises(UnknownQuoteError):
        asyncio.run(adapter.create_hold("quote_" + "f" * 32))
    with pytest.raises(ProviderError):
        asyncio.run(adapter.create_hold("injected"))


def test_hold_expiry_and_repeat_preserve_finite_inventory(adapter, dates):
    async def run():
        quote = await suite(adapter, dates)
        hold = await adapter.create_hold(quote["price_quote_id"])
        assert (await adapter.create_hold(quote["price_quote_id"])).hold_id == hold.hold_id
        assert (await suite(adapter, dates))["available_rooms"] == 1
        with sqlite3.connect(adapter._path) as db:
            db.execute("UPDATE stay_holds SET expires_at=0 WHERE id=?", (hold.hold_id,))
        assert await adapter.get_hold(hold.hold_id) is None
        assert (await suite(adapter, dates))["available_rooms"] == 2
        result = await adapter.confirm(hold.hold_id, GUEST, "expired-hold")
        assert result == {"ok": False, "error": "hold_expired_or_unknown"}
    asyncio.run(run())


def test_booking_survives_restart_replay_and_cancellation(adapter, dates):
    async def run():
        hold = await adapter.create_hold((await suite(adapter, dates))["price_quote_id"])
        outcome = await adapter.confirm(hold.hold_id, GUEST, "confirmed-once")
        assert outcome["ok"] is True
        assert outcome["booking"]["quoted_total"] == "398.00"
        assert outcome["booking"]["guest_name"] == "Demo Esimene"
        restarted = DemoStayAdapter(adapter._path)
        assert await restarted.confirm(hold.hold_id, GUEST, "confirmed-once") == outcome
        assert len((await restarted.get_operator_bookings())["items"]) == 1
        assert (await suite(restarted, dates))["available_rooms"] == 1
        assert (await restarted.confirm(hold.hold_id, GUEST, "different-key"))["error"] == "hold_expired_or_unknown"
        cancelled = await restarted.cancel(outcome["booking_id"], "cancel-once")
        assert cancelled["status"] == "cancelled"
        assert await DemoStayAdapter(adapter._path).cancel(outcome["booking_id"], "cancel-once") == cancelled
        assert (await suite(restarted, dates))["available_rooms"] == 2
        assert "email" not in str((await restarted.get_operator_bookings())["items"])
    asyncio.run(run())


def test_parallel_holds_and_confirmations_cannot_oversell(adapter, dates):
    async def run():
        adapters = [DemoStayAdapter(adapter._path) for _ in range(5)]
        quotes = [await suite(a, dates) for a in adapters]
        held = await asyncio.gather(*[a.create_hold(q["price_quote_id"]) for a, q in zip(adapters, quotes)],
                                    return_exceptions=True)
        holds = [h for h in held if not isinstance(h, Exception)]
        assert len(holds) == 2
        assert len({h.hold_id for h in holds}) == 2
        outcomes = await asyncio.gather(*[a.confirm(holds[0].hold_id, GUEST, f"race-{i}")
                                        for i, a in enumerate(adapters)])
        assert sum(o["ok"] for o in outcomes) == 1
        assert len((await adapter.get_operator_bookings())["items"]) == 1
        assert await adapter.search_availability(*dates, {"adults": 2, "room_type": "spa-suite"}) == []
    asyncio.run(run())


def test_checkout_night_is_reusable_and_other_intervals_overlap(adapter, dates):
    async def run():
        for i in range(2):
            hold = await adapter.create_hold((await suite(adapter, dates))["price_quote_id"])
            assert (await adapter.confirm(hold.hold_id, GUEST, f"occupy-{i}"))["ok"]
        start = datetime.fromisoformat(dates[1]).date()
        following = (start.isoformat(), (start + timedelta(days=2)).isoformat())
        assert (await suite(adapter, following))["available_rooms"] == 2
        overlapping = (dates[0], (start + timedelta(days=1)).isoformat())
        assert await adapter.search_availability(*overlapping, {"adults": 2, "room_type": "spa-suite"}) == []
    asyncio.run(run())


def test_price_change_and_guest_validation(adapter, dates):
    async def run():
        hold = await adapter.create_hold((await suite(adapter, dates))["price_quote_id"])
        with sqlite3.connect(adapter._path) as db:
            db.execute("UPDATE stay_room_types SET nightly_cents=20000 WHERE id='spa-suite'")
        assert (await adapter.confirm(hold.hold_id, GUEST, "moved-price"))["error"] == "price_changed"
        with pytest.raises(ProviderError):
            await adapter.confirm(hold.hold_id, {**GUEST, "email": "guest@example.com"}, "real-guest")
    asyncio.run(run())


def test_confirmation_rechecks_dates_at_write_time(adapter, dates):
    async def run():
        hold = await adapter.create_hold((await suite(adapter, dates))["price_quote_id"])
        today = datetime.now(ZoneInfo("Europe/Tallinn")).date()
        with sqlite3.connect(adapter._path) as db:
            db.execute("UPDATE stay_quotes SET checkin=?,checkout=? WHERE id=?",
                       ((today - timedelta(days=1)).isoformat(), today.isoformat(), hold.price_quote_id))
        result = await adapter.confirm(hold.hold_id, GUEST, "past-date-at-confirm")
        assert result == {"ok": False, "error": "stay_dates_expired"}
        assert (await adapter.get_operator_bookings())["items"] == []
    asyncio.run(run())


def test_idempotency_key_cannot_change_target(adapter, dates):
    async def run():
        hold = await adapter.create_hold((await suite(adapter, dates))["price_quote_id"])
        booked = await adapter.confirm(hold.hold_id, GUEST, "one-key")
        assert booked["ok"]
        assert (await adapter.cancel(booked["booking_id"], "one-key"))["error"] == "idempotency_conflict"
        assert (await adapter.get_operator_bookings())["items"][0]["status"] == "confirmed"
    asyncio.run(run())


def test_dispatcher_room_contract(adapter, dates):
    async def run():
        dispatcher = Dispatcher(stay=adapter)
        names = {t["function"]["name"] for t in dispatcher.available_tools()}
        assert names == {"get_stay_catalogue", "search_availability", "hold_offer", "confirm_booking", "cancel_booking"}
        result = await dispatcher.dispatch("search_availability", {
            "checkin": dates[0], "checkout": dates[1], "adults": 2, "children": 2,
        })
        hold = await dispatcher.dispatch("hold_offer", {"price_quote_id": result["offers"][0]["price_quote_id"]})
        assert hold["recap"]["room_type_id"] == "family-room"
        assert hold["price_quote_id"] == result["offers"][0]["price_quote_id"]
        confirmed = await dispatcher.dispatch("confirm_booking", {"hold_id": hold["hold_id"], "guest": GUEST})
        assert confirmed["ok"]
        assert (await dispatcher.dispatch("cancel_booking", {"booking_id": confirmed["booking_id"]}))["ok"]
    asyncio.run(run())
