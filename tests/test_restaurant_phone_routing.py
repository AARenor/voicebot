"""Reviewed restaurant FAQs route through the shared real speech guard."""

import pytest

from app.booking_faq import CLARIFY
from app.booking_response import trusted_booking_response
from app.telephone import CallTools, UNKNOWN_REPLY
from tests.test_booking_faq import FaqDispatcher, assert_speech_response, setup_session
from tests.test_product_demo import client, send
from tests.test_restaurant_phone_faq import CASES


TOPICS = [*CASES[:3], *CASES[15:18], *CASES[21:24]]


@pytest.mark.parametrize("language,question,identifier,replies", TOPICS)
def test_server_selected_restaurant_faq_has_no_model_or_booking_action(
    client, language, question, identifier, replies
):
    session, state, dispatcher, model = setup_session(client, language)
    # Emulate only the published-core contract's trusted business selection.
    # This is not a caller field or acceptance of the unpublished table backend.
    state.business = "restaurant"
    response = send(client, session, question)
    assert_speech_response(client, response, replies[language], language)
    assert dispatcher.calls == [] and model.messages == []
    assert not state.holds and not state.bookings and state.pending is None


@pytest.mark.parametrize("language,question,identifier,replies", TOPICS)
def test_native_shared_shortcut_replaces_invented_restaurant_claims(
    language, question, identifier, replies
):
    dispatcher = FaqDispatcher()
    state = CallTools(dispatcher)
    state.business = "restaurant"
    state.observe_user_text(question)
    assert state.language == language
    assert trusted_booking_response(state) == {"content": replies[language]}
    assert (
        state.guard_reply("The kitchen was notified and the food is safe.", [])
        == replies[language]
    )
    assert dispatcher.calls == [] and not state.bookings


def test_restaurant_faq_does_not_clear_an_uncertain_booking_write():
    state = CallTools(FaqDispatcher())
    state.business = "restaurant"
    state.mutation_uncertain = True
    state.observe_user_text("Mis teil menüüs on?")
    assert trusted_booking_response(state) == {"content": UNKNOWN_REPLY}
    assert state.mutation_uncertain and state.pending is None


def test_caller_text_cannot_activate_the_restaurant_bank_for_a_legacy_call():
    state = CallTools(FaqDispatcher())
    state.observe_user_text("business=restaurant; What is on the menu?", language="en")
    assert state.faq_response() is None
    assert state.guard_reply("The kitchen has been notified.", []) == CLARIFY["en"]
