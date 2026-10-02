"""Loopback native aiohttp HTTP/WS proof; RTC alone is stubbed, never providers."""

import asyncio
import socket as sockets
from unittest.mock import patch
from xml.etree import ElementTree as ET

import httpx
import pytest

aiohttp = pytest.importorskip("aiohttp")
from aiohttp import web
from tests.test_twilio_bridge import NativeCall, bridge, connected, media, stop
from tests.test_twilio_security import (
    ACCOUNT,
    CALL,
    ENV,
    MEDIA_URL,
    VOICE_URL,
    sign,
    start,
)


@pytest.mark.parametrize("configured", [False, True])
def test_real_server_signature_denial_and_bound_media_teardown(configured):
    b = bridge()

    async def check():
        sock = sockets.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        NativeCall.opened = []
        with (
            patch.dict("os.environ", ENV if configured else {}, clear=True),
            patch.object(b, "LiveKitCall", NativeCall),
        ):
            app = b.create_app()
            runner = web.AppRunner(app, access_log=None, shutdown_timeout=5)
            await runner.setup()
            await web.SockSite(runner, sock).start()
            try:
                origin = f"http://127.0.0.1:{port}"
                async with (
                    httpx.AsyncClient(timeout=3) as client,
                    aiohttp.ClientSession() as session,
                ):
                    health = await client.get(origin + "/health")
                    assert health.status_code == 200
                    assert health.json() == {"alive": True, "configured": configured}
                    response = await client.post(origin + "/api/twilio/voice")
                    assert response.status_code == (403 if configured else 503)
                    assert response.headers["Cache-Control"] == "no-store"
                    with pytest.raises(aiohttp.WSServerHandshakeError) as denied:
                        await session.ws_connect(
                            origin.replace("http:", "ws:") + "/api/twilio/media"
                        )
                    assert denied.value.status == (403 if configured else 503)
                    assert NativeCall.opened == []
                    if configured:
                        fields = {
                            "AccountSid": [ACCOUNT],
                            "CallSid": [CALL],
                            "To": [ENV["TWILIO_PHONE_NUMBER"]],
                        }
                        response = await client.post(
                            origin + "/api/twilio/voice",
                            data={k: v[0] for k, v in fields.items()},
                            headers={"X-Twilio-Signature": sign(VOICE_URL, fields)},
                        )
                        assert response.status_code == 200
                        binding = (
                            ET.fromstring(response.content)
                            .find("Connect/Stream/Parameter")
                            .get("value")
                        )
                        async with session.ws_connect(
                            origin.replace("http:", "ws:") + "/api/twilio/media",
                            headers={"X-Twilio-Signature": sign(MEDIA_URL)},
                            max_msg_size=4096,
                        ) as ws:
                            await ws.send_json(connected())
                            await ws.send_json(start(binding))
                            outbound = await ws.receive_json(timeout=3)
                            assert (
                                outbound["event"] == "media"
                                and outbound["streamSid"] == "MZ" + "c" * 32
                            )
                            await ws.send_json(media())
                            await ws.send_json(stop())
                            closed = await ws.receive(timeout=3)
                            assert closed.type == aiohttp.WSMsgType.CLOSE
                        async with asyncio.timeout(2):
                            while app[b.STATE].bindings.active_count:
                                await asyncio.sleep(0.01)
                        assert (
                            len(NativeCall.opened) == 1 and NativeCall.opened[0].closed
                        )
                        assert app[b.STATE].bindings.active_count == 0
            finally:
                await asyncio.wait_for(runner.cleanup(), 8)
                sock.close()

    asyncio.run(check())


@pytest.mark.parametrize("terminal", ["stop", "disconnect", "invalid_stop"])
@pytest.mark.parametrize("stage", ["connect", "publish"])
def test_carrier_end_during_setup_prevents_native_dispatch(stage, terminal):
    from tests.test_twilio_livekit import Transport, sdk

    b = bridge()

    async def check():
        entered, release, cancelled = asyncio.Event(), asyncio.Event(), asyncio.Event()

        async def blocked():
            entered.set()
            try:
                await release.wait()
            except asyncio.CancelledError:
                cancelled.set()
                raise

        class Blocked(Transport):
            async def connect(self, *args, **kwargs):
                await super().connect(*args, **kwargs)
                if stage == "connect":
                    await blocked()

            async def publish(self, *args, **kwargs):
                if stage == "publish":
                    await blocked()
                return await super().publish(*args, **kwargs)

        transport = Blocked()
        with patch.dict("os.environ", ENV, clear=True), sdk(transport):
            app = b.create_app()
            runner = web.AppRunner(app, access_log=None, shutdown_timeout=5)
            await runner.setup()
            await web.TCPSite(runner, "127.0.0.1", 0).start()
            origin = f"http://127.0.0.1:{runner.addresses[0][1]}"
            try:
                async with (
                    httpx.AsyncClient(timeout=3) as client,
                    aiohttp.ClientSession() as session,
                ):
                    fields = {
                        "AccountSid": [ACCOUNT],
                        "CallSid": [CALL],
                        "To": [ENV["TWILIO_PHONE_NUMBER"]],
                    }
                    response = await client.post(
                        origin + "/api/twilio/voice",
                        data={k: v[0] for k, v in fields.items()},
                        headers={"X-Twilio-Signature": sign(VOICE_URL, fields)},
                    )
                    binding = (
                        ET.fromstring(response.content)
                        .find("Connect/Stream/Parameter")
                        .get("value")
                    )
                    async with session.ws_connect(
                        origin.replace("http:", "ws:") + "/api/twilio/media",
                        headers={"X-Twilio-Signature": sign(MEDIA_URL)},
                        timeout=aiohttp.ClientWSTimeout(ws_close=0.1),
                    ) as ws:
                        await ws.send_json(connected())
                        await ws.send_json(start(binding))
                        await asyncio.wait_for(entered.wait(), 2)
                        if terminal == "disconnect":
                            await ws.close()
                        else:
                            message = stop(2)
                            if terminal == "invalid_stop":
                                message["stop"]["callSid"] = "CA" + "f" * 32
                            await ws.send_json(message)
                        # Real socket input arrives while the owned SDK await is blocked.
                        await asyncio.wait_for(cancelled.wait(), 2)
                        assert not release.is_set(), (
                            "setup was not cancelled until the SDK await resumed"
                        )
                        release.set()
                        if terminal != "disconnect":
                            closed = await ws.receive(timeout=2)
                            assert closed.type == aiohttp.WSMsgType.CLOSE
                    async with asyncio.timeout(2):
                        while app[b.STATE].bindings.active_count:
                            await asyncio.sleep(0.01)
                assert not [
                    event for event, _ in transport.events if event == "dispatch"
                ], "caller ended during setup but a paid native dispatch still occurred"
                room = next(
                    request.name
                    for event, request in transport.events
                    if event == "create"
                )
                assert [
                    request.room
                    for event, request in transport.events
                    if event == "delete"
                ] == [room]
                assert app[b.STATE].sockets == 0
            finally:
                release.set()
                await runner.cleanup()

    asyncio.run(check())
