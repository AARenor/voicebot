import asyncio
import copy
import json
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from app.booking.tools import Dispatcher
from app.telephone import CallTools, CONSENT_TEXT, sdk_tools


CONSENT = "Jah, kinnitan selle testbroneeringu."
DAY = (datetime.now(ZoneInfo("Europe/Tallinn")) + timedelta(days=7)).date().isoformat()
REQUEST = {"date": DAY, "start_time": "10:30"}


class LiveSlots:
    operational = True

    def __init__(self):
        self.calls = []
        self.catalogue = {
            "services": [{"id": 6, "name": "Backend consultation", "duration": 45}],
            "providers": [{"id": 2, "name": "Backend therapist", "services": [6]}],
        }
        self.slots = [
            {
                "slotId": "backend-slot",
                "serviceId": "6",
                "providerId": "2",
                "date": DAY,
                "start": DAY + " 10:30:00",
            }
        ]
        self.confirm_result = {"ok": True, "booking": {"id": 42}}

    async def get_slot_catalogue(self):
        self.calls.append(("catalogue", {}))
        return copy.deepcopy(self.catalogue)

    async def search_slots(self, service, date, provider):
        self.calls.append(
            ("search", {"service": service, "date": date, "provider": provider})
        )
        return copy.deepcopy(self.slots)

    async def create_hold(self, slot_id):
        self.calls.append(("hold", {"slot_id": slot_id}))
        return SimpleNamespace(hold_id="backend-hold")

    async def confirm(self, hold_id, guest, key):
        self.calls.append(
            ("confirm", {"hold_id": hold_id, "guest": copy.deepcopy(guest), "key": key})
        )
        return copy.deepcopy(self.confirm_result)

    async def cancel(self, booking_id, key):
        self.calls.append(("cancel", {"booking_id": booking_id, "key": key}))
        return {"ok": True, "booking_id": booking_id}


class ObservedCallTools(CallTools):
    """Record the real policy boundary, without replacing its implementation."""

    def __init__(self, dispatcher):
        super().__init__(dispatcher)
        self.dispatched = []

    async def dispatch(self, name, args):
        self.dispatched.append(name)
        return await super().dispatch(name, args)


def state_and_backend():
    backend = LiveSlots()
    return ObservedCallTools(Dispatcher(slot=backend)), backend


async def plan(state, **overrides):
    return await state.dispatch("plan_demo_booking", {**REQUEST, **overrides})


def test_single_plan_reuses_catalogue_search_hold_prepare_guards_without_booking():
    async def run():
        state, backend = state_and_backend()
        result = await plan(state, guest_fixture_id="guest-002")
        assert result.get("ok"), result
        assert state.dispatched == [
            "plan_demo_booking",
            "get_slot_catalogue",
            "search_slots",
            "hold_slot",
            "prepare_demo_booking",
        ]
        assert [name for name, _ in backend.calls] == [
            "catalogue",
            "search",
            "hold",
            "catalogue",
        ]
        assert backend.calls[1][1] == {"service": "6", "provider": "2", "date": DAY}
        assert backend.calls[2][1]["slot_id"] == backend.slots[0]["slotId"]
        assert result["hold_id"] == "backend-hold"
        assert result["recap"] == {
            "serviceId": "6",
            "service_name": "Backend consultation",
            "providerId": "2",
            "provider_name": "Backend therapist",
            "date": DAY,
            "start": DAY + " 10:30:00",
            "timezone": "Europe/Tallinn",
            "guest_name": "Demo Teine",
        }
        assert result["guest"]["email"] == f"demo.teine+{state.call_id}@example.invalid"
        assert CONSENT_TEXT in result["consent_prompt_et"]
        assert state.holds == {"backend-hold"}
        assert state.pending["approved"] is False
        assert await state.dispatch(
            "confirm_slot_booking", {"hold_id": result["hold_id"]}
        ) == {"error": "consent_required"}
        assert not state.bookings
        assert not any(name == "confirm" for name, _ in backend.calls)

    asyncio.run(run())


