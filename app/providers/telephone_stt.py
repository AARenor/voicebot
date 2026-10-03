"""Groq Whisper with language metadata through the public LiveKit STT contract.

The pinned Groq plugin requests JSON, which omits Whisper's detected language.
Verbose JSON lets the telephone worker choose the reply voice without a second
model request. LiveKit owns VAD adaptation, cancellation, retries and metrics.
"""

from __future__ import annotations

import httpx
from livekit import rtc
from livekit.agents import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    APIConnectOptions,
    LanguageCode,
    NOT_GIVEN,
    NotGivenOr,
    stt,
)
from livekit.agents.utils import AudioBuffer

from ..languages import LANGUAGES, language_code


class TelephoneSTT(stt.STT[str]):
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        mode: str = "auto",
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        super().__init__(
            capabilities=stt.STTCapabilities(streaming=False, interim_results=False)
        )
        if mode not in {"auto", *LANGUAGES}:
            raise ValueError("invalid telephone language mode")
        self._model, self.mode = model, mode
        self._http = httpx.AsyncClient(
            base_url="https://api.groq.com",
            transport=transport,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=30,
        )

    @property
    def model(self) -> str:
        return self._model

    @property
    def provider(self) -> str:
        return "Groq"

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _recognize_impl(
        self,
        buffer: AudioBuffer,
        *,
        language: NotGivenOr[str] = NOT_GIVEN,
        conn_options: APIConnectOptions,
    ) -> stt.SpeechEvent:
        data = {
            "model": self._model,
            "response_format": "verbose_json",
            "temperature": "0",
        }
        if self.mode != "auto":
            data["language"] = self.mode
        try:
            response = await self._http.post(
                "/openai/v1/audio/transcriptions",
                data=data,
                files={
                    "file": (
                        "chunk.wav",
                        rtc.combine_audio_frames(buffer).to_wav_bytes(),
                        "audio/wav",
                    )
                },
                timeout=httpx.Timeout(30, connect=conn_options.timeout),
            )
        except httpx.TimeoutException:
            raise APITimeoutError("telephone transcription timeout") from None
        except httpx.RequestError:
            raise APIConnectionError(
                "telephone transcription connection failed"
            ) from None
        if response.status_code >= 400:
            raise APIStatusError(
                "telephone transcription rejected", status_code=response.status_code
            ) from None
        try:
            payload = response.json()
            text = payload["text"]
            raw_language = payload.get("language")
            code = language_code(raw_language)
            if not isinstance(text, str) or (
                self.mode == "auto"
                and (not isinstance(raw_language, str) or not raw_language.strip())
            ):
                raise ValueError
            # Missing/malformed language is a provider failure, never an ET guess.
            if self.mode != "auto":
                code = self.mode
            segments = payload.get("segments", [])
            if not isinstance(segments, list):
                raise ValueError
            # Suppress silence hallucinations, especially a fabricated consent.
            if segments and all(
                isinstance(s, dict)
                and isinstance(s.get("no_speech_prob"), (int, float))
                and s["no_speech_prob"] >= 0.85
                and isinstance(s.get("avg_logprob"), (int, float))
                and s["avg_logprob"] < -1.0
                for s in segments
            ):
                text = ""
            return stt.SpeechEvent(
                type=stt.SpeechEventType.FINAL_TRANSCRIPT,
                alternatives=[
                    stt.SpeechData(
                        text=text,
                        language=LanguageCode(code or "und"),
                        metadata={"unsupported_language": code is None},
                    )
                ],
            )
        except (KeyError, TypeError, ValueError, AttributeError):
            raise APIStatusError(
                "invalid telephone transcription", status_code=502
            ) from None
