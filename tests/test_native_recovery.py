"""Native empty-generation/audio recovery without provider or carrier requests."""

import asyncio
from types import SimpleNamespace
from unittest.mock import patch

import pytest

pytest.importorskip("livekit.agents")

from livekit import rtc
from livekit.agents import llm

from app.booking.tools import Dispatcher
from app.telephone import CallTools, CONSENT_TEXT
from app.worker import TelephoneAgent
from tests.test_demo_plan import LiveSlots, REQUEST
from tests.test_native_booking_terminals import finalized, tool_chunk


@pytest.mark.parametrize("chunks", [[], ["  ", llm.ChatChunk(id="empty")]])
@pytest.mark.parametrize("language", ["et", "en", "ru"])
def test_native_empty_generation_produces_a_guarded_nonempty_reply(chunks, language):
    async def run():
        async def empty_response(*args):
            for chunk in chunks:
                yield chunk

        agent = TelephoneAgent(CallTools(Dispatcher(), language=language))
        with patch("livekit.agents.Agent.default.llm_node", empty_response):
            result = [
                item async for item in agent.llm_node(llm.ChatContext(), [], None)
            ]
        assert any(isinstance(item, str) and item.strip() for item in result)

        async def reply():
            for item in result:
                if isinstance(item, str):
                    yield item

        checked = await agent.checked_reply(reply())
        expected = {
            "et": (
                "Mis kuupäev sulle sobiks?",
                "Edu ei ole kinnitatud. Kontrolli testbroneeringu tulemust taustsüsteemist.",
            ),
            "en": (
                "What date would you like for your test booking?",
                "I couldn't verify that result. Please check the test booking in the booking system.",
            ),
            "ru": (
                "Какая дата вам подходит?",
                "Успех операции не подтверждён. Проверьте результат тестового бронирования в системе.",
            ),
        }
        assert checked == expected[language][bool(chunks)]

    asyncio.run(run())


def test_native_tool_only_generation_does_not_invent_a_spoken_failure():
    async def run():
        tool = llm.FunctionToolCall(
            name="get_demo_profile", arguments="{}", call_id="fixture-call"
        )
        chunk = llm.ChatChunk(
            id="tool", delta=llm.ChoiceDelta(role="assistant", tool_calls=[tool])
        )

        async def tool_response(*args):
            yield chunk

        agent = TelephoneAgent(CallTools(Dispatcher()))
        with patch("livekit.agents.Agent.default.llm_node", tool_response):
            result = [
                item async for item in agent.llm_node(llm.ChatContext(), [], None)
            ]
        assert len(result) == 1
        assert result[0].delta.tool_calls[0].name == "get_demo_profile"
        assert result[0].delta.tool_calls[0].arguments == "{}"

    asyncio.run(run())


@pytest.mark.parametrize("language", ["et", "en", "ru"])
def test_native_prepared_recap_does_not_need_a_second_model_request(language):
    async def run():
        state = CallTools(Dispatcher(slot=LiveSlots()), language=language)
        agent = TelephoneAgent(state)
        request = {
            "et": "Palun valmista testbroneering ette.",
            "en": "Please prepare a test booking.",
            "ru": "Подготовьте тестовое бронирование.",
        }[language]
        message = await finalized(agent, request)
        context = llm.ChatContext(items=[message])

        async def planning(*args):
            yield tool_chunk("plan_demo_booking", REQUEST, "fixture-plan")

        with patch("livekit.agents.Agent.default.llm_node", planning):
            chunks = [item async for item in agent.llm_node(context, agent.tools, None)]
        call = chunks[0].delta.tool_calls[0]
        assert (await state.dispatch(call.name, call.arguments))["ok"]
        canonical = state.render_recap()
        context.items.append(
            llm.FunctionCallOutput(
                name=call.name,
                call_id=call.call_id,
                output="{}",
                is_error=False,
            )
        )

        async def rejected_followup(*args):
            raise AssertionError("unnecessary model followup")
            yield

        with patch("livekit.agents.Agent.default.llm_node", rejected_followup):
            result = [item async for item in agent.llm_node(context, agent.tools, None)]
        assert result == [canonical]
        assert state.pending and not state.pending["delivery"]

    asyncio.run(run())


