"""Twilio mu-law ↔ private LiveKit microphone; native worker owns the agent.

Run with the pinned Python 3.12 media image: python -m app.twilio_bridge.
No carrier account API, provider loop, recording, or caller/transcript storage.
"""

from __future__ import annotations

import asyncio
import audioop
import base64
import json
import logging
import re
import time
import uuid
import wave
from datetime import timedelta
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qsl
from xml.etree import ElementTree as ET

from aiohttp import web, WSMsgType

from .twilio_security import (
    Bindings,
    BridgeError,
    Config,
    FALLBACK_URL,
    MAX_PENDING,
    MEDIA_URL,
    NATIVE_AUDIO_MARK,
    VOICE_URL,
    authorize_start,
    authorized_call,
    valid_media_signature,
    valid_signature,
)

CALL_TIMEOUT = 600
FIRST_AUDIO_TIMEOUT = 45
HANDSHAKE_TIMEOUT = 5
SETUP_TIMEOUT = 15
IO_TIMEOUT = 2
CLOSE_TIMEOUT = 5
MAX_MESSAGE_BYTES = 4096
MAX_FORM_BYTES = 16384
FALLBACK_FILE = Path(__file__).parent / "audio" / "unavailable-et.wav"
STATE = web.AppKey("twilio_state", SimpleNamespace)


class BridgeDisconnected(Exception):
    pass


async def bounded_close(close):
    try:
        await asyncio.wait_for(close(), CLOSE_TIMEOUT)
    except (Exception, asyncio.CancelledError):
        # Independent resources must still be closed after any earlier failure.
        pass


def uint(value, maximum, *, minimum=0):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{1,8}", value):
        raise BridgeError("media_invalid")
    number = int(value)
    if not minimum <= number <= maximum:
        raise BridgeError("media_invalid")
    return number


class MediaProtocol:
    def __init__(self, account, call, stream, clock=time.monotonic):
        self.account, self.call, self.stream, self.clock = account, call, stream, clock
        self.started = clock()
        self.last_budget, self.sample_budget, self.message_budget = (
            self.started,
            8000.0,
            100.0,
        )
        self.sequence, self.chunk, self.timestamp, self.samples, self.messages = (
            1,
            0,
            0,
            0,
            0,
        )

    def accept(self, message):
        try:
            now = self.clock()
            elapsed, delta = now - self.started, max(0, now - self.last_budget)
            self.last_budget = now
            self.sample_budget = min(8000, self.sample_budget + 8000 * delta)
            self.message_budget = min(100, self.message_budget + 100 * delta) - 1
            self.messages += 1
            if (
                elapsed >= CALL_TIMEOUT
                or self.messages > 60000
                or self.message_budget < 0
            ):
                raise BridgeError("media_limit")
            if (
                message["streamSid"] != self.stream
                or uint(message["sequenceNumber"], 100000, minimum=1)
                != self.sequence + 1
            ):
                raise BridgeError("media_invalid")
            event = message["event"]
            result = None
            if event == "media":
                media = message["media"]
                chunk = uint(media["chunk"], 60000, minimum=1)
                timestamp = uint(media["timestamp"], 600000)
                if (
                    media["track"] != "inbound"
                    or chunk != self.chunk + 1
                    or timestamp < self.timestamp
                    or timestamp > 1000 * elapsed + 2000
                ):
                    raise BridgeError("media_invalid")
                payload = media["payload"]
                if not isinstance(payload, str) or not 1 <= len(payload) <= 2136:
                    raise BridgeError("media_invalid")
                decoded = base64.b64decode(payload, validate=True)
                if not 1 <= len(decoded) <= 1600:
                    raise BridgeError("media_invalid")
                self.samples += len(decoded)
                self.sample_budget -= len(decoded)
                if self.samples > 4800000 or self.sample_budget < 0:
                    raise BridgeError("media_limit")
                self.chunk, self.timestamp = chunk, timestamp
                result = audioop.ulaw2lin(decoded, 2)
            elif event == "stop":
                if (
                    message["stop"]["accountSid"] != self.account
                    or message["stop"]["callSid"] != self.call
                ):
                    raise BridgeError("media_invalid")
                result = "stop"
            elif event == "dtmf":
                dtmf = message["dtmf"]
                if dtmf["track"] != "inbound_track" or dtmf["digit"] not in tuple(
                    "0123456789*#ABCD"
                ):
                    raise BridgeError("media_invalid")
            elif event == "mark":
                name = message["mark"]["name"]
                if not isinstance(name, str) or not re.fullmatch(
                    r"[A-Za-z0-9_-]{1,64}", name
                ):
                    raise BridgeError("media_invalid")
            else:
                raise BridgeError("media_invalid")
            self.sequence += 1
            return result
        except (ValueError, TypeError, KeyError, AttributeError):
            raise BridgeError("media_invalid") from None


