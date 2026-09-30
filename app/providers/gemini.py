"""Gemini REST client: text-only secondary LLM (failover, no tools).

POST https://generativelanguage.googleapis.com/v1beta/models/
{model}:generateContent (key in query). Used ONLY as turn-loop failover
when the primary is rate-limited/down; it answers from the transcript
without function-calling. Free tier is volatile — design to low RPD and
never rely on it as primary. Free-tier prompts may train models: keep
PII out (names/phones stay in tool args, not prose) or move to paid.
"""

from __future__ import annotations

import httpx

from .errors import (
    ProviderError,
    RetryableProviderError,
    raise_for_provider,
)

DEFAULT_MODEL = "gemini-2.5-flash-lite"


def _flatten(messages: list[dict]) -> str:
    lines = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        role = message.get("role", "user")
        content = message.get("content")
        if content is None:
            continue
        lines.append(f"{role}: {content}")
    return "\n".join(lines)[-8000:]


class GeminiClient:
    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_MODEL,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._key = api_key
        self._model = model
        self._http = httpx.Client(timeout=30.0, transport=transport)

    def __repr__(self) -> str:
        return "GeminiClient(redacted)"

    def close(self) -> None:
        self._http.close()

    def chat(self, messages: list[dict], tools=None) -> dict:
        """Text-only chat (tools ignored: secondary never function-calls)."""
        body = {"contents": [{"parts": [{"text": _flatten(messages)}]}]}
        try:
            response = self._http.post(
                "https://generativelanguage.googleapis.com/v1beta/models/"
                f"{self._model}:generateContent",
                params={"key": self._key},
                json=body,
            )
        except httpx.RequestError as exc:
            raise RetryableProviderError(
                f"gemini.chat: transport error: {exc}"
            ) from exc
        raise_for_provider(response, "gemini.chat")
        try:
            parts = response.json()["candidates"][0]["content"]["parts"]
            text = "".join(p.get("text", "") for p in parts)
            return {"role": "assistant", "content": text}
        except (KeyError, IndexError, ValueError, TypeError, AttributeError) as exc:
            raise ProviderError(f"gemini.chat: bad payload: {exc}") from exc
