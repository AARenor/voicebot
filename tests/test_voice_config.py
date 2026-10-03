"""Actual outbound provider settings and bounded native diagnostics, no network."""

import asyncio
import json
import logging
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest

from app.providers.errors import ProviderError
from app.providers.groq import GroqClient
from app.providers.voice_config import VoiceConfig


def test_environment_model_selection_reaches_actual_http_requests():
    seen = []

    def respond(request):
        seen.append(request)
        if request.url.path.endswith("transcriptions"):
            return httpx.Response(200, json={"text": "Jah, kinnitan."})
        return httpx.Response(200, json={"choices": [{"message": {"content": "Tere!"}}]})

    with patch.dict("os.environ", {
        "GROQ_CHAT_MODEL": "openai/gpt-oss-20b",
        "GROQ_STT_MODEL": "whisper-large-v3-turbo",
        "GROQ_MAX_COMPLETION_TOKENS": "3072",
    }, clear=True):
        client = GroqClient("fixture", transport=httpx.MockTransport(respond))
    try:
        client.transcribe(b"RIFF")
        client.chat([{"role": "user", "content": "Tere"}], tools=[{"type": "function"}])
    finally:
        client.close()
    assert b"whisper-large-v3-turbo" in seen[0].content
    assert b'name="language"\r\n\r\net\r\n' in seen[0].content
    body = json.loads(seen[1].content)
    assert body["model"] == "openai/gpt-oss-20b"
    assert body["max_completion_tokens"] == 3072
    assert body["reasoning_effort"] == "low"
    assert body["include_reasoning"] is False
    assert body["parallel_tool_calls"] is False


def test_override_for_non_reasoning_model_omits_unsupported_oss_options():
    body = None

    def respond(request):
        nonlocal body
        body = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "OK"}}]})

    client = GroqClient("fixture", transport=httpx.MockTransport(respond), config=VoiceConfig())
    try:
        client.chat([], model="llama-3.3-70b-versatile")
    finally:
        client.close()
    assert "reasoning_effort" not in body and "include_reasoning" not in body


def test_truncated_tool_completion_is_provider_failure():
    payload = {"choices": [{"finish_reason": "length", "message": {"tool_calls": []}}]}
    client = GroqClient("fixture", transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload)))
    try:
        with pytest.raises(ProviderError, match="incomplete completion") as caught:
            client.chat([])
        assert caught.value.reason == "completion_incomplete"
        assert caught.value.status_code == 200
    finally:
        client.close()


def test_provider_reasoning_is_not_retained_in_conversation():
    payload = {"choices": [{"message": {"content": "Tere!", "reasoning": "private reasoning"}}]}
    client = GroqClient("fixture", transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload)))
    try:
        assert client.chat([]) == {"content": "Tere!"}
    finally:
        client.close()


@pytest.mark.parametrize("env", [
    {"GROQ_CHAT_MODEL": "bad\nprivate value"},
    {"GROQ_STT_MODEL": "bad model"},
    {"GROQ_MAX_COMPLETION_TOKENS": "100"},
    {"GROQ_MAX_COMPLETION_TOKENS": "unbounded"},
])
def test_invalid_model_settings_fail_before_paid_provider_requests(env):
    with pytest.raises(ValueError, match="invalid voice"):
        VoiceConfig.from_env(env)


