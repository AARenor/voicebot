"""Published hotel FAQ shortcuts must not override the restaurant domain."""

import pytest

from app.booking_faq import load_faq
from app.booking.tools import Dispatcher
from app.telephone import CallTools
from tests.test_table_policy import table_state


@pytest.mark.parametrize("language", ["et", "en", "ru"])
def test_restaurant_never_selects_archived_booking_faq_bank(language):
    state, _ = table_state(language=language)
    for entry in load_faq():
        state.observe_user_text(entry["question_" + language], language=language)
        assert not state.faq_entries, entry["id"]
        assert entry["id"] != "booking-047" or state.faq_response() is None


@pytest.mark.parametrize("language", ["et", "en", "ru"])
def test_archived_adapters_keep_reviewed_faq_shortcuts(language):
    state = CallTools(Dispatcher(), language=language)
    entry = next(entry for entry in load_faq() if entry["id"] == "booking-047")
    state.observe_user_text(entry["question_" + language], language=language)
    assert state.faq_response() == {"content": entry["answer_" + language]}
