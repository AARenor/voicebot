"""Azure Neural TTS REST client for the supported ET/EN/RU voice paths.

Flow (Azure Speech REST, verified learn.microsoft.com language-support):
  POST https://{region}.api.cognitive.microsoft.com/sts/v1.0/issueToken
    (header Ocp-Apim-Subscription-Key) -> bearer token (~10 min life)
  POST https://{region}.tts.speech.microsoft.com/cognitiveServices/v1
    (Authorization: Bearer, Content-Type: application/ssml+xml,
     X-Microsoft-OutputFormat) with SSML -> audio bytes
Token cached client-side (9-min monotonic TTL, validated before caching).
On 401 the token is force-refreshed once and the synth retried once.
F0: 0.5M neural chars/mo free.
SSML tags other than break/phoneme count as billable — keep SSML lean.
"""

from __future__ import annotations

import re
import time
from dataclasses import replace

import httpx
from xml.sax.saxutils import quoteattr

from .speech_delivery import SpeechDelivery, is_recap, speech_markup

from .errors import (
    ProviderError,
    RetryableProviderError,
    raise_for_provider,
)
from .speech_text import normalize_estonian_speech
from .modern_tts import (
    Mp3Audio,
    TOTAL_TIMEOUT,
    check_status,
    provider_error,
    remaining,
    validate_text,
)

TOKEN_TTL_SECONDS = 9 * 60

# Native voices for each language; a lower pitch is not a substitute for a male
# voice. Profiles share the authenticated client without mutating its settings.
AZURE_PRESETS = {
    "azure-male": {
        "et": ("et-EE-KertNeural", "et-EE"),
        "en": ("en-US-GuyNeural", "en-US"),
        "ru": ("ru-RU-DmitryNeural", "ru-RU"),
    },
    "azure-calm": {
        "et": ("et-EE-AnuNeural", "et-EE"),
        "en": ("en-US-JennyNeural", "en-US"),
        "ru": ("ru-RU-SvetlanaNeural", "ru-RU"),
    },
}


def validated_voice(voice, lang):
    voice = voice.strip() if isinstance(voice, str) else ""
    lang = lang.strip() if isinstance(lang, str) else ""
    if (
        lang not in {"et-EE", "ru-RU"} and not re.fullmatch(r"en-[A-Z]{2}", lang)
    ) or not re.fullmatch(re.escape(lang) + r"-[A-Za-z0-9]+Neural", voice):
        raise ValueError("supported speech voice required")
    return voice, lang


class _LanguageSpeaker:
    """Per-turn view of a shared client; never mutate another call's voice."""

    def __init__(self, client, voice, lang, delivery=None):
        self.client, self.voice, self.lang = client, voice, lang
        self.delivery = delivery

    def synthesize(self, text):
        return self.client.synthesize(
            text, voice=self.voice, lang=self.lang, delivery=self.delivery
        )

    def stream(self, text):
        return self.client.stream(
            text, voice=self.voice, lang=self.lang, delivery=self.delivery
        )


class _ProfileSpeaker:
    audio_type = "audio/mpeg"
    streaming = True

    def __init__(self, client, profile):
        self.client, self.profile = client, profile

    def for_language(self, language):
        if language not in AZURE_PRESETS[self.profile]:
            raise ValueError("unsupported speech language")
        delivery = self.client._delivery
        if self.profile == "azure-calm" and delivery.mode == "natural":
            delivery = replace(
                delivery,
                rate=max(0.85, delivery.rate - 0.04),
                recap_rate=max(0.85, delivery.recap_rate - 0.03),
                sentence_pause_ms=240,
            )
        return _LanguageSpeaker(
            self.client, *AZURE_PRESETS[self.profile][language], delivery=delivery
        )


def ssml(
    text: str, voice: str, lang: str, delivery: SpeechDelivery | None = None
) -> str:
    """Escape literal speech and apply shared voice-specific delivery."""
    body = speech_markup(
        normalize_estonian_speech(text, lang),
        voice,
        lang,
        delivery or SpeechDelivery(),
        recap=is_recap(text),
    )
    return (
        "<speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis' "
        f"xmlns:mstts='http://www.w3.org/2001/mstts' xml:lang={quoteattr(lang)}>"
        f"<voice name={quoteattr(voice)}>{body}</voice></speak>"
    )


