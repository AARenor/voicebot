import asyncio
import base64
import importlib
import importlib.util
import json
import struct
from copy import deepcopy
from unittest.mock import patch
from urllib.parse import urlencode
from xml.etree import ElementTree as ET

import pytest
from tests.test_twilio_client import (
    TestClient,
    WebSocketDenialResponse,
    WebSocketDisconnect,
)

from tests.test_twilio_security import (
    ACCOUNT,
    CALL,
    ENV,
    MEDIA_URL,
    STREAM,
    VOICE_URL,
    sign,
    start,
)


def bridge():
    assert importlib.util.find_spec("app.twilio_bridge"), "carrier bridge missing"
    return importlib.import_module("app.twilio_bridge")


class NativeCall:
    """Only external RTC transport is replaced, never protocol/admission logic."""

    opened = []

    def __init__(self, cfg, sender):
        self.sender, self.ended = sender, asyncio.Event()
        self.pcm, self.closed = [], False

    async def start(self):
        self.opened.append(self)
        await self.sender.audio(struct.pack("<h", 1000) * 160)

    async def feed(self, pcm):
        self.pcm.append(pcm)

    async def close(self):
        self.closed = True


@pytest.fixture
def client():
    b = bridge()
    NativeCall.opened = []
    with (
        patch.dict("os.environ", ENV, clear=True),
        patch.object(b, "LiveKitCall", NativeCall),
    ):
        app = b.create_app()
        with TestClient(app) as c:
            yield c


def voice(client, fields=None, url=VOICE_URL, signature=None, query=""):
    fields = fields or {
        "AccountSid": [ACCOUNT],
        "CallSid": [CALL],
        "To": [ENV["TWILIO_PHONE_NUMBER"]],
        "From": ["+12025550456"],
    }
    return client.post(
        "/api/twilio/voice" + query,
        content=urlencode(fields, doseq=True),
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "X-Twilio-Signature": sign(url, fields) if signature is None else signature,
        },
    )


def binding(client, call=CALL):
    response = voice(
        client,
        {
            "AccountSid": [ACCOUNT],
            "CallSid": [call],
            "To": [ENV["TWILIO_PHONE_NUMBER"]],
        },
    )
    assert response.status_code == 200
    root = ET.fromstring(response.text)
    stream = root.find("Connect/Stream")
    assert stream.get("url") == MEDIA_URL
    assert root.find("Hangup") is not None
    return stream.find("Parameter").get("value")


def connected():
    return {"event": "connected", "protocol": "Call", "version": "1.0.0"}


def media(sequence=2, *, payload=None, stream=STREAM, timestamp=0, chunk=1):
    return {
        "event": "media",
        "sequenceNumber": str(sequence),
        "streamSid": stream,
        "media": {
            "track": "inbound",
            "chunk": str(chunk),
            "timestamp": str(timestamp),
            "payload": payload or base64.b64encode(b"\xff\x00\x80\x7f" * 40).decode(),
        },
    }


def stop(sequence=3):
    return {
        "event": "stop",
        "sequenceNumber": str(sequence),
        "streamSid": STREAM,
        "stop": {"accountSid": ACCOUNT, "callSid": CALL},
    }


def ws(client, **kwargs):
    return client.websocket_connect(
        "/api/twilio/media", headers={"X-Twilio-Signature": sign(MEDIA_URL)}, **kwargs
    )


def test_webhook_authentication_precedes_state_and_returns_private_twiml(client):
    assert voice(client, signature="").status_code == 403
    assert (
        voice(client, url="https://foreign.invalid/api/twilio/voice").status_code == 403
    )
    assert voice(client, query="?foreign=1").status_code == 403
    assert client.app.state.bindings.active_count == 0
    first = binding(client)
    assert binding(client) == first
    response = voice(client)
    assert response.headers["Cache-Control"] == "no-store"
    assert "12025550456" not in response.text and "Recording" not in response.text
    assert NativeCall.opened == []


@pytest.mark.parametrize(
    "body,content_type",
    [
        ("CallSid=%XX", "application/x-www-form-urlencoded"),
        ("{}", "application/json"),
        ("x=" + "a" * 17000, "application/x-www-form-urlencoded"),
        ("&".join("x=1" for _ in range(70)), "application/x-www-form-urlencoded"),
    ],
)
def test_malformed_or_unbounded_webhook_rejected_before_paid_job(
    client, body, content_type
):
    response = client.post(
        "/api/twilio/voice",
        content=body,
        headers={"Content-Type": content_type, "X-Twilio-Signature": sign(VOICE_URL)},
    )
    assert response.status_code in (400, 413, 415)
    assert response.headers["Cache-Control"] == "no-store"
    assert NativeCall.opened == []


