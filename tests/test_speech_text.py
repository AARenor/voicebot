"""Clock range pronunciation is applied only at the speech provider boundary."""

import xml.etree.ElementTree as ET

import httpx
import pytest

from app.providers.azure_tts import AzureTtsClient, ssml
from app.providers.speech_text import normalize_estonian_speech


@pytest.mark.parametrize("text, expected", [
    ("9-17", "9 kuni kell 17"),
    ("9–17.", "9 kuni kell 17."),
    ("Avatud 9 — 17.", "Avatud 9 kuni kell 17."),
    ("Tööajad: esmaspäev 09:00–17:00.", "Tööajad: esmaspäev 9 kuni kell 17."),
    ("Kell 09:00-17:00", "Kell 9 kuni kell 17"),
    ("09:30 – 17:45", "9:30 kuni kell 17:45"),
    ("00:00–23:59", "0 kuni kell 23:59"),
    ("Tööajad 9–17, paus 12:00–13:00.", "Tööajad 9 kuni kell 17, paus 12 kuni kell 13."),
    ("Kuupäev 2026-10-03, kell 09:00–10:30.", "Kuupäev 2026-10-03, kell 9 kuni kell 10:30."),
])
def test_estonian_clock_ranges_are_natural_and_keep_minutes(text, expected):
    assert normalize_estonian_speech(text) == expected
    assert normalize_estonian_speech(expected) == expected


@pytest.mark.parametrize("text", [
    "Kuupäev 2026-10-03.",
    "Telefon +372 5900-1700.",
    "Hind 9-17 eurot.",
    "Avatud pakkumised hinnaga 9–17 EUR.",
    "Temperatuur 9–17 kraadi.",
    "Osaleb 9–17 külalist.",
    "Toakood A9-17.",
    "09:80–17:00",
    "09:00–17:90",
    "25:00–27:00",
    "Avatud 9.5–17.5.",
])
def test_dates_identifiers_other_units_and_invalid_times_are_unchanged(text):
    assert normalize_estonian_speech(text) == text


def test_other_speech_languages_are_unchanged():
    assert normalize_estonian_speech("Open 09:00–17:00", "en-US") == "Open 09:00–17:00"


def test_ssml_normalizes_estonian_hours_then_escapes_markup():
    original = "<Demo & Spa> tööajad: 09:00–17:00."
    rendered = ssml(original, "et-EE-AnuNeural", "et-EE")
    root = ET.fromstring(rendered)
    assert "".join(root.itertext()) == "<Demo & Spa> tööajad: 9 kuni kell 17."
    assert original == "<Demo & Spa> tööajad: 09:00–17:00."
    assert "&lt;Demo &amp; Spa&gt;" in rendered


def test_azure_sends_natural_hours_without_changing_display_text_on_retry():
    bodies = []

    def handler(request):
        if "issueToken" in str(request.url):
            return httpx.Response(200, text="fixture-token")
        bodies.append(request.content.decode("utf-8"))
        return httpx.Response(401 if len(bodies) == 1 else 200, content=b"AUDIO")

    client = AzureTtsClient(
        "fixture", "northeurope", "et-EE-AnuNeural", "et-EE",
        transport=httpx.MockTransport(handler),
    )
    display_text = "Esmaspäev: 09:00–17:00, paus 12:30–13:00."
    try:
        assert client.synthesize(display_text) == b"AUDIO"
    finally:
        client.close()
    assert len(bodies) == 2 and bodies[0] == bodies[1]
    assert "9 kuni kell 17, paus 12:30 kuni kell 13" in bodies[0]
    assert display_text == "Esmaspäev: 09:00–17:00, paus 12:30–13:00."
