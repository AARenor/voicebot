import asyncio
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.booking.tools import Dispatcher
from app.telephone import CallTools, CONSENT_TEXT
from tests.test_demo_plan import DAY, LiveSlots
from tests.test_telephone import booked, Slots


CONSENT = "Jah, kinnitan selle testbroneeringu."


async def raw_prepared(state):
    slots = await state.dispatch(
        "search_slots", {"service": "6", "provider": "2", "date": DAY}
    )
    hold = await state.dispatch("hold_slot", {"slot_id": slots["slots"][0]["slotId"]})
    return await state.dispatch("prepare_demo_booking", {"hold_id": hold["hold_id"]})


def test_preparation_without_specific_recap_delivery_cannot_authorize_booking():
    async def run():
        backend = LiveSlots()
        state = CallTools(Dispatcher(slot=backend))
        assert (await raw_prepared(state))["ok"]
        state.observe_user_text(CONSENT)
        assert await state.dispatch(
            "confirm_slot_booking", {"hold_id": "backend-hold"}
        ) == {"error": "consent_required"}
        assert not any(name == "confirm" for name, _ in backend.calls)

    asyncio.run(run())


def test_canonical_delivery_is_owned_exact_and_required_before_final_consent():
    async def run():
        backend = LiveSlots()
        state = CallTools(Dispatcher(slot=backend))
        ready = await raw_prepared(state)
        assert callable(getattr(state, "render_recap", None)), (
            "canonical recap is missing"
        )
        text = state.render_recap(ready["hold_id"])
        assert state.pending["recap"]["start"].startswith(DAY)
        assert "Eesti aja järgi" in text
        for field in (
            "Backend consultation",
            "Backend therapist",
            "10:30",
            "Demo Esimene",
            CONSENT_TEXT,
        ):
            assert field in text
        assert "example.invalid" not in text and "+120255501" not in text
        assert state.pending["delivery"] is False
        assert state.mark_recap_delivered("foreign") is False
        assert state.mark_recap_delivered(ready["hold_id"]) is True
        assert state.pending["approved"] is False
        state.observe_user_text(CONSENT)
        assert (
            await state.dispatch("confirm_slot_booking", {"hold_id": ready["hold_id"]})
        )["ok"] is True

    asyncio.run(run())


@pytest.mark.parametrize(
    "text",
    [
        "Testbroneering on kinnitatud.",
        "Broneerisin sulle aja.",
        "Testbroneering on tühistatud.",
        "Your booking is confirmed.",
    ],
)
def test_success_prose_requires_authoritative_current_outcome(text):
    state = CallTools(Dispatcher())
    assert callable(getattr(state, "guard_reply", None)), (
        "authoritative speech guard is missing"
    )
    reply = state.guard_reply(text, [])
    assert reply != text
    assert "ei ole kinnitatud" in reply


@pytest.mark.parametrize(
    "error",
    [
        "write_outcome_unknown",
        "cancel_outcome_unknown",
        "mutation_outcome_unknown",
        "not_owned",
        "consent_required",
    ],
)
def test_failed_or_unknown_result_cannot_be_spoken_as_success(error):
    state = CallTools(Dispatcher())
    assert callable(getattr(state, "guard_reply", None)), (
        "authoritative speech guard is missing"
    )
    reply = state.guard_reply("Testbroneering on kinnitatud.", [{"error": error}])
    assert "on kinnitatud" not in reply
    assert "ei ole kinnitatud" in reply
    if error.endswith("outcome_unknown"):
        assert "ebaselge" in reply
        assert "Ära korda" in reply


def test_cancelled_booking_cannot_replay_old_confirmation_success():
    async def run():
        backend = Slots()
        state = CallTools(backend)
        await booked(state)
        state.observe_user_text("Palun tühista see testbroneering.")
        assert (
            await state.dispatch("cancel_slot_booking", {"booking_id": "owned-booking"})
        )["ok"]
        assert await state.dispatch(
            "confirm_slot_booking", {"hold_id": "owned-hold"}
        ) == {"error": "already_cancelled"}
        assert sum(name == "confirm_slot_booking" for name, _ in backend.calls) == 1
        assert sum(name == "cancel_slot_booking" for name, _ in backend.calls) == 1

    asyncio.run(run())


