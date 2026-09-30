"""Groq REST client: Whisper STT (chunked file API) + chat w/ tools.

Endpoints follow Groq's OpenAI-compatible API (verified against
console.groq.com/docs/speech-to-text + /docs/text-chat patterns):
  POST {base}/openai/v1/audio/transcriptions  (multipart: file, model)
  POST {base}/openai/v1/chat/completions      (json: model, messages[, tools])
Free tier: whisper 20 RPM / 2K RPD / 7.2K ASH / 28.8K ASD (2026-09-29);
429s carry retry-after — caller retries with backoff (Groq → Gemini →
OpenRouter chain lives in pipeline, not here).
"""

from __future__ import annotations

import httpx

from .errors import (
    ProviderError,
    RetryableProviderError,
    raise_for_provider,
)

DEFAULT_BASE_URL = "https://api.groq.com"
STT_MODEL = "whisper-large-v3-turbo"  # $0.04/hr; NOT the TalTech ET finetune
CHAT_MODEL = "llama-3.1-8b-instant"  # pin + monitor: Groq catalog churns


class GroqClient:
    def __init__(
        self,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
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
        self, audio: bytes, filename: str = "chunk.wav", model: str = STT_MODEL
    ) -> str:
        """Transcribe one VAD chunk. Returns plain text."""
        response = self._post(
            "/openai/v1/audio/transcriptions",
            "groq.transcribe",
            files={"file": (filename, audio, "audio/wav")},
            data={"model": model},
        )
        try:
            payload = response.json()
            return str(payload["text"])
        except (KeyError, IndexError, ValueError, TypeError, AttributeError) as exc:
            raise ProviderError(f"groq.transcribe: bad payload: {exc}") from exc

    def chat(
        self,
        messages: list[dict],
        model: str = CHAT_MODEL,
        tools: list[dict] | None = None,
    ) -> dict:
        """Chat completion. Returns the assistant message dict
        (may carry tool_calls for booking function-calling)."""
        body: dict = {"model": model, "messages": messages}
        if tools:
            body["tools"] = tools
        response = self._post("/openai/v1/chat/completions", "groq.chat", json=body)
        try:
            payload = response.json()
            message = payload["choices"][0]["message"]
            return dict(message)
        except (KeyError, IndexError, ValueError, TypeError, AttributeError) as exc:
            raise ProviderError(f"groq.chat: bad payload: {exc}") from exc
