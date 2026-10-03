"""Exercise the real ASGI transport, not TestClient's buffered TTFB."""

import asyncio
import base64
import json
import threading
from unittest.mock import patch

import pytest

from app import callslog
from app.server import create_app
from tests.test_product_demo import (
    AUTH,
    CONSENT,
    BookingLlm,
    SimpleLlm,
    Speaker,
    client,
    install_backend,
    start,
)

STREAM_AUTH = {**AUTH, "Accept": "application/x-ndjson"}


class StreamingSpeaker(Speaker):
    def __init__(self, *, partial_failure=False, blocked=False, many=False):
        super().__init__()
        self.partial_failure, self.blocked, self.many = partial_failure, blocked, many
        self.release = threading.Event()
        self.entered = threading.Event()
        self.completed = threading.Event()

    def stream(self, text):
        self.spoken.append(text)
        self.entered.set()
        yield b"first-real-mp3-fixture"
        if self.blocked:
            assert self.release.wait(5), "fixture producer was not released"
        if self.partial_failure:
            raise RuntimeError("PRIVATE provider response")
        for _ in range(80 if self.many else 1):
            yield b"last-real-mp3-fixture"
        self.completed.set()


def events(response):
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/x-ndjson")
    return [json.loads(line) for line in response.text.splitlines()]


def test_stream_is_guarded_ordered_and_preserves_canonical_done(client):
    speaker = StreamingSpeaker()
    client.app.state.stack.update(
        tts=speaker, llm_primary=SimpleLlm("Sinu testbroneering on edukalt loodud.")
    )
    result = client.post(
        "/api/turn", headers=STREAM_AUTH, json={"text": "Soovin testbroneeringut"}
    )
    items = events(result)
    assert [item["type"] for item in items] == ["reply", "audio", "audio", "done"]
    assert items[0] == {
        "type": "reply",
        "reply": speaker.spoken[-1],
        "language": "et",
        "audio_type": "audio/mpeg",
    }
    assert items[0]["reply"] != "Sinu testbroneering on edukalt loodud."
    assert [item["seq"] for item in items if item["type"] == "audio"] == [0, 1]
    assert base64.b64decode(items[1]["audio_b64"]) == b"first-real-mp3-fixture"
    done = items[-1]
    assert done["reply"] == items[0]["reply"] and done["audio_b64"] == ""
    assert done["audio_type"] == "audio/mpeg" and not done["tts_failed"]
    assert done["booking_changes"] == done["booking_ids"] == done["warnings"] == []
    assert done["voice"]["requested"] == done["voice"]["effective"] == "azure"
    assert done["voice"]["streaming"] is True
    assert done["timings_ms"]["tts_first_audio_ms"] >= 0
    assert result.headers["Cache-Control"] == "no-store"


def test_buffered_speaker_uses_one_real_chunk_and_json_stays_buffered(client):
    result = client.post("/api/turn", headers=STREAM_AUTH, json={"text": "Tere"})
    items = events(result)
    assert [item["type"] for item in items] == ["reply", "audio", "done"]
    assert base64.b64decode(items[1]["audio_b64"]).decode() == items[0]["reply"]
    assert len(client.app.state.stack["tts"].spoken) == 1
    ordinary = client.post("/api/turn", headers=AUTH, json={"text": "Tere"})
    assert ordinary.status_code == 200 and ordinary.json()["audio_b64"]


@pytest.mark.parametrize("unknown", [False, True])
def test_stream_receipt_authorizes_exactly_one_later_owned_write(
    client, tmp_path, unknown
):
    day, records, writes = install_backend(client, tmp_path, unknown=unknown)
    client.app.state.stack.update(llm_primary=BookingLlm(day), tts=StreamingSpeaker())
    key = start(client)
    prepared = events(
        client.post(
            "/api/turn",
            headers=STREAM_AUTH,
            json={"session_id": key, "text": "Soovin testbroneeringut"},
        )
    )
    assert all("recap_delivery_id" not in item for item in prepared[:-1])
    assert prepared[-1]["recap_delivery_id"] and not records
    receipt = prepared[-1]["recap_delivery_id"]
    body = {"session_id": key, "text": CONSENT, "recap_delivery_id": receipt}
    done = events(client.post("/api/turn", headers=STREAM_AUTH, json=body))[-1]
    assert done["outcome"] == ("unknown_outcome" if unknown else "tools_ok")
    assert (
        sum(r.method == "POST" and r.url.path.endswith("/appointments") for r in writes)
        == 1
    )
    if not unknown:
        assert done["booking_changes"][0]["action"] == "confirmed"
    events(client.post("/api/turn", headers=STREAM_AUTH, json=body))
    assert (
        sum(r.method == "POST" and r.url.path.endswith("/appointments") for r in writes)
        == 1
    )


