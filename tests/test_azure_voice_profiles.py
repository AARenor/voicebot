"""Real Azure request routing with synthetic HTTP/audio; no live providers."""

import base64
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from xml.etree import ElementTree as ET

import httpx
import pytest

from app.providers.azure_tts import AzureTtsClient
from app.languages import CONSENT
from app.providers.errors import ProviderError
from app.providers.demo_voices import DemoVoices
from app.providers.speech_delivery import SpeechDelivery
from tests.test_restaurant_http import AUTH, client as client

SSML = "{http://www.w3.org/2001/10/synthesis}"
MSTTS = "{http://www.w3.org/2001/mstts}"
MP3 = (Path(__file__).parent / "fixtures/speech-tone.mp3").read_bytes()


@pytest.fixture
def azure(client):
    requests = []

    def respond(request):
        if request.url.path.endswith("issueToken"):
            return httpx.Response(200, text="fixture-token")
        requests.append(ET.fromstring(request.content))
        return httpx.Response(200, content=MP3)

    speaker = AzureTtsClient(
        "fixture", "fixture", "et-EE-AnuNeural", "et-EE",
        languages={
            "et": ("et-EE-AnuNeural", "et-EE"),
            "en": ("en-US-JennyNeural", "en-US"),
            "ru": ("ru-RU-SvetlanaNeural", "ru-RU"),
        },
        transport=httpx.MockTransport(respond),
    )
    client.app.state.stack.update(tts=speaker, voices=DemoVoices.from_env({}))
    yield speaker, requests
    speaker.close()


def voice(document):
    return document.find(SSML + "voice").get("name")


@pytest.mark.parametrize("language,expected", [
    ("et", "et-EE-KertNeural"),
    ("en", "en-US-GuyNeural"),
    ("ru", "ru-RU-DmitryNeural"),
])
def test_male_voice_owns_greeting_and_turn_in_each_language(client, azure, language, expected):
    speaker, requests = azure
    started = client.post("/api/demo/session", headers=AUTH, json={
        "language": language, "voice": "azure-male",
    })
    assert started.status_code == 200, started.text
    data = started.json()
    assert data["voice"]["effective"] == "azure-male"
    assert base64.b64decode(data["audio_b64"]) == MP3
    reply = client.post("/api/turn", headers=AUTH, json={
        "session_id": data["session_id"], "voice": "azure-calm",
        "language": language,
        "text": {"et": "Milline on menüü?", "en": "What is on the menu?", "ru": "Что есть в меню?"}[language],
    })
    assert reply.status_code == 200, reply.text
    assert reply.json()["voice"]["effective"] == "azure-male"
    assert all(voice(document) == expected for document in requests)
    assert client.app.state.stack["tts"] is speaker
    assert speaker._voice == "et-EE-AnuNeural"


def test_profiles_are_available_without_additional_provider_credentials(client, azure):
    catalog = client.get("/api/demo/voices", headers=AUTH).json()["voices"]
    available = {row["id"] for row in catalog if row["available"]}
    assert available == {"azure", "azure-male", "azure-calm"}
    assert all(row["configured"] for row in catalog if row["id"] in available)


def test_parallel_profiles_keep_their_voice_and_pacing_isolated(azure):
    speaker, requests = azure
    registry = DemoVoices.from_env({})
    profiles = ["azure-male", "azure-calm", "azure"] * 3

    def synthesize(profile):
        return registry.choose(profile, azure=speaker).for_language("et").synthesize(profile)

    with ThreadPoolExecutor(max_workers=3) as pool:
        assert list(pool.map(synthesize, profiles)) == [MP3] * len(profiles)
    for document in requests:
        text = "".join(document.itertext())
        assert voice(document) == ("et-EE-KertNeural" if text == "azure-male" else "et-EE-AnuNeural")
        assert document.find(".//" + SSML + "prosody").get("rate") == (
            "0.94" if text == "azure-calm" else "0.98"
        )
        assert document.find(".//" + MSTTS + "silence").get("value") == (
            "240ms" if text == "azure-calm" else "180ms"
        )
    assert speaker._delivery == SpeechDelivery()


@pytest.mark.parametrize("profile", ["azure-male", "azure-calm"])
def test_profile_streams_native_mp3_and_preserves_canonical_recap(azure, profile):
    speaker, requests = azure
    selected = DemoVoices.from_env({}).choose(profile, azure=speaker).for_language("et")
    recap = "2026-11-02 kell 19:30. " + CONSENT["et"]
    assert b"".join(selected.stream(recap)) == MP3
    document = requests[-1]
    assert "".join(document.itertext()) == recap
    assert document.find(".//" + MSTTS + "silence") is None
    assert document.find(".//" + SSML + "prosody").get("rate") == (
        "0.91" if profile == "azure-calm" else "0.94"
    )


