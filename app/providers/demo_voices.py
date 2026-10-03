"""Configuration-only demo voice catalog and request-local fallback routing."""

from __future__ import annotations

import importlib
import os
from contextlib import closing, nullcontext

from .modern_tts import (
    CartesiaTtsClient,
    ElevenLabsTtsClient,
    GoogleTtsClient,
    MAX_AUDIO_BYTES,
    Mp3Audio,
    provider_error,
    validate_text,
)

PROFILES = {
    "azure": ("Azure Neural", ("et", "en", "ru"), True),
    "elevenlabs": ("ElevenLabs v4 Turbo", ("et", "en", "ru"), True),
    "google": ("Google Chirp 3 HD", ("et", "en", "ru"), False),
    "cartesia": ("Cartesia Sonic 3.6", ("en", "ru"), True),
}


def dependency_available(name):
    try:
        importlib.import_module(name)
        return True
    except ImportError:
        return False


class DemoVoices:
    def __init__(self, clients=None, *, readiness=None):
        self._clients = {
            key: value
            for key, value in (clients or {}).items()
            if key in PROFILES and key != "azure"
        }
        self._readiness = dict(readiness or {})

    def __repr__(self):
        return "DemoVoices(redacted)"

    @classmethod
    def from_env(cls, env=None):
        env = os.environ if env is None else env
        clients, readiness = {}, {}
        definitions = (
            (
                "elevenlabs",
                ("ELEVENLABS_API_KEY", "ELEVENLABS_VOICE_ID"),
                "websockets.sync.client",
                lambda: ElevenLabsTtsClient(
                    env.get("ELEVENLABS_API_KEY"), env.get("ELEVENLABS_VOICE_ID")
                ),
            ),
            (
                "google",
                ("GOOGLE_TTS_ACCESS_TOKEN",),
                "google.auth.transport.requests"
                if env.get("GOOGLE_TTS_USE_ADC") == "1"
                and not env.get("GOOGLE_TTS_ACCESS_TOKEN")
                else None,
                lambda: GoogleTtsClient(
                    env.get("GOOGLE_TTS_ACCESS_TOKEN"),
                    use_adc=env.get("GOOGLE_TTS_USE_ADC") == "1",
                    quota_project=env.get("GOOGLE_CLOUD_QUOTA_PROJECT"),
                    voices={
                        language: env.get(
                            f"GOOGLE_TTS_{language.upper()}_VOICE",
                            locale + "-Chirp3-HD-Kore",
                        )
                        for language, locale in (
                            ("et", "et-EE"),
                            ("en", "en-US"),
                            ("ru", "ru-RU"),
                        )
                    },
                ),
            ),
            (
                "cartesia",
                ("CARTESIA_API_KEY", "CARTESIA_VOICE_ID"),
                None,
                lambda: CartesiaTtsClient(
                    env.get("CARTESIA_API_KEY"), env.get("CARTESIA_VOICE_ID")
                ),
            ),
        )
        for profile, required, dependency, build in definitions:
            configured = all(env.get(key) for key in required) or (
                profile == "google" and env.get("GOOGLE_TTS_USE_ADC") == "1"
            )
            if not configured:
                readiness[profile] = (False, "not_configured")
                continue
            try:
                client = build()
            except (ValueError, TypeError):
                readiness[profile] = (False, "invalid_configuration")
                continue
            if dependency and not dependency_available(dependency):
                client.close()
                readiness[profile] = (True, "dependency_unavailable")
                continue
            clients[profile] = client
        return cls(clients, readiness=readiness)

    def catalog(self, azure=None):
        rows = []
        for profile, (label, languages, streaming) in PROFILES.items():
            available = (
                azure is not None if profile == "azure" else profile in self._clients
            )
            configured, reason = self._readiness.get(
                profile, (available, None if available else "not_configured")
            )
            rows.append(
                {
                    "id": profile,
                    "label": label,
                    "languages": list(languages),
                    "configured": bool(configured),
                    "available": bool(available),
                    "disabled_reason": reason,
                    "streaming": streaming,
                }
            )
        return rows

    def choose(self, profile_id="azure", azure=None):
        if not isinstance(profile_id, str) or profile_id not in PROFILES:
            raise ValueError("unknown voice profile") from None
        if (profile_id == "azure" and azure is None) or (
            profile_id != "azure" and profile_id not in self._clients
        ):
            raise ValueError("voice profile unavailable") from None
        return _Choice(profile_id, self._clients.get(profile_id), azure)

    def close(self):
        for client in self._clients.values():
            client.close()


class _Choice:
    audio_type = "audio/mpeg"

    def __init__(self, requested, client, azure, language="et"):
        self._requested, self._client, self._azure, self._language = (
            requested,
            client,
            azure,
            language,
        )
        unsupported = requested != "azure" and language not in PROFILES[requested][1]
        self._effective = "azure" if unsupported else requested
        self._reason = "unsupported_language" if unsupported else None

    def __repr__(self):
        return "DemoVoiceChoice(redacted)"

    def for_language(self, language):
        if language not in ("et", "en", "ru"):
            raise provider_error("request_rejected") from None
        return _Choice(self._requested, self._client, self._azure, language)

    @property
    def voice_info(self):
        return {
            "requested": self._requested,
            "effective": self._effective,
            "language": self._language,
            "fallback": self._effective != self._requested,
            "reason": self._reason,
            "streaming": PROFILES[self._effective][2],
        }

    @property
    def streaming(self):
        return self.voice_info["streaming"]

    def _speaker(self):
        client = self._azure if self._effective == "azure" else self._client
        if client is None:
            raise provider_error("provider_unavailable") from None
        return (
            client.for_language(self._language)
            if hasattr(client, "for_language")
            else client
        )

    def _fallback(self):
        if self._effective == "azure" or self._azure is None:
            return False
        self._effective, self._reason = "azure", "provider_failure"
        return True

    def synthesize(self, text):
        validate_text(text)
        for _ in range(2):
            try:
                audio = self._speaker().synthesize(text)
                if (
                    not isinstance(audio, bytes)
                    or not audio
                    or len(audio) > MAX_AUDIO_BYTES
                ):
                    raise provider_error()
                if self._effective != "azure":
                    validator = Mp3Audio()
                    validator.feed(audio)
                    validator.finish()
                return audio
            except Exception:
                if not self._fallback():
                    raise provider_error("provider_unavailable") from None
        raise provider_error("provider_unavailable") from None

    def stream(self, text):
        validate_text(text)
        sent = 0
        for _ in range(2):
            try:
                total = 0
                validator = Mp3Audio() if self._effective != "azure" else None
                speaker = self._speaker()
                iterator = iter(
                    speaker.stream(text)
                    if callable(getattr(speaker, "stream", None))
                    else (speaker.synthesize(text),)
                )
                context = (
                    closing(iterator)
                    if callable(getattr(iterator, "close", None))
                    else nullcontext(iterator)
                )
                with context:
                    for chunk in iterator:
                        if not isinstance(chunk, bytes):
                            raise provider_error()
                        if not chunk:
                            continue
                        total += len(chunk)
                        if total > MAX_AUDIO_BYTES:
                            raise provider_error()
                        if validator is not None:
                            chunk = validator.feed(chunk)
                        if chunk:
                            sent += 1
                            yield chunk
                    if validator is not None:
                        validator.finish()
                    if not sent:
                        raise provider_error()
                return
            except Exception:
                if sent:
                    raise provider_error("completion_incomplete") from None
                if not self._fallback():
                    raise provider_error("provider_unavailable") from None
        raise provider_error("provider_unavailable") from None
