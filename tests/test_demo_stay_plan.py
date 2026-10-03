"""One model tool prepares an exact room quote without bypassing call policy."""

import asyncio
import copy
import sqlite3
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.booking.demo_stay import DemoStayAdapter
from app.booking.tools import Dispatcher
from app.telephone import CallTools, CONSENT_TEXT, sdk_tools


class ObservedCallTools(CallTools):
    def __init__(self, dispatcher):
        super().__init__(dispatcher)
        self.dispatched = []

    async def dispatch(self, name, args):
        self.dispatched.append(name)
        return await super().dispatch(name, args)


@pytest.fixture
def backend(tmp_path):
    return DemoStayAdapter(str(tmp_path / "rooms.db"))


@pytest.fixture
def state(backend):
    return ObservedCallTools(Dispatcher(stay=backend))


@pytest.fixture
def request_args():
    day = datetime.now(ZoneInfo("Europe/Tallinn")).date() + timedelta(days=10)
    return {"checkin": day.isoformat(), "checkout": (day + timedelta(days=2)).isoformat(),
            "adults": 2, "children": 0, "room_type": "garden-double"}


async def plan(state, request_args, **overrides):
    return await state.dispatch("plan_demo_stay", {**request_args, **overrides})


@pytest.mark.parametrize("room_type,total", [("garden-double", "258.00"), ("  SPAA SVIIT  ", "398.00")])
def test_one_plan_reads_holds_and_prepares_exact_quote_without_confirming(state, backend, request_args, room_type, total):
    async def run():
        state.observe_user_text(CONSENT_TEXT)
        result = await plan(state, request_args, room_type=room_type, guest_fixture_id="guest-002")
        assert result["ok"] is True
        assert state.dispatched == ["plan_demo_stay", "get_stay_catalogue", "search_availability",
                                    "hold_offer", "prepare_demo_stay"]
        assert result["quoted_total"] == total
        assert result["recap"]["quoted_total"] == total
        assert result["recap"]["checkin"] == request_args["checkin"]
        assert result["recap"]["checkout"] == request_args["checkout"]
        assert result["recap"]["guest_name"] == "Demo Teine"
        assert state.held_stays[result["hold_id"]]["price_quote_id"] == result["price_quote_id"]
        assert state.pending["approved"] is False and state.pending["delivery"] is False
        assert total + " EUR" in state.render_recap()
        assert (await backend.get_operator_bookings())["items"] == []
        assert (await state.dispatch("confirm_booking", {"hold_id": result["hold_id"]}))["error"] == "consent_required"
        assert state.mark_recap_delivered(result["hold_id"])
        state.observe_user_text(CONSENT_TEXT)
        confirmed = await state.dispatch("confirm_booking", {"hold_id": result["hold_id"]})
        assert confirmed["ok"] is True
        assert confirmed["booking"]["quoted_total"] == total
        assert confirmed["booking"]["guest_name"] == "Demo Teine"
        assert len((await backend.get_operator_bookings())["items"]) == 1
    asyncio.run(run())


@pytest.mark.parametrize("overrides", [
    {"checkin": "not-a-date"}, {"checkin": "2026-02-30"}, {"checkin": "2026-1-1"},
    {"checkin": []}, {"checkout": None}, {"adults": True}, {"adults": 0},
    {"adults": "2"}, {"children": True}, {"children": -1}, {"children": 9},
    {"room_type": []}, {"room_type": "x" * 201},
])
def test_malformed_plan_never_reads_backend(state, backend, request_args, overrides):
    async def run():
        assert await plan(state, request_args, **overrides) == {"error": "invalid_arguments"}
        assert state.dispatched == ["plan_demo_stay"]
        assert (await backend.get_operator_bookings())["items"] == []
    asyncio.run(run())


