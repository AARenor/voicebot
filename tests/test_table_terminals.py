"""Restaurant terminal actions stay on the trusted policy/SDK, not model prose."""

import asyncio
from unittest.mock import patch

import pytest

from app.booking_response import trusted_booking_response
from app.languages import CONSENT
from tests.test_table_policy import prepare_table, table_state


@pytest.mark.parametrize("language", ["et", "en", "ru"])
def test_trusted_table_terminal_actions_need_no_model_requests(language):
    async def run():
        state, backend = table_state(language=language)
        ready = await prepare_table(state)
        assert trusted_booking_response(state, after_tool=True) == {
            "content": state.render_recap()
        }
        assert trusted_booking_response(state) is None
        state.mark_recap_delivered(ready["hold_id"])
        state.observe_user_text(CONSENT[language], language=language)
        assert trusted_booking_response(state, allow_actions=False) is None
        command = trusted_booking_response(state)
        assert command == {
            "name": "confirm_table_booking",
            "arguments": {"hold_id": ready["hold_id"]},
        }
        confirmed = await state.dispatch(command["name"], command["arguments"])
        assert confirmed.get("ok"), confirmed
        assert trusted_booking_response(state, after_tool=True) == {
            "content": state.guard_reply("", state.results)
        }
        state.observe_user_text(
            {
                "et": "Palun tühista see testbroneering.",
                "en": "Please cancel this test booking.",
                "ru": "Пожалуйста отмените это тестовое бронирование.",
            }[language],
            language=language,
        )
        command = trusted_booking_response(state)
        assert command == {
            "name": "cancel_table_booking",
            "arguments": {"booking_id": confirmed["booking_id"]},
        }
        assert (await state.dispatch(command["name"], command["arguments"]))["ok"]
        assert [name for name, _ in backend.calls if name in {"confirm", "cancel"}] == [
            "confirm",
            "cancel",
        ]

    asyncio.run(run())


@pytest.mark.parametrize(
    "error",
    ["write_outcome_unknown", "cancel_outcome_unknown", "mutation_outcome_unknown"],
)
def test_table_unknown_write_is_sticky_and_cannot_blind_retry(error):
    async def run():
        state, backend = table_state()
        ready = await prepare_table(state)
        state.mark_recap_delivered(ready["hold_id"])
        state.observe_user_text(CONSENT["et"])
        backend.confirm_result = {"error": error}
        assert (
            await state.dispatch("confirm_table_booking", {"hold_id": ready["hold_id"]})
        )["error"] == error
        state.observe_user_text(CONSENT["et"])
        assert state.mutation_uncertain and state.outcome == "write_outcome_unknown"
        assert trusted_booking_response(state) == {"content": state.guard_reply("", [])}
        await state.dispatch("confirm_table_booking", {"hold_id": ready["hold_id"]})
        assert (await prepare_table(state))["error"] == "mutation_outcome_unknown"
        assert sum(name == "confirm" for name, _ in backend.calls) == 1
        assert not state.bookings and state.pending is None

    asyncio.run(run())


def test_sdk_table_tools_use_the_same_owned_policy_and_compact_schema():
    pytest.importorskip("livekit.agents")
    from livekit.agents.llm.tool_context import get_raw_function_info
    from app.telephone import sdk_tools

    async def run():
        state, backend = table_state()
        tools = {
            get_raw_function_info(tool).name: tool
            for tool in sdk_tools(state, conversation=True)
        }
        assert set(tools) == {
            "get_demo_profile",
            "get_table_catalogue",
            "plan_demo_table",
            "confirm_table_booking",
            "cancel_table_booking",
        }
        ready = await tools["plan_demo_table"](
            {"date": backend.offers[0]["date"], "start_time": "18:30", "party_size": 4}
        )
        assert ready.get("ok"), ready
        assert (await tools["confirm_table_booking"]({"hold_id": ready["hold_id"]}))[
            "error"
        ] == "consent_required"
        state.mark_recap_delivered(ready["hold_id"])
        state.observe_user_text(CONSENT["et"])
        assert (await tools["confirm_table_booking"]({"hold_id": ready["hold_id"]}))[
            "ok"
        ]

    asyncio.run(run())


