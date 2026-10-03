"""Read-only restaurant questions retain preferences, never booking authority."""

import asyncio

import pytest

from app.booking_response import trusted_booking_response
from app.conversation import Conversation
from app.demo import load_demo_data
from app.telephone import CallTools
from tests.test_table_policy import DAY, REQUEST, prepare_table, table_state
from tests.test_table_http import AUTH, client


REQUESTS = {
    "et": f"Broneeri laud {DAY} 4 inimesele.",
    "en": f"Book a table on {DAY} for four.",
    "ru": f"Хочу забронировать столик на {DAY} для четверых.",
}
QUESTIONS = [
    ("et", "Millal restoran avatud on?", "hours"),
    ("en", "What time does the restaurant close?", "hours"),
    ("en", "What are the restaurant opening hours?", "hours"),
    ("ru", "Какие часы работы ресторана?", "hours"),
    ("ru", "Когда открыт демонстрационный ресторан?", "hours"),
    ("et", "Mis on menüüs?", "menu"),
    ("en", "What's on the menu?", "menu"),
    ("ru", "Что в меню?", "menu"),
    ("et", "Kas salat sobib gluteenivaba dieediga?", "dietary"),
    ("et", "Kas menüüs on gluteenivabu roogi?", "dietary"),
    ("en", "Is the salad safe for a peanut allergy?", "dietary"),
    ("en", "Are there gluten-free dishes on the menu?", "dietary"),
    ("ru", "Есть ли безглютеновые блюда?", "dietary"),
]


@pytest.mark.parametrize("language,question,focus", QUESTIONS)
def test_restaurant_read_interlude_keeps_date_and_true_diner_count(
    language, question, focus
):
    state, backend = table_state(language=language)
    state.observe_user_text(REQUESTS[language], language=language)
    assert state.booking_inquiry == {"kind": "table", "date": DAY, "party_size": 4}
    state.observe_user_text(question, language=language)
    assert state.conversation.focus == focus
    assert trusted_booking_response(state) == {
        "name": "get_table_catalogue",
        "arguments": {},
    }
    assert state.booking_inquiry == {"kind": "table", "date": DAY, "party_size": 4}
    assert not backend.calls and state.pending is None
    state.observe_user_text("18:30", language=language)
    assert state.booking_inquiry == {"kind": "table", **REQUEST}


@pytest.mark.parametrize("language", ["et", "en", "ru"])
def test_read_interlude_cannot_keep_delivered_recap_authorization(language):
    async def run():
        state, backend = table_state(language=language)
        await prepare_table(state)
        hold_id = state.pending["hold_id"]
        assert state.mark_recap_delivered(hold_id)
        question = next(
            text
            for lang, text, focus in QUESTIONS
            if lang == language and focus == "hours"
        )
        state.observe_user_text(question, language=language)
        assert state.pending is None and state.cancel_approval is None
        assert await state.dispatch("confirm_table_booking", {"hold_id": hold_id}) == {
            "error": "consent_required"
        }
        assert not any(name == "confirm" for name, _ in backend.calls)

    asyncio.run(run())


@pytest.mark.parametrize(
    "text",
    [
        "Book another table and show the menu",
        "Cancel my booking; what's on the menu?",
        "Confirm it and tell me the opening hours",
        "Forget the date, what is on the menu?",
        "Ei, näita menüüd",
        "Нет, расскажите о меню",
        "19:30 or show the menu",
        "Show the menu, tomorrow instead",
        "Show the menu but for two instead",
        "Soovin homme lauda ja menüüd",
        "Actually we are five; what is on the menu?",
        "Show the menu; for five or six people.",
        "We will come next Friday; show the menu.",
        "Meid on nüüd viis; mis on menüüs?",
        "Нас теперь пятеро; что в меню?",
    ],
)
def test_mixed_or_correcting_read_question_cannot_preserve_old_preferences(text):
    state, _ = table_state(language="en")
    state.observe_user_text(REQUESTS["en"], language="en")
    state.observe_user_text(text, language="en")
    assert state.booking_inquiry is None
    assert trusted_booking_response(state) != {
        "name": "get_table_catalogue",
        "arguments": {},
    }


