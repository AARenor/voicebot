"""Published restaurant answers use real construction and do not write notes/orders."""

import asyncio

import pytest

from app.booking_faq import load_faq, FAQ_PATH
from app.booking_response import trusted_booking_response
from app.restaurant_call import COPY
from tests.test_restaurant_conversation import make_state, prepare
from tests.test_restaurant_http import AUTH, client, start

BANK = load_faq(FAQ_PATH.with_name("restaurant-phone-faq.json"))
CASES = [
    (language, entry["question_" + language], entry["answer_" + language])
    for entry in BANK
    for language in ("et", "en", "ru")
]


@pytest.mark.parametrize("language,question,answer", CASES)
def test_published_unsupported_answer_uses_real_restaurant_http_without_model(
    client, language, question, answer
):
    session = start(client, "et")["session_id"]
    response = client.post(
        "/api/turn", headers=AUTH, json={"session_id": session, "text": question}
    )
    assert response.status_code == 200
    assert response.json()["language"] == language
    assert response.json()["reply"] == answer
    state = client.app.state.demo_sessions.sessions[session].tools
    assert not state.holds and not state.bookings


@pytest.mark.parametrize("language,question,answer", CASES)
def test_restaurant_answer_cannot_authorize_an_existing_recap(
    make_state, language, question, answer
):
    async def run():
        state = make_state(language)
        proposal = await prepare(state)
        assert state.mark_recap_delivered(proposal["hold_id"])
        state.observe_user_text(question)
        assert not state.pending and not state.bookings
        assert trusted_booking_response(state) == {"content": answer}
        assert (
            await state.dispatch(
                "confirm_slot_booking", {"hold_id": proposal["hold_id"]}
            )
        )["error"] == "consent_required"

    asyncio.run(run())


def test_restaurant_unknown_write_takes_priority_over_static_phone_answers(make_state):
    state = make_state("en")
    state.mutation_uncertain = True
    state.observe_user_text("Can I order takeaway?")
    assert trusted_booking_response(state) == {"content": COPY["en"]["unknown"]}


@pytest.mark.parametrize(
    "language,text",
    [
        (
            "et",
            "Kas saate mu allergia broneeringule kirja panna? Broneeri laud homme kell 14:00 neljale.",
        ),
        (
            "en",
            "Can you record an allergy note? Book a table tomorrow at 14:00 for four.",
        ),
        (
            "ru",
            "Можете записать мою аллергию в бронирование? Забронируйте столик завтра в 14:00 на четверых.",
        ),
    ],
)
def test_mixed_restaurant_answer_and_booking_is_not_a_static_shortcut(
    make_state, language, text
):
    state = make_state(language)
    state.observe_user_text(text, language=language)
    assert not state.faq_entries
    response = trusted_booking_response(state)
    assert response["name"] == "plan_restaurant_reservation"
    assert response["arguments"]["party_size"] == 4
    assert response["arguments"]["start_time"] == "14:00"


def test_mixed_request_prepares_the_requested_table_without_confirming(client):
    session = start(client, "en")["session_id"]
    response = client.post(
        "/api/turn",
        headers=AUTH,
        json={
            "session_id": session,
            "text": "Can you record an allergy note? Book a table tomorrow at 14:00 for four.",
            "language": "en",
        },
    )
    assert response.status_code == 200 and response.json()["recap_delivery_id"]
    state = client.app.state.demo_sessions.sessions[session].tools
    assert state.pending["recap"]["party_size"] == 4
    assert state.pending["recap"]["start"].endswith("14:00:00")
    assert len(state.holds) == 1 and not state.bookings


@pytest.mark.parametrize(
    "language,repeat",
    [
        ("et", "Palun korda."),
        ("en", "Please repeat that."),
        ("ru", "Повторите, пожалуйста."),
    ],
)
def test_combined_restaurant_faq_repeat_preserves_caller_question_order(
    make_state, language, repeat
):
    state = make_state(language)
    state.observe_user_text(
        BANK[1]["question_" + language] + " " + BANK[0]["question_" + language],
        language=language,
    )
    first = state.guard_reply("untrusted", [])
    assert first == BANK[1]["answer_" + language] + " " + BANK[0]["answer_" + language]
    state.observe_user_text(repeat, language=language)
    assert state.guard_reply("untrusted", []) == first