def test_guard_allows_only_live_confirmed_or_actual_cancelled_status_and_keeps_price_gate():
    async def run():
        state = CallTools(Slots())
        assert callable(getattr(state, "guard_reply", None)), (
            "authoritative speech guard is missing"
        )
        await booked(state)
        assert (
            state.guard_reply("Testbroneering on kinnitatud.", [])
            == "Testbroneering on kinnitatud."
        )
        assert (
            state.guard_reply("See maksab 120 eurot.", [])
            == "Ma ei saa praegu hinda kinnitada."
        )
        state.observe_user_text("Palun tühista see testbroneering.")
        await state.dispatch("cancel_slot_booking", {"booking_id": "owned-booking"})
        assert (
            state.guard_reply("Testbroneering on kinnitatud.", [])
            != "Testbroneering on kinnitatud."
        )
        assert (
            state.guard_reply("Testbroneering on tühistatud.", [])
            == "Testbroneering on tühistatud."
        )

    asyncio.run(run())


def test_native_tts_forces_canonical_recap_but_does_not_mark_until_completed_item():
    pytest.importorskip("livekit.agents")
    from app.worker import TelephoneAgent
    from livekit import rtc
    from livekit.agents.voice.speech_handle import SpeechHandle

    async def run():
        state = CallTools(Dispatcher(slot=LiveSlots()))
        await raw_prepared(state)
        agent = TelephoneAgent(state)
        canonical = state.render_recap()
        seen = []
        speech = SpeechHandle.create()

        async def text():
            yield "Tere!"

        async def synthesize(agent, text, settings):
            async for part in text:
                seen.append(part)
            yield rtc.AudioFrame(b"\x10\x01" * 480, 24000, 1, 480)

        with (
            patch("livekit.agents.Agent.default.tts_node", synthesize),
            patch.object(agent, "_current_speech", return_value=speech),
        ):
            assert len([frame async for frame in agent.tts_node(text(), None)]) == 1
        assert "Backend consultation" in seen[0], (
            "optional model prose was spoken instead of recap"
        )
        assert seen == [canonical]
        assert state.pending["delivery"] is False
        assert [part async for part in agent.transcription_node(text(), None)] == seen
        agent.on_conversation_item_added(
            SimpleNamespace(
                item=SimpleNamespace(
                    role="user", interrupted=False, text_content=seen[0]
                )
            )
        )
        assert state.pending["delivery"] is False
        item = SimpleNamespace(
            role="assistant", interrupted=False, text_content=seen[0]
        )
        speech._item_added([item])
        agent.on_conversation_item_added(SimpleNamespace(item=item))
        assert state.pending["delivery"] is True
        assert state.pending["approved"] is False
        state.observe_user_text(CONSENT)
        assert (
            await state.dispatch("confirm_slot_booking", {"hold_id": "backend-hold"})
        )["ok"]

    asyncio.run(run())


def test_native_tts_failure_even_with_completed_item_does_not_authorize_booking():
    pytest.importorskip("livekit.agents")
    from app.worker import TelephoneAgent

    async def run():
        state = CallTools(Dispatcher(slot=LiveSlots()))
        await raw_prepared(state)
        agent = TelephoneAgent(state)
        canonical = state.render_recap()

        async def text():
            yield "Testbroneering valmis."

        async def fail(*args):
            raise RuntimeError("private provider response")
            yield

        with patch("livekit.agents.Agent.default.tts_node", fail):
            assert len([frame async for frame in agent.tts_node(text(), None)]) > 200
        agent.on_conversation_item_added(
            SimpleNamespace(
                item=SimpleNamespace(
                    role="assistant", interrupted=False, text_content=canonical
                )
            )
        )
        state.observe_user_text(CONSENT)
        assert (
            await state.dispatch("confirm_slot_booking", {"hold_id": "backend-hold"})
        )["error"] == "consent_required"

    asyncio.run(run())


