"""Native terminal replies retain SDK tool execution and playback consent."""

import asyncio
import json
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

pytest.importorskip("livekit.agents")
from livekit import rtc
from livekit.agents import AgentSession, llm, tts
from livekit.agents.types import USERDATA_TIMED_TRANSCRIPT
from livekit.agents.voice import io
from livekit.agents.voice.agent import ModelSettings
from livekit.agents.voice.speech_handle import SpeechHandle

from app.booking.demo_stay import DemoStayAdapter
from app.booking.tools import Dispatcher
from app.telephone import CallTools, CONSENT_TEXT, GREETING, MUTATION_REPLIES
from app.worker import TelephoneAgent
from app.providers.speech_text import normalize_estonian_speech
from tests.test_demo_plan import LiveSlots, REQUEST


def tool_chunk(name, arguments, call_id="planning-call"):
    return llm.ChatChunk(
        id="fixture-response",
        delta=llm.ChoiceDelta(
            role="assistant",
            tool_calls=[
                llm.FunctionToolCall(
                    name=name,
                    arguments=json.dumps(arguments),
                    call_id=call_id,
                )
            ],
        ),
    )


class PlanningModel(llm.LLM):
    def __init__(self, name, arguments):
        super().__init__()
        self.name, self.arguments, self.calls = name, arguments, 0

    def chat(self, *, chat_ctx, tools, conn_options, **kwargs):
        self.calls += 1
        assert self.calls == 1, "a terminal reply requested the model again"
        return PlanningStream(
            self, chat_ctx=chat_ctx, tools=tools, conn_options=conn_options
        )


class PlanningStream(llm.LLMStream):
    async def _run(self):
        self._event_ch.send_nowait(tool_chunk(self._llm.name, self._llm.arguments))


class UnusedModel(llm.LLM):
    def __init__(self):
        super().__init__()
        self.calls = 0

    def chat(self, **kwargs):
        self.calls += 1
        raise AssertionError("hours must not call the model")


class UnusedTTS(tts.TTS):
    def __init__(self):
        super().__init__(
            capabilities=tts.TTSCapabilities(streaming=False),
            sample_rate=24000,
            num_channels=1,
        )

    def synthesize(self, *args, **kwargs):
        raise AssertionError("external speech provider forbidden")


class Playback(io.AudioOutput):
    def __init__(self):
        super().__init__(
            label="fixture",
            sample_rate=24000,
            capabilities=io.AudioOutputCapabilities(pause=False),
        )
        self.duration = 0

    async def capture_frame(self, frame):
        await super().capture_frame(frame)
        self.duration += frame.duration

    def flush(self):
        super().flush()
        self.on_playback_finished(playback_position=self.duration, interrupted=False)

    def clear_buffer(self):
        self.on_playback_finished(playback_position=self.duration, interrupted=True)


async def synthesize(agent, text, settings):
    # The real TelephoneAgent still validates text and records completed frames.
    async for _ in text:
        pass
    yield rtc.AudioFrame(b"\x01\x00" * 240, 24000, 1, 240)


async def finalized(agent, text):
    message = llm.ChatMessage(role="user", content=[text])
    await agent.on_user_turn_completed(agent.chat_ctx.copy(), message)
    return message


async def native_turn(session, agent, text):
    handle = session.generate_reply(user_input=await finalized(agent, text))
    await asyncio.wait_for(handle, 4)
    assert handle.exception() is None