def test_partial_stream_failure_has_no_fallback_or_receipt(client, tmp_path):
    day, records, writes = install_backend(client, tmp_path)
    speaker = StreamingSpeaker(partial_failure=True)
    client.app.state.stack.update(llm_primary=BookingLlm(day), tts=speaker)
    key = start(client)
    before = len(speaker.spoken)
    response = client.post(
        "/api/turn",
        headers=STREAM_AUTH,
        json={"session_id": key, "text": "Soovin testbroneeringut"},
    )
    items = events(response)
    assert [item["type"] for item in items] == ["reply", "audio", "done"]
    done = items[-1]
    assert done["tts_failed"] and done["outcome"] == "tts_failed"
    assert done["audio_b64"] == "" and done["recap_delivery_id"] is None
    assert done["reply"] == items[0]["reply"]
    assert len(speaker.spoken) == before + 1 and "PRIVATE" not in response.text
    session = client.app.state.demo_sessions.sessions[key]
    assert session.recap_delivery is None and session.tools.pending is None
    assert not records and not writes


@pytest.mark.parametrize("audio", [None, "not audio bytes", [b"not complete audio"]])
def test_nonbyte_synthesis_cannot_arm_recap_receipt(client, tmp_path, audio):
    day, records, writes = install_backend(client, tmp_path)

    class InvalidSpeaker:
        def synthesize(self, text):
            return audio

    client.app.state.stack["llm_primary"] = BookingLlm(day)
    key = start(client)
    client.app.state.stack["tts"] = InvalidSpeaker()
    response = client.post(
        "/api/turn",
        headers=AUTH,
        json={"session_id": key, "text": "Soovin testbroneeringut"},
    )
    assert response.status_code == 200
    assert response.json()["tts_failed"] and not response.json()["audio_b64"]
    assert response.json()["recap_delivery_id"] is None
    assert client.app.state.demo_sessions.sessions[key].recap_delivery is None
    assert not records and not writes


def test_audio_bounds_close_iterator_and_do_not_emit_oversized_chunk(client):
    from app.browser_audio import MAX_AUDIO_BYTES

    class Source:
        closed = False

        def __iter__(self):
            return self

        def __next__(self):
            return b"x" * (MAX_AUDIO_BYTES + 1)

        def close(self):
            self.closed = True

    class BoundedSpeaker(Speaker):
        def __init__(self):
            super().__init__()
            self.source = Source()

        def stream(self, text):
            return self.source

    speaker = BoundedSpeaker()
    client.app.state.stack["tts"] = speaker
    result = client.post("/api/turn", headers=STREAM_AUTH, json={"text": "Tere"})
    items = events(result)
    assert [item["type"] for item in items] == ["reply", "done"]
    assert items[-1]["tts_failed"] and items[-1]["recap_delivery_id"] is None
    assert speaker.source.closed


def test_full_thread_queue_unblocks_on_disconnect_without_consumer():
    from app.browser_audio import AudioEvents

    async def check():
        cleared = []
        bridge = AudioEvents(lambda: cleared.append(True))
        for _ in range(bridge.queue.maxsize):
            bridge.emit({"type": "audio", "audio_b64": "eA=="})
        entered = threading.Event()

        def blocked_emit():
            entered.set()
            bridge.emit({"type": "audio", "audio_b64": "eA=="})

        producer = asyncio.create_task(asyncio.to_thread(blocked_emit))
        assert await asyncio.to_thread(entered.wait, 1)
        assert not producer.done() and bridge.queue.full()
        bridge.disconnect()
        await asyncio.wait_for(producer, 1)
        assert cleared == [True] and bridge.closed.is_set()

    asyncio.run(check())