@lru_cache(maxsize=1)
def fallback_pcm():
    with wave.open(str(FALLBACK_FILE), "rb") as wav:
        if (
            wav.getsampwidth() != 2
            or wav.getnchannels() != 1
            or wav.getnframes() > wav.getframerate() * 10
        ):
            raise BridgeError("fallback_unavailable", 503)
        pcm = wav.readframes(wav.getnframes())
        return audioop.ratecv(pcm, 2, 1, wav.getframerate(), 8000, None)[0]


class TwilioSender:
    def __init__(self, socket, stream):
        self.socket, self.stream = socket, stream
        self.lock, self.first_audio = asyncio.Lock(), asyncio.Event()
        self.epoch, self.samples, self.clears, self.next_frame = 0, 0, 0, 0.0
        self.native_marked = False

    async def audio(self, pcm, *, native=False):
        if not isinstance(pcm, bytes) or not 2 <= len(pcm) <= 3200 or len(pcm) % 2:
            raise BridgeError("output_invalid")
        epoch = self.epoch
        for offset in range(0, len(pcm), 320):
            frame = pcm[offset : offset + 320]
            await asyncio.sleep(max(0, self.next_frame - time.monotonic()))
            async with self.lock:
                if epoch != self.epoch:
                    return
                self.samples += len(frame) // 2
                if self.samples > 4800000:
                    raise BridgeError("output_limit")
                message = {
                    "event": "media",
                    "streamSid": self.stream,
                    "media": {
                        "payload": base64.b64encode(audioop.lin2ulaw(frame, 2)).decode()
                    },
                }
                await asyncio.wait_for(self.socket.send_json(message), IO_TIMEOUT)
                self.next_frame = time.monotonic() + len(frame) / 16000
                if audioop.rms(frame, 2) > 32:
                    self.first_audio.set()
                    if native and not self.native_marked:
                        await asyncio.wait_for(
                            self.socket.send_json(
                                {
                                    "event": "mark",
                                    "streamSid": self.stream,
                                    "mark": {"name": NATIVE_AUDIO_MARK},
                                }
                            ),
                            IO_TIMEOUT,
                        )
                        self.native_marked = True

    async def clear(self):
        # Invalidates queued local frames immediately, before waiting for a send.
        self.epoch += 1
        self.clears += 1
        if self.clears > 600:
            raise BridgeError("output_limit")
        async with self.lock:
            await asyncio.wait_for(
                self.socket.send_json({"event": "clear", "streamSid": self.stream}),
                IO_TIMEOUT,
            )

    async def failure(self):
        await self.clear()
        pcm = fallback_pcm()
        for offset in range(0, len(pcm), 320):
            await self.audio(pcm[offset : offset + 320])
        # Frames are paced, so only a final packet (not seconds of queue) remains.
        await asyncio.sleep(0.2)


