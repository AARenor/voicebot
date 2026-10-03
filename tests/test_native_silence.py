"""Pinned native SSE parsing, guarded empty recovery and per-speech delivery."""

import asyncio
import json
from types import SimpleNamespace as NS
from unittest.mock import patch

import httpx
import pytest

pytest.importorskip("livekit.agents")
from livekit import rtc
from livekit.agents import AgentSession, llm, tts
from livekit.agents.voice.speech_handle import SpeechHandle
from livekit.agents.voice import io
from livekit.plugins import groq
from openai import AsyncOpenAI

from app.booking.tools import Dispatcher
from app.telephone import ASK_DATE_TIME, CallTools, MUTATION_REPLIES, UNKNOWN_REPLY
from app.worker import TelephoneAgent
from tests.test_demo_delivery import raw_prepared
from tests.test_demo_plan import LiveSlots
from tests.test_demo_plan import REQUEST


class UnusedTTS(tts.TTS):
    def __init__(self):
        super().__init__(
            capabilities=tts.TTSCapabilities(streaming=False),
            sample_rate=24000,
            num_channels=1,
        )

    def synthesize(self, *args, **kwargs):
        raise AssertionError("external TTS forbidden")


class Sink(io.AudioOutput):
    def __init__(self):
        super().__init__(
            label="fixture",
            capabilities=io.AudioOutputCapabilities(pause=False),
            sample_rate=24000,
        )
        self.pcm, self.duration = [], 0

    async def capture_frame(self, frame):
        await super().capture_frame(frame)
        self.pcm.append(bytes(frame.data))
        self.duration += frame.duration

    def flush(self):
        super().flush()
        self.on_playback_finished(playback_position=self.duration, interrupted=False)

    def clear_buffer(self):
        self.on_playback_finished(playback_position=self.duration, interrupted=True)


class SSE(httpx.AsyncByteStream):
    def __init__(self, chunks):
        self.data = (
            b"".join(b"data: " + json.dumps(c).encode() + b"\n\n" for c in chunks)
            + b"data: [DONE]\n\n"
        )

    async def __aiter__(self):
        for offset in range(0, len(self.data), 31):
            yield self.data[offset : offset + 31]


def chunk(delta=None, finish=None):
    return {
        "id": "fixture",
        "object": "chat.completion.chunk",
        "created": 1,
        "model": "openai/gpt-oss-20b",
        "choices": [{"index": 0, "delta": delta or {}, "finish_reason": finish}],
    }


@pytest.mark.parametrize(
    "mode",
    [
        "empty_stop",
        "empty_length",
        "usage_only",
        "complete_tool_length",
        "partial_tool_length",
        "tool_then_empty",
        "tool_then_text",
        "text",
    ],
)
@pytest.mark.parametrize("language", ["et", "en"])
def test_native_sse_empty_recovery_never_executes_truncated_tools(mode, language):
    async def run():
        requests, spoken, errors = [], [], []
        state = CallTools(Dispatcher(), language=language)
        agent = TelephoneAgent(state)

        async def handler(request):
            requests.append(json.loads(request.content))
            if (
                mode.startswith(("complete_tool", "partial_tool", "tool_then"))
                and len(requests) == 1
            ):
                args = '{"' if mode == "partial_tool_length" else "{}"
                finish = "length" if mode.endswith("length") else "tool_calls"
                chunks = [
                    chunk(
                        {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "fixture-tool",
                                    "type": "function",
                                    "function": {
                                        "name": "get_demo_profile",
                                        "arguments": args,
                                    },
                                }
                            ]
                        }
                    ),
                    chunk(finish=finish),
                ]
            elif mode in {"text", "tool_then_text"}:
                chunks = [
                    chunk({"content": "Hello!" if language == "en" else "Tere!"}),
                    chunk(finish="stop"),
                ]
            else:
                chunks = [chunk(finish="length" if mode == "empty_length" else "stop")]
                if mode == "usage_only":
                    chunks.append(
                        {
                            "id": "fixture",
                            "model": "openai/gpt-oss-20b",
                            "choices": [],
                            "usage": {
                                "prompt_tokens": 10,
                                "completion_tokens": 512,
                                "total_tokens": 522,
                            },
                        }
                    )
            return httpx.Response(
                200, headers={"Content-Type": "text/event-stream"}, stream=SSE(chunks)
            )

        async def synthesize(agent, text, settings):
            async for part in text:
                spoken.append(part)
            yield rtc.AudioFrame(b"\x10\x01" * 480, 24000, 1, 480)

        client = AsyncOpenAI(
            api_key="fixture",
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
            max_retries=0,
        )
        model = groq.LLM(
            model="openai/gpt-oss-20b",
            api_key="fixture",
            client=client,
            max_completion_tokens=512,
            parallel_tool_calls=False,
        )
        session = AgentSession(
            llm=model, tts=UnusedTTS(), turn_handling={"turn_detection": "manual"}
        )
        sink = Sink()
        session.output.audio = sink
        session.on("conversation_item_added", agent.on_conversation_item_added)
        session.on("error", lambda event: errors.append(event))
        with patch("livekit.agents.Agent.default.tts_node", synthesize):
            await session.start(agent=agent, record=False)
            try:
                speech = session.generate_reply(user_input="Soovin testbroneeringut.")
                await asyncio.wait_for(speech, 3)
                assert not speech.exception() and not errors
                assert spoken == [
                    ("Hello!" if language == "en" else "Tere!")
                    if mode in {"text", "tool_then_text"}
                    else (
                        "What date would you like for your test booking?"
                        if language == "en"
                        else ASK_DATE_TIME
                    )
                ]
                assert sink.pcm and any(sink.pcm[0])
                assert len(requests) == (2 if mode.startswith("tool_then") else 1)
                assert len(state.results) == (1 if mode.startswith("tool_then") else 0)
                assert all(
                    r["max_completion_tokens"] == 512
                    and r["reasoning_effort"] == "low"
                    and r["parallel_tool_calls"] is False
                    for r in requests
                )
            finally:
                await session.aclose()
                await model.aclose()
                await client.close()

    asyncio.run(run())