def test_missing_environment_defaults_to_503_before_webhook_or_socket():
    b = bridge()
    with patch.dict("os.environ", {}, clear=True), TestClient(b.create_app()) as c:
        health = c.get("/health")
        assert health.status_code == 200
        assert health.json() == {"alive": True, "configured": False}
        response = c.post("/api/twilio/voice", content="private-content")
        assert response.status_code == 503
        assert response.headers["Cache-Control"] == "no-store"
        with pytest.raises(WebSocketDenialResponse) as denied:
            with c.websocket_connect("/api/twilio/media"):
                pass
        assert denied.value.status_code == 503


@pytest.mark.parametrize(
    "signature,path",
    [
        ("", "/api/twilio/media"),
        (sign("wss://foreign.invalid/api/twilio/media"), "/api/twilio/media"),
        (sign(MEDIA_URL), "/api/twilio/media?x=1"),
    ],
)
def test_ws_rejects_signature_or_query_before_accept_or_paid_job(
    client, signature, path
):
    with pytest.raises(WebSocketDenialResponse) as denied:
        with client.websocket_connect(path, headers={"X-Twilio-Signature": signature}):
            pass
    assert denied.value.status_code == 403
    assert NativeCall.opened == []


def test_bound_socket_decodes_inbound_and_encodes_outbound_then_tears_down(client):
    nonce = binding(client)
    with ws(client) as socket:
        socket.send_json(connected())
        socket.send_json(start(nonce))
        sent = socket.receive_json()
        assert sent["event"] == "media" and sent["streamSid"] == STREAM
        audio = base64.b64decode(sent["media"]["payload"])
        assert audio == b"\xce" * 160, "not raw 8 kHz mu-law"
        socket.send_json(media())
        socket.send_json(stop())
        with pytest.raises(WebSocketDisconnect):
            socket.receive_json()
    call = NativeCall.opened[0]
    assert call.pcm == [struct.pack("<hhhh", 0, -32124, 32124, 0) * 40]
    assert call.closed and client.app.state.bindings.active_count == 0
    with ws(client) as replay:
        replay.send_json(connected())
        replay.send_json(start(nonce))
        with pytest.raises(WebSocketDisconnect):
            replay.receive_json()
    assert len(NativeCall.opened) == 1


@pytest.mark.parametrize(
    "change",
    [
        "foreign_account",
        "foreign_call",
        "foreign_binding",
        "bad_encoding",
        "no_connected",
        "binary",
        "oversized",
        "duplicate_json",
    ],
)
def test_invalid_handshake_never_dispatches_native_agent(client, change):
    nonce = binding(client)
    message = start(nonce)
    if change == "foreign_account":
        message["start"]["accountSid"] = "AC" + "e" * 32
    if change == "foreign_call":
        message["start"]["callSid"] = "CA" + "e" * 32
    if change == "foreign_binding":
        message["start"]["customParameters"]["call_binding"] = "a" * 32
    if change == "bad_encoding":
        message["start"]["mediaFormat"]["encoding"] = "audio/pcm"
    with ws(client) as socket:
        if change != "no_connected":
            socket.send_json(connected())
        if change == "binary":
            socket.send_bytes(b"invalid")
        elif change == "oversized":
            socket.send_text("a" * 5000)
        elif change == "duplicate_json":
            socket.send_text('{"event":"start","event":"media"}')
        else:
            socket.send_json(message)
        with pytest.raises(WebSocketDisconnect):
            socket.receive_json()
    assert NativeCall.opened == []
    assert client.app.state.bindings.active_count == 0


def test_disconnect_and_invalid_media_release_capacity_and_do_not_expose_errors(client):
    nonce = binding(client)
    with ws(client) as socket:
        socket.send_json(connected())
        socket.send_json(start(nonce))
        socket.receive_json()
        socket.send_json(media(payload="%%%PRIVATE%%%"))
        with pytest.raises(WebSocketDisconnect):
            socket.receive_json()
    assert NativeCall.opened[0].closed
    assert not NativeCall.opened[0].pcm
    assert client.app.state.bindings.active_count == 0
    nonce = binding(client, "CA" + "f" * 32)
    with ws(client) as socket:
        socket.send_json(connected())
        socket.send_json(start(nonce, call="CA" + "f" * 32))
        socket.receive_json()
    assert NativeCall.opened[-1].closed
    assert client.app.state.bindings.active_count == 0


