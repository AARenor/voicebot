import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

pytest.importorskip("livekit.agents")

from app.booking.tools import Dispatcher
from app.telephone import CallTools
from app.worker import TelephoneAgent, entrypoint
from app import callslog, worker


def test_prewarm_keeps_supported_vad_defaults_for_exact_short_commitments():
    proc = SimpleNamespace(userdata={})
    marker = object()
    with patch("app.worker.silero.VAD.load", return_value=marker) as load:
        worker.prewarm(proc)
    load.assert_called_once_with()
    assert proc.userdata["vad"] is marker


def test_fatal_provider_diagnostic_contains_only_closed_kind_and_status(caplog):
    class Failure(RuntimeError):
        status_code = 429

    event = SimpleNamespace(
        error=SimpleNamespace(
            type="llm_error",
            recoverable=False,
            error=Failure("private body and credential"),
        )
    )
    failed = asyncio.Event()
    worker.on_provider_error(failed, event)
    assert failed.is_set()
    assert "llm_error" in caplog.text and "429" in caplog.text
    assert "private body" not in caplog.text and "credential" not in caplog.text


def test_worker_does_not_authorize_individual_stt_fragments():
    async def run():
        observed = []
        state = SimpleNamespace(
            call_id="a" * 32,
            outcome="completed",
            pending=None,
            results=[{"old": True}],
            observe_user_text=lambda text, *, is_final: observed.append(
                (text, is_final)
            ),
        )
        callbacks = {}
        session = SimpleNamespace(
            on=lambda name, fn: callbacks.update({name: fn}),
            aclose=AsyncMock(),
            say=Mock(),
            interrupt=Mock(),
            current_speech=None,
        )

        async def start(**kwargs):
            await callbacks["user_state_changed"](SimpleNamespace(new_state="speaking"))
            callbacks["close"](None)

        session.start = start
        adapter = SimpleNamespace(close=AsyncMock())
        ctx = SimpleNamespace(
            proc=SimpleNamespace(userdata={"vad": object()}),
            room=SimpleNamespace(
                on=Mock(),
                name="demo-fixture",
                local_participant=SimpleNamespace(
                    set_attributes=AsyncMock(), publish_data=AsyncMock()
                ),
            ),
            connect=AsyncMock(),
            wait_for_participant=AsyncMock(),
            api=SimpleNamespace(room=SimpleNamespace(delete_room=AsyncMock())),
            shutdown=Mock(),
        )
        with (
            patch("app.worker.validate_environment"),
            patch("app.worker.protect_logs"),
            patch("app.worker.EasyAppointmentsAdapter", return_value=adapter),
            patch("app.worker.CallTools", return_value=state),
            patch("app.worker.AgentSession", return_value=session) as constructed,
            patch("app.worker.TelephoneAgent"),
            patch("app.worker.groq.STT"),
            patch("app.worker.groq.LLM"),
            patch("app.worker.azure.TTS"),
            patch("app.callslog.log_call") as log,
            patch.dict(
                "os.environ",
                {
                    "EASY_BASE_URL": "http://fixture",
                    "EASY_API_KEY": "fixture",
                    "EASY_STATE_DB": "/unused",
                    "GROQ_API_KEY": "fixture",
                    "AZURE_SPEECH_KEY": "fixture",
                    "AZURE_REGION": "fixture",
                },
            ),
        ):
            await entrypoint(ctx)
        assert "user_input_transcribed" not in callbacks
        assert observed == []
        assert constructed.call_args.kwargs["turn_handling"]["endpointing"] == {
            "mode": "fixed",
            "min_delay": 1.2,
            "max_delay": 3.0,
        }
        ctx.room.local_participant.set_attributes.assert_awaited_once_with(
            {"voicebot.call_id": "a" * 32}
        )
        published = ctx.room.local_participant.publish_data
        published.assert_awaited_once()
        assert published.await_args.args[0].startswith(b"clear:")
        assert published.await_args.kwargs == {
            "topic": "voicebot.interruption",
            "reliable": True,
        }
        session.interrupt.assert_called_once_with()
        log.assert_called_once()
        assert log.call_args.args[1:] == (
            "et",
            "",
            "Synthetic telephone demo",
            "completed",
        )

    asyncio.run(run())


