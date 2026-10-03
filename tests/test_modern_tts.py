"""Offline protocol and failure tests; all authorization fixtures are synthetic."""

import base64
import importlib
import importlib.util
import json
from dataclasses import FrozenInstanceError

import httpx
import pytest

from app.providers.azure_tts import AzureTtsClient
from app.providers.errors import ProviderError


# Two complete MPEG-1 layer-III frames, not a magic-prefix-only fixture.
FRAME = b"\xff\xfb\x90\x00" + bytes(413)
MP3 = FRAME * 2
TEXT = "  Tere <Mari> & 21. oktoober! Привет.\n"
VOICE_ID = "00000000-0000-4000-8000-000000000001"


def test_eleven_pinned_websocket_transport_emits_before_terminal_completion():
    """Wrong connect options or buffered receive must break this real boundary."""
    import threading

    sync_client = pytest.importorskip("websockets.sync.client")
    sync_server = pytest.importorskip("websockets.sync.server")
    release = threading.Event()
    received = []

    def handler(socket):
        received.append(socket.request.headers.get("xi-api-key"))
        for _ in range(3):
            received.append(json.loads(socket.recv(timeout=3)))
        socket.send(json.dumps(audio_message(FRAME)))
        if release.wait(3):
            socket.send(json.dumps(audio_message(FRAME, True)))

    with sync_server.serve(handler, "127.0.0.1", 0) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        uri = f"ws://127.0.0.1:{server.socket.getsockname()[1]}"

        def connector(url, **options):
            assert url == (
                "wss://api.elevenlabs.io/v1/text-to-dialogue/stream-input"
                "?model_id=eleven_v4_turbo&output_format=mp3_44100_128"
            )
            return sync_client.connect(uri, **options)

        client = modern().ElevenLabsTtsClient(
            "synthetic-eleven", "synthetic-voice", connector=connector
        )
        iterator = client.for_language("et").stream(TEXT)
        try:
            assert next(iterator) == FRAME
            assert not release.is_set()
            assert received == [
                "synthetic-eleven",
                {"voices": ["synthetic-voice"]},
                {
                    "inputs": [
                        {"text": TEXT, "voice_id": "synthetic-voice", "new_turn": False}
                    ]
                },
                {"close_socket": True},
            ]
            release.set()
            assert list(iterator) == [FRAME]
        finally:
            release.set()
            iterator.close()
            client.close()
    thread.join(timeout=3)
    assert not thread.is_alive()


def modern():
    assert importlib.util.find_spec("app.providers.modern_tts"), (
        "modern TTS boundary missing"
    )
    return importlib.import_module("app.providers.modern_tts")


class ByteStream(httpx.SyncByteStream):
    def __init__(self, chunks, error=None):
        self.chunks, self.error, self.closed = chunks, error, False

    def __iter__(self):
        yield from self.chunks
        if self.error:
            raise self.error

    def close(self):
        self.closed = True


class Socket:
    def __init__(self, messages):
        self.messages = iter(messages)
        self.sent, self.timeouts, self.closed = [], [], False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def send(self, message):
        self.sent.append(json.loads(message))

    def recv(self, timeout):
        self.timeouts.append(timeout)
        item = next(self.messages)
        if isinstance(item, Exception):
            raise item
        return json.dumps(item)

    def close(self):
        self.closed = True


def eleven(messages):
    socket, calls = Socket(messages), []

    def connect(url, **kwargs):
        calls.append((url, kwargs))
        return socket

    client = modern().ElevenLabsTtsClient(
        "synthetic-eleven", "synthetic-voice", connector=connect
    )
    return client, socket, calls


def audio_message(audio=MP3, final=False):
    return {"audio": base64.b64encode(audio).decode(), "is_final": final}


