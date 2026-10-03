"""Recoverable speech stays specific; booking truth and metadata stay guarded."""

import asyncio

import pytest

from app.booking.tools import Dispatcher
from app.telephone import CallTools, UNKNOWN_REPLY, UNVERIFIED_REPLY
from tests.test_demo_plan import LiveSlots


def test_plain_missing_date_time_request_is_not_a_mutation_claim():
    state = CallTools(Dispatcher())
    question = "Palun ütle soovitud kuupäev ja kellaaeg."
    assert state.guard_reply(question, []) == question


@pytest.mark.parametrize(
    "error,expected",
    [
        (
            "slot_unavailable",
            "Soovitud aeg ei ole saadaval. Palun vali teine kuupäev või kellaaeg.",
        ),
        (
            "past_datetime",
            "See kuupäev ja kellaaeg on juba möödunud. Palun vali tulevane aeg.",
        ),
        (
            "consent_required",
            "Testbroneering ei ole kinnitatud. Enne kinnitamist tuleb uus kokkuvõte ette lugeda. Palun ütle soovitud kuupäev ja kellaaeg.",
        ),
    ],
)
def test_expected_recoverable_error_gives_safe_next_step(error, expected):
    state = CallTools(Dispatcher())
    assert (
        state.guard_reply("Testbroneering on kinnitatud.", [{"error": error}])
        == expected
    )
    state._unknown_mutation()
    assert state.guard_reply(expected, [{"error": error}]) == UNKNOWN_REPLY


@pytest.mark.parametrize(
    "text",
    [
        "Kell kümme on vaba, kas sobib?",
        "Broneerisin sulle aja, kas sobib?",
        "Palun ütle soovitud kuupäev ja kellaaeg. Broneering on kinnitatud.",
        "Palun ütle soovitud kuupäev ja kellaaeg. Hind on 10 eurot.",
    ],
)
def test_clarification_allowlist_never_licenses_availability_price_or_success(text):
    state = CallTools(Dispatcher())
    assert state.guard_reply(text, []) in {
        UNVERIFIED_REPLY,
        "Ma ei saa praegu hinda kinnitada.",
    }


@pytest.mark.parametrize("language", ["et", "en"])
@pytest.mark.parametrize(
    "start,estonian,english",
    [
        (
            "2026-10-20 10:30:00",
            "20. oktoobril 2026 kell 10:30",
            "20 October 2026 at 10:30 AM",
        ),
        (
            "2026-10-20T07:30:00+00:00",
            "20. oktoobril 2026 kell 10:30",
            "20 October 2026 at 10:30 AM",
        ),
        (
            "2026-10-20T22:30:00+00:00",
            "21. oktoobril 2026 kell 01:30",
            "21 October 2026 at 1:30 AM",
        ),
    ],
)
def test_spa_recap_speaks_tallinn_date_without_changing_booking_metadata(
    language, start, estonian, english
):
    async def run():
        backend = LiveSlots()
        backend.slots[0].update(date=start[:10], start=start)
        state = CallTools(Dispatcher(slot=backend), language=language)
        slots = await state.dispatch(
            "search_slots", {"service": "6", "provider": "2", "date": start[:10]}
        )
        hold = await state.dispatch(
            "hold_slot", {"slot_id": slots["slots"][0]["slotId"]}
        )
        assert (
            await state.dispatch("prepare_demo_booking", {"hold_id": hold["hold_id"]})
        )["ok"]
        metadata = state.pending["recap"].copy()
        text = state.render_recap()
        assert (
            english + ", Tallinn local time"
            if language == "en"
            else estonian + ", Eesti aja järgi"
        ) in text
        assert state.guard_reply("untrusted model prose", state.results) == text
        assert "2026-10-20" not in text and "Europe/Tallinn" not in text
        assert metadata["start"] == start
        assert state.pending["recap"] == metadata
        assert not state.pending["delivery"] and not state.pending["approved"]

    asyncio.run(run())