def test_capacity_returns_cached_estonian_audio_and_hangup_without_paid_job(client):
    store = client.app.state.bindings
    for n in range(2):
        call = "CA" + f"{n:032x}"
        store.consume(call, store.reserve(call))
    response = voice(client)
    root = ET.fromstring(response.text)
    assert root.find("Connect") is None
    assert (
        root.find("Play").text
        == "https://robot.arleserver.cfd/api/twilio/unavailable-et.wav"
    )
    assert root.find("Hangup") is not None
    audio = client.get("/api/twilio/unavailable-et.wav")
    assert audio.status_code == 200 and audio.content.startswith(b"RIFF")
    assert NativeCall.opened == []


@pytest.mark.parametrize(
    "change",
    [
        "foreign_stream",
        "outbound",
        "duplicate_seq",
        "bad_payload",
        "oversized",
        "future_timestamp",
        "duplicate_chunk",
    ],
)
def test_media_protocol_rejects_untrusted_or_incoherent_frames(change):
    b = bridge()
    clock = [0.0]
    protocol = b.MediaProtocol(ACCOUNT, CALL, STREAM, clock=lambda: clock[0])
    assert protocol.accept(media()) == struct.pack("<hhhh", 0, -32124, 32124, 0) * 40
    message = media(3, timestamp=20, chunk=2)
    if change == "foreign_stream":
        message["streamSid"] = "MZ" + "e" * 32
    if change == "outbound":
        message["media"]["track"] = "outbound"
    if change == "duplicate_seq":
        message["sequenceNumber"] = "2"
    if change == "bad_payload":
        message["media"]["payload"] = "private!!!"
    if change == "oversized":
        message["media"]["payload"] = base64.b64encode(b"x" * 1601).decode()
    if change == "future_timestamp":
        message["media"]["timestamp"] = "600001"
    if change == "duplicate_chunk":
        message["media"]["chunk"] = "1"
    with pytest.raises(b.BridgeError):
        protocol.accept(message)


def test_media_rate_and_total_time_bound_runaway_sender():
    b = bridge()
    clock = [0.0]
    protocol = b.MediaProtocol(ACCOUNT, CALL, STREAM, clock=lambda: clock[0])
    with pytest.raises(b.BridgeError):
        for n in range(1, 100):
            protocol.accept(
                media(
                    n + 1,
                    timestamp=0,
                    chunk=n,
                    payload=base64.b64encode(b"x" * 1600).decode(),
                )
            )
    clock[0] = 601
    with pytest.raises(b.BridgeError):
        protocol.accept(media(100, timestamp=599999, chunk=100))


def test_idle_time_cannot_be_banked_for_a_later_media_burst():
    b = bridge()
    clock = [0.0]
    protocol = b.MediaProtocol(ACCOUNT, CALL, STREAM, clock=lambda: clock[0])
    clock[0] = 30
    with pytest.raises(b.BridgeError):
        for n in range(1, 9):
            protocol.accept(
                media(
                    n + 1,
                    timestamp=0,
                    chunk=n,
                    payload=base64.b64encode(b"x" * 1600).decode(),
                )
            )


@pytest.mark.parametrize("samples,retained", [(1600, 5), (1, 50)])
def test_setup_pcm_buffer_keeps_only_bounded_latest_audio(samples, retained):
    from types import SimpleNamespace

    b = bridge()

    async def check():
        clock, frames, delivered = [0.0], [], []
        read_waiting, fed = asyncio.Event(), asyncio.Event()

        class Socket:
            async def receive(self):
                if not frames:
                    read_waiting.set()
                    await asyncio.Event().wait()
                clock[0] += max(0.01, samples / 8000)
                return SimpleNamespace(
                    type=b.WSMsgType.TEXT, data=json.dumps(frames.pop(0))
                )

        async def feed(pcm):
            delivered.append(pcm)
            if len(delivered) == retained:
                fed.set()

        for n in range(1, 76):
            frames.append(
                media(
                    n + 1,
                    chunk=n,
                    timestamp=0,
                    payload=base64.b64encode(bytes([n]) * samples).decode(),
                )
            )
        native = SimpleNamespace(ended=asyncio.Event(), feed=feed)
        protocol = b.MediaProtocol(ACCOUNT, CALL, STREAM, clock=lambda: clock[0])
        incoming = b.IncomingAudio(Socket(), protocol, native)
        reader = asyncio.create_task(incoming.read())
        await asyncio.wait_for(read_waiting.wait(), 1)
        assert incoming.queue.maxsize == 50
        assert incoming.queue.qsize() == retained and incoming.bytes <= 16000
        assert not delivered, "setup audio was sent before RTC was ready"
        feeder = asyncio.create_task(incoming.feed())
        try:
            await asyncio.wait_for(fed.wait(), 1)
            expected = [
                b.audioop.ulaw2lin(bytes([n]) * samples, 2)
                for n in range(76 - retained, 76)
            ]
            assert delivered == expected and incoming.bytes == 0
        finally:
            reader.cancel()
            feeder.cancel()
            await asyncio.gather(reader, feeder, return_exceptions=True)

    asyncio.run(check())


