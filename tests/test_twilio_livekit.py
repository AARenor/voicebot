"""Native SDK contract tests replace only room/API/track network resources."""

import asyncio
import base64
import json
import re
import struct
from types import SimpleNamespace
from unittest.mock import patch

import pytest

pytest.importorskip("livekit.rtc")
from livekit import api, rtc
from tests.test_twilio_bridge import bridge
from tests.test_twilio_security import ACCOUNT, CALL, ENV, STREAM, security


class Transport:
    def __init__(self, fail=None):
        self.events, self.fail, self.callbacks, self.frames = [], fail, {}, []
        self.room = SimpleNamespace(
            local_participant=SimpleNamespace(
                publish_track=self.publish, unpublish_track=self.unpublish
            ),
            on=self.on,
            connect=self.connect,
            disconnect=self.disconnect,
        )
        self.client = SimpleNamespace(
            room=SimpleNamespace(create_room=self.create, delete_room=self.delete),
            agent_dispatch=SimpleNamespace(create_dispatch=self.dispatch),
            aclose=self.api_close,
        )

    def on(self, event, callback):
        self.callbacks[event] = callback

    async def create(self, request):
        self.events.append(("create", request))

    async def delete(self, request):
        self.events.append(("delete", request))

    async def dispatch(self, request):
        self.events.append(("dispatch", request))

    async def connect(self, url, credential, **kwargs):
        payload = credential.split(".")[1]
        self.grants = json.loads(
            base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))
        )
        self.events.append(("connect", url))
        if self.fail == "connect":
            raise RuntimeError("PRIVATE connect failure")

    async def disconnect(self):
        self.events.append(("disconnect", None))

    async def publish(self, track, options):
        self.events.append(("publish", options))
        return SimpleNamespace(sid="TRfixture")

    async def unpublish(self, sid):
        self.events.append(("unpublish", sid))
        if self.fail == "unpublish":
            raise RuntimeError("PRIVATE teardown failure")

    async def api_close(self):
        self.events.append(("api_close", None))

    def source(self, rate, channels, **kwargs):
        assert (rate, channels, kwargs["queue_size_ms"]) == (8000, 1, 100)

        async def capture(frame):
            assert frame.sample_rate == 8000 and frame.num_channels == 1
            self.frames.append(bytes(frame.data))

        async def close():
            self.events.append(("source_close", None))

        return SimpleNamespace(capture_frame=capture, aclose=close)


def sdk(transport):
    from contextlib import ExitStack

    stack = ExitStack()

    def connect_api(**kwargs):
        assert kwargs.get("failover") is False, (
            "agent dispatch may be automatically retried"
        )
        return transport.client

    stack.enter_context(patch.object(api, "LiveKitAPI", side_effect=connect_api))
    stack.enter_context(patch.object(rtc, "Room", return_value=transport.room))
    stack.enter_context(patch.object(rtc, "AudioSource", side_effect=transport.source))
    stack.enter_context(
        patch.object(
            rtc.LocalAudioTrack, "create_audio_track", return_value=SimpleNamespace()
        )
    )
    return stack


class Sender:
    def __init__(self):
        self.pcm, self.clears = [], 0

    async def audio(self, data, *, native=False):
        self.pcm.append(data)

    async def clear(self):
        self.clears += 1


def test_native_room_dispatch_and_microphone_are_individually_owned():
    b = bridge()

    async def check():
        t, sender = Transport(), Sender()
        with sdk(t):
            call = b.LiveKitCall(security().Config.from_env(ENV), sender)
            await call.start()
            await call.feed(struct.pack("<h", 1000) * 160)
            room = t.events[0][1].name
            assert re.fullmatch(r"voicebot-twilio-[a-f0-9]{32}", room)
            created = t.events[0][1]
            assert created.max_participants == 2 and created.empty_timeout <= 30
            dispatch = next(r for name, r in t.events if name == "dispatch")
            assert dispatch.room == room and dispatch.agent_name == "voicebot"
            assert ACCOUNT not in dispatch.metadata and CALL not in dispatch.metadata
            assert t.grants["video"]["room"] == room
            assert t.grants["video"]["canPublishSources"] == ["microphone"]
            assert t.grants["video"].get("roomAdmin") is not True
            assert t.frames == [struct.pack("<h", 1000) * 160]
            await call.close()
            deletes = [r.room for name, r in t.events if name == "delete"]
            assert deletes == [room]
            assert {"source_close", "disconnect", "api_close", "unpublish"} <= {
                name for name, _ in t.events
            }
            await call.close()
            assert len([r for name, r in t.events if name == "delete"]) == 1

    asyncio.run(check())