@pytest.mark.parametrize(
    "overrides",
    [
        {"date": "nonsense"},
        {"date": "2026-02-30"},
        {"date": "2026-1-1"},
        {"date": []},
        {"start_time": "9:5"},
        {"start_time": "24:00"},
        {"start_time": "10:30:00"},
        {"start_time": None},
    ],
)
def test_malformed_plan_is_rejected_before_backend(overrides):
    async def run():
        state, backend = state_and_backend()
        assert await plan(state, **overrides) == {"error": "invalid_arguments"}
        assert not backend.calls

    asyncio.run(run())


def test_past_date_or_elapsed_time_today_never_searches_backend():
    async def run():
        today = datetime.now(ZoneInfo("Europe/Tallinn")).date()
        for requested_day in (
            (today - timedelta(days=1)).isoformat(),
            today.isoformat(),
        ):
            state, backend = state_and_backend()
            assert await plan(state, date=requested_day, start_time="00:00") == {
                "error": "past_datetime"
            }
            assert not backend.calls

    asyncio.run(run())


@pytest.mark.parametrize("fixture", ["unknown", None, []])
def test_plan_rejects_fake_guest_before_backend(fixture):
    async def run():
        state, backend = state_and_backend()
        assert await plan(state, guest_fixture_id=fixture) == {
            "error": "unknown_guest_fixture"
        }
        assert not backend.calls

    asyncio.run(run())


@pytest.mark.parametrize("section", ["services", "providers"])
def test_plan_rejects_ambiguous_catalogue_without_selecting_first(section):
    async def run():
        state, backend = state_and_backend()
        backend.catalogue[section].append({**backend.catalogue[section][0], "id": 99})
        assert await plan(state) == {"error": "ambiguous_catalogue"}
        assert [name for name, _ in backend.calls] == ["catalogue"]
        assert not state.holds

    asyncio.run(run())


@pytest.mark.parametrize(
    "catalogue",
    [{}, {"services": [], "providers": []}, {"services": None, "providers": []}],
)
def test_plan_rejects_empty_or_malformed_catalogue(catalogue):
    async def run():
        state, backend = state_and_backend()
        backend.catalogue = catalogue
        assert await plan(state) == {"error": "booking_unavailable"}
        assert [name for name, _ in backend.calls] == ["catalogue"]

    asyncio.run(run())


def test_closed_day_does_not_invent_hours_or_hold():
    async def run():
        state, backend = state_and_backend()
        backend.slots = []
        assert await plan(state) == {"error": "slot_unavailable"}
        assert [name for name, _ in backend.calls] == ["catalogue", "search"]
        assert not state.holds

    asyncio.run(run())


@pytest.mark.parametrize(
    "change",
    [
        {"start": DAY + " 11:00"},
        {"providerId": "99"},
        {"serviceId": "99"},
        {"date": "2099-01-01", "start": "2099-01-01 10:30"},
    ],
)
def test_plan_requires_exact_returned_date_time_service_provider(change):
    async def run():
        state, backend = state_and_backend()
        backend.slots[0].update(change)
        assert await plan(state) == {"error": "slot_unavailable"}
        assert not state.holds
        assert not any(name == "hold" for name, _ in backend.calls)

    asyncio.run(run())


def test_duplicate_exact_slots_fail_closed_as_ambiguous():
    async def run():
        state, backend = state_and_backend()
        backend.slots.append(copy.deepcopy(backend.slots[0]))
        assert await plan(state) == {"error": "ambiguous_slot"}
        assert not state.holds

    asyncio.run(run())


@pytest.mark.parametrize(
    "extra",
    [
        {"hold_id": "foreign"},
        {"service": "foreign"},
        {"provider": "foreign"},
        {"guest": {"email": "real@example.com"}},
        {"consent": True},
    ],
)
def test_plan_does_not_accept_foreign_identifiers_guest_or_model_approval(extra):
    async def run():
        state, backend = state_and_backend()
        assert await plan(state, **extra) == {"error": "invalid_arguments"}
        assert not backend.calls

    asyncio.run(run())