@pytest.mark.parametrize(
    "language,locale", [("et", "et-EE"), ("en", "en-US"), ("ru", "ru-RU")]
)
def test_google_exact_buffered_contract(language, locale):
    requests = []

    def handler(request):
        requests.append(request)
        assert (
            str(request.url) == "https://texttospeech.googleapis.com/v1/text:synthesize"
        )
        assert request.headers["authorization"] == "Bearer synthetic-google"
        assert request.headers["x-goog-user-project"] == "synthetic-project"
        assert json.loads(request.content) == {
            "input": {"text": TEXT},
            "voice": {"languageCode": locale, "name": locale + "-Chirp3-HD-Kore"},
            "audioConfig": {"audioEncoding": "MP3"},
        }
        return httpx.Response(
            200, json={"audioContent": base64.b64encode(MP3).decode()}
        )

    client = modern().GoogleTtsClient(
        "synthetic-google",
        quota_project="synthetic-project",
        transport=httpx.MockTransport(handler),
    )
    try:
        view = client.for_language(language)
        assert view.synthesize(TEXT) == MP3
        assert list(view.stream(TEXT)) == [MP3]
        assert client.audio_type == "audio/mpeg"
        assert client.streaming is False
        assert len(requests) == 2
        with pytest.raises((FrozenInstanceError, AttributeError)):
            view.language = "ru"
        assert "synthetic-google" not in repr(client)
    finally:
        client.close()


def test_google_adc_refreshes_request_headers_without_network_or_key_files():
    events = []

    class Credentials:
        def before_request(self, request, method, url, headers):
            events.append((request, method, url))
            headers["authorization"] = "Bearer synthetic-refreshed"

    request_adapter = object()

    def handler(request):
        assert request.headers["authorization"] == "Bearer synthetic-refreshed"
        assert len(events) == 1
        return httpx.Response(
            200, json={"audioContent": base64.b64encode(MP3).decode()}
        )

    client = modern().GoogleTtsClient(
        use_adc=True,
        credentials=Credentials(),
        auth_request=request_adapter,
        transport=httpx.MockTransport(handler),
    )
    try:
        assert client.synthesize(TEXT) == MP3
        assert events == [
            (
                request_adapter,
                "POST",
                "https://texttospeech.googleapis.com/v1/text:synthesize",
            )
        ]
    finally:
        client.close()


@pytest.mark.parametrize("language", ["et", "en", "ru"])
def test_eleven_documented_websocket_preserves_text_requires_final_and_closes(language):
    client, socket, calls = eleven([audio_message(FRAME), audio_message(FRAME, True)])
    try:
        assert client.for_language(language).synthesize(TEXT) == MP3
        assert (
            calls[0][0]
            == "wss://api.elevenlabs.io/v1/text-to-dialogue/stream-input?model_id=eleven_v4_turbo&output_format=mp3_44100_128"
        )
        options = calls[0][1]
        assert options["additional_headers"] == {"xi-api-key": "synthetic-eleven"}
        assert 0 < options["open_timeout"] <= 10
        assert 0 < options["close_timeout"] <= 5
        assert options["max_size"] <= 1024 * 1024
        assert options["max_queue"] <= 16
        assert socket.sent[0] == {"voices": ["synthetic-voice"]}
        assert socket.sent[1] == {
            "inputs": [{"text": TEXT, "voice_id": "synthetic-voice", "new_turn": False}]
        }
        assert socket.sent[-1] == {"close_socket": True}
        assert all(0 < timeout <= 10 for timeout in socket.timeouts)
        assert socket.closed
        assert client.streaming is True
        assert "synthetic-eleven" not in repr(client)
        assert "synthetic-voice" not in repr(client.for_language(language))
    finally:
        client.close()


@pytest.mark.parametrize(
    "messages,reason",
    [
        ([{"audio": "!!!", "is_final": True}], "invalid_response"),
        ([{"error": "private upstream detail", "is_final": True}], "request_rejected"),
        ([audio_message(FRAME)], "completion_incomplete"),
        ([TimeoutError("private timeout detail")], "transport_error"),
        ([audio_message(b"", True)], "invalid_response"),
        ([audio_message(FRAME[:-1], True)], "completion_incomplete"),
    ],
)
def test_eleven_malformed_empty_timeout_and_premature_close_are_safe(messages, reason):
    client, socket, _ = eleven(messages)
    try:
        with pytest.raises(ProviderError) as caught:
            client.synthesize(TEXT)
        assert caught.value.reason == reason
        assert "private" not in str(caught.value)
        assert "synthetic" not in repr(caught.value)
        assert socket.closed
    finally:
        client.close()