def test_native_clear_discards_sdk_queued_audio_without_ending_call():
    b = bridge()

    class Stream:
        instances = []

        def __init__(self, **kwargs):
            assert kwargs["capacity"] == 1 and kwargs["frame_size_ms"] == 20
            self.queue, self.second_read = asyncio.Queue(maxsize=1), asyncio.Event()
            self.reads, self.closed, self.track = 0, False, kwargs["track"]
            self.instances.append(self)

        def __aiter__(self):
            return self

        async def __anext__(self):
            frame = await self.queue.get()
            self.reads += 1
            if self.reads == 2:
                self.second_read.set()
            return SimpleNamespace(frame=frame)

        def push(self, value):
            self.queue.put_nowait(
                rtc.AudioFrame(struct.pack("<h", value) * 160, 8000, 1, 160)
            )

        async def aclose(self):
            self.closed = True

    async def check():
        sent = []

        class Socket:
            async def send_json(self, message):
                sent.append(message)

        t, sender = Transport(), b.TwilioSender(Socket(), STREAM)
        with sdk(t), patch.object(rtc, "AudioStream", Stream):
            call = b.LiveKitCall(security().Config.from_env(ENV), sender)
            await call.start()
            agent = SimpleNamespace(kind=4, identity="native-agent")
            track = SimpleNamespace(kind=1)
            publication = SimpleNamespace(source=rtc.TrackSource.SOURCE_MICROPHONE)
            t.callbacks["track_subscribed"](track, publication, agent)
            old = call.stream
            try:
                old.push(1000)
                await asyncio.wait_for(sender.first_audio.wait(), 1)
                old.push(1000)
                await asyncio.wait_for(old.second_read.wait(), 1)
                old.push(
                    1000
                )  # SDK capacity-one queue, while the prior frame waits 20 ms.
                t.callbacks["data_received"](
                    SimpleNamespace(
                        topic="voicebot.interruption",
                        data=b"clear:" + b"a" * 32,
                        participant=agent,
                    )
                )
                await asyncio.wait_for(call.interruption, 1)
                await asyncio.sleep(0.03)  # Real sender pacing; no fake clock/sleep.
                audio_control = [m for m in sent if m["event"] in ("media", "clear")]
                assert [m["event"] for m in audio_control] == ["media", "clear"], (
                    "queued pre-clear SDK frame was sent after clear"
                )
                assert old.closed and len(Stream.instances) == 1
                t.callbacks["data_received"](
                    SimpleNamespace(
                        topic="voicebot.interruption",
                        data=b"resume:" + b"a" * 32,
                        participant=agent,
                    )
                )
                await asyncio.wait_for(call.interruption, 1)
                assert len(Stream.instances) == 2
                assert call.stream.track is track and not call.ended.is_set()
                call.stream.push(2000)
                async with asyncio.timeout(1):
                    while len([m for m in sent if m["event"] == "media"]) < 2:
                        await asyncio.sleep(0.001)
                audio = [m["media"]["payload"] for m in sent if m["event"] == "media"]
                assert audio == [
                    base64.b64encode(
                        b.audioop.lin2ulaw(struct.pack("<h", v) * 160, 2)
                    ).decode()
                    for v in (1000, 2000)
                ]
            finally:
                current = call.stream
                await call.close()
                assert current.closed

    asyncio.run(check())


def test_only_first_audible_native_output_emits_fixed_provenance_mark():
    b = bridge()

    class Stream:
        def __init__(self, **kwargs):
            self.closed = False

        def __aiter__(self):
            return self.frames()

        async def frames(self):
            for value in (0, 1000, 2000):
                yield SimpleNamespace(
                    frame=rtc.AudioFrame(struct.pack("<h", value) * 160, 8000, 1, 160)
                )
            await asyncio.Event().wait()

        async def aclose(self):
            self.closed = True

    async def check():
        sent, ready = [], asyncio.Event()

        class Socket:
            async def send_json(self, message):
                sent.append(message)
                if len([m for m in sent if m["event"] == "media"]) == 3:
                    ready.set()

        t, sender = Transport(), b.TwilioSender(Socket(), STREAM)
        with sdk(t), patch.object(rtc, "AudioStream", Stream):
            call = b.LiveKitCall(security().Config.from_env(ENV), sender)
            await call.start()
            agent = SimpleNamespace(kind=4, identity="native-agent")
            t.callbacks["track_subscribed"](
                SimpleNamespace(kind=1),
                SimpleNamespace(source=rtc.TrackSource.SOURCE_MICROPHONE),
                agent,
            )
            try:
                await asyncio.wait_for(ready.wait(), 1)
                assert [m["event"] for m in sent] == ["media", "media", "mark", "media"]
                assert [m for m in sent if m["event"] == "mark"] == [
                    {
                        "event": "mark",
                        "streamSid": STREAM,
                        "mark": {"name": "voicebot-native-audio"},
                    }
                ]
            finally:
                await call.close()

    asyncio.run(check())


