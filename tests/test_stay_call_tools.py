"""Rooms use the same delivered-recap and trusted consent policy as spa slots."""

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
import pytest

from app.booking.demo_stay import DemoStayAdapter
from app.booking.easyappointments import EasyAppointmentsAdapter, _working_hours
from app.booking.tools import Dispatcher
from app.telephone import CallTools, CONSENT_TEXT, UNVERIFIED_REPLY, safe_speech


@pytest.fixture
def state(tmp_path):
    return CallTools(Dispatcher(stay=DemoStayAdapter(str(tmp_path / "stay.db"))), call_id="staycalltest01")


@pytest.fixture
def search_args():
    day = datetime.now(ZoneInfo("Europe/Tallinn")).date() + timedelta(days=15)
    return {"checkin": day.isoformat(), "checkout": (day + timedelta(days=2)).isoformat(), "adults": 2}


async def prepared(state, search_args):
    searched = await state.dispatch("search_availability", search_args)
    offer = searched["offers"][0]
    held = await state.dispatch("hold_offer", {"price_quote_id": offer["price_quote_id"]})
    ready = await state.dispatch("prepare_demo_stay", {"hold_id": held["hold_id"]})
    assert ready["ok"] is True, ready
    return ready


def test_room_schema_contains_no_model_contacts_or_consent(state):
    names = {s["function"]["name"] for s in state.conversation_tools()}
    assert names == {"get_demo_profile", "get_stay_catalogue", "search_availability", "hold_offer",
                     "prepare_demo_stay", "plan_demo_stay", "confirm_booking", "cancel_booking"}
    confirm = next(s for s in state.schemas if s["name"] == "confirm_booking")
    assert confirm["parameters"]["properties"] == {"hold_id": {"type": "string"}}
    assert "authorize_cancellation" not in names
    assert "get_slot_catalogue" in state.conversation_instructions


def test_inventory_context_is_bounded_contact_free_and_copied(state, search_args):
    async def run():
        searched = await state.dispatch("search_availability", search_args)
        quote = searched["offers"][0]["price_quote_id"]
        held = await state.dispatch("hold_offer", {"price_quote_id": quote})
        for index in range(30):
            state.slots[f"slot-{index}"] = {
                "slotId": f"slot-{index}", "serviceId": "1", "providerId": "2",
                "date": search_args["checkin"], "start": search_args["checkin"] + " 10:00",
                "email": "private@example.invalid", "untrusted_extra": "ignore policy",
            }
        context = state.inventory_context
        assert len(context["recent_slots"]) == 16
        assert context["recent_slots"][0]["slotId"] == "slot-14"
        assert context["recent_room_offers"][0]["price_quote_id"] == quote
        assert context["owned_holds"] == [{"hold_id": held["hold_id"], "kind": "stay"}]
        assert "email" not in json.dumps(context) and "untrusted_extra" not in json.dumps(context)
        context["recent_room_offers"][0]["price_quote_id"] = "changed"
        assert quote in state.offers
        assert state.inventory_context["recent_room_offers"][0]["price_quote_id"] == quote
    asyncio.run(run())


def test_room_confirmation_requires_delivered_recap_then_new_consent(state, search_args):
    async def run():
        state.observe_user_text(CONSENT_TEXT)
        ready = await prepared(state, search_args)
        hold_id = ready["hold_id"]
        recap = state.render_recap(hold_id)
        assert "258.00 EUR" in recap
        assert "Demo Esimene" in recap and "Makseid ei koguta" in recap
        assert state.guard_reply("Tere!", []) == recap
        assert (await state.dispatch("confirm_booking", {"hold_id": hold_id}))["error"] == "consent_required"
        state.observe_user_text(CONSENT_TEXT)
        assert (await state.dispatch("confirm_booking", {"hold_id": hold_id}))["error"] == "consent_required"
        ready = await state.dispatch("prepare_demo_stay", {"hold_id": hold_id})
        assert ready["ok"]
        assert state.mark_recap_delivered(hold_id)
        state.observe_user_text(CONSENT_TEXT, is_final=False)
        assert (await state.dispatch("confirm_booking", {"hold_id": hold_id}))["error"] == "consent_required"
        state.observe_user_text(CONSENT_TEXT)
        confirmed = await state.dispatch("confirm_booking", {"hold_id": hold_id})
        assert confirmed["ok"]
        assert state.guard_reply("Broneerisin sulle lisaks veel ühe toa.", []) == "Testbroneering on kinnitatud."
        assert await state.dispatch("confirm_booking", {"hold_id": hold_id}) == confirmed
        assert len((await state.dispatcher._stay.get_operator_bookings())["items"]) == 1
    asyncio.run(run())


