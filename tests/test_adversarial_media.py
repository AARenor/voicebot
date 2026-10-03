"""Real native API contracts with isolated media resources; never a phone call."""

import asyncio
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock, patch

import pytest

pytest.importorskip("livekit.agents")
from livekit import rtc  # noqa: E402
from app import worker as w  # noqa: E402
from tests.test_twilio_livekit import Sender, Transport, sdk  # noqa: E402
from tests.test_twilio_security import ENV, security  # noqa: E402
from app import twilio_bridge as b  # noqa: E402


@pytest.mark.parametrize("failure", ["publish", "unpublish", None])
def test_failure_audio_is_microphone_and_source_closes_on_every_path(failure):
    async def run():
        source = NS(
            capture_frame=AsyncMock(), wait_for_playout=AsyncMock(), aclose=AsyncMock()
        )
        publication = NS(sid="fixture", wait_for_subscription=AsyncMock())
        participant = NS(
            publish_track=AsyncMock(return_value=publication),
            unpublish_track=AsyncMock(),
        )
        if failure == "publish":
            participant.publish_track.side_effect = RuntimeError("fixture")
        elif failure == "unpublish":
            participant.unpublish_track.side_effect = RuntimeError("fixture")
        with (
            patch.object(rtc, "AudioSource", return_value=source),
            patch.object(rtc.LocalAudioTrack, "create_audio_track", return_value=NS()),
        ):
            try:
                await w.play_failure(NS(local_participant=participant))
            except RuntimeError:
                assert failure is not None
        source.aclose.assert_awaited_once()
        published = participant.publish_track.call_args
        options = published.kwargs.get(
            "options",
            published.args[1] if len(published.args) > 1 else rtc.TrackPublishOptions(),
        )
        assert options.source == rtc.TrackSource.SOURCE_MICROPHONE

    asyncio.run(run())


@pytest.mark.parametrize(
    "kind", ["tts_error", "empty_audio", "confirmed", "unknown", "partial"]
)
@pytest.mark.parametrize("language", ["et", "en"])
def test_cached_apology_history_matches_actual_audio(kind, language):
    from livekit.agents import AgentSession, tts
    from livekit.agents.voice import io
    from app.booking.tools import Dispatcher
    from app.telephone import CallTools, FALLBACK, GREETING

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
            self.on_playback_finished(
                playback_position=self.duration, interrupted=False
            )

        def clear_buffer(self):
            self.on_playback_finished(playback_position=self.duration, interrupted=True)

    async def run():
        async def fail(*args):
            if kind == "partial":
                yield rtc.AudioFrame(b"\x10\x01" * 480, 24000, 1, 480)
            if kind != "empty_audio":
                raise RuntimeError("fixture TTS failure")

        agent = w.TelephoneAgent(CallTools(Dispatcher(), language=language))
        fallback = (
            "Sorry, the service is unavailable. Please try again later."
            if language == "en"
            else FALLBACK
        )
        if kind == "confirmed":
            agent.state.turn_mutation = "confirmed"
        elif kind == "unknown":
            agent.state._unknown_mutation()
        session = AgentSession(
            tts=UnusedTTS(), turn_handling={"turn_detection": "manual"}
        )
        sink, messages = Sink(), []
        session.output.audio = sink
        session.on("conversation_item_added", agent.on_conversation_item_added)
        session.on("conversation_item_added", lambda event: messages.append(event.item))
        with patch("livekit.agents.Agent.default.tts_node", fail):
            await session.start(agent=agent, record=False)
            try:
                await asyncio.wait_for(session.say(GREETING), 3)
                expected = b"".join(
                    [bytes(frame.data) async for frame in w.fallback_audio(language)]
                )
                if kind == "partial":
                    expected = b"\x10\x01" * 480 + expected
                assert b"".join(sink.pcm) == expected
                await asyncio.sleep(0)
                assistant = [
                    item
                    for item in messages
                    if getattr(item, "role", None) == "assistant"
                ]
                assert len(assistant) == 1
                assert assistant[0].text_content == fallback
                assert agent.chat_ctx.items[-1].text_content == fallback
                assert session.history.items[-1].text_content == fallback
                assert [
                    item.text_content
                    for item in session.history.items
                    if getattr(item, "role", None) == "assistant"
                ] == [fallback]
            finally:
                await session.aclose()

    asyncio.run(run())


