"""Shared speech/model settings for HTTP turns and the native telephone worker.

Defaults are current production Groq models, checked against the provider's
model and speech documentation. The multilingual accuracy model is preferred
for booking dates and consent; operators can select turbo after measuring it.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
import re

STT_MODEL = "whisper-large-v3"
CHAT_MODEL = "openai/gpt-oss-120b"
STT_LANGUAGE = "et"
MAX_COMPLETION_TOKENS = 2048


@dataclass(frozen=True)
class VoiceConfig:
    chat_model: str = CHAT_MODEL
    stt_model: str = STT_MODEL
    max_completion_tokens: int = MAX_COMPLETION_TOKENS

    @classmethod
    def from_env(cls, env=None):
        env = os.environ if env is None else env

        def model(name, default):
            value = env.get(name, default).strip() or default
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9/._-]{0,127}", value):
                raise ValueError("invalid voice model configuration")
            return value

        try:
            tokens = int(env.get("GROQ_MAX_COMPLETION_TOKENS", MAX_COMPLETION_TOKENS))
        except (TypeError, ValueError):
            raise ValueError("invalid voice completion limit") from None
        if not 512 <= tokens <= 8192:
            raise ValueError("invalid voice completion limit")
        return cls(
            chat_model=model("GROQ_CHAT_MODEL", CHAT_MODEL),
            stt_model=model("GROQ_STT_MODEL", STT_MODEL),
            max_completion_tokens=tokens,
        )

    def chat_options(self, model=None):
        model = self.chat_model if model is None else model
        options = {"max_completion_tokens": self.max_completion_tokens}
        if model in {"openai/gpt-oss-20b", "openai/gpt-oss-120b"}:
            # Reasoning uses the same completion budget as the spoken answer.
            # Keep enough room for valid tool arguments, with short reasoning.
            options.update(reasoning_effort="low", include_reasoning=False)
        return options