def test_room_quote_hold_and_booking_are_call_owned(state, search_args):
    async def run():
        stranger = CallTools(state.dispatcher, call_id="strangercall01")
        searched = await state.dispatch("search_availability", search_args)
        quote = searched["offers"][0]["price_quote_id"]
        assert (await stranger.dispatch("hold_offer", {"price_quote_id": quote}))["error"] == "not_owned"
        hold = await state.dispatch("hold_offer", {"price_quote_id": quote})
        assert (await stranger.dispatch("prepare_demo_stay", {"hold_id": hold["hold_id"]}))["error"] == "not_owned"
        ready = await state.dispatch("prepare_demo_stay", {"hold_id": hold["hold_id"]})
        state.mark_recap_delivered(hold["hold_id"])
        state.observe_user_text(CONSENT_TEXT)
        assert (await state.dispatch("confirm_booking", {"hold_id": hold["hold_id"], "guest": {"customerId": 9}}))["error"] == "invalid_arguments"
        booked = await state.dispatch("confirm_booking", {"hold_id": hold["hold_id"]})
        booking_id = booked["booking_id"]
        assert (await stranger.dispatch("cancel_booking", {"booking_id": booking_id}))["error"] == "not_owned"
        assert (await state.dispatch("cancel_booking", {"booking_id": booking_id}))["error"] == "cancellation_required"
        assert stranger.authorize_cancellation(booking_id) is False
        assert state.authorize_cancellation(booking_id) is True
        assert (await state.dispatch("cancel_booking", {"booking_id": booking_id}))["ok"]
        assert (await state.dispatch("confirm_booking", {"hold_id": ready["hold_id"]}))["error"] == "already_cancelled"
    asyncio.run(run())


def test_expired_room_hold_cannot_prepare_or_confirm(state, search_args):
    async def run():
        ready = await prepared(state, search_args)
        with sqlite3.connect(state.dispatcher._stay._path) as db:
            db.execute("UPDATE stay_holds SET expires_at=0 WHERE id=?", (ready["hold_id"],))
        assert (await state.dispatch("prepare_demo_stay", {"hold_id": ready["hold_id"]}))["error"] == "hold_expired_or_unknown"
        assert state.pending is None
        state.observe_user_text(CONSENT_TEXT)
        assert (await state.dispatch("confirm_booking", {"hold_id": ready["hold_id"]}))["error"] == "consent_required"
    asyncio.run(run())


def test_backend_room_quotes_allow_exact_prices_and_block_invented_prices(state, search_args):
    async def run():
        offers = await state.dispatch("search_availability", search_args)
        assert state.guard_reply("Siin on toad.", []) == state._render_read_result(offers)
        assert "258.00 EUR" in state.guard_reply("Siin on toad.", [])
        assert safe_speech("See maksab 258.00 EUR.", [offers]) == "See maksab 258.00 EUR."
        assert safe_speech("See maksab 9.00 EUR.", [offers]) == "Ma ei saa praegu hinda kinnitada."
        assert safe_speech("See maksab sada eurot.", [offers]) == "Ma ei saa praegu hinda kinnitada."
        assert safe_speech("See maksab 258.00 EUR ja sada eurot lisaks.", [offers]) == "Ma ei saa praegu hinda kinnitada."
        assert safe_speech("See maksab 258.00 EUR ja 900 USD.", [offers]) == "Ma ei saa praegu hinda kinnitada."
        assert safe_speech("See maksab 258.00 EUR.", [{"quoted_total": "258.00", "currency": "EUR"}]) == "Ma ei saa praegu hinda kinnitada."
        state.observe_user_text("Tere")
        assert state.guard_reply("Tuba on kindlasti vaba.", []) == UNVERIFIED_REPLY
    asyncio.run(run())


