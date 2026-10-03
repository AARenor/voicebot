"""Optional MP3 providers. Fixed endpoints, exact text, and safe error envelopes.

Dependencies are imported only when used; readiness is never an audition.
"""

from __future__ import annotations

import base64
import binascii
import json
import re
import threading
import time
from dataclasses import dataclass, field
from types import MappingProxyType

import httpx

from .errors import ProviderError, RateLimitedError, RetryableProviderError

MAX_AUDIO_BYTES = 8 * 1024 * 1024
MAX_MESSAGE_BYTES = 1024 * 1024
TOTAL_TIMEOUT = 35.0
READ_TIMEOUT = 10.0
GOOGLE_URL = "https://texttospeech.googleapis.com/v1/text:synthesize"
CARTESIA_URL = "https://api.cartesia.ai/tts/bytes"
ELEVEN_URL = (
    "wss://api.elevenlabs.io/v1/text-to-dialogue/stream-input"
    "?model_id=eleven_v4_turbo&output_format=mp3_44100_128"
)
LOCALES = {"et": "et-EE", "en": "en-US", "ru": "ru-RU"}


def provider_error(reason="invalid_response", status=None):
    """Never include a provider payload, exception, URL, or configuration."""
    cls = (
        RetryableProviderError
        if reason in {"transport_error", "provider_unavailable"}
        else ProviderError
    )
    return cls(reason, reason=reason, status_code=status)


def check_status(response):
    status = response.status_code
    if 200 <= status < 300:
        return
    if status == 429:
        # Response headers are untrusted too; expose no arbitrary text.
        try:
            retry = float(response.headers.get("retry-after", ""))
            retry = retry if 0 <= retry <= 3600 else None
        except ValueError:
            retry = None
        raise RateLimitedError("rate_limited", retry) from None
    raise provider_error(
        "provider_unavailable" if status >= 500 else "request_rejected", status
    ) from None


def validate_text(text, limit=5000, *, byte_limit=None):
    if not isinstance(text, str) or not text.strip() or len(text) > limit:
        raise provider_error("request_rejected") from None
    try:
        encoded = text.encode("utf-8")
    except UnicodeError:
        raise provider_error("request_rejected") from None
    if len(encoded) > (byte_limit or limit * 4):
        raise provider_error("request_rejected") from None


def validate_config(value, pattern=None):
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 4096
        or any(ord(char) < 33 or ord(char) > 126 for char in value)
        or (pattern and re.fullmatch(pattern, value) is None)
    ):
        raise ValueError("invalid provider configuration") from None
    return value


def remaining(deadline):
    seconds = deadline - time.monotonic()
    if seconds <= 0:
        raise provider_error("transport_error") from None
    return min(READ_TIMEOUT, seconds)


def decode_audio(value, limit=MAX_AUDIO_BYTES):
    if not isinstance(value, str) or len(value) > ((limit + 2) // 3) * 4:
        raise provider_error() from None
    try:
        audio = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error):
        raise provider_error() from None
    if len(audio) > limit:
        raise provider_error() from None
    return audio


class Mp3Audio:
    """Incremental layer-III framing check; hold incomplete frames until complete.

    Checks framing/length, not perceived quality or MPEG sample decoding.
    """

    def __init__(self):
        self.pending = bytearray()
        self.prefix = bytearray()
        self.total = self.frames = 0
        self.tag_seen = self.finished_tag = False

    def feed(self, chunk):
        if not isinstance(chunk, bytes):
            raise provider_error() from None
        self.total += len(chunk)
        if self.total > MAX_AUDIO_BYTES or (self.finished_tag and chunk):
            raise provider_error() from None
        self.pending.extend(chunk)
        output = bytearray()
        offset = 0
        while len(self.pending) - offset >= 4:
            head = self.pending[offset : offset + 10]
            if not self.frames and not self.tag_seen and head[:3] == b"ID3":
                if len(head) < 10:
                    break
                if (
                    head[3] not in (2, 3, 4)
                    or head[4] == 255
                    or any(n & 128 for n in head[6:10])
                ):
                    raise provider_error() from None
                size = 10 + sum(
                    n << shift for n, shift in zip(head[6:10], (21, 14, 7, 0))
                )
                if head[3] == 4 and head[5] & 16:
                    size += 10
                if size > MAX_AUDIO_BYTES:
                    raise provider_error() from None
                if len(self.pending) - offset < size:
                    break
                self.prefix.extend(self.pending[offset : offset + size])
                self.tag_seen = True
                offset += size
                continue
            if self.frames and head[:3] == b"TAG":
                if len(self.pending) - offset < 128:
                    break
                if len(self.pending) - offset != 128:
                    raise provider_error() from None
                output.extend(self.pending[offset:])
                offset += 128
                self.finished_tag = True
                break
            bits = int.from_bytes(head[:4], "big")
            version, layer = (bits >> 19) & 3, (bits >> 17) & 3
            bitrate, rate = (bits >> 12) & 15, (bits >> 10) & 3
            if (
                bits >> 21 != 0x7FF
                or version == 1
                or layer != 1
                or bitrate in (0, 15)
                or rate == 3
                or bits & 3 == 2
            ):
                raise provider_error() from None
            rates = (44100, 48000, 32000)
            sample_rate = rates[rate] // (
                1 if version == 3 else 2 if version == 2 else 4
            )
            bitrates = (
                (0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320)
                if version == 3
                else (0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160)
            )
            size = (144000 if version == 3 else 72000) * bitrates[
                bitrate
            ] // sample_rate + ((bits >> 9) & 1)
            if len(self.pending) - offset < size:
                break
            output.extend(self.prefix)
            self.prefix.clear()
            output.extend(self.pending[offset : offset + size])
            offset += size
            self.frames += 1
        del self.pending[:offset]
        return bytes(output)

    def finish(self):
        if self.pending:
            raise provider_error("completion_incomplete") from None
        if not self.frames:
            raise provider_error() from None


