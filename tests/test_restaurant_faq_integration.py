"""Restaurant answers use real business construction and table consent policy."""

import asyncio

import pytest

from app.booking.tools import Dispatcher
from app.booking_response import trusted_booking_response
from app.languages import CONSENT
from tests.test_booking_faq import assert_speech_response
from tests.test_product_demo import SimpleLlm, client, send, start
from tests.test_restaurant_phone_routing import TOPICS
from tests.test_table_policy import Tables, prepare_table, table_state


@pytest.mark.parametrize("language,question,identifier,replies", TOPICS)
def test_restaurant_constructor_routes_faq_without_table_actions(
    language, question, identifier, replies
):
    state, backend = table_state()
    assert state.business == "restaurant"
    state.observe_user_text(question)
    assert state.language == language
    assert trusted_booking_response(state) == {"content": replies[language]}
    assert backend.calls == [] and not state.holds and not state.bookings


@pytest.mark.parametrize("language,question,identifier,replies", TOPICS)
def test_http_dispatcher_selects_restaurant_without_a_caller_selector(
    client, language, question, identifier, replies
):
    backend = Tables()
    model = SimpleLlm("The kitchen was notified and your table is confirmed.")
    client.app.state.stack.update(
        dispatcher=Dispatcher(table=backend, business="restaurant"),
        llm_primary=model,
    )
    session = start(client)
    state = client.app.state.demo_sessions.sessions[session].tools
    assert state.business == "restaurant"
    response = send(client, session, question)
    assert_speech_response(client, response, replies[language], language)
    assert backend.calls == [] and model.messages == [] and not state.bookings


@pytest.mark.parametrize("field", ["business", "domain"])
def test_http_caller_cannot_override_the_server_restaurant_business(client, field):
    backend = Tables()
    client.app.state.stack.update(
        dispatcher=Dispatcher(table=backend, business="restaurant")
    )
    session = start(client)
    response = send(client, session, "Mis teil menüüs on?", **{field: "legacy"})
    assert response.status_code == 400
    assert (
        client.app.state.demo_sessions.sessions[session].tools.business == "restaurant"
    )
    assert backend.calls == []


@pytest.mark.parametrize("language,question,identifier,replies", TOPICS[:3])
def test_restaurant_faq_does_not_authorize_a_previously_delivered_table_recap(
    language, question, identifier, replies
):
    async def run():
        state, backend = table_state(language=language)
        await prepare_table(state)
        hold_id = state.pending["hold_id"]
        assert state.mark_recap_delivered(hold_id)
        state.observe_user_text(question, language=language)
        assert trusted_booking_response(state) == {"content": replies[language]}
        assert state.pending is None
        state.observe_user_text(CONSENT[language], language=language)
        result = await state.dispatch("confirm_table_booking", {"hold_id": hold_id})
        assert result.get("ok") is not True
        assert not any(name == "confirm" for name, _ in backend.calls)
        assert not state.bookings

    asyncio.run(run())


@pytest.mark.parametrize(
    "language,question",
    [
        ("et", "Mis teil menüüs on? Broneeri laud homme kell 18:30 neljale."),
        ("en", "What is on the menu? Book a table tomorrow at 18:30 for four."),
        ("ru", "Что у вас в меню? Забронируйте столик завтра в 18:30 на четверых."),
    ],
)
def test_mixed_restaurant_question_keeps_the_table_request(client, language, question):
    backend, model = Tables(), SimpleLlm()
    client.app.state.stack.update(
        dispatcher=Dispatcher(table=backend, business="restaurant"),
        llm_primary=model,
    )
    session = start(client)
    state = client.app.state.demo_sessions.sessions[session].tools
    response = send(client, session, question, language=language)
    assert response.status_code == 200
    assert state.faq_entries == () and state.faq_response() is None
    # The bounded clarification parser intentionally rejects mixed clauses.
    # The planner must receive the entire request instead of losing the booking
    # clause to a static FAQ shortcut or a guessed preference.
    assert state.booking_inquiry is None
    assert any(
        message.get("role") == "user" and message.get("content") == question
        for messages in model.messages
        for message in messages
    )
    assert backend.calls == [] and not state.bookings


def test_restaurant_faq_preserves_sticky_uncertain_table_write():
    state, backend = table_state()
    state.mutation_uncertain = True
    state.observe_user_text("Mis teil menüüs on?")
    from app.telephone import UNKNOWN_REPLY

    assert trusted_booking_response(state) == {"content": UNKNOWN_REPLY}
    assert state.mutation_uncertain and state.booking_inquiry is None
    assert backend.calls == [] and not state.bookings