class AzureTtsClient:
    audio_type = "audio/mpeg"
    streaming = True

    def __init__(
        self,
        subscription_key: str,
        region: str,
        voice: str,
        lang: str,
        output_format: str = "audio-48khz-96kbitrate-mono-mp3",
        transport: httpx.BaseTransport | None = None,
        *,
        languages: dict[str, tuple[str, str]] | None = None,
        delivery: SpeechDelivery | None = None,
    ) -> None:
        voice, lang = validated_voice(voice, lang)
        self._key = subscription_key
        self._region = region
        self._voice = voice
        self._lang = lang
        self._format = output_format
        self._languages = dict(languages or {})
        self._delivery = delivery or SpeechDelivery()
        for language, pair in self._languages.items():
            checked = validated_voice(*pair)
            if (
                language not in {"et", "en", "ru"}
                or checked[1].split("-")[0] != language
            ):
                raise ValueError("supported speech voice required")
            self._languages[language] = checked
        self._http = httpx.Client(timeout=30.0, transport=transport)
        self._token: str | None = None
        self._token_at: float = 0.0

    def __repr__(self) -> str:
        return f"AzureTtsClient({self._voice}, redacted)"

    def close(self) -> None:
        self._http.close()

    def get_token(self, force: bool = False) -> str:
        """Fetch (and cache) a bearer token. Empty tokens never cache."""
        if (
            not force
            and self._token is not None
            and time.monotonic() - self._token_at < TOKEN_TTL_SECONDS
        ):
            return self._token
        try:
            response = self._http.post(
                f"https://{self._region}.api.cognitive.microsoft.com"
                "/sts/v1.0/issueToken",
                headers={"Ocp-Apim-Subscription-Key": self._key},
                content=b"",
            )
        except httpx.RequestError as exc:
            raise RetryableProviderError(
                f"azure.token: transport error: {exc}"
            ) from exc
        raise_for_provider(response, "azure.token")
        token = response.text
        if not token:
            # Never cache empties: next call refetches (P0-3).
            self._token = None
            raise ProviderError("azure.token: empty token")
        self._token = token
        self._token_at = time.monotonic()
        return token

    def for_language(self, language):
        if language not in {"et", "en", "ru"}:
            raise ValueError("unsupported speech language")
        if language in self._languages:
            voice, lang = self._languages[language]
        elif language == self._lang.split("-")[0]:
            voice, lang = self._voice, self._lang
        else:
            raise ValueError("speech language not configured")
        return _LanguageSpeaker(self, voice, lang)

    def for_profile(self, profile):
        if profile not in AZURE_PRESETS:
            raise ValueError("unknown Azure voice profile")
        return _ProfileSpeaker(self, profile)

    def synthesize(self, text: str, *, voice=None, lang=None, delivery=None) -> bytes:
        """Synthesize one reply turn. Returns audio bytes."""
        voice, lang = validated_voice(
            self._voice if voice is None else voice,
            self._lang if lang is None else lang,
        )
        return self._synthesize_once(
            text, self.get_token(), voice=voice, lang=lang, delivery=delivery
        )

    def stream(self, text: str, *, voice=None, lang=None, delivery=None):
        """Real REST streaming; refresh once only before any audio is emitted."""
        validate_text(text)
        voice, lang = validated_voice(
            self._voice if voice is None else voice,
            self._lang if lang is None else lang,
        )
        body = ssml(text, voice, lang, delivery or self._delivery).encode("utf-8")
        deadline = time.monotonic() + TOTAL_TIMEOUT
        try:
            token = self.get_token()
            for attempt in range(2):
                remaining(deadline)
                refresh = False
                with self._http.stream(
                    "POST",
                    f"https://{self._region}.tts.speech.microsoft.com/cognitiveServices/v1",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/ssml+xml",
                        "X-Microsoft-OutputFormat": self._format,
                    },
                    content=body,
                    timeout=10.0,
                ) as response:
                    if response.status_code == 401 and attempt == 0:
                        refresh = True
                    else:
                        check_status(response)
                        audio = Mp3Audio()
                        for raw in response.iter_bytes():
                            remaining(deadline)
                            chunk = audio.feed(raw)
                            if chunk:
                                yield chunk
                        audio.finish()
                        return
                if refresh:
                    token = self.get_token(force=True)
        except ProviderError as error:
            raise provider_error(
                error.reason or "provider_unavailable", error.status_code
            ) from None
        except Exception:
            raise provider_error("transport_error") from None

    def _synthesize_once(
        self, text: str, token: str, *, voice=None, lang=None, delivery=None
    ) -> bytes:
        body = ssml(
            text, voice or self._voice, lang or self._lang, delivery or self._delivery
        ).encode("utf-8")
        try:
            response = self._http.post(
                f"https://{self._region}.tts.speech.microsoft.com/cognitiveServices/v1",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/ssml+xml",
                    "X-Microsoft-OutputFormat": self._format,
                },
                content=body,
            )
        except httpx.RequestError as exc:
            raise RetryableProviderError(
                f"azure.synthesize: transport error: {exc}"
            ) from exc
        if response.status_code == 401:
            # Token may be expired/revoked: refresh once, retry once.
            token = self.get_token(force=True)
            try:
                response = self._http.post(
                    f"https://{self._region}.tts.speech.microsoft.com"
                    "/cognitiveServices/v1",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/ssml+xml",
                        "X-Microsoft-OutputFormat": self._format,
                    },
                    content=body,
                )
            except httpx.RequestError as exc:
                raise RetryableProviderError(
                    f"azure.synthesize: transport error: {exc}"
                ) from exc
        raise_for_provider(response, "azure.synthesize")
        return response.content