@pytest.mark.parametrize("interrupted", [True, False])
def test_interrupted_or_mismatching_completed_item_cannot_mark_delivery(interrupted):
    pytest.importorskip("livekit.agents")
    from app.worker import TelephoneAgent
    from livekit import rtc
    from livekit.agents.voice.speech_handle import SpeechHandle

    async def run():
        state = CallTools(Dispatcher(slot=LiveSlots()))
        await raw_prepared(state)
        assert callable(getattr(state, "render_recap", None)), (
            "canonical recap is missing"
        )
        agent = TelephoneAgent(state)
        speech = SpeechHandle.create()
        canonical = state.render_recap()

        async def text():
            yield "Tere!"

        async def synthesize(agent, text, settings):
            async for _ in text:
                pass
            yield rtc.AudioFrame(b"\x10\x01" * 480, 24000, 1, 480)

        with (
            patch("livekit.agents.Agent.default.tts_node", synthesize),
            patch.object(agent, "_current_speech", return_value=speech),
        ):
            assert len([f async for f in agent.tts_node(text(), None)]) == 1
        item = SimpleNamespace(
            role="assistant",
            interrupted=interrupted,
            text_content=canonical if interrupted else "Tere!",
        )
        speech._item_added([item])
        agent.on_conversation_item_added(SimpleNamespace(item=item))
        state.observe_user_text(CONSENT)
        assert (
            await state.dispatch("confirm_slot_booking", {"hold_id": "backend-hold"})
        )["error"] == "consent_required"

    asyncio.run(run())


def test_old_completed_recap_cannot_mark_a_new_preparation_of_same_hold():
    pytest.importorskip("livekit.agents")
    from app.worker import TelephoneAgent
    from livekit import rtc

    async def run():
        state = CallTools(Dispatcher(slot=LiveSlots()))
        await raw_prepared(state)
        assert callable(getattr(state, "render_recap", None)), (
            "canonical recap is missing"
        )
        agent = TelephoneAgent(state)
        canonical = state.render_recap()

        async def text():
            yield "Tere!"

        async def synthesize(agent, text, settings):
            async for _ in text:
                pass
            yield rtc.AudioFrame(b"\x10\x01" * 480, 24000, 1, 480)

        with patch("livekit.agents.Agent.default.tts_node", synthesize):
            assert [f async for f in agent.tts_node(text(), None)]
        await state.dispatch("prepare_demo_booking", {"hold_id": "backend-hold"})
        agent.on_conversation_item_added(
            SimpleNamespace(
                item=SimpleNamespace(
                    role="assistant", interrupted=False, text_content=canonical
                )
            )
        )
        assert state.pending["delivery"] is False

    asyncio.run(run())


def test_denied_mutation_is_recorded_for_guard_even_with_an_older_owned_booking():
    async def run():
        state = CallTools(Slots())
        await booked(state)
        state.observe_user_text("Proovi teist broneeringut.")
        assert (await state.dispatch("confirm_slot_booking", {"hold_id": "foreign"}))[
            "error"
        ] == "not_owned"
        assert (
            state.guard_reply("Testbroneering on kinnitatud.", state.results)
            != "Testbroneering on kinnitatud."
        )
        assert state.results[-1] == {"error": "not_owned"}

    asyncio.run(run())


def test_price_blocked_recap_and_expired_delivery_cannot_authorize_booking():
    async def run():
        state = CallTools(Dispatcher(slot=LiveSlots()))
        await raw_prepared(state)
        pending = state.pending
        with patch(
            "app.telephone.time.monotonic", return_value=pending["expires_at"] + 1
        ):
            assert state.mark_recap_delivered("backend-hold") is False
        await raw_prepared(state)
        assert (
            state.guard_reply("See maksab 120 eurot.", state.results)
            == "Ma ei saa praegu hinda kinnitada."
        )
        assert state.mark_recap_delivered("backend-hold") is False
        state.observe_user_text(CONSENT)
        assert (
            await state.dispatch("confirm_slot_booking", {"hold_id": "backend-hold"})
        )["error"] == "consent_required"

    asyncio.run(run())


def test_partial_synthesis_never_marks_delivery_on_a_completed_item():
    pytest.importorskip("livekit.agents")
    from app.worker import TelephoneAgent
    from livekit import rtc

    async def run():
        state = CallTools(Dispatcher(slot=LiveSlots()))
        await raw_prepared(state)
        agent = TelephoneAgent(state)
        canonical = state.render_recap()
        first = rtc.AudioFrame(b"\x10\x01" * 480, 24000, 1, 480)

        async def text():
            yield "Tere!"

        async def incomplete(agent, text, settings):
            async for _ in text:
                pass
            yield first
            yield rtc.AudioFrame(b"\x10\x01" * 480, 24000, 1, 480)

        with patch("livekit.agents.Agent.default.tts_node", incomplete):
            audio = agent.tts_node(text(), None)
            assert await anext(audio) is first
            await audio.aclose()
        agent.on_conversation_item_added(
            SimpleNamespace(
                item=SimpleNamespace(
                    role="assistant", interrupted=False, text_content=canonical
                )
            )
        )
        state.observe_user_text(CONSENT)
        assert (
            await state.dispatch("confirm_slot_booking", {"hold_id": "backend-hold"})
        )["error"] == "consent_required"

    asyncio.run(run())