def test_reversed_long_and_past_stays_never_search(state, request_args):
    async def run():
        start = datetime.fromisoformat(request_args["checkin"]).date()
        yesterday = datetime.now(ZoneInfo("Europe/Tallinn")).date() - timedelta(days=1)
        cases = [
            ({"checkout": request_args["checkin"]}, "invalid_arguments"),
            ({"checkout": (start + timedelta(days=31)).isoformat()}, "invalid_arguments"),
            ({"checkin": yesterday.isoformat()}, "past_datetime"),
        ]
        for overrides, error in cases:
            state.dispatched.clear()
            assert await plan(state, request_args, **overrides) == {"error": error}
            assert state.dispatched == ["plan_demo_stay"]
    asyncio.run(run())


@pytest.mark.parametrize("fixture", ["unknown", None, []])
def test_unknown_guest_is_rejected_before_catalogue(state, request_args, fixture):
    async def run():
        assert await plan(state, request_args, guest_fixture_id=fixture) == {"error": "unknown_guest_fixture"}
        assert state.dispatched == ["plan_demo_stay"]
    asyncio.run(run())


@pytest.mark.parametrize("room_type", [None, "", "unknown-room"])
def test_missing_or_unknown_room_type_returns_real_options_without_holding(state, request_args, room_type):
    async def run():
        result = await plan(state, request_args, room_type=room_type)
        assert result["needs_room_type"] is True
        assert len(result["catalogue"]["room_types"]) == 3
        assert {offer["room_type_id"] for offer in result["offers"]} == {"garden-double", "spa-suite", "family-room"}
        assert state.dispatched == ["plan_demo_stay", "get_stay_catalogue", "search_availability"]
        assert state.holds == set() and state.pending is None
        assert "258.00 EUR" in state.guard_reply("Siin on valikud.", [])
    asyncio.run(run())


def test_single_available_room_type_still_requires_user_choice(state, request_args):
    async def run():
        result = await plan(state, request_args, room_type=None, children=2)
        assert result["needs_room_type"] is True
        assert [offer["room_type_id"] for offer in result["offers"]] == ["family-room"]
        assert state.holds == set() and state.pending is None
        selected = await plan(state, request_args, room_type="family-room", children=2)
        assert selected["ok"] is True
        assert selected["recap"]["adults"] == 2 and selected["recap"]["children"] == 2
    asyncio.run(run())


def test_ambiguous_catalogue_names_do_not_choose_first(state, backend, request_args):
    async def run():
        with sqlite3.connect(backend._path) as db:
            db.execute("UPDATE stay_room_types SET name='Peretuba' WHERE id='garden-double'")
        result = await plan(state, request_args, room_type="Peretuba")
        assert result["needs_room_type"] is True
        assert result["offers"]
        assert state.holds == set() and state.pending is None
        assert "hold_offer" not in state.dispatched
    asyncio.run(run())


def test_multiple_matching_offers_are_options_not_an_arbitrary_rate(state, backend, request_args):
    async def run():
        original = backend.search_availability
        async def multiple(*args):
            return [*(await original(*args)), *(await original(*args))]
        backend.search_availability = multiple
        result = await plan(state, request_args)
        assert result["needs_room_type"] is True
        assert len(result["offers"]) == 2
        assert state.holds == set() and state.pending is None
    asyncio.run(run())


@pytest.mark.parametrize("change,error", [
    ({"room_type_id": "spa-suite"}, "room_unavailable"),
    ({"adults": 3}, "booking_unavailable"),
    ({"checkout": "2099-11-05"}, "booking_unavailable"),
])
def test_nonmatching_backend_offers_are_never_held(state, backend, request_args, change, error):
    async def run():
        original = backend.search_availability
        async def changed(*args):
            return [{**offer, **change} for offer in await original(*args)]
        backend.search_availability = changed
        assert (await plan(state, request_args))["error"] == error
        assert state.holds == set() and state.pending is None
    asyncio.run(run())


