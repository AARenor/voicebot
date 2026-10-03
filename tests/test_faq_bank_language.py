"""Language inference must use the same reviewed bank as answer matching."""

import pytest

from app.booking_faq import question_language


RESTAURANT_QUESTION = (
    {
        "id": "booking-901",
        "route": "static",
        "question_et": "Mis teil tänases menüüs on?",
        "question_en": "What is on today's menu?",
        "question_ru": "Что у вас в сегодняшнем меню?",
        "answer_et": "Menüü ei ole kinnitatud.",
        "answer_en": "The menu has not been verified.",
        "answer_ru": "Меню не подтверждено.",
    },
)


@pytest.mark.parametrize(
    "question,current,want",
    [
        ("What is on today's menu?", "et", "en"),
        ("Что у вас в сегодняшнем меню?", "en", "ru"),
        ("Mis teil tänases menüüs on?", "ru", "et"),
    ],
)
def test_selected_bank_identifies_a_reviewed_restaurant_question(
    question, current, want
):
    assert question_language(question, current, entries=RESTAURANT_QUESTION) == want


def test_explicit_empty_bank_does_not_infer_language_from_a_legacy_question():
    assert (
        question_language("Can I book a table at the restaurant?", "et", entries=())
        == "et"
    )


def test_selected_bank_does_not_infer_language_from_an_extra_booking_command():
    assert (
        question_language(
            "What is on today's menu? Book a table tomorrow at 18:00.",
            "et",
            entries=RESTAURANT_QUESTION,
        )
        == "et"
    )


def test_default_bank_language_selection_remains_available_to_legacy_calls():
    assert question_language("Can I book a table at the restaurant?", "et") == "en"