def test_completed_native_user_turn_observes_aggregated_text_before_tools():
    async def run():
        from tests.test_telephone import Slots, prepared

        state = CallTools(Slots())
        assert (await prepared(state))["ok"]
        agent = TelephoneAgent(state)
        await agent.on_user_turn_completed(
            None,
            SimpleNamespace(
                role="user", text_content="Jah, kinnitan selle testbroneeringu."
            ),
        )
        assert (
            await state.dispatch("confirm_slot_booking", {"hold_id": "owned-hold"})
        )["ok"]
        await agent.on_user_turn_completed(
            None,
            SimpleNamespace(
                role="user",
                text_content="Palun tühista broneering, mille just selles kõnes tegime.",
            ),
        )
        assert (
            await state.dispatch(
                "cancel_slot_booking", {"booking_id": state.last_booking}
            )
        )["ok"]

    asyncio.run(run())


def test_completed_native_turn_decline_cannot_become_partial_affirmation():
    async def run():
        from tests.test_telephone import Slots, prepared

        state = CallTools(Slots())
        assert (await prepared(state))["ok"]
        agent = TelephoneAgent(state)
        await agent.on_user_turn_completed(
            None,
            SimpleNamespace(
                role="user",
                text_content="Jah, kinnitan selle testbroneeringu. Ei, ära kinnita.",
            ),
        )
        assert (
            await state.dispatch("confirm_slot_booking", {"hold_id": "owned-hold"})
        )["error"] == "consent_required"

    asyncio.run(run())


def test_worker_prompt_discloses_loaded_fiction_and_current_date():
    agent = TelephoneAgent(CallTools(Dispatcher()))
    assert "Meretuule Demo Spa" in agent.instructions
    assert "current_date" in agent.instructions
    assert "plan_demo_booking" in agent.instructions
    assert "Ära küsi päris" in agent.instructions
    assert "working_hours" not in agent.instructions
    assert "2026-10-05" not in agent.instructions


def test_native_agent_uses_compact_prompt_and_only_conversation_tools():
    from livekit.agents.llm.tool_context import get_raw_function_info
    from tests.test_telephone import Slots

    state = CallTools(Slots())
    agent = TelephoneAgent(state)
    assert hasattr(state, "conversation_instructions"), (
        "compact instructions are missing"
    )
    assert agent.instructions == state.conversation_instructions
    assert {get_raw_function_info(tool).name for tool in agent.tools} == {
        "get_demo_profile",
        "plan_demo_booking",
        "confirm_slot_booking",
        "cancel_slot_booking",
    }


@pytest.mark.parametrize(
    "outcome",
    [
        "completed",
        "booking_confirmed",
        "booking_cancelled",
        "hold_created",
        "booking_unavailable",
        "write_outcome_unknown",
        "private@example.com",
    ],
)
def test_native_call_summary_is_static_and_logged_once(outcome):
    assert callable(getattr(worker, "log_call_summary", None)), (
        "native call summary is missing"
    )
    db = callslog.open_log()
    state = SimpleNamespace(
        outcome=outcome,
        call_id="private-room-name",
        results=[{"transcript": "private@example.com", "phone": "+37255555555"}],
    )
    try:
        with patch("app.callslog.get_default", return_value=db):
            worker.log_call_summary(state)
            worker.log_call_summary(state)
        rows = callslog.list_calls(db)
        assert len(rows) == 1
        assert rows[0]["summary"] == "Synthetic telephone demo"
        assert rows[0]["outcome"] == ("completed" if "@" in outcome else outcome)
        assert "private" not in repr(rows)
        assert "+372" not in repr(rows)
    finally:
        db.close()