class LiveKitCall:
    """Own exactly one opaque room and native RTC participant; no agent logic."""

    def __init__(self, config, sender):
        self.config, self.sender = config, sender
        opaque = uuid.uuid4().hex
        self.name, self.identity = "voicebot-twilio-" + opaque, "carrier-" + opaque
        self.client = self.room = self.source = self.publication = self.stream = None
        self.track = self.agent_track = None
        self.agent_identity = None
        self.pause_generation = None
        self.terminal_output = False
        self.control_tasks = set()
        self.output = self.interruption = None
        self.ended = asyncio.Event()
        self.failed = False
        self.closed, self.create_attempted = False, False

    async def start(self):
        from livekit import api, rtc

        self.client = api.LiveKitAPI(
            url=self.config.livekit_url,
            api_key=self.config.livekit_key,
            api_secret=self.config.livekit_secret,
            failover=False,
        )
        self.room = rtc.Room()
        self.room.on("track_subscribed", self._on_track)
        self.room.on("data_received", self._on_data)
        self.room.on("disconnected", lambda *_: self.ended.set())
        self.room.on(
            "participant_disconnected",
            lambda participant: (
                self.ended.set()
                if participant.identity == self.agent_identity
                else None
            ),
        )
        self.create_attempted = True
        await self.client.room.create_room(
            api.CreateRoomRequest(
                name=self.name,
                empty_timeout=30,
                departure_timeout=5,
                max_participants=2,
            )
        )
        credential = (
            api.AccessToken(self.config.livekit_key, self.config.livekit_secret)
            .with_identity(self.identity)
            .with_ttl(timedelta(seconds=CALL_TIMEOUT + 30))
            .with_grants(
                api.VideoGrants(
                    room_join=True,
                    room=self.name,
                    can_publish=True,
                    can_publish_sources=["microphone"],
                    can_subscribe=True,
                    can_publish_data=False,
                )
            )
            .to_jwt()
        )
        await self.room.connect(
            self.config.livekit_url,
            credential,
            options=rtc.RoomOptions(auto_subscribe=True, connect_timeout=10),
        )
        self.source = rtc.AudioSource(8000, 1, queue_size_ms=100)
        self.track = rtc.LocalAudioTrack.create_audio_track(
            "carrier-microphone", self.source
        )
        self.publication = await self.room.local_participant.publish_track(
            self.track,
            rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE),
        )
        # Let the sole socket reader drain already-arrived input before paid work.
        await asyncio.sleep(0)
        if self.ended.is_set():
            raise BridgeDisconnected()
        await self.client.agent_dispatch.create_dispatch(
            api.CreateAgentDispatchRequest(room=self.name, agent_name=self.config.agent)
        )

    def _on_track(self, track, publication, participant):
        from livekit import rtc

        if (
            self.closed
            or self.terminal_output
            or participant.kind != rtc.ParticipantKind.PARTICIPANT_KIND_AGENT
            or track.kind != rtc.TrackKind.KIND_AUDIO
            or publication.source != rtc.TrackSource.SOURCE_MICROPHONE
        ):
            return
        if self.agent_track is not None:
            if (
                participant.identity == self.agent_identity
                and getattr(track, "name", "") == "voicebot-fallback"
            ):
                self.terminal_output = True
                self.pause_generation = None
                self._schedule_control(
                    self._clear(replacement=track, previous=self.interruption)
                )
            return
        self.agent_identity = participant.identity
        self.agent_track = track
        self.terminal_output = getattr(track, "name", "") == "voicebot-fallback"
        self._subscribe_audio()

    def _schedule_control(self, coroutine):
        task = asyncio.create_task(coroutine)
        self.control_tasks.add(task)
        task.add_done_callback(self.control_tasks.discard)
        self.interruption = task

    def _subscribe_audio(self):
        from livekit import rtc

        self.stream = rtc.AudioStream(
            track=self.agent_track,
            sample_rate=8000,
            num_channels=1,
            frame_size_ms=20,
            capacity=1,
        )
        self.output = asyncio.create_task(self._output())

    async def _output(self):
        try:
            async for event in self.stream:
                frame = event.frame
                if (
                    frame.sample_rate != 8000
                    or frame.num_channels != 1
                    or frame.samples_per_channel > 1600
                ):
                    raise BridgeError("output_invalid")
                await self.sender.audio(bytes(frame.data), native=True)
        except Exception:
            self.failed = True
            self.ended.set()
        # Track retirement is not participant hangup: the same bound agent may
        # publish its fatal-error apology after AgentSession closes the old mic.

    def _on_data(self, packet):
        from livekit import rtc

        participant = packet.participant
        if (
            self.closed
            or self.terminal_output
            or participant is None
            or participant.kind != rtc.ParticipantKind.PARTICIPANT_KIND_AGENT
            or participant.identity != self.agent_identity
            or packet.topic != "voicebot.interruption"
        ):
            return
        if not isinstance(packet.data, bytes):
            return
        control = re.fullmatch(rb"(clear|resume|failed):([a-f0-9]{32})", packet.data)
        if control is None:
            return
        command, generation = control.groups()
        if command == b"clear":
            self.pause_generation = generation
            self._schedule_control(
                self._clear(restart=False, previous=self.interruption)
            )
        elif command == b"failed" and generation == self.pause_generation:
            self.failed = True
            self.ended.set()
        elif command == b"resume" and generation == self.pause_generation:
            self._schedule_control(self._resume(generation, self.interruption))

    async def _resume(self, generation, previous):
        try:
            if previous is not None:
                await asyncio.wait_for(previous, CLOSE_TIMEOUT)
            if (
                not self.closed
                and not self.ended.is_set()
                and self.pause_generation == generation
            ):
                self.pause_generation = None
                self._subscribe_audio()
        except Exception:
            self.failed = True
            self.ended.set()

    async def _clear(self, *, replacement=None, restart=True, previous=None):
        try:
            if self.output is not None:
                self.output.cancel()
            await self.sender.clear()
            if previous is not None:
                await asyncio.wait_for(previous, CLOSE_TIMEOUT)
            # Select the retired epoch AFTER its predecessor completes; never
            # reread a mutable task reference while awaiting that task.
            output, stream = self.output, self.stream
            if output is not None:
                output.cancel()
                await asyncio.wait_for(
                    asyncio.gather(output, return_exceptions=True), CLOSE_TIMEOUT
                )
            if stream is not None:
                await asyncio.wait_for(stream.aclose(), CLOSE_TIMEOUT)
            if restart and not self.closed and not self.ended.is_set():
                if replacement is not None:
                    self.agent_track = replacement
                    self.pause_generation = None
                self._subscribe_audio()
        except Exception:
            self.failed = True
            self.ended.set()

    async def feed(self, pcm):
        from livekit import rtc

        await self.source.capture_frame(
            rtc.AudioFrame(
                data=pcm,
                sample_rate=8000,
                num_channels=1,
                samples_per_channel=len(pcm) // 2,
            )
        )

    async def close(self):
        if self.closed:
            return
        self.closed = True
        tasks = list(self.control_tasks)
        if self.output is not None:
            tasks.append(self.output)
        for task in tasks:
            task.cancel()
        if tasks:
            await bounded_close(lambda: asyncio.gather(*tasks, return_exceptions=True))
        if self.stream is not None:
            await bounded_close(self.stream.aclose)
        if self.publication is not None and self.room is not None:
            await bounded_close(
                lambda: self.room.local_participant.unpublish_track(
                    self.publication.sid
                )
            )
        if self.source is not None:
            await bounded_close(self.source.aclose)
        if self.room is not None:
            await bounded_close(self.room.disconnect)
        if self.client is not None:
            if self.create_attempted:
                from livekit import api

                await bounded_close(
                    lambda: self.client.room.delete_room(
                        api.DeleteRoomRequest(room=self.name)
                    )
                )
            await bounded_close(self.client.aclose)
        self.track = self.agent_track = self.source = self.stream = self.publication = (
            self.room
        ) = self.client = None