def test_old_failed_speech_cannot_replace_a_later_response():
    from livekit.agents import llm
    from app.booking.tools import Dispatcher
    from app.telephone import CallTools, GREETING

    agent = w.TelephoneAgent(CallTools(Dispatcher()))
    agent._fallback_reply = GREETING
    agent._fallback_speech = object()
    session = NS(current_speech=object())
    item = llm.ChatMessage(role="assistant", content=[GREETING])
    with patch.object(w.TelephoneAgent, "session", property(lambda _: session)):
        agent.on_conversation_item_added(NS(item=item))
    assert item.text_content == GREETING


def test_native_output_failure_keeps_failure_reason_for_carrier_handler():
    async def run():
        async def frames():
            yield NS(frame=rtc.AudioFrame(bytes(320), 16000, 1, 160))

        call = b.LiveKitCall(security().Config.from_env(ENV), Sender())
        call.stream = frames()
        await call._output()
        assert call.ended.is_set()
        assert getattr(call, "failed", False)

    asyncio.run(run())


def test_unpublished_original_microphone_does_not_hang_up_before_fallback():
    async def run():
        async def ended_stream():
            if False:
                yield

        call = b.LiveKitCall(security().Config.from_env(ENV), Sender())
        call.stream = ended_stream()
        await call._output()
        assert not call.ended.is_set(), (
            "track retirement was treated as participant hangup"
        )

    asyncio.run(run())


@pytest.mark.parametrize("reason", ["first_audio", "native_output"])
def test_failure_ends_carrier_before_slow_native_cleanup(reason):
    from tests.test_twilio_bridge import binding, connected, ws
    from tests.test_twilio_client import TestClient, WebSocketDisconnect
    from tests.test_twilio_security import start

    closed_before_cleanup, fallback = [], []

    class Native:
        def __init__(self, config, sender):
            self.sender, self.ended = sender, asyncio.Event()
            self.failed = reason == "native_output"

        async def start(self):
            if self.failed:
                self.ended.set()

        async def feed(self, pcm):
            pass

        async def close(self):
            closed_before_cleanup.append(self.sender.socket.closed)

    async def apology(sender):
        fallback.append(True)

    with (
        patch.dict("os.environ", ENV, clear=True),
        patch.object(b, "LiveKitCall", Native),
        patch.object(b, "FIRST_AUDIO_TIMEOUT", 0.01),
        patch.object(b.TwilioSender, "failure", apology),
    ):
        with TestClient(b.create_app()) as client:
            nonce = binding(client)
            with ws(client) as socket:
                socket.send_json(connected())
                socket.send_json(start(nonce))
                with pytest.raises(WebSocketDisconnect) as ended:
                    socket.receive_json()
                assert ended.value.code == 1011
            assert fallback == [True]
            assert closed_before_cleanup and all(closed_before_cleanup)
            assert client.app.state.bindings.active_count == 0


def test_fatal_initialization_failure_closes_allocated_adapter_and_owned_room():
    async def run():
        adapter = NS(close=AsyncMock())
        ctx = NS(
            connect=AsyncMock(),
            room=NS(name="fixture"),
            api=NS(room=NS(delete_room=AsyncMock())),
            shutdown=Mock(),
        )
        with (
            patch.object(w, "validate_environment"),
            patch.dict(
                w.os.environ,
                {
                    "EASY_BASE_URL": "http://fixture.invalid",
                    "EASY_API_KEY": "fixture",
                    "GROQ_API_KEY": "fixture",
                    "AZURE_SPEECH_KEY": "fixture",
                    "AZURE_REGION": "fixture",
                    "EASY_STATE_DB": "unused-fixture",
                },
                clear=True,
            ),
            patch.object(w, "EasyAppointmentsAdapter", return_value=adapter),
            patch.object(w.groq, "STT"),
            patch.object(w.groq, "LLM"),
            patch.object(
                w.azure, "TTS", side_effect=RuntimeError("fixture constructor")
            ),
            patch.object(w, "play_failure", new=AsyncMock()),
        ):
            await w.entrypoint(ctx)
        adapter.close.assert_awaited_once()
        ctx.api.room.delete_room.assert_awaited_once()
        ctx.shutdown.assert_called_once()

    asyncio.run(run())


