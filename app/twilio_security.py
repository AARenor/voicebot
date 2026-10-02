"""Fixed-origin Twilio authentication and bounded, memory-only call bindings."""

from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import os
import re
import secrets
import threading
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

VOICE_URL = "https://robot.arleserver.cfd/api/twilio/voice"
MEDIA_URL = "wss://robot.arleserver.cfd/api/twilio/media"
NATIVE_AUDIO_MARK = "voicebot-native-audio"
FALLBACK_URL = "https://robot.arleserver.cfd/api/twilio/unavailable-et.wav"
MAX_PENDING = 16
MAX_ACTIVE = 2
BINDING_TTL = 30
REPLAY_TTL = 86400
MAX_USED = 1024


class BridgeError(Exception):
    """Only fixed error codes cross the HTTP/log boundary."""

    def __init__(self, code="forbidden", status=403):
        super().__init__(code)
        self.code, self.status = code, status


def valid_sid(value, prefix):
    return isinstance(value, str) and bool(
        re.fullmatch(prefix + r"[0-9a-fA-F]{32}", value)
    )


def private_media_host(host):
    if host in {"localhost", "livekit", "voicebot-media-livekit"}:
        return True
    try:
        address = ipaddress.ip_address(host)
        return address.is_loopback or any(
            address in ipaddress.ip_network(net)
            for net in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "fc00::/7")
        )
    except ValueError:
        return False


@dataclass(frozen=True, repr=False)
class Config:
    auth: str
    account: str
    phone: str
    livekit_url: str
    livekit_key: str
    livekit_secret: str
    agent: str = "voicebot"

    @classmethod
    def from_env(cls, env=None):
        env = os.environ if env is None else env
        names = (
            "TWILIO_AUTH_TOKEN",
            "TWILIO_ACCOUNT_SID",
            "TWILIO_PHONE_NUMBER",
            "LIVEKIT_URL",
            "LIVEKIT_API_KEY",
            "LIVEKIT_API_SECRET",
        )
        values = [env.get(name, "") for name in names]
        if not all(
            isinstance(v, str)
            and 1 <= len(v) <= 512
            and v.isascii()
            and not any(c.isspace() for c in v)
            for v in values
        ):
            return None
        auth, account, phone, url, key, secret = values
        agent = env.get("VOICEBOT_AGENT_NAME", "voicebot")
        if (
            not 16 <= len(auth) <= 256
            or not valid_sid(account, "AC")
            or not re.fullmatch(r"\+[1-9][0-9]{1,14}", phone)
        ):
            return None
        try:
            parsed = urlsplit(url)
            if (
                parsed.scheme not in ("ws", "wss")
                or not private_media_host(parsed.hostname)
                or parsed.username
                or parsed.password
                or parsed.query
                or parsed.fragment
                or parsed.path not in ("", "/")
            ):
                return None
            if parsed.port is not None and not 1 <= parsed.port <= 65535:
                return None
        except ValueError:
            return None
        if not isinstance(agent, str) or not re.fullmatch(
            r"[A-Za-z0-9_-]{1,48}", agent
        ):
            return None
        return cls(auth, account, phone, url, key, secret, agent)


def valid_signature(config, url, params, signature):
    if not isinstance(signature, str) or not re.fullmatch(
        r"[A-Za-z0-9+/]{27}=", signature
    ):
        return False
    # Match Twilio's official RequestValidator: sort names and unique values,
    # keep whitespace, and include unknown parameters rather than a whitelist.
    text = url + "".join(
        key + value for key in sorted(params) for value in sorted(set(params[key]))
    )
    digest = hmac.new(config.auth.encode(), text.encode(), hashlib.sha1).digest()
    return hmac.compare_digest(base64.b64encode(digest).decode(), signature)


def valid_media_signature(config, signature):
    # Exact supplied WSS origin plus Twilio's documented slash quirk only.
    return any(
        valid_signature(config, url, {}, signature)
        for url in (MEDIA_URL, MEDIA_URL + "/")
    )


def authorized_call(config, params):
    if params.get("AccountSid") != [config.account] or params.get("To") != [
        config.phone
    ]:
        raise BridgeError()
    call = params.get("CallSid", [])
    if len(call) != 1 or not valid_sid(call[0], "CA"):
        raise BridgeError()
    return call[0]


class Bindings:
    # ponytail: single process, <=16 pending/2 active, 1024 calls/day; fail closed
    # on replay-ledger saturation. Shared durable admission if replicas grow.
    def __init__(self, clock=time.monotonic):
        self.clock, self.lock = clock, threading.Lock()
        self.pending, self.active, self.used = {}, set(), {}

    def _prune(self):
        now = self.clock()
        self.pending = {
            key: value for key, value in self.pending.items() if value[1] > now
        }
        self.used = {key: expiry for key, expiry in self.used.items() if expiry > now}

    @property
    def active_count(self):
        with self.lock:
            return len(self.active)

    def reserve(self, call):
        with self.lock:
            self._prune()
            if call in self.pending:
                return self.pending[call][0]
            key = hashlib.sha256(call.encode()).digest()
            if key in self.used or call in self.active:
                raise BridgeError("call_binding_used")
            if (
                len(self.pending) >= MAX_PENDING
                or len(self.active) >= MAX_ACTIVE
                or len(self.used) >= MAX_USED
            ):
                return None
            binding = secrets.token_urlsafe(24)
            self.pending[call] = (binding, self.clock() + BINDING_TTL)
            self.used[key] = self.clock() + REPLAY_TTL
            return binding

    def consume(self, call, binding):
        with self.lock:
            self._prune()
            pending = self.pending.get(call)
            if (
                pending is None
                or not isinstance(binding, str)
                or not hmac.compare_digest(pending[0], binding)
            ):
                raise BridgeError("call_binding_invalid")
            del self.pending[call]
            if len(self.active) >= MAX_ACTIVE:
                raise BridgeError("capacity", 503)
            self.active.add(call)

    def release(self, call):
        with self.lock:
            self.active.discard(call)


def authorize_start(config, bindings, message):
    try:
        start = message["start"]
        stream, call = start["streamSid"], start["callSid"]
        media = start["mediaFormat"]
        custom = start["customParameters"]
        if (
            message["event"] != "start"
            or message["sequenceNumber"] != "1"
            or message["streamSid"] != stream
            or not valid_sid(stream, "MZ")
            or not valid_sid(call, "CA")
        ):
            raise BridgeError("start_invalid")
        if start["accountSid"] != config.account or start["tracks"] != ["inbound"]:
            raise BridgeError("start_invalid")
        if (
            media.get("encoding") != "audio/x-mulaw"
            or type(media.get("sampleRate")) is not int
            or media["sampleRate"] != 8000
            or type(media.get("channels")) is not int
            or media["channels"] != 1
        ):
            raise BridgeError("start_invalid")
        if (
            set(custom) != {"call_binding"}
            or not isinstance(custom["call_binding"], str)
            or not re.fullmatch(r"[A-Za-z0-9_-]{32}", custom["call_binding"])
        ):
            raise BridgeError("start_invalid")
    except (KeyError, TypeError, AttributeError):
        raise BridgeError("start_invalid") from None
    bindings.consume(call, custom["call_binding"])
    return call, stream
