"""Provider-free Russian policy, native voice and SDK playback regressions."""

import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from app.booking.demo_stay import DemoStayAdapter
from app.booking.tools import Dispatcher
from app.languages import CONSENT, requested_language, select_language
from app.providers.voice_config import SpeechConfig
from app.russian import localize
from app.telephone import FALLBACK, MUTATION_REPLIES, UNVERIFIED_REPLY, CallTools
from tests.test_demo_delivery import raw_prepared
from tests.test_demo_plan import REQUEST, LiveSlots
from tests.test_spa_hours_inquiry import Hours
from tests.test_telephone import Slots


@pytest.mark.parametrize("text", [
    "Russian, please.", "Palun vene keeles.", "По-русски, пожалуйста.",
    "Пожалуйста, говорите на русском языке.",
])
def test_explicit_russian_language_request(text):
    assert requested_language(text) == "ru"


@pytest.mark.parametrize("text", ["10:30", "2", "2026-11-02", "да", "нет"])
def test_numeric_and_weak_followups_retain_russian_voice(text):
    assert select_language(text, "english", "ru") == "ru"
    state = CallTools(Slots(), language="ru")
    state.observe_user_text(text, detected_language="estonian")
    assert state.language == "ru"
    assert not state.cancel_approval and not state.bookings


def test_russian_faq_and_prompt_use_approved_fictional_facts():
    state = CallTools(Slots(), language="ru")
    for entry in state.demo["faq"]:
        assert entry["answer_ru"]
        assert state.guard_reply(entry["answer_ru"], []) == entry["answer_ru"]
    prompt = state.conversation_instructions
    assert "Current caller language: Russian" in prompt
    assert "answer_ru" in prompt and CONSENT["ru"] in prompt
    assert "current_date" in prompt and "Europe/Tallinn" in prompt
    assert "guest-001" in prompt and "example.invalid" not in prompt
    assert state.guard_reply("Я подтвердил ваше бронирование.", []) == localize(
        UNVERIFIED_REPLY, "ru"
    )


def test_russian_hours_readback_preserves_database_names_times_and_breaks():
    async def run():
        state = CallTools(Hours(), language="ru")
        state.observe_user_text("Какие часы работы спа и когда перерыв?")
        assert state.language == "ru" and state.conversation.focus == "hours"
        result = await state.dispatch("get_slot_catalogue", {})
        reply = state.guard_reply("Специалист работает круглосуточно.", [result])
        assert "Database therapist" in reply
        assert "понедельник: 08:30–16:45, перерыв 11:15–11:50" in reply
        assert "воскресенье: закрыто" in reply
        assert "Доступное время нужно проверить отдельно" in reply
        assert "Backend consultation" not in reply and "круглосуточно" not in reply
        assert state.dispatcher.calls == [("get_slot_catalogue", {})]
        assert not state.pending and not state.bookings
        state.observe_user_text("Какие часы работы спа?")
        unknown = state.guard_reply("", [{"services": [], "providers": []}])
        from app.booking_faq import MISSING_FACTS

        assert unknown == MISSING_FACTS["ru"]
        assert "09:00" not in unknown and "17:00" not in unknown

    asyncio.run(run())


@pytest.mark.parametrize("boundary", ["undelivered", "expired", "foreign", "interim"])
def test_russian_consent_requires_current_delivered_owned_recap(boundary):
    async def run():
        backend = LiveSlots()
        state = CallTools(Dispatcher(slot=backend), language="ru")
        ready = await raw_prepared(state)
        recap = state.render_recap()
        assert "Backend consultation" in recap and "Backend therapist" in recap
        assert "Demo Esimene" in recap and "10:30" in recap
        assert CONSENT["ru"] in recap and CONSENT["ru"] in ready["consent_prompt_ru"]
        assert not state.pending["delivery"] and not state.pending["approved"]
        assert not state.mark_recap_delivered("foreign-hold")
        if boundary != "undelivered":
            # Policy-only negative fixtures simulate the trusted reader; the
            # positive lifecycle below requires actual SDK playback completion.
            assert state.mark_recap_delivered(ready["hold_id"])
        if boundary == "expired":
            state.pending["expires_at"] = 0
        state.observe_user_text(CONSENT["ru"], is_final=boundary != "interim")
        denied = await state.dispatch("confirm_slot_booking", {
            "hold_id": "foreign-hold" if boundary == "foreign" else ready["hold_id"],
        })
        assert "error" in denied
        assert not any(name == "confirm" for name, _ in backend.calls)
        assert not state.bookings

    asyncio.run(run())


