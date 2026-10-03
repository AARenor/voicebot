"""Estonian delivery preserves booking facts and uses reviewed restaurant replies."""

import xml.etree.ElementTree as ET

import pytest

from app.conversation import QUESTIONS, approved_dialogue
from app.languages import ENGLISH_INVITATION
from app.providers.azure_tts import ssml
from app.providers.speech_delivery import SpeechDelivery, speech_markup
from app.telephone import CallTools
from tests.test_product_demo import client, send, start


SSML = "{http://www.w3.org/2001/10/synthesis}"
MSTTS = "{http://www.w3.org/2001/mstts}"


class NoBookingTools:
    def available_tools(self):
        return []


def test_initial_greeting_and_automatic_language_invitation_remain_approved():
    state = CallTools(NoBookingTools(), business="restaurant")
    assert state.guard_reply(state.greeting, []) == state.greeting
    assert state.guard_reply(ENGLISH_INVITATION, []) == ENGLISH_INVITATION


@pytest.mark.parametrize("text,alias", [
    ("Kell 9.", "kell üheksa"),
    ("kell 9:05", "kell üheksa viis"),
    ("kell 09:30 kuni kell 17:45", "kell üheksa kolmkümmend kuni kell seitseteist nelikümmend viis"),
    ("Avatud 09:30–17:45.", "kell üheksa kolmkümmend kuni kell seitseteist nelikümmend viis"),
])
def test_single_digit_times_and_ranges_receive_estonian_pronunciation(text, alias):
    root = ET.fromstring(ssml(text, "et-EE-AnuNeural", "et-EE"))
    assert [node.get("alias") for node in root.iter(SSML + "sub")] == [alias]


@pytest.mark.parametrize("text", [
    "kell 24:00", "kell 9:60", "Toakood A9-17.",
    "Broneering 9017, hind 9–17 eurot.", "Kuupäev 2026-02-30.",
])
def test_invalid_times_dates_prices_and_identifiers_are_not_reinterpreted(text):
    root = ET.fromstring(ssml(text, "et-EE-AnuNeural", "et-EE"))
    assert not list(root.iter(SSML + "sub"))
    assert "".join(root.itertext()) == text


def test_invalid_range_start_is_not_partially_pronounced_as_midnight():
    text = "kell 24:00 kuni kell 17:00"
    root = ET.fromstring(ssml(text, "et-EE-AnuNeural", "et-EE"))
    assert [node.get("alias") for node in root.iter(SSML + "sub")] == ["kell seitseteist"]
    assert "".join(root.itertext()) == text


@pytest.mark.parametrize("recap,tail,sentence", [(False, "120ms", "200ms"), (True, "240ms", "320ms")])
def test_native_and_http_markup_share_bounded_pauses(recap, tail, sentence):
    text = "Tere! Kuidas saan aidata?"
    body = speech_markup(text, "et-EE-AnuNeural", "et-EE", SpeechDelivery(), recap=recap)
    root = ET.fromstring(f'<voice xmlns:mstts="http://www.w3.org/2001/mstts">{body}</voice>')
    assert {node.get("type"): node.get("value") for node in root.iter(MSTTS + "silence")} == {
        "Leading-exact": "0ms", "Tailing-exact": tail, "Sentenceboundary-exact": sentence,
    }
    assert "".join(root.itertext()) == text
    if not recap:
        http = ET.fromstring(ssml(text, "et-EE-AnuNeural", "et-EE"))
        assert [node.attrib for node in http.iter(MSTTS + "silence")] == [
            node.attrib for node in root.iter(MSTTS + "silence")
        ]


def test_neutral_mode_and_other_languages_do_not_get_estonian_pause_settings():
    for voice, locale, delivery in [
        ("et-EE-AnuNeural", "et-EE", SpeechDelivery(mode="neutral")),
        ("en-US-JennyNeural", "en-US", SpeechDelivery()),
        ("ru-RU-SvetlanaNeural", "ru-RU", SpeechDelivery()),
    ]:
        root = ET.fromstring(ssml("Hello & welcome!", voice, locale, delivery))
        assert not list(root.iter(MSTTS + "silence"))
        assert "".join(root.itertext()) == "Hello & welcome!"


@pytest.mark.parametrize("question", ["Kas sa oled inimene?", "Kas saan inimesega rääkida?", "Aitäh!"])
def test_restaurant_social_answers_do_not_offer_legacy_bookings(question):
    state = CallTools(NoBookingTools(), business="restaurant")
    state.observe_user_text(question, language="et")
    reply = state.direct_reply
    assert reply in approved_dialogue("et", business="restaurant")
    assert "hotell" not in reply and "spaa" not in reply and "testbroneering" not in reply
    assert QUESTIONS["et"]["booking_kind"][0] not in approved_dialogue("et", business="restaurant")


@pytest.mark.parametrize("question,expected", [
    ("Millal restoran avatud on?", "Restorani lahtiolekuaegu pole selles demos veel määratud."),
    ("Kas saan siin päris lauda broneerida?", "Selles demos ei saa veel lauda broneerida. Restorani lauabroneeringute süsteem pole seadistatud."),
])
def test_common_restaurant_questions_use_identical_reviewed_text_and_audio(client, question, expected):
    session = start(client)
    response = send(client, session, question, language="et")
    assert response.status_code == 200
    data = response.json()
    assert data["reply"] == expected
    assert client.app.state.stack["tts"].spoken[-1] == expected
    assert data["timings_ms"]["llm"] == 0
    assert data["booking_changes"] == []
    assert client.app.state.stack["llm_primary"].messages == []