@pytest.mark.parametrize("language", ["en", "ru"])
def test_cartesia_exact_contract_streams_before_completion(language):
    stream = ByteStream([FRAME, FRAME])

    def handler(request):
        assert str(request.url) == "https://api.cartesia.ai/tts/bytes"
        assert request.headers["authorization"] == "Bearer synthetic-cartesia"
        assert request.headers["cartesia-version"] == "2026-08-14"
        assert json.loads(request.content) == {
            "model_id": "sonic-3.6-2026-08-27",
            "transcript": TEXT,
            "voice": {"id": VOICE_ID},
            "language": language,
            "normalization": "off",
            "output_format": {
                "container": "mp3",
                "sample_rate": 44100,
                "bit_rate": 128000,
            },
        }
        return httpx.Response(200, stream=stream)

    client = modern().CartesiaTtsClient(
        "synthetic-cartesia", VOICE_ID, transport=httpx.MockTransport(handler)
    )
    try:
        iterator = client.for_language(language).stream(TEXT)
        assert next(iterator) == FRAME
        assert not stream.closed
        assert list(iterator) == [FRAME]
        assert stream.closed
        assert client.languages == ("en", "ru")
        assert client.streaming is True
    finally:
        client.close()


def test_cartesia_partial_failure_is_typed_and_closes_response():
    stream = ByteStream([FRAME], httpx.ReadError("private upstream detail"))
    client = modern().CartesiaTtsClient(
        "synthetic-cartesia",
        VOICE_ID,
        transport=httpx.MockTransport(lambda r: httpx.Response(200, stream=stream)),
    )
    try:
        iterator = client.stream(TEXT)
        assert next(iterator) == FRAME
        with pytest.raises(ProviderError) as caught:
            next(iterator)
        assert caught.value.reason == "transport_error"
        assert "private" not in repr(caught.value)
        assert stream.closed
    finally:
        client.close()


@pytest.mark.parametrize(
    "status,reason",
    [(401, "request_rejected"), (429, "rate_limited"), (503, "provider_unavailable")],
)
@pytest.mark.parametrize("provider", ["google", "cartesia"])
def test_http_errors_do_not_expose_bodies_or_credentials(provider, status, reason):
    transport = httpx.MockTransport(
        lambda r: httpx.Response(
            status, text="private upstream detail", headers={"retry-after": "2"}
        )
    )
    module = modern()
    client = (
        module.GoogleTtsClient("synthetic-google", transport=transport)
        if provider == "google"
        else module.CartesiaTtsClient(
            "synthetic-cartesia", VOICE_ID, transport=transport
        )
    )
    try:
        with pytest.raises(ProviderError) as caught:
            client.synthesize(TEXT)
        assert caught.value.reason == reason
        assert caught.value.status_code == status
        assert "private" not in repr(caught.value)
        assert "https://" not in str(caught.value)
    finally:
        client.close()


@pytest.mark.parametrize(
    "audio,reason",
    [
        (b"", "invalid_response"),
        (b"not mp3", "invalid_response"),
        (MP3[:-1], "completion_incomplete"),
        (MP3 + b"junk", "invalid_response"),
    ],
)
@pytest.mark.parametrize("provider", ["google", "cartesia"])
def test_invalid_and_truncated_audio_never_completes(provider, audio, reason):
    module = modern()
    transport = httpx.MockTransport(
        lambda r: (
            httpx.Response(200, json={"audioContent": base64.b64encode(audio).decode()})
            if provider == "google"
            else httpx.Response(200, content=audio)
        )
    )
    client = (
        module.GoogleTtsClient("synthetic-google", transport=transport)
        if provider == "google"
        else module.CartesiaTtsClient(
            "synthetic-cartesia", VOICE_ID, transport=transport
        )
    )
    try:
        with pytest.raises(ProviderError) as caught:
            client.synthesize(TEXT)
        assert caught.value.reason == reason
    finally:
        client.close()


@pytest.mark.parametrize(
    "payload", [{}, [], {"audioContent": "!!!"}, {"audioContent": 123}]
)
def test_google_bad_envelopes_are_typed(payload):
    client = modern().GoogleTtsClient(
        "synthetic-google",
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json=payload)),
    )
    try:
        with pytest.raises(ProviderError) as caught:
            client.synthesize(TEXT)
        assert caught.value.reason == "invalid_response"
    finally:
        client.close()