@pytest.mark.parametrize("stage", ["get_slot_catalogue", "search_slots", "create_hold"])
def test_backend_failures_are_closed_without_auto_confirmation(stage):
    async def run():
        state, backend = state_and_backend()

        async def fail(*args):
            raise RuntimeError("private provider body")

        setattr(backend, stage, fail)
        assert await plan(state) == {"error": "booking_unavailable"}
        assert state.pending is None
        assert not state.bookings

    asyncio.run(run())


def test_plan_preserves_subsequent_final_consent_uniqueness_replay_and_owned_cancel():
    async def run():
        state, backend = state_and_backend()
        state.observe_user_text(CONSENT)
        ready = await state.dispatch("plan_demo_booking", json.dumps(REQUEST))
        assert ready.get("ok"), ready
        args = {"hold_id": ready["hold_id"]}
        assert state.mark_recap_delivered(ready["hold_id"])
        state.observe_user_text(CONSENT, is_final=False)
        assert (await state.dispatch("confirm_slot_booking", args))[
            "error"
        ] == "consent_required"
        state.observe_user_text(CONSENT)
        first = await state.dispatch("confirm_slot_booking", args)
        assert first["ok"] is True
        assert await state.dispatch("confirm_slot_booking", args) == first
        assert sum(name == "confirm" for name, _ in backend.calls) == 1
        guest = next(
            payload["guest"] for name, payload in backend.calls if name == "confirm"
        )
        assert guest["email"] == f"demo.esimene+{state.call_id}@example.invalid"
        other = CallTools(Dispatcher(slot=backend))
        assert (await other.dispatch("confirm_slot_booking", args))[
            "error"
        ] == "not_owned"
        cancel_args = {"booking_id": "42"}
        assert (await state.dispatch("cancel_slot_booking", cancel_args))[
            "error"
        ] == "cancellation_required"
        state.observe_user_text("Palun tühista see testbroneering.")
        cancelled = await state.dispatch("cancel_slot_booking", cancel_args)
        assert cancelled["ok"] is True
        assert await state.dispatch("cancel_slot_booking", cancel_args) == cancelled
        assert sum(name == "cancel" for name, _ in backend.calls) == 1

    asyncio.run(run())


@pytest.mark.parametrize("new_request", [{**REQUEST, "start_time": "bad"}, [], "{"])
def test_new_plan_even_if_invalid_clears_old_approval(new_request):
    async def run():
        state, backend = state_and_backend()
        assert (await plan(state)).get("ok")
        assert state.mark_recap_delivered("backend-hold")
        state.observe_user_text(CONSENT)
        assert (await state.dispatch("plan_demo_booking", new_request))[
            "error"
        ] == "invalid_arguments"
        assert (
            await state.dispatch("confirm_slot_booking", {"hold_id": "backend-hold"})
        )["error"] == "consent_required"
        assert not any(name == "confirm" for name, _ in backend.calls)

    asyncio.run(run())


def test_plan_decline_expiry_require_fresh_consent_and_unknown_blocks_retry():
    async def run():
        state, backend = state_and_backend()
        assert (await plan(state)).get("ok")
        state.observe_user_text("Ei, ära kinnita broneeringut.")
        args = {"hold_id": "backend-hold"}
        assert (await state.dispatch("confirm_slot_booking", args))[
            "error"
        ] == "consent_required"
        with patch("app.telephone.time.monotonic", return_value=100):
            assert (await plan(state)).get("ok")
            assert state.mark_recap_delivered("backend-hold")
            state.observe_user_text(CONSENT)
        with patch("app.telephone.time.monotonic", return_value=161):
            assert (await state.dispatch("confirm_slot_booking", args))[
                "error"
            ] == "consent_required"
        assert (await plan(state)).get("ok")
        assert state.mark_recap_delivered("backend-hold")
        state.observe_user_text(CONSENT)
        backend.confirm_result = {"ok": False, "error": "write_outcome_unknown"}
        assert (await state.dispatch("confirm_slot_booking", args))[
            "error"
        ] == "write_outcome_unknown"
        assert state.outcome == "write_outcome_unknown"
        assert (await state.dispatch("confirm_slot_booking", args))[
            "error"
        ] == "write_outcome_unknown"
        assert (await plan(state))["error"] == "mutation_outcome_unknown"
        assert not state.mark_recap_delivered("backend-hold")
        state.observe_user_text(CONSENT)
        await state.dispatch("confirm_slot_booking", args)
        writes = [payload for name, payload in backend.calls if name == "confirm"]
        assert len(writes) == 1
        assert not state.bookings

    asyncio.run(run())