@pytest.mark.parametrize("state_kind", ["confirmed", "unknown", "rejected"])
def test_empty_recovery_preserves_guarded_outcome(state_kind):
    async def run():
        state = CallTools(Dispatcher())
        if state_kind == "confirmed":
            state.turn_mutation = "confirmed"
            expected = MUTATION_REPLIES["confirmed"]
        elif state_kind == "unknown":
            state._unknown_mutation()
            expected = UNKNOWN_REPLY
        else:
            state.results.append({"error": "not_owned"})
            expected = "Toiming ei õnnestunud; edu ei ole kinnitatud."

        async def empty(*args):
            if False:
                yield

        agent = TelephoneAgent(state)
        with patch("livekit.agents.Agent.default.llm_node", empty):
            parts = [p async for p in agent.llm_node(None, [], None)]
        assert parts == [ASK_DATE_TIME]

        async def text():
            for p in parts:
                yield p

        assert await agent.checked_reply(text()) == expected

    asyncio.run(run())


@pytest.mark.parametrize("error", [RuntimeError, asyncio.CancelledError])
def test_empty_recovery_propagates_failure_and_cancellation(error):
    async def run():
        async def fail(*args):
            raise error("fixture")
            yield

        agent = TelephoneAgent(CallTools(Dispatcher()))
        with patch("livekit.agents.Agent.default.llm_node", fail), pytest.raises(error):
            [p async for p in agent.llm_node(None, [], None)]

    asyncio.run(run())


def test_tool_chunk_is_preserved_without_spurious_question():
    async def run():
        tool = llm.ChatChunk(
            id="fixture",
            delta=llm.ChoiceDelta(
                role="assistant",
                tool_calls=[
                    llm.FunctionToolCall(
                        name="get_demo_profile", arguments="{}", call_id="fixture-tool"
                    )
                ],
            ),
        )

        async def tools(*args):
            yield tool

        agent = TelephoneAgent(CallTools(Dispatcher()))
        with patch("livekit.agents.Agent.default.llm_node", tools):
            assert [p async for p in agent.llm_node(None, [], None)] == [tool]

    asyncio.run(run())