def test_unavailable_requested_room_does_not_substitute_another_type(state, backend, request_args):
    async def run():
        with sqlite3.connect(backend._path) as db:
            db.execute("UPDATE stay_rooms SET active=0 WHERE room_type_id='garden-double'")
        result = await plan(state, request_args)
        assert result["error"] == "room_unavailable"
        assert result["offers"] == []
        assert state.holds == set() and state.pending is None
    asyncio.run(run())


def test_quote_expiry_between_search_and_hold_cannot_prepare(state, backend, request_args):
    async def run():
        original = backend.create_hold
        async def expired(quote_id):
            with sqlite3.connect(backend._path) as db:
                db.execute("UPDATE stay_quotes SET expires_at=0 WHERE id=?", (quote_id,))
            return await original(quote_id)
        backend.create_hold = expired
        assert (await plan(state, request_args))["error"] == "booking_unavailable"
        assert state.holds == set() and state.pending is None
    asyncio.run(run())


def test_plan_cannot_supply_contacts_consent_or_foreign_write_identity(state, request_args):
    async def run():
        for extra in ({"guest": {"customerId": 1}}, {"consent": True}, {"hold_id": "foreign"}):
            assert await plan(state, request_args, **extra) == {"error": "invalid_arguments"}
        ready = await plan(state, request_args)
        stranger = CallTools(state.dispatcher)
        assert (await stranger.dispatch("confirm_booking", {"hold_id": ready["hold_id"]}))["error"] == "not_owned"
        state.mutation_uncertain = True
        assert (await plan(state, request_args))["error"] == "mutation_outcome_unknown"
    asyncio.run(run())


@pytest.mark.parametrize("phase", ["catalogue", "search", "hold", "prepare"])
@pytest.mark.parametrize("interrupted", [False, True])
def test_every_stay_plan_await_preserves_superseding_turn(state, backend, request_args, phase, interrupted):
    async def run():
        started, finish = asyncio.Event(), asyncio.Event()
        method = {"catalogue": "get_stay_catalogue", "search": "search_availability",
                  "hold": "create_hold", "prepare": "get_hold"}[phase]
        original = getattr(backend, method)
        async def paused(*args):
            started.set()
            await finish.wait()
            return await original(*args)
        setattr(backend, method, paused)
        old_plan = asyncio.create_task(plan(state, request_args))
        await asyncio.wait_for(started.wait(), 2)
        state.observe_user_text("Ei, ära broneeri.")
        await state.dispatch("get_demo_profile", {})
        results, outcome, holds = copy.deepcopy(state.results), state.outcome, set(state.holds)
        if interrupted:
            old_plan.cancel()
            with pytest.raises(asyncio.CancelledError):
                await old_plan
        else:
            finish.set()
            assert await asyncio.wait_for(old_plan, 2) == {"error": "turn_superseded"}
        assert state.pending is None
        assert state.results == results and state.outcome == outcome
        assert state.holds == holds
        assert state.bookings == set()
    asyncio.run(run())


def test_http_tool_schema_exposes_one_plan_with_server_bound_guest(state):
    schema = next(tool["function"] for tool in state.conversation_tools()
                  if tool["function"]["name"] == "plan_demo_stay")
    assert schema["parameters"]["required"] == ["checkin", "checkout"]
    assert schema["parameters"]["additionalProperties"] is False
    assert schema["parameters"]["properties"]["guest_fixture_id"]["default"] == "guest-001"
    assert not {"guest", "consent", "idempotency_key", "hold_id"} & set(schema["parameters"]["properties"])
    assert "plan_demo_stay" in state.conversation_instructions


def test_native_tool_uses_the_same_plan_policy(state, request_args):
    pytest.importorskip("livekit.agents")
    from livekit.agents.llm.tool_context import get_raw_function_info
    async def run():
        tools = {get_raw_function_info(tool).name: tool for tool in sdk_tools(state, conversation=True)}
        result = await tools["plan_demo_stay"](request_args)
        assert result["ok"] is True
        assert state.pending["approved"] is False
        assert "confirm_booking" not in state.dispatched
    asyncio.run(run())
