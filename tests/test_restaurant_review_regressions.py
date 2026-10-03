"""Independent-review repros run against the real restaurant policy and ledger."""

import asyncio
import sqlite3
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.booking.demo_table import DemoTableAdapter
from app.booking.tools import Dispatcher
from app.telephone import CallTools


@pytest.mark.parametrize("guest", ["guest-001", "guest-002"])
def test_replanning_owned_six_person_sitting_reuses_capacity_and_resets_consent(
    tmp_path, guest
):
    async def run():
        path = str(tmp_path / "tables.db")
        backend = DemoTableAdapter(path)
        state = CallTools(Dispatcher(table=backend, business="restaurant"))
        day = (
            datetime.now(ZoneInfo("Europe/Tallinn")).date() + timedelta(days=7)
        ).isoformat()
        request = {"date": day, "start_time": "18:00", "party_size": 6}
        first = await state.dispatch("plan_demo_table", request)
        assert first.get("ok") is True
        prior = state.pending
        assert state.mark_recap_delivered(first["hold_id"])
        state.observe_user_text("Palun sama laud uuesti.")
        again = await state.dispatch(
            "plan_demo_table", {**request, "guest_fixture_id": guest}
        )
        assert again.get("ok") is True, again
        assert again["hold_id"] == first["hold_id"]
        assert state.pending is not prior
        assert not state.pending["delivery"] and not state.pending["approved"]
        assert state.pending["guest_fixture_id"] == guest
        with sqlite3.connect(path) as db:
            assert (
                db.execute(
                    "SELECT COUNT(*) FROM table_holds WHERE status='held'"
                ).fetchone()[0]
                == 1
            )
            assert db.execute("SELECT COUNT(*) FROM table_bookings").fetchone()[0] == 0
        assert not state.bookings

    asyncio.run(run())


@pytest.mark.parametrize(
    "language,question,answer",
    [
        (
            "en",
            "Is this a real restaurant?",
            "No. Meretuule restoran is a fictional testing environment. Test reservations do not entitle you to a real restaurant visit.",
        ),
        (
            "et",
            "Kas see on päris restoran?",
            "Ei. Meretuule restoran on väljamõeldud katsetuskeskkond. Testbroneeringud ei anna õigust päris restoranikülastusele.",
        ),
        (
            "ru",
            "Это настоящий ресторан?",
            "Нет. Meretuule restoran — вымышленная тестовая среда. Тестовые бронирования не дают права на посещение настоящего ресторана.",
        ),
    ],
)
def test_selected_business_manual_faq_detects_language_without_metadata(
    tmp_path, language, question, answer
):
    state = CallTools(
        Dispatcher(
            table=DemoTableAdapter(str(tmp_path / "tables.db")), business="restaurant"
        ),
        language="et",
    )
    state.observe_user_text(question)
    assert state.language == language
    assert state.guard_reply("Unverified model prose.", []) == answer


def test_changed_owned_sitting_releases_only_its_abandoned_unconfirmed_hold(tmp_path):
    async def run():
        backend = DemoTableAdapter(str(tmp_path / "tables.db"))
        state = CallTools(Dispatcher(table=backend, business="restaurant"))
        other = CallTools(Dispatcher(table=backend, business="restaurant"))
        day = (
            datetime.now(ZoneInfo("Europe/Tallinn")).date() + timedelta(days=7)
        ).isoformat()
        request = {"date": day, "start_time": "18:00", "party_size": 6}
        first = await state.dispatch("plan_demo_table", request)
        foreign = await other.dispatch("plan_demo_table", {**request, "party_size": 2})
        assert first.get("ok") and foreign.get("ok")
        state.observe_user_text("Palun viiele inimesele.")
        changed = await state.dispatch("plan_demo_table", {**request, "party_size": 5})
        assert changed.get("ok") is True, changed
        assert changed["hold_id"] != first["hold_id"]
        assert await backend.get_hold(first["hold_id"]) is None
        assert await backend.get_hold(foreign["hold_id"]) is not None
        assert await backend.get_hold(changed["hold_id"]) is not None
        assert first["hold_id"] not in state.holds
        assert not state.bookings and not other.bookings

    asyncio.run(run())


def test_direct_search_replaces_owned_hold_without_releasing_foreign_capacity(tmp_path):
    async def run():
        backend = DemoTableAdapter(str(tmp_path / "tables.db"))
        state = CallTools(Dispatcher(table=backend, business="restaurant"))
        day = (
            datetime.now(ZoneInfo("Europe/Tallinn")).date() + timedelta(days=7)
        ).isoformat()
        request = {"date": day, "start_time": "18:00", "party_size": 6}
        first = await state.dispatch("plan_demo_table", request)
        assert first.get("ok") is True
        searched = await state.dispatch("search_tables", request)
        assert searched.get("offers"), searched
        assert await backend.get_hold(first["hold_id"]) is None
        assert first["hold_id"] not in state.holds
        assert not state.pending and not state.bookings

    asyncio.run(run())


@pytest.mark.parametrize("guard", ["confirmed", "uncertain"])
def test_new_search_never_releases_confirmed_or_uncertain_owned_capacity(
    tmp_path, guard
):
    async def run():
        backend = DemoTableAdapter(str(tmp_path / "tables.db"))
        state = CallTools(Dispatcher(table=backend, business="restaurant"))
        day = (
            datetime.now(ZoneInfo("Europe/Tallinn")).date() + timedelta(days=7)
        ).isoformat()
        request = {"date": day, "start_time": "18:00", "party_size": 6}
        first = await state.dispatch("plan_demo_table", request)
        assert first.get("ok") is True
        if guard == "confirmed":
            assert state.mark_recap_delivered(first["hold_id"])
            state.observe_user_text("Jah, kinnitan.")
            assert (
                await state.dispatch(
                    "confirm_table_booking", {"hold_id": first["hold_id"]}
                )
            )["ok"]
            assert await backend.release_hold(first["hold_id"]) is False
        else:
            state.mutation_uncertain = True
        searched = await state.dispatch("search_tables", request)
        assert searched.get("offers") == []
        assert first["hold_id"] in state.holds
        if guard == "uncertain":
            assert await backend.get_hold(first["hold_id"]) is not None
            assert state.mutation_uncertain

    asyncio.run(run())


def test_reselecting_still_live_offer_never_replays_a_released_hold_receipt(tmp_path):
    async def run():
        backend = DemoTableAdapter(str(tmp_path / "tables.db"))
        state = CallTools(Dispatcher(table=backend, business="restaurant"))
        day = (
            datetime.now(ZoneInfo("Europe/Tallinn")).date() + timedelta(days=7)
        ).isoformat()
        request = {"date": day, "start_time": "18:00", "party_size": 6}
        offer = (await state.dispatch("search_tables", request))["offers"][0]
        first = await state.dispatch(
            "hold_table", {"table_offer_id": offer["table_offer_id"]}
        )
        assert first.get("hold_id")
        assert (await state.dispatch("search_tables", request))["offers"]
        assert await backend.get_hold(first["hold_id"]) is None
        again = await state.dispatch(
            "hold_table", {"table_offer_id": offer["table_offer_id"]}
        )
        assert again.get("hold_id") != first["hold_id"]
        assert await backend.get_hold(again["hold_id"]) is not None
        prepared = await state.dispatch(
            "prepare_demo_table", {"hold_id": again["hold_id"]}
        )
        assert prepared.get("ok") is True, prepared
        assert not state.pending["delivery"] and not state.bookings

    asyncio.run(run())
