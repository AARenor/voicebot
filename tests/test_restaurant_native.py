"""Real installed media SDK wiring with local provider/session doubles."""

import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock, patch
from zoneinfo import ZoneInfo

import pytest

pytest.importorskip("livekit.agents")

from app import worker  # noqa: E402
from app.restaurant_call import RestaurantCallTools  # noqa: E402
from app.restaurant_call import COPY  # noqa: E402
from app.booking.restaurant import RestaurantAdapter  # noqa: E402
from app.business import restaurant_dispatcher  # noqa: E402
from app.call_factory import make_call_tools  # noqa: E402
from app.restaurant_data import load_restaurant_data  # noqa: E402
from livekit.agents import AgentSession  # noqa: E402
from tests.test_native_booking_terminals import (  # noqa: E402
    Playback,
    UnusedModel,
    UnusedTTS,
    native_turn,
    synthesize,
)


@pytest.mark.parametrize(
    "language,utterance,confirmation",
    [
        ("et", "Soovin homme lauda neljale kell 14.00", "ja kinnitää"),
        ("et", "Soovin lauaks homseks kell 14.00 nelja inimesega", "ja kinnitää"),
        ("et", "named-date", "ja kinnitää"),
        ("en", "A table for four tomorrow at 2 pm", "Yes, please confirm."),
        ("ru", "Столик на четверых завтра в 14:00", "Да, подтверждаю."),
    ],
)
def test_native_sdk_confirmation_is_visible_in_the_restaurant_database(
    tmp_path, language, utterance, confirmation
):
    async def run():
        request_text = utterance
        if request_text == "named-date":
            from tests.test_restaurant_http import spoken_tomorrow

            request_text = f"Soovin lauda {spoken_tomorrow()} kell 14 nelja külalisega"
        data = load_restaurant_data()
        path = str(tmp_path / "shared-restaurant.db")
        adapter = RestaurantAdapter(path, data=data, allow_writes=True)
        state = make_call_tools(restaurant_dispatcher(adapter, data), language=language)
        agent = worker.TelephoneAgent(state)
        model = UnusedModel()
        session = AgentSession(
            llm=model, tts=UnusedTTS(), turn_handling={"turn_detection": "manual"}
        )
        session.output.audio = Playback()
        session.on("conversation_item_added", agent.on_conversation_item_added)
        with patch("livekit.agents.Agent.default.tts_node", synthesize):
            await session.start(agent=agent, record=False)
            try:
                await native_turn(session, agent, request_text)
                assert state.pending["delivery"] and not state.pending["approved"]
                await native_turn(session, agent, confirmation)
                assert len(state.bookings) == 1
                assert (
                    agent.chat_ctx.items[-1].text_content == COPY[language]["confirmed"]
                )
                assert model.calls == 0
            finally:
                await session.aclose()
        # This is the same scoped reader used by the website, with a fresh
        # connection to the durable database rather than the call's memory.
        reader = RestaurantAdapter(path, data=data, allow_writes=False)
        day = (
            datetime.now(ZoneInfo("Europe/Tallinn")).date() + timedelta(days=1)
        ).isoformat()
        rows = (await reader.get_operator_bookings(day))["items"]
        assert len(rows) == 1 and rows[0]["status"] == "confirmed"
        assert rows[0]["service_id"] == 4
        assert str(rows[0]["id"]) in state.bookings

    asyncio.run(run())


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
