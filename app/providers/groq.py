"""Groq REST client: Whisper STT (chunked file API) + chat w/ tools.

Endpoints follow Groq's OpenAI-compatible API (verified against
console.groq.com/docs/speech-to-text + /docs/text-chat patterns):
  POST {base}/openai/v1/audio/transcriptions  (multipart: file, model)
  POST {base}/openai/v1/chat/completions      (json: model, messages[, tools])
429s carry retry-after; the turn controller owns retries and failover.
Sync requests are sent through the HTTP turn controller's thread boundary.
"""

from __future__ import annotations

import httpx

from .errors import (
    ProviderError,
    RetryableProviderError,
    raise_for_provider,
)
from .voice_config import (
    CHAT_MODEL as CHAT_MODEL,
    STT_LANGUAGE,
    STT_MODEL as STT_MODEL,
    VoiceConfig,
)

DEFAULT_BASE_URL = "https://api.groq.com"


class GroqClient:
    def __init__(
        self,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
        transport: httpx.BaseTransport | None = None,
        *,
        config: VoiceConfig | None = None,
    ) -> None:
        self.config = VoiceConfig.from_env() if config is None else config
        self._key = api_key
        self._base = base_url.rstrip("/")
        self._http = httpx.Client(
            transport=transport,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=30.0,
        )

    def __repr__(self) -> str:
        return "GroqClient(redacted)"

    def close(self) -> None:
        self._http.close()

    def _post(self, path: str, context: str, **kwargs) -> httpx.Response:
        try:
            response = self._http.post(f"{self._base}{path}", **kwargs)
        except httpx.RequestError as exc:
            raise RetryableProviderError(f"{context}: transport error: {exc}") from exc
        raise_for_provider(response, context)
        return response

    def transcribe(
        self, audio: bytes, filename: str = "chunk.wav", model: str | None = None
    ) -> str:
        """Transcribe one VAD chunk. Returns plain text."""
        response = self._post(
            "/openai/v1/audio/transcriptions",
            "groq.transcribe",
            files={"file": (filename, audio, "audio/wav")},
            data={
                "model": model or self.config.stt_model,
                "language": STT_LANGUAGE,
                "response_format": "json",
                "temperature": "0",
            },
        )
        try:
            payload = response.json()
            text = payload["text"]
            if not isinstance(text, str):
                raise TypeError("transcription text is not a string")
            return text
        except (KeyError, IndexError, ValueError, TypeError, AttributeError) as exc:
            raise ProviderError(f"groq.transcribe: bad payload: {exc}") from exc

    def chat(
        self,
        messages: list[dict],
        model: str | None = None,
        tools: list[dict] | None = None,
    ) -> dict:
        """Chat completion. Returns the assistant message dict
        (may carry tool_calls for booking function-calling)."""
        model = model or self.config.chat_model
        body: dict = {
            "model": model,
            "messages": messages,
            **self.config.chat_options(model),
        }
        if tools:
            body["tools"] = tools
            body["parallel_tool_calls"] = False
        response = self._post("/openai/v1/chat/completions", "groq.chat", json=body)
        try:
            payload = response.json()
            choice = payload["choices"][0]
            if choice.get("finish_reason") == "length":
                raise ProviderError("groq.chat: incomplete completion")
            message = dict(choice["message"])
            # Provider reasoning is neither a spoken reply nor conversation data.
            message.pop("reasoning", None)
            return message
        except (KeyError, IndexError, ValueError, TypeError, AttributeError) as exc:
            raise ProviderError(f"groq.chat: bad payload: {exc}") from exc