def test_rejected_terminal_write_finishes_truthfully_without_model_followup():
    async def run():
        state, backend = table_state()
        ready = await prepare_table(state)
        state.mark_recap_delivered(ready["hold_id"])
        state.observe_user_text(CONSENT["et"])
        backend.confirm_result = {"ok": False, "error": "table_unavailable"}
        await state.dispatch("confirm_table_booking", {"hold_id": ready["hold_id"]})
        assert trusted_booking_response(state, after_tool=True) == {
            "content": state.guard_reply("", state.results)
        }
        assert not state.bookings and state.pending is None

    asyncio.run(run())


@pytest.mark.parametrize(
    "change",
    [
        {"party_size": 2},
        {"party_size": 4.0},
        {"date": "2099-01-01"},
        {"start_time": "19:00"},
        {"table_id": "table-04"},
        {"table_name": "Laud 4"},
        {"capacity": 6},
        {"duration_minutes": 60},
        {"start": "2099-01-01T18:30:00+02:00"},
        {"end": "2099-01-01T20:30:00+02:00"},
        {"timezone": "UTC"},
        {"venue_name": "Other Restaurant"},
        {"guest_name": "Demo Teine"},
        {"table_offer_id": "foreign"},
        {"kind": "stay"},
        {"status": "cancelled"},
        {"quoted_total": "25.00"},
    ],
)
def test_table_confirmation_receipt_for_different_request_cannot_become_success(change):
    async def run():
        state, backend = table_state()
        ready = await prepare_table(state)
        state.mark_recap_delivered(ready["hold_id"])
        state.observe_user_text(CONSENT["et"])
        original = backend.confirm

        async def mismatched(*args):
            result = await original(*args)
            result["booking"].update(change)
            return result

        backend.confirm = mismatched
        assert (
            await state.dispatch("confirm_table_booking", {"hold_id": ready["hold_id"]})
        )["error"] == "write_outcome_unknown"
        assert state.mutation_uncertain and not state.bookings
        assert not state.booking_receipts and state.pending is None

    asyncio.run(run())


@pytest.mark.parametrize(
    "field", ["date", "start", "end", "party_size", "table_id", "guest_name", "status"]
)
def test_incomplete_table_confirmation_receipt_is_not_success(field):
    async def run():
        state, backend = table_state()
        ready = await prepare_table(state)
        state.mark_recap_delivered(ready["hold_id"])
        state.observe_user_text(CONSENT["et"])
        original = backend.confirm

        async def incomplete(*args):
            result = await original(*args)
            result["booking"].pop(field)
            return result

        backend.confirm = incomplete
        result = await state.dispatch(
            "confirm_table_booking", {"hold_id": ready["hold_id"]}
        )
        assert result == {"error": "write_outcome_unknown"}
        assert state.mutation_uncertain and not state.bookings

    asyncio.run(run())


@pytest.mark.parametrize(
    "change",
    [
        {"booking_id": None},
        {"kind": None},
        {"status": None},
        {"kind": "stay"},
        {"status": "confirmed"},
    ],
)
def test_table_cancellation_missing_or_contradictory_receipt_is_not_success(change):
    async def run():
        state, backend = table_state()
        ready = await prepare_table(state)
        state.mark_recap_delivered(ready["hold_id"])
        state.observe_user_text(CONSENT["et"])
        confirmed = await state.dispatch(
            "confirm_table_booking", {"hold_id": ready["hold_id"]}
        )
        booking_id = confirmed["booking_id"]
        assert state.authorize_cancellation(booking_id)
        for field, value in change.items():
            if value is None:
                backend.cancel_result.pop(field)
            else:
                backend.cancel_result[field] = value
        assert await state.dispatch(
            "cancel_table_booking", {"booking_id": booking_id}
        ) == {"error": "cancel_outcome_unknown"}
        assert state.mutation_uncertain and not state.cancelled_bookings
        assert len(state.booking_receipts) == 1
        state.observe_user_text("Palun tühista see testbroneering.")
        assert (
            await state.dispatch("cancel_table_booking", {"booking_id": booking_id})
        ).get("error")
        assert sum(name == "cancel" for name, _ in backend.calls) == 1

    asyncio.run(run())