def test_native_summary_failure_does_not_prevent_cleanup():
    assert callable(getattr(worker, "log_call_summary", None)), (
        "native call summary is missing"
    )

    async def run():
        state = SimpleNamespace(outcome="booking_confirmed")
        session = SimpleNamespace(aclose=AsyncMock())
        adapter = SimpleNamespace(close=AsyncMock())
        ctx = SimpleNamespace(
            api=SimpleNamespace(room=SimpleNamespace(delete_room=AsyncMock())),
            room=SimpleNamespace(name="demo-room"),
            shutdown=Mock(),
        )
        with patch(
            "app.callslog.log_call", side_effect=RuntimeError("private@example.com")
        ):
            await worker.cleanup_call(ctx, session, adapter, state=state, failed=True)
        adapter.close.assert_awaited_once()
        ctx.api.room.delete_room.assert_awaited_once()
        ctx.shutdown.assert_called_once()

    asyncio.run(run())


def test_native_failed_summary_preserves_unknown_write_outcome():
    db = callslog.open_log()
    try:
        state = SimpleNamespace(outcome="write_outcome_unknown")
        with patch("app.callslog.get_default", return_value=db):
            worker.log_call_summary(state, failed=True)
        assert callslog.list_calls(db)[0]["outcome"] == "write_outcome_unknown"
    finally:
        db.close()


def test_vad_speaking_publishes_static_reliable_clear_and_invalidates_undelivered_recap():
    async def run():
        from tests.test_telephone import Slots, held

        state = CallTools(Slots())
        await held(state)
        assert (
            await state.dispatch("prepare_demo_booking", {"hold_id": "owned-hold"})
        )["ok"]
        events = []

        async def publish(payload, **kwargs):
            events.append((payload, kwargs))

        room = SimpleNamespace(local_participant=SimpleNamespace(publish_data=publish))
        session = SimpleNamespace(interrupt=Mock(), current_speech=None)
        pending_tasks = set()
        task = worker.on_user_state(
            session,
            SimpleNamespace(new_state="speaking"),
            state=state,
            room=room,
            pending_tasks=pending_tasks,
        )
        session.interrupt.assert_called_once_with()
        assert state.pending is None
        assert task in pending_tasks
        await task
        assert len(events) == 1
        assert events[0][0].startswith(b"clear:") and len(events[0][0]) == 38
        assert events[0][1] == {"topic": "voicebot.interruption", "reliable": True}
        assert not pending_tasks

    asyncio.run(run())


def test_interruption_publish_failure_is_private_and_does_not_block_local_interrupt(
    caplog,
):
    async def run():
        async def failed_publish(*args, **kwargs):
            raise RuntimeError("private transcript and phone")

        room = SimpleNamespace(
            local_participant=SimpleNamespace(publish_data=failed_publish)
        )
        session = SimpleNamespace(interrupt=Mock(), current_speech=None)
        assert (
            worker.on_user_state(
                session, SimpleNamespace(new_state="listening"), room=room
            )
            is None
        )
        await worker.on_user_state(
            session, SimpleNamespace(new_state="speaking"), room=room
        )
        session.interrupt.assert_called_once_with()
        assert "private transcript" not in caplog.text and "phone" not in caplog.text

    asyncio.run(run())


@pytest.mark.parametrize("recoverable", [True, False])
def test_provider_error_invalidates_any_pending_recap(recoverable):
    state = CallTools(Dispatcher())
    state.pending = {"delivery": True, "approved": True}
    failed = asyncio.Event()
    worker.on_provider_error(
        failed,
        SimpleNamespace(
            error=SimpleNamespace(
                recoverable=recoverable, type="tts_error", error=RuntimeError("private")
            )
        ),
        state=state,
    )
    assert state.pending is None
    assert failed.is_set() is (not recoverable)


@pytest.mark.parametrize("has_speech", [True, False])
def test_vad_only_invalidates_delivered_recap_when_audio_is_actually_interrupted(
    has_speech,
):
    async def run():
        from tests.test_telephone import Slots, prepared

        state = CallTools(Slots())
        assert (await prepared(state))["ok"]
        session = SimpleNamespace(
            interrupt=Mock(),
            current_speech=SimpleNamespace(done=lambda: False) if has_speech else None,
        )
        worker.on_user_state(
            session, SimpleNamespace(new_state="speaking"), state=state
        )
        state.observe_user_text("Jah, kinnitan selle testbroneeringu.")
        result = await state.dispatch("confirm_slot_booking", {"hold_id": "owned-hold"})
        assert bool(result.get("ok")) is (not has_speech)

    asyncio.run(run())