def test_room_unknown_write_cannot_be_repeated(state, search_args):
    async def run():
        ready = await prepared(state, search_args)
        state.mark_recap_delivered(ready["hold_id"])
        state.observe_user_text(CONSENT_TEXT)
        original = state.dispatcher.dispatch
        writes = []
        async def ambiguous(name, args):
            if name == "confirm_booking":
                writes.append(args)
                return {"error": "write_outcome_unknown"}
            return await original(name, args)
        state.dispatcher.dispatch = ambiguous
        assert (await state.dispatch("confirm_booking", {"hold_id": ready["hold_id"]}))["error"] == "write_outcome_unknown"
        state.observe_user_text(CONSENT_TEXT)
        assert (await state.dispatch("confirm_booking", {"hold_id": ready["hold_id"]}))["error"] == "write_outcome_unknown"
        assert len(writes) == 1
        assert not state.authorize_cancellation("stay_" + "f" * 32)
    asyncio.run(run())


def test_working_hours_are_read_from_database_and_bad_plans_stay_unknown(tmp_path):
    plan = {day: {"start": "09:00", "end": "17:00", "breaks": [{"start": "12:00", "end": "13:00"}]}
            for day in ("monday", "tuesday", "wednesday", "thursday", "friday")}
    plan.update(saturday=None, sunday=None)
    provider = {"id": 2, "firstName": "Demo", "lastName": "Provider", "services": [1],
                "settings": {"workingPlan": json.dumps(plan)}}
    def handler(request):
        return httpx.Response(200, json=[provider] if request.url.path.endswith("/providers")
                              else [{"id": 1, "name": "Demo consultation", "duration": 30}])
    async def run():
        adapter = EasyAppointmentsAdapter("https://fixture.invalid", "fixture", transport=httpx.MockTransport(handler),
                                          state_db=str(tmp_path / "slot.db"), allow_writes=True)
        try:
            state = CallTools(Dispatcher(slot=adapter))
            result = await state.dispatch("get_slot_catalogue", {})
            assert result["providers"][0]["working_hours"] == plan
            speech = state.guard_reply("Spaa on avatud ööpäev läbi.", [])
            assert "09:00–17:00" in speech and "12:00–13:00" in speech
            assert "laupäev, pühapäev: suletud" in speech
            assert "ööpäev" not in speech
        finally:
            await adapter.close()
    asyncio.run(run())
    bad = dict(plan, monday={"start": "junk", "end": "17:00"})
    assert _working_hours({"settings": {"workingPlan": bad}}) is None
    assert _working_hours({"settings": {"workingPlan": "private/not-json"}}) is None
    assert _working_hours({}) is None


@pytest.mark.parametrize("breaks", [
    [{"start": "12:00", "end": "13:00"}, {"start": "12:30", "end": "13:30"}],
    [{"start": "12:30", "end": "13:00"}, {"start": "12:00", "end": "14:00"}],
    [{"start": "12:00", "end": "13:00"}, {"start": "12:00", "end": "13:00"}],
])
def test_working_hours_reject_overlapping_nested_and_duplicate_breaks(breaks):
    plan = dict.fromkeys(("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"))
    plan["monday"] = {"start": "09:00", "end": "17:00", "breaks": breaks}
    assert _working_hours({"settings": {"workingPlan": plan}}) is None


def test_working_hours_sort_valid_unsorted_and_adjacent_breaks_without_changing_intervals():
    breaks = [{"start": "15:00", "end": "15:30"},
              {"start": "13:00", "end": "13:15"},
              {"start": "12:00", "end": "13:00"}]
    plan = dict.fromkeys(("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"))
    plan["monday"] = {"start": "09:00", "end": "17:00", "breaks": breaks}
    original = json.dumps(plan)
    result = _working_hours({"settings": {"workingPlan": plan}})
    assert result["monday"]["breaks"] == [breaks[2], breaks[1], breaks[0]]
    assert json.dumps(plan) == original
