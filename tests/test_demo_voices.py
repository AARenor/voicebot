"""Session selection, configuration-only readiness, and no-audio fallback."""

import importlib
import importlib.util
import json

import pytest

from app.providers.errors import ProviderError
from tests.test_modern_tts import FRAME, MP3, TEXT, VOICE_ID


def registry():
    assert importlib.util.find_spec("app.providers.demo_voices"), (
        "demo voice registry missing"
    )
    return importlib.import_module("app.providers.demo_voices").DemoVoices


class Speaker:
    audio_type = "audio/mpeg"
    streaming = True
    languages = ("en", "ru")

    def __init__(self, chunks=(MP3,), error=None):
        self.chunks, self.error = chunks, error
        self.calls, self.closed = [], False

    def for_language(self, language):
        parent = self

        class View:
            def synthesize(self, text):
                parent.calls.append((language, "synthesize", text))
                if parent.error:
                    raise parent.error
                return b"".join(parent.chunks)

            def stream(self, text):
                parent.calls.append((language, "stream", text))
                yield from parent.chunks
                if parent.error:
                    raise parent.error

        return View()

    def close(self):
        self.closed = True


def test_empty_configuration_catalog_is_safe_and_default_azure_is_late_bound():
    voices = registry().from_env({})
    first, second = Speaker(), Speaker()
    try:
        catalog = voices.catalog(azure=first)
        assert [row["id"] for row in catalog] == [
            "azure",
            "elevenlabs",
            "google",
            "cartesia",
        ]
        assert all(
            set(row)
            == {
                "id",
                "label",
                "languages",
                "configured",
                "available",
                "disabled_reason",
                "streaming",
            }
            for row in catalog
        )
        assert catalog[0]["available"] is True
        assert all(
            row["configured"] is False
            and row["available"] is False
            and row["disabled_reason"] == "not_configured"
            for row in catalog[1:]
        )
        assert voices.choose(azure=second).for_language("et").synthesize(TEXT) == MP3
        assert first.calls == []
        assert second.calls == [("et", "synthesize", TEXT)]
        assert voices.catalog()[0]["available"] is False
    finally:
        voices.close()
    assert not first.closed and not second.closed


@pytest.mark.parametrize("profile", ["bogus", "https://private.example", None, [], {}])
def test_unknown_profile_error_is_fixed_and_cannot_reflect_input(profile):
    voices = registry().from_env({})
    with pytest.raises(ValueError, match="^unknown voice profile$"):
        voices.choose(profile, azure=Speaker())


def test_unconfigured_selection_is_rejected_not_silently_selected():
    voices = registry().from_env({})
    with pytest.raises(ValueError, match="^voice profile unavailable$"):
        voices.choose("google", azure=Speaker())


def test_environment_configuration_is_not_live_verification_and_no_private_data_leaks():
    env = {
        "ELEVENLABS_API_KEY": "synthetic-eleven",
        "ELEVENLABS_VOICE_ID": "synthetic-voice",
        "GOOGLE_TTS_ACCESS_TOKEN": "synthetic-google",
        "CARTESIA_API_KEY": "synthetic-cartesia",
        "CARTESIA_VOICE_ID": VOICE_ID,
    }
    voices = registry().from_env(env)
    try:
        catalog = voices.catalog(azure=Speaker())
        assert all(row["configured"] for row in catalog)
        assert "et" not in catalog[-1]["languages"]
        assert catalog[2]["streaming"] is False
        public = json.dumps(catalog) + repr(voices)
        assert "synthetic" not in public and VOICE_ID not in public
        assert "verified" not in public
    finally:
        voices.close()


def test_missing_optional_dependency_is_unavailable_without_import_crash(monkeypatch):
    registry()
    module = importlib.import_module("app.providers.demo_voices")
    monkeypatch.setattr(module, "dependency_available", lambda name: False)
    voices = module.DemoVoices.from_env(
        {
            "ELEVENLABS_API_KEY": "synthetic-eleven",
            "ELEVENLABS_VOICE_ID": "synthetic-voice",
            "GOOGLE_TTS_USE_ADC": "1",
        }
    )
    try:
        for row in voices.catalog(azure=Speaker())[1:3]:
            assert row["configured"] is True
            assert row["available"] is False
            assert row["disabled_reason"] == "dependency_unavailable"
    finally:
        voices.close()


@pytest.mark.parametrize(
    "env",
    [
        {"CARTESIA_API_KEY": "synthetic-cartesia", "CARTESIA_VOICE_ID": "bad/private"},
        {
            "GOOGLE_TTS_ACCESS_TOKEN": "synthetic-google",
            "GOOGLE_TTS_ET_VOICE": "en-US-Chirp3-HD-Kore",
        },
        {
            "ELEVENLABS_API_KEY": "synthetic-eleven",
            "ELEVENLABS_VOICE_ID": "../../private",
        },
    ],
)
def test_invalid_configuration_has_closed_reason_no_echo(env):
    voices = registry().from_env(env)
    try:
        modern_rows = voices.catalog(azure=Speaker())[1:]
        row = next(
            row for row in modern_rows if row["disabled_reason"] != "not_configured"
        )
        assert row["configured"] is False
        assert row["available"] is False
        assert row["disabled_reason"] == "invalid_configuration"
        assert "private" not in json.dumps(modern_rows)
    finally:
        voices.close()


