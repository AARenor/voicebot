"""Browser audio fidelity must not change language or canonical speech."""

import xml.etree.ElementTree as ET

import httpx
import pytest

from app.providers.azure_tts import AzureTtsClient


@pytest.mark.parametrize(
    "language,voice,locale",
    [("et", "et-EE-AnuNeural", "et-EE"), ("en", "en-US-JennyNeural", "en-US")],
)
def test_language_speaker_requests_high_fidelity_mp3_without_changing_speech(
    language, voice, locale
):
    requests = []

    def respond(request):
        if request.url.path.endswith("issueToken"):
            return httpx.Response(200, text="fixture-bearer")
        requests.append(request)
        return httpx.Response(200, content=b"fixture-audio")

    client = AzureTtsClient(
        "fixture",
        "fixture",
        "et-EE-AnuNeural",
        "et-EE",
        transport=httpx.MockTransport(respond),
        languages={
            "et": ("et-EE-AnuNeural", "et-EE"),
            "en": ("en-US-JennyNeural", "en-US"),
        },
    )
    text = "Mari & Jüri <demo>, 2026-10-10. 129.50 EUR."
    try:
        assert client.for_language(language).synthesize(text) == b"fixture-audio"
        assert len(requests) == 1
        assert (
            requests[0].headers["X-Microsoft-OutputFormat"]
            == "audio-48khz-96kbitrate-mono-mp3"
        )
        root = ET.fromstring(requests[0].content)
        assert root.find(".//{*}voice").attrib["name"] == voice
        assert root.attrib["{http://www.w3.org/XML/1998/namespace}lang"] == locale
        assert "".join(root.itertext()) == text
    finally:
        client.close()