def test_sender_clear_is_serialized_and_invalidates_old_pcm():
    b = bridge()

    class Socket:
        def __init__(self):
            self.sent, self.sending = [], False

        async def send_json(self, message):
            assert not self.sending, "concurrent WebSocket sends"
            self.sending = True
            await asyncio.sleep(0)
            self.sent.append(message)
            self.sending = False

    async def check():
        socket = Socket()
        sender = b.TwilioSender(socket, STREAM)
        task = asyncio.create_task(sender.audio(struct.pack("<h", 1000) * 320))
        await asyncio.sleep(0.005)
        await sender.clear()
        await task
        assert [m["event"] for m in socket.sent] == ["media", "clear"]
        await sender.audio(struct.pack("<h", 2000) * 160)
        assert socket.sent[-1]["event"] == "media"
        assert sender.first_audio.is_set()

    asyncio.run(check())


def test_first_audio_timeout_tears_down_instead_of_waiting_forever(client):
    b = bridge()

    class Silent(NativeCall):
        async def start(self):
            self.opened.append(self)

    with (
        patch.object(b, "LiveKitCall", Silent),
        patch.object(b, "FIRST_AUDIO_TIMEOUT", 0.02),
        patch.object(b.TwilioSender, "failure", return_value=None),
    ):
        nonce = binding(client)
        with ws(client) as socket:
            socket.send_json(connected())
            socket.send_json(start(nonce))
            with pytest.raises(WebSocketDisconnect):
                socket.receive_json()
    assert NativeCall.opened[-1].closed
    assert client.app.state.bindings.active_count == 0


def test_first_audio_deadline_includes_room_setup_time():
    b = bridge()

    async def check():
        sender = type("Waiting", (), {"first_audio": asyncio.Event()})()
        with patch.object(b, "FIRST_AUDIO_TIMEOUT", 0.03):
            result = await asyncio.wait_for(
                b.call_deadline(sender, b.time.monotonic() - 0.04), 0.015
            )
        assert result == "first_audio_timeout"

    asyncio.run(check())


def test_duration_limit_closes_native_call_and_releases_admission(client):
    b = bridge()
    with patch.object(b, "CALL_TIMEOUT", 0.03):
        nonce = binding(client)
        with ws(client) as socket:
            socket.send_json(connected())
            socket.send_json(start(nonce))
            socket.receive_json()
            with pytest.raises(WebSocketDisconnect):
                socket.receive_json()
    assert NativeCall.opened[-1].closed
    assert client.app.state.bindings.active_count == 0


def test_carrier_hangup_precedes_native_teardown_waits(client):
    b = bridge()

    class Closing(NativeCall):
        async def close(self):
            self.carrier_closed_before_cleanup = self.sender.socket.closed
            self.closed = True

    with patch.object(b, "LiveKitCall", Closing):
        nonce = binding(client)
        with ws(client) as socket:
            socket.send_json(connected())
            socket.send_json(start(nonce))
            socket.receive_json()
            socket.send_json(stop(2))
            with pytest.raises(WebSocketDisconnect):
                socket.receive_json()
    assert NativeCall.opened[-1].carrier_closed_before_cleanup


def test_credential_and_binding_never_leak_in_closed_provider_failure(client):
    b = bridge()

    class Broken(NativeCall):
        async def start(self):
            self.opened.append(self)
            raise RuntimeError("PRIVATE paid transport failure")

    with (
        patch.object(b, "LiveKitCall", Broken),
        patch.object(b.TwilioSender, "failure", return_value=None),
    ):
        nonce = binding(client)
        with ws(client) as socket:
            socket.send_json(connected())
            socket.send_json(start(nonce))
            with pytest.raises(WebSocketDisconnect) as closed:
                socket.receive_json()
        assert closed.value.code == 1011 and not closed.value.reason
    assert NativeCall.opened[-1].closed
    assert client.app.state.bindings.active_count == 0


def test_cached_failure_streams_raw_mulaw_without_synthesis():
    b = bridge()
    sent = []

    class Socket:
        async def send_json(self, message):
            sent.append(message)

    async def no_wait(_):
        pass

    async def check():
        with patch.object(b.asyncio, "sleep", no_wait):
            await b.TwilioSender(Socket(), STREAM).failure()
        assert sent[0] == {"event": "clear", "streamSid": STREAM}
        payload = b"".join(base64.b64decode(m["media"]["payload"]) for m in sent[1:])
        assert 40000 < len(payload) < 60000 and not payload.startswith(b"RIFF")

    asyncio.run(check())