@pytest.mark.parametrize("mutation", ["confirm", "cancel"])
@pytest.mark.parametrize(
    "failure", ["exception", "cancellation", "empty_receipt", "wrong_id"]
)
def test_table_mutation_exceptions_and_untrusted_receipts_are_sticky_unknown(
    mutation, failure
):
    async def run():
        state, backend = table_state()
        ready = await prepare_table(state)
        state.mark_recap_delivered(ready["hold_id"])
        state.observe_user_text(CONSENT["et"])
        if mutation == "cancel":
            confirmed = await state.dispatch(
                "confirm_table_booking", {"hold_id": ready["hold_id"]}
            )
            assert state.authorize_cancellation(confirmed["booking_id"])
            name, args = "cancel_table_booking", {"booking_id": confirmed["booking_id"]}
        else:
            name, args = "confirm_table_booking", {"hold_id": ready["hold_id"]}
        original = getattr(backend, mutation)

        async def bad_write(*arguments):
            await original(*arguments)
            if failure == "exception":
                raise RuntimeError("PRIVATE provider body")
            if failure == "cancellation":
                raise asyncio.CancelledError
            if failure == "empty_receipt":
                return {}
            return {"ok": True, "booking_id": "foreign", "booking": {"id": "foreign"}}

        setattr(backend, mutation, bad_write)
        if failure == "cancellation":
            with pytest.raises(asyncio.CancelledError):
                await state.dispatch(name, args)
        else:
            assert (await state.dispatch(name, args)).get("error") in {
                "write_outcome_unknown",
                "cancel_outcome_unknown",
            }
        assert state.mutation_uncertain and state.outcome == "write_outcome_unknown"
        state.observe_user_text(CONSENT["et"])
        assert (await state.dispatch(name, args)).get("error")
        assert sum(call == mutation for call, _ in backend.calls) == 1
        assert "PRIVATE" not in state.guard_reply("success", [])

    asyncio.run(run())


@pytest.mark.parametrize("language", ["et", "en", "ru"])
def test_real_native_table_plan_delivery_confirm_cancel_use_one_model_call(
    tmp_path, language
):
    pytest.importorskip("livekit.agents")
    from livekit.agents import AgentSession
    from app.booking.demo_table import DemoTableAdapter
    from app.booking.tools import Dispatcher
    from app.telephone import CallTools
    from app.worker import TelephoneAgent
    from tests.test_native_booking_terminals import (
        PlanningModel,
        UnusedTTS,
        Playback,
        native_turn,
        synthesize,
    )
    from tests.test_table_policy import DAY, REQUEST

    async def run():
        backend = DemoTableAdapter(str(tmp_path / "restaurant.db"))
        state = CallTools(
            Dispatcher(table=backend, business="restaurant"), language=language
        )
        model = PlanningModel("plan_demo_table", REQUEST)
        agent = TelephoneAgent(state)
        session = AgentSession(
            llm=model, tts=UnusedTTS(), turn_handling={"turn_detection": "manual"}
        )
        session.output.audio = Playback()
        session.on("conversation_item_added", agent.on_conversation_item_added)
        executed = []
        session.on(
            "function_tools_executed",
            lambda event: executed.extend(event.function_calls),
        )
        with patch("livekit.agents.Agent.default.tts_node", synthesize):
            await session.start(agent=agent, record=False)
            try:
                await native_turn(
                    session,
                    agent,
                    {
                        "et": f"Soovin lauda broneerida {DAY} kell 18:30, kokku 4 inimest.",
                        "en": f"Please book a table on {DAY} at 18:30 for 4 people.",
                        "ru": f"Хочу забронировать столик на {DAY} в 18:30 для 4 человек.",
                    }[language],
                )
                assert model.calls == 1
                assert state.language == language
                assert state.pending["kind"] == "table"
                assert state.pending["delivery"] and not state.pending["approved"]
                assert agent.chat_ctx.items[-1].text_content == state.render_recap()
                assert not state.bookings
                await native_turn(session, agent, CONSENT[language])
                assert len(state.bookings) == 1 and state.turn_mutation == "confirmed"
                readback = await backend.get_operator_bookings(DAY)
                assert readback["items"][0]["id"] == state.last_booking
                assert readback["items"][0]["party_size"] == 4
                await native_turn(
                    session,
                    agent,
                    {
                        "et": "Palun tühista see testbroneering.",
                        "en": "Please cancel this test booking.",
                        "ru": "Пожалуйста отмените это тестовое бронирование.",
                    }[language],
                )
                assert state.cancelled_bookings == state.bookings
                assert (await backend.get_operator_bookings(DAY))["items"][0][
                    "status"
                ] == "cancelled"
                assert model.calls == 1
                assert [call.name for call in executed] == [
                    "plan_demo_table",
                    "confirm_table_booking",
                    "cancel_table_booking",
                ]
            finally:
                await session.aclose()

    asyncio.run(run())
