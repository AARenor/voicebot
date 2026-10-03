"""Cross-lane contracts: actual catalog, bounded transport and receipt ownership."""

import asyncio
import time

import pytest

from tests.test_browser_audio_stream import AsgiExchange, StreamingSpeaker
from tests.test_product_demo import AUTH, client, start


def test_stream_explicitly_disables_proxy_buffering(client):
    response = client.post(
        "/api/turn",
        headers={**AUTH, "Accept": "application/x-ndjson"},
        json={"text": "Tere"},
    )
    assert response.status_code == 200
    assert response.headers.get("x-accel-buffering") == "no"


@pytest.mark.parametrize(
    "setting,want",
    [
        (None, 650),
        ("800", 800),
        ("300", 300),
        ("2000", 2000),
        ("0", 650),
        ("2001", 650),
        ("not-a-number", 650),
        ("650.5", 650),
    ],
)
def test_actual_catalog_matches_browser_envelope_and_bounds_endpointing(
    client, monkeypatch, setting, want
):
    if setting is None:
        monkeypatch.delenv("VOICEBOT_MIC_SILENCE_MS", raising=False)
    else:
        monkeypatch.setenv("VOICEBOT_MIC_SILENCE_MS", setting)
    response = client.get("/api/demo/voices", headers=AUTH)
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, dict), "browser requires a named voices envelope"
    assert set(data) == {"voices", "endpointing_ms"}
    assert data["endpointing_ms"] == want
    assert [row["id"] for row in data["voices"]] == [
        "azure",
        "elevenlabs",
        "google",
        "cartesia",
    ]
    assert data["voices"][0]["available"] is True
    assert all(not row["available"] for row in data["voices"][1:])
    assert response.headers["cache-control"] == "no-store"


def test_expired_transport_unblocks_a_full_queue_without_cancelling_work():
    from app.browser_audio import AudioEvents

    async def check():
        invalidated = []
        events = AudioEvents(lambda: invalidated.append(True))
        for _ in range(events.queue.maxsize):
            events.queue.put_nowait({"type": "audio", "audio_b64": "eA=="})
        events.deadline = time.monotonic() - 1
        task = asyncio.create_task(asyncio.to_thread(events.emit, {"type": "reply"}))
        try:
            try:
                await asyncio.wait_for(asyncio.shield(task), 0.2)
            except TimeoutError:
                pytest.fail(
                    "expired transport left its producer blocked on backpressure"
                )
            assert events.closed.is_set() and invalidated == [True]
            assert events.queue.empty()
        finally:
            events.disconnect()
            await task

    asyncio.run(check())


def test_late_disconnect_from_old_turn_cannot_clear_new_owned_receipt(client):
    async def check():
        speaker = StreamingSpeaker(blocked=True)
        client.app.state.stack["tts"] = speaker
        key = start(client)
        session = client.app.state.demo_sessions.sessions[key]
        exchange = await AsgiExchange(
            client.app, {"session_id": key, "text": "Tere"}
        ).start()
        try:
            assert (await exchange.event())["type"] == "reply"
            assert (await exchange.event())["type"] == "audio"
            old_transport = next(iter(client.app.state.turn_streams))
            speaker.release.set()
            await asyncio.wait_for(asyncio.gather(*client.app.state.turn_producers), 2)
            acquired = client.app.state.demo_sessions.acquire(key, session.owner)
            assert acquired is session
            new_receipt = {"id": "b" * 32}
            session.recap_delivery = new_receipt
            old_transport.on_disconnect()
            assert session.recap_delivery is new_receipt, (
                "old transport invalidated a later generation's receipt"
            )
            client.app.state.demo_sessions.release(session)
        finally:
            speaker.release.set()
            if not exchange.task.done():
                await exchange.disconnect()

    asyncio.run(check())