@pytest.mark.parametrize(
    "error",
    ["write_outcome_unknown", "cancel_outcome_unknown", "mutation_outcome_unknown"],
)
def test_uncertain_cancellation_remains_unknown_on_next_user_turn(error):
    async def run():
        backend = LiveSlots()

        async def uncertain_cancel(booking_id, key):
            return {"ok": False, "error": error}

        backend.cancel = uncertain_cancel
        state = CallTools(Dispatcher(slot=backend))
        ready = await raw_prepared(state)
        assert state.mark_recap_delivered(ready["hold_id"])
        state.observe_user_text(CONSENT)
        assert (
            await state.dispatch("confirm_slot_booking", {"hold_id": ready["hold_id"]})
        )["ok"]
        state.observe_user_text("Palun tühista see testbroneering.")
        assert (await state.dispatch("cancel_slot_booking", {"booking_id": "42"}))[
            "error"
        ] == error
        assert state.outcome == "write_outcome_unknown"
        state.observe_user_text("Kas broneering on alles?")
        reply = state.guard_reply("Testbroneering on kinnitatud.", state.results)
        assert "ebaselge" in reply and "Ära korda" in reply

    asyncio.run(run())


def test_native_text_stream_failure_invalidates_recap_and_plays_cached_fallback():
    pytest.importorskip("livekit.agents")
    from app.worker import TelephoneAgent

    async def run():
        state = CallTools(Dispatcher(slot=LiveSlots()))
        ready = await raw_prepared(state)
        assert state.mark_recap_delivered(ready["hold_id"])
        agent = TelephoneAgent(state)

        async def text():
            yield "Tere!"
            raise RuntimeError("private model response")

        # No TTS call is needed when the incoming generation itself has failed.
        with patch("livekit.agents.Agent.default.tts_node") as synthesize:
            assert len([frame async for frame in agent.tts_node(text(), None)]) > 200
            synthesize.assert_not_called()
        assert state.pending is None
        state.observe_user_text(CONSENT)
        assert (
            await state.dispatch("confirm_slot_booking", {"hold_id": ready["hold_id"]})
        )["error"] == "consent_required"

    asyncio.run(run())


def test_native_tts_failure_does_not_replace_an_uncertain_write_outcome():
    pytest.importorskip("livekit.agents")
    from app.worker import TelephoneAgent

    async def run():
        backend = LiveSlots()
        backend.confirm_result = {"ok": False, "error": "write_outcome_unknown"}
        state = CallTools(Dispatcher(slot=backend))
        ready = await raw_prepared(state)
        assert state.mark_recap_delivered(ready["hold_id"])
        state.observe_user_text(CONSENT)
        await state.dispatch("confirm_slot_booking", {"hold_id": ready["hold_id"]})
        agent = TelephoneAgent(state)

        async def text():
            yield "Testbroneering on kinnitatud."

        async def fail(*args):
            raise RuntimeError("private TTS response")
            yield

        with patch("livekit.agents.Agent.default.tts_node", fail):
            assert len([frame async for frame in agent.tts_node(text(), None)]) > 200
        assert state.outcome == "write_outcome_unknown"

    asyncio.run(run())


def test_an_older_booking_does_not_authorize_success_for_a_new_unwritten_hold():
    async def run():
        backend = LiveSlots()
        state = CallTools(Dispatcher(slot=backend))
        ready = await raw_prepared(state)
        assert state.mark_recap_delivered(ready["hold_id"])
        state.observe_user_text(CONSENT)
        assert (
            await state.dispatch("confirm_slot_booking", {"hold_id": ready["hold_id"]})
        )["ok"]
        state.observe_user_text("Soovin veel üht testbroneeringut.")
        backend.slots[0]["slotId"] = "next-returned-slot"

        async def next_hold(slot_id):
            return SimpleNamespace(hold_id="next-owned-hold")

        backend.create_hold = next_hold
        ready = await raw_prepared(state)
        assert state.mark_recap_delivered(ready["hold_id"])
        state.observe_user_text(CONSENT)
        assert (
            state.guard_reply("Testbroneering on kinnitatud.", state.results)
            != "Testbroneering on kinnitatud."
        )
        assert sum(name == "confirm" for name, _ in backend.calls) == 1

    asyncio.run(run())