def test_native_startup_uses_same_models_and_room_journal(tmp_path):
    pytest.importorskip("livekit.agents")
    from app import worker

    async def run():
        callbacks = {}
        session = NS(
            on=lambda name, fn: callbacks.update({name: fn}),
            aclose=AsyncMock(), say=lambda _: None,
        )

        async def start(**kwargs):
            callbacks["close"](None)

        session.start = start
        ctx = NS(
            proc=NS(userdata={"vad": object()}),
            room=NS(on=Mock(), name="fixture", local_participant=NS(set_attributes=AsyncMock())),
            connect=AsyncMock(), wait_for_participant=AsyncMock(),
            api=NS(room=NS(delete_room=AsyncMock())), shutdown=Mock(),
        )
        env = {
            "EASY_BASE_URL": "https://fixture.invalid", "EASY_API_KEY": "fixture",
            "EASY_STATE_DB": str(tmp_path / "easy-booking.db"), "EASY_DEMO_WRITES": "1",
            "GROQ_API_KEY": "fixture", "AZURE_SPEECH_KEY": "fixture", "AZURE_REGION": "fixture",
            "GROQ_CHAT_MODEL": "openai/gpt-oss-120b", "GROQ_STT_MODEL": "whisper-large-v3",
            "GROQ_MAX_COMPLETION_TOKENS": "2048",
        }
        with (
            patch.dict("os.environ", env, clear=True),
            patch.object(worker, "validate_environment"), patch.object(worker, "protect_logs"),
            patch.object(worker, "EasyAppointmentsAdapter", return_value=NS(close=AsyncMock())),
            patch.object(worker, "DemoStayAdapter") as stay,
            patch.object(worker, "AgentSession", return_value=session),
            patch.object(worker, "TelephoneAgent"), patch.object(worker.callslog, "log_call"),
            patch.object(worker, "TelephoneSTT", return_value=NS(aclose=AsyncMock())) as stt,
            patch.object(worker.groq, "LLM") as llm,
            patch.object(worker.azure, "TTS"),
        ):
            await worker.entrypoint(ctx)
        stay.assert_called_once_with(str(tmp_path / "stay-booking.db"))
        assert stt.call_args.kwargs["model"] == "whisper-large-v3"
        assert stt.call_args.kwargs["mode"] == "auto"
        assert llm.call_args.kwargs["model"] == "openai/gpt-oss-120b"
        assert llm.call_args.kwargs["max_completion_tokens"] == 2048
        assert llm.call_args.kwargs["reasoning_effort"] == "low"
        ctx.shutdown.assert_called_once()

    asyncio.run(run())


def test_native_latency_samples_are_bounded_and_have_no_provider_identifiers(caplog):
    pytest.importorskip("livekit.agents")
    from app.worker import VoiceMetrics

    metrics = VoiceMetrics()
    for _ in range(100):
        metrics.observe(NS(metrics=NS(type="llm_metrics", duration=0.1, ttft=0.02, request_id="PRIVATE")))
    metrics.observe(NS(metrics=NS(type="tts_metrics", duration=float("nan"), ttfb=-1)))
    metrics.observe_playback(NS(item=NS(role="assistant", metrics={"e2e_latency": 0.8})))
    with caplog.at_level(logging.INFO, logger="voicebot.telephone"):
        metrics.log_summary()
    assert len(metrics.samples["llm"]) == 60
    assert "samples=60 p50_ms=100 p95_ms=100" in caplog.text
    assert "reply_first_audio" in caplog.text and "800" in caplog.text
    assert "PRIVATE" not in caplog.text and "nan" not in caplog.text


def test_worker_failure_diagnostic_has_stage_without_exception_text(caplog):
    pytest.importorskip("livekit.agents")
    from app.worker import log_failure

    log_failure("session_start", RuntimeError("PRIVATE provider body"))
    assert "stage=session_start" in caplog.text
    assert "PRIVATE" not in caplog.text


def test_late_cached_fallback_does_not_relabel_another_speech():
    pytest.importorskip("livekit.agents")
    from app.booking.tools import Dispatcher
    from app.telephone import CallTools
    from app.worker import TelephoneAgent

    agent = TelephoneAgent(CallTools(Dispatcher()))
    agent._fallback_reply = "Tere!"
    agent._fallback_speech = object()
    current = object()
    message = NS(role="assistant", text_content="Tere!", content=["Tere!"], interrupted=False)
    with patch.object(agent, "_current_speech", return_value=current):
        agent.on_conversation_item_added(NS(item=message))
    assert message.content == ["Tere!"]


def test_twilio_diagnostics_retain_stage_without_remote_error_text(caplog):
    pytest.importorskip("aiohttp")
    from app.twilio_bridge import log_bridge_failure

    log_bridge_failure("native_setup", RuntimeError("PRIVATE participant and credentials"))
    assert "stage=native_setup code=error" in caplog.text
    assert "PRIVATE" not in caplog.text


def test_already_received_audio_does_not_timeout_when_deadline_task_starts_late():
    pytest.importorskip("aiohttp")
    from app import twilio_bridge

    async def run():
        sender = NS(first_audio=asyncio.Event())
        sender.first_audio.set()
        with patch.object(twilio_bridge, "FIRST_AUDIO_TIMEOUT", 0.01), patch.object(twilio_bridge, "CALL_TIMEOUT", 0.01):
            assert await twilio_bridge.call_deadline(sender, twilio_bridge.time.monotonic() - 0.02) == "duration_limit"

    asyncio.run(run())
