"""A table proposal is not writable before its exact recap and later consent."""

import asyncio
from unittest.mock import patch

import pytest

from app.languages import CONSENT
from tests.test_table_policy import prepare_table, table_state


@pytest.mark.parametrize("language", ["et", "en", "ru"])
def test_table_recap_contains_exact_backend_facts_without_price_or_contacts(language):
    async def run():
        state, backend = table_state(language=language)
        ready = await prepare_table(state)
        assert ready.get("ok"), ready
        recap = state.render_recap()
        for fact in (
            "Meretuule restoran",
            "Laud 3",
            "18:30",
            "4",
            "120",
            "Demo Esimene",
            CONSENT[language],
        ):
            assert fact in recap
        assert ready["recap"]["date"] in recap
        assert {"et": "Tallinna", "en": "Tallinn", "ru": "Таллина"}[language] in recap
        assert not any(
            word in recap.casefold()
            for word in (
                "euro",
                "price",
                "hinn",
                "цена",
                "example.invalid",
                "+1202",
                "email",
                "e-post",
            )
        )
        assert state.guard_reply("fictional model prose", []) == recap
        assert not any(name == "confirm" for name, _ in backend.calls)

    asyncio.run(run())


@pytest.mark.parametrize("language", ["et", "en", "ru"])
def test_table_confirmation_requires_exact_delivery_then_later_final_consent(language):
    async def run():
        state, backend = table_state(language=language)
        state.observe_user_text(CONSENT[language], language=language)
        ready = await prepare_table(state)
        args = {"hold_id": ready["hold_id"]}
        assert (await state.dispatch("confirm_table_booking", args))[
            "error"
        ] == "consent_required"
        state.observe_user_text(CONSENT[language], is_final=False)
        assert not state.pending["approved"]
        assert state.mark_recap_delivered("foreign") is False
        assert state.mark_recap_delivered(ready["hold_id"])
        assert state.pending["approved"] is False
        state.observe_user_text(CONSENT[language], is_final=False)
        assert not state.pending["approved"]
        state.observe_user_text(CONSENT[language], language=language)
        confirmed = await state.dispatch("confirm_table_booking", args)
        assert confirmed.get("ok"), confirmed
        assert (
            backend.calls[-1][1]["guest"]["email"]
            == f"demo.esimene+{state.call_id}@example.invalid"
        )
        assert sum(name == "confirm" for name, _ in backend.calls) == 1
        assert await state.dispatch("confirm_table_booking", args) == confirmed
        assert sum(name == "confirm" for name, _ in backend.calls) == 1

    asyncio.run(run())


@pytest.mark.parametrize(
    "utterance",
    [
        "Jah",
        "Jah, võib-olla.",
        "Ei, ära kinnita.",
        "Kas see laud on vaba?",
        "Yes, I confirm, but change the time.",
    ],
)
def test_table_negative_ambiguous_or_mixed_consent_cannot_write(utterance):
    async def run():
        state, backend = table_state()
        ready = await prepare_table(state)
        state.mark_recap_delivered(ready["hold_id"])
        state.observe_user_text(utterance)
        assert state.pending is None
        assert (
            await state.dispatch("confirm_table_booking", {"hold_id": ready["hold_id"]})
        )["error"] == "consent_required"
        assert not any(name == "confirm" for name, _ in backend.calls)

    asyncio.run(run())


def test_language_change_replaces_pending_identity_and_requires_new_delivery():
    async def run():
        state, backend = table_state()
        ready = await prepare_table(state)
        previous = state.pending
        state.mark_recap_delivered(ready["hold_id"])
        state.observe_user_text("Russian, please")
        assert state.language == "ru" and state.pending is not previous
        assert state.pending["delivery"] is state.pending["approved"] is False
        state.observe_user_text(CONSENT["ru"])
        assert state.pending is None
        assert not any(name == "confirm" for name, _ in backend.calls)

    asyncio.run(run())