@pytest.mark.parametrize(
    "question,failed",
    [
        (
            "Mis kell spaateenindaja töötab ja millal on tema lõunapaus? "
            "Palun kontrolli tööplaani.",
            False,
        ),
        ("Palun näita spaa tööaegu, tahaks teada.", False),
        ("Palun näita spaa tööaegu, tahaks teada.", True),
    ],
)
def test_sdk_hours_execute_catalogue_and_finish_without_model(question, failed):
    async def run():
        backend = LiveSlots()
        backend.catalogue["providers"][0]["working_hours"] = {
            "monday": {
                "start": "09:00",
                "end": "17:00",
                "breaks": [{"start": "12:00", "end": "13:00"}],
            },
            "sunday": None,
        }
        if failed:

            async def failed_catalogue():
                backend.calls.append(("catalogue", {}))
                raise RuntimeError("PRIVATE backend exception")

            backend.get_slot_catalogue = failed_catalogue

        state = CallTools(Dispatcher(slot=backend))
        model = UnusedModel()
        agent = TelephoneAgent(state)
        session = AgentSession(
            llm=model, tts=UnusedTTS(), turn_handling={"turn_detection": "manual"}
        )
        session.output.audio = Playback()
        session.on("conversation_item_added", agent.on_conversation_item_added)
        executed, spoken = [], []
        session.on(
            "function_tools_executed",
            lambda event: executed.extend(event.function_calls),
        )

        async def tts_boundary(agent, text, settings):
            spoken.extend([part async for part in text])
            yield rtc.AudioFrame(b"\x01\x00" * 240, 24000, 1, 240)

        with patch("livekit.agents.Agent.default.tts_node", tts_boundary):
            await session.start(agent=agent, record=False)
            try:
                await native_turn(session, agent, question)
                assert model.calls == 0
                assert [call.name for call in executed] == ["get_slot_catalogue"]
                assert json.loads(executed[0].arguments) == {}
                assert backend.calls == [("catalogue", {})]
                assert not state.bookings and state.pending is None
                assert not state.booking_inquiry and state.turn_mutation is None
                canonical = state.guard_reply("", state.results)
                assert agent.chat_ctx.items[-1].text_content == canonical
                assert spoken == [normalize_estonian_speech(canonical)]
                if failed:
                    assert state.results == [{"error": "booking_unavailable"}]
                    assert canonical == "Toiming ei õnnestunud; edu ei ole kinnitatud."
                    assert "PRIVATE" not in str(agent.chat_ctx.items)
                else:
                    assert "Backend therapist" in canonical
                    assert "09:00–17:00" in canonical and "12:00–13:00" in canonical
                    assert "paus" in canonical and "suletud" in canonical
                    assert (
                        "9 kuni kell 17" in spoken[0] and "12 kuni kell 13" in spoken[0]
                    )
            finally:
                await session.aclose()

    asyncio.run(run())


def test_native_speech_normalizes_hours_after_guard_without_replacing_history():
    async def run():
        backend = LiveSlots()
        backend.catalogue["providers"][0]["working_hours"] = {
            "monday": {"start": "09:00", "end": "17:00", "breaks": []},
        }
        state = CallTools(Dispatcher(slot=backend))
        state.observe_user_text("Mis on tööajad?")
        assert not (await state.dispatch("get_slot_catalogue", {})).get("error")
        agent = TelephoneAgent(state)
        canonical = state.guard_reply("", state.results)
        assert "09:00–17:00" in canonical
        spoken = []
        frame = rtc.AudioFrame(b"\x01\x00" * 240, 24000, 1, 240)

        async def text():
            yield ""

        async def tts_boundary(agent, text, settings):
            spoken.extend([part async for part in text])
            yield frame

        with patch("livekit.agents.Agent.default.tts_node", tts_boundary):
            assert [output async for output in agent.tts_node(text(), None)] == [frame]
        assert spoken == [normalize_estonian_speech(canonical)]
        assert "9 kuni kell 17" in spoken[0]

        async def actual_speech():
            for part in frame.userdata[USERDATA_TIMED_TRANSCRIPT]:
                yield part

        assert [
            part async for part in agent.transcription_node(actual_speech(), None)
        ] == [canonical]
        assert state.pending is None

    asyncio.run(run())