def test_docker_grace_budgets_native_shutdown_not_just_server_drain():
    import yaml

    root = Path(__file__).resolve().parents[1]
    worker = yaml.safe_load((root / "deploy/telephony/compose.yaml").read_text())[
        "services"
    ]["worker"]
    grace = int(worker["stop_grace_period"].removesuffix("s"))
    # Pinned native job waits 15s BEFORE cancelling entrypoint; cleanup has
    # three independently bounded 5s closes, plus failure-audio budget.
    assert w.server._shutdown_process_timeout >= 15 + 15 + 5
    assert grace >= w.server._drain_timeout + 2 * w.server._shutdown_process_timeout + 5
    bridge = yaml.safe_load(
        (root / "deploy/telephony/twilio-compose.yaml").read_text()
    )["services"]["twilio-bridge"]
    assert (
        worker["environment"]["VOICEBOT_AGENT_NAME"]
        == bridge["environment"]["VOICEBOT_AGENT_NAME"]
    )


def test_clear_is_prompt_but_resume_waits_for_native_interruption_completion():
    async def run():
        interrupted = asyncio.get_running_loop().create_future()
        events, ready = [], asyncio.Event()

        async def publish(data, **kwargs):
            events.append(data)
            ready.set()

        room = NS(local_participant=NS(publish_data=publish))
        session = NS(interrupt=Mock(return_value=interrupted), current_speech=None)
        task = w.on_user_state(session, NS(new_state="speaking"), room=room)
        await ready.wait()
        assert len(events) == 1 and events[0].startswith(b"clear:")
        assert not task.done()
        interrupted.set_result(None)
        await task
        assert events[1] == events[0].replace(b"clear:", b"resume:", 1)

    asyncio.run(run())


def test_failed_native_interruption_never_resumes_old_audio():
    async def run():
        interrupted = asyncio.get_running_loop().create_future()
        interrupted.set_exception(RuntimeError("fixture failure"))
        publish = AsyncMock()
        await w.publish_interruption(
            NS(local_participant=NS(publish_data=publish)), interrupted
        )
        data = [args.args[0] for args in publish.await_args_list]
        assert len(data) == 2 and data[0].startswith(b"clear:")
        assert data[1] == data[0].replace(b"clear:", b"failed:", 1)

    asyncio.run(run())


@pytest.mark.parametrize("failure", ["timeout", "cancelled"])
def test_interruption_future_timeout_or_cancellation_signals_terminal_failure(failure):
    async def run():
        future = asyncio.get_running_loop().create_future()
        if failure == "cancelled":
            future.cancel()
        publish = AsyncMock()
        original = asyncio.wait_for

        async def bounded(awaitable, timeout):
            return await original(awaitable, min(timeout, 0.01))

        with patch.object(w.asyncio, "wait_for", bounded):
            await w.publish_interruption(
                NS(local_participant=NS(publish_data=publish)), future
            )
        data = [args.args[0] for args in publish.await_args_list]
        assert len(data) == 2 and data[1].startswith(b"failed:")
        if failure == "timeout":
            assert not future.cancelled()

    asyncio.run(run())


