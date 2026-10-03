"""Work plans and lunch breaks select verified spa hours, never booking intent."""

import pytest

from app.conversation import Conversation, read_focus, spa_hours_focus


@pytest.mark.parametrize("text", [
    "Mis kell spaateenindaja töötab ja millal on tema lõunapaus? Palun kontrolli tööplaani.",
    "Millal spaa terapeut töötab?",
    "Mis kell massöör alustab ja lõpetab?",
    "Palun näita spaateenindaja tööplaani.",
    "Kas spaaterapeudil on lõunapaus?",
    "Millal teenindaja pausid on?",
    "Palun kontrolli spaa töögraafikut.",
    "Mis on spaateenindaja tööajad?",
    "What is the spa therapist's schedule?",
    "When does the spa provider work and take a lunch break?",
    "Please check the spa work plan.",
    "What time does the therapist start work?",
    "Can you show the spa timetable?",
])
def test_spa_schedule_questions_have_hours_focus(text):
    assert spa_hours_focus(text)
    assert read_focus(text) == "hours"
    conversation = Conversation()
    conversation.observe(text, "en" if text[0].isascii() and text.startswith(("What", "When", "Please", "Can")) else "et")
    assert conversation.focus == "hours" and conversation.intent is None


@pytest.mark.parametrize("text", [
    "Mis kell hotelli teenindaja töötab?",
    "What time does the hotel receptionist work?",
    "Mis kell saab hotellitoast lahkuda?",
    "Kas spaaterapeut saab homme kell 10 broneerida?",
    "Palun näita spaa tööaegu, tahaks brooneerida.",
    "Palun kinnita spaabroneering ja ütle tööajad.",
    "Please book the spa at ten and show the schedule.",
    "Please cancel my spa booking during the lunch break.",
    "Show the spa schedule and book a room.",
    "Mis teenustega spaaterapeut töötab?",
    "What services does the spa provider work with?",
    "See ei tööta.",
    "Spa does not work.",
    "Tere!",
    "Spa tööplaan",
    None,
    "spa " + "tööplaan " * 300,
])
def test_unrelated_mixed_mutations_and_unbounded_text_do_not_route_to_spa_hours(text):
    assert not spa_hours_focus(text)


@pytest.mark.parametrize("text, focus", [
    ("Mis spaateenuseid pakute?", "services"),
    ("What spa treatments are available?", "services"),
    ("Millised on tööajad?", "hours"),
    ("What are the opening hours?", "hours"),
    ("Milliseid toatüüpe pakute?", None),
    ("Tere!", None),
])
def test_existing_read_focus_is_preserved(text, focus):
    assert read_focus(text) == focus
