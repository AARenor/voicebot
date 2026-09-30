"""Azure Neural TTS REST client (ET primary: Anu/Kert).

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

import time

import httpx

from .errors import (
    ProviderError,
    RetryableProviderError,
    raise_for_provider,
)

TOKEN_TTL_SECONDS = 9 * 60


def ssml(text: str, voice: str, lang: str) -> str:
    """Minimal SSML (lean = fewer billable tag chars)."""
    escaped = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return (
        f"<speak version='1.0' xml:lang='{lang}'>"
        f"<voice name='{voice}'>{escaped}</voice></speak>"
    )


class AzureTtsClient:
    def __init__(
        self,
        subscription_key: str,
        region: str,
        voice: str,
        lang: str,
        output_format: str = "audio-16khz-32kbitrate-mono-mp3",
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not voice or not lang:
            raise ValueError("azure: voice and lang are required")
        self._key = subscription_key
        self._region = region
        self._voice = voice
        self._lang = lang
        self._format = output_format
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

    def synthesize(self, text: str) -> bytes:
        """Synthesize one reply turn. Returns audio bytes."""
        return self._synthesize_once(text, self.get_token())

    def _synthesize_once(self, text: str, token: str) -> bytes:
        try:
            response = self._http.post(
                f"https://{self._region}.tts.speech.microsoft.com/cognitiveServices/v1",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/ssml+xml",
                    "X-Microsoft-OutputFormat": self._format,
                },
                content=ssml(text, self._voice, self._lang).encode("utf-8"),
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
                    content=ssml(text, self._voice, self._lang).encode("utf-8"),
                )
            except httpx.RequestError as exc:
                raise RetryableProviderError(
                    f"azure.synthesize: transport error: {exc}"
                ) from exc
        raise_for_provider(response, "azure.synthesize")
        return response.content