def test_rejected_male_voice_falls_back_before_audio_and_reports_actual_voice(azure):
    speaker, requests = azure
    speaker._http.close()

    def respond(request):
        if request.url.path.endswith("issueToken"):
            return httpx.Response(200, text="fixture-token")
        document = ET.fromstring(request.content)
        requests.append(document)
        return httpx.Response(400 if voice(document) == "et-EE-KertNeural" else 200, content=MP3)

    speaker._http = httpx.Client(transport=httpx.MockTransport(respond))
    selected = DemoVoices.from_env({}).choose("azure-male", azure=speaker).for_language("et")
    assert b"".join(selected.stream("Tere!")) == MP3
    assert [voice(document) for document in requests] == ["et-EE-KertNeural", "et-EE-AnuNeural"]
    assert selected.voice_info["effective"] == "azure"
    assert selected.voice_info["reason"] == "provider_failure"


def test_partial_male_audio_failure_never_switches_voice(azure):
    speaker, requests = azure
    speaker._http.close()

    class PartialAudio(httpx.SyncByteStream):
        def __iter__(self):
            yield MP3
            raise httpx.ReadError("fixture interrupted")

    def respond(request):
        if request.url.path.endswith("issueToken"):
            return httpx.Response(200, text="fixture-token")
        requests.append(ET.fromstring(request.content))
        return httpx.Response(200, stream=PartialAudio())

    speaker._http = httpx.Client(transport=httpx.MockTransport(respond))
    selected = DemoVoices.from_env({}).choose("azure-male", azure=speaker).for_language("et")
    stream = selected.stream("Tere!")
    assert next(stream)
    with pytest.raises(ProviderError):
        list(stream)
    assert len(requests) == 1
    assert selected.voice_info["effective"] == "azure-male"


def test_neutral_delivery_disables_calm_style_and_pause_adjustments(azure):
    speaker, requests = azure
    speaker._delivery = SpeechDelivery(mode="neutral")
    selected = DemoVoices.from_env({}).choose("azure-calm", azure=speaker).for_language("et")
    assert selected.synthesize("Tere! Mis kell sobiks?") == MP3
    assert requests[-1].find(".//" + SSML + "prosody") is None
    assert requests[-1].find(".//" + MSTTS + "silence") is None


@pytest.mark.parametrize("language", ["et", "en", "ru", "auto"])
def test_audition_is_fixed_text_without_model_session_or_booking(client, azure, language):
    response = client.post("/api/demo/voices/preview", headers=AUTH, json={
        "language": language, "voice": "azure-male",
    })
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["language"] == ("et" if language == "auto" else language)
    assert data["voice"]["effective"] == "azure-male"
    assert base64.b64decode(data["audio_b64"]) == MP3
    assert response.headers["cache-control"] == "no-store"
    assert not client.app.state.demo_sessions.sessions
    assert "recap_delivery_id" not in data


@pytest.mark.parametrize("body,code", [
    ({"voice": "unknown"}, 422),
    ({"voice": "azure-male", "language": "fi"}, 400),
    ({"voice": "azure-male", "text": "Jah, kinnitan."}, 400),
    ({"voice": ["azure-male"]}, 422),
])
def test_audition_rejects_invalid_inputs_before_synthesis(client, azure, body, code):
    assert client.post("/api/demo/voices/preview", headers=AUTH, json=body).status_code == code
    assert not azure[1]


def test_audition_authenticates_before_reading_or_synthesis(client, azure):
    assert client.post("/api/demo/voices/preview", content=b"malformed").status_code == 403
    assert not azure[1]


def test_audition_provider_failure_is_closed_and_has_no_session(client, azure):
    azure[0]._http.close()
    response = client.post("/api/demo/voices/preview", headers=AUTH, json={"voice": "azure-male"})
    assert response.status_code == 503
    assert response.json() == {"detail": "voice_preview_unavailable"}
    assert not client.app.state.demo_sessions.sessions


@pytest.mark.parametrize("setting", ["0", "501", "180.5", "not-a-number"])
def test_invalid_sentence_pause_configuration_is_rejected(setting):
    with pytest.raises(ValueError, match="invalid speech delivery configuration"):
        SpeechDelivery.from_env({"VOICEBOT_SENTENCE_PAUSE_MS": setting})