@pytest.mark.parametrize("closing", ["failure", "call_close"])
def test_interruption_reset_failure_or_concurrent_close_never_recreates_stream(closing):
    b = bridge()

    async def check():
        entered, created = asyncio.Event(), []

        class Stream:
            def __init__(self, **kwargs):
                self.closes = 0
                created.append(self)

            def __aiter__(self):
                return self

            async def __anext__(self):
                await asyncio.Event().wait()

            async def aclose(self):
                self.closes += 1
                entered.set()
                if closing == "failure":
                    raise RuntimeError("PRIVATE stream close failure")
                if self.closes == 1:
                    await asyncio.Event().wait()

        t, sender = Transport(), Sender()
        with sdk(t), patch.object(rtc, "AudioStream", Stream):
            call = b.LiveKitCall(security().Config.from_env(ENV), sender)
            await call.start()
            agent = SimpleNamespace(kind=4, identity="native-agent")
            t.callbacks["track_subscribed"](
                SimpleNamespace(kind=1),
                SimpleNamespace(source=rtc.TrackSource.SOURCE_MICROPHONE),
                agent,
            )
            t.callbacks["data_received"](
                SimpleNamespace(
                    topic="voicebot.interruption",
                    data=b"clear:" + b"a" * 32,
                    participant=agent,
                )
            )
            await asyncio.wait_for(entered.wait(), 1)
            if closing == "failure":
                await asyncio.wait_for(call.interruption, 1)
                assert call.ended.is_set()
            await asyncio.wait_for(call.close(), 1)
            assert len(created) == 1 and created[0].closes == 2
            assert call.output.done() and call.interruption.done()
            owned = next(
                request.name for event, request in t.events if event == "create"
            )
            assert [
                request.room for event, request in t.events if event == "delete"
            ] == [owned]

    asyncio.run(check())


@pytest.mark.parametrize("fail", ["connect", "unpublish"])
def test_partial_setup_or_cleanup_failure_still_deletes_only_own_room(fail):
    b = bridge()

    async def check():
        t = Transport(fail)
        with sdk(t):
            call = b.LiveKitCall(security().Config.from_env(ENV), Sender())
            if fail == "connect":
                with pytest.raises(RuntimeError):
                    await call.start()
            else:
                await call.start()
            await call.close()
            room = next(r.name for name, r in t.events if name == "create")
            assert [r.room for name, r in t.events if name == "delete"] == [room]
            assert {"disconnect", "api_close"} <= {name for name, _ in t.events}
            if fail == "unpublish":
                assert "source_close" in {name for name, _ in t.events}

    asyncio.run(check())


def test_only_native_agent_track_and_interruption_topic_reach_carrier():
    b = bridge()

    class Stream:
        def __init__(self, **kwargs):
            assert kwargs["sample_rate"] == 8000 and kwargs["num_channels"] == 1
            assert kwargs["capacity"] <= 2 and kwargs["frame_size_ms"] == 20
            self.closed = False

        def __aiter__(self):
            return self.frames()

        async def frames(self):
            yield SimpleNamespace(
                frame=rtc.AudioFrame(struct.pack("<h", 1000) * 160, 8000, 1, 160)
            )
            await asyncio.Event().wait()

        async def aclose(self):
            self.closed = True

    async def check():
        t, sender = Transport(), Sender()
        with sdk(t), patch.object(rtc, "AudioStream", Stream):
            call = b.LiveKitCall(security().Config.from_env(ENV), sender)
            await call.start()
            foreign = SimpleNamespace(kind=0, identity="foreign")
            agent = SimpleNamespace(kind=4, identity="native-agent")
            track = SimpleNamespace(kind=1)
            publication = SimpleNamespace(source=rtc.TrackSource.SOURCE_MICROPHONE)
            t.callbacks["track_subscribed"](track, publication, foreign)
            t.callbacks["data_received"](
                SimpleNamespace(
                    topic="voicebot.interruption", data=b"clear", participant=foreign
                )
            )
            await asyncio.sleep(0)
            assert sender.pcm == [] and sender.clears == 0
            t.callbacks["track_subscribed"](track, publication, agent)
            await asyncio.sleep(0.001)
            assert sender.pcm == [struct.pack("<h", 1000) * 160]
            for packet in [
                SimpleNamespace(topic="other", data=b"clear", participant=agent),
                SimpleNamespace(
                    topic="voicebot.interruption", data=b"PRIVATE", participant=agent
                ),
            ]:
                t.callbacks["data_received"](packet)
            await asyncio.sleep(0)
            assert sender.clears == 0
            t.callbacks["data_received"](
                SimpleNamespace(
                    topic="voicebot.interruption",
                    data=b"clear:" + b"a" * 32,
                    participant=agent,
                )
            )
            await asyncio.sleep(0.001)
            assert sender.clears == 1
            stream = call.stream
            await call.close()
            assert stream.closed

    asyncio.run(check())
