"""Request-local MP3 transport; the existing turn still owns booking truth."""

from __future__ import annotations

import asyncio
import base64
import json
from inspect import getattr_static
import queue
import threading
import time

from starlette.responses import StreamingResponse

from .providers.errors import ProviderError

MAX_AUDIO_BYTES = 8 * 1024 * 1024
AUDIO_CHUNK_BYTES = 32 * 1024
STREAM_DELIVERY_TIMEOUT = 120.0


class AudioEvents:
    """Bounded thread-to-loop bridge that stops emitting, not producing, on EOF."""

    def __init__(self, on_disconnect):
        self.loop = asyncio.get_running_loop()
        self.queue = queue.Queue(maxsize=8)
        self.ready = asyncio.Event()
        self.closed = threading.Event()
        self.finished = False
        self.delivered = False
        self.on_disconnect = on_disconnect
        self.deadline = time.monotonic() + STREAM_DELIVERY_TIMEOUT

    def emit(self, event):
        while not self.closed.is_set():
            if time.monotonic() >= self.deadline:
                # Retire transport only; the owned write/synthesis still drains.
                self.disconnect()
                return
            try:
                self.queue.put(event, timeout=0.05)
                self.loop.call_soon_threadsafe(self.ready.set)
                return
            except queue.Full:
                continue

    async def finish(self, response):
        try:
            await asyncio.to_thread(
                self.emit, {**response, "type": "done", "audio_b64": ""}
            )
        finally:
            self.finished = True
            self.ready.set()

    def disconnect(self):
        self.closed.set()
        if not self.delivered:
            self.on_disconnect()
        while True:
            try:
                self.queue.get_nowait()
            except queue.Empty:
                break
        self.loop.call_soon_threadsafe(self.ready.set)

    async def body(self):
        while not self.closed.is_set():
            self.ready.clear()
            try:
                event = self.queue.get_nowait()
            except queue.Empty:
                if self.finished:
                    return
                await self.ready.wait()
                continue
            yield (
                json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n"
            ).encode()
            if event["type"] == "done":
                self.delivered = True

    def response(self):
        bridge = self

        class Response(StreamingResponse):
            async def __call__(self, scope, receive, send):
                try:
                    await super().__call__(scope, receive, send)
                finally:
                    bridge.disconnect()

        return Response(
            self.body(),
            media_type="application/x-ndjson",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )


class StreamingSpeaker:
    """Return real complete audio to _speak while emitting its bounded chunks."""

    def __init__(self, provider, events):
        self.provider, self.events = provider, events
        self.first_audio_ms = None
        self.seq = 0

    def for_language(self, language):
        if callable(getattr_static(self.provider, "for_language", None)):
            self.provider = self.provider.for_language(language)
        return self

    @property
    def voice_info(self):
        return (
            getattr(self.provider, "voice_info", None)
            if getattr_static(self.provider, "voice_info", None) is not None
            else None
        )

    @property
    def streaming(self):
        return callable(getattr_static(self.provider, "stream", None))

    def synthesize(self, text):
        started = time.perf_counter()
        chunks = (
            self.provider.stream(text)
            if self.streaming
            else (self.provider.synthesize(text),)
        )
        audio = bytearray()
        try:
            for chunk in chunks:
                if not isinstance(chunk, bytes):
                    raise ProviderError("audio_invalid", reason="invalid_response")
                if not chunk:
                    continue
                if len(audio) + len(chunk) > MAX_AUDIO_BYTES:
                    raise ProviderError("audio_too_large", reason="invalid_response")
                if self.first_audio_ms is None:
                    self.first_audio_ms = round(
                        (time.perf_counter() - started) * 1000, 1
                    )
                audio.extend(chunk)
                for offset in range(0, len(chunk), AUDIO_CHUNK_BYTES):
                    self.events.emit(
                        {
                            "type": "audio",
                            "seq": self.seq,
                            "audio_b64": base64.b64encode(
                                chunk[offset : offset + AUDIO_CHUNK_BYTES]
                            ).decode(),
                        }
                    )
                    self.seq += 1
        finally:
            close = getattr(chunks, "close", None)
            if callable(close):
                close()
        return bytes(audio)