@pytest.mark.parametrize(
    "language,fragment",
    [
        ("et", "teine kuupäev või kellaaeg"),
        ("en", "another date or time"),
        ("ru", "другую дату или время"),
    ],
)
def test_full_exact_sitting_asks_for_new_time_not_fewer_diners(language, fragment):
    state, backend = table_state(language=language)
    reply = state.guard_reply("", [{"error": "table_unavailable"}])
    assert fragment in reply
    assert state.guard_reply("", [{"error": "booking_unavailable"}]) != reply
    assert not backend.calls


@pytest.mark.parametrize("language", ["et", "en", "ru"])
def test_approved_dietary_and_waitlist_answers_need_no_model_or_booking_action(
    language,
):
    demo = load_demo_data(business="restaurant")
    topics = {entry["question_en"]: entry for entry in demo["faq"]}
    for question in (
        "Is allergy information verified?",
        "Can you add me to a waitlist?",
    ):
        assert question in topics
        entry = topics[question]
        state, backend = table_state(language=language)
        state.observe_user_text(REQUESTS[language], language=language)
        state.observe_user_text(entry["question_" + language], language=language)
        reply = trusted_booking_response(state, allow_actions=False)
        assert reply == {"content": entry["answer_" + language]}
        assert state.booking_inquiry == {"kind": "table", "date": DAY, "party_size": 4}
        assert state.pending is None and not backend.calls


@pytest.mark.parametrize("language,question,focus", QUESTIONS)
def test_failed_read_interlude_is_not_retried_or_presented_as_menu_information(
    language, question, focus
):
    state, backend = table_state(language=language)
    state.observe_user_text(question, language=language)
    state.results.append({"error": "booking_unavailable"})
    response = trusted_booking_response(state, after_tool=True)
    assert response == {"content": state.guard_reply("", state.results)}
    assert not backend.calls and state.pending is None
    assert not any(
        dish in response["content"]
        for dish in ("Green salad", "Roheline salat", "Зелёный салат")
    )


def test_legacy_menu_word_does_not_activate_restaurant_read_routing():
    conversation = Conversation()
    conversation.observe("What's on the menu?", "en")
    assert conversation.focus is None


@pytest.mark.parametrize(
    "language,text",
    [
        ("en", "Actually we are five; what is on the menu?"),
        ("et", "Meid on nüüd viis; mis on menüüs?"),
        ("ru", "Нас теперь пятеро; что в меню?"),
    ],
)
def test_http_mixed_headcount_correction_reaches_planning_without_stale_inquiry(
    client, language, text
):
    session = client.post(
        "/api/demo/session", json={"language": language}, headers=AUTH
    ).json()["session_id"]
    for utterance in (REQUESTS[language], text):
        response = client.post(
            "/api/turn",
            json={"session_id": session, "text": utterance, "language": language},
            headers=AUTH,
        )
        assert response.status_code == 200
    assert client.app.state.stack["llm_primary"].calls == 1
    assert (
        client.app.state.demo_sessions.sessions[session].tools.booking_inquiry is None
    )


@pytest.mark.parametrize("language,question,focus", QUESTIONS)
def test_http_restaurant_read_uses_canonical_catalogue_without_model_or_reservation(
    client, language, question, focus
):
    session = client.post(
        "/api/demo/session", json={"language": language}, headers=AUTH
    ).json()["session_id"]
    response = client.post(
        "/api/turn",
        json={"session_id": session, "text": question, "language": language},
        headers=AUTH,
    )
    assert response.status_code == 200
    reply = response.json()["reply"]
    expected = {
        "menu": {"et": "Roheline salat", "en": "Green salad", "ru": "Зелёный салат"},
        "dietary": {
            "et": "ei ole kinnitatud",
            "en": "are not verified",
            "ru": "не подтверждены",
        },
        "hours": {"et": "12:00–22:00", "en": "12:00–22:00", "ru": "с 12:00 до 22:00"},
    }[focus][language]
    assert expected in reply
    assert client.app.state.stack["llm_primary"].calls == 0
    assert response.json()["booking_ids"] == []
    assert client.app.state.demo_sessions.sessions[session].tools.pending is None
