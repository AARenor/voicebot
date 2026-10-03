"""Supported HTTP input and Azure locale validation; no real provider requests."""

from unittest.mock import patch
from xml.etree import ElementTree

import httpx
import pytest

from app.providers.azure_tts import AzureTtsClient
from app.server import build_stack
from tests.test_product_demo import client as client  # noqa: PLC0414
from tests.test_product_demo import send, start


@pytest.mark.parametrize("language", ["de", "fi", "ET", "et-EE", None, [], True])
def test_unsupported_http_language_fails_before_observation_or_providers(
    client, language
):
    session_id = start(client)
    spoken_before = list(client.app.state.stack["tts"].spoken)
    session = client.app.state.demo_sessions.sessions[session_id]
    response = send(client, session_id, "Soovin spaahooldust.", language=language)
    assert response.status_code == 400, response.text
    assert response.json() == {"detail": "language_not_supported"}
    assert response.headers["Cache-Control"] == "no-store"
    assert session.turn_count == 0 and session.tools._turn_serial == 0
    assert not client.app.state.stack["llm_primary"].messages
    assert client.app.state.stack["tts"].spoken == spoken_before


@pytest.mark.parametrize(
    "voice,lang",
    [
        ("en-US-JennyNeural", "et-EE"),
        ("ru-RU-SvetlanaNeural", "ru-EE"),
        ("et-EE-AnuNeural", "en-US"),
        ("et-EE-AnuNeural", "et"),
        ("", "et-EE"),
        (None, "et-EE"),
        ("et-EE-AnuNeural", None),
        ("et-EE-AnuNeural'><break/>", "et-EE"),
    ],
)
def test_http_azure_rejects_unsupported_or_unsafe_locale_before_provider_requests(
    voice, lang
):
    requests = []
    transport = httpx.MockTransport(lambda request: requests.append(request))
    with pytest.raises(ValueError, match="supported speech voice required"):
        AzureTtsClient("fixture", "fixture", voice, lang, transport=transport)
    assert requests == []


@pytest.mark.parametrize("voice", [None, " et-EE-KertNeural "])
def test_http_stack_preserves_anu_default_and_sends_validated_et_ssml(voice):
    requests = []

    def provider(request):
        requests.append(request)
        return httpx.Response(
            200, text="fixture" if request.url.path.endswith("issueToken") else "audio"
        )

    real_client = httpx.Client

    def local_client(**kwargs):
        return real_client(**{**kwargs, "transport": httpx.MockTransport(provider)})

    env = {"AZURE_SPEECH_KEY": "fixture", "AZURE_REGION": "fixture"}
    if voice is not None:
        env.update(AZURE_VOICE=voice, AZURE_LANG=" et-EE ")
    with patch.dict("os.environ", env, clear=True), patch("httpx.Client", local_client):
        stack = build_stack()
    try:
        assert stack["tts"].synthesize("Tere!") == b"audio"
    finally:
        stack["tts"].close()
    assert len(requests) == 2
    ssml = requests[-1].content.decode()
    parsed = ElementTree.fromstring(ssml)
    assert parsed.attrib["{http://www.w3.org/XML/1998/namespace}lang"] == "et-EE"
    assert parsed.find("{http://www.w3.org/2001/10/synthesis}voice").attrib["name"] == (
        voice.strip() if voice else "et-EE-AnuNeural"
    )


def test_http_startup_rejects_an_unsupported_azure_configuration():
    env = {
        "AZURE_SPEECH_KEY": "fixture",
        "AZURE_REGION": "fixture",
        "AZURE_VOICE": "en-US-JennyNeural",
        "AZURE_LANG": "en-US",
    }
    with (
        patch.dict("os.environ", env, clear=True),
        pytest.raises(ValueError, match="invalid telephone speech configuration"),
    ):
        build_stack()
