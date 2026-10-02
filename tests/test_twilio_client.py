"""Synchronous test facade over real loopback aiohttp, not an ASGI simulation."""

import asyncio
import json
import threading
from types import SimpleNamespace

import httpx
import pytest

aiohttp = pytest.importorskip("aiohttp")
from aiohttp import web


class WebSocketDisconnect(Exception):
    def __init__(self, code=1000):
        self.code, self.reason = code, ""


class WebSocketDenialResponse(Exception):
    def __init__(self, status, headers):
        self.status_code, self.headers = status, headers


class TestClient:
    __test__ = False

    def __init__(self, app):
        from app.twilio_bridge import STATE

        self.application = app
        self.app = SimpleNamespace(state=app[STATE])
        self.loop = asyncio.new_event_loop()
        self.started = threading.Event()

    def run(self, coroutine):
        return asyncio.run_coroutine_threadsafe(coroutine, self.loop).result(timeout=15)

    async def setup(self):
        self.runner = web.AppRunner(
            self.application,
            access_log=None,
            shutdown_timeout=5,
            handler_cancellation=True,
        )
        await self.runner.setup()
        site = web.TCPSite(self.runner, "127.0.0.1", 0)
        await site.start()
        self.port = self.runner.addresses[0][1]
        self.session = aiohttp.ClientSession()

    def __enter__(self):
        def serve():
            self.loop.run_until_complete(self.setup())
            self.started.set()
            self.loop.run_forever()

        self.thread = threading.Thread(target=serve, daemon=True)
        self.thread.start()
        assert self.started.wait(5), "test server did not start"
        self.http = httpx.Client(base_url=f"http://127.0.0.1:{self.port}", timeout=5)
        return self

    def __exit__(self, *_):
        self.http.close()

        async def close():
            await self.session.close()
            await self.runner.cleanup()

        self.run(close())
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(5)
        self.loop.close()

    def post(self, *args, **kwargs):
        return self.http.post(*args, **kwargs)

    def get(self, *args, **kwargs):
        return self.http.get(*args, **kwargs)

    def websocket_connect(self, path, headers=None):
        return Socket(self, path, headers)


class Socket:
    def __init__(self, client, path, headers):
        self.client, self.path, self.headers = client, path, headers

    def __enter__(self):
        async def connect():
            return await self.client.session.ws_connect(
                f"ws://127.0.0.1:{self.client.port}" + self.path,
                headers=self.headers,
                max_msg_size=4096,
            )

        try:
            self.socket = self.client.run(connect())
        except aiohttp.WSServerHandshakeError as error:
            raise WebSocketDenialResponse(error.status, error.headers) from None
        return self

    def __exit__(self, *_):
        async def close():
            await self.socket.close()
            async with asyncio.timeout(3):
                while self.client.app.state.sockets:
                    await asyncio.sleep(0.01)

        self.client.run(close())

    def send_json(self, message):
        self.client.run(self.socket.send_json(message))

    def send_text(self, text):
        self.client.run(self.socket.send_str(text))

    def send_bytes(self, data):
        self.client.run(self.socket.send_bytes(data))

    def receive_json(self):
        message = self.client.run(self.socket.receive(timeout=5))
        if message.type != aiohttp.WSMsgType.TEXT:
            raise WebSocketDisconnect(
                message.data
                if message.type == aiohttp.WSMsgType.CLOSE
                else self.socket.close_code or 1000
            )
        return json.loads(message.data)