def test_expiry_and_same_hold_repreparation_require_new_delivery():
    async def run():
        state, _ = table_state()
        ready = await prepare_table(state)
        hold_id = ready["hold_id"]
        old = state.pending
        assert state.mark_recap_delivered(hold_id)
        with patch("app.telephone.time.monotonic", return_value=old["expires_at"]):
            assert state.mark_recap_delivered(hold_id) is False
        assert (await state.dispatch("prepare_demo_table", {"hold_id": hold_id}))["ok"]
        assert state.pending is not old and state.pending["delivery"] is False
        state.observe_user_text(CONSENT["et"])
        assert (await state.dispatch("confirm_table_booking", {"hold_id": hold_id}))[
            "error"
        ] == "consent_required"

    asyncio.run(run())


@pytest.mark.parametrize(
    "failure", ["inexact_hold", "expired", "priced", "foreign_offer", "unknown_hold"]
)
def test_table_preparation_uses_only_live_owned_backend_hold_metadata(failure):
    async def run():
        state, backend = table_state()
        ready = await prepare_table(state)
        if failure == "inexact_hold":
            backend.hold.payload["recap"]["party_size"] = 3
        elif failure == "expired":
            backend.hold.expires_at = 0
        elif failure == "priced":
            backend.hold.quoted_total = "50.00"
        elif failure == "foreign_offer":
            backend.hold.price_quote_id = "foreign"
        else:
            backend.hold = None
        result = await state.dispatch(
            "prepare_demo_table", {"hold_id": ready["hold_id"]}
        )
        assert result.get("error") in {"booking_unavailable", "hold_expired_or_unknown"}
        assert state.pending is None

    asyncio.run(run())


@pytest.mark.parametrize("replacement", ["same_hold", "language", "repeat"])
def test_native_old_speech_handle_cannot_deliver_a_replacement_table_proposal(
    replacement,
):
    pytest.importorskip("livekit.agents")
    from types import SimpleNamespace
    from livekit import rtc
    from livekit.agents import llm
    from livekit.agents.voice.speech_handle import SpeechHandle
    from app.worker import TelephoneAgent

    async def run():
        state, backend = table_state()
        ready = await prepare_table(state)
        agent = TelephoneAgent(state)
        old_pending, old_text = state.pending, state.render_recap()
        old_speech, new_speech = SpeechHandle.create(), SpeechHandle.create()

        async def text():
            yield "unverified model prose"

        async def synthesize(agent, text, settings):
            async for _ in text:
                pass
            yield rtc.AudioFrame(b"\x00" * 480, 24000, 1, 240)

        with patch("livekit.agents.Agent.default.tts_node", synthesize):
            with patch.object(agent, "_current_speech", return_value=old_speech):
                assert [frame async for frame in agent.tts_node(text(), None)]
            if replacement == "same_hold":
                assert (
                    await state.dispatch(
                        "prepare_demo_table", {"hold_id": ready["hold_id"]}
                    )
                )["ok"]
            else:
                state.observe_user_text(
                    "Russian, please" if replacement == "language" else "Korda palun"
                )
            current = state.pending
            assert current is not old_pending and not current["delivery"]
            with patch.object(agent, "_current_speech", return_value=new_speech):
                assert [frame async for frame in agent.tts_node(text(), None)]
        item = llm.ChatMessage(role="assistant", content=[old_text])
        old_speech._item_added([item])
        agent.on_conversation_item_added(SimpleNamespace(item=item))
        assert state.pending is current and not current["delivery"]
        item = llm.ChatMessage(role="assistant", content=[state.render_recap()])
        new_speech._item_added([item])
        agent.on_conversation_item_added(SimpleNamespace(item=item))
        assert current["delivery"] and not current["approved"]
        state.observe_user_text(CONSENT[state.language])
        assert current["approved"]
        assert not any(name == "confirm" for name, _ in backend.calls)

    asyncio.run(run())