@pytest.mark.parametrize("text", [
    "Да", "Да, подтверждаю?", "Да, подтверждаю. Нет, не бронируйте.",
    "Да, подтверждаю бронирование другого гостя.", "Нет, не подтверждаю.",
])
def test_uncertain_russian_answers_cannot_confirm(text):
    async def run():
        backend = LiveSlots()
        state = CallTools(Dispatcher(slot=backend), language="ru")
        ready = await raw_prepared(state)
        assert state.mark_recap_delivered(ready["hold_id"])
        state.observe_user_text(text)
        result = await state.dispatch("confirm_slot_booking", {"hold_id": ready["hold_id"]})
        assert result["error"] == "consent_required"
        assert not any(name == "confirm" for name, _ in backend.calls)

    asyncio.run(run())


@pytest.mark.parametrize("previous_language", ["et", "en"])
def test_switch_to_russian_invalidates_previous_language_delivery(previous_language):
    async def run():
        backend = LiveSlots()
        state = CallTools(Dispatcher(slot=backend), language=previous_language)
        ready = await raw_prepared(state)
        old_pending = state.pending
        assert state.mark_recap_delivered(ready["hold_id"])
        state.observe_user_text("По-русски, пожалуйста.")
        assert state.language == "ru" and state.pending is not old_pending
        assert not state.pending["delivery"] and not state.pending["approved"]
        assert CONSENT["ru"] in state.render_recap()
        state.observe_user_text(CONSENT["ru"])
        result = await state.dispatch("confirm_slot_booking", {"hold_id": ready["hold_id"]})
        assert result["error"] == "consent_required"
        assert not any(name == "confirm" for name, _ in backend.calls)

    asyncio.run(run())


@pytest.mark.parametrize("kind", ["slot", "stay"])
def test_russian_sdk_playback_later_consent_and_owned_cancellation(tmp_path, kind):
    pytest.importorskip("livekit.agents")
    from livekit.agents import AgentSession

    from app.worker import TelephoneAgent
    from tests.test_native_booking_terminals import (
        PlanningModel,
        Playback,
        UnusedTTS,
        native_turn,
        synthesize,
    )

    async def run():
        if kind == "slot":
            backend = LiveSlots()
            state = CallTools(Dispatcher(slot=backend), language="ru")
            name, arguments = "plan_demo_booking", REQUEST
        else:
            backend = DemoStayAdapter(str(tmp_path / "russian-stay.db"))
            state = CallTools(Dispatcher(stay=backend), language="ru")
            day = datetime.now(ZoneInfo("Europe/Tallinn")).date() + timedelta(days=12)
            name, arguments = "plan_demo_stay", {
                "checkin": day.isoformat(), "checkout": (day + timedelta(days=2)).isoformat(),
                "adults": 2, "children": 0, "room_type": "garden-double",
            }
        model = PlanningModel(name, arguments)
        agent = TelephoneAgent(state)
        session = AgentSession(
            llm=model, tts=UnusedTTS(), turn_handling={"turn_detection": "manual"},
        )
        session.output.audio = Playback()
        session.on("conversation_item_added", agent.on_conversation_item_added)
        executed = []
        session.on("function_tools_executed", lambda event: executed.extend(event.function_calls))
        with patch("livekit.agents.Agent.default.tts_node", synthesize):
            await session.start(agent=agent, record=False)
            try:
                await native_turn(session, agent, "Пожалуйста, подготовьте тестовое бронирование.")
                canonical = state.render_recap()
                assert CONSENT["ru"] in canonical
                assert state.pending["delivery"] and not state.pending["approved"]
                assert agent.chat_ctx.items[-1].text_content == canonical
                assert not state.bookings and model.calls == 1
                if kind == "stay":
                    quote = state.pending["quote"]
                    assert f"{quote['quoted_total']} EUR" in canonical
                    assert "Оплата не взимается" in canonical
                await native_turn(session, agent, CONSENT["ru"])
                assert len(state.bookings) == 1 and state.turn_mutation == "confirmed"
                assert agent.chat_ctx.items[-1].text_content == localize(MUTATION_REPLIES["confirmed"], "ru")
                if kind == "stay":
                    assert len((await backend.get_operator_bookings())["items"]) == 1
                await native_turn(session, agent, "Да, отмените.")
                assert state.cancelled_bookings == state.bookings
                assert agent.chat_ctx.items[-1].text_content == localize(MUTATION_REPLIES["cancelled"], "ru")
                assert model.calls == 1
                assert [call.name for call in executed] == [
                    name, "confirm_booking" if kind == "stay" else "confirm_slot_booking",
                    "cancel_booking" if kind == "stay" else "cancel_slot_booking",
                ]
                if kind == "stay":
                    assert (await backend.get_operator_bookings())["items"][0]["status"] == "cancelled"
                else:
                    assert sum(name == "confirm" for name, _ in backend.calls) == 1
                    assert sum(name == "cancel" for name, _ in backend.calls) == 1
            finally:
                await session.aclose()

    asyncio.run(run())