@pytest.mark.parametrize("kind", ["slot", "stay"])
def test_sdk_plan_recap_later_consent_confirm_cancel_need_one_model_call(
    tmp_path, kind
):
    async def run():
        if kind == "slot":
            backend = LiveSlots()
            state = CallTools(Dispatcher(slot=backend))
            name, arguments = "plan_demo_booking", REQUEST
        else:
            backend = DemoStayAdapter(str(tmp_path / "stay.db"))
            state = CallTools(Dispatcher(stay=backend))
            day = datetime.now(ZoneInfo("Europe/Tallinn")).date() + timedelta(days=12)
            name, arguments = (
                "plan_demo_stay",
                {
                    "checkin": day.isoformat(),
                    "checkout": (day + timedelta(days=2)).isoformat(),
                    "adults": 2,
                    "children": 0,
                    "room_type": "garden-double",
                },
            )
        model = PlanningModel(name, arguments)
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
                await native_turn(session, agent, "Palun valmista testbroneering ette.")
                canonical = state.render_recap()
                assert state.pending["delivery"] and not state.pending["approved"]
                assert agent.chat_ctx.items[-1].text_content == canonical
                assert not state.bookings and model.calls == 1
                await native_turn(session, agent, CONSENT_TEXT)
                assert len(state.bookings) == 1 and state.turn_mutation == "confirmed"
                assert (
                    agent.chat_ctx.items[-1].text_content
                    == MUTATION_REPLIES["confirmed"]
                )
                await native_turn(session, agent, "Jah, tühista.")
                assert state.cancelled_bookings == state.bookings
                assert (
                    agent.chat_ctx.items[-1].text_content
                    == MUTATION_REPLIES["cancelled"]
                )
                assert model.calls == 1
                assert [call.name for call in executed] == [
                    name,
                    "confirm_booking" if kind == "stay" else "confirm_slot_booking",
                    "cancel_booking" if kind == "stay" else "cancel_slot_booking",
                ]
            finally:
                await session.aclose()

    asyncio.run(run())


async def prepared_agent():
    state = CallTools(Dispatcher(slot=LiveSlots()))
    agent = TelephoneAgent(state)
    await finalized(agent, "Valmista testbroneering ette.")
    assert (await state.dispatch("plan_demo_booking", REQUEST))["ok"]
    return agent


async def collect(agent, items, *, tool_choice="auto"):
    return [
        chunk
        async for chunk in agent.llm_node(
            llm.ChatContext(items=items),
            agent.tools,
            ModelSettings(tool_choice=tool_choice),
        )
    ]


@pytest.mark.parametrize(
    "case", ["wrong_user", "old_tool", "tool_choice_none", "tool_removed"]
)
def test_action_shortcut_requires_current_initial_turn_and_allowed_tool(case):
    async def run():
        agent = await prepared_agent()
        state = agent.state
        assert state.mark_recap_delivered(state.pending["hold_id"])
        consent = await finalized(agent, CONSENT_TEXT)
        items, choice = [consent], "auto"
        if case == "wrong_user":
            items = [llm.ChatMessage(role="user", content=[CONSENT_TEXT])]
        elif case == "old_tool":
            items.append(
                llm.FunctionCallOutput(
                    name="plan_demo_booking", call_id="old", output="{}", is_error=False
                )
            )
        elif case == "tool_choice_none":
            choice = "none"
        else:
            await agent.update_tools([])
        delegated = []

        async def fallback(*args):
            delegated.append(True)
            yield GREETING

        with patch("livekit.agents.Agent.default.llm_node", fallback):
            assert await collect(agent, items, tool_choice=choice) == [GREETING]
        assert delegated == [True] and not state.bookings

    asyncio.run(run())