def signature_header(headers):
    signatures = headers.getall("x-twilio-signature", [])
    if len(signatures) != 1 or not re.fullmatch(r"[A-Za-z0-9+/]{27}=", signatures[0]):
        raise BridgeError()
    return signatures[0]


async def form_fields(request):
    if (
        request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        != "application/x-www-form-urlencoded"
    ):
        raise BridgeError("form_required", 415)
    data = bytearray()
    async for chunk in request.content.iter_chunked(MAX_FORM_BYTES + 1):
        if len(data) + len(chunk) > MAX_FORM_BYTES:
            raise BridgeError("form_too_large", 413)
        data.extend(chunk)
    try:
        text = data.decode("utf-8", errors="strict")
        if re.search(r"%(?![0-9a-fA-F]{2})", text):
            raise ValueError()
        fields = {}
        for key, value in parse_qsl(
            text,
            keep_blank_values=True,
            strict_parsing=True,
            max_num_fields=64,
            encoding="utf-8",
            errors="strict",
        ):
            if not key or len(key) > 128 or len(value) > 4096:
                raise ValueError()
            fields.setdefault(key, []).append(value)
        return fields
    except (ValueError, UnicodeError):
        raise BridgeError("form_invalid", 400) from None


def unique_json(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise BridgeError("message_invalid")
        result[key] = value
    return result


async def receive_message(socket, timeout=15):
    # Inline receive drains queued messages without scheduling a second consumer.
    async with asyncio.timeout(timeout):
        message = await socket.receive()
    if message.type in (
        WSMsgType.CLOSE,
        WSMsgType.CLOSING,
        WSMsgType.CLOSED,
        WSMsgType.ERROR,
    ):
        raise BridgeDisconnected()
    text = message.data if message.type == WSMsgType.TEXT else None
    if not isinstance(text, str) or not 1 <= len(text.encode()) <= MAX_MESSAGE_BYTES:
        raise BridgeError("message_invalid")
    try:
        parsed = json.loads(
            text,
            object_pairs_hook=unique_json,
            parse_constant=lambda _: (_ for _ in ()).throw(
                BridgeError("message_invalid")
            ),
        )
        if not isinstance(parsed, dict):
            raise BridgeError("message_invalid")
        return parsed
    except (ValueError, RecursionError):
        raise BridgeError("message_invalid") from None


class IncomingAudio:
    """One socket reader; retain only the latest second/50 frames during setup."""

    def __init__(self, socket, protocol, native):
        self.socket, self.protocol, self.native = socket, protocol, native
        self.queue, self.bytes = asyncio.Queue(maxsize=50), 0

    async def read(self):
        try:
            while True:
                result = self.protocol.accept(await receive_message(self.socket))
                if result == "stop":
                    return "stop"
                if isinstance(result, bytes):
                    while self.queue.full() or self.bytes + len(result) > 16000:
                        self.bytes -= len(self.queue.get_nowait())
                    self.queue.put_nowait(result)
                    self.bytes += len(result)
        finally:
            self.native.ended.set()

    async def feed(self):
        while True:
            pcm = await self.queue.get()
            self.bytes -= len(pcm)
            await asyncio.wait_for(self.native.feed(pcm), IO_TIMEOUT)


async def call_deadline(sender, started):
    try:
        remaining = max(0, FIRST_AUDIO_TIMEOUT - (time.monotonic() - started))
        await asyncio.wait_for(sender.first_audio.wait(), remaining)
    except TimeoutError:
        return "first_audio_timeout"
    await asyncio.sleep(max(0, CALL_TIMEOUT - (time.monotonic() - started)))
    return "duration_limit"


def twiml(binding):
    root = ET.Element("Response")
    if binding:
        stream = ET.SubElement(ET.SubElement(root, "Connect"), "Stream", url=MEDIA_URL)
        ET.SubElement(stream, "Parameter", name="call_binding", value=binding)
    else:
        ET.SubElement(root, "Play").text = FALLBACK_URL
    ET.SubElement(root, "Hangup")
    return web.Response(
        text=ET.tostring(root, encoding="unicode"),
        content_type="application/xml",
        headers={"Cache-Control": "no-store"},
    )


def private_error(error):
    return web.json_response(
        {"detail": error.code},
        status=error.status,
        headers={"Cache-Control": "no-store"},
    )


def create_app():
    async def shutdown(app):
        tasks = list(app[STATE].running)
        for task in tasks:
            task.cancel()
        if tasks:
            await bounded_close(lambda: asyncio.gather(*tasks, return_exceptions=True))

    app = web.Application(client_max_size=MAX_FORM_BYTES)
    app[STATE] = SimpleNamespace(
        config=Config.from_env(), bindings=Bindings(), sockets=0, running=set()
    )
    app.on_shutdown.append(shutdown)
    routes = web.RouteTableDef()

    @routes.get("/health")
    async def health(request):
        return web.json_response(
            {"alive": True, "configured": app[STATE].config is not None},
            headers={"Cache-Control": "no-store"},
        )

    @routes.get("/api/twilio/unavailable-et.wav")
    async def unavailable_audio(request):
        return web.FileResponse(
            FALLBACK_FILE,
            headers={
                "Content-Type": "audio/wav",
                "Cache-Control": "public, max-age=3600",
            },
        )

    @routes.post("/api/twilio/voice")
    async def voice(request):
        try:
            config = app[STATE].config
            if config is None:
                raise BridgeError("bridge_not_configured", 503)
            signature = signature_header(request.headers)
            if request.query_string:
                raise BridgeError()
            fields = await asyncio.wait_for(form_fields(request), HANDSHAKE_TIMEOUT)
            if not valid_signature(config, VOICE_URL, fields, signature):
                raise BridgeError()
            call = authorized_call(config, fields)
            return twiml(app[STATE].bindings.reserve(call))
        except BridgeError as error:
            return private_error(error)
        except Exception:
            return private_error(BridgeError("bridge_unavailable", 503))

    @routes.get("/api/twilio/media/")
    @routes.get("/api/twilio/media")
    async def media(request):
        state = app[STATE]
        config = state.config
        try:
            if config is None:
                raise BridgeError("bridge_not_configured", 503)
            if request.query_string or not valid_media_signature(
                config, signature_header(request.headers)
            ):
                raise BridgeError()
            if state.sockets >= MAX_PENDING:
                raise BridgeError("capacity", 503)
        except BridgeError as error:
            return private_error(error)

        socket = web.WebSocketResponse(
            max_msg_size=MAX_MESSAGE_BYTES,
            compress=False,
            timeout=IO_TIMEOUT,
            writer_limit=4096,
        )
        if not socket.can_prepare(request).ok:
            return private_error(BridgeError("websocket_required", 400))

        state.sockets += 1
        state.running.add(asyncio.current_task())
        call = sender = native = None
        tasks, close_code = [], 1000
        try:
            await socket.prepare(request)
            if request.transport is not None:
                request.transport.set_write_buffer_limits(high=4096, low=1024)
            connection = await receive_message(socket, HANDSHAKE_TIMEOUT)
            if (
                connection.get("event") != "connected"
                or connection.get("protocol") != "Call"
                or connection.get("version") != "1.0.0"
            ):
                raise BridgeError("connected_invalid")
            message = await receive_message(socket, HANDSHAKE_TIMEOUT)
            try:
                call, stream = authorize_start(config, state.bindings, message)
            except BridgeError as error:
                if error.code == "capacity":
                    sender = TwilioSender(socket, message["streamSid"])
                    await sender.failure()
                    return socket
                raise
            sender = TwilioSender(socket, stream)
            protocol = MediaProtocol(config.account, call, stream)
            native = LiveKitCall(config, sender)
            incoming = IncomingAudio(socket, protocol, native)
            reader = asyncio.create_task(incoming.read())
            setup = asyncio.create_task(asyncio.wait_for(native.start(), SETUP_TIMEOUT))
            ended = asyncio.create_task(native.ended.wait())
            tasks = [reader, setup, ended]
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            if reader in done or ended in done:
                setup.cancel()
                if reader in done:
                    reader.result()
                if getattr(native, "failed", False):
                    raise RuntimeError("native output failed")
                return socket
            setup.result()
            tasks = [
                reader,
                ended,
                asyncio.create_task(incoming.feed()),
                asyncio.create_task(call_deadline(sender, protocol.started)),
            ]
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in tasks:
                if task not in done:
                    task.cancel()
            for task in done:
                result = task.result()
                if result == "first_audio_timeout":
                    raise TimeoutError("first audio unavailable")
            if getattr(native, "failed", False):
                raise RuntimeError("native output failed")
        except (BridgeError, BridgeDisconnected):
            close_code = 1008
        except Exception:
            close_code = 1011
            for task in tasks:
                task.cancel()
            output = getattr(native, "output", None)
            if output is not None:
                output.cancel()
                await bounded_close(
                    lambda: asyncio.gather(output, return_exceptions=True)
                )
            if sender is not None:
                try:
                    await sender.failure()
                except Exception:
                    pass
        finally:
            for task in tasks:
                task.cancel()
            # Carrier hangup must not wait for several independent SDK/API closes.
            await bounded_close(lambda: socket.close(code=close_code))
            if tasks:
                await bounded_close(
                    lambda: asyncio.gather(*tasks, return_exceptions=True)
                )
            if native is not None:
                await native.close()
            if call is not None:
                state.bindings.release(call)
            state.sockets -= 1
            state.running.discard(asyncio.current_task())
        return socket

    app.add_routes(routes)
    return app


def main():
    # This dedicated process emits no request URLs, headers, bodies, SDK
    # exceptions, participant IDs, transcripts, or raw credential-bearing logs.
    logging.disable(logging.CRITICAL)
    web.run_app(
        create_app(),
        host="0.0.0.0",
        port=8082,
        print=None,
        access_log=None,
        shutdown_timeout=35,
        handler_cancellation=True,
    )


if __name__ == "__main__":
    main()