def test_bounds_reject_before_network_and_large_audio_is_rejected(monkeypatch):
    module = modern()
    requests = []
    client = module.GoogleTtsClient(
        "synthetic-google",
        transport=httpx.MockTransport(
            lambda r: (
                requests.append(r)
                or httpx.Response(
                    200, json={"audioContent": base64.b64encode(MP3).decode()}
                )
            )
        ),
    )
    try:
        for invalid in ("", " " * 10, "x" * 6000, None):
            with pytest.raises(ProviderError):
                client.synthesize(invalid)
        assert requests == []
        monkeypatch.setattr(module, "MAX_AUDIO_BYTES", len(FRAME))
        with pytest.raises(ProviderError):
            client.synthesize(TEXT)
    finally:
        client.close()


def test_azure_stream_is_real_and_keeps_format_cache_ssml_and_language():
    streams, requests = [], []

    def handler(request):
        requests.append(request)
        if "issueToken" in str(request.url):
            return httpx.Response(200, text="synthetic-azure")
        assert (
            request.headers["X-Microsoft-OutputFormat"]
            == "audio-48khz-96kbitrate-mono-mp3"
        )
        assert 'name="en-US-JennyNeural"' in request.content.decode()
        assert "&lt;Mari&gt; &amp;" in request.content.decode()
        stream = ByteStream([FRAME, FRAME])
        streams.append(stream)
        return httpx.Response(200, stream=stream)

    client = AzureTtsClient(
        "synthetic-azure-key",
        "northeurope",
        "et-EE-AnuNeural",
        "et-EE",
        languages={"en": ("en-US-JennyNeural", "en-US")},
        transport=httpx.MockTransport(handler),
    )
    try:
        assert callable(getattr(client, "stream", None)), "Azure HTTP streaming missing"
        view = client.for_language("en")
        iterator = view.stream(TEXT)
        assert next(iterator) == FRAME
        assert not streams[0].closed
        iterator.close()
        assert streams[0].closed
        assert b"".join(view.stream(TEXT)) == MP3
        assert len([r for r in requests if "issueToken" in str(r.url)]) == 1
    finally:
        client.close()


def test_azure_stream_refreshes_once_before_audio_and_never_after_audio():
    synths, sources = [], []

    def handler(request):
        if "issueToken" in str(request.url):
            return httpx.Response(200, text="synthetic-azure")
        synths.append(request)
        source = (
            ByteStream([])
            if len(synths) == 1
            else ByteStream([FRAME], httpx.ReadError("private upstream detail"))
        )
        sources.append(source)
        return httpx.Response(401 if len(synths) == 1 else 200, stream=source)

    client = AzureTtsClient(
        "synthetic-azure-key",
        "northeurope",
        "et-EE-AnuNeural",
        "et-EE",
        transport=httpx.MockTransport(handler),
    )
    try:
        assert callable(getattr(client, "stream", None)), "Azure HTTP streaming missing"
        iterator = client.stream(TEXT)
        assert next(iterator) == FRAME
        with pytest.raises(ProviderError) as caught:
            next(iterator)
        assert "private" not in str(caught.value)
        assert len(synths) == 2
        assert all(source.closed for source in sources)
    finally:
        client.close()


@pytest.mark.parametrize("cut", [1, 3, 9, 100, len(FRAME) - 1])
def test_stream_handles_split_id3_and_frames_without_dropping_bytes(cut):
    audio = b"ID3\x04\x00\x00\x00\x00\x00\x03abc" + MP3 + b"TAG" + bytes(125)
    source = ByteStream(
        [audio[index : index + cut] for index in range(0, len(audio), cut)]
    )
    client = modern().CartesiaTtsClient(
        "synthetic-cartesia",
        VOICE_ID,
        transport=httpx.MockTransport(lambda r: httpx.Response(200, stream=source)),
    )
    try:
        assert b"".join(client.stream(TEXT)) == audio
        assert source.closed
    finally:
        client.close()


def test_eleven_cancel_and_client_close_release_live_connection():
    client, socket, _ = eleven([audio_message(FRAME), audio_message(FRAME, True)])
    iterator = client.stream(TEXT)
    assert next(iterator) == FRAME
    assert not socket.closed
    client.close()
    assert socket.closed
    iterator.close()
    assert client._sockets == set()