def test_conversation_tools_advertise_catalogue_and_service_selection_paths():
    state, _ = state_and_backend()
    assert callable(getattr(state, "conversation_tools", None)), (
        "compact tools are missing"
    )
    tools = state.conversation_tools()
    assert {t["function"]["name"] for t in tools} == {
        "get_demo_profile",
        "plan_demo_booking",
        "confirm_slot_booking",
        "cancel_slot_booking",
        "get_slot_catalogue",
        "search_slots",
        "hold_slot",
        "prepare_demo_booking",
    }
    assert {
        "get_slot_catalogue",
        "search_slots",
        "hold_slot",
        "prepare_demo_booking",
    } <= state.names
    tools[0]["function"]["parameters"]["properties"]["model_flag"] = {}
    assert (
        "model_flag"
        not in state.conversation_tools()[0]["function"]["parameters"]["properties"]
    )


def test_compact_prompt_keeps_fiction_faq_names_date_safety_without_contacts_or_history():
    state, _ = state_and_backend()
    assert hasattr(state, "conversation_instructions"), (
        "compact instructions are missing"
    )
    instructions = state.conversation_instructions
    assert "Meretuule Demo Spa" in instructions
    assert "current_date" in instructions
    assert "Europe/Tallinn" in instructions
    assert "Demo Esimene" in instructions and "Demo Teine" in instructions
    assert state.demo["faq"][0]["answer_et"] in instructions
    assert CONSENT_TEXT in instructions
    assert "plan_demo_booking" in instructions
    assert "Ära küsi päris" in instructions
    assert "get_slot_catalogue" in instructions
    assert "get_stay_catalogue" in instructions
    assert "search_availability" in instructions
    assert state.call_id not in instructions
    assert "example.invalid" not in instructions and "+120255501" not in instructions
    assert "2026-10-05" not in instructions and "working_hours" not in instructions
    full = len(state.instructions) + len(
        json.dumps(state.available_tools(), ensure_ascii=False)
    )
    compact = len(instructions) + len(
        json.dumps(state.conversation_tools(), ensure_ascii=False)
    )
    assert compact < full, (full, compact)


def test_native_sdk_compact_tools_delegate_one_plan_and_leave_default_tools_available():
    pytest.importorskip("livekit.agents")
    from livekit.agents.llm.tool_context import get_raw_function_info

    async def run():
        state, backend = state_and_backend()
        assert callable(getattr(state, "conversation_tools", None)), (
            "compact tools are missing"
        )
        compact = {
            get_raw_function_info(t).name: t
            for t in sdk_tools(state, conversation=True)
        }
        assert set(compact) == {
            "get_demo_profile",
            "plan_demo_booking",
            "confirm_slot_booking",
            "cancel_slot_booking",
            "get_slot_catalogue",
            "search_slots",
            "hold_slot",
            "prepare_demo_booking",
        }
        manual = {get_raw_function_info(t).name for t in sdk_tools(state)}
        assert {"search_slots", "hold_slot", "prepare_demo_booking"} <= manual
        assert (await compact["plan_demo_booking"](REQUEST))["ok"] is True
        assert not any(name == "confirm" for name, _ in backend.calls)

    asyncio.run(run())
