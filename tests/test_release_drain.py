"""Release shutdown must finish admitted calls instead of cancelling them."""

import asyncio
from unittest.mock import patch

import pytest


def test_bridge_shutdown_waits_for_an_admitted_stream_to_finish():
    pytest.importorskip("aiohttp")
    from app import twilio_bridge as bridge

    async def run():
        with patch.dict("os.environ", {}, clear=True):
            app = bridge.create_app()
        app.freeze()
        release = asyncio.Event()
        finished = []

        async def stream():
            await release.wait()
            finished.append(True)

        task = asyncio.create_task(stream())
        app[bridge.STATE].running.add(task)
        shutdown = asyncio.create_task(app.shutdown())
        try:
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            assert not task.cancelled(), "deployment cancelled an admitted stream"
            assert not shutdown.done(), "shutdown did not wait for the stream"
            release.set()
            await asyncio.wait_for(shutdown, 1)
            assert finished == [True]
        finally:
            release.set()
            for pending in (task, shutdown):
                if not pending.done():
                    pending.cancel()
            await asyncio.gather(task, shutdown, return_exceptions=True)

    asyncio.run(run())


def test_bridge_rejects_new_admission_while_existing_stream_drains():
    pytest.importorskip("aiohttp")
    from app import twilio_bridge as bridge
    from tests.test_twilio_client import TestClient
    from tests.test_twilio_security import ENV, MEDIA_URL, sign

    with (
        patch.dict("os.environ", ENV, clear=True),
        TestClient(bridge.create_app()) as client,
    ):

        async def start_drain():
            release = asyncio.Event()
            task = asyncio.create_task(release.wait())
            client.application[bridge.STATE].running.add(task)
            shutdown = asyncio.create_task(client.application.shutdown())
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            return release, task, shutdown

        release, task, shutdown = client.run(start_drain())
        try:
            voice = client.post("/api/twilio/voice")
            assert voice.status_code == 503
            assert voice.json()["detail"] == "bridge_draining"
            media = client.get(
                "/api/twilio/media", headers={"X-Twilio-Signature": sign(MEDIA_URL)}
            )
            assert media.status_code == 503
            assert client.application[bridge.STATE].sockets == 0
        finally:

            async def finish():
                release.set()
                await asyncio.gather(task, shutdown, return_exceptions=True)

            client.run(finish())


def test_worker_sdk_drain_budget_allows_the_bounded_call_to_complete():
    pytest.importorskip("livekit.agents")
    from app.worker import server

    # Admission/setup, a 600-second call and independently bounded cleanup must
    # finish before the SDK's CLI forces shutdown. Docker grace is checked live.
    assert server._drain_timeout >= 900


def test_bridge_drain_timeout_is_a_failure_not_a_successful_shutdown():
    pytest.importorskip("aiohttp")
    from app import twilio_bridge as bridge

    async def run():
        with patch.dict("os.environ", {}, clear=True):
            app = bridge.create_app()
        app.freeze()
        task = asyncio.create_task(asyncio.Event().wait())
        app[bridge.STATE].running.add(task)
        try:
            with patch.object(bridge, "DRAIN_TIMEOUT", 0.01, create=True):
                with pytest.raises(RuntimeError, match="bridge_drain_timeout"):
                    await app.shutdown()
            assert task.cancelled()
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(run())