@pytest.mark.parametrize("failure", ["interrupted", "synthesis"])
def test_failed_or_interrupted_recap_cannot_shortcut_later_confirmation(failure):
    async def run():
        agent = await prepared_agent()
        canonical = agent.state.render_recap()
        proposal = agent.state.pending
        speech = SpeechHandle.create()

        async def text():
            yield canonical

        async def failing(*args):
            raise RuntimeError("fixture synthesis failure")
            yield

        with (
            patch(
                "livekit.agents.Agent.default.tts_node",
                failing if failure == "synthesis" else synthesize,
            ),
            patch.object(agent, "_current_speech", return_value=speech),
        ):
            assert [frame async for frame in agent.tts_node(text(), None)]
        if failure == "interrupted":
            assert agent.state.pending is proposal and not proposal["delivery"]
            # A completed item from another speech cannot acknowledge this recap.
            unrelated = SpeechHandle.create()
            old_item = llm.ChatMessage(role="assistant", content=[canonical])
            unrelated._item_added([old_item])
            agent.on_conversation_item_added(SimpleNamespace(item=old_item))
            assert agent.state.pending is proposal and not proposal["delivery"]
        else:
            assert agent.state.pending is None
        item = llm.ChatMessage(
            role="assistant",
            content=[canonical],
            interrupted=failure == "interrupted",
        )
        speech._item_added([item])
        agent.on_conversation_item_added(SimpleNamespace(item=item))
        assert agent.state.pending is None
        consent = await finalized(agent, CONSENT_TEXT)

        async def fallback(*args):
            yield GREETING

        with patch("livekit.agents.Agent.default.llm_node", fallback):
            assert await collect(agent, [consent]) == [GREETING]
        assert not agent.state.bookings and agent.state.pending is None

    asyncio.run(run())


def test_nonterminal_read_delegates_and_old_call_ids_do_not_survive_final_turn():
    async def run():
        agent = TelephoneAgent(CallTools(Dispatcher(slot=LiveSlots())))
        message = await finalized(agent, "Millised teenused on saadaval?")

        async def read_model(*args):
            yield tool_chunk("get_slot_catalogue", {})

        with patch("livekit.agents.Agent.default.llm_node", read_model):
            await collect(agent, [message])
        assert agent._tool_call_ids == {"planning-call"}
        await agent.state.dispatch("get_slot_catalogue", {})
        output = llm.FunctionCallOutput(
            name="get_slot_catalogue",
            call_id="planning-call",
            output="fixture",
            is_error=False,
        )
        delegated = []

        async def fallback(*args):
            delegated.append(True)
            yield GREETING

        with patch("livekit.agents.Agent.default.llm_node", fallback):
            assert await collect(agent, [message, output]) == [GREETING]
            newer = await finalized(agent, "Ei, ära broneeri.")
            assert not agent._tool_call_ids
            assert await collect(agent, [message, output]) == [GREETING]
            assert await collect(agent, [newer, output]) == [GREETING]
        assert len(delegated) == 3

    asyncio.run(run())


@pytest.mark.parametrize("phase", ["approved", "prepared"])
def test_sdk_config_updates_do_not_hide_current_user_or_tool_output(phase):
    async def run():
        agent = TelephoneAgent(CallTools(Dispatcher(slot=LiveSlots())))
        message = await finalized(agent, "Valmista testbroneering ette.")
        assert (await agent.state.dispatch("plan_demo_booking", REQUEST))["ok"]
        if phase == "approved":
            assert agent.state.mark_recap_delivered(agent.state.pending["hold_id"])
            message = await finalized(agent, CONSENT_TEXT)
            items = [message]
        else:
            agent._tool_call_ids.add("current-plan")
            items = [
                message,
                llm.FunctionCallOutput(
                    name="plan_demo_booking",
                    call_id="current-plan",
                    output="fixture",
                    is_error=False,
                ),
            ]
        items.append(llm.AgentConfigUpdate(instructions=agent.instructions))

        async def forbidden(*args):
            raise AssertionError("configuration metadata caused a provider request")
            yield

        with patch("livekit.agents.Agent.default.llm_node", forbidden):
            chunks = await collect(agent, items)
        if phase == "approved":
            assert chunks[0].delta.tool_calls[0].name == "confirm_slot_booking"
            assert not agent.state.bookings  # SDK executor alone performs the write.
        else:
            assert chunks == [agent.state.render_recap()]
            assert agent.state.pending["delivery"] is False

    asyncio.run(run())


