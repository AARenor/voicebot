"""Speech-input failures stay distinct from silence and never authorize tools."""

import asyncio
from unittest.mock import Mock

import pytest

from app.turn import REPEAT_PROMPT, STT_UNAVAILABLE, TURN_UNAVAILABLE, run_turn


@pytest.mark.parametrize("language", ["et", "en", "ru"])
def test_recognition_language_is_forwarded(language):
    stt = Mock()
    stt.transcribe.return_value = "Tere"
    llm = Mock()
    llm.chat.return_value = {"content": "Tere!"}
    tts = Mock()
    tts.synthesize.return_value = b"audio"
    dispatcher = Mock()
    dispatcher.available_tools.return_value = []
    result = asyncio.run(
        run_turn(b"audio", stt, llm, tts, dispatcher, language=language)
    )
    stt.transcribe.assert_called_once_with(b"audio", language=language)
    assert result["text_heard"] == "Tere"
    assert result["input_status"] == "recognized"


@pytest.mark.parametrize("text", ["", "   ", "\n"])
def test_empty_recognition_skips_model_and_tools(text):
    stt, llm, tts, dispatcher = Mock(), Mock(), Mock(), Mock()
    stt.transcribe.return_value = text
    tts.synthesize.return_value = b"audio"
    result = asyncio.run(run_turn(b"audio", stt, llm, tts, dispatcher))
    assert result["reply"] == REPEAT_PROMPT["et"]
    assert result["input_status"] == "no_speech"
    assert result["fallback_used"] is False
    llm.chat.assert_not_called()
    dispatcher.available_tools.assert_not_called()


def test_response_failure_does_not_mislabel_speech_or_price():
    llm, tts, dispatcher = Mock(), Mock(), Mock()
    llm.chat.side_effect = RuntimeError("private provider response")
    tts.synthesize.return_value = b"audio"
    dispatcher.available_tools.return_value = []
    result = asyncio.run(run_turn(b"", None, llm, tts, dispatcher, text="Tere"))
    assert result["reply"] == TURN_UNAVAILABLE["et"]
    assert result["text_heard"] == "Tere"
    assert result["input_status"] == "typed"
    assert result["fallback_used"] is True
    assert "private" not in str(result)


def test_grounded_missing_date_and_time_questions_are_allowed():
    from app.booking.tools import Dispatcher
    from app.telephone import ASK_DATE, ASK_TIME, CallTools

    state = CallTools(Dispatcher())
    for text in (ASK_DATE, ASK_TIME):
        assert state.guard_reply(text, []) == text


@pytest.mark.parametrize(
    "value", [None, True, {"private": "secret"}, RuntimeError("private-secret")]
)
def test_invalid_or_failed_provider_does_not_ask_caller_to_repeat(value):
    stt, llm, tts, dispatcher = Mock(), Mock(), Mock(), Mock()
    if isinstance(value, Exception):
        stt.transcribe.side_effect = value
    else:
        stt.transcribe.return_value = value
    tts.synthesize.return_value = b"audio"
    result = asyncio.run(run_turn(b"audio", stt, llm, tts, dispatcher))
    assert result["reply"] == STT_UNAVAILABLE["et"]
    assert result["input_status"] == "stt_unavailable"
    assert result["fallback_used"] is True
    assert "private" not in str(result)
    llm.chat.assert_not_called()
    dispatcher.available_tools.assert_not_called()