@pytest.mark.parametrize(
    "case,status",
    [
        ("auth", 403),
        ("large", 413),
        ("malformed", 400),
        ("foreign", 403),
        ("busy", 409),
        ("expired", 410),
    ],
)
def test_stream_guards_reject_before_provider_execution(client, case, status):
    key = start(client)
    session = client.app.state.demo_sessions.sessions[key]
    headers = dict(STREAM_AUTH)
    body = {"session_id": key, "text": "Tere"}
    if case == "auth":
        headers.pop("Authorization")
    elif case == "foreign":
        session.owner = "another-owner"
    elif case == "busy":
        session.busy = True
    elif case == "expired":
        session.expires_at = 0
    before = len(client.app.state.stack["tts"].spoken)
    options = (
        {"content": b"x" * 750_001}
        if case == "large"
        else {"content": b"{"}
        if case == "malformed"
        else {"json": body}
    )
    result = client.post("/api/turn", headers=headers, **options)
    assert result.status_code == status
    assert result.headers["Cache-Control"] == "no-store"
    assert len(client.app.state.stack["tts"].spoken) == before
    assert not client.app.state.stack["llm_primary"].messages


class AsgiExchange:
    """An incremental HTTP peer with explicit disconnect, using the app's ASGI API."""

    def __init__(self, app, body):
        self.app, self.body = app, json.dumps(body).encode()
        self.inbound, self.outbound = asyncio.Queue(), asyncio.Queue()
        self.task = None
        self.buffer = b""

    async def start(self):
        await self.inbound.put(
            {"type": "http.request", "body": self.body, "more_body": False}
        )
        scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.0"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/api/turn",
            "raw_path": b"/api/turn",
            "query_string": b"",
            "root_path": "",
            "server": ("fixture", 80),
            "client": ("fixture", 1234),
            "headers": [
                (b"authorization", AUTH["Authorization"].encode()),
                (b"accept", b"application/x-ndjson"),
                (b"content-type", b"application/json"),
            ],
        }
        self.task = asyncio.create_task(
            self.app(scope, self.inbound.get, self.outbound.put)
        )
        return self

    async def event(self):
        while b"\n" not in self.buffer:
            message = await asyncio.wait_for(self.outbound.get(), 2)
            if message["type"] == "http.response.start":
                assert message["status"] == 200
                assert (b"content-type", b"application/x-ndjson") in message["headers"]
            else:
                self.buffer += message.get("body", b"")
                assert message.get("more_body", False) or b"\n" in self.buffer, (
                    "response ended without an NDJSON event"
                )
        line, self.buffer = self.buffer.split(b"\n", 1)
        return json.loads(line)

    async def disconnect(self):
        await self.inbound.put({"type": "http.disconnect"})
        await asyncio.wait_for(self.task, 2)


@pytest.mark.parametrize(
    "disconnect,many", [(False, False), (True, False), (True, True)]
)
def test_first_chunk_precedes_completion_and_disconnect_keeps_producer_ownership(
    monkeypatch, disconnect, many
):
    async def check():
        with patch.dict(
            "os.environ", {"OPERATOR_TOKEN": "fixture-operator"}, clear=True
        ):
            callslog.reset_default()
            app = create_app()
        monkeypatch.setenv("OPERATOR_TOKEN", "fixture-operator")
        speaker = StreamingSpeaker(blocked=True, many=many)
        app.state.stack.update(tts=speaker, llm_primary=SimpleLlm())
        async with app.router.lifespan_context(app):
            from app.hackathon import operator_scope

            data = app.state.demo_sessions.create(
                app.state.stack["dispatcher"], operator_scope(AUTH["Authorization"])
            )
            session = app.state.demo_sessions.sessions[data["session_id"]]
            exchange = await AsgiExchange(
                app, {"session_id": data["session_id"], "text": "Tere"}
            ).start()
            try:
                assert (await exchange.event())["type"] == "reply"
                assert (await exchange.event())["type"] == "audio"
                assert not speaker.completed.is_set() and session.busy
                assert hasattr(app.state, "turn_producers") and app.state.turn_producers
                if disconnect:
                    await exchange.disconnect()
                    assert session.busy and app.state.turn_producers
                    session.recap_delivery = {"id": "a" * 32}
                    speaker.release.set()
                    await asyncio.wait_for(asyncio.gather(*app.state.turn_producers), 2)
                    assert session.recap_delivery is None and not session.busy
                    assert speaker.completed.is_set(), (
                        "disconnect cancelled the running synthesis"
                    )
                else:
                    speaker.release.set()
                    assert (await exchange.event())["type"] == "audio"
                    assert (await exchange.event())["type"] == "done"
                    await asyncio.wait_for(exchange.task, 2)
                    assert speaker.completed.is_set() and not session.busy
            finally:
                speaker.release.set()
                if not exchange.task.done():
                    await exchange.disconnect()
        callslog.reset_default()

    asyncio.run(check())


