"""Published Russian speech must coexist with the repair's SSML validation."""

import httpx
import pytest
from xml.etree import ElementTree

from app.providers.azure_tts import AzureTtsClient


@pytest.mark.parametrize("direct", [True, False], ids=["direct", "language-view"])
def test_published_russian_voice_produces_matching_safe_ssml(direct):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(
            200, text="fixture" if request.url.path.endswith("issueToken") else "audio"
        )

    speaker = AzureTtsClient(
        "fixture",
        "fixture",
        "ru-RU-SvetlanaNeural" if direct else "et-EE-AnuNeural",
        "ru-RU" if direct else "et-EE",
        transport=httpx.MockTransport(respond),
        languages={} if direct else {"ru": ("ru-RU-SvetlanaNeural", "ru-RU")},
    )
    try:
        selected = speaker if direct else speaker.for_language("ru")
        assert selected.synthesize("Здравствуйте!") == b"audio"
    finally:
        speaker.close()
    assert len(requests) == 2
    parsed = ElementTree.fromstring(requests[-1].content)
    assert parsed.attrib["{http://www.w3.org/XML/1998/namespace}lang"] == "ru-RU"
    assert (
        parsed.find("{http://www.w3.org/2001/10/synthesis}voice").attrib["name"]
        == "ru-RU-SvetlanaNeural"
    )


def test_russian_voice_cannot_inject_ssml_before_provider_access():
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, text="fixture")

    with pytest.raises(ValueError):
        AzureTtsClient(
            "fixture",
            "fixture",
            "ru-RU-SvetlanaNeural'><break/>",
            "ru-RU",
            transport=httpx.MockTransport(respond),
        )
    assert requests == []