def test_language_views_are_request_local_and_unsupported_et_falls_back():
    modern, azure = Speaker(), Speaker()
    voices = registry()({"cartesia": modern})
    try:
        choice = voices.choose("cartesia", azure=azure)
        et, ru = choice.for_language("et"), choice.for_language("ru")
        assert et.synthesize(TEXT) == MP3
        assert ru.synthesize(TEXT) == MP3
        assert et.voice_info == {
            "requested": "cartesia",
            "effective": "azure",
            "language": "et",
            "fallback": True,
            "reason": "unsupported_language",
            "streaming": True,
        }
        assert ru.voice_info == {
            "requested": "cartesia",
            "effective": "cartesia",
            "language": "ru",
            "fallback": False,
            "reason": None,
            "streaming": True,
        }
        assert azure.calls == [("et", "synthesize", TEXT)]
        assert modern.calls == [("ru", "synthesize", TEXT)]
        info = ru.voice_info
        info["effective"] = "mutated"
        assert ru.voice_info["effective"] == "cartesia"
    finally:
        voices.close()
    assert modern.closed and not azure.closed


def test_buffered_failure_falls_back_once_with_exact_text():
    modern, azure = Speaker(error=RuntimeError("private upstream detail")), Speaker()
    voices = registry()({"cartesia": modern})
    try:
        choice = voices.choose("cartesia", azure=azure).for_language("en")
        assert choice.synthesize(TEXT) == MP3
        assert len(modern.calls) == len(azure.calls) == 1
        assert modern.calls[0][2] == azure.calls[0][2] == TEXT
        assert choice.voice_info["effective"] == "azure"
        assert choice.voice_info["reason"] == "provider_failure"
    finally:
        voices.close()


def test_stream_failure_before_first_nonempty_chunk_falls_back_once():
    modern, azure = (
        Speaker(chunks=(b"",), error=RuntimeError("private upstream detail")),
        Speaker(),
    )
    voices = registry()({"cartesia": modern})
    try:
        choice = voices.choose("cartesia", azure=azure).for_language("ru")
        assert b"".join(choice.stream(TEXT)) == MP3
        assert azure.calls == [("ru", "stream", TEXT)]
        assert choice.voice_info["effective"] == "azure"
    finally:
        voices.close()


def test_stream_failure_after_audio_never_appends_azure_and_is_safe():
    modern, azure = (
        Speaker(chunks=(FRAME,), error=RuntimeError("private upstream detail")),
        Speaker(),
    )
    voices = registry()({"cartesia": modern})
    try:
        choice = voices.choose("cartesia", azure=azure).for_language("en")
        iterator = choice.stream(TEXT)
        assert next(iterator) == FRAME
        with pytest.raises(ProviderError) as caught:
            next(iterator)
        assert caught.value.reason == "completion_incomplete"
        assert "private" not in repr(caught.value)
        assert azure.calls == []
        assert choice.voice_info["effective"] == "cartesia"
    finally:
        voices.close()


def test_failed_azure_fallback_does_not_retry_or_leak_error():
    modern, azure = (
        Speaker(chunks=(), error=RuntimeError("private modern")),
        Speaker(chunks=(), error=RuntimeError("private azure")),
    )
    voices = registry()({"cartesia": modern})
    try:
        with pytest.raises(ProviderError) as caught:
            voices.choose("cartesia", azure=azure).for_language("en").synthesize(TEXT)
        assert "private" not in repr(caught.value)
        assert len(modern.calls) == len(azure.calls) == 1
    finally:
        voices.close()


@pytest.mark.parametrize("audio", [b"", b"not mp3", MP3[:-1]])
def test_malformed_modern_buffered_audio_falls_back_once(audio):
    modern, azure = Speaker(chunks=(audio,)), Speaker()
    voices = registry()({"cartesia": modern})
    try:
        choice = voices.choose("cartesia", azure=azure).for_language("en")
        assert choice.synthesize(TEXT) == MP3
        assert choice.voice_info["effective"] == "azure"
        assert len(azure.calls) == 1
    finally:
        voices.close()


def test_malformed_modern_stream_before_audio_falls_back_but_truncated_after_audio_does_not():
    azure = Speaker()
    voices = registry()({"cartesia": Speaker(chunks=(b"not mp3",))})
    try:
        assert (
            b"".join(
                voices.choose("cartesia", azure=azure).for_language("en").stream(TEXT)
            )
            == MP3
        )
        assert len(azure.calls) == 1
    finally:
        voices.close()
    azure.calls.clear()
    voices = registry()({"cartesia": Speaker(chunks=(FRAME, FRAME[:-1]))})
    try:
        iterator = (
            voices.choose("cartesia", azure=azure).for_language("en").stream(TEXT)
        )
        assert next(iterator) == FRAME
        with pytest.raises(ProviderError):
            list(iterator)
        assert azure.calls == []
    finally:
        voices.close()


def test_stream_close_failure_is_sanitized_and_pre_audio_failure_falls_back():
    class BadIterator:
        def __iter__(self):
            return self

        def __next__(self):
            raise StopIteration

        def close(self):
            raise RuntimeError("private cleanup detail")

    class BadClient(Speaker):
        def for_language(self, language):
            return self

        def stream(self, text):
            return BadIterator()

    azure = Speaker()
    voices = registry()({"cartesia": BadClient()})
    try:
        assert (
            b"".join(
                voices.choose("cartesia", azure=azure).for_language("en").stream(TEXT)
            )
            == MP3
        )
        assert len(azure.calls) == 1
    finally:
        voices.close()


def test_synthesize_only_azure_fake_preserves_legacy_default_behavior():
    class Legacy:
        def synthesize(self, text):
            assert text == TEXT
            return b"legacy fixture audio"

    voices = registry().from_env({})
    choice = voices.choose(azure=Legacy())
    assert choice.synthesize(TEXT) == b"legacy fixture audio"
    assert list(choice.stream(TEXT)) == [b"legacy fixture audio"]
    voices.close()