@pytest.mark.parametrize("generated", [True, False])
@pytest.mark.parametrize("language", ["et", "en"])
def test_real_sdk_playback_delivers_only_the_preparation_before_new_consent(
    generated, language
):
    """say and generated speech emit SDK events in different orders."""

    async def run():
        requests = []

        def handler(request):
            requests.append(json.loads(request.content))
            n = len(requests)
            if (generated and n in (1, 3)) or (not generated and n == 1):
                name, args = (
                    ("plan_demo_booking", REQUEST)
                    if generated and n == 1
                    else ("confirm_slot_booking", {"hold_id": "backend-hold"})
                )
                chunks = [
                    chunk(
                        {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": f"fixture-{n}",
                                    "type": "function",
                                    "function": {
                                        "name": name,
                                        "arguments": json.dumps(args),
                                    },
                                }
                            ]
                        }
                    ),
                    chunk(finish="tool_calls"),
                ]
            else:
                chunks = [chunk({"content": "Tere!"}), chunk(finish="stop")]
            return httpx.Response(
                200, headers={"Content-Type": "text/event-stream"}, stream=SSE(chunks)
            )

        async def synthesize(agent, text, settings):
            async for _ in text:
                pass
            yield rtc.AudioFrame(b"\x10\x01" * 480, 24000, 1, 480)

        client = AsyncOpenAI(
            api_key="fixture",
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
            max_retries=0,
        )
        model = groq.LLM(
            api_key="fixture",
            client=client,
            max_completion_tokens=512,
            parallel_tool_calls=False,
        )
        backend = LiveSlots()
        state = CallTools(Dispatcher(slot=backend), language=language)
        agent = TelephoneAgent(state)
        session = AgentSession(
            llm=model, tts=UnusedTTS(), turn_handling={"turn_detection": "manual"}
        )
        sink = Sink()
        session.output.audio = sink
        session.on("conversation_item_added", agent.on_conversation_item_added)
        with patch("livekit.agents.Agent.default.tts_node", synthesize):
            await session.start(agent=agent, record=False)
            try:
                request = (
                    "I would like a test booking."
                    if language == "en"
                    else "Soovin testbroneeringut."
                )
                consent = "Yes, I confirm." if language == "en" else "Jah, kinnitan."
                state.observe_user_text(request)
                if generated:
                    await asyncio.wait_for(
                        session.generate_reply(user_input=request), 3
                    )
                else:
                    assert (await state.dispatch("plan_demo_booking", REQUEST))["ok"]
                    await asyncio.wait_for(session.say(state.render_recap()), 3)
                assert sink.pcm and state.pending["delivery"], (
                    "completed native PCM did not deliver its recap"
                )
                assert not state.pending["approved"] and not state.bookings
                state.observe_user_text(consent)
                await asyncio.wait_for(session.generate_reply(user_input=consent), 3)
                assert state.bookings == {"42"}
                assert sum(name == "confirm" for name, _ in backend.calls) == 1
                assert len(requests) == (4 if generated else 2)
            finally:
                await session.aclose()
                await model.aclose()
                await client.close()

    asyncio.run(run())


@pytest.mark.parametrize("interrupted", [False, True])
def test_late_recap_item_cannot_deliver_new_identical_preparation_or_consume_its_speech(
    interrupted,
):
    async def run():
        state = CallTools(Dispatcher(slot=LiveSlots()))
        await raw_prepared(state)
        agent = TelephoneAgent(state)
        canonical = state.render_recap()
        first, second = SpeechHandle.create(), SpeechHandle.create()

        async def text():
            yield "Tere!"

        async def synthesize(agent, text, settings):
            async for _ in text:
                pass
            yield rtc.AudioFrame(b"\x10\x01" * 480, 24000, 1, 480)

        with patch("livekit.agents.Agent.default.tts_node", synthesize):
            with patch.object(agent, "_current_speech", return_value=first):
                assert [f async for f in agent.tts_node(text(), None)]
            await state.dispatch("prepare_demo_booking", {"hold_id": "backend-hold"})
            pending = state.pending
            with patch.object(agent, "_current_speech", return_value=second):
                assert [f async for f in agent.tts_node(text(), None)]
        first_item = llm.ChatMessage(
            role="assistant", content=[canonical], interrupted=interrupted
        )
        first._item_added([first_item])
        agent.on_conversation_item_added(NS(item=first_item))
        assert state.pending is pending and not pending["delivery"], (
            "stale speech authorized new identical recap"
        )
        second_item = llm.ChatMessage(role="assistant", content=[canonical])
        second._item_added([second_item])
        agent.on_conversation_item_added(NS(item=second_item))
        assert pending["delivery"] and not pending["approved"]
        state.observe_user_text("Jah, kinnitan.")
        assert pending["approved"]
        assert not first._item_added_callbacks and not second._item_added_callbacks

    asyncio.run(run())