@pytest.mark.parametrize("scenario", ["late_clear", "close_pending"])
def test_terminal_fallback_rejects_retired_mic_controls_and_close_cancels_predecessors(
    scenario,
):
    async def run():
        entered, release = asyncio.Event(), asyncio.Event()

        class Stream:
            def __init__(self, **kwargs):
                self.track, self.closed = kwargs["track"], False

            def __aiter__(self):
                return self

            async def __anext__(self):
                await asyncio.Event().wait()

            async def aclose(self):
                self.closed = True

        class Blocked(Sender):
            async def clear(self):
                self.clears += 1
                if self.clears == 1:
                    entered.set()
                    await release.wait()

        transport, sender = Transport(), Blocked()
        with (
            sdk(transport),
            patch.object(rtc, "AudioStream", Stream),
            patch.object(b, "CLOSE_TIMEOUT", 0.05),
        ):
            call = b.LiveKitCall(security().Config.from_env(ENV), sender)
            await call.start()
            agent = NS(kind=4, identity="fixture-agent")
            mic = NS(source=rtc.TrackSource.SOURCE_MICROPHONE)
            call._on_track(NS(kind=1, name="microphone"), mic, agent)

            def packet():
                return NS(
                    topic="voicebot.interruption",
                    data=b"clear:" + b"a" * 32,
                    participant=agent,
                )

            if scenario == "late_clear":
                call._on_track(NS(kind=1, name="voicebot-fallback"), mic, agent)
            else:
                call._on_data(packet())
            predecessor = call.interruption
            await entered.wait()
            call._on_data(packet())
            if scenario == "close_pending":
                await call.close()
                assert predecessor.done(), (
                    "older control task survived owned call cleanup"
                )
            else:
                release.set()
                await call.interruption
                assert not call.failed and not call.ended.is_set()
                assert not call.output.done()
                assert call.stream.track.name == "voicebot-fallback"
                await call.close()

    asyncio.run(run())


def test_bridge_rejects_old_generation_until_matching_native_resume():
    async def run():
        created = []

        class Stream:
            def __init__(self, **kwargs):
                self.track, self.closed = kwargs["track"], False
                self.queue = asyncio.Queue()
                created.append(self)

            def __aiter__(self):
                return self

            async def __anext__(self):
                return await self.queue.get()

            async def aclose(self):
                self.closed = True

        transport, sender = Transport(), Sender()
        with sdk(transport), patch.object(rtc, "AudioStream", Stream):
            call = b.LiveKitCall(security().Config.from_env(ENV), sender)
            await call.start()
            agent = NS(kind=4, identity="fixture-agent")
            call._on_track(
                NS(kind=1), NS(source=rtc.TrackSource.SOURCE_MICROPHONE), agent
            )
            old = call.stream

            def packet(command, generation):
                return NS(
                    topic="voicebot.interruption",
                    data=command + b":" + generation,
                    participant=agent,
                )

            generation = b"a" * 32
            call._on_data(packet(b"clear", generation))
            await call.interruption
            old.queue.put_nowait(NS(frame=rtc.AudioFrame(bytes(320), 8000, 1, 160)))
            assert old.closed and len(created) == 1
            assert sender.pcm == []
            call._on_data(packet(b"resume", b"b" * 32))
            await asyncio.sleep(0)
            assert len(created) == 1
            call._on_data(packet(b"resume", generation))
            await call.interruption
            assert len(created) == 2
            await call.close()

    asyncio.run(run())


def test_bound_agent_fallback_replaces_microphone_but_foreign_tracks_do_not():
    async def run():
        created = []

        class Stream:
            def __init__(self, **kwargs):
                self.track, self.closed = kwargs["track"], False
                created.append(self)

            def __aiter__(self):
                return self

            async def __anext__(self):
                await asyncio.Event().wait()

            async def aclose(self):
                self.closed = True

        transport = Transport()
        with sdk(transport), patch.object(rtc, "AudioStream", Stream):
            call = b.LiveKitCall(security().Config.from_env(ENV), Sender())
            await call.start()
            agent = NS(kind=4, identity="fixture-agent")
            mic = NS(source=rtc.TrackSource.SOURCE_MICROPHONE)
            first = NS(kind=1, name="microphone")
            call._on_track(first, mic, agent)
            old = call.stream
            replacement = NS(kind=1, name="voicebot-fallback")
            call._on_track(replacement, mic, NS(kind=4, identity="foreign-agent"))
            assert call.agent_track is first
            call._on_track(NS(kind=1, name="unapproved"), mic, agent)
            assert call.agent_track is first
            call._on_track(replacement, mic, agent)
            try:
                async with asyncio.timeout(1):
                    while call.agent_track is first:
                        await asyncio.sleep(0)
                assert old.closed
                assert call.stream.track is replacement
                assert len(created) == 2
            finally:
                await call.close()

    asyncio.run(run())
