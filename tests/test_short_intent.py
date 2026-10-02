"""Concise exact commitments keep the existing ownership/delivery boundary."""

import asyncio

import pytest

from app.telephone import CallTools, CONSENT_TEXT
from tests.test_telephone import Slots, booked, prepared


def test_short_canonical_prompt_and_owned_lifecycle():
    async def run():
        state = CallTools(Slots())
        await prepared(state)
        assert CONSENT_TEXT == "Jah, kinnitan."
        assert f"„{CONSENT_TEXT}”" in state.render_recap()
        state.observe_user_text(CONSENT_TEXT)
        assert (
            await state.dispatch("confirm_slot_booking", {"hold_id": "owned-hold"})
        )["ok"]
        state.observe_user_text("Jah, tühista.")
        assert (
            await state.dispatch("cancel_slot_booking", {"booking_id": "owned-booking"})
        )["ok"]
        assert state.turn_mutation == "cancelled"
        assert state.cancelled_bookings == {"owned-booking"}
        assert (
            sum(name == "cancel_slot_booking" for name, _ in state.dispatcher.calls)
            == 1
        )

    asyncio.run(run())


@pytest.mark.parametrize("boundary", ["undelivered", "expired", "foreign"])
def test_short_confirmation_never_bypasses_recap_or_ownership(boundary):
    async def run():
        state = CallTools(Slots())
        await prepared(state)
        if boundary == "undelivered":
            state.pending["delivery"] = False
        if boundary == "expired":
            state.pending["expires_at"] = 0
        state.observe_user_text("Jah, kinnitan.")
        target = "foreign-hold" if boundary == "foreign" else "owned-hold"
        assert "error" in await state.dispatch(
            "confirm_slot_booking", {"hold_id": target}
        )
        assert not any(
            name == "confirm_slot_booking" for name, _ in state.dispatcher.calls
        )

    asyncio.run(run())


@pytest.mark.parametrize(
    "text",
    [
        "Jah",
        "Jah?",
        "Kinnitan?",
        "Jah, kinnitan. Ei, ära kinnita.",
        "Jah, kinnitan teise kõne broneeringu.",
    ],
)
def test_ambiguous_or_mixed_short_answer_cannot_authorize(text):
    async def run():
        state = CallTools(Slots())
        await prepared(state)
        state.observe_user_text(text)
        assert (
            await state.dispatch("confirm_slot_booking", {"hold_id": "owned-hold"})
        )["error"] == "consent_required"

    asyncio.run(run())


@pytest.mark.parametrize("text", ["Jah", "Jah?", "Jah, tühista. Ei, ära tühista."])
def test_ambiguous_or_mixed_cancellation_cannot_authorize(text):
    async def run():
        state = CallTools(Slots())
        await booked(state)
        state.observe_user_text(text)
        assert (
            await state.dispatch("cancel_slot_booking", {"booking_id": "owned-booking"})
        )["error"] == "cancellation_required"
        assert state.bookings == {"owned-booking"}

    asyncio.run(run())


def test_short_cancellation_is_latest_owned_only():
    async def run():
        state = CallTools(Slots())
        await booked(state)
        state.observe_user_text("Jah, tühista.")
        assert "error" in await state.dispatch(
            "cancel_slot_booking", {"booking_id": "foreign"}
        )
        assert not any(
            name == "cancel_slot_booking" for name, _ in state.dispatcher.calls
        )

    asyncio.run(run())