@pytest.mark.parametrize("language", ["et", "en"])
def test_native_normalization_keeps_the_captured_voice_language(language):
    async def run():
        state = CallTools(Dispatcher(slot=LiveSlots()), language=language)
        voice_updates, spoken = [], []
        provider = SimpleNamespace(
            update_options=lambda **options: voice_updates.append(options)
        )
        agent = TelephoneAgent(state, speech_provider=provider)
        reply = (
            "Opening hours 09:00–17:00" if language == "en" else "Tööajad 09:00–17:00"
        )
        frame = rtc.AudioFrame(b"\x01\x00" * 240, 24000, 1, 240)

        async def checked_reply(text):
            return reply

        async def text():
            yield reply

        async def boundary(agent, text, settings):
            # A later user turn changes state after this voice was selected.
            state.language = "en" if language == "et" else "et"
            spoken.extend([part async for part in text])
            yield frame

        with (
            patch.object(agent, "checked_reply", checked_reply),
            patch("livekit.agents.Agent.default.tts_node", boundary),
        ):
            assert [output async for output in agent.tts_node(text(), None)] == [frame]
        assert spoken == [normalize_estonian_speech(reply, language)]
        assert str(frame.userdata[USERDATA_TIMED_TRANSCRIPT][0]) == reply
        assert voice_updates[0]["language"] == (
            "en-US" if language == "en" else "et-EE"
        )

    asyncio.run(run())


def test_late_model_chunk_cannot_attach_old_tool_output_to_newer_proposal():
    async def run():
        agent = TelephoneAgent(CallTools(Dispatcher(slot=LiveSlots())))
        older = await finalized(agent, "Esimene päring.")
        started, release = asyncio.Event(), asyncio.Event()

        async def delayed(*args):
            started.set()
            await release.wait()
            yield tool_chunk("get_slot_catalogue", {}, "older-call")

        with patch("livekit.agents.Agent.default.llm_node", delayed):
            pending_stream = asyncio.create_task(collect(agent, [older]))
            await asyncio.wait_for(started.wait(), 2)
            newer = await finalized(agent, "Valmista uus testbroneering ette.")
            assert (await agent.state.dispatch("plan_demo_booking", REQUEST))["ok"]
            release.set()
            assert await asyncio.wait_for(pending_stream, 2) == []
        assert not agent._tool_call_ids
        proposal = agent.state.pending
        output = llm.FunctionCallOutput(
            name="get_slot_catalogue",
            call_id="older-call",
            output="fixture",
            is_error=False,
        )

        async def fallback(*args):
            yield GREETING

        with patch("livekit.agents.Agent.default.llm_node", fallback):
            assert await collect(agent, [older, newer, output]) == [GREETING]
        assert agent.state.pending is proposal and not agent.state.bookings

    asyncio.run(run())


def test_native_followup_model_gets_parsed_tomorrow_and_time():
    async def run():
        agent = TelephoneAgent(CallTools(Dispatcher(slot=LiveSlots())))
        first = await finalized(agent, "Tere, tahaks homme bruneerida spaad?")
        assert await collect(agent, [first])
        assert agent.state.booking_inquiry.get("date")
        followup = await finalized(agent, "Kell 10:30.")
        seen = []

        async def model(agent, chat_ctx, tools, settings):
            seen.extend(
                item.text_content
                for item in chat_ctx.items
                if isinstance(item, llm.ChatMessage) and item.role == "system"
            )
            yield GREETING

        with patch("livekit.agents.Agent.default.llm_node", model):
            assert await collect(agent, [first, followup]) == [GREETING]
        assert any(
            "Server-owned booking inquiry" in text
            and agent.state.booking_inquiry["date"] in text
            and "10:30" in text
            for text in seen
        )
        assert agent.state.pending is None and not agent.state.bookings

    asyncio.run(run())