def test_native_russian_recognition_selects_svetlana_voice_and_instructions():
    pytest.importorskip("livekit.agents")
    from livekit import rtc
    from livekit.agents import llm, stt
    from livekit.agents.voice.agent import ModelSettings

    from app.worker import TelephoneAgent

    async def run():
        updates = []
        provider = SimpleNamespace(update_options=lambda **options: updates.append(options))
        speech = SpeechConfig.from_env({})
        state = CallTools(Slots())
        agent = TelephoneAgent(state, speech_config=speech, speech_provider=provider)

        async def events(*args):
            yield stt.SpeechEvent(
                type=stt.SpeechEventType.FINAL_TRANSCRIPT,
                alternatives=[stt.SpeechData(text="Здравствуйте!", language="ru")],
            )

        with patch("livekit.agents.Agent.default.stt_node", events):
            assert len([event async for event in agent.stt_node(None, None)]) == 1
        message = llm.ChatMessage(role="user", content=["Здравствуйте!"])
        await agent.on_user_turn_completed(llm.ChatContext(), message)
        assert state.language == "ru" and "Current caller language: Russian" in agent.instructions

        async def text():
            yield "Здравствуйте!"

        frame = rtc.AudioFrame(b"\x10\x01" * 480, 24000, 1, 480)

        async def synthesis(*args):
            yield frame

        with patch("livekit.agents.Agent.default.tts_node", synthesis):
            assert [part async for part in agent.tts_node(text(), ModelSettings())] == [frame]
        assert updates == [{"voice": "ru-RU-SvetlanaNeural", "language": "ru-RU"}]
        assert agent._final_user_turn == (message.id, state._turn_serial)

    asyncio.run(run())


def test_native_russian_failure_uses_actual_estonian_cached_audio_and_history():
    pytest.importorskip("livekit.agents")
    from livekit.agents.types import USERDATA_TIMED_TRANSCRIPT

    from app.worker import TelephoneAgent, fallback_audio

    async def run():
        state = CallTools(Dispatcher(slot=LiveSlots()), language="ru")
        await raw_prepared(state)
        agent = TelephoneAgent(state)

        async def text():
            yield state.render_recap()

        async def fail(*args):
            raise RuntimeError("private provider fixture")
            yield

        with patch("livekit.agents.Agent.default.tts_node", fail):
            frames = [frame async for frame in agent.tts_node(text(), None)]
        cached = [frame async for frame in fallback_audio("et")]
        assert len(frames) > 100 and all(frame.sample_rate == 24000 for frame in frames)
        assert any(any(frame.data) for frame in frames)
        assert [bytes(frame.data) for frame in frames] == [bytes(frame.data) for frame in cached]

        async def actual_speech():
            for frame in frames:
                for part in frame.userdata.get(USERDATA_TIMED_TRANSCRIPT, []):
                    yield part

        assert [part async for part in agent.transcription_node(actual_speech(), None)] == [FALLBACK]
        assert state.language == "ru" and state.pending is None
        assert state.outcome == "provider_error" and not state.bookings

    asyncio.run(run())