def test_eleven_deadline_cannot_be_extended_by_empty_metadata(monkeypatch):
    module = modern()
    client, socket, _ = eleven([{}, {}, {}, {}])
    ticks = iter([0.0, 1.0, 36.0, 37.0])
    monkeypatch.setattr(module.time, "monotonic", lambda: next(ticks))
    with pytest.raises(ProviderError) as caught:
        client.synthesize(TEXT)
    assert caught.value.reason == "transport_error"
    assert socket.closed
    client.close()


def test_eleven_final_audio_received_after_total_deadline_is_not_success(monkeypatch):
    module = modern()
    client, socket, _ = eleven([audio_message(MP3, True)])
    ticks = iter([0.0, 1.0, 36.0])
    monkeypatch.setattr(module.time, "monotonic", lambda: next(ticks))
    with pytest.raises(ProviderError) as caught:
        client.synthesize(TEXT)
    assert caught.value.reason == "transport_error"
    assert socket.closed
    client.close()


@pytest.mark.parametrize("provider", ["google", "cartesia"])
def test_http_redirects_are_not_followed_or_reported_with_private_url(provider):
    requests = []
    module = modern()

    def handler(request):
        requests.append(request)
        return httpx.Response(307, headers={"location": "https://private.example/path"})

    client = (
        module.GoogleTtsClient(
            "synthetic-google", transport=httpx.MockTransport(handler)
        )
        if provider == "google"
        else module.CartesiaTtsClient(
            "synthetic-cartesia", VOICE_ID, transport=httpx.MockTransport(handler)
        )
    )
    try:
        with pytest.raises(ProviderError) as caught:
            client.synthesize(TEXT)
        assert caught.value.reason == "request_rejected"
        assert "private" not in str(caught.value)
        assert len(requests) == 1
    finally:
        client.close()


@pytest.mark.parametrize("audio", [b"", b"not mp3", MP3[:-1]])
def test_azure_stream_rejects_empty_malformed_and_truncated_audio(audio):
    source = ByteStream([audio])
    client = AzureTtsClient(
        "synthetic-azure-key",
        "northeurope",
        "et-EE-AnuNeural",
        "et-EE",
        transport=httpx.MockTransport(
            lambda r: (
                httpx.Response(200, text="synthetic-azure")
                if "issueToken" in str(r.url)
                else httpx.Response(200, stream=source)
            )
        ),
    )
    try:
        with pytest.raises(ProviderError):
            b"".join(client.stream(TEXT))
        assert source.closed
    finally:
        client.close()


def test_google_adc_owned_request_has_bounded_refresh_and_is_closed(monkeypatch):
    import sys
    import types

    module = modern()
    calls, sessions = [], []

    class Request:
        def __init__(self):
            self.closed = False
            self.session = self
            sessions.append(self)

        def __call__(self, *args, **kwargs):
            calls.append(kwargs)
            return object()

        def close(self):
            self.closed = True

    class Credentials:
        def before_request(self, request, method, url, headers):
            request(url="https://oauth.invalid/", method="POST")
            headers["Authorization"] = "Bearer synthetic-refreshed"

    auth = types.ModuleType("google.auth")
    auth.default = lambda **kwargs: (Credentials(), "unused")
    google = types.ModuleType("google")
    google.auth = auth
    request_module = types.ModuleType("google.auth.transport.requests")
    request_module.Request = Request
    monkeypatch.setitem(sys.modules, "google", google)
    monkeypatch.setitem(sys.modules, "google.auth", auth)
    monkeypatch.setitem(sys.modules, "google.auth.transport.requests", request_module)
    client = module.GoogleTtsClient(
        use_adc=True,
        transport=httpx.MockTransport(
            lambda r: httpx.Response(
                200, json={"audioContent": base64.b64encode(MP3).decode()}
            )
        ),
    )
    try:
        assert client.synthesize(TEXT) == MP3
        assert all(
            0 < call.get("timeout", float("inf")) <= module.READ_TIMEOUT
            for call in calls
        )
    finally:
        client.close()
    assert sessions and all(session.closed for session in sessions)
