"""Bounded preparation deadlines and validated language-specific HTTP speech."""

import httpx
import pytest
from xml.etree import ElementTree

from app.providers.azure_tts import AzureTtsClient
from tests.test_product_demo import BookingLlm, install_backend, send, start
from tests.test_product_demo import client as client


def test_recap_deadline_is_the_preparation_deadline_not_the_session(client, tmp_path):
    day, _, _ = install_backend(client, tmp_path)
    client.app.state.stack["llm_primary"] = BookingLlm(day)
    result = send(client, start(client), "Soovin testbroneeringut").json()
    assert result["recap_delivery_id"]
    assert 0 < result["recap_expires_in_s"] <= 60 < result["expires_in_s"]


def test_valid_english_voice_reaches_actual_ssml():
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(
            200, text="fixture" if request.url.path.endswith("issueToken") else "audio"
        )

    speaker = AzureTtsClient(
        "fixture",
        "fixture",
        "en-US-JennyNeural",
        "en-US",
        transport=httpx.MockTransport(respond),
    )
    try:
        assert speaker.synthesize("Hello!") == b"audio"
    finally:
        speaker.close()
    assert len(requests) == 2
    parsed = ElementTree.fromstring(requests[-1].content)
    assert parsed.attrib["{http://www.w3.org/XML/1998/namespace}lang"] == "en-US"
    assert (
        parsed.find("{http://www.w3.org/2001/10/synthesis}voice").attrib["name"]
        == "en-US-JennyNeural"
    )


@pytest.mark.parametrize("kind", ["mapping", "override", "unsupported_language"])
def test_unsafe_or_unsupported_voice_never_contacts_a_provider(kind):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, text="fixture")

    options = (
        {"languages": {"en": ("en-US-JennyNeural'><break/>", "en-US")}}
        if kind == "mapping"
        else {}
    )
    with pytest.raises(ValueError):
        with_speech = AzureTtsClient(
            "fixture",
            "fixture",
            "et-EE-AnuNeural",
            "et-EE",
            transport=httpx.MockTransport(respond),
            **options,
        )
        try:
            if kind == "override":
                with_speech.synthesize(
                    "Hello!", voice="en-US-JennyNeural'><break/>", lang="en-US"
                )
            elif kind == "unsupported_language":
                with_speech.for_language("de")
        finally:
            with_speech.close()
    assert requests == []