def test_shutdown_disables_queued_emission_before_draining_producer(monkeypatch):
    async def check():
        with patch.dict(
            "os.environ", {"OPERATOR_TOKEN": "fixture-operator"}, clear=True
        ):
            callslog.reset_default()
            app = create_app()
        monkeypatch.setenv("OPERATOR_TOKEN", "fixture-operator")
        speaker = StreamingSpeaker(blocked=True, many=True)
        app.state.stack.update(tts=speaker, llm_primary=SimpleLlm())
        from app.hackathon import operator_scope

        lifespan = app.router.lifespan_context(app)
        await lifespan.__aenter__()
        data = app.state.demo_sessions.create(
            app.state.stack["dispatcher"], operator_scope(AUTH["Authorization"])
        )
        exchange = await AsgiExchange(
            app, {"session_id": data["session_id"], "text": "Tere"}
        ).start()
        try:
            assert (await exchange.event())["type"] == "reply"
            assert (await exchange.event())["type"] == "audio"
            assert hasattr(app.state, "turn_streams"), (
                "shutdown has no stream emission tracker"
            )
            shutdown = asyncio.create_task(lifespan.__aexit__(None, None, None))
            # Synchronize on the producer's own closed emission gate, not a sleep.
            bridge = next(iter(app.state.turn_streams))
            assert await asyncio.to_thread(bridge.closed.wait, 1)
            assert not shutdown.done(), "shutdown discarded in-flight synthesis"
            speaker.release.set()
            await asyncio.wait_for(shutdown, 2)
            assert speaker.completed.is_set() and not app.state.turn_producers
            await asyncio.wait_for(exchange.task, 2)
        finally:
            speaker.release.set()
            if not exchange.task.done():
                await exchange.disconnect()
            await lifespan.__aexit__(None, None, None)
        callslog.reset_default()

    asyncio.run(check())


def test_disconnect_before_reply_does_not_unlock_running_thread_or_rearm_receipt(
    client,
):
    entered, release = threading.Event(), threading.Event()

    class SlowLlm(SimpleLlm):
        calls = 0

        def chat(self, messages, tools=None):
            self.calls += 1
            entered.set()
            assert release.wait(5)
            return {"content": "Tere!"}

    client.app.state.stack["llm_primary"] = SlowLlm()
    key = start(client)
    session = client.app.state.demo_sessions.sessions[key]

    async def check():
        exchange = await AsgiExchange(
            client.app, {"session_id": key, "text": "Soovin testbroneeringut"}
        ).start()
        try:
            assert await asyncio.to_thread(entered.wait, 2)
            session.recap_delivery = {"id": "a" * 32}
            await exchange.disconnect()
            assert session.busy and session.recap_delivery is None
            from fastapi import HTTPException

            with pytest.raises(HTTPException) as denied:
                client.app.state.demo_sessions.acquire(key, session.owner)
            assert denied.value.status_code == 409
            (producer,) = client.app.state.turn_producers
            release.set()
            await asyncio.wait_for(producer, 2)
            assert not session.busy and session.recap_delivery is None
            assert client.app.state.stack["llm_primary"].calls == 1
        finally:
            release.set()
            if not exchange.task.done():
                await exchange.disconnect()

    asyncio.run(check())
