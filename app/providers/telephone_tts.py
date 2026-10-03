"""Azure plugin extension through its public per-sentence synthesis interface."""

from __future__ import annotations

from typing import Any

from livekit.agents import APIConnectOptions, NOT_GIVEN, NotGivenOr, tts
from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS
from livekit.agents.utils import is_given
from livekit.plugins import azure

from .speech_delivery import SpeechDelivery, speech_markup


class TelephoneTTS(azure.TTS):
    def __init__(
        self,
        *,
        voice: str,
        language: str,
        delivery: SpeechDelivery,
        **kwargs: Any,
    ) -> None:
        self._delivery = delivery
        self._voice, self._language = voice, language
        self._recap = False
        super().__init__(voice=voice, language=language, **kwargs)

    def update_options(
        self,
        *,
        voice: NotGivenOr[str] = NOT_GIVEN,
        language: NotGivenOr[str] = NOT_GIVEN,
        **kwargs: Any,
    ) -> None:
        super().update_options(voice=voice, language=language, **kwargs)
        if is_given(voice):
            self._voice = voice
        if is_given(language):
            self._language = language

    def set_recap_delivery(self, recap: bool) -> None:
        self._recap = recap

    def synthesize(
        self,
        text: str,
        *,
        conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS,
    ) -> tts.ChunkedStream:
        # The SDK tokenizes PLAIN text first. Each actual synthesis request gets
        # complete markup, so sentence boundaries cannot split XML elements.
        body = speech_markup(
            text,
            self._voice,
            self._language,
            self._delivery,
            recap=self._recap,
        )
        return super().synthesize(body, conn_options=conn_options)
