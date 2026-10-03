"""Real installed media SDK wiring with local provider/session doubles."""

import asyncio
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock, patch

import pytest

pytest.importorskip("livekit.agents")

from app import worker  # noqa: E402
from app.restaurant_call import RestaurantCallTools  # noqa: E402


@pytest.mark.parametrize("language", ["et", "en", "ru"])
def test_native_startup_uses_restaurant_policy_and_shared_database(tmp_path, language):
    async def run():
        callbacks = {}
        session = NS(
            on=lambda name, fn: callbacks.update({name: fn}),
            aclose=AsyncMock(),
            say=Mock(),
        )

        async def start(**kwargs):
            callbacks["close"](None)

        session.start = start
        ctx = NS(
            proc=NS(userdata={"vad": object()}),
            room=NS(
                on=Mock(),
                name="restaurant-fixture",
                local_participant=NS(set_attributes=AsyncMock()),
            ),
            connect=AsyncMock(),
            wait_for_participant=AsyncMock(),
            api=NS(room=NS(delete_room=AsyncMock())),
            shutdown=Mock(),
        )
        env = {
            "VOICEBOT_BUSINESS_TYPE": "restaurant",
            "RESTAURANT_DEMO_WRITES": "1",
            "RESTAURANT_STATE_DB": str(tmp_path / "restaurant.db"),
            "CALLS_DB": str(tmp_path / "calls.db"),
            "VOICEBOT_TELEPHONE_LANGUAGE": language,
            "VOICEBOT_TELEPHONE_DEMO": "1",
            "LIVEKIT_URL": "ws://localhost:7880",
            "LIVEKIT_API_KEY": "fixture",
            "LIVEKIT_API_SECRET": "fixture",
            "GROQ_API_KEY": "fixture",
            "AZURE_SPEECH_KEY": "fixture",
            "AZURE_REGION": "fixture",
        }
        with patch.dict("os.environ", env, clear=True), patch.object(
            worker, "protect_logs"
        ), patch.object(worker, "EasyAppointmentsAdapter") as legacy, patch.object(
            worker, "DemoStayAdapter"
        ) as rooms, patch.object(
            worker, "AgentSession", return_value=session
        ), patch.object(
            worker, "TelephoneAgent", wraps=worker.TelephoneAgent
        ) as agent, patch.object(
            worker.callslog, "log_call"
        ), patch.object(
            worker.callslog, "history_safe"
        ), patch.object(
            worker, "TelephoneSTT", return_value=NS(aclose=AsyncMock())
        ), patch.object(
            worker.groq, "LLM"
        ), patch.object(
            worker, "TelephoneTTS"
        ), patch.object(
            worker, "play_failure", new_callable=AsyncMock
        ) as failure:
            await worker.entrypoint(ctx)
        legacy.assert_not_called()
        rooms.assert_not_called()
        failure.assert_not_called()
        state = agent.call_args.args[0]
        assert isinstance(state, RestaurantCallTools)
        assert state.language == language
        assert state.dispatcher._slot.state_db == env["RESTAURANT_STATE_DB"]
        names = {tool["function"]["name"] for tool in state.conversation_tools()}
        assert names == {
            "get_restaurant_information",
            "plan_restaurant_reservation",
            "confirm_slot_booking",
            "cancel_slot_booking",
        }
        session.say.assert_called_once_with(state.greeting)
        ctx.shutdown.assert_called_once()

    asyncio.run(run())
