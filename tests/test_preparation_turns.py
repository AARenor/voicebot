"""Late preparation reads must not restore proposals after a newer final turn."""

import asyncio
import copy
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.booking.demo_stay import DemoStayAdapter
from app.booking.tools import Dispatcher
from app.telephone import CallTools, CONSENT_TEXT
from tests.test_demo_plan import LiveSlots, REQUEST


async def held_state(kind, tmp_path):
    if kind == "slot":
        state = CallTools(Dispatcher(slot=LiveSlots()))
        searched = await state.dispatch("search_slots", {
            "service": "6", "provider": "2", "date": REQUEST["date"],
        })
        held = await state.dispatch("hold_slot", {"slot_id": searched["slots"][0]["slotId"]})
        return state, held["hold_id"], "prepare_demo_booking"
    state = CallTools(Dispatcher(stay=DemoStayAdapter(str(tmp_path / "stay.db"))))
    day = datetime.now(ZoneInfo("Europe/Tallinn")).date() + timedelta(days=15)
    searched = await state.dispatch("search_availability", {
        "checkin": day.isoformat(), "checkout": (day + timedelta(days=2)).isoformat(), "adults": 2,
    })
    held = await state.dispatch("hold_offer", {"price_quote_id": searched["offers"][0]["price_quote_id"]})
    return state, held["hold_id"], "prepare_demo_stay"


@pytest.mark.parametrize("kind", ["slot", "stay"])
@pytest.mark.parametrize("replacement", ["decline", "new_proposal"])
@pytest.mark.parametrize("late_failure", [False, True])
@pytest.mark.parametrize("dispatch", [False, True])
def test_superseded_preparation_preserves_newer_turn_state(tmp_path, kind, replacement, late_failure, dispatch):
    async def run():
        state, hold_id, prepare_name = await held_state(kind, tmp_path)
        started, finish = asyncio.Event(), asyncio.Event()
        first_read = True
        original = state.dispatcher.dispatch if kind == "slot" else state.dispatcher.get_stay_hold

        async def paused(*args):
            nonlocal first_read
            if first_read and (kind == "stay" or args[0] == "get_slot_catalogue"):
                first_read = False
                started.set()
                await finish.wait()
                if late_failure:
                    raise RuntimeError("old preparation read failed")
            return await original(*args)

        if kind == "slot":
            state.dispatcher.dispatch = paused
        else:
            state.dispatcher.get_stay_hold = paused
        invocation = state.dispatch(prepare_name, {"hold_id": hold_id}) if dispatch else getattr(state, prepare_name)(hold_id)
        old_preparation = asyncio.create_task(invocation)
        await asyncio.wait_for(started.wait(), 2)
        state.observe_user_text("Ei, ära broneeri.")
        if replacement == "new_proposal":
            newer = await state.dispatch(prepare_name, {"hold_id": hold_id, "guest_fixture_id": "guest-002"})
            assert newer["ok"] is True
        else:
            await state.dispatch("get_demo_profile", {})
        pending = copy.deepcopy(state.pending)
        results = copy.deepcopy(state.results)
        outcome = state.outcome
        finish.set()
        assert await asyncio.wait_for(old_preparation, 2) == {"error": "turn_superseded"}
        assert state.pending == pending
        assert state.results == results
        assert state.outcome == outcome
        if replacement == "decline":
            assert state.pending is None
            assert state.mark_recap_delivered(hold_id) is False
        else:
            assert state.pending["guest_fixture_id"] == "guest-002"
            assert state.pending["approved"] is False and state.pending["delivery"] is False
        state.observe_user_text(CONSENT_TEXT)
        confirm = "confirm_slot_booking" if kind == "slot" else "confirm_booking"
        assert (await state.dispatch(confirm, {"hold_id": hold_id}))["error"] == "consent_required"
    asyncio.run(run())


@pytest.mark.parametrize("phase", ["catalogue", "search", "hold", "prepare"])
def test_superseded_spa_plan_stops_after_each_preparation_await(phase):
    async def run():
        backend = LiveSlots()
        state = CallTools(Dispatcher(slot=backend))
        started, finish = asyncio.Event(), asyncio.Event()
        method = {"catalogue": "get_slot_catalogue", "search": "search_slots",
                  "hold": "create_hold", "prepare": "get_slot_catalogue"}[phase]
        original = getattr(backend, method)
        reads = 0

        async def paused(*args):
            nonlocal reads
            reads += 1
            if reads == (2 if phase == "prepare" else 1):
                started.set()
                await finish.wait()
            return await original(*args)

        setattr(backend, method, paused)
        old_plan = asyncio.create_task(state.dispatch("plan_demo_booking", REQUEST))
        await asyncio.wait_for(started.wait(), 2)
        state.observe_user_text("Ei, ära broneeri.")
        await state.dispatch("get_demo_profile", {})
        results = copy.deepcopy(state.results)
        outcome = state.outcome
        owned_holds = set(state.holds)
        finish.set()
        assert await asyncio.wait_for(old_plan, 2) == {"error": "turn_superseded"}
        assert state.pending is None
        assert state.results == results
        assert state.outcome == outcome
        assert state.holds == owned_holds
        assert not any(name == "confirm" for name, _ in backend.calls)
    asyncio.run(run())