@dataclass(frozen=True)
class _LanguageSpeaker:
    client: object = field(repr=False)
    language: str
    audio_type = "audio/mpeg"

    @property
    def streaming(self):
        return self.client.streaming

    def for_language(self, language):
        return self.client.for_language(language)

    def synthesize(self, text):
        return self.client._synthesize(text, self.language)

    def stream(self, text):
        return self.client._stream(text, self.language)


class _Client:
    languages = ("et", "en", "ru")
    audio_type = "audio/mpeg"
    streaming = True

    def __repr__(self):
        return f"{type(self).__name__}(redacted)"

    def for_language(self, language):
        if language not in self.languages:
            raise provider_error("request_rejected") from None
        return _LanguageSpeaker(self, language)

    def synthesize(self, text):
        return self._synthesize(text, self.languages[0])

    def stream(self, text):
        return self._stream(text, self.languages[0])

    def _synthesize(self, text, language):
        return b"".join(self._stream(text, language))


class ElevenLabsTtsClient(_Client):
    def __init__(self, api_key, voice_id, *, connector=None):
        self._key = validate_config(api_key)
        self._voice = validate_config(voice_id, r"[A-Za-z0-9_-]{1,128}")
        self._connector = connector
        self._lock = threading.Lock()
        self._sockets = set()
        self._closed = False

    def close(self):
        with self._lock:
            self._closed = True
            sockets = tuple(self._sockets)
        for socket in sockets:
            try:
                socket.close()
            except Exception:
                pass

    def _stream(self, text, language):
        validate_text(text, 5000)
        deadline = time.monotonic() + TOTAL_TIMEOUT
        audio = Mp3Audio()
        socket = None
        try:
            connector = self._connector
            if connector is None:
                from websockets.sync.client import connect

                connector = connect
            if self._closed:
                raise provider_error("transport_error")
            with connector(
                ELEVEN_URL,
                additional_headers={"xi-api-key": self._key},
                open_timeout=10,
                close_timeout=2,
                max_size=MAX_MESSAGE_BYTES,
                max_queue=8,
                proxy=None,
            ) as socket:
                with self._lock:
                    if self._closed:
                        raise provider_error("transport_error")
                    self._sockets.add(socket)
                socket.send(json.dumps({"voices": [self._voice]}))
                socket.send(
                    json.dumps(
                        {
                            "inputs": [
                                {
                                    "text": text,
                                    "voice_id": self._voice,
                                    "new_turn": False,
                                }
                            ]
                        }
                    )
                )
                socket.send(json.dumps({"close_socket": True}))
                for _ in range(4096):
                    try:
                        raw = socket.recv(timeout=remaining(deadline))
                    except ProviderError:
                        raise
                    except TimeoutError:
                        raise provider_error("transport_error") from None
                    except Exception:
                        raise provider_error("completion_incomplete") from None
                    remaining(deadline)
                    if (
                        not isinstance(raw, (str, bytes))
                        or len(raw) > MAX_MESSAGE_BYTES
                    ):
                        raise provider_error()
                    try:
                        message = json.loads(raw)
                    except (ValueError, UnicodeError):
                        raise provider_error() from None
                    if not isinstance(message, dict):
                        raise provider_error()
                    if "error" in message:
                        raise provider_error("request_rejected")
                    if "is_final" in message and type(message["is_final"]) is not bool:
                        raise provider_error()
                    if "audio" in message:
                        chunk = audio.feed(
                            decode_audio(
                                message["audio"], MAX_AUDIO_BYTES - audio.total
                            )
                        )
                        if chunk:
                            yield chunk
                    if message.get("is_final") is True:
                        audio.finish()
                        return
                raise provider_error("completion_incomplete")
        except ProviderError:
            raise
        except Exception:
            raise provider_error("transport_error") from None
        finally:
            if socket is not None:
                with self._lock:
                    self._sockets.discard(socket)


