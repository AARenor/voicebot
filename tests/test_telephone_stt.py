"""Actual LiveKit recognition requests using synthetic provider responses."""

import asyncio
from types import SimpleNamespace as NS
from unittest.mock import patch

import httpx
import pytest

pytest.importorskip("livekit.agents")
from livekit import rtc  # noqa: E402
from livekit.agents import APIError, APIConnectOptions  # noqa: E402

from app.languages import ENGLISH  # noqa: E402
from app.providers.telephone_stt import TelephoneSTT  # noqa: E402
from app.telephone import CallTools  # noqa: E402
from app.worker import TelephoneAgent  # noqa: E402
from tests.test_telephone import Slots  # noqa: E402


def audio_frame():
    return rtc.AudioFrame(
        data=bytes(3200), sample_rate=16000, num_channels=1, samples_per_channel=1600
    )


@pytest.mark.parametrize(
    "reported,expected",
    [("english", "en"), ("estonian", "et"), ("en-US", "en"), ("et", "et")],
)
def test_auto_stt_omits_hint_and_preserves_provider_language(reported, expected):
    async def run():
        seen = []

        def respond(request):
            seen.append(request)
            return httpx.Response(
                200, json={"text": "Hello there", "language": reported}
            )

        provider = TelephoneSTT(
            api_key="fixture",
            model="whisper-large-v3",
            transport=httpx.MockTransport(respond),
        )
        try:
            event = await provider.recognize(
                audio_frame(), conn_options=APIConnectOptions(max_retry=0)
            )
            assert str(event.alternatives[0].language) == expected
            assert event.alternatives[0].text == "Hello there"
            body = seen[0].content
            assert b"verbose_json" in body and b"whisper-large-v3" in body
            assert b'name="language"' not in body and b'name="prompt"' not in body
            assert b"RIFF" in body and b"Yes, I confirm" not in body
        finally:
            await provider.aclose()
        assert provider._http.is_closed

    asyncio.run(run())


@pytest.mark.parametrize("mode", ["en", "et"])
def test_fixed_mode_sends_explicit_accuracy_hint(mode):
    async def run():
        seen = []

        def respond(request):
            seen.append(request)
            return httpx.Response(200, json={"text": "Hello", "language": "english"})

        provider = TelephoneSTT(
            api_key="fixture",
            model="whisper-large-v3",
            mode=mode,
            transport=httpx.MockTransport(respond),
        )
        try:
            event = await provider.recognize(
                audio_frame(), conn_options=APIConnectOptions(max_retry=0)
            )
            assert str(event.alternatives[0].language) == mode
            assert ('name="language"\r\n\r\n' + mode).encode() in seen[0].content
        finally:
            await provider.aclose()

    asyncio.run(run())


@pytest.mark.parametrize(
    "payload",
    [
        {"text": "Hello"},
        {"text": 42, "language": "english"},
        {"text": "Hello", "language": ""},
        {"text": "Hello", "language": None},
        {"text": "Hello", "language": "english", "segments": "private"},
    ],
)
def test_malformed_language_results_fail_without_guessing(payload):
    async def run():
        provider = TelephoneSTT(
            api_key="fixture",
            model="whisper-large-v3",
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload)),
        )
        try:
            with pytest.raises(APIError):
                await provider.recognize(
                    audio_frame(), conn_options=APIConnectOptions(max_retry=0)
                )
        finally:
            await provider.aclose()

    asyncio.run(run())


def test_silence_hallucination_cannot_fabricate_a_consent_transcript():
    async def run():
        payload = {
            "text": "Yes, I confirm.",
            "language": "english",
            "segments": [{"no_speech_prob": 0.97, "avg_logprob": -1.5}],
        }
        provider = TelephoneSTT(
            api_key="fixture",
            model="whisper-large-v3",
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload)),
        )
        try:
            event = await provider.recognize(
                audio_frame(), conn_options=APIConnectOptions(max_retry=0)
            )
            assert event.alternatives[0].text == ""
        finally:
            await provider.aclose()

    asyncio.run(run())


def test_unsupported_language_asks_supported_language_and_blocks_tools():
    async def run():
        provider = TelephoneSTT(
            api_key="fixture",
            model="whisper-large-v3",
            transport=httpx.MockTransport(
                lambda _: httpx.Response(
                    200, json={"text": "Bonjour", "language": "french"}
                )
            ),
        )
        try:
            event = await provider.recognize(
                audio_frame(), conn_options=APIConnectOptions(max_retry=0)
            )
        finally:
            await provider.aclose()
        assert event.alternatives[0].metadata == {"unsupported_language": True}
        state = CallTools(Slots(), language="en")
        agent = TelephoneAgent(state)

        async def events(*args):
            yield event

        with patch("livekit.agents.Agent.default.stt_node", events):
            assert len([ev async for ev in agent.stt_node(None, None)]) == 1
        await agent.on_user_turn_completed(
            None, NS(role="user", text_content="Bonjour")
        )
        assert state.guard_reply("Anything", []) == ENGLISH["unsupported"]
        assert (await state.dispatch("get_slot_catalogue", {}))[
            "error"
        ] == "clarification_required"
        assert not state.dispatcher.calls
        state.observe_user_text("English please")
        assert not state.unsupported_language

    asyncio.run(run())


@pytest.mark.parametrize("status", [401, 429, 503])
def test_provider_failures_never_expose_response_contents(status):
    async def run():
        provider = TelephoneSTT(
            api_key="fixture",
            model="whisper-large-v3",
            transport=httpx.MockTransport(
                lambda _: httpx.Response(status, text="PRIVATE response and key")
            ),
        )
        try:
            with pytest.raises(APIError) as error:
                await provider.recognize(
                    audio_frame(), conn_options=APIConnectOptions(max_retry=0)
                )
            assert "PRIVATE" not in str(error.value)
        finally:
            await provider.aclose()

    asyncio.run(run())


def test_disconnect_cancels_inflight_transcription_and_releases_client():
    async def run():
        entered = asyncio.Event()
        cancelled = asyncio.Event()

        async def respond(request):
            entered.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                raise

        provider = TelephoneSTT(
            api_key="fixture",
            model="whisper-large-v3",
            transport=httpx.MockTransport(respond),
        )
        task = asyncio.create_task(provider.recognize(audio_frame()))
        await asyncio.wait_for(entered.wait(), timeout=1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await provider.aclose()
        assert cancelled.is_set() and provider._http.is_closed

    asyncio.run(run())
