"""Recoverable speech stays specific; booking truth and metadata stay guarded."""

import asyncio

import pytest

from app.booking.tools import Dispatcher
from app.telephone import CallTools, UNKNOWN_REPLY, UNVERIFIED_REPLY
from tests.test_demo_delivery import raw_prepared
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


@pytest.mark.parametrize("start", ["2026-10-20 10:30:00", "2026-10-20T07:30:00+00:00"])
def test_spa_recap_speaks_tallinn_date_without_changing_booking_metadata(start):
    async def run():
        state = CallTools(Dispatcher(slot=LiveSlots()))
        await raw_prepared(state)
        state.pending["recap"]["start"] = start
        metadata = state.pending["recap"].copy()
        text = state.render_recap()
        assert "20. oktoobril 2026 kell 10:30, Eesti aja järgi" in text
        assert "2026-10-20" not in text and "Europe/Tallinn" not in text
        assert state.pending["recap"] == metadata
        assert not state.pending["delivery"] and not state.pending["approved"]

    asyncio.run(run())