@pytest.mark.parametrize(
    "language,consent",
    [
        ("et", "Jah, kinnitan."),
        ("en", "Yes, I confirm."),
        ("ru", "Да, подтверждаю."),
    ],
)
def test_native_delivered_owned_consent_uses_the_existing_confirmation_tool(
    language, consent
):
    async def run():
        backend = LiveSlots()
        state = CallTools(Dispatcher(slot=backend), language=language)
        assert (await state.dispatch("plan_demo_booking", REQUEST))["ok"]
        assert state.mark_recap_delivered(state.pending["hold_id"])
        agent = TelephoneAgent(state)
        message = await finalized(agent, consent)
        context = llm.ChatContext(items=[message])

        async def rejected_provider(*args):
            raise AssertionError("owned confirmation should not need a model")
            yield

        with patch("livekit.agents.Agent.default.llm_node", rejected_provider):
            result = [item async for item in agent.llm_node(context, agent.tools, None)]
        assert len(result) == 1
        call = result[0].delta.tool_calls[0]
        assert call.name == "confirm_slot_booking"
        assert call.arguments == '{"hold_id": "backend-hold"}'
        assert not any(name == "confirm" for name, _ in backend.calls)

    asyncio.run(run())


@pytest.mark.parametrize(
    "language,utterance",
    [
        ("et", "Korda palun"),
        ("en", "Please speak in English."),
        ("ru", "Говорите по-русски."),
    ],
)
def test_native_repeat_or_language_switch_answers_the_current_owned_recap(
    language, utterance
):
    async def run():
        state = CallTools(Dispatcher(slot=LiveSlots()))
        assert (await state.dispatch("plan_demo_booking", REQUEST))["ok"]
        original = state.pending
        agent = TelephoneAgent(state)
        message = await finalized(agent, utterance)
        canonical = state.render_recap()

        async def forbidden(*args):
            raise AssertionError("owned recap must not need another model request")
            yield

        with patch("livekit.agents.Agent.default.llm_node", forbidden):
            parts = [
                part
                async for part in agent.llm_node(
                    llm.ChatContext(items=[message]),
                    agent.tools,
                    None,
                )
            ]
        assert state.pending is not original and state.language == language
        assert parts == [canonical] and canonical
        assert not state.pending["delivery"] and not state.pending["approved"]
        assert not state.bookings

    asyncio.run(run())


def test_native_silent_audio_cannot_deliver_a_booking_recap():
    async def run():
        backend = LiveSlots()
        state = CallTools(Dispatcher(slot=backend))
        assert (await state.dispatch("plan_demo_booking", REQUEST))["ok"]
        hold_id = state.pending["hold_id"]
        canonical = state.render_recap()
        agent = TelephoneAgent(state)

        async def text():
            yield canonical

        async def silent_synthesis(agent, text, settings):
            async for _ in text:
                pass
            yield rtc.AudioFrame(bytes(960), 24000, 1, 480)

        with patch("livekit.agents.Agent.default.tts_node", silent_synthesis):
            frames = [frame async for frame in agent.tts_node(text(), None)]
        agent.on_conversation_item_added(
            SimpleNamespace(item=llm.ChatMessage(role="assistant", content=[canonical]))
        )
        assert state.pending is None
        assert any(any(frame.data) for frame in frames)
        state.observe_user_text(CONSENT_TEXT)
        result = await state.dispatch("confirm_slot_booking", {"hold_id": hold_id})
        assert not result.get("ok")
        assert not any(name == "confirm" for name, _ in backend.calls)

    asyncio.run(run())


def test_native_empty_audio_stream_plays_independent_failure_audio():
    async def run():
        async def text():
            yield "Tere!"

        async def empty_synthesis(agent, text, settings):
            async for _ in text:
                pass
            if False:
                yield

        agent = TelephoneAgent(CallTools(Dispatcher()))
        with patch("livekit.agents.Agent.default.tts_node", empty_synthesis):
            frames = [frame async for frame in agent.tts_node(text(), None)]
        assert frames
        assert any(any(frame.data) for frame in frames)

    asyncio.run(run())
