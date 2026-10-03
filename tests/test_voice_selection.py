"""Session-owned speech routing; every speaker here is an offline fixture."""

import base64
from unittest.mock import patch

import pytest

from tests.test_product_demo import AUTH, SimpleLlm, Speaker, client


def test_bootstrap_installs_optional_registry_without_capturing_default_azure():
    from app.server import build_stack

    with patch.dict("os.environ", {}, clear=True):
        stack = build_stack()
    assert stack.get("voices") is not None, "bootstrap has no optional voice registry"
    azure = Speaker()
    rows = stack["voices"].catalog(azure=azure)
    assert {row["id"] for row in rows} == {"azure", "elevenlabs", "google", "cartesia"}
    assert next(row for row in rows if row["id"] == "azure")["available"]
    assert (
        stack["voices"].choose(azure=azure).for_language("en").synthesize("Hello")
        == b"Hello"
    )
    stack["voices"].close()


class Choice:
    def __init__(self, requested, azure, modern, language="et"):
        self.requested, self.azure, self.modern = requested, azure, modern
        self.language = language

    def for_language(self, language):
        return Choice(self.requested, self.azure, self.modern, language)

    @property
    def voice_info(self):
        fallback = self.requested == "cartesia" and self.language == "et"
        return {
            "requested": self.requested,
            "effective": "azure" if fallback else self.requested,
            "language": self.language,
            "fallback": fallback,
            "reason": "unsupported_language" if fallback else None,
            "streaming": True,
        }

    def synthesize(self, text):
        speaker = self.azure if self.voice_info["effective"] == "azure" else self.modern
        return speaker.synthesize(text)

    def stream(self, text):
        yield self.synthesize(text)


class Registry:
    def __init__(self):
        self.modern = Speaker()
        self.selections = []

    def catalog(self, azure=None):
        return [
            {
                "id": "azure",
                "label": "Azure",
                "languages": ["et", "en", "ru"],
                "configured": azure is not None,
                "available": azure is not None,
                "disabled_reason": None if azure is not None else "not_configured",
                "streaming": True,
            }
        ]

    def choose(self, profile_id="azure", azure=None):
        self.selections.append((profile_id, azure))
        if profile_id == "google":
            raise ValueError("PRIVATE configuration")
        return Choice(profile_id, azure, self.modern)


def test_catalog_is_authenticated_private_and_uses_current_azure(client):
    registry = Registry()
    client.app.state.stack["voices"] = registry
    assert client.get("/api/demo/voices").status_code == 403
    result = client.get("/api/demo/voices", headers=AUTH)
    assert result.status_code == 200
    assert result.headers["Cache-Control"] == "no-store"
    assert result.json() == {
        "voices": [
            {
                "id": "azure",
                "label": "Azure",
                "languages": ["et", "en", "ru"],
                "configured": True,
                "available": True,
                "disabled_reason": None,
                "streaming": True,
            }
        ],
        "endpointing_ms": 650,
    }


@pytest.mark.parametrize("language", ["et", "en", "ru"])
def test_selected_voice_owns_greeting_and_turn_without_global_mutation(
    client, language
):
    registry = Registry()
    azure = client.app.state.stack["tts"]
    client.app.state.stack["voices"] = registry
    started = client.post(
        "/api/demo/session",
        headers=AUTH,
        json={"language": language, "voice": "elevenlabs"},
    )
    assert started.status_code == 200
    data = started.json()
    session = client.app.state.demo_sessions.sessions[data["session_id"]]
    assert session.voice_id == "elevenlabs"
    assert data["voice"]["language"] == language
    assert data["voice"]["effective"] == "elevenlabs"
    assert registry.modern.spoken == [data["greeting"]]
    result = client.post(
        "/api/turn",
        headers=AUTH,
        json={
            "session_id": data["session_id"],
            "text": {"et": "Tere", "en": "Hello", "ru": "Привет"}[language],
            "language": language,
            "voice": "azure",
        },
    )
    assert result.status_code == 200
    reply = result.json()
    assert reply["voice"]["requested"] == "elevenlabs"
    assert registry.modern.spoken[-1] == reply["reply"]
    assert base64.b64decode(reply["audio_b64"]).decode() == reply["reply"]
    assert not azure.spoken and client.app.state.stack["tts"] is azure


def test_detected_language_uses_explicit_azure_fallback_for_cartesia(client):
    registry = Registry()
    client.app.state.stack["voices"] = registry
    started = client.post(
        "/api/demo/session",
        headers=AUTH,
        json={"voice": "cartesia", "language": "auto"},
    )
    assert started.status_code == 200
    assert started.json()["voice"] == Choice("cartesia", None, None).voice_info

    class Stt:
        def transcribe(self, audio, *, language):
            return "Hello!"

    client.app.state.stack["stt"] = Stt()
    result = client.post(
        "/api/turn",
        headers=AUTH,
        json={
            "session_id": started.json()["session_id"],
            "language": "auto",
            "audio_b64": base64.b64encode(b"offline speech").decode(),
        },
    )
    assert result.status_code == 200
    assert result.json()["voice"]["effective"] == "cartesia"
    assert result.json()["voice"]["language"] == "en"
    assert not result.json()["voice"]["fallback"]


@pytest.mark.parametrize(
    "voice,status", [(None, 422), ([], 422), ("unknown", 422), ("google", 503)]
)
def test_invalid_or_unavailable_voice_never_constructs_session_or_runs_provider(
    client, voice, status
):
    registry = Registry()
    client.app.state.stack["voices"] = registry
    result = client.post("/api/demo/session", headers=AUTH, json={"voice": voice})
    assert result.status_code == status
    assert result.headers["Cache-Control"] == "no-store"
    assert "PRIVATE" not in result.text
    assert not client.app.state.demo_sessions.sessions
    assert not registry.modern.spoken and not client.app.state.stack["tts"].spoken
    result = client.post(
        "/api/turn", headers=AUTH, json={"text": "Tere", "voice": voice}
    )
    assert result.status_code == status
    assert not client.app.state.stack["llm_primary"].messages


def test_standalone_voice_and_legacy_stack_keep_json_compatible(client):
    registry = Registry()
    client.app.state.stack["voices"] = registry
    result = client.post(
        "/api/turn",
        headers=AUTH,
        json={"text": "Hello", "language": "en", "voice": "elevenlabs"},
    )
    assert result.status_code == 200
    assert result.json()["voice"]["effective"] == "elevenlabs"
    assert result.json()["audio_b64"] and result.json()["session_id"] is None
    client.app.state.stack.pop("voices")
    result = client.post("/api/turn", headers=AUTH, json={"text": "Tere"})
    assert result.status_code == 200 and result.json()["audio_b64"]
    assert set(result.json()["timings_ms"]) == {"stt", "llm", "tools", "tts", "total"}