class GoogleTtsClient(_Client):
    streaming = False

    def __init__(
        self,
        access_token=None,
        *,
        voices=None,
        use_adc=False,
        quota_project=None,
        transport=None,
        credentials=None,
        auth_request=None,
    ):
        if not access_token and not use_adc:
            raise ValueError("invalid provider configuration")
        self._access = validate_config(access_token) if access_token else None
        self._voices = MappingProxyType(
            {
                language: (voices or {}).get(language, locale + "-Chirp3-HD-Kore")
                for language, locale in LOCALES.items()
            }
        )
        for language, name in self._voices.items():
            validate_config(
                name,
                re.escape(LOCALES[language]) + r"-Chirp3-HD-[A-Za-z][A-Za-z0-9-]{0,64}",
            )
        self._quota = (
            validate_config(quota_project, r"[A-Za-z0-9._:-]{1,128}")
            if quota_project
            else None
        )
        self._credentials, self._auth_request = credentials, auth_request
        self._owns_auth_request = auth_request is None
        self._credential_lock = threading.Lock()
        self._http = httpx.Client(
            timeout=httpx.Timeout(READ_TIMEOUT), transport=transport, trust_env=False
        )

    def close(self):
        self._http.close()
        if self._owns_auth_request and self._auth_request is not None:
            self._auth_request.session.close()

    def _headers(self, deadline):
        headers = {}
        if self._access:
            headers["Authorization"] = f"Bearer {self._access}"
        else:
            if not self._credential_lock.acquire(timeout=remaining(deadline)):
                raise provider_error("transport_error")
            try:
                if self._auth_request is None:
                    from google.auth.transport.requests import Request

                    self._auth_request = Request()
                transport = self._auth_request
                request = transport
                if self._owns_auth_request:

                    def request(*args, **kwargs):
                        kwargs["timeout"] = remaining(deadline)
                        return transport(*args, **kwargs)

                if self._credentials is None:
                    import google.auth

                    self._credentials, _ = google.auth.default(
                        scopes=["https://www.googleapis.com/auth/cloud-platform"],
                        request=request,
                    )
                self._credentials.before_request(request, "POST", GOOGLE_URL, headers)
            finally:
                self._credential_lock.release()
        if self._quota:
            headers["x-goog-user-project"] = self._quota
        return headers

    def _synthesize(self, text, language):
        validate_text(text, byte_limit=5000)
        deadline = time.monotonic() + TOTAL_TIMEOUT
        try:
            headers = self._headers(deadline)
            remaining(deadline)
            with self._http.stream(
                "POST",
                GOOGLE_URL,
                headers=headers,
                json={
                    "input": {"text": text},
                    "voice": {
                        "languageCode": LOCALES[language],
                        "name": self._voices[language],
                    },
                    "audioConfig": {"audioEncoding": "MP3"},
                },
            ) as response:
                check_status(response)
                body = bytearray()
                for chunk in response.iter_bytes(16384):
                    remaining(deadline)
                    if (
                        len(body) + len(chunk)
                        > ((MAX_AUDIO_BYTES + 2) // 3) * 4 + 65536
                    ):
                        raise provider_error()
                    body.extend(chunk)
            try:
                envelope = json.loads(body)
            except (ValueError, UnicodeError):
                raise provider_error(status=response.status_code) from None
            if not isinstance(envelope, dict):
                raise provider_error(status=response.status_code)
            result = decode_audio(envelope.get("audioContent"), MAX_AUDIO_BYTES)
            audio = Mp3Audio()
            audio.feed(result)
            audio.finish()
            return result
        except ProviderError:
            raise
        except Exception:
            raise provider_error("transport_error") from None

    def _stream(self, text, language):
        yield self._synthesize(text, language)


class CartesiaTtsClient(_Client):
    languages = ("en", "ru")

    def __init__(self, api_key, voice_id, *, transport=None):
        self._key = validate_config(api_key)
        self._voice = validate_config(
            voice_id, r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}"
        )
        self._http = httpx.Client(
            timeout=httpx.Timeout(READ_TIMEOUT), transport=transport, trust_env=False
        )

    def close(self):
        self._http.close()

    def _stream(self, text, language):
        validate_text(text, 5000)
        deadline = time.monotonic() + TOTAL_TIMEOUT
        audio = Mp3Audio()
        try:
            with self._http.stream(
                "POST",
                CARTESIA_URL,
                headers={
                    "Authorization": f"Bearer {self._key}",
                    "Cartesia-Version": "2026-08-14",
                },
                json={
                    "model_id": "sonic-3.6-2026-08-27",
                    "transcript": text,
                    "voice": {"id": self._voice},
                    "language": language,
                    "normalization": "off",
                    "output_format": {
                        "container": "mp3",
                        "sample_rate": 44100,
                        "bit_rate": 128000,
                    },
                },
            ) as response:
                check_status(response)
                for raw in response.iter_bytes():
                    remaining(deadline)
                    chunk = audio.feed(raw)
                    if chunk:
                        yield chunk
                audio.finish()
        except ProviderError:
            raise
        except Exception:
            raise provider_error("transport_error") from None
